from __future__ import annotations

import json
import sqlite3

from elevate_state import SessionDB
from gateway import usage_ledger


def test_record_gateway_turn_writes_program_specific_row_to_state_db(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    session_db = SessionDB(db_path=db_path)
    session_db.create_session("session-1", source="telegram", model="gpt-5.5")
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 100)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_toolsets", lambda toolsets: 250)

    try:
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
            session_db=session_db,
        )
    finally:
        session_db.close()

    assert row_id == 1
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM turn_usage").fetchone()
        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    assert session_count == 1
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


def test_record_gateway_turn_prefers_agent_result_session_id_after_split(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    session_db = SessionDB(db_path=db_path)
    session_db.create_session("old-session", source="telegram", model="m")
    session_db.create_session("new-session", source="telegram", model="m")
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_toolsets", lambda toolsets: 0)

    try:
        usage_ledger.record_gateway_turn(
            agent_result={"session_id": "new-session", "model": "m"},
            session_id="old-session",
            source="telegram",
            session_db=session_db,
        )
        rows = usage_ledger.recent_turns(limit=1, session_db=session_db)
    finally:
        session_db.close()

    assert rows[0]["session_id"] == "new-session"


def test_duplicate_platform_event_is_not_double_counted(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    session_db = SessionDB(db_path=db_path)
    session_db.create_session("session-1", source="telegram", model="m")
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_toolsets", lambda toolsets: 0)

    try:
        for _ in range(2):
            usage_ledger.record_gateway_turn(
                agent_result={"session_id": "session-1", "model": "m", "input_tokens": 10},
                session_key="telegram:123",
                message_id="msg-1",
                source="telegram",
                session_db=session_db,
            )
    finally:
        session_db.close()

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM turn_usage").fetchone()[0]

    assert count == 1


def test_recent_turns_tie_breaks_by_newest_id(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    session_db = SessionDB(db_path=db_path)
    session_db.create_session("old", source="telegram", model="m1")
    session_db.create_session("new", source="telegram", model="m2")
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_toolsets", lambda toolsets: 0)
    monkeypatch.setattr(usage_ledger.time, "time", lambda: 123.0)

    try:
        usage_ledger.record_gateway_turn(
            agent_result={"session_id": "old", "model": "m1"},
            source="telegram",
            session_db=session_db,
        )
        usage_ledger.record_gateway_turn(
            agent_result={"session_id": "new", "model": "m2"},
            source="telegram",
            session_db=session_db,
        )

        rows = usage_ledger.recent_turns(limit=2, session_db=session_db)
    finally:
        session_db.close()

    assert [row["session_id"] for row in rows] == ["new", "old"]


def test_failed_turn_records_status_without_message_content(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    session_db = SessionDB(db_path=db_path)
    session_db.create_session("session-1", source="telegram", model="m")
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_defs", lambda tools: 0)
    monkeypatch.setattr(usage_ledger, "_safe_tool_schema_tokens_for_toolsets", lambda toolsets: 0)

    try:
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
            session_db=session_db,
        )
    finally:
        session_db.close()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM turn_usage").fetchone()

    assert row["status"] == "failed"
    assert row["error_type"] == "TimeoutError"
    assert row["latency_ms"] == 999
    assert "content" not in row.keys()
