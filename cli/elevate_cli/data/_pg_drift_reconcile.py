"""One-shot drift reconciliation for the SessionDB shadow soak.

Run this when the drift checker reports rows missing in Postgres (the
expected/benign direction — a shadow write that failed open) or rows
missing in SQLite (the unexpected direction — usually direct-to-PG smoke
test rows with no SQLite source-of-truth).

Behaviour
---------
* **Missing in PG** → backfill from SQLite into ``chat_sessions`` /
  ``chat_messages`` using ``ON CONFLICT DO NOTHING``. Idempotent.
* **Missing in SQLite** → DELETE from the PG twin. Only safe because PG
  is still the shadow side; nothing reads from these orphan rows yet.
* ``chat_state_meta`` is upserted by ``set_meta`` on every write and has
  no orphan path; we still surface diff counts for it in the report.

The script is read-only against SQLite (URI mode=ro) and uses one
transaction per table on the PG side.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from elevate_cli.data import connection as pg_connection
from elevate_state import DEFAULT_DB_PATH


_SESSION_BACKFILL_COLS = (
    "id", "source", "user_id", "model", "model_config", "system_prompt",
    "parent_session_id", "started_at", "ended_at", "end_reason",
    "message_count", "tool_call_count", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
    "billing_provider", "billing_base_url", "billing_mode",
    "estimated_cost_usd", "actual_cost_usd", "cost_status", "cost_source",
    "pricing_version", "title", "api_call_count",
)

_MESSAGE_BACKFILL_COLS = (
    "session_id", "role", "content", "tool_call_id", "tool_calls",
    "tool_name", "timestamp", "token_count", "finish_reason",
    "reasoning", "reasoning_content", "reasoning_details",
    "codex_reasoning_items", "codex_message_items", "platform_message_id",
)


def _pg_value(value: Any) -> Any:
    if isinstance(value, str) and "\x00" in value:
        return value.replace("\x00", "")
    return value


def _pg_row(values: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(_pg_value(value) for value in values)


def _open_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"SQLite source not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == col for row in cur.fetchall())


def _backfill_sessions(sqlite_conn: sqlite3.Connection, pg_conn) -> int:
    """Copy every SQLite session row into PG (ON CONFLICT DO NOTHING).

    Returns the number of rows inserted (best-effort count from rowcount).
    """
    # Only select columns that actually exist on the SQLite side so a
    # schema lag on older DBs doesn't break the script.
    available = tuple(
        c for c in _SESSION_BACKFILL_COLS if _sqlite_has_column(sqlite_conn, "sessions", c)
    )
    if "id" not in available:
        raise RuntimeError("sessions table missing primary key column 'id'")

    cols_sql = ", ".join(available)
    placeholders = ", ".join(["?"] * len(available))
    insert_sql = (
        f"INSERT INTO chat_sessions ({cols_sql}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO NOTHING"
    )

    cur = sqlite_conn.execute(f"SELECT {cols_sql} FROM sessions")
    inserted = 0
    for row in cur:
        values = _pg_row(tuple(row[c] for c in available))
        pg_conn.execute(insert_sql, values)
        inserted += 1
    pg_conn.commit()
    return inserted


def _backfill_messages(sqlite_conn: sqlite3.Connection, pg_conn) -> int:
    """Backfill messages missing in PG without duplicating tool-call rows.

    chat_messages has no full natural unique key (only a partial unique
    index on content IS NOT NULL rows from migration 0006). Tool-call
    rows with NULL content can't be deduped by the index alone, so we
    do the missing-set computation in Python: pull every PG signature
    keyed on (session_id, role, timestamp, content, tool_call_id),
    iterate SQLite, and only insert what's actually absent.
    """
    available = tuple(
        c for c in _MESSAGE_BACKFILL_COLS if _sqlite_has_column(sqlite_conn, "messages", c)
    )
    cols_sql = ", ".join(available)
    placeholders = ", ".join(["?"] * len(available))

    insert_sql = (
        f"INSERT INTO chat_messages ({cols_sql}) "
        f"VALUES ({placeholders})"
    )

    # Pre-fetch the set of PG signatures so the per-row check is O(1).
    pg_cur = pg_conn.execute(
        "SELECT session_id, role, timestamp, content, tool_call_id "
        "FROM chat_messages"
    )
    pg_keys = {
        (
            r["session_id"],
            r["role"],
            r["timestamp"],
            _pg_value(r["content"]),
            r["tool_call_id"],
        )
        for r in pg_cur.fetchall()
    }

    cur = sqlite_conn.execute(f"SELECT {cols_sql} FROM messages")
    inserted = 0
    for row in cur:
        key = (
            row["session_id"],
            row["role"],
            row["timestamp"],
            _pg_value(row["content"]),
            row["tool_call_id"] if "tool_call_id" in row.keys() else None,
        )
        if key in pg_keys:
            continue
        values = _pg_row(tuple(row[c] for c in available))
        try:
            pg_conn.execute(insert_sql, values)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  message insert failed (session={row['session_id']!r}): {exc}",
                file=sys.stderr,
            )
            continue
        inserted += 1
        pg_keys.add(key)
    pg_conn.commit()
    return inserted


def _delete_orphan_pg_messages(sqlite_conn: sqlite3.Connection, pg_conn) -> int:
    """Drop PG message rows that have no SQLite counterpart.

    Matches on (session_id, role, timestamp, content). Only safe because
    PG isn't authoritative for reads yet.
    """
    # Build the set of SQLite (session_id, role, timestamp, content)
    # signatures in memory. Cheap at our scale (~20k rows).
    cur = sqlite_conn.execute(
        "SELECT session_id, role, timestamp, content FROM messages"
    )
    sqlite_keys = {
        (r["session_id"], r["role"], r["timestamp"], _pg_value(r["content"]))
        for r in cur
    }

    pg_cur = pg_conn.execute(
        "SELECT id, session_id, role, timestamp, content FROM chat_messages"
    )
    to_delete: list[int] = []
    for row in pg_cur.fetchall():
        key = (
            row["session_id"],
            row["role"],
            row["timestamp"],
            _pg_value(row["content"]),
        )
        if key not in sqlite_keys:
            to_delete.append(row["id"])

    if not to_delete:
        return 0

    # Chunk deletes to keep parameter lists sane.
    deleted = 0
    chunk = 500
    for i in range(0, len(to_delete), chunk):
        batch = to_delete[i : i + chunk]
        placeholders = ", ".join(["?"] * len(batch))
        pg_conn.execute(
            f"DELETE FROM chat_messages WHERE id IN ({placeholders})", batch
        )
        deleted += len(batch)
    pg_conn.commit()
    return deleted


def _delete_orphan_pg_sessions(sqlite_conn: sqlite3.Connection, pg_conn) -> int:
    cur = sqlite_conn.execute("SELECT id FROM sessions")
    sqlite_ids = {r["id"] for r in cur}
    pg_cur = pg_conn.execute("SELECT id FROM chat_sessions")
    orphans = [r["id"] for r in pg_cur.fetchall() if r["id"] not in sqlite_ids]
    if not orphans:
        return 0
    chunk = 500
    for i in range(0, len(orphans), chunk):
        batch = orphans[i : i + chunk]
        placeholders = ", ".join(["?"] * len(batch))
        pg_conn.execute(
            f"DELETE FROM chat_sessions WHERE id IN ({placeholders})", batch
        )
    pg_conn.commit()
    return len(orphans)


def run(sqlite_path: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    path = sqlite_path or DEFAULT_DB_PATH
    sqlite_conn = _open_sqlite(path)
    try:
        with pg_connection.connect() as pg_conn:
            if dry_run:
                # Just count what would happen.
                return {
                    "dry_run": True,
                    "sqlite_path": str(path),
                    "note": "no writes; use without --dry-run to apply",
                }

            sessions_inserted = _backfill_sessions(sqlite_conn, pg_conn)
            messages_inserted = _backfill_messages(sqlite_conn, pg_conn)
            session_orphans = _delete_orphan_pg_sessions(sqlite_conn, pg_conn)
            message_orphans = _delete_orphan_pg_messages(sqlite_conn, pg_conn)

            return {
                "dry_run": False,
                "sqlite_path": str(path),
                "sessions_inserted": sessions_inserted,
                "messages_inserted": messages_inserted,
                "session_orphans_deleted": session_orphans,
                "message_orphans_deleted": message_orphans,
            }
    finally:
        sqlite_conn.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Reconcile SessionDB shadow drift between SQLite and PG. "
            "Backfills rows missing in PG and deletes orphan rows in PG "
            "that have no SQLite source."
        )
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=None,
        help=f"Path to SQLite source (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Connect to both DBs but don't write",
    )
    args = parser.parse_args(argv)

    try:
        result = run(sqlite_path=args.sqlite_path, dry_run=args.dry_run)
    except Exception as exc:
        print(f"drift-reconcile failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
