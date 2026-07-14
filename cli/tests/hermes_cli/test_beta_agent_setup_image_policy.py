"""Realtor Beta image services must stay on the signed-pack credential lane."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import sqlite3
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli.config import get_config_path, get_env_path
from elevate_cli.web_routes import admin_setup


def _client(monkeypatch, connection):
    import elevate_cli.data as data_module

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(data_module, "connect", connect)
    app = FastAPI()
    app.include_router(admin_setup.create_admin_setup_router(web_actor="test"))
    return TestClient(app), data_module


@pytest.mark.parametrize(
    "item",
    [
        {
            "key": "model_image",
            "status": "configured",
            "provider": "gemini",
            "value": {"apiKey": "gemini-secret"},
        },
        {
            "key": "model_image",
            "status": "configured",
            "provider": "nano_banana",
            "value": {"apiKey": "", "usesEnvSecret": True},
        },
        {
            "key": "model_image",
            "status": "configured",
            "provider": "openai_images",
            "value": {"apiKey": ""},
        },
        {
            "key": "model_image",
            "status": "missing",
            "provider": None,
            "value": {"apiKey": "provider-secret"},
        },
        {
            "key": "model_image",
            "status": "missing",
            "provider": None,
            "value": {"runtimeProvider": "replicate"},
        },
    ],
)
def test_beta_image_provider_rejection_is_typed_and_byte_atomic(
    monkeypatch,
    tmp_path,
    item,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config_path = get_config_path()
    env_path = get_env_path()
    config_path.write_bytes(b"model:\n  provider: openai-codex\n  default: gpt-5.5\n")
    env_path.write_bytes(b"EXISTING_MARKER=unchanged\n")

    db_path = tmp_path / "agent-setup.db"
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    connection.execute("INSERT INTO sentinel(value) VALUES ('unchanged')")
    connection.commit()

    client, data_module = _client(monkeypatch, connection)
    env_writer = MagicMock()
    setup_writer = MagicMock()
    config_writer = MagicMock()
    auth_reader = MagicMock(
        side_effect=AssertionError("image rejection must precede auth")
    )
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)
    monkeypatch.setattr(data_module, "update_agent_setup", setup_writer)
    monkeypatch.setattr(
        admin_setup,
        "_materialize_agent_setup_to_config",
        config_writer,
    )
    monkeypatch.setattr(admin_setup, "read_beta_codex_auth_status", auth_reader)

    before = {
        "config": config_path.read_bytes(),
        "env": env_path.read_bytes(),
        "db": db_path.read_bytes(),
    }
    response = client.put("/api/agent/setup", json={"items": [item]})
    connection.close()

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "beta_image_provider_not_allowed"
    assert detail["policyVersion"]
    assert config_path.read_bytes() == before["config"]
    assert env_path.read_bytes() == before["env"]
    assert db_path.read_bytes() == before["db"]
    auth_reader.assert_not_called()
    env_writer.assert_not_called()
    setup_writer.assert_not_called()
    config_writer.assert_not_called()


class _NoPrimaryConnection:
    def execute(self, _query, _params):
        class _Cursor:
            @staticmethod
            def fetchone():
                return None

        return _Cursor()


def test_beta_empty_image_placeholder_and_hostile_embedding_are_safe_before_writes(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        admin_setup,
        "read_beta_codex_auth_status",
        lambda _home: {"logged_in": True},
    )
    monkeypatch.setattr(admin_setup, "load_config", lambda: {})
    env_writer = MagicMock()
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)
    items = [
        {
            "key": "model_image",
            "status": "missing",
            "provider": None,
            "value": {"apiKey": "", "usesEnvSecret": False},
        },
        {
            "key": "model_embedding",
            "status": "configured",
            "provider": "gemini",
            "value": {
                "model": "hostile-embedding",
                "apiKey": "must-not-materialize",
                "usesEnvSecret": True,
            },
        },
    ]

    validated = admin_setup._preflight_beta_agent_setup_update(
        _NoPrimaryConnection(),
        deepcopy(items),
    )
    safe = admin_setup._materialize_agent_setup_secrets(validated)

    by_key = {item["key"]: item for item in safe}
    assert by_key["model_image"] == items[0]
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
    assert "must-not-materialize" not in repr(safe)
    env_writer.assert_not_called()


def test_nonexact_beta_keeps_legacy_image_provider_materialization(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    env_writer = MagicMock()
    monkeypatch.setattr(admin_setup, "save_env_value", env_writer)
    items = [
        {
            "key": "model_image",
            "status": "configured",
            "provider": "gemini",
            "value": {"apiKey": "legacy-gemini-secret"},
        }
    ]

    validated = admin_setup._preflight_beta_agent_setup_update(
        object(),
        deepcopy(items),
    )
    safe = admin_setup._materialize_agent_setup_secrets(validated)

    env_writer.assert_called_once_with("GEMINI_API_KEY", "legacy-gemini-secret")
    assert safe[0]["value"] == {"apiKey": "", "usesEnvSecret": True}
