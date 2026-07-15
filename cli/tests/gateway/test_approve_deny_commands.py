"""Tests for /approve and /deny gateway commands.

Verifies that dangerous command approvals use the blocking gateway approval
mechanism — the agent thread blocks until the user responds with /approve
or /deny, mirroring the CLI's synchronous input() flow.

Supports multiple concurrent approvals (parallel subagents, execute_code)
via a per-session queue.
"""

import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=_make_source(),
        message_id="m1",
    )


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._background_tasks = set()
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    return runner


def _clear_approval_state():
    """Reset all module-level approval state between tests."""
    from tools import approval as mod
    mod._gateway_queues.clear()
    mod._gateway_notify_cbs.clear()
    mod._gateway_grant_stores.clear()
    mod._session_approved.clear()
    mod._permanent_approved.clear()
    mod._pending.clear()


def _durable_beta_entry(db, session_key: str, command: str):
    """Seed the same durable grant an exact-Beta terminal request creates."""
    from gateway.session_context import clear_session_vars, set_session_vars
    from tools import approval

    approval._initialize_approval_store(db)
    session_tokens = set_session_vars(
        platform="telegram",
        chat_id="c1",
        user_id="u1",
        session_key=session_key,
        message_id="m1",
    )
    policy_token = approval.set_current_execution_policy(
        approval.ExecutionPolicy.for_mode(f"turn-{command}", "default"),
        policy_revision=0,
    )
    try:
        entry = approval._ApprovalEntry(
            {"command": command},
            grant_store=db,
        )
        assert approval._prepare_durable_approval_grant(
            entry,
            session_key,
            command,
            timeout_seconds=300,
        )
        return entry
    finally:
        approval.reset_current_execution_policy(policy_token)
        clear_session_vars(session_tokens)


# ------------------------------------------------------------------
# Blocking gateway approval infrastructure (tools/approval.py)
# ------------------------------------------------------------------


class TestBlockingGatewayApproval:
    """Tests for the blocking approval mechanism in tools/approval.py."""

    def setup_method(self):
        _clear_approval_state()

    def test_register_and_resolve_unblocks_entry(self):
        """resolve_gateway_approval signals the entry's event."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, has_blocking_approval,
            _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-session"
        register_gateway_notify(session_key, lambda d: None)

        # Simulate what check_all_command_guards does
        entry = _ApprovalEntry({"command": "rm -rf /"})
        _gateway_queues.setdefault(session_key, []).append(entry)

        assert has_blocking_approval(session_key) is True

        # Resolve from another thread
        def resolve():
            time.sleep(0.1)
            resolve_gateway_approval(session_key, "once")

        t = threading.Thread(target=resolve)
        t.start()
        resolved = entry.event.wait(timeout=5)
        t.join()

        assert resolved is True
        assert entry.result == "once"
        unregister_gateway_notify(session_key)

    def test_resolve_returns_zero_when_no_pending(self):
        from tools.approval import resolve_gateway_approval
        assert resolve_gateway_approval("nonexistent", "once") == 0

    def test_resolve_all_unblocks_multiple_entries(self):
        """resolve_gateway_approval with resolve_all=True signals all entries."""
        from tools.approval import (
            resolve_gateway_approval, _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-all"
        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        e3 = _ApprovalEntry({"command": "cmd3"})
        _gateway_queues[session_key] = [e1, e2, e3]

        count = resolve_gateway_approval(session_key, "session", resolve_all=True)
        assert count == 3
        assert all(e.event.is_set() for e in [e1, e2, e3])
        assert all(e.result == "session" for e in [e1, e2, e3])

    def test_resolve_single_pops_oldest_fifo(self):
        """resolve_gateway_approval without resolve_all resolves oldest first."""
        from tools.approval import (
            resolve_gateway_approval,
            _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-fifo"
        e1 = _ApprovalEntry({"command": "first"})
        e2 = _ApprovalEntry({"command": "second"})
        _gateway_queues[session_key] = [e1, e2]

        count = resolve_gateway_approval(session_key, "once")
        assert count == 1
        assert e1.event.is_set()
        assert e1.result == "once"
        assert not e2.event.is_set()
        assert len(_gateway_queues[session_key]) == 1

    def test_entry_emits_opaque_id_and_retains_root_lineage(self):
        from tools.approval import _ApprovalEntry

        entry = _ApprovalEntry(
            {
                "command": "rm -rf /important",
                "correlation_id": "corr_0123456789abcdef0123456789abcdef",
                "request_id": "caller-controlled-id",
            }
        )

        assert len(entry.request_id) == 32
        assert all(char in "0123456789abcdef" for char in entry.request_id)
        assert entry.request_id != "caller-controlled-id"
        assert entry.data["request_id"] == entry.request_id
        assert entry.data["requestId"] == entry.request_id
        assert entry.data["correlation_id"] == "corr_0123456789abcdef0123456789abcdef"

        semantic = _ApprovalEntry(
            {
                "command": "rm -rf /important",
                "correlation_id": "customer@example.com",
                "session_id": "telegram:user-123:chat-456",
            }
        )
        assert semantic.correlation_id == ""
        assert "correlation_id" not in semantic.data
        assert "session_id" not in semantic.data

    @pytest.mark.parametrize(
        "unsafe",
        [
            "0123456789abcdef0123456789abcdef",
            "01234567-89ab-cdef-0123-456789abcdef",
            "request.0123456789abcdef0123456789abcdef",
            "wake.0123456789abcdef0123456789abcdef",
        ],
    )
    def test_entry_rejects_noncanonical_lineage(self, unsafe):
        from tools.approval import _ApprovalEntry

        entry = _ApprovalEntry({"command": "danger", "correlation_id": unsafe})

        assert entry.correlation_id == ""
        assert "correlation_id" not in entry.data

    @pytest.mark.parametrize("prefix", ["corr_", "attempt_"])
    def test_entry_reads_only_central_lineage_from_bound_context(self, prefix):
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools.approval import _ApprovalEntry

        root = f"{prefix}0123456789abcdef0123456789abcdef"
        tokens = set_session_vars(
            correlation_id=root,
            message_id="0123456789abcdef0123456789abcdef",
        )
        try:
            entry = _ApprovalEntry({"command": "danger"})
        finally:
            clear_session_vars(tokens)

        assert entry.correlation_id == root
        assert entry.data["correlation_id"] == root

    def test_failed_receipt_write_is_retried_under_concurrency(self):
        from tools.approval import _ApprovalEntry, _record_approval_receipt

        entry = _ApprovalEntry({"command": "danger"})
        first_write_started = threading.Event()
        release_first_write = threading.Event()
        calls = []

        def record_event(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                first_write_started.set()
                assert release_first_write.wait(timeout=5)
                return False
            return True

        def write_receipt():
            _record_approval_receipt(
                entry,
                "semantic-session-key",
                outcome="deny",
                reason="user_response",
            )

        with patch(
            "elevate_cli.diagnostics.session_recorder.record_session_event",
            side_effect=record_event,
        ):
            first = threading.Thread(target=write_receipt)
            second = threading.Thread(target=write_receipt)
            first.start()
            assert first_write_started.wait(timeout=5)
            second.start()
            release_first_write.set()
            first.join(timeout=5)
            second.join(timeout=5)

            deadline = time.monotonic() + 5
            while entry.receipt_outcome is None and time.monotonic() < deadline:
                time.sleep(0.01)

        assert not first.is_alive()
        assert not second.is_alive()
        assert len(calls) == 2
        assert entry.receipt_outcome == "deny"

    def test_receipt_never_persists_raw_session_or_semantic_lineage(self):
        from tools.approval import (
            _ApprovalEntry,
            _gateway_queues,
            resolve_gateway_approval,
        )

        session_key = "telegram:user@example.com:customer-name"
        entry = _ApprovalEntry(
            {
                "command": "danger",
                "correlation_id": "closing-for-Smith-family",
                "session_id": session_key,
            }
        )
        _gateway_queues[session_key] = [entry]

        with patch(
            "elevate_cli.diagnostics.session_recorder.record_session_event",
            return_value=True,
        ) as record_event:
            assert resolve_gateway_approval(
                session_key,
                "deny",
                request_id=entry.request_id,
            ) == 1

        receipt = record_event.call_args
        assert receipt.kwargs["session_id"] is None
        assert receipt.kwargs["correlation_id"] is None
        serialized = repr(receipt)
        assert "user@example.com" not in serialized
        assert "customer-name" not in serialized
        assert "Smith-family" not in serialized

    def test_request_id_resolves_out_of_order_and_stale_id_touches_nothing(self):
        from tools.approval import (
            _ApprovalEntry,
            _gateway_queues,
            resolve_gateway_approval,
        )

        session_key = "test-targeted"
        first = _ApprovalEntry({"command": "first"})
        second = _ApprovalEntry({"command": "second"})
        _gateway_queues[session_key] = [first, second]

        with patch(
            "elevate_cli.diagnostics.session_recorder.record_session_event",
            return_value=True,
        ) as record_event:
            assert resolve_gateway_approval(
                session_key,
                "deny",
                request_id=second.request_id,
            ) == 1
            assert second.event.is_set()
            assert second.result == "deny"
            assert not first.event.is_set()

            record_event.reset_mock()
            assert resolve_gateway_approval(
                session_key,
                "once",
                request_id="stale-or-wrong-id",
            ) == 0
            assert not first.event.is_set()
            assert _gateway_queues[session_key] == [first]
            record_event.assert_not_called()

            assert resolve_gateway_approval(
                session_key,
                "once",
                request_id=first.request_id,
            ) == 1
            assert first.event.is_set()
            assert first.result == "once"
            receipt = record_event.call_args
            assert receipt.args[0] == "approval.decision"
            assert receipt.kwargs["payload"] == {
                "request_id": first.request_id,
                "outcome": "once",
                "reason": "user_response",
                "status": "resolved",
            }

    def test_invalid_choice_fails_closed_without_consuming_request(self):
        from tools.approval import (
            _ApprovalEntry,
            _gateway_queues,
            resolve_gateway_approval,
        )

        session_key = "test-invalid-choice"
        entry = _ApprovalEntry({"command": "danger"})
        _gateway_queues[session_key] = [entry]

        assert resolve_gateway_approval(
            session_key,
            "not-a-real-choice",
            request_id=entry.request_id,
        ) == 0
        assert _gateway_queues[session_key] == [entry]
        assert not entry.event.is_set()
        assert entry.result is None

    def test_unregister_signals_all_entries(self):
        """unregister_gateway_notify signals all waiting entries to prevent hangs."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            _ApprovalEntry, _gateway_queues,
        )
        session_key = "test-cleanup"
        register_gateway_notify(session_key, lambda d: None)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        unregister_gateway_notify(session_key)
        assert e1.event.is_set()
        assert e2.event.is_set()


# ------------------------------------------------------------------
# /approve command
# ------------------------------------------------------------------


class TestApproveCommand:

    def setup_method(self):
        _clear_approval_state()

    @pytest.mark.asyncio
    async def test_approve_resolves_blocking_approval(self):
        """Basic /approve signals the oldest blocked agent thread."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        result = await runner._handle_approve_command(_make_event("/approve"))
        assert "approved" in result.lower()
        assert "resuming" in result.lower()
        assert entry.event.is_set()

    @pytest.mark.asyncio
    async def test_approve_all_resolves_multiple(self):
        """/approve all resolves all pending approvals."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_approve_command(_make_event("/approve all"))
        assert "2 commands" in result
        assert e1.event.is_set()
        assert e2.event.is_set()

    @pytest.mark.asyncio
    async def test_approve_all_session(self):
        """/approve all session resolves all with session scope."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_approve_command(_make_event("/approve all session"))
        assert "session" in result.lower()
        assert e1.result == "session"
        assert e2.result == "session"

    @pytest.mark.asyncio
    async def test_approve_no_pending(self):
        """/approve with no pending approval returns helpful message."""
        runner = _make_runner()
        result = await runner._handle_approve_command(_make_event("/approve"))
        assert "No pending command" in result

    @pytest.mark.asyncio
    async def test_approve_stale_old_style_pending(self):
        """Old-style _pending_approvals without blocking event reports expired."""
        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)
        runner._pending_approvals[session_key] = {"command": "test"}

        result = await runner._handle_approve_command(_make_event("/approve"))
        assert "expired" in result.lower() or "no longer waiting" in result.lower()
        assert session_key not in runner._pending_approvals

    @pytest.mark.asyncio
    async def test_exact_beta_requires_and_resolves_the_displayed_request_id(
        self,
        monkeypatch,
        tmp_path,
    ):
        from elevate_state import SessionDB
        from tools.approval import _gateway_queues

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)
        db = SessionDB(tmp_path / "state.db")
        first = _durable_beta_entry(db, session_key, "first")
        second = _durable_beta_entry(db, session_key, "second")
        _gateway_queues[session_key] = [first, second]

        missing = await runner._handle_approve_command(_make_event("/approve"))
        assert "request-id" in missing
        assert not first.event.is_set()
        assert not second.event.is_set()

        result = await runner._handle_approve_command(
            _make_event(f"/approve {second.request_id}")
        )

        assert "approved" in result.lower()
        assert not first.event.is_set()
        assert second.event.is_set()
        assert second.result == "once"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scope", ["all", "session", "always"])
    async def test_exact_beta_rejects_ambiguous_or_persistent_text_scope(
        self,
        monkeypatch,
        scope,
    ):
        from tools.approval import _ApprovalEntry, _gateway_queues

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        runner = _make_runner()
        session_key = runner._session_key_for_source(_make_source())
        entry = _ApprovalEntry({"command": "danger"})
        _gateway_queues[session_key] = [entry]

        result = await runner._handle_approve_command(
            _make_event(f"/approve {scope}")
        )

        assert "one identified command" in result
        assert not entry.event.is_set()


# ------------------------------------------------------------------
# /deny command
# ------------------------------------------------------------------


class TestDenyCommand:

    def setup_method(self):
        _clear_approval_state()

    @pytest.mark.asyncio
    async def test_deny_resolves_blocking_approval(self):
        """/deny signals the oldest blocked agent thread with 'deny'."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        result = await runner._handle_deny_command(_make_event("/deny"))
        assert "denied" in result.lower()
        assert entry.event.is_set()
        assert entry.result == "deny"

    @pytest.mark.asyncio
    async def test_deny_all_resolves_all(self):
        """/deny all denies all pending approvals."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        e1 = _ApprovalEntry({"command": "cmd1"})
        e2 = _ApprovalEntry({"command": "cmd2"})
        _gateway_queues[session_key] = [e1, e2]

        result = await runner._handle_deny_command(_make_event("/deny all"))
        assert "2 commands" in result
        assert all(e.result == "deny" for e in [e1, e2])

    @pytest.mark.asyncio
    async def test_deny_no_pending(self):
        """/deny with no pending approval returns helpful message."""
        runner = _make_runner()
        result = await runner._handle_deny_command(_make_event("/deny"))
        assert "No pending command" in result

    @pytest.mark.asyncio
    async def test_exact_beta_denies_only_the_displayed_request_id(
        self,
        monkeypatch,
        tmp_path,
    ):
        from elevate_state import SessionDB
        from tools.approval import _gateway_queues

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)
        db = SessionDB(tmp_path / "state.db")
        first = _durable_beta_entry(db, session_key, "first")
        second = _durable_beta_entry(db, session_key, "second")
        _gateway_queues[session_key] = [first, second]

        result = await runner._handle_deny_command(
            _make_event(f"/deny {second.request_id}")
        )

        assert "denied" in result.lower()
        assert not first.event.is_set()
        assert second.event.is_set()
        assert second.result == "deny"


class TestApprovalTextFallback:
    def test_exact_beta_prints_request_specific_one_time_commands(self, monkeypatch):
        from gateway.run import _gateway_approval_text_prompt

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        request_id = "0123456789abcdef0123456789abcdef"

        message = _gateway_approval_text_prompt(
            "rm -rf /important",
            "destructive command",
            request_id,
        )

        assert f"/approve {request_id}" in message
        assert f"/deny {request_id}" in message
        assert "/approve session" not in message
        assert "/approve always" not in message

    def test_exact_beta_missing_request_id_fails_closed(self, monkeypatch):
        from gateway.run import _gateway_approval_text_prompt

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

        message = _gateway_approval_text_prompt("danger", "reason", "")

        assert "secure request ID is missing" in message
        assert "no command was approved" in message
        assert "/approve" not in message

    def test_non_exact_channel_keeps_stable_text_commands(self, monkeypatch):
        from gateway.run import _gateway_approval_text_prompt

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")

        message = _gateway_approval_text_prompt("danger", "reason", "")

        assert "/approve session" in message
        assert "/approve always" in message


# ------------------------------------------------------------------
# Bare "yes" must NOT trigger approval
# ------------------------------------------------------------------


class TestBareTextNoLongerApproves:

    def setup_method(self):
        _clear_approval_state()

    @pytest.mark.asyncio
    async def test_yes_does_not_execute_pending_command(self):
        """Saying 'yes' must not trigger approval. Only /approve works."""
        from tools.approval import _ApprovalEntry, _gateway_queues

        runner = _make_runner()
        source = _make_source()
        session_key = runner._session_key_for_source(source)

        entry = _ApprovalEntry({"command": "test"})
        _gateway_queues[session_key] = [entry]

        # "yes" is not /approve — entry should still be pending
        assert not entry.event.is_set()


# ------------------------------------------------------------------
# End-to-end blocking flow
# ------------------------------------------------------------------


class TestBlockingApprovalE2E:
    """Test the full blocking flow: agent thread blocks → user approves → agent resumes."""

    def setup_method(self):
        _clear_approval_state()
        os.environ.pop("ELEVATE_YOLO_MODE", None)
        os.environ.pop("ELEVATE_INTERACTIVE", None)
        os.environ.pop("ELEVATE_GATEWAY_SESSION", None)
        os.environ.pop("ELEVATE_EXEC_ASK", None)
        os.environ.pop("ELEVATE_SESSION_KEY", None)

    def test_blocking_approval_approve_once(self):
        """check_all_command_guards blocks until resolve_gateway_approval is called."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
        )

        session_key = "e2e-test"
        notified = []

        register_gateway_notify(session_key, lambda d: notified.append(d))

        result_holder = [None]

        def agent_thread():
            from tools.approval import reset_current_session_key, set_current_session_key

            token = set_current_session_key(session_key)
            os.environ["ELEVATE_GATEWAY_SESSION"] = "1"
            os.environ["ELEVATE_EXEC_ASK"] = "1"
            os.environ["ELEVATE_SESSION_KEY"] = session_key
            try:
                result_holder[0] = check_all_command_guards(
                    "rm -rf /important", "local"
                )
            finally:
                os.environ.pop("ELEVATE_GATEWAY_SESSION", None)
                os.environ.pop("ELEVATE_EXEC_ASK", None)
                os.environ.pop("ELEVATE_SESSION_KEY", None)
                reset_current_session_key(token)

        t = threading.Thread(target=agent_thread)
        t.start()

        for _ in range(100):
            if notified:
                break
            time.sleep(0.05)

        assert len(notified) == 1
        assert "rm -rf /important" in notified[0]["command"]

        resolve_gateway_approval(session_key, "once")
        t.join(timeout=5)

        assert result_holder[0] is not None
        assert result_holder[0]["approved"] is True
        unregister_gateway_notify(session_key)

    def test_blocking_approval_deny(self):
        """check_all_command_guards returns BLOCKED when denied."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
        )

        session_key = "e2e-deny"
        notified = []
        register_gateway_notify(session_key, lambda d: notified.append(d))

        result_holder = [None]

        def agent_thread():
            from tools.approval import reset_current_session_key, set_current_session_key

            token = set_current_session_key(session_key)
            os.environ["ELEVATE_GATEWAY_SESSION"] = "1"
            os.environ["ELEVATE_EXEC_ASK"] = "1"
            os.environ["ELEVATE_SESSION_KEY"] = session_key
            try:
                result_holder[0] = check_all_command_guards(
                    "rm -rf /important", "local"
                )
            finally:
                os.environ.pop("ELEVATE_GATEWAY_SESSION", None)
                os.environ.pop("ELEVATE_EXEC_ASK", None)
                os.environ.pop("ELEVATE_SESSION_KEY", None)
                reset_current_session_key(token)

        t = threading.Thread(target=agent_thread)
        t.start()
        for _ in range(50):
            if notified:
                break
            time.sleep(0.05)

        resolve_gateway_approval(session_key, "deny")
        t.join(timeout=5)

        assert result_holder[0]["approved"] is False
        assert "BLOCKED" in result_holder[0]["message"]
        unregister_gateway_notify(session_key)

    def test_blocking_approval_timeout(self):
        """check_all_command_guards returns BLOCKED on timeout."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            check_all_command_guards,
        )

        session_key = "e2e-timeout"
        register_gateway_notify(session_key, lambda d: None)

        result_holder = [None]

        def agent_thread():
            from tools.approval import reset_current_session_key, set_current_session_key

            token = set_current_session_key(session_key)
            os.environ["ELEVATE_GATEWAY_SESSION"] = "1"
            os.environ["ELEVATE_EXEC_ASK"] = "1"
            os.environ["ELEVATE_SESSION_KEY"] = session_key
            try:
                with patch("tools.approval._get_approval_config",
                           return_value={"gateway_timeout": 1}):
                    result_holder[0] = check_all_command_guards(
                        "rm -rf /important", "local"
                    )
            finally:
                os.environ.pop("ELEVATE_GATEWAY_SESSION", None)
                os.environ.pop("ELEVATE_EXEC_ASK", None)
                os.environ.pop("ELEVATE_SESSION_KEY", None)
                reset_current_session_key(token)

        with patch(
            "elevate_cli.diagnostics.session_recorder.record_session_event",
            return_value=True,
        ) as record_event:
            t = threading.Thread(target=agent_thread)
            t.start()
            t.join(timeout=10)

        assert result_holder[0]["approved"] is False
        assert "timed out" in result_holder[0]["message"]
        timeout_receipts = [
            call
            for call in record_event.call_args_list
            if call.args[0] == "approval.decision"
            and call.kwargs["payload"].get("outcome") == "timeout"
        ]
        assert len(timeout_receipts) == 1
        assert timeout_receipts[0].kwargs["payload"]["reason"] == "wait_timeout"
        unregister_gateway_notify(session_key)

    def test_parallel_subagent_approvals(self):
        """Multiple threads can block concurrently and be resolved independently."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
            _gateway_queues,
        )

        session_key = "e2e-parallel"
        notified = []
        register_gateway_notify(session_key, lambda d: notified.append(d))

        results = [None, None, None]

        def make_agent(idx, cmd):
            def run():
                from tools.approval import reset_current_session_key, set_current_session_key

                token = set_current_session_key(session_key)
                os.environ["ELEVATE_GATEWAY_SESSION"] = "1"
                os.environ["ELEVATE_EXEC_ASK"] = "1"
                os.environ["ELEVATE_SESSION_KEY"] = session_key
                try:
                    results[idx] = check_all_command_guards(cmd, "local")
                finally:
                    os.environ.pop("ELEVATE_GATEWAY_SESSION", None)
                    os.environ.pop("ELEVATE_EXEC_ASK", None)
                    os.environ.pop("ELEVATE_SESSION_KEY", None)
                    reset_current_session_key(token)
            return run

        threads = [
            threading.Thread(target=make_agent(0, "rm -rf /a")),
            threading.Thread(target=make_agent(1, "rm -rf /b")),
            threading.Thread(target=make_agent(2, "rm -rf /c")),
        ]
        for t in threads:
            t.start()

        # Wait for all 3 to block
        for _ in range(100):
            if len(notified) >= 3:
                break
            time.sleep(0.05)

        assert len(notified) == 3
        assert len(_gateway_queues.get(session_key, [])) == 3

        # Approve all at once
        count = resolve_gateway_approval(session_key, "session", resolve_all=True)
        assert count == 3

        for t in threads:
            t.join(timeout=5)

        assert all(r is not None for r in results)
        assert all(r["approved"] is True for r in results)
        unregister_gateway_notify(session_key)

    def test_parallel_mixed_approve_deny(self):
        """Approve some, deny others in a parallel batch."""
        from tools.approval import (
            register_gateway_notify, unregister_gateway_notify,
            resolve_gateway_approval, check_all_command_guards,
        )

        session_key = "e2e-mixed"
        register_gateway_notify(session_key, lambda d: None)

        results = [None, None]

        def make_agent(idx, cmd):
            def run():
                from tools.approval import reset_current_session_key, set_current_session_key

                token = set_current_session_key(session_key)
                os.environ["ELEVATE_GATEWAY_SESSION"] = "1"
                os.environ["ELEVATE_EXEC_ASK"] = "1"
                os.environ["ELEVATE_SESSION_KEY"] = session_key
                try:
                    results[idx] = check_all_command_guards(cmd, "local")
                finally:
                    os.environ.pop("ELEVATE_GATEWAY_SESSION", None)
                    os.environ.pop("ELEVATE_EXEC_ASK", None)
                    os.environ.pop("ELEVATE_SESSION_KEY", None)
                    reset_current_session_key(token)
            return run

        threads = [
            threading.Thread(target=make_agent(0, "rm -rf /x")),
            threading.Thread(target=make_agent(1, "rm -rf /y")),
        ]
        for t in threads:
            t.start()

        # Wait for both threads to register pending approvals instead of
        # relying on a fixed sleep.  The approval module stores entries in
        # _gateway_queues[session_key] — poll until we see 2 entries.
        from tools.approval import _gateway_queues
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if len(_gateway_queues.get(session_key, [])) >= 2:
                break
            time.sleep(0.05)

        # Approve first, deny second
        resolve_gateway_approval(session_key, "once")   # oldest
        resolve_gateway_approval(session_key, "deny")   # next

        for t in threads:
            t.join(timeout=5)

        assert all(r is not None for r in results)
        assert sorted(r["approved"] for r in results) == [False, True]
        assert sum("BLOCKED" in (r.get("message") or "") for r in results) == 1
        unregister_gateway_notify(session_key)

    def test_parallel_requests_resolve_by_id_not_queue_order(self):
        """Out-of-order UI decisions stay attached to their own commands."""
        from tools.approval import (
            check_all_command_guards,
            register_gateway_notify,
            reset_current_session_key,
            resolve_gateway_approval,
            set_current_session_key,
            unregister_gateway_notify,
        )

        session_key = "e2e-targeted"
        notified = []
        results = {}
        register_gateway_notify(session_key, lambda data: notified.append(data))

        def run(command):
            token = set_current_session_key(session_key)
            try:
                results[command] = check_all_command_guards(command, "local")
            finally:
                reset_current_session_key(token)

        commands = ["rm -rf /approve-me", "rm -rf /deny-me"]
        with patch(
            "tools.approval._is_gateway_approval_context",
            return_value=True,
        ), patch(
            "elevate_cli.diagnostics.session_recorder.record_session_event",
            return_value=True,
        ):
            threads = [threading.Thread(target=run, args=(command,)) for command in commands]
            for thread in threads:
                thread.start()

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and len(notified) < 2:
                time.sleep(0.05)

            by_command = {item["command"]: item for item in notified}
            assert set(by_command) == set(commands)
            assert all(item["requestId"] == item["request_id"] for item in notified)

            # Resolve the second prompt first, proving queue order is irrelevant.
            assert resolve_gateway_approval(
                session_key,
                "deny",
                request_id=by_command["rm -rf /deny-me"]["request_id"],
            ) == 1
            assert resolve_gateway_approval(
                session_key,
                "once",
                request_id=by_command["rm -rf /approve-me"]["request_id"],
            ) == 1

            for thread in threads:
                thread.join(timeout=5)

        assert results["rm -rf /approve-me"]["approved"] is True
        assert results["rm -rf /deny-me"]["approved"] is False
        assert "BLOCKED" in results["rm -rf /deny-me"]["message"]
        unregister_gateway_notify(session_key)


# ------------------------------------------------------------------
# Fallback: no gateway callback (cron/batch mode)
# ------------------------------------------------------------------


class TestFallbackNoCallback:

    def setup_method(self):
        _clear_approval_state()

    def test_no_callback_returns_approval_required(self):
        """Without a registered callback, the fallback returns pending_approval.

        PR #6d495d9e7 renamed the LLM-visible status from ``approval_required``
        to ``pending_approval`` to make the state distinguishable from a
        failed tool call.
        """
        from tools.approval import check_all_command_guards

        os.environ["ELEVATE_EXEC_ASK"] = "1"
        os.environ["ELEVATE_SESSION_KEY"] = "no-callback-test"
        try:
            result = check_all_command_guards("rm -rf /important", "local")
        finally:
            os.environ.pop("ELEVATE_EXEC_ASK", None)
            os.environ.pop("ELEVATE_SESSION_KEY", None)

        assert result["approved"] is False
        assert result.get("status") == "pending_approval"
        assert result.get("approval_pending") is True
