"""Per-turn usage helpers for gateway/model runs.

The canonical storage is Elevate's existing state.db. Provider/OAuth dashboards
can include usage from Claude Code, side panels, web apps, or other clients on
the same account; these rows record what Elevate itself did for each gateway
turn.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_TOOL_TOKEN_CACHE: dict[tuple[str, ...], int] = {}


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_tool_schema_tokens_for_defs(tool_defs: list[dict[str, Any]] | None) -> int:
    if not tool_defs:
        return 0
    try:
        from agent.model_metadata import estimate_request_tokens_rough

        return int(estimate_request_tokens_rough([], tools=tool_defs))
    except Exception as exc:
        logger.debug("Failed to estimate selected tool schema tokens: %s", exc)
        return 0


def _safe_tool_schema_tokens_for_toolsets(toolsets: Iterable[str] | None) -> int:
    names = tuple(sorted(str(name) for name in (toolsets or []) if str(name)))
    if not names:
        return 0
    cached = _TOOL_TOKEN_CACHE.get(names)
    if cached is not None:
        return cached
    try:
        from model_tools import get_tool_definitions

        tokens = _safe_tool_schema_tokens_for_defs(
            get_tool_definitions(enabled_toolsets=list(names), quiet_mode=True)
        )
    except Exception as exc:
        logger.debug("Failed to estimate configured tool schema tokens: %s", exc)
        tokens = 0
    _TOOL_TOKEN_CACHE[names] = tokens
    return tokens


def _session_db_from_path(db_path: Path | None):
    from elevate_state import SessionDB

    return SessionDB(db_path=db_path) if db_path is not None else SessionDB()


def build_turn_usage_row(
    *,
    agent_result: dict[str, Any],
    session_id: str | None = None,
    session_key: str | None = None,
    message_id: str | None = None,
    source: str | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any] | None:
    """Build a safe metadata-only turn_usage row.

    Never includes user message text, assistant response text, tool arguments, or
    secret-bearing payloads. Tool calls are stored by tool name only.
    """
    if not isinstance(agent_result, dict):
        return None

    selected_toolsets = agent_result.get("selected_toolsets") or []
    requested_toolsets = agent_result.get("requested_toolsets") or []
    configured_toolsets = agent_result.get("configured_toolsets") or []
    tools = agent_result.get("tools") or []
    tool_calls = agent_result.get("tool_calls") or []

    selected_schema_tokens = _safe_tool_schema_tokens_for_defs(tools if isinstance(tools, list) else [])
    configured_schema_tokens = _safe_tool_schema_tokens_for_toolsets(configured_toolsets)
    savings_tokens = max(0, configured_schema_tokens - selected_schema_tokens)
    savings_pct = (
        (savings_tokens / configured_schema_tokens) * 100.0
        if configured_schema_tokens > 0
        else None
    )

    resolved_session_id = agent_result.get("session_id") or session_id or None
    status = agent_result.get("status") or ("failed" if agent_result.get("failed") else "ok")

    return {
        "timestamp": time.time(),
        "session_id": resolved_session_id,
        "session_key": session_key or "",
        "message_id": message_id or "",
        "source": source or "",
        "provider": agent_result.get("provider") or "",
        "model": agent_result.get("model") or "",
        "gateway_tool_profile": agent_result.get("gateway_tool_profile") or "",
        "gateway_tool_profile_reason": agent_result.get("gateway_tool_profile_reason") or "",
        "selected_toolsets": _json_dumps(selected_toolsets),
        "requested_toolsets": _json_dumps(requested_toolsets),
        "configured_toolsets": _json_dumps(configured_toolsets),
        "loaded_tool_count": len(tools) if isinstance(tools, list) else 0,
        "selected_tool_schema_tokens": selected_schema_tokens,
        "configured_tool_schema_tokens": configured_schema_tokens,
        "estimated_tool_schema_savings_tokens": savings_tokens,
        "estimated_tool_schema_savings_pct": savings_pct,
        "input_tokens": _as_int(agent_result.get("input_tokens")),
        "output_tokens": _as_int(agent_result.get("output_tokens")),
        "total_tokens": _as_int(agent_result.get("total_tokens")),
        "cache_read_tokens": _as_int(agent_result.get("cache_read_tokens")),
        "cache_write_tokens": _as_int(agent_result.get("cache_write_tokens")),
        "reasoning_tokens": _as_int(agent_result.get("reasoning_tokens")),
        "api_calls": _as_int(agent_result.get("api_calls")),
        "estimated_cost_usd": _as_float(agent_result.get("estimated_cost_usd")),
        "cost_status": agent_result.get("cost_status") or "",
        "cost_source": agent_result.get("cost_source") or "",
        "latency_ms": _as_int(latency_ms),
        "tool_calls": _json_dumps([str(name) for name in tool_calls] if isinstance(tool_calls, list) else []),
        "status": str(status),
        "error_type": str(agent_result.get("error_type") or ""),
    }


def record_gateway_turn(
    *,
    agent_result: dict[str, Any],
    session_id: str | None = None,
    session_key: str | None = None,
    message_id: str | None = None,
    source: str | None = None,
    latency_ms: int | None = None,
    session_db: Any | None = None,
    db_path: Path | None = None,
) -> int | None:
    """Persist one Elevate gateway turn into the existing state DB."""
    row = build_turn_usage_row(
        agent_result=agent_result,
        session_id=session_id,
        session_key=session_key,
        message_id=message_id,
        source=source,
        latency_ms=latency_ms,
    )
    if row is None:
        return None

    owns_db = False
    db = session_db
    try:
        if db is None:
            db = _session_db_from_path(db_path)
            owns_db = True
        return db.record_turn_usage(row)
    except Exception as exc:
        logger.debug("Failed to write usage ledger row: %s", exc)
        return None
    finally:
        if owns_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def recent_turns(limit: int = 20, session_db: Any | None = None, db_path: Path | None = None) -> list[dict[str, Any]]:
    owns_db = False
    db = session_db
    try:
        if db is None:
            db = _session_db_from_path(db_path)
            owns_db = True
        return db.recent_turn_usage(limit=limit)
    finally:
        if owns_db and db is not None:
            try:
                db.close()
            except Exception:
                pass
