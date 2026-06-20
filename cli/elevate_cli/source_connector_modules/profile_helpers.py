"""Profile grouping helpers for source inbox records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _as_dict(value: Any) -> dict[str, Any]:
    return _source_connectors()._as_dict(value)


def _safe_int(value: Any, default: int = 0) -> int:
    return _source_connectors()._safe_int(value, default)


def _parse_record_dt(value: Any):
    return _source_connectors()._parse_record_dt(value)


def _source_record_counts(source: JsonRecord) -> dict[str, int]:
    counts = source.get("recordCounts")
    return counts if isinstance(counts, dict) else {}


def _source_has_inbox_records(source: JsonRecord) -> bool:
    counts = _source_record_counts(source)
    return any(int(counts.get(key) or 0) > 0 for key in ("messages", "conversations", "contacts"))


def _string_values(value: Any) -> list[str]:
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_string_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for key in ("value", "phone", "email", "number", "address", "name", "label", "id"):
            if key in value:
                values.extend(_string_values(value.get(key)))
        return values
    text = str(value or "").strip()
    return [text] if text else []


def _phone_key(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 7:
        return None
    return f"phone:{digits[-10:] if len(digits) >= 10 else digits}"


def _email_key(value: str) -> str | None:
    text = value.strip().lower()
    if "@" not in text or "." not in text.split("@")[-1]:
        return None
    return f"email:{text}"


def _name_key(value: str) -> str | None:
    normalized = " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
    if len(normalized) < 4 or normalized in {"client conversation", "lofty lead", "apple messages conversation"}:
        return None
    return f"name:{normalized}"


def _profile_verifiers(record: JsonRecord) -> list[JsonRecord]:
    verifiers: list[JsonRecord] = []

    def add(kind: str, value: str, key: str | None) -> None:
        if key:
            verifiers.append({"kind": kind, "value": value, "key": key})

    for field in ("phones", "phone", "handle", "chat_identifier", "participant_handles"):
        for value in _string_values(record.get(field)):
            phone_key = _phone_key(value)
            if phone_key:
                add("phone", value, phone_key)
                continue
            add("email", value, _email_key(value))
    for field in ("emails", "email"):
        for value in _string_values(record.get(field)):
            add("email", value, _email_key(value))

    by_key: dict[str, JsonRecord] = {}
    for verifier in verifiers:
        key = str(verifier.get("key") or "")
        if key and key not in by_key:
            by_key[key] = verifier
    return sorted(by_key.values(), key=lambda item: (str(item.get("kind") or ""), str(item.get("value") or "")))


def _profile_match_keys(record: JsonRecord, thread: JsonRecord) -> list[str]:
    return [str(item["key"]) for item in _profile_verifiers(record) if item.get("key")]


def _merge_profile_verifiers(existing: Any, incoming: list[JsonRecord]) -> list[JsonRecord]:
    by_key: dict[str, JsonRecord] = {}
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, str):
                # Older cached profile data may have stored verifier keys as strings.
                key = item.strip()
                if key:
                    kind = key.split(":", 1)[0] if ":" in key else "unknown"
                    by_key[key] = {"kind": kind, "value": key.split(":", 1)[-1], "key": key}
                continue
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            value = str(item.get("value") or "").strip()
            kind = str(item.get("kind") or "").strip()
            if key and value and kind:
                by_key[key] = {"kind": kind, "value": value, "key": key}
    elif isinstance(existing, str):
        key = existing.strip()
        if key:
            kind = key.split(":", 1)[0] if ":" in key else "unknown"
            by_key[key] = {"kind": kind, "value": key.split(":", 1)[-1], "key": key}
    for item in incoming:
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if key and value and kind:
            by_key[key] = {"kind": kind, "value": value, "key": key}
    return sorted(by_key.values(), key=lambda item: (str(item.get("kind") or ""), str(item.get("value") or "")))


def _profile_contact_values(record: JsonRecord) -> tuple[list[str], list[str]]:
    phones: list[str] = []
    emails: list[str] = []
    for field in ("phones", "phone", "handle", "chat_identifier", "participant_handles"):
        for value in _string_values(record.get(field)):
            if _phone_key(value):
                phones.append(value)
            elif _email_key(value):
                emails.append(value)
    for field in ("emails", "email"):
        for value in _string_values(record.get(field)):
            if _email_key(value):
                emails.append(value)
    return sorted(set(phones)), sorted(set(emails))


SOCIAL_SOURCE_IDS = {"social", "instagram", "facebook", "facebook-messenger", "meta", "tiktok", "linkedin"}
SOCIAL_INTENT_WORDS = (
    "buy",
    "buyer",
    "sell",
    "seller",
    "home",
    "house",
    "condo",
    "listing",
    "showing",
    "mortgage",
    "preapproved",
    "pre-approved",
    "relocate",
    "moving",
    "price",
    "valuation",
    "cma",
    "realtor",
    "agent",
)


def _is_social_intent(source: JsonRecord, thread: JsonRecord) -> bool:
    haystack = " ".join(
        str(value or "").lower()
        for value in (
            source.get("id"),
            source.get("label"),
            thread.get("channel"),
            thread.get("latestText"),
        )
    )
    is_social = any(source_id in haystack for source_id in SOCIAL_SOURCE_IDS)
    return is_social and any(word in haystack for word in SOCIAL_INTENT_WORDS)


def _profile_label(score: int) -> str:
    if score >= 76:
        return "hot"
    if score >= 54:
        return "warm"
    if score >= 35:
        return "watch"
    return "normal"


def _merge_profile(profile: JsonRecord, source: JsonRecord, thread: JsonRecord) -> None:
    record = _as_dict(thread.get("record"))
    phones, emails = _profile_contact_values(record)
    verifiers = _profile_verifiers(record)
    contact_id = str(thread.get("contactId") or record.get("contact_id") or "").strip()
    conversation_id = str(
        thread.get("conversationId")
        or record.get("conversation_id")
        or record.get("source_record_id")
        or ""
    ).strip()
    profile["sources"] = sorted({*profile.get("sources", []), str(thread.get("sourceLabel") or source.get("label") or "")})
    profile["sourceIds"] = sorted({*profile.get("sourceIds", []), str(thread.get("sourceId") or source.get("id") or "")})
    profile["channels"] = sorted({*profile.get("channels", []), str(thread.get("channel") or "")})
    if contact_id:
        profile["contactIds"] = sorted({*profile.get("contactIds", []), contact_id})
    if conversation_id:
        profile["conversationIds"] = sorted({*profile.get("conversationIds", []), conversation_id})
    profile["phones"] = sorted({*profile.get("phones", []), *phones})
    profile["emails"] = sorted({*profile.get("emails", []), *emails})
    profile["verifiers"] = _merge_profile_verifiers(profile.get("verifiers"), verifiers)
    profile["threadIds"] = sorted({*profile.get("threadIds", []), str(thread.get("id") or "")})
    profile["threadCount"] = len(profile["threadIds"])
    profile["hasConversation"] = True
    source_id = str(thread.get("sourceId") or source.get("id") or "")
    if source_id == "crm" or "crm" in str(thread.get("sourceLabel") or "").lower():
        profile["hasCrm"] = True
        profile["crmStage"] = record.get("stage") or profile.get("crmStage")
        profile["leadSource"] = record.get("lead_source") or record.get("source") or profile.get("leadSource")
    if _is_social_intent(source, thread):
        profile["isPotentialLead"] = True
    score = max(_safe_int(profile.get("heatScore")), _safe_int(thread.get("heatScore")))
    profile["heatScore"] = score
    profile["heatLabel"] = _profile_label(score)
    latest = _parse_record_dt(thread.get("latestAt"))
    current_latest = _parse_record_dt(profile.get("latestAt"))
    if latest and (not current_latest or latest >= current_latest):
        profile["latestAt"] = thread.get("latestAt")
        profile["latestText"] = thread.get("latestText")
    if not profile.get("displayName") or str(profile.get("displayName")) == "Client conversation":
        profile["displayName"] = thread.get("personName") or profile.get("displayName")
    tags = _string_values(record.get("tags"))
    profile["tags"] = sorted({*profile.get("tags", []), *tags})[:12]


def _profiles_from_threads(threads: list[JsonRecord], source_by_id: dict[str, JsonRecord]) -> list[JsonRecord]:
    profiles: dict[str, JsonRecord] = {}
    key_to_profile: dict[str, str] = {}
    for thread in threads:
        source = source_by_id.get(str(thread.get("sourceId") or ""), {})
        record = _as_dict(thread.get("record"))
        keys = _profile_match_keys(record, thread)
        profile_id = next((key_to_profile[key] for key in keys if key in key_to_profile), "")
        if not profile_id:
            profile_id = keys[0] if keys else f"thread:{thread.get('id')}"
        profile = profiles.setdefault(
            profile_id,
            {
                "id": profile_id,
                "displayName": thread.get("personName") or "Client conversation",
                "sources": [],
                "sourceIds": [],
                "channels": [],
                "contactIds": [],
                "conversationIds": [],
                "verifiers": [],
                "phones": [],
                "emails": [],
                "threadIds": [],
                "threadCount": 0,
                "latestText": thread.get("latestText"),
                "latestAt": thread.get("latestAt"),
                "heatScore": thread.get("heatScore") or 0,
                "heatLabel": thread.get("heatLabel") or "normal",
                "hasCrm": False,
                "hasConversation": False,
                "isPotentialLead": False,
                "crmStage": None,
                "leadSource": None,
                "tags": [],
            },
        )
        for key in keys:
            key_to_profile[key] = profile_id
        _merge_profile(profile, source, thread)
    return sorted(
        profiles.values(),
        key=lambda item: (
            1 if item.get("hasCrm") else 0,
            _safe_int(item.get("heatScore")),
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
