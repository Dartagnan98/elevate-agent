"""C1 regression — get_compression_tip must resolve the true tip even when a
shadow write was dropped in either direction. PG resolves the fresh tip, then
the SQLite walk continues from there (direction-agnostic, never regresses).
"""
import elevate_state
from elevate_state import SessionDB


def _chain(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session(session_id="P", source="cli")
    db.append_message("P", "user", content="hi")
    db.end_session("P", "compression")
    db.create_session(session_id="C", source="cli", parent_session_id="P")
    return db


def test_sqlite_walk_finds_child_pg_missed(tmp_path, monkeypatch):
    db = _chain(tmp_path)
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    # PG dropped the shadow for C → returns the input unchanged.
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.get_compression_tip", lambda sid: sid
    )
    assert db.get_compression_tip("P") == "C", "SQLite walk must find the child PG missed"


def test_pg_tip_then_sqlite_extends(tmp_path, monkeypatch):
    db = _chain(tmp_path)
    db.end_session("C", "compression")
    db.create_session(session_id="D", source="cli", parent_session_id="C")
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: True)
    # PG knows up to C; SQLite has the newer grandchild D.
    monkeypatch.setattr(
        "elevate_cli.data.chat_sessions.get_compression_tip",
        lambda sid: "C" if sid == "P" else sid,
    )
    assert db.get_compression_tip("P") == "D", "must extend from PG's tip to the newest child"


def test_pure_sqlite_walk_when_pg_off(tmp_path, monkeypatch):
    db = _chain(tmp_path)
    monkeypatch.setattr(elevate_state, "_read_from_pg", lambda: False)
    assert db.get_compression_tip("P") == "C"
