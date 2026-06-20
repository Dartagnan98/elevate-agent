"""Compact source record snapshots for list views."""

from __future__ import annotations

from typing import Any


JsonRecord = dict[str, Any]


_LIST_RECORD_FIELDS = {
    "id",
    "source_id",
    "source_record_id",
    "conversation_id",
    "contact_id",
    "display_name",
    "person_key",
    "direction",
    "timestamp",
    "latest_at",
    "created_at",
    "updated_at",
    "day",
    "channel",
    "service",
    "handle",
    "chat_identifier",
    "participant_handles",
    "phone",
    "phones",
    "email",
    "emails",
    "stage",
    "status",
    "priority",
    "tags",
    "lead_source",
    "source",
    "title",
    "summary",
    "latest_text",
    "text",
    "message_count",
    "total_messages",
    "inbound_count",
    "outbound_count",
    "confidence",
}


def _compact_list_text(value: Any, *, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _list_record_snapshot(record: JsonRecord) -> JsonRecord:
    """Small source-record shape for inbox lists.

    Raw connector rows can contain large provider payloads, MIME bodies, or
    attachment metadata. Board/list views only need identity, matching, and
    preview fields; full context stays available through the thread endpoint.
    """

    snapshot: JsonRecord = {}
    for key in _LIST_RECORD_FIELDS:
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        if key in {"summary", "latest_text", "text", "title"}:
            compact = _compact_list_text(value)
            if compact:
                snapshot[key] = compact
            continue
        if isinstance(value, (str, int, float, bool)):
            snapshot[key] = value
        elif isinstance(value, list):
            snapshot[key] = [
                _compact_list_text(item, limit=160) if isinstance(item, str) else item
                for item in value[:20]
                if item is not None
            ]
        elif isinstance(value, dict):
            # Preserve simple provider metadata but never nested raw bodies.
            snapshot[key] = {
                str(k): _compact_list_text(v, limit=160) if isinstance(v, str) else v
                for k, v in list(value.items())[:20]
                if isinstance(v, (str, int, float, bool)) or v is None
            }
    return snapshot
