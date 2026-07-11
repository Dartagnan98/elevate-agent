from types import SimpleNamespace

import pytest

from elevate_cli.data import usage_ledger


def test_turns_for_session_reads_canonical_rows_oldest_first(monkeypatch):
    queries = []
    rows = [
        {"id": 1, "session_id": "session-1", "timestamp": 10.0},
        {"id": 2, "session_key": "session-1", "timestamp": 11.0},
    ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, params):
            queries.append((query, params))
            return SimpleNamespace(fetchall=lambda: rows)

    monkeypatch.setattr(usage_ledger, "connect", FakeConnection)

    assert usage_ledger.turns_for_session("session-1") == rows
    assert queries[0][1] == ("session-1", "session-1", 1000)
    assert "ORDER BY timestamp ASC, id ASC" in queries[0][0]


def test_turns_for_session_leaves_connection_failures_to_route_fallback(monkeypatch):
    class BrokenConnection:
        def __enter__(self):
            raise RuntimeError("pg unavailable")

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(usage_ledger, "connect", BrokenConnection)

    try:
        usage_ledger.turns_for_session("session-1")
    except RuntimeError as exc:
        assert str(exc) == "pg unavailable"
    else:
        raise AssertionError("canonical read failure was swallowed")


class _BrokenConnection:
    def __enter__(self):
        raise RuntimeError("pg unavailable")

    def __exit__(self, *_args):
        return None


def test_record_turn_strict_mode_raises_and_default_remains_fail_soft(monkeypatch):
    monkeypatch.setattr(usage_ledger, "connect", _BrokenConnection)

    assert usage_ledger.record_turn({}) is None
    with pytest.raises(RuntimeError, match="pg unavailable"):
        usage_ledger.record_turn({}, strict=True)


def test_record_turn_strict_mode_preserves_dedup_none(monkeypatch):
    class DedupeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query, _values):
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            return None

    monkeypatch.setattr(usage_ledger, "connect", DedupeConnection)

    assert usage_ledger.record_turn({}, strict=True) is None


def test_recent_turns_strict_mode_raises_and_default_remains_fail_soft(monkeypatch):
    monkeypatch.setattr(usage_ledger, "connect", _BrokenConnection)

    assert usage_ledger.recent_turns() == []
    with pytest.raises(RuntimeError, match="pg unavailable"):
        usage_ledger.recent_turns(strict=True)


def test_sum_recent_tokens_strict_mode_raises_and_default_remains_fail_soft(monkeypatch):
    monkeypatch.setattr(usage_ledger, "connect", _BrokenConnection)

    assert usage_ledger.sum_recent_tokens(since=1.0) == 0
    with pytest.raises(RuntimeError, match="pg unavailable"):
        usage_ledger.sum_recent_tokens(since=1.0, strict=True)
