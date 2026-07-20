"""Best-effort WebSocket publisher transport for the PTY-side gateway.

The dashboard's `/api/pty` spawns `elevate --tui` as a child process, which
spawns its own ``tui_gateway.entry``.  Tool/reasoning/status events fire on
*that* gateway's transport — three processes removed from the dashboard
server itself.  To surface them in the dashboard sidebar (`/api/events`),
the PTY-side gateway opens a back-WS to the dashboard at startup and
mirrors every emit through this transport.

Wire protocol: ordinary dispatcher JSON frames plus authenticated
hello/control/ack frames for provider repair. Event delivery remains
best-effort and non-blocking. The control receiver reconnects and re-hellos
with the same dashboard-issued instance identity after socket loss, allowing
the dashboard to resend an unfinished repair phase without killing the PTY.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Callable, Optional

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:  # pragma: no cover - websockets is a required install path
    ws_connect = None  # type: ignore[assignment]

_log = logging.getLogger(__name__)

_DRAIN_STOP = object()

_QUEUE_MAX = 256
SIDECAR_PROTOCOL = "elevate.pty-repair.v1"
_CONTROL_PHASES = frozenset({"prepare", "commit", "release"})


class WsPublisherTransport:
    __slots__ = (
        "_url",
        "_instance_id",
        "_control_handler",
        "_connect_timeout",
        "_require_registration_ack",
        "_lock",
        "_ws",
        "_closed",
        "_q",
        "_worker",
        "_receiver",
    )

    def __init__(
        self,
        url: str,
        *,
        instance_id: str,
        control_handler: Callable[[dict], dict] | None = None,
        connect_timeout: float = 2.0,
        require_registration_ack: bool = False,
    ) -> None:
        self._url = url
        self._instance_id = instance_id
        self._control_handler = control_handler
        self._connect_timeout = connect_timeout
        self._require_registration_ack = bool(require_registration_ack)
        self._lock = threading.Lock()
        self._ws: Optional[object] = None
        self._closed = threading.Event()
        self._q: queue.Queue[object] = queue.Queue(maxsize=_QUEUE_MAX)
        self._worker: Optional[threading.Thread] = None
        self._receiver: Optional[threading.Thread] = None

        if ws_connect is None:
            self._closed.set()
            return

        # Try once synchronously so the normal path registers before the PTY
        # can accept meaningful input. The receiver keeps retrying with a
        # bounded backoff if dashboard startup or a later socket drop races us.
        self._connect()
        self._worker = threading.Thread(
            target=self._drain,
            name="elevate-ws-pub",
            daemon=True,
        )
        self._worker.start()
        self._receiver = threading.Thread(
            target=self._receive_controls,
            name="elevate-ws-pub-control",
            daemon=True,
        )
        self._receiver.start()

    def _hello_line(self) -> str:
        return json.dumps(
            {
                "elevate_sidecar": "hello",
                "protocol": SIDECAR_PROTOCOL,
                "instance": self._instance_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _connect(self) -> bool:
        if self._closed.is_set() or ws_connect is None:
            return False
        socket = None
        try:
            socket = ws_connect(
                self._url,
                open_timeout=self._connect_timeout,
                max_size=None,
            )
            if self._require_registration_ack:
                # Exact Beta participates in the authenticated duplex repair
                # protocol. Its socket is not live until the dashboard has
                # accepted this exact PTY instance into the repair registry.
                socket.send(self._hello_line())
                try:
                    raw_ack = socket.recv(timeout=self._connect_timeout)
                except TypeError:
                    # Small test/custom transports may expose only recv(). The
                    # production websockets sync client supports the timeout.
                    raw_ack = socket.recv()
                ack = json.loads(raw_ack)
                if (
                    not isinstance(ack, dict)
                    or ack.get("elevate_sidecar") != "hello_ack"
                    or ack.get("protocol") != SIDECAR_PROTOCOL
                    or ack.get("instance") != self._instance_id
                    or ack.get("registered") is not True
                ):
                    raise RuntimeError(
                        "dashboard did not acknowledge PTY repair registration"
                    )
            # Stable intentionally stays on the historical one-way event
            # stream: no hello means both current and legacy dashboards treat
            # the first outbound frame as an event. Sending a hello without
            # consuming its hello_ack made the receiver reject that valid ACK,
            # emit a malformed control ACK, and reconnect forever.
        except Exception as exc:
            _log.debug("event publisher connect failed: %s", exc)
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass
            return False
        with self._lock:
            if self._closed.is_set():
                try:
                    socket.close()
                except Exception:
                    pass
                return False
            if self._ws is not None:
                try:
                    socket.close()
                except Exception:
                    pass
                return True
            self._ws = socket
        return True

    def _disconnect(self, socket: object) -> None:
        with self._lock:
            if self._ws is socket:
                self._ws = None
        try:
            socket.close()  # type: ignore[union-attr]
        except Exception:
            pass

    def _send_on(self, socket: object, obj: dict | str) -> None:
        line = (
            obj
            if isinstance(obj, str)
            else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        )
        with self._lock:
            if self._ws is not socket:
                raise RuntimeError("event publisher socket was superseded")
            socket.send(line)  # type: ignore[union-attr]

    def _current_socket(self) -> object | None:
        with self._lock:
            return self._ws

    @property
    def connected(self) -> bool:
        return self._current_socket() is not None and not self._closed.is_set()

    def _send_now(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        socket = self._current_socket()
        if socket is None:
            raise RuntimeError("event publisher is disconnected")
        self._send_on(socket, line)

    def _receive_controls(self) -> None:
        backoff = 0.05
        while not self._closed.is_set():
            socket = self._current_socket()
            if socket is None:
                if self._connect():
                    backoff = 0.05
                    continue
                self._closed.wait(timeout=backoff)
                backoff = min(1.0, backoff * 2)
                continue
            message: object = None
            try:
                raw = socket.recv()  # type: ignore[union-attr]
                if not self._require_registration_ack:
                    # Stable is event-only. Ignore any unsolicited server
                    # frame instead of interpreting it as repair control and
                    # replying with a malformed negative ACK.
                    continue
                message = json.loads(raw)
                if (
                    not isinstance(message, dict)
                    or message.get("elevate_sidecar") != "control"
                    or message.get("protocol") != SIDECAR_PROTOCOL
                    or message.get("instance") != self._instance_id
                    or message.get("phase") not in _CONTROL_PHASES
                    or not isinstance(message.get("repair_id"), str)
                    or not isinstance(message.get("attempt"), str)
                    or not isinstance(message.get("attempt_seq"), int)
                    or isinstance(message.get("attempt_seq"), bool)
                    or message.get("attempt_seq") < 1
                ):
                    raise ValueError("invalid provider-repair control frame")
                if self._control_handler is None:
                    raise RuntimeError("provider-repair control is unavailable")
                receipt = self._control_handler(message)
                if not isinstance(receipt, dict):
                    raise RuntimeError("provider-repair control returned no receipt")
                ack = {
                    "elevate_sidecar": "ack",
                    "protocol": SIDECAR_PROTOCOL,
                    "instance": self._instance_id,
                    "repair_id": message["repair_id"],
                    "attempt": message["attempt"],
                    "attempt_seq": message["attempt_seq"],
                    "phase": message["phase"],
                    "ok": True,
                    "receipt": receipt,
                }
            except Exception as exc:
                if self._closed.is_set():
                    return
                # A receive failure is a transport break, not a failed control
                # receipt. Reconnect and re-hello; the dashboard will resend
                # the still-pending barrier phase for this exact instance.
                if not isinstance(message, dict):
                    _log.debug("event publisher receive failed: %s", exc)
                    self._disconnect(socket)
                    continue
                _log.exception("event publisher control failed")
                ack = {
                    "elevate_sidecar": "ack",
                    "protocol": SIDECAR_PROTOCOL,
                    "instance": self._instance_id,
                    "repair_id": (
                        message.get("repair_id", "")
                        if isinstance(message, dict)
                        else ""
                    ),
                    "attempt": (
                        message.get("attempt", "")
                        if isinstance(message, dict)
                        else ""
                    ),
                    "attempt_seq": (
                        message.get("attempt_seq", 0)
                        if isinstance(message, dict)
                        else 0
                    ),
                    "phase": (
                        message.get("phase", "")
                        if isinstance(message, dict)
                        else ""
                    ),
                    "ok": False,
                    "error": "provider_repair_failed",
                }
            try:
                self._send_on(socket, ack)
            except Exception as exc:
                _log.debug("event publisher control ack failed: %s", exc)
                self._disconnect(socket)

    def _drain(self) -> None:
        while True:
            item = self._q.get()
            if item is _DRAIN_STOP:
                return
            if not isinstance(item, str):
                continue
            socket = self._current_socket()
            if socket is None:
                continue
            try:
                self._send_on(socket, item)
            except Exception as exc:
                _log.debug("event publisher write failed: %s", exc)
                self._disconnect(socket)

    def write(self, obj: dict) -> bool:
        if self._closed.is_set() or self._worker is None:
            return False

        line = json.dumps(obj, ensure_ascii=False)

        try:
            self._q.put_nowait(line)

            return True
        except queue.Full:
            return False

    def close(self) -> None:
        self._closed.set()
        socket = self._current_socket()
        if socket is not None:
            self._disconnect(socket)
        w = self._worker
        if w is not None and w.is_alive():
            try:
                self._q.put_nowait(_DRAIN_STOP)
            except queue.Full:
                # Best-effort: if the queue is wedged, the daemon thread
                # will be torn down with the process.
                pass
            w.join(timeout=3.0)
        self._worker = None
        receiver = self._receiver
        if receiver is not None and receiver.is_alive():
            receiver.join(timeout=3.0)
        self._receiver = None

        with self._lock:
            self._ws = None
