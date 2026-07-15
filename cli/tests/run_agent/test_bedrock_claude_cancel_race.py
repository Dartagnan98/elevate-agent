"""Cancellation fences for the active Bedrock-Claude Messages paths."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from run_agent import AIAgent, SteerCutInterrupt, _ProviderAttempt


CLAUDE_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_ENDPOINT = "https://bedrock-runtime.us-east-1.amazonaws.com"


class _RecordingMessages:
    def __init__(self) -> None:
        self.create_called = threading.Event()
        self.stream_called = threading.Event()

    def create(self, **_kwargs):
        self.create_called.set()
        return SimpleNamespace(content=[])

    def stream(self, **_kwargs):
        self.stream_called.set()
        raise AssertionError("messages.stream must not dispatch")


class _RecordingClient:
    def __init__(self) -> None:
        self.messages = _RecordingMessages()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _agent_stub(client: _RecordingClient) -> AIAgent:
    agent = AIAgent.__new__(AIAgent)
    agent.api_mode = "anthropic_messages"
    agent.provider = "bedrock"
    agent.model = CLAUDE_MODEL
    agent.base_url = BEDROCK_ENDPOINT
    agent._anthropic_client = client
    agent._anthropic_api_key = "aws-sdk"
    agent._anthropic_base_url = BEDROCK_ENDPOINT
    agent._is_anthropic_oauth = False
    agent._bedrock_guardrail_config = None
    agent._interrupt_requested = False
    agent._touch_activity = MagicMock()
    agent._emit_status = MagicMock()
    agent._replace_primary_openai_client = MagicMock()
    agent._close_request_openai_client = MagicMock()
    agent._fire_stream_delta = MagicMock()
    agent._fire_reasoning_delta = MagicMock()
    agent._fire_tool_gen_started = MagicMock()
    return agent


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("cancel_kind", ["timeout", "steer"])
def test_cancel_during_blocked_refresh_never_dispatches_on_rebuilt_client(
    monkeypatch: pytest.MonkeyPatch,
    streaming: bool,
    cancel_kind: str,
) -> None:
    old_client = _RecordingClient()
    replacement_client = _RecordingClient()
    agent = _agent_stub(old_client)
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    refresh_finished = threading.Event()
    spawned_workers = []

    def _blocked_refresh() -> bool:
        refresh_started.set()
        release_refresh.wait(timeout=3.0)
        refresh_finished.set()
        return False

    rebuild_calls = []

    def _rebuild() -> None:
        rebuild_calls.append(agent._anthropic_client)
        agent._anthropic_client = replacement_client

    agent._try_refresh_anthropic_client_credentials = _blocked_refresh
    agent._rebuild_anthropic_client = _rebuild
    real_spawn = agent._spawn_model_worker

    def _capture_worker(*args, **kwargs):
        worker = real_spawn(*args, **kwargs)
        spawned_workers.append(worker)
        return worker

    agent._spawn_model_worker = _capture_worker
    agent._consume_steer_cut_request = lambda: (
        cancel_kind == "steer" and refresh_started.is_set()
    )
    agent._compute_non_stream_stale_timeout = lambda _messages: (
        0.05 if cancel_kind == "timeout" else 5.0
    )
    monkeypatch.setenv(
        "ELEVATE_STREAM_STALE_TIMEOUT",
        "0.05" if cancel_kind == "timeout" else "5",
    )
    monkeypatch.setenv("ELEVATE_STREAM_RETRIES", "0")

    call = (
        agent._interruptible_streaming_api_call
        if streaming
        else agent._interruptible_api_call
    )
    expected_error = SteerCutInterrupt if cancel_kind == "steer" else TimeoutError

    try:
        with pytest.raises(expected_error):
            call(
                {
                    "model": CLAUDE_MODEL,
                    "messages": [{"role": "user", "content": "cancel me"}],
                }
            )
        assert refresh_started.is_set()
        assert old_client.close_calls == 1
        assert rebuild_calls == [old_client]
        assert agent._anthropic_client is replacement_client
        assert replacement_client.close_calls == 0
        assert not old_client.messages.create_called.is_set()
        assert not old_client.messages.stream_called.is_set()
        assert not replacement_client.messages.create_called.is_set()
        assert not replacement_client.messages.stream_called.is_set()
    finally:
        release_refresh.set()

    assert refresh_finished.wait(timeout=1.0)
    assert len(spawned_workers) == 1
    spawned_workers[0].join(timeout=1.0)
    assert not spawned_workers[0].is_alive(), "revoked raw worker must drain"
    assert not replacement_client.messages.create_called.wait(timeout=0.05)
    assert not replacement_client.messages.stream_called.wait(timeout=0.05)
    agent._fire_stream_delta.assert_not_called()
    agent._fire_reasoning_delta.assert_not_called()
    agent._fire_tool_gen_started.assert_not_called()


@pytest.mark.parametrize("streaming", [False, True])
def test_cancel_at_anthropic_dispatch_fence_never_calls_sdk(
    monkeypatch: pytest.MonkeyPatch,
    streaming: bool,
) -> None:
    old_client = _RecordingClient()
    replacement_client = _RecordingClient()
    agent = _agent_stub(old_client)
    fence_entered = threading.Event()
    release_fence = threading.Event()
    spawned_workers = []
    real_dispatch = _ProviderAttempt.dispatch_if_active

    def _blocked_dispatch(attempt: _ProviderAttempt, callback, *args, **kwargs):
        fence_entered.set()
        release_fence.wait(timeout=3.0)
        return real_dispatch(attempt, callback, *args, **kwargs)

    def _rebuild() -> None:
        assert agent._anthropic_client is old_client
        agent._anthropic_client = replacement_client

    real_spawn = agent._spawn_model_worker

    def _capture_worker(*args, **kwargs):
        worker = real_spawn(*args, **kwargs)
        spawned_workers.append(worker)
        return worker

    monkeypatch.setattr(
        _ProviderAttempt,
        "dispatch_if_active",
        _blocked_dispatch,
    )
    monkeypatch.setenv("ELEVATE_STREAM_STALE_TIMEOUT", "5")
    monkeypatch.setenv("ELEVATE_STREAM_RETRIES", "0")
    agent._try_refresh_anthropic_client_credentials = lambda: False
    agent._rebuild_anthropic_client = _rebuild
    agent._spawn_model_worker = _capture_worker
    agent._consume_steer_cut_request = lambda: fence_entered.is_set()
    agent._compute_non_stream_stale_timeout = lambda _messages: 5.0
    call = (
        agent._interruptible_streaming_api_call
        if streaming
        else agent._interruptible_api_call
    )

    try:
        with pytest.raises(SteerCutInterrupt):
            call(
                {
                    "model": CLAUDE_MODEL,
                    "messages": [{"role": "user", "content": "cancel at fence"}],
                }
            )
        assert fence_entered.is_set()
        assert old_client.close_calls == 1
        assert agent._anthropic_client is replacement_client
    finally:
        release_fence.set()

    assert len(spawned_workers) == 1
    spawned_workers[0].join(timeout=1.0)
    assert not spawned_workers[0].is_alive()
    assert not old_client.messages.create_called.is_set()
    assert not old_client.messages.stream_called.is_set()
    assert not replacement_client.messages.create_called.is_set()
    assert not replacement_client.messages.stream_called.is_set()


class _BlockingRawStream:
    def __init__(self) -> None:
        self.iterating = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0
        self._yielded_after_close = False

    def __iter__(self):
        return self

    def __next__(self):
        self.iterating.set()
        self.closed.wait(timeout=3.0)
        if self._yielded_after_close:
            raise StopIteration
        self._yielded_after_close = True
        # Deliberately produce a late delta after close. The revoked attempt
        # must discard it before any callback or final-message publication.
        return SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="late text"),
        )

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()

    def get_final_message(self):
        raise AssertionError("revoked raw stream must not publish a final message")


class _StreamManager:
    def __init__(self, raw_stream: _BlockingRawStream) -> None:
        self.raw_stream = raw_stream
        self.exited = threading.Event()

    def __enter__(self):
        return self.raw_stream

    def __exit__(self, _exc_type, _exc, _tb):
        self.exited.set()
        return False


class _StreamingMessages(_RecordingMessages):
    def __init__(self, manager: _StreamManager) -> None:
        super().__init__()
        self.manager = manager

    def stream(self, **_kwargs):
        self.stream_called.set()
        return self.manager


def test_stale_anthropic_stream_closes_exact_raw_stream_and_quiesces_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_stream = _BlockingRawStream()
    manager = _StreamManager(raw_stream)
    old_client = _RecordingClient()
    old_client.messages = _StreamingMessages(manager)
    replacement_client = _RecordingClient()
    agent = _agent_stub(old_client)
    agent._try_refresh_anthropic_client_credentials = lambda: False
    agent._consume_steer_cut_request = lambda: False

    def _rebuild() -> None:
        assert agent._anthropic_client is old_client
        agent._anthropic_client = replacement_client

    agent._rebuild_anthropic_client = _rebuild
    monkeypatch.setenv("ELEVATE_STREAM_STALE_TIMEOUT", "0.05")
    monkeypatch.setenv("ELEVATE_STREAM_RETRIES", "0")

    with pytest.raises(TimeoutError, match="Streaming API call timed out"):
        agent._interruptible_streaming_api_call(
            {
                "model": CLAUDE_MODEL,
                "messages": [{"role": "user", "content": "wait forever"}],
            }
        )

    assert old_client.messages.stream_called.is_set()
    assert raw_stream.iterating.is_set()
    assert raw_stream.close_calls == 1
    assert manager.exited.is_set(), "raw worker must drain before timeout returns"
    assert old_client.close_calls == 1
    assert agent._anthropic_client is replacement_client
    assert replacement_client.close_calls == 0
    agent._fire_stream_delta.assert_not_called()
    agent._fire_reasoning_delta.assert_not_called()
    agent._fire_tool_gen_started.assert_not_called()
