"""SQL migration runner for the embedded-Postgres operational store.

Discovers numbered ``.sql`` files in ``elevate_cli/data/migrations_pg/``
and applies them in lexical order against the central operational
store. Each applied file is recorded in the ``_schema_migrations``
table with the file's SHA-256 — re-running is a no-op.

History note: pre-Postgres builds shipped 24 numbered migrations under
``migrations/`` for SQLite. Those are kept on disk for archaeology but
no longer applied. The Postgres cutover replaces them with a single
``0001_pg_init.sql`` generated from the SQLite head-schema dump and
translated by ``_tools/sqlite_to_pg.py``. Existing installs get their
ledger seeded past history during the SQLite → PG data migration.

Design rules:

* **Append-only.** Once a migration ships, never edit it. Schema fixes
  go in a new ``000N_*.sql`` file under ``migrations_pg/``.
* **One file = one migration.** Multi-statement scripts are fine but
  they're applied as a single ``executescript`` call (one ``cur.execute``
  with the whole body) — Postgres allows multi-statement strings as
  long as none are parameterized.
* **Hash mismatch is a hard error.** If the stored sha256 for an applied
  version differs from the on-disk file, ``run_pending`` raises
  ``MigrationDriftError`` rather than silently re-applying.

The runner does NOT handle data backfills — those live in
``elevate_cli/data/backfill.py`` and are invoked by ``elevate
migrate-data``. This module is purely for DDL.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

_LOG = logging.getLogger(__name__)


_MIGRATIONS_DIR = Path(__file__).parent / "migrations_pg"
_VERSION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_COMPATIBLE_PRIOR_HASHES: dict[str, set[str]] = {}


class MigrationError(RuntimeError):
    """Generic migration failure."""


class MigrationDriftError(MigrationError):
    """A migration on disk differs from what was applied to the database."""


class _MigrationFile(NamedTuple):
    version: str
    name: str
    path: Path
    sha256: str

    @classmethod
    def from_path(cls, path: Path) -> "_MigrationFile":
        m = _VERSION_RE.match(path.name)
        if not m:
            raise MigrationError(
                f"migration filename '{path.name}' does not match NNNN_name.sql"
            )
        body = path.read_bytes()
        return cls(
            version=m.group(1),
            name=path.name,
            path=path,
            sha256=hashlib.sha256(body).hexdigest(),
        )


def discover() -> list[_MigrationFile]:
    """Return all migration files, sorted by version. Empty if none.

    Validates that versions are strictly monotonic (no duplicates).
    """
    if not _MIGRATIONS_DIR.exists():
        return []
    files = [
        _MigrationFile.from_path(p)
        for p in sorted(_MIGRATIONS_DIR.glob("*.sql"))
    ]
    seen: set[str] = set()
    for f in files:
        if f.version in seen:
            raise MigrationError(f"duplicate migration version {f.version}")
        seen.add(f.version)
    return files


def _ensure_ledger(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            version    TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            sha256     TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def applied(conn) -> dict[str, dict[str, str]]:
    """Map ``version → {name, sha256, applied_at}`` for everything in the ledger."""
    _ensure_ledger(conn)
    rows = conn.execute(
        "SELECT version, name, sha256, applied_at FROM _schema_migrations"
    ).fetchall()
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        out[r[0]] = {"name": r[1], "sha256": r[2], "applied_at": r[3]}
    return out


def run_pending(conn) -> list[str]:
    """Apply any migrations not yet recorded in ``_schema_migrations``.

    Returns the list of versions that were applied this call. A no-op
    when the database is already at head.

    Raises :class:`MigrationDriftError` if a previously-applied migration
    has a different sha256 on disk — the caller should not attempt to
    "fix" this; treat it as a hard incident.
    """
    files = discover()
    seen = applied(conn)
    new_versions: list[str] = []

    for f in files:
        prior = seen.get(f.version)
        if prior is not None:
            if prior["sha256"] != f.sha256:
                if prior["sha256"] in _COMPATIBLE_PRIOR_HASHES.get(f.version, set()):
                    conn.execute(
                        "UPDATE _schema_migrations SET name=?, sha256=? WHERE version=?",
                        (f.name, f.sha256, f.version),
                    )
                    conn.commit()
                    continue
                # Version-slot reuse: the on-disk migration has a different
                # *filename* than what the ledger recorded. This happens when
                # the PG ledger was pre-seeded with legacy SQLite migration
                # labels (see `_pg_data_migrate._seed_legacy_ledger`) and a
                # PG-era migration later took the same version number. The
                # legacy seed is a label, not an actual applied schema, so
                # we drop the ledger row and apply the on-disk file fresh.
                #
                # Genuine drift (same filename, edited body) still falls
                # through to MigrationDriftError below.
                if prior.get("name") and prior["name"] != f.name:
                    conn.execute(
                        "DELETE FROM _schema_migrations WHERE version=?",
                        (f.version,),
                    )
                    conn.commit()
                    # Fall through to the apply block.
                else:
                    raise MigrationDriftError(
                        f"migration {f.version} on disk differs from applied "
                        f"copy: stored sha256={prior['sha256']} but file is "
                        f"{f.sha256}. Migrations are append-only — fix this with "
                        f"a new numbered migration, do not edit {f.name}."
                    )
            else:
                continue

        sql = f.path.read_text(encoding="utf-8")
        # Apply the DDL as one batched statement. Commit before recording
        # the ledger row so a partial-apply crash leaves a recoverable
        # state. (Postgres will roll back the implicit tx on error, but
        # any DDL inside that tx is gone too — which is what we want.)
        try:
            conn.executescript(sql)
        except Exception as exc:
            raise MigrationError(f"migration {f.name} failed: {exc}") from exc

        conn.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (f.version, f.name, f.sha256, _utcnow_iso()),
        )
        conn.commit()
        new_versions.append(f.version)

    # After the schema is at head, assert the code's INSERT column whitelists
    # are satisfied. A column referenced in code with no migration to create it
    # (the lofty_lead_user_id incident) is otherwise invisible until an INSERT
    # fails live and — under a shared transaction — silently drops the batch.
    gaps = check_write_schema(conn)
    if gaps:
        _LOG.critical(
            "SCHEMA/CODE DRIFT: write columns referenced in code are missing "
            "from the database (add a numbered migration to create them; "
            "INSERTs into these tables will fail until then): %s",
            gaps,
        )

    return new_versions


# ─── Schema-vs-code guard ──────────────────────────────────────────────
#
# Tables whose INSERT is built from a code-side column list. Adding a column to
# one of these lists without a matching migration makes every INSERT fail — and
# under the shared-transaction backfill that silently drops the whole sync. This
# guard catches the gap: loudly at startup (run_pending logs it) and as a hard
# failure in CI (tests/test_write_schema.py), so it can never ship again.


def _write_column_registry() -> dict[str, tuple[str, ...]]:
    from elevate_cli.data.contacts import _ENRICHMENT_COLUMNS
    from elevate_cli.data.deals import _DEAL_INSERT_BASE_COLUMNS

    return {
        "contacts": tuple(_ENRICHMENT_COLUMNS),
        "deals": tuple(_DEAL_INSERT_BASE_COLUMNS),
    }


def _table_columns(conn, table: str) -> set[str]:
    """Column names for ``table``, or empty set if it can't be introspected
    (table absent, or backend without information_schema)."""
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?",
            (table,),
        ).fetchall()
        cols = {r[0] for r in rows}
        if cols:
            return cols
    except Exception:
        pass
    try:  # SQLite fallback
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


def check_write_schema(conn) -> dict[str, list[str]]:
    """Return ``{table: [missing columns]}`` for the code write-whitelists that
    the DB does not satisfy. Empty dict means code and schema agree. Tables that
    don't exist yet (older/partial installs) are skipped, not reported."""
    missing: dict[str, list[str]] = {}
    for table, columns in _write_column_registry().items():
        present = _table_columns(conn, table)
        if not present:
            continue
        gap = [c for c in columns if c not in present]
        if gap:
            missing[table] = gap
    return missing


def head_version() -> str | None:
    """Highest known version on disk, or None when no migrations exist."""
    files = discover()
    return files[-1].version if files else None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "MigrationError",
    "MigrationDriftError",
    "applied",
    "discover",
    "head_version",
    "run_pending",
]
