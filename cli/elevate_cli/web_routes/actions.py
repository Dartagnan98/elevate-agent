"""Elevate background action routes for the dashboard."""

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException


SpawnElevateAction = Callable[[List[str], str], subprocess.Popen]
TailLines = Callable[[Path, int], List[str]]
IsPackagedRuntime = Callable[[], bool]
GitValue = Callable[..., str | None]


def create_actions_router(
    *,
    project_root: Path,
    action_log_dir: Path,
    action_log_files: Dict[str, str],
    action_procs: Dict[str, subprocess.Popen],
    spawn_elevate_action: SpawnElevateAction,
    tail_lines: TailLines,
    is_packaged_desktop_runtime: IsPackagedRuntime,
    git_value: GitValue,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build routes for background Elevate actions and update status."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.post("/api/elevate/update")
    async def update_elevate():
        """Kick off ``elevate update`` in the background."""
        if is_packaged_desktop_runtime():
            raise HTTPException(
                status_code=400,
                detail="Desktop app updates are managed by the built-in app updater.",
            )
        try:
            proc = spawn_elevate_action(["update"], "elevate-update")
        except Exception as exc:
            _log.exception("Failed to spawn elevate update")
            raise HTTPException(status_code=500, detail=f"Failed to start update: {exc}")
        return {
            "ok": True,
            "pid": proc.pid,
            "name": "elevate-update",
        }

    @router.get("/api/elevate/update/status")
    async def get_elevate_update_status(refresh: bool = False):
        """Return whether this checkout is behind the release branch."""
        try:
            if is_packaged_desktop_runtime():
                return {
                    "available": False,
                    "behind": None,
                    "ahead": 0,
                    "branch": None,
                    "checked_at": time.time(),
                    "command": "desktop updater",
                    "local": None,
                    "origin_url": None,
                    "repo_dir": str(project_root),
                    "upstream": None,
                    "error": "desktop_app_managed_update",
                }

            from elevate_cli.banner import (
                _resolve_repo_dir,
                check_for_updates,
                get_git_banner_state,
            )
            from elevate_cli.config import recommended_update_command

            repo_dir = _resolve_repo_dir()
            if repo_dir is None:
                return {
                    "available": False,
                    "behind": None,
                    "ahead": 0,
                    "branch": None,
                    "checked_at": time.time(),
                    "command": recommended_update_command(),
                    "local": None,
                    "origin_url": None,
                    "repo_dir": None,
                    "upstream": None,
                    "error": "not_git_install",
                }

            loop = asyncio.get_running_loop()
            behind = await loop.run_in_executor(
                None,
                lambda: check_for_updates(force=refresh, cache_seconds=5 * 60),
            )
            git_state = get_git_banner_state(repo_dir) or {}
            branch = git_value(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
            origin_url = git_value(repo_dir, "remote", "get-url", "origin")
            available = bool(behind and behind > 0)
            return {
                "available": available,
                "behind": behind,
                "ahead": int(git_state.get("ahead") or 0),
                "branch": branch,
                "checked_at": time.time(),
                "command": recommended_update_command(),
                "local": git_state.get("local"),
                "origin_url": origin_url,
                "repo_dir": str(repo_dir),
                "upstream": git_state.get("upstream"),
                "error": None,
            }
        except Exception as exc:
            _log.exception("GET /api/elevate/update/status failed")
            return {
                "available": False,
                "behind": None,
                "ahead": 0,
                "branch": None,
                "checked_at": time.time(),
                "command": "elevate update",
                "local": None,
                "origin_url": None,
                "repo_dir": None,
                "upstream": None,
                "error": str(exc),
            }

    @router.get("/api/actions/{name}/status")
    async def get_action_status(name: str, lines: int = 200):
        """Tail an action log and report whether the process is still running."""
        log_file_name = action_log_files.get(name)
        if log_file_name is None:
            raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

        log_path = action_log_dir / log_file_name
        tail = tail_lines(log_path, min(max(lines, 1), 2000))

        proc = action_procs.get(name)
        if proc is None:
            running = False
            exit_code: Optional[int] = None
            pid: Optional[int] = None
        else:
            exit_code = proc.poll()
            running = exit_code is None
            pid = proc.pid

        return {
            "name": name,
            "running": running,
            "exit_code": exit_code,
            "pid": pid,
            "lines": tail,
        }

    return router
