"""Tests for Telegram inline keyboard approval buttons."""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root is importable
# ---------------------------------------------------------------------------
_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


# ---------------------------------------------------------------------------
# Minimal Telegram mock so TelegramAdapter can be imported
# ---------------------------------------------------------------------------
def _ensure_telegram_mock():
    """Wire up the minimal mocks required to import TelegramAdapter."""
    if "telegram" in sys.modules and hasattr(sys.modules["telegram"], "__file__"):
        return

    mod = MagicMock()
    mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
    mod.constants.ParseMode.MARKDOWN = "Markdown"
    mod.constants.ParseMode.MARKDOWN_V2 = "MarkdownV2"
    mod.constants.ParseMode.HTML = "HTML"
    mod.constants.ChatType.PRIVATE = "private"
    mod.constants.ChatType.GROUP = "group"
    mod.constants.ChatType.SUPERGROUP = "supergroup"
    mod.constants.ChatType.CHANNEL = "channel"
    # Provide real exception classes so ``except (NetworkError, ...)`` in
    # connect() doesn't blow up under xdist when this mock leaks.
    mod.error.NetworkError = type("NetworkError", (OSError,), {})
    mod.error.TimedOut = type("TimedOut", (OSError,), {})
    mod.error.BadRequest = type("BadRequest", (Exception,), {})

    for name in ("telegram", "telegram.ext", "telegram.constants", "telegram.request"):
        sys.modules.setdefault(name, mod)
    sys.modules.setdefault("telegram.error", mod.error)


_ensure_telegram_mock()

from gateway.platforms.telegram import TelegramAdapter
from gateway.config import Platform, PlatformConfig


def _make_adapter(extra=None):
    """Create a TelegramAdapter with mocked internals."""
    config = PlatformConfig(enabled=True, token="test-token", extra=extra or {})
    adapter = TelegramAdapter(config)
    adapter._bot = AsyncMock()
    adapter._app = MagicMock()
    return adapter


# ===========================================================================
# send_exec_approval — inline keyboard buttons
# ===========================================================================

class TestTelegramExecApproval:
    """Test the send_exec_approval method sends InlineKeyboard buttons."""

    @pytest.mark.asyncio
    async def test_sends_inline_keyboard(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        result = await adapter.send_exec_approval(
            chat_id="12345",
            command="rm -rf /important",
            session_key="agent:main:telegram:group:12345:99",
            description="dangerous deletion",
            request_id="request-send",
        )

        assert result.success is True
        assert result.message_id == "42"

        adapter._bot.send_message.assert_called_once()
        kwargs = adapter._bot.send_message.call_args[1]
        assert kwargs["chat_id"] == 12345
        assert "rm -rf /important" in kwargs["text"]
        assert "dangerous deletion" in kwargs["text"]
        assert kwargs["reply_markup"] is not None  # InlineKeyboardMarkup

    @pytest.mark.asyncio
    async def test_stores_approval_state(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        await adapter.send_exec_approval(
            chat_id="12345",
            command="echo test",
            session_key="my-session-key",
            request_id="request-telegram",
        )

        # The approval_id should map to the session_key
        assert len(adapter._approval_state) == 1
        approval_id = list(adapter._approval_state.keys())[0]
        assert adapter._approval_state[approval_id] == {
            "request_id": "request-telegram",
            "session_key": "my-session-key",
        }

    @pytest.mark.asyncio
    async def test_sends_in_thread(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        await adapter.send_exec_approval(
            chat_id="12345",
            command="ls",
            session_key="s",
            metadata={"thread_id": "999"},
            request_id="request-thread",
        )

        kwargs = adapter._bot.send_message.call_args[1]
        assert kwargs.get("message_thread_id") == 999

    @pytest.mark.asyncio
    async def test_not_connected(self):
        adapter = _make_adapter()
        adapter._bot = None
        result = await adapter.send_exec_approval(
            chat_id="12345", command="ls", session_key="s"
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_disable_link_previews_sets_preview_kwargs(self):
        adapter = _make_adapter(extra={"disable_link_previews": True})
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        await adapter.send_exec_approval(
            chat_id="12345", command="ls", session_key="s", request_id="request-preview"
        )

        kwargs = adapter._bot.send_message.call_args[1]
        assert (
            kwargs.get("disable_web_page_preview") is True
            or kwargs.get("link_preview_options") is not None
        )

    @pytest.mark.asyncio
    async def test_truncates_long_command(self):
        adapter = _make_adapter()
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        adapter._bot.send_message = AsyncMock(return_value=mock_msg)

        long_cmd = "x" * 5000
        await adapter.send_exec_approval(
            chat_id="12345", command=long_cmd, session_key="s", request_id="request-long"
        )

        kwargs = adapter._bot.send_message.call_args[1]
        assert "..." in kwargs["text"]
        assert len(kwargs["text"]) < 5000

    @pytest.mark.asyncio
    async def test_interactive_prompt_without_identity_fails_closed(self):
        adapter = _make_adapter()

        result = await adapter.send_exec_approval(
            chat_id="12345", command="ls", session_key="s"
        )

        assert result.success is False
        assert "identity" in (result.error or "").lower()


class TestBetaTelegramAgentBotRefresh:
    """Hot refresh must not reopen a locked or arbitrary Beta bot lane."""

    @pytest.mark.asyncio
    async def test_refresh_starts_only_active_pack_agent_bots(self, monkeypatch):
        from elevate_cli import beta_env_policy

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(
            beta_env_policy,
            "beta_active_pack_env_metadata",
            lambda: {
                "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN": {},
            },
        )
        monkeypatch.setattr(
            "gateway.config._gateway_env_values",
            lambda: {
                "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN": "ea-token",
                "ELEVATE_AGENT_MARKETING_TELEGRAM_BOT_TOKEN": "locked-token",
                "ELEVATE_AGENT_ADS_TELEGRAM_BOT_TOKEN": "arbitrary-token",
            },
        )
        adapter = _make_adapter()
        adapter._agent_request_kwargs = {"connection_pool_size": 1}
        adapter._start_agent_polling_app = AsyncMock()

        await adapter._refresh_agent_bots()

        adapter._start_agent_polling_app.assert_awaited_once()
        assert (
            adapter._start_agent_polling_app.await_args.kwargs["agent_id"]
            == "executive-assistant"
        )

    @pytest.mark.asyncio
    async def test_refresh_stops_bot_when_beta_pack_locks(self, monkeypatch):
        from elevate_cli import beta_env_policy

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(
            beta_env_policy,
            "beta_active_pack_env_metadata",
            lambda: {
                "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN": {},
            },
        )
        monkeypatch.setattr("gateway.config._gateway_env_values", lambda: {})
        adapter = _make_adapter()
        adapter._agent_request_kwargs = {"connection_pool_size": 1}
        locked_app = MagicMock()
        locked_app.updater.running = True
        locked_app.updater.stop = AsyncMock()
        locked_app.running = True
        locked_app.stop = AsyncMock()
        locked_app.shutdown = AsyncMock()
        adapter._agent_apps["marketing"] = locked_app
        adapter._agent_bots["marketing"] = MagicMock()

        await adapter._refresh_agent_bots()

        assert "marketing" not in adapter._agent_apps
        assert "marketing" not in adapter._agent_bots
        locked_app.updater.stop.assert_awaited_once()
        locked_app.stop.assert_awaited_once()
        locked_app.shutdown.assert_awaited_once()


# ===========================================================================
# _handle_callback_query — approval button clicks
# ===========================================================================

class TestTelegramApprovalCallback:
    """Test the approval callback handling in _handle_callback_query."""

    @pytest.mark.asyncio
    async def test_resolves_approval_on_click(self):
        adapter = _make_adapter()
        # Set up approval state
        adapter._approval_state[1] = {
            "request_id": "request-once",
            "session_key": "agent:main:telegram:group:12345:99",
        }

        # Mock callback query
        query = AsyncMock()
        query.data = "ea:once:1"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()
        query.from_user.first_name = "Norbert"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._handle_callback_query(update, context)

        mock_resolve.assert_called_once_with(
            "agent:main:telegram:group:12345:99",
            "once",
            request_id="request-once",
        )
        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()

        # State should be cleaned up
        assert 1 not in adapter._approval_state

    @pytest.mark.asyncio
    async def test_deny_button(self):
        adapter = _make_adapter()
        adapter._approval_state[2] = {
            "request_id": "request-deny",
            "session_key": "some-session",
        }

        query = AsyncMock()
        query.data = "ea:deny:2"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()
        query.from_user.first_name = "Alice"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._handle_callback_query(update, context)

        mock_resolve.assert_called_once_with(
            "some-session",
            "deny",
            request_id="request-deny",
        )
        edit_kwargs = query.edit_message_text.call_args[1]
        assert "Denied" in edit_kwargs["text"]

    @pytest.mark.asyncio
    async def test_already_resolved(self):
        adapter = _make_adapter()
        # No state for approval_id 99 — already resolved

        query = AsyncMock()
        query.data = "ea:once:99"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()
        query.from_user.first_name = "Bob"
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            await adapter._handle_callback_query(update, context)

        # Should NOT resolve — already handled
        mock_resolve.assert_not_called()
        # Should still ack with "already resolved" message
        query.answer.assert_called_once()
        assert "already been resolved" in query.answer.call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_beta_wildcard_cannot_authorize_actual_button_caller(self):
        adapter = _make_adapter()
        pairing_store = MagicMock()
        pairing_store.is_approved.return_value = False
        adapter._approval_state[7] = {
            "request_id": "request-beta",
            "session_key": "beta-session",
        }
        query = AsyncMock()
        query.data = "ea:once:7"
        query.message = MagicMock(chat_id=12345)
        query.from_user = MagicMock(id=222, first_name="Unpaired")
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query)

        with (
            patch.dict(
                os.environ,
                {
                    "ELEVATE_RELEASE_CHANNEL": "beta",
                    "TELEGRAM_ALLOWED_USERS": "*",
                },
                clear=False,
            ),
            patch("gateway.pairing.PairingStore", return_value=pairing_store),
            patch("tools.approval.resolve_gateway_approval") as resolve,
        ):
            await adapter._handle_callback_query(update, MagicMock())

        resolve.assert_not_called()
        assert 7 in adapter._approval_state
        assert "not authorized" in query.answer.await_args.kwargs["text"].lower()

    @pytest.mark.asyncio
    async def test_beta_numeric_allowlist_binds_actual_button_caller(self):
        adapter = _make_adapter()
        adapter._approval_state[8] = {
            "request_id": "request-beta",
            "session_key": "beta-session",
        }
        query = AsyncMock()
        query.data = "ea:deny:8"
        query.message = MagicMock(chat_id=12345)
        query.from_user = MagicMock(id=222, first_name="Owner")
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock(callback_query=query)

        with (
            patch.dict(
                os.environ,
                {
                    "ELEVATE_RELEASE_CHANNEL": "beta",
                    "TELEGRAM_ALLOWED_USERS": "*,222",
                },
                clear=False,
            ),
            patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve,
        ):
            await adapter._handle_callback_query(update, MagicMock())

        resolve.assert_called_once_with(
            "beta-session",
            "deny",
            request_id="request-beta",
        )

    def test_beta_paired_numeric_caller_is_authorized(self):
        pairing_store = MagicMock()
        pairing_store.is_approved.return_value = True
        with (
            patch.dict(
                os.environ,
                {
                    "ELEVATE_RELEASE_CHANNEL": "beta",
                    "TELEGRAM_ALLOWED_USERS": "",
                },
                clear=False,
            ),
            patch("gateway.pairing.PairingStore", return_value=pairing_store),
        ):
            assert (
                TelegramAdapter._is_callback_user_authorized("222", "admin")
                is True
            )

        pairing_store.is_approved.assert_called_once_with("telegram", "222", "admin")

    @pytest.mark.asyncio
    async def test_model_picker_callback_not_affected(self):
        """Ensure model picker callbacks still route correctly."""
        adapter = _make_adapter()

        query = AsyncMock()
        query.data = "mp:some_provider"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        # Model picker callback should be handled (not crash)
        # We just verify it doesn't try to resolve an approval
        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            with patch.object(adapter, "_handle_model_picker_callback", new_callable=AsyncMock):
                await adapter._handle_callback_query(update, context)

        mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_not_affected(self, tmp_path):
        """Ensure update prompt callbacks still work."""
        adapter = _make_adapter()

        query = AsyncMock()
        query.data = "update_prompt:y"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()
        query.from_user.id = 123
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            with patch("elevate_constants.get_elevate_home", return_value=tmp_path):
                with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": ""}):
                    await adapter._handle_callback_query(update, context)

        # Should NOT have triggered approval resolution
        mock_resolve.assert_not_called()
        assert (tmp_path / ".update_response").read_text() == "y"

    @pytest.mark.asyncio
    async def test_update_prompt_callback_rejects_unauthorized_user(self, tmp_path):
        """Update prompt buttons should honor TELEGRAM_ALLOWED_USERS."""
        adapter = _make_adapter()

        query = AsyncMock()
        query.data = "update_prompt:y"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()
        query.from_user.id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("elevate_constants.get_elevate_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        assert "not authorized" in query.answer.call_args[1]["text"].lower()
        query.edit_message_text.assert_not_called()
        assert not (tmp_path / ".update_response").exists()

    @pytest.mark.asyncio
    async def test_update_prompt_callback_allows_authorized_user(self, tmp_path):
        """Allowed Telegram users can still answer update prompt buttons."""
        adapter = _make_adapter()

        query = AsyncMock()
        query.data = "update_prompt:n"
        query.message = MagicMock()
        query.message.chat_id = 12345
        query.from_user = MagicMock()
        query.from_user.id = 111
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        with patch("elevate_constants.get_elevate_home", return_value=tmp_path):
            with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USERS": "111"}):
                await adapter._handle_callback_query(update, context)

        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        assert (tmp_path / ".update_response").read_text() == "n"
