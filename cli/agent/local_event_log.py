"""Opt-in append-only JSONL ledgers for local backend diagnostics.

These logs are intentionally metadata-only. They record chronology, ids,
counts, roles, sizes, and tool/session state transitions without dumping raw
user messages, prompts, tool arguments, or tool outputs.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from elevate_constants import get_config_path, get_elevate_home

try:
    from agent.compaction_trace import current_trace_fields, message_stats
except Exception:  # pragma: no cover - import safety during early startup
    current_trace_fields = None

    def message_stats(messages: Any, *, tail: int = 6) -> dict[str, Any]:
        return {"message_count": len(messages) if isinstance(messages, list) else 0}


_SESSION_LOG = "session-events"
_TOOL_LOG = "tool-events"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=8)
def enabled(kind: str = "") -> bool:
    normalized = str(kind or "").strip().lower().replace("-", "_")
    env_names = []
    if normalized.startswith("session"):
        env_names.append("ELEVATE_SESSION_EVENTS")
    elif normalized.startswith("tool"):
        env_names.append("ELEVATE_TOOL_EVENTS")
    env_names.extend(("ELEVATE_JSONL_TRACE", "ELEVATE_EVENT_TRACE"))
    for name in env_names:
        value = os.environ.get(name)
        if value is not None:
            return _truthy(value)

    try:
        import yaml

        path = get_config_path()
        if not path.exists():
            return False
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        diagnostics = cfg.get("diagnostics") if isinstance(cfg, dict) else {}
        logging_cfg = cfg.get("logging") if isinstance(cfg, dict) else {}
        keys = ["jsonl_trace", "event_trace", "local_event_log"]
        if normalized.startswith("session"):
            keys.insert(0, "session_events")
        elif normalized.startswith("tool"):
            keys.insert(0, "tool_events")
        for section in (diagnostics, logging_cfg):
            if not isinstance(section, Mapping):
                continue
            for key in keys:
                if key in section:
                    return _truthy(section.get(key))
    except Exception:
        return False
    return False


def log_dir() -> Path:
    override = os.environ.get("ELEVATE_EVENT_TRACE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return get_elevate_home() / "logs"


def log_path(kind: str) -> Path:
    normalized = str(kind or "").strip().lower().replace("_", "-")
    if normalized.startswith("session"):
        override = os.environ.get("ELEVATE_SESSION_EVENTS_PATH", "").strip()
        filename = "session-events.jsonl"
    elif normalized.startswith("tool"):
        override = os.environ.get("ELEVATE_TOOL_EVENTS_PATH", "").strip()
        filename = "tool-events.jsonl"
    else:
        override = ""
        filename = f"{normalized or 'events'}.jsonl"
    if override:
        return Path(override).expanduser()
    return log_dir() / filename


def log_session_event(event: str, **fields: Any) -> None:
    _write_event(_SESSION_LOG, event, fields)


def log_tool_event(event: str, **fields: Any) -> None:
    _write_event(_TOOL_LOG, event, fields)


def _write_event(kind: str, event: str, fields: Mapping[str, Any]) -> None:
    if not enabled(kind):
        return
    payload: dict[str, Any] = {
        "event": event,
        "event_id": uuid.uuid4().hex[:16],
        "kind": kind,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "monotonic": round(time.monotonic(), 6),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
    }
    try:
        if current_trace_fields:
            trace_fields = current_trace_fields()
            if trace_fields.get("trace_id"):
                payload["trace_id"] = trace_fields.get("trace_id")
            if trace_fields.get("trigger"):
                payload.setdefault("trigger", trace_fields.get("trigger"))
            if trace_fields.get("source"):
                payload.setdefault("source", trace_fields.get("source"))
    except Exception:
        pass
    payload.update({k: _safe_value(v) for k, v in fields.items() if v is not None})
    try:
        path = log_path(kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    except Exception:
        pass


def payload_stats(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"payload_type": type(payload).__name__, "payload_present": payload is not None}
    keys = sorted(str(k) for k in payload.keys())
    stats: dict[str, Any] = {
        "payload_keys": keys,
        "payload_key_count": len(keys),
        "payload_json_chars": _json_len(payload),
    }
    text = payload.get("text") or payload.get("message")
    if isinstance(text, str):
        stats["payload_text_chars"] = len(text)
        label = _status_text_label(text)
        if label:
            stats["payload_text_label"] = label
    kind = payload.get("kind")
    if isinstance(kind, str):
        stats["payload_kind"] = kind
    if isinstance(payload.get("messages"), list):
        stats["payload_message_count"] = len(payload["messages"])
    if isinstance(payload.get("replay_events"), list):
        stats["payload_replay_event_count"] = len(payload["replay_events"])
    if isinstance(payload.get("running_tools"), list):
        stats["payload_running_tool_count"] = len(payload["running_tools"])
    if isinstance(payload.get("usage"), Mapping):
        stats["payload_usage_keys"] = sorted(str(k) for k in payload["usage"].keys())
    return stats


def tool_arg_stats(args: Any) -> dict[str, Any]:
    if not isinstance(args, Mapping):
        return {"arg_type": type(args).__name__, "arg_json_chars": _json_len(args)}
    keys = sorted(str(k) for k in args.keys())
    return {
        "arg_keys": keys,
        "arg_key_count": len(keys),
        "arg_json_chars": _json_len(args),
        "arg_types": {
            str(k): type(v).__name__
            for k, v in sorted(args.items(), key=lambda item: str(item[0]))
        },
        "has_command_arg": "command" in args,
        "has_path_arg": any(k in args for k in ("path", "file", "filename")),
        "has_session_id_arg": "session_id" in args,
    }


def tool_result_stats(result: Any) -> dict[str, Any]:
    text = _content_text(result)
    stats = {
        "result_type": type(result).__name__,
        "result_chars": len(text),
        "result_line_count": text.count("\n") + 1 if text.strip() else 0,
        "result_json_chars": _json_len(result),
        "result_multimodal": isinstance(result, (list, tuple, dict)) and not isinstance(result, str),
    }
    if isinstance(result, list):
        stats["result_block_count"] = len(result)
        stats["result_block_types"] = [
            str(item.get("type") or type(item).__name__)
            for item in result[:20]
            if isinstance(item, Mapping)
        ]
    elif isinstance(result, Mapping):
        stats["result_keys"] = sorted(str(k) for k in result.keys())[:30]
    return stats


def message_event_stats(messages: Any) -> dict[str, Any]:
    return message_stats(messages)


def _status_text_label(text: str) -> str:
    lowered = text.lower()
    if "compacting context" in lowered:
        return "compacting_context"
    if "session compacted" in lowered:
        return "session_compacted"
    if "thinking" in lowered:
        return "thinking"
    return ""


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
                elif item.get("type") in {"image_url", "input_image", "image"}:
                    parts.append("[image]")
        return "\n".join(parts)
    if isinstance(value, Mapping):
        text = value.get("text") or value.get("content")
        if isinstance(text, str):
            return text
        return json.dumps({str(k): type(v).__name__ for k, v in value.items()}, sort_keys=True)
    return str(value)


def _json_len(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return len(str(value))


def _safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(v) for v in value]
    return str(value)
