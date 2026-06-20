"""Draft queue helper functions for source inbox records."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from elevate_cli.source_connector_modules.profile_helpers import SOCIAL_SOURCE_IDS


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _as_dict(value: Any) -> dict[str, Any]:
    return _source_connectors()._as_dict(value)


def _safe_int(value: Any, default: int = 0) -> int:
    return _source_connectors()._safe_int(value, default)


def _tag_text(value: Any) -> str:
    return _source_connectors()._tag_text(value)


def _record_person_name(record: JsonRecord) -> str:
    return _source_connectors()._record_person_name(record)


def _channel_for_source(source_id: str) -> str | None:
    return _source_connectors()._channel_for_source(source_id)


def _latest_text(record: JsonRecord) -> str:
    return _source_connectors()._latest_text(record)


def _thread_key(record: JsonRecord) -> str:
    return _source_connectors()._thread_key(record)


def _channel_label(source_id: str, source: JsonRecord, record: JsonRecord) -> str:
    return _source_connectors()._channel_label(source_id, source, record)


def _record_timestamp(record: JsonRecord) -> str:
    return _source_connectors()._record_timestamp(record)


def _list_record_snapshot(record: JsonRecord) -> JsonRecord:
    return _source_connectors()._list_record_snapshot(record)


def _task_key(record: JsonRecord) -> str:
    for key in ("task_id", "source_record_id", "id", "conversation_id", "contact_id", "title"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return hashlib.sha1(json.dumps(record, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _draft_text_for_task(record: JsonRecord) -> str:
    for key in ("draft_text", "draft", "message", "proposed_text", "reply_text", "text"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return str(record.get("summary") or "").strip()


def _is_message_draft_task(record: JsonRecord) -> bool:
    haystack = " ".join(
        _tag_text(record.get(key))
        for key in ("task_type", "title", "summary", "tags", "channel", "target_ui_surfaces")
    )
    if "connector_setup" in haystack:
        return False
    # Synthetic CRM lead-arrival records (Lofty sync emits one per lead with
    # task_type=lead_follow_up + approval_required=False). These belong in
    # Hot Leads / contact records, not "Approve replies". 2026-05-25.
    task_type = str(record.get("task_type") or "").strip().lower()
    if task_type == "lead_follow_up":
        return False
    # Explicit opt-out wins over keyword sniffing.
    if record.get("approval_required") is False:
        return False
    if record.get("approval_required") is True:
        return True
    return any(
        token in haystack
        for token in (
            "message_draft",
            "draft reply",
            "reply draft",
            "follow_up",
            "follow-up",
            "text message",
            "dm reply",
            "comment reply",
            "outreach",
        )
    )


def _draft_recipient(record: JsonRecord, fallback: str = "Client") -> str:
    return _record_person_name(record) or fallback


_TEMPLATE_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _first_name_from_person(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"client", "conversation", "client conversation"}:
        return "there"
    first = re.split(r"\s+", text, maxsplit=1)[0].strip(" ,")
    return first or "there"


def _record_field(record: JsonRecord, *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for child in ("name", "label", "value", "area", "city"):
                        text = str(item.get(child) or "").strip()
                        if text:
                            return text
                else:
                    text = str(item or "").strip()
                    if text:
                        return text
            continue
        if isinstance(value, dict):
            for child in ("name", "label", "value", "area", "city"):
                text = str(value.get(child) or "").strip()
                if text:
                    return text
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _outreach_lane_for_thread(thread: JsonRecord) -> str:
    label = str(thread.get("leadLabel") or thread.get("heatLabel") or "").strip().lower()
    if label == "hot":
        return "hot-leads-watcher"
    if _safe_int(thread.get("outboundCount")) > 0:
        return "follow-ups"
    return "new-outreach"


def _template_channel_for_thread(source_id: str, thread: JsonRecord) -> str:
    outbound = _channel_for_source(source_id)
    if outbound:
        return outbound
    raw = str(thread.get("channel") or "").strip().lower()
    if "email" in raw or "gmail" in raw:
        return "email"
    if "message" in raw or "sms" in raw or "text" in raw:
        return "sms"
    if "instagram" in raw or "facebook" in raw or "messenger" in raw or "social" in raw:
        return "social_dm"
    return "any"


def _template_values_for_thread(source: JsonRecord, thread: JsonRecord) -> dict[str, str]:
    record = _as_dict(thread.get("record"))
    latest = str(thread.get("latestText") or _latest_text(record) or "").strip()
    area = _record_field(
        record,
        "area",
        "areas",
        "neighborhood",
        "neighbourhood",
        "city",
        "market",
        "location",
    )
    topic = _record_field(record, "topic", "intent", "title", "summary") or "your search"
    source_label = str(thread.get("sourceLabel") or source.get("label") or source.get("source") or "your message").strip()
    signal = str(thread.get("scoreReason") or "").strip()
    if not signal:
        label = str(thread.get("leadLabel") or thread.get("heatLabel") or "").strip()
        signal = f"{label} signal" if label else "recent activity"
    return {
        "first_name": _first_name_from_person(thread.get("personName")),
        "city": _record_field(record, "city", "market", "area", "location") or "the area",
        "topic": topic,
        "source": source_label,
        "area": area or "the area",
        "signal": signal,
        "address": _record_field(record, "address", "property_address", "listing_address") or "the listing",
        "criteria": _record_field(record, "criteria", "saved_search", "search_criteria", "summary") or "your search",
        "delta": _record_field(record, "delta", "market_delta") or "a bit",
        "latest_message": latest,
    }


def _render_outreach_template(body: str, source: JsonRecord, thread: JsonRecord) -> str:
    values = _template_values_for_thread(source, thread)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key) or "that"

    rendered = _TEMPLATE_TOKEN_RE.sub(repl, body or "").strip()
    rendered = re.sub(r"[ \t]{2,}", " ", rendered)
    rendered = re.sub(r"\s+([,.?!])", r"\1", rendered)
    return rendered


def _select_thread_template(source: JsonRecord, thread: JsonRecord) -> JsonRecord | None:
    try:
        from elevate_cli import outreach_db
    except Exception:
        return None

    lane = _outreach_lane_for_thread(thread)
    source_id = str(thread.get("sourceId") or source.get("id") or "")
    channel = _template_channel_for_thread(source_id, thread)
    try:
        templates = outreach_db.list_templates(lane=lane, include_inactive=False)
    except Exception:
        return None

    candidates: list[tuple[int, JsonRecord]] = []
    for idx, template in enumerate(templates):
        if not template.get("active"):
            continue
        if str(template.get("status") or "active") != "active":
            continue
        template_channel = str(template.get("channel") or "any").strip() or "any"
        if template_channel not in {"any", channel}:
            continue
        candidates.append((idx, template))
    if not candidates:
        return None

    def sort_key(item: tuple[int, JsonRecord]) -> tuple[int, float, float, int, int]:
        idx, template = item
        uses = _safe_int(template.get("uses"))
        reply_rate = float(template.get("replyRate") or 0.0)
        win_rate = float(template.get("winRate") or 0.0)
        return (0 if uses == 0 else 1, -reply_rate, -win_rate, uses, idx)

    _, selected = sorted(candidates, key=sort_key)[0]
    selected = dict(selected)
    selected["_outreachLane"] = lane
    selected["_outreachChannel"] = channel
    return selected


def _templated_draft_for_thread(source: JsonRecord, thread: JsonRecord) -> JsonRecord | None:
    template = _select_thread_template(source, thread)
    if not template:
        return None
    rendered = _render_outreach_template(str(template.get("body") or ""), source, thread)
    if not rendered:
        return None
    return {
        "draftText": rendered,
        "templateId": template.get("id"),
        "templateName": template.get("name"),
        "templateChannel": template.get("channel") or "any",
        "outreachLane": template.get("_outreachLane") or _outreach_lane_for_thread(thread),
    }


def _fallback_draft_for_thread(thread: JsonRecord) -> str:
    name = str(thread.get("personName") or "there").strip()
    first = name.split()[0] if name and name.lower() not in {"client", "conversation"} else "there"
    source = str(thread.get("sourceLabel") or thread.get("channel") or "your message").strip()
    if str(thread.get("sourceId") or "").lower() in SOCIAL_SOURCE_IDS or "instagram" in source.lower() or "facebook" in source.lower():
        return (
            f"Hi {first}, thanks for reaching out. Are you looking for more details on a specific property, "
            "or are you starting to explore buying or selling?"
        )
    if str(thread.get("sourceId") or "").lower() == "crm":
        return f"Hi {first}, just checking in. Are you still looking for help with your next real estate step?"
    return f"Hi {first}, thanks for the message. What would be the most helpful next step for you right now?"


def _draft_from_task(source: JsonRecord, record: JsonRecord, state: JsonRecord | None = None) -> JsonRecord:
    state = state or {}
    source_id = str(source.get("id") or record.get("source_id") or "").strip()
    task_id = _task_key(record)
    draft_text = str(state.get("draft_text") or _draft_text_for_task(record)).strip()
    return {
        "id": f"{source_id}:{task_id}",
        "sourceId": source_id,
        "sourceLabel": str(source.get("label") or source_id),
        "taskId": task_id,
        "threadId": _thread_key(record),
        "contactId": record.get("contact_id"),
        "conversationId": record.get("conversation_id") or record.get("source_record_id"),
        "personName": _draft_recipient(record),
        "channel": _channel_label(source_id, source, record),
        "title": str(record.get("title") or "Review draft follow-up").strip(),
        "draftText": draft_text or "Draft text has not been generated yet.",
        "context": str(record.get("summary") or record.get("latest_text") or record.get("text") or "").strip(),
        "latestAt": _record_timestamp(record),
        "status": str(state.get("status") or record.get("status") or "pending"),
        "approvalRequired": bool(record.get("approval_required", True)),
        "generated": False,
        "fallback": False,
        "record": _list_record_snapshot(record),
    }


def _draft_from_thread(source: JsonRecord, thread: JsonRecord) -> JsonRecord:
    source_id = str(thread.get("sourceId") or source.get("id") or "").strip()
    thread_id = str(thread.get("threadId") or _thread_key(_as_dict(thread.get("record"))))
    template_draft = _templated_draft_for_thread(source, thread)
    record = dict(_as_dict(thread.get("record")))
    if template_draft:
        record.update({
            "template_id": template_draft.get("templateId"),
            "template_name": template_draft.get("templateName"),
            "template_channel": template_draft.get("templateChannel"),
            "outreach_lane": template_draft.get("outreachLane"),
        })
    return {
        "id": f"{source_id}:thread-draft:{thread_id}",
        "sourceId": source_id,
        "sourceLabel": str(thread.get("sourceLabel") or source.get("label") or source_id),
        "taskId": f"thread-draft:{thread_id}",
        "threadId": thread_id,
        "contactId": thread.get("contactId"),
        "conversationId": thread.get("conversationId"),
        "personName": str(thread.get("personName") or "Client"),
        "channel": str(thread.get("channel") or _channel_label(source_id, source, _as_dict(thread.get("record")))),
        "title": "Draft follow-up",
        "draftText": str((template_draft or {}).get("draftText") or _fallback_draft_for_thread(thread)),
        "context": str(thread.get("latestText") or "").strip(),
        "latestAt": str(thread.get("latestAt") or ""),
        "status": "pending",
        "approvalRequired": True,
        "generated": True,
        "fallback": template_draft is None,
        "templateId": (template_draft or {}).get("templateId"),
        "templateName": (template_draft or {}).get("templateName"),
        "outreachLane": (template_draft or {}).get("outreachLane"),
        "record": record,
    }
