"""Thread metadata routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class ThreadScoreBody(BaseModel):
    sourceId: str
    threadId: str
    score: int
    label: str
    reason: Optional[str] = None
    scoredBy: Optional[str] = None


class ThreadDeadBody(BaseModel):
    sourceId: str
    threadId: str
    reason: Optional[str] = None
    scoredBy: Optional[str] = None


def create_threads_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build thread metadata routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/threads/meta")
    async def list_thread_meta_endpoint(
        label: Optional[str] = None,
        minScore: Optional[int] = None,
        limit: int = 200,
    ):
        try:
            from elevate_cli import outreach_db

            return {
                "items": outreach_db.list_thread_meta(label=label, min_score=minScore, limit=limit),
                "stats": outreach_db.thread_meta_stats(),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/threads/meta failed")
            raise HTTPException(status_code=500, detail=f"List thread meta failed: {exc}")

    @router.get("/api/threads/meta/{source_id}/{thread_id}")
    async def get_thread_meta_endpoint(source_id: str, thread_id: str):
        try:
            from elevate_cli import outreach_db

            meta = outreach_db.get_thread_meta(source_id, thread_id)
            if meta is None:
                raise HTTPException(status_code=404, detail="not scored")
            return {"meta": meta}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/threads/meta/{source_id}/{thread_id} failed")
            raise HTTPException(status_code=500, detail=f"Get thread meta failed: {exc}")

    @router.post("/api/threads/score")
    async def score_thread_endpoint(body: ThreadScoreBody):
        try:
            from elevate_cli import outreach_db

            meta = outreach_db.upsert_thread_score(
                body.sourceId,
                body.threadId,
                score=body.score,
                label=body.label,
                reason=body.reason,
                scored_by=body.scoredBy,
            )
            return {"meta": meta}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/threads/score failed")
            raise HTTPException(status_code=500, detail=f"Score thread failed: {exc}")

    @router.post("/api/threads/dead")
    async def mark_thread_dead_endpoint(body: ThreadDeadBody):
        try:
            from elevate_cli import outreach_db

            meta = outreach_db.mark_thread_dead(
                body.sourceId,
                body.threadId,
                reason=body.reason,
                scored_by=body.scoredBy,
            )
            return {"meta": meta}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/threads/dead failed")
            raise HTTPException(status_code=500, detail=f"Mark dead failed: {exc}")

    return router
