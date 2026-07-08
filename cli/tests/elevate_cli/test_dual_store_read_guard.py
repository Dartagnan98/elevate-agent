"""A1 regression — PG-first reads must not serve a short/stale transcript.

A dropped Postgres shadow write leaves PG behind the authoritative SQLite copy.
get_messages / get_messages_as_conversation / message_count are PG-first; without
a completeness guard they serve the truncated PG copy to the customer and the
agent's context. These assert the asymmetric guard: fall back to SQLite when PG
is short/empty, but keep trusting PG for a foreign session (SQLite has fewer/zero
rows — that session lives only in PG).
"""
from __future__ import annotations

import elevate_state
from elevate_state import SessionDB


def _seed(tmp_path, n=5):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session(session_id="s1", source="cli")
    for i in range(n):
        db.append_message("s1", "user", content=f"m{i}", client_message_id=f"c{i}")
    return db


def _pg_rows(n):
    return [{"role": "user", "content": f"m{i}"} for i in range(n)]


def test_get_messages_falls_back_when_pg_short(tmp_path, monkeypatch):
    db = _seed(tmp_path, n=5)
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    # PG is missing the last write (dropped shadow).
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.get_messages", lambda sid: _pg_rows(4)
    )
    msgs = db.get_messages("s1")
    assert len(msgs) == 5, "should serve authoritative SQLite when PG is short"


def test_get_messages_trusts_pg_for_foreign_session(tmp_path, monkeypatch):
    db = SessionDB(db_path=tmp_path / "state.db")  # no local rows
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.get_messages", lambda sid: _pg_rows(3)
    )
    msgs = db.get_messages("foreign")
    assert len(msgs) == 3, "must NOT blank a foreign PG-only session (asymmetric rule)"


def test_get_messages_uses_pg_when_complete(tmp_path, monkeypatch):
    db = _seed(tmp_path, n=3)
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    calls = {"pg": 0}

    def fake_pg(sid):
        calls["pg"] += 1
        return _pg_rows(3)

    monkeypatch.setattr("elevate_cli.data.chat_sessions.get_messages", fake_pg)
    msgs = db.get_messages("s1")
    assert len(msgs) == 3 and calls["pg"] == 1, "PG should be used when complete"


def test_conversation_falls_back_on_empty_pg(tmp_path, monkeypatch):
    db = _seed(tmp_path, n=4)
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    # Empty (non-None) PG result must NOT skip the SQLite fallback (the is-None bug).
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.get_messages_for_sessions", lambda sids: []
    )
    conv = db.get_messages_as_conversation("s1")
    assert len(conv) == 4, "empty PG must fall back to SQLite, not return empty"


def test_message_count_prefers_authoritative_sqlite(tmp_path, monkeypatch):
    db = _seed(tmp_path, n=6)
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.message_count", lambda sid: 4
    )
    assert db.message_count("s1") == 6, "count must reflect authoritative SQLite"
