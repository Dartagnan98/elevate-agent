import base64
import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from elevate_cli import cloud_skills
from elevate_cli import access as access_mod
from elevate_cli import license as license_mod
from elevate_cli.access import dashboard_access_status, load_access_config


ATTACKER_BACKEND = "https://attacker.example.test"


class _FailedResponse:
    def __init__(self, status_code: int = 500) -> None:
        self.status_code = status_code
        self.text = "upstream failure"

    @property
    def is_success(self) -> bool:
        return False


class _RecordingClient:
    def __init__(
        self,
        calls: list[dict[str, Any]],
        status_code: int = 500,
        **_kwargs: Any,
    ) -> None:
        self._calls = calls
        self._status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any]) -> _FailedResponse:
        self._calls.append({"url": url, "json": json})
        return _FailedResponse(self._status_code)


def _access_token(*, expires_at: int | None = None) -> str:
    payload = json.dumps({"exp": expires_at or int(time.time()) + 3600}).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"header.{encoded}.signature"


class _SuccessResponse:
    status_code = 200
    text = ""
    is_success = True

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _SuccessClient:
    def __init__(self, calls: list[str], payload: dict[str, Any], **_kwargs: Any) -> None:
        self._calls = calls
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any]) -> _SuccessResponse:
        self._calls.append(url)
        return _SuccessResponse(self._payload)


class _SequenceClient:
    def __init__(
        self,
        calls: list[str],
        payloads: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        self._calls = calls
        self._payloads = payloads

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any]) -> _SuccessResponse:
        self._calls.append(url)
        return _SuccessResponse(self._payloads.pop(0))


@pytest.fixture(autouse=True)
def _local_beta_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".elevate-beta"
    root.mkdir()
    monkeypatch.setenv("ELEVATE_HOME", str(root))
    monkeypatch.setattr(license_mod, "_beta_profile_root", lambda: root)
    monkeypatch.setattr(license_mod, "LICENSE_PATH", root / "license.json")
    monkeypatch.setattr(
        license_mod,
        "LICENSE_FAIL_PATH",
        root / ".license_refresh_failures",
    )


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
    license_path.chmod(0o600)
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_mod, "_beta_profile_root", lambda: license_path.parent)

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
    license_path.chmod(0o600)
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_mod, "_beta_profile_root", lambda: license_path.parent)
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
    license_path.chmod(0o600)
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_mod, "_beta_profile_root", lambda: license_path.parent)
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


def test_exact_beta_success_persists_one_complete_verified_entitlement_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    token = _access_token()
    payload = {
        "access_token": token,
        "refresh_token": "refresh-secret",
        "license_id": "license-1",
        "tier": "pro",
        "entitlements": ["realEstateSales", "real_estate_admin"],
    }
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, payload, **kwargs),
    )

    lic = license_mod.login("agent@example.test", "secret-password")
    activation = license_mod.activate_install(lic, sync_skills=False)

    assert calls == [f"{license_mod.DEFAULT_BACKEND}/api/auth/login"]
    assert license_mod.load() == lic
    assert json.loads(license_mod.LICENSE_PATH.read_text()) == lic.to_dict()
    assert stat.S_IMODE(license_mod.LICENSE_PATH.stat().st_mode) == 0o600
    assert license_mod.LICENSE_PATH.stat().st_nlink == 1
    assert activation["activation_complete"] is True
    assert activation["skill_sync_warnings"] == []
    assert activation["packs"]["realEstateSales"] is True
    assert activation["packs"]["realEstateAdmin"] is True


@pytest.mark.parametrize(
    "store_kind",
    [
        "symlink",
        "profile_symlink",
        "hardlink",
        "public_file",
        "shared_root",
        "managed",
        "unwritable",
    ],
)
def test_exact_beta_unsafe_profile_fails_before_any_auth_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_kind: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    root = license_mod._beta_profile_root()
    if store_kind == "managed":
        (root / ".managed").write_text("managed\n")
    elif store_kind == "unwritable":
        root.chmod(0o500)
    elif store_kind == "shared_root":
        root.chmod(0o770)
    elif store_kind == "public_file":
        license_mod.LICENSE_PATH.write_text("{}")
        license_mod.LICENSE_PATH.chmod(0o644)
    elif store_kind == "profile_symlink":
        redirected = tmp_path / "redirected-profile"
        redirected.mkdir()
        root.rmdir()
        root.symlink_to(redirected, target_is_directory=True)
    else:
        target = tmp_path / "outside-license.json"
        target.write_text("{}")
        if store_kind == "symlink":
            license_mod.LICENSE_PATH.symlink_to(target)
        else:
            os.link(target, license_mod.LICENSE_PATH)

    def fail_if_networked(**_kwargs: Any):
        raise AssertionError("unsafe profile reached the network")

    monkeypatch.setattr(license_mod.httpx, "Client", fail_if_networked)
    try:
        with pytest.raises(license_mod.LicenseError) as exc_info:
            license_mod.request_login_code("agent@example.test")
    finally:
        if store_kind in {"unwritable", "shared_root"}:
            root.chmod(0o700)

    assert exc_info.value.code.startswith("beta_license_store_")


def test_exact_beta_atomic_verification_fault_invalidates_previous_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    old = license_mod.License(
        access_token=_access_token(),
        refresh_token="old-refresh",
        license_id="license-old",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=["real_estate_sales"],
    )
    license_mod.save(old)
    new = license_mod.License(
        access_token=_access_token(),
        refresh_token="new-refresh",
        license_id="license-new",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=[],
    )
    real_replace = license_mod._atomic_beta_replace
    calls = 0

    def corrupt_first_write(data: bytes | None) -> None:
        nonlocal calls
        calls += 1
        real_replace(b"{}" if calls == 1 else data)

    monkeypatch.setattr(license_mod, "_atomic_beta_replace", corrupt_first_write)

    with pytest.raises(license_mod.LicenseError):
        license_mod.save(new)

    assert calls == 2
    assert not license_mod.LICENSE_PATH.exists()
    assert license_mod.load() is None
    assert dashboard_access_status()["packs"]["realEstateAny"] is False


@pytest.mark.parametrize("snapshot", ["missing", "tampered", "expired"])
def test_exact_beta_invalid_snapshot_overrides_stale_config_grants_to_core_only(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = {
        "entitlements": {
            "real_estate_sales": {"status": "active", "owned_snapshot": True},
            "real_estate_admin": {"status": "active", "owned_snapshot": True},
        }
    }
    if snapshot == "tampered":
        license_mod.LICENSE_PATH.write_text("not-json")
        license_mod.LICENSE_PATH.chmod(0o600)
    elif snapshot == "expired":
        expired = license_mod.License(
            access_token=_access_token(expires_at=1),
            refresh_token="refresh",
            license_id="license-1",
            tier="pro",
            email="agent@example.test",
            expires_at=1,
            entitlements=["real_estate_sales", "real_estate_admin"],
        )
        license_mod.LICENSE_PATH.write_text(json.dumps(expired.to_dict()))
        license_mod.LICENSE_PATH.chmod(0o600)

    access = load_access_config({"access": stale})
    status = dashboard_access_status(access)

    assert status["packs"]["realEstateAny"] is False
    assert access["entitlements"]["real_estate_sales"]["status"] == "locked"
    assert access["entitlements"]["real_estate_admin"]["status"] == "locked"


def test_exact_beta_empty_revocation_snapshot_overrides_stale_config_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    revoked = license_mod.License(
        access_token=_access_token(),
        refresh_token="refresh",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=[],
    )
    license_mod.save(revoked)
    stale = {
        "entitlements": {
            "real_estate_sales": {"status": "active", "owned_snapshot": True},
            "real_estate_admin": {"status": "active", "owned_snapshot": True},
        }
    }

    status = dashboard_access_status(load_access_config({"access": stale}))

    assert status["packs"]["realEstateAny"] is False


def test_exact_beta_hq_team_grant_activates_required_affiliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    lic = license_mod.License(
        access_token=_access_token(),
        refresh_token="refresh",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=[access_mod.ENTITLEMENT_TEAM_PACK],
    )
    license_mod.save(lic)

    access = load_access_config()

    assert access["affiliation"]["status"] == "active"
    assert access_mod.is_entitlement_active(
        access_mod.ENTITLEMENT_TEAM_PACK,
        access,
    ) is True


def test_exact_beta_missing_snapshot_locks_every_noncore_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv(access_mod.DEV_DASHBOARD_UNLOCK_ENV, "1")
    stale = {
        "profile": access_mod.PROFILE_TEAM_PACK,
        "entitlements": {
            access_mod.ENTITLEMENT_EXP: {
                "status": "active",
                "owned_snapshot": True,
            },
            access_mod.ENTITLEMENT_TEAM_PACK: {
                "status": "active",
                "owned_snapshot": True,
            },
            access_mod.ENTITLEMENT_REAL_ESTATE_SALES: {
                "status": "active",
                "owned_snapshot": True,
            },
            "custom_paid_pack": {
                "status": "active",
                "owned_snapshot": True,
            },
        },
    }

    access = load_access_config({"access": stale})
    status = dashboard_access_status(access)

    assert status["devOverride"] is False
    assert status["packs"]["realEstateAny"] is False
    assert access["entitlements"][access_mod.ENTITLEMENT_CORE]["status"] == "active"
    for name, entry in access["entitlements"].items():
        if name != access_mod.ENTITLEMENT_CORE:
            assert entry["status"] == "locked"
            assert entry["owned_snapshot"] is False


@pytest.mark.parametrize(
    ("function_name", "args"),
    [
        ("login", ("agent@example.test", "secret-password")),
        ("create_account", ("agent@example.test", "secret-password")),
        ("login_with_code", ("agent@example.test", "123456")),
    ],
)
def test_exact_beta_every_token_auth_flow_rejects_incomplete_entitlement_success(
    monkeypatch: pytest.MonkeyPatch,
    function_name: str,
    args: tuple[str, ...],
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    payload = {
        "access_token": _access_token(),
        "refresh_token": "refresh-secret",
        "license_id": "license-1",
        "tier": "pro",
    }
    stale = license_mod.License(
        access_token=_access_token(),
        refresh_token="stale-refresh",
        license_id="stale-license",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=["real_estate_sales"],
    )
    license_mod.save(stale)
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, payload, **kwargs),
    )

    with pytest.raises(license_mod.LicenseError) as exc_info:
        getattr(license_mod, function_name)(*args)

    assert exc_info.value.code == "beta_entitlement_snapshot_missing"
    assert not license_mod.LICENSE_PATH.exists()
    assert len(calls) == 1


def test_exact_beta_device_link_rejects_incomplete_approved_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(license_mod.time, "sleep", lambda _seconds: None)
    license_mod.save(
        license_mod.License(
            access_token=_access_token(),
            refresh_token="stale-refresh",
            license_id="stale-license",
            tier="pro",
            email="agent@example.test",
            expires_at=int(time.time()) + 3600,
            entitlements=["real_estate_sales"],
        )
    )
    payloads = [
        {
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://example.test/link",
            "expires_in": 60,
            "interval": 1,
        },
        {
            "status": "approved",
            "email": "agent@example.test",
            "access_token": _access_token(),
            "refresh_token": "refresh-secret",
            "license_id": "license-1",
            "tier": "pro",
        },
    ]
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SequenceClient(calls, payloads, **kwargs),
    )

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert exc_info.value.code == "beta_entitlement_snapshot_missing"
    assert not license_mod.LICENSE_PATH.exists()
    assert calls == [
        f"{license_mod.DEFAULT_BACKEND}/api/device/start",
        f"{license_mod.DEFAULT_BACKEND}/api/device/poll",
    ]


@pytest.mark.parametrize("status_code", [401, 402])
def test_exact_beta_refresh_rejection_removes_stale_paid_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = license_mod.License(
        access_token=_access_token(),
        refresh_token="stale-refresh",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=["real_estate_sales"],
    )
    license_mod.save(stale)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient(calls, status_code=status_code, **kwargs),
    )

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.refresh(stale)

    assert exc_info.value.code == "beta_license_revoked"
    assert not license_mod.LICENSE_PATH.exists()
    assert dashboard_access_status()["packs"]["realEstateAny"] is False


def test_exact_beta_entitlement_verification_failure_removes_partial_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    payload = {
        "access_token": _access_token(),
        "refresh_token": "refresh-secret",
        "license_id": "license-1",
        "tier": "pro",
        "entitlements": ["real_estate_sales"],
    }
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, payload, **kwargs),
    )

    def fail_verification(_lic: license_mod.License) -> None:
        raise license_mod.LicenseError(
            "forced verification mismatch",
            code="beta_entitlement_persistence_mismatch",
        )

    monkeypatch.setattr(license_mod, "sync_license_entitlements", fail_verification)

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.login("agent@example.test", "secret-password")

    assert exc_info.value.code == "beta_entitlement_persistence_mismatch"
    assert not license_mod.LICENSE_PATH.exists()


@pytest.mark.parametrize("command_name", ["cmd_activate", "cmd_link"])
def test_exact_beta_cli_surfaces_typed_activation_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command_name: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    lic = license_mod.License(
        access_token=_access_token(),
        refresh_token="refresh-secret",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=int(time.time()) + 3600,
        entitlements=[],
    )
    monkeypatch.setattr(license_mod, "login", lambda *_args: lic)
    monkeypatch.setattr(license_mod, "link_device", lambda *_args: lic)

    def fail_activation(*_args: Any, **_kwargs: Any):
        raise license_mod.LicenseError(
            "forced persistence mismatch",
            code="beta_license_persistence_mismatch",
        )

    monkeypatch.setattr(license_mod, "activate_install", fail_activation)
    args = SimpleNamespace(
        email="agent@example.test",
        password="secret-password",
        backend_url=None,
        skip_skill_sync=True,
        label="Realtor Mac",
    )

    assert getattr(license_mod, command_name)(args) == 1
    assert "beta_license_persistence_mismatch" in capsys.readouterr().err
