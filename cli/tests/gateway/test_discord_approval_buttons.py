"""Identity binding for Discord dangerous-command approval buttons."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.discord import DiscordAdapter, ExecApprovalView, discord


@pytest.mark.asyncio
async def test_send_exec_approval_binds_central_request_identity():
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="token"))
    message = SimpleNamespace(id=42)
    channel = SimpleNamespace(send=AsyncMock(return_value=message))
    adapter._client = SimpleNamespace(
        get_channel=lambda _channel_id: channel,
        fetch_channel=AsyncMock(return_value=channel),
    )

    embed = SimpleNamespace(add_field=lambda **_kwargs: None)
    with patch.object(discord, "Embed", return_value=embed):
        result = await adapter.send_exec_approval(
            chat_id="123",
            command="rm -rf /tmp/example",
            session_key="discord-session",
            request_id="request-discord",
        )

    assert result.success is True
    view = channel.send.await_args.kwargs["view"]
    assert view.session_key == "discord-session"
    assert view.request_id == "request-discord"


@pytest.mark.asyncio
async def test_interactive_prompt_without_identity_fails_closed():
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="token"))
    channel = SimpleNamespace(send=AsyncMock())
    adapter._client = SimpleNamespace(
        get_channel=lambda _channel_id: channel,
        fetch_channel=AsyncMock(return_value=channel),
    )

    result = await adapter.send_exec_approval(
        chat_id="123",
        command="rm -rf /tmp/example",
        session_key="discord-session",
    )

    assert result.success is False
    assert "identity" in (result.error or "").lower()
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_button_targets_its_request_not_fifo_queue():
    view = ExecApprovalView(
        session_key="discord-session",
        request_id="request-discord",
        allowed_user_ids=set(),
    )
    interaction = SimpleNamespace(
        message=SimpleNamespace(embeds=[]),
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        user=SimpleNamespace(display_name="Agent", id=123),
    )

    with patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve:
        await view._resolve(
            interaction,
            "once",
            discord.Color.green(),
            "Approved once",
        )

    resolve.assert_called_once_with(
        "discord-session",
        "once",
        request_id="request-discord",
    )
