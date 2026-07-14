"""Fail-closed Realtor Beta coverage for gateway model switching."""

from __future__ import annotations

import copy
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

import elevate_cli.model_switch as model_switch
from elevate_cli.auth import DEFAULT_CODEX_BASE_URL
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS,
    BetaProviderPolicyError,
)
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType, SendResult
from gateway.platforms.telegram import TelegramAdapter
from gateway.run import GatewayRunner
from gateway.session import SessionSource
import gateway.run as gateway_run


_BETA_ENV_KEYS = (
    "ELEVATE_INFERENCE_PROVIDER",
    "ELEVATE_MODEL",
    "ELEVATE_CODEX_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
)


class _FakeAgent:
    def __init__(
        self,
        *,
        provider: str = "openai-codex",
        model: str = "gpt-5.4",
        api_key: str = "cached-evil-key",
        base_url: str = "https://cached.attacker.invalid/v1",
        api_mode: str = "anthropic_messages",
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.api_mode = api_mode
        self.switch_calls: list[dict] = []

    def switch_model(self, **kwargs) -> None:
        self.switch_calls.append(dict(kwargs))
        self.model = kwargs["new_model"]
        self.provider = kwargs["new_provider"]
        self.api_key = kwargs["api_key"]
        self.base_url = kwargs["base_url"]
        self.api_mode = kwargs["api_mode"]


def _event(text: str = "/model gpt-5.5") -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="12345",
            chat_type="dm",
        ),
    )


def _runner(*, event: MessageEvent, agent: _FakeAgent | None = None) -> GatewayRunner:
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner.config = None
    runner.session_store = None
    runner._voice_mode = {}
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._evict_cached_agent = MagicMock()
    runner._source_delivery_metadata = lambda _source: None
    if agent is not None:
        session_key = runner._session_key_for_source(event.source)
        runner._agent_cache[session_key] = (agent, 0.0)
    return runner


def _write_config(home, *, provider: str = "openai-codex") -> bytes:
    payload = {
        "model": {
            "default": "gpt-5.4",
            "provider": provider,
            "base_url": "https://config.attacker.invalid/v1",
            "api_key": "config-evil-key",
            "api_mode": "anthropic_messages",
        },
        "providers": {
            "hostile": {
                "base_url": "https://provider.attacker.invalid/v1",
                "api_key": "provider-evil-key",
            }
        },
        "custom_providers": [
            {
                "name": "Hostile",
                "base_url": "https://custom.attacker.invalid/v1",
                "api_key": "custom-evil-key",
            }
        ],
    }
    config_path = home / "config.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return config_path.read_bytes()


def _write_auth(home, *, access_token: str = "beta-local-access") -> bytes:
    payload = {
        "version": 1,
        "providers": {
            "openai-codex": {
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": "beta-local-refresh",
                }
            }
        },
    }
    auth_path = home / "auth.json"
    auth_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return auth_path.read_bytes()


def _switch_result(
    *,
    model: str = "gpt-5.5",
    provider: str = "openai-codex",
    api_key: str = "result-evil-key",
    base_url: str = "https://result.attacker.invalid/v1",
    api_mode: str = "anthropic_messages",
):
    return SimpleNamespace(
        success=True,
        error_message="",
        new_model=model,
        target_provider=provider,
        api_key=api_key,
        base_url=base_url,
        api_mode=api_mode,
        provider_label="Hostile Result Label",
        model_info=None,
        warning_message="",
    )


def _state_snapshot(runner: GatewayRunner, home, agent: _FakeAgent | None) -> dict:
    cache_items = {
        key: tuple(id(value) for value in entry)
        for key, entry in runner._agent_cache.items()
    }
    return {
        "config": (home / "config.yaml").read_bytes()
        if (home / "config.yaml").exists()
        else None,
        "auth": (home / "auth.json").read_bytes()
        if (home / "auth.json").exists()
        else None,
        "overrides": copy.deepcopy(runner._session_model_overrides),
        "notes": copy.deepcopy(runner._pending_model_notes),
        "cache_id": id(runner._agent_cache),
        "cache_items": cache_items,
        "agent": copy.deepcopy(vars(agent)) if agent is not None else None,
        "environment": dict(os.environ),
    }


@pytest.fixture
def beta_home(tmp_path, monkeypatch):
    home = tmp_path / "beta-home"
    home.mkdir()
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    for key in _BETA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(gateway_run, "_elevate_home", home)
    return home


@pytest.mark.asyncio
async def test_beta_direct_model_switch_requires_current_home_auth_without_mutation(
    beta_home, monkeypatch
):
    config_before = _write_config(beta_home)
    event = _event("/model gpt-5.5 --global")
    agent = _FakeAgent()
    runner = _runner(event=event, agent=agent)
    switch = MagicMock(side_effect=AssertionError("generic switch must not run"))
    monkeypatch.setattr(model_switch, "switch_model", switch)
    before = _state_snapshot(runner, beta_home, agent)

    response = await runner._handle_model_command(event)

    assert "[beta_codex_auth_required]" in response
    assert _state_snapshot(runner, beta_home, agent) == before
    assert (beta_home / "config.yaml").read_bytes() == config_before
    switch.assert_not_called()
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_source",
    ["config", "environment", "session", "cached-agent"],
)
async def test_beta_rejects_hostile_provider_state_before_any_mutation(
    beta_home, monkeypatch, hostile_source
):
    config_provider = "anthropic" if hostile_source == "config" else "openai-codex"
    _write_config(beta_home, provider=config_provider)
    _write_auth(beta_home)
    event = _event()
    agent = _FakeAgent(
        provider="anthropic" if hostile_source == "cached-agent" else "openai-codex"
    )
    runner = _runner(event=event, agent=agent)
    session_key = runner._session_key_for_source(event.source)
    if hostile_source == "environment":
        monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "anthropic")
    if hostile_source == "session":
        runner._session_model_overrides[session_key] = {
            "model": "gpt-5.4",
            "provider": "anthropic",
            "api_key": "session-evil-key",
            "base_url": "https://session.attacker.invalid/v1",
            "api_mode": "anthropic_messages",
        }
    switch = MagicMock(side_effect=AssertionError("generic switch must not run"))
    monkeypatch.setattr(model_switch, "switch_model", switch)
    before = _state_snapshot(runner, beta_home, agent)

    response = await runner._handle_model_command(event)

    assert "[beta_provider_not_allowed]" in response
    assert _state_snapshot(runner, beta_home, agent) == before
    switch.assert_not_called()
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_source",
    ["request", "config", "environment", "session", "cached-agent"],
)
async def test_beta_rejects_hostile_model_state_before_any_mutation(
    beta_home, monkeypatch, hostile_source
):
    _write_config(beta_home)
    if hostile_source == "config":
        config_path = beta_home / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["model"]["default"] = "claude-hostile"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    _write_auth(beta_home)
    event = _event(
        "/model claude-hostile" if hostile_source == "request" else "/model gpt-5.5"
    )
    agent = _FakeAgent(
        model="claude-hostile" if hostile_source == "cached-agent" else "gpt-5.4"
    )
    runner = _runner(event=event, agent=agent)
    session_key = runner._session_key_for_source(event.source)
    if hostile_source == "environment":
        monkeypatch.setenv("ELEVATE_MODEL", "claude-hostile")
    if hostile_source == "session":
        runner._session_model_overrides[session_key] = {
            "model": "claude-hostile",
            "provider": "openai-codex",
            "api_key": "session-evil-key",
            "base_url": "https://session.attacker.invalid/v1",
            "api_mode": "anthropic_messages",
        }
    switch = MagicMock(side_effect=AssertionError("generic switch must not run"))
    monkeypatch.setattr(model_switch, "switch_model", switch)
    before = _state_snapshot(runner, beta_home, agent)

    response = await runner._handle_model_command(event)

    assert "[beta_model_not_allowed]" in response
    assert _state_snapshot(runner, beta_home, agent) == before
    switch.assert_not_called()
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
async def test_beta_rejects_custom_codex_endpoint_before_any_mutation(
    beta_home, monkeypatch
):
    _write_config(beta_home)
    _write_auth(beta_home)
    monkeypatch.setenv(
        "ELEVATE_CODEX_BASE_URL", "https://codex.attacker.invalid/v1"
    )
    event = _event()
    agent = _FakeAgent()
    runner = _runner(event=event, agent=agent)
    switch = MagicMock(side_effect=AssertionError("generic switch must not run"))
    monkeypatch.setattr(model_switch, "switch_model", switch)
    before = _state_snapshot(runner, beta_home, agent)

    response = await runner._handle_model_command(event)

    assert "[beta_codex_endpoint_not_allowed]" in response
    assert _state_snapshot(runner, beta_home, agent) == before
    switch.assert_not_called()
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
async def test_beta_revalidates_hostile_switch_result_before_global_persistence(
    beta_home, monkeypatch
):
    _write_config(beta_home)
    _write_auth(beta_home)
    event = _event("/model gpt-5.5 --global")
    agent = _FakeAgent()
    runner = _runner(event=event, agent=agent)
    switch = MagicMock(return_value=_switch_result(provider="anthropic"))
    monkeypatch.setattr(model_switch, "switch_model", switch)
    before = _state_snapshot(runner, beta_home, agent)

    response = await runner._handle_model_command(event)

    assert "[beta_provider_not_allowed]" in response
    assert _state_snapshot(runner, beta_home, agent) == before
    switch.assert_called_once()
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
async def test_beta_ignores_cached_session_config_and_result_credentials(
    beta_home, monkeypatch
):
    config_before = _write_config(beta_home)
    _write_auth(beta_home)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-evil-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.attacker.invalid/v1")
    event = _event()
    agent = _FakeAgent()
    runner = _runner(event=event, agent=agent)
    session_key = runner._session_key_for_source(event.source)
    runner._session_model_overrides[session_key] = {
        "model": "gpt-5.4",
        "provider": "openai-codex",
        "api_key": "session-evil-key",
        "base_url": "https://session.attacker.invalid/v1",
        "api_mode": "anthropic_messages",
    }
    calls: list[dict] = []

    def fake_switch_model(**kwargs):
        calls.append(dict(kwargs))
        return _switch_result()

    monkeypatch.setattr(model_switch, "switch_model", fake_switch_model)
    environment_before = dict(os.environ)

    response = await runner._handle_model_command(event)

    assert calls == [
        {
            "raw_input": "gpt-5.5",
            "current_provider": "openai-codex",
            "current_model": "gpt-5.4",
            "current_base_url": DEFAULT_CODEX_BASE_URL,
            "current_api_key": "beta-local-access",
            "is_global": False,
            "explicit_provider": "openai-codex",
            "user_providers": None,
            "custom_providers": None,
        }
    ]
    assert agent.switch_calls == [
        {
            "new_model": "gpt-5.5",
            "new_provider": "openai-codex",
            "api_key": "beta-local-access",
            "base_url": DEFAULT_CODEX_BASE_URL,
            "api_mode": "codex_responses",
        }
    ]
    assert runner._session_model_overrides[session_key] == {
        "model": "gpt-5.5",
        "provider": "openai-codex",
        "api_key": "beta-local-access",
        "base_url": DEFAULT_CODEX_BASE_URL,
        "api_mode": "codex_responses",
    }
    assert (beta_home / "config.yaml").read_bytes() == config_before
    assert dict(os.environ) == environment_before
    runner._evict_cached_agent.assert_called_once_with(session_key)
    assert "Model switched to `gpt-5.5`" in response
    assert "Provider: OpenAI Codex" in response
    assert "attacker" not in response.lower()
    assert "Hostile Result Label" not in response


@pytest.mark.asyncio
async def test_beta_picker_exposes_only_codex_and_rejects_hostile_callback(
    beta_home, monkeypatch
):
    _write_config(beta_home)
    _write_auth(beta_home)
    event = _event("/model")
    agent = _FakeAgent()
    runner = _runner(event=event, agent=agent)
    captured: dict = {}

    class _PickerAdapter:
        async def send_model_picker(self, **kwargs):
            captured.update(kwargs)
            return SendResult(success=True, message_id="picker-1")

    runner.adapters[Platform.TELEGRAM] = _PickerAdapter()
    switch = MagicMock(side_effect=AssertionError("generic switch must not run"))
    monkeypatch.setattr(model_switch, "switch_model", switch)

    response = await runner._handle_model_command(event)

    assert response is None
    assert captured["providers"] == [
        {
            "slug": "openai-codex",
            "name": "OpenAI Codex",
            "models": list(BETA_ALLOWED_MODELS),
            "total_models": len(BETA_ALLOWED_MODELS),
            "is_current": True,
        }
    ]
    before = _state_snapshot(runner, beta_home, agent)
    with pytest.raises(BetaProviderPolicyError) as exc:
        await captured["on_model_selected"](
            "12345", "gpt-5.5", "anthropic"
        )
    assert exc.value.code == "beta_provider_not_allowed"
    assert _state_snapshot(runner, beta_home, agent) == before
    switch.assert_not_called()
    runner._evict_cached_agent.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_beta_picker_failure_is_typed_and_preserves_state_identity(
    beta_home,
):
    adapter = object.__new__(TelegramAdapter)

    async def blocked_callback(_chat_id, _model_id, _provider_slug):
        raise BetaProviderPolicyError(
            "OpenAI Codex auth is missing.",
            code="beta_codex_auth_required",
        )

    state = {
        "providers": [],
        "model_list": ["gpt-5.5"],
        "selected_provider": "openai-codex",
        "on_model_selected": blocked_callback,
    }
    adapter._model_picker_state = {"12345": state}
    before = copy.deepcopy(state)
    query = SimpleNamespace(
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    await adapter._handle_model_picker_callback(query, "mm:0", "12345")

    assert adapter._model_picker_state["12345"] is state
    assert state == before
    edit = query.edit_message_text.await_args.kwargs
    assert "[beta_codex_auth_required]" in edit["text"]
    query.answer.assert_awaited_once_with(
        text="Model switch blocked [beta_codex_auth_required]."
    )


@pytest.mark.asyncio
async def test_telegram_non_exact_beta_keeps_stable_failure_cleanup(
    beta_home, monkeypatch
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    adapter = object.__new__(TelegramAdapter)

    async def stable_failure(_chat_id, _model_id, _provider_slug):
        raise ValueError("stable boom")

    state = {
        "providers": [],
        "model_list": ["stable-model"],
        "selected_provider": "stable-provider",
        "on_model_selected": stable_failure,
    }
    adapter._model_picker_state = {"12345": state}
    query = SimpleNamespace(
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    await adapter._handle_model_picker_callback(query, "mm:0", "12345")

    assert "12345" not in adapter._model_picker_state
    assert query.edit_message_text.await_args.kwargs["text"] == (
        "Error switching model: stable boom"
    )
    query.answer.assert_awaited_once_with(text="Model switched!")


@pytest.mark.asyncio
async def test_non_exact_beta_channel_keeps_stable_model_switch_behavior(
    beta_home, monkeypatch
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    _write_config(beta_home, provider="anthropic")
    event = _event("/model claude-sonnet-4")
    agent = _FakeAgent(provider="anthropic", model="claude-sonnet-3")
    runner = _runner(event=event, agent=agent)
    stable_result = _switch_result(
        model="claude-sonnet-4",
        provider="anthropic",
        api_key="stable-key",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
    )
    monkeypatch.setattr(
        model_switch, "switch_model", MagicMock(return_value=stable_result)
    )

    response = await runner._handle_model_command(event)

    session_key = runner._session_key_for_source(event.source)
    assert "Model switched to `claude-sonnet-4`" in response
    assert runner._session_model_overrides[session_key]["provider"] == "anthropic"
    assert agent.switch_calls[0]["api_key"] == "stable-key"
    runner._evict_cached_agent.assert_called_once_with(session_key)
