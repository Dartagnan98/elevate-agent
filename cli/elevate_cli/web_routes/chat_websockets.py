"""Chat websocket routes for the embedded dashboard terminal."""

import asyncio
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import uuid
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
_VALID_INSTANCE_RE = re.compile(r"^[a-f0-9]{32}$")
_VALID_REPAIR_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_SIDECAR_PROTOCOL = "elevate.pty-repair.v1"

# Dashboard WS auth: prefer the token carried in the WebSocket subprotocol so it
# stays OUT of the request URL — full URLs (including ?token=) land in proxy /
# tunnel access logs and browser history, and one of these tokens grants a PTY
# shell. The ?token= query is kept as a fallback for older clients. C6.
_WS_AUTH_PROTO = "elevate.auth.v1"


def _ws_auth_token(ws) -> str:
    offered = list(ws.scope.get("subprotocols") or [])
    if _WS_AUTH_PROTO in offered:
        for proto in offered:
            if proto and proto != _WS_AUTH_PROTO:
                return proto
    return ws.query_params.get("token", "")


def _ws_accept_subprotocol(ws):
    """Echo the auth marker on accept when the client offered it — a browser
    FAILS the handshake (close 1006) if a subprotocol it offered isn't echoed
    back. None when the client used the ?token= fallback (no subprotocol)."""
    return _WS_AUTH_PROTO if _WS_AUTH_PROTO in (ws.scope.get("subprotocols") or []) else None
_event_channels: dict[str, set] = {}
_event_lock = asyncio.Lock()

# The PTY child owns its Python actor in another process.  This registry turns
# the existing authenticated event publisher into a duplex repair channel so
# provider setup can fence and rebuild that actor without killing the PTY (and
# losing staged attachments).  Keys are channel + one unguessable PTY instance.
_pty_repair_condition = threading.Condition(threading.RLock())
_active_pty_bridges: dict[tuple[str, str], object | None] = {}
_pty_publishers: dict[tuple[str, str], tuple[object, asyncio.AbstractEventLoop]] = {}
_pty_repair_barrier: dict[str, object] | None = None
_pty_repair_attempt_sequences: dict[str, int] = {}
_dashboard_repair_control_plane_ready = False


def dashboard_repair_control_plane_ready() -> bool:
    """Whether this process owns the dashboard's PTY lifecycle registry."""
    return _dashboard_repair_control_plane_ready


def _exact_beta_active() -> bool:
    from elevate_constants import exact_realtor_beta_active

    return exact_realtor_beta_active()


def _validated_repair_id(value: object) -> str:
    repair_id = str(value or "").strip()
    if not _VALID_REPAIR_ID_RE.fullmatch(repair_id):
        raise ValueError("invalid Realtor Beta PTY repair generation")
    return repair_id


def _new_pty_barrier(repair_id: str) -> dict[str, object]:
    attempt_seq = _pty_repair_attempt_sequences.get(repair_id, 0) + 1
    _pty_repair_attempt_sequences[repair_id] = attempt_seq
    return {
        "repair_id": repair_id,
        "attempt": uuid.uuid4().hex,
        "attempt_seq": attempt_seq,
        "phase": "prepare",
        "expected": set(_active_pty_bridges),
        "prepared": set(),
        "completed": set(),
        "released": set(),
        "prepare_sent": set(),
        "commit_sent": set(),
        "release_sent": set(),
        "failure": None,
    }


def _control_frame(
    key: tuple[str, str],
    repair_id: str,
    attempt: str,
    attempt_seq: int,
    phase: str,
) -> str:
    return json.dumps(
        {
            "elevate_sidecar": "control",
            "protocol": _SIDECAR_PROTOCOL,
            "instance": key[1],
            "repair_id": repair_id,
            "attempt": attempt,
            "attempt_seq": attempt_seq,
            "phase": phase,
        },
        separators=(",", ":"),
    )


def _pending_control_sends_locked(
    barrier: dict[str, object], phase: str
) -> list[tuple[tuple[str, str], object, asyncio.AbstractEventLoop, str]]:
    expected = barrier["expected"]
    sent_name = {
        "prepare": "prepare_sent",
        "commit": "commit_sent",
        "release": "release_sent",
    }[phase]
    sent = barrier[sent_name]
    ready = {
        "prepare": expected,
        "commit": barrier["prepared"],
        "release": barrier["completed"],
    }[phase]
    assert isinstance(expected, set) and isinstance(sent, set) and isinstance(ready, set)
    sends = []
    for key in sorted(expected):
        if key in sent or key not in ready:
            continue
        publisher = _pty_publishers.get(key)
        if publisher is None:
            continue
        sent.add(key)
        ws, loop = publisher
        sends.append(
            (
                key,
                ws,
                loop,
                _control_frame(
                    key,
                    str(barrier["repair_id"]),
                    str(barrier["attempt"]),
                    int(barrier["attempt_seq"]),
                    phase,
                ),
            )
        )
    return sends


def _fail_pty_barrier(message: str) -> None:
    with _pty_repair_condition:
        barrier = _pty_repair_barrier
        if barrier is not None and barrier.get("failure") is None:
            barrier["failure"] = message
        _pty_repair_condition.notify_all()


def _send_control_frames(
    sends: list[tuple[tuple[str, str], object, asyncio.AbstractEventLoop, str]],
    *,
    timeout_s: float,
) -> None:
    for _key, ws, loop, payload in sends:
        try:
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                # This API is deliberately synchronous because provider setup
                # runs in its worker thread. Blocking the publisher's own loop
                # would deadlock both send and ACK; fail closed immediately if
                # a future caller violates that boundary.
                raise RuntimeError(
                    "PTY provider repair cannot block its publisher event loop"
                )
            future = asyncio.run_coroutine_threadsafe(ws.send_text(payload), loop)
            future.result(timeout=max(0.1, min(timeout_s, 5.0)))
        except Exception:
            _fail_pty_barrier("a live PTY publisher could not receive provider repair")
            return


def _wait_for_pty_barrier_phase(
    repair_id: str,
    phase: str,
    *,
    timeout_s: float,
) -> dict[str, object]:
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    target_name = {
        "prepare": "prepared",
        "commit": "completed",
        "release": "released",
    }[phase]
    while True:
        with _pty_repair_condition:
            barrier = _pty_repair_barrier
            if barrier is None or barrier.get("repair_id") != repair_id:
                raise RuntimeError("Realtor Beta PTY repair barrier was superseded")
            failure = barrier.get("failure")
            if failure:
                raise RuntimeError(str(failure))
            expected = barrier["expected"]
            achieved = barrier[target_name]
            assert isinstance(expected, set) and isinstance(achieved, set)
            if achieved == expected:
                return {
                    "repair_id": repair_id,
                    "expected": len(expected),
                    target_name: len(achieved),
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                barrier["failure"] = (
                    f"timed out waiting for live PTY provider repair {phase} receipts"
                )
                _pty_repair_condition.notify_all()
                raise TimeoutError(str(barrier["failure"]))
            sends = _pending_control_sends_locked(barrier, phase)
        _send_control_frames(sends, timeout_s=remaining)
        with _pty_repair_condition:
            _pty_repair_condition.wait(timeout=min(remaining, 0.1))


def begin_exact_beta_pty_runtime_repair(
    repair_id: str,
    *,
    timeout_s: float = 15.0,
) -> dict[str, object]:
    """Fence every dashboard-owned PTY child before provider config mutation."""
    global _pty_repair_barrier
    repair_id = _validated_repair_id(repair_id)
    if not _exact_beta_active():
        return {"repair_id": repair_id, "expected": 0, "prepared": 0}
    with _pty_repair_condition:
        current = _pty_repair_barrier
        if current is not None and current.get("repair_id") != repair_id:
            if current.get("failure") is None:
                raise RuntimeError("another Realtor Beta PTY repair is active")
        if (
            current is None
            or current.get("repair_id") != repair_id
            or current.get("failure") is not None
        ):
            _pty_repair_barrier = _new_pty_barrier(repair_id)
        barrier = _pty_repair_barrier
        assert barrier is not None
        sends = _pending_control_sends_locked(barrier, "prepare")
    _send_control_frames(sends, timeout_s=timeout_s)
    return _wait_for_pty_barrier_phase(
        repair_id, "prepare", timeout_s=timeout_s
    )


def complete_exact_beta_pty_runtime_repair(
    repair_id: str,
    *,
    timeout_s: float = 95.0,
) -> dict[str, object]:
    """Commit and wait for actual rebuilt == marked receipts from every PTY."""
    global _pty_repair_barrier
    repair_id = _validated_repair_id(repair_id)
    if not _exact_beta_active():
        return {"repair_id": repair_id, "expected": 0, "completed": 0}
    with _pty_repair_condition:
        barrier = _pty_repair_barrier
        if barrier is None or barrier.get("repair_id") != repair_id:
            raise RuntimeError("Realtor Beta PTY repair was not prepared")
        if barrier.get("failure"):
            raise RuntimeError(str(barrier["failure"]))
        if barrier["prepared"] != barrier["expected"]:
            raise RuntimeError("not every live PTY acknowledged provider repair prepare")
        barrier["phase"] = "commit"
        sends = _pending_control_sends_locked(barrier, "commit")
    _send_control_frames(sends, timeout_s=timeout_s)
    result = _wait_for_pty_barrier_phase(
        repair_id, "commit", timeout_s=timeout_s
    )
    with _pty_repair_condition:
        barrier = _pty_repair_barrier
        if barrier is None or barrier.get("repair_id") != repair_id:
            raise RuntimeError("Realtor Beta PTY release was superseded")
        barrier["phase"] = "release"
        sends = _pending_control_sends_locked(barrier, "release")
    _send_control_frames(sends, timeout_s=timeout_s)
    release_result = _wait_for_pty_barrier_phase(
        repair_id, "release", timeout_s=timeout_s
    )
    with _pty_repair_condition:
        barrier = _pty_repair_barrier
        if barrier is None or barrier.get("repair_id") != repair_id:
            raise RuntimeError("Realtor Beta PTY repair completion was superseded")
        _pty_repair_barrier = None
        _pty_repair_condition.notify_all()
    return {**result, "released": release_result["released"]}


def _sidecar_ack_identity(
    key: tuple[str, str], message: object
) -> tuple[str, str, int, str, bool]:
    if (
        not isinstance(message, dict)
        or message.get("elevate_sidecar") != "ack"
        or message.get("protocol") != _SIDECAR_PROTOCOL
        or message.get("instance") != key[1]
        or not isinstance(message.get("ok"), bool)
    ):
        raise ValueError("invalid PTY provider-repair acknowledgement")
    repair_id = _validated_repair_id(message.get("repair_id"))
    attempt = _validated_repair_id(message.get("attempt"))
    attempt_seq = message.get("attempt_seq")
    if (
        not isinstance(attempt_seq, int)
        or isinstance(attempt_seq, bool)
        or attempt_seq < 1
    ):
        raise ValueError("invalid PTY provider-repair attempt sequence")
    phase = message.get("phase")
    if phase not in {"prepare", "commit", "release"}:
        raise ValueError("invalid PTY provider-repair acknowledgement phase")
    return repair_id, attempt, attempt_seq, phase, bool(message["ok"])


def _validate_sidecar_ack(key: tuple[str, str], message: object) -> tuple[str, str]:
    repair_id, _attempt, _attempt_seq, phase, ok = _sidecar_ack_identity(
        key, message
    )
    if not ok:
        raise ValueError("PTY provider-repair acknowledgement reported failure")
    assert isinstance(message, dict)
    receipt = message.get("receipt")
    if not isinstance(receipt, dict) or receipt.get("repair_id") != repair_id:
        raise ValueError("PTY provider-repair receipt generation mismatch")
    if phase == "prepare":
        counts = [
            receipt.get("marked"),
            receipt.get("running"),
            receipt.get("quiesced"),
            receipt.get("pending"),
        ]
    elif phase == "commit":
        counts = [
            receipt.get("marked"),
            receipt.get("rebuilt"),
            receipt.get("pending"),
        ]
    else:
        counts = []
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts
    ):
        raise ValueError("PTY provider-repair receipt counts are invalid")
    if phase == "prepare" and not (
        receipt["pending"] == 0
        and receipt["quiesced"] == receipt["marked"]
    ):
        raise ValueError("PTY provider-repair did not quiesce every marked actor")
    if phase == "commit" and not (
        receipt["pending"] == 0 and receipt["rebuilt"] == receipt["marked"]
    ):
        raise ValueError("PTY provider-repair did not rebuild every marked actor")
    if phase == "release" and receipt.get("released") is not True:
        raise ValueError("PTY provider-repair release receipt is invalid")
    return repair_id, phase


def _reserve_active_pty(key: tuple[str, str]) -> bool:
    if _exact_beta_active():
        from elevate_cli.beta_provider_policy import beta_runtime_repair_blocked_reason

        if beta_runtime_repair_blocked_reason():
            return False
    with _pty_repair_condition:
        if _pty_repair_barrier is not None:
            return False
        if key in _active_pty_bridges:
            return False
        _active_pty_bridges[key] = None
        _pty_repair_condition.notify_all()
        return True


def _attach_active_pty_bridge(key: tuple[str, str], bridge: object) -> None:
    with _pty_repair_condition:
        if key not in _active_pty_bridges:
            raise RuntimeError("PTY provider-repair reservation was lost")
        _active_pty_bridges[key] = bridge
        _pty_repair_condition.notify_all()


def _remove_active_pty(key: tuple[str, str]) -> None:
    with _pty_repair_condition:
        existed = key in _active_pty_bridges
        _active_pty_bridges.pop(key, None)
        _pty_publishers.pop(key, None)
        barrier = _pty_repair_barrier
        if (
            existed
            and barrier is not None
            and key in barrier["expected"]
            and key not in barrier["completed"]
            and barrier.get("failure") is None
        ):
            barrier["failure"] = "a snapshotted live PTY closed during provider repair"
        _pty_repair_condition.notify_all()


def _pty_input_blocked(key: tuple[str, str] | None) -> bool:
    if key is None or not _exact_beta_active():
        return False
    from elevate_cli.beta_provider_policy import beta_runtime_repair_blocked_reason

    if beta_runtime_repair_blocked_reason():
        return True
    with _pty_repair_condition:
        barrier = _pty_repair_barrier
        return bool(barrier is not None and key in barrier["expected"])


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
    global _dashboard_repair_control_plane_ready
    _dashboard_repair_control_plane_ready = True
    router = APIRouter()
    _log = log

    def _build_sidecar_url(channel: str, instance: str) -> Optional[str]:
        """ws:// URL the PTY child should publish events to, or None when unbound."""
        host = bound_host()
        port = bound_port()

        if not host or not port:
            return None

        netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
        qs = urllib.parse.urlencode(
            {
                "token": session_token(),
                "channel": channel,
                "instance": instance,
            }
        )

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
        token = _ws_auth_token(ws)
        expected = session_token()
        if not hmac.compare_digest(token.encode(), expected.encode()):
            await ws.close(code=4401)
            return

        client_host = ws.client.host if ws.client else ""
        if client_host and client_host not in _LOOPBACK_HOSTS:
            await ws.close(code=4403)
            return

        await ws.accept(subprotocol=_ws_accept_subprotocol(ws))

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
        if _exact_beta_active() and not channel:
            await ws.send_text(
                "\r\n\x1b[31mChat could not start safely: missing session channel.\x1b[0m\r\n"
            )
            await ws.close(code=4400)
            return
        instance = uuid.uuid4().hex
        bridge_key = (channel, instance) if channel else None
        if bridge_key is not None and not _reserve_active_pty(bridge_key):
            await ws.send_text(
                "\r\n\x1b[38;5;215mChat is refreshing the Codex provider; retry shortly.\x1b[0m\r\n"
            )
            await ws.close(code=1013)
            return
        sidecar_url = (
            _build_sidecar_url(channel, instance) if channel else None
        )

        bridge = None
        reservation_attached = bridge_key is None
        try:
            argv, cwd, env = resolve_chat_argv(
                resume=resume,
                sidecar_url=sidecar_url,
            )
            bridge = pty_bridge_class().spawn(argv, cwd=cwd, env=env)
            if bridge_key is not None:
                _attach_active_pty_bridge(bridge_key, bridge)
                reservation_attached = True
        except SystemExit as exc:
            # _make_tui_argv calls sys.exit(1) when node/npm is missing.
            await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
            await ws.close(code=1011)
            return
        except pty_unavailable_error_class() as exc:
            await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
            await ws.close(code=1011)
            return
        except (FileNotFoundError, OSError) as exc:
            await ws.send_text(f"\r\n\x1b[31mChat failed to start: {exc}\x1b[0m\r\n")
            await ws.close(code=1011)
            return
        except Exception:
            # Resolver/plugin/spawn implementations are extension points and
            # may fail with arbitrary exceptions. Never leave their reserved
            # instance as a phantom live PTY in the repair snapshot.
            _log.exception("Chat PTY failed before repair-registry attachment")
            if bridge is not None:
                try:
                    bridge.close()
                except Exception:
                    pass
            await ws.send_text(
                "\r\n\x1b[31mChat could not start safely. Please retry.\x1b[0m\r\n"
            )
            await ws.close(code=1011)
            return
        finally:
            if bridge_key is not None and not reservation_attached:
                _remove_active_pty(bridge_key)

        assert bridge is not None

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
        repair_notice_sent = False

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

                if _pty_input_blocked(bridge_key):
                    if not repair_notice_sent:
                        await ws.send_text(
                            "\r\n\x1b[38;5;215mCodex provider refresh in progress; input is paused.\x1b[0m\r\n"
                        )
                        repair_notice_sent = True
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
            if bridge_key is not None:
                _remove_active_pty(bridge_key)


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

        token = _ws_auth_token(ws)
        if not hmac.compare_digest(token.encode(), session_token().encode()):
            await ws.close(code=4401)
            return

        client_host = ws.client.host if ws.client else ""
        if client_host and client_host not in _LOOPBACK_HOSTS:
            await ws.close(code=4403)
            return

        from tui_gateway.ws import handle_ws

        try:
            await handle_ws(ws, subprotocol=_ws_accept_subprotocol(ws))
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

        token = _ws_auth_token(ws)
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
        instance = ws.query_params.get("instance", "")
        if _exact_beta_active() and not _VALID_INSTANCE_RE.fullmatch(instance):
            await ws.close(code=4400)
            return

        await ws.accept(subprotocol=_ws_accept_subprotocol(ws))

        publisher_key: tuple[str, str] | None = None
        try:
            first_payload = await ws.receive_text()
            try:
                first_message = json.loads(first_payload)
            except (TypeError, json.JSONDecodeError):
                first_message = None

            is_hello = (
                isinstance(first_message, dict)
                and first_message.get("elevate_sidecar") == "hello"
            )
            if is_hello:
                if (
                    first_message.get("protocol") != _SIDECAR_PROTOCOL
                    or first_message.get("instance") != instance
                    or not _VALID_INSTANCE_RE.fullmatch(instance)
                ):
                    await ws.close(code=4400)
                    return
                publisher_key = (channel, instance)
                direct_payload = None
                reject_code = None
                with _pty_repair_condition:
                    if publisher_key not in _active_pty_bridges:
                        if _exact_beta_active():
                            reject_code = 4404
                        else:
                            # Stable legacy/custom sidecars are event-only and
                            # do not participate in the Beta PTY registry.
                            publisher_key = None
                    elif publisher_key in _pty_publishers:
                        reject_code = 4409
                    if publisher_key is not None and reject_code is None:
                        _pty_publishers[publisher_key] = (
                            ws,
                            asyncio.get_running_loop(),
                        )
                        barrier = _pty_repair_barrier
                        if (
                            barrier is not None
                            and publisher_key in barrier["expected"]
                        ):
                            barrier_phase = str(barrier.get("phase") or "prepare")
                            if (
                                barrier_phase == "release"
                                and publisher_key in barrier["completed"]
                            ):
                                phase = "release"
                            elif (
                                barrier_phase == "commit"
                                and publisher_key in barrier["prepared"]
                            ):
                                phase = "commit"
                            else:
                                phase = "prepare"
                            sent = barrier[f"{phase}_sent"]
                            if publisher_key not in sent:
                                sent.add(publisher_key)
                                direct_payload = _control_frame(
                                    publisher_key,
                                    str(barrier["repair_id"]),
                                    str(barrier["attempt"]),
                                    int(barrier["attempt_seq"]),
                                    phase,
                                )
                    _pty_repair_condition.notify_all()
                if reject_code is not None:
                    await ws.close(code=reject_code)
                    return
                await ws.send_text(
                    json.dumps(
                        {
                            "elevate_sidecar": "hello_ack",
                            "protocol": _SIDECAR_PROTOCOL,
                            "instance": instance,
                            "registered": publisher_key is not None,
                        },
                        separators=(",", ":"),
                    )
                )
                if direct_payload is not None:
                    await ws.send_text(direct_payload)
            elif _exact_beta_active():
                await ws.close(code=4400)
                return
            else:
                # Stable keeps accepting the historical one-way event stream.
                await _broadcast_event(channel, first_payload)

            while True:
                payload = await ws.receive_text()
                try:
                    message = json.loads(payload)
                except (TypeError, json.JSONDecodeError):
                    message = None
                if (
                    publisher_key is not None
                    and isinstance(message, dict)
                    and message.get("elevate_sidecar") == "ack"
                ):
                    try:
                        (
                            repair_id,
                            attempt,
                            attempt_seq,
                            phase,
                            ok,
                        ) = _sidecar_ack_identity(publisher_key, message)
                    except Exception:
                        await ws.close(code=4400)
                        return
                    with _pty_repair_condition:
                        barrier = _pty_repair_barrier
                        # Authenticated ACKs can arrive after timeout, retry,
                        # or aggregate completion. They describe an older
                        # barrier and must not poison the current generation.
                        if (
                            barrier is None
                            or barrier.get("repair_id") != repair_id
                            or barrier.get("attempt") != attempt
                            or barrier.get("attempt_seq") != attempt_seq
                            or publisher_key not in barrier["expected"]
                            or phase != barrier.get("phase")
                        ):
                            continue
                        if not ok:
                            barrier["failure"] = (
                                "a live PTY could not complete provider repair"
                            )
                            _pty_repair_condition.notify_all()
                            continue
                        try:
                            _validate_sidecar_ack(publisher_key, message)
                        except Exception:
                            barrier["failure"] = (
                                "a live PTY returned an invalid provider-repair receipt"
                            )
                            _pty_repair_condition.notify_all()
                            continue
                        target = barrier[
                            {
                                "prepare": "prepared",
                                "commit": "completed",
                                "release": "released",
                            }[phase]
                        ]
                        target.add(publisher_key)
                        _pty_repair_condition.notify_all()
                    continue
                await _broadcast_event(channel, payload)
        except WebSocketDisconnect:
            pass
        finally:
            if publisher_key is not None:
                with _pty_repair_condition:
                    if _pty_publishers.get(publisher_key, (None,))[0] is ws:
                        _pty_publishers.pop(publisher_key, None)
                    barrier = _pty_repair_barrier
                    if barrier is not None and publisher_key in barrier["expected"]:
                        # A publisher socket may reconnect while its PTY stays
                        # alive. Make the current phase sendable again; the
                        # exact barrier still times out fail-closed if no
                        # authenticated hello returns.
                        if publisher_key not in barrier["prepared"]:
                            barrier["prepare_sent"].discard(publisher_key)
                        if publisher_key not in barrier["completed"]:
                            barrier["commit_sent"].discard(publisher_key)
                        if publisher_key not in barrier["released"]:
                            barrier["release_sent"].discard(publisher_key)
                    _pty_repair_condition.notify_all()


    @router.websocket("/api/events")
    async def events_ws(ws: WebSocket) -> None:
        if not embedded_chat_enabled():
            await ws.close(code=4403)
            return

        token = _ws_auth_token(ws)
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

        await ws.accept(subprotocol=_ws_accept_subprotocol(ws))

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
