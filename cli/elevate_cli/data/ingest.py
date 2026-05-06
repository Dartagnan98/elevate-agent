"""Connector ingest run tracking + rollback.

Every connector wrap (Lofty, Apple Messages, Composio Gmail, …) opens
an ingest run, processes its rows, then closes the run. Every row that
lands in the DB carries the run id, which gives us replay (re-run a
single ingest) and surgical rollback (delete every row from one run).

Public surface:

* :func:`record_ingest_run_started`
* :func:`record_ingest_run_completed`
* :func:`update_ingest_run_counters`
* :func:`rollback_ingest_run`
"""

from __future__ import annotations

import sqlite3
from typing import Any

from elevate_cli.data._util import new_id, now_iso


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceId": row["source_id"],
        "startedAt": row["started_at"],
        "completedAt": row["completed_at"],
        "status": row["status"],
        "rowsSeen": row["rows_seen"],
        "rowsWritten": row["rows_written"],
        "rowsQuarantined": row["rows_quarantined"],
        "error": row["error"],
    }


def record_ingest_run_started(
    conn: sqlite3.Connection, source_id: str
) -> dict[str, Any]:
    rid = new_id()
    conn.execute(
        """
        INSERT INTO ingest_runs(id, source_id, started_at, status)
        VALUES (?, ?, ?, 'running')
        """,
        (rid, source_id, now_iso()),
    )
    return _row_to_run(
        conn.execute("SELECT * FROM ingest_runs WHERE id=?", (rid,)).fetchone()
    )


def record_ingest_run_completed(
    conn: sqlite3.Connection,
    ingest_run_id: str,
    *,
    status: str,
    rows_seen: int,
    rows_written: int,
    rows_quarantined: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    if status not in {"completed", "failed", "partial"}:
        raise ValueError(f"invalid ingest run terminal status {status!r}")
    conn.execute(
        """
        UPDATE ingest_runs
        SET status=?, rows_seen=?, rows_written=?, rows_quarantined=?,
            error=?, completed_at=?
        WHERE id=?
        """,
        (status, rows_seen, rows_written, rows_quarantined, error, now_iso(), ingest_run_id),
    )
    return _row_to_run(
        conn.execute(
            "SELECT * FROM ingest_runs WHERE id=?", (ingest_run_id,)
        ).fetchone()
    )


def update_ingest_run_counters(
    conn: sqlite3.Connection,
    ingest_run_id: str,
    *,
    rows_seen_delta: int = 0,
    rows_written_delta: int = 0,
    rows_quarantined_delta: int = 0,
) -> None:
    """Cheap incremental update used inside a hot ingest loop. Call
    :func:`record_ingest_run_completed` once at the end with the final
    totals — this helper is for visibility while the run is still
    in-flight (e.g. cron status pages)."""
    conn.execute(
        """
        UPDATE ingest_runs
        SET rows_seen        = rows_seen + ?,
            rows_written     = rows_written + ?,
            rows_quarantined = rows_quarantined + ?
        WHERE id = ?
        """,
        (rows_seen_delta, rows_written_delta, rows_quarantined_delta, ingest_run_id),
    )


def get_ingest_run(
    conn: sqlite3.Connection, ingest_run_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ingest_runs WHERE id=?", (ingest_run_id,)
    ).fetchone()
    return _row_to_run(row) if row else None


def rollback_ingest_run(
    conn: sqlite3.Connection,
    ingest_run_id: str,
    *,
    actor: str,
) -> dict[str, int]:
    """Delete every row created by a single ingest run.

    The action is allowed for any actor — the caller (CLI command,
    /admin endpoint) is responsible for gating who can trigger it. We
    record the actor in the ingest_runs.error field for audit.

    Returns a count dict ``{events: N, contacts: N, ...}`` showing what
    was removed. Identity rows attached to deleted contacts disappear via
    ``ON DELETE CASCADE``; events too.
    """
    counts: dict[str, int] = {}

    # Order matters: delete dependent rows before parents so the FK
    # cascades stay predictable.
    cur = conn.execute(
        "DELETE FROM events WHERE ingest_run_id = ?", (ingest_run_id,)
    )
    counts["events"] = cur.rowcount

    cur = conn.execute(
        "DELETE FROM contacts WHERE ingest_run_id = ?", (ingest_run_id,)
    )
    counts["contacts"] = cur.rowcount

    conn.execute(
        """
        UPDATE ingest_runs
        SET status='failed', error=?, completed_at=?
        WHERE id=?
        """,
        (f"rolled_back_by:{actor}", now_iso(), ingest_run_id),
    )
    return counts
