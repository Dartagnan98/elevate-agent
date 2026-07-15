import base64
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from elevate_cli import cloud_skills
from elevate_cli import access as access_mod
from elevate_cli import entitlement_assertion as assertion_mod
from elevate_cli import license as license_mod
from elevate_cli import web_auth
import elevate_constants
from elevate_cli.access import dashboard_access_status, load_access_config


ATTACKER_BACKEND = "https://attacker.example.test"
_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
_TEST_PUBLIC_KEY = base64.b64encode(
    _TEST_PRIVATE_KEY.public_key().public_bytes(
        Encoding.DER,
        PublicFormat.SubjectPublicKeyInfo,
    )
).decode("ascii")


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


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _signed_assertion(
    *,
    access_token: str,
    refresh_token: str,
    license_id: str,
    email: str,
    tier: str,
    entitlements: list[str],
    expires_at: int,
) -> str:
    issued_at = expires_at - 3600
    header = {
        "alg": "EdDSA",
        "typ": assertion_mod.ENTITLEMENT_ASSERTION_TYPE,
        "kid": assertion_mod.ENTITLEMENT_ASSERTION_KID,
    }
    claims = {
        "iss": assertion_mod.ENTITLEMENT_ASSERTION_ISSUER,
        "aud": assertion_mod.ENTITLEMENT_ASSERTION_AUDIENCE,
        "schema": assertion_mod.ENTITLEMENT_ASSERTION_SCHEMA,
        "sub": f"user-{license_id}",
        "license_id": license_id,
        "email": email.strip().lower(),
        "tier": tier,
        "entitlements": sorted(set(entitlements)),
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
        "jti": f"assertion-{license_id}-{refresh_token}",
        "ath": assertion_mod.token_binding_hash(access_token),
        "rth": assertion_mod.token_binding_hash(refresh_token),
    }
    protected = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{protected}.{payload}".encode("ascii")
    signature = _b64url(_TEST_PRIVATE_KEY.sign(signing_input))
    return f"{protected}.{payload}.{signature}"


def _signed_payload(
    *,
    access_token: str | None = None,
    refresh_token: str = "refresh-secret",
    license_id: str = "license-1",
    email: str = "agent@example.test",
    tier: str = "pro",
    entitlements: list[str] | None = None,
    expires_at: int | None = None,
) -> dict[str, Any]:
    expiry = expires_at or int(time.time()) + 3600
    access = access_token or _access_token(expires_at=expiry)
    granted = sorted(set(entitlements or []))
    assertion = _signed_assertion(
        access_token=access,
        refresh_token=refresh_token,
        license_id=license_id,
        email=email,
        tier=tier,
        entitlements=granted,
        expires_at=expiry,
    )
    return {
        "access_token": access,
        "refresh_token": refresh_token,
        "license_id": license_id,
        "tier": tier,
        "email": email.strip().lower(),
        "expires_at": expiry,
        "entitlements": granted,
        "entitlement_assertion": assertion,
    }


def _beta_license(**kwargs: Any) -> license_mod.License:
    return license_mod._beta_license_from_mapping(_signed_payload(**kwargs))


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
    monkeypatch.setattr(
        assertion_mod,
        "ENTITLEMENT_ASSERTION_PUBLIC_KEYS",
        {assertion_mod.ENTITLEMENT_ASSERTION_KID: _TEST_PUBLIC_KEY},
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
    lic = _beta_license(access_token="current-access")
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
    payload = _signed_payload(
        entitlements=["real_estate_admin", "real_estate_sales"],
    )
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, payload, **kwargs),
    )

    monkeypatch.setattr(
        cloud_skills,
        "sync_all",
        lambda: {"skill_count": 0, "skill_names": [], "errors": []},
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
    old = _beta_license(
        refresh_token="old-refresh",
        license_id="license-old",
        entitlements=["real_estate_sales"],
    )
    license_mod.save(old)
    new = _beta_license(
        refresh_token="new-refresh",
        license_id="license-new",
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
        expired_at = int(time.time()) - 10
        expired = _signed_payload(
            access_token=_access_token(expires_at=expired_at),
            refresh_token="refresh",
            expires_at=expired_at,
            entitlements=["real_estate_sales", "real_estate_admin"],
        )
        license_mod.LICENSE_PATH.write_text(json.dumps(expired))
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
    revoked = _beta_license(refresh_token="refresh", entitlements=[])
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
    lic = _beta_license(
        refresh_token="refresh",
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
    stale = _beta_license(
        refresh_token="stale-refresh",
        license_id="stale-license",
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

    assert exc_info.value.code == "beta_entitlement_assertion_missing"
    assert license_mod.load() == stale
    assert len(calls) == 1


def test_exact_beta_device_link_rejects_incomplete_approved_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(license_mod.time, "sleep", lambda _seconds: None)
    stale = _beta_license(
        refresh_token="stale-refresh",
        license_id="stale-license",
        entitlements=["real_estate_sales"],
    )
    license_mod.save(stale)
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

    assert exc_info.value.code == "beta_entitlement_assertion_missing"
    assert license_mod.load() == stale
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
    stale = _beta_license(
        refresh_token="stale-refresh",
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


def test_exact_beta_refresh_accepts_and_persists_only_rotated_signed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = _beta_license(
        access_token="stale-access",
        refresh_token="stale-refresh",
        entitlements=["real_estate_sales"],
    )
    license_mod.save(stale)
    rotated_payload = _signed_payload(
        access_token="rotated-access",
        refresh_token="rotated-refresh",
        entitlements=["real_estate_admin"],
    )
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, rotated_payload, **kwargs),
    )

    rotated = license_mod.refresh(stale)

    assert rotated.access_token == "rotated-access"
    assert rotated.refresh_token == "rotated-refresh"
    assert rotated.entitlements == ["real_estate_admin"]
    assert license_mod.load() == rotated


def test_exact_beta_device_link_accepts_only_signed_approved_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(license_mod.time, "sleep", lambda _seconds: None)
    approved = {
        "status": "approved",
        **_signed_payload(entitlements=["real_estate_admin"]),
    }
    payloads = [
        {
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://example.test/link",
            "expires_in": 60,
            "interval": 1,
        },
        approved,
    ]
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SequenceClient(calls, payloads, **kwargs),
    )

    lic = license_mod.link_device("Realtor Mac", interval_override=1)

    assert lic.entitlements == ["real_estate_admin"]
    assert license_mod.load() == lic


def test_exact_beta_entitlement_verification_failure_removes_partial_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    payload = _signed_payload(entitlements=["real_estate_sales"])
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
    lic = _beta_license(entitlements=[])
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


def test_exact_beta_unsigned_forged_snapshot_grants_no_identity_or_paid_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    forged = {
        "access_token": _access_token(),
        "refresh_token": "attacker-refresh",
        "license_id": "attacker-license",
        "tier": "builder",
        "email": "attacker@example.test",
        "expires_at": int(time.time()) + 86_400,
        "entitlements": ["real_estate_admin", "real_estate_sales"],
    }
    license_mod.LICENSE_PATH.write_text(json.dumps(forged), encoding="utf-8")
    license_mod.LICENSE_PATH.chmod(0o600)

    assert license_mod.load() is None
    assert web_auth.license_signed_in(license_path=license_mod.LICENSE_PATH) is False
    assert elevate_constants.get_account_key() == "default"
    assert dashboard_access_status()["packs"]["realEstateAny"] is False


def test_exact_beta_signed_reader_drives_web_tui_and_uncached_account_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    first = _beta_license(email="first@example.test")
    license_mod.save(first)

    assert web_auth.license_signed_in(license_path=license_mod.LICENSE_PATH) is True
    assert elevate_constants.get_account_key() == (
        "acct_" + hashlib.sha1(first.email.encode()).hexdigest()[:16]
    )

    from tui_gateway import server as tui_server

    monkeypatch.setattr(tui_server, "_LICENSE_PATH", license_mod.LICENSE_PATH)
    monkeypatch.setattr(tui_server, "_SIGN_IN_BYPASS", True)
    assert tui_server._license_signed_in() is True

    second = _beta_license(
        access_token="second-access",
        refresh_token="second-refresh",
        license_id="license-2",
        email="second@example.test",
    )
    license_mod.save(second)
    assert elevate_constants.get_account_key() == (
        "acct_" + hashlib.sha1(second.email.encode()).hexdigest()[:16]
    )


@pytest.mark.parametrize("kind", ["garbage", "symlink"])
def test_exact_beta_web_tui_and_account_identity_fail_closed_on_unsafe_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    if kind == "garbage":
        license_mod.LICENSE_PATH.write_text("not-json", encoding="utf-8")
    else:
        target = tmp_path / "outside-license.json"
        target.write_text(json.dumps(_signed_payload()), encoding="utf-8")
        license_mod.LICENSE_PATH.symlink_to(target)
    if not license_mod.LICENSE_PATH.is_symlink():
        license_mod.LICENSE_PATH.chmod(0o600)

    from tui_gateway import server as tui_server

    monkeypatch.setattr(tui_server, "_LICENSE_PATH", license_mod.LICENSE_PATH)
    monkeypatch.setattr(tui_server, "_SIGN_IN_BYPASS", True)
    assert web_auth.license_signed_in(license_path=license_mod.LICENSE_PATH) is False
    assert tui_server._license_signed_in() is False
    assert elevate_constants.get_account_key() == "default"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "attacker@example.test"),
        ("license_id", "attacker-license"),
        ("tier", "builder"),
        ("expires_at", 4_102_444_800),
        ("entitlements", ["real_estate_admin"]),
        ("access_token", "different-access"),
        ("refresh_token", "different-refresh"),
    ],
)
def test_exact_beta_local_duplicate_and_token_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    payload = _signed_payload(entitlements=["real_estate_admin", "real_estate_sales"])
    payload[field] = value
    license_mod.LICENSE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    license_mod.LICENSE_PATH.chmod(0o600)

    assert license_mod.load() is None
    assert dashboard_access_status()["packs"]["realEstateAny"] is False


def test_exact_beta_hq_unsigned_duplicate_cannot_override_signed_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    payload = _signed_payload(entitlements=[])
    payload["entitlements"] = ["real_estate_admin"]
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, payload, **kwargs),
    )

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.login("agent@example.test", "secret-password")

    assert exc_info.value.code == "beta_entitlement_response_mismatch"
    assert license_mod.load() is None


def test_exact_beta_never_derives_expiry_or_grants_from_local_access_jwt_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    signed_expiry = int(time.time()) + 3600
    forged_jwt_expiry = 4_102_444_800
    payload = _signed_payload(
        access_token=_access_token(expires_at=forged_jwt_expiry),
        entitlements=[],
        expires_at=signed_expiry,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, payload, **kwargs),
    )

    lic = license_mod.login("agent@example.test", "secret-password")

    assert lic.expires_at == signed_expiry
    assert lic.expires_at != license_mod._decode_jwt_exp(lic.access_token)
    assert lic.entitlements == []


def test_exact_beta_late_refresh_rejection_does_not_erase_new_signed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = _beta_license(
        access_token="stale-access",
        refresh_token="stale-refresh",
    )
    newer = _beta_license(
        access_token="new-access",
        refresh_token="new-refresh",
        license_id="license-1",
    )
    license_mod.save(stale)

    class _RacingClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _FailedResponse:
            assert json == {"refresh_token": "stale-refresh"}
            license_mod.save(newer)
            return _FailedResponse(401)

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _RacingClient())

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.refresh(stale)

    assert exc_info.value.code == "beta_license_revoked"
    assert license_mod.load() == newer


def test_exact_beta_losing_concurrent_save_does_not_erase_new_signed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    losing = _beta_license(
        access_token="losing-access",
        refresh_token="losing-refresh",
    )
    winner = _beta_license(
        access_token="winner-access",
        refresh_token="winner-refresh",
    )
    real_replace = license_mod._atomic_beta_replace
    calls = 0

    def install_winner(_data: bytes | None) -> None:
        nonlocal calls
        calls += 1
        real_replace(json.dumps(winner.to_dict()).encode("utf-8"))

    monkeypatch.setattr(license_mod, "_atomic_beta_replace", install_winner)

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.save(losing)

    assert exc_info.value.code == "beta_license_persistence_mismatch"
    assert calls == 1
    assert license_mod.load() == winner


def test_exact_beta_forces_skill_sync_even_when_skip_was_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    lic = _beta_license(entitlements=[])
    license_mod.save(lic)
    calls = 0

    def sync_all() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"skill_count": 0, "skill_names": [], "errors": []}

    monkeypatch.setattr(cloud_skills, "sync_all", sync_all)

    activation = license_mod.activate_install(lic, sync_skills=False)

    assert calls == 1
    assert activation["activation_complete"] is True


@pytest.mark.parametrize("failure", ["exception", "warning"])
def test_exact_beta_activation_skill_failure_is_typed_and_never_complete(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    lic = _beta_license(entitlements=[])
    license_mod.save(lic)

    if failure == "exception":
        def fail_sync():
            raise RuntimeError("network failed")

        monkeypatch.setattr(cloud_skills, "sync_all", fail_sync)
        expected_code = "beta_skill_sync_failed"
    else:
        monkeypatch.setattr(
            cloud_skills,
            "sync_all",
            lambda: {"skill_count": 0, "skill_names": [], "errors": ["bad pack"]},
        )
        expected_code = "beta_skill_sync_incomplete"

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.activate_install(lic, sync_skills=False)

    assert exc_info.value.code == expected_code


def test_stable_activation_keeps_legacy_warning_success_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    lic = license_mod.License(
        access_token="access",
        refresh_token="refresh",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=4_102_444_800,
        entitlements=[],
    )
    monkeypatch.setattr(
        cloud_skills,
        "sync_all",
        lambda: {"skill_count": 0, "skill_names": [], "errors": ["legacy warning"]},
    )

    activation = license_mod.activate_install(lic)

    assert activation["skill_sync_warnings"] == ["legacy warning"]
    assert activation["activation_complete"] is True


def test_stable_cli_keeps_legacy_zero_exit_for_skill_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    lic = license_mod.License(
        access_token="access",
        refresh_token="refresh",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=4_102_444_800,
        entitlements=[],
    )
    monkeypatch.setattr(license_mod, "login", lambda *_args: lic)
    monkeypatch.setattr(license_mod, "sync_license_entitlements", lambda _lic: None)
    monkeypatch.setattr(
        cloud_skills,
        "sync_all",
        lambda: {"skill_count": 0, "skill_names": [], "errors": ["legacy warning"]},
    )
    args = SimpleNamespace(
        email=lic.email,
        password="secret",
        backend_url=None,
        skip_skill_sync=False,
    )

    assert license_mod.cmd_activate(args) == 0
