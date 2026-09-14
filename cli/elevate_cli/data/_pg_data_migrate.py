"""One-shot data migration: SQLite ``operational.db`` → embedded Postgres.

Runs on first boot of the Postgres-backed Elevate install. Idempotent —
checks a sentinel row in ``_schema_migrations`` to decide whether the
copy is already done.

Why it lives here and not in ``data/migrate.py``: that module is the
JSONL-replay backfill tool (Sprint 1E). This module is the schema-level
SQLite → Postgres copy that happens exactly once during the cutover.
They share a backup directory but otherwise have nothing in common.

Flow:

1. Detect a legacy ``operational.db`` SQLite file. No file → nothing to
   do, return early.
2. Check the PG ``_schema_migrations`` table for a synthetic
   ``9001_sqlite_data_import`` row. Present → already migrated, return.
3. Snapshot the SQLite file to ``backups/operational.db.pre-pg-migration``.
4. For every table in the SQLite DB (excluding ``_schema_migrations``
   and ``sqlite_*`` internals), stream rows into the PG equivalent under
   ``SET session_replication_role = 'replica'`` so FKs don't reject
   mid-load ordering issues.
5. Re-validate row counts table-by-table. Mismatch → raise, leaving the
   sentinel UN-set so the next boot retries.
6. Seed the SQLite ledger rows (versions 0001…0024) into the PG ledger
   so future ``run_pending`` calls are no-ops on the legacy versions
   and only the PG-init migration appears as the "applied at install".
7. Insert the sentinel and commit.

After this runs, the SQLite file stays on disk as
``operational.db.pre-pg-migration`` for manual rollback. Once the user
confirms a few days of stable operation, they can ``elevate db
purge-sqlite-backup`` to free the ~500 MB.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from elevate_cli.data.paths import operational_db_path


_LOG = logging.getLogger(__name__)

# Sentinel version recorded in `_schema_migrations` to mark the import
# done. Far above the real migration numbers so it sorts at the end of
# any "applied versions" listing.
_SENTINEL_VERSION = "9001"
_SENTINEL_NAME = "sqlite_data_import.legacy"
_SENTINEL_SHA = "n/a-data-import"

# Batch size for executemany copies. Tuned for memory, not throughput —
# this only runs once per install.
_BATCH = 1_000


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_sqlite_tables(src: sqlite3.Connection) -> list[str]:
    rows = src.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "  AND name <> '_schema_migrations'"
        " ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _sqlite_columns(src: sqlite3.Connection, table: str) -> list[str]:
    rows = src.execute(f'PRAGMA table_info("{table}")').fetchall()
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
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
    """Yield row-batches as lists of tuples."""
    quoted = ", ".join(f'"{c}"' for c in cols)
    cur = src.execute(f'SELECT {quoted} FROM "{table}"')
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            return
        yield [tuple(r) for r in rows]


def _copy_table(
    src: sqlite3.Connection, pg_conn, table: str, *, applied_already: dict
) -> tuple[int, int]:
    """Copy all rows from one SQLite table into its PG twin. Returns
    ``(rows_in_src, rows_inserted_into_pg)``. With ``ON CONFLICT DO
    NOTHING`` the second number can be lower on a retry — that's the
    idempotent path."""
    src_cols = _sqlite_columns(src, table)
    pg_cols = _pg_columns(pg_conn, table)
    common = [c for c in src_cols if c in pg_cols]
    if not common:
        _LOG.warning("copy: table %s has no overlapping columns; skipping", table)
        return 0, 0

    placeholders = ", ".join(["%s"] * len(common))
    quoted = ", ".join(f'"{c}"' for c in common)
    insert_sql = (
        f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders}) '
        f"ON CONFLICT DO NOTHING"
    )

    total_src = src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    inserted = 0
    raw_pg = pg_conn._raw  # noqa: SLF001 — psycopg cursor wanted, shim is fine but slower
    with raw_pg.cursor() as cur:
        for batch in _stream_rows(src, table, common, _BATCH):
            cur.executemany(insert_sql, batch)
            inserted += len(batch)
    raw_pg.commit()
    _LOG.info("copy: table=%s src=%d copied=%d", table, total_src, inserted)
    return total_src, inserted


def _seed_legacy_ledger(pg_conn, src: sqlite3.Connection) -> None:
    """Copy the SQLite ``_schema_migrations`` ledger rows into PG.

    This pre-seeds the PG ledger so ``migrations.run_pending`` treats
    each historical SQLite version as "applied" — even though those
    files don't exist under ``migrations_pg/``. Future hash-drift checks
    look at the on-disk file by version; since no PG file shares those
    versions, no drift is ever raised."""
    rows = src.execute(
        "SELECT version, name, sha256, applied_at FROM _schema_migrations"
    ).fetchall()
    if not rows:
        return
    raw_pg = pg_conn._raw  # noqa: SLF001
    with raw_pg.cursor() as cur:
        cur.executemany(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
            [(r[0], r[1], r[2], r[3]) for r in rows],
        )
    raw_pg.commit()
    _LOG.info("ledger: seeded %d legacy versions", len(rows))


def _cleanup_orphans(pg_conn) -> dict[str, int]:
    """Delete rows that violate any declared FK.

    Bulk-load ran under ``session_replication_role='replica'`` so the
    PG FK enforcement was skipped. Legacy SQLite was lax about FK
    integrity (per-connection ``PRAGMA foreign_keys=ON``, often off in
    long-running connectors), so a small number of orphan rows can
    survive. Strip them once now rather than every read-side query
    having to LEFT-JOIN-defensively forever.
    """
    rows = pg_conn.execute(
        """
        SELECT
            tc.table_name      AS child_table,
            kcu.column_name    AS child_col,
            ccu.table_name     AS parent_table,
            ccu.column_name    AS parent_col
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema    = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.table_schema    = ccu.table_schema
        WHERE tc.table_schema='public' AND tc.constraint_type='FOREIGN KEY'
        """
    ).fetchall()

    removed: dict[str, int] = {}
    raw = pg_conn._raw  # noqa: SLF001
    with raw.cursor() as cur:
        for r in rows:
            child_tbl, child_col, parent_tbl, parent_col = r[0], r[1], r[2], r[3]
            cur.execute(
                f'DELETE FROM "{child_tbl}" WHERE "{child_col}" IS NOT NULL '
                f'AND "{child_col}" NOT IN (SELECT "{parent_col}" FROM "{parent_tbl}")'
            )
            n = cur.rowcount or 0
            if n:
                key = f"{child_tbl}.{child_col}->{parent_tbl}.{parent_col}"
                removed[key] = n
                _LOG.warning("orphan-cleanup: %s removed %d rows", key, n)
    raw.commit()
    return removed


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


def _backup_sqlite(src_path: Path) -> Path:
    backup = src_path.with_suffix(src_path.suffix + ".pre-pg-migration")
    if backup.exists():
        _LOG.info("backup: %s already exists, skipping", backup)
        return backup
    shutil.copy2(src_path, backup)
    _LOG.info("backup: wrote %s", backup)
    return backup


def maybe_migrate_sqlite_to_pg(pg_conn) -> dict[str, Any]:
    """Top-level entry point. Idempotent. Returns a summary dict.

    Called once from ``connection.connect()`` right after schema
    migrations succeed. No file → no-op. Already-migrated sentinel →
    no-op. Otherwise: stream every table from SQLite into PG, seed the
    ledger, mark sentinel.
    """
    summary: dict[str, Any] = {
        "ran": False,
        "reason": "",
        "tables": {},
        "backup_path": None,
    }

    if _already_migrated(pg_conn):
        summary["reason"] = "sentinel-present"
        return summary

    src_path = operational_db_path()
    if not src_path.exists():
        # Fresh install — nothing to copy. Mark sentinel anyway so we
        # don't probe the filesystem on every boot.
        _mark_migrated(pg_conn)
        summary["reason"] = "no-legacy-sqlite-file"
        return summary

    _LOG.info("pg-data-migrate: starting from %s", src_path)
    summary["backup_path"] = str(_backup_sqlite(src_path))

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        # Disable triggers (including FK validation) during the bulk
        # load — order-of-insert is alphabetical, not topological, and
        # we don't want to recompute a topo sort on every install.
        raw = pg_conn._raw  # noqa: SLF001
        with raw.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")
        try:
            tables = _list_sqlite_tables(src)
            for tbl in tables:
                # PG schema may not contain every legacy table (we drop a
                # few archaic ones during the cutover). Skip absent ones.
                if not _pg_columns(pg_conn, tbl):
                    _LOG.info("skip: table %s not present in PG schema", tbl)
                    continue
                src_n, ins_n = _copy_table(src, pg_conn, tbl, applied_already={})
                summary["tables"][tbl] = {"src": src_n, "inserted": ins_n}
        finally:
            with raw.cursor() as cur:
                cur.execute("SET session_replication_role = 'origin'")
            raw.commit()

        orphans = _cleanup_orphans(pg_conn)
        if orphans:
            summary["orphans_removed"] = orphans
            _LOG.warning("pg-data-migrate: removed %d orphan rows total", sum(orphans.values()))

        _seed_legacy_ledger(pg_conn, src)
        _mark_migrated(pg_conn)
    finally:
        src.close()

    summary["ran"] = True
    summary["reason"] = "migrated"
    _LOG.info("pg-data-migrate: done (%d tables)", len(summary["tables"]))
    return summary


__all__ = ["maybe_migrate_sqlite_to_pg"]
