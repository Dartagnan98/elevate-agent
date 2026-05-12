"""Always-on workflow supervisor for visible agents.

The gateway already owns the long-lived runtime and cron ticker. This module is
the small bridge that keeps workflow queues moving: each tick drains durable
agent handoffs and queued Admin action runs into cron, then the normal cron
scheduler executes the launched jobs.
"""

from __future__ import annotations

import json
import os
import time
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for local dev
    fcntl = None

from elevate_cli.config import load_config
from elevate_cli.data.paths import data_root
from elevate_cli.data._util import now_iso


_LOCK = threading.Lock()
_LOOP_LOCK = threading.Lock()
_STOP_EVENT = threading.Event()
_WAKE_EVENT = threading.Event()
_LOOP_THREAD: threading.Thread | None = None
_LOOP_STARTED_AT: str | None = None
_LAST_WAKE_AT: str | None = None
_LAST_WAKE_REASON = ""
_WAKE_COUNT = 0
_LAST_CONSUMED_WAKE_TOKEN = ""
_STATUS_FILE_NAME = "agent_worker_status.json"
_LOCK_FILE_NAME = ".agent_worker.lock"
_WAKE_FILE_NAME = "agent_worker_wake.json"


def _status_path():
    return data_root() / _STATUS_FILE_NAME


def _lock_path():
    return data_root() / _LOCK_FILE_NAME


def _wake_path():
    return data_root() / _WAKE_FILE_NAME


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, seconds))).isoformat()


def _int_setting(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        parsed = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else load_config()
    worker = cfg.get("agent_worker") if isinstance(cfg.get("agent_worker"), dict) else {}
    enabled = worker.get("enabled", True)
    return {
        "enabled": str(enabled).strip().lower() not in {"0", "false", "no", "off"},
        "max_handoffs_per_tick": _int_setting(worker.get("max_handoffs_per_tick"), 25),
        "max_admin_runs_per_tick": _int_setting(worker.get("max_admin_runs_per_tick"), 25),
        "stale_running_minutes": _int_setting(worker.get("stale_running_minutes"), 120, minimum=1),
        "heartbeat_interval_seconds": _int_setting(
            worker.get("heartbeat_interval_seconds"),
            30,
            minimum=5,
        ),
        "wake_poll_seconds": _int_setting(worker.get("wake_poll_seconds"), 1, minimum=1),
    }


def _loop_running() -> bool:
    thread = _LOOP_THREAD
    return bool(thread and thread.is_alive())


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _loop_payload_from_status(
    stored: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stored_loop = stored.get("loop") if isinstance(stored.get("loop"), dict) else {}
    running = _loop_running()
    if not running and stored_loop.get("running"):
        worker = _config(config)
        heartbeat = stored.get("heartbeat") if isinstance(stored.get("heartbeat"), dict) else {}
        last_seen = _parse_iso(heartbeat.get("lastBeatAt")) or _parse_iso(stored_loop.get("startedAt"))
        max_age = max(90, worker["heartbeat_interval_seconds"] * 3)
        running = bool(
            last_seen
            and datetime.now(timezone.utc) - last_seen <= timedelta(seconds=max_age)
        )
    return {
        **stored_loop,
        "running": running,
        "startedAt": _LOOP_STARTED_AT or stored_loop.get("startedAt"),
    }


def _base_snapshot(state: str = "unknown", *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    worker = _config(config)
    return {
        "enabled": worker["enabled"],
        "mode": "heartbeat+wake",
        "state": state,
        "lastReason": "",
        "lastTickAt": None,
        "lastSuccessAt": None,
        "lastError": "",
        "drained": {"handoffs": 0, "adminRuns": 0},
        "recovered": {"staleHandoffs": 0, "staleAdminRuns": 0},
        "limits": {
            "handoffs": worker["max_handoffs_per_tick"],
            "adminRuns": worker["max_admin_runs_per_tick"],
            "staleRunningMinutes": worker["stale_running_minutes"],
        },
        "heartbeat": {
            "enabled": worker["enabled"],
            "intervalSeconds": worker["heartbeat_interval_seconds"],
            "lastBeatAt": None,
            "nextBeatAt": None,
        },
        "wake": {
            "enabled": worker["enabled"],
            "pending": False,
            "lastWakeAt": _LAST_WAKE_AT,
            "lastReason": _LAST_WAKE_REASON,
            "count": _WAKE_COUNT,
        },
        "loop": {
            "running": _loop_running(),
            "startedAt": _LOOP_STARTED_AT,
        },
    }


def _read_status() -> dict[str, Any] | None:
    path = _status_path()
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return stored if isinstance(stored, dict) else None


def _write_status(status: dict[str, Any]) -> None:
    path = _status_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def snapshot(*, config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = _base_snapshot("idle", config=config)
    stored = _read_status()
    if stored is None:
        return base
    if isinstance(stored, dict):
        merged = {**base, **stored}
        merged["enabled"] = base["enabled"]
        merged["limits"] = base["limits"]
        merged["mode"] = base["mode"]
        merged["loop"] = {
            **base["loop"],
            **(stored.get("loop") if isinstance(stored.get("loop"), dict) else {}),
            **_loop_payload_from_status(stored, config=config),
        }
        merged["heartbeat"] = {
            **base["heartbeat"],
            **(stored.get("heartbeat") if isinstance(stored.get("heartbeat"), dict) else {}),
            "enabled": base["heartbeat"]["enabled"],
            "intervalSeconds": base["heartbeat"]["intervalSeconds"],
        }
        stored_wake = stored.get("wake") if isinstance(stored.get("wake"), dict) else {}
        merged["wake"] = {
            **base["wake"],
            **stored_wake,
            "enabled": base["wake"]["enabled"],
            "pending": (_loop_running() and _WAKE_EVENT.is_set()) or bool(stored_wake.get("pending")),
        }
        return merged
    return base


def _merge_runtime_status(
    status: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    reason: str = "",
    last_beat_at: str | None = None,
    next_beat_at: str | None = None,
) -> dict[str, Any]:
    stored = _read_status() or {}
    stored_heartbeat = stored.get("heartbeat") if isinstance(stored.get("heartbeat"), dict) else {}
    stored_wake = stored.get("wake") if isinstance(stored.get("wake"), dict) else {}
    worker = _config(config)
    try:
        stored_wake_count = int(stored_wake.get("count") or 0)
    except (TypeError, ValueError):
        stored_wake_count = 0
    status["mode"] = "heartbeat+wake"
    status["lastReason"] = reason or status.get("lastReason") or stored.get("lastReason") or ""
    status["heartbeat"] = {
        "enabled": worker["enabled"],
        "intervalSeconds": worker["heartbeat_interval_seconds"],
        "lastBeatAt": last_beat_at or stored_heartbeat.get("lastBeatAt"),
        "nextBeatAt": next_beat_at or stored_heartbeat.get("nextBeatAt"),
    }
    status["wake"] = {
        "enabled": worker["enabled"],
        "pending": _loop_running() and _WAKE_EVENT.is_set(),
        "lastWakeAt": _LAST_WAKE_AT or stored_wake.get("lastWakeAt"),
        "lastReason": _LAST_WAKE_REASON or stored_wake.get("lastReason") or "",
        "count": max(_WAKE_COUNT, stored_wake_count),
    }
    status["loop"] = {
        **_loop_payload_from_status(stored, config=config),
    }
    return status


def tick(
    *,
    actor: str = "agent-worker",
    config: dict[str, Any] | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    worker = _config(config)
    now = now_iso()
    last_beat_at = now if reason == "heartbeat" else None
    next_beat_at = (
        _iso_after(worker["heartbeat_interval_seconds"])
        if reason == "heartbeat"
        else None
    )
    if not worker["enabled"]:
        status = _base_snapshot("disabled", config=config)
        status["lastTickAt"] = now
        _merge_runtime_status(
            status,
            config=config,
            reason=reason,
            last_beat_at=last_beat_at,
            next_beat_at=next_beat_at,
        )
        _write_status(status)
        return status

    if not _LOCK.acquire(blocking=False):
        status = snapshot(config=config)
        status["state"] = "locked"
        status["lastTickAt"] = now
        status["lastReason"] = reason
        return status

    lock_fd = None
    try:
        lock_path = _lock_path()
        lock_fd = open(lock_path, "w")
        if fcntl:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                status = snapshot(config=config)
                status["state"] = "locked"
                status["lastTickAt"] = now_iso()
                status["lastReason"] = reason
                return status

        from elevate_cli.data import (
            connect,
            drain_queued_action_runs,
            drain_queued_agent_handoffs,
            mark_stale_action_runs,
            mark_stale_agent_handoffs,
        )

        handoffs: list[dict[str, Any]] = []
        admin_runs: list[dict[str, Any]] = []
        stale_handoffs: list[dict[str, Any]] = []
        stale_admin_runs: list[dict[str, Any]] = []
        with connect() as conn:
            stale_handoffs = mark_stale_agent_handoffs(
                conn,
                max_running_minutes=worker["stale_running_minutes"],
                actor=actor,
            )
            stale_admin_runs = mark_stale_action_runs(
                conn,
                max_running_minutes=worker["stale_running_minutes"],
                actor=actor,
            )
            if worker["max_handoffs_per_tick"]:
                handoffs = drain_queued_agent_handoffs(
                    conn,
                    limit=worker["max_handoffs_per_tick"],
                    actor=actor,
                )
            if worker["max_admin_runs_per_tick"]:
                admin_runs = drain_queued_action_runs(
                    conn,
                    limit=worker["max_admin_runs_per_tick"],
                    actor=actor,
                )

        now = now_iso()
        status = _base_snapshot("ok", config=config)
        status.update(
            {
                "lastTickAt": now,
                "lastSuccessAt": now,
                "lastError": "",
                "drained": {
                    "handoffs": len(handoffs),
                    "adminRuns": len(admin_runs),
                },
                "recovered": {
                    "staleHandoffs": len(stale_handoffs),
                    "staleAdminRuns": len(stale_admin_runs),
                },
            }
        )
        _merge_runtime_status(
            status,
            config=config,
            reason=reason,
            last_beat_at=last_beat_at,
            next_beat_at=next_beat_at,
        )
        _write_status(status)
        return status
    except Exception as exc:
        status = _base_snapshot("error", config=config)
        status["lastTickAt"] = now_iso()
        status["lastError"] = str(exc)
        _merge_runtime_status(
            status,
            config=config,
            reason=reason,
            last_beat_at=last_beat_at,
            next_beat_at=next_beat_at,
        )
        _write_status(status)
        return status
    finally:
        try:
            if fcntl and lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            if lock_fd:
                lock_fd.close()
            _LOCK.release()


def request_wake(
    *,
    reason: str = "manual",
    actor: str = "system",
    delay_seconds: float = 0.0,
) -> dict[str, Any]:
    """Persist a cross-process worker wake request and nudge this process too."""
    global _LAST_WAKE_AT, _LAST_WAKE_REASON, _WAKE_COUNT

    now = _utc_iso()
    clean_reason = str(reason or "manual").strip()[:160] or "manual"
    _WAKE_COUNT += 1
    _LAST_WAKE_AT = now
    _LAST_WAKE_REASON = clean_reason
    payload = {
        "requestedAt": now,
        "notBefore": _iso_after(delay_seconds),
        "reason": clean_reason,
        "actor": str(actor or "system"),
        "count": _WAKE_COUNT,
        "token": f"{time.time_ns()}:{os.getpid()}:{_WAKE_COUNT}",
    }
    path = _wake_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    if _loop_running():
        _WAKE_EVENT.set()

    status = snapshot()
    status["wake"] = {
        **(status.get("wake") if isinstance(status.get("wake"), dict) else {}),
        "enabled": status.get("enabled", True),
        "pending": True,
        "lastWakeAt": now,
        "lastReason": clean_reason,
        "count": _WAKE_COUNT,
    }
    _write_status(status)
    return status


def _read_wake_request() -> dict[str, Any] | None:
    path = _wake_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    not_before = str(payload.get("notBefore") or "")
    if not_before:
        try:
            ready_at = datetime.fromisoformat(not_before)
            if ready_at.tzinfo is None:
                ready_at = ready_at.replace(tzinfo=timezone.utc)
            if ready_at.astimezone(timezone.utc) > datetime.now(timezone.utc):
                return None
        except ValueError:
            pass
    return payload


def _consume_wake_request() -> tuple[bool, str]:
    global _LAST_CONSUMED_WAKE_TOKEN, _LAST_WAKE_AT, _LAST_WAKE_REASON, _WAKE_COUNT

    payload = _read_wake_request()
    if not payload:
        if _WAKE_EVENT.is_set():
            _WAKE_EVENT.clear()
            return True, _LAST_WAKE_REASON or "wake"
        return False, ""

    token = str(payload.get("token") or payload.get("requestedAt") or "")
    if token and token == _LAST_CONSUMED_WAKE_TOKEN and not _WAKE_EVENT.is_set():
        return False, ""

    _LAST_CONSUMED_WAKE_TOKEN = token
    _WAKE_EVENT.clear()
    _LAST_WAKE_AT = str(payload.get("requestedAt") or _LAST_WAKE_AT or "")
    _LAST_WAKE_REASON = str(payload.get("reason") or _LAST_WAKE_REASON or "wake")
    try:
        _WAKE_COUNT = max(_WAKE_COUNT, int(payload.get("count") or 0))
    except (TypeError, ValueError):
        pass
    return True, _LAST_WAKE_REASON or "wake"


def _should_run_cron_after(status: dict[str, Any]) -> bool:
    drained = status.get("drained") if isinstance(status.get("drained"), dict) else {}
    return bool(int(drained.get("handoffs") or 0) or int(drained.get("adminRuns") or 0))


def _worker_loop(
    *,
    config: dict[str, Any] | None = None,
    after_tick: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    worker = _config(config)
    heartbeat_interval = worker["heartbeat_interval_seconds"]
    poll_interval = worker["wake_poll_seconds"]
    next_heartbeat = time.monotonic()
    while not _STOP_EVENT.is_set():
        reason = ""
        wake_ready, wake_reason = _consume_wake_request()
        if wake_ready:
            reason = f"wake:{wake_reason}"
        elif time.monotonic() >= next_heartbeat:
            reason = "heartbeat"

        if reason:
            status = tick(actor=f"agent-worker:{reason}", config=config, reason=reason)
            if after_tick is not None and _should_run_cron_after(status):
                try:
                    after_tick(status)
                except Exception:
                    pass
            next_heartbeat = time.monotonic() + heartbeat_interval

        wait_for = min(poll_interval, max(0.1, next_heartbeat - time.monotonic()))
        _STOP_EVENT.wait(timeout=wait_for)


def start_background_loop(
    *,
    config: dict[str, Any] | None = None,
    after_tick: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Start the gateway-owned heartbeat/wake loop if it is not running."""
    global _LOOP_THREAD, _LOOP_STARTED_AT

    with _LOOP_LOCK:
        if _loop_running():
            return snapshot(config=config)
        _STOP_EVENT.clear()
        _LOOP_STARTED_AT = _utc_iso()
        _LOOP_THREAD = threading.Thread(
            target=_worker_loop,
            kwargs={"config": config, "after_tick": after_tick},
            daemon=True,
            name="agent-worker-loop",
        )
        _LOOP_THREAD.start()
        status = snapshot(config=config)
        status["state"] = "listening" if status.get("enabled") else "disabled"
        status["loop"] = {
            **(status.get("loop") if isinstance(status.get("loop"), dict) else {}),
            "running": True,
            "startedAt": _LOOP_STARTED_AT,
        }
        status["lastReason"] = "loop_start"
        _write_status(status)
        return status


def stop_background_loop(timeout: float = 5.0) -> dict[str, Any]:
    """Stop the local heartbeat/wake loop."""
    global _LOOP_THREAD

    _STOP_EVENT.set()
    _WAKE_EVENT.set()
    thread = _LOOP_THREAD
    if thread is not None:
        thread.join(timeout=timeout)
    with _LOOP_LOCK:
        if _LOOP_THREAD is thread:
            _LOOP_THREAD = None
    status = snapshot()
    status["loop"] = {
        **(status.get("loop") if isinstance(status.get("loop"), dict) else {}),
        "running": False,
    }
    status["lastReason"] = "loop_stop"
    _write_status(status)
    return status
