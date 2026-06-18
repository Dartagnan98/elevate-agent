#!/usr/bin/env python3
"""Smoke-test the installed Elevate dashboard/gateway runtime.

This intentionally exercises the packaged app path instead of localhost dev:

1. Compare repo web_dist with the installed app web_dist.
2. Fetch the installed dashboard HTML and discover the active asset hashes.
3. Connect to the dashboard JSON-RPC WebSocket sidecar.
4. Create a chat session, submit an exact-reply prompt, and wait for completion.
5. Scan fresh Electron logs for the stale-socket/blank-shell errors we have hit.

It does not start/patch/restart the app. Run it after the installed app is
already running on the dashboard port.
"""

from __future__ import annotations

import argparse
import asyncio
import filecmp
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover - environment guard
    websockets = None  # type: ignore[assignment]


DEFAULT_APP = Path(
    "/Users/dartagnanpatricio/Applications/Elevate.app"
)
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
    installed_index_asset: str | None = None
    installed_chat_asset: str | None = None
    persisted_session_id: str | None = None
    sidecar_session_id: str | None = None
    final_text: str | None = None
    log_hits: list[str] = field(default_factory=list)
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


def extract_required(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"could not find {label}")
    return match.group(1)


def read_recent_log_hits(path: Path, since: datetime) -> list[str]:
    if not path.exists():
        return []

    hits: list[str] = []
    line_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = line_re.match(line)
        if match:
            try:
                stamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if stamp < since.replace(microsecond=0):
                continue
        if any(pattern in line for pattern in BAD_LOG_PATTERNS):
            hits.append(line.strip())
    return hits[-20:]


async def run_sidecar_smoke(
    *,
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_script())
    parser.add_argument("--port", type=int, default=9120)
    parser.add_argument(
        "--prompt",
        default="Reply exactly: installed compaction smoke ok",
    )
    parser.add_argument("--expected", default="installed compaction smoke ok")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--skip-parity", action="store_true")
    parser.add_argument(
        "--check-file",
        action="append",
        default=[],
        help="Extra CLI-relative file to compare, e.g. gateway/run.py.",
    )
    parser.add_argument("--skip-sidecar", action="store_true")
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

    if not args.skip_sidecar:
        try:
            asyncio.run(
                run_sidecar_smoke(
                    port=args.port,
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
