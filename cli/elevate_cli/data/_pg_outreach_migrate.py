"""One-shot data migration: SQLite outreach.db -> embedded Postgres.

Sentinel: ``9009_outreach_data_import.legacy`` in ``_schema_migrations``.

Source: ``$ELEVATE_HOME/tools/data/outreach/outreach.db`` (the live
elevate_cli.outreach_db store).

Destinations: ``outreach_templates``, ``outreach_draft_attempts``,
``outreach_send_queue``, ``outreach_thread_meta``, ``outreach_lane_config``,
``outreach_inbound_seen``, ``outreach_meta`` in ``elevate_operational`` (PG).

Coordination with 0011_outreach_store.sql:

* The migration SQL stashes the stale (lane, name) -> stale_id mapping
  from the old rich ``public.templates`` into
  ``_outreach_template_remap_stash`` before dropping the old tables.
* This migrator imports the live sqlite data, then uses that stash plus
  the new live ``outreach_templates(lane, name) -> id`` mapping to
  rewrite ``events.template_id`` so the 15 historical rows pointing at
  stale UUIDs land back on the right (lane, name).
* Stale ids that have no matching live template (e.g. the
  ``('new-outreach', 'reply')`` template was PG-only seed never present
  in sqlite) get NULL'd — there's no FK constraint left to satisfy.

Failure mode: copy errors leave the sentinel UN-set so the next boot
retries.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elevate_constants import get_elevate_home


_LOG = logging.getLogger(__name__)

_SENTINEL_VERSION = "9009"
_SENTINEL_NAME = "outreach_data_import.legacy"
_SENTINEL_SHA = "n/a-outreach-import"

_BATCH = 500


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def outreach_store_path() -> Path:
    return get_elevate_home() / "tools" / "data" / "outreach" / "outreach.db"


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


def _copy(
    src: sqlite3.Connection,
    raw,
    *,
    src_table: str,
    dst_table: str,
    columns: str,
    conflict_clause: str,
    summary: dict[str, Any],
) -> None:
    if not _has_table(src, src_table):
        return
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


def _remap_events_template_id(raw, summary: dict[str, Any]) -> None:
    """Repoint events.template_id from the stale 0001-era UUIDs to the live
    sqlite ones we just imported.

    Reads:
      _outreach_template_remap_stash (lane, name, stale_id)  -- from 0011
      outreach_templates             (lane, name, id)         -- just imported

    Writes:
      events.template_id = new_id  WHERE old_id had a (lane, name) match
      events.template_id = NULL    WHERE old_id had no match in the live data
    """
    with raw.cursor() as cur:
        cur.execute(
            """
            UPDATE events e
            SET    template_id = ot.id
            FROM   _outreach_template_remap_stash s
            JOIN   outreach_templates ot
                   ON ot.lane = s.lane AND ot.name = s.name
            WHERE  e.template_id = s.stale_id
            """
        )
        remapped = cur.rowcount

        cur.execute(
            """
            UPDATE events
            SET    template_id = NULL
            WHERE  template_id IS NOT NULL
              AND  template_id NOT IN (SELECT id FROM outreach_templates)
            """
        )
        orphaned = cur.rowcount

    summary["events_template_id_remap"] = {
        "remapped": remapped,
        "orphaned_nulled": orphaned,
    }


def _drop_remap_stash(raw) -> None:
    with raw.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _outreach_template_remap_stash")


def maybe_migrate_outreach_store(pg_conn) -> dict[str, Any]:
    """Top-level entry point. Idempotent. Returns a summary dict."""
    summary: dict[str, Any] = {"ran": False, "reason": "", "tables": {}}

    if _already_migrated(pg_conn):
        summary["reason"] = "sentinel-present"
        return summary

    src_path = outreach_store_path()
    raw = pg_conn._raw  # noqa: SLF001

    if not src_path.exists() or src_path.stat().st_size == 0:
        # No live data, but the remap stash may still point at stale
        # public.templates ids. Null those out so events.template_id
        # doesn't carry dead references, then mark the sentinel.
        try:
            _remap_events_template_id(raw, summary)
            raw.commit()
        except Exception:  # pragma: no cover -- defensive
            raw.rollback()
            raise
        _drop_remap_stash(raw)
        raw.commit()
        _mark_migrated(pg_conn)
        summary["reason"] = "no-legacy-outreach-sqlite"
        return summary

    _LOG.info("pg-outreach-migrate: starting from %s", src_path)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        _copy(
            src, raw,
            src_table="templates",
            dst_table="outreach_templates",
            columns=(
                "id, lane, name, body, channel, active, uses, replies, wins, "
                "status, rationale, created_at, updated_at"
            ),
            conflict_clause="ON CONFLICT (id) DO NOTHING",
            summary=summary,
        )

        _copy(
            src, raw,
            src_table="draft_attempts",
            dst_table="outreach_draft_attempts",
            columns=(
                "id, template_id, lane, source_id, thread_id, task_id, "
                "status, created_at, outcome_recorded_at, outcome"
            ),
            conflict_clause="ON CONFLICT (id) DO NOTHING",
            summary=summary,
        )

        _copy(
            src, raw,
            src_table="send_queue",
            dst_table="outreach_send_queue",
            columns=(
                "id, idempotency_key, source_id, thread_id, task_id, channel, "
                "payload_json, status, attempts, next_retry_at, last_error, "
                "provider_message_id, attempt_id, created_at, updated_at"
            ),
            conflict_clause="ON CONFLICT (id) DO NOTHING",
            summary=summary,
        )

        _copy(
            src, raw,
            src_table="thread_meta",
            dst_table="outreach_thread_meta",
            columns=(
                "source_id, thread_id, score, label, reason, scored_by, "
                "scored_at, updated_at"
            ),
            conflict_clause="ON CONFLICT (source_id, thread_id) DO NOTHING",
            summary=summary,
        )

        _copy(
            src, raw,
            src_table="lane_config",
            dst_table="outreach_lane_config",
            columns="lane, enabled_channels_json, updated_at",
            conflict_clause="ON CONFLICT (lane) DO NOTHING",
            summary=summary,
        )

        _copy(
            src, raw,
            src_table="inbound_seen",
            dst_table="outreach_inbound_seen",
            columns="toolkit, provider_message_id, seen_at",
            conflict_clause="ON CONFLICT (toolkit, provider_message_id) DO NOTHING",
            summary=summary,
        )

        _copy(
            src, raw,
            src_table="meta",
            dst_table="outreach_meta",
            columns="key, value",
            conflict_clause="ON CONFLICT (key) DO NOTHING",
            summary=summary,
        )

        _remap_events_template_id(raw, summary)
        raw.commit()
        _drop_remap_stash(raw)
        raw.commit()
        _mark_migrated(pg_conn)
    finally:
        src.close()

    summary["ran"] = True
    summary["reason"] = "migrated"
    _LOG.info("pg-outreach-migrate: done (%d tables)", len(summary["tables"]))
    return summary


__all__ = ["maybe_migrate_outreach_store", "outreach_store_path"]
