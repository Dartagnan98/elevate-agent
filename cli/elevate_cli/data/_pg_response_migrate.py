"""One-shot data migration: SQLite ``response_store.db`` → embedded Postgres.

Companion to ``_pg_memory_migrate.py``. Runs on first boot after the
``0009_response_store.sql`` migration ships. Idempotent — checks a
``9007_response_data_import.legacy`` sentinel row in
``_schema_migrations`` to decide whether the copy is already done.

Source: ``$ELEVATE_HOME/response_store.db`` (the gateway api_server.py
ResponseStore sqlite file).

Destination: ``response_store_responses`` + ``response_store_conversations``
in ``elevate_operational`` (PG).

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

_SENTINEL_VERSION = "9007"
_SENTINEL_NAME = "response_data_import.legacy"
_SENTINEL_SHA = "n/a-response-import"

_BATCH = 500


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def response_store_path() -> Path:
    return get_elevate_home() / "response_store.db"


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


def maybe_migrate_response_store(pg_conn) -> dict[str, Any]:
    """Top-level entry point. Idempotent. Returns a summary dict."""
    summary: dict[str, Any] = {"ran": False, "reason": "", "tables": {}}

    if _already_migrated(pg_conn):
        summary["reason"] = "sentinel-present"
        return summary

    src_path = response_store_path()
    if not src_path.exists():
        _mark_migrated(pg_conn)
        summary["reason"] = "no-legacy-response-sqlite"
        return summary

    _LOG.info("pg-response-migrate: starting from %s", src_path)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    raw = pg_conn._raw  # noqa: SLF001
    try:
        # responses
        rows = src.execute(
            "SELECT response_id, data, accessed_at FROM responses"
        ).fetchall()
        copied_r = 0
        with raw.cursor() as cur:
            for i in range(0, len(rows), _BATCH):
                batch = [
                    (r["response_id"], r["data"], float(r["accessed_at"]))
                    for r in rows[i : i + _BATCH]
                ]
                cur.executemany(
                    "INSERT INTO response_store_responses "
                    "(response_id, data, accessed_at) VALUES (%s, %s, %s) "
                    "ON CONFLICT (response_id) DO NOTHING",
                    batch,
                )
                copied_r += len(batch)
        summary["tables"]["response_store_responses"] = {
            "src": len(rows), "inserted": copied_r,
        }

        # conversations
        crows = src.execute(
            "SELECT name, response_id FROM conversations"
        ).fetchall()
        copied_c = 0
        with raw.cursor() as cur:
            for i in range(0, len(crows), _BATCH):
                batch = [
                    (r["name"], r["response_id"]) for r in crows[i : i + _BATCH]
                ]
                cur.executemany(
                    "INSERT INTO response_store_conversations "
                    "(name, response_id) VALUES (%s, %s) "
                    "ON CONFLICT (name) DO NOTHING",
                    batch,
                )
                copied_c += len(batch)
        summary["tables"]["response_store_conversations"] = {
            "src": len(crows), "inserted": copied_c,
        }
        raw.commit()
        _mark_migrated(pg_conn)
    finally:
        src.close()

    summary["ran"] = True
    summary["reason"] = "migrated"
    _LOG.info("pg-response-migrate: done (%d tables)", len(summary["tables"]))
    return summary


__all__ = ["maybe_migrate_response_store", "response_store_path"]
