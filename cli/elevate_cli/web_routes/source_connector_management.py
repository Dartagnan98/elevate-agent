"""Source connector management routes."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SourceConnectorAction(BaseModel):
    action: str
    sourceId: str


def register_source_connector_management_routes(router: APIRouter, *, log: logging.Logger) -> None:
    @router.get("/api/source-connectors")
    async def get_source_connectors(include_prompts: bool = False):
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            return build_source_connectors_response(include_prompts=include_prompts)
        except Exception as exc:
            log.exception("GET /api/source-connectors failed")
            raise HTTPException(status_code=500, detail=f"Source connectors failed: {exc}")

    @router.post("/api/source-connectors")
    async def update_source_connector(body: SourceConnectorAction):
        if body.action not in {"scaffold", "refresh", "run-prompt"}:
            raise HTTPException(status_code=400, detail="Unsupported source connector action")
        try:
            from elevate_cli.source_connectors import (
                AGENT_SESSION_SOURCE_IDS,
                WIRED_SOURCE_IDS,
                build_source_connectors_response,
                connector_view as _connector_view,
                get_source_root_info,
                initialize_apple_messages_source,
                scaffold_source,
                source_prompt_for,
            )

            refresh_summary: dict[str, Any] | None = None
            run_result: dict[str, Any] | None = None
            run_error: str | None = None
            composio_summary: dict[str, Any] | None = None

            def _run_canonical(source_id: str) -> dict[str, Any] | None:
                """Fire the source's wired pull or scaffold its setup task."""
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

            if body.action == "refresh":
                refresh_summary = _run_canonical(body.sourceId)
            elif body.action == "run-prompt":
                prompt_text = source_prompt_for(body.sourceId)
                wired = body.sourceId in WIRED_SOURCE_IDS
                agent_session = body.sourceId in AGENT_SESSION_SOURCE_IDS
                if not agent_session:
                    try:
                        composio_summary = _run_canonical(body.sourceId)
                    except Exception as exc:
                        log.exception("run-prompt for %s failed", body.sourceId)
                        run_error = f"{type(exc).__name__}: {exc}"

                info = get_source_root_info()
                source_root = Path(info["sourceRoot"])
                view = _connector_view(source_root, body.sourceId) or {}

                counts = view.get("recordCounts") if isinstance(view, dict) else None
                counts = counts if isinstance(counts, dict) else {}
                contact_count = int(counts.get("contacts") or 0)
                conversation_count = int(counts.get("conversations") or 0)
                message_count = int(counts.get("messages") or 0)

                auth_status = view.get("authStatus") if isinstance(view, dict) else None
                last_error = view.get("lastError") if isinstance(view, dict) else None
                next_step = view.get("nextOperatorStep") if isinstance(view, dict) else None
                connected = bool(view.get("connected")) if isinstance(view, dict) else False

                outcome_kind: str
                outcome_message: str

                if run_error:
                    outcome_kind = "error"
                    outcome_message = f"Run failed: {run_error}"
                elif agent_session:
                    outcome_kind = "dispatched"
                    outcome_message = (
                        "Opening a visible agent session for this connector. "
                        "Watch the Chat tab for commands, browser steps when needed, verification, and output."
                    )
                elif body.sourceId == "social" and isinstance(composio_summary, dict):
                    total_new = composio_summary.get("total_new") or 0
                    total_fetched = composio_summary.get("total_fetched") or 0
                    outcome_kind = "ok"
                    outcome_message = f"Composio pulled {total_new} new / {total_fetched} fetched into Postgres."
                elif body.sourceId == "crm" and auth_status == "missing_secret":
                    outcome_kind = "needs_operator"
                    outcome_message = (
                        next_step
                        or "CRM API key not configured - add it in the CRM Integration panel, then click Run prompt again."
                    )
                elif body.sourceId == "crm":
                    outcome_kind = "ok" if connected else ("error" if last_error else "ok")
                    outcome_message = (
                        f"Pulled {contact_count} CRM contacts / {message_count} activities into Postgres."
                        if connected
                        else (last_error or "CRM sync ran - see Sources page for details.")
                    )
                elif body.sourceId == "apple-messages":
                    outcome_kind = "ok"
                    outcome_message = (
                        f"Apple Messages: {contact_count} contacts, {conversation_count} chats, {message_count} messages indexed."
                    )
                elif body.sourceId == "xposure-pcs":
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

                run_result = {
                    "sourceId": body.sourceId,
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
                        "sourceDir": view.get("sourceDir") if isinstance(view, dict) else None,
                    },
                    "next_action_for_operator": (
                        "The dashboard should navigate to /chat with this prompt seeded."
                        if agent_session
                        else None if wired else (
                            f"Open {view.get('sourceDir') if isinstance(view, dict) else 'data/sources/<source-id>'}/tasks.jsonl, "
                            "or dispatch to Jimmy via the dispatch-bridge."
                        )
                    ),
                }
                if isinstance(composio_summary, dict):
                    refresh_summary = composio_summary
            else:
                scaffold_source(body.sourceId)

            payload: dict[str, Any] = {
                "ok": True,
                **build_source_connectors_response(include_prompts=False),
            }
            if refresh_summary is not None:
                payload["refresh"] = refresh_summary
            if run_result is not None:
                payload["run"] = run_result
            return payload
        except Exception as exc:
            log.exception("POST /api/source-connectors failed")
            raise HTTPException(status_code=500, detail=f"Source connector update failed: {exc}")

    @router.get("/api/source-connectors/{source_id}/prompt")
    async def get_source_connector_prompt(source_id: str):
        try:
            from elevate_cli.source_connectors import source_prompt_for

            prompt = source_prompt_for(source_id)
            if not prompt:
                raise ValueError(f"Unknown source connector: {source_id}")
            return {"sourceId": source_id, "prompt": prompt}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            log.exception("GET /api/source-connectors/%s/prompt failed", source_id)
            raise HTTPException(status_code=500, detail=f"Source prompt failed: {exc}")

    @router.get("/api/source-connectors/{source_id}/records")
    async def get_source_connector_records(source_id: str, limit: int = 12):
        try:
            from elevate_cli.source_connectors import build_source_records_response

            return build_source_records_response(source_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            log.exception("GET /api/source-connectors/%s/records failed", source_id)
            raise HTTPException(status_code=500, detail=f"Source records failed: {exc}")
