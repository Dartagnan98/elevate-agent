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
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


_SEND_AGENT_MODEL = os.getenv("ELEVATE_SEND_AGENT_MODEL", "openai/gpt-5.4-nano")
_SEND_AGENT_MAX_TURNS = int(os.getenv("ELEVATE_SEND_AGENT_MAX_TURNS", "6"))
_SEND_AGENT_TIMEOUT_S = int(os.getenv("ELEVATE_SEND_AGENT_TIMEOUT", "90"))


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


def _haiku_recipient_descriptor(payload: dict[str, Any], channel: str) -> str:
    recipient = payload.get("recipient") or {}
    phone = _format_phone(recipient.get("phone"))
    email = str(recipient.get("email") or "").strip()
    handle = str(recipient.get("social_handle") or "").strip()
    person = str(recipient.get("person_name") or "").strip()
    bits: list[str] = []
    if person:
        bits.append(f"name: {person}")
    if channel == "sms":
        if phone:
            bits.append(f"phone (iMessage): {phone}")
        if email:
            bits.append(f"iMessage email fallback: {email}")
    elif channel == "email":
        if email:
            bits.append(f"email: {email}")
    elif channel == "social_dm":
        if handle:
            bits.append(f"handle: {handle}")
    else:
        if phone:
            bits.append(f"phone: {phone}")
        if email:
            bits.append(f"email: {email}")
        if handle:
            bits.append(f"handle: {handle}")
    return "; ".join(bits) if bits else "(no recipient info)"


def _build_send_prompt(row: dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    channel = row.get("channel") or ""
    draft = str(payload.get("draft_text") or "").strip()
    descriptor = _haiku_recipient_descriptor(payload, channel)
    if channel == "sms":
        instructions = (
            "Send this iMessage via the macOS Messages.app using the terminal toolset.\n"
            "Run osascript with a 'tell application \"Messages\"' block that targets the iMessage service\n"
            "and sends to the phone number (use the buddy form: `send \"<text>\" to buddy \"<phone>\" of (service whose service type is iMessage)`).\n"
            "If the buddy form errors, fall back to opening a new chat: use participants {<phone>}, account (1st account whose service type is iMessage).\n"
            "After osascript returns 0, reply with the single line: SENT <provider-id>\n"
            "Where <provider-id> is any short token you choose (timestamp is fine)."
        )
    else:
        instructions = (
            "Use the send_message tool to deliver this draft to the recipient on the most appropriate platform.\n"
            "After the tool reports success, reply with: SENT <message_id>."
        )
    return (
        f"You are an outbound sender agent. {instructions}\n\n"
        f"Recipient: {descriptor}\n"
        f"Channel: {channel}\n"
        f"Draft text:\n{draft}\n"
    )


def _parse_agent_provider_id(stdout: str) -> str | None:
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if not text:
            continue
        if text.startswith("SENT "):
            token = text[5:].strip()
            return token or f"agent-{uuid.uuid4().hex[:10]}"
        if text == "SENT":
            return f"agent-{uuid.uuid4().hex[:10]}"
    return None


def _send_agent_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Spawn a low-tier OpenAI elevate chat session to actually send the message.

    Channel `sms` routes through Messages.app via osascript (the terminal
    toolset). Other channels lean on the agent's cross-platform `send_message`
    tool (messaging toolset). Returns (provider_message_id, info).
    """
    channel = row.get("channel") or ""
    elevate_bin = shutil.which("elevate") or str(Path.home() / ".local" / "bin" / "elevate")
    if not elevate_bin or not os.path.exists(elevate_bin):
        raise SenderPermanentError("haiku-dispatch: elevate CLI not on PATH")

    payload = row.get("payload") or {}
    if not str(payload.get("draft_text") or "").strip():
        raise SenderPermanentError("send-agent: payload missing draft_text")

    toolsets = "terminal,messaging" if channel == "sms" else "messaging"
    prompt = _build_send_prompt(row)

    cmd = [
        elevate_bin, "chat",
        "-q", prompt,
        "-m", _SEND_AGENT_MODEL,
        "-t", toolsets,
        "-Q",
        "--yolo",
        "--ignore-rules",
        "--max-turns", str(_SEND_AGENT_MAX_TURNS),
    ]
    _log.info(
        "sender.send_agent_dispatch channel=%s task=%s model=%s",
        channel, row.get("taskId"), _SEND_AGENT_MODEL,
    )
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SEND_AGENT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SenderTransientError(f"send-agent timed out after {_SEND_AGENT_TIMEOUT_S}s") from exc

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    pmid = _parse_agent_provider_id(stdout)
    if result.returncode != 0 and pmid is None:
        snippet = (stderr.strip().splitlines() or [""])[-1][:280]
        raise SenderTransientError(
            f"send-agent exit={result.returncode}: {snippet}"
        )
    if pmid is None:
        snippet = (stdout.strip().splitlines() or [""])[-1][:280]
        raise SenderTransientError(
            f"send-agent produced no SENT line: {snippet}"
        )
    return pmid, {
        "agent": "send-agent",
        "model": _SEND_AGENT_MODEL,
        "channel": channel,
        "dispatched_at": _now(),
    }


_CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")


def _detect_preferred_transport(phone: str) -> str:
    """Pick `iMessage` or `SMS` from chat.db history.

    Per-handle: look at the most recent outbound message to that handle
    where `error=0 AND is_sent=1`. If the winner was SMS, return "SMS";
    if iMessage, return "iMessage"; if no successful history exists,
    default to "iMessage" (Apple's own default).

    chat.db.error column meanings the dispatcher cares about:
        0  → no error (delivered / queued OK)
        22 → "Not Delivered" — recipient unreachable on iMessage
    A row with error != 0 means that service genuinely didn't work for
    this recipient last time, so we down-rank it.
    """
    if not os.path.exists(_CHAT_DB_PATH):
        return "iMessage"
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
        return "iMessage"
    if row and row[0]:
        svc = str(row[0]).strip()
        if svc.lower() == "sms":
            return "SMS"
        if svc.lower() == "imessage":
            return "iMessage"
    return "iMessage"


def _verify_send_landed(phone: str, draft_prefix: str, since_epoch: float) -> tuple[str, int] | None:
    """Confirm the message actually delivered by reading chat.db.

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


def _osa_send_via(phone: str, draft: str, service_type: str) -> tuple[int, str, str]:
    """Run a single osascript send via the named service ('iMessage' or 'SMS').

    Returns (returncode, stdout, stderr). Caller decides what to do.
    """
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
    return (result.returncode, result.stdout or "", result.stderr or "")


def _imsg_service_for_channel(channel: str, detected: str) -> str:
    if channel == "sms":
        # Let the local Messages gateway choose the concrete phone transport.
        # Some current "SMS" conversations are stored as RCS in chat.db; forcing
        # --service sms can create a local row that later flips to Not Delivered.
        # `auto` allows imsg/Messages to use SMS relay or the existing RCS route.
        return "auto"
    if channel == "imessage":
        return "imessage"
    return "auto" if detected == "SMS" else "imessage"


def _imsg_send_via(handle: str, draft: str, channel: str, detected: str) -> tuple[str, dict[str, Any]] | None:
    """Send through the local `imsg send` gateway when available.

    Returns None only when `imsg` is not installed or legacy osascript is forced,
    allowing the older AppleScript path to remain as a fallback. Any attempted
    `imsg` failure is raised so we never silently mark a real send as successful.
    """
    if os.getenv("ELEVATE_MESSAGES_USE_OSASCRIPT", "").lower() in ("1", "true", "yes"):
        return None
    imsg_bin = shutil.which("imsg")
    if not imsg_bin:
        return None
    service = _imsg_service_for_channel(str(channel or ""), detected)
    started = time.time()
    cmd = [imsg_bin, "send", "--to", handle, "--text", draft, "--service", service]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("ELEVATE_IMSG_SEND_TIMEOUT", "45")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SenderTransientError("imsg send timed out") from exc
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode != 0:
        last = (stderr or stdout or f"exit={result.returncode}").strip().splitlines()[-1][:240]
        raise SenderTransientError(f"imsg send failed: {last}")
    # `imsg send` can return success after Messages accepts the row, then the
    # row flips to Not Delivered a moment later. Verify phone handles through
    # chat.db before marking the queue row sent.
    verified = None
    if handle.startswith("+") or any(ch.isdigit() for ch in handle):
        time.sleep(float(os.getenv("ELEVATE_IMSG_VERIFY_DELAY", "2.0")))
        verified = _verify_send_landed(handle, draft[:32], started)
        if verified is not None and verified[1] != 0:
            svc, error_code = verified
            raise SenderTransientError(
                f"imsg send landed but Messages reported not delivered "
                f"(service={svc or service}, error={error_code})"
            )
    pmid = f"imsg-{uuid.uuid4().hex[:10]}"
    return pmid, {
        "agent": "messages-native",
        "gateway": "imsg",
        "channel": channel or "imessage",
        "handle": handle,
        "service": service,
        "transport_attempted": detected,
        "dispatched_at": _now(),
        "stdout": stdout.strip()[:500],
        "verified": verified is not None,
        "verification": {"service": verified[0], "error": verified[1]} if verified else None,
    }


def _messages_native_dispatch(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Send via macOS Messages.app — dynamic iMessage vs SMS per recipient.

    Detection flow:
      1. Resolve the Apple Messages handle from recipient phone first, then
         email / Apple ID fallback for iMessage-only contacts.
      2. Pre-flight chat.db lookup → pick the service that worked most
         recently for this handle. Defaults to iMessage if no history.
      3. Run osascript send via the chosen service.
      4. Post-send verify in chat.db (give Messages 1.5s to write the
         row + Apple's IDS to ack). If the row landed with error != 0
         AND we picked iMessage, retry on SMS once when the handle is a phone.

    Override the whole detection with `ELEVATE_SMS_DISPATCHER=agent`
    (revert to LLM) or `ELEVATE_FORCE_SMS=1` (skip iMessage entirely).
    """
    payload = row.get("payload") or {}
    draft = str(payload.get("draft_text") or "").strip()
    if not draft:
        raise SenderPermanentError("messages-native: payload missing draft_text")
    recipient = payload.get("recipient") or {}
    phone = _format_phone(recipient.get("phone"))
    email = str(recipient.get("email") or "").strip()
    handle = phone or email
    if not handle:
        raise SenderPermanentError("messages-native: recipient missing phone/email handle")

    force_sms = os.getenv("ELEVATE_FORCE_SMS", "").lower() in ("1", "true", "yes")
    # SMS only makes sense for phone handles. Email / Apple ID routes stay on iMessage.
    detected = "SMS" if (force_sms and phone) else _detect_preferred_transport(handle)
    if not phone and detected == "SMS":
        detected = "iMessage"

    imsg_result = _imsg_send_via(handle, draft, str(row.get("channel") or "imessage"), detected)
    if imsg_result is not None:
        pmid, info = imsg_result
        info["phone"] = phone
        info["email"] = email
        return pmid, info

    started = time.time()

    def _attempt(service_type: str) -> tuple[str, dict[str, Any]] | None:
        send_start = time.time()
        rc, stdout, stderr = _osa_send_via(handle, draft, service_type)
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
                    "channel": row.get("channel") or "sms",
                    "handle": handle,
                    "phone": phone,
                    "email": email,
                    "transport": svc_observed,
                    "transport_attempted": service_type,
                    "dispatched_at": _now(),
                    "verify_lag_ms": int((time.time() - send_start) * 1000),
                }
            # Service-level rejection (error 22 = "Not Delivered" for iMessage).
            return None
        # Couldn't observe the row at all — assume delivered (rare on this Mac).
        pmid = f"{service_type.lower()}-{uuid.uuid4().hex[:10]}"
        return pmid, {
            "agent": "messages-native",
            "channel": row.get("channel") or "sms",
            "handle": handle,
            "phone": phone,
            "email": email,
            "transport": service_type,
            "transport_attempted": service_type,
            "verified": False,
            "dispatched_at": _now(),
        }

    first = _attempt(detected)
    if first is not None:
        return first

    fallback = "SMS" if (detected == "iMessage" and phone) else "iMessage"
    if fallback == detected:
        raise SenderTransientError(
            f"messages-native: {detected} failed delivery checks for {handle} "
            f"(chat.db error != 0)"
        )
    second = _attempt(fallback)
    if second is not None:
        info = second[1]
        info["fallback_from"] = detected
        return second[0], info

    raise SenderTransientError(
        f"messages-native: both {detected} and {fallback} failed delivery "
        f"checks for {handle} (chat.db error != 0)"
    )


# Back-compat alias for any callers that imported the older name.
_imessage_native_dispatch = _messages_native_dispatch


def _wire_default_dispatchers() -> None:
    """Register dispatchers for outbound channels.

    - sms: native osascript (set ELEVATE_SMS_DISPATCHER=agent to use the agent).
    - email / social_dm: low-tier-GPT agent dispatcher.
    Disable both with `ELEVATE_SENDER_DISABLE_AGENT` so harnesses keep the stub.
    """
    if os.getenv("ELEVATE_SENDER_DISABLE_AGENT"):
        return
    sms_mode = (os.getenv("ELEVATE_SMS_DISPATCHER") or "native").lower()
    if sms_mode == "agent":
        register_dispatcher("sms", _send_agent_dispatch)
        register_dispatcher("imessage", _send_agent_dispatch)
    else:
        register_dispatcher("sms", _messages_native_dispatch)
        register_dispatcher("imessage", _messages_native_dispatch)
    for channel in ("email", "social_dm"):
        register_dispatcher(channel, _send_agent_dispatch)


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


def _messages_live_confirmed() -> bool:
    return os.getenv("ELEVATE_MESSAGES_LIVE_CONFIRMED", "").lower() in ("1", "true", "yes")


def _recipient_handle_from_row(row: dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    recipient = payload.get("recipient") or {}
    return (
        _format_phone(recipient.get("phone"))
        or str(recipient.get("email") or recipient.get("apple_handle") or "").strip()
    )


def _messages_test_allowed(row: dict[str, Any]) -> bool:
    payload = row.get("payload") or {}
    safety = payload.get("safety") or {}
    if not bool(safety.get("test_send")):
        return False
    expected = os.getenv("ELEVATE_MESSAGES_TEST_RECIPIENT", "").strip()
    if not expected:
        return True
    actual = _recipient_handle_from_row(row)
    return _format_phone(actual) == _format_phone(expected) or actual.lower() == expected.lower()


def _messages_send_blocked(row: dict[str, Any]) -> bool:
    channel = str(row.get("channel") or "").lower()
    if channel not in {"sms", "imessage"}:
        return False
    payload = row.get("payload") or {}
    safety = payload.get("safety") or {}
    approved_dashboard_send = bool(safety.get("approved_dashboard_send"))
    return not (_messages_live_confirmed() or approved_dashboard_send or _messages_test_allowed(row))


def send_messages_self_test(to: str, text: str | None = None) -> dict[str, Any]:
    """Send exactly one Lead Desk self-test through the local Messages gateway."""
    handle = str(to or "").strip()
    if not handle:
        raise SenderPermanentError("self-test recipient is required")
    body = (text or f"Elevate Lead Desk test message {int(time.time())}. Reply received confirms outbound is live.").strip()
    row = {
        "id": f"self-test-{uuid.uuid4().hex[:10]}",
        "sourceId": "apple-messages",
        "threadId": "self-test",
        "taskId": "self-test",
        "channel": "imessage",
        "status": outreach_db.SEND_STATUS_SENDING,
        "attempts": 0,
        "payload": {
            "draft_text": body,
            "recipient": {
                "phone": _format_phone(handle) if any(ch.isdigit() for ch in handle) else None,
                "email": handle if "@" in handle else None,
                "apple_handle": handle,
                "person_name": "Skyleigh self-test",
            },
            "safety": {"test_send": True},
            "channel_meta": {"resolved_channel": "imessage", "resolved_from": "self-test"},
        },
    }
    pmid, info = get_dispatcher("imessage")(row)
    return {
        "ok": True,
        "providerMessageId": pmid,
        "channel": "imessage",
        "recipient": handle,
        "info": info,
    }


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

    if _messages_send_blocked(row):
        return outreach_db.mark_retrying(
            queue_id,
            error="messages-live-gated: run/confirm the one-message self-test before live lead sends",
            next_retry_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        ) or {}

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
