"""Privacy-safe local session event recorder.

The recorder is intentionally local-first and best-effort. It writes structured
JSONL breadcrumbs that can be bundled for support without storing raw prompts,
answers, reasoning, PDFs, or file paths by default.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from elevate_constants import get_elevate_home

try:  # POSIX only; Windows falls back to best-effort unlocked writes.
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - platform fallback
    fcntl = None  # type: ignore


DEFAULT_RETENTION_DAYS = 7
DEFAULT_MAX_FILE_SIZE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_DIR_SIZE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_EVENT_BYTES = 16 * 1024
LOCK_TIMEOUT_SECONDS = 0.05

_FALSE_VALUES = {"0", "false", "no", "off"}
_SEQ = 0
_SEQ_LOCK = Lock()

_FORBIDDEN_KEYS = {
    "answer",
    "body",
    "content",
    "file_path",
    "html",
    "markdown",
    "message",
    "path",
    "pdf_text",
    "prompt",
    "raw",
    "reasoning",
    "stack",
    "text",
    "traceback",
}

_SAFE_NUMERIC_KEYS = {
    "api_calls",
    "duration_ms",
    "duration_seconds",
    "input_tokens",
    "message_count",
    "output_tokens",
    "reasoning_tokens",
    "replay_count",
    "retry_count",
    "tool_count",
}

_SAFE_STATE_KEYS = {
    "asset",
    "backend_build",
    "child_session_id",
    "component",
    "end_reason",
    "error_class",
    "error_message",
    "frontend_asset",
    "model",
    "parent_session_id",
    "provider",
    "source",
    "status",
    "task_id",
    "turn_id",
    "where",
}

_SAFE_BOOL_KEYS = {
    "attached",
    "child_replay_attached",
    "child_replay_running",
    "failed",
    "followup",
    "noop",
    "payload_truncated",
    "running",
    "success",
}

_SAFE_PAYLOAD_KEYS = _SAFE_NUMERIC_KEYS | _SAFE_STATE_KEYS | _SAFE_BOOL_KEYS

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"
)
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passcode|code|authorization)\s*[:=]\s*['\"]?([^'\"\s,;]+)"
)
_POSIX_PATH_RE = re.compile(
    r"(?<!:)(?<![A-Za-z0-9_.-])/(?:Users|home|tmp|private|var|opt|root|Volumes)/[^\s\"'<>]+"
)
_WINDOWS_PATH_RE = re.compile(
    r"\b[A-Za-z]:\\(?:Users|Temp|Windows|Program Files|Program Files \(x86\))\\[^\s\"'<>]+"
)
_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


def recorder_enabled() -> bool:
    """Return whether local recorder writes are enabled."""
    return os.getenv("ELEVATE_SESSION_RECORDER", "1").strip().lower() not in _FALSE_VALUES


def session_events_dir() -> Path:
    """Return the recorder directory under the current Elevate home."""
    return get_elevate_home() / "logs" / "session-events"


def _next_seq() -> int:
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        return _SEQ


def _base_report() -> dict[str, int]:
    return {
        "events_seen": 0,
        "events_written": 0,
        "events_dropped": 0,
        "malformed_lines": 0,
        "unknown_keys_dropped": 0,
        "forbidden_keys_dropped": 0,
        "strings_redacted": 0,
        "oversize_payloads_truncated": 0,
    }


def _coerce_str(value: Any, *, max_len: int = 512) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    if len(text) > max_len:
        text = text[: max_len - 1] + "..."
    return text


def _clean_event_name(value: Any) -> str:
    text = _coerce_str(value, max_len=96).strip().lower()
    return text if _EVENT_NAME_RE.match(text) else "diagnostics.event"


def _redact_paths(text: str) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        raw = match.group(0)
        name = Path(raw.rstrip(".,;:")).name or "[path]"
        suffix = raw[len(raw.rstrip(".,;:")) :]
        return f"[path:{name}]{suffix}"

    text = _POSIX_PATH_RE.sub(repl, text)
    text = _WINDOWS_PATH_RE.sub(repl, text)
    return text, count


def _redact_string(value: str, report: dict[str, int]) -> str:
    before = value
    try:
        from agent.redact import redact_sensitive_text

        value = redact_sensitive_text(value, force=True)
    except Exception:
        pass

    value = _EMAIL_RE.sub("[redacted-email]", value)
    value = _PHONE_RE.sub("[redacted-phone]", value)
    value = _SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}=[redacted-secret]", value)
    value, path_count = _redact_paths(value)
    if path_count:
        report["strings_redacted"] += path_count
    if value != before:
        report["strings_redacted"] += 1
    return value


def _sanitize_value(value: Any, report: dict[str, int]) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(_coerce_str(value), report)
    return _redact_string(_coerce_str(value), report)


def sanitize_payload(event_type: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, int]]:
    """Return an allowlisted, redacted payload and a redaction report."""
    report = _base_report()
    if not isinstance(payload, dict):
        return {}, report

    safe: dict[str, Any] = {}
    for key, value in payload.items():
        key_str = _coerce_str(key, max_len=96)
        lowered = key_str.lower()
        if lowered in _FORBIDDEN_KEYS:
            report["forbidden_keys_dropped"] += 1
            continue
        if lowered not in _SAFE_PAYLOAD_KEYS and not lowered.endswith("_hash"):
            report["unknown_keys_dropped"] += 1
            continue
        safe[key_str] = _sanitize_value(value, report)
    return safe, report


def _sanitize_envelope_field(value: Any, report: dict[str, int], *, max_len: int = 256) -> str | None:
    if value is None:
        return None
    text = _redact_string(_coerce_str(value, max_len=max_len), report)
    return text or None


def _attach_redaction_report(event: dict[str, Any], report: dict[str, int]) -> None:
    redaction = {
        key: report.get(key, 0)
        for key in (
            "unknown_keys_dropped",
            "forbidden_keys_dropped",
            "strings_redacted",
            "oversize_payloads_truncated",
        )
        if report.get(key, 0)
    }
    if redaction:
        event["redaction"] = redaction


def build_session_event(
    event_type: str,
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    source: str = "backend",
    component: str | None = None,
    parent_session_id: str | None = None,
    child_session_id: str | None = None,
    task_id: str | None = None,
    app_version: str | None = None,
    frontend_asset: str | None = None,
    backend_build: str | None = None,
    install_id_hash: str | None = None,
    account_id_hash: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Build a sanitized event envelope without writing it."""
    report = _base_report()
    clean_payload, payload_report = sanitize_payload(event_type, payload)
    for key, value in payload_report.items():
        report[key] = report.get(key, 0) + value

    event = {
        "schema_version": 1,
        "ts": time.time(),
        "ts_monotonic": time.monotonic(),
        "event_id": uuid.uuid4().hex,
        "seq": _next_seq(),
        "event": _clean_event_name(event_type),
        "severity": _coerce_str(severity or "info", max_len=24),
        "source": _coerce_str(source or "backend", max_len=64),
        "component": _coerce_str(component or source or "unknown", max_len=128),
        "pid": os.getpid(),
        "payload": clean_payload,
    }

    optional_fields = {
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "turn_id": turn_id,
        "task_id": task_id,
        "app_version": app_version,
        "frontend_asset": frontend_asset,
        "backend_build": backend_build,
        "install_id_hash": install_id_hash,
        "account_id_hash": account_id_hash,
    }
    for key, value in optional_fields.items():
        clean = _sanitize_envelope_field(value, report)
        if clean:
            event[key] = clean

    _attach_redaction_report(event, report)
    return event, report


def _json_line(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _ensure_dir(base_dir: Path) -> bool:
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(base_dir, 0o700)
        return True
    except OSError:
        return False


def _event_file(base_dir: Path, now: float | None = None) -> Path:
    stamp = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
    return base_dir / f"{stamp}.jsonl"


def _acquire_lock(lock_fh: Any, timeout: float = LOCK_TIMEOUT_SECONDS) -> bool:
    if fcntl is None:
        return True
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        except OSError:
            return False


def _release_lock(lock_fh: Any) -> None:
    if fcntl is None:
        return
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _rotate_if_needed(path: Path, max_file_size: int) -> None:
    try:
        if path.exists() and path.stat().st_size >= max_file_size:
            rotated = path.with_name(
                f"{path.stem}-{time.strftime('%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:6]}.jsonl"
            )
            os.replace(path, rotated)
            try:
                os.chmod(rotated, 0o600)
            except OSError:
                pass
    except OSError:
        pass


def _prune(base_dir: Path, *, retention_days: int, max_dir_size: int) -> None:
    try:
        files = sorted(
            [p for p in base_dir.glob("*.jsonl") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
        )
    except OSError:
        return

    cutoff = time.time() - max(0, retention_days) * 86400
    kept: list[Path] = []
    for path in files:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
            else:
                kept.append(path)
        except OSError:
            pass

    try:
        sized = [(p, p.stat().st_size) for p in kept if p.exists()]
    except OSError:
        return
    total = sum(size for _, size in sized)
    for path, size in sized:
        if total <= max_dir_size:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def _write_event_line(
    line: bytes,
    *,
    base_dir: Path,
    max_file_size: int,
    retention_days: int,
    max_dir_size: int,
) -> bool:
    if not _ensure_dir(base_dir):
        return False

    lock_path = base_dir / "session-events.lock"
    try:
        with open(lock_path, "a+b") as lock_fh:
            if not _acquire_lock(lock_fh):
                return False
            try:
                _prune(base_dir, retention_days=retention_days, max_dir_size=max_dir_size)
                target = _event_file(base_dir)
                _rotate_if_needed(target, max_file_size)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line)
                finally:
                    os.close(fd)
                try:
                    os.chmod(target, 0o600)
                except OSError:
                    pass
                return True
            finally:
                _release_lock(lock_fh)
    except OSError:
        return False


def record_session_event(
    event_type: str,
    session_id: str | None = None,
    turn_id: str | None = None,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    *,
    source: str = "backend",
    component: str | None = None,
    parent_session_id: str | None = None,
    child_session_id: str | None = None,
    task_id: str | None = None,
    app_version: str | None = None,
    frontend_asset: str | None = None,
    backend_build: str | None = None,
    install_id_hash: str | None = None,
    account_id_hash: str | None = None,
) -> bool:
    """Append one sanitized session event. Returns False on best-effort failure."""
    if not recorder_enabled():
        return False

    event, report = build_session_event(
        event_type,
        session_id=session_id,
        turn_id=turn_id,
        payload=payload,
        severity=severity,
        source=source,
        component=component,
        parent_session_id=parent_session_id,
        child_session_id=child_session_id,
        task_id=task_id,
        app_version=app_version,
        frontend_asset=frontend_asset,
        backend_build=backend_build,
        install_id_hash=install_id_hash,
        account_id_hash=account_id_hash,
    )

    line = _json_line(event)
    if len(line) > DEFAULT_MAX_EVENT_BYTES:
        event["payload"] = {"payload_truncated": True}
        report["oversize_payloads_truncated"] += 1
        _attach_redaction_report(event, report)
        line = _json_line(event)
    if len(line) > DEFAULT_MAX_EVENT_BYTES:
        return False

    ok = _write_event_line(
        line,
        base_dir=session_events_dir(),
        max_file_size=DEFAULT_MAX_FILE_SIZE_BYTES,
        retention_days=DEFAULT_RETENTION_DAYS,
        max_dir_size=DEFAULT_MAX_DIR_SIZE_BYTES,
    )
    return bool(ok)


def record_frontend_trace(payload: dict[str, Any]) -> bool:
    """Record a sanitized frontend event envelope."""
    if not isinstance(payload, dict):
        return False
    event_type = str(payload.get("event") or payload.get("type") or "frontend.event")
    return record_session_event(
        event_type,
        session_id=payload.get("session_id"),
        turn_id=payload.get("turn_id"),
        parent_session_id=payload.get("parent_session_id"),
        child_session_id=payload.get("child_session_id"),
        task_id=payload.get("task_id"),
        payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else payload,
        severity=str(payload.get("severity") or "info"),
        source="frontend",
        component=str(payload.get("component") or "frontend"),
    )


def _matches_event(
    event: dict[str, Any],
    *,
    session_id: str | None,
    child_session_id: str | None,
    task_id: str | None,
    include_lineage: bool,
) -> bool:
    wanted = {v for v in (session_id, child_session_id, task_id) if v}
    if not wanted:
        return True

    fields = {"session_id", "child_session_id", "task_id"}
    if include_lineage:
        fields.add("parent_session_id")

    for field in fields:
        if event.get(field) in wanted:
            return True
    payload = event.get("payload")
    if isinstance(payload, dict):
        for field in fields:
            if payload.get(field) in wanted:
                return True
    return False


def collect_session_events(
    session_id: str | None = None,
    *,
    child_session_id: str | None = None,
    task_id: str | None = None,
    since_seconds: int | float | None = 1800,
    include_lineage: bool = True,
) -> dict[str, Any]:
    """Collect sanitized recorder events and collection diagnostics."""
    report = _base_report()
    events: list[dict[str, Any]] = []
    base_dir = session_events_dir()
    cutoff = None if since_seconds is None else time.time() - float(since_seconds)
    try:
        files = sorted(base_dir.glob("*.jsonl"))
    except OSError:
        return {"events": events, "report": report}

    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = list(f)
        except OSError:
            continue
        for line in lines:
            report["events_seen"] += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                report["malformed_lines"] += 1
                continue
            if not isinstance(event, dict):
                report["malformed_lines"] += 1
                continue
            try:
                ts = float(event.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0
            if cutoff is not None and ts < cutoff:
                continue
            if not _matches_event(
                event,
                session_id=session_id,
                child_session_id=child_session_id,
                task_id=task_id,
                include_lineage=include_lineage,
            ):
                continue
            events.append(event)

    report["events_written"] = len(events)
    return {"events": events, "report": report}
