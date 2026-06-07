"""Per-turn gateway usage ledger — Postgres-backed.

Replaces the ``turn_usage`` table that previously lived in
``~/.elevate/state.db`` and the vestigial ``~/.elevate/usage_ledger.sqlite``
file. Backfill happens in ``elevate_cli.data._aux_data_migrate``.

Public API mirrors the helpers in ``gateway.usage_ledger`` so that file
can swap one import and stop touching state.db / SessionDB entirely.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from elevate_cli.data.connection import connect

logger = logging.getLogger(__name__)


# Columns in insertion order. Mirrors state.db `turn_usage` schema minus the
# auto-generated `id`. Adding a new column? Add it in 0004_usage_ledger.sql
# first, then extend this tuple in the SAME ORDER as the table definition.
_INSERT_COLUMNS = (
    "timestamp",
    "session_id",
    "session_key",
    "message_id",
    "source",
    "provider",
    "model",
    "gateway_tool_profile",
    "gateway_tool_profile_reason",
    "selected_toolsets",
    "requested_toolsets",
    "configured_toolsets",
    "loaded_tool_count",
    "selected_tool_schema_tokens",
    "configured_tool_schema_tokens",
    "estimated_tool_schema_savings_tokens",
    "estimated_tool_schema_savings_pct",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "api_calls",
    "estimated_cost_usd",
    "cost_status",
    "cost_source",
    "latency_ms",
    "tool_calls",
    "status",
    "error_type",
)


def record_turn(row: Dict[str, Any]) -> Optional[int]:
    """Insert one turn-usage row. Returns the new id, or None on dedup/error.

    Dedup: the unique partial index ``idx_turn_usage_dedup`` enforces
    one row per ``(source, session_key, message_id)`` triple where all
    three are non-empty.
    """
    if not isinstance(row, dict):
        return None

    values: list[Any] = []
    for col in _INSERT_COLUMNS:
        v = row.get(col)
        # Normalise defaults to keep NOT NULL columns happy.
        if v is None and col in {
            "loaded_tool_count",
            "selected_tool_schema_tokens",
            "configured_tool_schema_tokens",
            "estimated_tool_schema_savings_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "api_calls",
            "latency_ms",
        }:
            v = 0
        values.append(v)

    col_list = ", ".join(_INSERT_COLUMNS)
    placeholders = ", ".join(["?"] * len(_INSERT_COLUMNS))
    sql = (
        f"INSERT INTO turn_usage ({col_list}) VALUES ({placeholders}) "
        "ON CONFLICT DO NOTHING RETURNING id"
    )

    try:
        with connect() as conn:
            cur = conn.execute(sql, values)
            result = cur.fetchone()
            conn.commit()
            if result is None:
                return None
            return int(result[0])
    except Exception as exc:
        logger.debug("Failed to write usage ledger row: %s", exc)
        return None


def recent_turns(limit: int = 20) -> List[Dict[str, Any]]:
    """Return the most recent rows, newest first."""
    limit = max(1, min(int(limit or 20), 1000))
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turn_usage ORDER BY timestamp DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("Failed to read usage ledger: %s", exc)
        return []


def sum_recent_tokens(
    *,
    since: float,
    source: str | None = None,
    session_key: str | None = None,
) -> int:
    """Sum total tokens for recent ledger rows."""
    where = ["timestamp >= ?"]
    params: list[Any] = [float(since)]
    if source:
        where.append("source = ?")
        params.append(str(source))
    if session_key:
        where.append("session_key = ?")
        params.append(str(session_key))
    sql = f"SELECT COALESCE(SUM(total_tokens), 0) AS total FROM turn_usage WHERE {' AND '.join(where)}"
    try:
        with connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return 0
        return int(row["total"] if isinstance(row, dict) else row[0] or 0)
    except Exception as exc:
        logger.debug("Failed to sum usage ledger tokens: %s", exc)
        return 0


__all__ = ["record_turn", "recent_turns", "sum_recent_tokens"]
