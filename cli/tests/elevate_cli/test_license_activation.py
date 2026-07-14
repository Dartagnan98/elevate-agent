import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from elevate_cli import cloud_skills
from elevate_cli import license as license_mod


ATTACKER_BACKEND = "https://attacker.example.test"


class _FailedResponse:
    def __init__(self, status_code: int = 500) -> None:
        self.status_code = status_code
        self.text = "upstream failure"

    @property
    def is_success(self) -> bool:
        return False


class _RecordingClient:
    def __init__(self, calls: list[dict[str, Any]], **_kwargs: Any) -> None:
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any]) -> _FailedResponse:
        self._calls.append({"url": url, "json": json})
        return _FailedResponse()


def test_activate_install_syncs_dashboard_packs_and_paid_skills(monkeypatch):
    lic = license_mod.License(
        access_token="token",
        refresh_token="refresh",
        license_id="lic_123",
        tier="pro",
        email="agent@example.com",
        expires_at=4_000_000_000,
        entitlements=["real_estate_admin", "real_estate_cma"],
    )

    monkeypatch.setattr(
        cloud_skills,
        "sync_all",
        lambda: {
            "path": "/tmp/elevate-skills",
            "skill_count": 2,
            "skill_names": ["seller-package", "closing-admin"],
            "removed": [],
            "errors": [],
        },
    )

    result = license_mod.activate_install(lic)

    assert result["packs"]["realEstateAdmin"] is True
    assert result["packs"]["realEstateCma"] is True
    assert result["packs"]["realEstateSales"] is False
    assert result["skill_count"] == 2
    assert result["skill_names"] == ["seller-package", "closing-admin"]


def test_activate_install_can_skip_skill_sync():
    lic = license_mod.License(
        access_token="token",
        refresh_token="refresh",
        license_id="lic_123",
        tier="pro",
        email="agent@example.com",
        expires_at=4_000_000_000,
        entitlements=["real_estate_sales"],
    )

    result = license_mod.activate_install(lic, sync_skills=False)

    assert result["packs"]["realEstateSales"] is True
    assert result["skill_count"] == 0
    assert result["skill_names"] == []


def test_license_save_creates_private_token_file(tmp_path, monkeypatch):
    path = tmp_path / ".elevate" / "license.json"
    monkeypatch.setattr(license_mod, "LICENSE_PATH", path)
    lic = license_mod.License(
        access_token="access-secret",
        refresh_token="refresh-secret",
        license_id="lic_123",
        tier="pro",
        email="agent@example.com",
        expires_at=4_000_000_000,
        entitlements=["real_estate_sales"],
    )

    license_mod.save(lic)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_suffix(".json.tmp").exists()
    assert json.loads(path.read_text())["refresh_token"] == "refresh-secret"


def test_backend_url_requires_explicit_elevation_hq_origin(monkeypatch):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.setattr(license_mod, "BACKEND_URL", "")

    with pytest.raises(license_mod.LicenseError, match="ELEVATE_BACKEND_URL"):
        license_mod.backend_url()


def test_activate_command_persists_backend_url(monkeypatch, capsys):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    saved = {}
    lic = license_mod.License(
        access_token="token",
        refresh_token="refresh",
        license_id="lic_123",
        tier="pro",
        email="agent@example.com",
        expires_at=4_000_000_000,
        entitlements=["real_estate_admin"],
    )

    class Args:
        email = "agent@example.com"
        password = "secret"
        backend_url = "https://api.example.test/"
        skip_skill_sync = True

    monkeypatch.setattr(license_mod, "BACKEND_URL", "")
    monkeypatch.setattr(license_mod, "login", lambda email, password: lic)
    monkeypatch.setattr(
        "elevate_cli.config.save_env_value",
        lambda key, value: saved.__setitem__(key, value),
    )

    assert license_mod.cmd_activate(Args()) == 0
    assert license_mod.BACKEND_URL == "https://api.example.test"
    assert saved["ELEVATE_BACKEND_URL"] == "https://api.example.test"
    assert "activated agent@example.com" in capsys.readouterr().out


def test_exact_beta_backend_resolver_ignores_process_and_profile_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)

    assert license_mod.backend_url() == license_mod.DEFAULT_BACKEND
    assert license_mod.BACKEND_URL == ATTACKER_BACKEND
    assert os.environ["ELEVATE_BACKEND_URL"] == ATTACKER_BACKEND


@pytest.mark.parametrize("command_name", ["cmd_activate", "cmd_subscribe", "cmd_link"])
def test_exact_beta_terminal_backend_override_is_typed_atomic_and_never_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command_name: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)

    license_path = tmp_path / "profile" / "license.json"
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(b'{"access_token":"existing"}\n')
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)

    managed_env = tmp_path / "managed" / "profile.env"
    managed_env.parent.mkdir(parents=True)
    managed_env.write_bytes(
        b"ELEVATE_BACKEND_URL=https://attacker.example.test\n"
        b"CRM_API_KEY=existing\n"
    )
    profile_env = tmp_path / "profile" / ".env"
    try:
        profile_env.symlink_to(managed_env)
    except OSError:
        pytest.skip("symlinks are unavailable")

    import elevate_cli.config as config_mod

    monkeypatch.setattr(config_mod, "get_env_path", lambda: profile_env)

    def fail_if_used(*_args: Any, **_kwargs: Any):
        raise AssertionError("credentials or device flow reached an attacker backend")

    monkeypatch.setattr(license_mod, "login", fail_if_used)
    monkeypatch.setattr(license_mod, "link_device", fail_if_used)
    monkeypatch.setattr(config_mod, "save_env_value", fail_if_used)
    args = SimpleNamespace(
        email="agent@example.test",
        password="secret-password",
        backend_url=ATTACKER_BACKEND,
        skip_skill_sync=True,
        label="Realtor Mac",
    )
    before_license = license_path.read_bytes()
    before_managed = managed_env.read_bytes()
    before_backend = license_mod.BACKEND_URL
    before_env = os.environ["ELEVATE_BACKEND_URL"]

    result = getattr(license_mod, command_name)(args)

    assert result == 2
    assert "beta_backend_override_not_allowed" in capsys.readouterr().err
    assert license_mod.BACKEND_URL == before_backend
    assert os.environ["ELEVATE_BACKEND_URL"] == before_env
    assert license_path.read_bytes() == before_license
    assert managed_env.read_bytes() == before_managed
    assert profile_env.is_symlink()


def test_exact_beta_refresh_sends_refresh_token_only_to_signed_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    license_path = tmp_path / "license.json"
    license_path.write_bytes(b'{"refresh_token":"existing"}\n')
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient(calls, **kwargs),
    )
    lic = license_mod.License(
        access_token="expired-access",
        refresh_token="refresh-secret",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=1,
        entitlements=[],
    )
    before_bytes = license_path.read_bytes()

    with pytest.raises(license_mod.LicenseError, match="Refresh failed"):
        license_mod.refresh(lic)

    assert calls == [
        {
            "url": f"{license_mod.DEFAULT_BACKEND}/api/license/refresh",
            "json": {"refresh_token": "refresh-secret"},
        }
    ]
    assert not calls[0]["url"].startswith(ATTACKER_BACKEND)
    assert license_path.read_bytes() == before_bytes
    assert license_mod.BACKEND_URL == ATTACKER_BACKEND
    assert os.environ["ELEVATE_BACKEND_URL"] == ATTACKER_BACKEND


def test_exact_beta_device_link_starts_only_on_signed_backend_without_state_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    license_path = tmp_path / "license.json"
    license_path.write_bytes(b'{"access_token":"existing"}\n')
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient(calls, **kwargs),
    )
    before_bytes = license_path.read_bytes()

    with pytest.raises(license_mod.LicenseError, match="Could not start device link"):
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert calls == [
        {
            "url": f"{license_mod.DEFAULT_BACKEND}/api/device/start",
            "json": {"device_label": "Realtor Mac"},
        }
    ]
    assert not calls[0]["url"].startswith(ATTACKER_BACKEND)
    assert license_path.read_bytes() == before_bytes
