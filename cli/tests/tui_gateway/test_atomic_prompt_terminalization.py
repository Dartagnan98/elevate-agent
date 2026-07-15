"""Focused ERB-303A gateway tests for atomic prompt terminal truth."""

from __future__ import annotations

import threading
import types

import pytest

from elevate_state import SessionDB
from tui_gateway import server


class _ImmediateThread:
    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target

    def start(self):
        self._target()


class _ResultAgent:
    model = "test/model"
    base_url = ""
    api_key = ""

    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.calls = 0

    def run_conversation(self, prompt, conversation_history=None, **kwargs):
        self.calls += 1
        return self.result_factory(prompt, list(conversation_history or []), kwargs)


def _session(agent, session_key: str) -> dict:
    return {
        "agent": agent,
        "session_key": session_key,
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "attached_videos": [],
        "attached_files": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
    }


def _configure(monkeypatch, tmp_path, agent, *, session_key="atomic-session"):
    db = SessionDB(db_path=tmp_path / f"{session_key}.db")
    db.create_session(session_key, source="tui")
    live = _session(agent, session_key)
    server._sessions["sid"] = live
    emitted = []
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_license_signed_in", lambda: True)
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_ensure_tui_tool_profile", lambda *_args: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda _cols: None)
    monkeypatch.setattr(server, "render_message", lambda _text, _cols: None)
    monkeypatch.setattr(server, "_get_usage", lambda _agent: {})
    monkeypatch.setattr(server, "_voice_tts_enabled", lambda: False)
    monkeypatch.setattr(server, "_record_backend_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_record_tui_turn_usage", lambda **_kwargs: None)
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event, sid, payload=None, **_kwargs: emitted.append(
            (event, sid, payload)
        )
        or True,
    )
    return db, live, emitted


def _submit(message_id: str, text: str = "Prepare the listing") -> dict:
    return server.handle_request(
        {
            "id": f"rpc-{message_id}",
            "method": "prompt.submit",
            "params": {
                "session_id": "sid",
                "text": text,
                "user_message_id": message_id,
            },
        }
    )


def _assistant_result(text: str, status: str, kwargs: dict) -> dict:
    result = {
        "final_response": text,
        "messages": [
            {
                "role": "assistant",
                "content": text,
                "client_message_id": kwargs["assistant_message_id"],
            }
        ],
    }
    if status == "pending":
        result.update(
            {
                "completed": False,
                "failed": False,
                "partial": True,
                "pending": True,
                "pending_tool_obligations": [
                    {"tool": "delegate_task", "status": "pending"}
                ],
            }
        )
    elif status == "needs_input":
        result.update(
            {
                "completed": False,
                "failed": False,
                "needs_input": True,
                "partial": True,
                "pending": False,
            }
        )
    elif status == "interrupted":
        result.update({"completed": False, "interrupted": True})
    elif status == "error":
        result.update({"completed": False, "failed": True, "error": text})
    else:
        result["completed"] = True
    return result


def test_terminal_commit_precedes_complete_and_idle(monkeypatch, tmp_path):
    agent = _ResultAgent(
        lambda _prompt, _history, kwargs: _assistant_result(
            "Done", "complete", kwargs
        )
    )
    db, live, emitted = _configure(monkeypatch, tmp_path, agent)
    order = []
    real_terminalize = db.terminalize_prompt_receipt_with_assistant
    real_idle = server._mark_session_idle

    def _terminalize(*args, **kwargs):
        result = real_terminalize(*args, **kwargs)
        order.append("durable-terminal")
        return result

    def _emit(event, sid, payload=None, **_kwargs):
        if event == "message.complete":
            receipt = db.get_prompt_receipt("atomic-session", "turn-order")
            assert receipt["status"] == "complete"
            assert receipt["terminal_payload"] == payload
            order.append("message.complete")
        emitted.append((event, sid, payload))
        return True

    def _idle(session, **kwargs):
        assert db.get_prompt_receipt("atomic-session", "turn-order")["status"] == "complete"
        order.append("idle")
        return real_idle(session, **kwargs)

    db.terminalize_prompt_receipt_with_assistant = _terminalize
    monkeypatch.setattr(server, "_emit", _emit)
    monkeypatch.setattr(server, "_mark_session_idle", _idle)
    try:
        response = _submit("turn-order")
        assert response["result"]["status"] == "streaming"
        assert order == ["durable-terminal", "message.complete", "idle"]
        assert live["running"] is False
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_projection_failure_after_commit_rehydrates_without_false_unknown(
    monkeypatch, tmp_path
):
    agent = _ResultAgent(
        lambda _prompt, _history, kwargs: _assistant_result(
            "Durably done", "complete", kwargs
        )
    )
    db, live, emitted = _configure(monkeypatch, tmp_path, agent)

    def _projection_failure(*_args, **_kwargs):
        raise ValueError("conflicting live projection")

    monkeypatch.setattr(
        server,
        "_project_terminal_assistant_history",
        _projection_failure,
    )
    try:
        response = _submit("turn-projection-failure")
        assert response["result"]["status"] == "streaming"

        completes = [
            payload
            for event, _sid, payload in emitted
            if event == "message.complete"
        ]
        assert len(completes) == 1
        assert not [
            payload
            for event, _sid, payload in emitted
            if event == "error" and payload.get("outcome_unknown")
        ]
        receipt = db.get_prompt_receipt(
            "atomic-session", "turn-projection-failure"
        )
        assert receipt["status"] == "complete"
        assert receipt["terminal_payload"] == completes[0]
        assert live["history"] == db.get_messages_as_conversation(
            "atomic-session"
        )
        assert live["running"] is False

        duplicate = _submit("turn-projection-failure")
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_payload"] == completes[0]
        assert agent.calls == 1
    finally:
        server._sessions.pop("sid", None)
        db.close()


@pytest.mark.parametrize(
    ("wire_status", "receipt_status", "text"),
    [
        ("complete", "complete", "Done"),
        ("pending", "deferred", "Background work is still running"),
        ("needs_input", "waiting_input", "Which province?"),
        ("interrupted", "interrupted", "Stopped"),
        ("error", "error", "Provider failed"),
    ],
)
def test_every_agent_terminal_status_is_atomic_and_duplicate_safe(
    monkeypatch,
    tmp_path,
    wire_status,
    receipt_status,
    text,
):
    agent = _ResultAgent(
        lambda _prompt, _history, kwargs: _assistant_result(
            text, wire_status, kwargs
        )
    )
    message_id = f"turn-{wire_status}"
    db, live, emitted = _configure(
        monkeypatch,
        tmp_path,
        agent,
        session_key=f"session-{wire_status}",
    )
    try:
        first = _submit(message_id)
        assert first["result"]["status"] == "streaming"
        complete = [payload for event, _sid, payload in emitted if event == "message.complete"]
        assert len(complete) == 1
        assert complete[0]["status"] == wire_status

        receipt = db.get_prompt_receipt(f"session-{wire_status}", message_id)
        assert receipt["status"] == receipt_status
        assert receipt["terminal_payload"] == complete[0]
        assert receipt["terminal_message_id"] == complete[0]["message_id"]
        transcript = db.get_messages_as_conversation(f"session-{wire_status}")
        assert transcript[-1]["finish_reason"] == wire_status
        assert live["running"] is False

        duplicate = _submit(message_id)
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_payload"] == complete[0]
        assert duplicate["result"]["message_id"] == complete[0]["message_id"]
        assert agent.calls == 1
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_empty_interrupted_result_is_durable_idle_and_duplicate_safe(
    monkeypatch, tmp_path
):
    def _empty_interrupted(_prompt, _history, kwargs):
        return {
            "completed": False,
            "final_response": None,
            "interrupted": True,
            "messages": [
                {
                    "role": "user",
                    "content": _prompt,
                    "client_message_id": kwargs["user_message_id"],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "client_message_id": kwargs["assistant_message_id"],
                }
            ],
        }

    agent = _ResultAgent(_empty_interrupted)
    db, live, emitted = _configure(monkeypatch, tmp_path, agent)
    try:
        first = _submit("turn-empty-interrupted")
        assert first["result"]["status"] == "streaming"

        completes = [
            payload
            for event, _sid, payload in emitted
            if event == "message.complete"
        ]
        assert len(completes) == 1
        terminal = completes[0]
        assert terminal["status"] == "interrupted"
        assert terminal["text"] == server._INTERRUPTED_BEFORE_RESPONSE_MESSAGE
        assert not [
            payload
            for event, _sid, payload in emitted
            if event == "error" and payload.get("outcome_unknown")
        ]

        receipt = db.get_prompt_receipt(
            "atomic-session", "turn-empty-interrupted"
        )
        assert receipt["status"] == "interrupted"
        assert receipt["terminal_payload"] == terminal
        transcript = db.get_messages_as_conversation("atomic-session")
        assert [message["role"] for message in transcript] == ["user", "assistant"]
        assert transcript[-1]["content"] == terminal["text"]
        assert transcript[-1]["finish_reason"] == "interrupted"
        assert live["history"] == transcript
        assert live["running"] is False

        duplicate = _submit("turn-empty-interrupted")
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_payload"] == terminal
        assert len(
            [event for event, _sid, _payload in emitted if event == "message.complete"]
        ) == 1
        assert db.get_messages_as_conversation("atomic-session") == transcript
        assert agent.calls == 1
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_empty_interrupt_does_not_rewrite_prior_empty_assistant(
    monkeypatch, tmp_path
):
    def _interrupted_without_current_assistant(prompt, history, kwargs):
        return {
            "completed": False,
            "final_response": None,
            "interrupted": True,
            "messages": [
                *history,
                {
                    "role": "user",
                    "content": prompt,
                    "client_message_id": kwargs["user_message_id"],
                },
            ],
        }

    agent = _ResultAgent(_interrupted_without_current_assistant)
    db, live, emitted = _configure(monkeypatch, tmp_path, agent)
    db.append_message(
        "atomic-session",
        "assistant",
        content="",
        finish_reason="stop",
        client_message_id="prior-empty-assistant",
    )
    live["history"] = db.get_messages_as_conversation("atomic-session")
    try:
        first = _submit("turn-empty-interrupted-after-prior")
        assert first["result"]["status"] == "streaming"

        complete = [
            payload
            for event, _sid, payload in emitted
            if event == "message.complete"
        ]
        assert len(complete) == 1
        terminal = complete[0]
        assert terminal["status"] == "interrupted"
        assert terminal["text"] == server._INTERRUPTED_BEFORE_RESPONSE_MESSAGE

        transcript = db.get_messages_as_conversation("atomic-session")
        assert transcript[0] == {
            "role": "assistant",
            "content": "",
            "client_message_id": "prior-empty-assistant",
            "finish_reason": "stop",
        }
        assert transcript[-1]["client_message_id"] == terminal["message_id"]
        assert transcript[-1]["content"] == terminal["text"]
        assert transcript[-1]["finish_reason"] == "interrupted"
        assert live["history"] == transcript
        assert live["running"] is False

        duplicate = _submit("turn-empty-interrupted-after-prior")
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_payload"] == terminal
        assert agent.calls == 1
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_agent_initialization_timeout_terminalizes_without_agent_run(
    monkeypatch, tmp_path
):
    agent = _ResultAgent(
        lambda *_args: pytest.fail("initialization failure must not run the agent")
    )
    waits = {"count": 0}

    def _wait_agent(*_args):
        waits["count"] += 1
        if waits["count"] == 1:
            return None
        return {"error": {"message": "agent initialization timed out"}}

    db, live, emitted = _configure(monkeypatch, tmp_path, agent)
    monkeypatch.setattr(server, "_wait_agent", _wait_agent)
    try:
        response = _submit("turn-init-timeout")
        assert "error" not in response, response
        receipt = db.get_prompt_receipt("atomic-session", "turn-init-timeout")
        assert receipt["status"] == "error"
        assert "timed out" in receipt["terminal_payload"]["text"]
        assert agent.calls == 0
        assert live["running"] is False
        assert [event for event, _sid, _payload in emitted].count(
            "message.complete"
        ) == 1
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_post_claim_policy_bind_failure_terminalizes_once_without_agent_run(
    monkeypatch, tmp_path
):
    from tools import approval

    agent = _ResultAgent(
        lambda *_args: pytest.fail("policy bind failure must not run the agent")
    )
    db, live, emitted = _configure(monkeypatch, tmp_path, agent)

    def _policy_bind_failure(*_args, **_kwargs):
        raise RuntimeError("policy bind failed")

    monkeypatch.setattr(
        approval,
        "set_current_execution_policy",
        _policy_bind_failure,
    )
    try:
        response = _submit("turn-policy-bind-failure")
        assert response["result"]["status"] == "streaming"

        complete = [
            payload
            for event, _sid, payload in emitted
            if event == "message.complete"
        ]
        assert len(complete) == 1
        assert complete[0]["status"] == "error"
        assert "policy bind failed" in complete[0]["text"]

        receipt = db.get_prompt_receipt(
            "atomic-session", "turn-policy-bind-failure"
        )
        assert receipt["status"] == "error"
        assert receipt["terminal_payload"] == complete[0]
        assert receipt["terminal_message_id"] == complete[0]["message_id"]
        transcript = db.get_messages_as_conversation("atomic-session")
        assert [message["role"] for message in transcript] == ["user", "assistant"]
        assert transcript[-1]["finish_reason"] == "error"
        assert transcript[-1]["content"] == complete[0]["text"]
        assert live["running"] is False
        assert agent.calls == 0

        duplicate = _submit("turn-policy-bind-failure")
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_payload"] == complete[0]
        assert len(
            [event for event, _sid, _payload in emitted if event == "message.complete"]
        ) == 1
        assert db.get_messages_as_conversation("atomic-session") == transcript
        assert agent.calls == 0
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_context_reference_block_terminalizes_without_agent_run(monkeypatch, tmp_path):
    import agent.context_references as context_references
    import agent.model_metadata as model_metadata

    agent = _ResultAgent(
        lambda *_args: pytest.fail("blocked context must not run the agent")
    )
    db, live, _emitted = _configure(monkeypatch, tmp_path, agent)
    monkeypatch.setattr(model_metadata, "get_model_context_length", lambda *_a, **_k: 1)
    monkeypatch.setattr(
        context_references,
        "preprocess_context_references",
        lambda *_a, **_k: types.SimpleNamespace(
            blocked=True,
            warnings=["Context path is outside the allowed root."],
            message="",
        ),
    )
    try:
        _submit("turn-context-blocked", "Read @/private/secret")
        receipt = db.get_prompt_receipt("atomic-session", "turn-context-blocked")
        assert receipt["status"] == "error"
        assert "outside the allowed root" in receipt["terminal_payload"]["text"]
        assert agent.calls == 0
        assert live["running"] is False
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_followup_receipt_terminalizes_only_final_reminted_assistant(
    monkeypatch, tmp_path
):
    def _result(_prompt, history, kwargs):
        if not history:
            return {
                "completed": True,
                "final_response": "First round",
                "pending_steer": "Finish the correction",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "First round",
                        "client_message_id": kwargs["assistant_message_id"],
                    }
                ],
            }
        return {
            "completed": True,
            "final_response": "Final round",
            "messages": [
                *history,
                {
                    "role": "assistant",
                    "content": "Final round",
                    "client_message_id": kwargs["assistant_message_id"],
                },
            ],
        }

    agent = _ResultAgent(_result)
    db, _live, emitted = _configure(monkeypatch, tmp_path, agent)
    import agent.title_generator as title_generator

    monkeypatch.setattr(title_generator, "maybe_auto_title", lambda *_a, **_k: None)
    try:
        response = _submit("turn-followup")
        initial_assistant_id = response["result"]["message_id"]
        completes = [payload for event, _sid, payload in emitted if event == "message.complete"]
        assert len(completes) == 2
        assert completes[0]["followup"] is True
        assert completes[0]["message_id"] == initial_assistant_id
        assert "followup" not in completes[1]
        assert completes[1]["message_id"] != initial_assistant_id

        receipt = db.get_prompt_receipt("atomic-session", "turn-followup")
        assert receipt["assistant_message_id"] == initial_assistant_id
        assert receipt["terminal_message_id"] == completes[1]["message_id"]
        assert receipt["terminal_payload"] == completes[1]
        assert agent.calls == 2
    finally:
        server._sessions.pop("sid", None)
        db.close()


def test_context_overflow_commits_before_reset_and_holds_running_fence(
    monkeypatch, tmp_path
):
    def _overflow(_prompt, _history, kwargs):
        return {
            "completed": False,
            "failed": True,
            "error": "maximum context length exceeded",
            "final_response": "maximum context length exceeded",
            "messages": [
                {
                    "role": "assistant",
                    "content": "maximum context length exceeded",
                    "client_message_id": kwargs["assistant_message_id"],
                }
            ],
        }

    agent = _ResultAgent(_overflow)
    db, live, emitted = _configure(monkeypatch, tmp_path, agent)
    order = []
    real_terminalize = db.terminalize_prompt_receipt_with_assistant
    real_idle = server._mark_session_idle

    def _terminalize(*args, **kwargs):
        result = real_terminalize(*args, **kwargs)
        order.append("durable-terminal")
        return result

    def _emit(event, sid, payload=None, **_kwargs):
        if event == "message.complete":
            order.append("message.complete")
        emitted.append((event, sid, payload))
        return True

    def _reset_actor(_sid, session, *, allow_running=False):
        assert allow_running is True
        assert session["running"] is True
        assert db.get_prompt_receipt("atomic-session", "turn-overflow")["status"] == "error"
        session["history"] = []
        session["history_version"] = int(session.get("history_version", 0)) + 1
        order.append("context-reset")

    def _idle(session, **kwargs):
        order.append("idle")
        return real_idle(session, **kwargs)

    db.terminalize_prompt_receipt_with_assistant = _terminalize
    monkeypatch.setattr(server, "_emit", _emit)
    monkeypatch.setattr(server, "_reset_session_agent", _reset_actor)
    monkeypatch.setattr(server, "_mark_session_idle", _idle)
    try:
        _submit("turn-overflow")
        assert order == [
            "durable-terminal",
            "message.complete",
            "context-reset",
            "idle",
        ]
        assert live["running"] is False
        complete = [payload for event, _sid, payload in emitted if event == "message.complete"]
        assert "Session auto-reset" in complete[0]["warning"]
        receipt = db.get_prompt_receipt("atomic-session", "turn-overflow")
        transcript = db.get_messages_as_conversation("atomic-session")
        assert transcript == [
            {
                "role": "assistant",
                "content": complete[0]["text"],
                "finish_reason": "error",
                "client_message_id": complete[0]["message_id"],
            }
        ]
        assert receipt["terminal_message_id"] == complete[0]["message_id"]
        assert receipt["terminal_payload"] == complete[0]
        assert server._history_to_messages(transcript) == [
            {
                "role": "assistant",
                "text": complete[0]["text"],
                "status": "error",
                "message_id": complete[0]["message_id"],
            }
        ]

        duplicate = _submit("turn-overflow")
        assert duplicate["result"]["status"] == "duplicate"
        assert duplicate["result"]["terminal_payload"] == complete[0]
        assert agent.calls == 1
    finally:
        server._sessions.pop("sid", None)
        db.close()
