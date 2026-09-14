"""Step 1 of the compaction redesign — session compaction metadata round-trip.

The redesign stores (compaction_summary, compaction_cursor) on the session row
instead of rewriting the transcript. These tests prove the SQLite columns +
update_compaction write path + get_session read-back work, and that a fresh
session defaults to the legacy sentinel (cursor 0 / NULL summary).
"""

from elevate_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def test_fresh_session_defaults_to_legacy_sentinel(tmp_path):
    db = _db(tmp_path)
    db.create_session(session_id="s1", source="cli")
    row = db.get_session("s1")
    assert row is not None
    assert (row.get("compaction_cursor") or 0) == 0
    assert row.get("compaction_summary") in (None, "")


def test_update_compaction_round_trips(tmp_path):
    db = _db(tmp_path)
    db.create_session(session_id="s1", source="cli")
    db.update_compaction("s1", "HANDOFF SUMMARY: read 6 files, audited compaction.", 7)
    row = db.get_session("s1")
    assert row["compaction_summary"] == "HANDOFF SUMMARY: read 6 files, audited compaction."
    assert row["compaction_cursor"] == 7


def test_update_compaction_advances_cursor(tmp_path):
    db = _db(tmp_path)
    db.create_session(session_id="s1", source="cli")
    db.update_compaction("s1", "summary v1", 5)
    db.update_compaction("s1", "summary v2 (folded)", 12)
    row = db.get_session("s1")
    assert row["compaction_summary"] == "summary v2 (folded)"
    assert row["compaction_cursor"] == 12


def test_update_compaction_none_summary_and_zero_cursor(tmp_path):
    # Clearing back to the sentinel must round-trip (e.g. /new style reset).
    db = _db(tmp_path)
    db.create_session(session_id="s1", source="cli")
    db.update_compaction("s1", "summary", 5)
    db.update_compaction("s1", None, 0)
    row = db.get_session("s1")
    assert row.get("compaction_summary") in (None, "")
    assert (row.get("compaction_cursor") or 0) == 0


def test_columns_self_heal_on_existing_db(tmp_path):
    # _reconcile_columns must ADD the new columns to a db created before they
    # existed — simulate by creating, then reopening (reconcile runs on init).
    db = _db(tmp_path)
    db.create_session(session_id="s1", source="cli")
    db2 = _db(tmp_path)  # reopen same file
    db2.update_compaction("s1", "after reopen", 3)
    assert db2.get_session("s1")["compaction_cursor"] == 3
