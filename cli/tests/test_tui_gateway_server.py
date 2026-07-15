import json
import os
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tui_gateway import server


@pytest.fixture(autouse=True)
def _allow_prompt_submit_without_license(monkeypatch):
    """Unit tests in this file exercise gateway RPC behavior behind the gate."""
    from elevate_cli import agent_hub
    from gateway import guardrails, usage_ledger

    monkeypatch.setattr(server, "_license_signed_in", lambda: True)
    monkeypatch.setattr(
        guardrails,
        "check_gateway_guardrails",
        lambda **_kwargs: types.SimpleNamespace(allowed=True),
    )
    monkeypatch.setattr(guardrails, "record_guardrail_block", lambda **_kwargs: None)
    monkeypatch.setattr(agent_hub, "agent_recent_activity_digest", lambda *_args: "")
    monkeypatch.setattr(usage_ledger, "record_gateway_turn", lambda **_kwargs: None)
    server._active_prompt_claims.clear()
    yield
    server._active_prompt_claims.clear()


class _ChunkyStdout:
    def __init__(self):
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        for ch in text:
            self.parts.append(ch)
            time.sleep(0.0001)
        return len(text)

    def flush(self) -> None:
        return None


class _BrokenStdout:
    def write(self, text: str) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        return None


def test_write_json_serializes_concurrent_writes(monkeypatch):
    out = _ChunkyStdout()
    monkeypatch.setattr(server, "_real_stdout", out)

    threads = [
        threading.Thread(target=server.write_json, args=({"seq": i, "text": "x" * 24},))
        for i in range(8)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    lines = "".join(out.parts).splitlines()

    assert len(lines) == 8
    assert {json.loads(line)["seq"] for line in lines} == set(range(8))


def test_write_json_returns_false_on_broken_pipe(monkeypatch):
    monkeypatch.setattr(server, "_real_stdout", _BrokenStdout())

    assert server.write_json({"ok": True}) is False


def test_exact_beta_approval_respond_requires_and_targets_request_id(monkeypatch):
    from tools import approval as approval_module

    sid = "approval-sid"
    session_key = "approval-session"
    first = approval_module._ApprovalEntry({"command": "first"})
    second = approval_module._ApprovalEntry({"command": "second"})
    server._sessions[sid] = {"session_key": session_key}
    approval_module._gateway_queues[session_key] = [first, second]
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        "elevate_cli.diagnostics.session_recorder.record_session_event",
        lambda *args, **kwargs: True,
    )

    try:
        missing = server._methods["approval.respond"](
            1,
            {"choice": "once", "session_id": sid},
        )
        assert missing["error"] == {
            "code": 4009,
            "message": "approval request id is required",
        }
        assert not first.event.is_set()
        assert not second.event.is_set()

        targeted = server._methods["approval.respond"](
            2,
            {
                "choice": "deny",
                "request_id": second.request_id,
                "session_id": sid,
            },
        )
        assert targeted["result"] == {"resolved": 1}
        assert second.event.is_set()
        assert second.result == "deny"
        assert not first.event.is_set()

        stale = server._methods["approval.respond"](
            3,
            {
                "choice": "once",
                "request_id": second.request_id,
                "session_id": sid,
            },
        )
        assert stale["error"] == {
            "code": 4009,
            "message": "no pending approval request",
        }
        assert approval_module._gateway_queues[session_key] == [first]
        assert not first.event.is_set()
    finally:
        server._sessions.pop(sid, None)
        approval_module._gateway_queues.pop(session_key, None)


def test_nonexact_tui_approval_keeps_legacy_fifo_compatibility(monkeypatch):
    from tools import approval as approval_module

    sid = "stable-approval-sid"
    session_key = "stable-approval-session"
    entry = approval_module._ApprovalEntry({"command": "legacy"})
    server._sessions[sid] = {"session_key": session_key}
    approval_module._gateway_queues[session_key] = [entry]
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.setattr(
        "elevate_cli.diagnostics.session_recorder.record_session_event",
        lambda *args, **kwargs: True,
    )

    try:
        response = server._methods["approval.respond"](
            4,
            {"choice": "once", "session_id": sid},
        )
        assert response["result"] == {"resolved": 1}
        assert entry.event.is_set()
        assert entry.result == "once"
    finally:
        server._sessions.pop(sid, None)
        approval_module._gateway_queues.pop(session_key, None)


@pytest.mark.parametrize("choice", ["session", "always"])
def test_exact_beta_approval_rejects_persistent_scopes_without_consuming_request(
    monkeypatch, choice
):
    from tools import approval as approval_module

    sid = "beta-persistent-approval-sid"
    session_key = "beta-persistent-approval-session"
    entry = approval_module._ApprovalEntry({"command": "sensitive"})
    server._sessions[sid] = {"session_key": session_key}
    approval_module._gateway_queues[session_key] = [entry]
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    try:
        response = server._methods["approval.respond"](
            5,
            {
                "choice": choice,
                "request_id": entry.request_id,
                "session_id": sid,
            },
        )

        assert response["error"] == {
            "code": 4008,
            "message": "Realtor Beta approvals apply to one request only",
        }
        assert approval_module._gateway_queues[session_key] == [entry]
        assert not entry.event.is_set()
        assert entry.result is None
    finally:
        server._sessions.pop(sid, None)
        approval_module._gateway_queues.pop(session_key, None)


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_nonexact_approval_keeps_persistent_scope_compatibility(
    monkeypatch, release_channel
):
    from tools import approval as approval_module

    sid = "compat-persistent-approval-sid"
    session_key = "compat-persistent-approval-session"
    entry = approval_module._ApprovalEntry({"command": "compat"})
    server._sessions[sid] = {"session_key": session_key}
    approval_module._gateway_queues[session_key] = [entry]
    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    monkeypatch.setattr(
        "elevate_cli.diagnostics.session_recorder.record_session_event",
        lambda *args, **kwargs: True,
    )

    try:
        response = server._methods["approval.respond"](
            6,
            {
                "choice": "session",
                "request_id": entry.request_id,
                "session_id": sid,
            },
        )

        assert response["result"] == {"resolved": 1}
        assert entry.event.is_set()
        assert entry.result == "session"
    finally:
        server._sessions.pop(sid, None)
        approval_module._gateway_queues.pop(session_key, None)


def test_debug_trace_log_redacts_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server._methods["debug.trace"](
        7,
        {
            "session_id": "sid-1",
            "payload": {
                "msg": (
                    "blank for joe@example.com token=sk-secret123 "
                    "password=hunter2 /Users/dartagnanpatricio/private/report.pdf"
                ),
                "authorization": "Bearer raw-token",
            },
        },
    )

    text = (tmp_path / "logs" / "blank-trace.log").read_text(encoding="utf-8")

    assert resp["result"] == {"ok": True}
    assert "joe@example.com" not in text
    assert "sk-secret123" not in text
    assert "hunter2" not in text
    assert "/Users/dartagnanpatricio" not in text
    assert "raw-token" not in text
    assert "[redacted-email]" in text
    assert "[redacted-secret]" in text
    assert "[path:report.pdf]" in text


def test_status_callback_emits_kind_and_text():
    with patch("tui_gateway.server._emit") as emit:
        cb = server._agent_cbs("sid")["status_callback"]
        cb("context_pressure", "85% to compaction")

    emit.assert_called_once_with(
        "status.update",
        "sid",
        {"kind": "context_pressure", "text": "85% to compaction"},
    )


def test_status_callback_accepts_single_message_argument():
    with patch("tui_gateway.server._emit") as emit:
        cb = server._agent_cbs("sid")["status_callback"]
        cb("thinking...")

    emit.assert_called_once_with(
        "status.update",
        "sid",
        {"kind": "status", "text": "thinking..."},
    )


def test_background_terminal_payload_marks_nonempty_failure_as_error():
    payload = server._agent_terminal_payload(
        {
            "final_response": "The provider failed after retries.",
            "failed": True,
            "completed": False,
        },
        task_id="bg-1",
    )

    assert payload == {
        "task_id": "bg-1",
        "status": "error",
        "text": "The provider failed after retries.",
        "error": "The provider failed after retries.",
    }


def test_background_terminal_payload_marks_async_obligation_pending():
    obligations = [
        {
            "tool": "terminal",
            "session_id": "proc-1",
            "status": "pending",
        }
    ]
    payload = server._agent_terminal_payload(
        {
            "completed": False,
            "failed": False,
            "final_response": "The terminal process is still running.",
            "partial": True,
            "pending": True,
            "pending_tool_obligations": obligations,
        },
        task_id="bg-1",
    )

    assert payload == {
        "task_id": "bg-1",
        "status": "pending",
        "text": "The terminal process is still running.",
        "warning": server._PENDING_WORK_WARNING,
        "pending_tool_obligations": obligations,
    }


def test_background_terminal_payload_marks_clarification_needs_input():
    payload = server._agent_terminal_payload(
        {
            "completed": False,
            "failed": False,
            "final_response": "Which province is the property in?",
            "needs_input": True,
            "partial": True,
            "pending": False,
        },
        task_id="bg-2",
    )

    assert payload == {
        "task_id": "bg-2",
        "status": "needs_input",
        "text": "Which province is the property in?",
        "warning": server._NEEDS_INPUT_WARNING,
    }


def test_tui_session_context_is_explicit_and_session_keyed():
    from gateway.session_context import get_session_env

    tokens = server._set_session_context(
        "session-key-1",
        correlation_id="user-turn-1",
    )
    try:
        assert get_session_env("ELEVATE_SESSION_PLATFORM") == "tui"
        assert get_session_env("ELEVATE_SESSION_CHAT_ID") == "session-key-1"
        assert get_session_env("ELEVATE_SESSION_KEY") == "session-key-1"
        assert get_session_env("ELEVATE_SESSION_CORRELATION_ID") == "user-turn-1"
        assert get_session_env("ELEVATE_SESSION_MESSAGE_ID") == ""
    finally:
        server._clear_session_context(tokens)


def test_emit_records_content_free_session_breadcrumb(monkeypatch):
    from elevate_cli.diagnostics import session_recorder

    calls = []
    monkeypatch.setattr(server, "write_json", lambda _obj: True)
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)) or True,
    )
    server._sessions["sid"] = {
        "correlation_id": "user-turn-1",
        "events_seq": 7,
    }
    try:
        server._emit(
            "message.complete",
            "sid",
            {
                "message_id": "assistant-1",
                "status": "complete",
                "text": "raw answer",
                "reasoning": "private reasoning",
                "usage": {
                    "input": 10,
                    "output": 3,
                    "reasoning": 2,
                },
            },
        )
    finally:
        server._sessions.pop("sid", None)

    assert len(calls) == 1
    event_type, kwargs = calls[0]
    assert event_type == "message.complete"
    assert kwargs["session_id"] == "sid"
    assert kwargs["correlation_id"] == "user-turn-1"
    assert kwargs["source"] == "tui_gateway"
    assert kwargs["component"] == "tui_gateway.server"
    assert kwargs["payload"] == {
        "event_seq": 7,
        "message_id": "assistant-1",
        "status": "complete",
        "input_tokens": 10,
        "output_tokens": 3,
        "reasoning_tokens": 2,
        "reasoning_chars": len("private reasoning"),
        "text_chars": len("raw answer"),
    }


def test_emit_preserves_tool_identity_under_root_correlation(monkeypatch):
    from elevate_cli.diagnostics import session_recorder

    calls = []
    monkeypatch.setattr(server, "write_json", lambda _obj: True)
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)) or True,
    )
    server._sessions["sid"] = {
        "correlation_id": "user-turn-1",
        "events_seq": 8,
    }
    try:
        server._emit(
            "tool.start",
            "sid",
            {
                "tool_id": "tool-1",
                "name": "document_search",
                "child_session_id": "child-1",
                "task_id": "task-1",
                "context": "private tool arguments",
            },
        )
    finally:
        server._sessions.pop("sid", None)

    assert calls == [
        (
            "tool.start",
            {
                "session_id": "sid",
                "correlation_id": "user-turn-1",
                "payload": {
                    "event_seq": 8,
                    "child_session_id": "child-1",
                    "task_id": "task-1",
                    "tool_id": "tool-1",
                    "tool_name": "document_search",
                },
                "source": "tui_gateway",
                "component": "tui_gateway.server",
            },
        )
    ]


def test_delayed_tool_completion_keeps_start_turn_root_after_rebind(monkeypatch):
    from elevate_cli.diagnostics import session_recorder

    recorder_calls = []
    wire_frames = []
    monkeypatch.setattr(
        server,
        "write_json",
        lambda obj: wire_frames.append(obj) or True,
    )
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: recorder_calls.append((event_type, kwargs))
        or True,
    )
    server._sessions["sid"] = _session(
        correlation_id="turn-A",
        edit_snapshots={},
        events_seq=1,
        running_tools={},
        tool_started_at={},
    )
    try:
        turn_a = server._agent_cbs("sid", correlation_id="turn-A")
        turn_a["tool_start_callback"]("tool-1", "document_search", {})
        assert server._sessions["sid"]["running_tools"]["tool-1"][
            "correlation_id"
        ] == "turn-A"

        # Turn B is now current and the reusable agent has its callbacks. The
        # late completion still resolves through tool-1's start-time snapshot.
        server._sessions["sid"]["correlation_id"] = "turn-B"
        turn_b = server._agent_cbs("sid", correlation_id="turn-B")
        turn_b["tool_complete_callback"](
            "tool-1",
            "document_search",
            {},
            json.dumps({"success": True}),
        )
    finally:
        server._sessions.pop("sid", None)

    completed_wire = next(
        frame["params"]["payload"]
        for frame in wire_frames
        if frame["params"]["type"] == "tool.complete"
    )
    assert completed_wire["correlation_id"] == "turn-A"
    completed_record = next(
        kwargs
        for event_type, kwargs in recorder_calls
        if event_type == "tool.complete"
    )
    assert completed_record["correlation_id"] == "turn-A"
    assert completed_record["payload"]["tool_id"] == "tool-1"


def test_delayed_child_progress_keeps_spawn_turn_root_after_rebind(monkeypatch):
    from elevate_cli.diagnostics import session_recorder
    from tools.delegate_tool import _build_child_progress_callback

    recorder_calls = []
    wire_frames = []
    monkeypatch.setattr(
        server,
        "write_json",
        lambda obj: wire_frames.append(obj) or True,
    )
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: recorder_calls.append((event_type, kwargs))
        or True,
    )
    agent = types.SimpleNamespace(_delegate_spinner=None)
    server._sessions["sid"] = _session(
        agent=agent,
        correlation_id="turn-A",
        events_seq=1,
    )
    try:
        server._bind_agent_turn_callbacks(
            agent,
            "sid",
            correlation_id="turn-A",
        )
        child_cb = _build_child_progress_callback(
            0,
            "prepare the CMA",
            agent,
            subagent_id="child-agent-1",
        )
        assert child_cb is not None

        server._sessions["sid"]["correlation_id"] = "turn-B"
        server._bind_agent_turn_callbacks(
            agent,
            "sid",
            correlation_id="turn-B",
        )
        child_cb(
            "subagent.complete",
            preview="done",
            status="completed",
        )
    finally:
        server._sessions.pop("sid", None)

    child_wire = next(
        frame["params"]["payload"]
        for frame in wire_frames
        if frame["params"]["type"] == "subagent.complete"
    )
    assert child_wire["correlation_id"] == "turn-A"
    child_record = next(
        kwargs
        for event_type, kwargs in recorder_calls
        if event_type == "subagent.complete"
    )
    assert child_record["correlation_id"] == "turn-A"
    assert child_record["payload"]["status"] == "completed"


def test_emit_throttles_delta_recorder(monkeypatch):
    from elevate_cli.diagnostics import session_recorder

    calls = []
    monkeypatch.setattr(server, "write_json", lambda _obj: True)
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)) or True,
    )
    server._RECORDER_DELTA_LAST.clear()
    server._sessions["sid"] = {"events_seq": 1}
    try:
        server._emit("message.delta", "sid", {"message_id": "m1", "text": "a"})
        server._emit("message.delta", "sid", {"message_id": "m1", "text": "b"})
        server._emit("message.delta", "sid", {"message_id": "m2", "text": "c"})
    finally:
        server._sessions.pop("sid", None)
        server._RECORDER_DELTA_LAST.clear()

    assert [call[0] for call in calls] == ["message.delta", "message.delta"]
    assert calls[0][1]["payload"]["message_id"] == "m1"
    assert calls[1][1]["payload"]["message_id"] == "m2"


def _capture_session_recorder(monkeypatch):
    from elevate_cli.diagnostics import session_recorder

    calls = []
    monkeypatch.setattr(
        session_recorder,
        "record_session_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)) or True,
    )
    return calls


def test_browser_tool_failure_records_friction_and_tool_error(monkeypatch):
    calls = _capture_session_recorder(monkeypatch)
    server._sessions["sid"] = _session(tool_progress_mode="off")
    try:
        server._on_tool_complete(
            "sid",
            "tool-1",
            "browser_navigate",
            {},
            json.dumps(
                {
                    "success": False,
                    "error": "Timed out opening https://secret.example/path?token=abc",
                    "browser_engine": "local",
                }
            ),
        )
    finally:
        server._sessions.pop("sid", None)

    friction = [call for call in calls if call[0] == "browser.friction_detected"]
    tool_errors = [call for call in calls if call[0] == "tool.error"]
    assert len(friction) == 1
    assert len(tool_errors) == 1
    payload = friction[0][1]["payload"]
    assert payload["tool_name"] == "browser_navigate"
    assert payload["stage"] == "navigate"
    assert payload["friction_kind"] == "timeout"
    assert payload["provider"] == "local"
    assert payload["outcome"] == "failed"
    assert "error" not in payload
    assert "url" not in payload
    assert "secret.example" not in json.dumps(payload)


def test_browser_bot_warning_records_blocked_friction(monkeypatch):
    calls = _capture_session_recorder(monkeypatch)
    server._sessions["sid"] = _session(tool_progress_mode="off")
    try:
        server._on_tool_complete(
            "sid",
            "tool-1",
            "browser_snapshot",
            {},
            json.dumps(
                {
                    "success": True,
                    "bot_detection_warning": "captcha detected on page",
                    "provider": "browser-use",
                }
            ),
        )
    finally:
        server._sessions.pop("sid", None)

    friction = [call for call in calls if call[0] == "browser.friction_detected"]
    assert len(friction) == 1
    assert friction[0][1]["payload"]["friction_kind"] == "blocked"
    assert [call[0] for call in calls].count("tool.error") == 0


def test_successful_browser_tool_records_no_friction(monkeypatch):
    calls = _capture_session_recorder(monkeypatch)
    server._sessions["sid"] = _session(tool_progress_mode="off")
    try:
        server._on_tool_complete(
            "sid",
            "tool-1",
            "browser_navigate",
            {},
            json.dumps({"success": True, "result": "ok"}),
        )
    finally:
        server._sessions.pop("sid", None)

    assert [call[0] for call in calls] == []


def test_tool_complete_emits_detected_failure(monkeypatch):
    server._sessions["sid"] = _session(
        tool_started_at={"tool-1": 10.0},
        running_tools={"tool-1": {"name": "terminal"}},
    )
    monkeypatch.setattr(server.time, "time", lambda: 12.0)
    try:
        with patch("tui_gateway.server._emit") as emit:
            server._on_tool_complete(
                "sid",
                "tool-1",
                "terminal",
                {},
                json.dumps({"exit_code": 2, "output": "command failed"}),
            )
    finally:
        server._sessions.pop("sid", None)

    emit.assert_called_once_with(
        "tool.complete",
        "sid",
        {
            "tool_id": "tool-1",
            "name": "terminal",
            "completed_at": 12.0,
            "duration_s": 2.0,
            "error": "terminal failed [exit 2]",
            "summary": "Failed in 2.0s",
        },
    )


@pytest.mark.parametrize("failed_count", [0, 3])
def test_tool_complete_keeps_successful_failed_count_successful(
    monkeypatch, failed_count
):
    server._sessions["sid"] = _session(
        tool_started_at={"tool-1": 10.0},
        running_tools={"tool-1": {"name": "leads_overview"}},
    )
    monkeypatch.setattr(server.time, "time", lambda: 12.0)
    result = json.dumps(
        {
            "success": True,
            "overview": {
                "pendingApproval": 0,
                "queued": 0,
                "sending": 0,
                "sent": 0,
                "failed": failed_count,
                "retrying": 0,
            },
        }
    )
    try:
        with patch("tui_gateway.server._emit") as emit:
            server._on_tool_complete(
                "sid", "tool-1", "leads_overview", {"recent_limit": 1}, result
            )
    finally:
        server._sessions.pop("sid", None)

    payload = emit.call_args.args[2]
    assert payload["summary"] == "Completed in 2.0s"
    assert "error" not in payload


def _session(agent=None, **extra):
    return {
        "agent": agent if agent is not None else types.SimpleNamespace(),
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        **extra,
    }


class _PromptReceiptDB:
    def __init__(self):
        self.rows = {}
        self.finish_reason_updates = []

    def prepare_prompt_receipt(
        self,
        session_id,
        content,
        *,
        assistant_message_id,
        client_message_id,
        payload,
        accepted_policy=None,
    ):
        key = (session_id, client_message_id)
        existing = self.rows.get(key)
        if existing is not None:
            if existing["content"] != content:
                raise ValueError("client_message_id already belongs to a different prompt")
            return {**existing, "inserted": False}
        row = {
            "accepted_policy": (
                accepted_policy.to_dict() if accepted_policy is not None else None
            ),
            "assistant_message_id": assistant_message_id,
            "client_message_id": client_message_id,
            "content": content,
            "effective_policy": (
                accepted_policy.to_dict() if accepted_policy is not None else None
            ),
            "owner_id": None,
            "payload": payload,
            "policy_revision": 0,
            "status": "pending",
        }
        self.rows[key] = row
        return {**row, "inserted": True}

    def claim_prompt_receipt(
        self, session_id, client_message_id, *, owner_id, reclaim_owner_id=None
    ):
        row = self.rows[(session_id, client_message_id)]
        allowed = row["status"] == "pending" or (
            row["status"] == "running" and row["owner_id"] == reclaim_owner_id
        )
        if not allowed:
            return False
        row["status"] = "running"
        row["owner_id"] = owner_id
        return True

    def finish_prompt_receipt(
        self, session_id, client_message_id, *, owner_id, status
    ):
        row = self.rows[(session_id, client_message_id)]
        if row["status"] != "running" or row["owner_id"] != owner_id:
            return False
        row["status"] = status
        return True

    def update_message_finish_reason(
        self, session_id, client_message_id, finish_reason
    ):
        self.finish_reason_updates.append(
            (session_id, client_message_id, finish_reason)
        )
        return True


def _install_prompt_receipt_db(monkeypatch):
    db = _PromptReceiptDB()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    return db


def test_reasoning_callbacks_honor_show_reasoning_toggle():
    server._sessions["sid"] = _session(show_reasoning=False)
    try:
        with patch("tui_gateway.server._emit") as emit:
            callbacks = server._agent_cbs("sid")
            callbacks["reasoning_callback"]("private thought")
            callbacks["thinking_callback"]("private thinking")
        emit.assert_not_called()

        server._sessions["sid"]["show_reasoning"] = True
        with patch("tui_gateway.server._emit") as emit:
            callbacks = server._agent_cbs("sid")
            callbacks["reasoning_callback"]("visible thought")
            callbacks["thinking_callback"]("visible thinking")

        assert [item.args for item in emit.call_args_list] == [
            ("reasoning.delta", "sid", {"text": "visible thought"}),
            ("thinking.delta", "sid", {"text": "visible thinking"}),
        ]
    finally:
        server._sessions.pop("sid", None)


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("completed", "completed"),
        ("interrupted", "interrupted"),
        ("cancelled", "interrupted"),
        ("timeout", "failed"),
        ("error", "failed"),
        ("failed", "failed"),
        (None, "failed"),
    ],
)
def test_subagent_complete_normalizes_terminal_wire_status(
    raw_status, expected
):
    server._sessions["sid"] = _session(tool_progress_mode="all")
    try:
        with patch("tui_gateway.server._emit") as emit:
            server._on_tool_progress(
                "sid",
                "subagent.complete",
                preview="finished",
                status=raw_status,
                error="detail",
            )
    finally:
        server._sessions.pop("sid", None)

    payload = emit.call_args.args[2]
    assert payload["status"] == expected
    assert payload["raw_status"] == str(raw_status or "")
    assert payload["error"] == "detail"


def test_config_set_yolo_toggles_session_scope():
    from tools.approval import clear_session, is_session_yolo_enabled

    server._sessions["sid"] = _session()
    try:
        resp_on = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )
        assert resp_on["result"]["value"] == "1"
        assert is_session_yolo_enabled("session-key") is True

        resp_off = server.handle_request(
            {
                "id": "2",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )
        assert resp_off["result"]["value"] == "0"
        assert is_session_yolo_enabled("session-key") is False
    finally:
        clear_session("session-key")
        server._sessions.clear()


def test_config_set_yolo_is_rejected_in_exact_beta(monkeypatch):
    from tools.approval import clear_session, is_session_yolo_enabled

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    server._sessions["sid"] = _session()
    try:
        response = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )

        assert response["error"]["code"] == 4008
        assert "unavailable" in response["error"]["message"].lower()
        assert is_session_yolo_enabled("session-key") is False
    finally:
        clear_session("session-key")
        server._sessions.clear()


@pytest.mark.parametrize(
    "requested",
    ["bypassPermissions", "smart", "off", "acceptEdits"],
)
def test_config_set_permission_mode_canonicalizes_unsupported_exact_beta_modes(
    monkeypatch, requested
):
    from tools.approval import clear_session, get_session_permission_mode

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    server._sessions["sid"] = _session()
    try:
        response = server.handle_request(
            {
                "id": "beta-permission-set",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "permission_mode",
                    "value": requested,
                },
            }
        )

        assert response["result"] == {
            "canonicalized": True,
            "key": "permission_mode",
            "reason": "beta_human_review_required",
            "value": "default",
        }
        assert get_session_permission_mode("session-key") == "default"
    finally:
        clear_session("session-key")
        server._sessions.clear()


@pytest.mark.parametrize("requested", ["default", "plan"])
def test_config_set_permission_mode_keeps_supported_exact_beta_modes(
    monkeypatch, requested
):
    from tools.approval import clear_session, get_session_permission_mode

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    server._sessions["sid"] = _session()
    try:
        response = server.handle_request(
            {
                "id": "beta-permission-supported",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "permission_mode",
                    "value": requested,
                },
            }
        )

        assert response["result"] == {
            "key": "permission_mode",
            "value": requested,
        }
        assert get_session_permission_mode("session-key") == requested
    finally:
        clear_session("session-key")
        server._sessions.clear()


def test_config_get_permission_mode_canonicalizes_stale_exact_beta_override(
    monkeypatch,
):
    from tools.approval import clear_session, set_session_permission_mode

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    server._sessions["sid"] = _session()
    set_session_permission_mode("session-key", "bypassPermissions")
    try:
        response = server.handle_request(
            {
                "id": "beta-permission-get",
                "method": "config.get",
                "params": {"session_id": "sid", "key": "permission_mode"},
            }
        )

        assert response["result"] == {
            "canonicalized": True,
            "reason": "beta_human_review_required",
            "value": "default",
        }
    finally:
        clear_session("session-key")
        server._sessions.clear()


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_nonexact_permission_mode_keeps_bypass_compatibility(
    monkeypatch, release_channel
):
    from tools.approval import clear_session, get_session_permission_mode

    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    server._sessions["sid"] = _session()
    try:
        response = server.handle_request(
            {
                "id": "compat-permission-set",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "permission_mode",
                    "value": "bypassPermissions",
                },
            }
        )

        assert response["result"] == {
            "key": "permission_mode",
            "value": "bypassPermissions",
        }
        assert get_session_permission_mode("session-key") == "bypassPermissions"
    finally:
        clear_session("session-key")
        server._sessions.clear()


@pytest.mark.parametrize("release_channel", [None, "Beta"])
@pytest.mark.parametrize("requested", ["smart", "off"])
def test_nonexact_permission_mode_keeps_unknown_mode_rejection(
    monkeypatch, release_channel, requested
):
    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)

    response = server.handle_request(
        {
            "id": "compat-permission-unknown",
            "method": "config.set",
            "params": {"key": "permission_mode", "value": requested},
        }
    )

    assert response["error"] == {
        "code": 4002,
        "message": f"unknown permission_mode: {requested}",
    }


def test_config_get_statusbar_survives_non_dict_display(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"display": "broken"})

    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "statusbar"}}
    )

    assert resp["result"]["value"] == "top"


def test_config_set_statusbar_survives_non_dict_display(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"display": "broken"}))
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "statusbar", "value": "bottom"},
        }
    )

    assert resp["result"]["value"] == "bottom"
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["tui_statusbar"] == "bottom"


def test_config_set_section_writes_per_section_override(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.activity", "value": "hidden"},
        }
    )

    assert resp["result"] == {"key": "details_mode.activity", "value": "hidden"}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["sections"] == {"activity": "hidden"}


def test_config_set_section_clears_override_on_empty_value(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"display": {"sections": {"activity": "hidden", "tools": "expanded"}}}
        )
    )
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.activity", "value": ""},
        }
    )

    assert resp["result"] == {"key": "details_mode.activity", "value": ""}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["sections"] == {"tools": "expanded"}


def test_config_set_section_rejects_unknown_section_or_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)

    bad_section = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.bogus", "value": "hidden"},
        }
    )
    assert bad_section["error"]["code"] == 4002

    bad_mode = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"key": "details_mode.tools", "value": "maximised"},
        }
    )
    assert bad_mode["error"]["code"] == 4002


def test_enable_gateway_prompts_sets_gateway_env(monkeypatch):
    monkeypatch.delenv("ELEVATE_EXEC_ASK", raising=False)
    monkeypatch.delenv("ELEVATE_GATEWAY_SESSION", raising=False)
    monkeypatch.delenv("ELEVATE_INTERACTIVE", raising=False)

    server._enable_gateway_prompts()

    assert server.os.environ["ELEVATE_GATEWAY_SESSION"] == "1"
    assert server.os.environ["ELEVATE_EXEC_ASK"] == "1"
    assert server.os.environ["ELEVATE_INTERACTIVE"] == "1"


def test_setup_status_reports_provider_config(monkeypatch):
    monkeypatch.setattr("elevate_cli.main._has_any_provider_configured", lambda: False)

    resp = server.handle_request({"id": "1", "method": "setup.status", "params": {}})

    assert resp["result"]["provider_configured"] is False


def test_config_set_reasoning_updates_live_session_and_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)
    agent = types.SimpleNamespace(reasoning_config=None)
    server._sessions["sid"] = _session(agent=agent)

    resp_effort = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "low"},
        }
    )
    assert resp_effort["result"]["value"] == "low"
    assert agent.reasoning_config == {"enabled": True, "effort": "low"}

    resp_show = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "show"},
        }
    )
    assert resp_show["result"]["value"] == "show"
    assert server._sessions["sid"]["show_reasoning"] is True


def test_config_set_verbose_updates_session_mode_and_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_elevate_home", tmp_path)
    agent = types.SimpleNamespace(verbose_logging=False)
    server._sessions["sid"] = _session(agent=agent)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "verbose", "value": "cycle"},
        }
    )

    assert resp["result"]["value"] == "verbose"
    assert server._sessions["sid"]["tool_progress_mode"] == "verbose"
    assert agent.verbose_logging is True


def test_config_set_model_uses_live_switch_path(monkeypatch):
    server._sessions["sid"] = _session()
    seen = {}

    def _fake_apply(sid, session, raw):
        seen["args"] = (sid, session["session_key"], raw)
        return {"value": "new/model", "warning": "catalog unreachable"}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "model", "value": "new/model"},
        }
    )

    assert resp["result"]["value"] == "new/model"
    assert resp["result"]["warning"] == "catalog unreachable"
    assert seen["args"] == ("sid", "session-key", "new/model")


def test_config_set_model_global_persists(monkeypatch):
    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-old"

        def switch_model(self, **kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="anthropic/claude-sonnet-4.6",
        target_provider="anthropic",
        api_key="sk-new",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
        warning_message="",
    )
    seen = {}
    saved = {}

    def _switch_model(**kwargs):
        seen.update(kwargs)
        return result

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr("elevate_cli.model_switch.switch_model", _switch_model)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr("elevate_cli.config.save_config", lambda cfg: saved.update(cfg))

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {
                "session_id": "sid",
                "key": "model",
                "value": "anthropic/claude-sonnet-4.6 --global",
            },
        }
    )

    assert resp["result"]["value"] == "anthropic/claude-sonnet-4.6"
    assert seen["is_global"] is True
    assert saved["model"]["default"] == "anthropic/claude-sonnet-4.6"
    assert saved["model"]["provider"] == "anthropic"
    assert saved["model"]["base_url"] == "https://api.anthropic.com"


def test_config_set_model_syncs_inference_provider_env(monkeypatch):
    """After an explicit provider switch, ELEVATE_INFERENCE_PROVIDER must
    reflect the user's choice so ambient re-resolution (credential pool
    refresh, aux clients) picks up the new provider instead of the original
    one persisted in config or shell env.

    Regression: a TUI user switched openrouter → anthropic and the TUI kept
    trying openrouter because the env-var-backed resolvers still saw the old
    provider.
    """

    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-or"

        def switch_model(self, **_kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="claude-sonnet-4.6",
        target_provider="anthropic",
        api_key="sk-ant",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
        warning_message="",
    )

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "openrouter")
    monkeypatch.setattr(
        "elevate_cli.model_switch.switch_model", lambda **_kwargs: result
    )
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

    server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {
                "session_id": "sid",
                "key": "model",
                "value": "claude-sonnet-4.6 --provider anthropic",
            },
        }
    )

    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == "anthropic"


def test_beta_tui_model_defaults_to_allowed_codex_model(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.delenv("ELEVATE_MODEL", raising=False)
    monkeypatch.setattr(server, "_load_cfg", lambda: {})

    assert server._resolve_model() == "gpt-5.5"


@pytest.mark.parametrize("source", ["environment", "config"])
def test_beta_tui_rejects_anthropic_model_sources(monkeypatch, source):
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.delenv("ELEVATE_MODEL", raising=False)
    config = {"model": {"default": "anthropic/claude-sonnet-4"}}
    if source == "environment":
        monkeypatch.setenv("ELEVATE_MODEL", "anthropic/claude-sonnet-4")
        config = {}
    monkeypatch.setattr(server, "_load_cfg", lambda: config)

    with pytest.raises(BetaProviderPolicyError) as exc:
        server._resolve_model()

    assert exc.value.code == "beta_model_not_allowed"


def test_beta_tui_model_switch_rejects_non_codex_before_switch(monkeypatch):
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        "elevate_cli.model_switch.switch_model",
        lambda **kwargs: pytest.fail("non-Codex switch reached model resolver"),
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        server._apply_model_switch(
            "sid",
            _session(
                agent=types.SimpleNamespace(
                    provider="openai-codex",
                    model="gpt-5.5",
                    base_url="https://chatgpt.com/backend-api/codex",
                    api_key="local-token",
                )
            ),
            "anthropic/claude-sonnet-4 --provider anthropic",
        )

    assert exc.value.code == "beta_provider_not_allowed"


def test_beta_tui_runtime_rejects_non_codex_result_with_visible_code(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **kwargs: {
            "provider": "anthropic",
            "api_mode": "anthropic_messages",
        },
    )

    with pytest.raises(RuntimeError, match="beta_provider_not_allowed"):
        server._resolve_tui_runtime()


def test_beta_background_agent_removes_fallback_chain(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setattr(
        server,
        "_resolve_tui_runtime",
        lambda: {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_key": "fresh-local-token",
            "api_mode": "codex_responses",
            "credential_pool": None,
        },
    )
    agent = types.SimpleNamespace(
        provider="openai-codex",
        model="gpt-5.4",
        base_url="https://hostile.example.test/v1",
        api_key="stale-host-key",
        api_mode="chat_completions",
        _fallback_model=[
            {
                "provider": "anthropic",
                "model": "anthropic/claude-sonnet-4",
            }
        ],
    )

    kwargs = server._background_agent_kwargs(agent, "task-1")

    assert kwargs["provider"] == "openai-codex"
    assert kwargs["model"] == "gpt-5.4"
    assert kwargs["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert kwargs["api_key"] == "fresh-local-token"
    assert kwargs["api_mode"] == "codex_responses"
    assert kwargs["credential_pool"] is None
    assert kwargs["fallback_model"] is None


def test_beta_background_agent_rejects_non_codex_parent(monkeypatch):
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setattr(
        server,
        "_resolve_tui_runtime",
        lambda: pytest.fail("runtime resolved for a non-Codex parent"),
    )
    agent = types.SimpleNamespace(
        provider="anthropic",
        model="gpt-5.4",
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        server._background_agent_kwargs(agent, "task-1")

    assert exc.value.code == "beta_provider_not_allowed"


def test_beta_tui_model_switch_replaces_stale_agent_credentials(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    # _apply_model_switch intentionally synchronizes these process-level
    # values. Register their original absence so this test cannot leak them
    # into later tests in the same worker.
    monkeypatch.delenv("ELEVATE_MODEL", raising=False)
    monkeypatch.delenv("ELEVATE_INFERENCE_PROVIDER", raising=False)
    initial_runtime = {
        "provider": "openai-codex",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_key": "initial-local-token",
        "api_mode": "codex_responses",
    }
    final_runtime = {
        **initial_runtime,
        "api_key": "final-local-token",
    }
    seen = {}
    runtime_calls = []

    def _resolve_runtime():
        runtime_calls.append(len(runtime_calls) + 1)
        return initial_runtime if len(runtime_calls) == 1 else final_runtime

    monkeypatch.setattr(server, "_resolve_tui_runtime", _resolve_runtime)

    class _Agent:
        provider = "openai-codex"
        model = "gpt-5.5"
        base_url = "https://hostile.example.test/v1"
        api_key = "stale-host-key"

        def switch_model(self, **kwargs):
            seen["agent"] = kwargs

    result = types.SimpleNamespace(
        success=True,
        new_model="gpt-5.4",
        target_provider="openai-codex",
        api_key="pipeline-hostile-key",
        base_url="https://pipeline-hostile.example.test/v1",
        api_mode="chat_completions",
        warning_message="",
    )

    def _switch_model(**kwargs):
        seen["pipeline"] = kwargs
        return result

    monkeypatch.setattr("elevate_cli.model_switch.switch_model", _switch_model)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

    response = server._apply_model_switch(
        "sid", _session(agent=_Agent()), "gpt-5.4"
    )

    assert response["value"] == "gpt-5.4"
    assert runtime_calls == [1, 2]
    assert seen["pipeline"]["current_base_url"] == initial_runtime["base_url"]
    assert seen["pipeline"]["current_api_key"] == initial_runtime["api_key"]
    assert seen["agent"]["new_provider"] == "openai-codex"
    assert seen["agent"]["base_url"] == final_runtime["base_url"]
    assert seen["agent"]["api_key"] == final_runtime["api_key"]
    assert seen["agent"]["api_mode"] == "codex_responses"


def test_beta_tui_model_switch_final_auth_race_has_zero_mutation(monkeypatch):
    from elevate_cli.beta_provider_policy import BetaProviderPolicyError

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.delenv("ELEVATE_MODEL", raising=False)
    monkeypatch.delenv("ELEVATE_INFERENCE_PROVIDER", raising=False)
    initial_runtime = {
        "provider": "openai-codex",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_key": "initial-local-token",
        "api_mode": "codex_responses",
    }
    runtime_calls = 0

    def _resolve_runtime():
        nonlocal runtime_calls
        runtime_calls += 1
        if runtime_calls == 1:
            return initial_runtime
        raise BetaProviderPolicyError(
            "OpenAI Codex auth disappeared before model-switch commit.",
            code="beta_codex_auth_required",
        )

    monkeypatch.setattr(server, "_resolve_tui_runtime", _resolve_runtime)

    class _Agent:
        provider = "openai-codex"
        model = "gpt-5.5"
        base_url = "https://cached.attacker.invalid/v1"
        api_key = "cached-evil-key"
        api_mode = "anthropic_messages"

        def switch_model(self, **_kwargs):
            pytest.fail("agent mutated after final Beta auth failure")

    agent = _Agent()
    result = types.SimpleNamespace(
        success=True,
        new_model="gpt-5.4",
        target_provider="openai-codex",
        api_key="pipeline-evil-key",
        base_url="https://pipeline.attacker.invalid/v1",
        api_mode="anthropic_messages",
        warning_message="",
    )
    monkeypatch.setattr(
        "elevate_cli.model_switch.switch_model", lambda **_kwargs: result
    )
    persist = MagicMock()
    monkeypatch.setattr(server, "_persist_model_switch", persist)
    monkeypatch.setattr(
        server,
        "_restart_slash_worker",
        lambda _session: pytest.fail("slash worker restarted after auth failure"),
    )
    monkeypatch.setattr(
        server,
        "_emit",
        lambda *_args, **_kwargs: pytest.fail("session event emitted after auth failure"),
    )
    agent_before = dict(vars(agent))
    env_before = {
        key: os.environ.get(key)
        for key in ("ELEVATE_MODEL", "ELEVATE_INFERENCE_PROVIDER")
    }
    result_before = dict(vars(result))

    with pytest.raises(BetaProviderPolicyError) as exc:
        server._apply_model_switch(
            "sid", _session(agent=agent), "gpt-5.4 --global"
        )

    assert exc.value.code == "beta_codex_auth_required"
    assert runtime_calls == 2
    assert dict(vars(agent)) == agent_before
    assert dict(vars(result)) == result_before
    assert {
        key: os.environ.get(key)
        for key in ("ELEVATE_MODEL", "ELEVATE_INFERENCE_PROVIDER")
    } == env_before
    persist.assert_not_called()


def test_config_set_personality_rejects_unknown_name(monkeypatch):
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda cfg=None: {"helpful": "You are helpful."},
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "personality", "value": "bogus"},
        }
    )

    assert "error" in resp
    assert "Unknown personality" in resp["error"]["message"]


def test_config_set_personality_resets_history_and_returns_info(monkeypatch):
    session = _session(
        agent=types.SimpleNamespace(),
        history=[{"role": "user", "text": "hi"}],
        history_version=4,
    )
    new_agent = types.SimpleNamespace(model="x")
    emits = []

    server._sessions["sid"] = session
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda cfg=None: {"helpful": "You are helpful."},
    )
    monkeypatch.setattr(
        server, "_make_agent", lambda sid, key, session_id=None: new_agent
    )
    monkeypatch.setattr(
        server, "_session_info", lambda agent: {"model": getattr(agent, "model", "?")}
    )
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
    monkeypatch.setattr(server, "_write_config_key", lambda path, value: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "personality", "value": "helpful"},
        }
    )

    assert resp["result"]["history_reset"] is True
    assert resp["result"]["info"] == {"model": "x"}
    assert session["history"] == []
    assert session["history_version"] == 5
    assert ("session.info", "sid", {"model": "x"}) in emits


def test_direct_compress_keeps_append_only_transcript_and_emits_pill(monkeypatch):
    """Manual /compress must (1) emit the 'Compacting context' pill before the
    blocking summary and 'Session compacted' after, and (2) not duplicate rows.

    Compaction redesign: _compress_context no longer ROTATES — the transcript is
    append-only and compaction lives in the payload cursor + metadata. So the
    session id is STABLE, session_key never swaps, and the in-memory history is
    the (unchanged) transcript. The pill rides the status.update channel."""
    original = [{"role": "user", "content": f"m{i}"} for i in range(8)]

    agent = types.SimpleNamespace(
        compression_enabled=True,
        _cached_system_prompt="sys",
        session_id="old-session",  # stable — no rotation in the cursor model
        # New compress_context returns the SAME transcript unchanged (the cut +
        # summary are persisted as metadata, not assembled into the list).
        _compress_context=lambda hist, *a, **k: (hist, "sys"),
        _persist_session=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("manual compact must not re-persist transcript rows")
        ),
    )
    session = _session(agent=agent, session_key="old-session")
    session["history"] = list(original)
    server._sessions["dsid"] = session

    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda _s: None)
    emitted = []
    try:
        with patch(
            "tui_gateway.server._emit",
            side_effect=lambda ev, s, p=None: emitted.append((ev, p)),
        ):
            out = server._run_direct_compress_slash("dsid", session, "")
    finally:
        server._sessions.pop("dsid", None)

    # The transcript stays unchanged in memory; session_key did NOT rotate.
    assert session["history"] == original
    assert session["session_key"] == "old-session"
    # Pill on before, off after — on the status.update channel the client reads.
    status_texts = [
        p.get("text") for (ev, p) in emitted if ev == "status.update"
    ]
    assert "Compacting context" in status_texts
    assert "Session compacted" in status_texts
    assert status_texts.index("Compacting context") < status_texts.index(
        "Session compacted"
    )
    # Result card still reports the numbers.
    assert "Compressed" in out or "messages" in out or "compact" in out.lower()


def test_session_compress_uses_compress_helper(monkeypatch):
    agent = types.SimpleNamespace()
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server,
        "_compress_session_history",
        lambda session, focus_topic=None: (2, {"total": 42}),
    )
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "x"})

    with patch("tui_gateway.server._emit") as emit:
        resp = server.handle_request(
            {"id": "1", "method": "session.compress", "params": {"session_id": "sid"}}
        )

    assert resp["result"]["removed"] == 2
    assert resp["result"]["usage"]["total"] == 42
    emit.assert_called_once_with("session.info", "sid", {"model": "x"})


def test_prompt_submit_sets_approval_session_key(monkeypatch):
    from tools.approval import get_current_session_key

    _install_prompt_receipt_db(monkeypatch)
    captured = {}

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            captured["session_key"] = get_current_session_key(default="")
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "ping"},
        }
    )

    assert resp["result"]["status"] == "streaming"
    assert captured["session_key"] == "session-key"


def test_prompt_submit_binds_only_effective_policy_read_back_from_receipt(
    monkeypatch,
):
    from tools import approval
    from tools.approval import (
        ExecutionPolicy,
        ExecutionPolicyMode,
        execution_policy_for_permission_mode,
        get_current_execution_policy,
        get_current_execution_policy_revision,
    )

    class _NarrowingReceiptDB(_PromptReceiptDB):
        def prepare_prompt_receipt(self, *args, **kwargs):
            receipt = super().prepare_prompt_receipt(*args, **kwargs)
            key = (args[0], kwargs["client_message_id"])
            if receipt["inserted"]:
                accepted = ExecutionPolicy.from_dict(receipt["accepted_policy"])
                effective = accepted.narrow(
                    {"read"},
                    mode=ExecutionPolicyMode.READ_ONLY,
                )
                self.rows[key]["effective_policy"] = effective.to_dict()
                receipt["effective_policy"] = effective.to_dict()
                self.rows[key]["policy_revision"] = 5
                receipt["policy_revision"] = 5
            return receipt

    db = _NarrowingReceiptDB()
    captured = {}

    class _Agent:
        def run_conversation(self, *_args, **_kwargs):
            captured["policy"] = get_current_execution_policy()
            captured["policy_revision"] = get_current_execution_policy_revision()
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    approval.set_session_permission_mode("session-key", "bypassPermissions")
    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)

    try:
        response = server.handle_request(
            {
                "id": "policy-1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "draft the follow-up",
                    "user_message_id": "user-policy-bind",
                },
            }
        )

        assert response["result"]["status"] == "streaming"
        stored = db.rows[("session-key", "user-policy-bind")]
        assert stored["accepted_policy"] == execution_policy_for_permission_mode(
            "user-policy-bind",
            "bypassPermissions",
        ).to_dict()
        expected_effective = ExecutionPolicy.for_mode(
            "user-policy-bind",
            ExecutionPolicyMode.READ_ONLY,
        )
        assert stored["effective_policy"] == expected_effective.to_dict()
        assert captured["policy"] == expected_effective
        assert captured["policy_revision"] == 5
        assert get_current_execution_policy() is None
        assert get_current_execution_policy_revision() is None
    finally:
        approval.clear_session("session-key")
        server._sessions.pop("sid", None)


def test_prompt_submit_rejects_unknown_permission_mode_before_persistence(
    monkeypatch,
):
    from tools import approval

    class _ForbiddenThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("unknown policy mode must not start a worker")

    db = _PromptReceiptDB()
    server._sessions["sid"] = _session()
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server.threading, "Thread", _ForbiddenThread)
    monkeypatch.setattr(
        approval,
        "_get_approval_config",
        lambda: {"permission_mode": "futureMode"},
    )

    try:
        response = server.handle_request(
            {
                "id": "unknown-policy",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "do something",
                    "user_message_id": "unknown-policy-user",
                },
            }
        )

        assert response["error"]["code"] == 4002
        assert "Unknown permission mode" in response["error"]["message"]
        assert db.rows == {}
        assert server._sessions["sid"]["running"] is False
    finally:
        approval.clear_session("session-key")
        server._sessions.pop("sid", None)


def test_prompt_submit_records_one_delta_usage_row_at_completion(monkeypatch):
    from gateway import usage_ledger

    db = _install_prompt_receipt_db(monkeypatch)
    clock = {"now": 100.0}
    recorded = []
    receipt_status_at_record = []
    claim_present_at_record = []
    running_at_record = []

    def record_gateway_turn(**kwargs):
        receipt_status_at_record.append(
            db.rows[("session-key", "user-usage")]["status"]
        )
        claim_present_at_record.append(
            ("session-key", "user-usage") in server._active_prompt_claims
        )
        running_at_record.append(server._sessions["sid"]["running"])
        recorded.append(kwargs)
        return 1

    class _Agent:
        model = "gemini-2.5-flash"
        provider = "gemini"
        session_input_tokens = 1_000
        session_output_tokens = 20
        session_total_tokens = 1_020
        session_cache_read_tokens = 10
        session_cache_write_tokens = 2
        session_reasoning_tokens = 3
        session_prompt_tokens = 1_000
        session_completion_tokens = 20
        session_api_calls = 1
        session_estimated_cost_usd = 0.1

        def run_conversation(self, *_args, **_kwargs):
            self.session_input_tokens = 1_700
            self.session_output_tokens = 47
            self.session_total_tokens = 1_747
            self.session_cache_read_tokens = 14
            self.session_cache_write_tokens = 3
            self.session_reasoning_tokens = 8
            self.session_prompt_tokens = 1_700
            self.session_completion_tokens = 47
            self.session_api_calls = 3
            self.session_estimated_cost_usd = 0.125
            clock["now"] = 100.5
            return {
                "completed": True,
                "failed": False,
                "final_response": "done",
                "messages": [{"role": "assistant", "content": "done"}],
                # Deliberately cumulative: the gateway must overwrite these
                # with the logical turn delta before recording.
                "input_tokens": 1_700,
                "output_tokens": 47,
                "total_tokens": 1_747,
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emitted = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server.time, "monotonic", lambda: clock["now"])
        monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
        monkeypatch.setattr(server, "render_message", lambda _text, _cols: "")
        monkeypatch.setattr(server, "_voice_tts_enabled", lambda: False)
        monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))
        monkeypatch.setattr(
            usage_ledger,
            "record_gateway_turn",
            record_gateway_turn,
        )

        response = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "ping",
                    "user_message_id": "user-usage",
                },
            }
        )

        complete = [args for args in emitted if args[0] == "message.complete"]
        assert response["result"]["status"] == "streaming"
        assert len(complete) == 1
        assert len(recorded) == 1
        assert receipt_status_at_record == ["complete"]
        assert claim_present_at_record == [False]
        assert running_at_record == [False]
        call = recorded[0]
        assert call["source"] == "tui"
        assert call["session_id"] == "session-key"
        assert call["session_key"] == "session-key"
        assert call["message_id"] == complete[0][2]["message_id"]
        assert call["latency_ms"] == 500
        assert {
            key: call["agent_result"][key]
            for key in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
                "api_calls",
                "status",
            )
        } == {
            "input_tokens": 700,
            "output_tokens": 27,
            "total_tokens": 727,
            "cache_read_tokens": 4,
            "cache_write_tokens": 1,
            "reasoning_tokens": 5,
            "api_calls": 2,
            "status": "complete",
        }
        assert call["agent_result"]["estimated_cost_usd"] == pytest.approx(0.025)
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_empty_model_result_is_visible_error(monkeypatch):
    from gateway import usage_ledger

    db = _install_prompt_receipt_db(monkeypatch)
    recorded = []

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            return {
                "final_response": "(empty)",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "(empty)",
                        "finish_reason": "stop",
                    }
                ],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emitted = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _agent: {})
        monkeypatch.setattr(server, "render_message", lambda _text, _cols: "")
        monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))
        monkeypatch.setattr(
            usage_ledger,
            "record_gateway_turn",
            lambda **kwargs: recorded.append(kwargs) or 1,
        )

        response = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "Use deals_overview before answering",
                    "user_message_id": "user-empty",
                },
            }
        )

        assert response.get("result")
        complete = [args for args in emitted if args[0] == "message.complete"]
        assert len(complete) == 1
        payload = complete[0][2]
        assert payload["status"] == "error"
        assert payload["text"] != "(empty)"
        assert "did not complete" in payload["text"].lower()
        assert len(recorded) == 1
        assert recorded[0]["message_id"] == payload["message_id"]
        assert recorded[0]["agent_result"]["status"] == "error"
        assert db.rows[("session-key", "user-empty")]["status"] == "error"
        assert server._sessions["sid"]["history"] == [
            {
                "role": "assistant",
                "content": server._EMPTY_MODEL_FAILURE,
                "finish_reason": "error",
            }
        ]
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_pending_turn_is_neither_success_nor_error(monkeypatch):
    db = _install_prompt_receipt_db(monkeypatch)
    obligations = [
        {
            "tool": "delegate_task",
            "task_id": "child-1",
            "status": "pending",
        }
    ]

    class _Agent:
        def run_conversation(self, *_args, **_kwargs):
            return {
                "completed": False,
                "failed": False,
                "final_response": "The delegated task is still running.",
                "partial": True,
                "pending": True,
                "pending_tool_obligations": obligations,
                "messages": [
                    {
                        "role": "assistant",
                        "content": "The delegated task is still running.",
                        "finish_reason": "incomplete",
                    }
                ],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emitted = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _agent: {})
        monkeypatch.setattr(server, "render_message", lambda _text, _cols: "")
        monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

        response = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "Prepare the package",
                    "user_message_id": "user-pending",
                },
            }
        )

        assert response["result"]["status"] == "streaming"
        complete = [args for args in emitted if args[0] == "message.complete"]
        assert len(complete) == 1
        payload = complete[0][2]
        assert payload["status"] == "pending"
        assert payload["text"] == "The delegated task is still running."
        assert payload["warning"] == server._PENDING_WORK_WARNING
        assert payload["pending_tool_obligations"] == obligations
        assert "error" not in payload
        assert db.rows[("session-key", "user-pending")]["status"] == "deferred"
        assert server._sessions["sid"]["running"] is False

        duplicate = server.handle_request(
            {
                "id": "2",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "Prepare the package",
                    "user_message_id": "user-pending",
                },
            }
        )
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_status"] == "pending"
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_needs_input_releases_turn_and_is_durable(monkeypatch):
    db = _install_prompt_receipt_db(monkeypatch)
    question = "Which province is the property in?"

    class _Agent:
        def run_conversation(self, *_args, **_kwargs):
            return {
                "completed": False,
                "failed": False,
                "final_response": question,
                "needs_input": True,
                "partial": True,
                "pending": False,
                "messages": [
                    {
                        "role": "assistant",
                        "content": question,
                        "finish_reason": "incomplete",
                    }
                ],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emitted = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _agent: {})
        monkeypatch.setattr(server, "render_message", lambda _text, _cols: "")
        monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

        response = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "Prepare the package",
                    "user_message_id": "user-needs-input",
                },
            }
        )

        assert response["result"]["status"] == "streaming"
        complete = [args for args in emitted if args[0] == "message.complete"]
        assert len(complete) == 1
        assert complete[0][2] == {
            "text": question,
            "usage": {},
            "status": "needs_input",
            "message_id": complete[0][2]["message_id"],
            "warning": server._NEEDS_INPUT_WARNING,
        }
        row = db.rows[("session-key", "user-needs-input")]
        assert row["status"] == "waiting_input"
        assert server._sessions["sid"]["running"] is False
        assert server._sessions["sid"]["history"][-1]["finish_reason"] == "needs_input"
        assert db.finish_reason_updates == [
            ("session-key", complete[0][2]["message_id"], "needs_input")
        ]

        duplicate = server.handle_request(
            {
                "id": "2",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "Prepare the package",
                    "user_message_id": "user-needs-input",
                },
            }
        )
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_status"] == "needs_input"
    finally:
        server._sessions.pop("sid", None)


def test_history_resume_preserves_incomplete_as_pending():
    messages = server._history_to_messages(
        [
            {
                "role": "assistant",
                "content": "Work is still running.",
                "finish_reason": "incomplete",
                "client_message_id": "assistant-pending",
            }
        ]
    )

    assert messages == [
        {
            "role": "assistant",
            "text": "Work is still running.",
            "status": "pending",
            "message_id": "assistant-pending",
        }
    ]


def test_history_resume_preserves_clarification_as_needs_input():
    messages = server._history_to_messages(
        [
            {
                "role": "assistant",
                "content": "Which province is the property in?",
                "finish_reason": "needs_input",
                "client_message_id": "assistant-question",
            }
        ]
    )

    assert messages == [
        {
            "role": "assistant",
            "text": "Which province is the property in?",
            "status": "needs_input",
            "message_id": "assistant-question",
        }
    ]


def test_context_overflow_reset_clears_replay_but_preserves_terminal_receipt(
    monkeypatch, tmp_path
):
    from elevate_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    session_key = "tui-overflow-session"
    db.create_session(session_key, source="tui")
    db.append_message(session_key, "user", content="x" * 10_000)
    db.append_message(
        session_key,
        "assistant",
        content="maximum context length exceeded",
        finish_reason="error",
    )
    db.prepare_prompt_receipt(
        session_key,
        "continue",
        assistant_message_id="assistant-overflow",
        client_message_id="user-overflow",
        payload={"text": "continue"},
    )
    assert db.claim_prompt_receipt(
        session_key, "user-overflow", owner_id="owner"
    )
    assert db.finish_prompt_receipt(
        session_key,
        "user-overflow",
        owner_id="owner",
        status="error",
    )

    session = _session(session_key=session_key, history=[{"role": "user", "content": "old"}])
    reset = MagicMock()
    monkeypatch.setattr(server, "_reset_session_agent", reset)

    server._reset_tui_context_overflow_session("sid", session, db)

    assert db.get_messages_as_conversation(session_key) == []
    duplicate = db.prepare_prompt_receipt(
        session_key,
        "continue",
        assistant_message_id="ignored",
        client_message_id="user-overflow",
        payload={"text": "continue"},
    )
    assert duplicate["inserted"] is False
    assert duplicate["status"] == "error"
    reset.assert_called_once_with("sid", session)
    db.close()


@pytest.mark.parametrize("agent_result", [None, "", "legacy string result"])
def test_prompt_submit_non_dict_result_is_terminal_error(monkeypatch, agent_result):
    db = _install_prompt_receipt_db(monkeypatch)

    class _Agent:
        def run_conversation(self, *args, **kwargs):
            return agent_result

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emitted = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _agent: {})
        monkeypatch.setattr(server, "render_message", lambda _text, _cols: "")
        monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

        server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "ping",
                    "user_message_id": "user-invalid-result",
                },
            }
        )

        complete = [args for args in emitted if args[0] == "message.complete"]
        assert len(complete) == 1
        assert complete[0][2]["status"] == "error"
        assert complete[0][2]["text"]
        assert db.rows[("session-key", "user-invalid-result")]["status"] == "error"
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_outer_exception_emits_terminal_error(monkeypatch, tmp_path):
    db = _install_prompt_receipt_db(monkeypatch)
    monkeypatch.setattr(server, "_CRASH_LOG", str(tmp_path / "crash.log"))

    class _Agent:
        def run_conversation(self, *args, **kwargs):
            raise RuntimeError("agent crashed")

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emitted = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

        server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "ping",
                    "user_message_id": "user-crash",
                },
            }
        )

        complete = [args for args in emitted if args[0] == "message.complete"]
        assert len(complete) == 1
        assert complete[0][2] == {
            "error": "agent crashed",
            "message_id": complete[0][2]["message_id"],
            "status": "error",
            "text": "agent crashed",
        }
        assert not [args for args in emitted if args[0] == "error"]
        assert db.rows[("session-key", "user-crash")]["status"] == "error"
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_expands_context_refs(monkeypatch):
    _install_prompt_receipt_db(monkeypatch)
    captured = {}

    class _Agent:
        model = "test/model"
        base_url = ""
        api_key = ""

        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            captured["prompt"] = prompt
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    fake_ctx = types.ModuleType("agent.context_references")
    fake_ctx.preprocess_context_references = (
        lambda message, **kwargs: types.SimpleNamespace(
            blocked=False,
            message="expanded prompt",
            warnings=[],
            references=[],
            injected_tokens=0,
        )
    )
    fake_meta = types.ModuleType("agent.model_metadata")
    fake_meta.get_model_context_length = lambda *args, **kwargs: 100000

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setitem(sys.modules, "agent.context_references", fake_ctx)
    monkeypatch.setitem(sys.modules, "agent.model_metadata", fake_meta)

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "@diff"},
        }
    )

    assert captured["prompt"] == "expanded prompt"


def test_prompt_submit_forwards_persist_user_message(monkeypatch):
    _install_prompt_receipt_db(monkeypatch)
    captured = {}

    class _Agent:
        def run_conversation(
            self,
            prompt,
            conversation_history=None,
            stream_callback=None,
            persist_user_message=None,
            **kwargs,
        ):
            captured["prompt"] = prompt
            captured["persist_user_message"] = persist_user_message
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    import elevate_cli.agent_hub as agent_hub
    monkeypatch.setattr(
        agent_hub,
        "agent_recent_activity_digest",
        lambda _agent_id: "[RECENT AUTONOMOUS ACTIVITY]\nheartbeat ran\n[/RECENT AUTONOMOUS ACTIVITY]",
    )

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {
                "session_id": "sid",
                "text": "[hub context]\n\nUser request: open it",
                "persist_user_message": "open it",
            },
        }
    )

    assert captured["prompt"].endswith("[hub context]\n\nUser request: open it")
    assert "RECENT AUTONOMOUS ACTIVITY" in captured["prompt"]
    assert captured["persist_user_message"] == "open it"


def test_user_turn_consuming_parked_result_records_origin_link(monkeypatch):
    _install_prompt_receipt_db(monkeypatch)
    recorder_calls = _capture_session_recorder(monkeypatch)
    captured = {}

    class _Agent:
        def run_conversation(
            self,
            prompt,
            conversation_history=None,
            stream_callback=None,
            **kwargs,
        ):
            captured["prompt"] = prompt
            return {
                "final_response": "The CMA is ready.",
                "messages": [{"role": "assistant", "content": "The CMA is ready."}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    session = _session(
        agent=_Agent(),
        pending_delegate_results=[
            {
                "status": "completed",
                "goal": "prepare the CMA",
                "summary": "Six comparable sales were verified.",
                "correlation_id": "turn-A",
                "relation": "delegate_result",
                "task_id": "dt-cma",
            }
        ],
    )
    server._sessions["sid"] = session
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *args: None)
        monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
        monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
        monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
        monkeypatch.setattr(server, "_get_usage", lambda _agent: {})

        resp = server.handle_request(
            {
                "id": "consume-rpc",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "What came back?",
                    "user_message_id": "turn-B",
                },
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert resp["result"]["correlation_id"] == "turn-B"
    assert "Six comparable sales were verified" in captured["prompt"]
    consumed = [
        kwargs
        for event_type, kwargs in recorder_calls
        if event_type == "delegate.result_consumed"
    ]
    assert len(consumed) == 1
    assert consumed[0]["correlation_id"] == "turn-B"
    assert consumed[0]["payload"] == {
        "parent_correlation_id": "turn-A",
        "relation": "delegate_result",
        "task_id": "dt-cma",
    }
    assert session.get("pending_delegate_results") == []


def test_prompt_submit_releases_running_before_auto_title(monkeypatch):
    _install_prompt_receipt_db(monkeypatch)
    captured = {}

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    fake_title = types.ModuleType("agent.title_generator")

    def _maybe_auto_title(*args, **kwargs):
        captured["running_during_title"] = server._sessions["sid"]["running"]

    fake_title.maybe_auto_title = _maybe_auto_title

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setitem(sys.modules, "agent.title_generator", fake_title)

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "ping"},
            }
        )

        assert resp["result"]["status"] == "streaming"
        assert captured["running_during_title"] is False
        assert server._sessions["sid"]["running"] is False
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_crash_after_receipt_recovers_once(monkeypatch, tmp_path):
    from elevate_state import SessionDB
    from tools import approval
    from tools.approval import (
        get_current_execution_policy,
        get_current_execution_policy_revision,
    )

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("session-key", source="tui")
    calls = {
        "correlation_ids": [],
        "policies": [],
        "policy_revisions": [],
        "runs": 0,
    }
    recorder_calls = _capture_session_recorder(monkeypatch)

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, **kwargs):
            from gateway.session_context import get_session_env

            calls["runs"] += 1
            calls["correlation_ids"].append(
                get_session_env("ELEVATE_SESSION_CORRELATION_ID")
            )
            calls["policies"].append(get_current_execution_policy())
            calls["policy_revisions"].append(
                get_current_execution_policy_revision()
            )
            return {
                "final_response": "",
                "messages": [
                    *(conversation_history or []),
                    {
                        "role": "user",
                        "content": prompt,
                        "client_message_id": kwargs["user_message_id"],
                    },
                ],
            }

    class _DeferredThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            rows = db.get_messages("session-key")
            assert [(row["role"], row["content"]) for row in rows] == [
                ("user", "prepare the listing"),
            ]
            receipt = db.get_recoverable_prompt_receipt("session-key")
            assert receipt["status"] == "pending"
            assert receipt["payload"]["correlation_id"] == "user-receipt-1"
            assert receipt["effective_policy"]["mode"] == "plan"

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *args: None)
    monkeypatch.setattr(server, "_emit", lambda *args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")
    approval.set_session_permission_mode("session-key", "plan")
    request = {
        "method": "prompt.submit",
        "params": {
            "correlation_id": "client-cannot-override-root",
            "session_id": "sid",
            "text": "prepare the listing",
            "user_message_id": "user-receipt-1",
        },
    }
    try:
        first = server.handle_request({"id": "rpc-1", **request})

        assert first["result"]["status"] == "streaming"
        assert first["result"]["correlation_id"] == "user-receipt-1"
        assert server._sessions["sid"]["correlation_id"] == "user-receipt-1"
        assert calls["runs"] == 0
        assert db.get_messages("session-key")[0]["client_message_id"] == "user-receipt-1"
        accepted = [call for call in recorder_calls if call[0] == "prompt.accepted"]
        assert len(accepted) == 1
        assert accepted[0][1]["correlation_id"] == "user-receipt-1"
        assert accepted[0][1]["payload"] == {
            "assistant_message_id": first["result"]["message_id"],
            "recovered": False,
            "status": "accepted",
            "user_message_id": "user-receipt-1",
        }

        # Simulate a process crash after commit but before the worker target ran:
        # all in-memory ack/claim state disappears, while state.db survives.
        server._sessions.pop("sid", None)
        server._active_prompt_claims.clear()
        monkeypatch.setattr(
            server,
            "_PROMPT_EXECUTION_OWNER",
            f"{os.getpid()}:restarted-runtime",
        )
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        server._sessions["sid"] = _session(
            agent=_Agent(),
            history=db.get_messages_as_conversation("session-key"),
        )
        # Recovery must ignore this ambient widening and bind the receipt's
        # original effective policy.
        approval.set_session_permission_mode("session-key", "default")

        assert server._recover_pending_prompt("sid", server._sessions["sid"]) is True
        assert calls["runs"] == 1
        assert calls["correlation_ids"] == ["user-receipt-1"]
        assert len(calls["policies"]) == 1
        assert calls["policies"][0].mode.value == "plan"
        assert calls["policies"][0].accepted_turn_id == "user-receipt-1"
        assert calls["policy_revisions"] == [0]
        assert len(db.get_messages("session-key")) == 1
        assert db.get_recoverable_prompt_receipt("session-key") is None
    finally:
        approval.clear_session("session-key")
        server._sessions.pop("sid", None)
        db.close()


def test_delegate_wake_prompt_persists_fresh_attempt_parent_lineage(monkeypatch):
    db = _install_prompt_receipt_db(monkeypatch)
    recorder_calls = _capture_session_recorder(monkeypatch)

    class _DeferredThread:
        def __init__(self, target=None, daemon=None, **_kwargs):
            self._target = target

        def start(self):
            return None

    server._sessions["sid"] = _session(agent=types.SimpleNamespace())
    try:
        monkeypatch.setattr(server.threading, "Thread", _DeferredThread)
        monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

        resp = server.handle_request(
            {
                "id": "wake-rpc",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "evaluate the completed delegate",
                    "persist_user_message": "⟦subagent-result:completed⟧ CMA",
                    "user_message_id": "wake.attempt-1",
                    "parent_correlation_id": "turn-A",
                    "relation": "delegate_result",
                },
            }
        )

        assert resp["result"]["correlation_id"] == "wake.attempt-1"
        row = db.rows[("session-key", "wake.attempt-1")]
        assert row["payload"]["parent_correlation_id"] == "turn-A"
        assert row["payload"]["relation"] == "delegate_result"
        accepted = [
            kwargs
            for event_type, kwargs in recorder_calls
            if event_type == "prompt.accepted"
        ]
        assert len(accepted) == 1
        assert accepted[0]["correlation_id"] == "wake.attempt-1"
        assert accepted[0]["payload"]["parent_correlation_id"] == "turn-A"
        assert accepted[0]["payload"]["relation"] == "delegate_result"
    finally:
        server._sessions.pop("sid", None)


@pytest.mark.parametrize(
    "variant",
    [
        "policyless_pending",
        "policyless_running",
        "malformed_accepted",
        "malformed_effective",
        "negative_revision",
    ],
)
def test_recovery_interrupts_and_persists_unsafe_policy_receipt(
    monkeypatch,
    tmp_path,
    variant,
):
    from elevate_state import SessionDB
    from tools.approval import ExecutionPolicy, ExecutionPolicyMode

    db = SessionDB(db_path=tmp_path / f"{variant}.db")
    db.create_session("session-key", source="tui")
    policy = (
        None
        if variant.startswith("policyless")
        else ExecutionPolicy.for_mode("unsafe-user", ExecutionPolicyMode.PLAN)
    )
    db.prepare_prompt_receipt(
        "session-key",
        "prepare the listing",
        assistant_message_id="unsafe-assistant",
        client_message_id="unsafe-user",
        payload={"text": "prepare the listing"},
        accepted_policy=policy,
    )
    if variant == "policyless_running":
        assert db.claim_prompt_receipt(
            "session-key",
            "unsafe-user",
            owner_id="old-owner",
        )
    elif variant == "malformed_accepted":
        db._conn.execute(
            "UPDATE prompt_receipts SET accepted_policy_json = ? "
            "WHERE session_id = ? AND client_message_id = ?",
            ("{malformed", "session-key", "unsafe-user"),
        )
    elif variant == "malformed_effective":
        db._conn.execute(
            "UPDATE prompt_receipts SET effective_policy_json = ? "
            "WHERE session_id = ? AND client_message_id = ?",
            ("{malformed", "session-key", "unsafe-user"),
        )
    elif variant == "negative_revision":
        db._conn.execute(
            "UPDATE prompt_receipts SET policy_revision = ? "
            "WHERE session_id = ? AND client_message_id = ?",
            (-1, "session-key", "unsafe-user"),
        )

    emitted = []

    class _ForbiddenAgent:
        def run_conversation(self, *_args, **_kwargs):
            raise AssertionError("unsafe recovery must not execute the agent")

    session = _session(
        agent=_ForbiddenAgent(),
        history=db.get_messages_as_conversation("session-key"),
    )
    server._sessions["sid"] = session
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event, sid, payload: emitted.append((event, sid, payload)),
    )
    monkeypatch.setattr(server, "render_message", lambda raw, _cols: raw)

    try:
        assert server._recover_pending_prompt("sid", session) is False

        receipt = db.get_prompt_receipt("session-key", "unsafe-user")
        assert receipt["status"] == "interrupted"
        assert db.get_recoverable_prompt_receipt("session-key") is None
        transcript = db.get_messages_as_conversation("session-key")
        assert [(message["role"], message["client_message_id"]) for message in transcript] == [
            ("user", "unsafe-user"),
            ("assistant", "unsafe-assistant"),
        ]
        assert transcript[-1]["finish_reason"] == "interrupted"
        assert "Please resend" in transcript[-1]["content"]
        assert session["history"] == transcript

        complete = [payload for event, _sid, payload in emitted if event == "message.complete"]
        assert len(complete) == 1
        assert complete[0]["status"] == "interrupted"
        assert complete[0]["completed"] is False
        assert complete[0]["correlation_id"] == "unsafe-user"
        assert complete[0]["user_message_id"] == "unsafe-user"
        assert "Please resend" in complete[0]["text"]
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_unsafe_policy_interrupt_does_not_emit_when_atomic_cas_loses(monkeypatch):
    class _RaceLostDB:
        def interrupt_prompt_receipt_with_assistant(self, *_args, **_kwargs):
            return False

    session = _session(history=[{"role": "user", "content": "keep"}])
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

    interrupted = server._interrupt_untrusted_prompt_receipt(
        _RaceLostDB(),
        "sid",
        session,
        "session-key",
        {
            "assistant_message_id": "assistant-race",
            "client_message_id": "user-race",
            "owner_id": None,
            "status": "pending",
        },
    )

    assert interrupted is False
    assert emitted == []
    assert session["history"] == [{"role": "user", "content": "keep"}]


def test_duplicate_submit_cannot_replace_persisted_policy_with_ambient_mode(
    monkeypatch,
    tmp_path,
):
    from elevate_state import SessionDB
    from tools import approval
    from tools.approval import (
        ExecutionPolicy,
        ExecutionPolicyMode,
        get_current_execution_policy,
    )

    db = SessionDB(db_path=tmp_path / "duplicate-policy.db")
    db.create_session("session-key", source="tui")
    original = ExecutionPolicy.for_mode("duplicate-user", ExecutionPolicyMode.PLAN)
    db.prepare_prompt_receipt(
        "session-key",
        "prepare the listing",
        assistant_message_id="duplicate-assistant",
        client_message_id="duplicate-user",
        payload={"text": "prepare the listing"},
        accepted_policy=original,
    )
    captured = []

    class _Agent:
        def run_conversation(self, *_args, **_kwargs):
            captured.append(get_current_execution_policy())
            return {
                "final_response": "done",
                "messages": [{"role": "assistant", "content": "done"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(
        agent=_Agent(),
        history=db.get_messages_as_conversation("session-key"),
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")
    approval.set_session_permission_mode("session-key", "default")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *_args: None)
    monkeypatch.setattr(server, "_emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)

    try:
        response = server.handle_request(
            {
                "id": "duplicate-policy",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "prepare the listing",
                    "user_message_id": "duplicate-user",
                },
            }
        )

        assert response["result"]["duplicate"] is True
        assert captured == [original]
        stored = db.get_prompt_receipt("session-key", "duplicate-user")
        assert stored["accepted_policy"] == original.to_dict()
        assert stored["effective_policy"] == original.to_dict()
        assert stored["policy_revision"] == 0
    finally:
        approval.clear_session("session-key")
        server._sessions.pop("sid", None)
        db.close()


def test_prompt_submit_persistence_failure_does_not_start_work(monkeypatch):
    class _FailingDB:
        def prepare_prompt_receipt(self, *args, **kwargs):
            raise OSError("disk unavailable")

    class _ForbiddenThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("worker must not be created")

    emitted = []
    server._sessions["sid"] = _session(attached_images=["keep.png"])
    monkeypatch.setattr(server, "_get_db", lambda: _FailingDB())
    monkeypatch.setattr(server.threading, "Thread", _ForbiddenThread)
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))
    try:
        resp = server.handle_request(
            {
                "id": "rpc-1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "prepare the listing",
                    "user_message_id": "user-receipt-1",
                },
            }
        )

        assert resp["error"]["code"] == 5009
        assert "prompt persistence failed" in resp["error"]["message"]
        assert server._sessions["sid"]["running"] is False
        assert server._sessions["sid"]["attached_images"] == ["keep.png"]
        assert emitted == []
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_concurrent_duplicates_execute_once(monkeypatch, tmp_path):
    from elevate_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("session-key", source="tui")
    calls = {"runs": 0}
    agent_started = threading.Event()
    release_agent = threading.Event()
    agent_done = threading.Event()

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, **kwargs):
            calls["runs"] += 1
            agent_started.set()
            assert release_agent.wait(timeout=5)
            agent_done.set()
            return {
                "final_response": "",
                "messages": [
                    *(conversation_history or []),
                    {
                        "role": "user",
                        "content": prompt,
                        "client_message_id": kwargs["user_message_id"],
                    },
                ],
            }

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *args: None)
    monkeypatch.setattr(server, "_emit", lambda *args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    request = {
        "method": "prompt.submit",
        "params": {
            "session_id": "sid",
            "text": "prepare the listing",
            "user_message_id": "user-retry-1",
        },
    }
    barrier = threading.Barrier(3)
    responses = []

    def _submit(request_id):
        barrier.wait(timeout=5)
        responses.append(server.handle_request({"id": request_id, **request}))

    submitters = [
        threading.Thread(target=_submit, args=(f"rpc-{index}",))
        for index in range(2)
    ]
    try:
        for submitter in submitters:
            submitter.start()
        barrier.wait(timeout=5)
        for submitter in submitters:
            submitter.join(timeout=5)

        assert agent_started.wait(timeout=5)
        assert len(responses) == 2
        assert all(response["result"]["status"] == "streaming" for response in responses)
        assert sorted(response["result"]["duplicate"] for response in responses) == [
            False,
            True,
        ]
        assert calls["runs"] == 1
        rows = db.get_messages("session-key")
        assert len(rows) == 1
        assert rows[0]["client_message_id"] == "user-retry-1"
    finally:
        release_agent.set()
        agent_done.wait(timeout=5)
        deadline = time.time() + 5
        while db.get_recoverable_prompt_receipt("session-key") and time.time() < deadline:
            time.sleep(0.01)
        server._sessions.pop("sid", None)
        db.close()


def test_prompt_submit_terminalization_failure_can_be_recovered(monkeypatch, tmp_path):
    from elevate_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("session-key", source="tui")
    calls = {"finishes": 0, "runs": 0}
    real_finish = db.finish_prompt_receipt

    def _finish_once_fails(*args, **kwargs):
        calls["finishes"] += 1
        if calls["finishes"] == 1:
            return False
        return real_finish(*args, **kwargs)

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, **kwargs):
            calls["runs"] += 1
            return {
                "final_response": "done",
                "messages": [
                    *(conversation_history or []),
                    {
                        "role": "user",
                        "content": prompt,
                        "client_message_id": kwargs["user_message_id"],
                    },
                ],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    db.finish_prompt_receipt = _finish_once_fails
    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *args: None)
    monkeypatch.setattr(server, "_emit", lambda *args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _raw, _cols: None)
    request = {
        "method": "prompt.submit",
        "params": {
            "session_id": "sid",
            "text": "prepare the listing",
            "user_message_id": "user-terminalize-1",
        },
    }
    try:
        first = server.handle_request({"id": "rpc-1", **request})
        assert first["result"]["status"] == "streaming"
        assert db.get_recoverable_prompt_receipt("session-key")["status"] == "running"
        assert ("session-key", "user-terminalize-1") not in server._active_prompt_claims

        retry = server.handle_request({"id": "rpc-2", **request})

        assert retry["result"]["status"] == "streaming"
        assert retry["result"]["recovered"] is True
        terminal_retry = server.handle_request({"id": "rpc-3", **request})
        assert terminal_retry["result"]["status"] == "duplicate"
        assert terminal_retry["result"]["terminal_status"] == "complete"
        assert calls == {"finishes": 2, "runs": 2}
        assert len(db.get_messages("session-key")) == 1
        assert db.get_recoverable_prompt_receipt("session-key") is None
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_image_attach_appends_local_image(monkeypatch):
    fake_cli = types.ModuleType("cli")
    fake_cli._IMAGE_EXTENSIONS = {".png"}
    fake_cli._detect_file_drop = lambda raw: {
        "path": Path("/tmp/cat.png"),
        "is_image": True,
        "remainder": "",
    }
    fake_cli._split_path_input = lambda raw: (raw, "")
    fake_cli._resolve_attachment_path = lambda raw: Path("/tmp/cat.png")

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "image.attach",
            "params": {"session_id": "sid", "path": "/tmp/cat.png"},
        }
    )

    assert resp["result"]["attached"] is True
    assert resp["result"]["name"] == "cat.png"
    assert len(server._sessions["sid"]["attached_images"]) == 1


def test_image_attach_accepts_unquoted_screenshot_path_with_spaces(monkeypatch):
    screenshot = Path("/tmp/Screenshot 2026-04-21 at 1.04.43 PM.png")
    fake_cli = types.ModuleType("cli")
    fake_cli._IMAGE_EXTENSIONS = {".png"}
    fake_cli._detect_file_drop = lambda raw: {
        "path": screenshot,
        "is_image": True,
        "remainder": "",
    }
    fake_cli._split_path_input = lambda raw: (
        "/tmp/Screenshot",
        "2026-04-21 at 1.04.43 PM.png",
    )
    fake_cli._resolve_attachment_path = lambda raw: None

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "image.attach",
            "params": {"session_id": "sid", "path": str(screenshot)},
        }
    )

    assert resp["result"]["attached"] is True
    assert resp["result"]["path"] == str(screenshot)
    assert resp["result"]["remainder"] == ""
    assert len(server._sessions["sid"]["attached_images"]) == 1


def test_commands_catalog_surfaces_quick_commands(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {
            "quick_commands": {
                "build": {"type": "exec", "command": "npm run build"},
                "git": {"type": "alias", "target": "/shell git"},
                "notes": {
                    "type": "exec",
                    "command": "cat NOTES.md",
                    "description": "Open design notes",
                },
            }
        },
    )

    resp = server.handle_request(
        {"id": "1", "method": "commands.catalog", "params": {}}
    )

    pairs = dict(resp["result"]["pairs"])
    assert "npm run build" in pairs["/build"]
    assert pairs["/git"].startswith("alias →")
    assert pairs["/notes"] == "Open design notes"

    user_cat = next(
        c for c in resp["result"]["categories"] if c["name"] == "User commands"
    )
    user_pairs = dict(user_cat["pairs"])
    assert set(user_pairs) == {"/build", "/git", "/notes"}

    assert resp["result"]["canon"]["/build"] == "/build"
    assert resp["result"]["canon"]["/notes"] == "/notes"


def test_command_dispatch_exec_nonzero_surfaces_error(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"quick_commands": {"boom": {"type": "exec", "command": "boom"}}},
    )
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1, stdout="", stderr="failed"
        ),
    )

    resp = server.handle_request(
        {"id": "1", "method": "command.dispatch", "params": {"name": "boom"}}
    )

    assert "error" in resp
    assert "failed" in resp["error"]["message"]


def test_plugins_list_surfaces_loader_error(monkeypatch):
    with patch("elevate_cli.plugins.get_plugin_manager", side_effect=Exception("boom")):
        resp = server.handle_request(
            {"id": "1", "method": "plugins.list", "params": {}}
        )

    assert "error" in resp
    assert "boom" in resp["error"]["message"]


def test_complete_slash_surfaces_completer_error(monkeypatch):
    with patch(
        "elevate_cli.commands.SlashCommandCompleter",
        side_effect=Exception("no completer"),
    ):
        resp = server.handle_request(
            {"id": "1", "method": "complete.slash", "params": {"text": "/mo"}}
        )

    assert "error" in resp
    assert "no completer" in resp["error"]["message"]


def test_input_detect_drop_attaches_image(monkeypatch):
    fake_cli = types.ModuleType("cli")
    fake_cli._detect_file_drop = lambda raw: {
        "path": Path("/tmp/cat.png"),
        "is_image": True,
        "remainder": "",
    }

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "input.detect_drop",
            "params": {"session_id": "sid", "text": "/tmp/cat.png"},
        }
    )

    assert resp["result"]["matched"] is True
    assert resp["result"]["is_image"] is True
    assert resp["result"]["text"] == "[User attached image: cat.png]"


def test_rollback_restore_resolves_number_and_file_path():
    calls = {}

    class _Mgr:
        enabled = True

        def list_checkpoints(self, cwd):
            return [{"hash": "aaa111"}, {"hash": "bbb222"}]

        def restore(self, cwd, target, file_path=None):
            calls["args"] = (cwd, target, file_path)
            return {"success": True, "message": "done"}

    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(_checkpoint_mgr=_Mgr()), history=[]
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "rollback.restore",
            "params": {"session_id": "sid", "hash": "2", "file_path": "src/app.tsx"},
        }
    )

    assert resp["result"]["success"] is True
    assert calls["args"][1] == "bbb222"
    assert calls["args"][2] == "src/app.tsx"


# ── session.steer ────────────────────────────────────────────────────


def test_session_steer_calls_agent_steer_when_agent_supports_it():
    """The TUI RPC method must call agent.steer(text) and return a
    queued status without touching interrupt state.
    """
    calls = {}

    class _Agent:
        def steer(self, text):
            calls["steer_text"] = text
            return True

        def interrupt(self, *args, **kwargs):
            calls["interrupt_called"] = True

    server._sessions["sid"] = _session(agent=_Agent())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "also check auth.log"},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "result" in resp, resp
    assert resp["result"]["status"] == "queued"
    assert resp["result"]["text"] == "also check auth.log"
    assert calls["steer_text"] == "also check auth.log"
    assert "interrupt_called" not in calls  # must NOT interrupt


def test_session_steer_records_correction_without_text(monkeypatch):
    recorder_calls = _capture_session_recorder(monkeypatch)
    monkeypatch.setattr(server, "write_json", lambda _obj: True)

    class _Agent:
        def steer(self, text):
            return True

    server._sessions["sid"] = _session(agent=_Agent())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {
                    "session_id": "sid",
                    "text": "raw correction text with https://secret.example",
                },
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "result" in resp, resp
    corrections = [
        call for call in recorder_calls
        if call[0] == "experience.correction_requested"
    ]
    assert len(corrections) == 1
    payload = corrections[0][1]["payload"]
    assert payload == {
        "stage": "steer",
        "friction_kind": "correction",
        "correction_count": 1,
        "attempt_count": 1,
        "friction_count": 1,
        "outcome": "queued",
    }
    assert "raw correction" not in json.dumps(corrections)
    assert "secret.example" not in json.dumps(corrections)


def test_steer_applied_records_recovery_when_tool_progress_disabled(monkeypatch):
    recorder_calls = _capture_session_recorder(monkeypatch)
    monkeypatch.setattr(server, "write_json", lambda _obj: True)
    server._sessions["sid"] = _session(tool_progress_mode="off")
    try:
        server._on_tool_progress(
            "sid",
            "steer.applied",
            count=2,
            via="tool_result",
            sources=["not recorded"],
        )
    finally:
        server._sessions.pop("sid", None)

    recovery = [
        call for call in recorder_calls
        if call[0] == "experience.recovery_attempted"
    ]
    assert len(recovery) == 1
    assert recovery[0][1]["payload"] == {
        "stage": "steer",
        "friction_kind": "correction",
        "correction_count": 2,
        "attempt_count": 1,
        "outcome": "applied",
    }
    assert "not recorded" not in json.dumps(recovery)


def test_session_steer_rejects_empty_text():
    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(steer=lambda t: True)
    )
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "   "},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4002


def test_session_steer_errors_when_agent_has_no_steer_method():
    server._sessions["sid"] = _session(agent=types.SimpleNamespace())  # no steer()
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4010


def test_session_info_includes_mcp_servers(monkeypatch):
    fake_status = [
        {"name": "github", "transport": "http", "tools": 12, "connected": True},
        {"name": "filesystem", "transport": "stdio", "tools": 4, "connected": True},
        {"name": "broken", "transport": "stdio", "tools": 0, "connected": False},
    ]
    fake_mod = types.ModuleType("tools.mcp_tool")
    fake_mod.get_mcp_status = lambda: fake_status
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", fake_mod)

    info = server._session_info(types.SimpleNamespace(tools=[], model=""))

    assert info["mcp_servers"] == fake_status


# ---------------------------------------------------------------------------
# History-mutating commands must reject while session.running is True.
# Without these guards, prompt.submit's post-run history write either
# clobbers the mutation (version matches) or silently drops the agent's
# output (version mismatch) — both produce UI<->backend state desync.
# ---------------------------------------------------------------------------


def test_session_undo_rejects_while_running():
    """Fix for TUI silent-drop #1: /undo must not mutate history
    while the agent is mid-turn — would either clobber the undo or
    cause prompt.submit to silently drop the agent's response."""
    server._sessions["sid"] = _session(
        running=True,
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.undo", "params": {"session_id": "sid"}}
        )
        assert resp.get("error"), "session.undo should reject while running"
        assert resp["error"]["code"] == 4009
        assert "session busy" in resp["error"]["message"]
        # History must be unchanged
        assert len(server._sessions["sid"]["history"]) == 2
    finally:
        server._sessions.pop("sid", None)


def test_session_undo_allowed_when_idle():
    """Regression guard: when not running, /undo still works."""
    server._sessions["sid"] = _session(
        running=False,
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.undo", "params": {"session_id": "sid"}}
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"
        assert resp["result"]["removed"] == 2
        assert server._sessions["sid"]["history"] == []
    finally:
        server._sessions.pop("sid", None)


def test_session_compress_rejects_while_running(monkeypatch):
    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.compress", "params": {"session_id": "sid"}}
        )
        assert resp.get("error")
        assert resp["error"]["code"] == 4009
    finally:
        server._sessions.pop("sid", None)


def test_rollback_restore_rejects_full_history_while_running(monkeypatch):
    """Full-history rollback must reject; file-scoped rollback still allowed."""
    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "rollback.restore",
                "params": {"session_id": "sid", "hash": "abc"},
            }
        )
        assert resp.get("error"), "full-history rollback should reject while running"
        assert resp["error"]["code"] == 4009
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_history_version_mismatch_surfaces_warning(monkeypatch):
    """Fix for TUI silent-drop #2: the defensive backstop at prompt.submit
    must attach a 'warning' to message.complete when history was
    mutated externally during the turn (instead of silently dropping
    the agent's output)."""
    _install_prompt_receipt_db(monkeypatch)
    # Agent bumps history_version itself mid-run to simulate an external
    # mutation slipping past the guards.
    session_ref = {"s": None}

    class _RacyAgent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            # Simulate: something external bumped history_version
            # while we were running.
            with session_ref["s"]["history_lock"]:
                session_ref["s"]["history_version"] += 1
            return {
                "final_response": "agent reply",
                "messages": [{"role": "assistant", "content": "agent reply"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_RacyAgent())
    session_ref["s"] = server._sessions["sid"]
    emits: list[tuple] = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")
        monkeypatch.setattr(server, "_emit", lambda *a: emits.append(a))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"

        # History should NOT contain the agent's output (version mismatch)
        assert server._sessions["sid"]["history"] == []

        # message.complete must carry a 'warning' so the UI / operator
        # knows the output was not persisted.
        complete_calls = [a for a in emits if a[0] == "message.complete"]
        assert len(complete_calls) == 1
        _, _, payload = complete_calls[0]
        assert "warning" in payload, (
            "message.complete must include a 'warning' field on "
            "history_version mismatch — otherwise the UI silently "
            "shows output that was never persisted"
        )
        assert (
            "not saved" in payload["warning"].lower()
            or "changed" in payload["warning"].lower()
        )
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_history_version_match_persists_normally(monkeypatch):
    """Regression guard: the backstop does not affect the happy path."""

    _install_prompt_receipt_db(monkeypatch)

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None,
            **kwargs,
        ):
            return {
                "final_response": "reply",
                "messages": [{"role": "assistant", "content": "reply"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emits: list[tuple] = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")
        monkeypatch.setattr(server, "_emit", lambda *a: emits.append(a))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
        assert resp.get("result")

        # History was written
        assert server._sessions["sid"]["history"] == [
            {"role": "assistant", "content": "reply"}
        ]
        assert server._sessions["sid"]["history_version"] == 1

        # No warning should be attached
        complete_calls = [a for a in emits if a[0] == "message.complete"]
        assert len(complete_calls) == 1
        _, _, payload = complete_calls[0]
        assert "warning" not in payload
    finally:
        server._sessions.pop("sid", None)


# ---------------------------------------------------------------------------
# session.interrupt must only cancel pending prompts owned by the calling
# session — it must not blast-resolve clarify/sudo/secret prompts on
# unrelated sessions sharing the same tui_gateway process.  Without
# session scoping the other sessions' prompts silently resolve to empty
# strings, unblocking their agent threads as if the user cancelled.
# ---------------------------------------------------------------------------


def test_interrupt_only_clears_own_session_pending():
    """session.interrupt on session A must NOT release pending prompts
    that belong to session B."""
    import types

    session_a = _session()
    session_a["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    session_b = _session()
    session_b["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    server._sessions["sid_a"] = session_a
    server._sessions["sid_b"] = session_b

    try:
        # Simulate pending prompts on both sessions (what _block creates
        # while a clarify/sudo/secret request is outstanding).
        ev_a = threading.Event()
        ev_b = threading.Event()
        server._pending["rid-a"] = ("sid_a", ev_a)
        server._pending["rid-b"] = ("sid_b", ev_b)
        server._answers.clear()

        # Interrupt session A.
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.interrupt",
                "params": {"session_id": "sid_a"},
            }
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"

        # Session A's pending must be released to empty.
        assert ev_a.is_set(), "sid_a pending Event should be set after interrupt"
        assert server._answers.get("rid-a") == ""

        # Session B's pending MUST remain untouched — no cross-session blast.
        assert not ev_b.is_set(), (
            "CRITICAL: session.interrupt on sid_a released a pending prompt "
            "belonging to sid_b — other sessions' clarify/sudo/secret "
            "prompts are being silently cancelled"
        )
        assert "rid-b" not in server._answers
    finally:
        server._sessions.pop("sid_a", None)
        server._sessions.pop("sid_b", None)
        server._pending.pop("rid-a", None)
        server._pending.pop("rid-b", None)
        server._answers.pop("rid-a", None)
        server._answers.pop("rid-b", None)


def test_interrupt_clears_multiple_own_pending():
    """When a single session has multiple pending prompts (uncommon but
    possible via nested tool calls), interrupt must release all of them."""
    import types

    sess = _session()
    sess["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    server._sessions["sid"] = sess

    try:
        ev1, ev2 = threading.Event(), threading.Event()
        server._pending["r1"] = ("sid", ev1)
        server._pending["r2"] = ("sid", ev2)

        resp = server.handle_request(
            {"id": "1", "method": "session.interrupt", "params": {"session_id": "sid"}}
        )
        assert resp.get("result")
        assert ev1.is_set() and ev2.is_set()
        assert server._answers.get("r1") == "" and server._answers.get("r2") == ""
    finally:
        server._sessions.pop("sid", None)
        for key in ("r1", "r2"):
            server._pending.pop(key, None)
            server._answers.pop(key, None)


def test_session_stop_forces_idle_and_kills_processes(monkeypatch):
    calls = {"interrupt": 0}

    class _Agent:
        def interrupt(self):
            calls["interrupt"] += 1

    fake_registry = types.ModuleType("tools.process_registry")
    fake_registry.process_registry = types.SimpleNamespace(kill_all=lambda: 2)
    monkeypatch.setitem(sys.modules, "tools.process_registry", fake_registry)

    server._sessions["sid"] = _session(
        agent=_Agent(),
        events=[
            {"type": "message.start", "session_id": "sid", "ts": 1710000000.0},
            {
                "type": "tool.start",
                "session_id": "sid",
                "ts": 1710000001.0,
                "payload": {"tool_id": "tool-1", "name": "shell"},
            },
        ],
        events_lock=threading.Lock(),
        running=True,
        running_tools={"tool-1": {"tool_id": "tool-1", "name": "shell"}},
    )

    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.stop", "params": {"session_id": "sid"}}
        )

        assert resp["result"] == {
            "status": "stopped",
            "interrupted": True,
            "killed": 2,
        }
        assert calls["interrupt"] == 1
        assert server._sessions["sid"]["running"] is False
        assert server._sessions["sid"]["running_tools"] == {}
        assert server._sessions["sid"]["events"] == []
    finally:
        server._sessions.pop("sid", None)


def test_clear_pending_without_sid_clears_all():
    """_clear_pending(None) is the shutdown path — must still release
    every pending prompt regardless of owning session."""
    ev1, ev2, ev3 = threading.Event(), threading.Event(), threading.Event()
    server._pending["a"] = ("sid_x", ev1)
    server._pending["b"] = ("sid_y", ev2)
    server._pending["c"] = ("sid_z", ev3)
    try:
        server._clear_pending(None)
        assert ev1.is_set() and ev2.is_set() and ev3.is_set()
    finally:
        for key in ("a", "b", "c"):
            server._pending.pop(key, None)
            server._answers.pop(key, None)


def test_respond_unpacks_sid_tuple_correctly():
    """After the (sid, Event) tuple change, _respond must still work."""
    ev = threading.Event()
    server._pending["rid-x"] = ("sid_x", ev)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "clarify.respond",
                "params": {"request_id": "rid-x", "answer": "the answer"},
            }
        )
        assert resp.get("result")
        assert ev.is_set()
        assert server._answers.get("rid-x") == "the answer"
    finally:
        server._pending.pop("rid-x", None)
        server._answers.pop("rid-x", None)


# ---------------------------------------------------------------------------
# /model switch and other agent-mutating commands must reject while the
# session is running.  agent.switch_model() mutates self.model, self.provider,
# self.base_url, self.client etc. in place — the worker thread running
# agent.run_conversation is reading those on every iteration.  Same class of
# bug as the session.undo / session.compress mid-run silent-drop; same fix
# pattern: reject with 4009 while running.
# ---------------------------------------------------------------------------


def test_config_set_model_rejects_while_running(monkeypatch):
    """/model via config.set must reject during an in-flight turn."""
    seen = {"called": False}

    def _fake_apply(sid, session, raw):
        seen["called"] = True
        return {"value": raw, "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)

    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "model",
                    "value": "anthropic/claude-sonnet-4.6",
                },
            }
        )
        assert resp.get("error")
        assert resp["error"]["code"] == 4009
        assert "session busy" in resp["error"]["message"]
        assert not seen["called"], (
            "_apply_model_switch was called mid-turn — would race with "
            "the worker thread reading agent.model / agent.client"
        )
    finally:
        server._sessions.pop("sid", None)


def test_config_set_model_allowed_when_idle(monkeypatch):
    """Regression guard: idle sessions can still switch models."""
    seen = {"called": False}

    def _fake_apply(sid, session, raw):
        seen["called"] = True
        return {"value": "newmodel", "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)

    server._sessions["sid"] = _session(running=False)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "model", "value": "newmodel"},
            }
        )
        assert resp.get("result")
        assert resp["result"]["value"] == "newmodel"
        assert seen["called"]
    finally:
        server._sessions.pop("sid", None)


def test_mirror_slash_side_effects_rejects_mutating_commands_while_running(monkeypatch):
    """Slash worker passthrough (e.g. /model, /personality, /prompt,
    /compact) must reject during an in-flight turn.  Same race as
    config.set — mutates live agent state while run_conversation is
    reading it."""
    import types

    applied = {"model": False, "compress": False}

    def _fake_apply_model(sid, session, arg):
        applied["model"] = True
        return {"value": arg, "warning": ""}

    def _fake_compress(session, focus):
        applied["compress"] = True
        return (0, {})

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply_model)
    monkeypatch.setattr(server, "_compress_session_history", _fake_compress)

    session = _session(running=True)
    session["agent"] = types.SimpleNamespace(model="x")

    for cmd, expected_name in [
        ("/model new/model", "model"),
        ("/personality default", "personality"),
        ("/prompt", "prompt"),
        ("/compact", "compact"),
    ]:
        warning = server._mirror_slash_side_effects("sid", session, cmd)
        assert (
            "session busy" in warning
        ), f"{cmd} should have returned busy warning, got: {warning!r}"
        assert f"/{expected_name}" in warning

    # None of the mutating side-effect helpers should have fired.
    assert not applied["model"], "model switch fired despite running session"
    assert not applied["compress"], "compress fired despite running session"


def test_mirror_slash_side_effects_allowed_when_idle(monkeypatch):
    """Regression guard: idle session still runs the side effects."""
    import types

    applied = {"model": False}

    def _fake_apply_model(sid, session, arg):
        applied["model"] = True
        return {"value": arg, "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply_model)

    session = _session(running=False)
    session["agent"] = types.SimpleNamespace(model="x")

    warning = server._mirror_slash_side_effects("sid", session, "/model foo")
    # Should NOT contain "session busy" — the switch went through.
    assert "session busy" not in warning
    assert applied["model"]


# ---------------------------------------------------------------------------
# session.create / session.close race: fast /new churn must not orphan the
# slash_worker subprocess or the global approval-notify registration.
# ---------------------------------------------------------------------------


def test_session_create_close_race_does_not_orphan_worker(monkeypatch):
    """Regression guard: if session.close runs while session.create's
    _build thread is still constructing the agent, the build thread
    must detect the orphan and clean up the notify registration it's
    about to install.  The slash worker is created lazily by slash.exec
    (419c82ec5) so _build must NOT allocate one — eagerly or on the
    orphan path."""
    import threading

    closed_workers: list[str] = []
    unregistered_keys: list[str] = []

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key
            self._closed = False

        def close(self):
            self._closed = True
            closed_workers.append(self.key)

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    # Make _build block until we release it — simulates slow agent init
    release_build = threading.Event()

    def _slow_make_agent(sid, key):
        release_build.wait(timeout=3.0)
        return _FakeAgent()

    # Stub everything _build touches
    monkeypatch.setattr(server, "_make_agent", _slow_make_agent)
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    rows = {}
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(
            create_session=lambda key, **_kw: rows.setdefault(key, {"id": key}),
            get_session=lambda key: rows.get(key),
        ),
    )
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)

    # Shim register/unregister to observe leaks
    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(
        _approval,
        "unregister_gateway_notify",
        lambda key: unregistered_keys.append(key),
    )
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    # Start: session.create spawns _build thread, returns synchronously
    resp = server.handle_request(
        {
            "id": "1",
            "method": "session.create",
            "params": {"cols": 80},
        }
    )
    assert resp.get("result"), f"got error: {resp.get('error')}"
    sid = resp["result"]["session_id"]
    build_done = server._sessions[sid]["agent_ready"]

    # Build thread is blocked in _slow_make_agent.  Close the session
    # NOW — this pops _sessions[sid] before _build can install the
    # worker/notify.
    close_resp = server.handle_request(
        {
            "id": "2",
            "method": "session.close",
            "params": {"session_id": sid},
        }
    )
    assert close_resp.get("result", {}).get("closed") is True

    # At this point session.close saw slash_worker=None (lazy — never
    # installed) so it didn't close anything.  Release the build thread
    # and let it finish — it should detect the orphan and unregister
    # the notify it just installed.
    release_build.set()

    # The build thread's finally sets agent_ready AFTER the orphan
    # cleanup, so once this returns the cleanup has run (or not).
    assert build_done.wait(timeout=3.0), "build thread never finished"

    # Lazy slash worker: _build never allocates one, so there is no
    # worker subprocess to orphan (or to close).
    assert (
        closed_workers == []
    ), f"build thread closed a worker it should never have created: {closed_workers}"
    # Notify may be unregistered by both session.close (unconditional)
    # and the orphan-cleanup path; the key guarantee is that the build
    # thread does at least one unregister call (any prior close
    # already popped the callback; the duplicate is a no-op).
    assert len(unregistered_keys) >= 1, (
        f"orphan notify registration was not unregistered — "
        f"unregistered_keys={unregistered_keys}"
    )


def test_session_create_no_race_keeps_worker_alive(monkeypatch):
    """Regression guard: when session.close does NOT race, the build
    thread must install the notify normally and leave it alone (no
    over-eager cleanup).  The slash worker is lazy (419c82ec5): None
    after build, created by the first slash.exec, and left installed."""
    closed_workers: list[str] = []
    unregistered_keys: list[str] = []

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key

        def run(self, cmd):
            return "ok"

        def close(self):
            closed_workers.append(self.key)

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    monkeypatch.setattr(server, "_make_agent", lambda sid, key: _FakeAgent())
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    rows = {}
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(
            create_session=lambda key, **_kw: rows.setdefault(key, {"id": key}),
            get_session=lambda key: rows.get(key),
        ),
    )
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)

    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(
        _approval,
        "unregister_gateway_notify",
        lambda key: unregistered_keys.append(key),
    )
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "session.create",
            "params": {"cols": 80},
        }
    )
    sid = resp["result"]["session_id"]

    # Wait for the build to finish (ready event inside session dict).
    session = server._sessions[sid]
    session["agent_ready"].wait(timeout=2.0)

    # Build finished without a close race — nothing should have been
    # cleaned up by the orphan check.
    assert (
        closed_workers == []
    ), f"build thread closed a worker despite no race: {closed_workers}"
    assert (
        unregistered_keys == []
    ), f"build thread unregistered its own notify despite no race: {unregistered_keys}"

    # Lazy worker: nothing installed at build time.
    assert session.get("slash_worker") is None

    # First slash.exec creates the worker and leaves it installed.
    fake_sc = types.ModuleType("agent.skill_commands")
    fake_sc.get_skill_commands = lambda: {}
    monkeypatch.setitem(sys.modules, "agent.skill_commands", fake_sc)

    exec_resp = server.handle_request(
        {
            "id": "2",
            "method": "slash.exec",
            "params": {"session_id": sid, "command": "/noop-test"},
        }
    )
    assert exec_resp.get("result", {}).get("output") == "ok", (
        f"slash.exec failed: {exec_resp.get('error')}"
    )
    assert session.get("slash_worker") is not None
    assert (
        closed_workers == []
    ), f"slash.exec closed its own worker despite no race: {closed_workers}"

    # Cleanup
    server._sessions.pop(sid, None)


def test_slash_exec_close_race_does_not_orphan_lazy_worker(monkeypatch):
    """Regression guard for the lazy slash-worker path: if session.close
    runs while slash.exec is constructing the worker, close sees
    slash_worker=None and closes nothing — slash.exec must detect the
    orphaned session dict and close the worker it just installed,
    otherwise the subprocess leaks until process exit (the atexit sweep
    only walks live _sessions)."""
    closed_workers: list[str] = []
    sid = "race-sid"

    class _RacingWorker:
        def __init__(self, key, model):
            self.key = key
            # Deterministically simulate session.close winning the race
            # mid-construction: it pops the session dict and, finding
            # slash_worker=None, closes nothing.
            server._sessions.pop(sid, None)

        def run(self, cmd):
            return "ok"

        def close(self):
            closed_workers.append(self.key)

    monkeypatch.setattr(server, "_SlashWorker", _RacingWorker)
    fake_sc = types.ModuleType("agent.skill_commands")
    fake_sc.get_skill_commands = lambda: {}
    monkeypatch.setitem(sys.modules, "agent.skill_commands", fake_sc)

    session = _session()
    server._sessions[sid] = session
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "slash.exec",
                "params": {"session_id": sid, "command": "/noop-test"},
            }
        )
        # The command itself still completes (worker ran before the
        # orphan check) — the guarantee is about cleanup, not output.
        assert resp.get("result", {}).get("output") == "ok", (
            f"slash.exec failed: {resp.get('error')}"
        )
        assert closed_workers == ["session-key"], (
            f"orphaned lazy worker was not closed — closed_workers={closed_workers}"
        )
        assert session.get("slash_worker") is None
    finally:
        server._sessions.pop(sid, None)


def test_get_db_degrades_cleanly_when_sessiondb_init_fails(monkeypatch):
    fake_mod = types.ModuleType("elevate_state")

    class _BrokenSessionDB:
        def __init__(self):
            raise RuntimeError("locking protocol")

    fake_mod.SessionDB = _BrokenSessionDB
    monkeypatch.setitem(sys.modules, "elevate_state", fake_mod)
    monkeypatch.setattr(server, "_db", None)
    monkeypatch.setattr(server, "_db_error", None)

    assert server._get_db() is None
    assert server._db_error == "locking protocol"


def test_session_create_rejects_when_state_db_is_unavailable(monkeypatch):
    before = set(server._sessions)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_db_error", "locking protocol")
    monkeypatch.setattr(
        server,
        "_make_agent",
        lambda *_args: (_ for _ in ()).throw(AssertionError("agent must not start")),
    )

    resp = server.handle_request(
        {"id": "1", "method": "session.create", "params": {"cols": 80}}
    )

    assert "result" not in resp
    assert resp["error"]["code"] == 5006
    assert "state.db unavailable: locking protocol" in resp["error"]["message"]
    assert "session_id" not in json.dumps(resp)
    assert set(server._sessions) == before


def test_session_create_rejects_when_create_session_raises(monkeypatch):
    before = set(server._sessions)
    agent_starts = []

    def create_session(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(create_session=create_session),
    )
    monkeypatch.setattr(
        server,
        "_make_agent",
        lambda *_args: agent_starts.append(True),
    )

    resp = server.handle_request(
        {"id": "1", "method": "session.create", "params": {"cols": 80}}
    )

    assert "result" not in resp
    assert resp["error"] == {
        "code": 5006,
        "message": "session persistence failed: disk full",
    }
    assert "session_id" not in json.dumps(resp)
    assert set(server._sessions) == before
    assert agent_starts == []


def test_session_create_rejects_when_durable_row_is_missing(monkeypatch):
    before = set(server._sessions)
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(
            create_session=lambda *_args, **_kwargs: "unverified",
            get_session=lambda _key: None,
        ),
    )
    monkeypatch.setattr(
        server,
        "_make_agent",
        lambda *_args: (_ for _ in ()).throw(AssertionError("agent must not start")),
    )

    resp = server.handle_request(
        {"id": "1", "method": "session.create", "params": {"cols": 80}}
    )

    assert "result" not in resp
    assert resp["error"] == {
        "code": 5006,
        "message": "session persistence failed: durable row missing",
    }
    assert "session_id" not in json.dumps(resp)
    assert set(server._sessions) == before


def test_session_list_returns_clean_error_when_state_db_is_unavailable(monkeypatch):
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_db_error", "locking protocol")

    resp = server.handle_request({"id": "1", "method": "session.list", "params": {}})

    assert "error" in resp
    assert "state.db unavailable: locking protocol" in resp["error"]["message"]


# --------------------------------------------------------------------------
# model.options — curated-list parity with `elevate model` and classic /model
# --------------------------------------------------------------------------


def test_model_options_does_not_overwrite_curated_models(monkeypatch):
    """The TUI model.options handler must surface the same curated model
    list as `elevate model` and the classic CLI /model picker.

    Regression: earlier versions of this handler unconditionally replaced
    each provider's curated ``models`` field with ``provider_model_ids()``
    (live /models catalog).  That pulled in hundreds of non-agentic models
    for providers like Nous whose /models endpoint returns image/video
    generators, rerankers, embeddings, and TTS models alongside chat models.
    """
    curated_providers = [
        {
            "slug": "nous",
            "name": "Nous",
            "models": ["moonshotai/kimi-k2.5", "anthropic/claude-opus-4.7"],
            "total_models": 30,
            "source": "built-in",
            "is_current": False,
            "is_user_defined": False,
        },
    ]

    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"providers": {}, "custom_providers": []},
    )

    with patch(
        "elevate_cli.model_switch.list_authenticated_providers",
        return_value=curated_providers,
    ) as listing:
        # If provider_model_ids gets called at all, the handler is still
        # overwriting curated with live — that's the regression we're
        # guarding against.
        with patch("elevate_cli.models.provider_model_ids") as live_fetch:
            resp = server._methods["model.options"](99, {"session_id": ""})

    assert "result" in resp, resp
    providers = resp["result"]["providers"]
    nous = next((p for p in providers if p.get("slug") == "nous"), None)
    assert nous is not None
    assert nous["models"] == [
        "moonshotai/kimi-k2.5",
        "anthropic/claude-opus-4.7",
    ]
    assert nous["total_models"] == 30
    # Handler must not consult the live catalog — curated is the truth.
    live_fetch.assert_not_called()
    # list_authenticated_providers is the single source.
    assert listing.call_count == 1


def test_exact_beta_model_options_canonicalizes_before_generic_discovery(monkeypatch):
    """A stale session/config cannot leak alternate provider state to the TUI."""
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    session = _session(
        agent=types.SimpleNamespace(
            provider="anthropic",
            model="claude-opus-4-6",
        )
    )
    monkeypatch.setitem(server._sessions, "beta-session", session)
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: pytest.fail("generic config discovery reached in exact Beta"),
    )
    monkeypatch.setattr(
        server,
        "_resolve_model",
        lambda: pytest.fail("generic model resolution reached in exact Beta"),
    )
    codex_rows = [
        {
            "slug": "openai-codex",
            "name": "OpenAI Codex",
            "models": ["gpt-5.5"],
            "is_current": True,
        }
    ]

    with patch(
        "elevate_cli.model_switch.list_authenticated_providers",
        return_value=codex_rows,
    ) as listing:
        resp = server._methods["model.options"](
            101,
            {"session_id": "beta-session"},
        )

    assert resp["result"] == {
        "providers": codex_rows,
        "model": "gpt-5.5",
        "provider": "openai-codex",
    }
    listing.assert_called_once_with(
        current_provider="openai-codex",
        current_model="gpt-5.5",
        max_models=50,
    )


def test_model_options_propagates_list_exception(monkeypatch):
    """If list_authenticated_providers itself raises, surface as an RPC
    error rather than swallowing to a blank picker."""
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"providers": {}, "custom_providers": []},
    )
    with patch(
        "elevate_cli.model_switch.list_authenticated_providers",
        side_effect=RuntimeError("catalog blew up"),
    ):
        resp = server._methods["model.options"](77, {"session_id": ""})
    assert "error" in resp
    assert resp["error"]["code"] == 5033
    assert "catalog blew up" in resp["error"]["message"]


def test_async_delegate_sink_rewakes_main_agent():
    """The async-delegation completion sink must, on a child result payload:
    flip the subagent dot, emit a lightweight delegate.complete ping (NO dumped
    text), and re-wake the main agent via prompt.submit so it evaluates the
    result and replies. The result must NOT be threaded as a fake user message;
    it rides into the wake turn as context (full text to the API) and is stored
    as a ⟦subagent-result⟧ card marker (persist_user_message)."""
    # Stamp idle well in the past so the sustained-quiet-window gate is already
    # satisfied and the watcher fires on its first pass (no real 2.5s wait).
    session = _session(idle_since=time.monotonic() - 100.0)
    sid = "async-sid"
    emitted = []
    submitted = []

    def fake_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "result": {"status": "streaming"}}

    with patch("tui_gateway.server._emit", side_effect=lambda ev, s, p=None: emitted.append((ev, s, p))), \
         patch("tui_gateway.server._record_backend_event") as record_backend, \
         patch.dict("tui_gateway.server._methods", {"prompt.submit": fake_submit}):
        sink = server._make_async_delegate_sink(
            sid,
            session,
            correlation_id="turn-A",
        )
        sink({
            "task_id": "dt_abc123",
            "results": [
                {
                    "task_index": 0,
                    "subagent_id": "sa-0-deadbeef",
                    "status": "completed",
                    "summary": "Pulled 6 comps; CMA drafted.",
                    "goal": "Run the Lewis Creek CMA",
                    "child_session_id": "child-1",
                }
            ],
            "total_duration_seconds": 12.3,
        })
        # The idle wake watcher runs on its own daemon thread — wait for it.
        for _ in range(100):
            if submitted:
                break
            time.sleep(0.03)

    kinds = [e[0] for e in emitted]
    assert "subagent.complete" in kinds
    assert "delegate.complete" in kinds
    # delegate.complete is now a lightweight ping — no dumped result text.
    dc = next(p for (ev, _s, p) in emitted if ev == "delegate.complete")
    assert dc["task_id"] == "dt_abc123"
    assert dc["status"] == "complete"
    assert "text" not in dc
    # The raw result is NOT threaded as a fake user message.
    assert session["history"] == []
    assert session["history_version"] == 0
    # The idle watcher consumed the parked result and re-woke via prompt.submit.
    assert len(submitted) == 1
    _rid, params = submitted[0]
    assert params["session_id"] == sid
    assert params["user_message_id"].startswith("wake.")
    assert params["user_message_id"] != "turn-A"
    assert params["parent_correlation_id"] == "turn-A"
    assert params["relation"] == "delegate_result"
    record_backend.assert_called_once_with(
        "delegate.result_consumed",
        sid,
        {
            "correlation_id": params["user_message_id"],
            "parent_correlation_id": "turn-A",
            "relation": "delegate_result",
            "task_id": "dt_abc123",
        },
    )
    assert "CMA drafted" in params["text"]  # API sees the full result + eval ask
    # Stored as a status-marked card, never a plain user bubble.
    assert params["persist_user_message"].startswith("⟦subagent-result:completed⟧")
    assert "Run the Lewis Creek CMA" in params["persist_user_message"]
    assert "CMA drafted" in params["persist_user_message"]
    # Consumed: nothing left parked for a later turn to double-report.
    assert session.get("pending_delegate_results") == []


def test_async_delegate_sink_normalizes_failure_status_and_preserves_error():
    class _NoopThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            return None

    emitted = []
    session = _session(running=True)
    with patch(
        "tui_gateway.server._emit",
        side_effect=lambda event, sid, payload=None: emitted.append(
            (event, sid, payload)
        ),
    ), patch("tui_gateway.server.threading.Thread", _NoopThread):
        server._make_async_delegate_sink("sid", session)(
            {
                "task_id": "dt-timeout",
                "results": [
                    {
                        "error": "child timed out",
                        "status": "timeout",
                        "subagent_id": "child-1",
                        "summary": "",
                        "task_index": 0,
                    }
                ],
            }
        )

    payload = next(
        payload for event, _sid, payload in emitted if event == "subagent.complete"
    )
    assert payload["status"] == "failed"
    assert payload["raw_status"] == "timeout"
    assert payload["error"] == "child timed out"


def test_parked_result_yields_to_busy_session():
    """If the session is BUSY when the delegation finishes (the user hit send
    at the same moment), the sink must NOT fire a competing wake turn — the
    result parks on the session for the user's turn to consume."""
    session = _session(running=True)
    submitted = []

    def fake_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "result": {"status": "streaming"}}

    with patch("tui_gateway.server._emit"), \
         patch.dict("tui_gateway.server._methods", {"prompt.submit": fake_submit}), \
         patch("tui_gateway.server.time.sleep"), \
         patch("tui_gateway.server.time.monotonic", side_effect=[0, 0, 100]):
        sink = server._make_async_delegate_sink(
            "busy-sid",
            session,
            correlation_id="turn-A",
        )
        sink({
            "task_id": "dt_busy1",
            "results": [{
                "task_index": 0,
                "status": "completed",
                "summary": "Found 7 leads.",
                "goal": "Find leads",
            }],
        })

    # No competing wake turn while busy; result parked for the user's turn.
    assert submitted == []
    parked = session.get("pending_delegate_results")
    assert parked and "Found 7 leads" in parked[0]["summary"]
    assert parked[0]["correlation_id"] == "turn-A"
    assert parked[0]["relation"] == "delegate_result"
    assert parked[0]["task_id"] == "dt_busy1"


def test_wake_defers_until_sustained_quiet_window():
    """Idle but not yet QUIET: a session that just went idle (idle_since
    moments ago) must NOT be woken — the watcher waits out the quiet window so
    it never pounces in the gap between a user's back-to-back turns."""
    # idle_since = now → quiet window NOT yet elapsed.
    session = _session(
        running=False,
        idle_since=1000.0,
        pending_delegate_results=[{"status": "completed", "goal": "g", "summary": "s"}],
    )
    submitted = []

    def fake_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "result": {"status": "streaming"}}

    # monotonic stays inside the quiet window then the deadline trips, so the
    # watcher loops a couple of times waiting and then gives up WITHOUT firing.
    with patch.dict("tui_gateway.server._methods", {"prompt.submit": fake_submit}), \
         patch("tui_gateway.server.time.sleep"), \
         patch("tui_gateway.server.time.monotonic", side_effect=[1000.0, 1000.5, 1001.0, 2000.0]):
        server._wake_main_agent_with_result("quiet-sid", session)

    assert submitted == []
    # Result still parked → it will ride the user's next turn.
    assert session.get("pending_delegate_results")


def test_wake_reparks_when_submit_loses_latch_race():
    """If a user turn claims the latch between our drain and submit (submit
    returns a 'session busy' error), the drained result must be RE-PARKED, not
    dropped."""
    session = _session(
        running=False,
        idle_since=0.0,  # quiet window long satisfied
        correlation_id="turn-B",
        pending_delegate_results=[
            {
                "status": "completed",
                "goal": "Find leads",
                "summary": "Found 7 leads.",
                "correlation_id": "turn-A",
                "relation": "delegate_result",
                "task_id": "dt-leads",
            }
        ],
    )
    submitted = []

    def busy_submit(rid, params):
        submitted.append((rid, params))
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": 4009, "message": "session busy"}}

    # monotonic: deadline calc (0→deadline 90), while-enter (1), quiet-window
    # elapsed check (10 → 10s idle ≥ 2.5 quiet), then while-exit (99999).
    # First pass: quiet satisfied → drain + submit → busy error → repark, then
    # the deadline trips so the loop ends.
    with patch.dict("tui_gateway.server._methods", {"prompt.submit": busy_submit}), \
         patch("tui_gateway.server.time.sleep"), \
         patch("tui_gateway.server.time.monotonic", side_effect=[0.0, 1.0, 10.0, 99999.0]):
        server._wake_main_agent_with_result("race-sid", session)

    # Submit was attempted and lost; the result is back in the parked queue.
    assert len(submitted) == 1
    _rid, params = submitted[0]
    assert params["user_message_id"].startswith("wake.")
    assert params["user_message_id"] not in {"turn-A", "turn-B"}
    assert params["parent_correlation_id"] == "turn-A"
    assert params["relation"] == "delegate_result"
    parked = session.get("pending_delegate_results")
    assert parked and "Found 7 leads" in parked[0]["summary"]
    assert parked[0]["correlation_id"] == "turn-A"
    assert parked[0]["task_id"] == "dt-leads"


def test_async_delegate_sink_rejects_malformed_payload_without_signaling():
    """Malformed results cannot park work, wake the agent, or signal success."""
    session = _session()
    with patch("tui_gateway.server._emit") as emit, patch(
        "tui_gateway.server.threading.Thread"
    ) as thread:
        sink = server._make_async_delegate_sink("sid", session)
        for payload in (
            None,
            {"task_id": "dt-string", "results": "not a list"},
            {"task_id": "dt-empty", "results": []},
            {"task_id": "dt-mixed", "results": [{"status": "completed"}, "bad"]},
            {"task_id": "dt-status", "results": [{}]},
            {"results": [{"status": "completed"}]},
        ):
            sink(payload)

    emit.assert_not_called()
    thread.assert_not_called()
    assert session.get("pending_delegate_results") in (None, [])


def test_slash_exec_compact_routes_to_compaction_handler(monkeypatch):
    """/compact reaches the in-process compaction handler via slash.exec —
    proving the command is wired end to end, not just that the strings exist
    in source. (/compress was removed; only /compact compacts.)"""
    calls = []
    monkeypatch.setattr(
        server,
        "_run_direct_compress_slash",
        lambda sid, session, focus: (calls.append((sid, focus)), "COMPACTED")[1],
    )
    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(compression_enabled=True),
        history=[{"role": "user", "content": str(i)} for i in range(6)],
    )
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "slash.exec",
                "params": {"session_id": "sid", "command": "/compact"},
            }
        )
    finally:
        server._sessions.pop("sid", None)
    assert (
        resp.get("result", {}).get("output") == "COMPACTED"
    ), f"/compact did not route to the compaction handler: {resp}"
    assert resp.get("result", {}).get("kind") == "compact"
    assert resp.get("result", {}).get("display") == "Finished compacting"
    assert calls, "/compact did not invoke _run_direct_compress_slash"


def test_slash_exec_compact_short_session_uses_compact_wording():
    """A too-short session yields the renamed 'compact' wording."""
    server._sessions["sid"] = _session(history=[{"role": "user", "content": "hi"}])
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "slash.exec",
                "params": {"session_id": "sid", "command": "/compact"},
            }
        )
    finally:
        server._sessions.pop("sid", None)
    out = resp.get("result", {}).get("output", "")
    assert "compact" in out.lower() and "compress" not in out.lower(), out
    assert "display" not in resp.get("result", {})


def test_get_usage_context_percent_measures_against_effective_trigger():
    """The context ring reads % of the compaction trigger, not the raw window."""

    class _Comp:
        last_prompt_tokens = 85_000
        context_length = 200_000
        threshold_tokens = 170_000  # 0.85 * window (aux clamp folds in here too)
        compression_count = 0

    class _Agent:
        model = "test-model"
        context_compressor = _Comp()

    usage = server._get_usage(_Agent())
    assert usage["context_trigger"] == 170_000
    assert usage["context_percent"] == 50  # 85k of the 170k trigger, not 43% of window
    assert usage["context_max"] == 200_000
