import base64
import hashlib
import json
import os
import stat
import threading
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


CANONICAL_REFRESH_A = _b64url(b"A" * 32)
CANONICAL_REFRESH_B = _b64url(b"B" * 32)
CANONICAL_REFRESH_C = _b64url(b"C" * 32)


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
    refresh_token: str = CANONICAL_REFRESH_A,
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
        "expires_in": 3600,
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
        payload = self._payload
        if url.endswith("/api/license/refresh") and "next_refresh_token" in json:
            payload = _signed_payload(
                access_token=payload["access_token"],
                refresh_token=json["next_refresh_token"],
                license_id=payload["license_id"],
                email=payload["email"],
                tier=payload["tier"],
                entitlements=payload["entitlements"],
                expires_at=payload["expires_at"],
            )
        return _SuccessResponse(payload)


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
    test_keys = {assertion_mod.ENTITLEMENT_ASSERTION_KID: _TEST_PUBLIC_KEY}
    monkeypatch.setattr(assertion_mod, "ENTITLEMENT_ASSERTION_PUBLIC_KEYS", test_keys)
    monkeypatch.setattr(
        assertion_mod,
        "ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS",
        tuple(sorted(test_keys)),
    )
    monkeypatch.setattr(
        assertion_mod,
        "ENTITLEMENT_ASSERTION_KEYSET_SHA256",
        assertion_mod.entitlement_assertion_keyset_sha256(test_keys),
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


def test_exact_beta_refresh_sends_recoverable_triplet_only_to_signed_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", ATTACKER_BACKEND)
    monkeypatch.setattr(license_mod, "BACKEND_URL", ATTACKER_BACKEND)
    license_path = tmp_path / "license.json"
    monkeypatch.setattr(license_mod, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_mod, "_beta_profile_root", lambda: license_path.parent)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient(calls, **kwargs),
    )
    lic = _beta_license(access_token="current-access")
    license_mod.save(lic)
    before_bytes = license_path.read_bytes()

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.refresh(lic)

    assert caught.value.code == "beta_auth_upstream_failed"
    assert len(calls) == 1
    assert calls[0]["url"] == f"{license_mod.DEFAULT_BACKEND}/api/license/refresh"
    assert calls[0]["json"]["refresh_token"] == CANONICAL_REFRESH_A
    assert set(calls[0]["json"]) == {
        "refresh_token",
        "next_refresh_token",
        "refresh_attempt_id",
    }
    from elevate_cli import refresh_pending

    assert refresh_pending.canonical_token32(calls[0]["json"]["next_refresh_token"])
    assert refresh_pending.canonical_token32(calls[0]["json"]["refresh_attempt_id"])
    assert (license_path.parent / refresh_pending.MARKER_NAME).exists()
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
        license_mod.save(new, expected=old)

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
        expired_at = int(time.time()) - 120
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
        refresh_token=CANONICAL_REFRESH_A,
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
        refresh_token=CANONICAL_REFRESH_A,
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
        refresh_token=CANONICAL_REFRESH_A,
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
        refresh_token=CANONICAL_REFRESH_A,
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
    assert rotated.refresh_token != CANONICAL_REFRESH_A
    assert rotated.entitlements == ["real_estate_admin"]
    assert license_mod.load() == rotated


def test_exact_beta_verification_failure_retries_identical_triplet_and_requires_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = _beta_license(
        access_token="stale-access",
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_sales"],
    )
    license_mod.save(stale)
    bodies: list[dict[str, Any]] = []

    class _MismatchThenReplayClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _SuccessResponse:
            bodies.append(dict(json))
            refresh_token = (
                CANONICAL_REFRESH_C
                if len(bodies) == 1
                else json["next_refresh_token"]
            )
            return _SuccessResponse(
                _signed_payload(
                    access_token=f"replay-access-{len(bodies)}",
                    refresh_token=refresh_token,
                    entitlements=["real_estate_admin"],
                )
            )

    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _MismatchThenReplayClient(),
    )
    from elevate_cli import refresh_pending

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.refresh(stale)
    assert caught.value.code == "beta_refresh_successor_mismatch"
    assert license_mod.load() == stale
    assert (license_mod._beta_profile_root() / refresh_pending.MARKER_NAME).exists()

    recovered = license_mod.refresh(stale)

    assert bodies[0] == bodies[1]
    assert recovered.refresh_token == bodies[0]["next_refresh_token"]
    assert recovered.entitlements == ["real_estate_admin"]
    assert not (license_mod._beta_profile_root() / refresh_pending.MARKER_NAME).exists()


def test_stable_refresh_keeps_legacy_v1_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    current = license_mod.License(
        access_token="stable-access",
        refresh_token="stable-refresh",
        license_id="stable-license",
        tier="pro",
        email="stable@example.test",
        expires_at=int(time.time()) + 60,
        entitlements=[],
    )
    calls: list[dict[str, Any]] = []

    class _StableClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, url: str, *, json: dict[str, Any]) -> _SuccessResponse:
            calls.append({"url": url, "json": dict(json)})
            return _SuccessResponse(
                {
                    "access_token": _access_token(),
                    "refresh_token": "stable-next",
                }
            )

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _StableClient())

    refreshed = license_mod.refresh(current)

    assert calls[0]["json"] == {"refresh_token": "stable-refresh"}
    assert refreshed.refresh_token == "stable-next"


def test_exact_beta_expired_signed_snapshot_has_no_access_then_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    expired_at = int(time.time()) - 120
    expired_payload = _signed_payload(
        access_token="expired-access",
        refresh_token=CANONICAL_REFRESH_A,
        email="returning@example.test",
        entitlements=["real_estate_sales"],
        expires_at=expired_at,
    )
    license_mod.LICENSE_PATH.write_text(
        json.dumps(expired_payload),
        encoding="utf-8",
    )
    license_mod.LICENSE_PATH.chmod(0o600)

    historical = license_mod.load()
    assert historical is not None
    assert historical.is_expired(margin=0) is True
    assert elevate_constants.get_account_key() == (
        "acct_" + hashlib.sha1(b"returning@example.test").hexdigest()[:16]
    )
    assert web_auth.license_signed_in(license_path=license_mod.LICENSE_PATH) is False
    assert dashboard_access_status()["packs"]["realEstateAny"] is False
    from tui_gateway import server as tui_server

    monkeypatch.setattr(tui_server, "_LICENSE_PATH", license_mod.LICENSE_PATH)
    monkeypatch.setattr(tui_server, "_SIGN_IN_BYPASS", True)
    assert tui_server._license_signed_in() is False

    refreshed_payload = _signed_payload(
        access_token="refreshed-access",
        refresh_token="refreshed-refresh",
        email="returning@example.test",
        entitlements=["real_estate_admin"],
    )
    calls: list[str] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, refreshed_payload, **kwargs),
    )

    refreshed = license_mod.ensure_valid()

    assert refreshed.access_token == "refreshed-access"
    assert refreshed.entitlements == ["real_estate_admin"]
    assert web_auth.license_signed_in(license_path=license_mod.LICENSE_PATH) is True
    assert tui_server._license_signed_in() is True
    assert dashboard_access_status()["packs"]["realEstateAdmin"] is True
    assert dashboard_access_status()["packs"]["realEstateSales"] is False


def test_exact_beta_expired_signed_successor_replays_pending_triplet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with refresh_pending.refresh_lock(license_mod._beta_profile_root()):
        pending = refresh_pending.create_pending(
            license_mod._beta_profile_root(),
            license_id="license-1",
            current_refresh_token=CANONICAL_REFRESH_A,
            created_at=int(time.time()) - 7200,
        )
    expired_payload = _signed_payload(
        access_token="expired-successor-access",
        refresh_token=pending.successor_refresh_token,
        expires_at=int(time.time()) - 120,
    )
    expired = license_mod._beta_license_from_mapping(
        expired_payload,
        require_current=False,
    )
    license_mod._atomic_beta_replace(json.dumps(expired.to_dict()).encode("utf-8"))
    calls: list[dict[str, Any]] = []

    class _ReplayClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, url: str, *, json: dict[str, Any]) -> _SuccessResponse:
            calls.append({"url": url, "json": dict(json)})
            return _SuccessResponse(
                _signed_payload(
                    access_token="fresh-successor-access",
                    refresh_token=json["next_refresh_token"],
                    entitlements=["real_estate_admin"],
                )
            )

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _ReplayClient())

    fresh = license_mod.refresh(expired)

    assert len(calls) == 1
    assert calls[0]["json"] == {
        "refresh_token": pending.current_refresh_token,
        "next_refresh_token": pending.successor_refresh_token,
        "refresh_attempt_id": pending.attempt_id,
    }
    assert fresh.refresh_token == pending.successor_refresh_token
    assert fresh.access_token == "fresh-successor-access"
    assert not (license_mod._beta_profile_root() / refresh_pending.MARKER_NAME).exists()


@pytest.mark.parametrize("state", ["successor", "newer"])
def test_exact_beta_signed_successor_or_newer_state_cleans_marker_without_network(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with refresh_pending.refresh_lock(license_mod._beta_profile_root()):
        pending = refresh_pending.create_pending(
            license_mod._beta_profile_root(),
            license_id="license-1",
            current_refresh_token=CANONICAL_REFRESH_A,
        )
    token = (
        pending.successor_refresh_token
        if state == "successor"
        else CANONICAL_REFRESH_C
    )
    current = _beta_license(refresh_token=token)
    license_mod._atomic_beta_replace(json.dumps(current.to_dict()).encode("utf-8"))

    class _NoNetwork:
        def __enter__(self):
            raise AssertionError("signed local state should resolve before network")

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _NoNetwork())

    assert license_mod.refresh(current) == current
    assert not (license_mod._beta_profile_root() / refresh_pending.MARKER_NAME).exists()


def test_exact_beta_ambiguous_4xx_retains_marker_without_v1_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    current = _beta_license(refresh_token=CANONICAL_REFRESH_A)
    license_mod.save(current)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient(calls, status_code=400, **kwargs),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.refresh(current)

    assert caught.value.code == "beta_refresh_protocol_rejected"
    assert len(calls) == 1
    assert set(calls[0]["json"]) == {
        "refresh_token",
        "next_refresh_token",
        "refresh_attempt_id",
    }
    assert license_mod.load() == current
    assert (license_mod._beta_profile_root() / refresh_pending.MARKER_NAME).exists()


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
    license_mod.save(second, expected=first)
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
        ("expires_in", 7200),
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
        refresh_token=CANONICAL_REFRESH_A,
    )
    newer = _beta_license(
        access_token="new-access",
        refresh_token=CANONICAL_REFRESH_C,
        license_id="license-1",
    )
    license_mod.save(stale)

    mutation_started = threading.Event()
    mutation_finished = threading.Event()
    mutation_thread: threading.Thread | None = None

    class _RacingClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _FailedResponse:
            nonlocal mutation_thread
            assert json["refresh_token"] == CANONICAL_REFRESH_A
            assert set(json) == {
                "refresh_token",
                "next_refresh_token",
                "refresh_attempt_id",
            }

            def mutate() -> None:
                mutation_started.set()
                license_mod.save(newer)
                mutation_finished.set()

            mutation_thread = threading.Thread(target=mutate)
            mutation_thread.start()
            assert mutation_started.wait(1)
            assert not mutation_finished.wait(0.05)
            return _FailedResponse(401)

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _RacingClient())

    with pytest.raises(license_mod.LicenseError) as exc_info:
        license_mod.refresh(stale)

    assert exc_info.value.code == "beta_license_revoked"
    assert mutation_thread is not None
    mutation_thread.join(2)
    assert mutation_finished.is_set()
    assert license_mod.load() == newer


def test_exact_beta_public_save_uses_snapshot_cas_and_clears_superseded_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    initial = _beta_license(
        access_token="initial-access",
        refresh_token=CANONICAL_REFRESH_A,
    )
    newer = _beta_license(
        access_token="newer-access",
        refresh_token=CANONICAL_REFRESH_C,
    )
    license_mod.save(initial)
    root = license_mod._beta_profile_root()
    with refresh_pending.refresh_lock(root):
        refresh_pending.create_pending(
            root,
            license_id=initial.license_id,
            current_refresh_token=initial.refresh_token,
        )

    license_mod.save(newer, expected=initial)

    assert license_mod.load() == newer
    assert not (root / refresh_pending.MARKER_NAME).exists()
    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.save(initial)
    assert caught.value.code == "beta_auth_superseded"
    assert license_mod.load() == newer


def test_exact_beta_late_401_preserves_newer_signed_historical_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    stale = _beta_license(
        access_token="stale-access",
        refresh_token=CANONICAL_REFRESH_A,
    )
    license_mod.save(stale)
    newer_payload = _signed_payload(
        access_token="newer-expired-access",
        refresh_token=CANONICAL_REFRESH_C,
        expires_at=int(time.time()) - 120,
    )
    newer = license_mod._beta_license_from_mapping(
        newer_payload,
        require_current=False,
    )

    class _HistoricalRaceClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _FailedResponse:
            assert json["refresh_token"] == CANONICAL_REFRESH_A
            license_mod._atomic_beta_replace(
                license_mod.json.dumps(newer.to_dict()).encode("utf-8")
            )
            return _FailedResponse(401)

    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _HistoricalRaceClient(),
    )

    assert license_mod.refresh(stale) == newer
    assert license_mod.load() == newer
    assert dashboard_access_status()["packs"]["realEstateAny"] is False


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


def test_stable_activation_keeps_incomplete_warning_semantics(
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
    assert activation["activation_complete"] is False


def test_stable_cli_keeps_incomplete_nonzero_exit_for_skill_warning(
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

    assert license_mod.cmd_activate(args) == 1


CANONICAL_DEVICE_D = _b64url(b"D" * 32)
CANONICAL_DEVICE_I = _b64url(b"I" * 32)


def _write_device_pending() -> Any:
    from elevate_cli import refresh_pending

    root = license_mod._beta_profile_root()
    with refresh_pending.refresh_lock(root):
        return refresh_pending.write_device_pending(
            root,
            device_code=CANONICAL_DEVICE_D,
            initial_refresh_token=CANONICAL_REFRESH_B,
            recovery_refresh_token=CANONICAL_REFRESH_C,
            recovery_attempt_id=CANONICAL_DEVICE_I,
        )


def _install_beta_snapshot(lic: license_mod.License) -> None:
    license_mod._atomic_beta_replace(
        json.dumps(lic.to_dict(), separators=(",", ":")).encode("utf-8")
    )


def _write_overlapping_refresh_marker() -> Any:
    from elevate_cli import refresh_pending

    pending = refresh_pending.PendingRefresh(
        schema=1,
        operation="refresh",
        license_id="license-1",
        current_refresh_token=CANONICAL_REFRESH_A,
        successor_refresh_token=CANONICAL_DEVICE_D,
        attempt_id=CANONICAL_DEVICE_I,
        created_at=int(time.time()),
    )
    path = license_mod._beta_profile_root() / refresh_pending.MARKER_NAME
    path.write_bytes(pending.to_bytes())
    path.chmod(0o600)
    return pending


def test_exact_beta_device_reconciliation_retains_resumable_prelicense_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    pending = _write_device_pending()

    outcome = license_mod.reconcile_device_pending()

    assert outcome.status == "pending"
    assert outcome.license is None
    assert outcome.pending == pending
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) == pending
    assert not license_mod.LICENSE_PATH.exists()


@pytest.mark.parametrize("refresh_token", [CANONICAL_REFRESH_B, CANONICAL_REFRESH_C])
def test_exact_beta_device_reconciliation_cleans_only_verified_current_b_or_c(
    monkeypatch: pytest.MonkeyPatch,
    refresh_token: str,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    lic = _beta_license(refresh_token=refresh_token, entitlements=[])
    _install_beta_snapshot(lic)
    real_sync = license_mod.sync_license_entitlements
    events: list[str] = []

    def verify_mirror(candidate: license_mod.License) -> None:
        assert refresh_pending.read_device_pending(
            license_mod._beta_profile_root()
        ) is not None
        assert license_mod.read_verified_beta_license_snapshot(
            require_current=True
        ) == candidate
        real_sync(candidate)
        events.append("mirror")

    monkeypatch.setattr(license_mod, "sync_license_entitlements", verify_mirror)

    outcome = license_mod.reconcile_device_pending()

    assert outcome.status == "already_persisted"
    assert outcome.license == lic
    assert outcome.pending is None
    assert events == ["mirror"]
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None


def test_exact_beta_device_reconciliation_retains_marker_when_mirror_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    pending = _write_device_pending()
    lic = _beta_license(refresh_token=CANONICAL_REFRESH_B, entitlements=[])
    _install_beta_snapshot(lic)

    def fail_mirror(_candidate: license_mod.License) -> None:
        raise license_mod.LicenseError(
            "mirror mismatch",
            code="beta_entitlement_persistence_mismatch",
        )

    monkeypatch.setattr(license_mod, "sync_license_entitlements", fail_mirror)

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.reconcile_device_pending()

    assert caught.value.code == "beta_entitlement_persistence_mismatch"
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) == pending
    assert license_mod.read_verified_beta_license_snapshot(require_current=True) == lic


def test_exact_beta_expired_explicit_auth_snapshot_supersedes_stale_device_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    expired = license_mod._beta_license_from_mapping(
        _signed_payload(
            refresh_token=CANONICAL_REFRESH_A,
            entitlements=["real_estate_admin"],
            expires_at=int(time.time()) - 30,
        ),
        require_current=False,
    )
    _install_beta_snapshot(expired)

    outcome = license_mod.reconcile_device_pending()

    assert outcome.status == "beta_auth_superseded"
    assert outcome.license == expired
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=False
    ) == expired


def test_exact_beta_expired_paid_supersession_clears_device_then_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    expired = license_mod._beta_license_from_mapping(
        _signed_payload(
            refresh_token=CANONICAL_REFRESH_A,
            entitlements=["real_estate_admin"],
            expires_at=int(time.time()) - 30,
        ),
        require_current=False,
    )
    _install_beta_snapshot(expired)
    calls: list[str] = []
    fresh_payload = _signed_payload(
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _SuccessClient(calls, fresh_payload, **kwargs),
    )

    fresh = license_mod.ensure_valid()

    assert calls == [f"{license_mod.DEFAULT_BACKEND}/api/license/refresh"]
    assert fresh.entitlements == ["real_estate_admin"]
    assert fresh.expires_at > int(time.time())
    assert fresh.refresh_token != CANONICAL_REFRESH_A
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None
    assert refresh_pending.read_pending(license_mod._beta_profile_root()) is None


@pytest.mark.parametrize("corrupt", ["marker", "license"])
def test_exact_beta_device_reconciliation_fails_closed_on_corrupt_state(
    monkeypatch: pytest.MonkeyPatch,
    corrupt: str,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    pending = _write_device_pending()
    marker_path = license_mod._beta_profile_root() / refresh_pending.DEVICE_MARKER_NAME
    if corrupt == "marker":
        marker_path.write_bytes(b"{}\n")
        marker_path.chmod(0o600)
    else:
        license_mod.LICENSE_PATH.write_bytes(b"{}\n")
        license_mod.LICENSE_PATH.chmod(0o600)
    before_marker = marker_path.read_bytes()
    before_license = (
        license_mod.LICENSE_PATH.read_bytes()
        if license_mod.LICENSE_PATH.exists()
        else None
    )

    with pytest.raises((license_mod.LicenseError, refresh_pending.RefreshPendingError)):
        license_mod.reconcile_device_pending()

    assert marker_path.read_bytes() == before_marker
    assert (
        license_mod.LICENSE_PATH.read_bytes()
        if license_mod.LICENSE_PATH.exists()
        else None
    ) == before_license
    if corrupt == "license":
        assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) == pending


def test_exact_beta_device_reconciliation_rejects_dual_markers_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    _write_overlapping_refresh_marker()
    root = license_mod._beta_profile_root()
    device_path = root / refresh_pending.DEVICE_MARKER_NAME
    refresh_path = root / refresh_pending.MARKER_NAME
    before = (device_path.read_bytes(), refresh_path.read_bytes())

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.reconcile_device_pending()

    assert caught.value.code == "beta_device_state_conflict"
    assert (device_path.read_bytes(), refresh_path.read_bytes()) == before
    assert not license_mod.LICENSE_PATH.exists()


def test_exact_beta_explicit_auth_clears_device_only_after_readback_and_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    payload = _signed_payload(refresh_token=CANONICAL_REFRESH_A, entitlements=[])
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], payload),
    )
    real_sync = license_mod.sync_license_entitlements
    events: list[str] = []

    def verify_mirror(candidate: license_mod.License) -> None:
        assert license_mod.read_verified_beta_license_snapshot(
            require_current=True
        ) == candidate
        assert refresh_pending.read_device_pending(
            license_mod._beta_profile_root()
        ) is not None
        events.append("mirror")
        real_sync(candidate)

    monkeypatch.setattr(license_mod, "sync_license_entitlements", verify_mirror)

    lic = license_mod.login("agent@example.test", "secret-password")

    assert events == ["mirror"]
    assert license_mod.read_verified_beta_license_snapshot(require_current=True) == lic
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None


def test_exact_beta_failed_explicit_auth_retains_device_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    pending = _write_device_pending()
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **kwargs: _RecordingClient([], status_code=401, **kwargs),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "wrong-password")

    assert caught.value.code == "beta_invalid_credentials"
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) == pending
    assert not license_mod.LICENSE_PATH.exists()


def test_exact_beta_logout_clears_license_refresh_then_exact_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    _write_overlapping_refresh_marker()
    lic = _beta_license(refresh_token=CANONICAL_REFRESH_A, entitlements=[])
    _install_beta_snapshot(lic)
    root = license_mod._beta_profile_root()
    events: list[str] = []
    real_replace = license_mod._atomic_beta_replace
    real_remove_refresh = refresh_pending.remove_pending
    real_remove_device = refresh_pending.remove_device_pending

    def record_replace(data: bytes | None) -> None:
        assert data is None
        real_replace(data)
        events.append("license")

    def record_remove_refresh(marker_root: Path) -> None:
        assert not license_mod.LICENSE_PATH.exists()
        real_remove_refresh(marker_root)
        events.append("refresh")

    def record_remove_device(marker_root: Path, expected: Any) -> bool:
        assert not (root / refresh_pending.MARKER_NAME).exists()
        removed = real_remove_device(marker_root, expected)
        events.append("device")
        return removed

    monkeypatch.setattr(license_mod, "_atomic_beta_replace", record_replace)
    monkeypatch.setattr(refresh_pending, "remove_pending", record_remove_refresh)
    monkeypatch.setattr(
        refresh_pending,
        "remove_device_pending",
        record_remove_device,
    )

    assert license_mod.clear() is True
    assert events == ["license", "refresh", "device"]
    assert not license_mod.LICENSE_PATH.exists()
    assert refresh_pending.read_pending(root) is None
    assert refresh_pending.read_device_pending(root) is None


def test_exact_beta_device_cas_never_clears_a_replaced_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    lic = _beta_license(refresh_token=CANONICAL_REFRESH_B, entitlements=[])
    _install_beta_snapshot(lic)
    replacement = refresh_pending.PendingDevice(
        schema=1,
        operation="device",
        device_code=_b64url(b"E" * 32),
        initial_refresh_token=_b64url(b"F" * 32),
        recovery_refresh_token=_b64url(b"G" * 32),
        recovery_attempt_id=_b64url(b"H" * 32),
        created_at=int(time.time()) + 1,
    )

    def replace_instead_of_remove(_root: Path, _expected: Any) -> bool:
        marker_path = (
            license_mod._beta_profile_root() / refresh_pending.DEVICE_MARKER_NAME
        )
        marker_path.write_bytes(replacement.to_bytes())
        marker_path.chmod(0o600)
        return False

    monkeypatch.setattr(
        refresh_pending,
        "remove_device_pending",
        replace_instead_of_remove,
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.reconcile_device_pending()

    assert caught.value.code == "beta_auth_superseded"
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) == replacement
    assert license_mod.read_verified_beta_license_snapshot(require_current=True) == lic


def test_exact_beta_readiness_keeps_valid_superseding_auth_signed_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    lic = _beta_license(refresh_token=CANONICAL_REFRESH_A, entitlements=[])
    _install_beta_snapshot(lic)

    assert license_mod.ensure_valid() == lic
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None


def test_exact_beta_explicit_auth_cas_failure_rolls_back_only_its_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    payload = _signed_payload(refresh_token=CANONICAL_REFRESH_A, entitlements=[])
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], payload),
    )
    replacement = refresh_pending.PendingDevice(
        schema=1,
        operation="device",
        device_code=_b64url(b"J" * 32),
        initial_refresh_token=_b64url(b"K" * 32),
        recovery_refresh_token=_b64url(b"L" * 32),
        recovery_attempt_id=_b64url(b"M" * 32),
        created_at=int(time.time()) + 1,
    )

    def replace_instead_of_remove(_root: Path, _expected: Any) -> bool:
        marker_path = (
            license_mod._beta_profile_root() / refresh_pending.DEVICE_MARKER_NAME
        )
        marker_path.write_bytes(replacement.to_bytes())
        marker_path.chmod(0o600)
        return False

    monkeypatch.setattr(
        refresh_pending,
        "remove_device_pending",
        replace_instead_of_remove,
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == "beta_auth_superseded"
    assert not license_mod.LICENSE_PATH.exists()
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) == replacement


def test_exact_beta_historical_supersession_skips_current_only_access_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    _write_device_pending()
    expired = license_mod._beta_license_from_mapping(
        _signed_payload(
            refresh_token=CANONICAL_REFRESH_A,
            entitlements=["real_estate_admin"],
            expires_at=int(time.time()) - 30,
        ),
        require_current=False,
    )
    _install_beta_snapshot(expired)

    def fail_if_projected(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("historical supersession must not require current access")

    monkeypatch.setattr(
        license_mod,
        "_verify_beta_entitlement_mirror",
        fail_if_projected,
    )

    outcome = license_mod.reconcile_device_pending()

    assert outcome.status == "beta_auth_superseded"
    assert refresh_pending.read_device_pending(license_mod._beta_profile_root()) is None
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=False
    ) == expired


def test_exact_beta_pre_rename_auth_failure_invalidates_paid_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    _install_beta_snapshot(prior)
    response_payload = _signed_payload(
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=[],
    )
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], response_payload),
    )
    real_replace = license_mod._atomic_beta_replace

    def fail_before_rename(data: bytes | None) -> None:
        if data is not None:
            raise OSError("injected pre-rename EIO")
        real_replace(None)

    monkeypatch.setattr(license_mod, "_atomic_beta_replace", fail_before_rename)

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == "beta_license_persistence_failed"
    assert not license_mod.LICENSE_PATH.exists()
    assert license_mod.load() is None


def test_exact_beta_pre_rename_auth_failure_preserves_third_signed_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    _install_beta_snapshot(prior)
    response_payload = _signed_payload(
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=[],
    )
    winner = _beta_license(
        refresh_token=CANONICAL_REFRESH_C,
        entitlements=["real_estate_sales"],
    )
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], response_payload),
    )
    real_replace = license_mod._atomic_beta_replace

    def install_winner_then_fail(data: bytes | None) -> None:
        if data is not None:
            real_replace(json.dumps(winner.to_dict()).encode("utf-8"))
            raise OSError("injected post-winner EIO")
        real_replace(None)

    monkeypatch.setattr(
        license_mod,
        "_atomic_beta_replace",
        install_winner_then_fail,
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == "beta_license_persistence_failed"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == winner


@pytest.mark.parametrize("flow", ["login", "create_account", "login_with_code"])
def test_exact_beta_delayed_explicit_auth_cannot_overwrite_full_snapshot_winner(
    monkeypatch: pytest.MonkeyPatch,
    flow: str,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        access_token="prior-access",
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    winner = _beta_license(
        access_token="winner-access",
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_sales"],
    )
    stale_payload = _signed_payload(
        access_token="stale-response-access",
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=[],
    )
    _install_beta_snapshot(prior)

    class _DelayedClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _SuccessResponse:
            assert json["email"] == "agent@example.test"
            _install_beta_snapshot(winner)
            return _SuccessResponse(stale_payload)

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _DelayedClient())

    with pytest.raises(license_mod.LicenseError) as caught:
        if flow == "login":
            license_mod.login("agent@example.test", "secret-password")
        elif flow == "create_account":
            license_mod.create_account("agent@example.test", "secret-password")
        else:
            license_mod.login_with_code("agent@example.test", "123456")

    assert caught.value.code == "beta_auth_superseded"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == winner


@pytest.mark.parametrize(
    "winner_refresh_token",
    [CANONICAL_REFRESH_C, CANONICAL_REFRESH_A],
    ids=["new-token", "same-token-different-assertion"],
)
def test_exact_beta_delayed_device_approval_cannot_overwrite_newer_login(
    monkeypatch: pytest.MonkeyPatch,
    winner_refresh_token: str,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(license_mod.time, "sleep", lambda _seconds: None)
    prior = _beta_license(
        access_token="prior-access",
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    winner = _beta_license(
        access_token="winner-access",
        refresh_token=winner_refresh_token,
        entitlements=["real_estate_sales"],
    )
    stale_approval = {
        "status": "approved",
        **_signed_payload(
            access_token="stale-device-access",
            refresh_token=CANONICAL_REFRESH_B,
            entitlements=[],
        ),
    }
    start_payload = {
        "device_code": "device-code",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://example.test/link",
        "expires_in": 60,
        "interval": 1,
    }
    _install_beta_snapshot(prior)
    pending_device = _write_device_pending()

    class _DelayedDeviceClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, url: str, *, json: dict[str, Any]) -> _SuccessResponse:
            assert json
            if url.endswith("/api/device/start"):
                return _SuccessResponse(start_payload)
            assert url.endswith("/api/device/poll")
            _install_beta_snapshot(winner)
            return _SuccessResponse(stale_approval)

    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _DelayedDeviceClient(),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.link_device("Realtor Mac", interval_override=1)

    assert caught.value.code == "beta_auth_superseded"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == winner
    assert refresh_pending.read_device_pending(
        license_mod._beta_profile_root()
    ) == pending_device


def test_exact_beta_precondition_mismatch_preserves_winner_identical_to_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        access_token="prior-access",
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    response_payload = _signed_payload(
        access_token="winner-access",
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=["real_estate_sales"],
    )
    winner = license_mod._beta_license_from_mapping(response_payload)
    _install_beta_snapshot(prior)

    class _IdenticalWinnerClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _SuccessResponse:
            assert json["email"] == "agent@example.test"
            _install_beta_snapshot(winner)
            return _SuccessResponse(response_payload)

    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _IdenticalWinnerClient(),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == "beta_auth_superseded"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == winner


def test_exact_beta_prewrite_marker_failure_preserves_response_identical_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        access_token="prior-access",
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    response_payload = _signed_payload(
        access_token="winner-access",
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=["real_estate_sales"],
    )
    winner = license_mod._beta_license_from_mapping(response_payload)
    _install_beta_snapshot(prior)
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], response_payload),
    )

    def install_winner_then_fail(_root: Path) -> tuple[Any | None, Any | None]:
        _install_beta_snapshot(winner)
        raise license_mod.LicenseError(
            "injected marker failure",
            code="beta_device_state_corrupt",
        )

    monkeypatch.setattr(
        license_mod,
        "_read_beta_credential_markers_unlocked",
        install_winner_then_fail,
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == "beta_device_state_corrupt"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == winner


def test_exact_beta_explicit_auth_repairs_unchanged_private_corrupt_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    license_mod.LICENSE_PATH.write_bytes(b'{"partial":')
    license_mod.LICENSE_PATH.chmod(0o600)
    payload = _signed_payload(
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=["real_estate_admin"],
    )
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], payload),
    )

    repaired = license_mod.login("agent@example.test", "secret-password")

    assert repaired.entitlements == ["real_estate_admin"]
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == repaired


def test_exact_beta_invalid_predecessor_write_failure_preserves_signed_third_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    license_mod.LICENSE_PATH.write_bytes(b'{"partial":')
    license_mod.LICENSE_PATH.chmod(0o600)
    response_payload = _signed_payload(
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=[],
    )
    winner = _beta_license(
        access_token="winner-access",
        refresh_token=CANONICAL_REFRESH_C,
        entitlements=["real_estate_sales"],
    )
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], response_payload),
    )
    real_replace = license_mod._atomic_beta_replace

    def install_winner_then_fail(data: bytes | None) -> None:
        if data is not None:
            real_replace(json.dumps(winner.to_dict()).encode("utf-8"))
            raise OSError("injected valid third winner")
        real_replace(None)

    monkeypatch.setattr(license_mod, "_atomic_beta_replace", install_winner_then_fail)

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == "beta_license_persistence_failed"
    assert license_mod.read_verified_beta_license_snapshot(
        require_current=True
    ) == winner


@pytest.mark.parametrize("corrupt_marker", ["refresh", "device"])
def test_exact_beta_logout_clears_license_and_other_marker_despite_corrupt_marker(
    monkeypatch: pytest.MonkeyPatch,
    corrupt_marker: str,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    _install_beta_snapshot(prior)
    _write_device_pending()
    _write_overlapping_refresh_marker()
    root = license_mod._beta_profile_root()
    refresh_path = root / refresh_pending.MARKER_NAME
    device_path = root / refresh_pending.DEVICE_MARKER_NAME
    corrupt_path = refresh_path if corrupt_marker == "refresh" else device_path
    other_path = device_path if corrupt_marker == "refresh" else refresh_path
    corrupt_path.write_bytes(b"{}\n")
    corrupt_path.chmod(0o600)
    before = corrupt_path.read_bytes()

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.clear()

    assert caught.value.code.startswith("beta_")
    assert not license_mod.LICENSE_PATH.exists()
    assert license_mod.load() is None
    assert corrupt_path.read_bytes() == before
    assert not other_path.exists()


@pytest.mark.parametrize("marker_fault", ["corrupt_device", "dual_valid"])
def test_exact_beta_signed_auth_marker_failure_invalidates_captured_paid_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    marker_fault: str,
) -> None:
    from elevate_cli import refresh_pending

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    prior = _beta_license(
        refresh_token=CANONICAL_REFRESH_A,
        entitlements=["real_estate_admin"],
    )
    _install_beta_snapshot(prior)
    _write_device_pending()
    root = license_mod._beta_profile_root()
    device_path = root / refresh_pending.DEVICE_MARKER_NAME
    if marker_fault == "corrupt_device":
        device_path.write_bytes(b"{}\n")
        device_path.chmod(0o600)
        marker_paths = [device_path]
    else:
        _write_overlapping_refresh_marker()
        marker_paths = [device_path, root / refresh_pending.MARKER_NAME]
    before = {path: path.read_bytes() for path in marker_paths}
    response_payload = _signed_payload(
        refresh_token=CANONICAL_REFRESH_B,
        entitlements=[],
    )
    monkeypatch.setattr(
        license_mod.httpx,
        "Client",
        lambda **_kwargs: _SuccessClient([], response_payload),
    )

    with pytest.raises(license_mod.LicenseError) as caught:
        license_mod.login("agent@example.test", "secret-password")

    assert caught.value.code == (
        "beta_device_state_conflict"
        if marker_fault == "dual_valid"
        else "beta_device_state_corrupt"
    )
    assert not license_mod.LICENSE_PATH.exists()
    assert license_mod.load() is None
    assert {path: path.read_bytes() for path in marker_paths} == before


def test_exact_beta_auth_and_refresh_never_read_or_surface_upstream_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    canary = "HQ-SECRET-BODY-CANARY"

    class _NoBodyResponse:
        status_code = 503
        is_success = False

        @property
        def text(self) -> str:
            raise AssertionError(f"exact Beta read secret body: {canary}")

    class _NoBodyClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, Any]) -> _NoBodyResponse:
            assert json
            return _NoBodyResponse()

    monkeypatch.setattr(license_mod.httpx, "Client", lambda **_kwargs: _NoBodyClient())

    with pytest.raises(license_mod.LicenseError) as login_error:
        license_mod.login("agent@example.test", "secret-password")
    assert login_error.value.code == "beta_auth_upstream_failed"
    assert canary not in str(login_error.value)

    current = _beta_license(refresh_token=CANONICAL_REFRESH_A, entitlements=[])
    _install_beta_snapshot(current)
    with pytest.raises(license_mod.LicenseError) as refresh_error:
        license_mod.refresh(current)
    assert refresh_error.value.code == "beta_auth_upstream_failed"
    assert canary not in str(refresh_error.value)
