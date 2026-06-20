"""Session list and search routes."""

import logging
import re
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException


GetSessionDb = Callable[[], Any]
PlatformChatSources = Callable[[], list[str]]
MarkSessionActivity = Callable[[list[dict[str, Any]], float], None]
SessionListPayload = Callable[[dict[str, Any]], dict[str, Any]]


def create_sessions_router(
    *,
    get_session_db: GetSessionDb,
    platform_chat_sources: PlatformChatSources,
    mark_session_activity: MarkSessionActivity,
    session_list_payload: SessionListPayload,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build session list and search routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/sessions")
    async def get_sessions(
        limit: int = 20,
        offset: int = 0,
        include_total: bool = True,
        include_details: bool = False,
    ):
        try:
            limit = max(1, min(int(limit or 20), 200))
            offset = max(0, int(offset or 0))
            if not include_details:
                try:
                    from elevate_cli.data.chat_sessions import (
                        list_session_summaries,
                        session_count as pg_session_count,
                    )

                    hidden = platform_chat_sources()
                    sessions = list_session_summaries(
                        limit=limit, offset=offset, exclude_sources=hidden
                    )
                    total = (
                        pg_session_count(exclude_sources=hidden)
                        if include_total
                        else offset + len(sessions)
                    )
                    now = time.time()
                    mark_session_activity(sessions, now)
                    return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
                except Exception:
                    _log.debug("PG slim session list failed, falling back to SessionDB", exc_info=True)

            db = get_session_db()
            try:
                hidden = platform_chat_sources()
                sessions = db.list_sessions_rich(
                    limit=limit, offset=offset, exclude_sources=hidden
                )
                total = (
                    db.session_count(exclude_sources=hidden)
                    if include_total
                    else offset + len(sessions)
                )
                now = time.time()
                mark_session_activity(sessions, now)
                if not include_details:
                    sessions = [session_list_payload(s) for s in sessions]
                return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
            finally:
                db.close()
        except Exception:
            _log.exception("GET /api/sessions failed")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get("/api/sessions/search")
    async def search_sessions(q: str = "", limit: int = 20):
        """Full-text search across session message content using FTS5."""
        if not q or not q.strip():
            return {"results": []}
        try:
            db = get_session_db()
            try:
                terms = []
                for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                    if token.startswith('"') or token.endswith("*"):
                        terms.append(token)
                    else:
                        terms.append(token + "*")
                prefix_query = " ".join(terms)
                matches = db.search_messages(query=prefix_query, limit=limit)
                hidden = set(platform_chat_sources())
                seen: dict = {}
                internal_prefixes = (
                    "[CONTEXT COMPACTION",
                    "[Your latest Plan panel plan was preserved",
                    "[Your active task list was preserved",
                    "[RECENT AUTONOMOUS ACTIVITY",
                )
                for m in matches:
                    if str(m.get("source") or "") in hidden:
                        continue
                    if m.get("role") == "user" and str(m.get("content") or "").lstrip().startswith(internal_prefixes):
                        continue
                    sid = m["session_id"]
                    if sid not in seen:
                        seen[sid] = {
                            "session_id": sid,
                            "snippet": m.get("snippet", ""),
                            "role": m.get("role"),
                            "source": m.get("source"),
                            "model": m.get("model"),
                            "session_started": m.get("session_started"),
                        }
                return {"results": list(seen.values())}
            finally:
                db.close()
        except Exception:
            _log.exception("GET /api/sessions/search failed")
            raise HTTPException(status_code=500, detail="Search failed")

    return router
