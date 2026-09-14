"""Chat websocket routes for the embedded dashboard terminal."""

import asyncio
import hmac
import os
import re
import sys
import urllib.parse
from typing import Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from elevate_cli.pty_bridge import PtyBridge, PtyUnavailableError


EmbeddedChatEnabled = Callable[[], bool]
SessionToken = Callable[[], str]
BoundValue = Callable[[], object]
LicenseSignedIn = Callable[[], bool]
ResolveChatArgv = Callable[[Optional[str], Optional[str]], tuple[list[str], Optional[str], Optional[dict]]]
PtyBridgeClass = Callable[[], type[PtyBridge]]
PtyUnavailableErrorClass = Callable[[], type[PtyUnavailableError]]


_RESIZE_RE = re.compile(rb"\x1b\[RESIZE:(\d+);(\d+)\]")
_PTY_READ_CHUNK_TIMEOUT = 0.2
_VALID_CHANNEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_event_channels: dict[str, set] = {}
_event_lock = asyncio.Lock()


def default_resolve_chat_argv(
    resume: Optional[str] = None,
    sidecar_url: Optional[str] = None,
) -> tuple[list[str], Optional[str], Optional[dict]]:
    """Resolve the argv + cwd + env for the chat PTY.

    Default: whatever ``elevate --tui`` would run.  Tests monkeypatch this
    function to inject a tiny fake command (``cat``, ``sh -c 'printf …'``)
    so nothing has to build Node or the TUI bundle.

    Session resume is propagated via the ``ELEVATE_TUI_RESUME`` env var —
    matching what ``elevate_cli.main._launch_tui`` does for the CLI path.
    Appending ``--resume <id>`` to argv doesn't work because ``ui-tui`` does
    not parse its argv.

    `sidecar_url` (when set) is forwarded as ``ELEVATE_TUI_SIDECAR_URL`` so
    the spawned ``tui_gateway.entry`` can mirror dispatcher emits to the
    dashboard's ``/api/pub`` endpoint (see :func:`pub_ws`).
    """
    from elevate_cli.main import PROJECT_ROOT, _make_tui_argv

    argv, cwd = _make_tui_argv(PROJECT_ROOT / "ui-tui", tui_dev=False)
    env = os.environ.copy()
    env["ELEVATE_PYTHON_SRC_ROOT"] = os.environ.get(
        "ELEVATE_PYTHON_SRC_ROOT", str(PROJECT_ROOT)
    )
    env.setdefault("ELEVATE_PYTHON", sys.executable)
    env.setdefault("ELEVATE_CWD", os.getcwd())

    if resume:
        env["ELEVATE_TUI_RESUME"] = resume

    if sidecar_url:
        env["ELEVATE_TUI_SIDECAR_URL"] = sidecar_url

    return list(argv), str(cwd) if cwd else None, env



def create_chat_websocket_router(
    *,
    embedded_chat_enabled: EmbeddedChatEnabled,
    session_token: SessionToken,
    bound_host: BoundValue,
    bound_port: BoundValue,
    license_signed_in: LicenseSignedIn,
    resolve_chat_argv: ResolveChatArgv,
    pty_bridge_class: PtyBridgeClass,
    pty_unavailable_error_class: PtyUnavailableErrorClass,
    log,
) -> APIRouter:
    router = APIRouter()
    _log = log

    def _build_sidecar_url(channel: str) -> Optional[str]:
        """ws:// URL the PTY child should publish events to, or None when unbound."""
        host = bound_host()
        port = bound_port()

        if not host or not port:
            return None

        netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
        qs = urllib.parse.urlencode({"token": session_token(), "channel": channel})

        return f"ws://{netloc}/api/pub?{qs}"


    async def _broadcast_event(channel: str, payload: str) -> None:
        """Fan out one publisher frame to every subscriber on `channel`."""
        async with _event_lock:
            subs = list(_event_channels.get(channel, ()))

        for sub in subs:
            try:
                await sub.send_text(payload)
            except Exception:
                # Subscriber went away mid-send; the /api/events finally clause
                # will remove it from the registry on its next iteration.
                pass


    def _channel_or_close_code(ws: WebSocket) -> Optional[str]:
        """Return the channel id from the query string or None if invalid."""
        channel = ws.query_params.get("channel", "")

        return channel if _VALID_CHANNEL_RE.match(channel) else None


    @router.websocket("/api/pty")
    async def pty_ws(ws: WebSocket) -> None:
        if not embedded_chat_enabled():
            await ws.close(code=4403)
            return

        # --- auth + loopback check (before accept so we can close cleanly) ---
        token = ws.query_params.get("token", "")
        expected = session_token()
        if not hmac.compare_digest(token.encode(), expected.encode()):
            await ws.close(code=4401)
            return

        client_host = ws.client.host if ws.client else ""
        if client_host and client_host not in _LOOPBACK_HOSTS:
            await ws.close(code=4403)
            return

        await ws.accept()

        # --- license gate ---------------------------------------------------
        # The chat refuses to start until the user has signed in. We render a
        # short, themed banner in the terminal pane and close cleanly so the
        # user sees the message in their chat panel and clicks the link to
        # sign in. Re-opening the chat after signing in works without an
        # app restart because this check happens per-connection.
        if client_host != "testclient" and not license_signed_in():
            banner = (
                "\r\n"
                "\x1b[38;5;215m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m\r\n"
                "\x1b[1m  Sign in to start chatting\x1b[0m\r\n"
                "\r\n"
                "  Open the Sign In window from the Elevate menu\r\n"
                "  (or press \x1b[1m\xe2\x8c\x98L\x1b[0m) and use your Elevation Real\r\n"
                "  Estate HQ account. Reopen this chat when done.\r\n"
                "\x1b[38;5;215m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m\r\n"
                "\r\n"
            )
            await ws.send_text(banner)
            await ws.close(code=1000)
            return

        # --- spawn PTY ------------------------------------------------------
        resume = ws.query_params.get("resume") or None
        channel = _channel_or_close_code(ws)
        sidecar_url = _build_sidecar_url(channel) if channel else None

        try:
            argv, cwd, env = resolve_chat_argv(resume=resume, sidecar_url=sidecar_url)
        except SystemExit as exc:
            # _make_tui_argv calls sys.exit(1) when node/npm is missing.
            await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
            await ws.close(code=1011)
            return


        try:
            bridge = pty_bridge_class().spawn(argv, cwd=cwd, env=env)
        except pty_unavailable_error_class() as exc:
            await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
            await ws.close(code=1011)
            return
        except (FileNotFoundError, OSError) as exc:
            await ws.send_text(f"\r\n\x1b[31mChat failed to start: {exc}\x1b[0m\r\n")
            await ws.close(code=1011)
            return

        loop = asyncio.get_running_loop()

        # --- reader task: PTY master → WebSocket ----------------------------
        async def pump_pty_to_ws() -> None:
            while True:
                chunk = await loop.run_in_executor(
                    None, bridge.read, _PTY_READ_CHUNK_TIMEOUT
                )
                if chunk is None:  # EOF
                    return
                if not chunk:  # no data this tick; yield control and retry
                    await asyncio.sleep(0)
                    continue
                try:
                    await ws.send_bytes(chunk)
                except Exception:
                    return

        reader_task = asyncio.create_task(pump_pty_to_ws())

        # --- writer loop: WebSocket → PTY master ----------------------------
        try:
            while True:
                msg = await ws.receive()
                msg_type = msg.get("type")
                if msg_type == "websocket.disconnect":
                    break
                raw = msg.get("bytes")
                if raw is None:
                    text = msg.get("text")
                    raw = text.encode("utf-8") if isinstance(text, str) else b""
                if not raw:
                    continue

                # Resize escape is consumed locally, never written to the PTY.
                match = _RESIZE_RE.match(raw)
                if match and match.end() == len(raw):
                    cols = int(match.group(1))
                    rows = int(match.group(2))
                    bridge.resize(cols=cols, rows=rows)
                    continue

                bridge.write(raw)
        except WebSocketDisconnect:
            pass
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except (asyncio.CancelledError, Exception):
                pass
            bridge.close()


    # ---------------------------------------------------------------------------
    # /api/ws — JSON-RPC WebSocket sidecar for the dashboard "Chat" tab.
    #
    # Drives the same `tui_gateway.dispatch` surface Ink uses over stdio, so the
    # dashboard can render structured metadata (model badge, tool-call sidebar,
    # slash launcher, session info) alongside the xterm.js terminal that PTY
    # already paints. Both transports bind to the same session id when one is
    # active, so a tool.start emitted by the agent fans out to both sinks.
    # ---------------------------------------------------------------------------


    @router.websocket("/api/ws")
    async def gateway_ws(ws: WebSocket) -> None:
        if not embedded_chat_enabled():
            await ws.close(code=4403)
            return

        token = ws.query_params.get("token", "")
        if not hmac.compare_digest(token.encode(), session_token().encode()):
            await ws.close(code=4401)
            return

        client_host = ws.client.host if ws.client else ""
        if client_host and client_host not in _LOOPBACK_HOSTS:
            await ws.close(code=4403)
            return

        from tui_gateway.ws import handle_ws

        try:
            await handle_ws(ws)
        except RuntimeError as exc:
            _log.debug("Chat sidecar websocket closed before handshake completed: %s", exc)


    # ---------------------------------------------------------------------------
    # /api/pub + /api/events — chat-tab event broadcast.
    #
    # The PTY-side ``tui_gateway.entry`` opens /api/pub at startup (driven by
    # ELEVATE_TUI_SIDECAR_URL set in /api/pty's PTY env) and writes every
    # dispatcher emit through it.  The dashboard fans those frames out to any
    # subscriber that opened /api/events on the same channel id.  This is what
    # gives the React sidebar its tool-call feed without breaking the PTY
    # child's stdio handshake with Ink.
    # ---------------------------------------------------------------------------


    @router.websocket("/api/pub")
    async def pub_ws(ws: WebSocket) -> None:
        if not embedded_chat_enabled():
            await ws.close(code=4403)
            return

        token = ws.query_params.get("token", "")
        if not hmac.compare_digest(token.encode(), session_token().encode()):
            await ws.close(code=4401)
            return

        client_host = ws.client.host if ws.client else ""
        if client_host and client_host not in _LOOPBACK_HOSTS:
            await ws.close(code=4403)
            return

        channel = _channel_or_close_code(ws)
        if not channel:
            await ws.close(code=4400)
            return

        await ws.accept()

        try:
            while True:
                await _broadcast_event(channel, await ws.receive_text())
        except WebSocketDisconnect:
            pass


    @router.websocket("/api/events")
    async def events_ws(ws: WebSocket) -> None:
        if not embedded_chat_enabled():
            await ws.close(code=4403)
            return

        token = ws.query_params.get("token", "")
        if not hmac.compare_digest(token.encode(), session_token().encode()):
            await ws.close(code=4401)
            return

        client_host = ws.client.host if ws.client else ""
        if client_host and client_host not in _LOOPBACK_HOSTS:
            await ws.close(code=4403)
            return

        channel = _channel_or_close_code(ws)
        if not channel:
            await ws.close(code=4400)
            return

        await ws.accept()

        async with _event_lock:
            _event_channels.setdefault(channel, set()).add(ws)

        try:
            while True:
                # Subscribers don't speak — the receive() just blocks until
                # disconnect so the connection stays open as long as the
                # browser holds it.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            async with _event_lock:
                subs = _event_channels.get(channel)

                if subs is not None:
                    subs.discard(ws)

                    if not subs:
                        _event_channels.pop(channel, None)


    return router
