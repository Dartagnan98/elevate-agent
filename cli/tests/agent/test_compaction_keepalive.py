"""Keepalive heartbeat for the blocking compaction summary call.

compress() runs the auxiliary summary LLM synchronously and can block the turn
for tens of seconds. Without a keepalive the dashboard WebSocket idles and gets
dropped, so post-compaction frames land on a dead socket and the chat looks
hung. compress_context wraps the call in a heartbeat that re-emits status and
touches activity while it blocks, then stops in a finally. These tests prove it
fires during the block and stops afterward.
"""

import time

import pytest

from agent.conversation_compression import compress_context


class _SlowCompressor:
    """summarize_to_cursor() that blocks, then optionally raises, to model a
    slow summary (the redesign call compress_context wraps in the heartbeat)."""

    def __init__(self, sleep_s, exc=None):
        self._sleep_s = sleep_s
        self._exc = exc
        # Attributes compressor_stats() reads; the rest default to None.
        self.context_length = 200000
        self.threshold_tokens = 170000

    def summarize_to_cursor(self, messages, *, prev_cursor=0,
                            previous_summary=None, focus_topic=None, force=False):
        time.sleep(self._sleep_s)
        if self._exc is not None:
            raise self._exc
        return None, prev_cursor


class _FakeAgent:
    def __init__(self, compressor):
        self.session_id = "test-session"
        self.model = "test-model"
        self._memory_manager = None
        self._compression_feasibility_checked = True
        self.context_compressor = compressor
        self.status_callback = lambda *a, **k: None
        self.status_emits = []
        self.activity_touches = []

    def _emit_status(self, message):
        self.status_emits.append(message)

    def _touch_activity(self, desc):
        self.activity_touches.append(desc)

    def _emit_warning(self, message):
        pass


def test_keepalive_fires_while_compress_blocks_and_stops_after(monkeypatch):
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "0.2")
    # Raise out of compress() so we exercise the heartbeat without dragging in
    # the session-rotation / DB machinery that runs on the success path.
    agent = _FakeAgent(_SlowCompressor(0.9, exc=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    beats = [m for m in agent.status_emits if "still summarizing" in m]
    assert len(beats) >= 2, agent.status_emits
    assert len(agent.activity_touches) >= 2, agent.activity_touches

    # Heartbeat thread stopped in the finally: no further beats after return.
    n = len(agent.status_emits)
    time.sleep(0.5)
    assert len(agent.status_emits) == n, "heartbeat thread leaked past compress_context"


def test_short_compaction_emits_no_heartbeat(monkeypatch):
    # Faster than one interval -> only the initial "summarizing" status, no beats.
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "5.0")
    agent = _FakeAgent(_SlowCompressor(0.05, exc=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    beats = [m for m in agent.status_emits if "still summarizing" in m]
    assert beats == [], agent.status_emits
