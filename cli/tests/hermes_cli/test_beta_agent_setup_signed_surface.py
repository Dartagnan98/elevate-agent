"""Exact Realtor Beta setup is limited to signed-pack capabilities."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli import config as config_module
from elevate_cli.beta_provider_policy import BetaProviderPolicyError
from elevate_cli.data import agent_setup as agent_setup_data
from elevate_cli.web_routes import admin_setup


class _NoPrimaryConnection:
    def execute(self, _query, _params):
        class _Cursor:
            @staticmethod
            def fetchone():
                return None

        return _Cursor()


def _client(monkeypatch, connection):
    import elevate_cli.data as data_module

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(data_module, "connect", connect)
    app = FastAPI()
    app.include_router(admin_setup.create_admin_setup_router(web_actor="test"))
    return TestClient(app), data_module


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (
            {
                "key": "composio_workspace",
                "status": "configured",
                "provider": "composio",
                "value": {"apiKey": "must-not-write"},
            },
            "beta_pack_account_setup_required",
        ),
        (
            {
                "key": "operator_channel_telegram",
                "status": "configured",
                "provider": "telegram",
                "value": {"botToken": "malformed", "chatId": "*"},
            },
            "beta_telegram_setup_route_required",
        ),
        (
            {
                "key": "operator_channel_discord",
                "status": "configured",
                "provider": "discord",
                "value": {"botToken": "must-not-write", "channelId": "all"},
            },
            "beta_channel_not_available",
        ),
        (
            {
                "key": "operator_channel_whatsapp",
                "status": "configured",
                "provider": "whatsapp",
                "value": {"token": "must-not-write", "provider": "meta"},
            },
            "beta_channel_not_available",
        ),
        (
            {
                "key": "operator_channel_slack",
                "status": "configured",
                "provider": "slack",
                "value": {"webhookUrl": "https://hooks.invalid"},
            },
            "beta_channel_not_available",
        ),
        (
            {
                "key": "outbound_discord",
                "status": "configured",
                "provider": "discord",
                "value": {"enabled": True},
            },
            "beta_outbound_channel_not_available",
        ),
        (
            {
                "key": "subagents_pack",
                "status": "configured",
                "provider": "agent_default",
                "value": {"enabled": True, "pack": "agent_default"},
            },
            "beta_signed_agent_roster_required",
        ),
        (
            {
                "key": "agent_channel_routing",
                "status": "configured",
                "provider": "elevate",
                "value": {"agents": {"ads": {"discord": ["all"]}}},
            },
            "beta_signed_agent_roster_required",
        ),
    ],
)
def test_beta_generic_setup_lanes_reject_before_any_writer(
    monkeypatch,
    item,
    code,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    auth_reader = MagicMock(return_value={"logged_in": True})
    env_writer = MagicMock()
    monkeypatch.setattr(admin_setup, "read_beta_codex_auth_status", auth_reader)
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)

    with pytest.raises(BetaProviderPolicyError) as caught:
        admin_setup._preflight_beta_agent_setup_update(
            _NoPrimaryConnection(),
            [deepcopy(item)],
        )

    assert caught.value.code == code
    auth_reader.assert_called_once()
    env_writer.assert_not_called()


def test_beta_agent_setup_route_rejects_unsupported_channel_batch_atomically(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    client, data_module = _client(monkeypatch, _NoPrimaryConnection())
    env_writer = MagicMock()
    setup_writer = MagicMock()
    config_writer = MagicMock()
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)
    monkeypatch.setattr(data_module, "update_agent_setup", setup_writer)
    monkeypatch.setattr(
        admin_setup,
        "_materialize_agent_setup_to_config",
        config_writer,
    )
    monkeypatch.setattr(
        admin_setup,
        "read_beta_codex_auth_status",
        MagicMock(return_value={"logged_in": True}),
    )

    response = client.put(
        "/api/agent/setup",
        json={
            "items": [
                {
                    "key": "operator_channel_discord",
                    "status": "configured",
                    "provider": "discord",
                    "value": {"botToken": "discord", "channelId": "all"},
                },
                {
                    "key": "operator_channel_whatsapp",
                    "status": "configured",
                    "provider": "whatsapp",
                    "value": {
                        "token": "whatsapp",
                        "provider": "meta",
                        "phoneId": "phone",
                    },
                },
                {
                    "key": "operator_channel_slack",
                    "status": "configured",
                    "provider": "slack",
                    "value": {"webhookUrl": "https://hooks.invalid"},
                },
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "beta_channel_not_available"
    env_writer.assert_not_called()
    setup_writer.assert_not_called()
    config_writer.assert_not_called()


def test_beta_empty_generic_placeholders_remain_non_mutating(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        admin_setup,
        "read_beta_codex_auth_status",
        lambda _home: {"logged_in": True},
    )
    monkeypatch.setattr(admin_setup, "load_config", lambda: {})
    env_writer = MagicMock()
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)
    items = [
        {
            "key": "composio_workspace",
            "status": "missing",
            "provider": None,
            "value": {"apiKey": "", "workspace": "", "usesEnvSecret": False},
        },
        {
            "key": "operator_channel_telegram",
            "status": "missing",
            "provider": None,
            "value": {"botToken": "", "chatId": "", "usesEnvSecret": False},
        },
        {
            "key": "operator_channel_discord",
            "status": "missing",
            "provider": None,
            "value": {"botToken": "", "channelId": ""},
        },
        {
            "key": "outbound_discord",
            "status": "skipped",
            "provider": None,
            "value": {"enabled": False},
        },
        {
            "key": "subagents_pack",
            "status": "skipped",
            "provider": None,
            "value": {"enabled": False, "pack": ""},
        },
        {
            "key": "agent_channel_routing",
            "status": "skipped",
            "provider": None,
            "value": {"agents": {}},
        },
    ]

    validated = admin_setup._preflight_beta_agent_setup_update(
        _NoPrimaryConnection(),
        deepcopy(items),
    )
    safe = admin_setup._materialize_agent_setup_secrets(validated)

    assert safe == items
    env_writer.assert_not_called()


def test_beta_runtime_overlay_ignores_ambient_host_capabilities(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-image")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ambient-composio")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "ambient-telegram")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "ambient-discord")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "ambient-channel")
    monkeypatch.setenv("WHATSAPP_TOKEN", "ambient-whatsapp")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "meta")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.invalid")
    monkeypatch.setattr(config_module, "load_env", lambda: {})
    monkeypatch.setattr(config_module, "load_config", lambda: {"model": {}})
    monkeypatch.setattr(
        "elevate_cli.beta_env_policy.enforce_beta_env_store_local",
        lambda: None,
    )
    monkeypatch.setattr(
        "elevate_cli.beta_env_policy.beta_active_pack_env_metadata",
        lambda: {
            "COMPOSIO_API_KEY": {},
            "TELEGRAM_BOT_TOKEN": {},
        },
    )

    overlays = agent_setup_data._detect_runtime_credentials()

    assert "model_image" not in overlays
    assert "composio_workspace" not in overlays
    assert "operator_channel_telegram" not in overlays
    assert "operator_channel_discord" not in overlays
    assert "operator_channel_whatsapp" not in overlays
    assert "operator_channel_slack" not in overlays
    assert "operator_channel_imessage" not in overlays


def test_beta_runtime_overlay_accepts_only_valid_profile_local_telegram(
    monkeypatch,
):
    profile_token = "123456:ABCDEFGHIJKLMNOPQRSTUVWX"
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999999:AMBIENTAMBIENTAMBIENT99")
    monkeypatch.setattr(
        config_module,
        "load_env",
        lambda: {
            "TELEGRAM_BOT_TOKEN": profile_token,
            "TELEGRAM_HOME_CHANNEL": "123456",
        },
    )
    monkeypatch.setattr(config_module, "load_config", lambda: {"model": {}})
    monkeypatch.setattr(
        "elevate_cli.beta_env_policy.enforce_beta_env_store_local",
        lambda: None,
    )
    monkeypatch.setattr(
        "elevate_cli.beta_env_policy.beta_active_pack_env_metadata",
        lambda: {
            "TELEGRAM_BOT_TOKEN": {},
            "TELEGRAM_HOME_CHANNEL": {},
        },
    )

    overlays = agent_setup_data._detect_runtime_credentials()

    telegram = overlays["operator_channel_telegram"]
    assert telegram["status"] == "configured"
    assert telegram["value"]["secretPreview"] == "…UVWX"
    assert telegram["value"]["homeChannel"] == "123456"
    assert "AMBIENT" not in repr(telegram)


def test_beta_runtime_overlay_does_not_mark_malformed_profile_token_configured(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        config_module,
        "load_env",
        lambda: {"TELEGRAM_BOT_TOKEN": "malformed"},
    )
    monkeypatch.setattr(config_module, "load_config", lambda: {"model": {}})
    monkeypatch.setattr(
        "elevate_cli.beta_env_policy.enforce_beta_env_store_local",
        lambda: None,
    )
    monkeypatch.setattr(
        "elevate_cli.beta_env_policy.beta_active_pack_env_metadata",
        lambda: {"TELEGRAM_BOT_TOKEN": {}},
    )

    overlays = agent_setup_data._detect_runtime_credentials()

    assert "operator_channel_telegram" not in overlays


@pytest.mark.parametrize(
    ("key", "expected_status", "blocked_reason"),
    [
        ("model_image", "skipped", "signed_realtor_pack_only"),
        ("operator_channel_discord", "skipped", "unsupported_beta_channel"),
        ("outbound_discord", "skipped", None),
        ("subagents_pack", "skipped", None),
        ("agent_channel_routing", "skipped", None),
    ],
)
def test_beta_overlay_repairs_stale_client_authored_capability_status(
    monkeypatch,
    key,
    expected_status,
    blocked_reason,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = {
        "key": key,
        "status": "configured",
        "provider": "hostile",
        "value": {"enabled": True, "apiKey": "must-not-surface"},
    }

    repaired = agent_setup_data._apply_runtime_overlay(stale, {})

    assert repaired["status"] == expected_status
    assert repaired["provider"] is None
    assert "must-not-surface" not in repr(repaired)
    if blocked_reason:
        assert repaired["value"]["blockedReason"] == blocked_reason
