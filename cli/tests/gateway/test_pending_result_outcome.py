from gateway.run import (
    _normalize_empty_agent_response,
    _should_clear_resume_pending_after_turn,
)


def _pending_result(**overrides):
    return {
        "completed": False,
        "failed": False,
        "partial": True,
        "pending": True,
        "pending_tool_obligations": [
            {
                "tool": "terminal",
                "session_id": "proc-1",
                "status": "pending",
            }
        ],
        **overrides,
    }


def test_pending_response_is_not_rewritten_as_processing_failure():
    text = "The background process is still running."

    assert _normalize_empty_agent_response(_pending_result(), text) == text


def test_empty_pending_response_gets_truthful_default_copy():
    response = _normalize_empty_agent_response(_pending_result(), "")

    assert response == (
        "Work is still pending. Completion has not been verified yet."
    )
    assert "Processing stopped" not in response
    assert "Please retry" not in response


def test_pending_turn_does_not_clear_restart_resume_marker():
    assert _should_clear_resume_pending_after_turn(_pending_result()) is False
