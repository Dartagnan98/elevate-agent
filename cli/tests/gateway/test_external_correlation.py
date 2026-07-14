"""Adversarial tests for external gateway execution lineage."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.correlation import (
    accept_external_correlation_id,
    correlation_scope,
    current_correlation_session_id,
    is_lineage_id,
    is_opaque_correlation_id,
    record_correlation_event,
)
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult
from gateway.run import GatewayRunner
from gateway.session import SessionSource


class _LineageAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(), Platform.TELEGRAM)
        self.results = []

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None, **kwargs):
        if self.results:
            return self.results.pop(0)
        return SendResult(success=True, message_id="sent")

    async def send_typing(self, chat_id, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id):
        return {"chat_id": chat_id}


def _source(chat_id: str = "customer-chat") -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=chat_id,
        chat_type="dm",
        user_id="customer-user",
    )


def test_external_root_rejects_semantic_customer_labels():
    semantic_values = [
        "123 Main Street",
        "Dartagnan@example.com",
        "customer-session-42",
        "idem_invoice_987",
        "run_0123456789abcdef",
    ]

    roots = [accept_external_correlation_id(value) for value in semantic_values]

    assert len(set(roots)) == len(roots)
    assert all(is_opaque_correlation_id(root) for root in roots)
    assert not any(value in roots for value in semantic_values)


def test_recorder_drops_private_session_and_task_labels():
    root = accept_external_correlation_id()
    private_session = "agent:main:telegram:dm:private-chat:jane@example.com"
    private_task = "offer-for-123-main-street"
    captured = []

    def capture(event_type, **kwargs):
        captured.append((event_type, kwargs))
        return True

    with patch(
        "elevate_cli.diagnostics.session_recorder.record_session_event",
        side_effect=capture,
    ):
        with correlation_scope(root, private_session):
            assert current_correlation_session_id() == ""
            assert record_correlation_event(
                "gateway.delivery.attempt.started",
                correlation_id=root,
                session_id=private_session,
                task_id=private_task,
                status="started",
            )

    assert len(captured) == 1
    _, kwargs = captured[0]
    assert "session_id" not in kwargs
    assert "task_id" not in kwargs
    serialized = repr(captured)
    assert "private-chat" not in serialized
    assert "jane@example.com" not in serialized
    assert "123-main-street" not in serialized
    assert private_task not in serialized


def test_recorder_keeps_only_strict_internal_session_and_task_ids():
    root = accept_external_correlation_id()
    captured = []

    with patch(
        "elevate_cli.diagnostics.session_recorder.record_session_event",
        side_effect=lambda event_type, **kwargs: captured.append(
            (event_type, kwargs)
        )
        or True,
    ):
        with correlation_scope(root, "20260714_120000_deadbeef"):
            assert current_correlation_session_id() == "20260714_120000_deadbeef"
            assert record_correlation_event(
                "gateway.delegate.completed",
                correlation_id=root,
                session_id=current_correlation_session_id(),
                task_id="dt_deadbeef",
                status="completed",
            )

    assert captured[0][1]["session_id"] == "20260714_120000_deadbeef"
    assert captured[0][1]["task_id"] == "dt_deadbeef"


@pytest.mark.asyncio
async def test_platform_acceptance_never_uses_message_or_customer_ids(monkeypatch):
    adapter = _LineageAdapter()
    adapter.set_message_handler(MagicMock())
    accepted = []
    recorded = []
    adapter._start_session_processing = lambda event, _key: accepted.append(event)
    monkeypatch.setattr(
        "gateway.correlation.record_correlation_event",
        lambda event_type, **kwargs: recorded.append((event_type, kwargs)) or True,
    )

    first = MessageEvent(
        text="prepare an offer",
        source=_source(),
        message_id="client-message-123",
        correlation_id="123 Main Street / Buyer Name",
        parent_correlation_id="customer-parent",
        relation="anything-goes",
    )
    second = MessageEvent(
        text="follow up",
        source=_source(),
        message_id="client-message-124",
    )

    await adapter.handle_message(first)
    await adapter.handle_message(second)

    roots = [event.correlation_id for event in accepted]
    assert len(set(roots)) == 2
    assert all(is_opaque_correlation_id(root) for root in roots)
    assert "client-message-123" not in roots
    assert "123 Main Street / Buyer Name" not in roots
    assert first.parent_correlation_id is None
    assert first.relation is None
    assert [event for event, _ in recorded] == [
        "gateway.request.accepted",
        "gateway.request.accepted",
    ]


@pytest.mark.asyncio
async def test_delivery_retries_are_distinct_immutable_attempts(monkeypatch):
    adapter = _LineageAdapter()
    adapter.results = [
        SendResult(success=False, error="ConnectError", retryable=True),
        SendResult(success=False, error="ConnectError", retryable=True),
        SendResult(success=True, message_id="ok"),
    ]
    recorded = []
    monkeypatch.setattr(
        "gateway.correlation.record_correlation_event",
        lambda event_type, **kwargs: recorded.append({"event": event_type, **kwargs}) or True,
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await adapter._send_with_retry(
            "private-chat-123",
            "customer contract content",
            correlation_id="Buyer Jane / 123 Main Street",
            max_retries=2,
            base_delay=0,
        )

    assert result.success
    starts = [e for e in recorded if e["event"].endswith("attempt.started")]
    assert len(starts) == 3
    assert len({e["correlation_id"] for e in starts}) == 3
    assert all(is_lineage_id(e["correlation_id"]) for e in starts)
    assert starts[0]["relation"] == "delivery_attempt"
    assert is_opaque_correlation_id(starts[0]["parent_correlation_id"])
    assert starts[1]["relation"] == starts[2]["relation"] == "retry_of"
    assert starts[1]["parent_correlation_id"] == starts[0]["correlation_id"]
    assert starts[2]["parent_correlation_id"] == starts[1]["correlation_id"]

    serialized = repr(recorded)
    assert "private-chat-123" not in serialized
    assert "customer contract content" not in serialized
    assert "Buyer Jane" not in serialized
    assert "123 Main Street" not in serialized


@pytest.mark.asyncio
async def test_repeated_deliveries_under_one_root_get_new_attempt_ids(monkeypatch):
    adapter = _LineageAdapter()
    root = accept_external_correlation_id()
    recorded = []
    monkeypatch.setattr(
        "gateway.correlation.record_correlation_event",
        lambda event_type, **kwargs: recorded.append((event_type, kwargs)) or True,
    )

    await adapter._send_with_retry("chat", "same", correlation_id=root)
    await adapter._send_with_retry("chat", "same", correlation_id=root)

    starts = [kwargs for event, kwargs in recorded if event.endswith("attempt.started")]
    assert len(starts) == 2
    assert starts[0]["parent_correlation_id"] == root
    assert starts[1]["parent_correlation_id"] == root
    assert starts[0]["correlation_id"] != starts[1]["correlation_id"]


def test_delayed_delegate_callbacks_keep_their_acceptance_root(monkeypatch):
    runner = object.__new__(GatewayRunner)
    runner._pending_platform_delegates = {}
    runner._pending_platform_delegates_lock = threading.RLock()
    runner._running_agents = {"session": object()}
    runner._run_platform_delegate_wake = MagicMock()

    # Do not launch the ten-minute idle watcher; the test only needs the sink
    # acceptance/parking boundary.
    fake_thread = MagicMock()
    monkeypatch.setattr("gateway.run.threading.Thread", lambda **_kwargs: fake_thread)
    monkeypatch.setattr(
        "gateway.correlation.record_correlation_event", lambda *_args, **_kwargs: True
    )

    root_a = "corr_" + "a" * 32
    root_b = "corr_" + "b" * 32
    source = SimpleNamespace(
        platform=Platform.TELEGRAM,
        chat_id="chat",
        thread_id=None,
    )
    sink_a = runner._make_platform_delegate_sink(
        session_key="session",
        session_id="session-id",
        source=source,
        loop=object(),
        correlation_id=root_a,
    )
    sink_b = runner._make_platform_delegate_sink(
        session_key="session",
        session_id="session-id",
        source=source,
        loop=object(),
        correlation_id=root_b,
    )

    # B is accepted before A reports back. A's delayed callback must still
    # point to A, not the newer mutable turn.
    sink_b({"task_id": "dt_b", "results": [{"status": "completed", "summary": "B"}]})
    sink_a({"task_id": "dt_a", "results": [{"status": "completed", "summary": "A"}]})

    parked = runner._pending_platform_delegates["session"]
    assert parked[0]["parent_correlation_id"] == root_b
    assert parked[1]["parent_correlation_id"] == root_a
    assert parked[0]["correlation_id"] != parked[1]["correlation_id"]
    assert all(is_opaque_correlation_id(item["correlation_id"]) for item in parked)
    assert fake_thread.start.call_count == 2
