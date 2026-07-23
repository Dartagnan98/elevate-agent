"""Adapter for the browser embedded in the Elevate desktop app.

The Electron main process publishes a loopback RPC endpoint under ELEVATE_HOME.
When it is present, the normal ``browser_*`` tools use that pane so the realtor
and the agent always see and operate the same tabs.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from elevate_constants import get_elevate_home


def _endpoint_file() -> Path:
    return get_elevate_home() / "browser-pane.json"


def is_available() -> bool:
    try:
        payload = json.loads(_endpoint_file().read_text(encoding="utf-8"))
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("port"), int)
            and bool(payload.get("token"))
        )
    except (OSError, ValueError, TypeError):
        return False


def _rpc(method: str, params: dict[str, Any], timeout: int) -> Any:
    config = json.loads(_endpoint_file().read_text(encoding="utf-8"))
    request = urllib.request.Request(
        f"http://127.0.0.1:{config['port']}/rpc",
        data=json.dumps({"method": method, "params": params}).encode("utf-8"),
        headers={
            "authorization": f"Bearer {config['token']}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read())
        except (ValueError, OSError):
            raise RuntimeError(f"browser pane RPC failed: HTTP {error.code}") from error
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload.get("result")


def _session_params(session_id: str | None) -> dict[str, Any]:
    return {"sessionKey": str(session_id or "default")}


def status(session_id: str | None, *, timeout: int = 30) -> dict[str, Any] | None:
    """Return the visible-pane state for one agent/chat session."""
    if not is_available():
        return None
    try:
        return _rpc("status", _session_params(session_id), timeout)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _active_tab(timeout: int, session_id: str | None) -> dict[str, Any]:
    session_params = _session_params(session_id)
    tabs = _rpc("list", session_params, timeout)
    if not tabs:
        tab_id = _rpc("new_tab", session_params, timeout)["tabId"]
        tabs = _rpc("list", session_params, timeout)
        return next(tab for tab in tabs if tab["id"] == tab_id)
    return next((tab for tab in tabs if tab.get("active")), tabs[0])


def _snapshot(page: dict[str, Any], compact: bool) -> tuple[str, dict[str, Any]]:
    title = str(page.get("title") or "")
    url = str(page.get("url") or "")
    lines = [f'- document "{title}"', f"  - url: {url}"]
    if not compact:
        text = str(page.get("text") or "").strip()
        if text:
            lines.extend(f"  - text: {line}" for line in text.splitlines())

    refs: dict[str, Any] = {}
    for element in page.get("elements") or []:
        if not isinstance(element, dict):
            continue
        ref = str(element.get("ref") or "")
        if not ref:
            continue
        role = str(element.get("role") or element.get("tag") or "element")
        name = str(element.get("name") or element.get("value") or "").replace('"', '\\"')
        disabled = " disabled" if element.get("disabled") else ""
        lines.append(f'  - {role} "{name}" [ref={ref}]{disabled}')
        refs[ref] = element
    return "\n".join(lines), refs


def _save_screenshot(encoded: str) -> str:
    output_dir = get_elevate_home() / "browser_screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"pane_{int(time.time() * 1000)}.png"
    output.write_bytes(base64.b64decode(encoded))
    return str(output)


def run_command(
    command: str,
    args: list[str] | None = None,
    *,
    timeout: int = 30,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Run one agent-browser-shaped command against the embedded pane.

    Returns ``None`` only when the pane endpoint is absent or stale, allowing
    the existing browser backend to remain the cross-platform fallback.
    """

    if not is_available():
        return None
    argv = list(args or [])
    session_params = _session_params(session_id)

    try:
        if command == "new_tab":
            target = argv[0] if argv else "about:blank"
            created = _rpc(
                "new_tab",
                {**session_params, "url": "about:blank"},
                timeout,
            )
            tab_id = created["tabId"]
            if target != "about:blank":
                _rpc(
                    "navigate",
                    {**session_params, "tabId": tab_id, "url": target},
                    timeout,
                )
            tabs = _rpc("list", session_params, timeout)
            tab = next((item for item in tabs if item.get("id") == tab_id), {})
            return {
                "success": True,
                "data": {
                    "tabId": tab_id,
                    "url": tab.get("url") or target,
                    "title": tab.get("title") or "",
                    "tabs": tabs,
                },
            }

        if command == "select_tab":
            if not argv:
                return {"success": False, "error": "select_tab requires a tab id"}
            tab_id = argv[0]
            result = _rpc(
                "select_tab",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            if not result.get("ok"):
                return {"success": False, "error": f"No visible browser tab named {tab_id}"}
            tabs = _rpc("list", session_params, timeout)
            tab = next((item for item in tabs if item.get("id") == tab_id), {})
            return {
                "success": True,
                "data": {
                    "tabId": tab_id,
                    "url": tab.get("url") or "",
                    "title": tab.get("title") or "",
                    "tabs": tabs,
                },
            }

        if command == "close_tab":
            tab = _active_tab(timeout, session_id)
            tab_id = argv[0] if argv else tab["id"]
            result = _rpc(
                "close_tab",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            if not result.get("ok"):
                return {"success": False, "error": f"No visible browser tab named {tab_id}"}
            tabs = _rpc("list", session_params, timeout)
            active = next((item for item in tabs if item.get("active")), {})
            return {
                "success": True,
                "data": {
                    "closedTabId": tab_id,
                    "activeTabId": active.get("id"),
                    "url": active.get("url") or "",
                    "title": active.get("title") or "",
                    "tabs": tabs,
                },
            }

        tab = _active_tab(timeout, session_id)
        tab_id = tab["id"]

        if command == "open":
            target = argv[0] if argv else "about:blank"
            result = _rpc(
                "navigate",
                {**session_params, "tabId": tab_id, "url": target},
                timeout,
            )
            page = _rpc(
                "read_page",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            return {
                "success": True,
                "data": {
                    "url": page.get("url") or result.get("url") or target,
                    "title": page.get("title") or "",
                },
            }

        if command == "snapshot":
            page = _rpc(
                "read_page",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            snapshot, refs = _snapshot(page, compact="-c" in argv)
            return {"success": True, "data": {"snapshot": snapshot, "refs": refs}}

        if command == "click":
            result = _rpc(
                "click",
                {**session_params, "tabId": tab_id, "ref": argv[0]},
                timeout,
            )
            return {"success": bool(result.get("ok")), "data": result}

        if command == "drag":
            if len(argv) < 2:
                return {"success": False, "error": "drag requires source and target refs"}
            result = _rpc(
                "drag",
                {
                    **session_params,
                    "tabId": tab_id,
                    "sourceRef": argv[0],
                    "targetRef": argv[1],
                },
                timeout,
            )
            return {"success": bool(result.get("ok")), "data": result}

        if command in {"fill", "type"}:
            if len(argv) < 2:
                return {"success": False, "error": f"{command} requires a ref and text"}
            result = _rpc(
                "fill",
                {
                    **session_params,
                    "tabId": tab_id,
                    "ref": argv[0],
                    "value": argv[1],
                },
                timeout,
            )
            return {"success": bool(result.get("ok")), "data": result}

        if command == "press":
            result = _rpc(
                "key",
                {**session_params, "tabId": tab_id, "key": argv[0]},
                timeout,
            )
            return {"success": bool(result.get("ok")), "data": result}

        if command == "scroll":
            direction = argv[0] if argv else "down"
            amount = int(argv[1]) if len(argv) > 1 else 500
            result = _rpc(
                "scroll",
                {
                    **session_params,
                    "tabId": tab_id,
                    "dy": -amount if direction == "up" else amount,
                },
                timeout,
            )
            return {"success": bool(result.get("ok")), "data": result}

        if command in {"back", "forward", "reload"}:
            result = _rpc(
                command,
                {**session_params, "tabId": tab_id},
                timeout,
            )
            return {
                "success": bool(result.get("ok")),
                "data": {"url": result.get("url") or ""},
            }

        if command == "eval":
            expression = argv[0] if argv else ""
            result = _rpc(
                "eval",
                {
                    **session_params,
                    "tabId": tab_id,
                    "expression": expression,
                },
                timeout,
            )
            return {
                "success": bool(result.get("ok")),
                "data": {"result": result.get("result")},
            }

        if command == "screenshot":
            result = _rpc(
                "screenshot",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            if not result.get("ok") or not result.get("png_base64"):
                return {"success": False, "error": "embedded browser screenshot failed"}
            return {
                "success": True,
                "data": {"path": _save_screenshot(result["png_base64"])},
            }

        if command in {"console", "errors"}:
            result = _rpc(
                "console",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            key = "messages" if command == "console" else "errors"
            return {"success": True, "data": {key: result.get(key, [])}}

        if command == "close":
            result = _rpc(
                "close_tab",
                {**session_params, "tabId": tab_id},
                timeout,
            )
            return {"success": bool(result.get("ok")), "data": result}

        if command in {"scrollintoview", "record"}:
            return {"success": True, "data": {}}

        return {"success": False, "error": f"unsupported embedded browser command: {command}"}
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    except Exception as error:
        return {"success": False, "error": str(error)}
