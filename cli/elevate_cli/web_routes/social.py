"""Social content engine routes."""

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SocialIdeaActionBody(BaseModel):
    action: str
    notes: Optional[str] = None
    edit: Optional[dict] = None


def _social_snapshot_path() -> Path:
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    workspace = (
        os.environ.get("ELEVATE_WORKSPACE_ID")
        or os.environ.get("ELEVATE_WORKSPACE")
        or "default"
    )
    return elevate_home / "state" / workspace / "social-snapshot.json"


def _social_metrics_path() -> Path:
    return _social_snapshot_path().parent / "social-metrics.jsonl"


def _social_tasks_path() -> Path:
    try:
        from elevate_cli.source_connectors import get_source_root_info
        info = get_source_root_info()
        root = Path(info.get("sourceRoot") or "")
        if root.parts:
            return root / "social" / "tasks.jsonl"
    except Exception:
        pass
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    return elevate_home / "tools" / "data" / "sources" / "social" / "tasks.jsonl"


def _read_social_tasks() -> list[dict]:
    path = _social_tasks_path()
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_social_tasks(records: list[dict]) -> None:
    path = _social_tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _load_social_fetcher(module_name: str):
    """Import a fetcher script from the installed social-content-engine skill."""
    elevate_home = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate")
    skill_root = elevate_home / "skills" / "social-media" / "social-content-engine" / "scripts"
    script_path = skill_root / f"{module_name}.py"
    if not script_path.exists():
        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "skills" / "social-content-engine" / "scripts" / f"{module_name}.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Fetcher script not found: {module_name}.py")
    spec = importlib.util.spec_from_file_location(f"_social_{module_name}", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load {module_name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def create_social_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build social content engine routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/social/snapshot")
    async def social_snapshot():
        path = _social_snapshot_path()
        if not path.exists():
            return {
                "exists": False,
                "snapshot_path": str(path),
                "message": "No snapshot yet. Run the social-content-engine skill or the aggregator script.",
            }
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.exception("GET /api/social/snapshot failed")
            raise HTTPException(status_code=500, detail=f"Snapshot read failed: {exc}")

    @router.get("/api/social/ideas")
    async def social_ideas(status: Optional[str] = None):
        try:
            all_tasks = _read_social_tasks()
            ideas = [t for t in all_tasks if str(t.get("task_type") or "").lower() == "social_post_idea"]
            if status:
                ideas = [t for t in ideas if str(t.get("status") or "").lower() == status.lower()]
            else:
                ideas = [t for t in ideas if str(t.get("status") or "").lower() in ("open", "pending_approval")]
            ideas.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            return {"items": ideas, "count": len(ideas)}
        except Exception as exc:
            _log.exception("GET /api/social/ideas failed")
            raise HTTPException(status_code=500, detail=f"Idea read failed: {exc}")

    @router.post("/api/social/ideas/{record_id}/action")
    async def social_idea_action(record_id: str, body: SocialIdeaActionBody):
        action = (body.action or "").lower().strip()
        if action not in {"approve", "reject", "edit"}:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        try:
            records = _read_social_tasks()
        except Exception as exc:
            _log.exception("POST /api/social/ideas action read failed")
            raise HTTPException(status_code=500, detail=f"Read failed: {exc}")

        from datetime import datetime, timezone
        found = False
        for r in records:
            if str(r.get("source_record_id") or "") != record_id:
                continue
            if str(r.get("task_type") or "").lower() != "social_post_idea":
                continue
            found = True
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            r["last_action_at"] = ts
            if body.notes:
                r.setdefault("notes", []).append({"ts": ts, "text": body.notes})
            if action == "approve":
                r["status"] = "approved"
                r["approval_required"] = False
            elif action == "reject":
                r["status"] = "rejected"
                r["approval_required"] = False
            elif action == "edit" and body.edit:
                for k in ("hook", "concept", "outline", "best_post_time", "platform", "format", "target_audience"):
                    if k in body.edit:
                        r[k] = body.edit[k]
            break

        if not found:
            raise HTTPException(status_code=404, detail=f"Idea {record_id} not found")

        try:
            _write_social_tasks(records)
        except Exception as exc:
            _log.exception("POST /api/social/ideas action write failed")
            raise HTTPException(status_code=500, detail=f"Write failed: {exc}")

        return {"ok": True, "record_id": record_id, "action": action}

    @router.get("/api/social/recent-posts")
    async def social_recent_posts(limit: int = 30):
        path = _social_metrics_path()
        if not path.exists():
            return {"items": [], "count": 0, "snapshot_path": str(path)}
        by_key: dict[tuple[str, str], dict] = {}
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    platform = row.get("platform")
                    post_id = row.get("post_id")
                    if not platform or not post_id:
                        continue
                    if str(row.get("media_type") or "").upper() == "ACCOUNT":
                        continue
                    key = (platform, post_id)
                    existing = by_key.get(key)
                    if not existing:
                        by_key[key] = row
                        continue
                    if (row.get("fetched_at") or "") > (existing.get("fetched_at") or ""):
                        preserved_raw = existing.get("raw") or row.get("raw")
                        by_key[key] = row
                        if preserved_raw and not by_key[key].get("raw"):
                            by_key[key]["raw"] = preserved_raw
                    else:
                        if row.get("raw") and not existing.get("raw"):
                            existing["raw"] = row.get("raw")
        except Exception as exc:
            _log.exception("GET /api/social/recent-posts failed")
            raise HTTPException(status_code=500, detail=f"Read failed: {exc}")

        items = list(by_key.values())
        items.sort(key=lambda x: x.get("posted_at") or x.get("fetched_at") or "", reverse=True)
        items = items[: max(1, min(limit, 1000))]
        return {"items": items, "count": len(items)}

    @router.post("/api/social/refresh")
    async def social_refresh(platform: Optional[str] = None, lookback_days: int = 730, max_posts: int = 200):
        requested = (platform or "").strip().lower()
        targets = [requested] if requested else ["instagram", "facebook", "youtube"]
        valid = {"instagram", "facebook", "youtube"}
        targets = [t for t in targets if t in valid]
        if not targets:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}")

        module_map = {
            "instagram": "instagram_insights",
            "facebook": "facebook_insights",
            "youtube": "youtube_analytics",
        }

        results: dict[str, Any] = {}

        def _run_one(p: str) -> dict:
            try:
                mod = _load_social_fetcher(module_map[p])
                return mod.fetch(lookback_days=lookback_days, max_posts=max_posts)
            except Exception as exc:
                _log.exception("social refresh %s failed", p)
                return {"platform": p, "status": "error", "error": str(exc)}

        for p in targets:
            results[p] = await asyncio.to_thread(_run_one, p)

        return {"ok": True, "results": results}

    return router
