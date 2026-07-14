#!/usr/bin/env python3
"""Run candidate-bound fresh-session exact-reply chats against Elevate Beta.

This is intentionally separate from ``installed_runtime_smoke.py``.  It does
not build, sign, publish, start, stop, or restart the app.  The caller supplies
an already-running installed app and its immutable candidate receipt.

Each turn uses a fresh persisted session, session-scoped ``plan`` permission
mode, and a deterministic no-tool exact-reply prompt.  Evidence contains only
candidate metadata, synthetic IDs, event names, durations, counts, and hashes;
raw prompts, replies, and transcript content are never written.

This runner does not inspect or erase the app profile, so it cannot prove a
clean-profile gate.  Its evidence marks profile cleanliness as unverified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

try:
    import websockets
except ImportError:  # pragma: no cover - live-run environment guard
    websockets = None  # type: ignore[assignment]


EVIDENCE_SCHEMA_VERSION = 1
DEFAULT_CHAT_COUNT = 20
DEFAULT_TIMEOUT_SECONDS = 180.0
MAX_CHAT_COUNT = 100
MAX_DASHBOARD_RESPONSE_BYTES = 64 * 1024 * 1024
PROMPT_TEMPLATE_ID = "candidate-bound-read-only-exact-reply-v1"
_TOKEN_RE = re.compile(r'__ELEVATE_SESSION_TOKEN__="([^"]+)"')
_INDEX_ASSET_RE = re.compile(r'src="/assets/(index-[^"]+\.js)"')
_CHAT_ASSET_RE = re.compile(r"(ChatPage-[A-Za-z0-9_-]+\.js)")
_SAFE_EVENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_READ_ONLY_ACTIVITY_PREFIXES = (
    "approval.",
    "delegate.",
    "effect.",
    "subagent.",
    "tool.",
)
_FORBIDDEN_EVIDENCE_KEYS = {
    "content",
    "expected",
    "final_output",
    "messages",
    "prompt",
    "rendered",
    "text",
    "transcript",
}


class CampaignFailure(RuntimeError):
    """A failure with a stable, content-free evidence code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RpcClient(Protocol):
    events: list[dict[str, Any]]

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]: ...

    async def wait_for_event(
        self,
        event_type: str,
        session_id: str,
        cursor: int,
        timeout: float,
    ) -> dict[str, Any]: ...

    def events_since(self, cursor: int, session_id: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class CandidateBinding:
    candidate_id: str
    source_receipt_id: str
    architecture: str
    receipt_sha256: str
    app_version: str
    app_bundle_manifest_sha256: str


@dataclass
class TurnEvidence:
    index: int
    ok: bool = False
    failure_code: str | None = None
    live_session_id: str | None = None
    persisted_session_id: str | None = None
    resumed_session_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    prompt_sha256: str | None = None
    expected_sha256: str | None = None
    final_sha256: str | None = None
    transcript_sha256: str | None = None
    final_chars: int = 0
    resumed_message_count: int = 0
    tool_message_count: int = 0
    event_types: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    terminal_status: str | None = None
    usage_present: bool = False
    duplicate_terminal_status: str | None = None
    duplicate_attempts: int = 0
    permission_mode: str | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_millis(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def evidence_integrity(evidence: dict[str, Any]) -> str:
    body = dict(evidence)
    body.pop("evidence_integrity_sha256", None)
    return sha256_text(canonical_json(body))


def assert_content_free_evidence(value: Any) -> None:
    """Reject accidental raw prompt/reply/transcript fields before writing."""

    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_EVIDENCE_KEYS:
                raise CampaignFailure("unsafe_evidence_field")
            assert_content_free_evidence(item)
    elif isinstance(value, list):
        for item in value:
            assert_content_free_evidence(item)


def require_safe_id(value: Any, failure_code: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise CampaignFailure(failure_code)
    return value


def validate_binding(binding: CandidateBinding) -> None:
    if not _SHA256_RE.fullmatch(binding.candidate_id):
        raise CampaignFailure("candidate_id_invalid")
    if not _SHA256_RE.fullmatch(binding.source_receipt_id):
        raise CampaignFailure("source_receipt_id_invalid")
    if binding.architecture not in {"x64", "arm64"}:
        raise CampaignFailure("candidate_architecture_invalid")
    if not _SHA256_RE.fullmatch(binding.receipt_sha256):
        raise CampaignFailure("candidate_receipt_hash_invalid")
    if not _SHA256_RE.fullmatch(binding.app_bundle_manifest_sha256):
        raise CampaignFailure("candidate_bundle_hash_invalid")
    if not _SAFE_VERSION_RE.fullmatch(binding.app_version):
        raise CampaignFailure("candidate_app_version_invalid")


def validate_runtime_binding(binding: dict[str, Any]) -> None:
    if binding.get("method") != "installed-dashboard-asset-parity-v1":
        raise CampaignFailure("candidate_runtime_binding_invalid")
    if binding.get("served_assets_match_installed") is not True:
        raise CampaignFailure("candidate_runtime_asset_mismatch")
    for key in ("index_asset_bytes_sha256", "chat_asset_bytes_sha256"):
        value = binding.get(key)
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise CampaignFailure("candidate_runtime_binding_invalid")


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    """Atomically publish owner-only evidence without replacing an existing file."""

    document = dict(evidence)
    document["evidence_integrity_sha256"] = evidence_integrity(document)
    assert_content_free_evidence(document)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    open_fd: int | None = fd
    try:
        os.fchmod(fd, 0o600)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("short evidence write")
            remaining = remaining[written:]
        os.fsync(fd)
        os.close(fd)
        open_fd = None
        os.link(temporary_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The fully-written inode is already linked atomically. Some
            # filesystems do not support directory fsync.
            pass
    finally:
        if open_fd is not None:
            os.close(open_fd)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def verify_candidate_binding(
    *,
    repo_root: Path,
    receipt_path: Path,
    installed_app: Path,
    architecture: str,
    timeout: float = 300.0,
) -> CandidateBinding:
    """Invoke the immutable app verifier exactly once and return safe binding data."""

    verifier = repo_root / "desktop/scripts/candidate-receipt.js"
    if not verifier.is_file():
        raise CampaignFailure("candidate_verifier_missing")
    try:
        completed = subprocess.run(
            [
                "node",
                str(verifier),
                "verify-app",
                "--receipt",
                str(receipt_path.resolve()),
                "--app",
                str(installed_app.resolve()),
                "--arch",
                architecture,
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CampaignFailure("candidate_binding_failed") from exc
    if completed.returncode != 0:
        raise CampaignFailure("candidate_binding_failed")
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise CampaignFailure("candidate_binding_invalid") from exc
    required = {
        "candidate_id": payload.get("candidate_id"),
        "source_receipt_id": payload.get("source_receipt_id"),
        "architecture": payload.get("candidate_architecture"),
        "receipt_sha256": payload.get("receipt_sha256"),
        "app_version": payload.get("app_version"),
        "app_bundle_manifest_sha256": payload.get("app_bundle_manifest_sha256"),
    }
    if any(not isinstance(item, str) or not item for item in required.values()):
        raise CampaignFailure("candidate_binding_incomplete")
    if required["architecture"] != architecture:
        raise CampaignFailure("candidate_architecture_mismatch")
    binding = CandidateBinding(**required)  # type: ignore[arg-type]
    validate_binding(binding)
    return binding


def load_release_metadata(
    receipt_path: Path, binding: CandidateBinding
) -> dict[str, Any]:
    try:
        receipt_bytes = receipt_path.read_bytes()
        if hashlib.sha256(receipt_bytes).hexdigest() != binding.receipt_sha256:
            raise CampaignFailure("candidate_receipt_changed")
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except CampaignFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignFailure("candidate_receipt_unreadable") from exc
    if receipt.get("candidate_id") != binding.candidate_id:
        raise CampaignFailure("candidate_receipt_changed")
    release = receipt.get("release") if isinstance(receipt.get("release"), dict) else {}
    profile = release.get("profile") if isinstance(release.get("profile"), dict) else {}
    try:
        preferred_port = int(profile.get("preferredPort") or 0)
    except (TypeError, ValueError) as exc:
        raise CampaignFailure("candidate_receipt_invalid") from exc
    return {
        "channel": str(release.get("channel") or ""),
        "app_bundle_name": str(profile.get("appBundleName") or ""),
        "preferred_port": preferred_port,
    }


def extract_asset_name(pattern: re.Pattern[str], value: str, failure_code: str) -> str:
    match = pattern.search(value)
    if not match:
        raise CampaignFailure(failure_code)
    return require_safe_id(match.group(1), failure_code)


def installed_dashboard_assets(installed_app: Path) -> tuple[str, str, str, str]:
    """Read the same installed index/ChatPage asset pair used by installed smoke."""

    web_dist = installed_app / "Contents/Resources/cli/elevate_cli/web_dist"
    index_path = web_dist / "index.html"
    try:
        index_html = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CampaignFailure("installed_dashboard_index_missing") from exc
    index_asset = extract_asset_name(
        _INDEX_ASSET_RE,
        index_html,
        "installed_dashboard_index_invalid",
    )
    try:
        index_js_bytes = (web_dist / "assets" / index_asset).read_bytes()
    except OSError as exc:
        raise CampaignFailure("installed_dashboard_asset_missing") from exc
    index_js = index_js_bytes.decode("utf-8", errors="replace")
    chat_asset = extract_asset_name(
        _CHAT_ASSET_RE,
        index_js,
        "installed_dashboard_chat_asset_invalid",
    )
    try:
        chat_asset_bytes = (web_dist / "assets" / chat_asset).read_bytes()
    except OSError as exc:
        raise CampaignFailure("installed_dashboard_chat_asset_missing") from exc
    return (
        index_asset,
        chat_asset,
        hashlib.sha256(index_js_bytes).hexdigest(),
        hashlib.sha256(chat_asset_bytes).hexdigest(),
    )


def fetch_dashboard_bytes(url: str, timeout: float, failure_code: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "elevate-clean-chat-campaign/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_DASHBOARD_RESPONSE_BYTES + 1)
            if len(body) > MAX_DASHBOARD_RESPONSE_BYTES:
                raise CampaignFailure("dashboard_response_too_large")
            return body
    except CampaignFailure:
        raise
    except Exception as exc:
        raise CampaignFailure(failure_code) from exc


def fetch_dashboard_text(url: str, timeout: float, failure_code: str) -> str:
    return fetch_dashboard_bytes(url, timeout, failure_code).decode(
        "utf-8", errors="replace"
    )


def verify_runtime_binding(
    *,
    port: int,
    timeout: float,
    campaign_id: str,
    installed_app: Path,
) -> tuple[str, dict[str, Any]]:
    """Bind the served dashboard to the candidate-verified installed web assets."""

    (
        expected_index,
        expected_chat,
        expected_index_sha256,
        expected_chat_sha256,
    ) = installed_dashboard_assets(installed_app)
    html = fetch_dashboard_text(
        f"http://127.0.0.1:{port}/chat?new={campaign_id}",
        timeout,
        "dashboard_unreachable",
    )
    token_match = _TOKEN_RE.search(html)
    if not token_match:
        raise CampaignFailure("dashboard_token_missing")
    served_index = extract_asset_name(
        _INDEX_ASSET_RE,
        html,
        "served_dashboard_index_invalid",
    )
    served_index_bytes = fetch_dashboard_bytes(
        f"http://127.0.0.1:{port}/assets/{served_index}",
        timeout,
        "served_dashboard_asset_unreachable",
    )
    served_chat = extract_asset_name(
        _CHAT_ASSET_RE,
        served_index_bytes.decode("utf-8", errors="replace"),
        "served_dashboard_chat_asset_invalid",
    )
    served_chat_bytes = fetch_dashboard_bytes(
        f"http://127.0.0.1:{port}/assets/{served_chat}",
        timeout,
        "served_dashboard_chat_asset_unreachable",
    )
    served_index_sha256 = hashlib.sha256(served_index_bytes).hexdigest()
    served_chat_sha256 = hashlib.sha256(served_chat_bytes).hexdigest()
    if (
        served_index != expected_index
        or served_chat != expected_chat
        or served_index_sha256 != expected_index_sha256
        or served_chat_sha256 != expected_chat_sha256
    ):
        raise CampaignFailure("candidate_runtime_asset_mismatch")
    return token_match.group(1), {
        "method": "installed-dashboard-asset-parity-v1",
        "served_assets_match_installed": True,
        "index_asset_bytes_sha256": served_index_sha256,
        "chat_asset_bytes_sha256": served_chat_sha256,
    }


def deterministic_turn_material(
    binding: CandidateBinding, index: int
) -> tuple[str, str]:
    expected = f"candidate {binding.candidate_id[:12]} clean chat {index:02d} ok"
    prompt = (
        "Read-only verification. Do not use tools, access connectors, read files, "
        f"or change any state. Reply exactly: {expected}"
    )
    return prompt, expected


def synthetic_message_id(
    campaign_id: str, binding: CandidateBinding, index: int
) -> str:
    digest = sha256_text(f"{campaign_id}:{binding.candidate_id}:{index}")[:32]
    return f"clean-chat-{digest}"


def message_text(message: dict[str, Any]) -> str:
    for key in ("text", "content"):
        value = message.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            for block in value:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    return block["text"]
    return ""


def transcript_hash(messages: list[dict[str, Any]]) -> str:
    normalized = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        normalized.append(
            {
                "role": str(message.get("role") or ""),
                "message_id": str(message.get("message_id") or ""),
                "status": str(message.get("status") or ""),
                "text_sha256": sha256_text(message_text(message)),
            }
        )
    return sha256_text(canonical_json(normalized))


def safe_event_type(event: dict[str, Any]) -> str | None:
    value = event.get("type")
    if not isinstance(value, str) or not _SAFE_EVENT_RE.match(value):
        return None
    return value


def safe_status(value: Any) -> str | None:
    if not isinstance(value, str) or not _SAFE_EVENT_RE.match(value):
        return None
    return value


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def summarize_events(record: TurnEvidence, events: list[dict[str, Any]]) -> None:
    types = [value for event in events if (value := safe_event_type(event))]
    record.event_types = list(dict.fromkeys(types))
    record.event_counts = dict(sorted(Counter(types).items()))


async def checked_request(
    rpc: RpcClient,
    failure_code: str,
    method: str,
    params: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    try:
        result = await rpc.request(method, params, timeout)
    except CampaignFailure:
        raise
    except Exception as exc:
        raise CampaignFailure(failure_code) from exc
    if not isinstance(result, dict):
        raise CampaignFailure(failure_code)
    return result


async def best_effort_close(
    rpc: RpcClient, session_id: str | None, timeout: float
) -> None:
    if not session_id:
        return
    try:
        await rpc.request(
            "session.close", {"session_id": session_id}, min(timeout, 30.0)
        )
    except Exception:
        pass


async def close_and_confirm(
    rpc: RpcClient,
    session_id: str,
    timeout: float,
    failure_code: str,
) -> None:
    deadline = time.monotonic() + min(timeout, 30.0)
    while True:
        closed = await checked_request(
            rpc,
            failure_code,
            "session.close",
            {"session_id": session_id},
            min(timeout, 30.0),
        )
        if closed.get("closed") is True:
            return
        if (
            closed.get("detached") is True
            and closed.get("running") is True
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.05)
            continue
        raise CampaignFailure(failure_code)


async def run_turn(
    *,
    rpc: RpcClient,
    binding: CandidateBinding,
    campaign_id: str,
    index: int,
    timeout: float,
    seen_persisted_sessions: set[str],
) -> TurnEvidence:
    record = TurnEvidence(index=index)
    started = time.monotonic()
    live_session_id: str | None = None
    resumed_session_id: str | None = None
    event_cursor = len(rpc.events)
    prompt, expected = deterministic_turn_material(binding, index)
    user_message_id = synthetic_message_id(campaign_id, binding, index)
    record.prompt_sha256 = sha256_text(prompt)
    record.expected_sha256 = sha256_text(expected)
    record.user_message_id = user_message_id

    try:
        phase = time.monotonic()
        created = await checked_request(
            rpc,
            "session_create_failed",
            "session.create",
            {"cols": 100},
            timeout,
        )
        record.timings_ms["session_create"] = int((time.monotonic() - phase) * 1000)
        live_session_id = require_safe_id(
            created.get("session_id"), "live_session_id_invalid"
        )
        persisted_session_id = require_safe_id(
            created.get("persisted_session_id"), "persisted_session_id_invalid"
        )
        record.live_session_id = live_session_id
        record.persisted_session_id = persisted_session_id
        if persisted_session_id in seen_persisted_sessions:
            raise CampaignFailure("persisted_session_not_fresh")
        seen_persisted_sessions.add(persisted_session_id)

        permission = await checked_request(
            rpc,
            "read_only_mode_failed",
            "config.set",
            {"session_id": live_session_id, "key": "permission_mode", "value": "plan"},
            min(timeout, 30.0),
        )
        if permission.get("value") != "plan":
            raise CampaignFailure("read_only_mode_failed")
        record.permission_mode = "plan"

        event_cursor = len(rpc.events)
        phase = time.monotonic()
        submitted = await checked_request(
            rpc,
            "prompt_submit_failed",
            "prompt.submit",
            {
                "session_id": live_session_id,
                "text": prompt,
                "user_message_id": user_message_id,
            },
            min(timeout, 30.0),
        )
        record.timings_ms["submit_ack"] = int((time.monotonic() - phase) * 1000)
        if submitted.get("status") == "sign_in_required":
            raise CampaignFailure("candidate_auth_required")
        if submitted.get("status") != "streaming" or submitted.get("duplicate") is True:
            raise CampaignFailure("submit_not_streaming")
        if submitted.get("user_message_id") != user_message_id:
            raise CampaignFailure("submit_identity_mismatch")
        assistant_message_id = require_safe_id(
            submitted.get("message_id"), "assistant_message_id_invalid"
        )
        record.assistant_message_id = assistant_message_id

        phase = time.monotonic()
        try:
            terminal_event = await rpc.wait_for_event(
                "message.complete",
                live_session_id,
                event_cursor,
                timeout,
            )
        except Exception as exc:
            raise CampaignFailure("terminal_timeout") from exc
        record.timings_ms["terminal_wait"] = int((time.monotonic() - phase) * 1000)
        turn_events = rpc.events_since(event_cursor, live_session_id)
        summarize_events(record, turn_events)
        required_events = {"message.start", "message.delta", "message.complete"}
        if not required_events.issubset(record.event_counts):
            raise CampaignFailure("streaming_missing")
        for event_type in required_events:
            matching = [
                event_payload(event)
                for event in turn_events
                if event.get("type") == event_type
            ]
            if not matching or any(
                item.get("message_id") != assistant_message_id for item in matching
            ):
                raise CampaignFailure("stream_identity_mismatch")

        terminal = event_payload(terminal_event)
        terminal_status = terminal.get("status")
        record.terminal_status = safe_status(terminal_status)
        if (
            terminal_status != "complete"
            or terminal.get("completed") is False
            or terminal.get("failed") is True
            or terminal.get("interrupted") is True
            or bool(terminal.get("error"))
        ):
            raise CampaignFailure("terminal_not_complete")
        if not isinstance(terminal.get("usage"), dict):
            raise CampaignFailure("terminal_usage_missing")
        record.usage_present = True
        final_text = terminal.get("text") or terminal.get("rendered")
        if (
            not isinstance(final_text, str)
            or not final_text.strip()
            or final_text.strip() == "(empty)"
        ):
            raise CampaignFailure("empty_output")
        record.final_chars = len(final_text)
        record.final_sha256 = sha256_text(final_text)
        if final_text != expected:
            raise CampaignFailure("unexpected_output")

        await close_and_confirm(
            rpc,
            live_session_id,
            timeout,
            "session_close_not_confirmed",
        )
        live_session_id = None

        phase = time.monotonic()
        resumed = await checked_request(
            rpc,
            "session_resume_failed",
            "session.resume",
            {"session_id": persisted_session_id, "include_messages": True, "cols": 100},
            min(timeout, 30.0),
        )
        record.timings_ms["resume"] = int((time.monotonic() - phase) * 1000)
        resumed_session_id = require_safe_id(
            resumed.get("session_id"), "resumed_session_id_invalid"
        )
        if resumed_session_id == record.live_session_id:
            raise CampaignFailure("resumed_session_not_distinct")
        if resumed.get("persisted_session_id") != persisted_session_id:
            raise CampaignFailure("resume_persisted_identity_mismatch")
        messages = resumed.get("messages")
        if not isinstance(messages, list):
            raise CampaignFailure("resumed_transcript_missing")
        record.resumed_session_id = resumed_session_id
        clean_messages = [message for message in messages if isinstance(message, dict)]
        record.resumed_message_count = len(clean_messages)
        record.transcript_sha256 = transcript_hash(clean_messages)
        user_matches = [
            message
            for message in clean_messages
            if message.get("role") == "user"
            and message.get("message_id") == user_message_id
            and message_text(message) == prompt
        ]
        assistant_matches = [
            message
            for message in clean_messages
            if message.get("role") == "assistant"
            and message.get("message_id") == assistant_message_id
            and message_text(message) == expected
        ]
        if not user_matches or not assistant_matches:
            raise CampaignFailure("resumed_transcript_mismatch")
        if (
            sum(message.get("role") == "user" for message in clean_messages) != 1
            or sum(message.get("role") == "assistant" for message in clean_messages)
            != 1
        ):
            raise CampaignFailure("resumed_transcript_not_clean")
        if any(
            str(message.get("status") or "") not in {"", "complete"}
            for message in assistant_matches
        ):
            raise CampaignFailure("resumed_terminal_not_complete")
        record.tool_message_count = sum(
            message.get("role") == "tool" for message in clean_messages
        )
        summarize_events(
            record,
            rpc.events_since(event_cursor, record.live_session_id or ""),
        )
        if record.tool_message_count or any(
            name.startswith(_READ_ONLY_ACTIVITY_PREFIXES) for name in record.event_types
        ):
            raise CampaignFailure("read_only_activity_detected")

        duplicate_cursor = len(rpc.events)
        duplicate_deadline = time.monotonic() + min(timeout, 30.0)
        phase = time.monotonic()
        while True:
            record.duplicate_attempts += 1
            duplicate = await checked_request(
                rpc,
                "duplicate_receipt_failed",
                "prompt.submit",
                {
                    "session_id": resumed_session_id,
                    "text": prompt,
                    "user_message_id": user_message_id,
                },
                min(timeout, 30.0),
            )
            if (
                duplicate.get("status") == "duplicate"
                and duplicate.get("terminal_status") == "complete"
            ):
                if (
                    duplicate.get("duplicate") is not True
                    or duplicate.get("correlation_id") != user_message_id
                    or duplicate.get("user_message_id") != user_message_id
                    or duplicate.get("message_id") != assistant_message_id
                ):
                    raise CampaignFailure("duplicate_receipt_identity_mismatch")
                record.duplicate_terminal_status = "complete"
                break
            if (
                duplicate.get("status") != "streaming"
                or duplicate.get("duplicate") is not True
                or time.monotonic() >= duplicate_deadline
            ):
                raise CampaignFailure("duplicate_terminal_receipt_missing")
            await asyncio.sleep(0.1)
        record.timings_ms["duplicate_receipt"] = int((time.monotonic() - phase) * 1000)
        duplicate_events = rpc.events_since(duplicate_cursor, resumed_session_id)
        if any(
            (name := safe_event_type(event))
            and name.startswith(("message.", *_READ_ONLY_ACTIVITY_PREFIXES))
            for event in duplicate_events
        ):
            raise CampaignFailure("duplicate_prompt_reexecuted")

        await close_and_confirm(
            rpc,
            resumed_session_id,
            timeout,
            "resumed_session_close_not_confirmed",
        )
        resumed_session_id = None
        record.ok = True
    except CampaignFailure as exc:
        record.failure_code = exc.code
        summarize_events(
            record, rpc.events_since(event_cursor, record.live_session_id or "")
        )
    finally:
        await best_effort_close(rpc, live_session_id, timeout)
        await best_effort_close(rpc, resumed_session_id, timeout)
        record.timings_ms["total"] = int((time.monotonic() - started) * 1000)
    return record


class JsonRpcWebSocket:
    """Small sequential JSON-RPC client that retains content-free event envelopes in memory."""

    def __init__(self, websocket: Any):
        self.websocket = websocket
        self.events: list[dict[str, Any]] = []
        self._next_id = 0

    def _record_event(self, message: dict[str, Any]) -> None:
        if message.get("method") != "event":
            return
        params = message.get("params")
        if isinstance(params, dict):
            self.events.append(params)

    async def _receive(self, timeout: float) -> dict[str, Any]:
        raw = await asyncio.wait_for(self.websocket.recv(), timeout=max(0.1, timeout))
        try:
            message = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CampaignFailure("gateway_invalid_json") from exc
        if not isinstance(message, dict):
            raise CampaignFailure("gateway_invalid_message")
        self._record_event(message)
        return message

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        self._next_id += 1
        request_id = f"clean-chat-{self._next_id}"
        await self.websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                separators=(",", ":"),
            )
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = await self._receive(deadline - time.monotonic())
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise CampaignFailure("gateway_rpc_error")
            result = message.get("result")
            if not isinstance(result, dict):
                raise CampaignFailure("gateway_rpc_result_invalid")
            return result
        raise CampaignFailure("gateway_rpc_timeout")

    def events_since(self, cursor: int, session_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events[cursor:]
            if not session_id or event.get("session_id") == session_id
        ]

    async def wait_for_event(
        self,
        event_type: str,
        session_id: str,
        cursor: int,
        timeout: float,
    ) -> dict[str, Any]:
        scan = cursor
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while scan < len(self.events):
                event = self.events[scan]
                scan += 1
                if (
                    event.get("type") == event_type
                    and event.get("session_id") == session_id
                ):
                    return event
            await self._receive(deadline - time.monotonic())
        raise CampaignFailure("gateway_event_timeout")


def build_campaign_evidence(
    *,
    binding: CandidateBinding,
    release_metadata: dict[str, Any],
    installed_app_name: str,
    campaign_id: str,
    dashboard_port: int,
    requested_count: int,
    timeout: float,
    started_at: datetime,
    completed_at: datetime,
    turns: list[TurnEvidence],
    runtime_binding: dict[str, Any],
) -> dict[str, Any]:
    validate_binding(binding)
    validate_runtime_binding(runtime_binding)
    require_safe_id(campaign_id, "campaign_id_invalid")
    if requested_count < 1 or requested_count > MAX_CHAT_COUNT:
        raise CampaignFailure("campaign_count_invalid")
    if not math.isfinite(timeout) or timeout <= 0:
        raise CampaignFailure("campaign_timeout_invalid")
    if not 1 <= dashboard_port <= 65535:
        raise CampaignFailure("dashboard_port_invalid")
    failures = Counter(turn.failure_code for turn in turns if turn.failure_code)
    passed = sum(turn.ok for turn in turns)
    evidence = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "kind": "elevate-exact-candidate-clean-chat-campaign",
        "ok": len(turns) == requested_count and passed == requested_count,
        "campaign_id": campaign_id,
        "candidate": asdict(binding),
        "runtime_binding": dict(runtime_binding),
        "release": {
            "channel": release_metadata.get("channel"),
            "app_bundle_name": release_metadata.get("app_bundle_name"),
            "installed_app_name": installed_app_name,
            "dashboard_port": dashboard_port,
            "host_architecture": platform.machine().lower(),
        },
        "configuration": {
            "requested_chat_count": requested_count,
            "timeout_seconds": timeout,
            "permission_mode": "plan",
            "prompt_template_id": PROMPT_TEMPLATE_ID,
            "fresh_persisted_session_per_turn": True,
            "profile_cleanliness": "unverified_by_runner",
        },
        "started_at": iso_millis(started_at),
        "completed_at": iso_millis(completed_at),
        "duration_ms": max(0, int((completed_at - started_at).total_seconds() * 1000)),
        "summary": {
            "attempted": len(turns),
            "passed": passed,
            "failed": len(turns) - passed,
            "failure_codes": dict(sorted(failures.items())),
        },
        "turns": [asdict(turn) for turn in turns],
    }
    assert_content_free_evidence(evidence)
    evidence["evidence_integrity_sha256"] = evidence_integrity(evidence)
    return evidence


async def run_campaign_with_rpc(
    *,
    rpc: RpcClient,
    binding: CandidateBinding,
    release_metadata: dict[str, Any],
    installed_app_name: str,
    campaign_id: str,
    dashboard_port: int,
    count: int,
    timeout: float,
    runtime_binding: dict[str, Any],
    started_at: datetime | None = None,
) -> dict[str, Any]:
    started = started_at or utc_now()
    turns: list[TurnEvidence] = []
    seen_persisted_sessions: set[str] = set()
    for index in range(1, count + 1):
        turns.append(
            await run_turn(
                rpc=rpc,
                binding=binding,
                campaign_id=campaign_id,
                index=index,
                timeout=timeout,
                seen_persisted_sessions=seen_persisted_sessions,
            )
        )
    return build_campaign_evidence(
        binding=binding,
        release_metadata=release_metadata,
        installed_app_name=installed_app_name,
        campaign_id=campaign_id,
        dashboard_port=dashboard_port,
        requested_count=count,
        timeout=timeout,
        started_at=started,
        completed_at=utc_now(),
        turns=turns,
        runtime_binding=runtime_binding,
    )


async def run_live_campaign(
    *,
    binding: CandidateBinding,
    release_metadata: dict[str, Any],
    installed_app: Path,
    installed_app_name: str,
    campaign_id: str,
    port: int,
    count: int,
    timeout: float,
) -> dict[str, Any]:
    if websockets is None:
        raise CampaignFailure("websockets_dependency_missing")
    token, runtime_binding = verify_runtime_binding(
        port=port,
        timeout=min(timeout, 30.0),
        campaign_id=campaign_id,
        installed_app=installed_app,
    )
    url = f"ws://127.0.0.1:{port}/api/ws?token={token}"
    try:
        async with websockets.connect(
            url, max_size=None, ping_interval=None
        ) as websocket:
            return await run_campaign_with_rpc(
                rpc=JsonRpcWebSocket(websocket),
                binding=binding,
                release_metadata=release_metadata,
                installed_app_name=installed_app_name,
                campaign_id=campaign_id,
                dashboard_port=port,
                count=count,
                timeout=timeout,
                runtime_binding=runtime_binding,
            )
    except CampaignFailure:
        raise
    except Exception as exc:
        raise CampaignFailure("gateway_connection_failed") from exc


def count_arg(value: str) -> int:
    count = int(value)
    if count < 1 or count > MAX_CHAT_COUNT:
        raise argparse.ArgumentTypeError(
            f"count must be between 1 and {MAX_CHAT_COUNT}"
        )
    return count


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return timeout


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--installed-app", type=Path, required=True)
    parser.add_argument(
        "--candidate-architecture", choices=("x64", "arm64"), required=True
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_script())
    parser.add_argument("--port", type=int)
    parser.add_argument("--count", type=count_arg, default=DEFAULT_CHAT_COUNT)
    parser.add_argument(
        "--timeout", type=positive_timeout, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        binding = verify_candidate_binding(
            repo_root=args.repo_root,
            receipt_path=args.candidate_receipt,
            installed_app=args.installed_app,
            architecture=args.candidate_architecture,
        )
        release_metadata = load_release_metadata(args.candidate_receipt, binding)
        port = args.port or release_metadata.get("preferred_port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise CampaignFailure("dashboard_port_missing")
        campaign_id = f"clean-chat-{binding.candidate_id[:12]}-{time.time_ns()}"
        evidence = asyncio.run(
            run_live_campaign(
                binding=binding,
                release_metadata=release_metadata,
                installed_app=args.installed_app,
                installed_app_name=args.installed_app.name,
                campaign_id=campaign_id,
                port=port,
                count=args.count,
                timeout=args.timeout,
            )
        )
    except CampaignFailure as exc:
        print(f"FAIL {exc.code}", file=sys.stderr)
        return 1

    output_path = args.json_out or (
        Path("/tmp")
        / f"elevate-clean-chat-{binding.candidate_id[:12]}-{int(time.time())}.json"
    )
    try:
        write_evidence(output_path, evidence)
    except (CampaignFailure, OSError) as exc:
        code = exc.code if isinstance(exc, CampaignFailure) else "evidence_write_failed"
        print(f"FAIL {code}", file=sys.stderr)
        return 1
    print(
        f"{'PASS' if evidence['ok'] else 'FAIL'} "
        f"{evidence['summary']['passed']}/{evidence['summary']['attempted']} "
        f"candidate={binding.candidate_id[:12]} evidence={output_path}"
    )
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
