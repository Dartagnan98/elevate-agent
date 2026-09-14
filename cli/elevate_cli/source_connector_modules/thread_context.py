"""Thread context response helpers for source inbox."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.connector_views import (
    _composio_connector_view,
    connector_view,
)
from elevate_cli.source_connector_modules.draft_helpers import (
    _draft_from_task,
    _is_message_draft_task,
    _task_key,
)
from elevate_cli.source_connector_modules.integration_settings import _as_dict
from elevate_cli.source_connector_modules.source_io import (
    _find_jsonl_record_by_id,
    _parse_record_dt,
    _read_jsonl_records,
    _read_source_ui_state,
    _record_timestamp,
    _snapshot_reader_lock,
    _source_dir,
    _stream_jsonl_records_by_id,
)
from elevate_cli.source_connector_modules.thread_helpers import (
    _record_person_name,
    _thread_key,
)


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _resolve_source_view(source_root: Path, source_id: str) -> JsonRecord | None:
    view = connector_view(source_root, source_id)
    if view is not None:
        return view
    if source_id.startswith("composio-"):
        return _composio_connector_view(source_root, source_id)
    return None


def _message_for_thread(record: JsonRecord) -> JsonRecord | None:
    # Thread drawer is the full-detail view — prefer `body` (untruncated)
    # over `text` (200-char snippet written by composio_inbound for the
    # inbox preview). Falls through to text/message/summary/title for
    # sources that don't split full vs preview.
    text = ""
    for key in ("body", "text", "message", "summary", "title"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            break
    sender = ""
    sender_payload = record.get("from") or record.get("sender") or {}
    if isinstance(sender_payload, dict):
        sender = str(sender_payload.get("name") or sender_payload.get("id") or "").strip()
    elif isinstance(sender_payload, str):
        sender = sender_payload.strip()
    direction = str(record.get("direction") or "").strip().lower() or None
    timestamp = _record_timestamp(record)
    if not text and not sender and not timestamp:
        return None
    return {
        "id": str(record.get("id") or record.get("source_record_id") or ""),
        "direction": direction or ("inbound" if sender else "outbound"),
        "sender": sender or None,
        "text": text,
        "timestamp": timestamp,
    }


def build_thread_context_response(
    source_id: str,
    thread_id: str,
    *,
    config: dict[str, Any] | None = None,
    limit: int = 200,
) -> JsonRecord:
    """Aggregate everything we know about a single thread for the drawer view.

    Pulls messages (filtered to this thread), the latest pending draft, prior
    sends from the queue, lead-scorer meta, and stub buckets for notes/activity
    so the UI can render placeholders until those endpoints land.
    """
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source = _resolve_source_view(source_root, source_id)
    if source is None:
        raise ValueError(f"Unknown source connector: {source_id}")

    safe_limit = max(20, min(int(limit or 200), 500))
    source_dir = _source_dir(source_root, source_id)

    # Frontend profiles emit threadIds as ``<source_id>:<thread_key>`` (see
    # ``_thread_from_record`` above). When the buyer-search drawer forwards
    # that string as the URL ``thread_id``, we end up looking for
    # ``crm:lofty-lead:1138...`` against contacts/conversations stored as
    # ``lofty-lead:1138...``. Strip the prefix defensively so both shapes
    # resolve.
    if thread_id.startswith(f"{source_id}:"):
        thread_id = thread_id[len(source_id) + 1 :]

    # Snapshot reader lock — keep messages/contacts/lead-events consistent
    # against any in-flight CRM sync (Codex audit P1, 2026-05-05).
    # 2026-05-26 fix: per-contact streaming for lead-events. Prior code did
    # `tail=True, limit=4000` which silently dropped activity/notes/tasks
    # for any contact whose events were ingested earlier than the last 4000
    # rows. With 2474 Lofty leads and 15455 lifetime events, every contact
    # past line ~11455 had an empty Property Activity panel.
    with _snapshot_reader_lock(source_dir):
        raw_messages = _read_jsonl_records(source_dir / "messages.jsonl", limit=2000, tail=True)
        # Targeted contact lookup: stream the whole file once and keep only
        # the row whose contact_id/id matches this thread. The prior
        # `_read_jsonl_records(limit=2000)` silently dropped any contact past
        # row 2000, breaking the Lead Score / Stage / Tags panel for hot
        # leads on CRMs with >2000 contacts (one Lofty workspace hit this at
        # 2474 contacts — every hot lead appended after row 2000 returned
        # `lead: null` in the drawer). Streaming a single-row pluck is O(n)
        # but unbounded by file size and uses constant memory.
        lead_record: JsonRecord | None = _find_jsonl_record_by_id(
            source_dir / "contacts.jsonl",
            thread_id,
            id_keys=("contact_id", "id", "source_record_id"),
        )
        lead_events_iter = _stream_jsonl_records_by_id(
            source_dir / "lead-events.jsonl",
            thread_id,
            id_keys=("contact_id", "conversation_id"),
        )

    messages: list[JsonRecord] = []
    person_name = ""
    for record in raw_messages:
        rec_thread = str(record.get("thread_id") or record.get("conversation_id") or "").strip()
        if rec_thread != thread_id:
            continue
        normalized = _message_for_thread(record)
        if normalized is None:
            continue
        if not person_name and normalized["direction"] == "inbound" and normalized.get("sender"):
            person_name = str(normalized["sender"])
        messages.append(normalized)
    messages.sort(key=lambda m: _parse_record_dt(m.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc))
    messages = messages[-safe_limit:]

    if lead_record is not None and not person_name:
        person_name = _record_person_name(lead_record)

    activity_records: list[JsonRecord] = []
    notes_records: list[JsonRecord] = []
    tasks_records: list[JsonRecord] = []
    for record in lead_events_iter:
        if str(record.get("contact_id") or record.get("conversation_id") or "").strip() != thread_id:
            continue
        event_type = str(record.get("type") or record.get("event_type") or "event").strip()
        timestamp = record.get("timestamp") or record.get("created_at") or record.get("last_seen_at")
        rec_id = str(record.get("source_record_id") or record.get("id") or "")
        if event_type in {"crm_note", "lofty_note"}:
            notes_records.append(
                {
                    "id": rec_id,
                    "title": record.get("title") or "Note",
                    "summary": record.get("summary") or record.get("text") or "",
                    "author": record.get("author"),
                    "timestamp": timestamp,
                }
            )
            continue
        if event_type in {"crm_task", "lofty_task"}:
            tasks_records.append(
                {
                    "id": rec_id,
                    "title": record.get("title") or "Task",
                    "summary": record.get("summary") or record.get("text") or "",
                    "status": record.get("status") or "open",
                    "dueAt": record.get("dueAt") or record.get("due_at"),
                    "timestamp": timestamp,
                }
            )
            continue
        activity_records.append(
            {
                "id": rec_id,
                "type": event_type,
                "subtype": record.get("subtype"),
                "title": record.get("title") or record.get("summary") or record.get("text"),
                "summary": record.get("summary") or record.get("text"),
                "address": record.get("address"),
                "timestamp": timestamp,
            }
        )

    def _by_ts_desc(rows: list[JsonRecord]) -> list[JsonRecord]:
        rows.sort(
            key=lambda a: _parse_record_dt(a.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc),
            reverse=True,
        )
        return rows

    activity_records = _by_ts_desc(activity_records)[:30]
    notes_records = _by_ts_desc(notes_records)[:30]
    tasks_records = _by_ts_desc(tasks_records)[:30]

    lead: JsonRecord | None = None
    if lead_record is not None:
        emails_raw = lead_record.get("emails") or lead_record.get("email")
        phones_raw = lead_record.get("phones") or lead_record.get("phone")
        if isinstance(emails_raw, (list, tuple)):
            emails = [str(e) for e in emails_raw if e]
        elif emails_raw:
            emails = [str(emails_raw)]
        else:
            emails = []
        if isinstance(phones_raw, (list, tuple)):
            phones = [str(p) for p in phones_raw if p]
        elif phones_raw:
            phones = [str(phones_raw)]
        else:
            phones = []
        tags_raw = lead_record.get("tags") or []
        if isinstance(tags_raw, (list, tuple)):
            tags_clean = [str(t) for t in tags_raw if t]
        else:
            tags_clean = [str(tags_raw)] if tags_raw else []
        score_val = lead_record.get("score")
        score_int: int | None
        try:
            score_int = int(score_val) if score_val is not None else None
        except (TypeError, ValueError):
            score_int = None
        lead = {
            "leadId": lead_record.get("lead_id") or lead_record.get("contact_id"),
            "displayName": lead_record.get("display_name") or person_name,
            "stage": lead_record.get("stage"),
            "leadSource": lead_record.get("lead_source") or lead_record.get("source"),
            "assignedUser": lead_record.get("assigned_user"),
            "score": score_int,
            "tags": tags_clean,
            "summary": lead_record.get("summary") or lead_record.get("text"),
            "emails": emails,
            "phones": phones,
            "channel": lead_record.get("channel"),
            "timestamp": lead_record.get("timestamp") or lead_record.get("last_seen_at"),
            "lastSeenAt": lead_record.get("last_seen_at"),
        }

    pending_draft: JsonRecord | None = None
    ui_state = _read_source_ui_state(source_dir)
    task_states = _as_dict(ui_state.get("tasks"))
    for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=200):
        if not _is_message_draft_task(record):
            continue
        if _thread_key(record) != thread_id:
            continue
        task_id = _task_key(record)
        state = _as_dict(task_states.get(task_id))
        status = str(state.get("status") or record.get("status") or "pending").lower()
        if status in {"approved", "done", "archived", "cancelled", "skipped"}:
            continue
        pending_draft = _draft_from_task(source, record, state)
        break

    sends: list[JsonRecord] = []
    meta: JsonRecord | None = None
    try:
        from elevate_cli import outreach_db as _odb
        sends = _odb.list_sends_by_thread(source_id, thread_id, limit=50)
        meta = _odb.get_thread_meta(source_id, thread_id)
    except Exception:
        sends = []
        meta = None

    last_inbound = next((m for m in reversed(messages) if m.get("direction") == "inbound"), None)
    last_outbound = next((m for m in reversed(messages) if m.get("direction") == "outbound"), None)

    return {
        "sourceId": source_id,
        "threadId": thread_id,
        "source": {
            "id": source.get("id"),
            "label": source.get("label"),
            "category": source.get("category"),
            "ownerAgent": source.get("ownerAgent"),
            "connected": source.get("connected"),
        },
        "personName": person_name or "Client",
        "messageCount": len(messages),
        "messages": messages,
        "lastInboundAt": (last_inbound or {}).get("timestamp"),
        "lastOutboundAt": (last_outbound or {}).get("timestamp"),
        "pendingDraft": pending_draft,
        "sends": sends,
        "meta": meta,
        "lead": lead,
        "notes": notes_records,
        "tasks": tasks_records,
        "activity": activity_records,
    }
