"""Shared helpers for classifying tool result payloads."""

from __future__ import annotations

import json
from typing import Any


FILE_MUTATING_TOOL_NAMES = frozenset({"write_file", "patch"})


def file_mutation_result_landed(tool_name: str, result: Any) -> bool:
    """Return True when a file mutation result proves the write landed."""
    if tool_name not in FILE_MUTATING_TOOL_NAMES or not isinstance(result, str):
        return False
    try:
        data = json.loads(result.strip())
    except Exception:
        return False
    if not isinstance(data, dict) or data.get("error"):
        return False
    if tool_name == "write_file":
        return "bytes_written" in data
    if tool_name == "patch":
        return data.get("success") is True
    return False


def classify_tool_failure(tool_name: str, result: Any) -> tuple[bool, str]:
    """Classify a tool result from its top-level outcome fields."""
    if result is None or file_mutation_result_landed(tool_name, result):
        return False, ""
    if not isinstance(result, str):
        return False, ""

    try:
        data = json.loads(result.strip())
    except Exception:
        data = None

    if tool_name in {"terminal", "process"}:
        if isinstance(data, dict):
            exit_code = data.get("exit_code")
            if exit_code is not None and exit_code != 0:
                return True, f" [exit {exit_code}]"
        # Some terminal/process failures do not include an exit code. Let the
        # shared top-level error/status checks classify those instead of
        # silently marking them successful. A process wait/poll result with a
        # non-zero exit is the terminal command's authoritative outcome too.

    if isinstance(data, dict):
        if (
            tool_name == "memory"
            and data.get("success") is False
            and "exceed the limit" in str(data.get("error") or "")
        ):
            return True, " [full]"
        status = str(data.get("status") or "").lower()
        if (
            data.get("success") is False
            or data.get("error")
            or status in {
                "cancelled",
                "canceled",
                "error",
                "failed",
                "interrupted",
                "killed",
            }
        ):
            return True, " [error]"
        return False, ""

    plain = result.lstrip().lower()
    if plain.startswith((
        "error:",
        "error ",
        "[tool execution cancelled",
        "[tool execution skipped",
        "tool execution failed:",
        "tool execution failed ",
    )):
        return True, " [error]"
    return False, ""
