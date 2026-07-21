"""Fail-closed OAuth containment for the exact Realtor Beta lane."""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from elevate_cli import auth as auth_module
from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    beta_runtime_repair_blocked_reason,
    beta_runtime_repair_generation,
    clear_beta_runtime_repair_state,
    read_beta_codex_auth_status,
)
from elevate_cli.env_loader import load_elevate_dotenv
from elevate_cli.web_routes import oauth
from elevate_cli.web_routes.status import _beta_runtime_receipt


NON_CODEX_PROVIDERS = tuple(
    provider["id"]
    for provider in oauth._OAUTH_PROVIDER_CATALOG
    if provider["id"] != BETA_ALLOWED_PROVIDER
)


def _release_test_delegate_repair_leases() -> None:
    """Keep a failed real-server repair from contaminating later tests."""
    from tools.delegate_tool import (
        release_delegate_provider_repair,
        set_spawn_paused,
    )

    tui_server = sys.modules.get("tui_gateway.server")
    leases_by_repair = getattr(
        tui_server, "_beta_runtime_delegate_repair_leases", None
    )
    targets_lock = getattr(
        tui_server, "_beta_runtime_repair_targets_lock", None
    )
    if isinstance(leases_by_repair, dict) and targets_lock is not None:
        with targets_lock:
            leases = list(leases_by_repair.values())
        for lease in leases:
            try:
                release_delegate_provider_repair(lease)
            except RuntimeError:
                pass
        with targets_lock:
            leases_by_repair.clear()
            for attr in (
                "_beta_runtime_repair_targets",
                "_beta_runtime_repair_completed",
                "_beta_runtime_control_receipts",
                "_beta_runtime_control_attempts",
            ):
                value = getattr(tui_server, attr, None)
                if hasattr(value, "clear"):
                    value.clear()
    set_spawn_paused(False)


@pytest.fixture(autouse=True)
def _isolated_beta_oauth(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    with oauth._oauth_sessions_lock:
        oauth._oauth_sessions.clear()
    from elevate_cli.web_routes import chat_websockets

    monkeypatch.setattr(
        chat_websockets,
        "_dashboard_repair_control_plane_ready",
        True,
    )
    with chat_websockets._pty_repair_condition:
        chat_websockets._active_pty_bridges.clear()
        chat_websockets._pty_publishers.clear()
        chat_websockets._pty_repair_barrier = None
    _release_test_delegate_repair_leases()
    clear_beta_runtime_repair_state()
    yield
    clear_beta_runtime_repair_state()
    _release_test_delegate_repair_leases()
    with oauth._oauth_sessions_lock:
        oauth._oauth_sessions.clear()
    with chat_websockets._pty_repair_condition:
        chat_websockets._active_pty_bridges.clear()
        chat_websockets._pty_publishers.clear()
        chat_websockets._pty_repair_barrier = None


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
        "disconnect_exact_beta_provider_auth",
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


def test_beta_disconnect_with_live_pty_runs_coordinator_off_publisher_loop(
    tmp_path,
):
    """The HTTP route must leave the publisher loop free to deliver prepare."""
    from elevate_cli.web_routes import chat_websockets

    token = "live-disconnect-token"
    channel = "live-disconnect"
    instance = "7" * 32
    key = (channel, instance)
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(_provider_state_payload()),
        encoding="utf-8",
    )

    application = FastAPI()
    application.include_router(
        oauth.create_oauth_router(require_token=lambda _request: None)
    )
    application.include_router(
        chat_websockets.create_chat_websocket_router(
            embedded_chat_enabled=lambda: True,
            session_token=lambda: token,
            bound_host=lambda: "127.0.0.1",
            bound_port=lambda: 9120,
            license_signed_in=lambda: True,
            resolve_chat_argv=lambda resume=None, sidecar_url=None: (
                ["/bin/true"],
                None,
                None,
            ),
            pty_bridge_class=lambda: SimpleNamespace,
            pty_unavailable_error_class=lambda: RuntimeError,
            log=SimpleNamespace(
                debug=lambda *_args, **_kwargs: None,
                exception=lambda *_args, **_kwargs: None,
            ),
        )
    )

    with TestClient(application) as client:
        with chat_websockets._pty_repair_condition:
            chat_websockets._active_pty_bridges[key] = object()
            chat_websockets._pty_repair_condition.notify_all()

        publisher_path = (
            "/api/pub"
            f"?token={token}&channel={channel}&instance={instance}"
        )
        with client.websocket_connect(publisher_path) as publisher:
            publisher.send_json(
                {
                    "elevate_sidecar": "hello",
                    "protocol": chat_websockets._SIDECAR_PROTOCOL,
                    "instance": instance,
                }
            )
            hello_ack = publisher.receive_json()
            assert hello_ack["elevate_sidecar"] == "hello_ack"
            assert hello_ack["registered"] is True

            response_box = {}

            def disconnect() -> None:
                response_box["response"] = client.delete(
                    f"/api/providers/oauth/{BETA_ALLOWED_PROVIDER}"
                )

            request_thread = threading.Thread(
                target=disconnect,
                name="oauth-live-disconnect-request",
            )
            request_thread.start()

            prepare = publisher.receive_json()
            assert prepare["elevate_sidecar"] == "control"
            assert prepare["phase"] == "prepare"
            publisher.send_json(
                {
                    "elevate_sidecar": "ack",
                    "protocol": chat_websockets._SIDECAR_PROTOCOL,
                    "instance": instance,
                    "repair_id": prepare["repair_id"],
                    "attempt": prepare["attempt"],
                    "attempt_seq": prepare["attempt_seq"],
                    "phase": "prepare",
                    "ok": True,
                    "receipt": {
                        "repair_id": prepare["repair_id"],
                        "marked": 0,
                        "running": 0,
                        "quiesced": 0,
                        "pending": 0,
                    },
                }
            )
            request_thread.join(timeout=3.0)

        assert request_thread.is_alive() is False
        response = response_box["response"]
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "provider": BETA_ALLOWED_PROVIDER,
        }
        # The auth store itself remains as an atomic, profile-local JSON
        # container; disconnect removes the provider credentials and active
        # selection rather than unlinking the whole store.
        persisted_auth = json.loads(auth_path.read_text(encoding="utf-8"))
        assert persisted_auth.get("active_provider") is None
        assert BETA_ALLOWED_PROVIDER not in persisted_auth.get("providers", {})
        assert "fake-access-token" not in auth_path.read_text(encoding="utf-8")
        assert read_beta_codex_auth_status(tmp_path)["logged_in"] is False
        assert beta_runtime_repair_blocked_reason() == "beta_codex_auth_required"


@pytest.mark.parametrize("failure_stage", ["pty_prepare", "auth_delete"])
def test_beta_disconnect_failure_is_truthful_and_keeps_runtime_fenced(
    tmp_path,
    monkeypatch,
    failure_stage,
):
    from elevate_cli.web_routes import chat_websockets
    from tools.delegate_tool import is_spawn_paused
    from tui_gateway import server as tui_server

    assert sys.modules.get("tui_gateway.server") is tui_server
    with tui_server._session_registry_lock:
        tui_server._sessions.clear()
        tui_server._session_aliases.clear()
        tui_server._resume_reservations.clear()
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(_provider_state_payload()), encoding="utf-8"
    )
    before_auth = auth_path.read_bytes()
    real_clear = auth_module.clear_provider_auth
    clear_calls = []

    def guarded_clear(provider_id):
        clear_calls.append(provider_id)
        if failure_stage == "auth_delete":
            raise OSError("simulated durable auth deletion failure")
        return real_clear(provider_id)

    monkeypatch.setattr(auth_module, "clear_provider_auth", guarded_clear)
    if failure_stage == "pty_prepare":
        monkeypatch.setattr(
            chat_websockets,
            "begin_exact_beta_pty_runtime_repair",
            lambda _repair_id: (_ for _ in ()).throw(
                RuntimeError("simulated partial PTY prepare failure")
            ),
        )

    response = _client().delete(
        f"/api/providers/oauth/{BETA_ALLOWED_PROVIDER}"
    )

    assert response.status_code == 500
    expected_error = (
        "simulated partial PTY prepare failure"
        if failure_stage == "pty_prepare"
        else "simulated durable auth deletion failure"
    )
    assert expected_error in response.json()["detail"]
    assert auth_path.read_bytes() == before_auth
    assert read_beta_codex_auth_status(tmp_path)["logged_in"] is True
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"
    assert beta_runtime_repair_generation() is not None
    assert is_spawn_paused() is True
    assert clear_calls == (
        [] if failure_stage == "pty_prepare" else [BETA_ALLOWED_PROVIDER]
    )


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
    monkeypatch.setattr(
        oauth,
        "_add_codex_pool_credential",
        lambda *_args, **_kwargs: pytest.fail(
            "Realtor Beta unexpectedly duplicated Codex auth into the pool"
        ),
    )
    hostile_url = "https://codex.attacker.invalid/v1"
    monkeypatch.setenv("ELEVATE_CODEX_BASE_URL", hostile_url)
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    live_repairs = []
    fake_tui_server = ModuleType("tui_gateway.server")

    def repair_live_sessions():
        live_repairs.append("repaired")
        return {"marked": 0, "rebuilt": 0, "draining": 0}

    fake_tui_server.invalidate_exact_beta_runtime_sessions = repair_live_sessions
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n"
        "  provider: gemini\n"
        "  default: gemini-2.5-flash\n"
        "  base_url: https://generativelanguage.googleapis.com/v1beta\n"
        "  api_key: stale-inline-secret\n"
        "  key_env: GEMINI_API_KEY\n",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# Keep this Realtor Beta account setting\n"
        "TELEGRAM_HOME_CHANNEL=123456\n"
        # python-dotenv accepts exported assignments too. They must be retired
        # or a cold gateway start silently restores the stale provider.
        "export ELEVATE_MODEL=gemini-2.5-flash\n"
        "export ELEVATE_INFERENCE_PROVIDER=gemini\n",
        encoding="utf-8",
    )
    session_id, _ = oauth._new_oauth_session(BETA_ALLOWED_PROVIDER, "device_code")

    oauth._codex_full_login_worker(session_id)

    session = oauth._oauth_sessions[session_id]
    assert session["status"] == "approved"
    assert hostile_url not in (tmp_path / "auth.json").read_text(encoding="utf-8")
    written_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert written_config["model"] == {
        "provider": BETA_ALLOWED_PROVIDER,
        "default": "gpt-5.6-sol",
        "base_url": BETA_CODEX_BASE_URL,
        "api_mode": "codex_responses",
    }
    assert "stale-inline-secret" not in config_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" not in config_path.read_text(encoding="utf-8")
    assert [call["url"] for call in http_calls] == [
        "https://auth.openai.com/api/accounts/deviceauth/usercode",
        "https://auth.openai.com/api/accounts/deviceauth/token",
        auth_module.CODEX_OAUTH_TOKEN_URL,
    ]
    assert "ELEVATE_MODEL" not in os.environ
    assert "ELEVATE_INFERENCE_PROVIDER" not in os.environ
    assert env_path.read_text(encoding="utf-8") == (
        "# Keep this Realtor Beta account setting\n"
        "TELEGRAM_HOME_CHANNEL=123456\n"
    )
    # Model a cold gateway start. The repaired profile must not reload the
    # retired Gemini overrides from its durable dotenv authority.
    load_elevate_dotenv(elevate_home=tmp_path)
    assert "ELEVATE_MODEL" not in os.environ
    assert "ELEVATE_INFERENCE_PROVIDER" not in os.environ
    assert live_repairs == ["repaired"]
    assert beta_runtime_repair_blocked_reason() is None

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


def test_beta_codex_config_repair_failure_never_reports_oauth_approved(
    tmp_path,
    monkeypatch,
):
    _install_fake_httpx(monkeypatch)
    config_path = tmp_path / "config.yaml"
    before = (
        b"model:\n"
        b"  provider: gemini\n"
        b"  default: gemini-2.5-flash\n"
    )
    config_path.write_bytes(before)
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    fake_tui_server = ModuleType("tui_gateway.server")
    fake_tui_server.invalidate_exact_beta_runtime_sessions = lambda: pytest.fail(
        "failed onboarding invalidated live sessions"
    )
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)

    def fail_config_update(*_args, **_kwargs):
        raise RuntimeError("canonical Beta config write failed")

    monkeypatch.setattr(auth_module, "_update_config_for_provider", fail_config_update)
    session_id, _ = oauth._new_oauth_session(BETA_ALLOWED_PROVIDER, "device_code")

    oauth._codex_full_login_worker(session_id)

    session = oauth._oauth_sessions[session_id]
    assert session["status"] == "error"
    assert session["error_message"] == "canonical Beta config write failed"
    assert config_path.read_bytes() == before
    assert os.environ["ELEVATE_MODEL"] == "gemini-2.5-flash"
    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == "gemini"


def test_beta_live_repair_failure_never_reports_oauth_approved(
    tmp_path,
    monkeypatch,
):
    _install_fake_httpx(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n  provider: gemini\n  default: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# preserve account settings\n"
        "TELEGRAM_HOME_CHANNEL=123456\n"
        "ELEVATE_MODEL=gemini-2.5-flash\n"
        "ELEVATE_INFERENCE_PROVIDER=gemini\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    repair_calls = []
    fake_tui_server = ModuleType("tui_gateway.server")

    def fail_live_repair():
        repair_calls.append("attempted")
        raise RuntimeError("simulated live repair failure")

    fake_tui_server.invalidate_exact_beta_runtime_sessions = fail_live_repair
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)
    session_id, _ = oauth._new_oauth_session(BETA_ALLOWED_PROVIDER, "device_code")

    oauth._codex_full_login_worker(session_id)

    session = oauth._oauth_sessions[session_id]
    assert session["status"] == "error"
    assert session["error_message"] == (
        "Realtor Beta could not refresh live sessions after Codex setup; retry setup"
    )
    assert repair_calls == ["attempted"]
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["model"] == {
        "provider": BETA_ALLOWED_PROVIDER,
        "default": "gpt-5.6-sol",
        "base_url": BETA_CODEX_BASE_URL,
        "api_mode": "codex_responses",
    }
    assert env_path.read_text(encoding="utf-8") == (
        "# preserve account settings\n"
        "TELEGRAM_HOME_CHANNEL=123456\n"
    )
    assert "ELEVATE_MODEL" not in os.environ
    assert "ELEVATE_INFERENCE_PROVIDER" not in os.environ
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"

    # A browser refresh reads auth/config again instead of the failed OAuth
    # session. The process-local gate must still keep runtimeReady false so the
    # wizard cannot silently advance with unrepaired live actors.
    receipt = _beta_runtime_receipt(
        elevate_home=tmp_path,
        config=yaml.safe_load(config_path.read_text(encoding="utf-8")),
        auth_status=read_beta_codex_auth_status(tmp_path),
    )
    assert receipt["runtimeReady"] is False
    assert receipt["blockedReason"] == "beta_provider_repair_failed"


def test_beta_incomplete_live_repair_never_reports_oauth_approved(
    tmp_path,
    monkeypatch,
):
    _install_fake_httpx(monkeypatch)
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: gemini\n  default: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    fake_tui_server = ModuleType("tui_gateway.server")
    fake_tui_server.invalidate_exact_beta_runtime_sessions = lambda: {
        "marked": 2,
        "rebuilt": 1,
        "draining": 0,
    }
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)
    session_id, _ = oauth._new_oauth_session(BETA_ALLOWED_PROVIDER, "device_code")

    oauth._codex_full_login_worker(session_id)

    session = oauth._oauth_sessions[session_id]
    assert session["status"] == "error"
    assert session["error_message"] == (
        "Realtor Beta could not refresh live sessions after Codex setup; retry setup"
    )


def test_beta_provider_update_retry_reuses_failed_repair_generation(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "auth.json").write_text(
        json.dumps(_provider_state_payload()), encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: gemini\n  default: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    repair_ids: list[str] = []
    prepare_attempts = 0
    fake_tui_server = ModuleType("tui_gateway.server")

    def prepare(repair_id):
        nonlocal prepare_attempts
        prepare_attempts += 1
        repair_ids.append(repair_id)
        if prepare_attempts == 1:
            raise RuntimeError("simulated prepare barrier failure")
        return {
            "repair_id": repair_id,
            "marked": 0,
            "running": 0,
            "quiesced": 0,
            "pending": 0,
        }

    fake_tui_server.prepare_exact_beta_runtime_sessions = prepare
    fake_tui_server.complete_exact_beta_runtime_sessions = lambda repair_id: {
        "repair_id": repair_id,
        "marked": 0,
        "rebuilt": 0,
        "pending": 0,
    }
    fake_tui_server.release_exact_beta_runtime_sessions = lambda repair_id: {
        "repair_id": repair_id,
        "released": True,
    }
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)

    with pytest.raises(RuntimeError, match="simulated prepare barrier failure"):
        auth_module._update_config_for_provider(
            BETA_ALLOWED_PROVIDER,
            BETA_CODEX_BASE_URL,
        )
    failed_generation = beta_runtime_repair_generation()
    assert failed_generation == repair_ids[0]
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"

    auth_module._update_config_for_provider(
        BETA_ALLOWED_PROVIDER,
        BETA_CODEX_BASE_URL,
    )

    assert repair_ids == [failed_generation, failed_generation]
    assert beta_runtime_repair_generation() is None
    assert beta_runtime_repair_blocked_reason() is None


def test_real_beta_provider_retry_retains_delegate_lease_until_all_ptys_complete(
    tmp_path,
    monkeypatch,
):
    from elevate_cli.web_routes import chat_websockets
    from tools.delegate_tool import is_spawn_paused
    from tui_gateway import server as tui_server

    assert sys.modules.get("tui_gateway.server") is tui_server
    (tmp_path / "auth.json").write_text(
        json.dumps(_provider_state_payload()), encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-codex\n"
        "  default: gpt-5.5\n"
        "  openai_runtime: codex_app_server\n",
        encoding="utf-8",
    )
    real_complete_ptys = (
        chat_websockets.complete_exact_beta_pty_runtime_repair
    )
    completion_attempts = 0

    def flaky_complete_ptys(repair_id):
        nonlocal completion_attempts
        completion_attempts += 1
        if completion_attempts == 1:
            raise RuntimeError("simulated aggregate PTY completion failure")
        return real_complete_ptys(repair_id)

    monkeypatch.setattr(
        chat_websockets,
        "complete_exact_beta_pty_runtime_repair",
        flaky_complete_ptys,
    )

    with pytest.raises(RuntimeError, match="could not refresh live sessions"):
        auth_module._update_config_for_provider(
            BETA_ALLOWED_PROVIDER,
            BETA_CODEX_BASE_URL,
        )

    repair_id = beta_runtime_repair_generation()
    assert repair_id is not None
    retained_lease = tui_server._beta_runtime_delegate_repair_leases[repair_id]
    assert is_spawn_paused() is True
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"

    auth_module._update_config_for_provider(
        BETA_ALLOWED_PROVIDER,
        BETA_CODEX_BASE_URL,
    )

    assert completion_attempts == 2
    assert retained_lease not in (
        tui_server._beta_runtime_delegate_repair_leases.values()
    )
    assert is_spawn_paused() is False
    assert beta_runtime_repair_generation() is None
    assert beta_runtime_repair_blocked_reason() is None
    repaired = yaml.safe_load(
        (tmp_path / "config.yaml").read_text(encoding="utf-8")
    )
    assert "openai_runtime" not in repaired["model"]


def test_concurrent_beta_updates_serialize_and_retry_same_failed_generation(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "auth.json").write_text(
        json.dumps(_provider_state_payload()), encoding="utf-8"
    )
    first_entered = threading.Event()
    release_first = threading.Event()
    repair_ids: list[str] = []
    active = 0
    max_active = 0
    calls_lock = threading.Lock()
    fake_tui_server = ModuleType("tui_gateway.server")

    def prepare(repair_id):
        nonlocal active, max_active
        with calls_lock:
            repair_ids.append(repair_id)
            active += 1
            max_active = max(max_active, active)
            attempt = len(repair_ids)
        try:
            if attempt == 1:
                first_entered.set()
                assert release_first.wait(timeout=2)
                raise RuntimeError("first concurrent prepare failed")
            return {
                "repair_id": repair_id,
                "marked": 0,
                "running": 0,
                "quiesced": 0,
                "pending": 0,
            }
        finally:
            with calls_lock:
                active -= 1

    fake_tui_server.prepare_exact_beta_runtime_sessions = prepare
    fake_tui_server.complete_exact_beta_runtime_sessions = lambda repair_id: {
        "repair_id": repair_id,
        "marked": 0,
        "rebuilt": 0,
        "pending": 0,
    }
    fake_tui_server.release_exact_beta_runtime_sessions = lambda repair_id: {
        "repair_id": repair_id,
        "released": True,
    }
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)
    outcomes: list[object] = []

    def update(model):
        try:
            outcomes.append(
                auth_module._update_config_for_provider(
                    BETA_ALLOWED_PROVIDER,
                    BETA_CODEX_BASE_URL,
                    default_model=model,
                )
            )
        except Exception as exc:
            outcomes.append(exc)

    first = threading.Thread(target=update, args=("gpt-5.4",), daemon=True)
    second = threading.Thread(target=update, args=("gpt-5.5",), daemon=True)
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    assert repair_ids == [repair_ids[0]]
    release_first.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive() and not second.is_alive()
    assert max_active == 1
    assert len(repair_ids) == 2 and repair_ids[0] == repair_ids[1]
    assert sum(isinstance(value, RuntimeError) for value in outcomes) == 1
    assert beta_runtime_repair_blocked_reason() is None


def test_beta_provider_repair_requires_durable_config_before_runtime_invalidation(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "auth.json").write_text(
        json.dumps(_provider_state_payload()),
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: gemini\n  default: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    fake_tui_server = ModuleType("tui_gateway.server")
    fake_tui_server.invalidate_exact_beta_runtime_sessions = lambda: pytest.fail(
        "unverified config write invalidated live sessions"
    )
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)

    def observe_pending_before_config_write(_config):
        assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_pending"

    monkeypatch.setattr(
        "elevate_cli.config.save_config",
        observe_pending_before_config_write,
    )

    with pytest.raises(RuntimeError, match="not durably saved"):
        auth_module._update_config_for_provider(
            BETA_ALLOWED_PROVIDER,
            BETA_CODEX_BASE_URL,
        )

    assert os.environ["ELEVATE_MODEL"] == "gemini-2.5-flash"
    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == "gemini"
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"


def test_beta_provider_env_cleanup_failure_never_touches_process_or_live_actors(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "auth.json").write_text(
        json.dumps(_provider_state_payload()),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    before = (
        b"# preserve me\n"
        b"ELEVATE_MODEL=gemini-2.5-flash\n"
        b"ELEVATE_INFERENCE_PROVIDER=gemini\n"
    )
    env_path.write_bytes(before)
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    fake_tui_server = ModuleType("tui_gateway.server")
    fake_tui_server.invalidate_exact_beta_runtime_sessions = lambda: pytest.fail(
        "failed environment cleanup invalidated live sessions"
    )
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)

    def fail_env_cleanup(_keys):
        raise OSError("simulated atomic dotenv replacement failure")

    monkeypatch.setattr("elevate_cli.config.remove_env_values", fail_env_cleanup)

    with pytest.raises(OSError, match="simulated atomic dotenv replacement failure"):
        auth_module._update_config_for_provider(
            BETA_ALLOWED_PROVIDER,
            BETA_CODEX_BASE_URL,
        )

    assert env_path.read_bytes() == before
    assert os.environ["ELEVATE_MODEL"] == "gemini-2.5-flash"
    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == "gemini"
    assert beta_runtime_repair_blocked_reason() == "beta_provider_repair_failed"


def test_beta_provider_env_cleanup_rejects_linked_store_without_side_effects(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "auth.json").write_text(
        json.dumps(_provider_state_payload()),
        encoding="utf-8",
    )
    borrowed_env = tmp_path / "borrowed.env"
    before = (
        b"# borrowed profile\n"
        b"ELEVATE_MODEL=gemini-2.5-flash\n"
        b"ELEVATE_INFERENCE_PROVIDER=gemini\n"
    )
    borrowed_env.write_bytes(before)
    env_path = tmp_path / ".env"
    env_path.symlink_to(borrowed_env)
    monkeypatch.setenv("ELEVATE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "gemini")
    fake_tui_server = ModuleType("tui_gateway.server")
    fake_tui_server.invalidate_exact_beta_runtime_sessions = lambda: pytest.fail(
        "linked environment cleanup invalidated live sessions"
    )
    monkeypatch.setitem(sys.modules, "tui_gateway.server", fake_tui_server)

    with pytest.raises(HTTPException) as exc_info:
        auth_module._update_config_for_provider(
            BETA_ALLOWED_PROVIDER,
            BETA_CODEX_BASE_URL,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "beta_env_store_not_local"
    assert env_path.is_symlink()
    assert borrowed_env.read_bytes() == before
    assert os.environ["ELEVATE_MODEL"] == "gemini-2.5-flash"
    assert os.environ["ELEVATE_INFERENCE_PROVIDER"] == "gemini"


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
    monkeypatch.setattr(
        auth_module,
        "_update_config_for_provider",
        lambda *_args, **_kwargs: pytest.fail(
            "Stable dashboard flow unexpectedly changed model configuration"
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
