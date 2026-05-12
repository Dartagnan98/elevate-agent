import pytest

from gateway.agent_lanes import (
    agent_telegram_bot_token_env_var,
    agent_telegram_delivery_target,
    agent_telegram_env_var,
    agent_telegram_lane_ready,
    parse_telegram_target,
    resolve_agent_lane_for_source,
    telegram_target_matches,
)


class _DummyChat:
    id = -100123456


class _DummyMessage:
    chat = _DummyChat()

    def __init__(self, thread_id=None):
        self.message_thread_id = thread_id


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)


def test_agent_telegram_env_var_is_stable():
    assert agent_telegram_env_var("executive-assistant") == "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL"
    assert agent_telegram_env_var("social-media") == "ELEVATE_AGENT_SOCIAL_MEDIA_TELEGRAM_CHANNEL"
    assert agent_telegram_bot_token_env_var("admin") == "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN"


def test_agent_telegram_delivery_target_uses_per_agent_env(monkeypatch):
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "-100123:42")
    assert agent_telegram_delivery_target("admin") == "telegram:-100123:42"


def test_agent_telegram_delivery_target_keeps_admin_legacy_env(monkeypatch):
    monkeypatch.delenv("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", raising=False)
    monkeypatch.setenv("ELEVATE_ADMIN_AGENT_TELEGRAM_CHANNEL", "-100999")
    assert agent_telegram_delivery_target("admin") == "telegram:-100999"


def test_agent_telegram_delivery_target_rejects_bot_token_in_channel(monkeypatch):
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "8076612932:AAELfye8qSZpbBVTg0fH5-bCpT1KGGsxsJY")
    assert agent_telegram_delivery_target("admin") == "telegram"


def test_non_executive_lane_not_ready_with_shared_bot_token(monkeypatch):
    token = "8076612932:AAELfye8qSZpbBVTg0fH5-bCpT1KGGsxsJY"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "-100123")
    assert agent_telegram_lane_ready("admin") is False


def test_executive_lane_can_use_legacy_shared_token_as_its_bot(monkeypatch):
    token = "8076612932:AAELfye8qSZpbBVTg0fH5-bCpT1KGGsxsJY"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL", "-100123")
    assert agent_telegram_lane_ready("executive-assistant") is True


def test_parse_and_match_telegram_targets():
    assert parse_telegram_target("telegram:-100123:42") == ("-100123", "42")
    assert parse_telegram_target("8076612932:AAELfye8qSZpbBVTg0fH5-bCpT1KGGsxsJY") == ("", None)
    assert telegram_target_matches("telegram:-100123:42", chat_id="-100123", thread_id="42")
    assert not telegram_target_matches("telegram:-100123:42", chat_id="-100123", thread_id="43")


def test_resolve_agent_lane_by_telegram_env(monkeypatch):
    monkeypatch.setenv("ELEVATE_AGENT_OUTREACH_TELEGRAM_CHANNEL", "-100777")
    config = {
        "agent_hub": {
            "default_agent": "executive-assistant",
            "agents": [
                {"id": "executive-assistant", "name": "Executive Assistant", "platforms": ["telegram"]},
                {"id": "outreach", "name": "Outreach", "platforms": ["telegram"]},
            ],
        }
    }
    agent = resolve_agent_lane_for_source(
        config,
        platform="telegram",
        chat_id="-100777",
        thread_id=None,
    )
    assert agent
    assert agent["id"] == "outreach"


def test_resolve_agent_lane_defaults_to_executive_assistant():
    config = {
        "agent_hub": {
            "default_agent": "executive-assistant",
            "agents": [
                {"id": "executive-assistant", "name": "Executive Assistant", "platforms": ["telegram"]},
                {"id": "admin", "name": "Admin", "platforms": ["telegram"]},
            ],
        }
    }
    agent = resolve_agent_lane_for_source(
        config,
        platform="telegram",
        chat_id="-100111",
        thread_id=None,
    )
    assert agent
    assert agent["id"] == "executive-assistant"


@pytest.mark.asyncio
async def test_telegram_agent_bot_first_message_initializes_lane(tmp_path, monkeypatch):
    from elevate_cli.config import get_env_value
    from gateway.config import PlatformConfig
    from gateway.platforms.telegram import TelegramAdapter

    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    adapter = TelegramAdapter(PlatformConfig())
    bot = _DummyBot()

    initialized = await adapter._maybe_initialize_agent_lane(
        _DummyMessage(thread_id=42),
        "admin",
        "Admin",
        bot,
    )

    assert initialized is True
    assert get_env_value("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL") == "-100123456:42"
    assert bot.sent == [
        {
            "chat_id": -100123456,
            "text": "Admin Telegram connected. Chat target saved.",
            "message_thread_id": 42,
        }
    ]


@pytest.mark.asyncio
async def test_telegram_agent_bot_initialization_does_not_overwrite_existing_lane(tmp_path, monkeypatch):
    from elevate_cli.config import get_env_value, save_env_value
    from gateway.config import PlatformConfig
    from gateway.platforms.telegram import TelegramAdapter

    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    save_env_value("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "existing-chat")
    adapter = TelegramAdapter(PlatformConfig())
    bot = _DummyBot()

    initialized = await adapter._maybe_initialize_agent_lane(
        _DummyMessage(thread_id=42),
        "admin",
        "Admin",
        bot,
    )

    assert initialized is False
    assert get_env_value("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL") == "existing-chat"
    assert bot.sent == []
