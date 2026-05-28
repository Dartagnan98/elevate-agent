"""One-shot data migration: SQLite ``kanban.db`` -> embedded Postgres.

Companion to ``_pg_memory_migrate.py`` / ``_pg_response_migrate.py``. Runs
on first boot after the ``0010_kanban_store.sql`` migration ships.
Idempotent via the ``9008_kanban_data_import.legacy`` sentinel row in
``_schema_migrations``.

Source: ``$ELEVATE_HOME/kanban.db`` (the live kanban board file).

Destinations: ``kanban_tasks``, ``kanban_task_links``,
``kanban_task_comments``, ``kanban_task_events``, ``kanban_task_runs``,
``kanban_notify_subs`` in ``elevate_operational`` (PG).

On early installs at cutover, the live ``kanban.db`` was an empty
0-byte file (the gateway recreates it on init when missing). The
migrator still handles populated DBs cleanly — if the file is empty, no
schema, or zero rows in every source table, the sentinel is set and the
function returns with ``"reason": "empty-legacy-kanban-sqlite"`` or
``"no-legacy-kanban-sqlite"``.

Failure mode: copy errors leave the sentinel UN-set so the next boot
retries. The source SQLite file is left untouched (read-only open).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elevate_constants import get_elevate_home


_LOG = logging.getLogger(__name__)

_SENTINEL_VERSION = "9008"
_SENTINEL_NAME = "kanban_data_import.legacy"
_SENTINEL_SHA = "n/a-kanban-import"

_BATCH = 500


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def kanban_store_path() -> Path:
    return get_elevate_home() / "kanban.db"


def _already_migrated(pg_conn) -> bool:
    row = pg_conn.execute(
        "SELECT 1 FROM _schema_migrations WHERE version = %s",
        (_SENTINEL_VERSION,),
    ).fetchone()
    return row is not None


def _mark_migrated(pg_conn) -> None:
    raw = pg_conn._raw  # noqa: SLF001
    with raw.cursor() as cur:
        cur.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
            (_SENTINEL_VERSION, _SENTINEL_NAME, _SENTINEL_SHA, _utcnow()),
        )
    raw.commit()


def _has_table(src: sqlite3.Connection, name: str) -> bool:
    row = src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _copy_tasks(src: sqlite3.Connection, raw, summary: dict[str, Any]) -> None:
    cols = (
        "id, title, body, assignee, status, priority, created_by, created_at, "
        "started_at, completed_at, workspace_kind, workspace_path, branch_name, "
        "claim_lock, claim_expires, tenant, result, idempotency_key, "
        "consecutive_failures, worker_pid, last_failure_error, "
        "max_runtime_seconds, last_heartbeat_at, current_run_id, "
        "workflow_template_id, current_step_key, skills, model_override, "
        "max_retries, session_id"
    )
    rows = src.execute(f"SELECT {cols} FROM tasks").fetchall()
    copied = 0
    placeholders = ",".join(["%s"] * len(cols.split(",")))
    with raw.cursor() as cur:
        for i in range(0, len(rows), _BATCH):
            batch = [tuple(r) for r in rows[i : i + _BATCH]]
            cur.executemany(
                f"INSERT INTO kanban_tasks ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT (id) DO NOTHING",
                batch,
            )
            copied += len(batch)
    summary["tables"]["kanban_tasks"] = {"src": len(rows), "inserted": copied}


def _copy_simple(
    src: sqlite3.Connection,
    raw,
    *,
    src_table: str,
    dst_table: str,
    columns: str,
    conflict_clause: str,
    summary: dict[str, Any],
) -> None:
    rows = src.execute(f"SELECT {columns} FROM {src_table}").fetchall()
    copied = 0
    placeholders = ",".join(["%s"] * len(columns.split(",")))
    with raw.cursor() as cur:
        for i in range(0, len(rows), _BATCH):
            batch = [tuple(r) for r in rows[i : i + _BATCH]]
            cur.executemany(
                f"INSERT INTO {dst_table} ({columns}) VALUES ({placeholders}) "
                f"{conflict_clause}",
                batch,
            )
            copied += len(batch)
    summary["tables"][dst_table] = {"src": len(rows), "inserted": copied}


def maybe_migrate_kanban_store(pg_conn) -> dict[str, Any]:
    """Top-level entry point. Idempotent. Returns a summary dict."""
    summary: dict[str, Any] = {"ran": False, "reason": "", "tables": {}}

    if _already_migrated(pg_conn):
        summary["reason"] = "sentinel-present"
        return summary

    src_path = kanban_store_path()
    if not src_path.exists():
        _mark_migrated(pg_conn)
        summary["reason"] = "no-legacy-kanban-sqlite"
        return summary

    if src_path.stat().st_size == 0:
        # The gateway touches an empty kanban.db on init when the file is
        # missing — treat that as nothing-to-migrate without trying to open
        # it (sqlite3 will accept the 0-byte file but every query will
        # raise on the missing schema).
        _mark_migrated(pg_conn)
        summary["reason"] = "empty-legacy-kanban-sqlite"
        return summary

    _LOG.info("pg-kanban-migrate: starting from %s", src_path)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    raw = pg_conn._raw  # noqa: SLF001
    try:
        if _has_table(src, "tasks"):
            _copy_tasks(src, raw, summary)

        if _has_table(src, "task_links"):
            _copy_simple(
                src, raw,
                src_table="task_links",
                dst_table="kanban_task_links",
                columns="parent_id, child_id",
                conflict_clause="ON CONFLICT (parent_id, child_id) DO NOTHING",
                summary=summary,
            )

        if _has_table(src, "task_comments"):
            # The sqlite ``id`` is an autoincrement integer; let PG mint a
            # fresh one. Comments aren't FK targets so renumbering is safe.
            _copy_simple(
                src, raw,
                src_table="task_comments",
                dst_table="kanban_task_comments",
                columns="task_id, author, body, created_at",
                conflict_clause="",
                summary=summary,
            )

        if _has_table(src, "task_events"):
            # task_events.run_id references task_runs.id, both of which are
            # autoincrement ints in sqlite. The run_id mapping breaks under
            # PG renumbering. We keep run_id values raw — historical analytic
            # join, not a hot path. If this ever matters we'll add a runs
            # id remap pass.
            _copy_simple(
                src, raw,
                src_table="task_events",
                dst_table="kanban_task_events",
                columns="task_id, run_id, kind, payload, created_at",
                conflict_clause="",
                summary=summary,
            )

        if _has_table(src, "task_runs"):
            _copy_simple(
                src, raw,
                src_table="task_runs",
                dst_table="kanban_task_runs",
                columns=(
                    "task_id, profile, step_key, status, claim_lock, "
                    "claim_expires, worker_pid, max_runtime_seconds, "
                    "last_heartbeat_at, started_at, ended_at, outcome, "
                    "summary, metadata, error"
                ),
                conflict_clause="",
                summary=summary,
            )

        if _has_table(src, "kanban_notify_subs"):
            _copy_simple(
                src, raw,
                src_table="kanban_notify_subs",
                dst_table="kanban_notify_subs",
                columns=(
                    "task_id, platform, chat_id, thread_id, user_id, "
                    "notifier_profile, created_at, last_event_id"
                ),
                conflict_clause=(
                    "ON CONFLICT (task_id, platform, chat_id, thread_id) "
                    "DO NOTHING"
                ),
                summary=summary,
            )

        raw.commit()
        _mark_migrated(pg_conn)
    finally:
        src.close()

    summary["ran"] = True
    summary["reason"] = "migrated"
    _LOG.info("pg-kanban-migrate: done (%d tables)", len(summary["tables"]))
    return summary


__all__ = ["maybe_migrate_kanban_store", "kanban_store_path"]
