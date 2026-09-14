"""The session-list preview must show the user's real first message, never the
compaction-internal scaffolding (role=user "[CONTEXT COMPACTION ...]" etc.) that a
compacted session persists as its first row. Exercises the real list_sessions SQL.
"""

import pytest

from elevate_state import SessionDB

INTERNAL = [
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted.",
    "[Your latest Plan panel plan was preserved] step one, step two.",
    "[Your active task list was preserved] todo: ship it.",
    "[RECENT AUTONOMOUS ACTIVITY] background work digest.",
]
_PREFIXES = (
    "[CONTEXT COMPACTION",
    "[Your latest Plan",
    "[Your active task",
    "[RECENT AUTONOMOUS",
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
    monkeypatch.delenv("ELEVATE_DISABLE_SQLITE_WRITE", raising=False)
    d = SessionDB(db_path=tmp_path / "state.db")
    yield d
    d.close()


def _preview_for(db, sid):
    for s in db.list_sessions_rich(limit=100):
        if s.get("id") == sid:
            return s.get("preview", "")
    raise AssertionError(f"session {sid} not returned by list_sessions_rich")


@pytest.mark.parametrize("internal", INTERNAL)
def test_preview_skips_internal_first_row(db, internal):
    db.create_session(session_id="s1", source="cli")
    db.append_message("s1", role="user", content=internal)              # scaffolding (first row)
    db.append_message("s1", role="assistant", content="acknowledged")
    db.append_message("s1", role="user", content="What is the weather today?")  # the real first msg
    preview = _preview_for(db, "s1")
    assert not preview.startswith(_PREFIXES), preview
    assert preview.startswith("What is the weather"), preview


def test_preview_unaffected_for_normal_session(db):
    db.create_session(session_id="s2", source="cli")
    db.append_message("s2", role="user", content="Hello there, a normal first message")
    assert _preview_for(db, "s2").startswith("Hello there")


def test_preview_blank_when_only_internal_user_rows(db):
    db.create_session(session_id="s3", source="cli")
    db.append_message("s3", role="user", content=INTERNAL[0])
    db.append_message("s3", role="assistant", content="ok")
    # No real user message -> preview should be blank, never the summary text.
    assert _preview_for(db, "s3") == ""
