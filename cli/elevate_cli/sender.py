"""Durable outbound message sender.

The approve flow in `source_connectors.update_source_task_state` enqueues a row
into `outreach_db.send_queue` inside the same transaction that flips task state
to `approved`. This module owns the *outbound* half: a tick loop claims due rows,
dispatches per channel, and durably records the outcome.

Sandbox mode can route through `_stub_dispatch` so the queue path is exercisable
without contacting a real recipient. Outside that explicit sandbox, channels
without a registered transport fail closed; a synthetic provider id must never
be recorded as a real send.

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

import json
import logging
import os
import random
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from elevate_cli import outreach_db
from elevate_constants import exact_realtor_beta_active, get_elevate_home


_log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600

# ---------------------------------------------------------------------------
# Exact Realtor Beta: the outbound send queue is a direct external-effect
# lane (Composio provider sends, native Apple Messages, agent dispatchers)
# that does not pass through the accepted-turn registry/effect-broker
# boundary.  The Beta containment contract keeps outbound/external writes
# denied until policy proof, so the whole lane fails closed here at its two
# chokepoints (``tick`` and ``dispatch_one``) with a typed refusal and ZERO
# state mutation by this module: no stale-send recovery, no row claim, no
# ``mark_*`` write, no dispatcher invocation.  Rows keep whatever durable
# state their caller left them in (``queued`` from the autonomous ticker,
# which refuses before claiming; ``sending`` when a human dashboard action
# claimed first) — a Stable profile later delivers ``queued`` rows and
# fail-closes stale ``sending`` rows to ``failed`` for operator
# verification via ``recover_stale_sends``.  No path resends
# automatically.  Stable behavior is byte-identical (ERB-406 sender-queue
# lane / package A5).
# ---------------------------------------------------------------------------
BETA_OUTBOUND_SEND_DISABLED_CODE = "beta_outbound_send_disabled"
BETA_OUTBOUND_SEND_DISABLED_MESSAGE = (
    "Realtor Beta does not dispatch queued outbound messages. The send "
    "queue was left untouched and no message was sent."
)


def outbound_send_disabled_reason() -> str | None:
    """Return the typed release-policy refusal when outbound send is disabled."""
    if not exact_realtor_beta_active():
        return None
    return (
        f"Error [{BETA_OUTBOUND_SEND_DISABLED_CODE}]: "
        f"{BETA_OUTBOUND_SEND_DISABLED_MESSAGE}"
    )


class SenderTransientError(Exception):
    """Recoverable: caller should retry with backoff."""


class SenderPermanentError(Exception):
    """Unrecoverable: caller should mark failed and stop retrying."""


# A dispatcher takes the queue row dict, returns (provider_message_id, info).
Dispatcher = Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]


def _stub_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Explicit-sandbox stub: simulate a send with a synthetic provider id.

    Phase 5a replaces this with channel-specific dispatchers (Composio social DMs,
    Composio Gmail send, Twilio SMS, CRM note adapters).
    """
    pmid = f"stub-{row['channel']}-{uuid.uuid4().hex[:12]}"
    _log.info(
        "sender.stub_dispatch channel=%s task=%s payload_keys=%s -> %s",
        row["channel"], row["taskId"], list(row.get("payload", {}).keys()), pmid,
    )
    return pmid, {"stub": True, "dispatched_at": _now()}


def _unsupported_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    channel = str(row.get("channel") or "unknown")
    raise SenderPermanentError(
        f"unsupported outbound channel {channel!r}: no dispatcher is registered; no message was sent"
    )


_DISPATCHERS: dict[str, Dispatcher] = {}


def sandbox_enabled() -> bool:
    """True when outreach must NEVER reach a real recipient.

    Guaranteed-safe kill switch for tests, demos, and dry runs. When set,
    every channel routes through ``_stub_dispatch`` — no Messages.app send,
    no Composio ``execute_tool``, no agent dispatcher — regardless of what
    ``_wire_default_dispatchers`` registered. This is the *only* mode that
    provides a single, defense-in-depth guarantee across ALL channels;
    ``ELEVATE_SENDER_DISABLE_AGENT`` alone still leaves native SMS live.

    Enable with ``ELEVATE_OUTREACH_SANDBOX=1`` (aliases: true/yes/on).
    """
    return (os.getenv("ELEVATE_OUTREACH_SANDBOX", "") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def register_dispatcher(channel: str, dispatcher: Dispatcher) -> None:
    """Register a channel-specific dispatcher. Phase 5a wires Composio
    toolkits + Twilio through here."""
    _DISPATCHERS[channel] = dispatcher


def get_dispatcher(channel: str) -> Dispatcher:
    # Sandbox is checked at dispatch time (not just wiring time) so it holds
    # even if a real dispatcher was registered before the flag was set.
    if sandbox_enabled():
        return _stub_dispatch
    return _DISPATCHERS.get(channel, _unsupported_dispatch)


_APPLE_MESSAGES_CHANNELS = frozenset({"sms", "imessage", "apple-messages", "apple_messages"})
APPLE_MESSAGES_OUTBOUND_DISABLED_ERROR = (
    "Apple Messages outbound is disabled; no message was sent"
)


def is_apple_messages_channel(channel: Any) -> bool:
    """Whether a queue channel ultimately uses the native Messages transport."""
    return str(channel or "").strip().lower() in _APPLE_MESSAGES_CHANNELS


def apple_messages_outbound_enabled(config: dict[str, Any] | None = None) -> bool:
    """Read the outbound kill switch from the active (or supplied) profile.

    The explicit outreach sandbox is the only exception: its dispatcher cannot
    reach a real recipient, so retaining the stub path makes dry-run coverage
    possible even when production Apple Messages delivery is paused.
    """
    if sandbox_enabled():
        return True
    from elevate_cli import source_connectors

    return bool(
        source_connectors.get_apple_messages_directions(config).get("outbound", True)
    )


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
        # A 2xx response only proves that Composio accepted the wrapper call.
        # Its body separately reports whether the provider tool succeeded.
        # Wrapper execution/log IDs are observability tokens, not evidence that
        # Gmail (or another provider) accepted the message.
        if not isinstance(data, dict) or data.get("successful") is not True:
            detail = data.get("error") if isinstance(data, dict) else None
            raise SenderPermanentError(
                f"composio[{toolkit}]: provider tool rejected the dispatch"
                + (f": {detail}" if str(detail or "").strip() else "")
                + "; no message was recorded as sent"
            )
        if str(data.get("error") or "").strip():
            raise SenderPermanentError(
                f"composio[{toolkit}]: provider tool returned an error: "
                f"{data['error']}; no message was recorded as sent"
            )

        # Composio tool results vary, but provider evidence lives inside the
        # nested tool data. Never promote wrapper execution_id/log_id/id fields
        # to provider receipts.
        nested_data = data.get("data")
        nested_data = nested_data if isinstance(nested_data, dict) else {}
        nested_error = nested_data.get("error")
        if str(nested_error or "").strip():
            raise SenderPermanentError(
                f"composio[{toolkit}]: provider returned an error: {nested_error}; "
                "no message was recorded as sent"
            )
        nested_message = nested_data.get("message")
        nested_message = nested_message if isinstance(nested_message, dict) else {}
        pmid = (
            nested_data.get("response_id")
            or nested_data.get("responseId")
            or nested_data.get("message_id")
            or nested_data.get("messageId")
            or nested_data.get("id")
            or nested_message.get("id")
        )
        if not str(pmid or "").strip():
            raise SenderPermanentError(
                f"composio[{toolkit}]: transport unavailable / no provider receipt; "
                "tool returned success but delivery outcome is unverified; verify before retrying"
            )
        return str(pmid), {
            "toolkit": toolkit,
            "slug": slug,
            "dispatched_at": _now(),
            "raw": data,
        }

    return _dispatch


def _format_phone(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"


def _send_agent_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Fail closed: free-form model output is not a provider send receipt.

    The previous transport spawned an agent and treated a ``SENT <token>`` line
    from its stdout as proof. That allowed hallucinated stdout (and even a
    non-zero subprocess carrying that stdout) to become a durable ``sent`` row.
    It is unsafe to invoke the agent and then retry without a provider receipt,
    because the first invocation may have delivered the message. Until this
    path can return a verifiable tool/provider result, it must not run at all.
    """
    channel = str(row.get("channel") or "unknown")
    raise SenderPermanentError(
        f"send-agent[{channel}]: transport unavailable / no provider receipt; no message was sent"
    )


_CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")


# ─────────────────────────────────────────────────────────────────────────────
# macOS SMS / iMessage transport — CANONICAL PATH. Any Mac-specific phone send
# goes through _messages_native_dispatch below; do not hand-roll transport
# decisions or osascript sends elsewhere. Full decision tree, the rationale for
# every choice, the liabilities (private IDS API, imsg dependency, FDA flakiness,
# SIP, carrier compliance), and the step-by-step REPAIR RUNBOOK for when a macOS
# update breaks it live in: cli/docs/mac-sms-transport.md  ← READ THAT FIRST.
# ─────────────────────────────────────────────────────────────────────────────

# Outreach-safe default transport. SMS reaches every phone (iPhone + Android);
# iMessage silently fails for non-Apple numbers. For COLD outreach to new
# numbers there is no message history to read, so the only safe default is SMS.
# We upgrade to iMessage ONLY on proven iMessage history. Override with
# ELEVATE_OUTREACH_DEFAULT_TRANSPORT=imessage to restore the old blue-first
# behaviour (not recommended for outreach).
def _outreach_default_transport() -> str:
    val = (os.getenv("ELEVATE_OUTREACH_DEFAULT_TRANSPORT", "") or "").strip().lower()
    return "iMessage" if val in ("imessage", "imsg") else "SMS"


_IDS_CAP_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools", "ids-capability.swift")


def _ids_capability_bin_path() -> str:
    return str(get_elevate_home() / "bin" / "ids-capability")


def _ids_capability_bin() -> str | None:
    """Path to the iMessage-capability probe binary, building it on demand.

    Returns the binary path if available/buildable, else None. Override the
    path with ELEVATE_IDS_CAPABILITY_BIN. Compiles the bundled Swift source
    (tools/ids-capability.swift) once with swiftc when the binary is missing —
    so it self-installs on any Mac with the Xcode command-line tools.
    """
    override = os.getenv("ELEVATE_IDS_CAPABILITY_BIN")
    if override:
        return override if (os.path.isfile(override) and os.access(override, os.X_OK)) else None
    binary = _ids_capability_bin_path()
    if os.path.isfile(binary) and os.access(binary, os.X_OK):
        return binary
    swiftc = shutil.which("swiftc")
    if not swiftc or not os.path.isfile(_IDS_CAP_SRC):
        return None
    try:
        os.makedirs(os.path.dirname(binary), exist_ok=True)
        r = subprocess.run(
            [swiftc, "-O", _IDS_CAP_SRC, "-o", binary],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if r.returncode == 0 and os.path.isfile(binary):
            os.chmod(binary, 0o755)
            return binary
        _log.warning("ids-capability build failed: %s", (r.stderr or "")[:200])
    except Exception as exc:  # noqa: BLE001
        _log.warning("ids-capability build error: %s", exc)
    return None


def _ids_capability(phone: str) -> str | None:
    """Ask Apple's IDS daemon whether a handle is iMessage-capable — the same
    blue/green check the iPhone does. Returns "iMessage", "SMS", or None when
    the probe is unavailable / inconclusive (caller falls back to SMS default).

    This is what lets us route a BRAND-NEW number (no message history) the way
    the iPhone would, instead of blindly defaulting. Read-only, no SIP, no
    injection. Never raises — a missing/old-macOS probe degrades to None.
    """
    bin_path = _ids_capability_bin()
    if not bin_path:
        return None
    dest = phone if (phone.startswith("tel:") or "@" in phone) else f"tel:{phone}"
    try:
        r = subprocess.run(
            [bin_path, dest], capture_output=True, text=True, timeout=12, check=False,
        )
    except Exception:  # noqa: BLE001
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    try:
        data = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return None
    t = str(data.get("transport") or "").lower()
    _log.info("sender.ids_capability phone=%s -> %s", phone, t or "?")
    if t == "imessage":
        return "iMessage"
    if t == "sms":
        return "SMS"
    return None


def _detect_preferred_transport(phone: str) -> str:
    """Pick `iMessage` or `SMS` for a recipient.

    Decision order:
      1. Proven chat.db history — iMessage ONLY when the last successful
         outbound was iMessage; SMS/RCS history routes SMS.
      2. NO history (a cold/new number) or chat.db unreadable — ask Apple's
         IDS daemon for the iMessage-capability of the handle (the same
         blue/green check the iPhone does), via the ids-capability probe.
      3. If IDS is inconclusive/unavailable — fall back to the outreach-safe
         default (SMS), which reaches every phone.

    Cold outreach targets numbers with no history, and iMessage to a non-Apple
    number silently fails (error 22, "sent" but never delivered). RCS contacts
    are Android users — macOS can *receive* RCS but cannot *send* it, so those
    route SMS too. We use the blue bubble only on positive proof (history or a
    live IDS hit).

    chat.db.error: 0 = accepted/queued without a recorded error, 22 =
    "Not Delivered" (unreachable on iMessage). Even error=0 is not
    recipient-delivery proof; it is only stronger dispatch evidence.
    """
    default = _outreach_default_transport()
    if not os.path.exists(_CHAT_DB_PATH):
        # No local history at all — ask IDS, then default.
        return _ids_capability(phone) or default
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(f"file:{_CHAT_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT m.service FROM message m "
                "JOIN handle h ON m.handle_id = h.ROWID "
                "WHERE h.id = ? AND m.is_from_me = 1 AND m.error = 0 AND m.is_sent = 1 "
                "ORDER BY m.date DESC LIMIT 1",
                (phone,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        # chat.db unreadable (e.g. FDA not effective in this process). Don't
        # guess from nothing — the IDS probe has its own access; ask it, then
        # fall back to the outreach-safe default. Never silently iMessage.
        return _ids_capability(phone) or default
    if row and row[0]:
        svc = str(row[0]).strip().lower()
        # iMessage is the only blue-bubble transport the Mac can send. Every
        # other successful service (sms, rcs, and any future carrier label)
        # is a non-iMessage recipient and must go out as SMS — the Mac can't
        # send RCS, and SMS is what actually lands for those numbers.
        if svc == "imessage":
            return "iMessage"
        return "SMS"
    # No successful history for this handle = a cold/new number. Ask Apple's
    # IDS (iPhone's blue/green check) before falling back to the SMS default.
    return _ids_capability(phone) or default


def _verify_send_landed(phone: str, draft_prefix: str, since_epoch: float) -> tuple[str, int] | None:
    """Read the newest matching Messages dispatch state from chat.db.

    Returns (service, error_code) for the most recent matching outbound
    row, or None if nothing matched. Used after osascript returns 0 to
    catch the silent-fail case where Messages.app accepts the send but
    Apple's IDS later rejects it (error=22 "Not Delivered").

    Matches on (handle.id == phone, is_from_me=1, date >= since_epoch).
    `text` may live in attributedBody on newer macOS, so we don't filter
    on draft content — the recency + handle match is enough.
    """
    if not os.path.exists(_CHAT_DB_PATH):
        return None
    # chat.db.date is nanoseconds since 2001-01-01 epoch.
    apple_epoch_offset = 978307200.0  # 2001-01-01 in unix seconds
    since_apple_ns = int((since_epoch - apple_epoch_offset) * 1_000_000_000)
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(f"file:{_CHAT_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            cur = conn.execute(
                "SELECT m.service, m.error FROM message m "
                "JOIN handle h ON m.handle_id = h.ROWID "
                "WHERE h.id = ? AND m.is_from_me = 1 AND m.date >= ? "
                "ORDER BY m.date DESC LIMIT 1",
                (phone, since_apple_ns),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    return (str(row[0] or ""), int(row[1] or 0))


def _sms_outbox_dir() -> str:
    return str(get_elevate_home() / "sms-outbox")


def _imsg_send_via_app(phone: str, draft: str, svc: str) -> tuple[int, str, str]:
    """Hand the send to the FOREGROUND Elevate app via the sms-outbox spool.

    Running `imsg` from this (headless backend) process hangs — macOS won't grant
    Automation→Messages to a non-foreground process. The Electron GUI process
    (which CAN hold Automation) watches ~/.elevate/sms-outbox, runs imsg, and
    writes back the result. We drop a request and poll for the response. Used
    when ELEVATE_SMS_VIA_APP is set (the dashboard sets it). See
    cli/docs/mac-sms-transport.md.
    """
    import time as _time

    outbox_dir = _sms_outbox_dir()
    os.makedirs(outbox_dir, exist_ok=True)
    rid = uuid.uuid4().hex
    req_path = os.path.join(outbox_dir, f"{rid}.req.json")
    res_path = os.path.join(outbox_dir, f"{rid}.res.json")
    tmp = req_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"to": phone, "text": draft, "service": svc}, fh)
    os.replace(tmp, req_path)
    _log.info("sender.imsg_app spooled service=%s phone=%s id=%s", svc, phone, rid)
    # Generous: the app may hit a wedged-Messages retry (imsg 30s + restart +
    # imsg 30s). Wait through that before giving up.
    deadline = _time.time() + 85
    while _time.time() < deadline:
        if os.path.exists(res_path):
            try:
                with open(res_path, encoding="utf-8") as fh:
                    res = json.load(fh)
            except Exception:  # noqa: BLE001
                res = None
            try:
                os.remove(res_path)
            except Exception:  # noqa: BLE001
                pass
            if isinstance(res, dict) and res.get("ok"):
                return (0, str(res.get("stdout") or '{"status":"sent"}'), "")
            err = (res or {}).get("error") if isinstance(res, dict) else "no result"
            return (1, "", f"app-send failed: {err}")
        _time.sleep(0.4)
    # No response — the GUI app may not be running. Clean up the request.
    try:
        os.remove(req_path)
    except Exception:  # noqa: BLE001
        pass
    return (124, "", "app-send timed out (Elevate app not draining sms-outbox?)")


def _imsg_send_via(phone: str, draft: str, service_type: str) -> tuple[int, str, str] | None:
    """Send via the `imsg` CLI, forcing the carrier transport.

    `imsg send --service sms` reliably forces a green-bubble SMS (osascript's
    `service type = SMS` is silently re-routed to iMessage by Messages for any
    iMessage-capable handle, which is the core bug). `imsg` also carries its
    OWN Full Disk Access grant, so it works even when the host app process
    can't read chat.db. Returns (rc, stdout, stderr), or None when `imsg`
    isn't installed (caller falls back to osascript).

    When ELEVATE_SMS_VIA_APP is set (the dashboard backend), the send is handed
    to the foreground Elevate app instead of run here — a headless process can't
    hold macOS Automation→Messages, so running imsg here just hangs.
    """
    svc = "imessage" if str(service_type).lower() == "imessage" else "sms"
    if os.getenv("ELEVATE_SMS_VIA_APP", "").strip().lower() in ("1", "true", "yes"):
        return _imsg_send_via_app(phone, draft, svc)
    imsg = shutil.which("imsg")
    if not imsg:
        return None
    try:
        result = subprocess.run(
            [imsg, "send", "--to", phone, "--text", draft, "--service", svc, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (124, "", "imsg timed out")
    _log.info(
        "sender.imsg_send service=%s phone=%s rc=%s out=%r",
        svc, phone, result.returncode,
        (result.stdout or result.stderr or "").strip()[:200],
    )
    return (result.returncode, result.stdout or "", result.stderr or "")


def _osa_send_via(phone: str, draft: str, service_type: str) -> tuple[int, str, str]:
    """Send one message via the named service ('iMessage' or 'SMS').

    Prefers the `imsg` CLI (forces the transport + has its own FDA); falls back
    to osascript when `imsg` isn't installed. Returns (returncode, stdout,
    stderr). Caller decides what to do.
    """
    via_imsg = _imsg_send_via(phone, draft, service_type)
    if via_imsg is not None:
        return via_imsg

    def _q(s: str) -> str:
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
    script = (
        'tell application "Messages"\n'
        f'  set targetService to 1st service whose service type = {service_type}\n'
        f'  send "{_q(draft)}" to buddy "{_q(phone)}" of targetService\n'
        'end tell\n'
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (124, "", "osascript timed out")
    _log.info(
        "sender.osa_send service=%s phone=%s rc=%s stderr=%r",
        service_type, phone, result.returncode,
        (result.stderr or "").strip()[:200],
    )
    return (result.returncode, result.stdout or "", result.stderr or "")


def _messages_native_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Send via macOS Messages.app — dynamic iMessage vs SMS per recipient.

    Detection flow:
      1. Pre-flight chat.db lookup → pick the service that worked most
         recently for this handle. Defaults to iMessage if no history.
      2. Run osascript send via the chosen service.
      3. Post-send verify in chat.db (give Messages 1.5s to write the
         row + Apple's IDS to ack). If the row landed with error != 0
         AND we picked iMessage, retry on SMS once.
      4. SMS legitimately succeeds even when chat.db.error != 0 in
         rare cases (carrier propagation lag), so SMS post-verify only
         fails on explicit "not sent" markers.

    Override the whole detection with `ELEVATE_SMS_DISPATCHER=agent`
    (revert to LLM) or `ELEVATE_FORCE_SMS=1` (skip iMessage entirely).
    """
    payload = row.get("payload") or {}
    draft = str(payload.get("draft_text") or "").strip()
    if not draft:
        raise SenderPermanentError("messages-native: payload missing draft_text")
    recipient = payload.get("recipient") or {}
    phone = _format_phone(recipient.get("phone"))
    if not phone:
        raise SenderPermanentError("messages-native: recipient missing phone")

    force_sms = os.getenv("ELEVATE_FORCE_SMS", "").lower() in ("1", "true", "yes")
    detected = "SMS" if force_sms else _detect_preferred_transport(phone)
    _log.info(
        "sender.messages_native phone=%s detected=%s force_sms=%s",
        phone, detected, force_sms,
    )
    def _attempt(service_type: str) -> tuple[str, dict[str, Any]] | None:
        send_start = time.time()
        rc, stdout, stderr = _osa_send_via(phone, draft, service_type)
        if rc != 0:
            last = (stderr or stdout or f"exit={rc}").strip().splitlines()[-1][:240]
            raise SenderTransientError(f"messages-native[{service_type}]: {last}")
        # Give Messages a moment to write the row + IDS to respond.
        time.sleep(1.6)
        verify = _verify_send_landed(phone, draft[:16], send_start - 0.5)
        if verify is None:
            # No row visible yet — give one more poll, then trust osascript.
            time.sleep(1.5)
            verify = _verify_send_landed(phone, draft[:16], send_start - 0.5)
        if verify is not None:
            svc_observed, err_code = verify
            if err_code == 0:
                pmid_prefix = "imessage" if svc_observed.lower() == "imessage" else "sms"
                pmid = f"{pmid_prefix}-{uuid.uuid4().hex[:10]}"
                return pmid, {
                    "agent": "messages-native",
                    "channel": "sms",
                    "phone": phone,
                    "transport": svc_observed,
                    "transport_attempted": service_type,
                    "dispatched_at": _now(),
                    "verify_lag_ms": int((time.time() - send_start) * 1000),
                }
            # Service-level rejection (error 22 = "Not Delivered" for iMessage).
            return None
        # Messages accepted the command, but the row is not observable yet.
        # Record dispatcher acceptance only; callers/UI must not upgrade this
        # synthetic correlation token into recipient-delivery proof.
        pmid = f"{service_type.lower()}-{uuid.uuid4().hex[:10]}"
        return pmid, {
            "agent": "messages-native",
            "channel": "sms",
            "phone": phone,
            "transport": service_type,
            "transport_attempted": service_type,
            "verified": False,
            "dispatched_at": _now(),
        }

    first = _attempt(detected)
    if first is not None:
        return first

    fallback = "SMS" if detected == "iMessage" else "iMessage"
    second = _attempt(fallback)
    if second is not None:
        info = second[1]
        info["fallback_from"] = detected
        return second[0], info

    raise SenderTransientError(
        f"messages-native: both {detected} and {fallback} failed delivery "
        f"checks for {phone} (chat.db error != 0)"
    )


# Back-compat alias for any callers that imported the older name.
_imessage_native_dispatch = _messages_native_dispatch


def _wire_default_dispatchers() -> None:
    """Register dispatchers for outbound channels.

    - sms: native Messages transport.
    - email / social_dm: no default until a provider/tool-backed dispatcher can
      return a trustworthy receipt. Free-form agent stdout is never registered.
    Use the explicit outreach sandbox flag when a harness intentionally needs
    synthetic stubs.
    """
    if sandbox_enabled():
        # Belt-and-suspenders: don't even register real transports. get_dispatcher
        # also guards, but this keeps _DISPATCHERS clean under sandbox.
        return
    if os.getenv("ELEVATE_SENDER_DISABLE_AGENT"):
        return
    sms_mode = (os.getenv("ELEVATE_SMS_DISPATCHER") or "native").lower()
    if sms_mode != "agent":
        register_dispatcher("sms", _messages_native_dispatch)
    else:
        _log.error(
            "ELEVATE_SMS_DISPATCHER=agent is disabled: transport unavailable / no provider receipt"
        )


_wire_default_dispatchers()


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
    # Exact Realtor Beta fails the whole outbound lane closed BEFORE any
    # queue-state write or dispatcher can run — including the crash-recovery
    # ``mark_sent`` short-circuit below.  The row is deliberately left in its
    # current durable state (never failed/retried/claimed by this refusal).
    policy_refusal = outbound_send_disabled_reason()
    if policy_refusal is not None:
        _log.warning(
            "sender.dispatch_one refused row %s (%s): %s",
            row.get("id"),
            row.get("channel"),
            policy_refusal,
        )
        return {
            "id": row.get("id"),
            "status": "policy_blocked",
            "error_code": BETA_OUTBOUND_SEND_DISABLED_CODE,
            "lastError": policy_refusal,
            "providerMessageId": None,
        }

    queue_id = row["id"]
    channel = row["channel"]
    attempts = int(row.get("attempts", 0))

    # Crash-recovery short-circuit: if a previous tick succeeded at the
    # provider but died before mark_sent, the next claim sees the row in
    # 'sending' with a provider_message_id already set. This only records the
    # prior durable provider evidence; it does not invoke a dispatcher, so it
    # remains safe when the outbound switch was turned off afterward.
    if row.get("providerMessageId") and row.get("status") != outreach_db.SEND_STATUS_SENT:
        return outreach_db.mark_sent(queue_id, row["providerMessageId"])

    # Final defense-in-depth boundary. Approval/retry/tick each check the same
    # profile-scoped flag earlier for better UX, but every path converges here
    # before a real Messages dispatcher can run. Sandbox remains a safe stub.
    if (
        not sandbox_enabled()
        and is_apple_messages_channel(channel)
        and not apple_messages_outbound_enabled()
    ):
        return outreach_db.mark_failed(
            queue_id,
            error=APPLE_MESSAGES_OUTBOUND_DISABLED_ERROR,
        )

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


def tick(*, batch: int = 10, skip_channels: "set[str] | None" = None) -> dict[str, Any]:
    """Claim up to `batch` due rows and dispatch each. Returns counts.

    ``skip_channels`` excludes channels from this tick. The launchd gateway
    passes ``{"sms"}`` because Mac Messages sends require Automation permission
    that only the Elevate app process can hold — SMS is delivered by the app's
    approve-tick, not the daemon. The app's tick passes no skip (handles all)."""
    # Exact Realtor Beta stops the tick before ANY queue mutation: no
    # stale-send recovery, no claim, no dispatch.  Typed refusal only.
    policy_refusal = outbound_send_disabled_reason()
    if policy_refusal is not None:
        _log.info("sender.tick refused: %s", policy_refusal)
        return {
            "claimed": 0,
            "sent": 0,
            "retrying": 0,
            "failed": 0,
            "recovered_sent": 0,
            "recovered_failed": 0,
            "policy_blocked": policy_refusal,
            "duration_ms": 0,
        }

    started = time.time()
    counts = {"claimed": 0, "sent": 0, "retrying": 0, "failed": 0}
    recovered = outreach_db.recover_stale_sends()
    counts["recovered_sent"] = recovered["sent"]
    counts["recovered_failed"] = recovered["failed"]
    effective_skip_channels = set(skip_channels or set())
    if not sandbox_enabled() and not apple_messages_outbound_enabled():
        # Leave paused SMS rows queued rather than claiming and failing them.
        # A direct dispatch_one call still fails closed, covering races and any
        # future caller that bypasses this scheduler boundary.
        effective_skip_channels.update(_APPLE_MESSAGES_CHANNELS)
    rows = outreach_db.claim_due_sends(
        limit=batch,
        skip_channels=effective_skip_channels or None,
    )
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
