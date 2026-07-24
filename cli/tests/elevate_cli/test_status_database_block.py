"""Reliability release (section B2): the /api/status health rail exposes a
``database`` block and never masks a DB failure as "0 active sessions"
(CONTRACT 2: ``{"reachable": bool, "latency_ms": float|None, "error": str|None}``).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from elevate_cli.web_routes import status as status_module
from elevate_cli.web_routes.status import create_status_router


def _endpoint(**kwargs):
    kwargs.setdefault("get_session_db", lambda: None)
    router = create_status_router(
        workspace_root=Path("/tmp/workspace"),
        session_active_window_sec=25,
        check_config_version_func=lambda: (1, 1),
        get_running_pid_func=lambda: None,
        read_runtime_status_func=lambda: None,
        gateway_health_url_func=lambda: None,
        probe_gateway_health_func=lambda: (False, None),
        **kwargs,
    )
    return next(route.endpoint for route in router.routes if route.path == "/api/status")


def test_status_database_block_reflects_reachable(monkeypatch):
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.active_session_count", lambda _w: 5, raising=False
    )
    endpoint = _endpoint(probe_database_func=lambda: (True, 4.2, None))

    payload = asyncio.run(endpoint())

    assert payload["database"] == {"reachable": True, "latency_ms": 4.2, "error": None}
    assert payload["active_sessions"] == 5


def test_status_database_block_reflects_unreachable(monkeypatch):
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.active_session_count", lambda _w: 0, raising=False
    )
    endpoint = _endpoint(probe_database_func=lambda: (False, None, "connection refused"))

    payload = asyncio.run(endpoint())

    assert payload["database"] == {
        "reachable": False,
        "latency_ms": None,
        "error": "connection refused",
    }


def test_session_count_failure_marks_db_unreachable_not_zero(monkeypatch):
    """A session-store read failure must surface as reachable=false instead of
    being silently swallowed as active_sessions=0 behind a healthy rail."""

    def _boom(_w):
        raise RuntimeError("db read failed")

    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.active_session_count", _boom, raising=False
    )

    class _DeadDb:
        def list_sessions_rich(self, limit):
            raise RuntimeError("db read failed")

        def close(self):
            pass

    # The direct probe "succeeds" but the session store is unreadable: the code
    # must not report reachable=true + 0 sessions.
    endpoint = _endpoint(
        get_session_db=lambda: _DeadDb(),
        probe_database_func=lambda: (True, 1.0, None),
    )

    payload = asyncio.run(endpoint())

    assert payload["active_sessions"] == 0
    assert payload["database"]["reachable"] is False
    assert payload["database"]["error"]  # a non-empty reason is surfaced


def test_cached_status_payload_never_serves_unreachable_db(monkeypatch):
    """The 1.5s happy-cache must be bypassed whenever the cached payload
    recorded an unreachable database, so the rail reflects live state."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(status_module, "beta_provider_policy_active", lambda: False)

    future = time.monotonic() + 100
    monkeypatch.setattr(status_module, "_status_cache_expires_at", future)

    # Cached payload says DB is DOWN -> must recompute (return None).
    monkeypatch.setattr(
        status_module,
        "_status_cache_payload",
        {"active_sessions": 0, "database": {"reachable": False, "latency_ms": None, "error": "x"}},
    )
    assert status_module._cached_status_payload() is None

    # Cached payload says DB is UP -> serve the cache.
    happy = {"active_sessions": 1, "database": {"reachable": True, "latency_ms": 2.0, "error": None}}
    monkeypatch.setattr(status_module, "_status_cache_payload", happy)
    served = status_module._cached_status_payload()
    assert served == happy
