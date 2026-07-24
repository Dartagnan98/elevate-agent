"""Reliability release (section D): JSONL-only session retention + the
non-destructive external-content FTS5 de-bloat migration.

Invariants asserted here:
  * The auto-maintenance sweep removes stale on-disk transcript files but
    deletes NO state.db rows (search recall over history is preserved).
  * The broadened predicate ages out never-ended sessions too, while the
    active-process guard + age threshold keep live sessions untouched.
  * The manual (``files_only=False``) prune path still deletes DB rows —
    unchanged behaviour for ``elevate sessions prune``.
  * After the inline->external-content FTS migration, search still returns
    hits for content, tool_name and tool_calls (no #16751 regression) and
    the redundant per-message copy table is gone with all rows intact.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from elevate_state import SessionDB


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
    monkeypatch.setenv("ELEVATE_DISABLE_PG_SHADOW", "1")
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        yield db
    finally:
        db.close()


def _seed(db: SessionDB, sessions_dir: Path) -> dict[str, float]:
    now = time.time()
    old = now - 200 * 86400
    recent = now - 2 * 86400
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for sid in ("old-ended", "old-open", "recent-open"):
        db.create_session(sid, "test")
        db.append_message(sid, "user", content=f"hi from {sid}")
        (sessions_dir / f"{sid}.jsonl").write_text("{}\n")
        (sessions_dir / f"request_dump_{sid}_1.json").write_text("{}")
    db._conn.execute(
        "UPDATE sessions SET started_at=?, ended_at=? WHERE id='old-ended'", (old, old + 10)
    )
    db._conn.execute(
        "UPDATE sessions SET started_at=?, ended_at=NULL WHERE id='old-open'", (old,)
    )
    db._conn.execute(
        "UPDATE sessions SET started_at=?, ended_at=NULL WHERE id='recent-open'", (recent,)
    )
    db._conn.commit()
    return {"now": now, "old": old, "recent": recent}


def test_auto_prune_sweeps_jsonl_only_and_keeps_db_rows(store, tmp_path):
    sessions_dir = tmp_path / "sessions"
    _seed(store, sessions_dir)

    result = store.maybe_auto_prune_and_vacuum(
        retention_days=90,
        min_interval_hours=0,
        vacuum=True,
        sessions_dir=sessions_dir,
        files_only=True,
    )
    assert "error" not in result
    assert result["skipped"] is False

    # Old sessions (ended OR never-ended) had their on-disk transcripts swept.
    assert not (sessions_dir / "old-ended.jsonl").exists()
    assert not (sessions_dir / "request_dump_old-ended_1.json").exists()
    assert not (sessions_dir / "old-open.jsonl").exists()
    # Recent session's files are kept.
    assert (sessions_dir / "recent-open.jsonl").exists()

    # No DB rows deleted — every session and message is intact.
    assert store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3
    assert store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3


def test_active_process_guard_protects_never_ended_session(store, tmp_path):
    sessions_dir = tmp_path / "sessions"
    _seed(store, sessions_dir)

    # Guard claims 'old-open' is still live -> its files must survive.
    def active_fn(session_id: str) -> bool:
        return session_id == "old-open"

    store.maybe_auto_prune_and_vacuum(
        retention_days=90,
        min_interval_hours=0,
        sessions_dir=sessions_dir,
        files_only=True,
        has_active_processes_fn=active_fn,
    )

    assert (sessions_dir / "old-open.jsonl").exists()  # guarded, kept
    assert not (sessions_dir / "old-ended.jsonl").exists()  # not guarded, swept
    assert store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3


def test_files_only_never_deletes_db_rows_even_without_sessions_dir(store, tmp_path):
    sessions_dir = tmp_path / "sessions"
    _seed(store, sessions_dir)
    # files_only with no sessions_dir is a no-op that touches nothing.
    swept = store.prune_sessions(older_than_days=90, files_only=True, sessions_dir=None)
    assert swept == 0
    assert store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3


def test_manual_prune_default_still_deletes_db_rows(store, tmp_path):
    """Regression guard: the default (files_only=False) path — used by the
    manual ``elevate sessions prune`` command — must keep deleting DB rows."""
    sessions_dir = tmp_path / "sessions"
    _seed(store, sessions_dir)

    deleted = store.prune_sessions(older_than_days=90, sessions_dir=sessions_dir)
    # Only the ENDED old session is deleted by the default (unbroadened) path.
    assert deleted == 1
    remaining = {
        row[0] for row in store._conn.execute("SELECT id FROM sessions").fetchall()
    }
    assert remaining == {"old-open", "recent-open"}


def _search(db: SessionDB, q: str):
    return [m["role"] for m in db.search_messages(q, limit=10)]


def test_fts_external_content_search_fresh_build(store):
    sid = store.create_session("s1", "test")
    store.append_message(sid, "user", content="deploy the docker kubernetes cluster")
    store.append_message(
        sid, "assistant", content="ok",
        tool_name="ripgrep_search", tool_calls={"pattern": "needle_in_toolcalls"},
    )

    # content, tool_name and tool_calls all remain searchable.
    assert _search(store, "docker") == ["user"]
    assert _search(store, "ripgrep_search") == ["assistant"]
    assert _search(store, "needle_in_toolcalls") == ["assistant"]

    # External-content: FTS5 stores no redundant per-message %_content copy.
    copy_tables = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('messages_fts_content','messages_fts_trigram_content')"
    ).fetchall()
    assert copy_tables == []


_OLD_INLINE_FTS = """
DROP TRIGGER IF EXISTS messages_fts_insert;
DROP TRIGGER IF EXISTS messages_fts_delete;
DROP TRIGGER IF EXISTS messages_fts_update;
DROP TRIGGER IF EXISTS messages_fts_trigram_insert;
DROP TRIGGER IF EXISTS messages_fts_trigram_delete;
DROP TRIGGER IF EXISTS messages_fts_trigram_update;
DROP TABLE IF EXISTS messages_fts;
DROP TABLE IF EXISTS messages_fts_trigram;
DROP VIEW IF EXISTS messages_fts_source;
CREATE VIRTUAL TABLE messages_fts USING fts5(content);
CREATE VIRTUAL TABLE messages_fts_trigram USING fts5(content, tokenize='trigram');
"""


def test_fts_migration_inline_to_external_preserves_search_and_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
    monkeypatch.setenv("ELEVATE_DISABLE_PG_SHADOW", "1")
    db_path = tmp_path / "state.db"

    # Build a current DB, then downgrade its FTS to the pre-v16 INLINE shape
    # (which keeps a full redundant copy in a messages_fts_content table).
    db = SessionDB(db_path=db_path)
    sid = db.create_session("s1", "test")
    db.append_message(sid, "user", content="deploy the docker cluster")
    db.append_message(
        sid, "assistant", content="ok",
        tool_name="ripgrep_search", tool_calls={"pat": "needle_tc"},
    )
    db._conn.executescript(_OLD_INLINE_FTS)
    concat = (
        "COALESCE(content,'')||' '||COALESCE(tool_name,'')||' '||COALESCE(tool_calls,'')"
    )
    db._conn.execute(
        f"INSERT INTO messages_fts(rowid, content) SELECT id, {concat} FROM messages"
    )
    db._conn.execute(
        f"INSERT INTO messages_fts_trigram(rowid, content) SELECT id, {concat} FROM messages"
    )
    db._conn.execute("UPDATE schema_version SET version=15")
    db._conn.commit()
    # Inline mode really does keep a per-message copy table.
    assert db._conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='messages_fts_content'"
    ).fetchone()[0] == 1
    db.close()

    # Reopen -> the v16 migration converts both indexes to external-content.
    db2 = SessionDB(db_path=db_path)
    try:
        assert db2._conn.execute("SELECT version FROM schema_version").fetchone()[0] == 16
        # The redundant inline copy table is gone.
        assert db2._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='messages_fts_content'"
        ).fetchone()[0] == 0
        # Search still returns hits across all three indexed fields.
        assert _search(db2, "docker") == ["user"]
        assert _search(db2, "ripgrep_search") == ["assistant"]
        assert _search(db2, "needle_tc") == ["assistant"]
        # No message rows were lost in the migration.
        assert db2._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    finally:
        db2.close()
