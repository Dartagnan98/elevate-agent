"""Shadow-read parity tracking.

Sprint 2's cutover from JSONL-derived reads to operational.db-derived
reads is gated on N requests with zero diffs. The middleware that runs
during shadow mode uses these helpers to record a per-request
``data_parity_snapshots`` row; the ``elevate parity-report`` CLI
queries them.

Public surface:

* :func:`record_parity_snapshot`
* :func:`parity_diff_count`
* :func:`recent_diffs`
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from elevate_cli.data._util import new_id, now_iso


def _normalize(obj: Any) -> str:
    """Stable JSON for hashing — keys sorted, no extra whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(obj: Any) -> str:
    return hashlib.sha256(_normalize(obj).encode("utf-8")).hexdigest()


def _diff(jsonl_resp: Any, db_resp: Any) -> dict[str, Any] | None:
    """Return a structural diff dict when responses differ, else None.

    For now this is intentionally cheap — full equality check on
    canonicalized JSON. Sprint 2 will add per-key diffing if the rate
    of mismatches makes the bare equality answer too noisy."""
    if _hash(jsonl_resp) == _hash(db_resp):
        return None
    return {
        "jsonl": jsonl_resp,
        "db": db_resp,
    }


def record_parity_snapshot(
    conn: sqlite3.Connection,
    *,
    endpoint: str,
    request_args: Any,
    jsonl_response: Any,
    db_response: Any,
) -> dict[str, Any]:
    """Persist one request's pair of responses + the diff (when any).

    Returns the dict form of the inserted row; the diff field is None
    when the responses were byte-equal."""
    diff = _diff(jsonl_response, db_response)
    sid = new_id()
    conn.execute(
        """
        INSERT INTO data_parity_snapshots(
            id, endpoint, request_args_json,
            jsonl_response_hash, db_response_hash,
            diff_json, captured_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            sid,
            endpoint,
            _normalize(request_args),
            _hash(jsonl_response),
            _hash(db_response),
            _normalize(diff) if diff is not None else None,
            now_iso(),
        ),
    )
    return {
        "id": sid,
        "endpoint": endpoint,
        "matched": diff is None,
    }


def parity_diff_count(
    conn: sqlite3.Connection, *, since: str | None = None
) -> int:
    """How many shadow-read snapshots disagreed since ``since`` (ISO ts).
    The Sprint 2 flip is gated on this returning 0 for a 3-day window."""
    sql = "SELECT COUNT(*) FROM data_parity_snapshots WHERE diff_json IS NOT NULL"
    params: list[Any] = []
    if since:
        sql += " AND captured_at >= ?"
        params.append(since)
    return int(conn.execute(sql, params).fetchone()[0])


def parity_total_count(
    conn: sqlite3.Connection, *, since: str | None = None
) -> int:
    """Total shadow-read snapshots since ``since``. Used to confirm the
    middleware is actually being exercised before declaring a clean
    window."""
    sql = "SELECT COUNT(*) FROM data_parity_snapshots WHERE 1=1"
    params: list[Any] = []
    if since:
        sql += " AND captured_at >= ?"
        params.append(since)
    return int(conn.execute(sql, params).fetchone()[0])


def recent_diffs(
    conn: sqlite3.Connection, *, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, endpoint, request_args_json, diff_json, captured_at
        FROM data_parity_snapshots
        WHERE diff_json IS NOT NULL
        ORDER BY captured_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "endpoint": r["endpoint"],
            "requestArgs": json.loads(r["request_args_json"]),
            "diff": json.loads(r["diff_json"]),
            "capturedAt": r["captured_at"],
        }
        for r in rows
    ]
