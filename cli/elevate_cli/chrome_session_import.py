"""Import authenticated Chrome sessions into the embedded desktop browser.

Cookie values stay local: Chrome exposes them over its loopback CDP endpoint,
then the desktop pane accepts them over its authenticated loopback RPC server.
The model receives counts and status only.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from elevate_cli import debug_browser


_COOKIE_FIELDS = (
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "session",
    "sameSite",
)


def _browser_websocket_url(cdp_url: str) -> str:
    with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=5) as response:
        payload = json.loads(response.read())
    websocket_url = payload.get("webSocketDebuggerUrl")
    if not isinstance(websocket_url, str) or not websocket_url.startswith("ws"):
        raise RuntimeError("Chrome did not expose a browser debugging socket")
    return websocket_url


def _cdp_call(cdp_url: str, method: str, timeout: float = 15.0) -> dict[str, Any]:
    from websockets.sync.client import connect

    request_id = 1
    deadline = time.monotonic() + timeout
    with connect(
        _browser_websocket_url(cdp_url),
        max_size=None,
        open_timeout=min(timeout, 10),
        close_timeout=2,
        ping_interval=None,
    ) as socket:
        socket.send(json.dumps({"id": request_id, "method": method}))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Chrome did not answer {method}")
            payload = json.loads(socket.recv(timeout=remaining))
            if payload.get("id") != request_id:
                continue
            if payload.get("error"):
                message = payload["error"].get("message") or str(payload["error"])
                raise RuntimeError(f"Chrome rejected {method}: {message}")
            result = payload.get("result")
            return result if isinstance(result, dict) else {}


def _export_cookie_payload(cookies: Any) -> list[dict[str, Any]]:
    if not isinstance(cookies, list):
        return []
    exported: list[dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        # Electron 39 cannot preserve CHIPS partition keys. Importing one as an
        # unpartitioned cookie would broaden its scope, so leave it in Chrome.
        if cookie.get("partitionKey"):
            continue
        payload = {field: cookie[field] for field in _COOKIE_FIELDS if field in cookie}
        if payload.get("name") and payload.get("domain"):
            exported.append(payload)
    return exported


def export_chrome_cookies(*, refresh: bool = True) -> dict[str, Any]:
    """Clone the active Chrome profile and export its cookies through CDP."""

    if not debug_browser.is_supported() or debug_browser.chrome_binary() is None:
        raise RuntimeError("Google Chrome or another supported Chromium browser is not installed")

    profile = debug_browser.detect_active_profile()
    source_profile = debug_browser.profile_label(profile)
    was_running = debug_browser.cdp_is_up()

    if refresh or not (debug_browser.debug_profile_dir() / "Default").is_dir():
        debug_browser.clone_profile(profile)
    if not debug_browser.launch_chrome(wait=True):
        raise RuntimeError("The local Chrome profile clone did not start")

    try:
        try:
            result = _cdp_call(debug_browser.CDP_URL, "Storage.getCookies")
        except RuntimeError:
            result = _cdp_call(debug_browser.CDP_URL, "Network.getAllCookies")
        cookies = _export_cookie_payload(result.get("cookies"))
        return {
            "sourceProfile": source_profile,
            "cookies": cookies,
            "exported": len(cookies),
        }
    finally:
        if not was_running:
            debug_browser.stop_chrome()
