"""Source inbox send-status and sent-message routes."""

import logging

from fastapi import APIRouter, HTTPException


def register_source_inbox_send_routes(router: APIRouter, *, log: logging.Logger) -> None:
    @router.get("/api/source-inbox/draft/{source_id}/{thread_id}/{task_id}/send-status")
    async def get_source_inbox_draft_send_status(source_id: str, thread_id: str, task_id: str):
        try:
            from elevate_cli import sender

            status = sender.status_for_task(source_id, thread_id, task_id)
            if status is None:
                return {"queued": False, "status": None}
            return {"queued": True, **status}
        except Exception as exc:
            log.exception("GET /api/source-inbox/draft/.../send-status failed")
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
            log.exception("GET /api/source-inbox/sent failed")
            raise HTTPException(status_code=500, detail=f"Sent list failed: {exc}")
