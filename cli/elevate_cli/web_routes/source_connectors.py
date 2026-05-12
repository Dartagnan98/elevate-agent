"""Source connector, source inbox, and sender routes for the dashboard."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SourceInboxThreadAction(BaseModel):
    action: str
    sourceId: str
    threadId: str


class SourceInboxDraftAction(BaseModel):
    action: str
    sourceId: str
    taskId: str
    draftText: str = ""


def create_source_connectors_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build routes for source connectors, source inbox, and sender controls."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    # ---------------------------------------------------------------------------
    # Real-estate source connectors and integration settings
    # ---------------------------------------------------------------------------


    @router.get("/api/source-connectors")
    async def get_source_connectors():
        try:
            from elevate_cli.source_connectors import build_source_connectors_response

            return build_source_connectors_response()
        except Exception as exc:
            _log.exception("GET /api/source-connectors failed")
            raise HTTPException(status_code=500, detail=f"Source connectors failed: {exc}")


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
            from elevate_cli.source_connectors import build_source_inbox_response
            from elevate_cli.data import db_source_inbox_response, shadow_read

            # Sprint 2: db_fn is wired. Production stays on legacy until
            # ELEVATE_DATA_PRIMARY=db flips after a clean parity window.
            return shadow_read(
                endpoint="GET /api/source-inbox",
                request_args={"limit": limit},
                jsonl_fn=lambda: build_source_inbox_response(limit=limit),
                db_fn=lambda: db_source_inbox_response(limit=limit),
            )
        except Exception as exc:
            _log.exception("GET /api/source-inbox failed")
            raise HTTPException(status_code=500, detail=f"Source inbox failed: {exc}")


    @router.get("/api/source-inbox/thread/{source_id}/{thread_id}")
    async def get_source_inbox_thread(source_id: str, thread_id: str, limit: int = 200):
        try:
            from elevate_cli.source_connectors import build_thread_context_response
            from elevate_cli.data import db_thread_context_response, shadow_read

            return shadow_read(
                endpoint="GET /api/source-inbox/thread",
                request_args={"sourceId": source_id, "threadId": thread_id, "limit": limit},
                jsonl_fn=lambda: build_thread_context_response(source_id, thread_id, limit=limit),
                db_fn=lambda: db_thread_context_response(source_id, thread_id, limit=limit),
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

            return update_source_thread_state(body.sourceId, body.threadId, body.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/source-inbox/thread failed")
            raise HTTPException(status_code=500, detail=f"Source inbox update failed: {exc}")


    @router.post("/api/source-inbox/draft")
    async def update_source_inbox_draft(body: SourceInboxDraftAction):
        try:
            from elevate_cli.source_connectors import update_source_task_state

            return update_source_task_state(
                body.sourceId,
                body.taskId,
                body.action,
                draft_text=body.draftText,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/source-inbox/draft failed")
            raise HTTPException(status_code=500, detail=f"Source draft update failed: {exc}")


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
