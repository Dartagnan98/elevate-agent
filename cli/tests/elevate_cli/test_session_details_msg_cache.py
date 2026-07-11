"""Coalescing cache for the per-open transcript read (session_details).

Opening a session fans out to 5 detail routes that each need the full
transcript; ``_load_session_messages`` collapses them to a single read within a
short TTL (and is called off the event loop via ``asyncio.to_thread``). This
guards that coalescing + expiry behavior.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from elevate_cli.web_routes import session_details as sd


class _FakeDb:
    def __init__(self) -> None:
        self.calls = 0

    def get_messages(self, active_id):
        self.calls += 1
        return [{"role": "user", "content": f"{active_id}-{self.calls}"}]


@pytest.fixture(autouse=True)
def _clear_cache():
    sd._MSG_CACHE.clear()
    yield
    sd._MSG_CACHE.clear()


def test_coalesces_within_ttl(monkeypatch):
    monkeypatch.setattr(sd.time, "monotonic", lambda: 1000.0)
    db = _FakeDb()

    first = sd._load_session_messages(db, "s1")
    second = sd._load_session_messages(db, "s1")

    assert db.calls == 1  # five routes → one real read
    assert second is first  # same object shared read-only across routes


def test_reads_again_after_ttl(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(sd.time, "monotonic", lambda: clock["t"])
    db = _FakeDb()

    sd._load_session_messages(db, "s1")
    clock["t"] += sd._MSG_CACHE_TTL + 0.01  # past expiry
    sd._load_session_messages(db, "s1")

    assert db.calls == 2


def test_keyed_per_session(monkeypatch):
    monkeypatch.setattr(sd.time, "monotonic", lambda: 1000.0)
    db = _FakeDb()

    a = sd._load_session_messages(db, "s1")
    b = sd._load_session_messages(db, "s2")

    assert db.calls == 2
    assert a is not b


def test_evicts_when_over_cap(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(sd.time, "monotonic", lambda: clock["t"])
    db = _FakeDb()

    # Fill well past the cap with already-expired entries, then insert one more.
    for i in range(sd._MSG_CACHE_MAX + 5):
        sd._load_session_messages(db, f"s{i}")
        clock["t"] += sd._MSG_CACHE_TTL + 0.01  # each prior entry is now stale
    assert len(sd._MSG_CACHE) <= sd._MSG_CACHE_MAX


class _TurnUsageDb:
    def __init__(self, legacy_rows=None):
        self.legacy_rows = legacy_rows or []
        self.legacy_calls = 0

    def resolve_session_id(self, session_id):
        return session_id

    def resolve_canonical_session_identity(self, session_id):
        return {
            "requested_session_id": session_id,
            "lineage_root_id": session_id,
            "active_session_id": session_id,
            "session_kind": "chat",
            "is_compression_tip": True,
        }

    def get_session(self, session_id):
        return {"id": session_id, "source": "tui"}

    def turn_usage_for_session(self, _session_id):
        self.legacy_calls += 1
        return self.legacy_rows

    def close(self):
        return None


def _turn_usage_endpoint(db):
    router = sd.create_session_detail_router(
        get_session_db=lambda: db,
        session_reveal_target=lambda _sid: None,
        open_in_file_manager=lambda _path: None,
        live_subagent_child_session_ids=lambda: set(),
        log=SimpleNamespace(debug=lambda *_args, **_kwargs: None),
    )
    return next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/sessions/{session_id}/turn_usage"
    )


def test_turn_usage_route_merges_recovery_rows_and_prefers_canonical_duplicate(
    monkeypatch,
):
    offloaded = []

    async def to_thread(func, *args):
        offloaded.append((func, args))
        return func(*args)

    db = _TurnUsageDb(
        legacy_rows=[
            {
                "message_id": "assistant-1",
                "model": "stale-import",
                "output_tokens": 999,
                "timestamp": 20.0,
            },
            {
                "message_id": "assistant-outage",
                "model": "gemini-2.5-flash",
                "output_tokens": 12,
                "timestamp": 10.0,
            },
        ]
    )
    def canonical_reader(_sid):
        return [
            {
                "message_id": "assistant-1",
                "model": "gemini-2.5-flash",
                "input_tokens": 700,
                "output_tokens": 47,
                "latency_ms": 2951,
                "timestamp": 20.0,
            }
        ]
    monkeypatch.setattr(sd, "turns_for_session", canonical_reader)
    monkeypatch.setattr(sd.asyncio, "to_thread", to_thread)

    result = asyncio.run(_turn_usage_endpoint(db)("session-1"))

    assert db.legacy_calls == 1
    assert offloaded == [
        (canonical_reader, ("session-1",)),
        (db.turn_usage_for_session, ("session-1",)),
    ]
    assert [row["message_id"] for row in result["turn_usage"]] == [
        "assistant-outage",
        "assistant-1",
    ]
    assert result["turn_usage"][0]["output_tokens"] == 12
    assert result["turn_usage"][1]["model"] == "gemini-2.5-flash"
    assert result["turn_usage"][1]["output_tokens"] == 47


def test_turn_usage_route_falls_back_to_legacy_rows(monkeypatch):
    db = _TurnUsageDb(
        legacy_rows=[{"message_id": "legacy", "output_tokens": 12}]
    )

    def fail_canonical(_sid):
        raise RuntimeError("pg unavailable")

    monkeypatch.setattr(sd, "turns_for_session", fail_canonical)

    result = asyncio.run(_turn_usage_endpoint(db)("session-1"))

    assert db.legacy_calls == 1
    assert result["turn_usage"][0]["message_id"] == "legacy"
    assert result["turn_usage"][0]["output_tokens"] == 12
