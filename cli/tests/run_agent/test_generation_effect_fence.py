"""Provider-worker regression tests for the per-turn effect fence."""

from __future__ import annotations

import contextvars
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.turn_fence import (
    TurnBusy,
    TurnCancelled,
    TurnFence,
    TurnPermit,
    acquire_owned_current_turn_permit,
    bind_turn_fence,
)
from run_agent import AIAgent


def _response(
    content="done",
    *,
    finish_reason="stop",
    reasoning_content=None,
    usage=None,
):
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning=None,
        reasoning_content=reasoning_content,
        reasoning_details=None,
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        model="test/model",
        usage=SimpleNamespace(**usage) if usage else None,
    )
    return response


def _real_agent(*, session_db=None) -> AIAgent:
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            model="test/model",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            session_db=session_db,
            session_id="fenced-session",
        )
    agent.client = MagicMock()
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._cleanup_task_resources = MagicMock()
    return agent


class _BlockingCompletions:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._started = started
        self._release = release

    def create(self, **_kwargs):
        self._started.set()
        assert self._release.wait(timeout=5), "test did not release provider"
        return SimpleNamespace(choices=[])


def _provider_stub(started: threading.Event, release: threading.Event):
    completions = _BlockingCompletions(started, release)

    class _Stub:
        api_mode = "chat_completions"
        model = "test-model"
        provider = "test-provider"
        _interrupt_requested = False

        def _create_request_openai_client(self, *, reason):
            assert reason == "chat_completion_request"
            return SimpleNamespace(
                chat=SimpleNamespace(completions=completions),
            )

        def _close_request_openai_client(self, _client, *, reason):
            # Simulate an SDK/transport that ignores close and keeps its raw
            # provider thread alive until the remote call returns.
            assert reason in {
                "interrupt_abort",
                "request_complete",
                "stale_call_kill",
                "steer_cut_abort",
            }

        def _compute_non_stream_stale_timeout(self, _messages):
            return 60.0

        def _touch_activity(self, _description):
            return None

        def _emit_status(self, _message):
            return None

        def _consume_steer_cut_request(self):
            return False

    stub = _Stub()
    stub._new_model_worker_thread = AIAgent._new_model_worker_thread.__get__(stub)
    stub._start_model_worker_thread = AIAgent._start_model_worker_thread.__get__(stub)
    stub._spawn_model_worker = AIAgent._spawn_model_worker.__get__(stub)
    stub._interruptible_api_call = AIAgent._interruptible_api_call.__get__(stub)
    return stub


def test_cancel_wins_before_raw_provider_worker_starts() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    target_called = threading.Event()
    result = {"response": None, "error": None}
    stub = _provider_stub(threading.Event(), threading.Event())

    with bind_turn_fence(fence, token):
        worker = stub._new_model_worker_thread(target_called.set, result)

    fence.request_cancel(token, reason="stop before dispatch")
    stub._start_model_worker_thread(worker)
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert not target_called.is_set()
    assert isinstance(result["error"], InterruptedError)
    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.wait_quiesced(timeout=1)


def test_provider_worker_holds_permit_after_polling_frame_interrupts() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    provider_started = threading.Event()
    release_provider = threading.Event()
    polling_frame_exited = threading.Event()
    stub = _provider_stub(provider_started, release_provider)
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                model_permit = acquire_owned_current_turn_permit(
                    "model", {"attempt": "blocked-provider"}
                )
                try:
                    stub._interruptible_api_call(
                        {"messages": []},
                        model_permit=model_permit,
                    )
                except BaseException as exc:  # capture assertion evidence
                    outcome["error"] = exc
                finally:
                    polling_frame_exited.set()
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    turn_context = contextvars.copy_context()
    turn_thread = threading.Thread(target=turn_context.run, args=(_run_turn,))
    turn_thread.start()

    assert provider_started.wait(timeout=2)
    assert fence.snapshot()["permits_by_kind"] == {"model": 1}

    fence.request_cancel(token, reason="user stop")
    stub._interrupt_requested = True
    assert polling_frame_exited.wait(timeout=2)
    turn_thread.join(timeout=2)

    assert isinstance(outcome.get("error"), InterruptedError)
    snapshot = fence.snapshot()
    assert snapshot["state"] == TurnFence.CANCELLING
    assert snapshot["worker_active"] is False
    assert snapshot["in_flight_permits"] == 1
    assert not snapshot["quiesced"]
    with pytest.raises(TurnBusy):
        fence.begin_turn("prompt-2", "actor-1")

    release_provider.set()
    assert fence.wait_quiesced(timeout=2)
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_cancelled_full_turn_returns_while_ignored_close_provider_drains(
    monkeypatch,
) -> None:
    provider_started = threading.Event()
    release_provider = threading.Event()
    turn_returned = threading.Event()
    completions = _BlockingCompletions(
        provider_started,
        release_provider,
    )
    request_client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent._create_request_openai_client = MagicMock(
        return_value=request_client
    )
    # Deliberately ignore both interrupt_abort and request_complete. The raw
    # provider worker must remain the exact owner of its model permit until
    # the blocked call really exits.
    agent._close_request_openai_client = MagicMock()
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
                turn_returned.set()
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            result = outcome.get("result", {})
            status = (
                "interrupted"
                if result.get("interrupted")
                else "completed"
                if result.get("completed")
                else "error"
            )
            fence.finish_worker(token, terminal_status=status)

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert provider_started.wait(timeout=3)
    assert fence.snapshot()["permits_by_kind"] == {"model": 1}

    fence.request_cancel(token, reason="stop ignored-close provider")
    agent._interrupt_requested = True
    assert turn_returned.wait(timeout=3)
    worker.join(timeout=3)

    assert "error" not in outcome
    assert not worker.is_alive()
    result = outcome["result"]
    assert result["completed"] is False
    assert result["interrupted"] is True
    assert result["durability_confirmed"] is False
    assert result["transcript_durable"] is False
    assert result["turn_exit_reason"] == (
        "interrupted_during_post_turn_effects"
    )
    assert result["messages"][-1]["finish_reason"] == "interrupted"

    draining = fence.snapshot()
    assert draining["state"] == TurnFence.CANCELLING
    assert draining["worker_active"] is False
    assert draining["permits_by_kind"] == {"model": 1}
    assert draining["quiesced"] is False
    close_reasons = [
        call.kwargs.get("reason")
        for call in agent._close_request_openai_client.call_args_list
    ]
    assert "interrupt_abort" in close_reasons

    release_provider.set()
    assert fence.wait_quiesced(timeout=3)
    assert fence.snapshot()["state"] == TurnFence.IDLE
    assert fence.snapshot()["in_flight_permits"] == 0


def test_preacquired_model_permit_wins_stop_before_raw_dispatch() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    target_called = threading.Event()
    result = {"response": None, "error": None}
    stub = _provider_stub(threading.Event(), threading.Event())

    with bind_turn_fence(fence, token):
        permit = acquire_owned_current_turn_permit("model")
        worker = stub._new_model_worker_thread(
            target_called.set,
            result,
            model_permit=permit,
        )
        fence.request_cancel(token, reason="stop after acquire")
        stub._start_model_worker_thread(worker, model_permit=permit)
        worker.join(timeout=2)

    assert target_called.is_set()
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.wait_quiesced(timeout=1)


def test_model_worker_prestart_failure_releases_preacquired_permit() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    target_called = threading.Event()
    result = {"response": None, "error": None}
    stub = _provider_stub(threading.Event(), threading.Event())

    with bind_turn_fence(fence, token):
        permit = acquire_owned_current_turn_permit("model")
        worker = stub._new_model_worker_thread(
            target_called.set,
            result,
            model_permit=permit,
        )

        def _raise_before_start():
            raise KeyboardInterrupt("pre-start")

        worker.start = _raise_before_start
        with pytest.raises(KeyboardInterrupt, match="pre-start"):
            stub._start_model_worker_thread(worker, model_permit=permit)

    assert not target_called.is_set()
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="error")
    assert fence.wait_quiesced(timeout=1)


def test_revoked_start_then_raise_worker_never_calls_provider_target() -> None:
    import run_agent

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    target_called = threading.Event()
    result = {"response": None, "error": None}
    attempt = run_agent._ProviderAttempt()
    stub = _provider_stub(threading.Event(), threading.Event())

    def _target() -> None:
        target_called.set()
        result["response"] = "stale-result"

    with pytest.raises(KeyboardInterrupt, match="after-start"):
        with bind_turn_fence(fence, token):
            permit = acquire_owned_current_turn_permit("model")
            worker = stub._new_model_worker_thread(
                _target,
                result,
                model_permit=permit,
                provider_attempt=attempt,
            )
            original_start = worker.start

            def _start_then_raise():
                original_start()
                raise KeyboardInterrupt("after-start")

            worker.start = _start_then_raise
            stub._start_model_worker_thread(
                worker,
                model_permit=permit,
                provider_attempt=attempt,
            )

    worker.join(timeout=2)
    assert not worker.is_alive()
    assert not target_called.is_set()
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="error")
    assert result["response"] is None
    assert isinstance(result["error"], run_agent._ProviderAttemptRevoked)
    assert fence.wait_quiesced(timeout=1)


def test_duplicate_model_permit_transfer_cannot_release_first_worker() -> None:
    import run_agent

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    first_started = threading.Event()
    release_first = threading.Event()
    stub = _provider_stub(threading.Event(), threading.Event())
    first_result = {"response": None, "error": None}
    second_result = {"response": None, "error": None}
    second_attempt = run_agent._ProviderAttempt()

    def _first_target() -> None:
        first_started.set()
        assert release_first.wait(timeout=5)

    with bind_turn_fence(fence, token):
        permit = acquire_owned_current_turn_permit("model")
        first_worker = stub._new_model_worker_thread(
            _first_target,
            first_result,
            model_permit=permit,
        )
        stub._start_model_worker_thread(
            first_worker, model_permit=permit
        )
        assert first_started.wait(timeout=2)

        duplicate_worker = stub._new_model_worker_thread(
            lambda: second_result.update(response="must-not-run"),
            second_result,
            model_permit=permit,
            provider_attempt=second_attempt,
        )
        with pytest.raises(TurnCancelled, match="already claimed"):
            stub._start_model_worker_thread(
                duplicate_worker,
                model_permit=permit,
                provider_attempt=second_attempt,
            )

        assert second_attempt.is_revoked() is False
        assert second_result["response"] is None
        assert fence.snapshot()["permits_by_kind"] == {"model": 1}

    fence.request_cancel(token, reason="stop while first worker is live")
    fence.finish_worker(token, terminal_status="interrupted")
    assert not fence.wait_quiesced(timeout=0.05)
    assert fence.snapshot()["in_flight_permits"] == 1

    release_first.set()
    first_worker.join(timeout=2)
    assert not first_worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_raw_provider_baseexception_is_returned_to_poller_and_releases() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    stub = _provider_stub(threading.Event(), threading.Event())

    def _explode(**_kwargs):
        raise KeyboardInterrupt("provider baseexception")

    client = stub._create_request_openai_client(
        reason="chat_completion_request"
    )
    client.chat.completions.create = _explode
    stub._create_request_openai_client = lambda **_kwargs: client

    with bind_turn_fence(fence, token):
        permit = acquire_owned_current_turn_permit("model")
        with pytest.raises(KeyboardInterrupt, match="provider baseexception"):
            stub._interruptible_api_call(
                {"messages": []}, model_permit=permit
            )
    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="error")
    assert fence.wait_quiesced(timeout=1)


def test_close_ignored_stale_timeout_retains_raw_worker_permit() -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    provider_started = threading.Event()
    release_provider = threading.Event()
    stub = _provider_stub(provider_started, release_provider)
    stub._compute_non_stream_stale_timeout = lambda _messages: 0.0

    with bind_turn_fence(fence, token):
        permit = acquire_owned_current_turn_permit("model")
        with pytest.raises(TimeoutError):
            stub._interruptible_api_call(
                {"messages": []}, model_permit=permit
            )
        assert provider_started.is_set()
        assert fence.snapshot()["in_flight_permits"] == 1

    fence.finish_worker(token, terminal_status="error")
    assert not fence.wait_quiesced(timeout=0.05)
    release_provider.set()
    assert fence.wait_quiesced(timeout=2)


def test_close_ignored_steer_retry_isolates_late_old_result() -> None:
    from run_agent import SteerCutInterrupt

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    first_started = threading.Event()
    release_first = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    class _TwoAttempts:
        def create(self, **_kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
                call_number = calls
            if call_number == 1:
                first_started.set()
                assert release_first.wait(timeout=5)
                return "late-old-response"
            return "fresh-retry-response"

    stub = _provider_stub(threading.Event(), threading.Event())
    completions = _TwoAttempts()
    stub._create_request_openai_client = lambda **_kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    cut_once = True

    def _consume_cut():
        nonlocal cut_once
        if cut_once and first_started.is_set():
            cut_once = False
            return True
        return False

    stub._consume_steer_cut_request = _consume_cut

    with bind_turn_fence(fence, token):
        first_permit = acquire_owned_current_turn_permit("model")
        with pytest.raises(SteerCutInterrupt):
            stub._interruptible_api_call(
                {"messages": []}, model_permit=first_permit
            )
        assert fence.snapshot()["in_flight_permits"] == 1

        retry_permit = acquire_owned_current_turn_permit("model")
        response = stub._interruptible_api_call(
            {"messages": []}, model_permit=retry_permit
        )
        assert response == "fresh-retry-response"
        assert calls == 2
        assert fence.snapshot()["in_flight_permits"] == 1
        release_first.set()
        deadline = time.time() + 2
        while fence.snapshot()["in_flight_permits"] and time.time() < deadline:
            time.sleep(0.01)

    assert fence.snapshot()["in_flight_permits"] == 0
    fence.finish_worker(token, terminal_status="complete")
    assert fence.wait_quiesced(timeout=1)


class _ToolCall:
    def __init__(
        self,
        arguments: str = "{}",
        *,
        tool_id: str = "tool-1",
        name: str = "fake_tool",
    ) -> None:
        self.id = tool_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=arguments)


def _tool_response(tool_calls, *, content=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=list(tool_calls),
        reasoning=None,
        reasoning_content=None,
        reasoning_details=None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        model="test/model",
        usage=None,
    )


def _concurrent_tool_stub(handler):
    class _Stub:
        _interrupt_requested = False
        log_prefix = ""
        quiet_mode = True
        verbose_logging = False
        log_prefix_chars = 200
        _checkpoint_mgr = MagicMock(enabled=False)
        _subdirectory_hints = MagicMock()
        tool_progress_callback = None
        tool_start_callback = None
        tool_complete_callback = None
        context_compressor = MagicMock(context_length=0)
        valid_tool_names = set()
        _turns_since_memory = 0
        _iters_since_skill = 0
        _current_tool = None
        _last_tool_batch_outcomes = []
        _active_action_user_message = None
        _print_fn = print

        def __init__(self) -> None:
            self._tool_worker_threads = set()
            self._tool_worker_threads_lock = threading.Lock()

        def _touch_activity(self, _description):
            return None

        def _vprint(self, _message, force=False):
            return None

        def _safe_print(self, _message):
            return None

        def _should_emit_quiet_tool_messages(self):
            return False

        def _should_start_quiet_spinner(self):
            return False

        def _apply_pending_steer_to_tool_results(self, *_args):
            return None

        def _invoke_tool(self, *args, **kwargs):
            return handler(*args, **kwargs)

    stub = _Stub()
    stub._subdirectory_hints.check_tool_call.return_value = ""
    stub._execute_tool_calls_concurrent = (
        AIAgent._execute_tool_calls_concurrent.__get__(stub)
    )
    stub._execute_tool_calls_concurrent_impl = (
        AIAgent._execute_tool_calls_concurrent_impl.__get__(stub)
    )
    return stub


def test_tool_permit_spans_handler_return_through_result_persistence(
    monkeypatch,
) -> None:
    """Stop after handler return cannot quiesce during result persistence."""
    import run_agent

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    handler_returned = threading.Event()
    persistence_entered = threading.Event()
    release_persistence = threading.Event()
    persistence_finished = threading.Event()
    messages: list[dict] = []

    def _handler(*_args, **_kwargs):
        handler_returned.set()
        return "tool output"

    def _blocking_persist(*, content, **_kwargs):
        persistence_entered.set()
        assert release_persistence.wait(timeout=5), "test did not release persistence"
        persistence_finished.set()
        return content

    monkeypatch.setattr(run_agent, "maybe_persist_tool_result", _blocking_persist)
    stub = _concurrent_tool_stub(_handler)
    assistant_message = SimpleNamespace(tool_calls=[_ToolCall()])

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                stub._execute_tool_calls_concurrent(
                    assistant_message,
                    messages,
                    "task-1",
                )
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    turn_thread = threading.Thread(target=_run_turn)
    turn_thread.start()

    assert handler_returned.wait(timeout=2)
    assert persistence_entered.wait(timeout=2)
    fence.request_cancel(token, reason="stop after handler")

    snapshot = fence.snapshot()
    assert snapshot["state"] == TurnFence.CANCELLING
    assert snapshot["permits_by_kind"] == {
        "tool": 1,
        "tool_batch_transaction": 1,
    }
    assert not snapshot["quiesced"]
    with pytest.raises(TurnBusy):
        fence.begin_turn("prompt-2", "actor-1")

    release_persistence.set()
    turn_thread.join(timeout=2)
    assert not turn_thread.is_alive()
    assert persistence_finished.is_set()
    assert messages == [
        {
            "role": "tool",
            "content": "tool output",
            "tool_call_id": "tool-1",
            "tool_name": "fake_tool",
        }
    ]
    assert fence.wait_quiesced(timeout=2)
    assert fence.snapshot()["state"] == TurnFence.IDLE


@pytest.mark.parametrize("mode", ["concurrent", "sequential"])
@pytest.mark.parametrize("path", ["invalid_arguments", "preflight_interrupt"])
def test_cancelled_parse_and_skipped_paths_do_not_mutate_history(
    mode: str,
    path: str,
) -> None:
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    fence.request_cancel(token, reason="stop before tool result")
    existing = {"role": "user", "content": "existing history"}
    messages = [existing.copy()]
    tool_call = _ToolCall("{" if path == "invalid_arguments" else "{}")
    assistant_message = SimpleNamespace(tool_calls=[tool_call])
    stub = SimpleNamespace(
        _interrupt_requested=path == "preflight_interrupt",
        log_prefix="",
        _vprint=lambda *_args, **_kwargs: None,
    )

    with bind_turn_fence(fence, token):
        if mode == "concurrent":
            AIAgent._execute_tool_calls_concurrent(
                stub,
                assistant_message,
                messages,
                "task-1",
            )
        else:
            AIAgent._execute_tool_calls_sequential(
                stub,
                assistant_message,
                messages,
                "task-1",
            )

    assert messages == [existing]
    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.wait_quiesced(timeout=1)


@pytest.mark.parametrize("mode", ["concurrent", "sequential"])
def test_cancel_winner_blocks_arbitrary_plugin_pre_tool_hook(
    monkeypatch,
    mode: str,
) -> None:
    from elevate_cli import plugins

    plugin_calls: list[str] = []

    def _plugin_hook(tool_name, *_args, **_kwargs):
        plugin_calls.append(tool_name)
        return None

    monkeypatch.setattr(plugins, "get_pre_tool_call_block_message", _plugin_hook)
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    fence.request_cancel(token, reason="stop before plugin policy")
    assistant_message = SimpleNamespace(tool_calls=[_ToolCall()])
    messages: list[dict] = []

    if mode == "concurrent":
        stub = _concurrent_tool_stub(
            lambda name, args, task_id, **_kwargs: _plugin_hook(
                name, args, task_id=task_id
            )
        )
    else:
        stub = SimpleNamespace(
            _interrupt_requested=False,
            log_prefix="",
            _vprint=lambda *_args, **_kwargs: None,
        )

    with bind_turn_fence(fence, token):
        if mode == "concurrent":
            AIAgent._execute_tool_calls_concurrent(
                stub, assistant_message, messages, "task-1"
            )
        else:
            AIAgent._execute_tool_calls_sequential(
                stub, assistant_message, messages, "task-1"
            )

    assert plugin_calls == []
    assert messages == []
    fence.finish_worker(token, terminal_status="interrupted")
    assert fence.wait_quiesced(timeout=1)


def test_model_result_permit_is_released_on_unexpected_baseexception(
    monkeypatch,
) -> None:
    """Binding cleanup cannot leak a real post-provider result permit."""
    agent = _real_agent()
    agent.client.chat.completions.create.return_value = _response("done")
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    acquired = threading.Event()
    outcome: dict[str, BaseException] = {}
    callback_count = 0

    def _thinking_callback(_message):
        nonlocal callback_count
        callback_count += 1
        if callback_count == 2:
            assert fence.snapshot()["permits_by_kind"].get("model_result") == 1
            acquired.set()
            raise KeyboardInterrupt("injected after model-result acquire")

    agent.thinking_callback = _thinking_callback
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                agent.run_conversation("hello")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            fence.finish_worker(token, terminal_status="error")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert acquired.wait(timeout=2)
    worker.join(timeout=2)

    assert isinstance(outcome.get("error"), KeyboardInterrupt)
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)
    assert fence.snapshot()["in_flight_permits"] == 0


def test_cancel_after_raw_provider_exit_blocks_result_projection(
    monkeypatch,
) -> None:
    """Stop at the raw-provider/result seam wins before every late effect."""
    import agent.turn_fence as turn_fence

    session_db = MagicMock()
    agent = _real_agent(session_db=session_db)
    agent.client.chat.completions.create.return_value = _response(
        "late response",
        usage={
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    )
    agent._persist_session = MagicMock()
    thinking_calls: list[str] = []
    agent.thinking_callback = thinking_calls.append

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    result_boundary = threading.Event()
    release_boundary = threading.Event()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == "model_result":
            result_boundary.set()
            assert release_boundary.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            status = (
                "interrupted"
                if outcome.get("result", {}).get("interrupted")
                else "error"
            )
            fence.finish_worker(token, terminal_status=status)

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert result_boundary.wait(timeout=2)
    thinking_count_at_boundary = len(thinking_calls)

    fence.request_cancel(token, reason="stop after provider")
    agent._interrupt_requested = True
    release_boundary.set()
    worker.join(timeout=5)

    assert "error" not in outcome
    result = outcome["result"]
    assert result["completed"] is False
    assert result["interrupted"] is True
    session_db.update_token_counts.assert_not_called()
    assert len(thinking_calls) == thinking_count_at_boundary
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_model_result_ownership_is_bounded_across_multi_call_turn(
    monkeypatch,
) -> None:
    """A prior result is released at the next dispatch, never accumulated."""
    import agent.turn_fence as turn_fence

    agent = _real_agent()
    agent.client.chat.completions.create.side_effect = [
        _response(content=None, reasoning_content="private reasoning"),
        _response(content="final answer"),
    ]
    agent._persist_session = MagicMock()
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    result_counts: list[int] = []
    original_acquire = turn_fence.acquire_current_turn_permit

    def _observed_acquire(kind, metadata=None):
        permit = original_acquire(kind, metadata)
        if kind == "model_result":
            result_counts.append(
                fence.snapshot()["permits_by_kind"].get("model_result", 0)
            )
        return permit

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _observed_acquire
    )
    try:
        with bind_turn_fence(fence, token):
            result = agent.run_conversation("hello")
    finally:
        fence.finish_worker(token, terminal_status="completed")

    assert result["completed"] is True
    assert result["final_response"] == "final answer"
    assert result_counts == [1, 1]
    assert fence.wait_quiesced(timeout=1)
    assert fence.snapshot()["in_flight_permits"] == 0


@pytest.mark.parametrize(
    ("entrypoint", "impl_name", "permit_kind", "needs_db"),
    [
        (
            "_flush_messages_to_session_db",
            "_flush_messages_to_session_db_impl",
            "session_db_flush",
            True,
        ),
        (
            "_save_session_log",
            "_save_session_log_impl",
            "session_log_write",
            False,
        ),
    ],
)
def test_cancel_at_persistence_acquire_boundary_blocks_all_preparation_and_writes(
    monkeypatch,
    entrypoint: str,
    impl_name: str,
    permit_kind: str,
    needs_db: bool,
) -> None:
    """Cancel after the legacy boolean-check seam cannot enter the impl."""
    import agent.turn_fence as turn_fence

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    at_boundary = threading.Event()
    release_boundary = threading.Event()
    mutation = MagicMock()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == permit_kind:
            at_boundary.set()
            assert release_boundary.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )
    monkeypatch.setattr(AIAgent, impl_name, mutation)
    stub = SimpleNamespace(_session_db=object() if needs_db else None)

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                method = getattr(AIAgent, entrypoint)
                if needs_db:
                    method(stub, [{"role": "user", "content": "hello"}], None)
                else:
                    method(stub, [{"role": "user", "content": "hello"}])
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert at_boundary.wait(timeout=2)
    fence.request_cancel(token, reason="stop at persistence seam")
    release_boundary.set()
    worker.join(timeout=2)

    mutation.assert_not_called()
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_precancelled_turn_skips_startup_hooks_system_write_and_end_hook(
    monkeypatch,
) -> None:
    session_db = MagicMock()
    agent = _real_agent(session_db=session_db)
    agent._cached_system_prompt = None
    agent._build_system_prompt = MagicMock(return_value="fresh system")
    agent._interrupt_requested = True
    hook_names: list[str] = []

    def _record_hook(name, **_kwargs):
        hook_names.append(name)
        return []

    monkeypatch.setattr("elevate_cli.plugins.invoke_hook", _record_hook)
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.request_cancel(token, reason="stop before worker starts")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    worker.join(timeout=5)

    assert "error" not in outcome
    assert outcome["result"]["completed"] is False
    assert outcome["result"]["interrupted"] is True
    assert "on_session_start" not in hook_names
    assert "pre_llm_call" not in hook_names
    assert "on_session_end" not in hook_names
    session_db.update_system_prompt.assert_not_called()
    agent.client.chat.completions.create.assert_not_called()
    assert fence.wait_quiesced(timeout=1)


def test_timed_out_memory_prefetch_keeps_generation_owned_until_real_exit() -> None:
    prefetch_started = threading.Event()
    release_prefetch = threading.Event()

    def _prefetch(_query):
        prefetch_started.set()
        assert release_prefetch.wait(timeout=5)
        return "stale memory"

    stub = SimpleNamespace(
        session_id="memory-session",
        _memory_manager=SimpleNamespace(prefetch_all=_prefetch),
    )
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["value"] = AIAgent._prefetch_memory_with_budget(
                    stub, stub._memory_manager.prefetch_all, "query", 0.05
                )
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert prefetch_started.wait(timeout=2)
    fence.request_cancel(token, reason="stop during prefetch")
    worker.join(timeout=2)

    assert outcome["value"] == ""
    assert not worker.is_alive()
    snapshot = fence.snapshot()
    assert snapshot["state"] == TurnFence.CANCELLING
    assert snapshot["worker_active"] is False
    assert snapshot["permits_by_kind"] == {"memory_prefetch": 1}
    assert snapshot["quiesced"] is False
    with pytest.raises(TurnBusy):
        fence.begin_turn("prompt-2", "actor-1")

    release_prefetch.set()
    assert fence.wait_quiesced(timeout=2)
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_normal_completion_returns_while_timed_out_memory_prefetch_drains(
    monkeypatch,
) -> None:
    prefetch_started = threading.Event()
    release_prefetch = threading.Event()

    def _prefetch(_query):
        prefetch_started.set()
        assert release_prefetch.wait(timeout=5)
        return "too-late memory"

    memory_manager = MagicMock()
    memory_manager.prefetch_all.side_effect = _prefetch
    agent = _real_agent()
    agent._memory_manager = memory_manager
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    monkeypatch.setenv("ELEVATE_MEMORY_PREFETCH_BUDGET_S", "0.01")
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            result = outcome.get("result", {})
            status = "completed" if result.get("completed") else "error"
            fence.finish_worker(token, terminal_status=status)

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert prefetch_started.wait(timeout=2)
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert "error" not in outcome
    result = outcome["result"]
    assert result["completed"] is True
    assert result["interrupted"] is False
    assert result["durability_confirmed"] is True
    snapshot = fence.snapshot()
    assert snapshot["terminal_committed"] is True
    assert snapshot["permits_by_kind"] == {"memory_prefetch": 1}
    assert snapshot["state"] == TurnFence.CANCELLING
    assert fence.wait_generation_quiesced(token, timeout=0.01) is False

    release_prefetch.set()
    assert fence.wait_generation_quiesced(token, timeout=2) is True
    assert fence.snapshot()["state"] == TurnFence.IDLE


def test_bound_gateway_turn_suppresses_detached_background_review(
    monkeypatch,
) -> None:
    thread_factory = MagicMock()
    monkeypatch.setattr(threading, "Thread", thread_factory)
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)

    with bind_turn_fence(fence, token):
        AIAgent._spawn_background_review(
            SimpleNamespace(),
            messages_snapshot=[],
            review_memory=True,
        )

    thread_factory.assert_not_called()
    fence.finish_worker(token, terminal_status="completed")
    assert fence.wait_quiesced(timeout=1)


def test_cancelled_shared_compression_stays_owned_through_method_exit(
    monkeypatch,
) -> None:
    from agent import conversation_compression

    summarizer_started = threading.Event()
    release_summarizer = threading.Event()

    def _summarize(*_args, **_kwargs):
        summarizer_started.set()
        assert release_summarizer.wait(timeout=5)
        return "compressed summary", 2

    compressor = SimpleNamespace(
        summarize_to_cursor=_summarize,
        context_length=1000,
        compression_count=1,
        _last_compress_aborted=False,
        _last_summary_error=None,
        _last_aux_model_failure_model=None,
        _last_aux_model_failure_error=None,
        _consecutive_low_yield_compactions=0,
    )
    memory_manager = SimpleNamespace(on_pre_compress=MagicMock())
    session_db = SimpleNamespace(update_compaction=MagicMock())
    stub = SimpleNamespace(
        _compression_feasibility_checked=True,
        session_id="compression-session",
        model="test/model",
        _emit_status=MagicMock(),
        _emit_warning=MagicMock(),
        _touch_activity=MagicMock(),
        _memory_manager=memory_manager,
        context_compressor=compressor,
        compaction_cursor=0,
        compaction_summary=None,
        commit_memory_session=MagicMock(),
        _session_db=session_db,
        _cached_system_prompt="stable system",
        _build_system_prompt=MagicMock(return_value="stable system"),
        _usage_projector=None,
        _vprint=MagicMock(),
        log_prefix="",
    )
    recorder = MagicMock()
    dedup_reset = MagicMock()
    monkeypatch.setattr(
        conversation_compression, "_record_compaction_event", recorder
    )
    monkeypatch.setattr("tools.file_tools.reset_file_dedup", dedup_reset)

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}
    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
    ]

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = AIAgent._compress_context(
                    stub,
                    messages,
                    "stable system",
                    approx_tokens=900,
                    task_id="task-1",
                )
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert summarizer_started.wait(timeout=2)
    fence.request_cancel(token, reason="stop during summary")

    snapshot = fence.snapshot()
    assert snapshot["state"] == TurnFence.CANCELLING
    assert snapshot["permits_by_kind"].get("compression") == 1
    assert snapshot["quiesced"] is False
    with pytest.raises(TurnBusy):
        fence.begin_turn("prompt-2", "actor-1")

    release_summarizer.set()
    worker.join(timeout=5)

    assert "error" not in outcome
    assert outcome["result"] == (messages, "stable system")
    memory_manager.on_pre_compress.assert_called_once_with(messages)
    stub.commit_memory_session.assert_called_once_with(messages)
    session_db.update_compaction.assert_called_once_with(
        "compression-session", "compressed summary", 2
    )
    dedup_reset.assert_called_once_with("task-1")
    assert recorder.call_count >= 2
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_cancel_before_iteration_summary_leaves_transcript_untouched() -> None:
    agent = _real_agent()
    messages = [{"role": "user", "content": "original"}]
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    fence.request_cancel(token, reason="stop before summary")

    try:
        with bind_turn_fence(fence, token):
            result = agent._handle_max_iterations(messages, 10)
    finally:
        fence.finish_worker(token, terminal_status="interrupted")

    assert result == ""
    assert messages == [{"role": "user", "content": "original"}]
    agent.client.chat.completions.create.assert_not_called()
    assert fence.wait_quiesced(timeout=1)


def test_cancel_between_empty_summary_and_retry_blocks_second_provider_call(
    monkeypatch,
) -> None:
    import agent.turn_fence as turn_fence

    agent = _real_agent()
    agent.client.chat.completions.create.return_value = _response(content="")
    messages = [{"role": "user", "content": "original"}]
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    retry_boundary = threading.Event()
    release_retry = threading.Event()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == "summary_model" and metadata.get("attempt") == 2:
            retry_boundary.set()
            assert release_retry.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent._handle_max_iterations(messages, 10)
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert retry_boundary.wait(timeout=2)
    assert agent.client.chat.completions.create.call_count == 1

    fence.request_cancel(token, reason="stop before summary retry")
    release_retry.set()
    worker.join(timeout=3)

    assert outcome["result"] == ""
    assert agent.client.chat.completions.create.call_count == 1
    assert messages == [{"role": "user", "content": "original"}]
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_late_cancel_suppresses_post_turn_effects_and_refreshes_result_truth(
    monkeypatch,
) -> None:
    import agent.turn_fence as turn_fence
    from agent import turn_attribution

    agent = _real_agent()
    agent.client.chat.completions.create.return_value = _response("done")
    memory_manager = MagicMock()
    memory_manager.prefetch_all.return_value = ""
    agent._memory_manager = memory_manager
    hook_names: list[str] = []

    def _record_hook(name, **_kwargs):
        hook_names.append(name)
        return []

    monkeypatch.setattr("elevate_cli.plugins.invoke_hook", _record_hook)
    attribution = MagicMock()
    monkeypatch.setattr(turn_attribution, "attribute_turn_safely", attribution)
    cleanup_boundary = threading.Event()
    release_cleanup = threading.Event()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == "task_cleanup":
            cleanup_boundary.set()
            assert release_cleanup.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert cleanup_boundary.wait(timeout=3)
    assert "post_llm_call" not in hook_names

    fence.request_cancel(token, reason="stop after terminal checkpoint")
    release_cleanup.set()
    worker.join(timeout=5)

    result = outcome["result"]
    assert result["completed"] is False
    assert result["interrupted"] is True
    assert result["turn_exit_reason"] == "interrupted_during_post_turn_effects"
    assert result["messages"][-1]["finish_reason"] == "interrupted"
    agent._cleanup_task_resources.assert_not_called()
    attribution.assert_not_called()
    memory_manager.sync_all.assert_not_called()
    memory_manager.queue_prefetch_all.assert_not_called()
    assert "post_llm_call" not in hook_names
    assert "on_session_end" not in hook_names
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_bound_turn_routes_attribution_without_detached_workers(
    monkeypatch,
) -> None:
    from agent import turn_attribution

    agent = _real_agent()
    agent.client.chat.completions.create.return_value = _response("done")
    agent._persist_session = MagicMock()
    attribution = MagicMock()
    monkeypatch.setattr(turn_attribution, "attribute_turn_safely", attribution)
    monkeypatch.setattr(turn_attribution, "should_wait_for_inference", lambda: False)
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    try:
        with bind_turn_fence(fence, token):
            result = agent.run_conversation("hello")
    finally:
        fence.finish_worker(token, terminal_status="completed")

    assert result["completed"] is True
    attribution.assert_called_once()
    assert attribution.call_args.kwargs["allow_background"] is False
    assert fence.wait_quiesced(timeout=1)


def test_attribution_background_policy_suppresses_both_detached_threads_but_default_remains(
    monkeypatch,
) -> None:
    from agent import turn_attribution
    from elevate_cli import access, data

    monkeypatch.setattr(access, "is_entitlement_active", lambda *_args: True)
    connection = MagicMock()
    connection_cm = MagicMock()
    connection_cm.__enter__.return_value = connection
    connection_cm.__exit__.return_value = False
    monkeypatch.setattr(data, "connect", lambda: connection_cm)
    monkeypatch.setattr(
        turn_attribution, "record_turn_activity", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        turn_attribution, "_scorecard_inference_enabled", lambda: True
    )
    monkeypatch.setattr(turn_attribution, "_resolver_enabled", lambda: True)

    thread_one = MagicMock()
    thread_two = MagicMock()
    thread_factory = MagicMock(side_effect=[thread_one, thread_two])
    monkeypatch.setattr(threading, "Thread", thread_factory)
    messages = [
        {"role": "user", "content": "Work the Smith deal"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "tool-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"contract.pdf"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tool-1", "content": "read"},
    ]

    turn_attribution.attribute_turn_safely(
        messages,
        agent_id="agent-1",
        session_id="session-1",
        allow_background=False,
    )
    thread_factory.assert_not_called()

    turn_attribution.attribute_turn_safely(
        messages,
        agent_id="agent-1",
        session_id="session-1",
    )
    assert thread_factory.call_count == 2
    thread_one.start.assert_called_once_with()
    thread_two.start.assert_called_once_with()


def test_cancel_at_callback_acquire_boundary_suppresses_thinking_publish(
    monkeypatch,
) -> None:
    import agent.turn_fence as turn_fence

    callback = MagicMock()
    stub = SimpleNamespace(thinking_callback=callback)
    stub._invoke_generation_callback = (
        AIAgent._invoke_generation_callback.__get__(stub)
    )
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    at_boundary = threading.Event()
    release_boundary = threading.Event()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == "thinking_callback":
            at_boundary.set()
            assert release_boundary.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                AIAgent._emit_thinking(stub, "working")
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert at_boundary.wait(timeout=2)
    fence.request_cancel(token, reason="stop before callback")
    release_boundary.set()
    worker.join(timeout=2)

    callback.assert_not_called()
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def _durable_test_agent(tmp_path, tool_calls):
    session_db = MagicMock()
    session_db.get_messages.return_value = []
    agent = _real_agent(session_db=session_db)
    agent.session_log_file = tmp_path / "session_fenced-session.json"
    agent.logs_dir = tmp_path
    agent.client.chat.completions.create.return_value = _tool_response(tool_calls)
    agent.valid_tool_names = {tc.function.name for tc in tool_calls}
    agent.tool_delay = 0
    return agent, session_db


def _persisted_roles(session_db):
    return [call.kwargs["role"] for call in session_db.append_message.call_args_list]


def _logged_messages(agent):
    payload = json.loads(agent.session_log_file.read_text(encoding="utf-8"))
    return payload["messages"]


def test_concurrent_mixed_winner_drains_ordered_results_and_durability(
    monkeypatch,
    tmp_path,
) -> None:
    import agent.turn_fence as turn_fence
    import run_agent

    calls = [
        _ToolCall(tool_id="tool-1"),
        _ToolCall(tool_id="tool-2"),
    ]
    agent, session_db = _durable_test_agent(tmp_path, calls)
    effects: list[str] = []

    def _invoke(_name, _args, _task, tool_call_id, **_kwargs):
        effects.append(tool_call_id)
        return f"committed:{tool_call_id}"

    agent._invoke_tool = _invoke
    monkeypatch.setattr(run_agent, "_should_parallelize_tool_batch", lambda _calls: True)
    monkeypatch.setattr("elevate_cli.plugins.invoke_hook", lambda *_a, **_k: [])

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    second_admission = threading.Event()
    release_admission = threading.Event()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == "tool" and (metadata or {}).get("tool_call_id") == "tool-2":
            second_admission.set()
            assert release_admission.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("do both")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert second_admission.wait(timeout=3)
    fence.request_cancel(token, reason="stop after first concurrent admission")
    agent._interrupt_requested = True
    release_admission.set()
    worker.join(timeout=8)

    assert "error" not in outcome
    result = outcome["result"]
    assert result["completed"] is False
    assert result["interrupted"] is True
    assert effects == ["tool-1"]
    tool_messages = [m for m in result["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["tool-1", "tool-2"]
    assert "committed:tool-1" in str(tool_messages[0]["content"])
    assert "not started" in str(tool_messages[1]["content"])
    assert len(agent._last_tool_batch_outcomes) == 2
    assert _persisted_roles(session_db) == ["user", "assistant", "tool", "tool"]
    logged = _logged_messages(agent)
    assert [m["role"] for m in logged] == ["user", "assistant", "tool", "tool"]
    assert [m.get("tool_call_id") for m in logged[-2:]] == ["tool-1", "tool-2"]
    assert agent._current_tool is None
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_sequential_first_winner_stop_before_second_is_durable_and_ordered(
    monkeypatch,
    tmp_path,
) -> None:
    import agent.turn_fence as turn_fence
    import run_agent

    calls = [
        _ToolCall(tool_id="tool-1"),
        _ToolCall(tool_id="tool-2"),
    ]
    agent, session_db = _durable_test_agent(tmp_path, calls)
    effects: list[str] = []

    def _invoke(_name, _args, _task, tool_call_id, **_kwargs):
        effects.append(tool_call_id)
        return f"committed:{tool_call_id}"

    monkeypatch.setattr(run_agent, "handle_function_call", _invoke)
    monkeypatch.setattr(run_agent, "_should_parallelize_tool_batch", lambda _calls: False)
    monkeypatch.setattr("elevate_cli.plugins.invoke_hook", lambda *_a, **_k: [])
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    second_admission = threading.Event()
    release_admission = threading.Event()
    original_acquire = turn_fence.acquire_current_turn_permit

    def _controlled_acquire(kind, metadata=None):
        if kind == "tool" and (metadata or {}).get("tool_call_id") == "tool-2":
            second_admission.set()
            assert release_admission.wait(timeout=5)
        return original_acquire(kind, metadata)

    monkeypatch.setattr(
        turn_fence, "acquire_current_turn_permit", _controlled_acquire
    )
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("do both in order")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert second_admission.wait(timeout=3)
    fence.request_cancel(token, reason="stop before second sequential effect")
    agent._interrupt_requested = True
    release_admission.set()
    worker.join(timeout=8)

    assert "error" not in outcome
    result = outcome["result"]
    assert result["interrupted"] is True
    assert effects == ["tool-1"]
    tool_messages = [m for m in result["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["tool-1", "tool-2"]
    assert len(agent._last_tool_batch_outcomes) == 2
    assert _persisted_roles(session_db) == ["user", "assistant", "tool", "tool"]
    assert [m["role"] for m in _logged_messages(agent)] == [
        "user",
        "assistant",
        "tool",
        "tool",
    ]
    assert agent._current_tool is None
    assert fence.wait_quiesced(timeout=1)


def test_single_effect_stop_before_batch_evidence_still_persists_once(
    monkeypatch,
    tmp_path,
) -> None:
    import run_agent

    calls = [_ToolCall(tool_id="tool-1")]
    agent, session_db = _durable_test_agent(tmp_path, calls)
    effects: list[str] = []
    monkeypatch.setattr(
        run_agent,
        "handle_function_call",
        lambda _n, _a, _t, tool_call_id, **_k: (
            effects.append(tool_call_id) or "committed once"
        ),
    )
    monkeypatch.setattr(run_agent, "_should_parallelize_tool_batch", lambda _calls: False)
    monkeypatch.setattr("elevate_cli.plugins.invoke_hook", lambda *_a, **_k: [])

    after_execution = threading.Event()
    release_evidence = threading.Event()
    original_execute = agent._execute_tool_calls

    def _blocked_execute(*args, **kwargs):
        original_execute(*args, **kwargs)
        after_execution.set()
        assert release_evidence.wait(timeout=5)

    agent._execute_tool_calls = _blocked_execute
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("do it once")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert after_execution.wait(timeout=3)
    assert fence.snapshot()["permits_by_kind"].get("tool_batch_transaction") == 1
    fence.request_cancel(token, reason="stop before batch evidence")
    agent._interrupt_requested = True
    release_evidence.set()
    worker.join(timeout=8)

    assert "error" not in outcome
    assert effects == ["tool-1"]
    assert len(agent._last_tool_batch_outcomes) == 1
    assert _persisted_roles(session_db) == ["user", "assistant", "tool"]
    assert [m["role"] for m in _logged_messages(agent)] == [
        "user",
        "assistant",
        "tool",
    ]
    assert outcome["result"]["interrupted"] is True
    assert agent._current_tool is None
    assert fence.wait_quiesced(timeout=1)


def test_concurrent_checkpoint_barrier_finishes_before_any_handler(
    monkeypatch,
) -> None:
    first_snapshot_started = threading.Event()
    release_snapshot = threading.Event()
    handlers_started = threading.Event()
    checkpoint_calls: list[str] = []

    def _ensure_checkpoint(workdir, _reason):
        checkpoint_calls.append(workdir)
        if len(checkpoint_calls) == 1:
            first_snapshot_started.set()
            assert release_snapshot.wait(timeout=5)
        return True

    checkpoint_mgr = SimpleNamespace(
        enabled=True,
        get_working_dir_for_path=lambda _path: "/shared-workdir",
        ensure_checkpoint=_ensure_checkpoint,
    )

    def _handler(*_args, **_kwargs):
        assert checkpoint_calls == ["/shared-workdir"]
        handlers_started.set()
        return "written"

    stub = _concurrent_tool_stub(_handler)
    stub._checkpoint_mgr = checkpoint_mgr
    calls = [
        _ToolCall(
            '{"path":"/shared-workdir/a.txt"}',
            tool_id="tool-1",
            name="write_file",
        ),
        _ToolCall(
            '{"path":"/shared-workdir/b.txt"}',
            tool_id="tool-2",
            name="write_file",
        ),
    ]
    assistant = SimpleNamespace(tool_calls=calls)
    messages: list[dict] = []
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                stub._execute_tool_calls_concurrent(
                    assistant, messages, "task-1"
                )
        finally:
            fence.finish_worker(token, terminal_status="completed")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert first_snapshot_started.wait(timeout=2)
    assert not handlers_started.is_set()
    release_snapshot.set()
    worker.join(timeout=5)

    assert handlers_started.is_set()
    assert checkpoint_calls == ["/shared-workdir"]
    assert [m["tool_call_id"] for m in messages] == ["tool-1", "tool-2"]
    assert fence.wait_quiesced(timeout=1)


def test_failed_initial_receipt_rejects_concurrent_guidance_and_rolls_back(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._user_turn_count = 7
    agent._turns_since_memory = 3
    agent._iters_since_skill = 2
    agent._correction_this_turn = True
    agent._active_action_user_message = "prior action"
    agent._current_task_id = "prior-task"
    agent._compression_warning = "saved warning"
    agent._cleanup_dead_connections = MagicMock(return_value=True)
    agent._replay_compression_warning = MagicMock()
    agent.context_compressor.compress = MagicMock()
    memory_manager = MagicMock()
    agent._memory_manager = memory_manager
    hook_names: list[str] = []
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook",
        lambda name, **_kwargs: hook_names.append(name) or [],
    )
    receipt_started = threading.Event()
    release_receipt = threading.Event()

    def _fail_receipt(*_args, **_kwargs):
        receipt_started.set()
        assert release_receipt.wait(timeout=5)
        return False

    agent._persist_session = _fail_receipt
    outcome: dict[str, object] = {}

    worker = threading.Thread(
        target=lambda: outcome.setdefault(
            "result", agent.run_conversation("hello", task_id="new-task")
        )
    )
    worker.start()
    assert receipt_started.wait(timeout=2)
    assert (
        agent.steer(
            "arrived during failed receipt",
            client_message_id="receipt-race-A",
        )
        is False
    )
    release_receipt.set()
    worker.join(timeout=5)

    result = outcome["result"]
    assert result["api_calls"] == 0
    assert result["durability_confirmed"] is False
    assert "pending_inputs" not in result
    assert agent._drain_pending_inputs() == []
    assert agent._user_turn_count == 7
    assert agent._turns_since_memory == 3
    assert agent._iters_since_skill == 2
    assert agent._correction_this_turn is True
    assert agent._active_action_user_message == "prior action"
    assert agent._current_task_id == "prior-task"
    assert agent._compression_warning == "saved warning"
    agent._cleanup_dead_connections.assert_not_called()
    agent._replay_compression_warning.assert_not_called()
    agent.context_compressor.compress.assert_not_called()
    memory_manager.on_turn_start.assert_not_called()
    memory_manager.prefetch_all.assert_not_called()
    agent.client.chat.completions.create.assert_not_called()
    assert hook_names == []
    assert not worker.is_alive()


def test_failed_system_startup_rejects_guidance_before_lane_opens(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._cached_system_prompt = None
    agent._persist_session = MagicMock(return_value=True)
    agent._build_system_prompt = MagicMock(return_value="system contract")
    session_db = MagicMock()
    agent._session_db = session_db
    startup_write = threading.Event()
    release_startup = threading.Event()

    def _ambiguous_write(*_args, **_kwargs):
        startup_write.set()
        assert release_startup.wait(timeout=5)
        raise RuntimeError("write result unknown")

    session_db.update_system_prompt.side_effect = _ambiguous_write
    session_db.get_session.return_value = {}
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )
    outcome: dict[str, object] = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault(
            "result", agent.run_conversation("hello")
        )
    )
    worker.start()
    assert startup_write.wait(timeout=2)
    assert (
        agent.queue_soft_interrupt(
            "arrived during startup",
            client_message_id="startup-race-B",
        )
        is False
    )
    release_startup.set()
    worker.join(timeout=5)

    result = outcome["result"]
    assert result["api_calls"] == 0
    assert result["completed"] is False
    assert "pending_inputs" not in result
    assert agent._drain_pending_inputs() == []
    agent.client.chat.completions.create.assert_not_called()
    assert not worker.is_alive()


def _queue_two_guidance_items_once(agent: AIAgent):
    queued = False

    def _step(*_args) -> None:
        nonlocal queued
        if queued:
            return
        queued = True
        assert agent.steer("steer A", client_message_id="arbitrary-A")
        assert agent.queue_soft_interrupt(
            "soft B", client_message_id="arbitrary-B"
        )

    return _step


def test_invalid_response_never_acks_and_cold_resume_recovers_exact_guidance(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent._api_max_retries = 1
    agent._fallback_chain = []
    agent.step_callback = _queue_two_guidance_items_once(agent)
    invalid = SimpleNamespace(
        choices=[], model="test/model", usage=None, error=None, message=None
    )
    agent.client.chat.completions.create.return_value = invalid
    applied_events: list[tuple[str, list[str]]] = []

    def _progress(event, *_args, **kwargs):
        applied_events.append(
            (event, list(kwargs.get("client_message_ids") or []))
        )

    agent.tool_progress_callback = _progress
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    result = agent.run_conversation("initial request")

    assert applied_events == []
    assert [item["client_message_id"] for item in result["pending_inputs"]] == [
        "arbitrary-A",
        "arbitrary-B",
    ]
    assert [item["lane"] for item in result["pending_inputs"]] == [
        "steer",
        "soft",
    ]
    assert result["messages"][-1]["finish_reason"] == (
        "error_guidance_unconsumed"
    )

    resumed = _real_agent()
    resumed._persist_session = MagicMock(return_value=True)
    resumed.client.chat.completions.create.return_value = _response("recovered")
    resumed_events: list[list[str]] = []

    def _resumed_progress(event, *_args, **kwargs):
        if event == "steer.applied":
            resumed_events.append(
                list(kwargs.get("client_message_ids") or [])
            )

    resumed.tool_progress_callback = _resumed_progress
    resumed_result = resumed.run_conversation(
        "resume now", conversation_history=result["messages"]
    )

    assert resumed_result["completed"] is True
    assert resumed_events == [["arbitrary-A", "arbitrary-B"]]
    sent_messages = (
        resumed.client.chat.completions.create.call_args.kwargs["messages"]
    )
    sent_text = "\n".join(str(msg.get("content") or "") for msg in sent_messages)
    assert "steer A" in sent_text
    assert "soft B" in sent_text
    assert "Invalid API response after" not in sent_text


def test_outcome_unknown_tool_batch_cold_resume_recovers_reserved_guidance(
    monkeypatch,
) -> None:
    import run_agent

    tool_call = _ToolCall(tool_id="tool-outcome-1")
    agent = _real_agent()
    agent.client.chat.completions.create.return_value = _tool_response(
        [tool_call]
    )
    agent.valid_tool_names = {tool_call.function.name}
    agent.tool_delay = 0
    durable_snapshots: list[list[dict]] = []

    def _persist(messages, *_args, **_kwargs):
        durable_snapshots.append(
            json.loads(json.dumps(messages))
        )
        return True

    agent._persist_session = MagicMock(side_effect=_persist)
    agent._persist_session_under_retained_turn_permit = MagicMock(
        return_value=False
    )
    queued = False

    def _step(*_args) -> None:
        nonlocal queued
        if queued:
            return
        queued = True
        assert agent.steer(
            "verify before retrying the effect",
            client_message_id="outcome-guidance-A",
        )

    effects: list[str] = []

    def _invoke(_name, _args, _task, tool_call_id, **_kwargs):
        effects.append(tool_call_id)
        return "external effect may have committed"

    agent.step_callback = _step
    monkeypatch.setattr(run_agent, "handle_function_call", _invoke)
    monkeypatch.setattr(
        run_agent,
        "_should_parallelize_tool_batch",
        lambda _calls: False,
    )
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    fence.bind_worker(token)
    try:
        with bind_turn_fence(fence, token):
            result = agent.run_conversation("perform the effect")
    finally:
        fence.finish_worker(token, terminal_status="error")

    assert effects == ["tool-outcome-1"]
    assert result["outcome_unknown"] is True
    assert result["completed"] is False
    assert [
        item["client_message_id"] for item in result["pending_inputs"]
    ] == ["outcome-guidance-A"]
    assert result["messages"][-1]["finish_reason"] == (
        "error_guidance_unconsumed"
    )
    assert durable_snapshots[-1][-1]["finish_reason"] == (
        "error_guidance_unconsumed"
    )
    assert fence.wait_quiesced(timeout=1)

    cold_history = json.loads(json.dumps(durable_snapshots[-1]))
    resumed = _real_agent()
    resumed._persist_session = MagicMock(return_value=True)
    resumed.client.chat.completions.create.return_value = _response(
        "recovered safely"
    )
    resumed_events: list[list[str]] = []

    def _resumed_progress(event, *_args, **kwargs):
        if event == "steer.applied":
            resumed_events.append(
                list(kwargs.get("client_message_ids") or [])
            )

    resumed.tool_progress_callback = _resumed_progress
    resumed_result = resumed.run_conversation(
        "resume and verify", conversation_history=cold_history
    )

    assert resumed_result["completed"] is True
    assert resumed_events == [["outcome-guidance-A"]]
    assert effects == ["tool-outcome-1"]
    sent_messages = (
        resumed.client.chat.completions.create.call_args.kwargs["messages"]
    )
    sent_text = "\n".join(
        str(message.get("content") or "") for message in sent_messages
    )
    assert "verify before retrying the effect" in sent_text
    assert "external effect may have committed" in sent_text
    assert "A tool action may have completed" not in sent_text


def test_guidance_reservation_failure_hands_off_exact_inputs_without_provider(
    monkeypatch,
) -> None:
    agent = _real_agent()
    persistence_results = iter([True, False, True])
    agent._persist_session = MagicMock(
        side_effect=lambda *_args, **_kwargs: next(persistence_results)
    )
    agent.step_callback = _queue_two_guidance_items_once(agent)
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    result = agent.run_conversation("hello")

    assert result["api_calls"] == 0
    assert result["completed"] is False
    assert result["durability_confirmed"] is False
    assert [item["client_message_id"] for item in result["pending_inputs"]] == [
        "arbitrary-A",
        "arbitrary-B",
    ]
    assert [item["lane"] for item in result["pending_inputs"]] == [
        "steer",
        "soft",
    ]
    agent.client.chat.completions.create.assert_not_called()
    assert agent._persist_session.call_count == 3
    assert (
        agent.steer("after handoff", client_message_id="after-handoff")
        is False
    )


def test_guidance_ack_occurs_only_after_final_projection(monkeypatch) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    agent.step_callback = _queue_two_guidance_items_once(agent)
    persist_counts_at_ack: list[int] = []

    def _progress(event, *_args, **_kwargs):
        if event == "steer.applied":
            persist_counts_at_ack.append(agent._persist_session.call_count)

    agent.tool_progress_callback = _progress
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    result = agent.run_conversation("hello")

    assert result["completed"] is True
    assert persist_counts_at_ack == [3]
    assert "pending_inputs" not in result
    assert "pending_input_acks" not in result


def test_baseexception_during_steer_ack_preserves_ack_pending_ownership(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    queued = False

    def _step(*_args) -> None:
        nonlocal queued
        if queued:
            return
        queued = True
        assert agent.steer(
            "durably consumed guidance",
            client_message_id="ack-baseexception-A",
        )

    def _interrupt_ack(event, *_args, **_kwargs) -> None:
        if event == "steer.applied":
            raise KeyboardInterrupt("injected ACK interruption")

    agent.step_callback = _step
    agent.tool_progress_callback = _interrupt_ack
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    with pytest.raises(KeyboardInterrupt, match="ACK interruption"):
        agent.run_conversation("hello")

    assert agent._persist_session.call_count == 3
    assert agent._pending_input_ack_items_runtime == []
    assert [
        item["client_message_id"]
        for item in agent._pending_input_ack_delivery_runtime
    ] == ["ack-baseexception-A"]


def test_failed_ui_ack_never_redelivers_durably_consumed_guidance(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    queued = False

    def _step(*_args):
        nonlocal queued
        if not queued:
            queued = True
            assert agent.steer(
                "consume exactly once", client_message_id="ack-failure-A"
            )

    def _broken_progress(*_args, **_kwargs):
        raise RuntimeError("gateway callback unavailable")

    agent.step_callback = _step
    agent.tool_progress_callback = _broken_progress
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    result = agent.run_conversation("hello")

    assert result["completed"] is True
    assert "pending_inputs" not in result
    assert result["ack_pending"] is True
    assert result["pending_input_acks"] == [
        {
            "client_message_id": "ack-failure-A",
            "status": "consumed_durable",
        }
    ]


def test_producer_in_terminal_transfer_to_clear_gap_is_rejected(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    original_clear = agent.clear_interrupt
    late_acceptance: list[bool] = []

    def _clear_probe(*, preserve_queued_inputs=False):
        late_acceptance.append(
            agent.steer("too late", client_message_id="terminal-gap-A")
        )
        return original_clear(
            preserve_queued_inputs=preserve_queued_inputs
        )

    agent.clear_interrupt = _clear_probe
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    result = agent.run_conversation("hello")

    assert result["completed"] is True
    assert late_acceptance == [False]
    assert "pending_inputs" not in result
    assert agent._drain_pending_inputs() == []


def test_final_projection_failure_suppresses_completion_effects(
    monkeypatch,
) -> None:
    from agent import turn_attribution

    agent = _real_agent()
    persistence_results = iter([True, False])
    agent._persist_session = MagicMock(
        side_effect=lambda *_args, **_kwargs: next(persistence_results)
    )
    agent.client.chat.completions.create.return_value = _response("done")
    agent._save_trajectory = MagicMock()
    memory_manager = MagicMock()
    memory_manager.prefetch_all.return_value = ""
    agent._memory_manager = memory_manager
    attribution = MagicMock()
    monkeypatch.setattr(turn_attribution, "attribute_turn_safely", attribution)
    hooks: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook",
        lambda name, **kwargs: hooks.append((name, kwargs)) or [],
    )

    result = agent.run_conversation("hello")

    assert result["completed"] is False
    assert result["durability_confirmed"] is False
    assert result["transcript_durable"] is False
    assert "durability" in result["error"]
    agent._save_trajectory.assert_called_once()
    assert agent._save_trajectory.call_args.args[-1] is False
    assert not any(name == "post_llm_call" for name, _ in hooks)
    session_end = [kwargs for name, kwargs in hooks if name == "on_session_end"]
    assert session_end and session_end[-1]["completed"] is False
    attribution.assert_not_called()
    memory_manager.sync_all.assert_not_called()
    memory_manager.queue_prefetch_all.assert_not_called()


def test_json_and_db_projection_exceptions_are_attempted_independently() -> None:
    agent = _real_agent(session_db=MagicMock())
    agent._save_session_log = MagicMock(
        side_effect=RuntimeError("json failed")
    )
    agent._flush_messages_to_session_db = MagicMock(
        side_effect=RuntimeError("db failed")
    )

    confirmed = agent._persist_session_projection(
        [{"role": "user", "content": "hello"}]
    )

    assert confirmed is False
    agent._save_session_log.assert_called_once()
    agent._flush_messages_to_session_db.assert_called_once()


def test_cancel_after_final_projection_marks_terminal_mutation_nondurable(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    final_projection_reached = threading.Event()
    release_post_projection = threading.Event()

    def _block_trajectory(*_args, **_kwargs):
        final_projection_reached.set()
        assert release_post_projection.wait(timeout=5)

    agent._save_trajectory = _block_trajectory
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
        finally:
            fence.finish_worker(token, terminal_status="interrupted")

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert final_projection_reached.wait(timeout=3)
    assert agent._persist_session.call_count == 2
    fence.request_cancel(token, reason="stop after final projection")
    release_post_projection.set()
    worker.join(timeout=5)

    result = outcome["result"]
    assert result["completed"] is False
    assert result["interrupted"] is True
    assert result["durability_confirmed"] is False
    assert result["transcript_durable"] is False
    assert result["messages"][-1]["finish_reason"] == "interrupted"
    assert "after the last durable transcript projection" in result["error"]
    assert agent._persist_session.call_count == 2
    assert not worker.is_alive()
    assert fence.wait_quiesced(timeout=1)


def test_stop_at_final_model_result_release_cannot_return_completed(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent._persist_session = MagicMock(return_value=True)
    agent.client.chat.completions.create.return_value = _response("done")
    monkeypatch.setattr(
        "elevate_cli.plugins.invoke_hook", lambda *_args, **_kwargs: []
    )

    final_release_reached = threading.Event()
    release_final_result = threading.Event()
    original_release = TurnPermit.release

    def _controlled_release(permit) -> None:
        if (
            permit.kind == "model_result"
            and not final_release_reached.is_set()
        ):
            final_release_reached.set()
            assert release_final_result.wait(timeout=5)
        original_release(permit)

    monkeypatch.setattr(TurnPermit, "release", _controlled_release)
    fence = TurnFence()
    token = fence.begin_turn("prompt-1", "actor-1")
    outcome: dict[str, object] = {}

    def _run_turn() -> None:
        fence.bind_worker(token)
        try:
            with bind_turn_fence(fence, token):
                outcome["result"] = agent.run_conversation("hello")
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            result = outcome.get("result", {})
            status = (
                "interrupted"
                if result.get("interrupted")
                else "completed"
                if result.get("completed")
                else "error"
            )
            fence.finish_worker(token, terminal_status=status)

    worker = threading.Thread(target=_run_turn)
    worker.start()
    assert final_release_reached.wait(timeout=3)
    assert fence.snapshot()["permits_by_kind"].get("model_result") == 1

    fence.request_cancel(token, reason="stop at final result release")
    release_final_result.set()
    worker.join(timeout=5)

    assert "error" not in outcome
    assert not worker.is_alive()
    result = outcome["result"]
    assert result["completed"] is False
    assert result["interrupted"] is True
    assert result["durability_confirmed"] is False
    assert result["transcript_durable"] is False
    assert result["turn_exit_reason"] == (
        "interrupted_during_post_turn_effects"
    )
    assert result["messages"][-1]["finish_reason"] == "interrupted"
    assert fence.snapshot()["terminal_committed"] is False
    assert fence.wait_quiesced(timeout=1)


def test_direct_summary_chat_call_projects_local_message_metadata() -> None:
    agent = _real_agent()
    agent.client.chat.completions.create.return_value = _response("summary")
    messages = [
        {
            "role": "user",
            "content": "original",
            "client_message_id": "local-id",
            "finish_reason": "guidance_reserved_soft",
            "_future_local_field": "must not leak",
        }
    ]

    assert agent._handle_max_iterations(messages, 1) == "summary"

    sent = agent.client.chat.completions.create.call_args.kwargs["messages"]
    assert all("client_message_id" not in msg for msg in sent)
    assert all("finish_reason" not in msg for msg in sent)
    assert all("_future_local_field" not in msg for msg in sent)


def test_direct_memory_flush_chat_call_projects_local_message_metadata(
    monkeypatch,
) -> None:
    agent = _real_agent()
    agent.valid_tool_names = {"memory"}
    agent._memory_store = object()
    agent._user_turn_count = 1
    agent.tools = [
        {
            "type": "function",
            "function": {"name": "memory", "parameters": {}},
        }
    ]
    captured: dict[str, object] = {}

    def _call_llm(**kwargs):
        captured.update(kwargs)
        return _response("no memory update")

    monkeypatch.setattr("agent.auxiliary_client.call_llm", _call_llm)
    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {
            "role": "user",
            "content": "three",
            "client_message_id": "local-id",
            "_future_local_field": "must not leak",
        },
    ]

    agent.flush_memories(messages, min_turns=0)

    sent = captured["messages"]
    assert all("client_message_id" not in msg for msg in sent)
    assert all("_future_local_field" not in msg for msg in sent)
