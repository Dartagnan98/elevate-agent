"""CRM and Lofty helper functions for source connectors."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _lofty_lead_name(lead: JsonRecord) -> str:
    full = str(lead.get("name") or lead.get("fullName") or lead.get("leadName") or "").strip()
    if full:
        return full
    first = str(lead.get("firstName") or "").strip()
    last = str(lead.get("lastName") or "").strip()
    return " ".join(part for part in (first, last) if part).strip() or "Lofty lead"


def _lofty_timestamp(lead: JsonRecord) -> str:
    for key in ("updatedAt", "lastActivityTime", "lastModified", "createdAt", "created", "updated"):
        parsed = _source_connectors()._parse_record_dt(lead.get(key))
        if parsed:
            return parsed.isoformat()
    return _source_connectors()._now()


def _list_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _tag_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        if isinstance(item, dict):
            raw = item.get("name") or item.get("tagName") or item.get("label") or item.get("value")
        else:
            raw = item
        text = str(raw or "").strip()
        if text:
            tags.append(text)
    return tags


def _extract_lead_records(payload: Any) -> list[JsonRecord]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("workingLeads", "leads", "people", "contacts", "data", "items", "results", "records", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _basic_auth_header(api_key: str) -> str:
    encoded = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _build_crm_auth(crm: JsonRecord, api_key: str) -> tuple[dict[str, str], str | None]:
    """Return (headers, query_param_override). headers always include Accept/Content-Type."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth_type = str(crm.get("auth_type") or "header").lower()
    if auth_type == "query":
        return headers, str(crm.get("auth_query_param") or "api_key")
    if auth_type == "basic":
        headers["Authorization"] = _basic_auth_header(api_key)
        return headers, None
    header_name = str(crm.get("auth_header") or "Authorization")
    prefix = str(crm.get("auth_prefix") or "")
    headers[header_name] = f"{prefix}{api_key}"
    return headers, None


def _generic_crm_get(
    crm: JsonRecord,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    base = str(crm.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("CRM base URL is not set")
    headers, query_param = _build_crm_auth(crm, api_key)
    url = f"{base}/{path.lstrip('/')}"
    merged_params = dict(params or {})
    if query_param:
        merged_params[query_param] = api_key
    if merged_params:
        query = urllib.parse.urlencode(
            {key: value for key, value in merged_params.items() if value is not None}
        )
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _generic_crm_write(
    crm: JsonRecord,
    api_key: str,
    path: str,
    body: JsonRecord,
    method: str = "POST",
) -> Any:
    base = str(crm.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("CRM base URL is not set")
    headers, query_param = _build_crm_auth(crm, api_key)
    url = f"{base}/{path.lstrip('/')}"
    if query_param:
        url = f"{url}?{urllib.parse.urlencode({query_param: api_key})}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _provider_label(provider: str) -> str:
    return {
        "followupboss": "Follow Up Boss",
        "sierra": "Sierra Interactive",
        "boldtrail": "BoldTrail",
        "brivity": "Brivity",
    }.get(provider.lower(), provider.title() if provider else "CRM")


def _lofty_headers(env_values: dict[str, str]) -> tuple[dict[str, str], str]:
    access_token = str(env_values.get("LOFTY_ACCESS_TOKEN") or "").strip()
    api_key = str(env_values.get("LOFTY_API_KEY") or "").strip()
    if access_token:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }, "oauth_access_token"
    if api_key:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"token {api_key}",
        }, "api_key"
    return {"Accept": "application/json", "Content-Type": "application/json"}, "missing"


def _lofty_get(
    path: str,
    env_values: dict[str, str],
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 18,
) -> Any:
    headers, _auth_type = _lofty_headers(env_values)
    if headers.get("Authorization") is None:
        raise RuntimeError("LOFTY_API_KEY or LOFTY_ACCESS_TOKEN is not set")
    base = "https://api.lofty.com"
    url = f"{base}/{path.lstrip('/')}"
    if params:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


_LOFTY_LIST_KEYS = (
    "data",
    "records",
    "items",
    "results",
    "activities",
    "notes",
    "tasks",
    "taskList",  # Lofty's actual wrapper for /v1.0/tasks
)


def _lofty_extract_list(payload: Any) -> list[JsonRecord]:
    """Lofty wraps lists under inconsistent keys (``data``, ``records``,
    ``items``, ``activities``, ``notes``, ``taskList``). Walk one level
    deep looking for a list of dicts and return it; otherwise [] so the
    caller can keep going."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in _LOFTY_LIST_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            cleaned = [item for item in candidate if isinstance(item, dict)]
            if cleaned:
                return cleaned
    inner = payload.get("data")
    if isinstance(inner, dict):
        for key in _LOFTY_LIST_KEYS:
            candidate = inner.get(key)
            if isinstance(candidate, list):
                cleaned = [item for item in candidate if isinstance(item, dict)]
                if cleaned:
                    return cleaned
    return []


def _lofty_get_first_ok(
    paths: tuple[str, ...],
    env_values: dict[str, str],
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 18,
) -> list[JsonRecord]:
    """Try each path in order; return the first response that yields a
    non-empty list of records. 404/403/timeout on one path falls through
    to the next instead of raising — Lofty's docs and reality diverge per
    workspace.

    Distinguishes "all paths returned an empty 200" (returns []) from
    "every path errored" (raises the last exception so callers can count
    real failures vs clean empties).
    """
    last_error: Exception | None = None
    saw_ok = False
    for path in paths:
        try:
            payload = _source_connectors()._lofty_get(path, env_values, params, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # 404 is a clean "this endpoint shape isn't supported on this
            # tenant" — fall through silently. Other HTTP errors track as
            # real failures so callers can count them.
            if exc.code == 404:
                saw_ok = True
                continue
            last_error = exc
            continue
        except Exception as exc:  # noqa: BLE001 — defensive cross-endpoint probe
            last_error = exc
            continue
        saw_ok = True
        records = _lofty_extract_list(payload)
        if records:
            return records
    if not saw_ok and last_error is not None:
        # Every probe errored — surface so caller can count it as a real
        # enrichment failure (Lofty 500/auth/timeout), not a clean empty lead.
        raise last_error
    return []


def _lofty_get_activities(
    lead_id: str, env_values: dict[str, str], *, limit: int = 50, timeout: int = 18,
) -> list[JsonRecord]:
    """Pull the lead's activity feed (page views, saved-search hits,
    tour requests, email opens). Tries v2.0 then v1.0 — endpoint shape
    varies across Lofty/Chime tenant migrations."""
    if not lead_id:
        return []
    params = {"limit": min(int(limit or 50), 100), "offset": 0}
    return _source_connectors()._lofty_get_first_ok(
        (
            f"v2.0/leads/{lead_id}/activities",
            f"v1.0/leads/{lead_id}/activities",
            f"v1.0/leads/{lead_id}/activity",
        ),
        env_values,
        params,
        timeout=timeout,
    )


def _lofty_get_notes(
    lead_id: str, env_values: dict[str, str], *, limit: int = 50, timeout: int = 18,
) -> list[JsonRecord]:
    """Pull the lead's free-form notes (the ones agents type into Lofty).

    Real Lofty shape: ``GET /v1.0/notes?leadId=<id>`` → ``{notes: [...]}``.
    The ``/v1.0/leads/{id}/notes`` path is POST-only — GET 404s. Try the
    real query-param shape first, then fall back in case a workspace runs
    a different version."""
    if not lead_id:
        return []
    return _source_connectors()._lofty_get_first_ok(
        (
            f"v1.0/notes?leadId={urllib.parse.quote(lead_id)}",
            f"v2.0/notes?leadId={urllib.parse.quote(lead_id)}",
            f"v1.0/leads/{lead_id}/notes",
        ),
        env_values,
        None,
        timeout=timeout,
    )


def _lofty_get_tasks(
    lead_id: str, env_values: dict[str, str], *, limit: int = 50, timeout: int = 18,
) -> list[JsonRecord]:
    """Pull the lead's tasks/follow-ups assigned in Lofty.

    Real Lofty shape: ``GET /v1.0/tasks?leadId=<id>`` → ``{taskList: [...]}``."""
    if not lead_id:
        return []
    return _source_connectors()._lofty_get_first_ok(
        (
            f"v1.0/tasks?leadId={urllib.parse.quote(lead_id)}",
            f"v2.0/tasks?leadId={urllib.parse.quote(lead_id)}",
            f"v1.0/leads/{lead_id}/tasks",
        ),
        env_values,
        None,
        timeout=timeout,
    )


def _lofty_epoch_ms_to_iso(value: Any) -> str | None:
    """Lofty hands timestamps in three shapes: ms-epoch int (1775072765444),
    ISO with ``GMT`` suffix (``2026-05-06T03:41:02GMT``), or already-clean
    ISO. Normalize to ISO-8601 with explicit ``+00:00`` so downstream sort
    keys are comparable. Returns ``None`` if the value can't be parsed."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            # Lofty's "created" field is ms since epoch.
            seconds = float(value) / 1000.0 if value > 1e11 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # ``2026-05-06T03:41:02GMT`` → strip ``GMT``, add ``+00:00``.
        if text.endswith("GMT"):
            text = text[:-3] + "+00:00"
        return text
    return None


def _lofty_listing_address(listing: Any) -> str | None:
    """Lofty's activity records embed the property under ``listing`` —
    pull a human-readable address from streetAddress + city + state."""
    if not isinstance(listing, dict):
        return None
    parts: list[str] = []
    street = str(listing.get("streetAddress") or "").strip()
    if street:
        parts.append(street)
    city = str(listing.get("city") or "").strip()
    state = str(listing.get("state") or "").strip()
    if city:
        parts.append(city)
    if state:
        parts.append(state)
    return ", ".join(parts) if parts else None


def _stable_hash_id(*parts: Any) -> str:
    """Build a deterministic 12-char id from normalized payload fields.

    Used as a fallback when Lofty hands us a record without an id —
    array index would be unstable across syncs (a deleted earlier row
    would shift all later ids). Hash makes the id stable to the record
    content."""
    payload = "|".join(str(p) if p is not None else "" for p in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _lofty_normalize_activity(record: JsonRecord, lead_id: str) -> JsonRecord:
    """Reduce a Lofty activity record to a stable shape for the event log.

    Two real shapes are seen in the wild:

    * Communication shape (``/v1.0/leads/{id}/activities``):
      ``{id, leadId, agentId, activityTime, channel, communicationType,
         direction, callingOutcome, leadPhoneNumber, emailEventType,
         emailSubject, note}`` — channel is ``Text``/``Email``/``Call``,
      direction ``Outbound``/``Inbound``, communicationType ``Auto``/``Manual``.
    * Browse shape (older endpoint): ``{type, text, link, picture, listing,
      created}`` where ``type`` is ``Browse``/``Search``/etc.

    The normalizer picks whichever fields are present and builds a
    human-readable title and timestamp."""
    raw_id = (
        record.get("id")
        or record.get("activityId")
        or record.get("eventId")
        or record.get("uuid")
        or ""
    )

    # Address first — useful for both title and summary.
    address = record.get("propertyAddress") or record.get("address")
    if not address:
        listing = record.get("listing")
        if isinstance(listing, dict):
            address = _lofty_listing_address(listing)
    if not address:
        prop = record.get("property")
        if isinstance(prop, dict):
            address = prop.get("address") or prop.get("formattedAddress") or _lofty_listing_address(prop)

    channel = str(record.get("channel") or "").strip()
    direction = str(record.get("direction") or "").strip()
    comm_type = str(record.get("communicationType") or "").strip()
    email_subject = str(record.get("emailSubject") or "").strip()
    calling_outcome = str(record.get("callingOutcome") or "").strip()
    email_event = str(record.get("emailEventType") or "").strip()
    note_text = str(record.get("note") or "").strip()

    activity_type = str(
        record.get("type")
        or record.get("eventType")
        or record.get("category")
        or record.get("action")
        or ""
    ).strip()
    # Communication shape has no `type`; synthesise a subtype from channel.
    if not activity_type and channel:
        activity_type = channel.lower()
    if not activity_type:
        activity_type = "activity"

    # Title prefers a human-readable description if Lofty gave us one.
    explicit_text = str(
        record.get("title")
        or record.get("description")
        or record.get("summary")
        or record.get("text")
        or ""
    ).strip()
    if explicit_text:
        title = explicit_text
    elif channel:
        # "Auto Text Outbound", "Manual Email Inbound: Subject", "Call Outbound — connected"
        bits: list[str] = []
        if comm_type and comm_type.lower() != "manual":
            bits.append(comm_type)
        bits.append(channel)
        if direction:
            bits.append(direction)
        title = " ".join(bits).strip()
        if email_subject:
            title = f"{title}: {email_subject}".strip(": ")
        elif calling_outcome:
            title = f"{title} — {calling_outcome}".strip(" —")
        elif email_event and channel.lower() == "email":
            title = f"{title} ({email_event})".strip()
    elif isinstance(address, str) and address:
        verb = {"Browse": "Browsed", "Search": "Searched"}.get(
            activity_type, activity_type.replace("_", " ").title()
        )
        title = f"{verb} {address}".strip()
    else:
        title = activity_type.replace("_", " ").title() or "Activity"

    summary_source = (
        record.get("description")
        or record.get("body")
        or note_text
        or record.get("details")
        or record.get("text")
    )
    summary = str(summary_source or title).strip()
    if isinstance(address, str) and address and address not in summary:
        summary = f"{summary} — {address}".strip(" —")

    timestamp = _lofty_epoch_ms_to_iso(
        record.get("createdAt")
        or record.get("created_at")
        or record.get("created")
        or record.get("ts")
        or record.get("timestamp")
        or record.get("activityTime")
        or record.get("eventTime")
    )
    return {
        "id": str(raw_id) if raw_id else "",
        "lead_id": lead_id,
        "subtype": activity_type,
        "title": title,
        "summary": summary,
        "address": address if isinstance(address, str) else None,
        "link": record.get("link") if isinstance(record.get("link"), str) else None,
        "timestamp": timestamp,
    }


def _lofty_normalize_note(record: JsonRecord, lead_id: str) -> JsonRecord:
    raw_id = record.get("id") or record.get("noteId") or record.get("uuid") or ""
    body = str(
        record.get("content")
        or record.get("body")
        or record.get("note")
        or record.get("text")
        or ""
    ).strip()
    author = (
        record.get("authorName")
        or record.get("author")
        or record.get("createdBy")
        or record.get("userName")
        or record.get("creatorName")
        or None
    )
    timestamp = _lofty_epoch_ms_to_iso(
        record.get("createdAt")
        or record.get("created_at")
        or record.get("createTime")
        or record.get("ts")
        or record.get("timestamp")
    )
    title = body[:80] + ("…" if len(body) > 80 else "")
    return {
        "id": str(raw_id) if raw_id else "",
        "lead_id": lead_id,
        "title": title or "Note",
        "summary": body,
        "author": author,
        "timestamp": timestamp,
    }


def _lofty_normalize_task(record: JsonRecord, lead_id: str) -> JsonRecord:
    """Real Lofty task shape:
    ``{id, content, type, deadline, finishTime, createTime, finishFlag,
    overdueFlag, deleteFlag, assignedUser, subject, body}``.
    ``deadline``, ``finishTime``, ``createTime`` are ISO strings ending
    in ``GMT``."""
    raw_id = record.get("id") or record.get("taskId") or record.get("uuid") or ""
    title = str(
        record.get("subject")
        or record.get("title")
        or record.get("content")
        or record.get("name")
        or record.get("description")
        or record.get("type")
        or "Task"
    ).strip() or "Task"
    summary = str(
        record.get("content")
        or record.get("description")
        or record.get("body")
        or record.get("notes")
        or title
    ).strip()
    finish_flag = bool(record.get("finishFlag"))
    overdue_flag = bool(record.get("overdueFlag"))
    raw_status = record.get("status") or record.get("state") or ""
    if raw_status:
        status = str(raw_status).strip().lower()
    elif finish_flag:
        status = "done"
    elif overdue_flag:
        status = "overdue"
    elif record.get("completed"):
        status = "done"
    else:
        status = "open"
    due = _lofty_epoch_ms_to_iso(
        record.get("deadline")
        or record.get("dueDate")
        or record.get("due_at")
        or record.get("dueAt")
        or record.get("scheduledFor")
    )
    timestamp = _lofty_epoch_ms_to_iso(
        record.get("createTime")
        or record.get("createdAt")
        or record.get("created_at")
    ) or due
    return {
        "id": str(raw_id) if raw_id else "",
        "lead_id": lead_id,
        "title": title,
        "summary": summary,
        "status": status,
        "type": str(record.get("type") or "").strip() or None,
        "assignedUser": record.get("assignedUser"),
        "dueAt": due,
        "timestamp": timestamp,
    }


def _lofty_write(
    path: str,
    env_values: dict[str, str],
    body: JsonRecord,
    method: str = "POST",
) -> Any:
    headers, _auth_type = _lofty_headers(env_values)
    if not headers.get("Authorization"):
        raise RuntimeError("LOFTY_API_KEY or LOFTY_ACCESS_TOKEN is not set")
    base = "https://api.chime.me"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")
