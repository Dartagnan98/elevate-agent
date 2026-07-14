"""Source inbox send-status and sent-message routes."""

import json
import logging
from datetime import datetime, timezone

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

        - `include_pending=false` (default): only rows marked sent. This is a
          dispatcher-acceptance state, not recipient-delivery proof.
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
        """send_queue rows that did not reach dispatcher acceptance.

        Explicitly skipped approval drafts remain in the approval work queue,
        where Undo restores them for review; they must never become a direct
        send path through the /leads 'Didn't Send' tab.
        """
        try:
            from elevate_cli import outreach_db

            statuses = (
                outreach_db.SEND_STATUS_FAILED,
                outreach_db.SEND_STATUS_RETRYING,
            )
            items = outreach_db.list_recent_sends(statuses=statuses, limit=limit)
            return {"items": items, "limit": limit}
        except Exception as exc:
            log.exception("GET /api/source-inbox/not-sent failed")
            raise HTTPException(status_code=500, detail=f"Not-sent list failed: {exc}")

    @router.post("/api/source-inbox/retry-send/{queue_id}")
    def retry_source_inbox_send(queue_id: str):
        """Retry exactly one failed send with current recipient data.

        The queue payload stores delivery fields under ``payload.recipient``.
        Claim the selected row as ``sending`` before dispatch so a global sender
        tick cannot race this explicit operator action or drain a different row.
        The response reports the dispatcher's actual terminal/retry state; it
        never upgrades a queue action into an unverified delivery claim.
        """
        try:
            from elevate_cli import outreach_db, sender

            with outreach_db.connect() as conn:
                with outreach_db.transaction(conn):
                    row = conn.execute(
                        "SELECT * FROM send_queue WHERE id=? FOR UPDATE",
                        (queue_id,),
                    ).fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail="send not found")

                    status = str(row["status"] or "")
                    if status != outreach_db.SEND_STATUS_FAILED:
                        raise HTTPException(
                            status_code=409,
                            detail=f"send is {status or 'unknown'}; only failed sends can be retried",
                        )

                    channel = str(row["channel"] or "").strip().lower()
                    if (
                        not sender.sandbox_enabled()
                        and sender.is_apple_messages_channel(channel)
                        and not sender.apple_messages_outbound_enabled()
                    ):
                        # Refuse before touching payload, attempts, status, or
                        # timestamps. Turning outbound off must make Retry a
                        # true no-op against the selected failed row.
                        raise HTTPException(
                            status_code=409,
                            detail=sender.APPLE_MESSAGES_OUTBOUND_DISABLED_ERROR,
                        )

                    raw_payload = row["payload_json"]
                    try:
                        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    except (TypeError, ValueError) as exc:
                        raise HTTPException(status_code=422, detail="send payload is not valid JSON") from exc
                    if not isinstance(payload, dict):
                        raise HTTPException(status_code=422, detail="send payload must be an object")

                    raw_recipient = payload.get("recipient")
                    if raw_recipient is not None and not isinstance(raw_recipient, dict):
                        raise HTTPException(status_code=422, detail="send recipient must be an object")
                    recipient = dict(raw_recipient or {})
                    contact_id = str(
                        recipient.get("contact_id") or payload.get("contact_id") or ""
                    ).strip()
                    contact_found = False
                    if contact_id:
                        contact = conn.execute(
                            "SELECT primary_phone, primary_email FROM contacts WHERE id=?",
                            (contact_id,),
                        ).fetchone()
                        if contact:
                            contact_found = True
                            current_phone = str(contact["primary_phone"] or "").strip()
                            current_email = str(contact["primary_email"] or "").strip()
                            # A linked contact is authoritative. Clearing a
                            # number/email in the contact must also clear stale
                            # queue data instead of sending to the old value.
                            recipient["phone"] = current_phone
                            recipient["email"] = current_email
                    payload["recipient"] = recipient

                    if (
                        sender.is_apple_messages_channel(channel)
                        and contact_id
                        and not contact_found
                    ):
                        raise HTTPException(
                            status_code=409,
                            detail="linked contact no longer exists; choose a valid contact before retrying",
                        )
                    if sender.is_apple_messages_channel(channel) and not str(
                        recipient.get("phone") or ""
                    ).strip():
                        raise HTTPException(
                            status_code=409,
                            detail="contact still has no phone number; update the contact before retrying",
                        )

                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        UPDATE send_queue
                           SET payload_json=?, status=?, next_retry_at=NULL,
                               last_error=NULL, attempts=0, updated_at=?
                         WHERE id=?
                        """,
                        (
                            json.dumps(payload, ensure_ascii=False),
                            outreach_db.SEND_STATUS_SENDING,
                            now,
                            queue_id,
                        ),
                    )
                    claimed_row = conn.execute(
                        "SELECT * FROM send_queue WHERE id=?",
                        (queue_id,),
                    ).fetchone()

            claimed = outreach_db._row_to_send(claimed_row)
            if claimed is None:
                raise HTTPException(status_code=500, detail="retry claim disappeared")
            result = sender.dispatch_one(claimed) or claimed
            result_status = str(result.get("status") or outreach_db.SEND_STATUS_SENDING)
            return {
                "requeued": True,
                "id": queue_id,
                "status": result_status,
                "phone": recipient.get("phone"),
                "lastError": result.get("lastError"),
                "providerMessageId": result.get("providerMessageId"),
            }
        except HTTPException:
            raise
        except Exception as exc:
            try:
                from elevate_cli import outreach_db

                outreach_db.mark_failed(queue_id, error=f"retry dispatch failed: {exc}")
            except Exception:
                pass
            log.exception("POST /api/source-inbox/retry-send failed")
            raise HTTPException(status_code=500, detail=f"Retry failed: {exc}")
