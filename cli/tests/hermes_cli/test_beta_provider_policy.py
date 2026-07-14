"""Focused tests for the fail-closed Realtor Beta provider boundary."""

import base64
import json
import time

import pytest

from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS,
    BETA_DEFAULT_MODEL,
    BetaProviderPolicyError,
    beta_provider_policy_active,
    read_beta_codex_auth_status,
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
