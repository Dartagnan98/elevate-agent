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
    # Compaction redesign state (cursor model).
    agent.compaction_cursor = 0
    agent.compaction_summary = None
    agent._usage_projector = None
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


class _CursorEngine:
    """Minimal cursor-model compressor stub: summarize_to_cursor returns a
    (summary, cursor) pair and never assembles/rewrites the transcript."""

    compression_count = 0

    def __init__(self, summary="## Active Task\n# Persisted Plan preserved", cursor=2):
        self._summary = summary
        self._cursor = cursor

    def summarize_to_cursor(self, messages, *, prev_cursor=0, previous_summary=None,
                            focus_topic=None, force=False):
        self.compression_count += 1
        return self._summary, self._cursor


def test_compress_context_does_not_inject_plan_rows_into_transcript():
    # Redesign: the plan is captured by the summarizer (cursor model), NOT
    # re-injected as a PLAN_INJECTION_HEADER message row. The transcript is
    # returned UNCHANGED — append-only, never rewritten.
    agent = _make_agent_with_engine(_CursorEngine())
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
    snapshot = [dict(m) for m in messages]

    compressed, _system_prompt = compress_context(
        agent, messages, "system", approx_tokens=100,
    )

    # Transcript untouched: no injected plan row, same list contents.
    assert compressed == snapshot
    injected = [
        m for m in compressed
        if isinstance(m, dict)
        and isinstance(m.get("content"), str)
        and m["content"].startswith(PLAN_INJECTION_HEADER)
    ]
    assert injected == []
    # The cursor + summary moved to agent metadata instead of a row.
    assert agent.compaction_cursor == 2
    assert agent.compaction_summary is not None


def test_run_agent_compress_context_sets_cursor_not_plan_row():
    agent = _make_agent_with_engine(_CursorEngine(cursor=2))
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
    snapshot = [dict(m) for m in messages]

    compressed, _system_prompt = AIAgent._compress_context(
        agent, messages, "system", approx_tokens=100,
    )

    assert compressed == snapshot  # transcript never rewritten
    injected = [
        m for m in compressed
        if isinstance(m, dict)
        and isinstance(m.get("content"), str)
        and m["content"].startswith(PLAN_INJECTION_HEADER)
    ]
    assert injected == []
    assert agent.compaction_cursor == 2
