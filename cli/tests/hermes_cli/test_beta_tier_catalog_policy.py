"""Exact Realtor Beta model-catalog and tier-mapping containment."""

from __future__ import annotations

import json

import pytest

from elevate_cli import config as config_module
from elevate_cli import models as models_module
from elevate_cli import tier_resolver
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_MODELS,
    BETA_ALLOWED_MODELS_VERSION,
    BETA_ALLOWED_PROVIDER,
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
    monkeypatch.setattr(config_module, "load_config", lambda: {})
    return home


def _write_fake_codex_auth(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(
        json.dumps({
            "providers": {
                BETA_ALLOWED_PROVIDER: {
                    "tokens": {
                        "access_token": "fake-local-access-token",
                        "refresh_token": "fake-local-refresh-token",
                    }
                }
            }
        }),
        encoding="utf-8",
    )


def _valid_mapping():
    return {
        "orchestrator": {
            "model": BETA_DEFAULT_MODEL,
            "provider": BETA_ALLOWED_PROVIDER,
        }
    }


def _block_generic_discovery(monkeypatch):
    calls = []

    def blocked(name):
        def fail(*args, **kwargs):
            calls.append((name, args, kwargs))
            raise AssertionError(f"exact Beta called generic provider discovery: {name}")

        return fail

    monkeypatch.setattr(
        models_module,
        "list_available_providers",
        blocked("list_available_providers"),
    )
    monkeypatch.setattr(
        models_module,
        "provider_model_ids",
        blocked("provider_model_ids"),
    )
    return calls


def _config_client(*, load_config_func=lambda: {}):
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
            save_config_func=lambda _config: None,
        )
    )
    return TestClient(app)


def test_beta_catalog_is_versioned_current_home_truth_without_discovery_or_mutation(
    beta_home,
    monkeypatch,
):
    discovery_calls = _block_generic_discovery(monkeypatch)
    assert not beta_home.exists()

    catalog = tier_resolver.list_available_models()

    assert [entry["id"] for entry in catalog["models"]] == list(BETA_ALLOWED_MODELS)
    assert {entry["provider"] for entry in catalog["models"]} == {
        BETA_ALLOWED_PROVIDER
    }
    assert {entry["authenticated"] for entry in catalog["models"]} == {False}
    assert {entry["ready"] for entry in catalog["models"]} == {False}
    assert {
        key: catalog[key]
        for key in (
            "default",
            "provider",
            "authenticated",
            "ready",
            "authReason",
            "policyBlocked",
            "blockedReason",
            "policyVersion",
            "allowedModelsVersion",
        )
    } == {
        "default": BETA_DEFAULT_MODEL,
        "provider": BETA_ALLOWED_PROVIDER,
        "authenticated": False,
        "ready": False,
        "authReason": "missing_auth_store",
        "policyBlocked": False,
        "blockedReason": None,
        "policyVersion": BETA_PROVIDER_POLICY_VERSION,
        "allowedModelsVersion": BETA_ALLOWED_MODELS_VERSION,
    }
    assert discovery_calls == []
    assert not beta_home.exists()


def test_beta_catalog_routes_use_fake_local_auth_and_block_other_providers(
    beta_home,
    monkeypatch,
):
    _write_fake_codex_auth(beta_home)
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: {
            "model": {
                "provider": BETA_ALLOWED_PROVIDER,
                "default": BETA_DEFAULT_MODEL,
            }
        },
    )
    discovery_calls = _block_generic_discovery(monkeypatch)
    auth_bytes = (beta_home / "auth.json").read_bytes()
    before = set(beta_home.rglob("*"))
    client = _config_client()

    available = client.get("/api/models/available")
    by_provider = client.get(
        "/api/models/by-provider",
        params={"provider": BETA_ALLOWED_PROVIDER},
    )
    implicit_provider = client.get("/api/models/by-provider")
    blocked = client.get(
        "/api/models/by-provider",
        params={"provider": "anthropic"},
    )

    assert available.status_code == 200
    available_body = available.json()
    assert [entry["id"] for entry in available_body["models"]] == list(
        BETA_ALLOWED_MODELS
    )
    assert available_body["authenticated"] is True
    assert available_body["ready"] is True
    assert available_body["allowedModelsVersion"] == BETA_ALLOWED_MODELS_VERSION

    for response in (by_provider, implicit_provider):
        assert response.status_code == 200
        assert response.json() == {
            "provider": BETA_ALLOWED_PROVIDER,
            "models": list(BETA_ALLOWED_MODELS),
            "default": BETA_DEFAULT_MODEL,
            "authenticated": True,
            "ready": True,
            "authReason": None,
            "policyBlocked": False,
            "blockedReason": None,
            "policyVersion": BETA_PROVIDER_POLICY_VERSION,
            "allowedModelsVersion": BETA_ALLOWED_MODELS_VERSION,
        }

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "beta_provider_not_allowed"
    assert discovery_calls == []
    assert (beta_home / "auth.json").read_bytes() == auth_bytes
    assert set(beta_home.rglob("*")) == before
    assert not (beta_home / tier_resolver.TIER_CONFIG_FILENAME).exists()


def test_beta_catalog_marks_hostile_existing_fallback_not_ready(
    beta_home,
    monkeypatch,
):
    _write_fake_codex_auth(beta_home)
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: {
            "model": {
                "provider": BETA_ALLOWED_PROVIDER,
                "default": BETA_DEFAULT_MODEL,
            },
            "fallback_model": {
                "provider": "anthropic",
                "model": "hostile-fallback",
            },
        },
    )
    discovery_calls = _block_generic_discovery(monkeypatch)
    before = (beta_home / "auth.json").read_bytes()

    catalog = tier_resolver.list_available_models()

    assert [entry["id"] for entry in catalog["models"]] == list(BETA_ALLOWED_MODELS)
    assert {entry["provider"] for entry in catalog["models"]} == {
        BETA_ALLOWED_PROVIDER
    }
    assert catalog["authenticated"] is True
    assert catalog["ready"] is False
    assert catalog["policyBlocked"] is True
    assert catalog["blockedReason"] == "beta_fallback_not_allowed"
    assert discovery_calls == []
    assert (beta_home / "auth.json").read_bytes() == before


@pytest.mark.parametrize(
    ("mapping", "code"),
    [
        (
            {
                "draft": {
                    "model": BETA_DEFAULT_MODEL,
                    "provider": "anthropic",
                }
            },
            "beta_provider_not_allowed",
        ),
        (
            {
                "draft": {
                    "model": "hostile-model",
                    "provider": BETA_ALLOWED_PROVIDER,
                }
            },
            "beta_model_not_allowed",
        ),
        (
            {
                "draft": {
                    "model": BETA_DEFAULT_MODEL,
                    "provider": BETA_ALLOWED_PROVIDER,
                    "fallback": {
                        "provider": "anthropic",
                        "model": "hostile-fallback",
                    },
                }
            },
            "beta_fallback_not_allowed",
        ),
    ],
)
def test_beta_tier_save_rejects_hostile_mapping_before_home_mutation(
    beta_home,
    mapping,
    code,
):
    assert not beta_home.exists()

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        tier_resolver.save_tier_config(mapping)

    assert exc_info.value.code == code
    assert not beta_home.exists()


def test_beta_tier_save_requires_current_profile_auth_before_home_mutation(beta_home):
    assert not beta_home.exists()

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        tier_resolver.save_tier_config(_valid_mapping())

    assert exc_info.value.code == "beta_codex_auth_required"
    assert not beta_home.exists()


def test_beta_tier_rejection_preserves_existing_bytes_and_creates_no_temp(
    beta_home,
):
    beta_home.mkdir(parents=True)
    tier_path = beta_home / tier_resolver.TIER_CONFIG_FILENAME
    before = b'{"draft":{"model":"gpt-5.5","provider":"openai-codex"}}\n'
    tier_path.write_bytes(before)

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        tier_resolver.save_tier_config({
            "draft": {
                "model": BETA_DEFAULT_MODEL,
                "provider": "openrouter",
            }
        })

    assert exc_info.value.code == "beta_provider_not_allowed"
    assert tier_path.read_bytes() == before
    assert not tier_path.with_suffix(".json.tmp").exists()


def test_beta_tier_save_persists_only_canonical_authenticated_mapping(beta_home):
    _write_fake_codex_auth(beta_home)

    path = tier_resolver.save_tier_config(_valid_mapping())

    assert json.loads(path.read_text(encoding="utf-8")) == _valid_mapping()
    assert not path.with_suffix(".json.tmp").exists()


def test_beta_resolution_rejects_hostile_existing_mapping_before_fallback(
    beta_home,
    monkeypatch,
):
    beta_home.mkdir(parents=True)
    tier_path = beta_home / tier_resolver.TIER_CONFIG_FILENAME
    before = json.dumps({
        "draft": {
            "model": BETA_DEFAULT_MODEL,
            "provider": "anthropic",
        }
    }).encode()
    tier_path.write_bytes(before)
    discovery_calls = _block_generic_discovery(monkeypatch)

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        tier_resolver.resolve_tier_with_provider("utility")

    assert exc_info.value.code == "beta_provider_not_allowed"
    assert discovery_calls == []
    assert tier_path.read_bytes() == before


def test_beta_resolution_rejects_malformed_existing_mapping_before_fallback(
    beta_home,
    monkeypatch,
):
    beta_home.mkdir(parents=True)
    tier_path = beta_home / tier_resolver.TIER_CONFIG_FILENAME
    before = b'{"draft":'
    tier_path.write_bytes(before)
    discovery_calls = _block_generic_discovery(monkeypatch)

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        tier_resolver.resolve_tier_with_provider("utility")

    assert exc_info.value.code == "beta_tier_mapping_invalid"
    assert discovery_calls == []
    assert tier_path.read_bytes() == before


def test_beta_resolution_never_returns_an_alternate_provider(
    beta_home,
    monkeypatch,
):
    _write_fake_codex_auth(beta_home)
    tier_resolver.save_tier_config(_valid_mapping())
    discovery_calls = _block_generic_discovery(monkeypatch)

    resolved = {
        tier_id: tier_resolver.resolve_tier_with_provider(tier_id)
        for tier_id in tier_resolver.VALID_TIERS
    }

    assert {provider for _model, provider in resolved.values()} == {
        BETA_ALLOWED_PROVIDER
    }
    assert {model for model, _provider in resolved.values()} <= set(BETA_ALLOWED_MODELS)
    assert discovery_calls == []


def test_beta_resolution_rejects_hostile_config_fallback_before_discovery(
    beta_home,
    monkeypatch,
):
    _write_fake_codex_auth(beta_home)
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: {
            "model": {
                "provider": BETA_ALLOWED_PROVIDER,
                "default": BETA_DEFAULT_MODEL,
            },
            "fallback_providers": [
                {"provider": "openrouter", "model": "hostile-fallback"}
            ],
        },
    )
    discovery_calls = _block_generic_discovery(monkeypatch)

    with pytest.raises(BetaProviderPolicyError) as exc_info:
        tier_resolver.resolve_tier_with_provider("utility")

    assert exc_info.value.code == "beta_fallback_not_allowed"
    assert discovery_calls == []
    assert not (beta_home / tier_resolver.TIER_CONFIG_FILENAME).exists()


def test_beta_tier_route_returns_typed_auth_error_before_mutation(beta_home):
    response = _config_client().put(
        "/api/config/tiers",
        json={"mapping": _valid_mapping()},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "beta_codex_auth_required"
    assert not beta_home.exists()


def test_non_beta_catalog_and_tier_persistence_remain_api_and_byte_compatible(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "stable"
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    entries = [{
        "id": "stable-model",
        "provider": "anthropic",
        "source": "harness",
        "tier_hint": "mid",
        "authenticated": True,
    }]
    monkeypatch.setattr(tier_resolver, "_enumerate_available_models", lambda: entries)
    monkeypatch.setattr(
        tier_resolver,
        "_harness_default_model",
        lambda: ("stable-model", "anthropic"),
    )

    assert tier_resolver.list_available_models() == {
        "models": entries,
        "default": "stable-model",
    }

    path = tier_resolver.save_tier_config({
        "draft": {"model": "stable-model", "provider": "anthropic"},
        "send": "stable-fast-model",
    })
    expected = {
        "draft": {"model": "stable-model", "provider": "anthropic"},
        "send": {"model": "stable-fast-model"},
    }
    assert path.read_text(encoding="utf-8") == json.dumps(
        expected,
        indent=2,
        sort_keys=True,
    )


def test_non_beta_provider_route_keeps_generic_api_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path / "stable"))
    calls = []
    monkeypatch.setattr(
        models_module,
        "normalize_provider",
        lambda provider: calls.append(("normalize", provider)) or "anthropic",
    )
    monkeypatch.setattr(
        models_module,
        "provider_model_ids",
        lambda provider: calls.append(("models", provider)) or ["stable-model"],
    )

    response = _config_client().get(
        "/api/models/by-provider",
        params={"provider": "claude"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "anthropic",
        "models": ["stable-model"],
    }
    assert calls == [("normalize", "claude"), ("models", "anthropic")]
