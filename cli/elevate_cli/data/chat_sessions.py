"""Postgres-backed chat session + message store (infrastructure layer).

Replaces ``state.db`` (sessions + messages + state_meta) and the legacy
``~/.elevate/sessions/*.jsonl`` transcript files.

This module ships the PG tables (migration 0005_chat_sessions.sql), the
backfill target, and a minimal read API. The full cutover of
``elevate_state.SessionDB`` to write here is queued as a follow-up sprint
because that class has ~20 non-test call sites and a 3,381-line surface
that needs the full test runner to validate. Until that ships, this
module's tables are populated by the one-shot backfill
(``elevate_cli/data/_aux_data_migrate.py``) and read by analytical
queries that benefit from PG's better indexing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from elevate_cli.data.connection import connect

logger = logging.getLogger(__name__)


# Columns kept identical to state.db sessions table (minus FTS) so the
# eventual cutover is a connection swap, not a rename.
_SESSION_COLUMNS = (
    "id", "source", "user_id", "model", "model_config", "system_prompt",
    "parent_session_id", "started_at", "ended_at", "end_reason",
    "message_count", "tool_call_count", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
    "billing_provider", "billing_base_url", "billing_mode",
    "estimated_cost_usd", "actual_cost_usd", "cost_status", "cost_source",
    "pricing_version", "title", "api_call_count",
    "handoff_state", "handoff_platform", "handoff_error",
)

_MESSAGE_COLUMNS = (
    "session_id", "role", "content", "tool_call_id", "tool_calls",
    "tool_name", "timestamp", "token_count", "finish_reason",
    "reasoning", "reasoning_content", "reasoning_details",
    "codex_reasoning_items", "codex_message_items", "platform_message_id",
)


def insert_session_if_missing(
    session_id: str,
    source: str,
    *,
    model: Optional[str] = None,
    model_config_json: Optional[str] = None,
    system_prompt: Optional[str] = None,
    user_id: Optional[str] = None,
    parent_session_id: Optional[str] = None,
    started_at: Optional[float] = None,
) -> None:
    """SessionDB._insert_session_row shadow target.

    Mirrors the SQLite INSERT OR IGNORE semantics — never overwrites
    an existing row. Used by SessionDB.create_session and any code path
    that needs an idempotent "session exists" guarantee.
    """
    if not session_id:
        return
    sql = (
        "INSERT INTO chat_sessions "
        "(id, source, user_id, model, model_config, system_prompt, "
        "parent_session_id, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO NOTHING"
    )
    with connect() as conn:
        conn.execute(
            sql,
            (
                session_id, source, user_id, model, model_config_json,
                system_prompt, parent_session_id, started_at,
            ),
        )
        conn.commit()


def end_session(session_id: str, ended_at: float, end_reason: str) -> None:
    if not session_id:
        return
    with connect() as conn:
        conn.execute(
            "UPDATE chat_sessions SET ended_at = ?, end_reason = ? "
            "WHERE id = ? AND ended_at IS NULL",
            (ended_at, end_reason, session_id),
        )
        conn.commit()


def reopen_session(session_id: str) -> None:
    if not session_id:
        return
    with connect() as conn:
        conn.execute(
            "UPDATE chat_sessions SET ended_at = NULL, end_reason = NULL "
            "WHERE id = ?",
            (session_id,),
        )
        conn.commit()


def update_system_prompt(session_id: str, system_prompt: str) -> None:
    if not session_id:
        return
    with connect() as conn:
        conn.execute(
            "UPDATE chat_sessions SET system_prompt = ? WHERE id = ?",
            (system_prompt, session_id),
        )
        conn.commit()


def update_token_counts(
    session_id: str,
    *,
    absolute: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    estimated_cost_usd: Optional[float] = None,
    actual_cost_usd: Optional[float] = None,
    cost_status: Optional[str] = None,
    cost_source: Optional[str] = None,
    pricing_version: Optional[str] = None,
    billing_provider: Optional[str] = None,
    billing_base_url: Optional[str] = None,
    billing_mode: Optional[str] = None,
    model: Optional[str] = None,
    api_call_count: int = 0,
) -> None:
    """Shadow target for SessionDB.update_token_counts.

    Mirrors the absolute/delta semantics of the SQLite path.
    """
    if not session_id:
        return
    # PG can't infer types of bare `?` placeholders that may be NULL —
    # text/numeric casts pin the type so the executor stops complaining
    # about `IndeterminateDatatype` on None values.
    if absolute:
        sql = (
            "UPDATE chat_sessions SET "
            "input_tokens = ?, output_tokens = ?, "
            "cache_read_tokens = ?, cache_write_tokens = ?, "
            "reasoning_tokens = ?, "
            "estimated_cost_usd = COALESCE(?::double precision, 0), "
            "actual_cost_usd = CASE WHEN ?::double precision IS NULL "
            "                       THEN actual_cost_usd "
            "                       ELSE ?::double precision END, "
            "cost_status = COALESCE(?::text, cost_status), "
            "cost_source = COALESCE(?::text, cost_source), "
            "pricing_version = COALESCE(?::text, pricing_version), "
            "billing_provider = COALESCE(billing_provider, ?::text), "
            "billing_base_url = COALESCE(billing_base_url, ?::text), "
            "billing_mode = COALESCE(billing_mode, ?::text), "
            "model = COALESCE(model, ?::text), "
            "api_call_count = ? "
            "WHERE id = ?"
        )
    else:
        sql = (
            "UPDATE chat_sessions SET "
            "input_tokens = input_tokens + ?, "
            "output_tokens = output_tokens + ?, "
            "cache_read_tokens = cache_read_tokens + ?, "
            "cache_write_tokens = cache_write_tokens + ?, "
            "reasoning_tokens = reasoning_tokens + ?, "
            "estimated_cost_usd = COALESCE(estimated_cost_usd, 0) "
            "                     + COALESCE(?::double precision, 0), "
            "actual_cost_usd = CASE WHEN ?::double precision IS NULL "
            "                       THEN actual_cost_usd "
            "                       ELSE COALESCE(actual_cost_usd, 0) "
            "                            + ?::double precision END, "
            "cost_status = COALESCE(?::text, cost_status), "
            "cost_source = COALESCE(?::text, cost_source), "
            "pricing_version = COALESCE(?::text, pricing_version), "
            "billing_provider = COALESCE(billing_provider, ?::text), "
            "billing_base_url = COALESCE(billing_base_url, ?::text), "
            "billing_mode = COALESCE(billing_mode, ?::text), "
            "model = COALESCE(model, ?::text), "
            "api_call_count = COALESCE(api_call_count, 0) + ? "
            "WHERE id = ?"
        )
    params = (
        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
        reasoning_tokens, estimated_cost_usd, actual_cost_usd, actual_cost_usd,
        cost_status, cost_source, pricing_version,
        billing_provider, billing_base_url, billing_mode,
        model, api_call_count, session_id,
    )
    with connect() as conn:
        conn.execute(sql, params)
        conn.commit()


def append_message_shadow(
    session_id: str,
    role: str,
    *,
    content: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_calls_json: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    token_count: Optional[int] = None,
    finish_reason: Optional[str] = None,
    reasoning: Optional[str] = None,
    reasoning_content: Optional[str] = None,
    reasoning_details_json: Optional[str] = None,
    codex_reasoning_items_json: Optional[str] = None,
    codex_message_items_json: Optional[str] = None,
    platform_message_id: Optional[str] = None,
    timestamp: Optional[float] = None,
    num_tool_calls: int = 0,
) -> None:
    """Shadow append: insert one message + bump chat_sessions counters.

    All structured fields are pre-serialised by the caller (matching the
    SQLite path's JSON-encoding before the transaction). Counter updates
    mirror SessionDB.append_message exactly.
    """
    if not session_id:
        return
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages "
            "(session_id, role, content, tool_call_id, tool_calls, "
            "tool_name, timestamp, token_count, finish_reason, "
            "reasoning, reasoning_content, reasoning_details, "
            "codex_reasoning_items, codex_message_items, "
            "platform_message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, role, content, tool_call_id, tool_calls_json,
                tool_name, timestamp, token_count, finish_reason,
                reasoning, reasoning_content, reasoning_details_json,
                codex_reasoning_items_json, codex_message_items_json,
                platform_message_id,
            ),
        )
        if num_tool_calls > 0:
            conn.execute(
                "UPDATE chat_sessions SET message_count = message_count + 1, "
                "tool_call_count = tool_call_count + ? WHERE id = ?",
                (num_tool_calls, session_id),
            )
        else:
            conn.execute(
                "UPDATE chat_sessions SET message_count = message_count + 1 "
                "WHERE id = ?",
                (session_id,),
            )
        conn.commit()


def replace_messages_shadow(
    session_id: str, rows: List[Dict[str, Any]],
) -> None:
    """Atomically delete + reinsert every chat_message for a session.

    Each row dict carries the same already-serialised fields as
    ``append_message_shadow``. Counter totals are recomputed from the
    incoming rows so they match the SQLite path's final values.
    """
    if not session_id:
        return
    total_messages = len(rows)
    total_tool_calls = sum(int(r.get("num_tool_calls") or 0) for r in rows)
    with connect() as conn:
        conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "UPDATE chat_sessions SET message_count = 0, "
            "tool_call_count = 0 WHERE id = ?",
            (session_id,),
        )
        if rows:
            payload = [
                (
                    session_id,
                    r.get("role") or "unknown",
                    r.get("content"),
                    r.get("tool_call_id"),
                    r.get("tool_calls_json"),
                    r.get("tool_name"),
                    r.get("timestamp"),
                    r.get("token_count"),
                    r.get("finish_reason"),
                    r.get("reasoning"),
                    r.get("reasoning_content"),
                    r.get("reasoning_details_json"),
                    r.get("codex_reasoning_items_json"),
                    r.get("codex_message_items_json"),
                    r.get("platform_message_id"),
                )
                for r in rows
            ]
            conn.executemany(
                "INSERT INTO chat_messages "
                "(session_id, role, content, tool_call_id, tool_calls, "
                "tool_name, timestamp, token_count, finish_reason, "
                "reasoning, reasoning_content, reasoning_details, "
                "codex_reasoning_items, codex_message_items, "
                "platform_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                payload,
            )
        conn.execute(
            "UPDATE chat_sessions SET message_count = ?, "
            "tool_call_count = ? WHERE id = ?",
            (total_messages, total_tool_calls, session_id),
        )
        conn.commit()


def upsert_session(row: Dict[str, Any]) -> None:
    """Upsert one chat session row into PG. Used by the backfill."""
    cols = list(_SESSION_COLUMNS)
    values = [row.get(c) for c in cols]

    # NOT NULL columns default to 0 when missing.
    int_defaults = {
        "message_count", "tool_call_count", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
        "api_call_count",
    }
    for i, c in enumerate(cols):
        if values[i] is None and c in int_defaults:
            values[i] = 0

    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))
    update_set = ", ".join(
        f"{c}=excluded.{c}" for c in cols if c != "id"
    )
    sql = (
        f"INSERT INTO chat_sessions ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {update_set}"
    )
    with connect() as conn:
        conn.execute(sql, values)
        conn.commit()


def insert_message(row: Dict[str, Any]) -> Optional[int]:
    """Insert one chat message row into PG. Returns new id."""
    cols = list(_MESSAGE_COLUMNS)
    values = [row.get(c) for c in cols]
    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))
    sql = (
        f"INSERT INTO chat_messages ({col_list}) VALUES ({placeholders}) "
        "RETURNING id"
    )
    with connect() as conn:
        cur = conn.execute(sql, values)
        result = cur.fetchone()
        conn.commit()
    return int(result[0]) if result is not None else None


def insert_messages_batch(rows: List[Dict[str, Any]]) -> int:
    """Bulk insert. Returns count actually inserted."""
    if not rows:
        return 0
    cols = list(_MESSAGE_COLUMNS)
    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO chat_messages ({col_list}) VALUES ({placeholders})"
    payload = [[r.get(c) for c in cols] for r in rows]
    with connect() as conn:
        conn.executemany(sql, payload)
        conn.commit()
    return len(payload)


def session_exists(session_id: str) -> bool:
    if not session_id:
        return False
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    return row is not None


def message_count(session_id: str | None = None) -> int:
    """Count messages, optionally scoped to one session.

    Matches the SessionDB.message_count signature exactly so the PG-first
    cutover in elevate_state.py can hand the call straight through.
    """
    with connect() as conn:
        if session_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()
    return int(row[0]) if row else 0


def session_count(source: str | None = None) -> int:
    """Count sessions, optionally filtered by source.

    Mirrors SessionDB.session_count so the cutover is a drop-in swap.
    """
    with connect() as conn:
        if source:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_sessions WHERE source = ?",
                (source,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()
    return int(row[0]) if row else 0


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one session by id, returned as a plain dict.

    Matches SessionDB.get_session: returns None when missing, dict
    keyed on chat_sessions column names otherwise. Callers should treat
    `chat_sessions` columns as the source of truth — they were named to
    match the SQLite `sessions` table 1:1, so existing call sites that
    poke at the returned dict by key continue to work.
    """
    if not session_id:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def get_messages(session_id: str) -> List[Dict[str, Any]]:
    """Fetch every message for a session in insertion order.

    Mirrors SessionDB.get_messages: returns a list of dicts. Caller is
    responsible for any post-processing (tool_calls JSON decoding,
    content normalisation) — we hand back the raw PG shape so the
    SessionDB-side cutover can keep its existing decode logic.
    """
    if not session_id:
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def recent_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """Most-recent chat sessions (started_at DESC). Read-only convenience."""
    limit = max(1, min(int(limit or 20), 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_meta(key: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM chat_state_meta WHERE key = ?",
            (key,),
        ).fetchone()
    return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_state_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def search_messages(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Full-text search via the GIN-indexed ``content_tsv`` column.

    Uses ``plainto_tsquery`` so callers can pass natural-language text
    (multi-word, no special operators required).
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 25), 200))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, tool_name, timestamp
            FROM chat_messages
            WHERE content_tsv @@ plainto_tsquery('english', ?)
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (q, limit),
        ).fetchall()
    return [dict(r) for r in rows]


__all__ = [
    "upsert_session",
    "insert_message",
    "insert_messages_batch",
    "session_exists",
    "message_count",
    "session_count",
    "get_session",
    "get_messages",
    "recent_sessions",
    "get_meta",
    "set_meta",
    "search_messages",
    # Shadow-write helpers (SessionDB hooks)
    "insert_session_if_missing",
    "end_session",
    "reopen_session",
    "update_system_prompt",
    "update_token_counts",
    "append_message_shadow",
    "replace_messages_shadow",
]
