"""Opt-in JSONL diagnostics for context compaction.

The trace is intentionally metadata-only: counts, roles, token estimates,
session ids, and marker presence. It must not write message bodies.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Mapping

from elevate_constants import get_config_path, get_elevate_home


_TRACE_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "elevate_compaction_trace_context",
    default={},
)

_SUMMARY_PREFIX = "[CONTEXT COMPACTION"
_LEGACY_SUMMARY_PREFIX = "[CONTEXT SUMMARY]:"
_PLAN_PREFIX = (
    "[Your latest Plan panel plan was preserved across context compression"
)
_TODO_PREFIX = "[Your active task list was preserved across context compression]"
_SUMMARY_END_MARKER = "--- END OF CONTEXT SUMMARY"
_MESSAGE_TOP_LEVEL_KEYS = {
    "legacy_summary_marker_count",
    "max_content_chars",
    "merged_summary_prefix_count",
    "message_count",
    "plan_marker_count",
    "role_counts",
    "summary_marker_count",
    "synthetic_user_message_count",
    "tail_roles",
    "todo_marker_count",
    "tool_call_message_count",
    "tool_result_message_count",
    "total_content_chars",
}
_COMPRESSOR_TOP_LEVEL_KEYS = {
    "awaiting_real_usage_after_compression",
    "compression_count",
    "context_length",
    "ineffective_compression_count",
    "last_compress_aborted",
    "last_compression_rough_tokens",
    "last_compression_savings_pct",
    "last_prompt_tokens",
    "last_real_prompt_tokens",
    "last_summary_dropped_count",
    "last_summary_fallback_used",
    "summary_target_ratio",
    "tail_token_budget",
    "threshold_tokens",
}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def enabled() -> bool:
    env_value = os.environ.get("ELEVATE_COMPACTION_TRACE")
    if env_value is not None:
        return _truthy(env_value)

    try:
        import yaml

        path = get_config_path()
        if not path.exists():
            return False
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section, key in (
            ("diagnostics", "compaction_trace"),
            ("logging", "compaction_trace"),
        ):
            value = (cfg.get(section) or {}).get(key) if isinstance(cfg, dict) else None
            if value is not None:
                return _truthy(value)
    except Exception:
        return False
    return False


def trace_path() -> Path:
    override = os.environ.get("ELEVATE_COMPACTION_TRACE_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return get_elevate_home() / "logs" / "compaction-trace.jsonl"


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def current_trace_id() -> str | None:
    value = _TRACE_CONTEXT.get().get("trace_id")
    return str(value) if value else None


def current_trace_fields() -> dict[str, Any]:
    return dict(_TRACE_CONTEXT.get())


def set_trace_context(trace_id: str | None = None, **fields: Any) -> str:
    prior = dict(_TRACE_CONTEXT.get())
    next_context = dict(prior)
    next_context.update({k: v for k, v in fields.items() if v is not None})
    next_context["trace_id"] = trace_id or prior.get("trace_id") or new_trace_id()
    _TRACE_CONTEXT.set(next_context)
    return str(next_context["trace_id"])


@contextlib.contextmanager
def trace_scope(trace_id: str | None = None, **fields: Any) -> Iterator[str]:
    prior = dict(_TRACE_CONTEXT.get())
    next_context = dict(prior)
    next_context.update({k: v for k, v in fields.items() if v is not None})
    next_context["trace_id"] = trace_id or prior.get("trace_id") or new_trace_id()
    token = _TRACE_CONTEXT.set(next_context)
    try:
        yield str(next_context["trace_id"])
    finally:
        _TRACE_CONTEXT.reset(token)


def trace_event(event: str, **fields: Any) -> None:
    if not enabled():
        return

    payload: dict[str, Any] = {
        "event": event,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "monotonic": round(time.monotonic(), 6),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
    }
    payload.update(_TRACE_CONTEXT.get())
    payload.update({k: _safe_value(v) for k, v in fields.items() if v is not None})
    for source_key, allowed_keys in (
        ("messages", _MESSAGE_TOP_LEVEL_KEYS),
        ("compressor", _COMPRESSOR_TOP_LEVEL_KEYS),
    ):
        source = payload.get(source_key)
        if not isinstance(source, Mapping):
            continue
        for key in allowed_keys:
            if key not in payload and key in source:
                payload[key] = source[key]

    try:
        path = trace_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    except Exception:
        pass


def message_stats(messages: Any, *, tail: int = 6) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {"message_count": 0}

    roles: Counter[str] = Counter()
    content_lengths: list[int] = []
    summary_markers = 0
    legacy_summary_markers = 0
    plan_markers = 0
    todo_markers = 0
    synthetic_user_messages = 0
    merged_summary_prefixes = 0
    tool_call_messages = 0
    tool_result_messages = 0

    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        role = str(msg.get("role") or "")
        roles[role] += 1
        text = _content_text(msg.get("content"))
        stripped = text.strip()
        content_lengths.append(len(text))

        is_summary = stripped.startswith(_SUMMARY_PREFIX)
        is_legacy_summary = stripped.startswith(_LEGACY_SUMMARY_PREFIX)
        is_plan = stripped.startswith(_PLAN_PREFIX)
        is_todo = stripped.startswith(_TODO_PREFIX)
        is_synthetic = is_summary or is_legacy_summary or is_plan or is_todo

        summary_markers += int(is_summary)
        legacy_summary_markers += int(is_legacy_summary)
        plan_markers += int(is_plan)
        todo_markers += int(is_todo)
        synthetic_user_messages += int(role == "user" and is_synthetic)
        merged_summary_prefixes += int(
            _SUMMARY_PREFIX in stripped and _SUMMARY_END_MARKER in stripped
        )
        tool_call_messages += int(bool(msg.get("tool_calls")))
        tool_result_messages += int(role == "tool")

    tail_roles = [
        str(m.get("role") or "")
        for m in messages[-tail:]
        if isinstance(m, Mapping)
    ]

    return {
        "message_count": len(messages),
        "role_counts": dict(sorted(roles.items())),
        "tail_roles": tail_roles,
        "total_content_chars": sum(content_lengths),
        "max_content_chars": max(content_lengths, default=0),
        "summary_marker_count": summary_markers,
        "legacy_summary_marker_count": legacy_summary_markers,
        "plan_marker_count": plan_markers,
        "todo_marker_count": todo_markers,
        "synthetic_user_message_count": synthetic_user_messages,
        "merged_summary_prefix_count": merged_summary_prefixes,
        "tool_call_message_count": tool_call_messages,
        "tool_result_message_count": tool_result_messages,
    }


def compressor_stats(compressor: Any) -> dict[str, Any]:
    if compressor is None:
        return {}
    return {
        "context_length": _safe_int(getattr(compressor, "context_length", None)),
        "threshold_tokens": _safe_int(getattr(compressor, "threshold_tokens", None)),
        "tail_token_budget": _safe_int(getattr(compressor, "tail_token_budget", None)),
        "summary_target_ratio": getattr(compressor, "summary_target_ratio", None),
        "compression_count": _safe_int(getattr(compressor, "compression_count", None)),
        "ineffective_compression_count": _safe_int(
            getattr(compressor, "_ineffective_compression_count", None)
        ),
        "last_compression_savings_pct": getattr(
            compressor, "_last_compression_savings_pct", None
        ),
        "last_prompt_tokens": _safe_int(getattr(compressor, "last_prompt_tokens", None)),
        "last_real_prompt_tokens": _safe_int(
            getattr(compressor, "last_real_prompt_tokens", None)
        ),
        "last_compression_rough_tokens": _safe_int(
            getattr(compressor, "last_compression_rough_tokens", None)
        ),
        "awaiting_real_usage_after_compression": bool(
            getattr(compressor, "awaiting_real_usage_after_compression", False)
        ),
        "last_compress_aborted": bool(
            getattr(compressor, "_last_compress_aborted", False)
        ),
        "last_summary_fallback_used": bool(
            getattr(compressor, "_last_summary_fallback_used", False)
        ),
        "last_summary_dropped_count": _safe_int(
            getattr(compressor, "_last_summary_dropped_count", None)
        ),
    }


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif item.get("type") in {"image_url", "input_image", "image"}:
                    parts.append("[image]")
        return "\n".join(parts)
    return str(content)


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(v) for v in value]
    return str(value)
