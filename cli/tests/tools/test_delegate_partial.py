"""Tests for the delegate_task partial-success contract + rate-limit telemetry.

2026-06-09 audit fixes:

- BUG 2: when a delegated child dies (timeout, error, empty response), the
  parent used to receive a bare failure with none of the child's work
  product.  _run_single_child now attaches ``partial: True`` +
  ``partial_output`` (last assistant text, tool-call count, output tail) on
  every non-completed entry so the parent can salvage instead of blind-
  retrying.  The success-path entry shape is unchanged.

- BUG 3: a child sitting in 429 backoff just looked "slow".  The child
  agent now counts rate-limit events (run_agent.py) and _run_single_child
  copies ``rate_limit_hits`` / ``rate_limit_backoff_seconds`` onto the
  result entry (success or failure) whenever hits > 0.

These tests deliberately avoid the shared MagicMock fixtures used by
tests/tools/test_delegate.py — they build a plain stub child instead.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from tools.delegate_tool import (
    _attach_rate_limit_telemetry,
    _build_partial_result_payload,
    _run_single_child,
    _PARTIAL_TEXT_MAX_CHARS,
)


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    return home


SAMPLE_MESSAGES = [
    {"role": "user", "content": "summarize the report"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "tc1", "function": {"name": "read_file", "arguments": '{"path": "report.md"}'}},
        ],
    },
    {"role": "tool", "tool_call_id": "tc1", "content": "report contents: revenue up 12%"},
    {"role": "assistant", "content": "Halfway done: revenue is up 12%, drafting the summary now."},
]


class _StubChild:
    """Plain stand-in for an AIAgent subagent (no MagicMock)."""

    def __init__(
        self,
        *,
        run_result=None,
        run_exc: Exception | None = None,
        hang_seconds: float = 0.0,
        live_messages=None,
        rate_limit_hits: int = 0,
        rate_limit_backoff: float = 0.0,
        api_call_count: int = 2,
    ):
        self.session_id = "child-sess-1"
        self.model = "test/model"
        self.tool_progress_callback = None
        self._delegate_role = "leaf"
        self._subagent_id = None  # skip TUI registry
        self._delegate_saved_tool_names = []
        self._session_messages = live_messages if live_messages is not None else []
        self.session_prompt_tokens = 10
        self.session_completion_tokens = 5
        self.session_reasoning_tokens = 0
        self.session_estimated_cost_usd = 0.0
        self.session_rate_limit_hits = rate_limit_hits
        self.session_rate_limit_backoff_seconds = rate_limit_backoff
        self._run_result = run_result
        self._run_exc = run_exc
        self._api_call_count = api_call_count
        self._hang = threading.Event()
        self._hang_seconds = hang_seconds
        self.interrupted = False
        self.closed = False

    def run_conversation(self, user_message, task_id=None, **_kw):
        if self._hang_seconds:
            self._hang.wait(self._hang_seconds)
        if self._run_exc is not None:
            raise self._run_exc
        return self._run_result

    def get_activity_summary(self):
        return {
            "api_call_count": self._api_call_count,
            "max_iterations": 50,
            "current_tool": None,
            "seconds_since_activity": 1,
        }

    def interrupt(self):
        self.interrupted = True
        self._hang.set()

    def close(self):
        self.closed = True


# ── _build_partial_result_payload ──────────────────────────────────────

class TestBuildPartialResultPayload:
    def test_salvages_text_tools_and_tail_from_result(self):
        payload = _build_partial_result_payload(
            _StubChild(), {"messages": SAMPLE_MESSAGES}
        )
        assert payload is not None
        assert "revenue is up 12%" in payload["last_assistant_text"]
        assert payload["tool_calls"] == 1
        assert payload["output_tail"]
        assert payload["output_tail"][-1]["tool"] == "read_file"
        assert "revenue up 12%" in payload["output_tail"][-1]["preview"]

    def test_falls_back_to_live_transcript(self):
        child = _StubChild(live_messages=SAMPLE_MESSAGES)
        payload = _build_partial_result_payload(child, None)
        assert payload is not None
        assert "revenue is up 12%" in payload["last_assistant_text"]

    def test_block_content_assistant_messages(self):
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "found the answer: 42"},
                ],
            },
        ]
        payload = _build_partial_result_payload(_StubChild(), {"messages": messages})
        assert payload["last_assistant_text"] == "found the answer: 42"

    def test_nothing_to_salvage_returns_none(self):
        assert _build_partial_result_payload(_StubChild(), None) is None
        assert _build_partial_result_payload(
            _StubChild(), {"messages": [{"role": "user", "content": "hi"}]}
        ) is None

    def test_long_text_is_tail_truncated(self):
        long_text = "x" * 10_000 + " FINAL FINDINGS"
        messages = [{"role": "assistant", "content": long_text}]
        payload = _build_partial_result_payload(_StubChild(), {"messages": messages})
        assert len(payload["last_assistant_text"]) <= _PARTIAL_TEXT_MAX_CHARS
        # The END of the message (latest findings) is what survives.
        assert payload["last_assistant_text"].endswith("FINAL FINDINGS")

    def test_magicmock_child_degrades_to_none(self):
        # MagicMock attrs aren't lists — salvage must not blow up on doubles.
        assert _build_partial_result_payload(MagicMock(), None) is None


# ── _attach_rate_limit_telemetry ───────────────────────────────────────

class TestAttachRateLimitTelemetry:
    def test_zero_hits_adds_no_keys(self):
        entry = {"status": "completed"}
        _attach_rate_limit_telemetry(entry, _StubChild())
        assert entry == {"status": "completed"}

    def test_hits_propagate_with_backoff_seconds(self):
        entry = {"status": "completed"}
        _attach_rate_limit_telemetry(
            entry, _StubChild(rate_limit_hits=3, rate_limit_backoff=12.34)
        )
        assert entry["rate_limit_hits"] == 3
        assert entry["rate_limit_backoff_seconds"] == 12.3

    def test_magicmock_attrs_are_ignored(self):
        entry = {"status": "completed"}
        _attach_rate_limit_telemetry(entry, MagicMock())
        assert entry == {"status": "completed"}


# ── _run_single_child integration (stub child, real plumbing) ─────────

class TestRunSingleChildPartialContract:
    def test_timeout_carries_partial_output(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 0.3)
        child = _StubChild(hang_seconds=5.0, live_messages=SAMPLE_MESSAGES)
        try:
            entry = _run_single_child(0, "summarize", child, None)
        finally:
            child.interrupt()

        assert entry["status"] == "timeout"
        assert entry["partial"] is True
        assert "revenue is up 12%" in entry["partial_output"]["last_assistant_text"]
        assert entry["partial_output"]["tool_calls"] == 1
        assert child.interrupted is True

    def test_worker_exception_carries_partial_output(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 30.0)
        child = _StubChild(
            run_exc=RuntimeError("provider exploded"),
            live_messages=SAMPLE_MESSAGES,
        )
        entry = _run_single_child(0, "summarize", child, None)

        assert entry["status"] == "error"
        assert "provider exploded" in entry["error"]
        assert entry["partial"] is True
        assert "revenue is up 12%" in entry["partial_output"]["last_assistant_text"]

    def test_failed_empty_response_carries_partial_output(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 30.0)
        child = _StubChild(
            run_result={
                "final_response": "",
                "completed": True,
                "api_calls": 3,
                "messages": SAMPLE_MESSAGES,
            }
        )
        entry = _run_single_child(0, "summarize", child, None)

        assert entry["status"] == "failed"
        assert entry["partial"] is True
        assert "revenue is up 12%" in entry["partial_output"]["last_assistant_text"]

    def test_failure_with_no_work_product_has_no_partial(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 30.0)
        child = _StubChild(
            run_result={"final_response": "", "completed": True, "api_calls": 0, "messages": []}
        )
        entry = _run_single_child(0, "summarize", child, None)

        assert entry["status"] == "failed"
        assert "partial" not in entry
        assert "partial_output" not in entry

    def test_success_path_shape_unchanged(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 30.0)
        child = _StubChild(
            run_result={
                "final_response": "All done.",
                "completed": True,
                "api_calls": 2,
                "messages": SAMPLE_MESSAGES,
            }
        )
        entry = _run_single_child(0, "summarize", child, None)

        assert entry["status"] == "completed"
        assert entry["summary"] == "All done."
        # Success-path stays byte-compatible: no new keys for the common case.
        assert "partial" not in entry
        assert "partial_output" not in entry
        assert "rate_limit_hits" not in entry
        assert "rate_limit_backoff_seconds" not in entry

    def test_rate_limit_hits_propagate_on_success(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 30.0)
        child = _StubChild(
            run_result={
                "final_response": "Done despite throttling.",
                "completed": True,
                "api_calls": 5,
                "messages": [],
            },
            rate_limit_hits=4,
            rate_limit_backoff=33.0,
        )
        entry = _run_single_child(0, "summarize", child, None)

        assert entry["status"] == "completed"
        assert entry["rate_limit_hits"] == 4
        assert entry["rate_limit_backoff_seconds"] == 33.0

    def test_rate_limit_hits_propagate_on_timeout(self, hermes_home, monkeypatch):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 0.3)
        child = _StubChild(
            hang_seconds=5.0,
            live_messages=SAMPLE_MESSAGES,
            rate_limit_hits=2,
            rate_limit_backoff=60.0,
        )
        try:
            entry = _run_single_child(0, "summarize", child, None)
        finally:
            child.interrupt()

        assert entry["status"] == "timeout"
        assert entry["rate_limit_hits"] == 2
        assert entry["rate_limit_backoff_seconds"] == 60.0


# ── child-agent counters exist on AIAgent (BUG 3 wiring sanity) ───────

def test_aiagent_defines_rate_limit_counters():
    """The counters delegate_tool reads must exist in AIAgent.__init__
    (grep-level pin so a refactor can't silently drop the telemetry)."""
    import inspect
    import run_agent

    src = inspect.getsource(run_agent.AIAgent.__init__)
    assert "self.session_rate_limit_hits" in src
    assert "self.session_rate_limit_backoff_seconds" in src
