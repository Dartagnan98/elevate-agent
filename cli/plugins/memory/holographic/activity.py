"""Lightweight activity stream for the local holographic memory pipeline."""

from __future__ import annotations

import calendar
import time
from pathlib import Path
from typing import Any

from elevate_constants import get_elevate_home
from utils import atomic_json_write

_MAX_EVENTS = 20
_STALE_AFTER_SECONDS = 60
_ACTIVE_STATES = {"searching", "verifying", "injecting", "maintaining", "embedding"}
_STEPS = ("search", "verify", "inject", "maintain")


def _activity_path() -> Path:
    return get_elevate_home() / "memory_activity.json"


def _now() -> float:
    return time.time()


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or _now()))


def _default_pipeline() -> dict[str, Any]:
    return {
        "derived_from_journal": False,
        "search": "pending",
        "verify": "pending",
        "inject": "pending",
        "maintain": "pending",
        "active": False,
        "last_step": "",
        "started_at": _iso(),
        "updated_at": _iso(),
    }


def _default_state() -> dict[str, Any]:
    return {
        "state": "idle",
        "state_since": _iso(),
        "updated_at": _iso(),
        "pipeline": _default_pipeline(),
        "recent_events": [],
    }


def _read() -> dict[str, Any]:
    path = _activity_path()
    try:
        if path.exists():
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return _default_state()


def _write(payload: dict[str, Any]) -> None:
    try:
        atomic_json_write(_activity_path(), payload, indent=2)
    except Exception:
        pass


def record_event(
    kind: str,
    *,
    message: str = "",
    state: str | None = None,
    step: str | None = None,
    status: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Record a memory activity event and optional pipeline transition."""

    payload = _read()
    now_iso = _iso()
    if state and payload.get("state") != state:
        payload["state"] = state
        payload["state_since"] = now_iso
    payload["updated_at"] = now_iso

    pipeline = payload.get("pipeline")
    if not isinstance(pipeline, dict):
        pipeline = _default_pipeline()
    pipeline["derived_from_journal"] = False
    pipeline["updated_at"] = now_iso
    if step in _STEPS and status:
        pipeline[step] = status
        pipeline["last_step"] = step
    pipeline["active"] = str(payload.get("state") or "idle") in _ACTIVE_STATES
    payload["pipeline"] = pipeline

    events = payload.get("recent_events")
    if not isinstance(events, list):
        events = []
    events.insert(
        0,
        {
            "kind": kind,
            "message": message,
            "timestamp": now_iso,
            "state": payload.get("state", "idle"),
            "step": step or "",
            "status": status or "",
            "data": data or {},
        },
    )
    payload["recent_events"] = events[:_MAX_EVENTS]
    _write(payload)


def pipeline_start(*, reason: str = "") -> None:
    payload = _read()
    now_iso = _iso()
    payload["state"] = "searching"
    payload["state_since"] = now_iso
    payload["updated_at"] = now_iso
    payload["pipeline"] = _default_pipeline()
    payload["pipeline"]["search"] = "running"
    payload["pipeline"]["active"] = True
    events = payload.get("recent_events") if isinstance(payload.get("recent_events"), list) else []
    events.insert(
        0,
        {
            "kind": "pipeline.started",
            "message": reason,
            "timestamp": now_iso,
            "state": "searching",
            "step": "search",
            "status": "running",
            "data": {},
        },
    )
    payload["recent_events"] = events[:_MAX_EVENTS]
    _write(payload)


def snapshot() -> dict[str, Any]:
    payload = _read()
    updated_at = payload.get("updated_at")
    try:
        updated_ts = calendar.timegm(time.strptime(str(updated_at), "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        updated_ts = 0.0
    state = str(payload.get("state") or "idle")
    if state in _ACTIVE_STATES and updated_ts and _now() - updated_ts > _STALE_AFTER_SECONDS:
        payload["state"] = "idle"
        pipeline = payload.get("pipeline") if isinstance(payload.get("pipeline"), dict) else {}
        pipeline["active"] = False
        payload["pipeline"] = pipeline
    return payload
