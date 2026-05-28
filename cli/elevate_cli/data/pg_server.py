"""Embedded Postgres lifecycle for the central operational store.

Replaces SQLite. Postgres runs as a child process of the gateway against
a per-install data dir under ``$ELEVATE_HOME/pgdata/``. Communication is
via a Unix domain socket (no TCP port), so there's no port collision
risk between Elevate installs on the same machine.

Why embedded Postgres and not SQLite:
- SQLite has a single global writer lock. A hung sync (Apple chat.db
  slow read, Composio stalled fetch) held that lock for hours on
  2026-05-24, bricking every dashboard surface with
  ``database is locked``. Postgres' MVCC eliminates this failure class.
- Real concurrent writers means the dashboard can read while syncs
  write, with zero contention.
- Data still lives 100% on the user's machine. Postgres is just an
  in-process storage engine. Privacy posture is identical to SQLite.

Bundled via the ``pgserver`` package (~80MB Postgres 16 binary, one-time
download cached in ``~/.cache/pgserver/``). First boot does ``initdb``
(~2s); subsequent boots are ~1s.
"""

from __future__ import annotations

import atexit
import os
import threading
from pathlib import Path
from typing import Optional

import pgserver

from elevate_constants import get_elevate_home


# Module-level singleton — one embedded Postgres per process. Gateway boots
# it during startup; everything else reads ``get_uri()`` lazily.
_server: Optional[object] = None
_server_lock = threading.Lock()


def pg_data_dir() -> Path:
    """Directory holding Postgres' data files. Survives process restarts."""
    root = get_elevate_home() / "pgdata"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_mode() -> str | None:
    """How pgserver shuts the postmaster down on process exit.

    ``stop`` flushes WAL and stops cleanly. ``None`` means leave it
    running (don't use — orphan postmaster). ``delete`` wipes the data
    dir (only for ephemeral test mode).
    """
    return os.environ.get("ELEVATE_PG_CLEANUP", "stop") or None


def get_server() -> object:
    """Boot embedded Postgres (idempotent) and return the pgserver handle."""
    global _server
    if _server is not None:
        return _server
    with _server_lock:
        if _server is not None:
            return _server
        data_dir = pg_data_dir()
        # cleanup_mode="stop" → pgserver runs `pg_ctl stop` in its atexit
        # handler, ensuring no orphan postmaster after gateway exit.
        srv = pgserver.get_server(str(data_dir), cleanup_mode=_cleanup_mode())
        _server = srv
        atexit.register(_atexit_stop)
        return _server


def get_uri(database: str = "postgres") -> str:
    """psycopg-compatible connection URI for the running embedded server.

    Uses a Unix domain socket under the data dir — no TCP port involved.
    """
    srv = get_server()
    uri = srv.get_uri()
    if database != "postgres":
        # pgserver hands us postgres://...?host=<socket_dir>; swap the
        # default ``postgres`` db for ours via the path component.
        # Format: postgresql://user:pass@/dbname?host=...
        if "?" in uri:
            base, query = uri.split("?", 1)
        else:
            base, query = uri, ""
        # base ends with /postgres — replace just the db name
        if base.endswith("/postgres"):
            base = base[: -len("/postgres")] + "/" + database
        uri = f"{base}?{query}" if query else base
    return uri


def ensure_database(database: str) -> None:
    """Create ``database`` if it doesn't exist.

    Postgres can't CREATE DATABASE inside a transaction or against the
    target DB itself, so we connect to ``postgres`` and check pg_database.
    """
    import psycopg

    if not _is_safe_identifier(database):
        raise ValueError(f"unsafe database name: {database!r}")

    with psycopg.connect(get_uri("postgres"), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database,),
            )
            if cur.fetchone() is None:
                # Identifier interpolation is unavoidable here (PG doesn't
                # allow bound parameters in DDL). Validated above.
                cur.execute(f'CREATE DATABASE "{database}"')


def _is_safe_identifier(name: str) -> bool:
    if not name or len(name) > 63:
        return False
    return all(c.isalnum() or c == "_" for c in name)


def _atexit_stop() -> None:
    global _server
    srv = _server
    _server = None
    if srv is None:
        return
    try:
        srv.cleanup()
    except Exception:
        # Best-effort shutdown — don't crash atexit.
        pass


def _reset_server_for_tests() -> None:
    """Stop and forget the embedded server so tests can swap ELEVATE_HOME."""
    _atexit_stop()


__all__ = [
    "get_server",
    "get_uri",
    "ensure_database",
    "pg_data_dir",
    "_reset_server_for_tests",
]
