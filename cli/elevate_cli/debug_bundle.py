"""Create privacy-safe, correlation-scoped Elevate support bundles.

Unlike ``elevate debug share``, this command never includes raw logs and never
uploads anything.  The archive contains only allowlisted runtime identity,
bounded local route health, and already-sanitized session-recorder events.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from elevate_constants import get_elevate_home


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9 ._+:/-]{1,128}$")
_SAFE_EVENT_LABEL_RE = re.compile(r"^[A-Za-z0-9._+:/-]{1,128}$")
_SAFE_METRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SAFE_STATUS_FIELDS = {
    "active_sessions",
    "config_version",
    "gateway_running",
    "gateway_state",
    "latest_config_version",
    "version",
}
_SAFE_EVENT_ENVELOPE_KEYS = {
    "account_id_hash",
    "app_version",
    "backend_build",
    "child_session_id",
    "component",
    "correlation_id",
    "event",
    "event_id",
    "frontend_asset",
    "install_id_hash",
    "parent_session_id",
    "schema_version",
    "seq",
    "session_id",
    "severity",
    "source",
    "task_id",
    "ts",
    "ts_monotonic",
    "turn_id",
}
_SAFE_EVENT_PAYLOAD_IDS = {
    "assistant_message_id",
    "child_session_id",
    "correlation_id",
    "message_id",
    "parent_session_id",
    "request_id",
    "task_id",
    "tool_id",
    "turn_id",
    "user_message_id",
}
_SAFE_EVENT_PAYLOAD_LABELS = {
    "end_reason",
    "error_class",
    "friction_kind",
    "kind",
    "model",
    "outcome",
    "provider",
    "source",
    "stage",
    "status",
    "tool_name",
    "where",
}


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_id(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(
            f"{label} must be 1-128 characters using only letters, numbers, '.', '_' or '-'"
        )
    return text


def _safe_sha256(value: object) -> str | None:
    text = str(value or "").strip().lower()
    return text if _SHA256_RE.fullmatch(text) else None


def _safe_label(value: object, *, max_len: int = 128) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > max_len or not _SAFE_LABEL_RE.fullmatch(text):
        return None
    return text


def _safe_event_label(value: object) -> str | None:
    """Accept code-like event labels, never free-form human text."""
    text = str(value or "").strip()
    return text if _SAFE_EVENT_LABEL_RE.fullmatch(text) else None


def _safe_metric_key(value: object) -> str | None:
    text = str(value or "").strip()
    return text if _SAFE_METRIC_KEY_RE.fullmatch(text) else None


def _parse_since(value: object) -> int | None:
    text = str(value or "30m").strip().lower()
    if text == "all":
        return None
    match = re.fullmatch(r"([1-9][0-9]*)([smhd]?)", text)
    if not match:
        raise ValueError("--last must be a positive duration such as 600, 30m, 2h, 1d, or all")
    amount = int(match.group(1))
    multiplier = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return amount * multiplier


def _candidate_identity(receipt_path: Path | None) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "app_bundle_name": _safe_label(os.getenv("ELEVATE_APP_BUNDLE_NAME")),
        "app_version": _safe_label(os.getenv("ELEVATE_APP_VERSION"), max_len=64),
        "architecture": _safe_label(
            os.getenv("ELEVATE_APP_ARCHITECTURE") or platform.machine(), max_len=32
        ),
        "candidate_binding": "source_receipt_only",
        "candidate_id": _safe_sha256(os.getenv("ELEVATE_CANDIDATE_ID")),
        "release_channel": _safe_label(os.getenv("ELEVATE_RELEASE_CHANNEL"), max_len=32),
        "source_receipt_id": _safe_sha256(os.getenv("ELEVATE_SOURCE_RECEIPT_ID")),
    }
    path = receipt_path or (
        Path(os.environ["ELEVATE_CANDIDATE_RECEIPT"])
        if os.getenv("ELEVATE_CANDIDATE_RECEIPT")
        else None
    )
    if path is None:
        return identity
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("candidate receipt must contain a JSON object")
    release = data.get("release") if isinstance(data.get("release"), dict) else {}
    profile = release.get("profile") if isinstance(release.get("profile"), dict) else {}
    candidate_id = _safe_sha256(data.get("candidate_id"))
    source_id = _safe_sha256(data.get("source_receipt_id"))
    if not candidate_id or not source_id:
        raise ValueError("candidate receipt is missing valid candidate/source receipt IDs")
    receipt_identity = {
        "app_bundle_name": _safe_label(profile.get("appBundleName")),
        "app_version": _safe_label(release.get("version"), max_len=64),
        "release_channel": _safe_label(release.get("channel"), max_len=32),
        "source_receipt_id": source_id,
    }
    mismatches = [
        key
        for key, receipt_value in receipt_identity.items()
        if identity.get(key) is not None and identity.get(key) != receipt_value
    ]
    if mismatches:
        raise ValueError(
            "candidate receipt does not match running metadata: " + ", ".join(mismatches)
        )
    runtime_fields_present = all(identity.get(key) is not None for key in receipt_identity)
    identity.update(
        {
            **receipt_identity,
            "candidate_binding": (
                "supplied_receipt_runtime_metadata_match"
                if runtime_fields_present
                else "supplied_receipt_runtime_metadata_missing"
            ),
            "candidate_id": candidate_id,
            "candidate_receipt_sha256": _sha256_bytes(raw),
        }
    )
    return identity


def _dashboard_port() -> int | None:
    raw = str(os.getenv("ELEVATE_DASHBOARD_PORT") or "").strip()
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _route_health(port: int | None, timeout: float = 1.5) -> dict[str, Any]:
    if port is None:
        return {"dashboard_port": None, "routes": {"/api/status": {"status": "unknown"}}}
    result: dict[str, Any] = {"dashboard_port": port, "routes": {}}
    for route in ("/api/status", "/chat"):
        entry: dict[str, Any]
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{route}", timeout=timeout
            ) as response:
                entry = {"http_status": int(response.status)}
                if route == "/api/status":
                    body = json.loads(response.read(64 * 1024).decode("utf-8", errors="replace"))
                    if isinstance(body, dict):
                        state: dict[str, Any] = {}
                        for key in sorted(_SAFE_STATUS_FIELDS):
                            value = body.get(key)
                            if isinstance(value, (bool, int, float)) and not isinstance(value, str):
                                state[key] = value
                            elif isinstance(value, str) and (safe := _safe_label(value)):
                                state[key] = safe
                        entry["state"] = state
        except urllib.error.HTTPError as exc:
            entry = {"http_status": int(exc.code)}
        except Exception as exc:
            entry = {"status": "unreachable", "error_class": type(exc).__name__}
        result["routes"][route] = entry
    return result


def _support_safe_event(event: object) -> dict[str, Any] | None:
    """Reduce an already-sanitized recorder event to metadata-only support fields."""
    if not isinstance(event, dict):
        return None
    clean: dict[str, Any] = {}
    for key in _SAFE_EVENT_ENVELOPE_KEYS:
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (int, float)):
            clean[key] = value
        elif key.endswith("_hash"):
            if safe_hash := _safe_sha256(value):
                clean[key] = safe_hash
        elif key.endswith("_id") or key in {"event_id", "event"}:
            try:
                clean[key] = _safe_id(value, label=key)
            except ValueError:
                continue
        elif safe := _safe_event_label(value):
            clean[key] = safe

    payload = event.get("payload")
    safe_payload: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            key = str(key)
            if key in _SAFE_EVENT_PAYLOAD_IDS:
                try:
                    safe_payload[key] = _safe_id(value, label=key)
                except ValueError:
                    pass
            elif key in _SAFE_EVENT_PAYLOAD_LABELS:
                if safe := _safe_event_label(value):
                    safe_payload[key] = safe
            elif key.endswith("_hash"):
                if safe_hash := _safe_sha256(value):
                    safe_payload[key] = safe_hash
            elif isinstance(value, bool):
                safe_payload[key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                safe_payload[key] = value
    clean["payload"] = safe_payload
    redaction = event.get("redaction")
    if isinstance(redaction, dict):
        clean["redaction"] = {}
        for key, value in redaction.items():
            safe_key = _safe_metric_key(key)
            if (
                safe_key
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                clean["redaction"][safe_key] = max(0, int(value))
    return clean


def build_support_payload(
    *,
    correlation_id: str,
    since_seconds: int | None,
    candidate_receipt: Path | None = None,
) -> dict[str, Any]:
    """Build the allowlisted bundle payload without writing it to disk."""
    from elevate_cli.diagnostics.session_recorder import collect_session_events

    correlation_id = _safe_id(correlation_id, label="correlation ID")
    snapshot = collect_session_events(
        correlation_id=correlation_id,
        since_seconds=since_seconds,
        include_lineage=True,
    )
    recorded_events = snapshot.get("events") if isinstance(snapshot, dict) else []
    recorded_events = recorded_events if isinstance(recorded_events, list) else []
    events = [
        safe_event
        for event in recorded_events
        if (safe_event := _support_safe_event(event)) is not None
    ]
    report = snapshot.get("report") if isinstance(snapshot, dict) else {}
    report = report if isinstance(report, dict) else {}
    counts: dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "diagnostics.event")[:96]
        counts[name] = counts.get(name, 0) + 1
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_unix": int(time.time()),
        "correlation_id": correlation_id,
        "candidate": _candidate_identity(candidate_receipt),
        "runtime": _route_health(_dashboard_port()),
        "event_type_counts": dict(sorted(counts.items())),
        "events": events,
        "redaction_report": {
            safe_key: int(value)
            for key, value in report.items()
            if (safe_key := _safe_metric_key(key))
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        },
    }
    payload["payload_sha256"] = _sha256_bytes(_canonical_json(payload))
    return payload


def write_support_bundle(
    payload: dict[str, Any],
    *,
    output: Path | None = None,
) -> tuple[Path, Path, str]:
    correlation_id = _safe_id(payload.get("correlation_id"), label="correlation ID")
    support_dir = get_elevate_home() / "support"
    support_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(support_dir, 0o700)
    except OSError:
        pass
    target = output or support_dir / (
        f"elevate-support-{correlation_id}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    )
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo("manifest.json")
            info.external_attr = 0o600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, _canonical_json(payload))
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    sidecar = target.with_suffix(target.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {target.name}\n", encoding="ascii")
    os.chmod(sidecar, 0o600)
    return target, sidecar, digest


def run_debug_bundle(args: Any) -> tuple[Path, Path, str]:
    correlation_id = _safe_id(
        getattr(args, "correlation", None), label="correlation ID"
    )
    receipt_value = getattr(args, "candidate_receipt", None)
    receipt = Path(receipt_value).expanduser().resolve() if receipt_value else None
    payload = build_support_payload(
        correlation_id=correlation_id,
        since_seconds=_parse_since(getattr(args, "last", "30m")),
        candidate_receipt=receipt,
    )
    output_value = getattr(args, "output", None)
    output = Path(output_value) if output_value else None
    bundle, sidecar, digest = write_support_bundle(payload, output=output)
    print(f"Support bundle: {bundle}")
    print(f"SHA-256: {digest}")
    print(f"Checksum file: {sidecar}")
    print("Privacy: structured sanitized events only; no raw logs or upload.")
    return bundle, sidecar, digest
