"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.config import (
    get_config_path,
    get_elevate_home,
    get_env_path,
    load_config,
    load_env,
    save_config,
    save_env_value,
)
from elevate_cli.source_connector_modules.prompts import (
    _local_counts_command,
    _local_python_prefix,
    _local_sync_command,
    _render_apple_messages_agent_prompt,
    _render_buyer_brief_agent_prompt,
    _render_crm_prompt,
    _render_social_agent_prompt,
    _render_xposure_pcs_agent_prompt,
    _render_xposure_pcs_views_agent_prompt,
    _source_file_count_commands,
    source_prompt_for,
)


JsonRecord = dict[str, Any]

from elevate_cli.source_connector_modules.source_catalog import (
    AGENT_SESSION_SOURCE_IDS,
    COMPOSIO_SOCIAL_CONTRACT,
    CONNECTION_CONTRACT,
    JSONL_FILES,
    OWNER_BY_SOURCE,
    SERVER_INLINE_SOURCE_IDS,
    SOURCE_CATEGORIES,
    SOURCE_CONNECTION_BLUEPRINTS,
    SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
    SOURCE_PROMPT_CATEGORIES,
    UI_BY_SOURCE,
    WIRED_SOURCE_IDS,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


from elevate_cli.source_connector_modules.source_io import (
    PROFILE_STATUS_VALUES,
    _JSONL_COUNT_CACHE,
    _JSONL_RECORD_CACHE,
    _count_jsonl,
    _find_jsonl_record_by_id,
    _profile_state_path,
    _read_json,
    _read_jsonl_records,
    _read_profile_state,
    _read_source_ui_state,
    _record_timestamp,
    _replace_jsonl,
    _parse_record_dt,
    _safe_int,
    _snapshot_reader_lock,
    _snapshot_writer_lock,
    _source_dir,
    _source_ui_state_path,
    _stream_jsonl_records_by_id,
    _tag_text,
    _write_json,
    _write_profile_state,
    _write_source_ui_state,
)


from elevate_cli.source_connector_modules.thread_helpers import (
    _AUTOMATED_DOMAIN_HINTS,
    _AUTOMATED_LOCALPARTS,
    _channel_label,
    _extract_email,
    _heat_score_for_record,
    _is_automated_email,
    _is_automated_sender_record,
    _latest_text,
    _record_person_name,
    _thread_from_record,
    _thread_key,
)

from elevate_cli.source_connector_modules.record_snapshots import (
    _LIST_RECORD_FIELDS,
    _compact_list_text,
    _list_record_snapshot,
)

from elevate_cli.source_connector_modules.draft_helpers import (
    _TEMPLATE_TOKEN_RE,
    _draft_from_task,
    _draft_from_thread,
    _draft_recipient,
    _draft_text_for_task,
    _fallback_draft_for_thread,
    _first_name_from_person,
    _is_message_draft_task,
    _outreach_lane_for_thread,
    _record_field,
    _render_outreach_template,
    _select_thread_template,
    _task_key,
    _template_channel_for_thread,
    _template_values_for_thread,
    _templated_draft_for_thread,
)

from elevate_cli.source_connector_modules.profile_helpers import (
    SOCIAL_INTENT_WORDS,
    SOCIAL_SOURCE_IDS,
    _email_key,
    _is_social_intent,
    _merge_profile,
    _merge_profile_verifiers,
    _name_key,
    _phone_key,
    _profile_contact_values,
    _profile_label,
    _profile_match_keys,
    _profile_verifiers,
    _profiles_from_threads,
    _source_has_inbox_records,
    _source_record_counts,
    _string_values,
)


from elevate_cli.source_connector_modules.apple_messages import (
    APPLE_EPOCH,
    _apple_dt,
    _apple_messages_chat_db_path,
    _apple_messages_source_dir,
    _init_apple_index_db,
    _load_chat_participants,
    _looks_like_fda_denied,
    _sqlite_uri,
    _update_span,
    _write_blocked_apple_messages_source,
    _write_paused_apple_messages_source,
    get_apple_messages_directions,
    initialize_apple_messages_source,
    set_apple_messages_directions,
)


from elevate_cli.source_connector_modules.connector_state import (
    _blueprint,
    _connector_recovery,
    _mutable_source_exists,
    _state_from_status,
)




from elevate_cli.source_connector_modules.connector_views import (
    _candidate_records_for_source,
    _composio_connector_view,
    _discover_composio_views,
    _initialize_behavior,
    build_source_connectors_response,
    build_source_records_response,
    connector_view,
)


from elevate_cli.source_connector_modules.source_inbox import (
    _collect_drafts_for_db_inbox,
    build_source_inbox_response,
)


from elevate_cli.source_connector_modules.private_search import (
    _PCS_BUYER_TAGS,
    _is_pcs_tag,
    _norm_email,
    _norm_phone,
    _pcs_tagged_crm_buyers,
    _read_private_search_buyers,
)


from elevate_cli.source_connector_modules.thread_context import (
    _message_for_thread,
    _resolve_source_view,
    build_thread_context_response,
)


from elevate_cli.source_connector_modules.source_actions import (
    _approve_atomic,
    _channel_for_source,
    _fire_approve_tick,
    _source_view_for_state,
    _thread_draft_template_state,
    update_profile_favorite,
    update_profile_state,
    update_source_task_state,
    update_source_thread_state,
)


from elevate_cli.source_connector_modules.source_scaffold import (
    scaffold_composio_social_source,
    scaffold_source,
)




from elevate_cli.source_connector_modules.crm_helpers import (
    _LOFTY_LIST_KEYS,
    _basic_auth_header,
    _build_crm_auth,
    _extract_lead_records,
    _generic_crm_get,
    _generic_crm_write,
    _list_text,
    _lofty_epoch_ms_to_iso,
    _lofty_extract_list,
    _lofty_get,
    _lofty_get_activities,
    _lofty_get_first_ok,
    _lofty_get_notes,
    _lofty_get_tasks,
    _lofty_headers,
    _lofty_lead_name,
    _lofty_listing_address,
    _lofty_normalize_activity,
    _lofty_normalize_note,
    _lofty_normalize_task,
    _lofty_timestamp,
    _lofty_write,
    _provider_label,
    _stable_hash_id,
    _tag_names,
)


def sync_generic_crm_source(
    config: dict[str, Any] | None = None, *, limit: int = 5000
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = _combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    provider = str(crm.get("provider") or "custom")
    label = str(crm.get("label") or _provider_label(provider))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")

    if not api_key or not str(crm.get("base_url") or "").strip():
        _write_json(
            source_dir / "source.json",
            {
                "source_id": "crm",
                "provider": label,
                "account_label": label,
                "connection_type": f"{provider}_api",
                "auth_status": "missing_secret",
                "sync_mode": "crm_lead_snapshot",
                "owner_agent": owner,
                "enabled_ui_surfaces": surfaces,
                "setup_status": "needs_operator",
                "last_sync_at": None,
                "setup_notes": f"Add {env_key} to ~/.elevate/.env and confirm the {label} base URL.",
            },
        )
        _write_json(
            source_dir / "status.json",
            {
                "connected": False,
                "import_only": False,
                "blocked": False,
                "last_error": None,
                "next_operator_step": f"Add the {label} API key, then sync CRM again.",
                "last_checked_at": now,
            },
        )
        for file_name in JSONL_FILES:
            _replace_jsonl(source_dir / file_name, [])
        view = connector_view(source_root, "crm")
        if view is None:
            raise RuntimeError(f"{label} source could not be read")
        return view

    leads: list[JsonRecord] = []
    attempted: list[str] = [leads_path]
    errors: list[str] = []
    pagination_params: dict[str, Any] = {"limit": min(limit, 100)}
    if provider == "followupboss":
        pagination_params = {"limit": min(limit, 100), "sort": "-updated"}
    elif provider == "sierra":
        pagination_params = {"page": 1, "pageSize": min(limit, 100)}
    elif provider == "boldtrail":
        pagination_params = {"limit": min(limit, 100), "sort": "-updated_at"}
    elif provider == "brivity":
        pagination_params = {"page": 1, "per_page": min(limit, 100)}
    try:
        payload = _generic_crm_get(crm, api_key, leads_path, pagination_params)
        leads = _extract_lead_records(payload)
    except Exception as exc:
        errors.append(f"{leads_path}: {exc}")

    deduped: list[JsonRecord] = []
    seen_ids: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("id") or lead.get("leadId") or lead.get("lead_id") or "").strip()
        if not lead_id:
            lead_id = f"unknown-{len(seen_ids) + 1}"
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        deduped.append(lead)

    contact_records: list[JsonRecord] = []
    conversation_records: list[JsonRecord] = []
    lead_events: list[JsonRecord] = []
    task_records: list[JsonRecord] = []
    for lead in deduped:
        lead_id = str(lead.get("id") or lead.get("leadId") or lead.get("lead_id") or "").strip()
        record_id = f"{provider}-lead:{lead_id or len(contact_records) + 1}"
        name = _lofty_lead_name(lead)
        timestamp = _lofty_timestamp(lead)
        stage = str(
            lead.get("stage") or lead.get("status") or lead.get("leadType") or lead.get("aiStage") or ""
        ).strip()
        source = str(
            lead.get("source") or lead.get("leadSource") or lead.get("origin") or ""
        ).strip()
        tags = _tag_names(lead.get("tags"))
        score = _safe_int(lead.get("score") or lead.get("leadScore"), 45)
        summary = (
            f"{name} from {label}"
            + (f" is in {stage}" if stage else "")
            + (f" via {source}" if source else "")
            + "."
        )
        base_record = {
            "source_id": "crm",
            "source_record_id": record_id,
            "conversation_id": record_id,
            "contact_id": record_id,
            "display_name": name,
            "channel": label,
            "timestamp": timestamp,
            "last_seen_at": timestamp,
            "last_message_at": timestamp,
            "text": summary,
            "summary": summary,
            "lead_id": lead_id or None,
            "stage": stage or None,
            "lead_source": source or None,
            "assigned_user": lead.get("assignedUser") or lead.get("assignedAgent") or lead.get("assigned_to"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, f"{provider}-crm", "crm-lead"],
            "confidence": 0.82,
            "target_ui_surfaces": surfaces,
        }
        contact_records.append(base_record)
        conversation_records.append(
            {
                **base_record,
                "total_messages": _safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
                "inbound_count": 0,
                "outbound_count": 0,
                "last_text": summary,
            }
        )
        lead_events.append(
            {
                **base_record,
                "type": "crm_lead_synced",
                "title": f"{label} lead synced",
            }
        )
        heat_score, heat_label = _heat_score_for_record(base_record)
        if heat_label in {"hot", "warm"}:
            task_records.append(
                {
                    **base_record,
                    "source_record_id": f"{record_id}:follow-up",
                    "title": f"Review {name}",
                    "status": "open",
                    "task_type": "lead_follow_up",
                    "approval_required": False,
                    "owner_agent": owner,
                    "summary": f"{name} looks {heat_label} in {label}. Review source, stage, notes, and next outreach step.",
                    "heat_score": heat_score,
                    "target_ui_surfaces": ["Leads", "Today", "Outreach"],
                }
            )

    # Atomic multi-file rewrite (Codex audit P1, 2026-05-05).
    with _snapshot_writer_lock(source_dir):
        preserved_tasks = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": label,
            "account_label": label,
            "connection_type": f"{provider}_api",
            "auth_status": f"{str(crm.get('auth_type') or 'header')}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": f"Read-only {label} lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                if deduped
                else f"{label} auth was found, but no lead rows were returned. Check the API key scope, then sync again."
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
            },
        },
    )
    # Continuous DB writethrough — Codex audit P0 (2026-05-05).
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough: {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": now, "error": str(exc)},
        )

    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError(f"{label} source could not be read")
    return view


# ── CRM write layer (create, note, stage update) ──────────────────────────────


def _sierra_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Sierra-ApiKey": api_key,
        "Sierra-OriginatingSystemName": "elevate",
    }


def _sierra_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_sierra_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _sierra_get(path: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    request = urllib.request.Request(url, headers=_sierra_headers(api_key), method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _brivity_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token token={api_key}",
    }


def _brivity_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://www.brivity.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_brivity_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _resolve_crm_context(
    config: dict[str, Any],
) -> tuple[str, str, JsonRecord, dict[str, str]]:
    """Return (provider, api_key, crm_config, env_values)."""
    env_values = _combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    # Honor whatever CRM was picked at onboarding/config — never assume Lofty.
    provider = _canonical_crm_provider(crm.get("provider"))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    if not api_key and provider == "lofty":
        api_key = str(env_values.get("LOFTY_API_KEY") or env_values.get("LOFTY_ACCESS_TOKEN") or "").strip()
    return provider, api_key, crm, env_values


def crm_find_lead(
    email: str = "",
    config: dict[str, Any] | None = None,
    *,
    phone: str = "",
) -> JsonRecord | None:
    """Find a CRM lead by email (or phone fallback). Returns normalized {id, stage, tags} or None."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    def _normalize_lofty(lead: JsonRecord) -> JsonRecord:
        return {
            "id": str(lead.get("leadId") or ""),
            "stage": str(lead.get("stage") or ""),
            "tags": [t.get("tagName") for t in (lead.get("tags") or []) if t.get("tagName")],
            "raw": lead,
        }

    if provider == "lofty":
        if email:
            payload = _lofty_get(f"v1.0/leads?email={urllib.parse.quote(email)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        if phone:
            payload = _lofty_get(f"v1.0/leads?phone={urllib.parse.quote(phone)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        return None

    if provider == "followupboss":
        if email:
            payload = _generic_crm_get(crm, api_key, "v1/people", {"email": email, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        if phone:
            payload = _generic_crm_get(crm, api_key, "v1/people", {"phone": phone, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        return None

    if provider == "sierra":
        if email:
            payload = _sierra_get("leads", api_key, {"email": email, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        if phone:
            payload = _sierra_get("leads", api_key, {"phone": phone, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        return None

    if provider == "brivity":
        # Brivity has no public search endpoint -- caller must track ids externally
        return None

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_find_lead not yet implemented for provider: {provider}")


def crm_create_lead(
    contact: JsonRecord,
    config: dict[str, Any] | None = None,
) -> str:
    """Create a lead in the CRM. contact = {firstName, lastName, email, phone, source, stage, tags}.
    Returns the new lead's CRM id."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)
    first = str(contact.get("firstName") or "")
    last = str(contact.get("lastName") or "")
    email = str(contact.get("email") or "")
    phone = str(contact.get("phone") or "")
    source = str(contact.get("source") or "elevate")
    stage = str(contact.get("stage") or "New Leads")
    tags = list(contact.get("tags") or [])

    if provider == "lofty":
        body: JsonRecord = {"firstName": first, "lastName": last, "source": source, "stage": stage, "tags": tags}
        if email:
            body["emails"] = [email]
        if phone:
            body["phones"] = [phone]
        result = _lofty_write("v1.0/leads", env_values, body, method="POST")
        return str(result.get("leadId") or result.get("id") or "")

    if provider == "followupboss":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["emails"] = [{"value": email, "type": "work"}]
        if phone:
            body["phones"] = [{"value": phone, "type": "mobile"}]
        result = _generic_crm_write(crm, api_key, "v1/people", body, method="POST")
        lead_id = str(result.get("id") or result.get("person", {}).get("id") or "")
        if lead_id and stage and stage != "New Leads":
            _generic_crm_write(crm, api_key, f"v1/people/{lead_id}", {"stage": stage}, method="PUT")
        return lead_id

    if provider == "sierra":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if tags:
            body["tags"] = tags
        if stage:
            body["leadType"] = stage  # Sierra uses leadType on create, status on update
        note_text = str(contact.get("note") or "")
        if note_text:
            body["note"] = note_text
        result = _sierra_write("leads", api_key, body, method="POST")
        return str((result.get("data") or {}).get("id") or "")

    if provider == "brivity":
        # Brivity uses snake_case and encodes notes in description
        body = {"source": source}
        if first:
            body["first_name"] = first
        if last:
            body["last_name"] = last
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if stage:
            # Brivity status enum: new, unqualified, watch, nurture, hot, archived
            body["status"] = stage.lower()
        note_text = str(contact.get("note") or "")
        if note_text:
            body["description"] = note_text
        result = _brivity_write("api/v2/leads", api_key, body, method="POST")
        return str((result.get("lead") or result).get("id") or "")

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_create_lead not yet implemented for provider: {provider}")


def crm_add_note(
    lead_id: str,
    note: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """Add a note to an existing CRM lead. Returns True on success."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        try:
            _lofty_write(f"v1.0/leads/{lead_id}/notes", env_values, {"content": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        try:
            _generic_crm_write(crm, api_key, "v1/notes", {"personId": int(lead_id), "body": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "sierra":
        try:
            _sierra_write(f"leads/{lead_id}/note", api_key, {"message": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no notes endpoint -- notes must go into description at create time
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_add_note not yet implemented for provider: {provider}")


def sync_pending_notes_to_lofty(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 25,
    max_attempts: int = 5,
) -> JsonRecord:
    """Push every ``notes`` row with ``crm_sync_state='pending'`` to
    Lofty. Returns a summary ``{pushed, skipped, failed, errors[]}``.

    Skip rules (counted in ``skipped``, not retried):
      * non-Lofty CRM provider — caller picked the wrong source.
      * Contact has no ``lofty_id`` identity — we have nowhere to POST.

    Failure rules:
      * 4xx → ``mark_lofty_failed(permanent=True)`` — payload bad, retry
        won't fix it. Operator can re-trigger by editing the body.
      * 5xx / timeout / unknown → ``mark_lofty_failed(permanent=False)`` —
        attempt counter bumps; row stays ``pending`` until ``max_attempts``.

    Content prefix: ``[AI/{author_name}] {body}`` — so the operator can
    skim Lofty's note feed and know what wrote each line.
    """
    config = config or load_config()
    provider, _api_key, _crm, env_values = _resolve_crm_context(config)

    summary: JsonRecord = {
        "provider": provider,
        "pushed": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    if provider != "lofty":
        # Future: dispatch to followupboss / sierra / etc. For now only
        # Lofty is wired — others fall through silently to keep the cron
        # safe to run regardless of which CRM the operator connected.
        return summary

    headers, _auth_type = _lofty_headers(env_values)
    if not headers.get("Authorization"):
        summary["errors"].append("LOFTY_API_KEY / LOFTY_ACCESS_TOKEN not set")
        return summary

    from elevate_cli.data import (
        connect as _db_connect,
        list_pending_lofty_notes,
        mark_lofty_synced,
        mark_lofty_failed,
    )

    with _db_connect() as conn:
        pending = list_pending_lofty_notes(conn, limit=limit, max_attempts=max_attempts)
        for note in pending:
            note_id = note["id"]
            contact_id = note["contactId"]
            # Resolve the contact's Lofty lead id via the identities table.
            lofty_row = conn.execute(
                "SELECT value FROM identities "
                "WHERE contact_id=? AND kind='lofty_id' LIMIT 1",
                (contact_id,),
            ).fetchone()
            if lofty_row is None or not lofty_row["value"]:
                # No Lofty linkage — permanently fail. If a Lofty identity
                # gets added later, the operator can re-trigger by editing
                # the note body (which moves it back to pending).
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error="contact has no lofty_id identity",
                    permanent=True,
                )
                summary["skipped"] += 1
                continue
            lead_id = str(lofty_row["value"])
            content = f"[AI/{note['authorName']}] {note['body']}"

            try:
                resp = _lofty_write(
                    f"v1.0/leads/{lead_id}/notes",
                    env_values,
                    {"content": content},
                    method="POST",
                )
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=True,
                    )
                    summary["failed"] += 1
                else:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=False,
                    )
                    summary["errors"].append(f"{note_id}: HTTP {exc.code}")
                continue
            except Exception as exc:
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error=str(exc)[:500],
                    permanent=False,
                )
                summary["errors"].append(f"{note_id}: {exc}")
                continue

            lofty_note_id = None
            if isinstance(resp, dict):
                # Lofty returns either {"noteId": …} or wraps the row under
                # "data". Probe both shapes.
                raw = resp.get("noteId") or resp.get("id")
                if raw is None and isinstance(resp.get("data"), dict):
                    raw = resp["data"].get("noteId") or resp["data"].get("id")
                if raw is not None:
                    lofty_note_id = str(raw)

            if lofty_note_id:
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=lofty_note_id)
                summary["pushed"] += 1
            else:
                # POST succeeded (no exception) but we couldn't parse the
                # id. Mark synced with a placeholder so we don't double-post,
                # but flag in errors so the operator can investigate.
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=f"unknown:{note_id}")
                summary["pushed"] += 1
                summary["errors"].append(
                    f"{note_id}: posted but noteId missing from response"
                )

    return summary


def crm_update_stage(
    lead_id: str,
    stage: str,
    tags: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    """Update a CRM lead's stage and optionally merge tags. Returns True on success."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        body: JsonRecord = {"stage": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _lofty_write(f"v1.0/leads/{lead_id}", env_values, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        body = {"stage": stage}
        try:
            _generic_crm_write(crm, api_key, f"v1/people/{lead_id}", body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "sierra":
        # Sierra status enum: New, Qualify, Active, Prime, Pending, Closed, Archived, Junk, DoNotContact, Watch, Blocked
        body = {"status": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _sierra_write(f"leads/{lead_id}", api_key, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no status-update endpoint -- re-POST with status to upsert by email
        # Caller should use crm_create_lead with status set instead
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_update_stage not yet implemented for provider: {provider}")


# Lofty enrichment is the dominant cost of `elevate sync crm`: 3 HTTP calls
# per lead (activities + notes + tasks). To prevent a slow tenant from hanging
# the whole sync, enrichment runs in parallel with a per-call ceiling and
# checkpoints to disk every N leads so a killed run resumes instead of restarting.
_LOFTY_ENRICHMENT_WORKERS = 8
_LOFTY_ENRICHMENT_TIMEOUT_S = 10
_LOFTY_ENRICHMENT_CHECKPOINT_EVERY = 5


def _lofty_load_enrichment_progress(
    artifacts_dir: Path,
) -> tuple[set[str], list[JsonRecord], dict[str, int]]:
    """Load the prior enrichment checkpoint so a resumed sync skips already-
    enriched lead_ids. Missing/corrupt file = clean start, never raises."""
    path = artifacts_dir / "enrichment_progress.json"
    if not path.exists():
        return set(), [], {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        return set(), [], {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    completed = {str(x) for x in (payload.get("completed_lead_ids") or []) if x}
    events = [e for e in (payload.get("events") or []) if isinstance(e, dict)]
    summary = payload.get("summary") or {}
    base_summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    for key in base_summary:
        base_summary[key] = int(summary.get(key, 0) or 0)
    return completed, events, base_summary


def _lofty_save_enrichment_progress(
    artifacts_dir: Path,
    *,
    completed_lead_ids: set[str],
    events: list[JsonRecord],
    summary: dict[str, int],
    total_leads: int,
    status: str,
) -> None:
    """Atomic checkpoint write — same readers/writers can see partial
    enrichment without a torn file."""
    payload = {
        "checkpointed_at": _now(),
        "status": status,
        "completed_lead_ids": sorted(completed_lead_ids),
        "completed_count": len(completed_lead_ids),
        "total_leads": total_leads,
        "summary": summary,
        "events": events,
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tmp = artifacts_dir / "enrichment_progress.json.tmp"
    final = artifacts_dir / "enrichment_progress.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)


def _lofty_enrich_one_lead(
    *,
    lead_id: str,
    record_id: str,
    base_record: JsonRecord,
    fallback_timestamp: str,
    env_values: dict[str, str],
    timeout: int,
) -> tuple[str, list[JsonRecord], dict[str, int]]:
    """Worker called from a thread pool. Pulls activities + notes + tasks
    for one lead and returns the typed lead_events + a per-lead summary
    delta. Never raises — endpoint errors increment the error counter so
    one slow lead can't block the whole pool."""
    events: list[JsonRecord] = []
    summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}

    try:
        activity_payload = _lofty_get_activities(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        activity_payload = []
        summary["errors"] += 1
    for raw_act in activity_payload:
        norm = _lofty_normalize_activity(raw_act, lead_id)
        act_id = norm["id"] or _stable_hash_id(
            norm["subtype"], norm["title"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:activity:{act_id}",
                "type": "crm_activity",
                "provider": "lofty",
                "subtype": norm["subtype"],
                "title": norm["title"],
                "summary": norm["summary"],
                "address": norm["address"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["activities"] = len(activity_payload)

    try:
        notes_payload = _lofty_get_notes(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        notes_payload = []
        summary["errors"] += 1
    for raw_note in notes_payload:
        norm = _lofty_normalize_note(raw_note, lead_id)
        note_id = norm["id"] or _stable_hash_id(
            norm["title"], norm["summary"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:note:{note_id}",
                "type": "crm_note",
                "provider": "lofty",
                "title": norm["title"] or "Note",
                "summary": norm["summary"],
                "author": norm["author"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["notes"] = len(notes_payload)

    try:
        tasks_payload = _lofty_get_tasks(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        tasks_payload = []
        summary["errors"] += 1
    tasks_payload = [t for t in tasks_payload if not t.get("deleteFlag")]
    for raw_task in tasks_payload:
        norm = _lofty_normalize_task(raw_task, lead_id)
        task_id = norm["id"] or _stable_hash_id(
            norm["title"], norm["summary"], norm["dueAt"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:task:{task_id}",
                "type": "crm_task",
                "provider": "lofty",
                "title": norm["title"],
                "summary": norm["summary"],
                "status": norm["status"],
                "task_subtype": norm["type"],
                "assignedUser": norm["assignedUser"],
                "dueAt": norm["dueAt"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["tasks"] = len(tasks_payload)

    return lead_id, events, summary


def sync_lofty_crm_source(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 5000,
    enrichment_limit: int = 5000,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = _combined_env(config)
    headers, auth_type = _lofty_headers(env_values)

    if not headers.get("Authorization"):
        _write_json(
            source_dir / "source.json",
            {
                "source_id": "crm",
                "provider": "Lofty CRM",
                "account_label": "Lofty CRM",
                "connection_type": "lofty_api",
                "auth_status": "missing_secret",
                "sync_mode": "crm_lead_snapshot",
                "owner_agent": owner,
                "enabled_ui_surfaces": surfaces,
                "setup_status": "needs_operator",
                "last_sync_at": None,
                "setup_notes": "Add LOFTY_API_KEY or LOFTY_ACCESS_TOKEN to ~/.elevate/.env or the tools root .env.",
            },
        )
        _write_json(
            source_dir / "status.json",
            {
                "connected": False,
                "import_only": False,
                "blocked": False,
                "last_error": None,
                "next_operator_step": "Add the Lofty API key, then initialize/sync CRM again.",
                "last_checked_at": now,
            },
        )
        for file_name in JSONL_FILES:
            _replace_jsonl(source_dir / file_name, [])
        view = connector_view(source_root, "crm")
        if view is None:
            raise RuntimeError("Lofty CRM source could not be read")
        return view

    # Lofty caps page size at 100. For limit>100 we paginate via offset.
    # The two endpoints are tried in fall-through order: v2.0/working-leads
    # returns the high-priority slice, v1.0/leads returns everything.
    leads: list[JsonRecord] = []
    attempted: list[str] = []
    errors: list[str] = []
    page_size = 100
    for path, base_params in (
        ("/v2.0/working-leads", {"aiStage": "HIGH_PRIORITY", "sort": "UpdateTime", "desc": "true"}),
        ("/v1.0/leads", {}),
    ):
        attempted.append(path)
        offset = 0
        endpoint_pulled = 0
        while endpoint_pulled < limit:
            params = {
                **base_params,
                "limit": min(page_size, limit - endpoint_pulled),
                "offset": offset,
            }
            try:
                payload = _lofty_get(path, env_values, params)
            except Exception as exc:
                errors.append(f"{path}@offset={offset}: {exc}")
                break
            extracted = _extract_lead_records(payload)
            if not extracted:
                break  # exhausted this endpoint
            leads.extend(extracted)
            endpoint_pulled += len(extracted)
            offset += len(extracted)
            if len(extracted) < page_size:
                break  # short page = last page

    deduped: list[JsonRecord] = []
    seen_ids: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("leadId") or lead.get("id") or lead.get("lead_id") or "").strip()
        if not lead_id:
            lead_id = f"unknown-{len(seen_ids) + 1}"
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        deduped.append(lead)

    contact_records: list[JsonRecord] = []
    conversation_records: list[JsonRecord] = []
    lead_events: list[JsonRecord] = []
    task_records: list[JsonRecord] = []
    pending_enrichments: list[JsonRecord] = []
    enrichment_summary: dict[str, int] = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    max_enriched = max(0, int(enrichment_limit or 0))
    for index, lead in enumerate(deduped):
        lead_id = str(lead.get("leadId") or lead.get("id") or lead.get("lead_id") or "").strip()
        record_id = f"lofty-lead:{lead_id or len(contact_records) + 1}"
        name = _lofty_lead_name(lead)
        timestamp = _lofty_timestamp(lead)
        stage = str(lead.get("stage") or lead.get("aiStage") or lead.get("status") or "").strip()
        source = str(lead.get("source") or lead.get("leadSource") or "").strip()
        tags = _tag_names(lead.get("tags"))
        score = _safe_int(lead.get("score") or lead.get("leadScore"), 45)
        summary = (
            f"{name} from Lofty"
            + (f" is in {stage}" if stage else "")
            + (f" via {source}" if source else "")
            + "."
        )
        # Carry the full Lofty lead profile through to JSONL so the
        # migrate.py writethrough can enrich the contacts row. Pre-0012
        # this only carried name/email/phone/stage and the drawer rendered
        # blank cards. See migration 0012_lofty_lead_metadata.sql for the
        # column list and _CONTACT_ENRICHMENT_KEY_MAP in migrate.py for
        # accepted aliases.
        def _lead_get(*keys: str) -> Any:
            for key in keys:
                if key in lead:
                    value = lead.get(key)
                    if value not in (None, ""):
                        return value
            return None

        base_record = {
            "source_id": "crm",
            "source_record_id": record_id,
            "conversation_id": record_id,
            "contact_id": record_id,
            "display_name": name,
            "channel": "Lofty CRM",
            "timestamp": timestamp,
            "last_seen_at": timestamp,
            "last_message_at": timestamp,
            "text": summary,
            "summary": summary,
            "lead_id": lead_id or None,
            "stage": stage or None,
            "lead_source": source or None,
            "assigned_user": _lead_get("assignedUser", "assignedAgent"),
            "assignedUser": _lead_get("assignedUser", "assignedAgent"),
            "assignedUserId": _lead_get("assignedUserId", "assigned_user_id"),
            "leadUserId": _lead_get("leadUserId", "lofty_lead_user_id"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, "lofty-crm", "crm-lead"],
            "confidence": 0.86,
            "target_ui_surfaces": surfaces,
            # --- Lofty enrichment (migration 0012) ---
            "pondId": _lead_get("pondId", "pond_id"),
            "pondName": _lead_get("pondName", "pond_name"),
            "referredBy": _lead_get("referredBy", "referred_by"),
            "opportunity": _lead_get("opportunity"),
            "buyingTimeFrame": _lead_get("buyingTimeFrame", "buying_time_frame"),
            "sellingTimeFrame": _lead_get("sellingTimeFrame", "selling_time_frame"),
            "preQual": _lead_get("preQual", "preQualStatus", "pre_qual_status"),
            "mortgage": _lead_get("mortgage", "mortgageStatus", "mortgage_status"),
            "fthb": _lead_get("fthb", "firstTimeHomeBuyer", "first_time_home_buyer"),
            "hasHouseToSell": _lead_get("hasHouseToSell", "has_house_to_sell", "houseToSell"),
            "withBuyerAgent": _lead_get("withBuyerAgent", "with_buyer_agent"),
            "withListingAgent": _lead_get("withListingAgent", "with_listing_agent"),
            "buyHouseIntent": _lead_get("buyHouseIntent", "buy_house_intent", "buyHouse"),
            "leadTypes": lead.get("leadTypes") or lead.get("lead_types") or [],
            "segments": lead.get("segments") or [],
            "cannotText": _lead_get("cannotText", "cannot_text"),
            "cannotCall": _lead_get("cannotCall", "cannot_call"),
            "cannotEmail": _lead_get("cannotEmail", "cannot_email"),
            "unsubscribed": _lead_get("unsubscribed", "unsubscription"),
            "hidden": _lead_get("hidden", "hiddenFlag"),
        }
        contact_records.append(base_record)
        conversation_records.append(
            {
                **base_record,
                "total_messages": _safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
                "inbound_count": 0,
                "outbound_count": 0,
                "last_text": summary,
            }
        )
        lead_events.append(
            {
                **base_record,
                "type": "crm_lead_synced",
                "title": "Lofty lead synced",
            }
        )

        # Phase 2 enrichment runs in parallel after Phase 1 writes the
        # lead snapshot to disk. Stash everything we need to enrich this
        # lead later so the thread pool has self-contained job inputs.
        if lead_id and index < max_enriched:
            pending_enrichments.append(
                {
                    "lead_id": lead_id,
                    "record_id": record_id,
                    "base_record": base_record,
                    "fallback_timestamp": timestamp,
                }
            )

        heat_score, heat_label = _heat_score_for_record(base_record)
        if heat_label in {"hot", "warm"}:
            task_records.append(
                {
                    **base_record,
                    "source_record_id": f"{record_id}:follow-up",
                    "title": f"Review {name}",
                    "status": "open",
                    "task_type": "lead_follow_up",
                    "approval_required": False,
                    "owner_agent": owner,
                    "summary": f"{name} looks {heat_label} in Lofty. Review source, stage, notes, and next outreach step.",
                    "heat_score": heat_score,
                    "target_ui_surfaces": ["Leads", "Today", "Outreach"],
                }
            )

    # === PHASE 1 — Lead snapshot to disk + writethrough to operational Postgres ===
    # Write the lead snapshot before enrichment so even if Phase 2 hangs or
    # gets killed, downstream readers (operational Postgres, /leads UI, thread
    # drawer) already see the 21 leads with stage/score/source. Enrichment
    # in Phase 2 only adds the activity/note/task lead_events.
    base_lead_events = list(lead_events)
    with _snapshot_writer_lock(source_dir):
        preserved_tasks_phase1 = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", base_lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks_phase1 + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": "Lofty CRM",
            "account_label": "Lofty CRM",
            "connection_type": "lofty_api",
            "auth_status": f"{auth_type}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": "Read-only Lofty lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "enrichment_status": "pending" if pending_enrichments else "skipped",
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(base_lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Lead snapshot written. Enrichment running in background — refresh in a minute for activities/notes."
                if pending_enrichments
                else (
                    "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                    if deduped
                    else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
                )
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(base_lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough (phase 1): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": _now(), "phase": 1, "error": str(exc)},
        )

    # === PHASE 2 — Parallel enrichment with checkpointing ===
    # Each lead needs 3 HTTP calls (activities + notes + tasks). Running
    # them serially × 21 leads × 18s timeout = 19 min worst case. Running
    # in parallel (8 workers, 10s timeout each) brings this to 1-3 min for
    # 21 leads. Checkpoints every N completed leads so a killed run
    # resumes from where it left off.
    enrichment_status = "skipped"
    if pending_enrichments:
        prior_completed, prior_events, prior_summary = _lofty_load_enrichment_progress(artifacts_dir)
        # Keep prior summary so resumed runs surface cumulative counts.
        for key in enrichment_summary:
            enrichment_summary[key] = prior_summary.get(key, 0)
        completed_lead_ids: set[str] = set(prior_completed)
        enrichment_events: list[JsonRecord] = [
            e for e in prior_events
            if str((e.get("lead_id") or "")).strip() in completed_lead_ids
        ]
        to_enrich = [
            job for job in pending_enrichments
            if job["lead_id"] not in completed_lead_ids
        ]
        total = len(pending_enrichments)
        done = len(completed_lead_ids)
        if to_enrich:
            print(
                f"[crm] enrichment phase: {done}/{total} already done, "
                f"enriching {len(to_enrich)} leads with {_LOFTY_ENRICHMENT_WORKERS} workers"
                f" (timeout={_LOFTY_ENRICHMENT_TIMEOUT_S}s/call)",
                file=sys.stderr,
                flush=True,
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=_LOFTY_ENRICHMENT_WORKERS,
                thread_name_prefix="lofty-enrich",
            ) as executor:
                futures = {
                    executor.submit(
                        _lofty_enrich_one_lead,
                        lead_id=job["lead_id"],
                        record_id=job["record_id"],
                        base_record=job["base_record"],
                        fallback_timestamp=job["fallback_timestamp"],
                        env_values=env_values,
                        timeout=_LOFTY_ENRICHMENT_TIMEOUT_S,
                    ): job["lead_id"]
                    for job in to_enrich
                }
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        lead_id, events, delta = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        enrichment_summary["errors"] += 1
                        errors.append(f"enrichment worker crashed: {exc}")
                        continue
                    completed_lead_ids.add(lead_id)
                    enrichment_events.extend(events)
                    for key, val in delta.items():
                        enrichment_summary[key] = enrichment_summary.get(key, 0) + int(val or 0)
                    done = len(completed_lead_ids)
                    if done % _LOFTY_ENRICHMENT_CHECKPOINT_EVERY == 0 or done == total:
                        # Atomic checkpoint: lead-events.jsonl + progress file
                        # both reflect the same partial state. Resume picks
                        # up from the union of base + checkpoint events.
                        with _snapshot_writer_lock(source_dir):
                            _replace_jsonl(
                                source_dir / "lead-events.jsonl",
                                base_lead_events + enrichment_events,
                            )
                        _lofty_save_enrichment_progress(
                            artifacts_dir,
                            completed_lead_ids=completed_lead_ids,
                            events=enrichment_events,
                            summary=enrichment_summary,
                            total_leads=total,
                            status="in_progress" if done < total else "complete",
                        )
                        print(
                            f"[crm] enriched {done}/{total} leads "
                            f"(activities={enrichment_summary['activities']}, "
                            f"notes={enrichment_summary['notes']}, "
                            f"tasks={enrichment_summary['tasks']}, "
                            f"errors={enrichment_summary['errors']})",
                            file=sys.stderr,
                            flush=True,
                        )
        # Always include prior + new events in the final lead_events list
        lead_events = base_lead_events + enrichment_events
        enrichment_status = "complete" if done >= total else "partial"

    # === PHASE 3 — Final atomic rewrite + writethrough ===
    # Atomic multi-file rewrite — readers holding _snapshot_reader_lock
    # see either the pre-sync snapshot or the post-sync snapshot, never
    # a torn one. Codex audit P1 (2026-05-05).
    with _snapshot_writer_lock(source_dir):
        preserved_tasks = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": "Lofty CRM",
            "account_label": "Lofty CRM",
            "connection_type": "lofty_api",
            "auth_status": f"{auth_type}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": "Read-only Lofty lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "enrichment_status": enrichment_status,
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                if deduped
                else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    if errors:
        _write_json(artifacts_dir / "last-sync-errors.json", {"checked_at": now, "errors": errors})

    # Continuous ingest into operational Postgres so DB-primary readers see
    # tonight's Lofty data without a manual ``elevate migrate-data`` rerun.
    # Codex audit P0 (2026-05-05): JSONL-only sync left the DB stale.
    # Phase 1 already ran a writethrough for the bare snapshot; this Phase 3
    # writethrough lands the enrichment lead_events.
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        # Never let the DB writethrough fail the sync; legacy JSONL is
        # still the canonical store under DB shadow-read mode.
        if errors is not None:
            errors.append(f"db writethrough (phase 3): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": now, "phase": 3, "error": str(exc)},
        )
    # Mark enrichment checkpoint complete so a subsequent run doesn't
    # re-enrich leads already finalized.
    if enrichment_status in {"complete", "partial"}:
        try:
            _lofty_save_enrichment_progress(
                artifacts_dir,
                completed_lead_ids=set(completed_lead_ids) if pending_enrichments else set(),
                events=[e for e in lead_events if e.get("type") != "crm_lead_synced"],
                summary=enrichment_summary,
                total_leads=len(pending_enrichments),
                status=enrichment_status,
            )
        except Exception:  # noqa: BLE001
            pass

    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError("Lofty CRM sync finished but could not be read")
    return view


def _walk_jsonl_into_pg(source_dir: Path) -> dict[str, Any]:
    """Replay the just-written JSONL snapshot through the operational
    Postgres walker so DB-primary readers see fresh data without a
    manual ``elevate migrate-data`` rerun. Idempotent — every helper
    underneath ``walk_jsonl_source`` is keyed on source_key /
    event_hash / etc."""
    from elevate_cli.data import connect as _data_connect
    from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source

    stats = BackfillStats()
    with _data_connect() as conn:
        walk_jsonl_source(source_dir, conn=conn, stats=stats, dry_run=False)
    return stats.to_dict()




from elevate_cli.source_connector_modules.integration_settings import (
    DEFAULT_CRM,
    _CRM_PROVIDER_ALIASES,
    _CRM_PROVIDER_ENV_DEFAULTS,
    _as_dict,
    _candidate_tools_root,
    _canonical_crm_provider,
    _combined_env,
    _configured_composio_server,
    _crm_to_ui,
    _expand_path,
    _merge_crm,
    _provider_from_admin_profile,
    _ui_crm_to_config,
    get_integration_settings,
    get_source_root_info,
    save_integration_settings,
    test_crm_connection,
)
