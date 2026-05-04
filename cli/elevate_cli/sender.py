"""Durable outbound message sender.

The approve flow in `source_connectors.update_source_task_state` enqueues a row
into `outreach_db.send_queue` inside the same transaction that flips task state
to `approved`. This module owns the *outbound* half: a tick loop claims due rows,
dispatches per channel, and durably records the outcome.

Phase 0 ships the queue + tick + dispatch *interface*. Channel dispatchers are
stubbed (`_stub_dispatch`) and return a synthetic `provider_message_id` so the
queue path is exercisable end-to-end without real provider creds. Phase 5a
replaces the stubs with real Composio `execute_tool` calls and Twilio.

Failure model
-------------
- Transient errors (`SenderTransientError`) -> mark_retrying with exponential
  backoff capped at 1h.
- Permanent errors (`SenderPermanentError` or unhandled exceptions after
  MAX_ATTEMPTS) -> mark_failed.
- Successful dispatch returns `(provider_message_id, info_dict)` -> mark_sent.

Idempotency: enqueue is keyed on `(source_id, thread_id, task_id, revision)`,
so double-click approve and browser retries cannot create duplicate rows.
mark_sent stores `provider_message_id` so a sender crash *after* a real
provider success leaves the row in `sending` until the next tick, which checks
for an existing `provider_message_id` and short-circuits to `sent`.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from elevate_cli import outreach_db


_log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600


class SenderTransientError(Exception):
    """Recoverable: caller should retry with backoff."""


class SenderPermanentError(Exception):
    """Unrecoverable: caller should mark failed and stop retrying."""


# A dispatcher takes the queue row dict, returns (provider_message_id, info).
Dispatcher = Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]


def _stub_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Phase 0 stub: pretends to send and returns a synthetic provider id.

    Phase 5a replaces this with channel-specific dispatchers (Composio social DMs,
    Composio Gmail send, Twilio SMS, CRM note adapters).
    """
    pmid = f"stub-{row['channel']}-{uuid.uuid4().hex[:12]}"
    _log.info(
        "sender.stub_dispatch channel=%s task=%s payload_keys=%s -> %s",
        row["channel"], row["taskId"], list(row.get("payload", {}).keys()), pmid,
    )
    return pmid, {"stub": True, "dispatched_at": _now()}


_DISPATCHERS: dict[str, Dispatcher] = {}


def register_dispatcher(channel: str, dispatcher: Dispatcher) -> None:
    """Register a channel-specific dispatcher. Phase 5a wires Composio
    toolkits + Twilio through here."""
    _DISPATCHERS[channel] = dispatcher


def get_dispatcher(channel: str) -> Dispatcher:
    return _DISPATCHERS.get(channel, _stub_dispatch)


def composio_dispatcher(toolkit: str) -> Dispatcher:
    """Return a Dispatcher that routes through Composio's ``execute_tool``.

    The queue ``payload`` must include:
    - ``connected_account_id`` — the Composio account to send from
    - ``slug`` — the Composio tool slug (e.g. ``GMAIL_SEND_EMAIL``)
    - ``args`` — tool-specific arguments dict

    Phase 5a uses this for Gmail / Outlook / Slack / etc. The capability
    matrix in ``composio_capabilities.json`` is the source of truth for
    which toolkit slugs are safe to expose in the channel picker.

    HTTP 408/429/5xx -> ``SenderTransientError`` (retry with backoff).
    Other 4xx -> ``SenderPermanentError`` (mark failed).
    """
    from elevate_cli import composio_client

    def _dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        payload = row.get("payload") or {}
        account_id = payload.get("connected_account_id") or ""
        slug = payload.get("slug") or ""
        args = payload.get("args") or {}
        if not account_id:
            raise SenderPermanentError(
                f"composio[{toolkit}]: payload missing connected_account_id"
            )
        if not slug:
            raise SenderPermanentError(
                f"composio[{toolkit}]: payload missing tool slug"
            )

        resp = composio_client.execute_tool(slug, account_id, args)
        if not resp.get("ok"):
            status = resp.get("status")
            err = resp.get("error") or "execute_tool failed"
            if status in (408, 429) or (isinstance(status, int) and status >= 500):
                raise SenderTransientError(f"composio[{toolkit}] {status}: {err}")
            raise SenderPermanentError(f"composio[{toolkit}] {status}: {err}")

        data = resp.get("data") or {}
        # Composio tool results vary; pick a stable id if present, otherwise
        # synthesize one bound to the slug+account so retries don't dup.
        pmid = (
            (data.get("data") or {}).get("response_id")
            or data.get("id")
            or data.get("execution_id")
            or f"composio-{toolkit}-{uuid.uuid4().hex[:12]}"
        )
        return str(pmid), {
            "toolkit": toolkit,
            "slug": slug,
            "dispatched_at": _now(),
            "raw": data,
        }

    return _dispatch


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff with jitter, capped."""
    base = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts)))
    jitter = random.uniform(0.7, 1.3)
    return int(base * jitter)


def _next_retry_at(attempts: int) -> str:
    delta = timedelta(seconds=_backoff_seconds(attempts))
    return (datetime.now(timezone.utc) + delta).isoformat()


def dispatch_one(row: dict[str, Any]) -> dict[str, Any]:
    """Send one queue row. Updates queue state. Safe to call concurrently with
    other rows because each `mark_*` call is its own atomic SQLite write."""
    queue_id = row["id"]
    channel = row["channel"]
    attempts = int(row.get("attempts", 0))

    # Crash-recovery short-circuit: if a previous tick succeeded at the
    # provider but died before mark_sent, the next claim sees the row in
    # 'sending' with a provider_message_id already set.
    if row.get("providerMessageId") and row.get("status") != outreach_db.SEND_STATUS_SENT:
        return outreach_db.mark_sent(queue_id, row["providerMessageId"])

    dispatcher = get_dispatcher(channel)
    try:
        pmid, _info = dispatcher(row)
    except SenderTransientError as exc:
        if attempts + 1 >= MAX_ATTEMPTS:
            return outreach_db.mark_failed(queue_id, error=f"max_attempts: {exc}")
        return outreach_db.mark_retrying(
            queue_id, error=str(exc), next_retry_at=_next_retry_at(attempts),
        )
    except SenderPermanentError as exc:
        return outreach_db.mark_failed(queue_id, error=str(exc))
    except Exception as exc:
        # Unknown exceptions are treated as transient until MAX_ATTEMPTS.
        if attempts + 1 >= MAX_ATTEMPTS:
            return outreach_db.mark_failed(queue_id, error=f"unhandled: {exc}")
        return outreach_db.mark_retrying(
            queue_id, error=f"unhandled: {exc}", next_retry_at=_next_retry_at(attempts),
        )

    if not pmid:
        return outreach_db.mark_retrying(
            queue_id,
            error="dispatcher returned empty provider_message_id",
            next_retry_at=_next_retry_at(attempts),
        )

    return outreach_db.mark_sent(queue_id, pmid)


def tick(*, batch: int = 10) -> dict[str, Any]:
    """Claim up to `batch` due rows and dispatch each. Returns counts.
    Called by the sender-tick cron every 2 minutes."""
    started = time.time()
    counts = {"claimed": 0, "sent": 0, "retrying": 0, "failed": 0}
    rows = outreach_db.claim_due_sends(limit=batch)
    counts["claimed"] = len(rows)
    for row in rows:
        result = dispatch_one(row) or {}
        status = (result or {}).get("status")
        if status == outreach_db.SEND_STATUS_SENT:
            counts["sent"] += 1
        elif status == outreach_db.SEND_STATUS_RETRYING:
            counts["retrying"] += 1
        elif status == outreach_db.SEND_STATUS_FAILED:
            counts["failed"] += 1
    counts["duration_ms"] = int((time.time() - started) * 1000)
    if counts["claimed"]:
        _log.info("sender.tick %s", counts)
    return counts


def status_for_task(source_id: str, thread_id: str, task_id: str) -> dict[str, Any] | None:
    """UI-shaped view of a task's most recent send_queue row, or None if the
    task was never enqueued (i.e. approve never ran or pre-Phase-0 approve)."""
    row = outreach_db.get_send_by_task(source_id, thread_id, task_id)
    if row is None:
        return None
    return {
        "queueId": row["id"],
        "status": row["status"],
        "channel": row["channel"],
        "attempts": row["attempts"],
        "nextRetryAt": row["nextRetryAt"],
        "lastError": row["lastError"],
        "providerMessageId": row["providerMessageId"],
        "createdAt": row["createdAt"],
        "updatedAt": row["updatedAt"],
    }
