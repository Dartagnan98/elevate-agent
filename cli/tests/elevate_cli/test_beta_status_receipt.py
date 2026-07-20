"""Runtime truth receipts used by the Realtor Beta desktop boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS_VERSION,
    BETA_ALLOWED_PROVIDER,
    BETA_DEFAULT_MODEL,
    BETA_PROVIDER_POLICY_VERSION,
    clear_beta_runtime_repair_state,
    mark_beta_runtime_repair_pending,
)
from elevate_cli.web_routes import status as status_module
from elevate_cli.web_routes.status import (
    _beta_runtime_receipt,
    create_status_router,
)


def _config(
    *,
    provider: str = BETA_ALLOWED_PROVIDER,
    model: str = BETA_DEFAULT_MODEL,
) -> dict:
    return {
        "model": {
            "provider": provider,
            "default": model,
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        }
    }


def _auth(*, ready: bool = True, reason: str | None = None) -> dict:
    return {"logged_in": ready, "reason": reason}


def test_beta_runtime_receipt_reports_only_public_runtime_truth(tmp_path):
    home = tmp_path / "profile" / ".." / ".elevate-beta"

    receipt = _beta_runtime_receipt(
        elevate_home=home,
        config=_config(),
        auth_status={
            "logged_in": True,
            "reason": None,
            "auth_store": "/secret/auth.json",
            "access_token": "must-not-leak",
        },
    )

    assert receipt == {
        "releaseChannel": "beta",
        "elevateHome": str(home.resolve(strict=False)),
        "providerPolicyVersion": BETA_PROVIDER_POLICY_VERSION,
        "allowedModelsVersion": BETA_ALLOWED_MODELS_VERSION,
        "entitlementAssertionSchema": 1,
        "entitlementAssertionAcceptedKeyIds": [
            "ent-2026-07-a",
            "ent-2026-07-b",
        ],
        "entitlementAssertionKeysetSha256": (
            "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c"
        ),
        "entitlementVerifierReady": True,
        "allowedProvider": BETA_ALLOWED_PROVIDER,
        "configuredProvider": BETA_ALLOWED_PROVIDER,
        "configuredModel": BETA_DEFAULT_MODEL,
        "authReady": True,
        "authReason": None,
        "runtimeReady": True,
        "blockedReason": None,
    }
    assert "secret" not in repr(receipt).lower()
    assert "auth.json" not in repr(receipt)


@pytest.mark.parametrize(
    ("config", "auth_status", "expected_reason"),
    [
        (_config(provider="anthropic"), _auth(), "beta_provider_not_allowed"),
        ({"model": {"default": BETA_DEFAULT_MODEL}}, _auth(), "beta_model_configuration_incomplete"),
        (_config(model="hostile-model"), _auth(), "beta_model_not_allowed"),
        (
            {**_config(), "memory": {"provider": "hindsight"}},
            _auth(),
            "beta_memory_provider_not_allowed",
        ),
        (
            {
                **_config(),
                "memory": {"provider": "holographic"},
                "plugins": {
                    "elevate-memory-store": {"embedding_enabled": True},
                },
            },
            _auth(),
            "beta_memory_embeddings_not_allowed",
        ),
        (_config(), _auth(ready=False, reason="missing_auth_store"), "missing_auth_store"),
        ({}, _auth(), "missing_beta_provider"),
    ],
)
def test_beta_runtime_receipt_fails_closed_with_typed_reason(
    tmp_path,
    config,
    auth_status,
    expected_reason,
):
    receipt = _beta_runtime_receipt(
        elevate_home=tmp_path,
        config=config,
        auth_status=auth_status,
    )

    assert receipt["runtimeReady"] is False
    assert receipt["blockedReason"] == expected_reason


def _status_endpoint(**kwargs):
    router = create_status_router(
        workspace_root=Path("/tmp/workspace"),
        get_session_db=lambda: None,
        session_active_window_sec=25,
        check_config_version_func=lambda: (1, 1),
        get_running_pid_func=lambda: None,
        read_runtime_status_func=lambda: None,
        gateway_health_url_func=lambda: None,
        probe_gateway_health_func=lambda: (False, None),
        **kwargs,
    )
    return next(route.endpoint for route in router.routes if route.path == "/api/status")


def test_status_adds_receipt_only_for_exact_lowercase_beta(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path / ".elevate-beta"))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    endpoint = _status_endpoint(
        read_raw_config_func=_config,
        get_elevate_home_func=lambda: tmp_path / ".elevate-beta",
        read_beta_codex_auth_status_func=lambda _home: _auth(),
    )

    payload = asyncio.run(endpoint())

    assert payload["beta_runtime"]["runtimeReady"] is True
    assert payload["beta_runtime"]["releaseChannel"] == "beta"
    assert payload["beta_runtime"]["entitlementAssertionSchema"] == 1
    assert payload["beta_runtime"]["entitlementAssertionAcceptedKeyIds"] == [
        "ent-2026-07-a",
        "ent-2026-07-b",
    ]
    assert payload["beta_runtime"]["entitlementAssertionKeysetSha256"] == (
        "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c"
    )
    assert payload["beta_runtime"]["entitlementVerifierReady"] is True


def test_beta_runtime_receipt_blocks_when_entitlement_verifier_is_unavailable(
    monkeypatch,
    tmp_path,
):
    from elevate_cli import entitlement_assertion

    monkeypatch.setattr(entitlement_assertion, "verifier_ready", lambda: False)

    receipt = _beta_runtime_receipt(
        elevate_home=tmp_path,
        config=_config(),
        auth_status=_auth(),
    )

    assert receipt["entitlementVerifierReady"] is False
    assert receipt["runtimeReady"] is False
    assert receipt["blockedReason"] == "beta_entitlement_verifier_unavailable"


def test_beta_runtime_receipt_blocks_hostile_ambient_provider_override(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")

    receipt = _beta_runtime_receipt(
        elevate_home=tmp_path,
        config=_config(),
        auth_status=_auth(),
    )

    assert receipt["runtimeReady"] is False
    assert receipt["blockedReason"] == "beta_provider_not_allowed"


def test_beta_repair_gate_bypasses_a_cached_ready_status(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    cached = {"beta_runtime": {"runtimeReady": True, "blockedReason": None}}
    monkeypatch.setattr(status_module, "_status_cache_payload", cached)
    monkeypatch.setattr(
        status_module,
        "_status_cache_expires_at",
        status_module.time.monotonic() + 60,
    )
    clear_beta_runtime_repair_state()
    try:
        assert status_module._cached_status_payload() == cached
        mark_beta_runtime_repair_pending()
        assert status_module._cached_status_payload() is None
    finally:
        clear_beta_runtime_repair_state()


@pytest.mark.parametrize("channel", ["latest", "Beta", "BETA", " beta"])
def test_stable_and_non_exact_channels_keep_legacy_status_shape(
    monkeypatch,
    tmp_path,
    channel,
):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path / ".elevate"))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", channel)

    def forbidden_read():
        raise AssertionError("Stable status must not enter the Beta receipt lane")

    endpoint = _status_endpoint(
        read_raw_config_func=forbidden_read,
        get_elevate_home_func=lambda: tmp_path / ".elevate",
        read_beta_codex_auth_status_func=lambda _home: forbidden_read(),
    )

    payload = asyncio.run(endpoint())

    assert "beta_runtime" not in payload
    assert "version" in payload
    assert "gateway_running" in payload
