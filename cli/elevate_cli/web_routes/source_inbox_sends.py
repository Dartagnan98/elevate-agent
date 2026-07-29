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

    @router.get("/api/source-inbox/not-sent")
    async def get_source_inbox_not_sent(limit: int = 100):
        """send_queue rows that did NOT get delivered — failed, skipped (e.g. no
        phone / safety hold), or stuck retrying. Powers the /leads 'Didn't Send'
        tab so silently-dropped approvals don't vanish off the board."""
        try:
            from elevate_cli import outreach_db

            statuses = (
                outreach_db.SEND_STATUS_FAILED,
                outreach_db.SEND_STATUS_SKIPPED,
                outreach_db.SEND_STATUS_RETRYING,
            )
            items = outreach_db.list_recent_sends(statuses=statuses, limit=limit)
            return {"items": items, "limit": limit}
        except Exception as exc:
            log.exception("GET /api/source-inbox/not-sent failed")
            raise HTTPException(status_code=500, detail=f"Not-sent list failed: {exc}")

    @router.post("/api/source-inbox/retry-send/{queue_id}")
    async def retry_source_inbox_send(queue_id: str):
        """Re-queue a failed/skipped send: re-resolve the contact's CURRENT phone
        into the payload (it may have been blank/duplicate before), flip status
        back to queued, then tick the sender. Powers the 'Retry' button."""
        try:
            import json as _json
            from elevate_cli import outreach_db, sender

            with outreach_db.connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT payload_json FROM send_queue WHERE id=%s", (queue_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="send not found")
                payload = _json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
                cid = payload.get("contact_id")
                if cid:
                    cur.execute("SELECT primary_phone FROM contacts WHERE id=%s", (cid,))
                    c = cur.fetchone()
                    if c and c[0]:
                        payload["phone"] = c[0]
                cur.execute(
                    "UPDATE send_queue SET payload_json=%s, status=%s, next_retry_at=NULL, last_error=NULL, attempts=0 WHERE id=%s",
                    (_json.dumps(payload), outreach_db.SEND_STATUS_QUEUED, queue_id),
                )
                conn.commit()
            tick = sender.tick(batch=5)
            return {"requeued": True, "phone": payload.get("phone"), "tick": tick}
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("POST /api/source-inbox/retry-send failed")
            raise HTTPException(status_code=500, detail=f"Retry failed: {exc}")
