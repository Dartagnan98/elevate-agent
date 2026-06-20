"""Core source-inbox routes."""

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


class SourceInboxFavoriteAction(BaseModel):
    profileId: str
    favorite: bool
    contactId: str | None = None
    returnInbox: bool = True


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


def register_source_inbox_routes(router: APIRouter, *, log: logging.Logger) -> None:
    def _source_inbox_response(limit: int = _SOURCE_INBOX_ACTION_LIMIT, *, debug: bool = False):
        from elevate_cli.source_connectors import build_source_inbox_response
        from elevate_cli.data import db_source_inbox_response

        try:
            payload = db_source_inbox_response(limit=limit)
            return _with_source_inbox_debug(payload, read_path="db") if debug else payload
        except Exception as exc:
            log.exception(
                "db_source_inbox_response failed, falling back to JSONL source inbox"
            )
            payload = build_source_inbox_response(limit=limit)
            return (
                _with_source_inbox_debug(payload, read_path="jsonl", fallback_error=exc)
                if debug
                else payload
            )

    @router.get("/api/source-inbox")
    async def get_source_inbox(limit: int = 16, debug: bool = False):
        try:
            return _source_inbox_response(limit=limit, debug=debug)
        except Exception:
            log.exception("GET /api/source-inbox failed")
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
                log.exception(
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
            log.exception("GET /api/source-inbox/thread/%s/%s failed", source_id, thread_id)
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
            log.exception("POST /api/source-inbox/thread failed")
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
            log.exception("POST /api/source-inbox/profile failed")
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
            log.exception("POST /api/source-inbox/profile/favorite failed")
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
            log.exception("POST /api/source-inbox/draft failed")
            raise HTTPException(status_code=500, detail=f"Source draft update failed: {exc}")
