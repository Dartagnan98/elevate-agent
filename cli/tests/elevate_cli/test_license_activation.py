from pathlib import Path

import pytest

from elevate_cli import cloud_skills
from elevate_cli import license as license_mod


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

    monkeypatch.setattr(cloud_skills, "mount_all", lambda: Path("/tmp/elevate-skills"))
    monkeypatch.setattr(
        cloud_skills,
        "mounted_skill_names",
        lambda: ["seller-package", "closing-admin"],
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


def test_backend_url_requires_explicit_elevation_hq_origin(monkeypatch):
    monkeypatch.setattr(license_mod, "BACKEND_URL", "")

    with pytest.raises(license_mod.LicenseError, match="ELEVATE_BACKEND_URL"):
        license_mod.backend_url()


def test_activate_command_persists_backend_url(monkeypatch, capsys):
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
