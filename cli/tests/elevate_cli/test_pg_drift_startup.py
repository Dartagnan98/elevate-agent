"""C2 — startup drift reconcile is safe-direction only (insert, never
delete), honors the live-write cutoff, and fails open."""
from __future__ import annotations

import contextlib
import sqlite3
import time

import pytest

from elevate_cli.data import _pg_drift_reconcile as mod


class _FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class _FakePg:
    """Records every statement; serves signature SELECTs from `pg_messages`."""

    def __init__(self, pg_messages=None, existing_session_ids=None):
        self.statements: list[str] = []
        self.pg_messages = pg_messages or []
        self.existing_session_ids = set(existing_session_ids or [])

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if sql.startswith("SELECT session_id, role, timestamp"):
            return _FakeCursor(rows=self.pg_messages)
        if sql.startswith("INSERT INTO chat_sessions"):
            new = params[0] not in self.existing_session_ids
            self.existing_session_ids.add(params[0])
            return _FakeCursor(rowcount=1 if new else 0)
        return _FakeCursor(rowcount=1)

    def commit(self):
        pass


@pytest.fixture
def sqlite_db(tmp_path):
    path = tmp_path / "elevate.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL);
        CREATE TABLE messages (
            session_id TEXT, role TEXT, content TEXT,
            timestamp REAL NOT NULL, tool_call_id TEXT
        );
        """
    )
    conn.execute("INSERT INTO sessions VALUES ('s1', 'cli', 100.0)")
    conn.execute(
        "INSERT INTO messages VALUES ('s1', 'user', 'old row', 100.0, NULL)"
    )
    conn.execute(
        "INSERT INTO messages VALUES ('s1', 'user', 'already in pg', 101.0, NULL)"
    )
    conn.commit()
    conn.close()
    return path


def _patch_pg(monkeypatch, fake):
    @contextlib.contextmanager
    def connect():
        yield fake

    monkeypatch.setattr(mod.pg_connection, "connect", connect)


def test_backfills_missing_and_never_deletes(monkeypatch, sqlite_db):
    fake = _FakePg(
        pg_messages=[
            {
                "session_id": "s1",
                "role": "user",
                "timestamp": 101.0,
                "content": "already in pg",
                "tool_call_id": None,
            }
        ]
    )
    _patch_pg(monkeypatch, fake)

    result = mod.reconcile_missing_in_pg(sqlite_db)

    assert result["sessions_inserted"] == 1
    assert result["messages_inserted"] == 1  # only "old row"
    assert not any(s.startswith("DELETE") for s in fake.statements)


def test_session_count_is_actual_inserts_not_scanned(monkeypatch, sqlite_db):
    fake = _FakePg(existing_session_ids={"s1"})
    _patch_pg(monkeypatch, fake)
    result = mod.reconcile_missing_in_pg(sqlite_db)
    assert result["sessions_inserted"] == 0  # conflict no-op, not counted


def test_before_cutoff_excludes_live_writes(monkeypatch, sqlite_db):
    conn = sqlite3.connect(sqlite_db)
    conn.execute(
        "INSERT INTO messages VALUES ('s1', 'user', 'mid-scan write', ?, NULL)",
        (time.time() + 3600,),
    )
    conn.commit()
    conn.close()

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    result = mod.reconcile_missing_in_pg(sqlite_db, before=200.0)
    assert result["messages_inserted"] == 2  # both old rows, not the live one


def test_startup_kickoff_fails_open(monkeypatch):
    from elevate_cli import web_server

    def boom(*a, **k):
        raise RuntimeError("pg unreachable")

    monkeypatch.setattr(mod, "reconcile_missing_in_pg", boom)
    web_server._kickoff_drift_backfill()  # must not raise
    for t in __import__("threading").enumerate():
        if t.name == "pg-drift-backfill":
            t.join(timeout=10)
    # reaching here without an exception is the assertion
