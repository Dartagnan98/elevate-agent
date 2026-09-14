"""Source connector action helpers for dashboard routes."""

import logging
from pathlib import Path
from typing import Any


def _run_canonical_source(source_id: str) -> dict[str, Any] | None:
    """Fire the source's wired pull or scaffold its setup task."""
    from elevate_cli.source_connectors import (
        initialize_apple_messages_source,
        scaffold_source,
    )

    if source_id == "apple-messages":
        initialize_apple_messages_source()
        return None
    if source_id == "crm":
        scaffold_source("crm")
        return None
    if source_id == "social":
        from elevate_cli import composio_inbound

        return composio_inbound.pull_all_supported()
    scaffold_source(source_id)
    return None


def _connector_counts(view: dict[str, Any]) -> tuple[int, int, int]:
    counts = view.get("recordCounts") if isinstance(view, dict) else None
    counts = counts if isinstance(counts, dict) else {}
    return (
        int(counts.get("contacts") or 0),
        int(counts.get("conversations") or 0),
        int(counts.get("messages") or 0),
    )


def _run_prompt_action(
    source_id: str,
    *,
    log: logging.Logger,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from elevate_cli.source_connectors import (
        AGENT_SESSION_SOURCE_IDS,
        WIRED_SOURCE_IDS,
        connector_view as _connector_view,
        get_source_root_info,
        source_prompt_for,
    )

    run_error: str | None = None
    composio_summary: dict[str, Any] | None = None

    prompt_text = source_prompt_for(source_id)
    wired = source_id in WIRED_SOURCE_IDS
    agent_session = source_id in AGENT_SESSION_SOURCE_IDS
    if not agent_session:
        try:
            composio_summary = _run_canonical_source(source_id)
        except Exception as exc:
            log.exception("run-prompt for %s failed", source_id)
            run_error = f"{type(exc).__name__}: {exc}"

    info = get_source_root_info()
    source_root = Path(info["sourceRoot"])
    view = _connector_view(source_root, source_id) or {}

    contact_count, conversation_count, message_count = _connector_counts(view)

    auth_status = view.get("authStatus") if isinstance(view, dict) else None
    last_error = view.get("lastError") if isinstance(view, dict) else None
    next_step = view.get("nextOperatorStep") if isinstance(view, dict) else None
    connected = bool(view.get("connected")) if isinstance(view, dict) else False

    if run_error:
        outcome_kind = "error"
        outcome_message = f"Run failed: {run_error}"
    elif agent_session:
        outcome_kind = "dispatched"
        outcome_message = (
            "Opening a visible agent session for this connector. "
            "Watch the Chat tab for commands, browser steps when needed, verification, and output."
        )
    elif source_id == "social" and isinstance(composio_summary, dict):
        total_new = composio_summary.get("total_new") or 0
        total_fetched = composio_summary.get("total_fetched") or 0
        outcome_kind = "ok"
        outcome_message = f"Composio pulled {total_new} new / {total_fetched} fetched into Postgres."
    elif source_id == "crm" and auth_status == "missing_secret":
        outcome_kind = "needs_operator"
        outcome_message = (
            next_step
            or "CRM API key not configured - add it in the CRM Integration panel, then click Run prompt again."
        )
    elif source_id == "crm":
        outcome_kind = "ok" if connected else ("error" if last_error else "ok")
        outcome_message = (
            f"Pulled {contact_count} CRM contacts / {message_count} activities into Postgres."
            if connected
            else (last_error or "CRM sync ran - see Sources page for details.")
        )
    elif source_id == "apple-messages":
        outcome_kind = "ok"
        outcome_message = (
            f"Apple Messages: {contact_count} contacts, {conversation_count} chats, {message_count} messages indexed."
        )
    elif source_id == "xposure-pcs":
        outcome_kind = "ok" if connected else ("error" if last_error else "needs_operator")
        outcome_message = (
            f"MLS Buyer Searches: {contact_count} buyer contacts pulled into Postgres."
            if connected
            else (last_error or next_step or "Xposure PCS sync ran - see Sources page for details.")
        )
    elif wired:
        outcome_kind = "ok"
        outcome_message = "Pulled inline - Postgres updated."
    else:
        outcome_kind = "dispatched"
        source_dir = view.get("sourceDir") if isinstance(view, dict) else None
        outcome_message = (
            f"Agent setup task scaffolded at {source_dir}/tasks.jsonl. "
            "Open /tasks or dispatch to Jimmy to build the connector."
        )

    source_dir = view.get("sourceDir") if isinstance(view, dict) else None
    run_result = {
        "sourceId": source_id,
        "wired": wired,
        "execution": (
            "agent_session_seed"
            if agent_session
            else ("server_inline" if wired else "agent_task_dispatched")
        ),
        "prompt": prompt_text,
        "outcome": {
            "kind": outcome_kind,
            "message": outcome_message,
            "recordCounts": {
                "contacts": contact_count,
                "conversations": conversation_count,
                "messages": message_count,
            },
            "lastError": last_error,
            "authStatus": auth_status,
            "nextOperatorStep": next_step,
            "sourceDir": source_dir,
        },
        "next_action_for_operator": (
            "The dashboard should navigate to /chat with this prompt seeded."
            if agent_session
            else None
            if wired
            else (
                f"Open {source_dir if source_dir else 'data/sources/<source-id>'}/tasks.jsonl, "
                "or dispatch to Jimmy via the dispatch-bridge."
            )
        ),
    }
    return run_result, composio_summary


def run_source_connector_action(
    action: str,
    source_id: str,
    *,
    log: logging.Logger,
) -> dict[str, Any]:
    """Run a source connector management action and return optional payload extras."""
    from elevate_cli.source_connectors import scaffold_source

    result: dict[str, Any] = {}

    if action == "refresh":
        refresh_summary = _run_canonical_source(source_id)
        if refresh_summary is not None:
            result["refresh"] = refresh_summary
        return result

    if action == "run-prompt":
        run_result, composio_summary = _run_prompt_action(source_id, log=log)
        result["run"] = run_result
        if isinstance(composio_summary, dict):
            result["refresh"] = composio_summary
        return result

    scaffold_source(source_id)
    return result
