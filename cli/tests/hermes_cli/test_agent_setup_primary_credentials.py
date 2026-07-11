"""Primary onboarding readiness must be tied to the selected provider."""

import pytest

from elevate_cli.data import agent_setup
from elevate_cli.web_routes.admin_setup import (
    _materialize_agent_setup_secrets,
    _wizard_runtime_provider,
)


_KEY_NAMES = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "MINIMAX_API_KEY",
    "DEEPSEEK_API_KEY",
    "ZHIPU_API_KEY",
    "GLM_API_KEY",
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
    "KIMI_API_KEY",
    "KIMI_CODING_API_KEY",
    "CUSTOM_LLM_KEY",
    "AZURE_FOUNDRY_API_KEY",
    "AZURE_FOUNDRY_BASE_URL",
}


def _detect(monkeypatch, *, provider, env=None, config_extra=None, oauth_provider=None):
    from elevate_cli import auth, config

    for name in _KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    cfg = {
        "model": {"provider": provider, "default": "test-model"},
        **(config_extra or {}),
    }
    file_env = dict(env or {})
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    monkeypatch.setattr(config, "load_env", lambda: file_env)
    monkeypatch.setattr(
        auth,
        "get_auth_status",
        lambda provider_id=None: {"logged_in": provider_id == oauth_provider},
    )
    monkeypatch.setattr(
        auth,
        "get_codex_auth_status",
        lambda: {"logged_in": oauth_provider == "openai-codex"},
    )
    return agent_setup._detect_runtime_credentials()["model_primary"]


@pytest.mark.parametrize(
    "provider",
    ["gemini", "xai", "minimax", "deepseek", "zai", "kimi-coding", "openrouter"],
)
def test_config_pin_without_matching_credential_is_selection_only(monkeypatch, provider):
    item = _detect(monkeypatch, provider=provider)

    assert item["status"] == "missing"
    assert item["provider"] == provider
    assert item["value"]["model"] == "test-model"
    assert item["value"]["runtimeProvider"] == provider
    assert item["value"]["secretPresent"] is False
    assert item["value"]["secretSource"] == "config"


@pytest.mark.parametrize(
    ("provider", "env_name"),
    [
        ("gemini", "GEMINI_API_KEY"),
        ("xai", "XAI_API_KEY"),
        ("minimax", "MINIMAX_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("zai", "GLM_API_KEY"),
        ("kimi-coding", "KIMI_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("alibaba", "DASHSCOPE_API_KEY"),
    ],
)
def test_matching_provider_env_key_promotes_configured(monkeypatch, provider, env_name):
    item = _detect(monkeypatch, provider=provider, env={env_name: "provider-key"})

    assert item["status"] == "configured"
    assert item["provider"] == provider
    assert item["value"]["secretPresent"] is True
    assert item["value"]["secretSource"] == "env"
    assert item["value"]["runtimeProvider"] == provider


def test_azure_foundry_requires_runtime_key_and_base_url(monkeypatch):
    key_only = _detect(
        monkeypatch,
        provider="azure-foundry",
        env={"AZURE_FOUNDRY_API_KEY": "azure-key"},
    )
    ready = _detect(
        monkeypatch,
        provider="azure-foundry",
        env={
            "AZURE_FOUNDRY_API_KEY": "azure-key",
            "AZURE_FOUNDRY_BASE_URL": "https://example.services.ai.azure.com",
        },
    )

    assert key_only["status"] == "missing"
    assert ready["status"] == "configured"
    assert ready["value"]["runtimeProvider"] == "azure-foundry"


def test_fresh_gemini_key_seeds_a_primary_model_without_existing_config(monkeypatch):
    from elevate_cli import auth, config

    for name in _KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_config", lambda: {"model": {}})
    monkeypatch.setattr(config, "load_env", lambda: {"GEMINI_API_KEY": "gemini-key"})
    monkeypatch.setattr(auth, "get_auth_status", lambda provider_id=None: {"logged_in": False})
    monkeypatch.setattr(auth, "get_codex_auth_status", lambda: {"logged_in": False})

    item = agent_setup._detect_runtime_credentials()["model_primary"]

    assert item["status"] == "configured"
    assert item["provider"] == "gemini"
    assert item["value"]["model"] == "gemini-2.5-flash"
    assert item["value"]["runtimeProvider"] == "gemini"
    assert item["value"]["secretPresent"] is True


def test_unrelated_openai_and_anthropic_keys_do_not_override_gemini(monkeypatch):
    item = _detect(
        monkeypatch,
        provider="gemini",
        env={
            "OPENAI_API_KEY": "unrelated-openai",
            "ANTHROPIC_API_KEY": "unrelated-anthropic",
        },
    )

    assert item["status"] == "missing"
    assert item["provider"] == "gemini"
    assert item["value"]["secretSource"] == "config"


def test_openai_and_openrouter_keys_do_not_qualify_each_other(monkeypatch):
    openai = _detect(
        monkeypatch,
        provider="openai",
        env={"OPENROUTER_API_KEY": "unrelated-router-key"},
    )
    openrouter = _detect(
        monkeypatch,
        provider="openrouter",
        env={"OPENAI_API_KEY": "unrelated-openai-key"},
    )

    assert openai["status"] == "missing"
    assert openrouter["status"] == "missing"


def test_configured_primary_is_downgraded_when_runtime_credential_is_missing():
    item = {
        "key": "model_primary",
        "status": "configured",
        "provider": "gemini",
        "value": {
            "model": "gemini-2.5-flash",
            "runtimeProvider": "gemini",
            "secretPresent": True,
            "secretSource": "env",
        },
    }
    overlays = {
        "model_primary": {
            "status": "missing",
            "provider": "gemini",
            "value": {
                "secretPresent": False,
                "secretSource": "config",
                "secretPreview": "",
            },
        }
    }

    merged = agent_setup._apply_runtime_overlay(item, overlays)

    assert merged["status"] == "missing"
    assert merged["value"]["secretPresent"] is False


def test_setup_values_strip_secrets_before_database_storage():
    value = {
        "model": "openai/gpt-4o-mini",
        "apiKey": "sk-plaintext",
        "runtimeProvider": "openrouter",
    }

    sanitized = agent_setup._sanitize_value_for_storage("model_primary", value)

    assert sanitized["apiKey"] == ""
    assert "sk-plaintext" not in str(sanitized)


def test_pasted_openai_key_materializes_direct_provider_not_codex_oauth():
    assert _wizard_runtime_provider(
        "openai", {"runtimeProvider": "openai"}
    ) == "openai"


@pytest.mark.parametrize(
    ("wizard_provider", "runtime_provider", "env_name"),
    [
        ("qwen", "alibaba", "DASHSCOPE_API_KEY"),
        ("azure_openai", "azure-foundry", "AZURE_FOUNDRY_API_KEY"),
    ],
)
def test_direct_key_provider_materializes_to_supported_runtime_and_env(
    monkeypatch,
    wizard_provider,
    runtime_provider,
    env_name,
):
    writes = []
    monkeypatch.setattr(
        "elevate_cli.web_routes.admin_setup.save_env_value",
        lambda key, value: writes.append((key, value)),
    )

    safe = _materialize_agent_setup_secrets(
        [
            {
                "key": "model_primary",
                "status": "configured",
                "provider": wizard_provider,
                "value": {
                    "model": "test-model",
                    "runtimeProvider": wizard_provider,
                    "apiKey": "provider-secret",
                },
            }
        ]
    )

    assert writes == [(env_name, "provider-secret")]
    assert safe[0]["value"]["apiKey"] == ""
    assert _wizard_runtime_provider(wizard_provider, safe[0]["value"]) == runtime_provider
    assert (
        _wizard_runtime_provider(wizard_provider, {"usesEnvSecret": True})
        == runtime_provider
    )


def test_codex_oauth_only_promotes_matching_codex_config(monkeypatch):
    disconnected = _detect(
        monkeypatch,
        provider="openai-codex",
        env={"OPENAI_API_KEY": "not-a-codex-credential"},
    )
    connected = _detect(
        monkeypatch,
        provider="openai-codex",
        env={"OPENAI_API_KEY": "not-a-codex-credential"},
        oauth_provider="openai-codex",
    )

    assert disconnected["status"] == "missing"
    assert connected["status"] == "configured"
    assert connected["value"]["secretSource"] == "oauth"


@pytest.mark.parametrize(
    "provider_entry",
    [
        {"base_url": "https://llm.example.test/v1", "key_env": "CUSTOM_LLM_KEY"},
        {"base_url": "https://llm.example.test/v1", "api_key": "inline-custom-key"},
    ],
)
def test_user_provider_key_env_and_inline_key_are_detected(monkeypatch, provider_entry):
    env = {"CUSTOM_LLM_KEY": "custom-env-key"} if provider_entry.get("key_env") else {}
    item = _detect(
        monkeypatch,
        provider="my-provider",
        env=env,
        config_extra={"providers": {"my-provider": provider_entry}},
    )

    assert item["status"] == "configured"
    assert item["provider"] == "my-provider"
    assert item["value"]["secretPresent"] is True
