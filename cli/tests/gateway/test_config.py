"""Tests for gateway configuration management."""

import os
from unittest.mock import patch

from gateway.config import (
    GatewayConfig,
    HomeChannel,
    Platform,
    PlatformConfig,
    SessionResetPolicy,
    _apply_env_overrides,
    _filter_beta_supported_platforms,
    load_gateway_config,
)


class TestHomeChannelRoundtrip:
    def test_to_dict_from_dict(self):
        hc = HomeChannel(platform=Platform.DISCORD, chat_id="999", name="general")
        d = hc.to_dict()
        restored = HomeChannel.from_dict(d)

        assert restored.platform == Platform.DISCORD
        assert restored.chat_id == "999"
        assert restored.name == "general"


class TestPlatformConfigRoundtrip:
    def test_to_dict_from_dict(self):
        pc = PlatformConfig(
            enabled=True,
            token="tok_123",
            home_channel=HomeChannel(
                platform=Platform.TELEGRAM,
                chat_id="555",
                name="Home",
            ),
            extra={"foo": "bar"},
        )
        d = pc.to_dict()
        restored = PlatformConfig.from_dict(d)

        assert restored.enabled is True
        assert restored.token == "tok_123"
        assert restored.home_channel.chat_id == "555"
        assert restored.extra == {"foo": "bar"}

    def test_disabled_no_token(self):
        pc = PlatformConfig()
        d = pc.to_dict()
        restored = PlatformConfig.from_dict(d)
        assert restored.enabled is False
        assert restored.token is None


class TestGetConnectedPlatforms:
    def test_returns_enabled_with_token(self):
        config = GatewayConfig(
            platforms={
                Platform.TELEGRAM: PlatformConfig(enabled=True, token="t"),
                Platform.DISCORD: PlatformConfig(enabled=False, token="d"),
                Platform.SLACK: PlatformConfig(enabled=True),  # no token
            },
        )
        connected = config.get_connected_platforms()
        assert Platform.TELEGRAM in connected
        assert Platform.DISCORD not in connected
        assert Platform.SLACK not in connected

    def test_empty_platforms(self):
        config = GatewayConfig()
        assert config.get_connected_platforms() == []

    def test_telegram_agent_bots_from_dynamic_env_enable_platform(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_AGENT_LISTING_MARKETING_TELEGRAM_BOT_TOKEN", "agent-token")
        config = GatewayConfig()

        _apply_env_overrides(config)

        telegram = config.platforms[Platform.TELEGRAM]
        assert telegram.enabled is True
        assert telegram.extra["agent_bots"]["listing-marketing"]["token"] == "agent-token"
        assert telegram.extra["agent_bots"]["listing-marketing"]["token_env"] == (
            "ELEVATE_AGENT_LISTING_MARKETING_TELEGRAM_BOT_TOKEN"
        )

    def test_telegram_agent_bots_from_saved_env_enable_platform(self, monkeypatch):
        monkeypatch.delenv("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setattr(
            "gateway.config._gateway_env_values",
            lambda: {"ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN": "saved-agent-token"},
        )
        config = GatewayConfig()

        _apply_env_overrides(config)

        telegram = config.platforms[Platform.TELEGRAM]
        assert telegram.enabled is True
        assert telegram.extra["agent_bots"]["admin"]["token"] == "saved-agent-token"
        assert telegram.extra["agent_bots"]["admin"]["token_env"] == "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN"

    def test_exact_beta_filters_locked_marketing_and_arbitrary_agent_bots(
        self,
        monkeypatch,
    ):
        from elevate_cli import beta_env_policy

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(
            "gateway.config._gateway_env_values",
            lambda: {
                "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN": "ea-token",
                "ELEVATE_AGENT_MARKETING_TELEGRAM_BOT_TOKEN": "locked-token",
                "ELEVATE_AGENT_ADS_TELEGRAM_BOT_TOKEN": "arbitrary-token",
            },
        )
        monkeypatch.setattr(
            beta_env_policy,
            "beta_active_pack_env_metadata",
            lambda: {
                "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN": {},
            },
        )
        config = GatewayConfig()

        _apply_env_overrides(config)

        telegram = config.platforms[Platform.TELEGRAM]
        assert set(telegram.extra["agent_bots"]) == {"executive-assistant"}
        assert telegram.extra["agent_bots"]["executive-assistant"]["token"] == "ea-token"
        assert "marketing" not in telegram.extra["agent_bots"]
        assert "ads" not in telegram.extra["agent_bots"]

    def test_exact_beta_keeps_agent_bots_for_active_pack_contracts(self, monkeypatch):
        from elevate_cli import beta_env_policy

        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setattr(
            "gateway.config._gateway_env_values",
            lambda: {
                "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN": "admin-token",
                "ELEVATE_AGENT_OUTREACH_TELEGRAM_BOT_TOKEN": "outreach-token",
                "ELEVATE_AGENT_MARKETING_TELEGRAM_BOT_TOKEN": "marketing-token",
                "ELEVATE_AGENT_SOCIAL_MEDIA_TELEGRAM_BOT_TOKEN": "social-token",
            },
        )
        allowed = {
            "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN",
            "ELEVATE_AGENT_OUTREACH_TELEGRAM_BOT_TOKEN",
            "ELEVATE_AGENT_MARKETING_TELEGRAM_BOT_TOKEN",
            "ELEVATE_AGENT_SOCIAL_MEDIA_TELEGRAM_BOT_TOKEN",
        }
        monkeypatch.setattr(
            beta_env_policy,
            "beta_active_pack_env_metadata",
            lambda: {key: {} for key in allowed},
        )
        config = GatewayConfig()

        _apply_env_overrides(config)

        assert set(config.platforms[Platform.TELEGRAM].extra["agent_bots"]) == {
            "admin",
            "outreach",
            "marketing",
            "social-media",
        }

    def test_dingtalk_recognised_via_extras(self):
        config = GatewayConfig(
            platforms={
                Platform.DINGTALK: PlatformConfig(
                    enabled=True,
                    extra={"client_id": "cid", "client_secret": "sec"},
                ),
            },
        )
        assert Platform.DINGTALK in config.get_connected_platforms()

    def test_dingtalk_recognised_via_env_vars(self, monkeypatch):
        """DingTalk configured via env vars (no extras) should still be
        recognised as connected — covers the case where _apply_env_overrides
        hasn't populated extras yet."""
        monkeypatch.setenv("DINGTALK_CLIENT_ID", "env_cid")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "env_sec")
        config = GatewayConfig(
            platforms={
                Platform.DINGTALK: PlatformConfig(enabled=True, extra={}),
            },
        )
        assert Platform.DINGTALK in config.get_connected_platforms()

    def test_dingtalk_missing_creds_not_connected(self, monkeypatch):
        monkeypatch.delenv("DINGTALK_CLIENT_ID", raising=False)
        monkeypatch.delenv("DINGTALK_CLIENT_SECRET", raising=False)
        config = GatewayConfig(
            platforms={
                Platform.DINGTALK: PlatformConfig(enabled=True, extra={}),
            },
        )
        assert Platform.DINGTALK not in config.get_connected_platforms()

    def test_dingtalk_disabled_not_connected(self):
        config = GatewayConfig(
            platforms={
                Platform.DINGTALK: PlatformConfig(
                    enabled=False,
                    extra={"client_id": "cid", "client_secret": "sec"},
                ),
            },
        )
        assert Platform.DINGTALK not in config.get_connected_platforms()


class TestSessionResetPolicy:
    def test_roundtrip(self):
        policy = SessionResetPolicy(mode="idle", at_hour=6, idle_minutes=120)
        d = policy.to_dict()
        restored = SessionResetPolicy.from_dict(d)
        assert restored.mode == "idle"
        assert restored.at_hour == 6
        assert restored.idle_minutes == 120

    def test_defaults(self):
        policy = SessionResetPolicy()
        assert policy.mode == "both"
        assert policy.at_hour == 4
        assert policy.idle_minutes == 1440

    def test_from_dict_treats_null_values_as_defaults(self):
        restored = SessionResetPolicy.from_dict(
            {"mode": None, "at_hour": None, "idle_minutes": None}
        )
        assert restored.mode == "both"
        assert restored.at_hour == 4
        assert restored.idle_minutes == 1440


class TestGatewayConfigRoundtrip:
    def test_full_roundtrip(self):
        config = GatewayConfig(
            platforms={
                Platform.TELEGRAM: PlatformConfig(
                    enabled=True,
                    token="tok_123",
                    home_channel=HomeChannel(Platform.TELEGRAM, "123", "Home"),
                ),
            },
            reset_triggers=["/new"],
            quick_commands={"limits": {"type": "exec", "command": "echo ok"}},
            group_sessions_per_user=False,
            thread_sessions_per_user=True,
        )
        d = config.to_dict()
        restored = GatewayConfig.from_dict(d)

        assert Platform.TELEGRAM in restored.platforms
        assert restored.platforms[Platform.TELEGRAM].token == "tok_123"
        assert restored.reset_triggers == ["/new"]
        assert restored.quick_commands == {"limits": {"type": "exec", "command": "echo ok"}}
        assert restored.group_sessions_per_user is False
        assert restored.thread_sessions_per_user is True

    def test_roundtrip_preserves_unauthorized_dm_behavior(self):
        config = GatewayConfig(
            unauthorized_dm_behavior="ignore",
            platforms={
                Platform.WHATSAPP: PlatformConfig(
                    enabled=True,
                    extra={"unauthorized_dm_behavior": "pair"},
                ),
            },
        )

        restored = GatewayConfig.from_dict(config.to_dict())

        assert restored.unauthorized_dm_behavior == "ignore"
        assert restored.platforms[Platform.WHATSAPP].extra["unauthorized_dm_behavior"] == "pair"


class TestBetaPlatformContainment:
    def test_exact_beta_removes_unsupported_adapters_after_merge(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        config = GatewayConfig(
            platforms={
                Platform.LOCAL: PlatformConfig(enabled=True),
                Platform.TELEGRAM: PlatformConfig(enabled=True, token="telegram-token"),
                Platform.API_SERVER: PlatformConfig(enabled=True),
                Platform.DISCORD: PlatformConfig(enabled=True, token="discord-token"),
                Platform.SLACK: PlatformConfig(enabled=True, token="slack-token"),
                Platform.WEBHOOK: PlatformConfig(enabled=True),
            }
        )

        _filter_beta_supported_platforms(config)

        assert set(config.platforms) == {
            Platform.LOCAL,
            Platform.TELEGRAM,
            Platform.API_SERVER,
        }

    def test_non_exact_channel_keeps_existing_adapter_behavior(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
        config = GatewayConfig(
            platforms={
                Platform.DISCORD: PlatformConfig(enabled=True, token="discord-token"),
                Platform.WEBHOOK: PlatformConfig(enabled=True),
            }
        )

        _filter_beta_supported_platforms(config)

        assert set(config.platforms) == {Platform.DISCORD, Platform.WEBHOOK}

    def test_exact_beta_drops_ambient_unsupported_tokens(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate-beta"
        elevate_home.mkdir()
        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "ambient-discord-token")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "ambient-slack-token")
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")

        config = load_gateway_config()

        assert Platform.DISCORD not in config.platforms
        assert Platform.SLACK not in config.platforms
        assert Platform.WHATSAPP not in config.platforms


class TestLoadGatewayConfig:
    def test_bridges_quick_commands_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "quick_commands:\n"
            "  limits:\n"
            "    type: exec\n"
            "    command: echo ok\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.quick_commands == {"limits": {"type": "exec", "command": "echo ok"}}

    def test_bridges_group_sessions_per_user_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text("group_sessions_per_user: false\n", encoding="utf-8")

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.group_sessions_per_user is False

    def test_bridges_thread_sessions_per_user_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text("thread_sessions_per_user: true\n", encoding="utf-8")

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.thread_sessions_per_user is True

    def test_thread_sessions_per_user_defaults_to_false(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text("{}\n", encoding="utf-8")

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.thread_sessions_per_user is False

    def test_bridges_discord_channel_prompts_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "discord:\n"
            "  channel_prompts:\n"
            "    \"123\": Research mode\n"
            "    456: Therapist mode\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.platforms[Platform.DISCORD].extra["channel_prompts"] == {
            "123": "Research mode",
            "456": "Therapist mode",
        }

    def test_bridges_telegram_channel_prompts_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "telegram:\n"
            "  channel_prompts:\n"
            '    "-1001234567": Research assistant\n'
            "    789: Creative writing\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.platforms[Platform.TELEGRAM].extra["channel_prompts"] == {
            "-1001234567": "Research assistant",
            "789": "Creative writing",
        }

    def test_bridges_slack_channel_prompts_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "slack:\n"
            "  channel_prompts:\n"
            '    "C01ABC": Code review mode\n',
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.platforms[Platform.SLACK].extra["channel_prompts"] == {
            "C01ABC": "Code review mode",
        }

    def test_invalid_quick_commands_in_config_yaml_are_ignored(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text("quick_commands: not-a-mapping\n", encoding="utf-8")

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.quick_commands == {}

    def test_bridges_unauthorized_dm_behavior_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "unauthorized_dm_behavior: ignore\n"
            "whatsapp:\n"
            "  unauthorized_dm_behavior: pair\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.unauthorized_dm_behavior == "ignore"
        assert config.platforms[Platform.WHATSAPP].extra["unauthorized_dm_behavior"] == "pair"

    def test_bridges_telegram_unauthorized_dm_behavior_from_env(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))
        monkeypatch.setenv(
            "TELEGRAM_BOT_TOKEN",
            "123456789:abcdefghijklmnopqrstuvwxyzABCDE",
        )
        monkeypatch.setenv("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", "pair")

        config = load_gateway_config()

        assert config.platforms[Platform.TELEGRAM].extra["unauthorized_dm_behavior"] == "pair"
        assert config.get_unauthorized_dm_behavior(Platform.TELEGRAM) == "pair"

    def test_bridges_telegram_disable_link_previews_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "telegram:\n"
            "  disable_link_previews: true\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))

        config = load_gateway_config()

        assert config.platforms[Platform.TELEGRAM].extra["disable_link_previews"] is True

    def test_bridges_telegram_proxy_url_from_config_yaml(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "telegram:\n"
            "  proxy_url: socks5://127.0.0.1:1080\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))
        monkeypatch.delenv("TELEGRAM_PROXY", raising=False)

        load_gateway_config()

        import os
        assert os.environ.get("TELEGRAM_PROXY") == "socks5://127.0.0.1:1080"

    def test_telegram_proxy_env_takes_precedence_over_config(self, tmp_path, monkeypatch):
        elevate_home = tmp_path / ".elevate"
        elevate_home.mkdir()
        config_path = elevate_home / "config.yaml"
        config_path.write_text(
            "telegram:\n"
            "  proxy_url: http://from-config:8080\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ELEVATE_HOME", str(elevate_home))
        monkeypatch.setenv("TELEGRAM_PROXY", "socks5://from-env:1080")

        load_gateway_config()

        import os
        assert os.environ.get("TELEGRAM_PROXY") == "socks5://from-env:1080"


class TestHomeChannelEnvOverrides:
    """Home channel env vars should apply even when the platform was already
    configured via config.yaml (not just when credential env vars create it)."""

    def test_existing_platform_configs_accept_home_channel_env_overrides(self):
        cases = [
            (
                Platform.SLACK,
                PlatformConfig(enabled=True, token="xoxb-from-config"),
                {"SLACK_HOME_CHANNEL": "C123", "SLACK_HOME_CHANNEL_NAME": "Ops"},
                ("C123", "Ops"),
            ),
            (
                Platform.SIGNAL,
                PlatformConfig(
                    enabled=True,
                    extra={"http_url": "http://localhost:9090", "account": "+15551234567"},
                ),
                {"SIGNAL_HOME_CHANNEL": "+1555000", "SIGNAL_HOME_CHANNEL_NAME": "Phone"},
                ("+1555000", "Phone"),
            ),
            (
                Platform.MATTERMOST,
                PlatformConfig(
                    enabled=True,
                    token="mm-token",
                    extra={"url": "https://mm.example.com"},
                ),
                {"MATTERMOST_HOME_CHANNEL": "ch_abc123", "MATTERMOST_HOME_CHANNEL_NAME": "General"},
                ("ch_abc123", "General"),
            ),
            (
                Platform.MATRIX,
                PlatformConfig(
                    enabled=True,
                    token="syt_abc123",
                    extra={"homeserver": "https://matrix.example.org"},
                ),
                {"MATRIX_HOME_ROOM": "!room123:example.org", "MATRIX_HOME_ROOM_NAME": "Bot Room"},
                ("!room123:example.org", "Bot Room"),
            ),
            (
                Platform.EMAIL,
                PlatformConfig(
                    enabled=True,
                    extra={
                        "address": "elevate@test.com",
                        "imap_host": "imap.test.com",
                        "smtp_host": "smtp.test.com",
                    },
                ),
                {"EMAIL_HOME_ADDRESS": "user@test.com", "EMAIL_HOME_ADDRESS_NAME": "Inbox"},
                ("user@test.com", "Inbox"),
            ),
            (
                Platform.SMS,
                PlatformConfig(enabled=True, api_key="token_abc"),
                {"SMS_HOME_CHANNEL": "+15559876543", "SMS_HOME_CHANNEL_NAME": "My Phone"},
                ("+15559876543", "My Phone"),
            ),
        ]

        for platform, platform_config, env, expected in cases:
            config = GatewayConfig(platforms={platform: platform_config})
            with patch.dict(os.environ, env, clear=True):
                _apply_env_overrides(config)

            home = config.platforms[platform].home_channel
            assert home is not None, f"{platform.value}: home_channel should not be None"
            assert (home.chat_id, home.name) == expected, platform.value
