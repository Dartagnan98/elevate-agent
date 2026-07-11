"""Canonical success/failure checks for ``AIAgent`` result dictionaries."""

from __future__ import annotations

from typing import Any


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
