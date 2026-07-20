"""Focused tests for the fail-closed Realtor Beta provider boundary."""

import base64
import json
import time

import pytest

from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_ALLOWED_MODELS,
    BETA_DEFAULT_MODEL,
    BetaProviderPolicyError,
    beta_model_or_default,
    beta_provider_policy_active,
    canonical_beta_provider,
    read_beta_codex_auth_status,
    require_beta_codex_auth,
    validate_beta_config_for_persistence,
    validate_beta_memory_provider,
    validate_beta_primary_item,
)


def _jwt(expiry: float) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": expiry}).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    return f"header.{payload}.signature"


def _write_codex_auth(home, *, access_token: str) -> bytes:
    payload = {
        "version": 1,
        "providers": {
            "openai-codex": {
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": "refresh-token",
                }
            }
        },
    }
    path = home / "auth.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path.read_bytes()


@pytest.mark.parametrize(
    ("channel", "active"),
    [("beta", True), ("Beta", False), (" beta", False), ("latest", False), (None, False)],
)
def test_beta_policy_activation_is_exact(channel, active):
    env = {} if channel is None else {"ELEVATE_RELEASE_CHANNEL": channel}

    assert beta_provider_policy_active(env) is active
    assert BETA_DEFAULT_MODEL in BETA_ALLOWED_MODELS


def test_beta_auth_inspection_is_local_read_only_and_does_not_refresh(tmp_path):
    home = tmp_path / "beta-home"
    home.mkdir()
    before = _write_codex_auth(home, access_token=_jwt(time.time() - 60))

    status = read_beta_codex_auth_status(home)

    assert status["logged_in"] is False
    assert status["reason"] == "codex_auth_missing_or_expired"
    assert (home / "auth.json").read_bytes() == before


def test_beta_auth_inspection_rejects_symlinked_home(tmp_path):
    real_home = tmp_path / "stable-home"
    real_home.mkdir()
    _write_codex_auth(real_home, access_token="current-token")
    linked_home = tmp_path / "beta-home"
    linked_home.symlink_to(real_home, target_is_directory=True)

    status = read_beta_codex_auth_status(linked_home)

    assert status["logged_in"] is False
    assert status["reason"] == "non_local_auth_store"


@pytest.mark.parametrize("value", [None, "", "auto", "openai-codex"])
def test_beta_provider_canonicalization_maps_only_absent_auto_or_codex(value):
    assert canonical_beta_provider(value) == BETA_ALLOWED_PROVIDER


def test_beta_provider_and_model_helpers_reject_non_beta_values():
    with pytest.raises(BetaProviderPolicyError) as provider_exc:
        canonical_beta_provider("anthropic", source="test provider")
    assert provider_exc.value.code == "beta_provider_not_allowed"

    with pytest.raises(BetaProviderPolicyError) as model_exc:
        beta_model_or_default("anthropic/claude-sonnet-4", source="test model")
    assert model_exc.value.code == "beta_model_not_allowed"
    assert beta_model_or_default("") == BETA_DEFAULT_MODEL


@pytest.mark.parametrize(
    "provider",
    [
        "builtin",
        "hindsight",
        "honcho",
        "retaindb",
        "mem0",
        "byterover",
        "openviking",
        "supermemory",
        "user-memory-plugin",
    ],
)
def test_beta_config_rejects_every_nonlocal_memory_provider(provider):
    with pytest.raises(BetaProviderPolicyError) as exc:
        validate_beta_config_for_persistence(
            {"memory": {"provider": provider}},
            {"logged_in": True},
            environ={"ELEVATE_RELEASE_CHANNEL": "beta"},
        )

    assert exc.value.code == "beta_memory_provider_not_allowed"


@pytest.mark.parametrize("provider", [None, "", "holographic"])
@pytest.mark.parametrize(
    "embedding_enabled",
    [None, False, 0, "", "0", "false", "no", "off", "disabled"],
)
def test_beta_config_allows_builtin_or_local_holographic_without_embeddings(
    provider,
    embedding_enabled,
):
    validate_beta_config_for_persistence(
        {
            "memory": {"provider": provider},
            "plugins": {
                "elevate-memory-store": {
                    "embedding_enabled": embedding_enabled,
                }
            },
        },
        {"logged_in": True},
        environ={"ELEVATE_RELEASE_CHANNEL": "beta"},
    )


@pytest.mark.parametrize(
    "embedding_enabled",
    [True, 1, "1", "true", "yes", "on", "enabled"],
)
def test_beta_config_rejects_holographic_embedding_inference(embedding_enabled):
    with pytest.raises(BetaProviderPolicyError) as exc:
        validate_beta_config_for_persistence(
            {
                "memory": {"provider": "holographic"},
                "plugins": {
                    "elevate-memory-store": {
                        "embedding_enabled": embedding_enabled,
                    }
                },
            },
            {"logged_in": True},
            environ={"ELEVATE_RELEASE_CHANNEL": "beta"},
        )

    assert exc.value.code == "beta_memory_embeddings_not_allowed"


@pytest.mark.parametrize("channel", ["stable", "Beta", "BETA", " beta"])
def test_non_exact_beta_channels_keep_external_memory_behavior(channel):
    validate_beta_config_for_persistence(
        {
            "memory": {"provider": "hindsight"},
            "plugins": {
                "elevate-memory-store": {"embedding_enabled": True},
            },
        },
        {"logged_in": False},
        environ={"ELEVATE_RELEASE_CHANNEL": channel},
    )


@pytest.mark.parametrize("provider", [None, "", "HOLOGRAPHIC"])
def test_beta_memory_entrypoint_helper_allows_only_local_providers(provider):
    assert validate_beta_memory_provider(
        provider,
        environ={"ELEVATE_RELEASE_CHANNEL": "beta"},
    ) in {"", "holographic"}


def test_beta_memory_entrypoint_helper_rejects_external_provider():
    with pytest.raises(BetaProviderPolicyError) as exc:
        validate_beta_memory_provider(
            "hindsight",
            environ={"ELEVATE_RELEASE_CHANNEL": "beta"},
        )

    assert exc.value.code == "beta_memory_provider_not_allowed"


def test_require_beta_codex_auth_fails_closed_without_local_store(tmp_path):
    with pytest.raises(BetaProviderPolicyError) as exc:
        require_beta_codex_auth(tmp_path)

    assert exc.value.code == "beta_codex_auth_required"


def test_beta_auth_pool_only_entry_is_not_runtime_ready(tmp_path):
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "version": 1,
                "credential_pool": {
                    "openai-codex": [
                        {
                            "access_token": "pool-only-token",
                            "last_status": "ok",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    status = read_beta_codex_auth_status(tmp_path)

    assert status["logged_in"] is False
    assert status["reason"] == "codex_auth_missing_or_expired"


@pytest.mark.parametrize(
    ("provider", "runtime_provider", "model", "logged_in", "code"),
    [
        ("gemini", "gemini", "gpt-5.5", True, "beta_provider_not_allowed"),
        ("openai-codex", "openai-codex", "gpt-4o", True, "beta_model_not_allowed"),
        ("openai-codex", "openai-codex", "gpt-5.5", False, "beta_codex_auth_required"),
    ],
)
def test_beta_primary_validation_rejects_provider_model_and_missing_local_auth(
    provider,
    runtime_provider,
    model,
    logged_in,
    code,
):
    with pytest.raises(BetaProviderPolicyError) as exc:
        validate_beta_primary_item(
            {
                "key": "model_primary",
                "status": "configured",
                "provider": provider,
                "value": {
                    "model": model,
                    "runtimeProvider": runtime_provider,
                    "apiKey": "",
                },
            },
            {"logged_in": logged_in},
        )

    assert exc.value.code == code


def test_beta_primary_validation_canonicalizes_web_transport_alias():
    canonical = validate_beta_primary_item(
        {
            "key": "model_primary",
            "status": "missing",
            "provider": "openai",
            "value": {
                "model": "gpt-5.5",
                "runtimeProvider": "openai-codex",
                "apiKey": "",
                "secretPresent": True,
                "authReady": False,
                "policyBlocked": True,
                "configuredProvider": "gemini",
            },
        },
        {"logged_in": True},
    )

    assert canonical["status"] == "configured"
    assert canonical["provider"] == "openai-codex"
    assert canonical["value"] == {
        "model": "gpt-5.5",
        "runtimeProvider": "openai-codex",
        "apiKey": "",
        "usesEnvSecret": False,
    }


def test_beta_primary_validation_rejects_hostile_ambient_override(monkeypatch):
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")

    with pytest.raises(BetaProviderPolicyError) as exc:
        validate_beta_primary_item(
            {
                "key": "model_primary",
                "status": "configured",
                "provider": "openai-codex",
                "value": {
                    "model": "gpt-5.5",
                    "runtimeProvider": "openai-codex",
                    "apiKey": "",
                },
            },
            {"logged_in": True},
        )

    assert exc.value.code == "beta_model_not_allowed"
