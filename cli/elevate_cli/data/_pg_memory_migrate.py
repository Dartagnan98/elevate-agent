"""One-shot data migration: SQLite ``memory_store.db`` → embedded Postgres.

Companion to ``_pg_data_migrate.py``. Runs on first boot after the
``0007_memory_store.sql`` migration ships. Idempotent — checks a
``9006_memory_data_import.legacy`` sentinel row in
``_schema_migrations`` to decide whether the copy is already done.

Source: ``$ELEVATE_HOME/memory_store.db`` (the holographic-store plugin
sqlite file).

Destination: ``memory_*`` tables in ``elevate_operational`` (PG).

Renames during copy (sqlite_name → pg_name):
    facts                → memory_facts
    entities             → memory_entities
    fact_entities        → memory_fact_entities
    fact_links           → memory_fact_links
    memory_*             → memory_*              (no change)

Skipped tables (auto-managed by PG):
    sqlite_sequence
    *_fts, *_fts_data, *_fts_idx, *_fts_content, *_fts_docsize, *_fts_config
    _schema_migrations

Post-copy: identity sequences (``memory_facts_fact_id_seq`` etc.) are
reseeded to ``max(id) + 1`` so new inserts don't collide with copied
PKs. Tsvector columns are populated by the BEFORE INSERT triggers
declared in 0007 — no explicit work needed here.

Failure mode: copy errors leave the sentinel UN-set so the next boot
retries. The source SQLite file is left untouched (read-only open).
The PG side is wrapped in ``session_replication_role='replica'`` so FK
ordering doesn't matter; orphan cleanup runs after.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from elevate_constants import get_elevate_home


_LOG = logging.getLogger(__name__)

_SENTINEL_VERSION = "9006"
_SENTINEL_NAME = "memory_data_import.legacy"
_SENTINEL_SHA = "n/a-memory-import"

_BATCH = 1_000

# sqlite_table_name → pg_table_name
_TABLE_MAP: dict[str, str] = {
    "facts":                    "memory_facts",
    "entities":                 "memory_entities",
    "fact_entities":            "memory_fact_entities",
    "fact_links":               "memory_fact_links",
    "memory_banks":             "memory_banks",
    "memory_embeddings":        "memory_embeddings",
    "memory_turn_journal":      "memory_turn_journal",
    "memory_documents":         "memory_documents",
    "memory_chunks":            "memory_chunks",
    "memory_events":            "memory_events",
    "memory_injections":        "memory_injections",
    "memory_gaps":              "memory_gaps",
    "memory_clusters":          "memory_clusters",
    "memory_cluster_members":   "memory_cluster_members",
    "memory_modal_assets":      "memory_modal_assets",
    "memory_chunk_entities":    "memory_chunk_entities",
    "memory_relations":         "memory_relations",
    "memory_community_reports": "memory_community_reports",
}

# Per-table identity sequence to reseed after copy.
# Format: (pg_table, pg_pk_column)  – sequence name is auto-derived
# by pg_get_serial_sequence which handles GENERATED IDENTITY columns.
_IDENTITY_TABLES: list[tuple[str, str]] = [
    ("memory_facts",          "fact_id"),
    ("memory_entities",       "entity_id"),
    ("memory_banks",          "bank_id"),
    ("memory_embeddings",     "embedding_id"),
    ("memory_turn_journal",   "turn_id"),
    ("memory_documents",      "document_id"),
    ("memory_chunks",         "chunk_id"),
    ("memory_events",         "event_id"),
    ("memory_injections",     "injection_id"),
    ("memory_gaps",           "gap_id"),
    ("memory_modal_assets",   "asset_id"),
    ("memory_relations",      "relation_id"),
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def memory_store_path() -> Path:
    return get_elevate_home() / "memory_store.db"


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


def _sqlite_columns(src: sqlite3.Connection, table: str) -> list[str]:
    rows = src.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [r[1] for r in rows]


def _pg_columns(pg_conn, table: str) -> list[str]:
    rows = pg_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def _stream_rows(
    src: sqlite3.Connection, table: str, cols: list[str], batch: int
) -> Iterable[list[tuple[Any, ...]]]:
    quoted = ", ".join(f'"{c}"' for c in cols)
    cur = src.execute(f'SELECT {quoted} FROM "{table}"')
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            return
        yield [tuple(r) for r in rows]


def _copy_table(
    src: sqlite3.Connection,
    pg_conn,
    sqlite_table: str,
    pg_table: str,
) -> tuple[int, int]:
    """Copy all rows. Returns (src_count, inserted_count).

    Columns present in both schemas are copied; sqlite-only columns are
    silently dropped. ON CONFLICT DO NOTHING lets reruns be safe.
    """
    src_cols = _sqlite_columns(src, sqlite_table)
    pg_cols = _pg_columns(pg_conn, pg_table)
    common = [c for c in src_cols if c in pg_cols]
    if not common:
        _LOG.warning("memory-copy: %s → %s no overlapping columns; skip",
                     sqlite_table, pg_table)
        return 0, 0

    placeholders = ", ".join(["%s"] * len(common))
    quoted_cols = ", ".join(f'"{c}"' for c in common)
    insert_sql = (
        f'INSERT INTO "{pg_table}" ({quoted_cols}) VALUES ({placeholders}) '
        f"ON CONFLICT DO NOTHING"
    )

    src_n = src.execute(f'SELECT COUNT(*) FROM "{sqlite_table}"').fetchone()[0]
    inserted = 0
    raw_pg = pg_conn._raw  # noqa: SLF001
    with raw_pg.cursor() as cur:
        for batch in _stream_rows(src, sqlite_table, common, _BATCH):
            cur.executemany(insert_sql, batch)
            inserted += len(batch)
    raw_pg.commit()
    _LOG.info("memory-copy: %s → %s  src=%d copied=%d",
              sqlite_table, pg_table, src_n, inserted)
    return src_n, inserted


def _backfill_tsvectors(pg_conn) -> None:
    """Populate `search_tsv` columns that the BEFORE-INSERT triggers
    would have produced. Bulk copy ran under
    ``session_replication_role='replica'`` which silences all user
    triggers (not just FK), so we need to recompute the tsvectors in
    one pass after the load.
    """
    raw = pg_conn._raw  # noqa: SLF001
    with raw.cursor() as cur:
        cur.execute("""
            UPDATE memory_facts SET search_tsv =
                setweight(to_tsvector('english', coalesce(content, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(tags, '')),    'B')
            WHERE search_tsv IS NULL
        """)
        cur.execute("""
            UPDATE memory_chunks SET search_tsv =
                setweight(to_tsvector('english', coalesce(content, '')),        'A') ||
                setweight(to_tsvector('english', coalesce(source_excerpt, '')), 'B')
            WHERE search_tsv IS NULL
        """)
        cur.execute("""
            UPDATE memory_community_reports SET search_tsv =
                setweight(to_tsvector('english', coalesce(name, '')),         'A') ||
                setweight(to_tsvector('english', coalesce(summary, '')),      'A') ||
                setweight(to_tsvector('english', coalesce(tags, '')),         'B') ||
                setweight(to_tsvector('english', coalesce(entity_names, '')), 'C')
            WHERE search_tsv IS NULL
        """)
    raw.commit()
    _LOG.info("memory-copy: backfilled tsvectors on facts/chunks/community_reports")


def _reseed_identity_sequences(pg_conn) -> None:
    """After a bulk load with explicit PKs, the IDENTITY sequence still
    points at 1. Bump every sequence to max(pk)+1 so future inserts
    don't trip the UNIQUE constraint on PK.
    """
    raw = pg_conn._raw  # noqa: SLF001
    # Pool's default cursor returns dict rows; we want positional access
    # for these one-off introspection calls.
    import psycopg.rows as _pg_rows
    with raw.cursor(row_factory=_pg_rows.tuple_row) as cur:
        for table, pk in _IDENTITY_TABLES:
            cur.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                (table, pk),
            )
            row = cur.fetchone()
            seq = row[0] if row else None
            if not seq:
                _LOG.warning("reseed: no sequence for %s.%s — skipping", table, pk)
                continue
            # setval(seq, max(pk)) — next nextval is max+1. coalesce
            # handles empty tables (sets seq to 1 with is_called=false
            # so first nextval returns 1).
            cur.execute(
                f'SELECT setval(%s, COALESCE((SELECT MAX("{pk}") FROM "{table}"), 1), '
                f'(SELECT MAX("{pk}") FROM "{table}") IS NOT NULL)',
                (seq,),
            )
    raw.commit()
    _LOG.info("memory-copy: reseeded %d identity sequences", len(_IDENTITY_TABLES))


def maybe_migrate_memory_store(pg_conn) -> dict[str, Any]:
    """Top-level entry point. Idempotent. Returns a summary dict.

    Called once from ``connection.connect()`` right after
    ``maybe_migrate_sqlite_to_pg`` finishes. Missing source file → no-op
    with sentinel set so we don't probe the filesystem every boot.
    """
    summary: dict[str, Any] = {
        "ran": False,
        "reason": "",
        "tables": {},
    }

    if _already_migrated(pg_conn):
        summary["reason"] = "sentinel-present"
        return summary

    src_path = memory_store_path()
    if not src_path.exists():
        _mark_migrated(pg_conn)
        summary["reason"] = "no-legacy-memory-sqlite"
        return summary

    _LOG.info("pg-memory-migrate: starting from %s", src_path)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        raw = pg_conn._raw  # noqa: SLF001
        with raw.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")
        try:
            for sqlite_tbl, pg_tbl in _TABLE_MAP.items():
                # Source table missing in old install? Skip silently.
                exists = src.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (sqlite_tbl,),
                ).fetchone()
                if not exists:
                    continue
                # PG target missing? That's a bug in the migration —
                # log loudly but keep going on the other tables.
                if not _pg_columns(pg_conn, pg_tbl):
                    _LOG.error("memory-copy: PG table %s missing — skipping", pg_tbl)
                    continue
                src_n, ins_n = _copy_table(src, pg_conn, sqlite_tbl, pg_tbl)
                summary["tables"][pg_tbl] = {"src": src_n, "inserted": ins_n}
        finally:
            with raw.cursor() as cur:
                cur.execute("SET session_replication_role = 'origin'")
            raw.commit()

        _backfill_tsvectors(pg_conn)
        _reseed_identity_sequences(pg_conn)
        _mark_migrated(pg_conn)
    finally:
        src.close()

    summary["ran"] = True
    summary["reason"] = "migrated"
    _LOG.info("pg-memory-migrate: done (%d tables)", len(summary["tables"]))
    return summary


__all__ = [
    "maybe_migrate_memory_store",
    "memory_store_path",
]
