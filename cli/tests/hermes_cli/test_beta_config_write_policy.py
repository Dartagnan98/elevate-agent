"""Realtor Beta provider policy at config persistence boundaries."""

from __future__ import annotations

import copy
import json

import pytest
import yaml

from elevate_cli import config as config_module
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    BETA_DEFAULT_MODEL,
    BETA_PROVIDER_POLICY_VERSION,
    BetaProviderPolicyError,
)


@pytest.fixture
def beta_home(tmp_path, monkeypatch):
    home = tmp_path / "realtor-beta"
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    config_module._CONFIG_CACHE_BY_PATH.clear()
    config_module._LAST_EXPANDED_CONFIG_BY_PATH.clear()
    return home


def _write_local_codex_auth(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "providers": {
                    BETA_ALLOWED_PROVIDER: {
                        "tokens": {
                            "access_token": "test-access-token",
                            "refresh_token": "test-refresh-token",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _valid_beta_config():
    return {
        "model": {
            "provider": BETA_ALLOWED_PROVIDER,
            "default": BETA_DEFAULT_MODEL,
            "base_url": BETA_CODEX_BASE_URL,
            "api_mode": "codex_responses",
        }
    }


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({"model": {"provider": "gemini", "default": "gemini-2.5-flash"}}, "beta_provider_not_allowed"),
        ({"model": BETA_DEFAULT_MODEL}, "beta_model_configuration_incomplete"),
        ({"model": {"provider": BETA_ALLOWED_PROVIDER, "default": "gpt-hostile"}}, "beta_model_not_allowed"),
        (
            {
                "model": {
                    "provider": BETA_ALLOWED_PROVIDER,
                    "default": BETA_DEFAULT_MODEL,
                    "base_url": "https://hostile.invalid/v1",
                }
            },
            "beta_custom_endpoint_not_allowed",
        ),
        (
            {
                "model": {
                    "provider": BETA_ALLOWED_PROVIDER,
                    "default": BETA_DEFAULT_MODEL,
                    "api_mode": "chat_completions",
                }
            },
            "beta_api_mode_not_allowed",
        ),
        (
            {
                "model": {
                    "provider": BETA_ALLOWED_PROVIDER,
                    "default": BETA_DEFAULT_MODEL,
                    "api_key": "not-a-real-key",
                }
            },
            "beta_primary_api_key_not_allowed",
        ),
        (
            {
                "model": {
                    "provider": BETA_ALLOWED_PROVIDER,
                    "default": BETA_DEFAULT_MODEL,
                    "openai_runtime": "codex_app_server",
                }
            },
            "beta_codex_app_server_not_allowed",
        ),
        (
            {
                "model": {
                    "provider": BETA_ALLOWED_PROVIDER,
                    "default": BETA_DEFAULT_MODEL,
                    "key_env": "OPENAI_API_KEY",
                }
            },
            "beta_primary_api_key_not_allowed",
        ),
        (
            {
                "model": {},
                "fallback_model": {"provider": "openrouter", "model": "fallback"},
            },
            "beta_fallback_not_allowed",
        ),
        (
            {"model": {}, "fallback_providers": ["anthropic"]},
            "beta_fallback_not_allowed",
        ),
        (
            {"model": {}, "custom_providers": {"hostile": {"base_url": "https://hostile.invalid"}}},
            "beta_custom_provider_not_allowed",
        ),
        (
            {"memory": {"provider": "hindsight"}},
            "beta_memory_provider_not_allowed",
        ),
        (
            {
                "memory": {"provider": "holographic"},
                "plugins": {
                    "elevate-memory-store": {"embedding_enabled": True},
                },
            },
            "beta_memory_embeddings_not_allowed",
        ),
        (
            {"quick_commands": {"escape": {"type": "exec", "command": "id"}}},
            "beta_quick_commands_not_allowed",
        ),
        (
            {"hooks": {"pre_tool_call": [{"command": "untrusted-hook"}]}},
            "beta_shell_hooks_not_allowed",
        ),
        ({"hooks_auto_accept": True}, "beta_shell_hooks_not_allowed"),
        (
            {"command_allowlist": ["pipe remote content to shell"]},
            "beta_command_allowlist_not_allowed",
        ),
        ({"approvals": {"mode": "smart"}}, "beta_approval_mode_not_allowed"),
        ({"approvals": {"mode": False}}, "beta_approval_mode_not_allowed"),
        (
            {"approvals": {"permission_mode": "bypassPermissions"}},
            "beta_permission_mode_not_allowed",
        ),
        (
            {"approvals": {"cron_mode": "approve"}},
            "beta_cron_approval_not_allowed",
        ),
        (
            {"terminal": {"backend": "ssh", "ssh_host": "hostile.invalid"}},
            "beta_terminal_backend_not_allowed",
        ),
        (
            {"security": {"allow_private_urls": True}},
            "beta_private_urls_not_allowed",
        ),
        (
            {"browser": {"allow_private_urls": "yes"}},
            "beta_private_urls_not_allowed",
        ),
        (
            {"platforms": {"discord": {"enabled": True, "token": "hostile"}}},
            "beta_platform_not_allowed",
        ),
        (
            {"platforms": {"webhook": {"enabled": True, "extra": {"routes": {}}}}},
            "beta_platform_not_allowed",
        ),
        (
            {"platforms": {"telegram": {"enabled": True, "token": "hostile"}}},
            "beta_platform_credential_not_allowed",
        ),
        (
            {
                "platforms": {
                    "telegram": {
                        "extra": {
                            "agent_bots": {
                                "admin": {"token": "hostile", "agent_id": "admin"},
                            }
                        }
                    }
                }
            },
            "beta_platform_credential_not_allowed",
        ),
        (
            {"ELEVATE_ALLOW_PRIVATE_URLS": "true"},
            "beta_direct_env_config_not_allowed",
        ),
        (
            {"providers": {"anthropic": {"api_key": "hostile"}}},
            "beta_provider_registry_not_allowed",
        ),
        (
            {"credential_pool_strategies": {"anthropic": "round-robin"}},
            "beta_credential_pool_not_allowed",
        ),
        (
            {"auxiliary": {"vision": {"provider": "anthropic"}}},
            "beta_auxiliary_provider_not_allowed",
        ),
        (
            {"auxiliary": {"vision": {"base_url": "https://hostile.invalid"}}},
            "beta_auxiliary_endpoint_not_allowed",
        ),
        (
            {"delegation": {"provider": "openrouter", "model": "hostile"}},
            "beta_auxiliary_provider_not_allowed",
        ),
    ],
)
def test_beta_save_rejects_provider_escape_before_profile_mutation(
    beta_home,
    config,
    code,
):
    assert not beta_home.exists()

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        config_module.save_config(config)

    assert exc_info.value.code == code
    assert not beta_home.exists()


def test_beta_rejection_preserves_existing_config_bytes(beta_home):
    beta_home.mkdir(parents=True)
    config_path = beta_home / "config.yaml"
    before = b"model:\n  provider: openai-codex\n  default: gpt-5.5\n"
    config_path.write_bytes(before)

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        config_module.save_config(
            {"model": {"provider": "anthropic", "default": "claude-hostile"}}
        )

    assert exc_info.value.code == "beta_provider_not_allowed"
    assert config_path.read_bytes() == before


def test_beta_configured_codex_requires_current_profile_auth(beta_home):
    with pytest.raises(BetaProviderPolicyError) as exc_info:
        config_module.save_config(_valid_beta_config())

    assert exc_info.value.code == "beta_codex_auth_required"
    assert not beta_home.exists()


def test_beta_valid_codex_config_persists_after_local_auth(beta_home):
    _write_local_codex_auth(beta_home)

    config_module.save_config(_valid_beta_config())

    written = yaml.safe_load((beta_home / "config.yaml").read_text(encoding="utf-8"))
    assert written["model"] == _valid_beta_config()["model"]


def test_beta_current_local_holographic_profile_shape_persists(beta_home):
    _write_local_codex_auth(beta_home)
    config = {
        **_valid_beta_config(),
        "memory": {"provider": "holographic"},
        "plugins": {
            "elevate-memory-store": {"embedding_enabled": False},
        },
    }

    config_module.save_config(config)

    written = yaml.safe_load((beta_home / "config.yaml").read_text(encoding="utf-8"))
    assert written["model"] == config["model"]
    assert written["memory"] == config["memory"]
    assert written["plugins"] == config["plugins"]


def test_beta_signed_default_config_shape_remains_persistable(beta_home):
    _write_local_codex_auth(beta_home)

    config_module.save_config(copy.deepcopy(config_module.DEFAULT_CONFIG))

    written = yaml.safe_load((beta_home / "config.yaml").read_text(encoding="utf-8"))
    assert written["terminal"]["backend"] == "local"
    assert set(written["platforms"]) == {"telegram", "api_server"}
    assert written["approvals"]["mode"] == "manual"
    assert written["quick_commands"] == {}


def test_non_beta_channels_keep_existing_config_behavior(tmp_path, monkeypatch):
    home = tmp_path / "stable"
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))

    config_module.save_config(
        {
            "model": {"provider": "gemini", "default": "gemini-2.5-flash"},
            "memory": {"provider": "hindsight"},
            "plugins": {
                "elevate-memory-store": {"embedding_enabled": True},
            },
            "quick_commands": {
                "compat": {"type": "exec", "command": "echo stable"},
            },
            "hooks": {
                "pre_tool_call": [{"command": "stable-hook"}],
            },
            "hooks_auto_accept": True,
            "command_allowlist": ["stable-pattern"],
            "approvals": {
                "mode": "smart",
                "permission_mode": "bypassPermissions",
                "cron_mode": "approve",
            },
            "terminal": {"backend": "ssh"},
            "security": {"allow_private_urls": True},
            "browser": {"allow_private_urls": True},
            "platforms": {"discord": {"enabled": True, "token": "stable-token"}},
            "ELEVATE_ALLOW_PRIVATE_URLS": "true",
            "providers": {"anthropic": {"api_key": "stable-key"}},
            "credential_pool_strategies": {"anthropic": "round-robin"},
            "auxiliary": {"vision": {"provider": "anthropic"}},
            "delegation": {"provider": "openrouter", "model": "stable-model"},
        }
    )

    written = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert written["model"]["provider"] == "gemini"
    assert written["memory"]["provider"] == "hindsight"
    assert written["plugins"]["elevate-memory-store"]["embedding_enabled"] is True
    assert written["quick_commands"]["compat"]["command"] == "echo stable"
    assert written["terminal"]["backend"] == "ssh"
    assert written["security"]["allow_private_urls"] is True
    assert written["platforms"]["discord"]["enabled"] is True
    assert written["ELEVATE_ALLOW_PRIVATE_URLS"] == "true"
    assert written["providers"]["anthropic"]["api_key"] == "stable-key"
    assert written["auxiliary"]["vision"]["provider"] == "anthropic"
    assert written["delegation"]["provider"] == "openrouter"


def _config_client(*, load_config_func=lambda: {}, save_config_func=lambda _cfg: None):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from elevate_cli.web_routes.config import create_config_router

    app = FastAPI()
    app.include_router(
        create_config_router(
            default_config={},
            config_schema={},
            category_order=[],
            load_config_func=load_config_func,
            save_config_func=save_config_func,
        )
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/config",
            {"config": {"model": {"provider": "gemini", "default": "gemini-hostile"}}},
        ),
        (
            "/api/config/raw",
            {"yaml_text": "model:\n  provider: gemini\n  default: gemini-hostile\n"},
        ),
    ],
)
def test_beta_config_routes_return_typed_409_before_save(
    beta_home,
    path,
    payload,
):
    saved = []
    client = _config_client(save_config_func=saved.append)

    response = client.put(path, json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "beta_provider_not_allowed",
        "message": "Realtor Beta does not allow configured provider 'gemini'.",
        "policyVersion": BETA_PROVIDER_POLICY_VERSION,
        "allowedProvider": BETA_ALLOWED_PROVIDER,
        "allowedModelsVersion": "2026-07-14-v1",
    }
    assert saved == []
    assert not beta_home.exists()


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/config", {"config": _valid_beta_config()}),
        ("/api/config/raw", {"yaml_text": yaml.safe_dump(_valid_beta_config())}),
    ],
)
def test_beta_config_routes_accept_valid_local_codex_state(
    beta_home,
    path,
    payload,
):
    _write_local_codex_auth(beta_home)
    saved = []
    client = _config_client(
        load_config_func=lambda: copy.deepcopy(_valid_beta_config()),
        save_config_func=saved.append,
    )

    response = client.put(path, json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert saved == [_valid_beta_config()]


@pytest.mark.parametrize("raw_route", [False, True])
def test_beta_generic_config_routes_reject_allowed_model_drift_before_save(
    beta_home,
    raw_route,
):
    _write_local_codex_auth(beta_home)
    current = _valid_beta_config()
    current_before = copy.deepcopy(current)
    prospective = copy.deepcopy(current)
    prospective["model"]["default"] = "gpt-5.4"
    saved = []
    client = _config_client(
        load_config_func=lambda: current,
        save_config_func=saved.append,
    )

    response = client.put(
        "/api/config/raw" if raw_route else "/api/config",
        json=(
            {"yaml_text": yaml.safe_dump(prospective)}
            if raw_route
            else {"config": prospective}
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "beta_app_onboarding_required"
    assert saved == []
    assert current == current_before


@pytest.mark.parametrize("raw_route", [False, True])
@pytest.mark.parametrize(
    ("config", "code"),
    [
        (
            {"memory": {"provider": "hindsight"}},
            "beta_memory_provider_not_allowed",
        ),
        (
            {
                "memory": {"provider": "holographic"},
                "plugins": {
                    "elevate-memory-store": {"embedding_enabled": True},
                },
            },
            "beta_memory_embeddings_not_allowed",
        ),
    ],
)
def test_beta_config_routes_reject_memory_inference_before_save(
    beta_home,
    raw_route,
    config,
    code,
):
    saved = []
    client = _config_client(save_config_func=saved.append)
    if raw_route:
        response = client.put(
            "/api/config/raw",
            json={"yaml_text": yaml.safe_dump(config)},
        )
    else:
        response = client.put("/api/config", json={"config": config})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert saved == []
    assert not beta_home.exists()


@pytest.mark.parametrize("raw_route", [False, True])
@pytest.mark.parametrize(
    ("config", "code"),
    [
        (
            {"quick_commands": {"escape": {"type": "exec", "command": "id"}}},
            "beta_quick_commands_not_allowed",
        ),
        (
            {"command_allowlist": ["pipe remote content to shell"]},
            "beta_command_allowlist_not_allowed",
        ),
        (
            {"approvals": {"mode": "smart"}},
            "beta_approval_mode_not_allowed",
        ),
        (
            {"terminal": {"backend": "ssh"}},
            "beta_terminal_backend_not_allowed",
        ),
        (
            {"browser": {"allow_private_urls": True}},
            "beta_private_urls_not_allowed",
        ),
        (
            {"platforms": {"discord": {"enabled": True, "token": "hostile"}}},
            "beta_platform_not_allowed",
        ),
        (
            {"ELEVATE_YOLO_MODE": "1"},
            "beta_direct_env_config_not_allowed",
        ),
        (
            {"auxiliary": {"approval": {"provider": "anthropic"}}},
            "beta_auxiliary_provider_not_allowed",
        ),
    ],
)
def test_beta_config_routes_reject_runtime_escape_before_save(
    beta_home,
    raw_route,
    config,
    code,
):
    saved = []
    client = _config_client(save_config_func=saved.append)
    payload = (
        {"yaml_text": yaml.safe_dump(config)}
        if raw_route
        else {"config": config}
    )

    response = client.put(
        "/api/config/raw" if raw_route else "/api/config",
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert saved == []
    assert not beta_home.exists()


def test_raw_config_non_mapping_remains_a_400(beta_home):
    response = _config_client().put(
        "/api/config/raw",
        json={"yaml_text": "- not\n- a\n- mapping\n"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "YAML must be a mapping"
