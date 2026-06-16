"""SessionDB → Postgres shadow-write hooks.

Wire-up layer between ``elevate_state.SessionDB`` (still SQLite) and the
PG ``chat_sessions`` / ``chat_messages`` / ``chat_state_meta`` tables.

Every public function here is:

  * Best-effort. Any exception is swallowed and logged at DEBUG so a PG
    hiccup never breaks the SQLite write that already succeeded.
  * Gated by ``ELEVATE_DISABLE_PG_SHADOW=1`` for emergency rollback —
    flip the env var and restart the gateway; SessionDB falls back to
    SQLite-only with no other change.
  * Pre-serialised by the caller (matches the SQLite path's
    ``json.dumps`` of structured fields before the transaction). Keeps
    the shadow hooks free of policy decisions.

PG reads are controlled separately by ``ELEVATE_SESSIONDB_READ_FROM_PG`` in
``elevate_state``. Local SQLite writes remain live.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SHADOW_DISABLED_ENV = "ELEVATE_DISABLE_PG_SHADOW"


def _shadow_enabled() -> bool:
    val = os.environ.get(_SHADOW_DISABLED_ENV, "")
    return val.strip().lower() not in {"1", "true", "yes", "on"}


def _safe(fn, *args, **kwargs) -> None:
    if not _shadow_enabled():
        return
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        logger.debug("pg-shadow: %s failed: %s", fn.__name__, exc)


def shadow_insert_session(
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
    from elevate_cli.data.chat_sessions import insert_session_if_missing

    _safe(
        insert_session_if_missing,
        session_id, source,
        model=model,
        model_config_json=model_config_json,
        system_prompt=system_prompt,
        user_id=user_id,
        parent_session_id=parent_session_id,
        started_at=started_at,
    )


def shadow_end_session(session_id: str, ended_at: float, end_reason: str) -> None:
    from elevate_cli.data.chat_sessions import end_session

    _safe(end_session, session_id, ended_at, end_reason)


def shadow_reopen_session(session_id: str) -> None:
    from elevate_cli.data.chat_sessions import reopen_session

    _safe(reopen_session, session_id)


def shadow_update_system_prompt(session_id: str, system_prompt: str) -> None:
    from elevate_cli.data.chat_sessions import update_system_prompt

    _safe(update_system_prompt, session_id, system_prompt)


def shadow_update_compaction(session_id: str, summary, cursor: int) -> None:
    from elevate_cli.data.chat_sessions import update_compaction

    _safe(update_compaction, session_id, summary, cursor)


def shadow_update_token_counts(
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
    from elevate_cli.data.chat_sessions import update_token_counts

    _safe(
        update_token_counts,
        session_id,
        absolute=absolute,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        estimated_cost_usd=estimated_cost_usd,
        actual_cost_usd=actual_cost_usd,
        cost_status=cost_status,
        cost_source=cost_source,
        pricing_version=pricing_version,
        billing_provider=billing_provider,
        billing_base_url=billing_base_url,
        billing_mode=billing_mode,
        model=model,
        api_call_count=api_call_count,
    )


def shadow_append_message(
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
    from elevate_cli.data.chat_sessions import append_message_shadow

    _safe(
        append_message_shadow,
        session_id, role,
        content=content,
        tool_name=tool_name,
        tool_calls_json=tool_calls_json,
        tool_call_id=tool_call_id,
        token_count=token_count,
        finish_reason=finish_reason,
        reasoning=reasoning,
        reasoning_content=reasoning_content,
        reasoning_details_json=reasoning_details_json,
        codex_reasoning_items_json=codex_reasoning_items_json,
        codex_message_items_json=codex_message_items_json,
        platform_message_id=platform_message_id,
        client_message_id=client_message_id,
        timestamp=timestamp,
        num_tool_calls=num_tool_calls,
    )


def shadow_replace_messages(session_id: str, rows: List[Dict[str, Any]]) -> None:
    from elevate_cli.data.chat_sessions import replace_messages_shadow

    _safe(replace_messages_shadow, session_id, rows)


def shadow_set_meta(key: str, value: str) -> None:
    from elevate_cli.data.chat_sessions import set_meta

    _safe(set_meta, key, value)


__all__ = [
    "shadow_insert_session",
    "shadow_end_session",
    "shadow_reopen_session",
    "shadow_update_system_prompt",
    "shadow_update_compaction",
    "shadow_update_token_counts",
    "shadow_append_message",
    "shadow_replace_messages",
    "shadow_set_meta",
]
