"""Regression tests for truthful /btw terminal outcomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import Platform
from gateway.session import SessionSource


def _make_runner(result):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    adapter = MagicMock()
    adapter.send = AsyncMock()
    adapter.extract_media = MagicMock(return_value=([], result.get("final_response", "")))
    adapter.extract_images = MagicMock(return_value=([], result.get("final_response", "")))
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._running_agents = {}
    runner._service_tier = None
    runner._source_delivery_metadata = lambda _source: {}
    runner._resolve_session_agent_runtime = lambda **_kwargs: (
        "test/model",
        {"api_key": "test-key"},
    )
    runner._load_reasoning_config = lambda: None
    runner._load_service_tier = lambda: None
    runner._resolve_turn_agent_config = lambda _question, model, runtime: {
        "model": model,
        "runtime": runtime,
    }
    runner._cleanup_agent_resources = MagicMock()
    runner._run_in_executor_with_context = AsyncMock(side_effect=lambda func: func())
    session = MagicMock(session_id="session-1")
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session
    runner.session_store.load_transcript.return_value = []
    return runner, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {
            "final_response": "I found three leads before the deadline.",
            "completed": False,
            "partial": True,
            "error": "deadline exceeded",
        },
        {
            "final_response": "",
            "completed": False,
            "failed": True,
            "error": "provider timeout",
        },
    ],
)
async def test_btw_renders_nonempty_and_empty_failures_as_errors(result):
    runner, adapter = _make_runner(result)
    source = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="user-1",
        chat_id="chat-1",
    )

    with patch("run_agent.AIAgent") as agent_class:
        agent_class.return_value.run_conversation.return_value = result
        await runner._run_btw_task("check the leads", source, "session-key", "btw-1")

    content = adapter.send.await_args.kwargs["content"]
    assert "❌ /btw failed" in content
    assert result["error"] in content
    if result["final_response"]:
        assert result["final_response"] in content
    assert "(No response generated)" not in content
    adapter.extract_media.assert_not_called()
    adapter.extract_images.assert_not_called()
