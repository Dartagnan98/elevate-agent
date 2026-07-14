"""Focused backend-identity tests for dashboard license routes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from elevate_cli import license as license_mod
from elevate_cli.web_routes.license import create_license_router


ATTACKER_BACKEND = "https://attacker.example.test"


class _FailureResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = "upstream rejected the request"

    @property
    def is_success(self) -> bool:
        return False


class _RecordingClient:
    def __init__(
        self,
        calls: list[dict[str, Any]],
        status_code: int,
        **_kwargs: Any,
    ) -> None:
        self._calls = calls
        self._status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any]) -> _FailureResponse:
        self._calls.append({"url": url, "json": json})
        return _FailureResponse(self._status_code)


class _SkillListResponse:
    status_code = 200
    text = ""
    is_success = True

    def json(self) -> dict[str, list[Any]]:
        return {"skills": []}


class _CloudRecordingClient:
    def __init__(
        self,
        calls: list[dict[str, Any]],
        *,
        base_url: str,
        **_kwargs: Any,
    ) -> None:
        self._calls = calls
        self._base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def get(self, path: str, *, headers: dict[str, str]) -> _SkillListResponse:
        self._calls.append(
            {"base_url": self._base_url, "path": path, "headers": headers}
        )
        return _SkillListResponse()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(create_license_router(require_token=lambda _request: None))
    return TestClient(app)


@pytest.fixture
def protected_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Seed license/config bytes behind the paths a vulnerable write would touch."""
    license_path = tmp_path / "profile" / "license.json"
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(b'{"access_token":"existing"}\n')
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)

    managed_env = tmp_path / "managed" / "profile.env"
    managed_env.parent.mkdir(parents=True)
    managed_env.write_bytes(
        b"CRM_API_KEY=existing\n"
        b"ELEVATE_BACKEND_URL=https://attacker.example.test\n"
    )
    profile_env = tmp_path / "profile" / ".env"
    try:
        profile_env.symlink_to(managed_env)
    except OSError:
        pytest.skip("symlinks are unavailable")

    import elevate_cli.config as config_mod

    monkeypatch.setattr(config_mod, "get_env_path", lambda: profile_env)
    return {
        "license_path": license_path,
        "license_bytes": license_path.read_bytes(),
        "managed_env": managed_env,
        "managed_bytes": managed_env.read_bytes(),
        "profile_env": profile_env,
    }


def _assert_profile_unchanged(protected_profile: dict[str, Any]) -> None:
    assert (
        protected_profile["license_path"].read_bytes()
        == protected_profile["license_bytes"]
    )
    assert (
        protected_profile["managed_env"].read_bytes()
        == protected_profile["managed_bytes"]
    )
    assert protected_profile["profile_env"].is_symlink()


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        (
            "/api/license/activate",
            {"email": "agent@example.test", "password": "secret-password"},
        ),
        (
            "/api/license/signup",
            {"email": "agent@example.test", "password": "secret-password"},
        ),
        ("/api/license/request-code", {"email": "agent@example.test"}),
        (
            "/api/license/activate-code",
            {"email": "agent@example.test", "code": "123456"},
        ),
    ],
)
def test_exact_beta_rejects_every_caller_backend_before_credentials_or_state_change(
    client: TestClient,
    protected_profile: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    payload: dict[str, str],
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", "https://preexisting.example.test")
    monkeypatch.setattr(license_mod, "BACKEND_URL", "https://preexisting.example.test")

    def fail_if_network_client_created(**_kwargs: Any):
        raise AssertionError("caller-controlled backend reached the network client")

    monkeypatch.setattr(license_mod.httpx, "Client", fail_if_network_client_created)
    before_backend = license_mod.BACKEND_URL
    before_env = os.environ["ELEVATE_BACKEND_URL"]

    response = client.post(route, json={**payload, "backend_url": ATTACKER_BACKEND})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "beta_backend_override_not_allowed",
        "message": (
            "Realtor Beta connects account sign-in only to Elevation Real Estate HQ. "
            "Remove the custom backend URL and try again."
        ),
    }
    assert license_mod.BACKEND_URL == before_backend
    assert os.environ["ELEVATE_BACKEND_URL"] == before_env
    _assert_profile_unchanged(protected_profile)


@pytest.mark.parametrize(
    ("route", "payload", "upstream_status", "route_status", "upstream_path"),
    [
        (
            "/api/license/activate",
            {"email": "agent@example.test", "password": "secret-password"},
            401,
            401,
            "/api/auth/login",
        ),
        (
            "/api/license/signup",
            {"email": "agent@example.test", "password": "secret-password"},
            400,
            400,
            "/api/auth/signup",
        ),
        (
            "/api/license/request-code",
            {"email": "agent@example.test"},
            500,
            400,
            "/api/auth/login-code/request",
        ),
        (
            "/api/license/activate-code",
            {"email": "agent@example.test", "code": "123456"},
            401,
            401,
            "/api/auth/login-code/verify",
        ),
    ],
)
def test_exact_beta_pins_every_auth_route_to_signed_backend_and_restores_failed_state(
    client: TestClient,
    protected_profile: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    payload: dict[str, str],
    upstream_status: int,
    route_status: int,
    upstream_path: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient(calls, upstream_status, **kwargs),
    )
    before_backend = license_mod.BACKEND_URL
    before_env = os.environ["ELEVATE_BACKEND_URL"]

    response = client.post(route, json=payload)

    assert response.status_code == route_status
    assert [call["url"] for call in calls] == [
        f"{license_mod.DEFAULT_BACKEND.rstrip('/')}{upstream_path}"
    ]
    assert all(not call["url"].startswith(ATTACKER_BACKEND) for call in calls)
    assert license_mod.BACKEND_URL == before_backend
    assert os.environ["ELEVATE_BACKEND_URL"] == before_env
    _assert_profile_unchanged(protected_profile)


def test_exact_beta_keeps_post_login_activation_inside_signed_backend_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    license_value = license_mod.License(
        access_token="access",
        refresh_token="refresh",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=4_102_444_800,
        entitlements=[],
    )
    observed: list[tuple[str, str]] = []

    def login(_email: str, _password: str) -> license_mod.License:
        observed.append(("login", license_mod.backend_url()))
        return license_value

    def activate_install(
        lic: license_mod.License,
        *,
        sync_skills: bool,
    ) -> dict[str, Any]:
        assert lic is license_value
        assert sync_skills is True
        observed.append(("activate", license_mod.backend_url()))
        return {"packs": {}, "skill_count": 0, "skill_names": [], "skill_error": None}

    monkeypatch.setattr(license_mod, "login", login)
    monkeypatch.setattr(license_mod, "activate_install", activate_install)

    response = client.post(
        "/api/license/activate",
        json={"email": "agent@example.test", "password": "secret-password"},
    )

    assert response.status_code == 200
    assert observed == [
        ("login", license_mod.DEFAULT_BACKEND),
        ("activate", license_mod.DEFAULT_BACKEND),
    ]
    assert license_mod.BACKEND_URL == ATTACKER_BACKEND
    assert os.environ["ELEVATE_BACKEND_URL"] == ATTACKER_BACKEND


def test_exact_beta_fails_closed_when_signed_backend_identity_is_missing(
    client: TestClient,
    protected_profile: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "DEFAULT_BACKEND", "")
    before_backend = license_mod.BACKEND_URL
    before_env = os.environ["ELEVATE_BACKEND_URL"]

    response = client.post(
        "/api/license/activate",
        json={"email": "agent@example.test", "password": "secret-password"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "beta_backend_identity_unavailable"
    assert license_mod.BACKEND_URL == before_backend
    assert os.environ["ELEVATE_BACKEND_URL"] == before_env
    _assert_profile_unchanged(protected_profile)


def test_exact_beta_web_skill_sync_never_sends_bearer_token_to_stale_backend(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import cloud_skills

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    lic = license_mod.License(
        access_token="bearer-secret",
        refresh_token="refresh-secret",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=4_102_444_800,
        entitlements=[],
    )
    monkeypatch.setattr(license_mod, "load", lambda: lic)
    monkeypatch.setattr(cloud_skills, "cloud_skills_dir", lambda: tmp_path / "skills")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cloud_skills.httpx,
        "Client",
        lambda **kwargs: _CloudRecordingClient(calls, **kwargs),
    )

    response = client.post("/api/license/sync-skills")

    assert response.status_code == 200
    assert calls == [
        {
            "base_url": license_mod.DEFAULT_BACKEND,
            "path": "/api/skills/list",
            "headers": {"authorization": "Bearer bearer-secret"},
        }
    ]
    assert calls[0]["base_url"] != ATTACKER_BACKEND
    assert license_mod.BACKEND_URL == ATTACKER_BACKEND
    assert os.environ["ELEVATE_BACKEND_URL"] == ATTACKER_BACKEND


@pytest.mark.parametrize(
    ("route", "payload", "function_name", "route_status", "should_persist"),
    [
        (
            "/api/license/activate",
            {"email": "agent@example.test", "password": "secret-password"},
            "login",
            401,
            True,
        ),
        (
            "/api/license/signup",
            {"email": "agent@example.test", "password": "secret-password"},
            "create_account",
            400,
            True,
        ),
        (
            "/api/license/request-code",
            {"email": "agent@example.test"},
            "request_login_code",
            400,
            False,
        ),
        (
            "/api/license/activate-code",
            {"email": "agent@example.test", "code": "123456"},
            "login_with_code",
            401,
            False,
        ),
    ],
)
def test_nonbeta_backend_override_remains_compatible(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    payload: dict[str, str],
    function_name: str,
    route_status: int,
    should_persist: bool,
) -> None:
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.delenv("ELEVATE_BACKEND_URL", raising=False)
    monkeypatch.setattr(license_mod, "BACKEND_URL", license_mod.DEFAULT_BACKEND)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    saved: list[tuple[str, str]] = []

    def fail_auth(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        raise license_mod.LicenseError("expected failure")

    monkeypatch.setattr(license_mod, function_name, fail_auth)
    import elevate_cli.config as config_mod

    monkeypatch.setattr(
        config_mod,
        "save_env_value",
        lambda key, value: saved.append((key, value)),
    )

    response = client.post(
        route,
        json={**payload, "backend_url": f"{ATTACKER_BACKEND}/"},
    )

    assert response.status_code == route_status
    assert len(calls) == 1
    assert license_mod.BACKEND_URL == ATTACKER_BACKEND
    assert os.environ["ELEVATE_BACKEND_URL"] == ATTACKER_BACKEND
    assert saved == (
        [("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)] if should_persist else []
    )
