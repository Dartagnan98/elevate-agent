"""SQLite ↔ Postgres drift checker for the SessionDB shadow-write soak.

Background
----------
The SessionDB writer cutover ships in two phases. Phase 2a (live) writes
every chat-table mutation to BOTH the legacy SQLite store at ``state.db``
and the new Postgres operational store, fail-open. The SQLite path stays
authoritative for reads.

Phase 2b flips reads to Postgres and deletes the SQLite write path. Before
that flip we want **48 hours of zero drift** — every row that exists in
SQLite must exist in Postgres with the same payload.

This module compares the two stores along three axes:

* **Row counts** for ``sessions/chat_sessions``, ``messages/chat_messages``,
  ``state_meta/chat_state_meta``.
* **Per-row content hashes** keyed on the natural identifier for each
  table. Mismatches and missing rows are reported by key.
* **Asymmetric flow**: rows in SQLite missing from PG are *shadow-write
  failures* (expected to converge to zero). Rows in PG missing from SQLite
  are *bugs* (should always be zero — PG only receives writes that already
  hit SQLite).

The script is intentionally read-only, takes no destructive action, and
prints a structured report. CI / a launchd timer can run it at the 48h
mark and gate the cutover on the exit code.

Exit codes
----------
* ``0`` — fully converged. Safe to flip reads to PG.
* ``1`` — drift detected. Output lists the diff. Do **not** flip.
* ``2`` — checker failed to run (PG unreachable, SQLite missing, etc.).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elevate_cli.data import connection as pg_connection
from elevate_state import DEFAULT_DB_PATH


# Natural-key tuples for each table. The drift checker treats these as
# the row identifier and hashes the rest of the columns it cares about
# to detect content mismatches.
_SESSION_HASH_COLS = (
    "id",
    "started_at",
    "ended_at",
    "message_count",
    "input_tokens",
    "output_tokens",
    "system_prompt",
    "model",
    "title",
)

_MESSAGE_HASH_COLS = (
    "session_id",
    "role",
    "content",
    "timestamp",
)

_STATE_META_HASH_COLS = ("key", "value")


@dataclass
class TableDiff:
    """Result of comparing a single SQLite table against its PG twin."""

    sqlite_table: str
    pg_table: str
    sqlite_count: int = 0
    pg_count: int = 0
    missing_in_pg: list[str] = field(default_factory=list)
    missing_in_sqlite: list[str] = field(default_factory=list)
    hash_mismatches: list[str] = field(default_factory=list)

    @property
    def converged(self) -> bool:
        return (
            self.sqlite_count == self.pg_count
            and not self.missing_in_pg
            and not self.missing_in_sqlite
            and not self.hash_mismatches
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sqlite_table": self.sqlite_table,
            "pg_table": self.pg_table,
            "sqlite_count": self.sqlite_count,
            "pg_count": self.pg_count,
            "missing_in_pg": self.missing_in_pg,
            "missing_in_sqlite": self.missing_in_sqlite,
            "hash_mismatches": self.hash_mismatches,
            "converged": self.converged,
        }


def _pg_value(value: Any) -> Any:
    if isinstance(value, str) and "\x00" in value:
        return value.replace("\x00", "")
    return value


def _hash_row(values: tuple) -> str:
    """SHA-256 of pipe-joined string values. Stable across runtimes."""
    payload = "|".join("" if v is None else str(_pg_value(v)) for v in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _open_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"SQLite source not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _collect_sqlite_hashes(
    conn: sqlite3.Connection,
    table: str,
    key_cols: tuple[str, ...],
    hash_cols: tuple[str, ...],
) -> tuple[int, dict[str, str]]:
    """Walk a SQLite table and return (count, {key: hash})."""
    cols_sql = ", ".join(key_cols + hash_cols)
    cur = conn.execute(f"SELECT {cols_sql} FROM {table}")
    out: dict[str, str] = {}
    count = 0
    for row in cur:
        key_values = tuple(row[c] for c in key_cols)
        hash_values = tuple(row[c] for c in hash_cols)
        key = _hash_row(key_values)[:32]
        out[key] = _hash_row(hash_values)
        count += 1
    return count, out


def _collect_pg_hashes(
    conn: pg_connection.PgConnection,
    table: str,
    key_cols: tuple[str, ...],
    hash_cols: tuple[str, ...],
) -> tuple[int, dict[str, str]]:
    """Walk a PG table and return (count, {key: hash}).

    Uses the same key/hash composition as the SQLite side so the maps
    are directly comparable.
    """
    cols_sql = ", ".join(key_cols + hash_cols)
    cur = conn.execute(f"SELECT {cols_sql} FROM {table}")
    out: dict[str, str] = {}
    count = 0
    for row in cur.fetchall():
        # PgConnection rows are dict-like via _Row shim.
        try:
            key_values = tuple(row[c] for c in key_cols)
            hash_values = tuple(row[c] for c in hash_cols)
        except (KeyError, TypeError):
            # Tuple-style fallback for raw rows.
            key_values = tuple(row[i] for i in range(len(key_cols)))
            hash_values = tuple(
                row[i] for i in range(len(key_cols), len(key_cols) + len(hash_cols))
            )
        key = _hash_row(key_values)[:32]
        out[key] = _hash_row(hash_values)
        count += 1
    return count, out


def _diff_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: pg_connection.PgConnection,
    sqlite_table: str,
    pg_table: str,
    key_cols: tuple[str, ...],
    hash_cols: tuple[str, ...],
    sample_cap: int = 25,
) -> TableDiff:
    """Compare one SQLite table against its PG twin."""
    sqlite_count, sqlite_map = _collect_sqlite_hashes(
        sqlite_conn, sqlite_table, key_cols, hash_cols
    )
    pg_count, pg_map = _collect_pg_hashes(
        pg_conn, pg_table, key_cols, hash_cols
    )

    sqlite_keys = set(sqlite_map.keys())
    pg_keys = set(pg_map.keys())

    missing_in_pg = sorted(sqlite_keys - pg_keys)[:sample_cap]
    missing_in_sqlite = sorted(pg_keys - sqlite_keys)[:sample_cap]
    hash_mismatches = sorted(
        k for k in (sqlite_keys & pg_keys) if sqlite_map[k] != pg_map[k]
    )[:sample_cap]

    return TableDiff(
        sqlite_table=sqlite_table,
        pg_table=pg_table,
        sqlite_count=sqlite_count,
        pg_count=pg_count,
        missing_in_pg=missing_in_pg,
        missing_in_sqlite=missing_in_sqlite,
        hash_mismatches=hash_mismatches,
    )


def run(sqlite_path: Path | None = None) -> dict[str, Any]:
    """Compare the SQLite SessionDB against the PG shadow.

    Returns a dict suitable for JSON serialisation.
    """
    path = sqlite_path or DEFAULT_DB_PATH
    sqlite_conn = _open_sqlite(path)
    try:
        with pg_connection.connect() as pg_conn:
            diffs = [
                _diff_table(
                    sqlite_conn,
                    pg_conn,
                    sqlite_table="sessions",
                    pg_table="chat_sessions",
                    key_cols=("id",),
                    hash_cols=_SESSION_HASH_COLS,
                ),
                _diff_table(
                    sqlite_conn,
                    pg_conn,
                    sqlite_table="messages",
                    pg_table="chat_messages",
                    # session_id + timestamp + role is unique in practice;
                    # using all 4 hash cols as the key avoids leaning on
                    # the auto-increment id which differs across stores.
                    key_cols=_MESSAGE_HASH_COLS,
                    hash_cols=_MESSAGE_HASH_COLS,
                ),
                _diff_table(
                    sqlite_conn,
                    pg_conn,
                    sqlite_table="state_meta",
                    pg_table="chat_state_meta",
                    key_cols=("key",),
                    hash_cols=_STATE_META_HASH_COLS,
                ),
            ]
    finally:
        sqlite_conn.close()

    converged = all(d.converged for d in diffs)
    return {
        "sqlite_path": str(path),
        "converged": converged,
        "tables": [d.to_dict() for d in diffs],
    }


def format_report(result: dict[str, Any]) -> str:
    """Render the drift result as a human-readable block."""
    lines: list[str] = []
    lines.append(f"SQLite source: {result['sqlite_path']}")
    lines.append(
        f"Verdict: {'CONVERGED' if result['converged'] else 'DRIFT DETECTED'}"
    )
    lines.append("")
    lines.append(
        f"{'sqlite':22s}  {'pg':22s}  {'sqlite#':>8s}  {'pg#':>8s}  "
        f"{'miss>pg':>8s}  {'miss>sl':>8s}  {'hashΔ':>6s}"
    )
    lines.append("-" * 92)
    for t in result["tables"]:
        lines.append(
            f"{t['sqlite_table']:22s}  {t['pg_table']:22s}  "
            f"{t['sqlite_count']:>8d}  {t['pg_count']:>8d}  "
            f"{len(t['missing_in_pg']):>8d}  {len(t['missing_in_sqlite']):>8d}  "
            f"{len(t['hash_mismatches']):>6d}"
        )

    # Sample keys for any non-converged table.
    for t in result["tables"]:
        if not (
            t["missing_in_pg"] or t["missing_in_sqlite"] or t["hash_mismatches"]
        ):
            continue
        lines.append("")
        lines.append(f"--- {t['sqlite_table']} → {t['pg_table']} samples ---")
        if t["missing_in_pg"]:
            lines.append(
                f"  missing in PG ({len(t['missing_in_pg'])}): "
                f"{', '.join(t['missing_in_pg'][:5])}"
                f"{'...' if len(t['missing_in_pg']) > 5 else ''}"
            )
        if t["missing_in_sqlite"]:
            lines.append(
                f"  missing in SQLite ({len(t['missing_in_sqlite'])}): "
                f"{', '.join(t['missing_in_sqlite'][:5])}"
                f"{'...' if len(t['missing_in_sqlite']) > 5 else ''}"
            )
        if t["hash_mismatches"]:
            lines.append(
                f"  hash mismatch ({len(t['hash_mismatches'])}): "
                f"{', '.join(t['hash_mismatches'][:5])}"
                f"{'...' if len(t['hash_mismatches']) > 5 else ''}"
            )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Compare SQLite SessionDB to the PG shadow. Exit 0 iff "
            "fully converged."
        )
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=None,
        help=f"Path to SQLite source (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of text"
    )
    args = parser.parse_args(argv)

    try:
        result = run(sqlite_path=args.sqlite_path)
    except Exception as exc:
        print(f"drift-check failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_report(result))

    return 0 if result["converged"] else 1


if __name__ == "__main__":
    sys.exit(main())
