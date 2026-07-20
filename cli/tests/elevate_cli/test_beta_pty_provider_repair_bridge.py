"""Cross-process Realtor Beta provider-repair barrier regressions."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from elevate_cli.web_routes import chat_websockets as bridge


TOKEN = "local-test-token"
CHANNEL = "repair-test"
INSTANCE = "1" * 32
REPAIR_ID = "a" * 32


@pytest.fixture
def repair_client(monkeypatch):
    from elevate_cli.beta_provider_policy import clear_beta_runtime_repair_state

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    clear_beta_runtime_repair_state()
    with bridge._pty_repair_condition:
        bridge._active_pty_bridges.clear()
        bridge._pty_publishers.clear()
        bridge._pty_repair_barrier = None
        bridge._pty_repair_attempt_sequences.clear()

    app = FastAPI()
    app.include_router(
        bridge.create_chat_websocket_router(
            embedded_chat_enabled=lambda: True,
            session_token=lambda: TOKEN,
            bound_host=lambda: "127.0.0.1",
            bound_port=lambda: 9120,
            license_signed_in=lambda: True,
            resolve_chat_argv=lambda resume=None, sidecar_url=None: (
                ["/bin/true"],
                None,
                None,
            ),
            pty_bridge_class=lambda: SimpleNamespace,
            pty_unavailable_error_class=lambda: RuntimeError,
            log=SimpleNamespace(debug=lambda *_args, **_kwargs: None),
        )
    )
    with TestClient(app) as client:
        yield client
    with bridge._pty_repair_condition:
        bridge._active_pty_bridges.clear()
        bridge._pty_publishers.clear()
        bridge._pty_repair_barrier = None
        bridge._pty_repair_attempt_sequences.clear()
    clear_beta_runtime_repair_state()


def _pub_path(instance: str = INSTANCE) -> str:
    return "/api/pub?" + urlencode(
        {"token": TOKEN, "channel": CHANNEL, "instance": instance}
    )


def _hello(instance: str = INSTANCE) -> dict:
    return {
        "elevate_sidecar": "hello",
        "protocol": bridge._SIDECAR_PROTOCOL,
        "instance": instance,
    }


def _hello_ack_payload(instance: str = INSTANCE) -> str:
    return json.dumps(
        {
            "elevate_sidecar": "hello_ack",
            "protocol": bridge._SIDECAR_PROTOCOL,
            "instance": instance,
            "registered": True,
        }
    )


def _receive_hello_ack(publisher, instance: str = INSTANCE) -> dict:
    ack = publisher.receive_json()
    assert ack == {
        "elevate_sidecar": "hello_ack",
        "protocol": bridge._SIDECAR_PROTOCOL,
        "instance": instance,
        "registered": True,
    }
    return ack


def _ack(control: dict, *, ok: bool = True) -> dict:
    phase = control["phase"]
    if phase == "prepare":
        receipt = {
            "repair_id": control["repair_id"],
            "marked": 2,
            "running": 1,
            "quiesced": 2,
            "pending": 0,
        }
    elif phase == "commit":
        receipt = {
            "repair_id": control["repair_id"],
            "marked": 2,
            "rebuilt": 2,
            "pending": 0,
        }
    else:
        receipt = {"repair_id": control["repair_id"], "released": True}
    return {
        "elevate_sidecar": "ack",
        "protocol": bridge._SIDECAR_PROTOCOL,
        "instance": control["instance"],
        "repair_id": control["repair_id"],
        "attempt": control["attempt"],
        "attempt_seq": control["attempt_seq"],
        "phase": phase,
        "ok": ok,
        **({"receipt": receipt} if ok else {"error": "provider_repair_failed"}),
    }


def _thread_call(fn, *args, **kwargs):
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # surface the exact worker outcome
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def _install_active_pty() -> tuple[str, str]:
    key = (CHANNEL, INSTANCE)
    with bridge._pty_repair_condition:
        bridge._active_pty_bridges[key] = object()
        bridge._pty_repair_condition.notify_all()
    return key


@pytest.mark.parametrize("failure_stage", ["resolver", "spawn"])
def test_unexpected_pty_start_failure_releases_registry_reservation(
    monkeypatch,
    failure_stage,
):
    from elevate_cli.beta_provider_policy import clear_beta_runtime_repair_state

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    clear_beta_runtime_repair_state()
    with bridge._pty_repair_condition:
        bridge._active_pty_bridges.clear()
        bridge._pty_publishers.clear()
        bridge._pty_repair_barrier = None

    def resolve(*, resume=None, sidecar_url=None):
        if failure_stage == "resolver":
            raise ValueError("unexpected resolver failure")
        return ["/bin/true"], None, None

    class RaisingBridge:
        @classmethod
        def spawn(cls, *_args, **_kwargs):
            raise ValueError("unexpected spawn failure")

    app = FastAPI()
    app.include_router(
        bridge.create_chat_websocket_router(
            embedded_chat_enabled=lambda: True,
            session_token=lambda: TOKEN,
            bound_host=lambda: "127.0.0.1",
            bound_port=lambda: 9120,
            license_signed_in=lambda: True,
            resolve_chat_argv=resolve,
            pty_bridge_class=lambda: RaisingBridge,
            pty_unavailable_error_class=lambda: RuntimeError,
            log=SimpleNamespace(
                debug=lambda *_args, **_kwargs: None,
                exception=lambda *_args, **_kwargs: None,
            ),
        )
    )
    path = "/api/pty?" + urlencode({"token": TOKEN, "channel": CHANNEL})
    with TestClient(app) as client:
        with client.websocket_connect(path) as websocket:
            assert "could not start safely" in websocket.receive_text()

    with bridge._pty_repair_condition:
        assert bridge._active_pty_bridges == {}
        assert bridge._pty_publishers == {}


def test_active_before_hello_joins_prepare_and_reconnects_during_commit(
    repair_client,
):
    """The snapshot waits for a late hello; commit survives publisher reconnect."""
    _install_active_pty()
    prepare_thread, prepare_box = _thread_call(
        bridge.begin_exact_beta_pty_runtime_repair,
        REPAIR_ID,
        timeout_s=2,
    )

    with repair_client.websocket_connect(_pub_path()) as publisher:
        publisher.send_json(_hello())
        _receive_hello_ack(publisher)
        prepare = publisher.receive_json()
        assert prepare["phase"] == "prepare"
        publisher.send_json(_ack(prepare))
        prepare_thread.join(timeout=2)
        assert not prepare_thread.is_alive()
        assert prepare_box == {
            "result": {"repair_id": REPAIR_ID, "expected": 1, "prepared": 1}
        }

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with bridge._pty_repair_condition:
            if not bridge._pty_publishers:
                break
        time.sleep(0.01)

    commit_thread, commit_box = _thread_call(
        bridge.complete_exact_beta_pty_runtime_repair,
        REPAIR_ID,
        timeout_s=2,
    )
    with repair_client.websocket_connect(_pub_path()) as publisher:
        publisher.send_json(_hello())
        _receive_hello_ack(publisher)
        commit = publisher.receive_json()
        assert commit["phase"] == "commit"
        publisher.send_json(_ack(commit))
        release = publisher.receive_json()
        assert release["phase"] == "release"
        assert bridge._pty_input_blocked((CHANNEL, INSTANCE)) is True
        publisher.send_json(_ack(release))
        commit_thread.join(timeout=2)

    assert not commit_thread.is_alive()
    assert commit_box == {
        "result": {
            "repair_id": REPAIR_ID,
            "expected": 1,
            "completed": 1,
            "released": 1,
        }
    }
    assert bridge._pty_input_blocked((CHANNEL, INSTANCE)) is False


def test_partial_commit_failure_retries_same_generation_without_killing_pty(
    repair_client,
):
    _install_active_pty()
    with repair_client.websocket_connect(_pub_path()) as publisher:
        publisher.send_json(_hello())
        _receive_hello_ack(publisher)

        prepare_thread, prepare_box = _thread_call(
            bridge.begin_exact_beta_pty_runtime_repair,
            REPAIR_ID,
            timeout_s=2,
        )
        prepare = publisher.receive_json()
        publisher.send_json(_ack(prepare))
        prepare_thread.join(timeout=2)
        assert "error" not in prepare_box

        failed_thread, failed_box = _thread_call(
            bridge.complete_exact_beta_pty_runtime_repair,
            REPAIR_ID,
            timeout_s=2,
        )
        commit = publisher.receive_json()
        publisher.send_json(_ack(commit, ok=False))
        failed_thread.join(timeout=2)
        assert isinstance(failed_box.get("error"), RuntimeError)

        retry_prepare_thread, retry_prepare_box = _thread_call(
            bridge.begin_exact_beta_pty_runtime_repair,
            REPAIR_ID,
            timeout_s=2,
        )
        retry_prepare = publisher.receive_json()
        assert retry_prepare["phase"] == "prepare"
        # Same generation, older barrier-attempt ACK: must be ignored.
        publisher.send_json(_ack(prepare))
        time.sleep(0.05)
        assert retry_prepare_thread.is_alive()
        publisher.send_json(_ack(retry_prepare))
        retry_prepare_thread.join(timeout=2)
        assert "error" not in retry_prepare_box

        retry_commit_thread, retry_commit_box = _thread_call(
            bridge.complete_exact_beta_pty_runtime_repair,
            REPAIR_ID,
            timeout_s=2,
        )
        retry_commit = publisher.receive_json()
        assert retry_commit["phase"] == "commit"
        publisher.send_json(_ack(retry_commit))
        retry_release = publisher.receive_json()
        assert retry_release["phase"] == "release"
        publisher.send_json(_ack(retry_release))
        retry_commit_thread.join(timeout=2)
        assert "error" not in retry_commit_box

        # A duplicate from the completed barrier must not close the publisher
        # or poison the next generation.
        publisher.send_json(_ack(retry_release))
        time.sleep(0.05)
        next_id = "b" * 32
        next_prepare_thread, next_prepare_box = _thread_call(
            bridge.begin_exact_beta_pty_runtime_repair,
            next_id,
            timeout_s=2,
        )
        next_prepare = publisher.receive_json()
        assert next_prepare["repair_id"] == next_id
        publisher.send_json(_ack(next_prepare))
        next_prepare_thread.join(timeout=2)
        assert "error" not in next_prepare_box


def test_disconnect_times_out_closed_then_child_close_allows_same_id_retry(
    repair_client,
):
    key = _install_active_pty()
    thread, box = _thread_call(
        bridge.begin_exact_beta_pty_runtime_repair,
        REPAIR_ID,
        timeout_s=0.3,
    )
    with repair_client.websocket_connect(_pub_path()) as publisher:
        publisher.send_json(_hello())
        _receive_hello_ack(publisher)
        control = publisher.receive_json()
        assert control["phase"] == "prepare"
        # Disconnect without an acknowledgement. The PTY remains expected.

    thread.join(timeout=2)
    assert isinstance(box.get("error"), TimeoutError)

    bridge._remove_active_pty(key)
    assert bridge.begin_exact_beta_pty_runtime_repair(
        REPAIR_ID, timeout_s=0.5
    ) == {"repair_id": REPAIR_ID, "expected": 0, "prepared": 0}


def test_wrong_instance_and_stale_generation_cannot_poison_current_barrier(
    repair_client,
):
    _install_active_pty()
    with repair_client.websocket_connect(_pub_path()) as publisher:
        publisher.send_json(_hello("2" * 32))
        with pytest.raises(WebSocketDisconnect) as exc_info:
            publisher.receive_text()
        assert exc_info.value.code == 4400

    thread, box = _thread_call(
        bridge.begin_exact_beta_pty_runtime_repair,
        REPAIR_ID,
        timeout_s=2,
    )
    with repair_client.websocket_connect(_pub_path()) as publisher:
        publisher.send_json(_hello())
        _receive_hello_ack(publisher)
        control = publisher.receive_json()
        bad = _ack(control)
        bad["repair_id"] = "b" * 32
        bad["receipt"]["repair_id"] = "b" * 32
        publisher.send_json(bad)
        time.sleep(0.05)
        assert thread.is_alive()
        publisher.send_json(_ack(control))
    thread.join(timeout=2)
    assert "error" not in box


def test_superseding_generation_is_rejected_while_barrier_is_live(repair_client):
    key = _install_active_pty()
    thread, _box = _thread_call(
        bridge.begin_exact_beta_pty_runtime_repair,
        REPAIR_ID,
        timeout_s=2,
    )
    with pytest.raises(RuntimeError, match="another Realtor Beta PTY repair"):
        bridge.begin_exact_beta_pty_runtime_repair("b" * 32, timeout_s=0.2)
    bridge._remove_active_pty(key)
    thread.join(timeout=2)


def test_control_send_on_publisher_loop_fails_immediately_instead_of_deadlocking(
    repair_client,
):
    key = (CHANNEL, INSTANCE)

    class FakePublisher:
        async def send_text(self, _payload: str) -> None:
            pytest.fail("same-loop send must be rejected before scheduling")

    async def exercise() -> None:
        with bridge._pty_repair_condition:
            bridge._active_pty_bridges[key] = object()
            bridge._pty_repair_barrier = bridge._new_pty_barrier(REPAIR_ID)
        started = time.monotonic()
        bridge._send_control_frames(
            [(key, FakePublisher(), asyncio.get_running_loop(), "{}")],
            timeout_s=1,
        )
        assert time.monotonic() - started < 0.2
        with bridge._pty_repair_condition:
            assert bridge._pty_repair_barrier["failure"]

    asyncio.run(exercise())


def test_child_publisher_hello_and_control_ack_are_duplex(monkeypatch):
    from tui_gateway import event_publisher

    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.inbound: queue.Queue[object] = queue.Queue()

        def send(self, payload: str) -> None:
            self.sent.append(payload)

        def recv(self):
            item = self.inbound.get(timeout=2)
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self) -> None:
            self.inbound.put(RuntimeError("closed"))

    socket = FakeSocket()
    socket.inbound.put(_hello_ack_payload())
    controls: list[dict] = []
    monkeypatch.setattr(
        event_publisher,
        "ws_connect",
        lambda *_args, **_kwargs: socket,
    )
    publisher = event_publisher.WsPublisherTransport(
        "ws://127.0.0.1/api/pub",
        instance_id=INSTANCE,
        control_handler=lambda message: controls.append(message) or {
            "repair_id": message["repair_id"],
            "marked": 0,
            "running": 0,
            "quiesced": 0,
            "pending": 0,
        },
        require_registration_ack=True,
    )
    hello = json.loads(socket.sent[0])
    assert hello == _hello()
    socket.inbound.put(
        json.dumps(
            {
                "elevate_sidecar": "control",
                "protocol": bridge._SIDECAR_PROTOCOL,
                "instance": INSTANCE,
                "repair_id": REPAIR_ID,
                "attempt": "c" * 32,
                "attempt_seq": 1,
                "phase": "prepare",
            }
        )
    )
    deadline = time.monotonic() + 2
    while len(socket.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    ack = json.loads(socket.sent[1])
    assert ack["ok"] is True
    assert ack["attempt"] == "c" * 32
    assert ack["receipt"]["marked"] == 0
    assert controls[0]["phase"] == "prepare"
    publisher.close()


def test_child_publisher_reconnects_and_rehellos_same_instance(monkeypatch):
    from tui_gateway import event_publisher

    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.inbound: queue.Queue[object] = queue.Queue()
            self.closed = False

        def send(self, payload: str) -> None:
            if self.closed:
                raise ConnectionError("socket closed")
            self.sent.append(payload)

        def recv(self):
            item = self.inbound.get(timeout=2)
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self) -> None:
            self.closed = True
            self.inbound.put(ConnectionError("socket closed"))

    first, second = FakeSocket(), FakeSocket()
    first.inbound.put(_hello_ack_payload())
    second.inbound.put(_hello_ack_payload())
    sockets: queue.Queue[FakeSocket] = queue.Queue()
    sockets.put(first)
    sockets.put(second)
    monkeypatch.setattr(
        event_publisher,
        "ws_connect",
        lambda *_args, **_kwargs: sockets.get(timeout=2),
    )
    publisher = event_publisher.WsPublisherTransport(
        "ws://127.0.0.1/api/pub",
        instance_id=INSTANCE,
        connect_timeout=0.05,
        control_handler=lambda message: {
            "repair_id": message["repair_id"],
            "released": True,
        },
        require_registration_ack=True,
    )
    assert json.loads(first.sent[0]) == _hello()

    first.inbound.put(ConnectionError("simulated network loss"))
    deadline = time.monotonic() + 2
    while not second.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(second.sent[0]) == _hello()

    second.inbound.put(
        json.dumps(
            {
                "elevate_sidecar": "control",
                "protocol": bridge._SIDECAR_PROTOCOL,
                "instance": INSTANCE,
                "repair_id": REPAIR_ID,
                "attempt": "d" * 32,
                "attempt_seq": 1,
                "phase": "release",
            }
        )
    )
    deadline = time.monotonic() + 2
    while len(second.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    ack = json.loads(second.sent[1])
    assert ack["ok"] is True
    assert ack["phase"] == "release"
    assert ack["instance"] == INSTANCE
    publisher.close()


def test_stable_publisher_reconnects_without_hello_ack_control_loop(
    monkeypatch,
):
    from tui_gateway import event_publisher

    class StableSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.inbound: queue.Queue[object] = queue.Queue()
            self.closed = False
            self.received = threading.Event()

        def send(self, payload: str) -> None:
            if self.closed:
                raise ConnectionError("socket closed")
            self.sent.append(payload)

        def recv(self):
            item = self.inbound.get(timeout=2)
            self.received.set()
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self) -> None:
            self.closed = True
            self.inbound.put(ConnectionError("socket closed"))

    first, second = StableSocket(), StableSocket()
    sockets: queue.Queue[StableSocket] = queue.Queue()
    sockets.put(first)
    sockets.put(second)
    connected: list[StableSocket] = []

    def connect(*_args, **_kwargs):
        socket = sockets.get(timeout=2)
        connected.append(socket)
        return socket

    controls: list[dict] = []
    monkeypatch.setattr(event_publisher, "ws_connect", connect)
    publisher = event_publisher.WsPublisherTransport(
        "ws://127.0.0.1/api/pub",
        instance_id=INSTANCE,
        connect_timeout=0.05,
        control_handler=lambda message: controls.append(message) or {},
        require_registration_ack=False,
    )

    # Stable is the legacy one-way stream. It must not send a protocol hello
    # that leaves the dashboard's hello_ack queued for the control receiver.
    assert connected == [first]
    assert first.sent == []
    first.inbound.put(_hello_ack_payload())
    assert first.received.wait(timeout=2)
    assert first.sent == []
    assert publisher.write({"type": "stable.first"}) is True
    deadline = time.monotonic() + 2
    while not first.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(first.sent[0]) == {"type": "stable.first"}

    first.inbound.put(ConnectionError("simulated Stable network loss"))
    deadline = time.monotonic() + 2
    while len(connected) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert connected == [first, second]
    assert second.sent == []
    assert publisher.write({"type": "stable.second"}) is True
    deadline = time.monotonic() + 2
    while not second.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(second.sent[0]) == {"type": "stable.second"}
    assert controls == []
    publisher.close()


def test_lost_phase_acks_reconnect_and_replay_cached_receipts(
    repair_client,
    monkeypatch,
):
    from elevate_cli.beta_provider_policy import (
        beta_runtime_repair_blocked_reason,
        clear_beta_runtime_repair_state,
    )
    from tools.delegate_tool import is_spawn_paused
    from tui_gateway import event_publisher, server

    class DropAckSocket:
        def __init__(self, drop_phase: str | None = None) -> None:
            self.drop_phase = drop_phase
            self.sent: list[str] = []
            self.inbound: queue.Queue[object] = queue.Queue()
            self.closed = False

        def send(self, payload: str) -> None:
            parsed = json.loads(payload)
            if (
                self.drop_phase
                and parsed.get("elevate_sidecar") == "ack"
                and parsed.get("phase") == self.drop_phase
            ):
                self.drop_phase = None
                self.closed = True
                raise ConnectionError("ACK lost after child side effect")
            if self.closed:
                raise ConnectionError("socket closed")
            self.sent.append(payload)

        def recv(self):
            item = self.inbound.get(timeout=2)
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self) -> None:
            self.closed = True
            self.inbound.put(ConnectionError("closed"))

    first = DropAckSocket("prepare")
    second = DropAckSocket("commit")
    third = DropAckSocket("release")
    fourth = DropAckSocket()
    sockets: queue.Queue[DropAckSocket] = queue.Queue()
    for socket in (first, second, third, fourth):
        socket.inbound.put(_hello_ack_payload())
        sockets.put(socket)
    monkeypatch.setattr(
        event_publisher,
        "ws_connect",
        lambda *_args, **_kwargs: sockets.get(timeout=2),
    )
    with server._beta_runtime_repair_targets_lock:
        server._beta_runtime_repair_targets.clear()
        server._beta_runtime_repair_completed.clear()
        server._beta_runtime_control_receipts.clear()
        server._beta_runtime_control_attempts.clear()
    clear_beta_runtime_repair_state()

    publisher = event_publisher.WsPublisherTransport(
        "ws://127.0.0.1/api/pub",
        instance_id=INSTANCE,
        connect_timeout=0.05,
        control_handler=server.handle_exact_beta_runtime_control,
        require_registration_ack=True,
    )
    attempt = "6" * 32

    def control(phase: str) -> str:
        return json.dumps(
            {
                "elevate_sidecar": "control",
                "protocol": bridge._SIDECAR_PROTOCOL,
                "instance": INSTANCE,
                "repair_id": REPAIR_ID,
                "attempt": attempt,
                "attempt_seq": 1,
                "phase": phase,
            }
        )

    first.inbound.put(control("prepare"))
    deadline = time.monotonic() + 2
    while not second.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(second.sent[0]) == _hello()
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"
    second.inbound.put(control("prepare"))
    deadline = time.monotonic() + 2
    while len(second.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(second.sent[1])["ok"] is True

    second.inbound.put(control("commit"))
    deadline = time.monotonic() + 2
    while not third.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(third.sent[0]) == _hello()
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"
    third.inbound.put(control("commit"))
    deadline = time.monotonic() + 2
    while len(third.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(third.sent[1])["receipt"]["pending"] == 0

    third.inbound.put(control("release"))
    deadline = time.monotonic() + 2
    while not fourth.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert json.loads(fourth.sent[0]) == _hello()
    assert beta_runtime_repair_blocked_reason() is None
    assert REPAIR_ID not in server._beta_runtime_delegate_repair_leases
    assert is_spawn_paused() is False
    fourth.inbound.put(control("release"))
    deadline = time.monotonic() + 2
    while len(fourth.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    replayed_release = json.loads(fourth.sent[1])
    assert replayed_release["ok"] is True
    assert replayed_release["receipt"] == {
        "repair_id": REPAIR_ID,
        "released": True,
    }
    publisher.close()
