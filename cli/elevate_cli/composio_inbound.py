"""Composio inbound message puller (Phase 5 of /leads plan).

Pulls DMs / replies / messages from each user-connected Composio toolkit and
normalizes them into the source-inbox jsonl format that the rest of `/leads`
already consumes.

Design rules
------------
- **Capability gate first.** Only toolkits whose ``inbound.supported`` is True
  in ``composio_capabilities.json`` are polled. Unverified toolkits are
  skipped with a banner reason — never silently fail.
- **Idempotent.** Each inbound record is keyed on ``provider_message_id``;
  the puller short-circuits when the message already exists.
- **Cursor-based incremental pulls.** Per-account cursor lives at
  ``data/sources/composio-<toolkit>/cursors.json`` and is bumped only after
  the page is durably written.
- **No webhooks.** Polling-only by design (Phase 5 plan rule). 10-minute
  default schedule; the cron job declares the schedule, this module just
  performs one tick when invoked.
- **Sender uses execute_tool through the Phase 5a wrapper too.** This
  module is the inbound twin: same chokepoint, opposite direction.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elevate_cli import composio_client
from elevate_cli.config import load_config
from elevate_cli.source_connectors import _candidate_tools_root, get_source_root_info

_log = logging.getLogger(__name__)

_WARNING_THROTTLE_SECONDS = 600.0
_warning_state: dict[tuple[Any, ...], dict[str, float | int]] = {}


def _warn_repeating(key: tuple[Any, ...], template: str, *args: Any) -> None:
    """Log the first repeated warning, then periodic summaries."""
    now = time.monotonic()
    state = _warning_state.get(key)
    if state is None:
        _warning_state[key] = {"last": now, "suppressed": 0}
        _log.warning(template, *args)
        return

    elapsed = now - state["last"]
    if elapsed < _WARNING_THROTTLE_SECONDS:
        state["suppressed"] = int(state["suppressed"]) + 1
        return

    suppressed = int(state["suppressed"])
    _log.warning(
        template + " (suppressed %d repeats over %.0fs)",
        *args,
        suppressed,
        elapsed,
    )
    state["last"] = now
    state["suppressed"] = 0


# Toolkit → kind of identity that uniquely keys the sender. Used by the
# contact-synthesizer below to project the per-message ``from`` field into
# a stable native id that the canonical walker can group on.
_TOOLKIT_TO_HANDLE_KIND: dict[str, str] = {
    "gmail": "email",
    "instagram": "instagram_id",
    "facebook": "facebook_id",
    "whatsapp": "wa_id",
    "telegram": "telegram_id",
    "slack": "slack_id",
}

_EMAIL_RE = re.compile(r"<([^>]+@[^>]+)>")


def _sender_identity(toolkit: str, sender_raw: Any) -> tuple[str, str, str]:
    """Return (kind, value, display_name) for a composio sender payload.

    Toolkit-specific extraction — gmail's ``from`` is "Name <email>", IG's
    is a dict, FB's nests email under ``from.email``. Falls back to the
    flattened sender string so we never lose a row, even when the toolkit
    payload shape drifts.
    """
    handle_kind = _TOOLKIT_TO_HANDLE_KIND.get(toolkit, f"{toolkit}_id")

    if isinstance(sender_raw, dict):
        for key in ("id", "username", "email"):
            v = sender_raw.get(key)
            if v:
                value = str(v).strip().lower()
                display = (
                    sender_raw.get("name")
                    or sender_raw.get("username")
                    or sender_raw.get("display_name")
                    or value
                )
                if key == "email" or "@" in value:
                    return ("email", value, str(display))
                return (handle_kind, value, str(display))
        return (handle_kind, "unknown", "Unknown sender")

    s = (str(sender_raw) if sender_raw is not None else "").strip()
    if not s:
        return (handle_kind, "unknown", "Unknown sender")

    m = _EMAIL_RE.search(s)
    if m:
        email = m.group(1).strip().lower()
        name = s.split("<", 1)[0].strip().strip('"') or email
        return ("email", email, name)

    if "@" in s and " " not in s:
        return ("email", s.lower(), s)

    return (handle_kind, s.lower(), s)


def _read_messages_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)


def synthesize_canonical_files(toolkit: str) -> dict[str, int]:
    """Rebuild ``contacts.jsonl`` + ``conversations.jsonl`` for a toolkit
    from its accumulated ``messages.jsonl``. Also stamps ``contact_id`` /
    ``conversation_id`` onto every message row so the canonical walker
    can join.

    Pure derivation — replays in-memory. Safe to re-run; output is
    deterministic for a given messages.jsonl.

    Returns ``{"contacts": N, "conversations": M, "messages": K}``.
    """
    source_id = _source_id_for_toolkit(toolkit)
    source_dir = _source_dir_for_toolkit(toolkit)
    messages_path = source_dir / "messages.jsonl"
    messages = _read_messages_jsonl(messages_path)
    if not messages:
        return {"contacts": 0, "conversations": 0, "messages": 0}

    contacts: dict[str, dict[str, Any]] = {}
    conversations: dict[str, dict[str, Any]] = {}
    updated_messages: list[dict[str, Any]] = []

    for msg in messages:
        sender_raw = msg.get("from") or msg.get("from_") or msg.get("sender")
        kind, value, display = _sender_identity(toolkit, sender_raw)
        native_contact_id = f"{kind}:{value}"
        thread_id = (
            msg.get("conversation_id")
            or msg.get("thread_id")
            or msg.get("threadId")
            or native_contact_id
        )
        ts = msg.get("timestamp") or msg.get("ts") or _now_iso()
        direction = msg.get("direction") or "inbound"

        c = contacts.get(native_contact_id)
        if c is None:
            c = {
                "source_id": source_id,
                "source_record_id": native_contact_id,
                "display_name": display,
                "channel": source_id,
                "handle": value,
                "identities": [{"kind": kind, "value": value}],
                "tags": [source_id, "message-contact"],
                "target_ui_surfaces": ["Outreach", "Leads", "Today", "Approvals"],
                "total_messages": 0,
                "inbound_count": 0,
                "outbound_count": 0,
                "first_seen_at": ts,
                "last_seen_at": ts,
                "last_text": "",
            }
            if kind == "email":
                c["primary_email"] = value
            contacts[native_contact_id] = c

        c["total_messages"] += 1
        if direction == "outbound":
            c["outbound_count"] += 1
        else:
            c["inbound_count"] += 1
        if ts < c["first_seen_at"]:
            c["first_seen_at"] = ts
        if ts > c["last_seen_at"]:
            c["last_seen_at"] = ts
            c["last_text"] = msg.get("text") or msg.get("last_text") or msg.get("body") or ""

        conv = conversations.get(thread_id)
        if conv is None:
            conversations[thread_id] = {
                "source_id": source_id,
                "source_record_id": thread_id,
                "conversation_id": thread_id,
                "contact_id": native_contact_id,
                "channel": source_id,
                "first_seen_at": ts,
                "last_seen_at": ts,
                "inbound_count": 0,
                "outbound_count": 0,
                "total_messages": 0,
            }
            conv = conversations[thread_id]
        conv["total_messages"] += 1
        if direction == "outbound":
            conv["outbound_count"] += 1
        else:
            conv["inbound_count"] += 1
        if ts < conv["first_seen_at"]:
            conv["first_seen_at"] = ts
        if ts > conv["last_seen_at"]:
            conv["last_seen_at"] = ts

        msg = dict(msg)
        msg["contact_id"] = native_contact_id
        msg["conversation_id"] = thread_id
        msg.setdefault("source_id", source_id)
        msg.setdefault("source_record_id", msg.get("provider_message_id") or msg.get("id"))
        msg.setdefault("timestamp", ts)
        msg.setdefault("channel", source_id)
        msg.setdefault("text", msg.get("body") or msg.get("last_text") or "")
        updated_messages.append(msg)

    _write_jsonl_atomic(source_dir / "contacts.jsonl", list(contacts.values()))
    _write_jsonl_atomic(source_dir / "conversations.jsonl", list(conversations.values()))
    _write_jsonl_atomic(messages_path, updated_messages)

    return {
        "contacts": len(contacts),
        "conversations": len(conversations),
        "messages": len(updated_messages),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_id_for_toolkit(toolkit: str) -> str:
    return f"composio-{toolkit}"


def _source_dir_for_toolkit(toolkit: str) -> Path:
    """Return the canonical source dir for a toolkit's inbound jsonl.

    Must match where ``build_source_inbox_response`` looks — that is,
    ``<sourceRoot>/composio-<toolkit>``. The earlier draft wrote to
    ``<toolsRoot>/composio-<toolkit>`` (one level up), which orphaned
    the messages from the /leads inbox builder.
    """
    config = load_config() or {}
    info = get_source_root_info(config)
    return Path(info["sourceRoot"]) / _source_id_for_toolkit(toolkit)


def _cursors_path(toolkit: str) -> Path:
    return _source_dir_for_toolkit(toolkit) / "cursors.json"


def _load_cursors(toolkit: str) -> dict[str, Any]:
    path = _cursors_path(toolkit)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log.warning("composio_inbound: failed to read cursors %s: %s", path, exc)
        return {}


def _save_cursors(toolkit: str, cursors: dict[str, Any]) -> None:
    path = _cursors_path(toolkit)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cursors, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _backfill_seen_table_from_jsonl(toolkit: str) -> int:
    """One-time migration: pre-populate inbound_seen from any pre-existing
    messages.jsonl so the first table-backed tick after upgrade doesn't
    re-pull the entire history.

    Idempotent: subsequent calls are O(rows already in inbound_seen) +
    O(file lines) — but the DB inserts are INSERT OR IGNORE so this only
    has to actually do work once. We gate the work on a meta marker per
    toolkit to keep the steady-state path cheap.
    """
    from elevate_cli import outreach_db as _odb

    marker_key = f"inbound_seen_backfill::{toolkit}"
    with _odb.connect() as conn:
        if _odb._read_meta(conn, marker_key):
            return 0

    src_dir = _source_dir_for_toolkit(toolkit)
    path = src_dir / "messages.jsonl"
    pmids: list[str] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    pmid = (rec or {}).get("provider_message_id") or (rec or {}).get("id") or ""
                    if pmid:
                        pmids.append(str(pmid))
        except Exception as exc:
            _log.warning("composio_inbound: backfill scan failed for %s: %s", path, exc)

    inserted = _odb.inbound_seen_record(toolkit, pmids) if pmids else 0
    with _odb.connect() as conn:
        with _odb.transaction(conn):
            _odb._write_meta(conn, marker_key, _now_iso())
    if inserted:
        _log.info("composio_inbound[%s]: backfilled %d pmids into inbound_seen", toolkit, inserted)
    return inserted


def _resolve_path(payload: Any, path: list[str] | None) -> Any:
    """Walk a list of keys through nested dicts; return None if any step misses."""
    if not path:
        return payload
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _flatten_sender(value: Any) -> str:
    """Coerce Composio's varied ``from`` shapes into a printable display string.

    IG returns ``{"from_": {"username": "..."}}``; FB returns
    ``{"from": {"name": "...", "email": "..."}}``; Gmail returns a string.
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "username", "display_name", "email", "id"):
            v = value.get(key)
            if v:
                return str(v).strip()
    return str(value).strip()


def _normalize(
    item: dict[str, Any],
    toolkit: str,
    account_id: str,
    *,
    conversation_id_override: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a Composio inbound payload to the source-inbox message shape.

    Composio returns toolkit-specific shapes (Gmail vs Slack vs IG differ);
    this normalizer pulls the common fields and stashes the raw payload so
    the UI can still expose toolkit-specific bits without us pre-modeling
    every variant. ``conversation_id_override`` lets the two-step walkers
    inject the parent conversation id when individual messages don't carry
    it (IG / FB messages list).
    """
    pmid = str(
        item.get("id")
        or item.get("messageId")
        or item.get("message_id")
        or item.get("threadId")
        or ""
    ).strip()
    thread_id = str(
        conversation_id_override
        or item.get("thread_id")
        or item.get("threadId")
        or item.get("conversation_id")
        or pmid
    ).strip()
    # IG renames `from` -> `from_` to dodge the Python keyword; cover both.
    sender_raw = (
        item.get("from")
        or item.get("from_")
        or item.get("sender")
        or item.get("author")
        or item.get("messageFrom")
        or ""
    )
    body = (
        item.get("body")
        or item.get("message")
        or item.get("text")
        or item.get("messageText")
        or item.get("snippet")
        or item.get("preview")
        or ""
    )
    ts = (
        item.get("ts")
        or item.get("created_time")
        or item.get("date")
        or item.get("created_at")
        or item.get("messageTimestamp")
        or _now_iso()
    )
    sender_str = _flatten_sender(sender_raw)
    body_str = str(body).strip()
    snippet = body_str if len(body_str) <= 200 else body_str[:197] + "..."
    record: dict[str, Any] = {
        # Composio-native fields (kept for downstream toolkit-specific UIs)
        "provider_message_id": pmid,
        "id": pmid,
        "thread_id": thread_id,
        "direction": "inbound",
        "from": sender_raw,
        "body": body,
        "ts": ts,
        "toolkit": toolkit,
        "connected_account_id": account_id,
        "raw": item,
        "ingested_at": _now_iso(),
        # Canonical fields the source-inbox builder reads (matches what
        # apple-messages and crm sources write so /leads can pick this up
        # without per-source special-cases).
        "source_id": f"composio-{toolkit}",
        "source_record_id": pmid,
        "conversation_id": thread_id,
        "channel": f"composio-{toolkit}",
        "service": toolkit,
        "display_name": sender_str or f"{toolkit} sender",
        "handle": sender_str,
        "text": snippet,
        "last_text": snippet,
        "timestamp": ts,
        "inbound_count": 1,
        "outbound_count": 0,
        "total_messages": 1,
    }
    if extra_context:
        # e.g. {"page_id": "...", "page_name": "..."} for FB so the UI can
        # show "via Training Academy Walnut Grove" without re-reading the raw payload.
        record["context"] = extra_context
    return record


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """True append, never read+rewrite. Atomic per-line writes.

    The source-inbox JSONLs are append-only by contract; rewriting them on
    every inbound batch would (a) be O(n) per tick and (b) blow up if the
    process dies mid-rewrite. Each line is one JSON object terminated by ``\\n``.
    """
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _selection_path(toolkit: str) -> Path:
    return _source_dir_for_toolkit(toolkit) / "selection.json"


def load_selection(toolkit: str) -> dict[str, Any]:
    path = _selection_path(toolkit)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log.warning("composio_inbound: failed to read selection %s: %s", path, exc)
        return {}


def save_selection(toolkit: str, selection: dict[str, Any]) -> None:
    path = _selection_path(toolkit)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _default_args_for(toolkit_slug: str, page_size: int) -> dict[str, Any]:
    """Per-toolkit defaults so the puller works with no per-account config.

    Gmail's GMAIL_FETCH_EMAILS requires ``query`` (we use ``in:inbox``);
    Slack's fetch requires ``channel``. Without these the call 400s and
    we silently report 0 fetched.
    """
    defaults: dict[str, Any] = {}
    if toolkit_slug == "gmail":
        defaults["query"] = "in:inbox"
        defaults["max_results"] = page_size
    elif toolkit_slug == "outlook":
        defaults["max_results"] = page_size
    return defaults


def _bearer_auth(token: str) -> dict[str, Any]:
    """Composio custom_auth_params shape for a Graph API page-token override."""
    return {"parameters": [{"name": "Authorization", "in": "header", "value": f"Bearer {token}"}]}


def _facebook_pages(account_id: str, account_user_id: str | None) -> list[dict[str, Any]]:
    """Refresh-and-return the user's FB pages with their access tokens."""
    cap = composio_client.capability("facebook")
    inbound = (cap or {}).get("inbound") or {}
    pages_slug = inbound.get("pages_slug") or "FACEBOOK_GET_USER_PAGES"
    response_path = inbound.get("pages_response_path") or ["data", "response_data", "data"]
    resp = composio_client.execute_tool(pages_slug, account_id, {}, user_id=account_user_id)
    if not resp.get("ok"):
        _log.warning("composio_inbound[facebook]: pages list failed: %s", resp.get("error"))
        return []
    pages = _resolve_path(resp.get("data") or {}, response_path) or []
    out: list[dict[str, Any]] = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if not pid:
            continue
        out.append({
            "id": str(pid),
            "name": str(p.get("name") or pid),
            "access_token": p.get("access_token"),
            "tasks": p.get("tasks") or [],
        })
    return out


def list_facebook_pages_for_picker() -> dict[str, Any]:
    """Return the union of all FB pages across connected FB accounts plus
    the current selection, for the page-picker UI.
    """
    accounts_resp = composio_client.list_all_connected_accounts(toolkit="facebook")
    if not accounts_resp.get("ok"):
        return {"ok": False, "error": accounts_resp.get("error"), "pages": [], "selected_page_ids": []}
    accounts = (accounts_resp.get("data") or {}).get("items") or []
    selection = load_selection("facebook")
    selected_ids = set(selection.get("selected_page_ids") or [])

    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    for acct in accounts:
        acct_id = acct.get("id") or acct.get("connected_account_id")
        if not acct_id:
            continue
        for p in _facebook_pages(acct_id, acct.get("user_id")):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            pages.append({
                "id": p["id"],
                "name": p["name"],
                "selected": p["id"] in selected_ids,
                "tasks": p["tasks"],
                "connected_account_id": acct_id,
            })
    return {"ok": True, "pages": pages, "selected_page_ids": list(selected_ids)}


def set_facebook_page_selection(page_ids: list[str]) -> dict[str, Any]:
    cleaned = [str(pid).strip() for pid in (page_ids or []) if str(pid).strip()]
    selection = load_selection("facebook")
    selection["selected_page_ids"] = sorted(set(cleaned))
    selection["updated_at"] = _now_iso()
    save_selection("facebook", selection)
    return {"ok": True, "selected_page_ids": selection["selected_page_ids"]}


def _walk_single(
    toolkit: str,
    inbound: dict[str, Any],
    account_id: str,
    account_user_id: str | None,
    cursors: dict[str, Any],
    page_size: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], int]:
    """Original single-call paginator (Gmail, Slack, Outlook)."""
    inbound_slug = inbound.get("slug") or ""
    required_args = inbound.get("required_args") or []
    if toolkit == "slack" and "channel" in required_args:
        _log.info("composio_inbound[slack]: skipping account %s — needs per-channel config", account_id)
        return [], 0

    cursor = cursors.get(account_id, {}).get("cursor")
    fetched = 0
    out: list[dict[str, Any]] = []
    pages = 0
    while pages < max_pages:
        args: dict[str, Any] = {"limit": page_size, **_default_args_for(toolkit, page_size)}
        if cursor:
            args["cursor"] = cursor
        resp = composio_client.execute_tool(inbound_slug, account_id, args, user_id=account_user_id)
        if not resp.get("ok"):
            error = resp.get("error")
            _warn_repeating(
                ("execute_tool", toolkit, account_id, inbound_slug, error),
                "composio_inbound[%s/%s]: execute_tool failed: %s",
                toolkit, account_id, error,
            )
            break
        data = (resp.get("data") or {}).get("data") or resp.get("data") or {}
        items: Any = None
        if isinstance(data, dict):
            for key in ("items", "messages", "value", "data"):
                candidate = data.get(key)
                if isinstance(candidate, list):
                    items = candidate
                    break
        if items is None and isinstance(data, list):
            items = data
        items = items or []
        fetched += len(items)
        for item in items:
            out.append(_normalize(item, toolkit, account_id))
        next_cursor = None
        if isinstance(data, dict):
            next_cursor = data.get("next_cursor") or data.get("nextCursor")
        if not next_cursor or not items:
            cursor = next_cursor or cursor
            break
        cursor = next_cursor
        pages += 1
    cursors[account_id] = {"cursor": cursor, "updated_at": _now_iso()}
    return out, fetched


def _walk_two_step(
    toolkit: str,
    inbound: dict[str, Any],
    account_id: str,
    account_user_id: str | None,
    page_size: int,
    max_conversations: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """List conversations, then for each conversation list messages.

    Used for Instagram. The conversation list returns IDs only (no body
    preview), so we must walk into each one to get message text.
    """
    convs_slug = inbound.get("conversations_slug")
    msgs_slug = inbound.get("messages_slug")
    convs_path = inbound.get("conversations_response_path") or ["data", "data"]
    msgs_path = inbound.get("messages_response_path") or ["data", "data"]
    convs_default = dict(inbound.get("conversations_default_args") or {})
    msgs_default = dict(inbound.get("messages_default_args") or {})
    if not convs_slug or not msgs_slug:
        return [], 0

    convs_resp = composio_client.execute_tool(convs_slug, account_id, convs_default, user_id=account_user_id)
    if not convs_resp.get("ok"):
        _log.warning("composio_inbound[%s/%s]: conversations failed: %s", toolkit, account_id, convs_resp.get("error"))
        return [], 0
    convs = _resolve_path(convs_resp.get("data") or {}, convs_path) or []
    out: list[dict[str, Any]] = []
    fetched = 0
    walked = 0
    for conv in convs:
        if walked >= max_conversations:
            break
        cid = (conv or {}).get("id") if isinstance(conv, dict) else None
        if not cid:
            continue
        walked += 1
        args = {**msgs_default, "conversation_id": cid}
        m_resp = composio_client.execute_tool(msgs_slug, account_id, args, user_id=account_user_id)
        if not m_resp.get("ok"):
            status = m_resp.get("status")
            if isinstance(status, int) and status >= 500:
                # 5xx survived composio_client's retry budget. Do NOT silently
                # `continue` — that lets the conversation fall through to a
                # generic canned draft downstream. Emit a sentinel record so
                # the thread stays visible but is marked draft-unavailable.
                # `direction="system"` (not "inbound") makes the fallback
                # generator in source_connectors skip it (the
                # `direction != "inbound"` guard, ~L2386).
                _log.warning(
                    "composio_inbound[%s/%s]: messages 5xx-exhausted for %s: %s — marking draft-unavailable",
                    toolkit, account_id, cid, m_resp.get("error"),
                )
                sentinel = _normalize(
                    {"id": f"unavailable-{cid}", "body": "", "ts": _now_iso()},
                    toolkit,
                    account_id,
                    conversation_id_override=str(cid),
                )
                sentinel["direction"] = "system"
                sentinel["messages_unavailable"] = True
                sentinel["status"] = "messages_unavailable"
                sentinel["inbound_count"] = 0
                sentinel["unavailable_reason"] = m_resp.get("error") or f"HTTP {status}"
                out.append(sentinel)
            else:
                # 4xx (auth/permission/not-found) is permanent — keep prior
                # behaviour: log it and move on.
                _log.warning(
                    "composio_inbound[%s/%s]: messages 4xx-permanent for %s: %s",
                    toolkit, account_id, cid, m_resp.get("error"),
                )
            continue
        items = _resolve_path(m_resp.get("data") or {}, msgs_path) or []
        fetched += len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append(_normalize(item, toolkit, account_id, conversation_id_override=str(cid)))
    return out, fetched


def _walk_facebook_pages(
    inbound: dict[str, Any],
    account_id: str,
    account_user_id: str | None,
    selected_page_ids: set[str],
    page_size: int,
    max_conversations_per_page: int = 25,
) -> tuple[list[dict[str, Any]], int]:
    """Three-step walk: pages -> conversations -> messages. Each call uses
    the page's own access_token via custom_auth_params."""
    convs_slug = inbound.get("conversations_slug") or "FACEBOOK_GET_PAGE_CONVERSATIONS"
    msgs_slug = inbound.get("messages_slug") or "FACEBOOK_GET_CONVERSATION_MESSAGES"
    convs_path = inbound.get("conversations_response_path") or ["data", "response_data", "data"]
    msgs_path = inbound.get("messages_response_path") or ["data", "response_data", "messages", "data"]
    convs_default = dict(inbound.get("conversations_default_args") or {})
    msgs_default = dict(inbound.get("messages_default_args") or {})

    pages = _facebook_pages(account_id, account_user_id)
    if selected_page_ids:
        pages = [p for p in pages if p["id"] in selected_page_ids]
    if not pages:
        return [], 0

    out: list[dict[str, Any]] = []
    fetched = 0
    for page in pages:
        page_token = page.get("access_token")
        if not page_token:
            _log.info("composio_inbound[facebook]: page %s has no access_token, skipping", page["id"])
            continue
        auth = _bearer_auth(page_token)
        args = {**convs_default, "page_id": page["id"]}
        c_resp = composio_client.execute_tool(
            convs_slug, account_id, args, user_id=account_user_id, custom_auth_params=auth,
        )
        if not c_resp.get("ok"):
            _log.warning("composio_inbound[facebook/%s]: convs failed: %s", page["id"], c_resp.get("error"))
            continue
        convs = _resolve_path(c_resp.get("data") or {}, convs_path) or []
        for ix, conv in enumerate(convs):
            if ix >= max_conversations_per_page:
                break
            cid = (conv or {}).get("id") if isinstance(conv, dict) else None
            if not cid:
                continue
            m_args = {**msgs_default, "conversation_id": cid}
            m_resp = composio_client.execute_tool(
                msgs_slug, account_id, m_args, user_id=account_user_id, custom_auth_params=auth,
            )
            if not m_resp.get("ok"):
                _log.warning("composio_inbound[facebook/%s]: msgs failed: %s", cid, m_resp.get("error"))
                continue
            items = _resolve_path(m_resp.get("data") or {}, msgs_path) or []
            fetched += len(items)
            ctx = {"page_id": page["id"], "page_name": page["name"]}
            for item in items:
                if not isinstance(item, dict):
                    continue
                out.append(_normalize(item, "facebook", account_id, conversation_id_override=str(cid), extra_context=ctx))
    return out, fetched


def pull_toolkit(toolkit: str, *, page_size: int = 50, max_pages: int = 5) -> dict[str, Any]:
    """Pull inbound messages for one toolkit. Returns counts + skip reason if any.

    Skips when the capability matrix says ``inbound.supported`` is False.
    Skips when no connected accounts exist for the toolkit. Dispatches on
    ``inbound.kind`` (``single``, ``two_step``, ``page_walk``).
    """
    cap = composio_client.capability(toolkit)
    inbound = (cap or {}).get("inbound") or {}
    if not inbound.get("supported"):
        return {
            "ok": False,
            "skipped": True,
            "reason": f"inbound not supported for {toolkit}: {inbound.get('verification', 'unknown')}",
            "toolkit": toolkit,
            "fetched": 0,
            "new": 0,
        }

    kind = inbound.get("kind") or "single"
    if kind == "single" and not inbound.get("slug"):
        return {
            "ok": False,
            "skipped": True,
            "reason": f"capability matrix has no inbound slug for {toolkit}",
            "toolkit": toolkit,
            "fetched": 0,
            "new": 0,
        }

    accounts_resp = composio_client.list_all_connected_accounts(toolkit=toolkit)
    if not accounts_resp.get("ok"):
        return {
            "ok": False,
            "skipped": True,
            "reason": f"list_connected_accounts failed: {accounts_resp.get('error')}",
            "toolkit": toolkit,
            "fetched": 0,
            "new": 0,
        }

    accounts = (accounts_resp.get("data") or {}).get("items") or []
    if not accounts:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no connected accounts",
            "toolkit": toolkit,
            "fetched": 0,
            "new": 0,
        }

    # FB requires the user to pick which pages to surface — auto-pulling
    # every page on the account would dump 19+ unrelated inboxes onto /leads.
    selected_page_ids: set[str] = set()
    if kind == "page_walk" and inbound.get("selection_required"):
        selection = load_selection(toolkit)
        selected_page_ids = set(selection.get("selected_page_ids") or [])
        if not selected_page_ids:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no pages selected — open Config → Composio → Facebook to pick pages",
                "toolkit": toolkit,
                "fetched": 0,
                "new": 0,
            }

    _backfill_seen_table_from_jsonl(toolkit)

    from elevate_cli import outreach_db as _odb

    cursors = _load_cursors(toolkit)
    new_records: list[dict[str, Any]] = []
    in_run_seen: set[str] = set()
    fetched = 0

    for account in accounts:
        account_id = (
            account.get("id")
            or account.get("connected_account_id")
            or account.get("uuid")
            or ""
        )
        if not account_id:
            continue
        account_user_id = account.get("user_id") or account.get("entity_id") or None

        if kind == "single":
            page_normalized, page_fetched = _walk_single(
                toolkit, inbound, account_id, account_user_id, cursors, page_size, max_pages,
            )
        elif kind == "two_step":
            page_normalized, page_fetched = _walk_two_step(
                toolkit, inbound, account_id, account_user_id, page_size,
            )
        elif kind == "page_walk":
            page_normalized, page_fetched = _walk_facebook_pages(
                inbound, account_id, account_user_id, selected_page_ids, page_size,
            )
        else:
            _log.warning("composio_inbound[%s]: unknown kind %r, skipping", toolkit, kind)
            continue

        fetched += page_fetched

        page_pmids = [n["provider_message_id"] for n in page_normalized if n["provider_message_id"]]
        already_seen = _odb.inbound_seen_lookup(toolkit, page_pmids)
        for normalized in page_normalized:
            pmid = normalized["provider_message_id"]
            if not pmid or pmid in already_seen or pmid in in_run_seen:
                continue
            in_run_seen.add(pmid)
            new_records.append(normalized)

    if new_records:
        path = _source_dir_for_toolkit(toolkit) / "messages.jsonl"
        _append_jsonl(path, new_records)
        _odb.inbound_seen_record(toolkit, [r["provider_message_id"] for r in new_records])
    _save_cursors(toolkit, cursors)

    writethrough_error: str | None = None
    if new_records:
        try:
            synthesize_canonical_files(toolkit)
        except Exception as exc:
            _log.exception("composio_inbound[%s]: synthesize failed", toolkit)
            writethrough_error = f"synthesize: {exc}"

        if writethrough_error is None:
            try:
                from elevate_cli.data import connect as _data_connect
                from elevate_cli.data.migrate import (
                    BackfillStats as _BackfillStats,
                    walk_jsonl_source as _walk_jsonl_source,
                )

                source_dir = _source_dir_for_toolkit(toolkit)
                stats = _BackfillStats()
                with _data_connect() as conn:
                    _walk_jsonl_source(source_dir, conn=conn, stats=stats, dry_run=False)
            except Exception as exc:
                _log.exception("composio_inbound[%s]: writethrough failed", toolkit)
                writethrough_error = str(exc)

    result: dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "toolkit": toolkit,
        "kind": kind,
        "accounts": len(accounts),
        "fetched": fetched,
        "new": len(new_records),
    }
    if writethrough_error:
        result["writethrough_error"] = writethrough_error
    return result


def pull_all_supported() -> dict[str, Any]:
    """One tick: pull every toolkit whose capability matrix supports inbound."""
    matrix = composio_client.load_capability_matrix() or {}
    toolkits = (matrix.get("toolkits") or {}).keys()
    results = []
    for slug in toolkits:
        try:
            results.append(pull_toolkit(slug))
        except Exception as exc:
            _log.exception("composio_inbound[%s]: tick failed", slug)
            results.append({
                "ok": False,
                "toolkit": slug,
                "error": str(exc),
                "fetched": 0,
                "new": 0,
            })
    summary = {
        "tick_at": _now_iso(),
        "toolkits": results,
        "total_new": sum(r.get("new", 0) for r in results),
        "total_fetched": sum(r.get("fetched", 0) for r in results),
    }
    if summary["total_new"]:
        _log.info("composio_inbound.tick %s", summary)
    return summary
