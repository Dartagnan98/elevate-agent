"""Fail-closed OAuth containment for the exact Realtor Beta lane."""

from __future__ import annotations

import copy
import json
import sys
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli import auth as auth_module
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    read_beta_codex_auth_status,
)
from elevate_cli.web_routes import oauth


NON_CODEX_PROVIDERS = tuple(
    provider["id"]
    for provider in oauth._OAUTH_PROVIDER_CATALOG
    if provider["id"] != BETA_ALLOWED_PROVIDER
)


@pytest.fixture(autouse=True)
def _isolated_beta_oauth(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    with oauth._oauth_sessions_lock:
        oauth._oauth_sessions.clear()
    yield
    with oauth._oauth_sessions_lock:
        oauth._oauth_sessions.clear()


def _client(require_token=None) -> TestClient:
    application = FastAPI()
    application.include_router(
        oauth.create_oauth_router(require_token=require_token or (lambda _request: None))
    )
    return TestClient(application)


def _provider_state_payload() -> dict:
    return {
        "active_provider": BETA_ALLOWED_PROVIDER,
        "providers": {
            BETA_ALLOWED_PROVIDER: {
                "tokens": {
                    "access_token": "fake-access-token",
                    "refresh_token": "fake-refresh-token",
                },
                "auth_mode": "chatgpt",
            },
        },
    }


def test_beta_catalog_exposes_only_codex_and_reads_current_home_status(
    tmp_path,
    monkeypatch,
):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps(_provider_state_payload()), encoding="utf-8")
    actual_reader = oauth.read_beta_codex_auth_status
    inspected = []

    def audited_reader(home):
        inspected.append(home)
        return actual_reader(home)

    monkeypatch.setattr(oauth, "read_beta_codex_auth_status", audited_reader)
    monkeypatch.setattr(
        oauth,
        "_resolve_provider_status",
        lambda *_args, **_kwargs: pytest.fail(
            "Beta OAuth catalog used a general provider status helper"
        ),
    )

    response = _client().get("/api/providers/oauth")

    assert response.status_code == 200
    providers = response.json()["providers"]
    assert [provider["id"] for provider in providers] == [BETA_ALLOWED_PROVIDER]
    assert inspected == [tmp_path]
    status = providers[0]["status"]
    assert status == {
        "logged_in": True,
        "source": "provider_state",
        "source_label": "Current Realtor Beta profile",
        "token_preview": "",
        "expires_at": None,
        "has_refresh_token": True,
        "auth_store": str(auth_path),
        "reason": None,
    }
    assert "fake-access-token" not in response.text
    assert "fake-refresh-token" not in response.text


def test_beta_catalog_rejects_symlinked_current_home_auth(tmp_path, monkeypatch):
    borrowed = tmp_path / "borrowed-auth.json"
    borrowed.write_text(json.dumps(_provider_state_payload()), encoding="utf-8")
    (tmp_path / "auth.json").symlink_to(borrowed)
    monkeypatch.setattr(
        oauth,
        "_resolve_provider_status",
        lambda *_args, **_kwargs: pytest.fail(
            "Beta OAuth catalog fell back to general auth status"
        ),
    )

    response = _client().get("/api/providers/oauth")

    assert response.status_code == 200
    status = response.json()["providers"][0]["status"]
    assert status["logged_in"] is False
    assert status["source"] is None
    assert status["reason"] == "non_local_auth_store"
    assert "fake-access-token" not in response.text


def test_beta_non_codex_paths_fail_before_session_auth_or_provider_mutation(
    tmp_path,
    monkeypatch,
):
    auth_path = tmp_path / "auth.json"
    auth_path.write_bytes(b'{"sentinel":"unchanged"}')
    sentinel_session = {
        "session_id": "sentinel-session",
        "provider": BETA_ALLOWED_PROVIDER,
        "flow": "device_code",
        "created_at": 1.0,
        "status": "pending",
        "error_message": None,
    }
    oauth._oauth_sessions["sentinel-session"] = sentinel_session
    before_sessions = copy.deepcopy(oauth._oauth_sessions)
    before_auth = auth_path.read_bytes()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("blocked Beta OAuth path reached a mutation boundary")

    async def unexpected_async(*_args, **_kwargs):
        unexpected()

    monkeypatch.setattr(oauth, "_gc_oauth_sessions", unexpected)
    monkeypatch.setattr(oauth, "_start_anthropic_pkce", unexpected)
    monkeypatch.setattr(oauth, "_start_device_code_flow", unexpected_async)
    monkeypatch.setattr(oauth, "_submit_anthropic_pkce", unexpected)
    monkeypatch.setattr(auth_module, "clear_provider_auth", unexpected)
    token_checks = []
    client = _client(require_token=lambda _request: token_checks.append(True))

    for provider_id in NON_CODEX_PROVIDERS:
        responses = (
            client.delete(f"/api/providers/oauth/{provider_id}"),
            client.post(f"/api/providers/oauth/{provider_id}/start"),
            client.post(
                f"/api/providers/oauth/{provider_id}/submit",
                json={"session_id": "sentinel-session", "code": "fake-code"},
            ),
            client.get(
                f"/api/providers/oauth/{provider_id}/poll/sentinel-session"
            ),
        )
        for response in responses:
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "beta_provider_not_allowed"
            assert response.json()["detail"]["allowedProvider"] == BETA_ALLOWED_PROVIDER

    assert len(token_checks) == len(NON_CODEX_PROVIDERS) * 3
    assert oauth._oauth_sessions == before_sessions
    assert auth_path.read_bytes() == before_auth


def test_beta_codex_start_poll_and_disconnect_remain_available(monkeypatch):
    started = []
    cleared = []

    async def fake_start(provider_id):
        started.append(provider_id)
        return {
            "session_id": "codex-session",
            "flow": "device_code",
            "user_code": "FAKE-CODE",
            "verification_url": "https://auth.openai.invalid/device",
            "expires_in": 900,
            "poll_interval": 5,
        }

    monkeypatch.setattr(oauth, "_start_device_code_flow", fake_start)
    monkeypatch.setattr(oauth, "_gc_oauth_sessions", lambda: None)
    monkeypatch.setattr(
        auth_module,
        "clear_provider_auth",
        lambda provider_id: cleared.append(provider_id) or True,
    )
    oauth._oauth_sessions["codex-session"] = {
        "session_id": "codex-session",
        "provider": BETA_ALLOWED_PROVIDER,
        "flow": "device_code",
        "created_at": 1.0,
        "status": "approved",
        "error_message": None,
    }
    client = _client()

    start = client.post(f"/api/providers/oauth/{BETA_ALLOWED_PROVIDER}/start")
    poll = client.get(
        f"/api/providers/oauth/{BETA_ALLOWED_PROVIDER}/poll/codex-session"
    )
    disconnect = client.delete(f"/api/providers/oauth/{BETA_ALLOWED_PROVIDER}")

    assert start.status_code == 200
    assert poll.status_code == 200
    assert poll.json()["status"] == "approved"
    assert disconnect.status_code == 200
    assert disconnect.json()["ok"] is True
    assert started == [BETA_ALLOWED_PROVIDER]
    assert cleared == [BETA_ALLOWED_PROVIDER]


def test_stable_catalog_and_non_codex_route_behavior_are_unchanged(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    status_calls = []
    cleared = []

    def fake_status(provider_id, _status_fn):
        status_calls.append(provider_id)
        return {"logged_in": False, "source": provider_id}

    monkeypatch.setattr(oauth, "_resolve_provider_status", fake_status)
    monkeypatch.setattr(oauth, "_gc_oauth_sessions", lambda: None)
    monkeypatch.setattr(
        oauth,
        "_start_anthropic_pkce",
        lambda: {"session_id": "stable-pkce", "flow": "pkce"},
    )
    monkeypatch.setattr(
        oauth,
        "_submit_anthropic_pkce",
        lambda session_id, code: {
            "ok": True,
            "status": "approved",
            "session_id": session_id,
            "code": code,
        },
    )
    monkeypatch.setattr(
        auth_module,
        "clear_provider_auth",
        lambda provider_id: cleared.append(provider_id) or True,
    )
    oauth._oauth_sessions["stable-session"] = {
        "session_id": "stable-session",
        "provider": "anthropic",
        "flow": "pkce",
        "created_at": 1.0,
        "status": "approved",
        "error_message": None,
    }
    client = _client()

    listed = client.get("/api/providers/oauth")
    start = client.post("/api/providers/oauth/anthropic/start")
    submit = client.post(
        "/api/providers/oauth/anthropic/submit",
        json={"session_id": "stable-session", "code": "stable-code"},
    )
    poll = client.get("/api/providers/oauth/anthropic/poll/stable-session")
    disconnect = client.delete("/api/providers/oauth/nous")

    expected_ids = [provider["id"] for provider in oauth._OAUTH_PROVIDER_CATALOG]
    assert listed.status_code == 200
    assert [provider["id"] for provider in listed.json()["providers"]] == expected_ids
    assert status_calls == expected_ids
    assert start.status_code == 200
    assert submit.status_code == 200
    assert submit.json()["status"] == "approved"
    assert poll.status_code == 200
    assert disconnect.status_code == 200
    assert cleared == ["nous"]


def _install_fake_httpx(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            if url.endswith("/api/accounts/deviceauth/usercode"):
                return FakeResponse(200, {
                    "user_code": "FAKE-CODE",
                    "device_auth_id": "fake-device-id",
                    "interval": "3",
                })
            if url.endswith("/api/accounts/deviceauth/token"):
                return FakeResponse(200, {
                    "authorization_code": "fake-authorization-code",
                    "code_verifier": "fake-code-verifier",
                })
            if url == auth_module.CODEX_OAUTH_TOKEN_URL:
                return FakeResponse(200, {
                    "access_token": "fake-access-token",
                    "refresh_token": "fake-refresh-token",
                })
            raise AssertionError(f"unexpected OAuth URL: {url}")

    fake_httpx = ModuleType("httpx")
    fake_httpx.Client = FakeClient
    fake_httpx.Timeout = lambda value: value
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setattr(oauth.time, "sleep", lambda _seconds: None)
    return calls


def test_beta_codex_completion_persists_runtime_provider_state_and_canonical_url(
    tmp_path,
    monkeypatch,
):
    http_calls = _install_fake_httpx(monkeypatch)
    pool_calls = []
    monkeypatch.setattr(
        oauth,
        "_add_codex_pool_credential",
        lambda access_token, refresh_token, *, base_url: pool_calls.append({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "base_url": base_url,
        }),
    )
    hostile_url = "https://codex.attacker.invalid/v1"
    monkeypatch.setenv("ELEVATE_CODEX_BASE_URL", hostile_url)
    session_id, _ = oauth._new_oauth_session(BETA_ALLOWED_PROVIDER, "device_code")

    oauth._codex_full_login_worker(session_id)

    session = oauth._oauth_sessions[session_id]
    assert session["status"] == "approved"
    assert pool_calls == [{
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "base_url": BETA_CODEX_BASE_URL,
    }]
    assert hostile_url not in (tmp_path / "auth.json").read_text(encoding="utf-8")
    assert [call["url"] for call in http_calls] == [
        "https://auth.openai.com/api/accounts/deviceauth/usercode",
        "https://auth.openai.com/api/accounts/deviceauth/token",
        auth_module.CODEX_OAUTH_TOKEN_URL,
    ]

    status = read_beta_codex_auth_status(tmp_path)
    assert status["logged_in"] is True
    assert status["source"] == "provider_state"
    monkeypatch.delenv("ELEVATE_CODEX_BASE_URL")
    runtime = auth_module.resolve_codex_runtime_credentials(
        refresh_if_expiring=False,
    )
    assert runtime["provider"] == BETA_ALLOWED_PROVIDER
    assert runtime["source"] == "elevate-auth-store"
    assert runtime["base_url"] == BETA_CODEX_BASE_URL
    assert runtime["api_key"] == "fake-access-token"


def test_stable_codex_completion_preserves_pool_only_and_endpoint_override(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    _install_fake_httpx(monkeypatch)
    pool_calls = []
    monkeypatch.setattr(
        oauth,
        "_add_codex_pool_credential",
        lambda access_token, refresh_token, *, base_url: pool_calls.append({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "base_url": base_url,
        }),
    )
    monkeypatch.setattr(
        auth_module,
        "_save_codex_tokens",
        lambda *_args, **_kwargs: pytest.fail(
            "Stable dashboard flow unexpectedly wrote Codex provider state"
        ),
    )
    stable_url = "https://stable-codex.invalid/v1"
    monkeypatch.setenv("ELEVATE_CODEX_BASE_URL", stable_url)
    session_id, _ = oauth._new_oauth_session(BETA_ALLOWED_PROVIDER, "device_code")

    oauth._codex_full_login_worker(session_id)

    session = oauth._oauth_sessions[session_id]
    assert session["status"] == "approved"
    assert pool_calls == [{
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "base_url": stable_url,
    }]
    assert not (tmp_path / "auth.json").exists()
