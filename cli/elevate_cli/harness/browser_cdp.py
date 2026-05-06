from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .redaction import sanitize_browser_snapshot

try:  # pragma: no cover - import availability is environment-specific
    import websockets
except Exception:  # pragma: no cover
    websockets = None  # type: ignore[assignment]


class BrowserWorkerError(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserTab:
    id: str
    title: str
    url: str
    type: str
    web_socket_debugger_url: str | None = None


class BrowserCDPWorker:
    """Lightweight CDP browser worker for controlled local Chrome sessions.

    This is intentionally smaller than the agent browser tool surface. It is for
    deterministic extraction/checkpoint jobs: list tabs, extract visible page
    data, and later navigate/crawl allowlisted URLs.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, allowed_domains: list[str] | None = None, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.allowed_domains = allowed_domains or []
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def list_tabs(self) -> list[BrowserTab]:
        data = self._get_json("/json/list")
        tabs: list[BrowserTab] = []
        for item in data:
            tabs.append(
                BrowserTab(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    type=item.get("type", ""),
                    web_socket_debugger_url=item.get("webSocketDebuggerUrl"),
                )
            )
        return tabs

    def select_tab(self, url_contains: str | None = None) -> BrowserTab | None:
        tabs = [tab for tab in self.list_tabs() if tab.type == "page"]
        if url_contains:
            return next((tab for tab in tabs if url_contains in tab.url), None)
        return tabs[0] if tabs else None

    def extract_tab(self, tab: BrowserTab) -> dict[str, Any]:
        if not tab.web_socket_debugger_url:
            raise BrowserWorkerError(f"Tab {tab.id} has no CDP websocket URL")
        self._assert_allowed(tab.url)
        expression = """
        (() => {
          const visibleText = document.body ? document.body.innerText : '';
          const links = Array.from(document.querySelectorAll('a[href]')).map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href
          }));
          const buttons = Array.from(document.querySelectorAll('button')).map(b => ({
            text: (b.innerText || b.textContent || b.getAttribute('aria-label') || '').trim(),
            type: b.getAttribute('type') || '',
            disabled: !!b.disabled
          })).filter(b => b.text || b.type);
          const fields = Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({
            tag: el.tagName,
            type: el.getAttribute('type') || '',
            name: el.getAttribute('name') || '',
            id: el.id || '',
            placeholder: el.getAttribute('placeholder') || '',
            value: el.getAttribute('type') === 'password' ? '' : (el.value || '')
          }));
          return {
            url: location.href,
            title: document.title,
            text: visibleText,
            links,
            buttons,
            fields,
            captured_at_ms: Date.now()
          };
        })()
        """
        result = run_async(self._evaluate(tab.web_socket_debugger_url, expression))
        remote_object = result.get("result", {}).get("result", {})
        value = remote_object.get("value")
        if value is None:
            raise BrowserWorkerError(f"CDP Runtime.evaluate returned no value: {result}")
        return sanitize_browser_snapshot(value)

    def _get_json(self, path: str) -> Any:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BrowserWorkerError(f"Unable to query Chrome CDP at {self.base_url}{path}: {exc}") from exc

    def _assert_allowed(self, url: str) -> None:
        if not self.allowed_domains:
            return
        host = urlparse(url).hostname or ""
        if not any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
            raise BrowserWorkerError(f"Blocked non-allowlisted browser URL: {url}")

    async def _evaluate(self, ws_url: str, expression: str) -> dict[str, Any]:
        if websockets is None:
            raise BrowserWorkerError("websockets package is required for CDP extraction")
        async with websockets.connect(ws_url, max_size=None, open_timeout=self.timeout, ping_interval=None) as ws:
            request = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
            }
            await ws.send(json.dumps(request))
            deadline = asyncio.get_event_loop().time() + self.timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise BrowserWorkerError("Timed out waiting for Runtime.evaluate")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                message = json.loads(raw)
                if message.get("id") == 1:
                    if "error" in message:
                        raise BrowserWorkerError(f"CDP error: {message['error']}")
                    return message


def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
