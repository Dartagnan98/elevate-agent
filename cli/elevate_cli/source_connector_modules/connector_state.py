"""Connector state and catalog lookup helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.source_catalog import SOURCE_CONNECTION_BLUEPRINTS
from elevate_cli.source_connector_modules.source_io import _source_dir


JsonRecord = dict[str, Any]


def _state_from_status(source_exists: bool, status: JsonRecord | None) -> str:
    if not source_exists and not status:
        return "not_configured"
    if not status:
        return "needs_operator"
    if status.get("blocked") is True:
        return "blocked"
    if status.get("connected") is True:
        return "connected"
    if status.get("import_only") is True:
        return "import_only"
    if str(status.get("last_error") or "").strip():
        return "error"
    return "needs_operator"


def _connector_recovery(
    *,
    source_id: str,
    state: str,
    owner_agent: str,
    last_error: str | None,
    next_operator_step: str | None,
) -> JsonRecord:
    """Classify the operator-facing recovery path for connector rows."""
    if state in {"connected", "import_only"}:
        return {
            "recoveryKind": "ready",
            "recoverySeverity": "none",
            "recoveryOwner": owner_agent,
            "recoveryAction": "",
        }
    if next_operator_step:
        action = next_operator_step
    elif source_id == "social":
        action = (
            "Open the Composio panel, verify the API key and connected accounts, "
            "then run the Social connector again."
        )
    elif state == "not_configured":
        action = "Open setup chat to create this connector's source files."
    elif state == "blocked":
        action = "Resolve the listed permission or credential blocker, then click Refresh."
    elif state == "error":
        action = "Review the last connector error, fix the upstream service or credential, then run again."
    else:
        action = "Open setup chat or copy the prompt for the owner agent to finish this connector."

    if state == "not_configured":
        kind = "missing_config"
        severity = "info"
    elif state == "blocked":
        kind = "operator_blocked"
        severity = "warning"
    elif state == "error":
        kind = "upstream_error"
        severity = "warning"
    else:
        kind = "needs_operator"
        severity = "info"

    return {
        "recoveryKind": kind,
        "recoverySeverity": severity,
        "recoveryOwner": owner_agent,
        "recoveryAction": action,
        "recoveryError": last_error or "",
    }


def _blueprint(source_id: str) -> JsonRecord | None:
    return next((item for item in SOURCE_CONNECTION_BLUEPRINTS if item["id"] == source_id), None)


def _mutable_source_exists(source_root: Path, source_id: str) -> bool:
    return bool(
        _blueprint(source_id)
        or (
            source_id.startswith("composio-")
            and "/" not in source_id
            and "\\" not in source_id
            and _source_dir(source_root, source_id).is_dir()
        )
    )
