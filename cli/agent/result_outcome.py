"""Canonical success/failure checks for ``AIAgent`` result dictionaries."""

from __future__ import annotations

from typing import Any


_EXPLICIT_CONTEXT_OVERFLOW_MARKERS = (
    "context_length_exceeded",
    "context length exceeded",
    "context window exceeded",
    "context window exceeds limit",
    "maximum context length",
    "maximum context window",
    "maximum model length",
    "prompt is too long",
    "prompt exceeds max length",
    "input is too long",
    "exceeds the max_model_len",
    "exceeds the maximum number of input tokens",
)


def agent_result_context_overflow(result: Any) -> bool:
    """Return whether replaying this failed turn would recreate overflow."""
    if not isinstance(result, dict):
        return False
    if result.get("compression_exhausted") is True:
        return True
    error_text = agent_result_error(result, default="").strip().lower()
    return bool(
        error_text
        and any(marker in error_text for marker in _EXPLICIT_CONTEXT_OVERFLOW_MARKERS)
    )


def agent_result_needs_input(result: Any) -> bool:
    """Return whether a turn stopped to ask the user for required input."""
    if not isinstance(result, dict):
        return False
    final_response = result.get("final_response")
    return bool(
        result.get("needs_input") is True
        and result.get("completed") is False
        and result.get("failed") is not True
        and result.get("partial") is True
        and result.get("pending") is not True
        and not result.get("interrupted")
        and not result.get("error")
        and isinstance(final_response, str)
        and final_response.strip()
    )


def agent_result_pending(result: Any) -> bool:
    """Return whether a turn stopped with explicitly tracked async work.

    ``partial=True`` by itself is not pending: provider truncations and other
    incomplete failures use that flag too.  A pending turn must carry the
    runtime's explicit pending sentinel and at least one concrete tool
    obligation, while remaining free of failure/interruption markers.
    """
    if not isinstance(result, dict):
        return False
    obligations = result.get("pending_tool_obligations")
    return bool(
        result.get("pending") is True
        and result.get("completed") is False
        and result.get("failed") is not True
        and result.get("partial") is True
        and not result.get("interrupted")
        and not result.get("error")
        and isinstance(obligations, list)
        and obligations
        and all(
            isinstance(item, dict)
            and str(item.get("status") or "").strip().lower() == "pending"
            for item in obligations
        )
    )


def agent_result_succeeded(result: Any) -> bool:
    """Return whether an agent result represents a completed successful turn."""
    final_response = result.get("final_response") if isinstance(result, dict) else None
    return bool(
        isinstance(result, dict)
        and isinstance(final_response, str)
        and final_response.strip()
        and not result.get("interrupted")
        and not result.get("failed")
        and not result.get("partial")
        and not result.get("error")
        and result.get("completed") is not False
    )


def agent_result_error(result: Any, default: str = "Agent run did not complete.") -> str:
    """Return the most useful user-visible text for an unsuccessful result."""
    if not isinstance(result, dict):
        return default
    return str(result.get("error") or result.get("final_response") or default)
