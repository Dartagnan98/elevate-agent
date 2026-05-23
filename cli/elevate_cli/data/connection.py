"""Connection helpers for the central operational store.

Every read/write inside ``elevate_cli.data.*`` goes through ``connect()``.
The first call in a process applies any pending migrations; subsequent
calls reuse a cached "schema is up to date" flag and skip the migrator.

PRAGMAs are set on every connection — SQLite does not persist them in
the database file:

* ``journal_mode=WAL`` — writers don't block readers
* ``synchronous=NORMAL`` — durable + fast on SSDs (acceptable risk for
  this workload, matches outreach.db's existing settings)
* ``foreign_keys=ON`` — CHECK constraints rely on FKs being enforced
* ``busy_timeout=5000`` — give the WAL 5s before throwing SQLITE_BUSY
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from elevate_cli.data import migrations
from elevate_cli.data.paths import operational_db_path


_schema_lock = threading.Lock()
_schema_ready_paths: set[str] = set()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")


def _ensure_schema(conn: sqlite3.Connection, db_path: str) -> None:
    """Run pending migrations exactly once per DB path per process.

    The cache is keyed by DB path so tests redirecting ``ELEVATE_HOME`` to
    different tempdirs each get a fresh migration run on first connect.
    The lock keeps two threads from racing the migrator.
    """
    if db_path in _schema_ready_paths:
        return
    with _schema_lock:
        if db_path in _schema_ready_paths:
            return
        migrations.run_pending(conn)
        _schema_ready_paths.add(db_path)


def _reset_schema_cache() -> None:
    """Test helper — drop the "schema is up to date" cache so the next
    ``connect()`` re-runs the migrator. Useful when a test redirects
    ``ELEVATE_HOME`` to a fresh tmp dir."""
    with _schema_lock:
        _schema_ready_paths.clear()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection to ``operational.db`` and yield it.

    Auto-commits on clean exit, rolls back on exception, closes always.
    """
    path = operational_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    try:
        _ensure_schema(conn, str(path))
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Wrap a block in an explicit IMMEDIATE transaction.

    Mirrors :func:`elevate_cli.outreach_db.transaction`: the caller has
    already opened a connection, and they want an exclusive write lock
    for the whole block (e.g. approve → enqueue must atomically pair the
    task-state flip with the send_queue insert).
    """
    if conn.in_transaction:
        conn.execute("ROLLBACK")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


__all__ = ["connect", "transaction"]
