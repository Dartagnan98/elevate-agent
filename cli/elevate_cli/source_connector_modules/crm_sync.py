"""CRM source snapshot sync helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.connector_views import connector_view
from elevate_cli.source_connector_modules.crm_helpers import (
    _extract_lead_records,
    _generic_crm_get,
    _lofty_lead_name,
    _lofty_timestamp,
    _provider_label,
    _tag_names,
)
from elevate_cli.source_connector_modules.integration_settings import _as_dict, _combined_env, _merge_crm
from elevate_cli.source_connector_modules.source_catalog import JSONL_FILES, OWNER_BY_SOURCE, UI_BY_SOURCE
from elevate_cli.source_connector_modules.source_io import (
    _read_jsonl_records,
    _replace_jsonl,
    _safe_int,
    _snapshot_writer_lock,
    _source_dir,
    _write_json,
)
from elevate_cli.source_connector_modules.thread_helpers import _heat_score_for_record


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def sync_generic_crm_source(
    config: dict[str, Any] | None = None, *, limit: int = 5000
) -> JsonRecord:
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = source_connectors._now()
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
        source_connectors._walk_jsonl_into_pg(source_dir)
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
