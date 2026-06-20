"""Source connector, source inbox, and sender routes for the dashboard."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from elevate_cli.web_routes.source_apple_messages import register_apple_messages_routes
from elevate_cli.web_routes.source_inbox_sends import register_source_inbox_send_routes
from elevate_cli.web_routes.source_sender import register_sender_routes


class SourceConnectorAction(BaseModel):
    action: str
    sourceId: str


class SourceInboxThreadAction(BaseModel):
    action: str
    returnInbox: bool = True
    sourceId: str
    threadId: str


class SourceInboxDraftAction(BaseModel):
    action: str
    returnInbox: bool = True
    sourceId: str
    taskId: str
    draftText: str = ""


class SourceInboxProfileAction(BaseModel):
    profileId: str
    returnInbox: bool = True
    status: str | None = None


class SourceInboxFavoriteAction(BaseModel):
    profileId: str
    favorite: bool
    contactId: str | None = None
    returnInbox: bool = True


def create_source_connectors_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build routes for source connectors, source inbox, and sender controls."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    # ---------------------------------------------------------------------------
    # Real-estate source connectors and integration settings
    # ---------------------------------------------------------------------------

    _SOURCE_INBOX_ACTION_LIMIT = 500

    def _source_inbox_counts(payload: dict) -> dict:
        def _len(key: str) -> int:
            value = payload.get(key)
            return len(value) if isinstance(value, list) else 0

        return {
            "sources": _len("sources"),
            "profiles": _len("profiles"),
            "threads": _len("threads"),
            "drafts": _len("drafts"),
            "skippedDrafts": _len("skippedDrafts"),
            "privateSearchBuyers": _len("privateSearchBuyers"),
            "recordCounts": payload.get("recordCounts") or {},
            "hiddenCounts": payload.get("hiddenCounts") or {},
        }

    def _with_source_inbox_debug(
        payload: dict,
        *,
        read_path: str,
        fallback_error: Exception | None = None,
    ) -> dict:
        debug = {
            "readPath": read_path,
            "fallback": read_path == "jsonl",
            "counts": _source_inbox_counts(payload),
        }
        if fallback_error is not None:
            debug["fallbackError"] = type(fallback_error).__name__
            debug["fallbackErrorCode"] = "source_inbox_db_read_failed"
        return {**payload, "debug": debug}

    def _source_inbox_response(limit: int = _SOURCE_INBOX_ACTION_LIMIT, *, debug: bool = False):
        from elevate_cli.source_connectors import build_source_inbox_response
        from elevate_cli.data import db_source_inbox_response

        try:
            payload = db_source_inbox_response(limit=limit)
            return _with_source_inbox_debug(payload, read_path="db") if debug else payload
        except Exception as exc:
            _log.exception(
                "db_source_inbox_response failed, falling back to JSONL source inbox"
            )
            payload = build_source_inbox_response(limit=limit)
            return (
                _with_source_inbox_debug(payload, read_path="jsonl", fallback_error=exc)
                if debug
                else payload
            )


    @router.get("/api/source-connectors")
    async def get_source_connectors(include_prompts: bool = False):
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            return build_source_connectors_response(include_prompts=include_prompts)
        except Exception as exc:
            _log.exception("GET /api/source-connectors failed")
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
                        _log.exception("run-prompt for %s failed", body.sourceId)
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
            _log.exception("POST /api/source-connectors failed")
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
            _log.exception("GET /api/source-connectors/%s/prompt failed", source_id)
            raise HTTPException(status_code=500, detail=f"Source prompt failed: {exc}")


    @router.get("/api/source-connectors/{source_id}/records")
    async def get_source_connector_records(source_id: str, limit: int = 12):
        try:
            from elevate_cli.source_connectors import build_source_records_response

            return build_source_records_response(source_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/source-connectors/%s/records failed", source_id)
            raise HTTPException(status_code=500, detail=f"Source records failed: {exc}")


    @router.get("/api/source-inbox")
    async def get_source_inbox(limit: int = 16, debug: bool = False):
        try:
            return _source_inbox_response(limit=limit, debug=debug)
        except Exception:
            _log.exception("GET /api/source-inbox failed")
            raise HTTPException(status_code=500, detail="source_inbox_unavailable")


    @router.get("/api/source-inbox/thread/{source_id}/{thread_id}")
    async def get_source_inbox_thread(source_id: str, thread_id: str, limit: int = 200):
        try:
            from elevate_cli.source_connectors import build_thread_context_response
            from elevate_cli.data import db_thread_context_response

            # DB is the source of truth for lead cards (Lead Score, Notes,
            # Property Activity, Send History all key off contacts.id +
            # events.contact_id). The legacy JSONL reader pulls a thin
            # slice — last 4000 lead-events globally, contacts.jsonl rows
            # only — and silently returns empty cards for any Lofty lead
            # whose enrichment didn't make it into the tail window. Prefer
            # the DB path; fall back to JSONL only on real DB errors so
            # the drawer never blanks out.
            try:
                return db_thread_context_response(
                    source_id, thread_id, limit=limit
                )
            except ValueError:
                # Unknown source connector — propagate as 404.
                raise
            except Exception:
                _log.exception(
                    "db_thread_context_response failed, falling back to JSONL for %s/%s",
                    source_id,
                    thread_id,
                )
                return build_thread_context_response(
                    source_id, thread_id, limit=limit
                )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/source-inbox/thread/%s/%s failed", source_id, thread_id)
            raise HTTPException(status_code=500, detail=f"Thread context failed: {exc}")


    @router.post("/api/source-inbox/thread")
    async def update_source_inbox_thread(body: SourceInboxThreadAction):
        try:
            from elevate_cli.source_connectors import update_source_thread_state

            update_source_thread_state(
                body.sourceId,
                body.threadId,
                body.action,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/source-inbox/thread failed")
            raise HTTPException(status_code=500, detail=f"Source inbox update failed: {exc}")


    @router.post("/api/source-inbox/profile")
    async def update_source_inbox_profile(body: SourceInboxProfileAction):
        try:
            from elevate_cli.source_connectors import update_profile_state

            update_profile_state(
                body.profileId,
                body.status,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/source-inbox/profile failed")
            raise HTTPException(status_code=500, detail=f"Profile update failed: {exc}")


    @router.post("/api/source-inbox/profile/favorite")
    async def update_source_inbox_profile_favorite(body: SourceInboxFavoriteAction):
        try:
            from elevate_cli.source_connectors import update_profile_favorite

            update_profile_favorite(
                body.profileId,
                favorite=body.favorite,
                contact_id=body.contactId,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/source-inbox/profile/favorite failed")
            raise HTTPException(status_code=500, detail=f"Favorite update failed: {exc}")


    @router.post("/api/source-inbox/draft")
    async def update_source_inbox_draft(body: SourceInboxDraftAction):
        try:
            from elevate_cli.source_connectors import update_source_task_state

            update_source_task_state(
                body.sourceId,
                body.taskId,
                body.action,
                draft_text=body.draftText,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/source-inbox/draft failed")
            raise HTTPException(status_code=500, detail=f"Source draft update failed: {exc}")

    register_apple_messages_routes(router, log=_log)
    register_source_inbox_send_routes(router, log=_log)
    register_sender_routes(router, log=_log)

    return router
