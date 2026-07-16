"""Deterministic adversarial coverage for gateway Stop/close boundaries.

These tests intentionally drive the public JSON-RPC methods.  They guard the
single cancellation primitive, exact turn fence, process scope, deferred actor
teardown, queued-steer boundary, and late interactive-prompt registration.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

from agent.turn_fence import TurnFence
from elevate_state import SessionDB
from tui_gateway import server


class _InterruptAgent:
    model = "test/model"
    base_url = ""
    api_key = ""

    def __init__(self) -> None:
        self.interrupt_calls = 0

    def interrupt(self) -> None:
        self.interrupt_calls += 1


def _live_session(agent, session_key: str = "stop-session") -> dict:
    return {
        "agent": agent,
        "session_key": session_key,
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "turn_fence": TurnFence(),
        "turn_token": None,
        "attached_images": [],
        "attached_videos": [],
        "attached_files": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        "running_tools": {},
        "events": [],
        "events_lock": threading.Lock(),
    }


@pytest.fixture(autouse=True)
def _isolate_gateway_state(monkeypatch):
    server._sessions.clear()
    server._active_prompt_claims.clear()
    with server._pending_lock:
        server._pending.clear()
        server._answers.clear()
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")
    monkeypatch.setattr(server, "_license_signed_in", lambda: True)
    monkeypatch.setattr(server, "_record_backend_event", lambda *_a, **_kw: None)
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    yield
    server._sessions.clear()
    server._active_prompt_claims.clear()
    with server._pending_lock:
        for _rid, (_sid, event) in list(server._pending.items()):
            event.set()
        server._pending.clear()
        server._answers.clear()


def _install_process_registry(monkeypatch):
    calls: list[dict] = []

    class _Registry:
        def kill_all(self, **kwargs):
            calls.append(dict(kwargs))
            return 1

    fake_module = types.ModuleType("tools.process_registry")
    fake_module.process_registry = _Registry()
    monkeypatch.setitem(sys.modules, "tools.process_registry", fake_module)
    return calls


@pytest.mark.parametrize(
    ("method", "extra_params"),
    [
        ("session.stop", {}),
        ("session.interrupt", {}),
        ("command.dispatch", {"name": "stop"}),
        ("slash.exec", {"command": "/stop"}),
    ],
    ids=["session-stop", "session-interrupt", "command-stop", "slash-stop"],
)
def test_all_stop_entrypoints_cancel_exact_turn_and_kill_only_session_processes(
    monkeypatch,
    method,
    extra_params,
):
    process_calls = _install_process_registry(monkeypatch)
    agent = _InterruptAgent()
    session = _live_session(agent, session_key="actor-A")
    fence = session["turn_fence"]
    token = fence.begin_turn("accepted-prompt-A", "gateway-worker-A")
    fence.bind_worker(token)
    session["turn_token"] = token
    session["running"] = True
    server._sessions["sid-A"] = session
    server._sessions["sid-B"] = _live_session(
        _InterruptAgent(), session_key="actor-B"
    )

    response = server.handle_request(
        {
            "id": f"rpc-{method}",
            "method": method,
            "params": {"session_id": "sid-A", **extra_params},
        }
    )

    assert "error" not in response
    stop_result = response["result"].get("stop", response["result"])
    assert stop_result["status"] == "stopping"
    assert stop_result["quiesced"] is False
    assert stop_result["running"] is True
    assert stop_result["killed"] == 1
    assert fence.snapshot()["cancelled"] is True
    assert fence.snapshot()["generation"] == token.generation
    assert fence.snapshot()["prompt_id"] == "accepted-prompt-A"
    assert process_calls == [{"session_key": "actor-A"}]
    assert agent.interrupt_calls == 1
    assert server._sessions["sid-B"]["running"] is False

    fence.finish_worker(token, terminal_status="interrupted")


class _QueuedSteerAgent:
    model = "test/model"
    base_url = ""
    api_key = ""

    def __init__(self) -> None:
        self.calls = 0
        self.interrupt_calls = 0

    def interrupt(self) -> None:
        self.interrupt_calls += 1

    def run_conversation(self, _prompt, conversation_history=None, **kwargs):
        self.calls += 1
        text = "first round" if self.calls == 1 else "forbidden continuation"
        result = {
            "completed": True,
            "final_response": text,
            "messages": [
                *(conversation_history or []),
                {
                    "role": "assistant",
                    "content": text,
                    "client_message_id": kwargs["assistant_message_id"],
                },
            ],
        }
        if self.calls == 1:
            result["pending_steer"] = "run the queued correction"
        return result


def _configure_prompt_gateway(monkeypatch, tmp_path, agent, emitted):
    db = SessionDB(db_path=tmp_path / "stop-adversarial.db")
    db.create_session("stop-session", source="tui")
    session = _live_session(agent)
    server._sessions["sid"] = session
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *_a: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _text, _cols: None)
    monkeypatch.setattr(server, "_voice_tts_enabled", lambda: False)
    monkeypatch.setattr(server, "_record_tui_turn_usage", lambda **_kw: None)
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event, sid, payload=None, **_kw: emitted.append(
            (event, sid, payload)
        )
        or True,
    )
    return db, session


def _submit(message_id: str) -> dict:
    return server.handle_request(
        {
            "id": f"rpc-{message_id}",
            "method": "prompt.submit",
            "params": {
                "session_id": "sid",
                "text": "Prepare the listing",
                "user_message_id": message_id,
            },
        }
    )


def test_stop_after_queued_steer_never_projects_or_starts_followup(
    monkeypatch,
    tmp_path,
):
    emitted: list[tuple] = []
    agent = _QueuedSteerAgent()
    db, session = _configure_prompt_gateway(monkeypatch, tmp_path, agent, emitted)
    process_calls = _install_process_registry(monkeypatch)
    followup_decided = threading.Event()
    allow_projection = threading.Event()
    terminal_projected = threading.Event()
    usage_calls = 0

    def _emit(event, sid, payload=None, **_kw):
        emitted.append((event, sid, payload))
        if event == "message.complete" and payload.get("status") == "interrupted":
            terminal_projected.set()
        return True

    monkeypatch.setattr(server, "_emit", _emit)

    def _usage(_agent):
        nonlocal usage_calls
        usage_calls += 1
        # Call 1 captures usage before the agent. Call 2 occurs after the
        # pending steer has been classified but before any followup frame.
        if usage_calls == 2:
            followup_decided.set()
            assert allow_projection.wait(timeout=3)
        return {}

    monkeypatch.setattr(server, "_get_usage", _usage)
    try:
        submitted = _submit("queued-steer-stop")
        assert "error" not in submitted, submitted
        assert submitted["result"]["status"] == "streaming"
        assert followup_decided.wait(timeout=3)

        stopped = server.handle_request(
            {
                "id": "stop-queued-steer",
                "method": "session.stop",
                "params": {"session_id": "sid"},
            }
        )
        assert stopped["result"]["status"] == "stopping"
        assert stopped["result"]["running"] is True
        allow_projection.set()
        assert terminal_projected.wait(timeout=3)
        completes = [
            payload for event, _sid, payload in emitted if event == "message.complete"
        ]
        assert len(completes) == 1
        assert completes[0]["status"] == "interrupted"
        assert "followup" not in completes[0]
        assert not any(
            event == "message.start" and payload.get("continuation") is True
            for event, _sid, payload in emitted
        )
        assert agent.calls == 1
        assert agent.interrupt_calls == 1
        assert process_calls == [{"session_key": "stop-session"}]
        receipt = db.get_prompt_receipt("stop-session", "queued-steer-stop")
        assert receipt["status"] == "interrupted"
        assert session["running"] is False
    finally:
        allow_projection.set()
        server._sessions.pop("sid", None)
        db.close()


class _ForceCloseAgent:
    model = "test/model"
    base_url = ""
    api_key = ""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.interrupt_calls = 0
        self.run_calls = 0
        self.shutdown_calls = 0
        self.shutdown_done = threading.Event()

    def interrupt(self) -> None:
        self.interrupt_calls += 1

    def shutdown_memory_provider(self) -> None:
        self.shutdown_calls += 1
        self.shutdown_done.set()

    def run_conversation(self, _prompt, conversation_history=None, **kwargs):
        self.run_calls += 1
        self.started.set()
        assert self.release.wait(timeout=3)
        return {
            "completed": True,
            "final_response": "late success must be cancelled",
            "messages": [
                *(conversation_history or []),
                {
                    "role": "assistant",
                    "content": "late success must be cancelled",
                    "client_message_id": kwargs["assistant_message_id"],
                },
            ],
        }


class _CloseCountingWorker:
    def __init__(self) -> None:
        self.close_calls = 0
        self.closed = threading.Event()

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


def test_force_close_retains_actor_until_terminal_projection_then_tears_down_once(
    monkeypatch,
    tmp_path,
):
    emitted: list[tuple] = []
    started = threading.Event()
    release = threading.Event()
    agent = _ForceCloseAgent(started, release)
    db, session = _configure_prompt_gateway(monkeypatch, tmp_path, agent, emitted)
    worker = _CloseCountingWorker()
    session["slash_worker"] = worker
    _install_process_registry(monkeypatch)
    projected_before_release: list[tuple[bool, int]] = []

    def _emit(event, sid, payload=None, **_kw):
        if event == "message.complete":
            projected_before_release.append(
                (server._sessions.get("sid") is session, agent.shutdown_calls)
            )
        emitted.append((event, sid, payload))
        return True

    monkeypatch.setattr(server, "_emit", _emit)
    try:
        submitted = _submit("force-close-running")
        assert "error" not in submitted, submitted
        assert submitted["result"]["status"] == "streaming"
        assert started.wait(timeout=3)

        closing = server.handle_request(
            {
                "id": "force-close",
                "method": "session.close",
                "params": {"session_id": "sid", "force": True},
            }
        )
        assert closing["result"] == {
            "closed": False,
            "closing": True,
            "running": True,
            "status": "stopping",
            "persisted_session_id": "stop-session",
        }
        assert server._sessions.get("sid") is session
        assert session["running"] is True
        assert session["close_after_turn"] is True
        assert session.get("agent_memory_released") is not True
        assert agent.shutdown_calls == 0
        assert worker.close_calls == 0

        release.set()
        assert worker.closed.wait(timeout=3)
        assert agent.shutdown_done.is_set()
        assert "sid" not in server._sessions
        assert projected_before_release == [(True, 0)]
        assert agent.shutdown_calls == 1
        assert worker.close_calls == 1
        assert session["agent_memory_released"] is True
        receipt = db.get_prompt_receipt("stop-session", "force-close-running")
        assert receipt["status"] == "interrupted"
        assert receipt["terminal_payload"]["status"] == "interrupted"

        already_closed = server.handle_request(
            {
                "id": "force-close-again",
                "method": "session.close",
                "params": {"session_id": "sid", "force": True},
            }
        )
        assert already_closed["result"] == {"closed": False}
        assert agent.shutdown_calls == 1
        assert worker.close_calls == 1
    finally:
        release.set()
        server._sessions.pop("sid", None)
        db.close()


@pytest.mark.parametrize(
    "event_name",
    ["clarify.request", "sudo.request", "secret.request"],
)
def test_late_interactive_prompt_registration_after_stop_is_refused(
    monkeypatch,
    event_name,
):
    _install_process_registry(monkeypatch)
    emitted: list[tuple] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda *args, **kwargs: emitted.append((args, kwargs)) or True,
    )
    agent = _InterruptAgent()
    session = _live_session(agent)
    fence = session["turn_fence"]
    token = fence.begin_turn("interactive-stop", "gateway-worker")
    fence.bind_worker(token)
    session["turn_token"] = token
    session["running"] = True
    server._sessions["sid"] = session

    stopped = server.handle_request(
        {
            "id": "stop-before-late-prompt",
            "method": "session.stop",
            "params": {"session_id": "sid"},
        }
    )
    assert stopped["result"]["status"] == "stopping"

    returned = threading.Event()
    result: list[str] = []

    def _register_late_prompt() -> None:
        result.append(
            server._block(
                event_name,
                "sid",
                {"prompt": "must not register"},
                timeout=60,
                turn_fence=fence,
                turn_token=token,
            )
        )
        returned.set()

    thread = threading.Thread(target=_register_late_prompt)
    thread.start()
    assert returned.wait(timeout=1), "late prompt registration blocked after Stop"
    thread.join(timeout=1)
    assert result == [""]
    assert emitted == []
    with server._pending_lock:
        assert not server._pending
        assert not server._answers

    fence.finish_worker(token, terminal_status="interrupted")


def test_process_stop_is_scoped_or_requires_explicit_confirmed_global(
    monkeypatch,
):
    process_calls = _install_process_registry(monkeypatch)
    server._sessions["sid"] = _live_session(
        _InterruptAgent(), session_key="process-scope"
    )

    rejected_params = [
        {},
        {"scope": "global"},
        {"confirm_global": True},
        {"scope": "session"},
    ]
    for index, params in enumerate(rejected_params):
        response = server.handle_request(
            {
                "id": f"reject-{index}",
                "method": "process.stop",
                "params": params,
            }
        )
        assert response["error"]["code"] == 4004
    assert process_calls == []

    scoped = server.handle_request(
        {
            "id": "scoped-process-stop",
            "method": "process.stop",
            "params": {"session_id": "sid"},
        }
    )
    assert scoped["result"] == {"killed": 1}
    assert process_calls == [{"session_key": "process-scope"}]

    global_stop = server.handle_request(
        {
            "id": "confirmed-global-stop",
            "method": "process.stop",
            "params": {"scope": "global", "confirm_global": True},
        }
    )
    assert global_stop["result"] == {"killed": 1}
    assert process_calls == [{"session_key": "process-scope"}, {}]
