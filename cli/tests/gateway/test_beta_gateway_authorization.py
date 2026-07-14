"""Exact-Beta remote gateway authorization fails closed."""

from types import SimpleNamespace

import pytest

from gateway.run import GatewayRunner
from gateway.session import Platform, SessionSource


@pytest.fixture(autouse=True)
def _beta_auth_env(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    for name in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "DISCORD_ALLOWED_USERS",
        "DISCORD_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(name, raising=False)


def _runner(*, paired: bool = False):
    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(is_approved=lambda *_args, **_kwargs: paired)
    return runner


def _source(
    platform: Platform = Platform.TELEGRAM,
    user_id: str = "123456789",
    *,
    agent_id: str = "executive-assistant",
):
    return SessionSource(
        platform=platform,
        chat_id="chat",
        user_id=user_id,
        agent_id=agent_id,
    )


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("TELEGRAM_ALLOWED_USERS", "*"),
        ("TELEGRAM_ALLOW_ALL_USERS", "true"),
        ("GATEWAY_ALLOWED_USERS", "*"),
        ("GATEWAY_ALLOW_ALL_USERS", "yes"),
    ],
)
def test_beta_rejects_wildcard_and_allow_all_escapes(monkeypatch, env_name, env_value):
    monkeypatch.setenv(env_name, env_value)

    assert _runner()._is_user_authorized(_source()) is False


def test_beta_accepts_explicit_numeric_telegram_caller(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "*, 123456789, not-a-user")

    assert _runner()._is_user_authorized(_source()) is True


def test_beta_accepts_agent_scoped_pairing():
    calls = []
    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(
        is_approved=lambda *args: calls.append(args) or True
    )

    assert runner._is_user_authorized(_source()) is True
    assert calls == [("telegram", "123456789", "executive-assistant")]


def test_beta_rejects_nonnumeric_telegram_identity_before_pairing():
    calls = []
    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(
        is_approved=lambda *args: calls.append(args) or True
    )

    assert runner._is_user_authorized(_source(user_id="@semantic-name")) is False
    assert calls == []


@pytest.mark.parametrize(
    "platform",
    [Platform.DISCORD, Platform.SLACK, Platform.WEBHOOK, Platform.HOMEASSISTANT],
)
def test_beta_rejects_unsupported_remote_platforms(monkeypatch, platform):
    monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
    monkeypatch.setenv("DISCORD_ALLOW_ALL_USERS", "true")

    assert _runner(paired=True)._is_user_authorized(_source(platform)) is False


def test_stable_keeps_legacy_wildcard_compatibility(monkeypatch):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "*")

    assert _runner()._is_user_authorized(_source()) is True
