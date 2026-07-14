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


def _switch_state(agent) -> tuple:
    compressor = getattr(agent, "context_compressor", None)
    return (
        agent.model,
        agent.provider,
        agent.base_url,
        agent.api_mode,
        agent.api_key,
        agent.client,
        dict(agent._client_kwargs),
        dict(agent._primary_runtime),
        list(agent._fallback_chain),
        agent._fallback_model,
        agent._credential_pool,
        dict(getattr(agent, "_transport_cache", {})),
        getattr(compressor, "model", None),
        getattr(compressor, "base_url", None),
        getattr(compressor, "api_key", None),
        getattr(compressor, "provider", None),
        getattr(compressor, "api_mode", None),
        getattr(compressor, "context_length", None),
        getattr(compressor, "threshold_tokens", None),
        getattr(agent, "_anthropic_client", None),
        getattr(agent, "_anthropic_api_key", None),
        getattr(agent, "_anthropic_base_url", None),
        getattr(agent, "_is_anthropic_oauth", None),
        getattr(agent, "_bedrock_region", None),
        getattr(agent, "acp_command", None),
        list(getattr(agent, "acp_args", []) or []),
    )


def test_beta_switch_freshly_resolves_current_profile_before_client(
    beta_agent, monkeypatch
):
    agent = beta_agent.build()
    old_client = agent.client
    beta_agent.created.clear()
    events: list[str] = []

    def resolve(**kwargs):
        events.append("resolve")
        assert kwargs == {
            "requested": "openai-codex",
            "target_model": "gpt-5.4",
        }
        return _runtime(beta_agent.home, token="rotated-profile-token")

    new_client = MagicMock()

    def openai(**kwargs):
        events.append("client")
        beta_agent.created.append(dict(kwargs))
        return new_client

    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolve
    )
    monkeypatch.setattr(run_agent, "OpenAI", openai)
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length", lambda *_args, **_kwargs: 200_000
    )

    agent.switch_model(
        "gpt-5.4",
        "openai-codex",
        base_url=BETA_CODEX_BASE_URL,
        api_mode="codex_responses",
    )

    assert events == ["resolve", "client"]
    assert agent.model == "gpt-5.4"
    assert agent.provider == "openai-codex"
    assert agent.base_url == BETA_CODEX_BASE_URL
    assert agent.api_mode == "codex_responses"
    assert agent.api_key == "rotated-profile-token"
    assert agent.client is new_client
    assert agent._client_kwargs["api_key"] == "rotated-profile-token"
    assert agent._client_kwargs["base_url"] == BETA_CODEX_BASE_URL
    assert agent._fallback_chain == []
    assert agent._fallback_model is None
    assert agent._anthropic_client is None
    assert agent._anthropic_api_key == ""
    assert agent._anthropic_base_url == ""
    assert agent._is_anthropic_oauth is False
    assert agent.acp_command is None
    assert agent.acp_args == []
    old_client.close.assert_called_once_with()


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"new_provider": "copilot-acp"}, "beta_provider_not_allowed"),
        ({"new_model": "evil/model"}, "beta_model_not_allowed"),
        (
            {"base_url": "https://openrouter.ai/api/v1"},
            "beta_custom_endpoint_not_allowed",
        ),
        ({"api_mode": "anthropic_messages"}, "beta_api_mode_not_allowed"),
        ({"api_key": "foreign-token"}, "beta_explicit_credentials_not_allowed"),
    ],
)
def test_beta_switch_rejects_hostile_arguments_without_mutation_or_client(
    beta_agent, monkeypatch, kwargs, code
):
    agent = beta_agent.build()
    old_client = agent.client
    before = _switch_state(agent)
    openai = MagicMock()
    anthropic = MagicMock()
    copilot = MagicMock()
    popen = MagicMock()
    monkeypatch.setattr(run_agent, "OpenAI", openai)
    monkeypatch.setattr("agent.anthropic_adapter.build_anthropic_client", anthropic)
    monkeypatch.setattr("agent.copilot_acp_client.CopilotACPClient", copilot)
    monkeypatch.setattr("agent.copilot_acp_client.subprocess.Popen", popen)

    switch_kwargs = {
        "new_model": "gpt-5.5",
        "new_provider": "openai-codex",
        "base_url": BETA_CODEX_BASE_URL,
        "api_mode": "codex_responses",
    }
    switch_kwargs.update(kwargs)
    with pytest.raises(BetaProviderPolicyError) as exc:
        agent.switch_model(**switch_kwargs)

    assert exc.value.code == code
    assert _switch_state(agent) == before
    openai.assert_not_called()
    anthropic.assert_not_called()
    copilot.assert_not_called()
    popen.assert_not_called()
    old_client.close.assert_not_called()


@pytest.mark.parametrize(
    "attribute,value,code",
    [
        ("acp_command", "copilot", "beta_external_process_not_allowed"),
        ("_credential_pool", object(), "beta_credential_pool_not_allowed"),
        (
            "_fallback_chain",
            [{"provider": "anthropic", "model": "claude"}],
            "beta_fallback_not_allowed",
        ),
        ("providers_order", ["openrouter"], "beta_provider_routing_not_allowed"),
        (
            "request_overrides",
            {"provider": {"order": ["openrouter"]}},
            "beta_request_overrides_not_allowed",
        ),
        ("provider", "copilot-acp", "beta_provider_not_allowed"),
        ("base_url", "acp://copilot", "beta_custom_endpoint_not_allowed"),
        ("api_mode", "anthropic_messages", "beta_api_mode_not_allowed"),
    ],
)
def test_beta_switch_rejects_hostile_live_routing_state_before_client(
    beta_agent, monkeypatch, attribute, value, code
):
    agent = beta_agent.build()
    setattr(agent, attribute, value)
    old_client = agent.client
    before = _switch_state(agent)
    openai = MagicMock()
    copilot = MagicMock()
    popen = MagicMock()
    monkeypatch.setattr(run_agent, "OpenAI", openai)
    monkeypatch.setattr("agent.copilot_acp_client.CopilotACPClient", copilot)
    monkeypatch.setattr("agent.copilot_acp_client.subprocess.Popen", popen)

    with pytest.raises(BetaProviderPolicyError) as exc:
        agent.switch_model(
            "gpt-5.5",
            "openai-codex",
            base_url=BETA_CODEX_BASE_URL,
            api_mode="codex_responses",
        )

    assert exc.value.code == code
    assert _switch_state(agent) == before
    openai.assert_not_called()
    copilot.assert_not_called()
    popen.assert_not_called()
    old_client.close.assert_not_called()


@pytest.mark.parametrize(
    "attribute,value,code",
    [
        ("_anthropic_client", object(), "beta_alternate_client_not_allowed"),
        ("_anthropic_api_key", "sk-ant-planted", "beta_alternate_client_not_allowed"),
        (
            "_anthropic_base_url",
            "https://api.anthropic.com",
            "beta_alternate_client_not_allowed",
        ),
        ("_is_anthropic_oauth", True, "beta_alternate_client_not_allowed"),
        ("_bedrock_region", "us-east-1", "beta_alternate_client_not_allowed"),
        (
            "_client_kwargs",
            {"command": "copilot", "args": ["--acp"]},
            "beta_external_process_not_allowed",
        ),
        (
            "_primary_runtime",
            {
                "provider": "openai-codex",
                "model": "gpt-5.5",
                "base_url": BETA_CODEX_BASE_URL,
                "api_mode": "codex_responses",
                "anthropic_api_key": "planted",
            },
            "beta_alternate_client_not_allowed",
        ),
    ],
)
def test_beta_switch_rejects_planted_alternate_client_state(
    beta_agent, monkeypatch, attribute, value, code
):
    agent = beta_agent.build()
    setattr(agent, attribute, value)
    before = _switch_state(agent)
    old_client = agent.client
    openai = MagicMock()
    anthropic = MagicMock()
    copilot = MagicMock()
    popen = MagicMock()
    monkeypatch.setattr(run_agent, "OpenAI", openai)
    monkeypatch.setattr("agent.anthropic_adapter.build_anthropic_client", anthropic)
    monkeypatch.setattr("agent.copilot_acp_client.CopilotACPClient", copilot)
    monkeypatch.setattr("agent.copilot_acp_client.subprocess.Popen", popen)

    with pytest.raises(BetaProviderPolicyError) as exc:
        agent.switch_model("gpt-5.5", "openai-codex")

    assert exc.value.code == code
    assert _switch_state(agent) == before
    openai.assert_not_called()
    anthropic.assert_not_called()
    copilot.assert_not_called()
    popen.assert_not_called()
    old_client.close.assert_not_called()


def test_beta_switch_revalidates_raw_config_before_runtime_resolution(
    beta_agent, monkeypatch
):
    agent = beta_agent.build()
    old_client = agent.client
    before = _switch_state(agent)
    beta_agent.home.joinpath("config.yaml").write_text(
        "model:\n  provider: anthropic\n  default: gpt-5.5\n",
        encoding="utf-8",
    )
    resolver = MagicMock(return_value=_runtime(beta_agent.home))
    openai = MagicMock()
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolver
    )
    monkeypatch.setattr(run_agent, "OpenAI", openai)

    with pytest.raises(BetaProviderPolicyError) as exc:
        agent.switch_model("gpt-5.5", "openai-codex")

    assert exc.value.code == "beta_provider_not_allowed"
    assert _switch_state(agent) == before
    resolver.assert_not_called()
    openai.assert_not_called()
    old_client.close.assert_not_called()


def test_beta_switch_client_failure_preserves_prior_runtime(beta_agent, monkeypatch):
    agent = beta_agent.build()
    old_client = agent.client
    before = _switch_state(agent)
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: _runtime(beta_agent.home, token="rotated-profile-token"),
    )
    monkeypatch.setattr(
        run_agent,
        "OpenAI",
        MagicMock(side_effect=RuntimeError("client construction failed")),
    )

    with pytest.raises(RuntimeError, match="client construction failed"):
        agent.switch_model("gpt-5.4", "openai-codex")

    assert _switch_state(agent) == before
    old_client.close.assert_not_called()


def test_beta_switch_rolls_back_and_closes_new_client_on_refresh_failure(
    beta_agent, monkeypatch
):
    agent = beta_agent.build()
    old_client = agent.client
    new_client = MagicMock()
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: _runtime(beta_agent.home, token="rotated-profile-token"),
    )
    monkeypatch.setattr(run_agent, "OpenAI", MagicMock(return_value=new_client))
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length", lambda *_args, **_kwargs: 200_000
    )
    monkeypatch.setattr(
        agent.context_compressor,
        "update_model",
        MagicMock(side_effect=RuntimeError("compressor refresh failed")),
    )
    before = _switch_state(agent)

    with pytest.raises(RuntimeError, match="compressor refresh failed"):
        agent.switch_model("gpt-5.4", "openai-codex")

    assert _switch_state(agent) == before
    new_client.close.assert_called_once_with()
    old_client.close.assert_not_called()


def test_exported_switch_helper_uses_same_beta_sink_guard(beta_agent, monkeypatch):
    from agent import agent_runtime_helpers

    agent = beta_agent.build()
    before = _switch_state(agent)
    openai = MagicMock()
    monkeypatch.setattr(run_agent, "OpenAI", openai)

    with pytest.raises(BetaProviderPolicyError) as exc:
        agent_runtime_helpers.switch_model(
            agent,
            "gpt-5.5",
            "copilot-acp",
            base_url="acp://copilot",
        )

    assert exc.value.code == "beta_provider_not_allowed"
    assert _switch_state(agent) == before
    openai.assert_not_called()


def test_non_exact_beta_switch_preserves_legacy_path(beta_agent, monkeypatch):
    agent = beta_agent.build()
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    resolver = MagicMock(side_effect=AssertionError("non-exact channel resolved Beta"))
    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider", resolver
    )
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length", lambda *_args, **_kwargs: 100_000
    )

    agent.switch_model(
        "legacy/model",
        "openrouter",
        api_key="legacy-key",
        base_url="https://openrouter.ai/api/v1",
        api_mode="chat_completions",
    )

    resolver.assert_not_called()
    assert agent.model == "legacy/model"
    assert agent.provider == "openrouter"
    assert agent.api_key == "legacy-key"
    assert agent.base_url == "https://openrouter.ai/api/v1"
    assert agent.api_mode == "chat_completions"
