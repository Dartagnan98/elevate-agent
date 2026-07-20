"""Exit-time memory flush writes traverse the exact-Beta policy boundary.

``flush_memories`` historically wrote the memory store directly
(``tools.memory_tool.memory_tool(...)``), bypassing every accepted-turn
policy gate — ERB lane 5's residual.  Under exact Realtor Beta the flush
write now routes through ``dispatch_builtin_memory_via_registry`` (the
atomic adapter): the undeclared built-in memory tool yields a typed
refusal BEFORE any write under every Beta cohort ceiling.  Outside Beta
the direct call is byte-identical to the legacy behavior.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent
from tools.approval import (
    ExecutionPolicy,
    reset_current_execution_policy,
    set_current_execution_policy,
)


def _make_tool_defs(*names: str) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": f"{n} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for n in names
    ]


def _mock_tool_call(name="memory", arguments="{}", call_id=None):
    return SimpleNamespace(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.fixture
def flush_agent():
    with (
        patch(
            "run_agent.get_tool_definitions",
            return_value=_make_tool_defs("web_search", "memory"),
        ),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        agent.client = MagicMock()
        agent._memory_store = MagicMock()
        agent._memory_flush_min_turns = 1
        agent._user_turn_count = 10
        agent._cached_system_prompt = "system"
        return agent


def _flush_response():
    memory_call = _mock_tool_call(
        name="memory",
        arguments=(
            '{"action":"add","target":"memory","content":"FLUSH_CONTENT"}'
        ),
        call_id="call-flush-beta",
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(content=None, tool_calls=[memory_call]),
            )
        ]
    )


def _messages():
    return [
        {"role": "user", "content": "remember this"},
        {"role": "assistant", "content": "working"},
        {"role": "user", "content": "one more"},
    ]


class TestBetaFlushRefusal:
    def test_exact_beta_flush_write_is_refused_before_the_store(
        self, flush_agent, monkeypatch
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        flush_agent.client.chat.completions.create.return_value = (
            _flush_response()
        )
        messages = _messages()
        with (
            patch(
                "agent.auxiliary_client.call_llm",
                side_effect=RuntimeError("no provider"),
            ),
            patch("tools.memory_tool.memory_tool") as mutate_memory,
        ):
            flush_agent.flush_memories(messages, min_turns=0)

        mutate_memory.assert_not_called()
        flush_agent._memory_store.add_memory.assert_not_called()
        # Flush artifacts are still stripped on the refusal path.
        assert all("_flush_sentinel" not in msg for msg in messages)

    def test_exact_beta_flush_stays_refused_even_with_a_bound_policy(
        self, flush_agent, monkeypatch
    ):
        """The built-in memory tool is deliberately undeclared (UNKNOWN
        effect); even a live accepted-turn draft policy cannot authorize
        the exit-time write."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        flush_agent.session_id = "session-flush-beta"
        flush_agent.client.chat.completions.create.return_value = (
            _flush_response()
        )
        policy = ExecutionPolicy.for_mode("turn-flush-beta", "draft_only")
        token = set_current_execution_policy(policy, policy_revision=1)
        try:
            with (
                patch(
                    "agent.auxiliary_client.call_llm",
                    side_effect=RuntimeError("no provider"),
                ),
                patch("tools.memory_tool.memory_tool") as mutate_memory,
            ):
                flush_agent.flush_memories(_messages(), min_turns=0)
        finally:
            reset_current_execution_policy(token)

        mutate_memory.assert_not_called()


class TestStableFlushParity:
    def test_outside_beta_the_direct_write_is_byte_identical(
        self, flush_agent, monkeypatch
    ):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        flush_agent.client.chat.completions.create.return_value = (
            _flush_response()
        )
        with (
            patch(
                "agent.auxiliary_client.call_llm",
                side_effect=RuntimeError("no provider"),
            ),
            patch("tools.memory_tool.memory_tool") as mutate_memory,
        ):
            flush_agent.flush_memories(_messages(), min_turns=0)

        mutate_memory.assert_called_once_with(
            action="add",
            target="memory",
            content="FLUSH_CONTENT",
            old_text=None,
            store=flush_agent._memory_store,
        )
