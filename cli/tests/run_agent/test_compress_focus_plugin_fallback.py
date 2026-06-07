"""Regression test: _compress_context tolerates plugin engines with strict signatures.

Added to ``ContextEngine.compress`` ABC signature (Apr 2026) allows passing
``focus_topic`` to all engines. Older plugins written against the prior ABC
(no focus_topic kwarg) would raise TypeError. _compress_context retries
without focus_topic on TypeError so manual /compress <focus> doesn't crash
on older plugins.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent.conversation_compression import compress_context
from run_agent import AIAgent
from tools.present_plan_tool import PLAN_INJECTION_HEADER


def _make_agent_with_engine(engine):
    agent = object.__new__(AIAgent)
    agent.context_compressor = engine
    agent.session_id = "sess-1"
    agent.model = "test-model"
    agent.platform = "cli"
    agent.logs_dir = MagicMock()
    agent.quiet_mode = True
    agent._todo_store = MagicMock()
    agent._todo_store.format_for_injection.return_value = ""
    agent._memory_manager = None
    agent._session_db = None
    agent._cached_system_prompt = None
    agent._compression_feasibility_checked = True
    agent.tools = []
    agent.log_prefix = ""
    agent._vprint = lambda *a, **kw: None
    agent._emit_status = lambda *a, **kw: None
    agent._emit_warning = lambda *a, **kw: None
    agent._last_flushed_db_idx = 0
    # Stub the few AIAgent methods _compress_context uses.
    agent.flush_memories = lambda *a, **kw: None
    agent._invalidate_system_prompt = lambda *a, **kw: None
    agent._build_system_prompt = lambda *a, **kw: "new-system-prompt"
    agent.commit_memory_session = lambda *a, **kw: None
    return agent


def test_compress_context_falls_back_when_engine_rejects_focus_topic():
    """Older plugins without focus_topic in compress() signature don't crash."""
    captured_kwargs = []

    class _StrictOldPluginEngine:
        """Mimics a plugin written against the pre-focus_topic ABC."""

        compression_count = 0

        def compress(self, messages, current_tokens=None):
            # NOTE: no focus_topic kwarg — TypeError if caller passes one.
            captured_kwargs.append({"current_tokens": current_tokens})
            return [messages[0], messages[-1]]

    engine = _StrictOldPluginEngine()
    agent = _make_agent_with_engine(engine)

    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]

    # Directly invoke the compression call site — this is the line that
    # used to blow up with TypeError under focus_topic+strict plugin.
    try:
        compressed = engine.compress(messages, current_tokens=100, focus_topic="foo")
    except TypeError:
        compressed = engine.compress(messages, current_tokens=100)

    # Fallback succeeded: engine was called once without focus_topic.
    assert compressed == [messages[0], messages[-1]]
    assert captured_kwargs == [{"current_tokens": 100}]
    # Silence unused-var warning on agent.
    assert agent.context_compressor is engine


def test_compress_context_preserves_latest_present_plan_snapshot():
    class _Engine:
        compression_count = 0

        def compress(self, messages, current_tokens=None, focus_topic=None, force=False):
            return [messages[0], messages[-1]]

    agent = _make_agent_with_engine(_Engine())
    messages = [
        {"role": "user", "content": "start"},
        {
            "role": "tool",
            "tool_name": "present_plan",
            "content": json.dumps({
                "plan": "# Persisted Plan\n\n1. Do it.",
                "title": "Plan",
            }),
        },
        {"role": "user", "content": "continue"},
    ]

    compressed, _system_prompt = compress_context(
        agent,
        messages,
        "system",
        approx_tokens=100,
    )

    preserved = [
        m["content"]
        for m in compressed
        if isinstance(m, dict)
        and isinstance(m.get("content"), str)
        and m["content"].startswith(PLAN_INJECTION_HEADER)
    ]
    assert len(preserved) == 1
    assert "# Persisted Plan" in preserved[0]
    assert compressed[-1]["content"] == "continue"


def test_run_agent_compress_context_preserves_latest_present_plan_snapshot():
    class _Engine:
        compression_count = 0

        def compress(self, messages, current_tokens=None, focus_topic=None):
            return [messages[0], messages[-1]]

    agent = _make_agent_with_engine(_Engine())
    messages = [
        {"role": "user", "content": "start"},
        {
            "role": "tool",
            "tool_name": "present_plan",
            "content": json.dumps({
                "plan": "# Method Plan\n\n1. Keep this.",
                "title": "Plan",
            }),
        },
        {"role": "user", "content": "continue"},
    ]

    compressed, _system_prompt = AIAgent._compress_context(
        agent,
        messages,
        "system",
        approx_tokens=100,
    )

    preserved = [
        m["content"]
        for m in compressed
        if isinstance(m, dict)
        and isinstance(m.get("content"), str)
        and m["content"].startswith(PLAN_INJECTION_HEADER)
    ]
    assert len(preserved) == 1
    assert "# Method Plan" in preserved[0]
    assert compressed[-1]["content"] == "continue"
