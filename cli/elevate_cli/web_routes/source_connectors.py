"""Source connector, source inbox, and sender routes for the dashboard."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


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


class AppleMessagesDirections(BaseModel):
    inbound: bool | None = None
    outbound: bool | None = None


def create_source_connectors_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build routes for source connectors, source inbox, and sender controls."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    # ---------------------------------------------------------------------------
    # Real-estate source connectors and integration settings
    # ---------------------------------------------------------------------------

    _SOURCE_INBOX_ACTION_LIMIT = 500

    def _source_inbox_response(limit: int = _SOURCE_INBOX_ACTION_LIMIT):
        from elevate_cli.source_connectors import build_source_inbox_response
        from elevate_cli.data import db_source_inbox_response

        try:
            return db_source_inbox_response(limit=limit)
        except Exception:
            _log.exception(
                "db_source_inbox_response failed, falling back to JSONL source inbox"
            )
            return build_source_inbox_response(limit=limit)


    @router.get("/api/source-connectors")
    async def get_source_connectors(include_prompts: bool = False):
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            return build_source_connectors_response(include_prompts=include_prompts)
        except Exception as exc:
            _log.exception("GET /api/source-connectors failed")
            raise HTTPException(status_code=500, detail=f"Source connectors failed: {exc}")


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
    async def get_source_inbox(limit: int = 16):
        try:
            return _source_inbox_response(limit=limit)
        except Exception as exc:
            _log.exception("GET /api/source-inbox failed")
            raise HTTPException(status_code=500, detail=f"Source inbox failed: {exc}")


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

    @router.get("/api/source-inbox/apple-messages/directions")
    async def get_apple_messages_directions_route():
        try:
            from elevate_cli.source_connectors import get_apple_messages_directions

            return get_apple_messages_directions(None)
        except Exception as exc:
            _log.exception("GET apple-messages/directions failed")
            raise HTTPException(status_code=500, detail=f"Failed to read directions: {exc}")

    @router.post("/api/source-inbox/apple-messages/directions")
    async def set_apple_messages_directions_route(body: AppleMessagesDirections):
        try:
            from elevate_cli.source_connectors import (
                initialize_apple_messages_source,
                set_apple_messages_directions,
            )

            result = set_apple_messages_directions(
                inbound=body.inbound, outbound=body.outbound
            )
            # Re-run init so status.json (and the banner) reflect the new inbound
            # state immediately: turning inbound off writes a non-blocked paused
            # status; turning it on re-checks chat.db access. Best-effort.
            try:
                initialize_apple_messages_source()
            except Exception:
                _log.warning("apple-messages re-init after toggle failed", exc_info=True)
            return result
        except Exception as exc:
            _log.exception("POST apple-messages/directions failed")
            raise HTTPException(status_code=500, detail=f"Failed to set directions: {exc}")


    @router.get("/api/source-inbox/draft/{source_id}/{thread_id}/{task_id}/send-status")
    async def get_source_inbox_draft_send_status(source_id: str, thread_id: str, task_id: str):
        try:
            from elevate_cli import sender

            status = sender.status_for_task(source_id, thread_id, task_id)
            if status is None:
                return {"queued": False, "status": None}
            return {"queued": True, **status}
        except Exception as exc:
            _log.exception("GET /api/source-inbox/draft/.../send-status failed")
            raise HTTPException(status_code=500, detail=f"Send status lookup failed: {exc}")


    @router.get("/api/source-inbox/sent")
    async def get_source_inbox_sent(limit: int = 100, include_pending: bool = False):
        """Recent send_queue rows, newest first. Powers the /leads Sent tab.

        - `include_pending=false` (default): only delivered messages (status=sent).
        - `include_pending=true`: also surfaces queued/sending/retrying/failed
          so the operator can see what's mid-flight or stuck.
        """
        try:
            from elevate_cli import outreach_db

            statuses: tuple[str, ...]
            if include_pending:
                statuses = (
                    outreach_db.SEND_STATUS_SENT,
                    outreach_db.SEND_STATUS_SENDING,
                    outreach_db.SEND_STATUS_QUEUED,
                    outreach_db.SEND_STATUS_RETRYING,
                    outreach_db.SEND_STATUS_FAILED,
                )
            else:
                statuses = (outreach_db.SEND_STATUS_SENT,)
            items = outreach_db.list_recent_sends(statuses=statuses, limit=limit)
            return {"items": items, "limit": limit, "includePending": include_pending}
        except Exception as exc:
            _log.exception("GET /api/source-inbox/sent failed")
            raise HTTPException(status_code=500, detail=f"Sent list failed: {exc}")


    @router.post("/api/sender/tick")
    async def post_sender_tick(batch: int = 10):
        """Manual sender tick — useful for tests/admin. Cron calls this on schedule."""
        try:
            from elevate_cli import sender

            return sender.tick(batch=max(1, min(100, batch)))
        except Exception as exc:
            _log.exception("POST /api/sender/tick failed")
            raise HTTPException(status_code=500, detail=f"Sender tick failed: {exc}")


    @router.get("/api/sender/stats")
    async def get_sender_stats():
        try:
            from elevate_cli import outreach_db

            return {"queue": outreach_db.send_queue_stats()}
        except Exception as exc:
            _log.exception("GET /api/sender/stats failed")
            raise HTTPException(status_code=500, detail=f"Sender stats failed: {exc}")



    return router
