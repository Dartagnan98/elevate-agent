"""Realtor Beta onboarding cannot materialize remote memory or embeddings."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli import config as config_module
from elevate_cli.beta_provider_policy import BetaProviderPolicyError
from elevate_cli.data import agent_setup as agent_setup_data
from elevate_cli.web_routes import admin_setup


class _NoQueryConnection:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("policy rejection must not query or mutate setup state")


def _client(monkeypatch, connection):
    import elevate_cli.data as data_module

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(data_module, "connect", connect)
    app = FastAPI()
    app.include_router(admin_setup.create_admin_setup_router(web_actor="test"))
    return TestClient(app), data_module


def _primary_item():
    return {
        "key": "model_primary",
        "status": "configured",
        "provider": "openai-codex",
        "value": {
            "model": "gpt-5.5",
            "runtimeProvider": "openai-codex",
            "apiKey": "",
        },
    }


def _current_primary_config():
    return {
        "model": {
            "provider": "openai-codex",
            "default": "gpt-5.5",
        }
    }


def test_beta_agent_setup_recovers_remote_memory_without_secret_side_effects(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    connection = _NoQueryConnection()
    client, data_module = _client(monkeypatch, connection)
    captured = []
    config_materializer = MagicMock(return_value={})
    env_write = MagicMock()
    monkeypatch.setattr(
        admin_setup,
        "read_beta_codex_auth_status",
        lambda _home: {"logged_in": True},
    )
    monkeypatch.setattr(
        admin_setup,
        "load_config",
        lambda: deepcopy(_current_primary_config()),
    )
    monkeypatch.setattr(
        admin_setup,
        "_materialize_agent_setup_to_config",
        config_materializer,
    )
    monkeypatch.setattr(admin_setup, "save_env_value", env_write)
    monkeypatch.setattr(
        data_module,
        "update_agent_setup",
        lambda _conn, *, items: captured.extend(deepcopy(items)),
    )
    monkeypatch.setattr(
        data_module,
        "get_agent_setup",
        lambda _conn: {"items": deepcopy(captured)},
    )

    response = client.put(
        "/api/agent/setup",
        json={
            "items": [
                _primary_item(),
                {
                    "key": "memory_store",
                    "status": "configured",
                    "provider": "supabase",
                    "value": {
                        "supabaseUrl": "https://remote.invalid",
                        "supabaseKey": "must-not-write",
                    },
                },
                {
                    "key": "model_embedding",
                    "status": "configured",
                    "provider": "voyage",
                    "value": {"apiKey": "must-not-write"},
                },
            ]
        },
    )

    assert response.status_code == 200
    by_key = {item["key"]: item for item in captured}
    assert by_key["memory_store"]["provider"] == "sqlite_local"
    assert by_key["memory_store"]["value"] == {"mode": "local"}
    assert by_key["model_embedding"]["status"] == "skipped"
    assert by_key["model_embedding"]["provider"] is None
    assert "must-not-write" not in repr(captured)
    config_materializer.assert_called_once_with(connection)
    env_write.assert_not_called()


@pytest.mark.parametrize("memory_provider", ["sqlite_local", "holographic", ""])
def test_beta_agent_setup_canonicalizes_local_memory_and_skips_embeddings(
    monkeypatch,
    memory_provider,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    connection = _NoQueryConnection()
    client, data_module = _client(monkeypatch, connection)
    captured = []
    env_write = MagicMock()
    monkeypatch.setattr(
        admin_setup,
        "read_beta_codex_auth_status",
        lambda _home: {"logged_in": True},
    )
    monkeypatch.setattr(
        admin_setup,
        "load_config",
        lambda: deepcopy(_current_primary_config()),
    )
    monkeypatch.setattr(admin_setup, "save_env_value", env_write)
    monkeypatch.setattr(
        data_module,
        "update_agent_setup",
        lambda _conn, *, items: captured.extend(deepcopy(items)),
    )
    monkeypatch.setattr(
        data_module,
        "get_agent_setup",
        lambda _conn: {"items": deepcopy(captured)},
    )
    monkeypatch.setattr(
        admin_setup,
        "_materialize_agent_setup_to_config",
        lambda _conn: {},
    )

    response = client.put(
        "/api/agent/setup",
        json={
            "items": [
                _primary_item(),
                {
                    "key": "memory_store",
                    "status": "configured",
                    "provider": memory_provider,
                    "value": {
                        "mode": "local",
                        "supabaseKey": "must-not-write",
                    },
                },
                {
                    "key": "model_embedding",
                    "status": "configured",
                    "provider": "voyage",
                    "value": {
                        "model": "voyage-3",
                        "apiKey": "must-not-write",
                    },
                },
            ]
        },
    )

    assert response.status_code == 200
    by_key = {item["key"]: item for item in captured}
    assert by_key["memory_store"] == {
        "key": "memory_store",
        "status": "configured",
        "provider": "sqlite_local",
        "value": {"mode": "local"},
        "notes": "Realtor Beta stores memory locally on this Mac.",
    }
    assert by_key["model_embedding"] == {
        "key": "model_embedding",
        "status": "skipped",
        "provider": None,
        "value": {
            "policyBlocked": True,
            "blockedReason": "unsupported_beta_embedding",
        },
        "notes": "Realtor Beta uses local memory without embedding-based recall.",
    }
    env_write.assert_not_called()


class _SetupRowsConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query):
        rows = self.rows

        class _Cursor:
            def fetchall(self):
                return rows

        return _Cursor()


def test_beta_config_materializer_repairs_stale_setup_rows(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config = {
        "memory": {"provider": "supabase"},
        "plugins": {
            "elevate-memory-store": {
                "embedding_enabled": True,
                "embedding_provider": "voyage",
                "embedding_model": "voyage-3",
                "embedding_base_url": "https://remote.invalid",
                "embedding_api_key_env": "VOYAGE_API_KEY",
            }
        },
    }
    rows = [
        {
            "key": "memory_store",
            "status": "configured",
            "provider": "supabase",
            "value_json": json.dumps({"supabaseUrl": "https://remote.invalid"}),
        },
        {
            "key": "model_embedding",
            "status": "configured",
            "provider": "voyage",
            "value_json": json.dumps({"model": "voyage-3"}),
        },
    ]
    saved = []
    monkeypatch.setattr(config_module, "load_config", lambda: deepcopy(config))
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda value: saved.append(deepcopy(value)),
    )

    applied = admin_setup._materialize_agent_setup_to_config(
        _SetupRowsConnection(rows)
    )

    assert applied == {
        "embedding": {"status": "skipped"},
        "memory": {"provider": "holographic"},
    }
    assert saved[0]["memory"]["provider"] == "holographic"
    store = saved[0]["plugins"]["elevate-memory-store"]
    assert store["embedding_enabled"] is False
    assert "embedding_provider" not in store
    assert "embedding_model" not in store
    assert "embedding_base_url" not in store
    assert "embedding_api_key_env" not in store


def test_beta_setup_runtime_overlay_ignores_ambient_remote_memory(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai")
    monkeypatch.setenv("VOYAGE_API_KEY", "ambient-voyage")
    monkeypatch.setenv("SUPABASE_URL", "https://remote.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "ambient-supabase")
    monkeypatch.setattr(config_module, "load_config", lambda: {"model": {}})
    monkeypatch.setattr(config_module, "load_env", lambda: {})

    overlays = agent_setup_data._detect_runtime_credentials()

    assert "model_embedding" not in overlays
    assert overlays["memory_store"] == {
        "status": "configured",
        "provider": "sqlite_local",
        "value": {"mode": "local"},
    }


def test_non_exact_beta_keeps_agent_setup_items_unchanged(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    items = [
        {
            "key": "memory_store",
            "status": "configured",
            "provider": "supabase",
            "value": {"supabaseKey": "stable-secret"},
        },
        {
            "key": "model_embedding",
            "status": "configured",
            "provider": "voyage",
            "value": {"apiKey": "stable-secret"},
        },
    ]

    assert admin_setup._preflight_beta_agent_setup_update(
        _NoQueryConnection(),
        items,
    ) == items


def test_beta_agent_setup_route_rejects_allowed_model_drift_before_db_write(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    connection = _NoQueryConnection()
    client, data_module = _client(monkeypatch, connection)
    setup_writer = MagicMock()
    materializer = MagicMock()
    env_writer = MagicMock()
    monkeypatch.setattr(
        admin_setup,
        "read_beta_codex_auth_status",
        lambda _home: {"logged_in": True},
    )
    monkeypatch.setattr(
        admin_setup,
        "load_config",
        lambda: {
            "model": {
                "provider": "openai-codex",
                "default": "gpt-5.5",
            }
        },
    )
    monkeypatch.setattr(data_module, "update_agent_setup", setup_writer)
    monkeypatch.setattr(
        admin_setup,
        "_materialize_agent_setup_to_config",
        materializer,
    )
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)
    drifted = _primary_item()
    drifted["value"]["model"] = "gpt-5.4"

    response = client.put("/api/agent/setup", json={"items": [drifted]})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "beta_app_onboarding_required"
    setup_writer.assert_not_called()
    materializer.assert_not_called()
    env_writer.assert_not_called()


def test_beta_config_materializer_rejects_model_drift_without_config_write(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config = {
        "model": {
            "provider": "openai-codex",
            "default": "gpt-5.5",
        }
    }
    before = deepcopy(config)
    rows = [
        {
            "key": "model_primary",
            "status": "configured",
            "provider": "openai-codex",
            "value_json": json.dumps(
                {
                    "model": "gpt-5.4",
                    "runtimeProvider": "openai-codex",
                    "apiKey": "",
                }
            ),
        }
    ]
    saved = []
    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", saved.append)

    with pytest.raises(BetaProviderPolicyError) as caught:
        admin_setup._materialize_agent_setup_to_config(
            _SetupRowsConnection(rows)
        )

    assert getattr(caught.value, "code", None) == "beta_app_onboarding_required"
    assert config == before
    assert saved == []


def test_beta_config_materializer_only_verifies_matching_primary_model(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config = {
        "model": {
            "provider": "openai-codex",
            "default": "gpt-5.5",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        }
    }
    before = deepcopy(config)
    rows = [
        {
            "key": "model_primary",
            "status": "configured",
            "provider": "openai-codex",
            "value_json": json.dumps(
                {
                    "model": "gpt-5.5",
                    "runtimeProvider": "openai-codex",
                    "apiKey": "",
                }
            ),
        }
    ]
    saved = []
    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", saved.append)

    applied = admin_setup._materialize_agent_setup_to_config(
        _SetupRowsConnection(rows)
    )

    assert applied["model"] == {
        "provider": "openai-codex",
        "model": "gpt-5.5",
        "status": "verified",
    }
    assert applied["embedding"] == {"status": "skipped"}
    assert applied["memory"] == {"provider": "holographic"}
    assert config["model"] == before["model"]
    assert saved[0]["model"] == before["model"]
    assert len(saved) == 1
