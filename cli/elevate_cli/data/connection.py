"""Connection helpers for the central operational store.

Every read/write inside ``elevate_cli.data.*`` goes through ``connect()``.
The first call in a process applies any pending migrations; subsequent
calls reuse a cached "schema is up to date" flag and skip the migrator.

Backed by embedded Postgres (see ``pg_server.py``). The
``sqlite3.Connection`` callers used to receive is now a thin shim
(``PgConnection``) over a pooled ``psycopg.Connection`` that exposes the
same ``execute() / commit() / rollback() / in_transaction / row_factory``
surface, so the 60+ callers in ``elevate_cli/`` don't have to change.

The shim also translates legacy ``?``-style placeholders to psycopg's
``%s`` style so existing SQL works unchanged.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from elevate_cli.data import migrations
from elevate_cli.data import pg_server


# Application DB inside the embedded Postgres instance. One DB per
# Elevate install — matches the old single ``operational.db`` file.
_APP_DB_NAME = "elevate_operational"

# Module-level connection pool. Embedded Postgres is single-host, so one
# pool is plenty. Sized to handle the dashboard + a few sync jobs hitting
# the DB concurrently.
_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()
_schema_lock = threading.Lock()
_schema_ready: bool = False


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        pg_server.ensure_database(_APP_DB_NAME)
        uri = pg_server.get_uri(_APP_DB_NAME)
        _pool = ConnectionPool(
            uri,
            min_size=1,
            max_size=10,
            kwargs={
                "row_factory": dict_row,
                "autocommit": False,
                # The embedded pgserver package can be relocated between
                # Python runtimes. Parallel workers inherit the original
                # install path and can fail on large dashboard scans; the app
                # benefits more from predictable local reads than parallelism.
                "options": (
                    "-c max_parallel_workers_per_gather=0 "
                    "-c max_parallel_maintenance_workers=0 "
                    "-c max_parallel_workers=0"
                ),
            },
            open=True,
        )
        return _pool


def _ensure_schema(conn: "PgConnection") -> None:
    """Run pending migrations + one-shot legacy-data import.

    Both gated by an in-process flag so the work only happens on the
    first ``connect()`` call. The legacy SQLite → PG import is itself
    idempotent (sentinel row in ``_schema_migrations``), but the
    in-process flag spares us the round-trip on every subsequent
    connection.
    """
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        migrations.run_pending(conn)
        # Import here to break a circular import: _pg_data_migrate
        # imports `_APP_DB_NAME` and `_Row` from this module.
        from elevate_cli.data import _pg_data_migrate
        _pg_data_migrate.maybe_migrate_sqlite_to_pg(conn)
        # Memory-store SQLite → PG one-shot import. Runs after the
        # operational copy so the FK targets it cares about (none cross
        # the boundary today, but if we ever link memory_facts to a
        # contact, that's the safe order).
        from elevate_cli.data import _pg_memory_migrate
        _pg_memory_migrate.maybe_migrate_memory_store(conn)
        # Gateway Responses-API LRU cache one-shot import. Tiny (20KB on
        # average), runs after memory because it depends on nothing.
        from elevate_cli.data import _pg_response_migrate
        _pg_response_migrate.maybe_migrate_response_store(conn)
        # Kanban board (~/.elevate/kanban.db) SQLite → PG. Usually a
        # no-op on Dartagnan's machine (empty kanban.db at cutover) but
        # the migrator handles populated boards on other installs.
        from elevate_cli.data import _pg_kanban_migrate
        _pg_kanban_migrate.maybe_migrate_kanban_store(conn)
        # Outreach store (~/.elevate/tools/data/outreach/outreach.db)
        # SQLite → PG. Also remaps events.template_id from the stale
        # 0001-era seed UUIDs to the freshly-imported live ones via
        # _outreach_template_remap_stash (populated by 0011 SQL).
        from elevate_cli.data import _pg_outreach_migrate
        _pg_outreach_migrate.maybe_migrate_outreach_store(conn)
        _schema_ready = True


def _reset_schema_cache() -> None:
    """Test helper — drop cached schema, pool, and embedded server state."""
    global _pool, _schema_ready
    with _schema_lock:
        _schema_ready = False
    with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        pool.close()
    pg_server._reset_server_for_tests()


# ─── Placeholder translation ───────────────────────────────────────────
# Legacy code uses sqlite3-style ``?`` placeholders. Psycopg expects
# ``%s``. Convert at execute-time so we don't have to touch every SQL
# string in the codebase. Skip translation when the query already uses
# ``%s`` or when there are no ``?`` outside string literals.

_QMARK_RE = re.compile(
    r"""
    (
        '(?:[^']|'')*'       # single-quoted string (with '' escape)
      | "(?:[^"]|"")*"       # double-quoted identifier (with "" escape)
      | --[^\n]*             # line comment
      | /\*.*?\*/            # block comment
    )
    | \?                      # the placeholder we want
    """,
    re.VERBOSE | re.DOTALL,
)


def _translate_placeholders(sql: str) -> str:
    # If the SQL has no legacy ``?`` placeholders, it's already
    # PG-native — leave it alone (literal ``%`` and existing ``%s``
    # placeholders are the caller's responsibility).
    if "?" not in sql:
        return sql

    # Legacy sqlite SQL: ``?`` placeholders + free ``%`` inside LIKE
    # patterns (``'%,'``, ``'%foo%'``). Psycopg sees any unescaped
    # ``%`` as the start of a placeholder and errors. Double every
    # literal ``%`` first, then translate ``?`` to the (single-``%``)
    # placeholder ``%s``.
    escaped = sql.replace("%", "%%")

    def _sub(m: re.Match) -> str:
        if m.group(1) is not None:
            return m.group(1)
        return "%s"

    return _QMARK_RE.sub(_sub, escaped)


# Sqlite ``INSERT OR IGNORE`` ↔ Postgres ``INSERT ... ON CONFLICT DO NOTHING``.
# Catches both ``INSERT OR IGNORE INTO`` and the rarer ``INSERT OR IGNORE
# (cols) ...`` shape. Only fires at the start of a statement to avoid
# rewriting unrelated literals.
_INSERT_OR_IGNORE_RE = re.compile(
    r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
    re.IGNORECASE,
)


def _translate_sqlite_isms(sql: str) -> str:
    """Convert SQLite-only DML keywords to Postgres equivalents.

    Conservative — only handles ``INSERT OR IGNORE`` (the only sqlite-ism
    used by operational-DB call sites; ``INSERT OR REPLACE`` lives in
    out-of-scope per-connector index DBs that stay on SQLite). Appends
    ``ON CONFLICT DO NOTHING`` if the rewritten statement doesn't already
    have an ON CONFLICT clause.
    """
    if not _INSERT_OR_IGNORE_RE.search(sql):
        return sql
    rewritten = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", sql)
    if re.search(r"\bON\s+CONFLICT\b", rewritten, re.IGNORECASE):
        return rewritten
    # Append before trailing `;` if present, else at end.
    stripped = rewritten.rstrip()
    if stripped.endswith(";"):
        return stripped[:-1] + " ON CONFLICT DO NOTHING;"
    return stripped + " ON CONFLICT DO NOTHING"


def _prepare_sql(sql: str) -> str:
    """Run both translation passes."""
    return _translate_sqlite_isms(_translate_placeholders(sql))


# ─── PgConnection shim ─────────────────────────────────────────────────


class _PgCursorShim:
    """Cursor that translates ``?`` → ``%s`` and exposes sqlite-ish attrs.

    Forwards everything else to the underlying psycopg cursor.
    """

    def __init__(self, cur: "psycopg.Cursor[Any]"):
        self._cur = cur

    @property
    def lastrowid(self) -> Optional[int]:
        # Not directly available in PG — callers that need it use
        # ``RETURNING id`` instead. Returning None keeps the attribute
        # available for sqlite-compat call sites that probe it.
        return None

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def execute(self, sql: str, params: Sequence[Any] | dict | None = None) -> "_PgCursorShim":
        self._cur.execute(_prepare_sql(sql), params or ())
        return self

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> "_PgCursorShim":
        self._cur.executemany(_prepare_sql(sql), list(seq))
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return _Row(row) if row is not None else None

    def fetchall(self):
        return [_Row(r) for r in self._cur.fetchall()]

    def fetchmany(self, size: int = 1):
        return [_Row(r) for r in self._cur.fetchmany(size)]

    def close(self) -> None:
        self._cur.close()

    def __iter__(self):
        for row in self._cur:
            yield _Row(row)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _Row(dict):
    """Dict-with-index-access so ``row[0]`` and ``row['col']`` both work.

    sqlite3.Row supported both; lots of call sites use the index form
    (``row[0]``), so we preserve it without forcing a sweep.
    """

    __slots__ = ("_keys",)

    def __init__(self, source: dict):
        super().__init__(source)
        self._keys = list(source.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return super().__getitem__(self._keys[key])
        return super().__getitem__(key)

    def keys(self):
        return self._keys

    def __iter__(self):
        # sqlite3.Row iterates values, not keys. Match that.
        for k in self._keys:
            yield super().__getitem__(k)


class PgConnection:
    """Sqlite-compatible wrapper around a pooled psycopg.Connection.

    Lifecycle: instances are created/yielded by ``connect()`` and live
    only inside that ``with`` block. ``commit()`` / ``rollback()`` /
    ``close()`` are delegated to the underlying connection; the pool
    reclaims it on context exit.
    """

    def __init__(self, raw: "psycopg.Connection[Any]"):
        self._raw = raw
        # sqlite3-compatible knob; psycopg already returns dict-like rows.
        self.row_factory = _Row

    # sqlite3.Connection.in_transaction equivalent.
    @property
    def in_transaction(self) -> bool:
        # psycopg.TransactionStatus enum lives at psycopg.pq
        try:
            return self._raw.info.transaction_status != psycopg.pq.TransactionStatus.IDLE
        except Exception:
            return False

    def cursor(self) -> _PgCursorShim:
        return _PgCursorShim(self._raw.cursor())

    def execute(self, sql: str, params: Sequence[Any] | dict | None = None) -> _PgCursorShim:
        cur = self._raw.cursor()
        cur.execute(_prepare_sql(sql), params or ())
        return _PgCursorShim(cur)

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> _PgCursorShim:
        cur = self._raw.cursor()
        cur.executemany(_prepare_sql(sql), list(seq))
        return _PgCursorShim(cur)

    def executescript(self, script: str) -> None:
        """sqlite3 compat — runs multi-statement SQL.

        Postgres can execute multiple semicolon-separated statements in
        one ``cur.execute()`` call as long as none of them are
        parameterized. Used by the migration runner.
        """
        with self._raw.cursor() as cur:
            cur.execute(script)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        try:
            self._raw.rollback()
        except psycopg.Error:
            pass

    def close(self) -> None:
        # Pool returns the connection on context-exit; we don't really
        # close here. Provided for sqlite3-compat.
        pass


# ─── Public API ────────────────────────────────────────────────────────


@contextmanager
def connect() -> Iterator[PgConnection]:
    """Open a pooled connection to the operational DB and yield it.

    Auto-commits on clean exit, rolls back on exception, releases to
    the pool always. API matches the old sqlite3-based version.
    """
    pool = _get_pool()
    with pool.connection() as raw:
        with raw.cursor() as cur:
            cur.execute("SET max_parallel_workers_per_gather = 0")
        conn = PgConnection(raw)
        try:
            _ensure_schema(conn)
            yield conn
            raw.commit()
        except Exception:
            try:
                raw.rollback()
            except psycopg.Error:
                pass
            raise


@contextmanager
def transaction(conn: PgConnection) -> Iterator[PgConnection]:
    """Open an explicit write transaction inside an already-open ``conn``.

    Matches the old sqlite ``BEGIN IMMEDIATE`` semantics: callers want a
    single atomic block (approve → enqueue must atomically pair the
    task-state flip with the send_queue insert).
    """
    raw = conn._raw  # noqa: SLF001 — internal shim helper
    # If we're already in a tx (which is the default in psycopg when
    # autocommit=False), commit it first so the new explicit one starts
    # fresh. Mirrors the old ROLLBACK-then-BEGIN pattern.
    if conn.in_transaction:
        raw.commit()
    # Psycopg auto-begins on the next statement; just yield.
    try:
        yield conn
    except Exception:
        raw.rollback()
        raise
    else:
        raw.commit()


__all__ = ["connect", "transaction", "PgConnection"]
