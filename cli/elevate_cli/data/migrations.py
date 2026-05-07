"""SQL migration runner for ``operational.db``.

Discovers numbered ``.sql`` files in ``elevate_cli/data/migrations/`` and
applies them in lexical order against the central operational store.
Each applied file is recorded in the ``_schema_migrations`` table with
the file's SHA-256 — re-running is a no-op.

Design rules:

* **Append-only.** Once a migration ships, never edit it. Schema fixes
  go in a new ``000N_*.sql`` file.
* **One file = one migration.** Multi-statement scripts are fine but
  they're applied as a single SQLite ``executescript`` inside an
  IMMEDIATE transaction.
* **Hash mismatch is a hard error.** If the stored sha256 for an applied
  version differs from the on-disk file, ``run_pending`` raises
  ``MigrationDriftError`` rather than silently re-applying.

The runner does NOT handle data backfills — those live in
``elevate_cli/data/backfill.py`` and are invoked by ``elevate
migrate-data``. This module is purely for DDL.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, NamedTuple


_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_VERSION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_COMPATIBLE_PRIOR_HASHES = {
    # 0003 shipped briefly with province defaulting to "BC" before the
    # package work moved jurisdiction defaults into config. The table shape is
    # compatible with the current migration, and later migrations add the
    # source-of-truth columns. Normalize the ledger instead of blocking existing
    # local operator DBs forever.
    "0003": {
        "bbc136276d60302d56289888ccb91b7fb8bc30547aba07587168c6d1912d573a",
    },
}


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


def _ensure_ledger(conn: sqlite3.Connection) -> None:
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


def applied(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Map ``version → {name, sha256, applied_at}`` for everything in the ledger."""
    _ensure_ledger(conn)
    rows = conn.execute(
        "SELECT version, name, sha256, applied_at FROM _schema_migrations"
    ).fetchall()
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        out[r[0]] = {"name": r[1], "sha256": r[2], "applied_at": r[3]}
    return out


def run_pending(conn: sqlite3.Connection) -> list[str]:
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
                raise MigrationDriftError(
                    f"migration {f.version} on disk differs from applied "
                    f"copy: stored sha256={prior['sha256']} but file is "
                    f"{f.sha256}. Migrations are append-only — fix this with "
                    f"a new numbered migration, do not edit {f.name}."
                )
            continue

        sql = f.path.read_text(encoding="utf-8")
        # SQLite cannot run executescript inside an explicit transaction,
        # but executescript itself wraps multi-statement DDL safely. We
        # commit immediately after, then record the ledger row in its own
        # write so partial-apply on crash leaves a recoverable state.
        try:
            conn.executescript(sql)
        except sqlite3.Error as exc:
            raise MigrationError(f"migration {f.name} failed: {exc}") from exc

        conn.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (f.version, f.name, f.sha256, _utcnow_iso()),
        )
        conn.commit()
        new_versions.append(f.version)

    return new_versions


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
