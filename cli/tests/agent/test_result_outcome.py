import pytest

from agent.result_outcome import (
    agent_result_error,
    agent_result_needs_input,
    agent_result_pending,
    agent_result_succeeded,
)


@pytest.mark.parametrize(
    "sentinel",
    [
        {"interrupted": True},
        {"failed": True},
        {"partial": True},
        {"error": "provider failed"},
        {"completed": False},
    ],
)
def test_nonempty_failure_sentinels_never_succeed(sentinel):
    result = {"final_response": "nonempty failure text", **sentinel}

    assert agent_result_succeeded(result) is False
    assert agent_result_error(result) in {"provider failed", "nonempty failure text"}


def test_legacy_result_without_explicit_completed_flag_still_succeeds():
    assert agent_result_succeeded({"final_response": "done"}) is True


@pytest.mark.parametrize("completed", [None, True])
def test_empty_result_never_succeeds(completed):
    result = {"final_response": ""}
    if completed is not None:
        result["completed"] = completed

    assert agent_result_succeeded(result) is False


def test_explicit_tool_obligation_is_pending_not_success_or_error():
    result = {
        "completed": False,
        "failed": False,
        "final_response": "Work is still running.",
        "partial": True,
        "pending": True,
        "pending_tool_obligations": [
            {"tool": "delegate_task", "task_id": "child-1", "status": "pending"}
        ],
    }

    assert agent_result_pending(result) is True
    assert agent_result_succeeded(result) is False


@pytest.mark.parametrize(
    "override",
    [
        {"pending_tool_obligations": []},
        {"pending_tool_obligations": [{"tool": "terminal", "status": "completed"}]},
        {"failed": True},
        {"error": "delivery failed"},
        {"interrupted": True},
        {"partial": False},
    ],
)
def test_pending_requires_clean_explicit_obligation(override):
    result = {
        "completed": False,
        "failed": False,
        "partial": True,
        "pending": True,
        "pending_tool_obligations": [
            {"tool": "terminal", "session_id": "proc-1", "status": "pending"}
        ],
        **override,
    }

    assert agent_result_pending(result) is False


def test_explicit_clarification_is_needs_input_not_success_pending_or_error():
    result = {
        "completed": False,
        "failed": False,
        "final_response": "Which province is this transaction in?",
        "needs_input": True,
        "partial": True,
        "pending": False,
    }

    assert agent_result_needs_input(result) is True
    assert agent_result_pending(result) is False
    assert agent_result_succeeded(result) is False


@pytest.mark.parametrize(
    "override",
    [
        {"final_response": ""},
        {"failed": True},
        {"error": "clarification failed"},
        {"interrupted": True},
        {"pending": True},
        {"partial": False},
        {"completed": True},
    ],
)
def test_needs_input_requires_clean_explicit_question(override):
    result = {
        "completed": False,
        "failed": False,
        "final_response": "Which province is this transaction in?",
        "needs_input": True,
        "partial": True,
        "pending": False,
        **override,
    }

    assert agent_result_needs_input(result) is False
