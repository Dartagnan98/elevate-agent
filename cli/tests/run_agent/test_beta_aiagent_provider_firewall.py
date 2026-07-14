"""Defense-in-depth provider containment at direct AIAgent construction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import run_agent
from elevate_cli.auth import AuthError
from elevate_cli.beta_provider_policy import (
    BETA_CODEX_BASE_URL,
    BetaProviderPolicyError,
)


def _runtime(home, token: str = "fresh-profile-token", **updates) -> dict:
    receipt = {
        "provider": "openai-codex",
        "requested_provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": BETA_CODEX_BASE_URL,
        "api_key": token,
        "source": "elevate-auth-store",
        "auth_store": str(home / "auth.json"),
    }
    receipt.update(updates)
    return receipt


@pytest.fixture
def beta_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    for name in (
        "ELEVATE_INFERENCE_PROVIDER",
        "ELEVATE_MODEL",
        "ELEVATE_CODEX_BASE_URL",
        "OPENAI_BASE_URL",
        "OPENROUTER_BASE_URL",
        "CUSTOM_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n",
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text("{}\n", encoding="utf-8")

    created: list[dict] = []

    def fake_openai(**kwargs):
        created.append(dict(kwargs))
        return MagicMock(
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )

    monkeypatch.setattr(run_agent, "OpenAI", fake_openai)
    monkeypatch.setattr(run_agent, "get_tool_definitions", lambda **_kwargs: [])
    monkeypatch.setattr(run_agent, "check_toolset_requirements", lambda: {})
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: _runtime(tmp_path),
    )

    def build(**kwargs):
        defaults = {
            "model": "gpt-5.5",
            "quiet_mode": True,
            "skip_context_files": True,
            "skip_memory": True,
            "persist_session": False,
        }
        defaults.update(kwargs)
        return run_agent.AIAgent(**defaults)

    return SimpleNamespace(home=tmp_path, created=created, build=build)


def test_direct_beta_constructor_uses_fresh_receipt_before_side_effects(
    beta_agent, monkeypatch
):
    events: list[str] = []

    def resolve(**kwargs):
        events.append("resolve")
        assert kwargs == {"requested": "openai-codex", "target_model": "gpt-5.5"}
        return _runtime(beta_agent.home)

    def install_stdio():
        events.append("stdio")

    def fake_openai(**kwargs):
        events.append("client")
        beta_agent.created.append(dict(kwargs))
        return MagicMock(api_key=kwargs["api_key"], base_url=kwargs["base_url"])

    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    monkeypatch.setattr(run_agent, "_install_safe_stdio", install_stdio)
    monkeypatch.setattr(run_agent, "OpenAI", fake_openai)

    agent = beta_agent.build(
        provider="auto",
        api_key="fresh-profile-token",
        base_url=f"{BETA_CODEX_BASE_URL}/",
        api_mode="codex_responses",
        request_overrides={"service_tier": "priority"},
    )

    assert events[:3] == ["resolve", "stdio", "client"]
    assert agent.provider == "openai-codex"
    assert agent.model == "gpt-5.5"
    assert agent.api_mode == "codex_responses"
    assert agent.api_key == "fresh-profile-token"
    assert agent.base_url == BETA_CODEX_BASE_URL
    assert agent.request_overrides == {"service_tier": "priority"}
    assert agent._credential_pool is None
    assert agent._fallback_chain == []
    assert beta_agent.created[0]["api_key"] == "fresh-profile-token"
    assert beta_agent.created[0]["base_url"] == BETA_CODEX_BASE_URL


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"provider": "openrouter"}, "beta_provider_not_allowed"),
        ({"model": "anthropic/claude-opus-4.6"}, "beta_model_not_allowed"),
        ({"base_url": "https://openrouter.ai/api/v1"}, "beta_custom_endpoint_not_allowed"),
        ({"api_mode": "chat_completions"}, "beta_api_mode_not_allowed"),
        ({"command": "copilot"}, "beta_external_process_not_allowed"),
        ({"args": ["--acp"]}, "beta_external_process_not_allowed"),
        ({"credential_pool": object()}, "beta_credential_pool_not_allowed"),
        (
            {"fallback_model": {"provider": "openrouter", "model": "evil/model"}},
            "beta_fallback_not_allowed",
        ),
        ({"providers_allowed": ["openrouter"]}, "beta_provider_routing_not_allowed"),
        ({"providers_ignored": ["openai"]}, "beta_provider_routing_not_allowed"),
        ({"providers_order": ["anthropic"]}, "beta_provider_routing_not_allowed"),
        ({"provider_sort": "price"}, "beta_provider_routing_not_allowed"),
        ({"provider_require_parameters": True}, "beta_provider_routing_not_allowed"),
        ({"provider_data_collection": "allow"}, "beta_provider_routing_not_allowed"),
        ({"openrouter_min_coding_score": 0.5}, "beta_provider_routing_not_allowed"),
        ({"request_overrides": {"model": "evil/model"}}, "beta_request_overrides_not_allowed"),
        (
            {"request_overrides": {"provider": {"order": ["openrouter"]}}},
            "beta_request_overrides_not_allowed",
        ),
    ],
)
def test_beta_rejects_alternate_construction_before_any_client(
    beta_agent, monkeypatch, kwargs, code
):
    copilot_client = MagicMock()
    monkeypatch.setattr(
        "agent.copilot_acp_client.CopilotACPClient", copilot_client
    )
    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build(**kwargs)

    assert exc.value.code == code
    copilot_client.assert_not_called()
    assert beta_agent.created == []


def test_beta_direct_copilot_acp_input_cannot_construct_client_or_process(
    beta_agent, monkeypatch
):
    copilot_client = MagicMock()
    popen = MagicMock()
    monkeypatch.setattr(
        "agent.copilot_acp_client.CopilotACPClient", copilot_client
    )
    monkeypatch.setattr("agent.copilot_acp_client.subprocess.Popen", popen)

    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build(
            provider="copilot-acp",
            api_key="copilot-token",
            base_url="acp://copilot",
            command="copilot",
            args=["--acp", "--stdio"],
        )

    assert exc.value.code == "beta_provider_not_allowed"
    copilot_client.assert_not_called()
    popen.assert_not_called()
    assert beta_agent.created == []


@pytest.mark.parametrize(
    "config,code",
    [
        (
            "model:\n  provider: anthropic\n  default: gpt-5.5\n",
            "beta_provider_not_allowed",
        ),
        (
            "model:\n  provider: openai-codex\n  default: evil/model\n",
            "beta_model_not_allowed",
        ),
        (
            "model:\n  provider: openai-codex\n  default: gpt-5.5\n"
            "  base_url: https://openrouter.ai/api/v1\n",
            "beta_custom_endpoint_not_allowed",
        ),
        (
            "model:\n  provider: openai-codex\n  default: gpt-5.5\n"
            "fallback_model:\n  provider: anthropic\n  model: claude\n",
            "beta_fallback_not_allowed",
        ),
    ],
)
def test_beta_rejects_hostile_raw_config_before_runtime_resolution(
    beta_agent, monkeypatch, config, code
):
    beta_agent.home.joinpath("config.yaml").write_text(config, encoding="utf-8")
    resolver = MagicMock(return_value=_runtime(beta_agent.home))
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolver
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build()

    assert exc.value.code == code
    resolver.assert_not_called()
    assert beta_agent.created == []


@pytest.mark.parametrize(
    "name,value,code",
    [
        ("ELEVATE_INFERENCE_PROVIDER", "anthropic", "beta_provider_not_allowed"),
        ("ELEVATE_MODEL", "evil/model", "beta_model_not_allowed"),
        ("ELEVATE_CODEX_BASE_URL", "https://evil.test/v1", "beta_custom_endpoint_not_allowed"),
        ("OPENAI_BASE_URL", "https://evil.test/v1", "beta_custom_endpoint_not_allowed"),
        ("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1", "beta_custom_endpoint_not_allowed"),
        ("CUSTOM_BASE_URL", "http://localhost:9000/v1", "beta_custom_endpoint_not_allowed"),
    ],
)
def test_beta_rejects_hostile_environment_before_runtime_resolution(
    beta_agent, monkeypatch, name, value, code
):
    monkeypatch.setenv(name, value)
    resolver = MagicMock(return_value=_runtime(beta_agent.home))
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolver
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build()

    assert exc.value.code == code
    resolver.assert_not_called()
    assert beta_agent.created == []


def test_beta_rejects_stale_caller_token_after_fresh_resolution(
    beta_agent, monkeypatch
):
    resolver = MagicMock(return_value=_runtime(beta_agent.home, token="rotated-token"))
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolver
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build(api_key="stale-token")

    assert exc.value.code == "beta_explicit_credentials_not_allowed"
    resolver.assert_called_once()
    assert beta_agent.created == []


def test_beta_final_auth_loss_never_reaches_stdio_or_client(beta_agent, monkeypatch):
    events: list[str] = []

    def lost_auth(**_kwargs):
        events.append("resolve")
        raise AuthError("auth disappeared")

    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", lost_auth
    )
    monkeypatch.setattr(
        run_agent, "_install_safe_stdio", lambda: events.append("stdio")
    )

    with pytest.raises(AuthError, match="auth disappeared"):
        beta_agent.build()

    assert events == ["resolve"]
    assert beta_agent.created == []


@pytest.mark.parametrize(
    "updates",
    [
        {"provider": "openrouter"},
        {"requested_provider": "auto"},
        {"api_mode": "chat_completions"},
        {"base_url": "https://openrouter.ai/api/v1"},
        {"source": "credential-pool"},
        {"auth_store": "/tmp/another-profile/auth.json"},
        {"api_key": ""},
        {"credential_pool": object()},
        {"fallback_model": {}},
        {"command": "copilot"},
        {"request_overrides": {}},
    ],
)
def test_beta_rejects_malformed_fresh_runtime_receipt(
    beta_agent, monkeypatch, updates
):
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: _runtime(beta_agent.home, **updates),
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build()

    assert exc.value.code == "beta_codex_runtime_not_local"
    assert beta_agent.created == []


def test_beta_rejects_non_mapping_runtime_receipt(beta_agent, monkeypatch):
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: None,
    )

    with pytest.raises(BetaProviderPolicyError) as exc:
        beta_agent.build()

    assert exc.value.code == "beta_codex_runtime_not_local"
    assert beta_agent.created == []


@pytest.mark.parametrize("channel", ["stable", "Beta", "BETA", "beta "])
def test_non_exact_beta_channels_preserve_legacy_constructor(
    beta_agent, monkeypatch, channel
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", channel)
    pool = object()
    fallback = {"provider": "anthropic", "model": "claude-sonnet"}

    agent = beta_agent.build(
        provider="openrouter",
        model="openrouter/test-model",
        api_key="legacy-key",
        base_url="https://openrouter.ai/api/v1",
        api_mode="chat_completions",
        credential_pool=pool,
        fallback_model=fallback,
        providers_allowed=["provider-a"],
        request_overrides={"model": "legacy-override"},
    )

    assert agent.provider == "openrouter"
    assert agent.model == "openrouter/test-model"
    assert agent.api_key == "legacy-key"
    assert agent._credential_pool is pool
    assert agent._fallback_model == fallback
    assert agent.providers_allowed == ["provider-a"]
    assert agent.request_overrides == {"model": "legacy-override"}
