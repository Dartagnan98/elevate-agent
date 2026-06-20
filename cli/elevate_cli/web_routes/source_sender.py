"""Sender control routes for the dashboard."""

import logging

from fastapi import APIRouter, HTTPException


def register_sender_routes(router: APIRouter, *, log: logging.Logger) -> None:
    @router.post("/api/sender/tick")
    async def post_sender_tick(batch: int = 10):
        """Manual sender tick — useful for tests/admin. Cron calls this on schedule."""
        try:
            from elevate_cli import sender

            return sender.tick(batch=max(1, min(100, batch)))
        except Exception as exc:
            log.exception("POST /api/sender/tick failed")
            raise HTTPException(status_code=500, detail=f"Sender tick failed: {exc}")

    @router.get("/api/sender/stats")
    async def get_sender_stats():
        try:
            from elevate_cli import outreach_db

            return {"queue": outreach_db.send_queue_stats()}
        except Exception as exc:
            log.exception("GET /api/sender/stats failed")
            raise HTTPException(status_code=500, detail=f"Sender stats failed: {exc}")
