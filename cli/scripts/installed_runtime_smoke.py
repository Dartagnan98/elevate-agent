#!/usr/bin/env python3
"""Smoke-test the installed Elevate dashboard/gateway runtime.

This intentionally exercises the packaged app path instead of localhost dev:

1. Compare repo web_dist with the installed app web_dist.
2. Fetch the installed dashboard HTML and discover the active asset hashes.
3. Connect to the dashboard JSON-RPC WebSocket sidecar.
4. Create a chat session, submit an exact-reply prompt, and wait for completion.
5. Scan fresh Electron logs for the stale-socket/blank-shell errors we have hit.

Optional flags add installed-code Telegram hygiene fixtures and a real installed
desktop compact/resume/follow-up smoke.

It does not start/patch/restart the app. Run it after the installed app is
already running on the dashboard port.
"""

from __future__ import annotations

import argparse
import asyncio
import filecmp
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover - environment guard
    websockets = None  # type: ignore[assignment]


DEFAULT_APP = Path(
    "/Users/dartagnanpatricio/Applications/Elevate.app"
)
DEFAULT_PORT = 9119
BAD_LOG_PATTERNS = (
    "gateway not connected",
    "Uncaught",
    "BLANK-TRACE",
    "did-fail-load",
)


@dataclass
class SmokeResult:
    ok: bool = True
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    dashboard_port: int | None = None
    installed_index_asset: str | None = None
    installed_chat_asset: str | None = None
    persisted_session_id: str | None = None
    sidecar_session_id: str | None = None
    resumed_session_id: str | None = None
    resumed_message_count: int | None = None
    final_text: str | None = None
    license_authenticated: bool | None = None
    license_expired: bool | None = None
    license_status_text: str | None = None
    telegram_fixture: dict[str, Any] | None = None
    telegram_hygiene: dict[str, Any] | None = None
    desktop_compaction: dict[str, Any] | None = None
    installed_app_seal: list[dict[str, Any]] = field(default_factory=list)
    log_hits: list[str] = field(default_factory=list)
    installed_whatsapp_bridge: dict[str, bool] | None = None
    installed_app_version: str | None = None
    output_path: str | None = None

    def pass_check(self, message: str) -> None:
        self.checks.append(message)

    def fail(self, message: str) -> None:
        self.ok = False
        self.failures.append(message)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def compare_trees(left: Path, right: Path, *, limit: int = 20) -> list[str]:
    if not left.exists():
        return [f"missing repo tree: {left}"]
    if not right.exists():
        return [f"missing installed tree: {right}"]

    diffs: list[str] = []

    def walk(a: Path, b: Path, rel: Path = Path("")) -> None:
        if len(diffs) >= limit:
            return
        cmp = filecmp.dircmp(a, b)
        for name in cmp.left_only:
            diffs.append(f"installed missing: {rel / name}")
            if len(diffs) >= limit:
                return
        for name in cmp.right_only:
            diffs.append(f"installed extra: {rel / name}")
            if len(diffs) >= limit:
                return
        for name in cmp.common_files:
            if not filecmp.cmp(a / name, b / name, shallow=False):
                diffs.append(f"content differs: {rel / name}")
                if len(diffs) >= limit:
                    return
        for name in cmp.common_dirs:
            walk(a / name, b / name, rel / name)

    walk(left, right)
    return diffs


def cli_relative_path(repo_root: Path, value: str) -> tuple[Path, Path]:
    rel = Path(value)
    if rel.parts and rel.parts[0] == "cli":
        repo_path = repo_root / rel
        installed_rel = Path(*rel.parts[1:])
    else:
        repo_path = repo_root / "cli" / rel
        installed_rel = rel
    return repo_path, installed_rel


def fetch_text(url: str, timeout: float) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_status(url: str, timeout: float, headers: dict[str, str] | None = None) -> int:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def extract_required(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"could not find {label}")
    return match.group(1)


def installed_dashboard_assets(installed_web_dist: Path) -> tuple[str, str]:
    html_path = installed_web_dist / "index.html"
    if not html_path.exists():
        raise RuntimeError(f"installed dashboard index missing: {html_path}")
    index_asset = extract_required(
        r'src="/assets/(index-[^"]+\.js)"',
        html_path.read_text(encoding="utf-8", errors="replace"),
        "installed index asset",
    )
    index_js_path = installed_web_dist / "assets" / index_asset
    if not index_js_path.exists():
        raise RuntimeError(f"installed dashboard asset missing: {index_js_path}")
    chat_asset = extract_required(
        r"(ChatPage-[A-Za-z0-9_-]+\.js)",
        index_js_path.read_text(encoding="utf-8", errors="replace"),
        "installed ChatPage asset",
    )
    return index_asset, chat_asset


def check_served_assets_match_installed(installed_web_dist: Path, result: SmokeResult) -> None:
    expected_index, expected_chat = installed_dashboard_assets(installed_web_dist)
    if result.installed_index_asset != expected_index:
        result.fail(
            "served dashboard index asset differs from installed web_dist: "
            f"{result.installed_index_asset!r} != {expected_index!r}"
        )
    if result.installed_chat_asset != expected_chat:
        result.fail(
            "served dashboard ChatPage asset differs from installed web_dist: "
            f"{result.installed_chat_asset!r} != {expected_chat!r}"
        )
    if result.installed_index_asset == expected_index and result.installed_chat_asset == expected_chat:
        result.pass_check("served dashboard assets match installed web_dist")


def check_protected_http_auth(*, port: int, token: str, timeout: float, result: SmokeResult) -> None:
    url = f"http://127.0.0.1:{port}/api/sessions?limit=1"
    unauth_status = fetch_status(url, timeout)
    if unauth_status != 401:
        result.fail(f"protected HTTP route without token returned {unauth_status}, expected 401")
    else:
        result.pass_check("protected HTTP route rejects missing token")

    authed_status = fetch_status(url, timeout, {"X-Elevate-Session-Token": token})
    if authed_status != 200:
        result.fail(f"protected HTTP route with session token returned {authed_status}, expected 200")
    else:
        result.pass_check("protected HTTP route accepts extracted session token")


def read_recent_log_hits(path: Path, since: datetime) -> list[str]:
    if not path.exists():
        return []

    hits: list[str] = []
    line_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]")
    fresh_block = False
    cutoff = since.replace(microsecond=0)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = line_re.match(line)
        if match:
            try:
                stamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                fresh_block = False
                continue
            fresh_block = stamp >= cutoff
            if not fresh_block:
                continue
        elif not fresh_block:
            continue
        if any(pattern in line for pattern in BAD_LOG_PATTERNS):
            hits.append(line.strip())
    return hits[-20:]


def read_selected_dashboard_port(path: Path, fallback: int = DEFAULT_PORT) -> int:
    if not path.exists():
        return fallback
    line_re = re.compile(r"\[startup\].*\bbackend:port-selected\s+(\d+)\b")
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        match = line_re.search(line)
        if match:
            return int(match.group(1))
    return fallback


def license_state_path() -> Path:
    elevate_home = os.environ.get("ELEVATE_HOME")
    if elevate_home:
        return Path(elevate_home) / "license.json"
    return Path.home() / ".elevate/license.json"


def read_license_state() -> tuple[bool | None, bool | None, str | None]:
    path = license_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, True, "Not activated. Run `elevate activate`."
    token = data.get("access_token")
    expires_at = data.get("expires_at")
    if not token or not isinstance(expires_at, (int, float)):
        return False, True, "License file is missing a valid access token."
    remaining = int(float(expires_at) - time.time())
    expired = remaining <= 30
    if expired:
        return True, True, "Subscribed, but local access token is expired."
    return True, False, f"Subscribed, token has {remaining // 60}m left."


def _command_output(completed: subprocess.CompletedProcess[str]) -> str:
    text = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    if not text:
        text = f"exit status {completed.returncode}"
    if len(text) > 4000:
        return text[-4000:]
    return text


def run_installed_app_seal(
    *,
    installed_app: Path,
    timeout: float,
    result: SmokeResult,
) -> None:
    """Verify the installed .app code signature and Gatekeeper assessment."""

    if not installed_app.exists():
        result.fail(f"installed app missing: {installed_app}")
        return

    commands = [
        (
            "codesign",
            [
                "codesign",
                "--verify",
                "--deep",
                "--strict",
                "--verbose=2",
                str(installed_app),
            ],
        ),
        (
            "spctl",
            [
                "spctl",
                "--assess",
                "--type",
                "execute",
                "--verbose=4",
                str(installed_app),
            ],
        ),
    ]

    for name, command in commands:
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=min(max(timeout, 1.0), 60.0),
                check=False,
            )
        except FileNotFoundError:
            result.installed_app_seal.append(
                {"name": name, "ok": False, "status": None, "output": "not found"}
            )
            result.fail(f"{name} unavailable for installed app seal check")
            continue
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + (exc.stderr or "")
            result.installed_app_seal.append(
                {
                    "name": name,
                    "ok": False,
                    "status": None,
                    "output": output.strip() or "timed out",
                }
            )
            result.fail(f"{name} timed out during installed app seal check")
            continue

        output = _command_output(completed)
        ok = completed.returncode == 0
        result.installed_app_seal.append(
            {
                "name": name,
                "ok": ok,
                "status": completed.returncode,
                "output": output,
            }
        )
        if not ok:
            lines = [line for line in output.splitlines() if line.strip()]
            summary = lines[-1] if lines else f"exit {completed.returncode}"
            result.fail(f"{name} installed app seal check failed: {summary}")

    if result.installed_app_seal and all(item["ok"] for item in result.installed_app_seal):
        result.pass_check("installed app seal valid (codesign + spctl)")


def read_installed_app_version(installed_app: Path) -> str | None:
    plist = installed_app / "Contents/Info.plist"
    try:
        completed = subprocess.run(
            [
                "plutil",
                "-extract",
                "CFBundleShortVersionString",
                "raw",
                str(plist),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def run_installed_whatsapp_bridge(
    *,
    installed_cli: Path,
    result: SmokeResult,
) -> None:
    """Verify packaged WhatsApp bridge files that /api/status can report on."""

    bridge_dir = installed_cli / "scripts/whatsapp-bridge"
    bridge_script = bridge_dir / "bridge.js"
    package_json = bridge_dir / "package.json"
    node_modules = bridge_dir / "node_modules"
    package_lock = bridge_dir / "package-lock.json"
    status = {
        "bridge_js": bridge_script.exists(),
        "package_json": package_json.exists(),
        "node_modules": node_modules.exists(),
        "package_lock": package_lock.exists(),
    }
    result.installed_whatsapp_bridge = status
    missing = [name for name, ok in status.items() if not ok]
    if missing:
        result.fail(
            "installed WhatsApp bridge incomplete: " + ", ".join(sorted(missing))
        )
        return
    result.pass_check("installed WhatsApp bridge present with dependencies")


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_from_offset(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, offset))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _session_compaction_lines(path: Path, offset: int, session_id: str) -> list[str]:
    text = _read_from_offset(path, offset)
    needle = f"session={session_id}"
    return [
        line.strip()
        for line in text.splitlines()
        if "compaction." in line and needle in line
    ][-20:]


def run_installed_telegram_fixture(
    *,
    installed_cli: Path,
    timeout: float,
    result: SmokeResult,
) -> None:
    """Exercise installed gateway hygiene helpers with Telegram-shaped data."""

    code = r"""
import json
import sys

sys.path.insert(0, sys.argv[1])

from gateway.run import (
    _HYGIENE_NOOP_RETRY_MARGIN,
    _hygiene_effective_messages_for_pressure,
    _hygiene_load_persisted_guard,
    _hygiene_persist_guard,
    _hygiene_record,
    _hygiene_should_skip,
)

history = [
    {
        "role": "user" if i % 2 == 0 else "assistant",
        "content": f"telegram fixture message {i}",
    }
    for i in range(450)
]

effective = _hygiene_effective_messages_for_pressure(
    history,
    compaction_cursor=440,
    compaction_summary="earlier Telegram context",
)
assert len(effective) == 11, len(effective)
assert "earlier Telegram context" in effective[0]["content"]
assert effective[1]["content"] == "telegram fixture message 440"

guard = {}
session_id = "telegram-fixture-session"
_hygiene_record(guard, session_id, msg_count=len(history), ineffective=True)

class FakeDB:
    def __init__(self):
        self.values = {}

    def get_meta(self, key):
        return self.values.get(key)

    def set_meta(self, key, value):
        self.values[key] = value

db = FakeDB()
_hygiene_persist_guard(db, guard)
reloaded = _hygiene_load_persisted_guard(db)

same_count_skips = _hygiene_should_skip(
    reloaded,
    session_id,
    msg_count=len(history),
    margin=_HYGIENE_NOOP_RETRY_MARGIN,
    reason="message_count",
    approx_tokens=100_000,
    warn_tokens=190_000,
)
grown_retries = not _hygiene_should_skip(
    reloaded,
    session_id,
    msg_count=len(history) + _HYGIENE_NOOP_RETRY_MARGIN + 1,
    margin=_HYGIENE_NOOP_RETRY_MARGIN,
    reason="message_count",
    approx_tokens=100_000,
    warn_tokens=190_000,
)

assert same_count_skips is True
assert grown_retries is True

print(json.dumps({
    "raw_messages": len(history),
    "effective_messages": len(effective),
    "same_count_skips": same_count_skips,
    "grown_retries": grown_retries,
    "guard_reloaded": session_id in _hygiene_load_persisted_guard(db),
}, sort_keys=True))
"""
    with TemporaryDirectory(prefix="elevate-telegram-fixture-") as tmp:
        env = os.environ.copy()
        env["ELEVATE_HOME"] = tmp
        env["PYTHONPATH"] = (
            str(installed_cli)
            + os.pathsep
            + env.get("PYTHONPATH", "")
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(installed_cli)],
            cwd=tmp,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"telegram fixture failed: {stderr}")

    line = completed.stdout.strip().splitlines()[-1]
    payload = json.loads(line)
    result.telegram_fixture = payload
    result.pass_check(
        "telegram fixture: cursor raw history trims to summary+tail and retry guard reloads"
    )


def run_installed_telegram_hygiene_soak(
    *,
    installed_cli: Path,
    timeout: float,
    result: SmokeResult,
) -> None:
    """Run installed GatewayRunner hygiene with synthetic Telegram events."""

    code = r"""
import asyncio
import importlib
import json
import logging
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, sys.argv[1])

fake_dotenv = types.ModuleType("dotenv")
fake_dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules["dotenv"] = fake_dotenv

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult
from gateway.session import SessionEntry, SessionSource


class CaptureAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="fake-token"), Platform.TELEGRAM)
        self.sent = []

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append({"chat_id": chat_id, "content": content})
        return SendResult(success=True, message_id="synthetic-1")

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


def make_history(n_messages, content_size=20):
    content = "x" * content_size
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": content,
            "timestamp": f"t{i}",
        }
        for i in range(n_messages)
    ]


def make_runner(gateway_run, *, session_id, history, row, last_prompt_tokens=0):
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="fake-token")}
    )
    runner.adapters = {Platform.TELEGRAM: CaptureAdapter()}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = SessionEntry(
        session_key="agent:main:telegram:dm:8404672468:agent:executive-assistant",
        session_id=session_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
        last_prompt_tokens=last_prompt_tokens,
    )
    runner.session_store.load_transcript.return_value = history
    runner.session_store.has_any_sessions.return_value = True
    runner.session_store.rewrite_transcript = MagicMock()
    runner.session_store.append_to_transcript = MagicMock()
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_model_overrides = {}
    runner._session_db = MagicMock()
    runner._session_db.get_session.return_value = row
    runner._session_db.get_meta.return_value = None
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "ok",
            "messages": [],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 35_500,
        }
    )
    return runner


async def main():
    gateway_run = importlib.import_module("gateway.run")
    gateway_run._elevate_home = Path(os.environ["ELEVATE_HOME"])
    gateway_run._resolve_runtime_agent_kwargs = lambda: {"api_key": "fake"}

    import agent.model_metadata
    agent.model_metadata.get_model_context_length = lambda *_args, **_kwargs: 100_000
    gateway_run.get_model_context_length = lambda *_args, **_kwargs: 100_000

    event = MessageEvent(
        text="hello",
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="8404672468",
            chat_type="dm",
            user_id="8404672468",
            agent_id="executive-assistant",
        ),
        message_id="1",
    )

    class CursorAgent:
        calls = 0
        def __init__(self, **_kwargs):
            type(self).calls += 1
            raise AssertionError("cursor-compacted history should not auto-compress")

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = CursorAgent
    sys.modules["run_agent"] = fake_run_agent

    cursor_runner = make_runner(
        gateway_run,
        session_id="installed-telegram-cursor",
        history=make_history(450, 20),
        row={
            "compaction_cursor": 430,
            "compaction_summary": "earlier Telegram turns summarized",
        },
        last_prompt_tokens=99_000,
    )
    cursor_result = await cursor_runner._handle_message(event)
    assert cursor_result == "ok"
    assert CursorAgent.calls == 0
    cursor_runner.session_store.rewrite_transcript.assert_not_called()

    class FailingCompressAgent:
        calls = 0
        def __init__(self, **_kwargs):
            type(self).calls += 1
            self.session_id = "installed-telegram-fail"
            self.compaction_cursor = 0
            self.compaction_summary = None
            self.context_compressor = SimpleNamespace(_last_compress_aborted=False)
            self.shutdown_memory_provider = MagicMock()
            self.close = MagicMock()

        def _compress_context(self, *_args, **_kwargs):
            raise RuntimeError("input exceeds the context window")

    fake_run_agent.AIAgent = FailingCompressAgent

    fail_runner = make_runner(
        gateway_run,
        session_id="installed-telegram-fail",
        history=make_history(450, 20),
        row={},
    )
    assert await fail_runner._handle_message(event) == "ok"
    assert FailingCompressAgent.calls == 1
    assert fail_runner._hygiene_noop_guard == {"installed-telegram-fail": 450}

    assert await fail_runner._handle_message(event) == "ok"
    assert FailingCompressAgent.calls == 1
    assert fail_runner._run_agent.await_count == 2
    fail_runner.session_store.rewrite_transcript.assert_not_called()

    del fail_runner._hygiene_noop_guard
    fail_runner._session_db.get_meta.return_value = json.dumps({"installed-telegram-fail": 450})
    assert await fail_runner._handle_message(event) == "ok"
    assert FailingCompressAgent.calls == 1
    assert fail_runner._run_agent.await_count == 3

    fail_runner.session_store.load_transcript.return_value = make_history(476, 20)
    fail_runner._run_agent.return_value = {
        "final_response": "",
        "messages": [],
        "tools": [],
        "history_offset": 0,
        "last_prompt_tokens": 0,
        "failed": True,
        "error": "Your input exceeds the context window of this model",
    }
    response = await fail_runner._handle_message(event)
    assert FailingCompressAgent.calls == 2
    assert "older Telegram thread is too large to recover automatically" in response
    assert "_emit_warning" not in response

    print(json.dumps({
        "cursor_raw_messages": 450,
        "cursor_hygiene_calls": CursorAgent.calls,
        "cursor_delegated_to_agent": cursor_runner._run_agent.await_count,
        "failed_recovery_calls": FailingCompressAgent.calls,
        "same_count_skipped": True,
        "persisted_guard_reloaded": True,
        "growth_retried": True,
        "clean_recovery_message": True,
    }, sort_keys=True))

asyncio.run(main())
"""
    with TemporaryDirectory(prefix="elevate-telegram-hygiene-soak-") as tmp:
        env = os.environ.copy()
        env["ELEVATE_HOME"] = tmp
        env["PYTHONPATH"] = (
            str(installed_cli)
            + os.pathsep
            + env.get("PYTHONPATH", "")
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(installed_cli)],
            cwd=tmp,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"telegram hygiene soak failed: {stderr}")

    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    result.telegram_hygiene = payload
    result.pass_check(
        "telegram hygiene soak: installed _handle_message skips cursor raw history and persists retry guard"
    )


async def run_sidecar_smoke(
    *,
    installed_web_dist: Path,
    port: int,
    prompt: str,
    expected: str,
    timeout: float,
    result: SmokeResult,
) -> None:
    if websockets is None:
        raise RuntimeError("websockets package is required for sidecar smoke")

    html = fetch_text(f"http://127.0.0.1:{port}/chat?new=installed-smoke", timeout)
    token = extract_required(
        r'__ELEVATE_SESSION_TOKEN__="([^"]+)"',
        html,
        "dashboard session token",
    )
    index_asset = extract_required(
        r'src="/assets/(index-[^"]+\.js)"',
        html,
        "index asset",
    )
    result.installed_index_asset = index_asset
    result.pass_check(f"dashboard html served {index_asset}")

    index_js = fetch_text(f"http://127.0.0.1:{port}/assets/{index_asset}", timeout)
    chat_asset = extract_required(
        r"(ChatPage-[A-Za-z0-9_-]+\.js)",
        index_js,
        "ChatPage asset",
    )
    result.installed_chat_asset = chat_asset
    result.pass_check(f"index references {chat_asset}")
    check_served_assets_match_installed(installed_web_dist, result)
    check_protected_http_auth(port=port, token=token, timeout=timeout, result=result)

    next_id = 1
    final_payload: dict[str, Any] | None = None
    url = f"ws://127.0.0.1:{port}/api/ws?token={token}"

    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        async def request(method: str, params: dict[str, Any], wait: float) -> dict[str, Any]:
            nonlocal next_id, final_payload
            request_id = f"smoke-{next_id}"
            next_id += 1
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    }
                )
            )
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                msg = json.loads(raw)
                if msg.get("method") == "event":
                    ev = msg.get("params") or {}
                    typ = ev.get("type")
                    if isinstance(typ, str):
                        result.events.append(typ)
                    if typ == "message.complete":
                        payload = ev.get("payload") or {}
                        if isinstance(payload, dict):
                            final_payload = payload
                if msg.get("id") == request_id:
                    return msg
            raise TimeoutError(f"request timed out: {method}")

        create = await request("session.create", {"cols": 100}, timeout)
        create_result = create.get("result") or {}
        if not isinstance(create_result, dict):
            raise RuntimeError(f"unexpected session.create result: {create!r}")
        sidecar_session_id = create_result.get("session_id")
        persisted_session_id = create_result.get("persisted_session_id")
        if not isinstance(sidecar_session_id, str):
            raise RuntimeError(f"missing sidecar session id: {create!r}")
        result.sidecar_session_id = sidecar_session_id
        result.persisted_session_id = (
            persisted_session_id if isinstance(persisted_session_id, str) else None
        )
        result.pass_check(f"created session {result.persisted_session_id or sidecar_session_id}")

        submit = await request(
            "prompt.submit",
            {"session_id": sidecar_session_id, "text": prompt},
            min(timeout, 30),
        )
        submit_result = submit.get("result") or {}
        if (
            isinstance(submit_result, dict)
            and submit_result.get("status") == "sign_in_required"
        ):
            raise RuntimeError(
                "prompt.submit auth gated (sign_in_required); refresh the installed app license"
            )
        if not isinstance(submit_result, dict) or submit_result.get("status") != "streaming":
            raise RuntimeError(f"prompt.submit did not stream: {submit!r}")
        result.pass_check("prompt.submit returned streaming")

        deadline = time.monotonic() + timeout
        while final_payload is None and time.monotonic() < deadline:
            raw = await asyncio.wait_for(
                ws.recv(),
                timeout=max(0.1, deadline - time.monotonic()),
            )
            msg = json.loads(raw)
            if msg.get("method") != "event":
                continue
            ev = msg.get("params") or {}
            typ = ev.get("type")
            if isinstance(typ, str):
                result.events.append(typ)
            if typ == "message.complete":
                payload = ev.get("payload") or {}
                if isinstance(payload, dict):
                    final_payload = payload

        if final_payload is None:
            raise TimeoutError("message.complete did not arrive")
        final_text = final_payload.get("text") or final_payload.get("rendered")
        result.final_text = final_text if isinstance(final_text, str) else None
        if result.final_text != expected:
            raise RuntimeError(
                f"unexpected final text: {result.final_text!r} != {expected!r}"
            )
        if "usage" not in final_payload:
            raise RuntimeError("message.complete missing usage payload")
        result.pass_check("message.complete matched expected text and included usage")

        required = {"message.start", "message.delta", "message.complete"}
        missing = sorted(required - set(result.events))
        if missing:
            raise RuntimeError(f"missing event types: {', '.join(missing)}")
        result.pass_check("required streaming events observed")

        if result.persisted_session_id and result.sidecar_session_id:
            await request(
                "session.close",
                {"session_id": result.sidecar_session_id},
                min(timeout, 30),
            )
            result.pass_check("closed live sidecar session before resume")

            resumed = await request(
                "session.resume",
                {
                    "session_id": result.persisted_session_id,
                    "include_messages": True,
                    "cols": 100,
                },
                min(timeout, 30),
            )
            resumed_result = resumed.get("result") or {}
            if not isinstance(resumed_result, dict):
                raise RuntimeError(f"unexpected session.resume result: {resumed!r}")
            result.resumed_session_id = resumed_result.get("session_id")
            messages = resumed_result.get("messages")
            if not isinstance(messages, list):
                raise RuntimeError(f"session.resume missing messages: {resumed!r}")
            result.resumed_message_count = len(messages)
            if not any(
                isinstance(message, dict)
                and message.get("role") == "assistant"
                and expected in str(message.get("content") or message.get("text") or "")
                for message in messages
            ):
                raise RuntimeError("resumed transcript missing final assistant text")
            result.pass_check("session.resume reloaded final assistant text")
            if isinstance(result.resumed_session_id, str):
                await request(
                    "session.close",
                    {"session_id": result.resumed_session_id},
                    min(timeout, 30),
                )
                result.pass_check("closed resumed sidecar session")


async def run_desktop_compacted_followup_smoke(
    *,
    port: int,
    timeout: float,
    result: SmokeResult,
) -> None:
    if websockets is None:
        raise RuntimeError("websockets package is required for sidecar smoke")

    html = fetch_text(f"http://127.0.0.1:{port}/chat?new=installed-compact-smoke", timeout)
    token = extract_required(
        r'__ELEVATE_SESSION_TOKEN__="([^"]+)"',
        html,
        "dashboard session token",
    )
    url = f"ws://127.0.0.1:{port}/api/ws?token={token}"
    agent_log = Path.home() / ".elevate/logs/agent.log"
    next_id = 1
    current_complete: dict[str, Any] | None = None

    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        async def request(method: str, params: dict[str, Any], wait: float) -> dict[str, Any]:
            nonlocal next_id, current_complete
            request_id = f"compact-smoke-{next_id}"
            next_id += 1
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    }
                )
            )
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                msg = json.loads(raw)
                if msg.get("method") == "event":
                    ev = msg.get("params") or {}
                    typ = ev.get("type")
                    if isinstance(typ, str):
                        result.events.append(typ)
                    if typ == "message.complete":
                        payload = ev.get("payload") or {}
                        if isinstance(payload, dict):
                            current_complete = payload
                if msg.get("id") == request_id:
                    return msg
            raise TimeoutError(f"request timed out: {method}")

        async def submit_exact(session_id: str, text: str, expected: str) -> dict[str, Any]:
            nonlocal current_complete
            current_complete = None
            submit = await request(
                "prompt.submit",
                {"session_id": session_id, "text": text},
                min(timeout, 30),
            )
            submit_result = submit.get("result") or {}
            if (
                isinstance(submit_result, dict)
                and submit_result.get("status") == "sign_in_required"
            ):
                raise RuntimeError(
                    "prompt.submit auth gated (sign_in_required); refresh the installed app license"
                )
            if not isinstance(submit_result, dict) or submit_result.get("status") != "streaming":
                raise RuntimeError(f"prompt.submit did not stream: {submit!r}")

            deadline = time.monotonic() + timeout
            while current_complete is None and time.monotonic() < deadline:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                msg = json.loads(raw)
                if msg.get("method") != "event":
                    continue
                ev = msg.get("params") or {}
                typ = ev.get("type")
                if isinstance(typ, str):
                    result.events.append(typ)
                if typ == "message.complete":
                    payload = ev.get("payload") or {}
                    if isinstance(payload, dict):
                        current_complete = payload
            if current_complete is None:
                raise TimeoutError("message.complete did not arrive")
            final_text = current_complete.get("text") or current_complete.get("rendered")
            if final_text != expected:
                raise RuntimeError(f"unexpected final text: {final_text!r} != {expected!r}")
            if "usage" not in current_complete:
                raise RuntimeError("message.complete missing usage payload")
            return current_complete

        create = await request("session.create", {"cols": 100}, timeout)
        create_result = create.get("result") or {}
        if not isinstance(create_result, dict):
            raise RuntimeError(f"unexpected session.create result: {create!r}")
        sidecar_session_id = create_result.get("session_id")
        persisted_session_id = create_result.get("persisted_session_id")
        if not isinstance(sidecar_session_id, str):
            raise RuntimeError(f"missing sidecar session id: {create!r}")
        if not isinstance(persisted_session_id, str):
            persisted_session_id = sidecar_session_id

        setup_turns = [
            ("Reply exactly: compact setup one", "compact setup one"),
            ("Reply exactly: compact setup two", "compact setup two"),
            ("Reply exactly: compact setup three", "compact setup three"),
            ("Reply exactly: compact setup four", "compact setup four"),
        ]
        for prompt, expected in setup_turns:
            await submit_exact(sidecar_session_id, prompt, expected)

        compact_log_offset = _file_size(agent_log)
        compact = await request(
            "session.compress",
            {
                "session_id": sidecar_session_id,
                "focus_topic": "installed compacted followup smoke",
            },
            min(timeout, 120),
        )
        compact_result = compact.get("result") or {}
        if not isinstance(compact_result, dict):
            raise RuntimeError(f"unexpected session.compress result: {compact!r}")
        removed = int(compact_result.get("removed") or 0)
        if removed <= 0:
            raise RuntimeError(f"session.compress did not advance cursor: {compact!r}")

        await asyncio.sleep(0.2)
        compact_lines = _session_compaction_lines(
            agent_log, compact_log_offset, persisted_session_id
        )
        if not any("compaction.completed" in line for line in compact_lines):
            raise RuntimeError("manual compaction completed but no structured log was found")
        after_compact_offset = _file_size(agent_log)

        await request(
            "session.close",
            {"session_id": sidecar_session_id},
            min(timeout, 30),
        )

        resumed = await request(
            "session.resume",
            {
                "session_id": persisted_session_id,
                "include_messages": True,
                "cols": 100,
            },
            min(timeout, 30),
        )
        resumed_result = resumed.get("result") or {}
        if not isinstance(resumed_result, dict):
            raise RuntimeError(f"unexpected session.resume result: {resumed!r}")
        resumed_session_id = resumed_result.get("session_id")
        if not isinstance(resumed_session_id, str):
            raise RuntimeError(f"session.resume missing live session id: {resumed!r}")

        followup = await submit_exact(
            resumed_session_id,
            "Reply exactly: compacted followup ok",
            "compacted followup ok",
        )
        post_followup_compactions = _session_compaction_lines(
            agent_log, after_compact_offset, persisted_session_id
        )
        if post_followup_compactions:
            raise RuntimeError(
                "follow-up retriggered compaction after resume: "
                + " | ".join(post_followup_compactions[-3:])
            )

        await request(
            "session.close",
            {"session_id": resumed_session_id},
            min(timeout, 30),
        )

    result.desktop_compaction = {
        "persisted_session_id": persisted_session_id,
        "setup_turns": len(setup_turns),
        "removed": removed,
        "resumed_session_id": resumed_session_id,
        "followup_final_text": followup.get("text") or followup.get("rendered"),
        "manual_compaction_events": compact_lines,
        "post_followup_compaction_events": post_followup_compactions,
    }
    result.pass_check(
        "desktop compacted followup: manual compact persisted, resume+followup completed without repeat compaction"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_script())
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--prompt",
        default="Reply exactly: installed compaction smoke ok",
    )
    parser.add_argument("--expected", default="installed compaction smoke ok")
    parser.add_argument("--expected-app-version")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--skip-parity", action="store_true")
    parser.add_argument(
        "--skip-seal",
        action="store_true",
        help="Skip codesign/spctl verification for dev-only installed runtime probes.",
    )
    parser.add_argument(
        "--check-file",
        action="append",
        default=[],
        help="Extra CLI-relative file to compare, e.g. gateway/run.py.",
    )
    parser.add_argument("--skip-sidecar", action="store_true")
    parser.add_argument(
        "--telegram-fixture",
        action="store_true",
        help=(
            "Run a disposable installed-code Telegram-style compaction fixture "
            "without touching real Telegram/session data."
        ),
    )
    parser.add_argument(
        "--telegram-hygiene-soak",
        action="store_true",
        help=(
            "Run installed GatewayRunner hygiene with synthetic Telegram events "
            "and disposable state."
        ),
    )
    parser.add_argument(
        "--desktop-compacted-followup",
        action="store_true",
        help=(
            "Create a real installed desktop chat, compact it, resume it, and "
            "send a follow-up."
        ),
    )
    parser.add_argument(
        "--main-log",
        type=Path,
        default=Path.home() / "Library/Logs/Elevate/main.log",
    )
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = SmokeResult()
    started_at = datetime.now()

    repo_web_dist = args.repo_root / "cli/elevate_cli/web_dist"
    installed_cli = args.installed_app / "Contents/Resources/cli"
    installed_web_dist = installed_cli / "elevate_cli/web_dist"
    dashboard_port = args.port or read_selected_dashboard_port(args.main_log, DEFAULT_PORT)
    result.dashboard_port = dashboard_port

    if args.expected_app_version:
        actual_version = read_installed_app_version(args.installed_app)
        result.installed_app_version = actual_version
        if actual_version != args.expected_app_version:
            result.fail(
                f"installed app version mismatch: {actual_version!r} != {args.expected_app_version!r}"
            )
        else:
            result.pass_check(f"installed app version matches {args.expected_app_version}")

    if not args.skip_seal:
        run_installed_app_seal(
            installed_app=args.installed_app,
            timeout=args.timeout,
            result=result,
        )

    if not args.skip_parity:
        diffs = compare_trees(repo_web_dist, installed_web_dist)
        if diffs:
            result.fail("installed web_dist does not match repo")
            result.failures.extend(diffs)
        else:
            result.pass_check("installed web_dist matches repo")

        for value in args.check_file:
            repo_path, installed_rel = cli_relative_path(args.repo_root, value)
            installed_path = installed_cli / installed_rel
            if not repo_path.exists():
                result.fail(f"missing repo check-file: {repo_path}")
            elif not installed_path.exists():
                result.fail(f"missing installed check-file: {installed_path}")
            elif not filecmp.cmp(repo_path, installed_path, shallow=False):
                result.fail(f"installed check-file differs: {installed_rel}")
            else:
                result.pass_check(f"installed {installed_rel} matches repo")

        run_installed_whatsapp_bridge(
            installed_cli=installed_cli,
            result=result,
        )

    if args.telegram_fixture:
        try:
            run_installed_telegram_fixture(
                installed_cli=installed_cli,
                timeout=args.timeout,
                result=result,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            result.fail(str(exc))

    if args.telegram_hygiene_soak:
        try:
            run_installed_telegram_hygiene_soak(
                installed_cli=installed_cli,
                timeout=args.timeout,
                result=result,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            result.fail(str(exc))

    if not args.skip_sidecar:
        (
            result.license_authenticated,
            result.license_expired,
            result.license_status_text,
        ) = read_license_state()
        try:
            asyncio.run(
                run_sidecar_smoke(
                    installed_web_dist=installed_web_dist,
                    port=dashboard_port,
                    prompt=args.prompt,
                    expected=args.expected,
                    timeout=args.timeout,
                    result=result,
                )
            )
        except (
            OSError,
            RuntimeError,
            TimeoutError,
            urllib.error.URLError,
            asyncio.TimeoutError,
        ) as exc:
            result.fail(f"sidecar smoke failed: {exc}")

    if args.desktop_compacted_followup:
        if result.license_authenticated is None:
            (
                result.license_authenticated,
                result.license_expired,
                result.license_status_text,
            ) = read_license_state()
        try:
            asyncio.run(
                run_desktop_compacted_followup_smoke(
                    port=dashboard_port,
                    timeout=args.timeout,
                    result=result,
                )
            )
        except (
            OSError,
            RuntimeError,
            TimeoutError,
            urllib.error.URLError,
            asyncio.TimeoutError,
        ) as exc:
            result.fail(f"desktop compacted followup smoke failed: {exc}")

    result.log_hits = read_recent_log_hits(args.main_log, started_at)
    if result.log_hits:
        result.fail("fresh Electron main log contains known bad pattern")

    output_path = args.json_out
    if output_path is None:
        output_path = Path("/tmp") / f"elevate-installed-smoke-{int(time.time())}.json"
    result.output_path = str(output_path)
    output_path.write_text(
        json.dumps(result.__dict__, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    print("PASS" if result.ok else "FAIL")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
