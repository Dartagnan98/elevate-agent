"""Tests for Feishu interactive card approval buttons."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root is importable
# ---------------------------------------------------------------------------
_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


# ---------------------------------------------------------------------------
# Minimal Feishu mock so FeishuAdapter can be imported without lark-oapi
# ---------------------------------------------------------------------------
def _ensure_feishu_mocks():
    """Provide stubs for lark-oapi / aiohttp.web so the import succeeds."""
    if importlib.util.find_spec("lark_oapi") is None and "lark_oapi" not in sys.modules:
        mod = MagicMock()
        for name in (
            "lark_oapi", "lark_oapi.api.im.v1",
            "lark_oapi.event", "lark_oapi.event.callback_type",
        ):
            sys.modules.setdefault(name, mod)
    if importlib.util.find_spec("aiohttp") is None and "aiohttp" not in sys.modules:
        aio = MagicMock()
        sys.modules.setdefault("aiohttp", aio)
        sys.modules.setdefault("aiohttp.web", aio.web)


_ensure_feishu_mocks()

from gateway.config import PlatformConfig
import gateway.platforms.feishu as feishu_module
from gateway.platforms.feishu import FeishuAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter() -> FeishuAdapter:
    """Create a FeishuAdapter with mocked internals."""
    config = PlatformConfig(enabled=True)
    adapter = FeishuAdapter(config)
    adapter._client = MagicMock()
    return adapter


def _make_card_action_data(
    action_value: dict,
    chat_id: str = "oc_12345",
    message_id: str = "message-1",
    open_id: str = "ou_user1",
    token: str = "tok_abc",
) -> SimpleNamespace:
    """Create a mock Feishu card action callback data object."""
    return SimpleNamespace(
        event=SimpleNamespace(
            token=token,
            context=SimpleNamespace(
                open_chat_id=chat_id,
                open_message_id=message_id,
            ),
            operator=SimpleNamespace(open_id=open_id),
            action=SimpleNamespace(
                tag="button",
                value=action_value,
            ),
        ),
    )


def _close_submitted_coro(coro, _loop):
    """Close scheduled coroutines in sync-handler tests to avoid unawaited warnings."""
    coro.close()
    return SimpleNamespace(add_done_callback=lambda *_args, **_kwargs: None)


def _approval_nonce(value: int) -> str:
    return f"{value:016x}"


def _seed_approval(
    adapter: FeishuAdapter,
    approval_id: int,
    *,
    actor_id: str = "",
    chat_id: str = "oc_12345",
    message_id: str | None = None,
) -> str:
    nonce = _approval_nonce(approval_id)
    adapter._approval_state[nonce] = {
        "actor_id": actor_id,
        "session_key": f"session-{approval_id}",
        "request_id": f"request-{approval_id}",
        "message_id": message_id or "message-1",
        "chat_id": chat_id,
    }
    return nonce


# ===========================================================================
# send_exec_approval — interactive card with buttons
# ===========================================================================

class TestFeishuExecApproval:
    """Test send_exec_approval sends an interactive card."""

    @pytest.mark.asyncio
    async def test_sends_interactive_card(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_001"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_send:
            result = await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="rm -rf /important",
                session_key="agent:main:feishu:group:oc_12345",
                description="dangerous deletion",
                request_id="request-send",
            )

        assert result.success is True
        assert result.message_id == "msg_001"

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        assert kwargs["chat_id"] == "oc_12345"
        assert kwargs["msg_type"] == "interactive"

        # Verify card payload contains the command and buttons
        card = json.loads(kwargs["payload"])
        assert card["header"]["template"] == "orange"
        assert "rm -rf /important" in card["elements"][0]["content"]
        assert "dangerous deletion" in card["elements"][0]["content"]

        # Check buttons
        actions = card["elements"][1]["actions"]
        assert len(actions) == 4
        action_names = [a["value"]["elevate_action"] for a in actions]
        assert action_names == [
            "approve_once", "approve_session", "approve_always", "deny"
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("release_channel", "expected_actions"),
        [
            ("beta", ["approve_once", "deny"]),
            ("Beta", ["approve_once", "approve_session", "approve_always", "deny"]),
        ],
    )
    async def test_beta_prompt_only_advertises_supported_scope(
        self, release_channel, expected_actions
    ):
        adapter = _make_adapter()
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_scope"),
        )

        with (
            patch.dict(
                os.environ,
                {"ELEVATE_RELEASE_CHANNEL": release_channel},
                clear=False,
            ),
            patch.object(
                adapter,
                "_feishu_send_with_retry",
                new_callable=AsyncMock,
                return_value=response,
            ) as send,
        ):
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="rm -rf /important",
                session_key="feishu-session",
                request_id="request-feishu",
            )

        card = json.loads(send.await_args.kwargs["payload"])
        actions = card["elements"][1]["actions"]
        assert [action["value"]["elevate_action"] for action in actions] == expected_actions

    @pytest.mark.asyncio
    async def test_stores_approval_state(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_002"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="echo test",
                session_key="my-session-key",
                request_id="request-feishu",
            )

        assert len(adapter._approval_state) == 1
        approval_id = list(adapter._approval_state.keys())[0]
        state = adapter._approval_state[approval_id]
        assert state["actor_id"] == ""
        assert state["session_key"] == "my-session-key"
        assert state["request_id"] == "request-feishu"
        assert state["message_id"] == "msg_002"
        assert state["chat_id"] == "oc_12345"

    @pytest.mark.asyncio
    async def test_stores_originating_actor_identity(self):
        adapter = _make_adapter()
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_actor"),
        )
        with patch.object(
            adapter,
            "_feishu_send_with_retry",
            new_callable=AsyncMock,
            return_value=response,
        ):
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="echo actor",
                session_key="actor-session",
                metadata={"approval_actor_id": "ou_owner"},
                request_id="request-actor",
            )

        assert next(iter(adapter._approval_state.values()))["actor_id"] == "ou_owner"

    @pytest.mark.asyncio
    async def test_not_connected(self):
        adapter = _make_adapter()
        adapter._client = None
        result = await adapter.send_exec_approval(
            chat_id="oc_12345", command="ls", session_key="s"
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_truncates_long_command(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_003"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_send:
            long_cmd = "x" * 5000
            await adapter.send_exec_approval(
                chat_id="oc_12345", command=long_cmd, session_key="s", request_id="request-long"
            )

        card = json.loads(mock_send.call_args[1]["payload"])
        content = card["elements"][0]["content"]
        assert "..." in content
        assert len(content) < 5000

    @pytest.mark.asyncio
    async def test_multiple_approvals_get_unique_ids(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_x"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await adapter.send_exec_approval(
                chat_id="oc_1", command="cmd1", session_key="s1", request_id="request-one"
            )
            await adapter.send_exec_approval(
                chat_id="oc_2", command="cmd2", session_key="s2", request_id="request-two"
            )

        assert len(adapter._approval_state) == 2
        ids = list(adapter._approval_state.keys())
        assert ids[0] != ids[1]
        assert all(len(approval_id) == 16 for approval_id in ids)

    @pytest.mark.asyncio
    async def test_restart_does_not_reuse_old_card_identity(self):
        adapter = _make_adapter()
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_restart"),
        )
        with patch.object(
            adapter,
            "_feishu_send_with_retry",
            new_callable=AsyncMock,
            return_value=response,
        ) as send:
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="echo restart",
                session_key="restart-session",
                request_id="request-restart",
            )

        card = json.loads(send.await_args.kwargs["payload"])
        approval_id = card["elements"][1]["actions"][0]["value"]["approval_id"]
        restarted = _make_adapter()
        restarted._loop = MagicMock(is_closed=MagicMock(return_value=False))
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
            message_id="msg_restart",
        )

        with patch("tools.approval.resolve_gateway_approval") as resolve:
            restarted._on_card_action_trigger(data)

        resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_nonce_mint_retries_a_live_collision(self):
        adapter = _make_adapter()
        response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_collision"),
        )
        colliding = "A" * 16
        fresh = "B" * 16
        adapter._approval_state[colliding] = {}

        with (
            patch.object(
                adapter,
                "_feishu_send_with_retry",
                new_callable=AsyncMock,
                return_value=response,
            ),
            patch(
                "gateway.approval_callback.secrets.token_urlsafe",
                side_effect=[colliding, fresh],
            ),
        ):
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="echo collision",
                session_key="collision-session",
                request_id="request-collision",
            )

        assert fresh in adapter._approval_state

    @pytest.mark.asyncio
    async def test_interactive_prompt_without_identity_fails_closed(self):
        adapter = _make_adapter()

        result = await adapter.send_exec_approval(
            chat_id="oc_12345", command="ls", session_key="s"
        )

        assert result.success is False
        assert "identity" in (result.error or "").lower()


# ===========================================================================
# _resolve_approval — approval state pop + gateway resolution
# ===========================================================================

class TestResolveApproval:
    """Test _resolve_approval pops state and calls resolve_gateway_approval."""

    @pytest.mark.asyncio
    async def test_resolves_once(self):
        adapter = _make_adapter()
        approval_id = _approval_nonce(1)
        adapter._approval_state[approval_id] = {
            "actor_id": "ou_norbert",
            "session_key": "agent:main:feishu:group:oc_12345",
            "request_id": "request-once",
            "message_id": "msg_001",
            "chat_id": "oc_12345",
        }

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._resolve_approval(
                approval_id,
                "once",
                "Norbert",
                actor_id="ou_norbert",
                chat_id="oc_12345",
                message_id="msg_001",
            )

        mock_resolve.assert_called_once_with(
            "agent:main:feishu:group:oc_12345",
            "once",
            request_id="request-once",
        )
        assert approval_id not in adapter._approval_state

    @pytest.mark.asyncio
    async def test_resolves_deny(self):
        adapter = _make_adapter()
        approval_id = _approval_nonce(2)
        adapter._approval_state[approval_id] = {
            "actor_id": "ou_alice",
            "session_key": "some-session",
            "request_id": "request-deny",
            "message_id": "msg_002",
            "chat_id": "oc_12345",
        }

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._resolve_approval(
                approval_id,
                "deny",
                "Alice",
                actor_id="ou_alice",
                chat_id="oc_12345",
                message_id="msg_002",
            )

        mock_resolve.assert_called_once_with(
            "some-session",
            "deny",
            request_id="request-deny",
        )

    @pytest.mark.asyncio
    async def test_resolves_session(self):
        adapter = _make_adapter()
        approval_id = _approval_nonce(3)
        adapter._approval_state[approval_id] = {
            "actor_id": "ou_bob",
            "session_key": "sess-3",
            "request_id": "request-session",
            "message_id": "msg_003",
            "chat_id": "oc_99",
        }

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._resolve_approval(
                approval_id,
                "session",
                "Bob",
                actor_id="ou_bob",
                chat_id="oc_99",
                message_id="msg_003",
            )

        mock_resolve.assert_called_once_with(
            "sess-3",
            "session",
            request_id="request-session",
        )

    @pytest.mark.asyncio
    async def test_resolves_always(self):
        adapter = _make_adapter()
        approval_id = _approval_nonce(4)
        adapter._approval_state[approval_id] = {
            "actor_id": "ou_carol",
            "session_key": "sess-4",
            "request_id": "request-always",
            "message_id": "msg_004",
            "chat_id": "oc_55",
        }

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._resolve_approval(
                approval_id,
                "always",
                "Carol",
                actor_id="ou_carol",
                chat_id="oc_55",
                message_id="msg_004",
            )

        mock_resolve.assert_called_once_with(
            "sess-4",
            "always",
            request_id="request-always",
        )

    @pytest.mark.asyncio
    async def test_already_resolved_drops_silently(self):
        adapter = _make_adapter()

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            await adapter._resolve_approval(
                _approval_nonce(99), "once", "Nobody"
            )

        mock_resolve.assert_not_called()

# ===========================================================================
# _handle_card_action_event — non-approval card actions
# ===========================================================================

class TestNonApprovalCardAction:
    """Non-approval card actions should still route as synthetic commands."""

    @pytest.mark.asyncio
    async def test_routes_as_synthetic_command(self):
        adapter = _make_adapter()

        data = _make_card_action_data(
            action_value={"custom_action": "something_else"},
            token="tok_normal",
        )

        with (
            patch.object(
                adapter, "_resolve_sender_profile", new_callable=AsyncMock,
                return_value={"user_id": "ou_u", "user_name": "Dave", "user_id_alt": None},
            ),
            patch.object(adapter, "get_chat_info", new_callable=AsyncMock, return_value={"name": "Test Chat"}),
            patch.object(adapter, "_handle_message_with_guards", new_callable=AsyncMock) as mock_handle,
        ):
            await adapter._handle_card_action_event(data)

        mock_handle.assert_called_once()
        event = mock_handle.call_args[0][0]
        assert "/card button" in event.text


# ===========================================================================
# _on_card_action_trigger — inline card response for approval actions
# ===========================================================================

class _FakeCallBackCard:
    def __init__(self):
        self.type = None
        self.data = None


class _FakeP2Response:
    def __init__(self):
        self.card = None


@pytest.fixture(autouse=False)
def _patch_callback_card_types(monkeypatch):
    """Provide real-ish P2CardActionTriggerResponse / CallBackCard for tests."""
    monkeypatch.setattr(feishu_module, "P2CardActionTriggerResponse", _FakeP2Response)
    monkeypatch.setattr(feishu_module, "CallBackCard", _FakeCallBackCard)


class TestCardActionCallbackResponse:
    """Test that _on_card_action_trigger returns updated card inline."""

    def test_drops_action_when_loop_not_ready(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = None
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": _approval_nonce(1)}
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_returns_card_for_approve_action(self, _patch_callback_card_types):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 1)
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
            open_id="ou_bob",
        )
        adapter._sender_name_cache["ou_bob"] = ("Bob", 9999999999)

        with patch("tools.approval.resolve_gateway_approval", return_value=1):
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is not None
        assert response.card.type == "raw"
        card = response.card.data
        assert card["header"]["template"] == "green"
        assert "Approved once" in card["header"]["title"]["content"]
        assert "Bob" in card["elements"][0]["content"]
        assert approval_id not in adapter._approval_state

    def test_returns_card_for_deny_action(self, _patch_callback_card_types):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 2)
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data(
            {"elevate_action": "deny", "approval_id": approval_id},
        )

        with patch("tools.approval.resolve_gateway_approval", return_value=1):
            response = adapter._on_card_action_trigger(data)

        assert response.card is not None
        card = response.card.data
        assert card["header"]["template"] == "red"
        assert "Denied" in card["header"]["title"]["content"]

    @pytest.mark.parametrize(
        ("actor_id", "chat_id", "message_id"),
        [
            ("", "oc_12345", "message-1"),
            ("ou_other", "oc_12345", "message-1"),
            ("ou_owner", "", "message-1"),
            ("ou_owner", "oc_other", "message-1"),
            ("ou_owner", "oc_12345", ""),
            ("ou_owner", "oc_12345", "message-other"),
        ],
    )
    def test_callback_must_match_bound_actor_chat_and_message(
        self,
        _patch_callback_card_types,
        actor_id,
        chat_id,
        message_id,
    ):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 20, actor_id="ou_owner")
        adapter._loop = MagicMock(is_closed=MagicMock(return_value=False))
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
            open_id=actor_id,
            chat_id=chat_id,
            message_id=message_id,
        )

        with patch("tools.approval.resolve_gateway_approval") as resolve:
            response = adapter._on_card_action_trigger(data)

        resolve.assert_not_called()
        assert approval_id in adapter._approval_state
        card = response.card.data
        assert card["header"]["template"] == "orange"
        assert "not confirmed" in card["elements"][0]["content"].lower()

    def test_duplicate_click_resolves_exactly_once(self, _patch_callback_card_types):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 21, actor_id="ou_owner")
        adapter._loop = MagicMock(is_closed=MagicMock(return_value=False))
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
            open_id="ou_owner",
        )

        with patch(
            "tools.approval.resolve_gateway_approval", return_value=1
        ) as resolve:
            first = adapter._on_card_action_trigger(data)
            second = adapter._on_card_action_trigger(data)

        resolve.assert_called_once_with(
            "session-21", "once", request_id="request-21"
        )
        assert "Approved once" in first.card.data["header"]["title"]["content"]
        assert "Approval Request Stale" in second.card.data["header"]["title"]["content"]

    def test_non_exact_resolver_count_never_reports_success(
        self, _patch_callback_card_types
    ):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 22, actor_id="ou_owner")
        adapter._loop = MagicMock(is_closed=MagicMock(return_value=False))
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
            open_id="ou_owner",
        )

        with patch("tools.approval.resolve_gateway_approval", return_value=2):
            response = adapter._on_card_action_trigger(data)

        assert approval_id not in adapter._approval_state
        card = response.card.data
        assert card["header"]["template"] == "orange"
        assert "Approved once" not in card["header"]["title"]["content"]

    def test_ignores_missing_approval_id(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data({"elevate_action": "approve_once"})

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_no_card_for_non_approval_action(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data({"some_other": "value"})

        with patch("asyncio.run_coroutine_threadsafe", side_effect=_close_submitted_coro):
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None

    def test_falls_back_to_open_id_when_name_not_cached(self, _patch_callback_card_types):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 3)
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data(
            {"elevate_action": "approve_session", "approval_id": approval_id},
            open_id="ou_unknown",
        )

        with patch("tools.approval.resolve_gateway_approval", return_value=1):
            response = adapter._on_card_action_trigger(data)

        card = response.card.data
        assert "ou_unknown" in card["elements"][0]["content"]

    def test_ignores_expired_cached_name(self, _patch_callback_card_types):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 4)
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
            open_id="ou_expired",
        )
        adapter._sender_name_cache["ou_expired"] = ("Old Name", 1)

        with patch("tools.approval.resolve_gateway_approval", return_value=1):
            response = adapter._on_card_action_trigger(data)

        card = response.card.data
        assert "Old Name" not in card["elements"][0]["content"]
        assert "ou_expired" in card["elements"][0]["content"]

    @pytest.mark.parametrize(
        ("release_channel", "expected_actions"),
        [
            ("beta", ["approve_once", "deny"]),
            ("Beta", ["approve_once", "approve_session", "approve_always", "deny"]),
        ],
    )
    def test_retry_card_preserves_channel_specific_scope(
        self, release_channel, expected_actions
    ):
        with patch.dict(
            os.environ,
            {"ELEVATE_RELEASE_CHANNEL": release_channel},
            clear=False,
        ):
            card = FeishuAdapter._build_pending_approval_card(
                approval_id=_approval_nonce(7),
                retryable=True,
                resolution_error=True,
            )

        actions = card["elements"][1]["actions"]
        assert [action["value"]["elevate_action"] for action in actions] == expected_actions

    @pytest.mark.parametrize("resolver_result", [0, RuntimeError("resolver down")])
    def test_unconfirmed_action_returns_retryable_pending_card(
        self, _patch_callback_card_types, resolver_result
    ):
        adapter = _make_adapter()
        approval_id = _seed_approval(adapter, 5)
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data(
            {"elevate_action": "approve_once", "approval_id": approval_id},
        )
        effect = (
            {"side_effect": resolver_result}
            if isinstance(resolver_result, Exception)
            else {"return_value": resolver_result}
        )

        with patch("tools.approval.resolve_gateway_approval", **effect):
            response = adapter._on_card_action_trigger(data)

        assert approval_id in adapter._approval_state
        card = response.card.data
        assert card["header"]["template"] == "orange"
        status = card["elements"][0]["content"].lower()
        if isinstance(resolver_result, Exception):
            assert "check failed" in status
            assert "try again" in status
        else:
            assert "may be stale" in status
        assert "no command was approved" in status
        assert card["elements"][1]["tag"] == "action"
