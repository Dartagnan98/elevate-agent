import pytest

from agent.result_outcome import agent_result_error, agent_result_succeeded


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
