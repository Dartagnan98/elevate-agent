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
import time
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
    "client_message_id",
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


def get_compression_tip(session_id: str) -> Optional[str]:
    """Walk the compression-continuation chain forward and return its tip.

    PG mirror of ``ElevateState.get_compression_tip`` (sessions are PG-backed
    post-cutover, so the SQLite walk would read stale rows). A compression
    continuation is a child session whose parent's ``end_reason='compression'``
    and which was created after the parent ended (``started_at >= ended_at``) —
    that second condition excludes delegate/branch children. Returns the latest
    continuation, or the input ``session_id`` when it is not part of a
    compression chain.
    """
    if not session_id:
        return session_id
    current = session_id
    with connect() as conn:
        # Bound the walk defensively — chains this deep are pathological.
        for _ in range(100):
            row = conn.execute(
                "SELECT id FROM chat_sessions "
                "WHERE parent_session_id = ? "
                "  AND started_at >= ("
                "      SELECT ended_at FROM chat_sessions "
                "      WHERE id = ? AND end_reason = 'compression'"
                "  ) "
                "ORDER BY started_at DESC LIMIT 1",
                (current, current),
            ).fetchone()
            if row is None:
                break
            current = row["id"] if not isinstance(row, (tuple, list)) else row[0]
    return current


def get_lineage_root(session_id: str) -> Optional[str]:
    """Walk parent_session_id backward to the logical root.

    ONLY folds compression/branch continuations into the parent's lineage. A
    SUBAGENT child is its own conversation — its parent link must NOT chain it
    up to the orchestrator, or opening the subagent redirects to the parent
    (and reports the parent's "chat" kind). Stop the walk at a subagent link.
    """
    if not session_id:
        return session_id
    current = session_id
    seen = {current}
    with connect() as conn:
        for _ in range(100):
            row = conn.execute(
                "SELECT parent_session_id, started_at FROM chat_sessions WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                return current
            if isinstance(row, (tuple, list)):
                parent_id, started_at = row[0], row[1]
            else:
                parent_id, started_at = row["parent_session_id"], row["started_at"]
            if not parent_id or parent_id in seen:
                return current
            parent = conn.execute(
                "SELECT ended_at, end_reason FROM chat_sessions WHERE id = ?",
                (parent_id,),
            ).fetchone()
            is_continuation = False
            if parent is not None:
                p_ended = parent["ended_at"] if not isinstance(parent, (tuple, list)) else parent[0]
                p_reason = parent["end_reason"] if not isinstance(parent, (tuple, list)) else parent[1]
                if p_reason == "compression" and p_ended is not None and started_at is not None and started_at >= p_ended:
                    is_continuation = True
                elif p_reason == "branched":
                    is_continuation = True
            if not is_continuation:
                # Subagent (or any non-continuation) link — current IS the root.
                return current
            seen.add(parent_id)
            current = parent_id
    return current


def infer_session_kind(session_id: str) -> str:
    """Infer the physical session kind from existing lineage fields."""
    if not session_id:
        return "chat"
    with connect() as conn:
        row = conn.execute(
            "SELECT id, source, parent_session_id, started_at FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return "chat"
        source = str(row["source"] or "")
        sid = str(row["id"] or "")
        if source == "cron" or sid.startswith("cron_"):
            return "cron"
        if sid.startswith(("bg_", "btw_")):
            return "background"
        parent_id = row["parent_session_id"]
        if not parent_id:
            return "chat"
        parent = conn.execute(
            "SELECT ended_at, end_reason FROM chat_sessions WHERE id = ?",
            (parent_id,),
        ).fetchone()
        if parent is not None:
            ended_at = parent["ended_at"]
            end_reason = parent["end_reason"]
            if end_reason == "compression" and ended_at is not None and row["started_at"] >= ended_at:
                return "compression"
            if end_reason == "branched":
                return "branch"
        return "subagent"


def resolve_canonical_session_identity(session_id: str) -> Dict[str, Any]:
    """Return the logical/root and active physical session ids for a target."""
    requested = session_id
    if not session_id:
        return {
            "requested_session_id": requested,
            "lineage_root_id": session_id,
            "active_session_id": session_id,
            "session_kind": "chat",
            "is_compression_tip": True,
        }
    root_id = get_lineage_root(session_id) or session_id
    active_id = get_compression_tip(root_id) or root_id
    return {
        "requested_session_id": requested,
        "lineage_root_id": root_id,
        "active_session_id": active_id,
        "session_kind": infer_session_kind(active_id),
        "is_compression_tip": active_id == session_id,
    }


def list_child_sessions(session_id: str) -> List[Dict[str, Any]]:
    """Return every physical descendant for a logical conversation lineage."""
    if not session_id:
        return []
    root_id = get_lineage_root(session_id) or session_id
    active_id = get_compression_tip(root_id) or root_id
    with connect() as conn:
        rows = conn.execute(
            """
            WITH RECURSIVE session_tree AS (
                SELECT *
                FROM chat_sessions
                WHERE id = ?
              UNION ALL
                SELECT child.*
                FROM chat_sessions child
                JOIN session_tree parent ON child.parent_session_id = parent.id
            )
            SELECT *
            FROM session_tree
            WHERE id != ?
            ORDER BY started_at ASC, id ASC
            """,
            (root_id, root_id),
        ).fetchall()
    children: List[Dict[str, Any]] = []
    for row in rows:
        child = dict(row)
        child["session_kind"] = infer_session_kind(str(child.get("id") or ""))
        child["lineage_root_id"] = root_id
        child["active_session_id"] = active_id
        child["is_active_session"] = child.get("id") == active_id
        children.append(child)
    return children


def delete_session(session_id: str) -> bool:
    """Delete one chat session row and its messages.

    Mirrors ``SessionDB.delete_session`` for the PG-backed session list: child
    sessions are orphaned so they remain independently accessible, while
    messages cascade through the FK.
    """
    if not session_id:
        return False
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        count = row[0] if isinstance(row, (tuple, list)) else row["count"]
        if int(count or 0) == 0:
            return False
        conn.execute(
            "UPDATE chat_sessions SET parent_session_id = NULL "
            "WHERE parent_session_id = ?",
            (session_id,),
        )
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        conn.commit()
    return True


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
    client_message_id: Optional[str] = None,
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
            "platform_message_id, client_message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, role, content, tool_call_id, tool_calls_json,
                tool_name, timestamp, token_count, finish_reason,
                reasoning, reasoning_content, reasoning_details_json,
                codex_reasoning_items_json, codex_message_items_json,
                platform_message_id, client_message_id,
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
                    r.get("client_message_id"),
                )
                for r in rows
            ]
            conn.executemany(
                "INSERT INTO chat_messages "
                "(session_id, role, content, tool_call_id, tool_calls, "
                "tool_name, timestamp, token_count, finish_reason, "
                "reasoning, reasoning_content, reasoning_details, "
                "codex_reasoning_items, codex_message_items, "
                "platform_message_id, client_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


def active_session_count(window_sec: int) -> int:
    """Count recently active open sessions without constructing SessionDB."""
    cutoff = time.time() - max(1, int(window_sec or 1))
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_sessions s
            WHERE s.ended_at IS NULL
              AND (
                s.parent_session_id IS NULL
                OR EXISTS (
                    SELECT 1 FROM chat_sessions p
                    WHERE p.id = s.parent_session_id
                      AND p.end_reason = 'branched'
                      AND s.started_at >= p.ended_at
                )
              )
              AND COALESCE(
                (SELECT MAX(m.timestamp) FROM chat_messages m WHERE m.session_id = s.id),
                s.started_at
              ) >= ?
            """,
            (cutoff,),
        ).fetchone()
    return int(row[0]) if row else 0


def list_session_summaries(
    *,
    limit: int = 20,
    offset: int = 0,
    source: str | None = None,
    exclude_sources: List[str] | None = None,
    include_children: bool = False,
) -> List[Dict[str, Any]]:
    """Slim dashboard list reader for sidebar/session cards.

    Selects only fields rendered by the dashboard shell and computes preview
    + last_active in PG. This keeps polling endpoints off the legacy SQLite
    SessionDB initializer while the rich reader remains available for full
    details.
    """
    limit = max(1, min(int(limit or 20), 200))
    offset = max(0, int(offset or 0))
    where_clauses: List[str] = []
    params: List[Any] = []

    if not include_children:
        where_clauses.append(
            "(s.parent_session_id IS NULL"
            " OR EXISTS (SELECT 1 FROM chat_sessions p"
            "            WHERE p.id = s.parent_session_id"
            "            AND p.end_reason = 'branched'"
            "            AND s.started_at >= p.ended_at))"
        )
        # Hide phantom empties: a session row that never received a message and
        # never earned a title is a draft the app eagerly minted (session.create
        # builds the row before the user types). It shouldn't clutter the
        # sidebar as a "General session" with no chat. Once a message lands
        # (message_count > 0) or it's titled, it shows.
        where_clauses.append("(s.message_count > 0 OR s.title IS NOT NULL)")
    if source:
        where_clauses.append("s.source = ?")
        params.append(source)
    if exclude_sources:
        placeholders = ",".join("?" for _ in exclude_sources)
        where_clauses.append(f"s.source NOT IN ({placeholders})")
        params.extend(exclude_sources)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([limit, offset])

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                s.id,
                s.source,
                s.user_id,
                s.model,
                s.parent_session_id,
                s.started_at,
                s.ended_at,
                s.end_reason,
                s.message_count,
                s.tool_call_count,
                s.input_tokens,
                s.output_tokens,
                s.cache_read_tokens,
                s.cache_write_tokens,
                s.reasoning_tokens,
                s.title,
                s.api_call_count,
                COALESCE(
                    (SELECT SUBSTRING(REGEXP_REPLACE(m.content, E'[\\n\\r]', ' ', 'g'), 1, 63)
                     FROM chat_messages m
                     WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                     ORDER BY m.timestamp, m.id LIMIT 1),
                    ''
                ) AS preview,
                COALESCE(
                    (SELECT MAX(m2.timestamp) FROM chat_messages m2 WHERE m2.session_id = s.id),
                    s.started_at
                ) AS last_active
            FROM chat_sessions s
            {where_sql}
            ORDER BY s.started_at DESC, s.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
    sessions = [dict(r) for r in rows]
    if include_children:
        for s in sessions:
            ident = resolve_canonical_session_identity(str(s.get("id") or ""))
            s.update(ident)
        return sessions

    projected: List[Dict[str, Any]] = []
    for s in sessions:
        ident = resolve_canonical_session_identity(str(s.get("id") or ""))
        active_id = ident.get("active_session_id")
        if active_id and active_id != s.get("id"):
            active = get_session(str(active_id))
            if active:
                merged = dict(s)
                for key in (
                    "id", "ended_at", "end_reason", "message_count",
                    "tool_call_count", "title", "model", "system_prompt",
                ):
                    if key in active:
                        merged[key] = active[key]
                with connect() as conn:
                    meta = conn.execute(
                        """
                        SELECT
                          COALESCE(
                            (SELECT SUBSTRING(REGEXP_REPLACE(m.content, E'[\\n\\r]', ' ', 'g'), 1, 63)
                             FROM chat_messages m
                             WHERE m.session_id = ? AND m.role = 'user' AND m.content IS NOT NULL
                             ORDER BY m.timestamp, m.id LIMIT 1),
                            ''
                          ) AS preview,
                          COALESCE(
                            (SELECT MAX(m2.timestamp) FROM chat_messages m2 WHERE m2.session_id = ?),
                            ?
                          ) AS last_active
                        """,
                        (active_id, active_id, active.get("started_at")),
                    ).fetchone()
                if meta:
                    merged["preview"] = meta["preview"]
                    merged["last_active"] = meta["last_active"]
                s = merged
        s.update(ident)
        projected.append(s)
    return projected


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


def get_messages_for_sessions(session_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch raw messages for multiple sessions in insertion order."""
    ids = [session_id for session_id in session_ids if session_id]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM chat_messages WHERE session_id IN ({placeholders}) ORDER BY id",
            tuple(ids),
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
            WHERE content_tsv @@ plainto_tsquery('simple', ?)
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
    "active_session_count",
    "get_compression_tip",
    "get_lineage_root",
    "infer_session_kind",
    "resolve_canonical_session_identity",
    "list_child_sessions",
    "list_session_summaries",
    "get_session",
    "get_messages",
    "get_messages_for_sessions",
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
