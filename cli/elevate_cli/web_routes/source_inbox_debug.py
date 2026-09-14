"""Debug payload helpers for source-inbox routes."""

from typing import Any


def source_inbox_counts(payload: dict[str, Any]) -> dict[str, Any]:
    def _len(key: str) -> int:
        value = payload.get(key)
        return len(value) if isinstance(value, list) else 0

    return {
        "sources": _len("sources"),
        "profiles": _len("profiles"),
        "threads": _len("threads"),
        "drafts": _len("drafts"),
        "skippedDrafts": _len("skippedDrafts"),
        "privateSearchBuyers": _len("privateSearchBuyers"),
        "recordCounts": payload.get("recordCounts") or {},
        "hiddenCounts": payload.get("hiddenCounts") or {},
    }


def with_source_inbox_debug(
    payload: dict[str, Any],
    *,
    read_path: str,
    fallback_error: Exception | None = None,
) -> dict[str, Any]:
    debug: dict[str, Any] = {
        "readPath": read_path,
        "fallback": read_path == "jsonl",
        "counts": source_inbox_counts(payload),
    }
    if fallback_error is not None:
        debug["fallbackError"] = type(fallback_error).__name__
        debug["fallbackErrorCode"] = "source_inbox_db_read_failed"
    return {**payload, "debug": debug}
