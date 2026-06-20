"""Read-only source connector view builders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from elevate_cli.config import load_config
from elevate_cli.source_connector_modules.connector_state import (
    _blueprint,
    _connector_recovery,
    _state_from_status,
)
from elevate_cli.source_connector_modules.integration_settings import get_source_root_info
from elevate_cli.source_connector_modules.source_catalog import (
    AGENT_SESSION_SOURCE_IDS,
    JSONL_FILES,
    OWNER_BY_SOURCE,
    SOURCE_CATEGORIES,
    SOURCE_CONNECTION_BLUEPRINTS,
    SOURCE_PROMPT_CATEGORIES,
    UI_BY_SOURCE,
    WIRED_SOURCE_IDS,
)
from elevate_cli.source_connector_modules.source_io import (
    _count_jsonl,
    _read_json,
    _read_jsonl_records,
    _snapshot_reader_lock,
    _source_dir,
)


JsonRecord = dict[str, Any]


def _source_prompt_for(source_id: str) -> str:
    from elevate_cli import source_connectors

    return source_connectors.source_prompt_for(source_id)


def _initialize_behavior(source_id: str) -> str:
    if source_id == "apple-messages":
        return "local_messages_import"
    if source_id == "social":
        return "composio_social_setup"
    return "agent_setup_task"


def connector_view(
    source_root: Path,
    source_id: str,
    *,
    include_prompt: bool = True,
) -> JsonRecord | None:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return None
    source_dir = _source_dir(source_root, source_id)
    source_path = source_dir / "source.json"
    status_path = source_dir / "status.json"
    artifacts_dir = source_dir / "artifacts"
    source = _read_json(source_path)
    status = _read_json(status_path)
    source_exists = bool(source)
    state = _state_from_status(source_exists, status)
    record_counts = {
        file_name.removesuffix(".jsonl"): _count_jsonl(source_dir / file_name)
        for file_name in JSONL_FILES
    }
    enabled_surfaces = source.get("enabled_ui_surfaces") if isinstance(source, dict) else None
    if not isinstance(enabled_surfaces, list):
        enabled_surfaces = UI_BY_SOURCE.get(source_id, [])
    owner_agent = ""
    if isinstance(source, dict):
        owner_agent = str(source.get("owner_agent") or "").strip()
    label = blueprint["source"]
    if isinstance(source, dict):
        label = str(source.get("provider") or source.get("account_label") or label).strip() or label
    owner_agent = owner_agent or OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    last_error = (
        str(status.get("last_error") or "").strip()
        if isinstance(status, dict) and status.get("last_error")
        else None
    )
    next_operator_step = (
        str(status.get("next_operator_step") or "").strip()
        if isinstance(status, dict) and status.get("next_operator_step")
        else (
            "Initialize this source to create the connector files."
            if state == "not_configured"
            else None
        )
    )
    recovery = _connector_recovery(
        source_id=source_id,
        state=state,
        owner_agent=owner_agent,
        last_error=last_error,
        next_operator_step=next_operator_step,
    )

    return {
        "id": source_id,
        "label": label,
        "category": blueprint.get("category", "admin"),
        "description": blueprint.get("description") or "",
        "wired": source_id in WIRED_SOURCE_IDS,
        "state": state,
        "sourceExists": source_exists,
        "sourceDir": str(source_dir),
        "sourcePath": str(source_path),
        "statusPath": str(status_path),
        "artifactsDir": str(artifacts_dir),
        "connectionType": source.get("connection_type") if isinstance(source, dict) else None,
        "syncMode": source.get("sync_mode") if isinstance(source, dict) else None,
        "authStatus": source.get("auth_status") if isinstance(source, dict) else None,
        "initializeBehavior": _initialize_behavior(source_id),
        "runMode": (
            "agent_session"
            if source_id in AGENT_SESSION_SOURCE_IDS
            else ("server_inline" if source_id in WIRED_SOURCE_IDS else "agent_setup_task")
        ),
        "ownerAgent": owner_agent,
        "enabledUiSurfaces": [str(item) for item in enabled_surfaces if str(item).strip()],
        "connected": bool(status and status.get("connected") is True),
        "importOnly": bool(status and status.get("import_only") is True),
        "blocked": bool(status and status.get("blocked") is True),
        "lastError": last_error,
        "nextOperatorStep": next_operator_step,
        **recovery,
        "lastCheckedAt": status.get("last_checked_at") if isinstance(status, dict) else None,
        "recordCounts": record_counts,
        "prompt": _source_prompt_for(source_id) if include_prompt else "",
    }


def build_source_connectors_response(
    config: dict[str, Any] | None = None,
    *,
    include_prompts: bool = True,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(
            source_root,
            str(item["id"]),
            include_prompt=include_prompts,
        )) is not None
    ]
    return {
        **info,
        "blueprints": [
            dict(
                item,
                prompt=_source_prompt_for(str(item["id"])) if include_prompts else "",
            )
            for item in SOURCE_CONNECTION_BLUEPRINTS
        ],
        "promptCategories": list(SOURCE_PROMPT_CATEGORIES),
        "categories": [dict(c) for c in SOURCE_CATEGORIES],
        "connectors": connectors,
    }


def build_source_records_response(
    source_id: str,
    *,
    config: dict[str, Any] | None = None,
    limit: int = 12,
) -> JsonRecord:
    """Return normalized local source records for an operator-facing dashboard.

    This is intentionally record-shaped, not connector-shaped: pages such as
    Leads should be able to render the latest client messages without exposing
    backend setup internals.
    """
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source = connector_view(source_root, source_id)
    if source is None:
        raise ValueError(f"Unknown source connector: {source_id}")

    source_dir = _source_dir(source_root, source_id)
    safe_limit = max(1, min(int(limit or 12), 100))
    # Shared lock so this multi-file read sees a consistent snapshot
    # against any in-flight CRM sync (Codex audit P1, 2026-05-05).
    with _snapshot_reader_lock(source_dir):
        records = {
            "contacts": _read_jsonl_records(source_dir / "contacts.jsonl", limit=safe_limit),
            "conversations": _read_jsonl_records(source_dir / "conversations.jsonl", limit=safe_limit),
            "messages": _read_jsonl_records(source_dir / "messages.jsonl", limit=safe_limit, tail=True),
            "messageDays": _read_jsonl_records(source_dir / "message-days.jsonl", limit=safe_limit),
            "leadEvents": _read_jsonl_records(source_dir / "lead-events.jsonl", limit=safe_limit),
            "tasks": _read_jsonl_records(source_dir / "tasks.jsonl", limit=safe_limit),
        }
    return {
        **info,
        "sourceId": source_id,
        "source": source,
        "limit": safe_limit,
        "records": records,
    }


def _candidate_records_for_source(source_dir: Path, source: JsonRecord, safe_limit: int) -> list[JsonRecord]:
    records = _read_jsonl_records(source_dir / "conversations.jsonl", limit=safe_limit)
    if not records and str(source.get("category") or "") == "leads":
        records = _read_jsonl_records(source_dir / "contacts.jsonl", limit=safe_limit)
    if not records:
        records = _read_jsonl_records(source_dir / "messages.jsonl", limit=safe_limit, tail=True)
    return records


def _composio_connector_view(source_root: Path, source_id: str) -> JsonRecord | None:
    """Synthesize a connector_view-shaped record for a composio-<toolkit> dir.

    The composio inbound puller writes per-toolkit dirs (composio-gmail,
    composio-slack, etc.) that aren't in SOURCE_CONNECTION_BLUEPRINTS. The
    inbox builder iterates the static blueprints, so without this synthetic
    view those messages never reach /leads.
    """
    source_dir = _source_dir(source_root, source_id)
    if not source_dir.exists():
        return None
    record_counts = {
        file_name.removesuffix(".jsonl"): _count_jsonl(source_dir / file_name)
        for file_name in JSONL_FILES
    }
    if not any(record_counts.values()):
        return None
    toolkit = source_id.removeprefix("composio-") or source_id
    return {
        "id": source_id,
        "label": f"Composio — {toolkit}",
        "category": "messages",
        "state": "connected",
        "sourceExists": True,
        "sourceDir": str(source_dir),
        "sourcePath": str(source_dir / "source.json"),
        "statusPath": str(source_dir / "status.json"),
        "artifactsDir": str(source_dir / "artifacts"),
        "connectionType": "composio",
        "syncMode": "poll",
        "authStatus": None,
        "initializeBehavior": "composio_social_setup",
        "runMode": "server_inline",
        "ownerAgent": OWNER_BY_SOURCE.get("social", "Executive Assistant"),
        "enabledUiSurfaces": UI_BY_SOURCE.get("social", []),
        "connected": True,
        "importOnly": False,
        "blocked": False,
        "lastError": None,
        "nextOperatorStep": None,
        "lastCheckedAt": None,
        "recordCounts": record_counts,
        "prompt": "",
    }


def _discover_composio_views(source_root: Path) -> list[JsonRecord]:
    """List synthetic views for every composio-<toolkit> dir on disk."""
    if not source_root.exists():
        return []
    views: list[JsonRecord] = []
    for child in sorted(source_root.iterdir()):
        if not child.is_dir() or not child.name.startswith("composio-"):
            continue
        view = _composio_connector_view(source_root, child.name)
        if view is not None:
            views.append(view)
    return views
