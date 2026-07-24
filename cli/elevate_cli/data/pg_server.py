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
# Cached connection URI for the running server. Stable across postmaster
# restarts (same pgdata ⇒ same socket dir + stored password), so ``get_uri()``
# can resolve it as a pure read without forcing a liveness probe/restart.
_base_uri: Optional[str] = None
# Postgres log-collector config is applied once per process (persisted to
# postgresql.auto.conf), best-effort.
_logging_configured: bool = False


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


def _postmaster_alive(srv: object) -> bool:
    """Cheap liveness check on a cached pgserver handle — is its postmaster
    process still running? No SQL round-trip; any error is treated as dead so
    the caller re-boots defensively."""
    try:
        info = srv.get_postmaster_info()
    except Exception:
        return False
    proc = getattr(info, "process", None)
    if proc is None:
        return False
    try:
        return bool(proc.is_running())
    except Exception:
        return False


def _boot_locked() -> object:
    """(Re)start the embedded postmaster against the existing pgdata and cache
    its handle + connection URI. Caller must hold ``_server_lock``.

    pgserver only runs ``initdb`` when the data dir is uninitialized; an
    existing install is brought back up with ``pg_ctl start`` (via the handle's
    ``ensure_postgres_running``), so a dead postmaster is restarted without ever
    losing data.
    """
    global _server, _base_uri
    data_dir = pg_data_dir()
    srv = _server
    if srv is None:
        # First boot this process: constructs the handle, runs initdb only if
        # needed, and starts the postmaster. cleanup_mode="stop" → pgserver runs
        # `pg_ctl stop` in its atexit handler, so no orphan postmaster remains.
        srv = pgserver.get_server(str(data_dir), cleanup_mode=_cleanup_mode())
        _server = srv
        atexit.register(_atexit_stop)
    else:
        # A cached handle whose postmaster died: pgserver.get_server would just
        # return the same dead cached instance, so restart it in place (reads
        # postmaster.pid, `pg_ctl start` if not running).
        srv.ensure_postgres_running()
    _base_uri = srv.get_uri()
    _configure_logging(srv)
    return srv


def get_server() -> object:
    """Boot embedded Postgres (idempotent) and return the pgserver handle.

    Self-healing (A2): the handle is cached for the process lifetime, but the
    postmaster it points at can die (crash, OOM, external kill). Rather than
    hand back a dead handle for the rest of the process, probe liveness and
    re-start against the existing pgdata when needed — never re-initdb'ing.
    """
    srv = _server
    if srv is not None and _postmaster_alive(srv):
        return srv
    with _server_lock:
        if _server is not None and _postmaster_alive(_server):
            return _server
        return _boot_locked()


def restart_server() -> object:
    """Force the embedded postmaster back up, restarting a dead one against the
    existing pgdata (A2/A3). Invoked by the connection pool's ``reconnect_failed``
    hook when it can no longer reach the server. Never re-initdb's."""
    with _server_lock:
        return _boot_locked()


def get_uri(database: str = "postgres") -> str:
    """psycopg-compatible connection URI for the running embedded server.

    Uses a Unix domain socket under the data dir — no TCP port involved.

    Returns the cached base URI (stable across restarts: the same pgdata means
    the same socket dir + stored password), booting the server once if it has
    never started this process. Resolving the URI is intentionally a pure read
    that does NOT trigger a liveness probe/restart, so an observational caller
    (``connection.database_reachable``) can distinguish a dead postmaster
    instead of silently healing it.
    """
    uri = _base_uri
    if uri is None:
        # Never booted this process — bring the server up once to learn the URI.
        fresh = get_server().get_uri()
        uri = _base_uri or fresh
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


def _configure_logging(srv: object) -> None:
    """Turn on Postgres' own log collector with rotation + truncation (C).

    pgserver boots with ``logging_collector`` off and redirects the postmaster
    stderr to a single ``pgdata/log`` file that is never rotated — on a chatty
    install (duplicate-key STATEMENT spew) that file grew unbounded. Enable the
    collector into a dedicated rotating directory and stop dumping multi-KB
    statement bodies on every ERROR.

    Applied once per process, best-effort — a failure here must never block DB
    startup. ``logging_collector`` and ``log_directory`` are postmaster-context
    GUCs that take effect on the next restart; ``log_rotation_*`` and
    ``log_min_error_statement`` (the knob that stops the statement-body spew)
    apply immediately via ``pg_reload_conf``. The dedicated ``pg_log``
    directory avoids colliding with the ``pgdata/log`` *file* pgserver hands to
    ``pg_ctl -l``.
    """
    global _logging_configured
    if _logging_configured:
        return
    import psycopg
    from psycopg import sql

    settings = {
        "logging_collector": "on",
        # Relative to the data dir; Postgres creates it. Distinct from the
        # ``pgdata/log`` file used by pg_ctl's -l redirect.
        "log_directory": "pg_log",
        "log_rotation_age": "1d",
        "log_rotation_size": "10MB",
        "log_truncate_on_rotation": "on",
        "log_min_error_statement": "panic",
    }
    try:
        with psycopg.connect(srv.get_uri(), autocommit=True) as conn:
            with conn.cursor() as cur:
                for name, value in settings.items():
                    cur.execute(
                        sql.SQL("ALTER SYSTEM SET {name} = {val}").format(
                            name=sql.Identifier(name),
                            val=sql.Literal(value),
                        )
                    )
                cur.execute("SELECT pg_reload_conf()")
        _logging_configured = True
    except Exception:
        # Best-effort: never let log tuning stop the database from coming up.
        pass


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
    global _server, _base_uri, _logging_configured
    srv = _server
    _server = None
    _base_uri = None
    _logging_configured = False
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
    "restart_server",
    "get_uri",
    "ensure_database",
    "pg_data_dir",
    "_reset_server_for_tests",
]
