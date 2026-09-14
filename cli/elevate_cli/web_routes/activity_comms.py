"""Fleet activity and Comms routes."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


FsCacheGet = Callable[[str], Any]
FsCachePut = Callable[[str, Any, float], None]


class _CommsMessageCreateBody(BaseModel):
    fromAgentId: Optional[str] = None
    from_agent_id: Optional[str] = None
    toAgentId: Optional[str] = None
    to_agent_id: Optional[str] = None
    agent: Optional[str] = None
    text: str
    priority: Optional[str] = None
    replyTo: Optional[str] = None
    reply_to: Optional[str] = None
    runNow: Optional[bool] = None
    run_now: Optional[bool] = None


def _activity_text(value: Any) -> Optional[str]:
    """Convert activity payload fragments into compact display text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_activity_text(item) for item in value]
        text = "; ".join(part for part in parts if part)
        return text or None
    if isinstance(value, dict):
        for key in (
            "summary",
            "attention_summary",
            "message",
            "title",
            "event",
            "category",
            "status",
        ):
            text = _activity_text(value.get(key))
            if text:
                return text
        try:
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            return None
    return str(value)


def _build_activity_items(log: logging.Logger) -> List[Dict[str, Any]]:
    """Scan account data for the fleet activity feed."""
    from elevate_constants import get_account_data_dir

    items: List[Dict[str, Any]] = []
    base = get_account_data_dir() / "heartbeats"
    try:
        runs_by_surface: Dict[str, List[Dict[str, Any]]] = {}
        try:
            from elevate_cli.data import connect as _runs_connect
            from elevate_cli.data import surface_state as _runs_state

            with _runs_connect() as _conn:
                for run in _runs_state.list_runs(_conn, limit=400):
                    bucket = runs_by_surface.setdefault(
                        str(run.get("surface") or "") or "system", []
                    )
                    if len(bucket) < 30:
                        bucket.append(run)
        except Exception:
            log.warning("activity: surface_runs unavailable", exc_info=True)
            runs_by_surface = {}
        for surface, runs in runs_by_surface.items():
            for run in runs:
                rec = run.get("record") if isinstance(run.get("record"), dict) else {}
                items.append({
                    "kind": "heartbeat",
                    "agent": surface,
                    "ts": _activity_text(rec.get("ran_at") or run.get("ran_at")) or "",
                    "title": _activity_text(
                        run.get("summary") or rec.get("summary") or rec.get("did")
                    ) or "ran",
                    "detail": _activity_text(rec.get("found") or rec.get("checked")),
                    "status": _activity_text(run.get("status")) or "ok",
                })
        if base.is_dir():
            for sdir in base.iterdir():
                if not sdir.is_dir():
                    continue
                surface = sdir.name
                if runs_by_surface.get(surface):
                    continue
                hist = sdir / "history"
                if not hist.is_dir():
                    continue
                for f in sorted(hist.glob("*.json"), reverse=True)[:30]:
                    try:
                        rec = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    items.append({
                        "kind": "heartbeat",
                        "agent": surface,
                        "ts": _activity_text(rec.get("ran_at") or f.stem) or f.stem,
                        "title": _activity_text(rec.get("summary") or rec.get("did")) or "ran",
                        "detail": _activity_text(rec.get("found") or rec.get("checked")),
                        "status": "ok",
                    })
        try:
            from cron.jobs import list_jobs

            for j in list_jobs(include_disabled=True):
                lr = j.get("last_run_at")
                if not lr:
                    continue
                o = j.get("origin") or {}
                items.append({
                    "kind": "cron",
                    "agent": _activity_text(o.get("surface") or j.get("agent")) or "system",
                    "ts": _activity_text(lr) or "",
                    "title": _activity_text(j.get("name")) or "job",
                    "detail": _activity_text(j.get("last_summary")),
                    "status": _activity_text(j.get("last_status")) or "ok",
                })
        except Exception:
            log.warning("activity: cron last-runs unavailable", exc_info=True)
        try:
            from elevate_cli.data.paths import data_root

            try:
                from elevate_cli.data import connect as _data_connect
                from elevate_cli.data import surface_state as _surface_state

                with _data_connect() as _conn:
                    activity_rows = _surface_state.list_activity(_conn, limit=120)
            except Exception:
                log.warning("activity: surface_activity unavailable", exc_info=True)
                activity_rows = []
            for rec in activity_rows:
                meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
                items.append({
                    "kind": _activity_text(meta.get("kind")) or "agent_activity",
                    "agent": _activity_text(rec.get("agent")) or "system",
                    "ts": _activity_text(rec.get("at")),
                    "title": _activity_text(rec.get("event") or meta.get("category"))
                    or "Agent activity",
                    "detail": _activity_text(rec.get("message") or meta.get("metadata")),
                    "status": _activity_text(meta.get("severity")) or "info",
                })

            pressure_log = data_root() / "agent_context_pressure.jsonl"
            if pressure_log.exists():
                lines = pressure_log.read_text(encoding="utf-8").splitlines()[-80:]
                for line in lines:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    items.append({
                        "kind": _activity_text(rec.get("kind")) or "context",
                        "agent": _activity_text(rec.get("agent")) or "system",
                        "ts": _activity_text(rec.get("ts")),
                        "title": _activity_text(rec.get("title")) or "Context pressure",
                        "detail": _activity_text(rec.get("detail")),
                        "status": _activity_text(rec.get("status")) or "warning",
                    })
        except Exception:
            log.warning("activity: context pressure log unavailable", exc_info=True)
    except Exception:
        log.exception("activity scan failed; returning partial results")
    return items


def create_activity_comms_router(
    *,
    fs_cache_get: FsCacheGet,
    fs_cache_put: FsCachePut,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/activity")
    def get_activity(limit: int = 100, agent: Optional[str] = None):
        try:
            items = fs_cache_get("activity")
            if items is None:
                items = _build_activity_items(_log)
                fs_cache_put("activity", items, 3.0)
            result = list(items)
            if agent:
                result = [i for i in result if i.get("agent") == agent]
            result.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
            return {"items": result[: max(1, min(limit, 300))]}
        except Exception as exc:
            _log.exception("GET /api/activity failed")
            raise HTTPException(status_code=500, detail=f"Activity failed: {exc}")

    @router.get("/api/comms/delivery-channels")
    def get_comms_delivery_channels():
        try:
            from gateway.channel_directory import load_directory

            directory = load_directory()
            out: List[Dict[str, Any]] = []
            for platform, channels in (directory.get("platforms") or {}).items():
                for ch in channels or []:
                    if not ch.get("id"):
                        continue
                    out.append({
                        "platform": platform,
                        "id": ch["id"],
                        "name": ch.get("name") or ch["id"],
                        "type": ch.get("type"),
                    })
            return {"channels": out, "updated_at": directory.get("updated_at")}
        except Exception as exc:
            _log.exception("GET /api/comms/delivery-channels failed")
            raise HTTPException(status_code=500, detail=f"Comms delivery channels failed: {exc}")

    @router.get("/api/comms/feed")
    def get_comms_feed(
        limit: int = 200,
        search: Optional[str] = None,
        agent: Optional[str] = None,
    ):
        try:
            from elevate_cli.data import connect, list_agent_comms_messages

            with connect() as conn:
                return list_agent_comms_messages(
                    conn,
                    agent_id=agent,
                    search=search,
                    limit=limit,
                )
        except Exception as exc:
            _log.exception("GET /api/comms/feed failed")
            raise HTTPException(status_code=500, detail=f"Comms feed failed: {exc}")

    @router.get("/api/comms/channels")
    def get_comms_channels(
        include_archived: bool = False,
        limit: int = 200,
    ):
        try:
            from elevate_cli.data import connect, list_agent_comms_channels

            with connect() as conn:
                return list_agent_comms_channels(
                    conn,
                    include_archived=include_archived,
                    limit=limit,
                )
        except Exception as exc:
            _log.exception("GET /api/comms/channels failed")
            raise HTTPException(status_code=500, detail=f"Comms channels failed: {exc}")

    @router.get("/api/comms/channel/{pair}")
    def get_comms_channel(pair: str, limit: int = 200):
        try:
            from elevate_cli.data import connect, get_agent_comms_channel

            with connect() as conn:
                return get_agent_comms_channel(conn, pair, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/comms/channel/%s failed", pair)
            raise HTTPException(status_code=500, detail=f"Comms channel failed: {exc}")

    @router.post("/api/messages/send")
    @router.post("/api/comms/messages")
    def create_comms_message(body: _CommsMessageCreateBody):
        try:
            from elevate_cli.data import connect, create_agent_comms_message

            from_id = body.fromAgentId or body.from_agent_id or "human-web"
            to_id = body.toAgentId or body.to_agent_id or body.agent
            if not to_id:
                raise HTTPException(status_code=400, detail="toAgentId or agent is required")
            with connect() as conn:
                return create_agent_comms_message(
                    conn,
                    from_agent_id=from_id,
                    to_agent_id=to_id,
                    text=body.text,
                    priority=body.priority or "normal",
                    reply_to=body.replyTo or body.reply_to,
                    run_now=bool(body.runNow or body.run_now),
                    actor="human:web" if str(from_id).strip().lower() in {"human", "human-web"} else from_id,
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/comms/messages failed")
            raise HTTPException(status_code=500, detail=f"Comms message failed: {exc}")

    return router
