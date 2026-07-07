"""Coalescing cache for the per-open transcript read (session_details).

Opening a session fans out to 5 detail routes that each need the full
transcript; ``_load_session_messages`` collapses them to a single read within a
short TTL (and is called off the event loop via ``asyncio.to_thread``). This
guards that coalescing + expiry behavior.
"""
from __future__ import annotations

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
