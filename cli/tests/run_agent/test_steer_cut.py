"""Steer-cut state machine: a /steer aborts an in-flight call mid-think.

The contract under test (see SteerCutInterrupt in run_agent.py):

- While the model is mid-think — reasoning deltas streaming, or the stream
  opened but no answer text yet — a steer/soft-interrupt requests a cut of
  the in-flight API call so it applies immediately.
- Once the final answer is streaming ("resolving"), the call is left to
  finish; the existing after-text drain delivers the steer right after.
- Non-streaming calls and idle windows are never cut.
- A stale cut flag self-heals when the pending payload was already drained
  through another injection point.
"""

from __future__ import annotations

import threading

from run_agent import AIAgent, SteerCutInterrupt


def _bare_agent() -> AIAgent:
    """Minimal AIAgent with just the steer/stream state, no __init__."""
    agent = object.__new__(AIAgent)
    agent._pending_steer = None
    agent._pending_steer_lock = threading.Lock()
    agent._pending_soft_interrupts = []
    agent._pending_soft_interrupts_lock = threading.Lock()
    agent._steer_cut_requested = False
    agent._stream_phase = "idle"
    agent.quiet_mode = True
    agent.log_prefix = ""
    agent.reasoning_callback = None
    agent.stream_delta_callback = None
    agent._stream_callback = None
    return agent


class TestCutRequestPhases:
    def test_thinking_phase_requests_cut(self):
        agent = _bare_agent()
        agent._stream_phase = "thinking"
        assert agent.steer("go check the logs instead")
        assert agent._steer_cut_requested is True

    def test_waiting_stream_phase_requests_cut(self):
        agent = _bare_agent()
        agent._stream_phase = "waiting_stream"
        assert agent.queue_soft_interrupt("change of plan")
        assert agent._steer_cut_requested is True

    def test_resolving_phase_never_cuts(self):
        # The model is streaming its final answer — almost done. The steer
        # waits for the after-text drain instead of cutting.
        agent = _bare_agent()
        agent._stream_phase = "resolving"
        assert agent.steer("actually do X")
        assert agent._steer_cut_requested is False

    def test_nonstream_phase_never_cuts(self):
        # No phase signal on a non-streaming call — aborting could discard
        # an already-complete response.
        agent = _bare_agent()
        agent._stream_phase = "nonstream"
        assert agent.steer("actually do X")
        assert agent._steer_cut_requested is False

    def test_idle_phase_never_cuts(self):
        agent = _bare_agent()
        agent._stream_phase = "idle"
        assert agent.queue_soft_interrupt("new info")
        assert agent._steer_cut_requested is False


class TestPhaseTransitions:
    def test_reasoning_delta_marks_thinking(self):
        agent = _bare_agent()
        agent._stream_phase = "waiting_stream"
        agent._fire_reasoning_delta("hmm, let me think")
        assert agent._stream_phase == "thinking"

    def test_stream_delta_marks_resolving(self):
        agent = _bare_agent()
        agent._stream_phase = "thinking"
        agent._fire_stream_delta("The answer is")
        assert agent._stream_phase == "resolving"

    def test_reasoning_never_downgrades_resolving(self):
        # Interleaved trailing reasoning must not re-open the cut window
        # once the final answer started streaming.
        agent = _bare_agent()
        agent._stream_phase = "resolving"
        agent._fire_reasoning_delta("one more thought")
        assert agent._stream_phase == "resolving"

    def test_codex_nonstream_branch_upgrades_to_thinking(self):
        # Codex streams internally even on the non-streaming dispatch branch;
        # its reasoning deltas arm the cut window.
        agent = _bare_agent()
        agent._stream_phase = "nonstream"
        agent._fire_reasoning_delta("reasoning…")
        assert agent._stream_phase == "thinking"
        assert agent.steer("redirect") and agent._steer_cut_requested is True


class TestConsumeCutRequest:
    def test_consumes_when_steer_pending(self):
        agent = _bare_agent()
        agent._stream_phase = "thinking"
        agent.steer("redirect")
        assert agent._consume_steer_cut_request() is True

    def test_consumes_when_soft_interrupt_pending(self):
        agent = _bare_agent()
        agent._stream_phase = "thinking"
        agent.queue_soft_interrupt("redirect")
        assert agent._consume_steer_cut_request() is True

    def test_no_flag_no_cut(self):
        agent = _bare_agent()
        agent._pending_steer = "queued but no cut requested"
        assert agent._consume_steer_cut_request() is False

    def test_stale_flag_self_heals_after_drain(self):
        # The payload was delivered through another drain point (tool result
        # injection) before the poll loop saw the flag — nothing left to cut
        # for, and the flag must not abort the NEXT call.
        agent = _bare_agent()
        agent._stream_phase = "thinking"
        agent.steer("redirect")
        agent._drain_pending_steer()
        assert agent._consume_steer_cut_request() is False
        assert agent._steer_cut_requested is False

    def test_clear_interrupt_clears_cut_flag(self):
        agent = _bare_agent()
        # clear_interrupt touches a wider set of attrs.
        agent._interrupt_requested = True
        agent._interrupt_message = None
        agent._interrupt_thread_signal_pending = False
        agent._execution_thread_id = None
        agent._tool_worker_threads = set()
        agent._tool_worker_threads_lock = threading.Lock()
        agent._stream_phase = "thinking"
        agent.steer("redirect")
        assert agent._steer_cut_requested is True
        agent.clear_interrupt()
        assert agent._steer_cut_requested is False
        assert agent._pending_steer is None


class TestSteerCutInterruptType:
    def test_not_an_interrupted_error(self):
        # The retry loop must be able to distinguish a steer cut (re-issue
        # the call) from a hard interrupt (end the turn).
        assert not issubclass(SteerCutInterrupt, InterruptedError)
        assert issubclass(SteerCutInterrupt, Exception)
