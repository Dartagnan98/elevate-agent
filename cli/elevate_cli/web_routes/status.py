"""Dashboard status route."""

import asyncio
import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter

from elevate_cli import __release_date__, __version__
from elevate_cli.config import (
    check_config_version,
    get_config_path,
    get_elevate_home,
    get_env_path,
)
from gateway.status import get_running_pid, read_runtime_status


GetSessionDb = Callable[[], Any]

_STATUS_CACHE_TTL_SEC = 1.5
_status_cache_payload: dict[str, Any] | None = None
_status_cache_expires_at = 0.0
_status_cache_lock = threading.Lock()
_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    logging.getLogger(__name__).warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r - using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint."""
    if not _GATEWAY_HEALTH_URL:
        return False, None

    base = _GATEWAY_HEALTH_URL.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=_GATEWAY_HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


def _cached_status_payload() -> dict[str, Any] | None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    now = time.monotonic()
    with _status_cache_lock:
        if _status_cache_payload is None or _status_cache_expires_at <= now:
            return None
        return dict(_status_cache_payload)


def _store_status_payload(payload: dict[str, Any]) -> None:
    global _status_cache_payload, _status_cache_expires_at
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _status_cache_lock:
        _status_cache_payload = dict(payload)
        _status_cache_expires_at = time.monotonic() + _STATUS_CACHE_TTL_SEC


def create_status_router(
    *,
    workspace_root: Path,
    get_session_db: GetSessionDb,
    session_active_window_sec: int,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build the dashboard status route."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/status")
    async def get_status():
        cached = _cached_status_payload()
        if cached is not None:
            return cached

        current_ver, latest_ver = check_config_version()

        gateway_pid = get_running_pid()
        gateway_running = gateway_pid is not None
        remote_health_body: dict | None = None

        if not gateway_running and _GATEWAY_HEALTH_URL:
            loop = asyncio.get_event_loop()
            alive, remote_health_body = await loop.run_in_executor(
                None, _probe_gateway_health
            )
            if alive:
                gateway_running = True
                if remote_health_body:
                    gateway_pid = remote_health_body.get("pid")

        gateway_state = None
        gateway_platforms: dict = {}
        gateway_exit_reason = None
        gateway_updated_at = None
        configured_gateway_platforms: set[str] | None = None
        try:
            from gateway.config import load_gateway_config

            gateway_config = load_gateway_config()
            configured_gateway_platforms = {
                platform.value for platform in gateway_config.get_connected_platforms()
            }
        except Exception:
            configured_gateway_platforms = None

        runtime = read_runtime_status()
        if runtime is None and remote_health_body and remote_health_body.get("gateway_state"):
            runtime = remote_health_body

        if runtime:
            gateway_state = runtime.get("gateway_state")
            gateway_platforms = runtime.get("platforms") or {}
            if configured_gateway_platforms is not None:
                gateway_platforms = {
                    key: value
                    for key, value in gateway_platforms.items()
                    if key in configured_gateway_platforms
                }
            gateway_exit_reason = runtime.get("exit_reason")
            gateway_updated_at = runtime.get("updated_at")
            if not gateway_running:
                gateway_state = gateway_state if gateway_state in ("stopped", "startup_failed") else "stopped"
                gateway_platforms = {}
            elif gateway_running and remote_health_body is not None:
                if gateway_state in (None, "stopped"):
                    gateway_state = "running"

        if gateway_running and gateway_state is None and remote_health_body is not None:
            gateway_state = "running"

        active_sessions = 0
        try:
            from elevate_cli.data.chat_sessions import active_session_count

            active_sessions = active_session_count(session_active_window_sec)
        except Exception:
            try:
                db = get_session_db()
                try:
                    sessions = db.list_sessions_rich(limit=50)
                    now = time.time()
                    active_sessions = sum(
                        1 for s in sessions
                        if s.get("ended_at") is None
                        and (now - s.get("last_active", s.get("started_at", 0)))
                        < session_active_window_sec
                    )
                finally:
                    db.close()
            except Exception:
                _log.debug("status active session count failed", exc_info=True)

        payload = {
            "version": __version__,
            "release_date": __release_date__,
            "project_root": str(workspace_root),
            "elevate_home": str(get_elevate_home()),
            "config_path": str(get_config_path()),
            "env_path": str(get_env_path()),
            "config_version": current_ver,
            "latest_config_version": latest_ver,
            "gateway_running": gateway_running,
            "gateway_pid": gateway_pid,
            "gateway_health_url": _GATEWAY_HEALTH_URL,
            "gateway_state": gateway_state,
            "gateway_platforms": gateway_platforms,
            "gateway_exit_reason": gateway_exit_reason,
            "gateway_updated_at": gateway_updated_at,
            "active_sessions": active_sessions,
        }
        _store_status_payload(payload)
        return payload

    return router
