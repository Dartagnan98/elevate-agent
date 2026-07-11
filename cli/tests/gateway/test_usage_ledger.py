from __future__ import annotations

import json

from elevate_cli.data import usage_ledger as pg_usage_ledger
from gateway import usage_ledger


def _capture_canonical_writes(monkeypatch):
    rows = []

    def record_turn(row, *, strict=False):
        assert strict is True
        rows.append(dict(row))
        return len(rows)

    monkeypatch.setattr(pg_usage_ledger, "record_turn", record_turn)
    return rows


def test_record_gateway_turn_writes_program_specific_row_to_canonical_store(monkeypatch):
    rows = _capture_canonical_writes(monkeypatch)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 100)
    monkeypatch.setattr(
        usage_ledger,
        "_safe_tool_schema_tokens_for_toolsets",
        lambda toolsets: 250,
    )

    row_id = usage_ledger.record_gateway_turn(
        agent_result={
            "session_id": "session-1",
            "provider": "openai",
            "model": "gpt-5.5",
            "gateway_tool_profile": "coding-edit",
            "gateway_tool_profile_reason": "matched coding-edit intent",
            "selected_toolsets": ["terminal", "file"],
            "requested_toolsets": ["terminal", "file", "todo"],
            "configured_toolsets": ["terminal", "file", "todo", "browser"],
            "tools": [{"type": "function", "function": {"name": "terminal"}}],
            "tool_calls": ["terminal"],
            "input_tokens": 1000,
            "output_tokens": 120,
            "total_tokens": 1120,
            "cache_read_tokens": 300,
            "cache_write_tokens": 20,
            "reasoning_tokens": 10,
            "api_calls": 2,
            "estimated_cost_usd": 0.0123,
            "cost_status": "estimated",
            "cost_source": "pricing_table",
        },
        session_key="telegram:123",
        message_id="msg-1",
        source="telegram",
        latency_ms=4567,
    )

    assert row_id == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "telegram"
    assert row["session_id"] == "session-1"
    assert row["session_key"] == "telegram:123"
    assert row["model"] == "gpt-5.5"
    assert row["gateway_tool_profile"] == "coding-edit"
    assert row["loaded_tool_count"] == 1
    assert row["selected_tool_schema_tokens"] == 100
    assert row["configured_tool_schema_tokens"] == 250
    assert row["estimated_tool_schema_savings_tokens"] == 150
    assert round(row["estimated_tool_schema_savings_pct"], 1) == 60.0
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 120
    assert row["total_tokens"] == 1120
    assert row["latency_ms"] == 4567
    assert row["status"] == "ok"
    assert row["error_type"] == ""
    assert json.loads(row["tool_calls"]) == ["terminal"]
    assert json.loads(row["selected_toolsets"]) == ["terminal", "file"]
    assert "content" not in row


def test_record_gateway_turn_prefers_agent_result_session_id_after_split(monkeypatch):
    rows = _capture_canonical_writes(monkeypatch)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(
        usage_ledger,
        "_safe_tool_schema_tokens_for_toolsets",
        lambda toolsets: 0,
    )

    usage_ledger.record_gateway_turn(
        agent_result={"session_id": "new-session", "model": "m"},
        session_id="old-session",
        source="telegram",
    )

    assert rows[0]["session_id"] == "new-session"


def test_duplicate_platform_event_reuses_canonical_dedup_key(monkeypatch):
    stored = {}

    def deduplicating_record(row, *, strict=False):
        assert strict is True
        key = (row["source"], row["session_key"], row["message_id"])
        if key in stored:
            return None
        stored[key] = dict(row)
        return len(stored)

    monkeypatch.setattr(pg_usage_ledger, "record_turn", deduplicating_record)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(
        usage_ledger,
        "_safe_tool_schema_tokens_for_toolsets",
        lambda toolsets: 0,
    )

    row_ids = [
        usage_ledger.record_gateway_turn(
            agent_result={
                "session_id": "session-1",
                "model": "m",
                "input_tokens": 10,
            },
            session_key="telegram:123",
            message_id="msg-1",
            source="telegram",
        )
        for _ in range(2)
    ]

    assert row_ids == [1, None]
    assert list(stored) == [("telegram", "telegram:123", "msg-1")]


def test_recent_turns_uses_canonical_reader_order(monkeypatch):
    calls = []
    expected = [
        {"session_id": "new", "model": "m2"},
        {"session_id": "old", "model": "m1"},
    ]

    def recent_turns(*, limit, strict=False):
        assert strict is True
        calls.append(limit)
        return expected

    monkeypatch.setattr(pg_usage_ledger, "recent_turns", recent_turns)

    assert usage_ledger.recent_turns(limit=2) == expected
    assert calls == [2]


def test_failed_turn_records_status_without_message_content(monkeypatch):
    rows = _capture_canonical_writes(monkeypatch)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(
        usage_ledger,
        "_safe_tool_schema_tokens_for_toolsets",
        lambda toolsets: 0,
    )

    usage_ledger.record_gateway_turn(
        agent_result={
            "session_id": "session-1",
            "model": "m",
            "failed": True,
            "error_type": "TimeoutError",
        },
        session_key="telegram:123",
        message_id="msg-failed",
        source="telegram",
        latency_ms=999,
    )

    row = rows[0]
    assert row["status"] == "failed"
    assert row["error_type"] == "TimeoutError"
    assert row["latency_ms"] == 999
    assert "content" not in row


def test_record_gateway_turn_falls_back_when_canonical_writer_raises(monkeypatch):
    class LegacySessionDb:
        def __init__(self):
            self.rows = []

        def record_turn_usage(self, row):
            self.rows.append(dict(row))
            return 9

    legacy = LegacySessionDb()
    monkeypatch.setattr(
        pg_usage_ledger,
        "record_turn",
        lambda _row, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("pg unavailable")
        ),
    )
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(
        usage_ledger,
        "_safe_tool_schema_tokens_for_toolsets",
        lambda toolsets: 0,
    )

    row_id = usage_ledger.record_gateway_turn(
        agent_result={"session_id": "session-1", "model": "m"},
        session_key="telegram:123",
        message_id="msg-1",
        source="telegram",
        session_db=legacy,
    )

    assert row_id == 9
    assert legacy.rows[0]["session_id"] == "session-1"


def test_recent_turns_falls_back_when_canonical_reader_raises(monkeypatch):
    class LegacySessionDb:
        def recent_turn_usage(self, limit):
            assert limit == 3
            return [{"session_id": "legacy"}]

    monkeypatch.setattr(
        pg_usage_ledger,
        "recent_turns",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("pg unavailable")),
    )

    assert usage_ledger.recent_turns(limit=3, session_db=LegacySessionDb()) == [
        {"session_id": "legacy"}
    ]


def test_sum_recent_tokens_uses_canonical_reader_in_strict_mode(monkeypatch):
    calls = []

    def sum_recent_tokens(*, since, source, session_key, strict=False):
        calls.append((since, source, session_key, strict))
        return 42

    monkeypatch.setattr(pg_usage_ledger, "sum_recent_tokens", sum_recent_tokens)

    assert usage_ledger.sum_recent_tokens(
        since=100.0,
        source="tui",
        session_key="session-1",
    ) == 42
    assert calls == [(100.0, "tui", "session-1", True)]


def test_sum_recent_tokens_falls_back_after_canonical_failure(monkeypatch):
    monkeypatch.setattr(
        pg_usage_ledger,
        "sum_recent_tokens",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("pg unavailable")),
    )
    monkeypatch.setattr(
        usage_ledger,
        "recent_turns",
        lambda **_kwargs: [
            {
                "timestamp": 101.0,
                "source": "tui",
                "session_key": "session-1",
                "total_tokens": 12,
            },
            {
                "timestamp": 99.0,
                "source": "tui",
                "session_key": "session-1",
                "total_tokens": 100,
            },
        ],
    )

    assert usage_ledger.sum_recent_tokens(
        since=100.0,
        source="tui",
        session_key="session-1",
    ) == 12
