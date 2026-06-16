"""Edge-case coverage for the compaction keepalive heartbeat.

Companion to ``test_compaction_keepalive.py``. That file proves the basic
fire-while-blocked / stop-after / no-beat-when-short behaviour. This one nails
down the corners of the heartbeat loop in ``compress_context``:

* multiple beats land for a multi-interval block (cadence, not just "at least
  one"),
* a raising ``_emit_status`` (or a ``None`` status_callback) does NOT crash the
  heartbeat thread or the compress_context call,
* ``_touch_activity`` is driven on EVERY interval alongside ``_emit_status``
  (the loop calls both, independently guarded),
* a sub-interval compress emits zero beats and zero touches.

All deterministic: a stub compressor that sleeps a fixed wall-clock time and
then raises, so we exercise the heartbeat without dragging in the
session-rotation / DB machinery on the success path. No network, no LLM, no
real ~/.elevate.
"""

import threading
import time

import pytest

from agent.conversation_compression import compress_context


class _SlowCompressor:
    """summarize_to_cursor() that blocks for ``sleep_s`` then raises ``exc``.

    Mirrors the stub in test_compaction_keepalive.py: blocking models a slow
    auxiliary summary call; raising lets us skip the success-path metadata
    write while still exercising the heartbeat + finally teardown.
    """

    def __init__(self, sleep_s, exc=None):
        self._sleep_s = sleep_s
        self._exc = exc
        self.context_length = 200000
        self.threshold_tokens = 170000

    def summarize_to_cursor(self, messages, *, prev_cursor=0,
                            previous_summary=None, focus_topic=None, force=False):
        time.sleep(self._sleep_s)
        if self._exc is not None:
            raise self._exc
        return None, prev_cursor


class _FakeAgent:
    """Minimal agent surface compress_context's heartbeat path touches."""

    def __init__(self, compressor, *, status_callback=True, emit_raises=False):
        self.session_id = "test-session"
        self.model = "test-model"
        self._memory_manager = None
        self._compression_feasibility_checked = True
        self.context_compressor = compressor
        # The heartbeat is a no-op when status_callback is None. Allow the
        # test to null it out to exercise that guard.
        self.status_callback = (lambda *a, **k: None) if status_callback else None
        self._emit_raises = emit_raises
        self.status_emits = []
        self.activity_touches = []

    def _emit_status(self, message):
        self.status_emits.append(message)
        # Only blow up on the HEARTBEAT beats, not the single pre-heartbeat
        # "Compacting context — summarizing…" status. That initial emit at the
        # top of compress_context is intentionally NOT guarded by the
        # heartbeat's try/except, so raising there would abort the call before
        # the thread ever starts and wouldn't test the heartbeat's own guard.
        if self._emit_raises and "still summarizing" in message:
            raise RuntimeError("status sink exploded")

    def _touch_activity(self, desc):
        self.activity_touches.append(desc)

    def _emit_warning(self, message):
        pass


def _beats(agent):
    return [m for m in agent.status_emits if "still summarizing" in m]


def _touch_beats(agent):
    # The initial _emit_status doesn't call _touch_activity; every heartbeat
    # loop does. So activity_touches are 1:1 with heartbeat iterations.
    return [d for d in agent.activity_touches if "compacting context" in d]


# (a) cadence: ~0.7s block at a 0.2s interval -> at least 2-3 beats.
def test_multiple_beats_for_multi_interval_block(monkeypatch):
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "0.2")
    agent = _FakeAgent(_SlowCompressor(0.7, exc=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    beats = _beats(agent)
    # 0.7s / 0.2s -> beats at ~0.2/0.4/0.6s = 3 expected; assert >=2 to stay
    # robust against scheduler jitter / slow CI without going soft on intent.
    assert len(beats) >= 2, agent.status_emits


# (b1) _emit_status raising every call must not crash the thread or the call.
def test_emit_status_raising_does_not_crash_heartbeat(monkeypatch):
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "0.2")
    agent = _FakeAgent(
        _SlowCompressor(0.7, exc=RuntimeError("boom")),
        emit_raises=True,
    )

    # compress_context must still propagate the COMPRESSOR error (RuntimeError
    # "boom"), not die on the status-sink's RuntimeError, and not hang.
    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    # Heartbeat kept looping despite every _emit_status raising: touches still
    # accrued on each interval (touch is guarded independently of emit).
    assert len(_touch_beats(agent)) >= 2, agent.activity_touches

    # And the heartbeat thread is gone — no leaked "compaction-keepalive".
    time.sleep(0.4)
    alive = [t for t in threading.enumerate() if t.name == "compaction-keepalive"]
    assert alive == [], alive


# (b2) status_callback is None: heartbeat no-ops, compress_context completes.
def test_none_status_callback_completes_cleanly(monkeypatch):
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "0.2")
    agent = _FakeAgent(
        _SlowCompressor(0.7, exc=RuntimeError("boom")),
        status_callback=None,
    )

    # The compressor error still propagates; the absent callback must not turn
    # this into a different failure mode or a hang.
    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    # No thread left behind regardless of the callback being None.
    time.sleep(0.4)
    alive = [t for t in threading.enumerate() if t.name == "compaction-keepalive"]
    assert alive == [], alive


# (c) BOTH _touch_activity and _emit_status fire on every interval, 1:1.
def test_touch_and_emit_paired_each_interval(monkeypatch):
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "0.2")
    agent = _FakeAgent(_SlowCompressor(0.7, exc=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    beats = _beats(agent)
    touches = _touch_beats(agent)
    assert len(beats) >= 2, agent.status_emits
    # Each heartbeat loop calls _touch_activity then _emit_status, so the two
    # counters track together. They can differ by at most one (a beat that ran
    # touch then was interrupted before emit by teardown), never more.
    assert abs(len(beats) - len(touches)) <= 1, (agent.status_emits, agent.activity_touches)
    assert len(touches) >= 2, agent.activity_touches


# (d) sub-interval compress -> zero beats AND zero touches.
def test_subinterval_compress_emits_nothing(monkeypatch):
    monkeypatch.setenv("ELEVATE_COMPACTION_KEEPALIVE_INTERVAL", "5.0")
    agent = _FakeAgent(_SlowCompressor(0.05, exc=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        compress_context(agent, [{"role": "user", "content": "hi"}], "sys")

    # First beat only fires AFTER one full interval (the loop waits before its
    # first iteration), so a 0.05s block under a 5s interval yields nothing.
    assert _beats(agent) == [], agent.status_emits
    assert _touch_beats(agent) == [], agent.activity_touches
