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
from types import SimpleNamespace
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
        self.run_calls = 0

    def run_conversation(self, user_message, task_id=None, **_kw):
        self.run_calls += 1
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


class _IgnoringInterruptChild(_StubChild):
    """Provider stand-in whose in-flight request ignores child.interrupt()."""

    def __init__(self):
        super().__init__(
            run_result={
                "final_response": "late result",
                "completed": True,
                "api_calls": 1,
                "messages": [],
            },
            api_call_count=1,
        )
        self.worker_started = threading.Event()
        self.release_worker = threading.Event()

    def run_conversation(self, user_message, task_id=None, **_kw):
        self.run_calls += 1
        self.worker_started.set()
        self.release_worker.wait(timeout=30.0)
        return self._run_result

    def interrupt(self, *_args, **_kwargs):
        # Deliberately record but ignore the interrupt, matching an unresponsive
        # provider socket that remains live beyond delegate_task's timeout.
        self.interrupted = True


class _ObservedSemaphore:
    def __init__(self, capacity: int, *, held_slots: int = 0):
        self._sem = threading.BoundedSemaphore(capacity)
        self.acquire_attempted = threading.Event()
        for _ in range(held_slots):
            assert self._sem.acquire(timeout=0.1)

    def acquire(self, timeout=None):
        self.acquire_attempted.set()
        return self._sem.acquire(timeout=timeout)

    def release(self):
        self._sem.release()


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
    def test_ignored_interrupt_quiesces_parent_turn_but_blocks_provider_repair(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool
        from agent.turn_fence import TurnFence, bind_turn_fence

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 0.1)
        child = _IgnoringInterruptChild()
        parent = SimpleNamespace(
            _active_children=[child],
            _active_children_lock=threading.Lock(),
            _current_task_id=None,
        )
        fence = TurnFence()
        token = fence.begin_turn("prompt-1", "session-1")
        fence.bind_worker(token)

        lease = None
        repair_quiesced = False
        try:
            with bind_turn_fence(fence, token, defer_terminal_seal=True):
                entry = _run_single_child(0, "keep running", child, parent)
                assert entry["status"] == "timeout"
                assert child.worker_started.wait(timeout=1.0)
                assert child.interrupted is True
                assert child.closed is False
                assert child in parent._active_children

                sealed = fence.seal_terminal(token, terminal_status="error")
                assert sealed["terminal_committed"] is True

            fence.finish_worker(token, terminal_status="error")
            # Async/background delegation must not make the chat session look
            # stalled after its parent terminal receipt is committed.
            assert fence.wait_generation_quiesced(token, timeout=0.05) is True

            lease = delegate_tool.begin_delegate_provider_repair()
            assert delegate_tool.interrupt_delegate_provider_repair(lease) == 1
            assert (
                delegate_tool.wait_for_delegate_provider_quiescence(
                    lease,
                    timeout=0.05,
                )
                is False
            )
            assert child.closed is False
            assert child in parent._active_children
        finally:
            child.release_worker.set()
            if lease is not None:
                repair_quiesced = delegate_tool.wait_for_delegate_provider_quiescence(
                    lease,
                    timeout=2.0,
                )
                delegate_tool.release_delegate_provider_repair(lease)

        assert lease is not None
        assert repair_quiesced is True
        assert child.closed is True
        assert child not in parent._active_children

    def test_provider_repair_counts_child_reserved_before_thread_start(
        self,
        hermes_home,
    ):
        import tools.delegate_tool as delegate_tool

        child = _IgnoringInterruptChild()
        children = [(0, {"goal": "pending"}, child)]
        delegate_tool._reserve_delegate_workers(children)
        lease = delegate_tool.begin_delegate_provider_repair()
        try:
            assert child.interrupted is True
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.05,
            ) is False
            delegate_tool._release_unclaimed_delegate_workers(children)
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.5,
            ) is True
        finally:
            delegate_tool.release_delegate_provider_repair(lease)

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

    @pytest.mark.parametrize(
        ("run_result", "expected_status", "expected_end_reason"),
        [
            (
                {
                    "final_response": "All done.",
                    "completed": True,
                    "api_calls": 1,
                    "messages": [],
                },
                "completed",
                "delegation_complete",
            ),
            (
                {
                    "final_response": "",
                    "completed": False,
                    "failed": True,
                    "api_calls": 1,
                    "messages": [],
                },
                "failed",
                "delegation_failed",
            ),
            (
                {
                    "final_response": "partial",
                    "completed": False,
                    "interrupted": True,
                    "api_calls": 1,
                    "messages": [],
                },
                "interrupted",
                "delegation_interrupted",
            ),
        ],
        ids=["success", "failure", "interrupted"],
    )
    def test_session_end_reason_matches_public_child_outcome(
        self,
        hermes_home,
        monkeypatch,
        run_result,
        expected_status,
        expected_end_reason,
    ):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 30.0)
        end_session = MagicMock()
        child = _StubChild(run_result=run_result)
        child._session_db = SimpleNamespace(end_session=end_session)

        entry = _run_single_child(0, "persist truthful outcome", child, None)

        assert entry["status"] == expected_status
        end_session.assert_called_once_with(child.session_id, expected_end_reason)

    def test_timeout_persists_timeout_reason_after_worker_cleanup(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 0.1)
        end_session = MagicMock()
        child = _StubChild(hang_seconds=5.0)
        child._session_db = SimpleNamespace(end_session=end_session)

        entry = _run_single_child(0, "time out", child, None)
        deadline = time.monotonic() + 2.0
        while not end_session.called and time.monotonic() < deadline:
            time.sleep(0.01)

        assert entry["status"] == "timeout"
        end_session.assert_called_once_with(
            child.session_id,
            "delegation_timeout",
        )

    def test_deferred_noncooperative_exit_cannot_rewrite_timeout_as_complete(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 0.1)
        end_session = MagicMock()
        child = _IgnoringInterruptChild()
        child._session_db = SimpleNamespace(end_session=end_session)

        try:
            entry = _run_single_child(0, "ignore timeout", child, None)
            assert entry["status"] == "timeout"
            end_session.assert_not_called()
        finally:
            child.release_worker.set()

        deadline = time.monotonic() + 2.0
        while not end_session.called and time.monotonic() < deadline:
            time.sleep(0.01)
        end_session.assert_called_once_with(
            child.session_id,
            "delegation_timeout",
        )

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


# ── leaf-cap and single-child interruption containment ─────────────────

class TestLeafConcurrencyContainment:
    @staticmethod
    def _parent(children):
        return SimpleNamespace(
            _active_children=list(children),
            _active_children_lock=threading.Lock(),
            _current_task_id=None,
            _interrupt_requested=False,
        )

    @staticmethod
    def _reserve(delegate_tool, children):
        built = [
            (index, {"goal": f"task {index}"}, child)
            for index, child in enumerate(children)
        ]
        delegate_tool._reserve_delegate_workers(built)

    @staticmethod
    def _run_in_thread(delegate_tool, child, parent, outcome):
        def _run():
            try:
                outcome["result"] = delegate_tool._run_single_child(
                    0,
                    "single child",
                    child,
                    parent,
                )
            except BaseException as exc:
                outcome["error"] = exc

        thread = threading.Thread(target=_run, name="delegate-single-regression")
        thread.start()
        return thread

    @staticmethod
    def _install_semaphore(delegate_tool, monkeypatch, semaphore, *, timeout=5.0):
        monkeypatch.setattr(delegate_tool, "_get_leaf_semaphore", lambda: semaphore)
        monkeypatch.setattr(delegate_tool, "_leaf_semaphore_size", 1)
        monkeypatch.setattr(delegate_tool, "_LEAF_ACQUIRE_TIMEOUT_SECONDS", timeout)
        monkeypatch.setattr(delegate_tool, "_LEAF_ACQUIRE_POLL_SECONDS", 0.02)
        monkeypatch.setattr(delegate_tool, "_CHILD_RESULT_POLL_SECONDS", 0.02)

    def test_saturated_single_child_stop_returns_before_slot_is_available(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        semaphore = _ObservedSemaphore(1, held_slots=1)
        self._install_semaphore(delegate_tool, monkeypatch, semaphore)
        child = _StubChild(
            run_result={
                "final_response": "must not run",
                "completed": True,
                "api_calls": 1,
                "messages": [],
            }
        )
        parent = self._parent([child])
        self._reserve(delegate_tool, [child])
        outcome = {}
        runner = self._run_in_thread(delegate_tool, child, parent, outcome)
        try:
            assert semaphore.acquire_attempted.wait(timeout=10.0)
            stop_started = time.monotonic()
            parent._interrupt_requested = True
            child.interrupt()
            runner.join(timeout=1.0)
            elapsed = time.monotonic() - stop_started

            assert runner.is_alive() is False
            assert elapsed < 0.75
            assert "error" not in outcome
            assert outcome["result"]["status"] == "interrupted"
            assert child.run_calls == 0
            assert child.closed is True
        finally:
            parent._interrupt_requested = True
            child.interrupt()
            semaphore.release()
            runner.join(timeout=2.0)

    def test_saturated_single_child_quiesces_promptly_for_provider_repair(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        semaphore = _ObservedSemaphore(1, held_slots=1)
        self._install_semaphore(delegate_tool, monkeypatch, semaphore)
        child = _IgnoringInterruptChild()
        parent = self._parent([child])
        self._reserve(delegate_tool, [child])
        outcome = {}
        runner = self._run_in_thread(delegate_tool, child, parent, outcome)
        lease = None
        try:
            assert semaphore.acquire_attempted.wait(timeout=10.0)
            lease = delegate_tool.begin_delegate_provider_repair()
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.75,
            ) is True
            runner.join(timeout=0.75)

            assert runner.is_alive() is False
            assert outcome["result"]["status"] == "interrupted"
            assert child.run_calls == 0
            assert child.closed is True
        finally:
            semaphore.release()
            runner.join(timeout=2.0)
            if lease is not None:
                delegate_tool.release_delegate_provider_repair(lease)

    def test_started_single_child_stop_returns_while_real_worker_stays_tracked(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        semaphore = _ObservedSemaphore(1)
        self._install_semaphore(delegate_tool, monkeypatch, semaphore)
        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 60.0)
        child = _IgnoringInterruptChild()
        parent = self._parent([child])
        self._reserve(delegate_tool, [child])
        outcome = {}
        runner = self._run_in_thread(delegate_tool, child, parent, outcome)
        lease = None
        repair_quiesced = False
        try:
            assert child.worker_started.wait(timeout=10.0)
            stop_started = time.monotonic()
            parent._interrupt_requested = True
            child.interrupt()
            runner.join(timeout=1.0)
            elapsed = time.monotonic() - stop_started

            assert runner.is_alive() is False
            assert elapsed < 0.75
            assert outcome["result"]["status"] == "interrupted"
            assert child.closed is False

            lease = delegate_tool.begin_delegate_provider_repair()
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.05,
            ) is False
        finally:
            child.release_worker.set()
            runner.join(timeout=2.0)
            if lease is not None:
                repair_quiesced = (
                    delegate_tool.wait_for_delegate_provider_quiescence(
                        lease,
                        timeout=2.0,
                    )
                )
                delegate_tool.release_delegate_provider_repair(lease)

        assert repair_quiesced is True
        assert child.closed is True

    def test_started_single_child_repair_is_fail_closed_until_real_exit(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        semaphore = _ObservedSemaphore(1)
        self._install_semaphore(delegate_tool, monkeypatch, semaphore)
        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 60.0)
        child = _IgnoringInterruptChild()
        parent = self._parent([child])
        self._reserve(delegate_tool, [child])
        outcome = {}
        runner = self._run_in_thread(delegate_tool, child, parent, outcome)
        lease = None
        repair_quiesced = False
        try:
            assert child.worker_started.wait(timeout=10.0)
            lease = delegate_tool.begin_delegate_provider_repair()
            runner.join(timeout=1.0)

            assert runner.is_alive() is False
            assert outcome["result"]["status"] == "interrupted"
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.05,
            ) is False
            assert child.closed is False
        finally:
            child.release_worker.set()
            runner.join(timeout=2.0)
            if lease is not None:
                repair_quiesced = (
                    delegate_tool.wait_for_delegate_provider_quiescence(
                        lease,
                        timeout=2.0,
                    )
                )
                delegate_tool.release_delegate_provider_repair(lease)

        assert repair_quiesced is True
        assert child.closed is True

    def test_saturated_leaf_stress_never_exceeds_configured_cap(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        capacity = 2
        semaphore = _ObservedSemaphore(capacity)
        monkeypatch.setattr(delegate_tool, "_get_leaf_semaphore", lambda: semaphore)
        monkeypatch.setattr(delegate_tool, "_leaf_semaphore_size", capacity)
        monkeypatch.setattr(delegate_tool, "_LEAF_ACQUIRE_TIMEOUT_SECONDS", 0.15)
        monkeypatch.setattr(delegate_tool, "_LEAF_ACQUIRE_POLL_SECONDS", 0.01)
        monkeypatch.setattr(delegate_tool, "_CHILD_RESULT_POLL_SECONDS", 0.01)
        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 5.0)

        lock = threading.Lock()
        release_running = threading.Event()
        cap_reached = threading.Event()
        active = 0
        maximum_active = 0

        class _CountingChild(_StubChild):
            def run_conversation(self, user_message, task_id=None, **_kw):
                nonlocal active, maximum_active
                self.run_calls += 1
                with lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                    if active == capacity:
                        cap_reached.set()
                try:
                    release_running.wait(timeout=2.0)
                    return self._run_result
                finally:
                    with lock:
                        active -= 1

        children = [
            _CountingChild(
                run_result={
                    "final_response": "done",
                    "completed": True,
                    "api_calls": 1,
                    "messages": [],
                }
            )
            for _ in range(8)
        ]
        parent = self._parent(children)
        self._reserve(delegate_tool, children)
        outcomes = [None] * len(children)
        threads = [
            threading.Thread(
                target=lambda index=index: outcomes.__setitem__(
                    index,
                    delegate_tool._run_single_child(
                        index,
                        f"stress {index}",
                        children[index],
                        parent,
                    ),
                )
            )
            for index in range(len(children))
        ]
        try:
            for thread in threads:
                thread.start()
            assert cap_reached.wait(timeout=10.0)
            time.sleep(0.25)
        finally:
            release_running.set()
            for thread in threads:
                thread.join(timeout=2.0)

        assert all(thread.is_alive() is False for thread in threads)
        assert maximum_active == capacity
        statuses = [outcome["status"] for outcome in outcomes]
        assert statuses.count("completed") == capacity
        assert statuses.count("timeout") == len(children) - capacity
        assert sum(child.run_calls for child in children) == capacity


# ── batch executor stop/start-failure containment ──────────────────────

class TestBatchExecutorContainment:
    @staticmethod
    def _parent(children):
        return SimpleNamespace(
            _active_children=list(children),
            _active_children_lock=threading.Lock(),
            _current_task_id=None,
            _interrupt_requested=False,
            _memory_manager=None,
            session_id="parent-session",
        )

    @staticmethod
    def _run_batch(delegate_tool, children, parent):
        tasks = [
            {"goal": f"non-cooperative task {index}"}
            for index in range(len(children))
        ]
        return delegate_tool._execute_and_finalize_delegation(
            [(index, tasks[index], child) for index, child in enumerate(children)],
            tasks,
            parent,
            time.monotonic(),
            len(children),
            [task["goal"] for task in tasks],
            len(children),
        )

    def test_parent_stop_returns_before_noncooperative_batch_workers_exit(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        monkeypatch.setattr(delegate_tool, "_get_child_timeout", lambda: 60.0)
        children = [_IgnoringInterruptChild(), _IgnoringInterruptChild()]
        parent = self._parent(children)
        built_children = [
            (index, {"goal": f"task {index}"}, child)
            for index, child in enumerate(children)
        ]
        delegate_tool._reserve_delegate_workers(built_children)

        outcome = {}

        def _run():
            try:
                outcome["result"] = self._run_batch(
                    delegate_tool,
                    children,
                    parent,
                )
            except BaseException as exc:  # surfaced below with its traceback text
                outcome["error"] = exc

        runner = threading.Thread(target=_run, name="delegate-stop-regression")
        lease = None
        repair_quiesced = False
        try:
            runner.start()
            assert all(
                child.worker_started.wait(timeout=10.0) for child in children
            )

            stop_started = time.monotonic()
            parent._interrupt_requested = True
            for child in children:
                child.interrupt()
            runner.join(timeout=1.5)
            stop_elapsed = time.monotonic() - stop_started

            assert runner.is_alive() is False
            assert stop_elapsed < 1.25
            assert "error" not in outcome
            assert [
                entry["status"] for entry in outcome["result"]["results"]
            ] == ["interrupted", "interrupted"]
            assert all(child.closed is False for child in children)

            # Returning an interrupted UI result is not a claim that provider
            # threads died. Repair remains fail-closed until both real workers
            # leave their blocking calls and lifetime cleanup retires them.
            lease = delegate_tool.begin_delegate_provider_repair()
            assert delegate_tool.interrupt_delegate_provider_repair(lease) == 2
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.05,
            ) is False
        finally:
            for child in children:
                child.release_worker.set()
            runner.join(timeout=2.0)
            if lease is not None:
                repair_quiesced = (
                    delegate_tool.wait_for_delegate_provider_quiescence(
                        lease,
                        timeout=2.0,
                    )
                )
                delegate_tool.release_delegate_provider_repair(lease)

        assert repair_quiesced is True
        assert all(child.closed is True for child in children)
        assert all(child not in parent._active_children for child in children)

    def test_mid_batch_submit_failure_retires_only_unstarted_reservations(
        self,
        hermes_home,
        monkeypatch,
    ):
        import tools.delegate_tool as delegate_tool

        real_executor = delegate_tool.ThreadPoolExecutor
        children = [
            _IgnoringInterruptChild(),
            _IgnoringInterruptChild(),
            _IgnoringInterruptChild(),
        ]
        parent = self._parent(children)
        built_children = [
            (index, {"goal": f"task {index}"}, child)
            for index, child in enumerate(children)
        ]
        delegate_tool._reserve_delegate_workers(built_children)

        first_started = threading.Event()
        shutdown_calls = []

        def _blocking_wrapper(*, task_index, goal, child, parent_agent):
            delegate_tool._claim_delegate_worker(child, task_index)
            first_started.set()
            try:
                child.worker_started.set()
                child.release_worker.wait(timeout=5.0)
                return {
                    "task_index": task_index,
                    "status": "completed",
                    "summary": goal,
                    "api_calls": 1,
                    "duration_seconds": 0.0,
                    "_child_role": "leaf",
                }
            finally:
                child.close()
                with parent_agent._active_children_lock:
                    if child in parent_agent._active_children:
                        parent_agent._active_children.remove(child)
                delegate_tool._retire_delegate_worker(child)

        class _FailSecondSubmitExecutor:
            def __init__(self, max_workers):
                self._real = real_executor(max_workers=max_workers)
                self._submits = 0

            def submit(self, fn, *args, **kwargs):
                self._submits += 1
                if self._submits == 2:
                    assert first_started.wait(timeout=2.0)
                    raise RuntimeError("simulated executor thread-start failure")
                return self._real.submit(fn, *args, **kwargs)

            def shutdown(self, *, wait=True, cancel_futures=False):
                shutdown_calls.append((wait, cancel_futures))
                return self._real.shutdown(
                    wait=wait,
                    cancel_futures=cancel_futures,
                )

        monkeypatch.setattr(delegate_tool, "ThreadPoolExecutor", _FailSecondSubmitExecutor)
        monkeypatch.setattr(delegate_tool, "_run_single_child", _blocking_wrapper)

        lease = None
        repair_quiesced = False
        try:
            with pytest.raises(
                RuntimeError,
                match="simulated executor thread-start failure",
            ):
                self._run_batch(delegate_tool, children, parent)

            assert shutdown_calls == [(False, True)]
            assert children[0].closed is False
            assert all(child.closed is True for child in children[1:])
            assert all(child not in parent._active_children for child in children[1:])

            lease = delegate_tool.begin_delegate_provider_repair()
            assert delegate_tool.interrupt_delegate_provider_repair(lease) == 1
            assert delegate_tool.wait_for_delegate_provider_quiescence(
                lease,
                timeout=0.05,
            ) is False
        finally:
            children[0].release_worker.set()
            if lease is not None:
                repair_quiesced = (
                    delegate_tool.wait_for_delegate_provider_quiescence(
                        lease,
                        timeout=2.0,
                    )
                )
                delegate_tool.release_delegate_provider_repair(lease)

        assert repair_quiesced is True
        assert children[0].closed is True
        assert children[0] not in parent._active_children


# ── child-agent counters exist on AIAgent (BUG 3 wiring sanity) ───────

def test_aiagent_defines_rate_limit_counters():
    """The counters delegate_tool reads must exist in AIAgent.__init__
    (grep-level pin so a refactor can't silently drop the telemetry)."""
    import inspect
    import run_agent

    src = inspect.getsource(run_agent.AIAgent.__init__)
    assert "self.session_rate_limit_hits" in src
    assert "self.session_rate_limit_backoff_seconds" in src
