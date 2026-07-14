from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.codex_runtime import run_codex_app_server_turn
from agent.transports.codex_app_server_session import (
    CodexAppServerSession,
    TurnResult,
)


class _NotificationClient:
    def __init__(self, notification):
        self._notifications = [notification]

    def initialize(self, **_kwargs):
        return None

    def request(self, method, _params, timeout):
        del timeout
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(f"unexpected request: {method}")

    def take_server_request(self, timeout):
        del timeout
        return None

    def take_notification(self, timeout):
        del timeout
        if self._notifications:
            return self._notifications.pop(0)
        return None

    def is_alive(self):
        return True

    def stderr_tail(self, _line_count):
        return []

    def close(self):
        return None


def _run_session_status(status, error=None):
    turn = {}
    if status is not None:
        turn["status"] = status
    if error is not None:
        turn["error"] = error
    notification = {
        "method": "turn/completed",
        "params": {"turn": turn},
    }
    client = _NotificationClient(notification)
    session = CodexAppServerSession(client_factory=lambda **_kwargs: client)
    return session.run_turn(
        "test terminal state",
        turn_timeout=0.2,
        notification_poll_timeout=0,
    )


@pytest.mark.parametrize(
    (
        "status",
        "expected_terminal_status",
        "expected_interrupted",
        "expects_error",
    ),
    [
        ("completed", "completed", False, False),
        ("interrupted", "interrupted", True, False),
        ("failed", "failed", False, True),
        (None, None, False, True),
        ("future_terminal", "future_terminal", False, True),
        ("Completed", "Completed", False, True),
    ],
)
def test_session_requires_exact_completed_terminal_status(
    status,
    expected_terminal_status,
    expected_interrupted,
    expects_error,
):
    result = _run_session_status(status)

    assert result.terminal_status == expected_terminal_status
    assert result.interrupted is expected_interrupted
    assert bool(result.error) is expects_error


def test_session_failed_without_error_payload_synthesizes_error():
    result = _run_session_status("failed")

    assert result.error
    assert "failed" in result.error


def test_session_preserves_failed_error_payload():
    result = _run_session_status("failed", {"message": "provider exploded"})

    assert result.error
    assert "provider exploded" in result.error


class _StaticSession:
    def __init__(self, turn):
        self._turn = turn
        self.close = MagicMock()

    def run_turn(self, *, user_input):
        assert user_input == "hello"
        return self._turn


def _run_wrapper(turn):
    session = _StaticSession(turn)
    agent = SimpleNamespace(
        _codex_session=session,
        _iters_since_skill=0,
        _skill_nudge_interval=0,
        valid_tool_names=set(),
        _sync_external_memory_for_turn=MagicMock(),
        _spawn_background_review=MagicMock(),
    )
    messages = [{"role": "user", "content": "hello"}]
    result = run_codex_app_server_turn(
        agent,
        user_message="hello",
        original_user_message="hello",
        messages=messages,
        effective_task_id="task-1",
    )
    return result, agent


@pytest.mark.parametrize(
    (
        "terminal_status",
        "final_text",
        "interrupted",
        "turn_error",
        "expected_completed",
        "expects_error",
    ),
    [
        ("completed", "verified answer", False, None, True, False),
        ("interrupted", "partial answer", True, None, False, False),
        ("failed", "", False, "provider failed", False, True),
        ("failed", "", True, "", False, True),
        (None, "", False, None, False, True),
        ("future_terminal", "unverified answer", False, None, False, True),
        ("completed", "   ", False, None, False, True),
        ("completed", "answer", True, None, False, True),
    ],
)
def test_run_codex_app_server_turn_requires_verified_nonempty_completion(
    terminal_status,
    final_text,
    interrupted,
    turn_error,
    expected_completed,
    expects_error,
):
    turn = TurnResult(
        terminal_status=terminal_status,
        final_text=final_text,
        interrupted=interrupted,
        error=turn_error,
        thread_id="thread-1",
        turn_id="turn-1",
    )

    result, agent = _run_wrapper(turn)

    assert result["completed"] is expected_completed
    assert result["partial"] is (not expected_completed)
    assert bool(result["error"]) is expects_error
    if expected_completed:
        agent._sync_external_memory_for_turn.assert_called_once()
    else:
        agent._sync_external_memory_for_turn.assert_not_called()
