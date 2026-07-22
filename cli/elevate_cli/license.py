"""
Elevate subscription license gate.

Lives alongside (but independent of) the BYOK auth system. That system
handles LLM provider credentials. This module handles the paid
subscription to the Elevation Real Estate HQ skill library.

Flow:
    elevate activate          -> POST /api/auth/login, stores license.json,
                                 syncs entitlements, unlocks paid packs
    elevate subscribe         -> backwards-compatible alias for activate
    elevate license status    -> show current license
    elevate license logout    -> delete license.json
    ensure_valid_license()   -> used by premium/cloud skill commands

License file layout (~/.elevate/license.json):
    {
      "access_token": "...",
      "refresh_token": "...",
      "license_id": "uuid",
      "tier": "pro" | "builder",
      "email": "user@...",
      "expires_at": 1234567890,
      "entitlement_assertion": "<backend-signed compact JWS>"
    }
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

DEFAULT_BACKEND = "https://api.elevationrealestatehq.com"
BACKEND_URL = os.environ.get("ELEVATE_BACKEND_URL", DEFAULT_BACKEND).rstrip("/")

LICENSE_PATH = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate") / "license.json"

# Sibling marker — counts consecutive 401s from /api/license/refresh so a
# transient HQ blip (network flap, deploy, brief auth race) doesn't nuke the
# user's session on the first failure. Wiping license.json on every 401 was
# the root cause of "I'm signed in but the modal pops on startup" — by the
# time the user opened the desktop, the gateway had already cleared the file
# in the background.
LICENSE_FAIL_PATH = LICENSE_PATH.parent / ".license_refresh_failures"
LICENSE_FAIL_THRESHOLD = 3

# Refresh when <5 minutes of access-token life remain.
REFRESH_MARGIN_SECONDS = 300
_STARTING_SNAPSHOT_UNSET = object()
_EXPECTED_PENDING_UNSET = object()
_BETA_ACTIVATION_RECEIPT_NAME = ".license-activation.json"
_BETA_ACTIVATION_RECEIPT_SCHEMA = 2
_BETA_ACTIVATION_RECEIPT_MAX_BYTES = 16 * 1024


def _read_fail_count() -> int:
    try:
        return int(LICENSE_FAIL_PATH.read_text().strip() or "0")
    except (OSError, ValueError):
        return 0


def _bump_fail_count() -> int:
    n = _read_fail_count() + 1
    try:
        LICENSE_FAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
        LICENSE_FAIL_PATH.write_text(str(n))
    except OSError:
        pass
    return n


def _reset_fail_count() -> None:
    try:
        if LICENSE_FAIL_PATH.exists():
            LICENSE_FAIL_PATH.unlink()
    except OSError:
        pass


@dataclass
class License:
    access_token: str
    refresh_token: str
    license_id: str
    tier: str
    email: str
    expires_at: int
    entitlements: list[str] | None = None
    entitlement_assertion: str | None = None
    subject: str | None = None

    def is_expired(self, margin: int = REFRESH_MARGIN_SECONDS) -> bool:
        return time.time() > (self.expires_at - margin)

    def to_dict(self) -> dict:
        payload = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "license_id": self.license_id,
            "tier": self.tier,
            "email": self.email,
            "expires_at": self.expires_at,
        }
        if self.entitlements is not None:
            payload["entitlements"] = list(self.entitlements)
        if self.entitlement_assertion is not None:
            payload["entitlement_assertion"] = self.entitlement_assertion
        if self.subject is not None:
            payload["subject"] = self.subject
        return payload


class LicenseError(Exception):
    """Raised when license is missing, revoked, or cannot be refreshed."""

    def __init__(self, message: str, *, code: str = "license_error") -> None:
        super().__init__(message)
        self.code = code

    def as_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class DevicePendingReconciliation:
    """Typed result of reconciling one exact-Beta Device marker.

    ``pending`` preserves pre-license recovery authority. ``interim_persisted``
    keeps signed B and the marker. ``already_persisted`` proves that signed C
    made the marker obsolete and durably removes it.
    ``predecessor_unverifiable`` retains both a signed non-B/C snapshot and the
    marker because their ordering cannot be reconstructed after restart.
    """

    status: str
    license: License | None
    pending: Any | None


@dataclass(frozen=True)
class _InvalidBetaSnapshotFingerprint:
    """Identity for one safe-but-unusable local license artifact."""

    sha256: str
    size: int


_BetaLocalSnapshotState = License | _InvalidBetaSnapshotFingerprint | None


@dataclass(frozen=True)
class _BetaInitialAuthAttempt:
    """Caller-owned B/C/I retained across an ambiguous initial auth response."""

    pending: Any
    starting_snapshot: _BetaLocalSnapshotState
    recover_first: bool


def _exact_realtor_beta_active() -> bool:
    """Return true only for the signed Realtor Beta release identity."""
    from elevate_cli.beta_provider_policy import beta_provider_policy_active

    return beta_provider_policy_active()


def _signed_beta_backend_url() -> str:
    """Return the backend identity compiled into the signed application."""
    backend = str(DEFAULT_BACKEND or "").strip().rstrip("/")
    if not backend:
        raise LicenseError(
            "Realtor Beta could not verify its Elevation Real Estate HQ "
            "sign-in service. Restart the app and try again.",
            code="beta_backend_identity_unavailable",
        )
    return backend


def _beta_profile_root() -> Path:
    """Return the profile root fixed by the signed Beta product identity."""
    return Path.home() / ".elevate-beta"


def _beta_store_error(code: str, message: str) -> LicenseError:
    return LicenseError(message, code=code)


def _auth_flow_error(
    message: str,
    *,
    beta_code: str,
    beta_message: str | None = None,
) -> LicenseError:
    """Keep Stable errors compatible while making every Beta path typed."""
    if _exact_realtor_beta_active():
        return LicenseError(beta_message or message, code=beta_code)
    return LicenseError(
        message,
        code="license_error",
    )


def _post_hq(base_url: str, path: str, payload: dict[str, Any]):
    try:
        with httpx.Client(timeout=15.0) as client:
            return client.post(f"{base_url}{path}", json=payload)
    except httpx.HTTPError as exc:
        if _exact_realtor_beta_active():
            raise LicenseError(
                "Elevation HQ could not be reached. Check your connection and try again.",
                code="beta_auth_upstream_unavailable",
            ) from exc
        raise


def _response_json(response: Any) -> Any:
    try:
        return response.json()
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if _exact_realtor_beta_active():
            raise LicenseError(
                "Elevation HQ returned an invalid account response.",
                code="beta_license_response_invalid",
            ) from exc
        raise


def preflight_beta_license_store(*, require_writable: bool = True) -> None:
    """Validate the exact-Beta license store before auth I/O.

    The path is bound to the product's dedicated local profile. Symlinked,
    hardlinked, cross-profile, managed, foreign-owned, and unwritable stores
    fail closed. A short exclusive-create probe proves write access instead of
    trusting ``os.access`` (which can lie under elevated test/runtime users).
    """
    if not _exact_realtor_beta_active():
        return

    root = _beta_profile_root().expanduser().absolute()
    license_path = LICENSE_PATH.expanduser().absolute()
    if license_path.name != "license.json" or license_path.parent != root:
        raise _beta_store_error(
            "beta_license_store_not_local",
            "Realtor Beta will only use its dedicated local Beta profile.",
        )

    try:
        from elevate_cli.config import is_managed

        if is_managed() or (root / ".managed").exists():
            raise _beta_store_error(
                "beta_license_store_managed",
                "This managed Realtor Beta profile cannot persist an account session.",
            )

        parent = root.parent
        if parent.is_symlink() or not parent.is_dir():
            raise _beta_store_error(
                "beta_license_store_not_local",
                "Realtor Beta could not verify its local profile parent.",
            )
        if not root.exists():
            if not require_writable:
                raise _beta_store_error(
                    "beta_license_snapshot_invalid",
                    "The Realtor Beta account snapshot is missing.",
                )
            root.mkdir(mode=0o700)
        root_lstat = root.lstat()
        if root.is_symlink() or not stat.S_ISDIR(root_lstat.st_mode):
            raise _beta_store_error(
                "beta_license_store_not_local",
                "Realtor Beta will not use a linked or non-directory profile.",
            )
        if root.resolve() != root or root_lstat.st_dev != parent.stat().st_dev:
            raise _beta_store_error(
                "beta_license_store_not_local",
                "Realtor Beta will not use a redirected or nonlocal profile.",
            )
        if hasattr(os, "getuid") and root_lstat.st_uid != os.getuid():
            raise _beta_store_error(
                "beta_license_store_not_local",
                "Realtor Beta will not use a profile owned by another account.",
            )
        if root_lstat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise _beta_store_error(
                "beta_license_store_not_private",
                "The Realtor Beta profile is writable by another account.",
            )
        if require_writable and not (root_lstat.st_mode & stat.S_IWUSR):
            raise _beta_store_error(
                "beta_license_store_unwritable",
                "The Realtor Beta profile is not writable by this account.",
            )

        if license_path.exists() or license_path.is_symlink():
            license_lstat = license_path.lstat()
            if (
                license_path.is_symlink()
                or not stat.S_ISREG(license_lstat.st_mode)
                or license_lstat.st_nlink != 1
                or (hasattr(os, "getuid") and license_lstat.st_uid != os.getuid())
            ):
                raise _beta_store_error(
                    "beta_license_store_not_local",
                    "Realtor Beta will not use a linked or shared license store.",
                )
            if stat.S_IMODE(license_lstat.st_mode) & 0o077:
                raise _beta_store_error(
                    "beta_license_store_not_private",
                    "The Realtor Beta account snapshot is readable by another account.",
                )

        if require_writable:
            dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            dir_flags |= getattr(os, "O_NOFOLLOW", 0)
            dir_fd = os.open(root, dir_flags)
            probe_name = f".license-preflight-{uuid.uuid4().hex}"
            try:
                probe_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                probe_flags |= getattr(os, "O_NOFOLLOW", 0)
                probe_fd = os.open(probe_name, probe_flags, 0o600, dir_fd=dir_fd)
                try:
                    os.write(probe_fd, b"ok")
                    os.fsync(probe_fd)
                finally:
                    os.close(probe_fd)
                os.unlink(probe_name, dir_fd=dir_fd)
            finally:
                try:
                    os.unlink(probe_name, dir_fd=dir_fd)
                except OSError:
                    pass
                os.close(dir_fd)
    except LicenseError:
        raise
    except Exception as exc:
        raise _beta_store_error(
            "beta_license_store_unavailable",
            "Realtor Beta could not verify its local account store.",
        ) from exc


def backend_url() -> str:
    """Return the configured Elevation HQ license/skill API origin."""
    # Exact Beta never trusts the mutable module global or profile/process
    # environment.  Every caller (login, refresh, device link, cloud skills,
    # automations, diagnostics, and startup sync) resolves through this
    # compiled identity at the moment it creates its HTTP client.
    if _exact_realtor_beta_active():
        preflight_beta_license_store(require_writable=True)
        return _signed_beta_backend_url()
    if not BACKEND_URL:
        raise LicenseError(
            "Elevation Real Estate HQ backend URL is not configured. "
            "Set ELEVATE_BACKEND_URL before running `elevate activate`.",
        )
    return BACKEND_URL


def configure_backend_override(
    backend_url_value: Optional[str],
    *,
    persist: bool,
) -> str:
    """Apply a legacy backend override or reject it for exact Realtor Beta.

    ``None`` means the caller did not request an override.  Empty strings are
    still rejected in Beta when the option/field was explicitly supplied, so
    the API and terminal can truthfully report that custom endpoints are not a
    supported Beta control.  Stable retains the historical mutable behavior.
    """
    global BACKEND_URL

    if _exact_realtor_beta_active():
        if backend_url_value is not None:
            raise LicenseError(
                "Realtor Beta connects account sign-in only to Elevation Real "
                "Estate HQ. Remove the custom backend URL and try again.",
                code="beta_backend_override_not_allowed",
            )
        return _signed_beta_backend_url()

    backend = str(backend_url_value or "").strip().rstrip("/")
    if not backend:
        # Preserve Stable's historical no-op semantics. The eventual network
        # caller remains responsible for reporting a missing backend.
        return BACKEND_URL

    BACKEND_URL = backend
    os.environ["ELEVATE_BACKEND_URL"] = backend
    if persist:
        try:
            from elevate_cli.config import save_env_value

            save_env_value("ELEVATE_BACKEND_URL", backend)
        except Exception:
            pass
    return backend


def _decode_jwt_exp(token: str) -> int:
    """Extract exp claim without verifying signature. The server is authoritative."""
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        return int(payload.get("exp", 0))
    except Exception:
        return 0


def _normalize_entitlement_name(name: str) -> str:
    text = str(name or "").strip()
    aliases = {
        "realEstateSales": "real_estate_sales",
        "realEstateMarketing": "real_estate_marketing",
        "realEstateAdmin": "real_estate_admin",
        "realEstateCma": "real_estate_cma",
        "real_estate_cma": "real_estate_cma",
    }
    return aliases.get(text, text)


def _normalize_entitlements(value: Any) -> list[str] | None:
    if value is None:
        return None
    raw: list[Any]
    if isinstance(value, dict):
        raw = [key for key, enabled in value.items() if enabled]
    elif isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        return None

    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = _normalize_entitlement_name(str(item or ""))
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _canonical_beta_license(
    *,
    access_token: str,
    refresh_token: str,
    entitlement_assertion: str,
    require_current: bool = True,
) -> License:
    """Derive every Beta paid field from one verified signed assertion."""
    try:
        from elevate_cli.entitlement_assertion import (
            EntitlementAssertionError,
            verify_entitlement_assertion,
        )
    except Exception as exc:
        raise LicenseError(
            "The Realtor Beta entitlement verifier is unavailable.",
            code="beta_entitlement_verifier_unavailable",
        ) from exc

    try:
        claims = verify_entitlement_assertion(
            entitlement_assertion,
            access_token=access_token,
            refresh_token=refresh_token,
            require_current=require_current,
        )
    except EntitlementAssertionError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc
    entitlements = _normalize_entitlements(list(claims.entitlements))
    if entitlements is None:
        raise LicenseError(
            "The Realtor Beta entitlement assertion is incomplete.",
            code="beta_entitlement_claim_invalid",
        )
    return License(
        access_token=access_token,
        refresh_token=refresh_token,
        license_id=claims.license_id,
        tier=claims.tier,
        email=claims.email,
        expires_at=claims.expires_at,
        entitlements=entitlements,
        entitlement_assertion=entitlement_assertion,
        subject=claims.subject,
    )


def _require_beta_response_duplicates_match(
    raw: dict[str, Any],
    canonical: License,
) -> None:
    """Reject unsigned response/snapshot fields that contradict the signer."""
    scalar_fields: dict[str, object] = {
        "license_id": canonical.license_id,
        "email": canonical.email,
        "tier": canonical.tier,
        "expires_at": canonical.expires_at,
        "subject": canonical.subject,
    }
    for name, expected in scalar_fields.items():
        if name in raw and raw.get(name) != expected:
            raise LicenseError(
                f"The Realtor Beta {name} field did not match its signed assertion.",
                code="beta_entitlement_response_mismatch",
            )
    if "sub" in raw and raw.get("sub") != canonical.subject:
        raise LicenseError(
            "The Realtor Beta subject field did not match its signed assertion.",
            code="beta_entitlement_response_mismatch",
        )
    if "expires_in" in raw and raw.get("expires_in") != 3600:
        raise LicenseError(
            "The Realtor Beta expiry field did not match its signed assertion.",
            code="beta_entitlement_response_mismatch",
        )
    for name in ("entitlements", "packs", "features"):
        if name not in raw:
            continue
        duplicate = _normalize_entitlements(raw.get(name))
        if duplicate != canonical.entitlements:
            raise LicenseError(
                "The Realtor Beta entitlement fields did not match their signed assertion.",
                code="beta_entitlement_response_mismatch",
            )


def _beta_license_from_mapping(
    raw: object,
    *,
    require_current: bool = True,
) -> License:
    """Build a canonical Beta license from an HQ response or local snapshot."""
    if not isinstance(raw, dict):
        raise LicenseError(
            "The account snapshot is not a JSON object.",
            code="beta_license_snapshot_invalid",
        )
    try:
        access_token = raw["access_token"]
        refresh_token = raw["refresh_token"]
        assertion = raw["entitlement_assertion"]
        if not all(isinstance(value, str) and value for value in (
            access_token,
            refresh_token,
            assertion,
        )):
            raise TypeError("signed token fields must be non-empty strings")
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseError(
            "The Realtor Beta account snapshot has no signed entitlement assertion. "
            "Sign in again.",
            code="beta_entitlement_assertion_missing",
        ) from exc
    canonical = _canonical_beta_license(
        access_token=access_token,
        refresh_token=refresh_token,
        entitlement_assertion=assertion,
        require_current=require_current,
    )
    _require_beta_response_duplicates_match(raw, canonical)
    return canonical


def _extract_entitlements(data: dict[str, Any]) -> list[str] | None:
    for key in ("entitlements", "packs", "features"):
        if key in data:
            return _normalize_entitlements(data.get(key))
    return None


def _complete_entitlements_from_response(
    data: dict[str, Any],
    *,
    fallback: list[str] | None = None,
) -> list[str] | None:
    entitlements = _extract_entitlements(data)
    if _exact_realtor_beta_active() and entitlements is None:
        raise LicenseError(
            "Elevation HQ did not return a complete entitlement snapshot. "
            "No paid Realtor Beta access was changed.",
            code="beta_entitlement_snapshot_missing",
        )
    return fallback if entitlements is None else entitlements


def _validate_complete_beta_license(lic: License, *, require_current: bool) -> None:
    if not _exact_realtor_beta_active():
        return
    canonical = _beta_license_from_mapping(
        lic.to_dict(),
        require_current=require_current,
    )
    if canonical.to_dict() != lic.to_dict():
        raise LicenseError(
            "The Realtor Beta account snapshot did not match its signed assertion.",
            code="beta_entitlement_response_mismatch",
        )


def _parse_license_payload(raw: object) -> License:
    if _exact_realtor_beta_active():
        return _beta_license_from_mapping(raw)
    if not isinstance(raw, dict):
        raise LicenseError(
            "The account snapshot is not a JSON object.",
            code="beta_license_snapshot_invalid",
        )
    try:
        return License(
            access_token=str(raw["access_token"]),
            refresh_token=str(raw["refresh_token"]),
            license_id=str(raw["license_id"]),
            tier=str(raw.get("tier", "pro")),
            email=str(raw.get("email", "")),
            expires_at=int(raw.get("expires_at", 0)),
            entitlements=_normalize_entitlements(raw.get("entitlements"))
            if "entitlements" in raw
            else None,
            entitlement_assertion=str(raw.get("entitlement_assertion"))
            if raw.get("entitlement_assertion")
            else None,
            subject=str(raw.get("subject")) if raw.get("subject") else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseError(
            "The account snapshot is malformed.",
            code="beta_license_snapshot_invalid",
        ) from exc


def read_verified_beta_license_snapshot(*, require_current: bool) -> License:
    """Read a signature-verified local Beta snapshot or raise typed.

    Historical mode authenticates an expired snapshot only so its bound refresh
    token and account identity can be continued. Paid access gates always call
    this reader with ``require_current=True``.
    """
    preflight_beta_license_store(require_writable=False)
    try:
        raw = json.loads(_read_beta_snapshot_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError(
            "The Realtor Beta account snapshot is missing or unreadable.",
            code="beta_license_snapshot_invalid",
        ) from exc
    lic = _beta_license_from_mapping(raw, require_current=require_current)
    _validate_complete_beta_license(lic, require_current=require_current)
    return lic


def _read_beta_snapshot_bytes() -> bytes:
    """Read license.json without following its final path component."""
    root = _beta_profile_root().expanduser().absolute()
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    dir_flags |= getattr(os, "O_NOFOLLOW", 0)
    dir_fd = os.open(root, dir_flags)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open("license.json", flags, dir_fd=dir_fd)
        try:
            file_stat = os.fstat(fd)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_nlink != 1
                or stat.S_IMODE(file_stat.st_mode) & 0o077
                or (hasattr(os, "getuid") and file_stat.st_uid != os.getuid())
            ):
                raise OSError("license snapshot is not a private regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


def _atomic_beta_replace(data: bytes | None) -> None:
    """Replace or remove license.json through a no-follow profile directory fd."""
    root = _beta_profile_root().expanduser().absolute()
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    dir_flags |= getattr(os, "O_NOFOLLOW", 0)
    dir_fd = os.open(root, dir_flags)
    tmp_name = f".license-{uuid.uuid4().hex}.tmp"
    try:
        if data is None:
            try:
                os.unlink("license.json", dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            try:
                os.stat("license.json", dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise OSError("license snapshot removal could not be verified")
            os.fsync(dir_fd)
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("license snapshot write made no progress")
                view = view[written:]
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(
            tmp_name,
            "license.json",
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
        )
        target_stat = os.stat("license.json", dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISREG(target_stat.st_mode) or target_stat.st_nlink != 1:
            raise OSError("atomic license target is not a private regular file")
        os.fsync(dir_fd)
    finally:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        os.close(dir_fd)


def _beta_activation_identity(lic: License) -> str:
    payload = {
        "email": lic.email,
        "entitlements": sorted(set(lic.entitlements or [])),
        "license_id": lic.license_id,
        "subject": lic.subject,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_beta_activation_receipt_replace(data: bytes | None) -> None:
    """Replace/remove the non-secret setup receipt under the private root."""
    root = _beta_profile_root().expanduser().absolute()
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    dir_flags |= getattr(os, "O_NOFOLLOW", 0)
    dir_fd = os.open(root, dir_flags)
    tmp_name = f".license-activation-{uuid.uuid4().hex}.tmp"
    try:
        if data is None:
            try:
                os.unlink(_BETA_ACTIVATION_RECEIPT_NAME, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            os.fsync(dir_fd)
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("activation receipt write made no progress")
                view = view[written:]
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(
            tmp_name,
            _BETA_ACTIVATION_RECEIPT_NAME,
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
        )
        target = os.stat(
            _BETA_ACTIVATION_RECEIPT_NAME,
            dir_fd=dir_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(target.st_mode) or target.st_nlink != 1:
            raise OSError("activation receipt target is not a private regular file")
        os.fsync(dir_fd)
    finally:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        os.close(dir_fd)


def _read_beta_activation_receipt_unlocked() -> dict[str, Any] | None:
    root = _beta_profile_root().expanduser().absolute()
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    dir_flags |= getattr(os, "O_NOFOLLOW", 0)
    dir_fd = os.open(root, dir_flags)
    fd: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(_BETA_ACTIVATION_RECEIPT_NAME, flags, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        file_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_nlink != 1
            or stat.S_IMODE(file_stat.st_mode) & 0o077
            or (hasattr(os, "getuid") and file_stat.st_uid != os.getuid())
            or file_stat.st_size > _BETA_ACTIVATION_RECEIPT_MAX_BYTES
        ):
            raise LicenseError(
                "Realtor Beta could not verify its private setup receipt.",
                code="beta_activation_receipt_invalid",
            )
        raw = os.read(fd, _BETA_ACTIVATION_RECEIPT_MAX_BYTES + 1)
        if len(raw) > _BETA_ACTIVATION_RECEIPT_MAX_BYTES:
            raise LicenseError(
                "Realtor Beta setup receipt is too large.",
                code="beta_activation_receipt_invalid",
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LicenseError(
                "Realtor Beta setup receipt is invalid.",
                code="beta_activation_receipt_invalid",
            ) from exc
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema",
                "identity_sha256",
                "skill_bundle_sha256",
                "completed_at",
            }
            or value.get("schema") != _BETA_ACTIVATION_RECEIPT_SCHEMA
            or not isinstance(value.get("completed_at"), int)
            or isinstance(value.get("completed_at"), bool)
            or value.get("completed_at", -1) < 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("identity_sha256", "")))
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(value.get("skill_bundle_sha256", "")),
            )
        ):
            raise LicenseError(
                "Realtor Beta setup receipt is invalid.",
                code="beta_activation_receipt_invalid",
            )
        return value
    finally:
        if fd is not None:
            os.close(fd)
        os.close(dir_fd)


def _invalidate_beta_snapshot_unlocked(message: str) -> None:
    """Remove local paid state while the caller owns the refresh lock."""
    try:
        _atomic_beta_replace(None)
    except Exception as exc:
        raise LicenseError(
            message,
            code="beta_license_persistence_failed",
        ) from exc


def _invalidate_beta_snapshot(message: str) -> None:
    """Remove all local paid state under the shared mutation lock."""
    if not _exact_realtor_beta_active():
        return
    from elevate_cli import refresh_pending

    try:
        preflight_beta_license_store(require_writable=True)
        root = _beta_profile_root().expanduser().absolute()
        with refresh_pending.refresh_lock(root) as lock_guard:
            pending = refresh_pending.read_pending(root)
            lock_guard.assert_held()
            _invalidate_beta_snapshot_unlocked(message)
            if pending is not None:
                lock_guard.assert_held()
                refresh_pending.remove_pending(root)
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _invalidate_beta_snapshot_if_matches_unlocked(
    lic: License,
    message: str,
) -> bool:
    """Remove only a matching snapshot while the caller owns the lock.

    Another process may already have rotated and persisted a new signed token
    pair.  A late 401 for the old pair must never erase that newer session.
    """
    try:
        current = read_verified_beta_license_snapshot(require_current=False)
    except LicenseError:
        _invalidate_beta_snapshot_unlocked(message)
        return True
    if not _same_beta_snapshot(current, lic):
        return False
    _invalidate_beta_snapshot_unlocked(message)
    return True


def _invalidate_beta_snapshot_if_matches(lic: License, message: str) -> bool:
    """Remove a matching snapshot under the shared mutation lock."""
    if not _exact_realtor_beta_active():
        return False
    from elevate_cli import refresh_pending

    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(
            _beta_profile_root().expanduser().absolute()
        ) as lock_guard:
            root = _beta_profile_root().expanduser().absolute()
            pending = refresh_pending.read_pending(root)
            lock_guard.assert_held()
            removed = _invalidate_beta_snapshot_if_matches_unlocked(lic, message)
            if removed and pending is not None:
                lock_guard.assert_held()
                refresh_pending.remove_pending(root)
            return removed
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _same_beta_snapshot(left: License, right: License) -> bool:
    """Compare the signed state that authorizes one refresh mutation."""
    return (
        left.access_token == right.access_token
        and left.refresh_token == right.refresh_token
        and left.license_id == right.license_id
        and left.entitlement_assertion == right.entitlement_assertion
        and left.subject == right.subject
    )


def beta_activation_complete(lic: License) -> bool:
    """Return true only for a receipt bound to the account and shipped skills."""
    if not _exact_realtor_beta_active():
        return True
    from elevate_cli.beta_skill_bundle import load_exact_beta_skill_bundle
    from elevate_cli import refresh_pending

    try:
        bundle = load_exact_beta_skill_bundle()
        preflight_beta_license_store(require_writable=False)
        root = _beta_profile_root().expanduser().absolute()
        with refresh_pending.refresh_lock(root) as lock_guard:
            lock_guard.assert_held()
            current = read_verified_beta_license_snapshot(require_current=True)
            # A desktop refresh can rotate the access token, refresh token,
            # and signed assertion after the status route read ``lic`` but
            # before this lock is acquired. Setup is bound to the stable
            # signed account identity, not to that rotating credential pair.
            current_identity = _beta_activation_identity(current)
            if current_identity != _beta_activation_identity(lic):
                return False
            receipt = _read_beta_activation_receipt_unlocked()
            return bool(
                receipt
                and receipt.get("identity_sha256") == current_identity
                and receipt.get("skill_bundle_sha256") == bundle.sha256
            )
    except (
        LicenseError,
        refresh_pending.RefreshPendingError,
        OSError,
        RuntimeError,
    ):
        return False


def _mark_beta_activation_complete(
    lic: License,
    *,
    skill_bundle_sha256: str,
) -> None:
    """Durably bind successful required setup to the current signed account."""
    if not _exact_realtor_beta_active():
        return
    from elevate_cli import refresh_pending

    if not re.fullmatch(r"[0-9a-f]{64}", skill_bundle_sha256):
        raise LicenseError(
            "Realtor Beta could not verify its bundled skill identity.",
            code="beta_skill_bundle_invalid",
        )

    root = _beta_profile_root().expanduser().absolute()
    payload = {
        "schema": _BETA_ACTIVATION_RECEIPT_SCHEMA,
        "identity_sha256": _beta_activation_identity(lic),
        "skill_bundle_sha256": skill_bundle_sha256,
        "completed_at": int(time.time()),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(root) as lock_guard:
            lock_guard.assert_held()
            current = read_verified_beta_license_snapshot(require_current=True)
            if not _same_beta_snapshot(current, lic):
                raise LicenseError(
                    "A newer Realtor Beta account replaced setup completion.",
                    code="beta_auth_superseded",
                )
            _atomic_beta_activation_receipt_replace(encoded)
            receipt = _read_beta_activation_receipt_unlocked()
            if (
                not receipt
                or receipt.get("identity_sha256")
                != _beta_activation_identity(current)
                or receipt.get("skill_bundle_sha256") != skill_bundle_sha256
            ):
                raise LicenseError(
                    "Realtor Beta could not verify required setup completion.",
                    code="beta_activation_receipt_failed",
                )
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc
    except OSError as exc:
        raise LicenseError(
            "Realtor Beta could not save required setup completion.",
            code="beta_activation_receipt_failed",
        ) from exc


def _invalid_beta_snapshot_fingerprint(raw: bytes) -> _InvalidBetaSnapshotFingerprint:
    return _InvalidBetaSnapshotFingerprint(
        sha256=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
    )


def _read_beta_local_snapshot_state_unlocked() -> _BetaLocalSnapshotState:
    """Read the exact local predecessor, including private corrupt artifacts.

    Explicit authentication may repair a safe, private, but partial snapshot.
    Capturing its byte fingerprint lets the post-network commit replace only
    that exact artifact; a different corrupt or signed cross-process winner is
    treated as a superseding mutation.
    """
    preflight_beta_license_store(require_writable=False)
    if not (LICENSE_PATH.exists() or LICENSE_PATH.is_symlink()):
        return None
    try:
        raw_bytes = _read_beta_snapshot_bytes()
    except OSError as exc:
        raise LicenseError(
            "The Realtor Beta account snapshot is missing or unreadable.",
            code="beta_license_snapshot_invalid",
        ) from exc

    fingerprint = _invalid_beta_snapshot_fingerprint(raw_bytes)
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
        lic = _beta_license_from_mapping(raw, require_current=False)
        _validate_complete_beta_license(lic, require_current=False)
        return lic
    except (UnicodeDecodeError, json.JSONDecodeError):
        return fingerprint
    except LicenseError as exc:
        # A missing verifier is an application/runtime failure, not evidence
        # that the existing account artifact itself is corrupt.
        if exc.code == "beta_entitlement_verifier_unavailable":
            raise
        return fingerprint


def _same_beta_local_snapshot_state(
    left: _BetaLocalSnapshotState,
    right: _BetaLocalSnapshotState,
) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, License) and isinstance(right, License):
        return _same_beta_snapshot(left, right)
    if isinstance(left, _InvalidBetaSnapshotFingerprint) and isinstance(
        right,
        _InvalidBetaSnapshotFingerprint,
    ):
        return left == right
    return False


def _invalidate_exact_beta_local_state_if_matches_unlocked(
    expected_states: tuple[_BetaLocalSnapshotState, ...],
    message: str,
) -> bool:
    """CAS-remove only an exact attempted or captured local auth state."""
    current = _read_beta_local_snapshot_state_unlocked()
    if current is None:
        return False
    if not any(
        _same_beta_local_snapshot_state(current, expected)
        for expected in expected_states
        if expected is not None
    ):
        return False
    _invalidate_beta_snapshot_unlocked(message)
    return True


def _read_beta_credential_markers_unlocked(
    root: Path,
) -> tuple[Any | None, Any | None]:
    """Read both credential-transition markers and reject impossible overlap."""
    from elevate_cli import refresh_pending

    pending_refresh = refresh_pending.read_pending(root)
    pending_device = refresh_pending.read_device_pending(root)
    if pending_refresh is not None and pending_device is not None:
        raise LicenseError(
            "Realtor Beta found overlapping credential transitions. "
            "No account state was changed.",
            code="beta_device_state_conflict",
        )
    return pending_refresh, pending_device


def _remove_exact_device_pending_unlocked(
    root: Path,
    pending_device: Any,
    *,
    failure_code: str,
    failure_message: str,
) -> None:
    """CAS-remove one captured Device marker or fail without touching its replacement."""
    from elevate_cli import refresh_pending

    if not refresh_pending.remove_device_pending(root, pending_device):
        raise LicenseError(failure_message, code=failure_code)


def _reconcile_device_pending_unlocked(
    root: Path,
    *,
    lock_guard: Any,
) -> DevicePendingReconciliation:
    """Reconcile local signed state against a present Device marker.

    This helper performs no network I/O and never rewrites ``license.json``.
    It is intentionally strict: malformed markers or snapshots are surfaced,
    and an impossible refresh+Device overlap changes nothing.
    """
    pending_refresh, pending_device = _read_beta_credential_markers_unlocked(root)
    del pending_refresh
    if pending_device is None:
        return DevicePendingReconciliation("none", None, None)

    if not (LICENSE_PATH.exists() or LICENSE_PATH.is_symlink()):
        return DevicePendingReconciliation("pending", None, pending_device)

    # Signed B is a durable interim result but cannot discard D/B/C/I: another
    # process may already have rotated the server to C. Signed C is final and
    # may remove the exact marker after currentness and mirror verification.
    historical = read_verified_beta_license_snapshot(require_current=False)
    if historical.refresh_token == pending_device.initial_refresh_token:
        current = read_verified_beta_license_snapshot(require_current=True)
        sync_license_entitlements(current)
        return DevicePendingReconciliation(
            "interim_persisted",
            current,
            pending_device,
        )
    if historical.refresh_token == pending_device.recovery_refresh_token:
        current = read_verified_beta_license_snapshot(require_current=True)
        sync_license_entitlements(current)
        lock_guard.assert_held()
        _remove_exact_device_pending_unlocked(
            root,
            pending_device,
            failure_code="beta_auth_superseded",
            failure_message=(
                "A newer Realtor Beta Device authorization replaced the "
                "recovery state before it could be completed."
            ),
        )
        return DevicePendingReconciliation("already_persisted", current, None)

    # The seven-field marker has no signed-predecessor fingerprint. A non-B/C
    # snapshot could be either the A that existed before this Device attempt or
    # a later explicit-auth winner. Cooperative explicit auth removes the
    # marker inside its own commit lock; a remaining pair is therefore not
    # proof of ordering. Preserve both instead of erasing recovery authority.
    return DevicePendingReconciliation(
        "predecessor_unverifiable",
        historical,
        pending_device,
    )


def reconcile_device_pending() -> DevicePendingReconciliation:
    """Reconcile exact-Beta Device recovery state under the shared auth lock."""
    if not _exact_realtor_beta_active():
        return DevicePendingReconciliation("none", None, None)

    from elevate_cli import refresh_pending

    root = _beta_profile_root().expanduser().absolute()
    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(root) as lock_guard:
            preflight_beta_license_store(require_writable=True)
            lock_guard.assert_held()
            return _reconcile_device_pending_unlocked(root, lock_guard=lock_guard)
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _persist_beta_refresh_snapshot(
    lic: License,
    *,
    expected: License,
    lock_guard: Any,
) -> License | None:
    """Persist verified refresh state without erasing A on an ambiguous fault.

    ``save()`` deliberately invalidates incomplete login responses. Refresh v2
    has a different recovery rule: once HQ may have rotated A to B, the durable
    A/B/I marker must survive every local persistence or verification failure.
    """
    _validate_complete_beta_license(lic, require_current=True)
    current = read_verified_beta_license_snapshot(require_current=False)
    if not _same_beta_snapshot(current, expected):
        return current
    payload = json.dumps(lic.to_dict(), indent=2).encode("utf-8")
    try:
        lock_guard.assert_held()
        _atomic_beta_replace(payload)
        persisted = read_verified_beta_license_snapshot(require_current=True)
        if persisted.to_dict() != lic.to_dict():
            raise LicenseError(
                "Realtor Beta could not verify its saved refresh snapshot.",
                code="beta_license_persistence_mismatch",
            )
        # The local paid-access mirror is part of completion. If it fails, B
        # and the marker remain; the next process resumes from signed B.
        sync_license_entitlements(persisted)
        return persisted
    except LicenseError:
        raise
    except Exception as exc:
        raise LicenseError(
            "Realtor Beta could not durably save its refreshed account snapshot.",
            code="beta_license_persistence_failed",
        ) from exc


def _verify_beta_entitlement_mirror(
    lic: License,
    *,
    require_current: bool,
) -> None:
    """Verify one signed snapshot against the durable local access mirror."""
    _validate_complete_beta_license(lic, require_current=require_current)
    persisted = read_verified_beta_license_snapshot(require_current=require_current)
    if persisted.to_dict() != lic.to_dict():
        raise LicenseError(
            "Realtor Beta could not verify the persisted account snapshot.",
            code="beta_license_persistence_mismatch",
        )
    from elevate_cli.access import (
        ACTIVE_AFFILIATION_STATUSES,
        ENTITLEMENT_CORE,
        REAL_ESTATE_ENTITLEMENTS,
        load_access_config,
    )

    access = load_access_config()
    granted = set(lic.entitlements or [])
    entries = access.get("entitlements") or {}
    authoritative = (set(entries) | granted) - {ENTITLEMENT_CORE}
    for entitlement in sorted(authoritative):
        entry = (access.get("entitlements") or {}).get(entitlement) or {}
        active = str(entry.get("status") or "").lower() == "active"
        owned = bool(entry.get("owned_snapshot"))
        allowed = entitlement in granted
        if active != allowed or owned != allowed:
            raise LicenseError(
                "Realtor Beta entitlement verification did not match HQ.",
                code="beta_entitlement_persistence_mismatch",
            )
    affiliation_active = str(
        (access.get("affiliation") or {}).get("status") or ""
    ).lower() in ACTIVE_AFFILIATION_STATUSES
    affiliation_expected = bool(granted & set(REAL_ESTATE_ENTITLEMENTS)) or any(
        entitlement in granted
        and bool((entries.get(entitlement) or {}).get("requires_active_affiliation"))
        for entitlement in authoritative
    )
    if affiliation_active != affiliation_expected:
        raise LicenseError(
            "Realtor Beta affiliation verification did not match HQ.",
            code="beta_entitlement_persistence_mismatch",
        )


def sync_license_entitlements(lic: License) -> None:
    """Mirror server-granted paid packs into local dashboard entitlements."""
    if _exact_realtor_beta_active():
        _verify_beta_entitlement_mirror(lic, require_current=True)
        return
    if lic.entitlements is None:
        return
    try:
        from elevate_cli.access import (
            REAL_ESTATE_ENTITLEMENTS,
            update_affiliation,
            update_entitlement,
        )

        granted = set(lic.entitlements)
        any_real_estate = False
        for entitlement in REAL_ESTATE_ENTITLEMENTS:
            allowed = entitlement in granted
            if allowed:
                any_real_estate = True
            update_entitlement(
                entitlement,
                status="active" if allowed else "locked",
                owned_snapshot=allowed,
            )
        # Real-estate packs carry requires_active_affiliation, so they stay
        # "locked" (and the dashboards stay hidden) even when owned unless an
        # affiliation is active. An HQ grant IS that affiliation — the realtor
        # is a paid customer — so activate it whenever any pack is granted.
        if any_real_estate:
            update_affiliation(status="active")
    except Exception:
        # Access sync should never make an otherwise valid login unusable.
        return


def load() -> Optional[License]:
    if _exact_realtor_beta_active():
        try:
            return read_verified_beta_license_snapshot(require_current=False)
        except LicenseError:
            return None
    if not LICENSE_PATH.exists():
        return None
    try:
        raw = json.loads(LICENSE_PATH.read_text())
        return License(
            access_token=raw["access_token"],
            refresh_token=raw["refresh_token"],
            license_id=raw["license_id"],
            tier=raw.get("tier", "pro"),
            email=raw.get("email", ""),
            expires_at=int(raw.get("expires_at", 0)),
            entitlements=_normalize_entitlements(raw.get("entitlements"))
            if "entitlements" in raw
            else None,
        )
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _save_exact_beta_unlocked(
    lic: License,
    *,
    starting_snapshot: _BetaLocalSnapshotState = None,
) -> None:
    _validate_complete_beta_license(lic, require_current=True)
    preflight_beta_license_store(require_writable=True)
    payload = json.dumps(lic.to_dict(), indent=2).encode("utf-8")
    try:
        _atomic_beta_replace(payload)
        persisted = read_verified_beta_license_snapshot(require_current=True)
        if persisted.to_dict() != lic.to_dict():
            raise LicenseError(
                "Realtor Beta could not verify its saved account snapshot.",
                code="beta_license_persistence_mismatch",
            )
    except Exception as exc:
        # Once HQ has returned a new authoritative snapshot, restoring old
        # paid grants would fail open if this response revoked them.
        removed = _invalidate_exact_beta_local_state_if_matches_unlocked(
            (lic, starting_snapshot),
            "Realtor Beta could not save or invalidate its account snapshot.",
        )
        if (
            not removed
            and not isinstance(starting_snapshot, _InvalidBetaSnapshotFingerprint)
            and isinstance(
                _read_beta_local_snapshot_state_unlocked(),
                _InvalidBetaSnapshotFingerprint,
            )
        ):
            # A safe-but-invalid artifact appearing during this write cannot
            # authorize paid access and is the partial attempted write. When
            # auth began from an invalid predecessor, however, a different
            # fingerprint is a real third mutation and must be preserved.
            _invalidate_beta_snapshot_unlocked(
                "Realtor Beta could not save or invalidate its account snapshot."
            )
        if isinstance(exc, LicenseError):
            raise
        raise LicenseError(
            "Realtor Beta could not save its account snapshot.",
            code="beta_license_persistence_failed",
        ) from exc


def save(lic: License, *, expected: License | None = None) -> None:
    if _exact_realtor_beta_active():
        from elevate_cli import refresh_pending

        try:
            preflight_beta_license_store(require_writable=True)
            with refresh_pending.refresh_lock(
                _beta_profile_root().expanduser().absolute()
            ) as lock_guard:
                root = _beta_profile_root().expanduser().absolute()
                lock_guard.assert_held()
                pending = refresh_pending.read_pending(root)
                current: License | None = None
                if LICENSE_PATH.exists() or LICENSE_PATH.is_symlink():
                    current = read_verified_beta_license_snapshot(
                        require_current=False
                    )
                if current is None:
                    if expected is not None:
                        raise LicenseError(
                            "A newer Realtor Beta session removed this account snapshot.",
                            code="beta_auth_superseded",
                        )
                elif not _same_beta_snapshot(current, lic):
                    if expected is None:
                        raise LicenseError(
                            "A newer Realtor Beta session replaced this account snapshot.",
                            code="beta_auth_superseded",
                        )
                    _validate_complete_beta_license(
                        expected,
                        require_current=False,
                    )
                    if not _same_beta_snapshot(current, expected):
                        raise LicenseError(
                            "A newer Realtor Beta session replaced this account snapshot.",
                            code="beta_auth_superseded",
                        )
                lock_guard.assert_held()
                _save_exact_beta_unlocked(lic, starting_snapshot=current)
                if pending is not None and not (
                    lic.license_id == pending.license_id
                    and lic.refresh_token == pending.current_refresh_token
                ):
                    lock_guard.assert_held()
                    refresh_pending.remove_pending(root)
        except refresh_pending.RefreshPendingError as exc:
            raise LicenseError(str(exc), code=exc.code) from exc
        return
    LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LICENSE_PATH.with_suffix(".json.tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(lic.to_dict(), indent=2))
    tmp.replace(LICENSE_PATH)
    os.chmod(LICENSE_PATH, 0o600)


def clear() -> bool:
    if _exact_realtor_beta_active():
        from elevate_cli import refresh_pending

        try:
            preflight_beta_license_store(require_writable=True)
            with refresh_pending.refresh_lock(
                _beta_profile_root().expanduser().absolute()
            ) as lock_guard:
                root = _beta_profile_root().expanduser().absolute()
                preflight_beta_license_store(require_writable=True)
                existed = LICENSE_PATH.exists() or LICENSE_PATH.is_symlink()
                lock_guard.assert_held()
                _atomic_beta_replace(None)
                cleanup_failure: BaseException | None = None
                try:
                    lock_guard.assert_held()
                    pending = refresh_pending.read_pending(root)
                    if pending is not None:
                        lock_guard.assert_held()
                        refresh_pending.remove_pending(root)
                except (refresh_pending.RefreshPendingError, LicenseError) as exc:
                    cleanup_failure = exc
                try:
                    lock_guard.assert_held()
                    pending_device = refresh_pending.read_device_pending(root)
                    if pending_device is not None:
                        lock_guard.assert_held()
                        _remove_exact_device_pending_unlocked(
                            root,
                            pending_device,
                            failure_code="beta_device_state_superseded",
                            failure_message=(
                                "A newer Realtor Beta Device authorization replaced "
                                "the state being cleared."
                            ),
                        )
                except (refresh_pending.RefreshPendingError, LicenseError) as exc:
                    if cleanup_failure is None:
                        cleanup_failure = exc
                try:
                    lock_guard.assert_held()
                    _atomic_beta_activation_receipt_replace(None)
                except (LicenseError, OSError) as exc:
                    if cleanup_failure is None:
                        cleanup_failure = exc
                if cleanup_failure is not None:
                    raise cleanup_failure
                return existed
        except refresh_pending.RefreshPendingError as exc:
            raise LicenseError(str(exc), code=exc.code) from exc
    if LICENSE_PATH.exists():
        LICENSE_PATH.unlink()
        return True
    return False


def _license_from_auth_response(
    data: object,
    *,
    email: str,
    existing: License | None = None,
) -> License:
    # Preserve Stable's legacy response interpretation exactly. Realtor Beta
    # takes the stricter complete-snapshot path below.
    if not _exact_realtor_beta_active():
        if existing is not None:
            return License(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                license_id=existing.license_id,
                tier=existing.tier,
                email=existing.email,
                expires_at=_decode_jwt_exp(data["access_token"]),
                entitlements=_extract_entitlements(data)
                if any(key in data for key in ("entitlements", "packs", "features"))
                else existing.entitlements,
            )
        return License(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            license_id=data["license_id"],
            tier=data.get("tier", "pro"),
            email=email,
            expires_at=_decode_jwt_exp(data["access_token"]),
            entitlements=_extract_entitlements(data),
        )

    if not isinstance(data, dict):
        raise LicenseError(
            "Elevation HQ returned an invalid account response.",
            code="beta_license_response_invalid",
        )
    lic = _beta_license_from_mapping(data)
    requested_email = str(email or "").strip().lower()
    if requested_email and requested_email != lic.email:
        raise LicenseError(
            "The signed Realtor Beta account did not match the requested email.",
            code="beta_entitlement_response_mismatch",
        )
    if existing is not None:
        _validate_complete_beta_license(existing, require_current=False)
        if (
            existing.license_id != lic.license_id
            or existing.email != lic.email
            or existing.subject != lic.subject
        ):
            raise LicenseError(
                "The refreshed Realtor Beta account changed signed identity.",
                code="beta_entitlement_response_mismatch",
            )
    _validate_complete_beta_license(lic, require_current=True)
    return lic


def _capture_explicit_auth_starting_snapshot() -> _BetaLocalSnapshotState | object:
    """Capture the exact predecessor before an explicit auth request."""
    if not _exact_realtor_beta_active():
        return _STARTING_SNAPSHOT_UNSET

    from elevate_cli import refresh_pending

    root = _beta_profile_root().expanduser().absolute()
    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(root) as lock_guard:
            lock_guard.assert_held()
            return _read_beta_local_snapshot_state_unlocked()
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _persist_authenticated_license(
    lic: License,
    *,
    starting_snapshot: _BetaLocalSnapshotState | object = _STARTING_SNAPSHOT_UNSET,
    expected_pending: object = _EXPECTED_PENDING_UNSET,
) -> None:
    if _exact_realtor_beta_active():
        from elevate_cli import refresh_pending

        try:
            preflight_beta_license_store(require_writable=True)
            with refresh_pending.refresh_lock(
                _beta_profile_root().expanduser().absolute()
            ) as lock_guard:
                root = _beta_profile_root().expanduser().absolute()
                installed_before: _BetaLocalSnapshotState = None
                predecessor_authorized = False
                write_attempted = False
                verified_commit = False
                try:
                    installed_before = _read_beta_local_snapshot_state_unlocked()
                    if starting_snapshot is not _STARTING_SNAPSHOT_UNSET:
                        if not _same_beta_local_snapshot_state(
                            installed_before,
                            starting_snapshot,
                        ):
                            raise LicenseError(
                                "A newer Realtor Beta session replaced this sign-in attempt.",
                                code="beta_auth_superseded",
                            )
                    predecessor_authorized = True

                    # Marker discovery is part of the post-HQ commit boundary.
                    # A corrupt or impossible marker must not leave captured
                    # paid grants usable after a signed revocation response.
                    pending, pending_device = _read_beta_credential_markers_unlocked(root)
                    if (
                        expected_pending is not _EXPECTED_PENDING_UNSET
                        and pending != expected_pending
                    ):
                        # A cancel/replacement after the request began owns the
                        # local transition. The old HQ response must mutate no
                        # snapshot and must not erase the newer marker.
                        predecessor_authorized = False
                        raise LicenseError(
                            "A newer Realtor Beta sign-in replaced this attempt.",
                            code="beta_auth_superseded",
                        )
                    lock_guard.assert_held()
                    write_attempted = True
                    _save_exact_beta_unlocked(
                        lic,
                        starting_snapshot=installed_before,
                    )
                    # Completion and the final signed readback remain inside
                    # the same mutation order as refresh/login/device writes.
                    sync_license_entitlements(lic)
                    persisted = read_verified_beta_license_snapshot(require_current=True)
                    if persisted.to_dict() != lic.to_dict():
                        raise LicenseError(
                            "A newer Realtor Beta session superseded activation.",
                            code="beta_auth_superseded",
                        )
                    # From this point forward the signed account snapshot is
                    # the authoritative commit. Marker cleanup is important
                    # recovery hygiene, but a post-unlink directory-fsync
                    # failure must never erase both the verified account and
                    # the already-unlinked recovery record.
                    verified_commit = True
                    if pending is not None:
                        lock_guard.assert_held()
                        refresh_pending.remove_pending(root)
                    if pending_device is not None:
                        lock_guard.assert_held()
                        _remove_exact_device_pending_unlocked(
                            root,
                            pending_device,
                            failure_code="beta_auth_superseded",
                            failure_message=(
                                "A newer Realtor Beta Device authorization "
                                "superseded this sign-in result."
                            ),
                        )
                except Exception:
                    # Do not inspect marker state during rollback: corrupt or
                    # replaced markers are retained as recovery evidence. Only
                    # the attempted snapshot or captured predecessor may go.
                    if predecessor_authorized and not verified_commit:
                        lock_guard.assert_held()
                        predecessor: _BetaLocalSnapshotState = (
                            starting_snapshot
                            if starting_snapshot is not _STARTING_SNAPSHOT_UNSET
                            else installed_before
                        )
                        rollback_states = (
                            (lic, predecessor)
                            if write_attempted
                            else (predecessor,)
                        )
                        _invalidate_exact_beta_local_state_if_matches_unlocked(
                            rollback_states,
                            "Realtor Beta could not roll back incomplete activation.",
                        )
                    raise
        except refresh_pending.RefreshPendingError as exc:
            raise LicenseError(str(exc), code=exc.code) from exc
        return
    save(lic)
    sync_license_entitlements(lic)


def _accept_authenticated_response(
    data: object,
    *,
    email: str,
    existing: License | None = None,
    starting_snapshot: _BetaLocalSnapshotState | object = _STARTING_SNAPSHOT_UNSET,
) -> License:
    """Validate and persist one HQ success response, or invalidate Beta."""
    try:
        lic = _license_from_auth_response(data, email=email, existing=existing)
        _persist_authenticated_license(lic, starting_snapshot=starting_snapshot)
        return lic
    except Exception:
        if _exact_realtor_beta_active() and existing is not None:
            _invalidate_beta_snapshot_if_matches(
                existing,
                "Realtor Beta could not invalidate incomplete account state."
            )
        raise


def _accept_hq_response(
    response: Any,
    *,
    email: str,
    existing: License | None = None,
    starting_snapshot: _BetaLocalSnapshotState | object = _STARTING_SNAPSHOT_UNSET,
) -> License:
    """Decode an HQ HTTP success under the same fail-closed boundary."""
    data = _response_json(response)
    return _accept_authenticated_response(
        data,
        email=email,
        existing=existing,
        starting_snapshot=starting_snapshot,
    )


def _prepare_beta_initial_auth(
    email: str,
    *,
    auth_kind: str,
) -> _BetaInitialAuthAttempt:
    """Stage or resume a private caller-owned initial-auth B/C/I triplet."""
    from elevate_cli import refresh_pending

    root = _beta_profile_root().expanduser().absolute()
    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(root) as lock_guard:
            lock_guard.assert_held()
            snapshot = _read_beta_local_snapshot_state_unlocked()
            if isinstance(snapshot, License):
                raise LicenseError(
                    "Sign out of the current Realtor Beta account before "
                    "starting another email-and-password sign-in.",
                    code="beta_auth_sign_out_required",
                )
            device_path = root / refresh_pending.DEVICE_MARKER_NAME
            if device_path.exists() or device_path.is_symlink():
                raise LicenseError(
                    "Finish or cancel the pending Realtor Beta Device sign-in "
                    "before using email and password.",
                    code="beta_auth_transition_conflict",
                )
            pending_refresh = refresh_pending.read_pending(root)
            if (
                pending_refresh is not None
                and refresh_pending.initial_auth_pending_matches(
                    pending_refresh,
                    email,
                    auth_kind=auth_kind,
                )
            ):
                return _BetaInitialAuthAttempt(
                    pending=pending_refresh,
                    starting_snapshot=snapshot,
                    recover_first=True,
                )
            if pending_refresh is None:
                lock_guard.assert_held()
                pending = refresh_pending.create_initial_auth_pending(
                    root,
                    email=email,
                    auth_kind=auth_kind,
                )
                return _BetaInitialAuthAttempt(
                    pending=pending,
                    starting_snapshot=snapshot,
                    recover_first=False,
                )
            if refresh_pending.is_initial_auth_pending(pending_refresh):
                message = (
                    "A different Realtor Beta password sign-in is awaiting "
                    "recovery. Finish it with the same email and Sign in/Create "
                    "account action before starting another one."
                )
            else:
                message = (
                    "Realtor Beta is already recovering another account "
                    "session. Let it finish before signing in with a password."
                )
            raise LicenseError(
                message,
                code="beta_auth_transition_conflict",
            )
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _discard_beta_initial_auth(attempt: _BetaInitialAuthAttempt) -> None:
    """CAS-remove one definitive failed attempt without erasing a replacement."""
    from elevate_cli import refresh_pending

    root = _beta_profile_root().expanduser().absolute()
    try:
        with refresh_pending.refresh_lock(root) as lock_guard:
            lock_guard.assert_held()
            current = refresh_pending.read_pending(root)
            if current == attempt.pending:
                lock_guard.assert_held()
                refresh_pending.remove_pending(root)
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _accept_beta_initial_auth_response(
    response: Any,
    *,
    attempt: _BetaInitialAuthAttempt,
    email: str,
    expected_refresh_token: str | None = None,
) -> License:
    data = _response_json(response)
    lic = _license_from_auth_response(data, email=email)
    if (
        expected_refresh_token is not None
        and lic.refresh_token != expected_refresh_token
    ):
        raise LicenseError(
            "Elevation HQ returned an account token that did not match the "
            "protected sign-in recovery.",
            code="beta_refresh_successor_mismatch",
        )
    _persist_authenticated_license(
        lic,
        starting_snapshot=attempt.starting_snapshot,
        expected_pending=attempt.pending,
    )
    return lic


def _try_recover_beta_initial_auth(
    attempt: _BetaInitialAuthAttempt,
    *,
    email: str,
) -> License | None:
    """Recover an ambiguous password-auth commit using only retained B/C/I."""
    if not attempt.recover_first:
        return None
    try:
        response = _post_hq(
            backend_url(),
            "/api/license/refresh",
            {
                "refresh_token": attempt.pending.current_refresh_token,
                "next_refresh_token": attempt.pending.successor_refresh_token,
                "refresh_attempt_id": attempt.pending.attempt_id,
            },
        )
    except LicenseError as exc:
        if exc.code == "beta_auth_upstream_unavailable":
            raise LicenseError(
                "Realtor Beta could not confirm the pending sign-in. "
                "Try again to resume it safely.",
                code="beta_initial_auth_recovery_ambiguous",
            ) from exc
        raise
    if response.status_code == 401:
        # HQ definitively rejected B. It is safe to retry password auth with
        # the exact same caller-owned token instead of risking a second
        # credential chain after an ambiguous refresh commit.
        return None
    if response.status_code == 402:
        _discard_beta_initial_auth(attempt)
        raise LicenseError(
            "No active subscription. Contact Elevation Real Estate HQ to activate Elevate.",
            code="beta_subscription_inactive",
        )
    if not response.is_success:
        raise LicenseError(
            "Realtor Beta could not confirm the pending sign-in "
            f"(HTTP {response.status_code}). Try again to resume it safely.",
            code="beta_initial_auth_recovery_ambiguous",
        )
    return _accept_beta_initial_auth_response(
        response,
        attempt=attempt,
        email=email,
        expected_refresh_token=attempt.pending.successor_refresh_token,
    )


def _post_beta_password_auth(
    path: str,
    payload: dict[str, Any],
    *,
    email: str,
    auth_kind: str,
) -> tuple[_BetaInitialAuthAttempt, License | None, Any | None]:
    attempt = _prepare_beta_initial_auth(email, auth_kind=auth_kind)
    recovered = _try_recover_beta_initial_auth(attempt, email=email)
    if recovered is not None:
        return attempt, recovered, None
    request = dict(payload)
    request["initial_refresh_token"] = attempt.pending.current_refresh_token
    response = _post_hq(backend_url(), path, request)
    return attempt, None, response


def login(email: str, password: str, device_label: Optional[str] = None) -> License:
    """POST /api/auth/login, persist license."""
    if _exact_realtor_beta_active():
        attempt, recovered, resp = _post_beta_password_auth(
            "/api/auth/login",
            {
                "email": email,
                "password": password,
                "device_label": device_label or os.uname().nodename,
            },
            email=email,
            auth_kind="login",
        )
        if recovered is not None:
            return recovered
        assert resp is not None
        if resp.status_code == 402:
            raise _auth_flow_error(
                "No active subscription. Contact Elevation Real Estate HQ to activate Elevate.",
                beta_code="beta_subscription_inactive",
            )
        if resp.status_code == 401:
            raise _auth_flow_error(
                "Invalid email or password.",
                beta_code="beta_invalid_credentials",
            )
        if not resp.is_success:
            raise _auth_flow_error(
                f"Login failed ({resp.status_code}).",
                beta_code="beta_auth_upstream_failed",
                beta_message=(
                    "Elevation HQ could not complete sign-in "
                    f"(HTTP {resp.status_code})."
                ),
            )
        return _accept_beta_initial_auth_response(
            resp,
            attempt=attempt,
            email=email,
            expected_refresh_token=attempt.pending.current_refresh_token,
        )

    base_url = backend_url()
    starting_snapshot = _capture_explicit_auth_starting_snapshot()
    resp = _post_hq(
        base_url,
        "/api/auth/login",
        {
            "email": email,
            "password": password,
            "device_label": device_label or os.uname().nodename,
        },
    )
    if resp.status_code == 402:
        raise _auth_flow_error(
            "No active subscription. Contact Elevation Real Estate HQ to activate Elevate.",
            beta_code="beta_subscription_inactive",
        )
    if resp.status_code == 401:
        raise _auth_flow_error(
            "Invalid email or password.",
            beta_code="beta_invalid_credentials",
        )
    if not resp.is_success:
        raise _auth_flow_error(
            (
                f"Login failed ({resp.status_code})."
                if _exact_realtor_beta_active()
                else f"Login failed ({resp.status_code}): {resp.text[:200]}"
            ),
            beta_code="beta_auth_upstream_failed",
            beta_message=f"Elevation HQ could not complete sign-in (HTTP {resp.status_code}).",
        )

    return _accept_hq_response(
        resp,
        email=email,
        starting_snapshot=starting_snapshot,
    )


def create_account(
    email: str,
    password: str,
    device_label: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> License:
    """POST /api/auth/signup (open self-serve account creation), persist license.

    Mirrors :func:`login` but hits the signup endpoint, which creates the
    account ACTIVE with no entitlements and returns the same token pair — so the
    realtor is signed straight in. Paid packs stay locked until an admin grants
    them per person from the control panel.
    """
    if _exact_realtor_beta_active():
        attempt, recovered, resp = _post_beta_password_auth(
            "/api/auth/signup",
            {
                "email": email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name,
                "device_label": device_label or os.uname().nodename,
            },
            email=email,
            auth_kind="signup",
        )
        if recovered is not None:
            return recovered
        assert resp is not None
        if resp.status_code == 409:
            raise _auth_flow_error(
                "An account with this email already exists — sign in instead.",
                beta_code="beta_account_exists",
            )
        if resp.status_code == 400:
            raise _auth_flow_error(
                "Enter a valid email and a password of at least 8 characters.",
                beta_code="beta_signup_invalid",
            )
        if resp.status_code == 429:
            raise _auth_flow_error(
                "Too many attempts. Please wait a few minutes and try again.",
                beta_code="beta_auth_rate_limited",
            )
        if not resp.is_success:
            raise _auth_flow_error(
                f"Account creation failed ({resp.status_code}).",
                beta_code="beta_auth_upstream_failed",
                beta_message=(
                    "Elevation HQ could not create the account "
                    f"(HTTP {resp.status_code})."
                ),
            )
        return _accept_beta_initial_auth_response(
            resp,
            attempt=attempt,
            email=email,
            expected_refresh_token=attempt.pending.current_refresh_token,
        )

    base_url = backend_url()
    starting_snapshot = _capture_explicit_auth_starting_snapshot()
    resp = _post_hq(
        base_url,
        "/api/auth/signup",
        {
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
            "device_label": device_label or os.uname().nodename,
        },
    )
    if resp.status_code == 409:
        raise _auth_flow_error(
            "An account with this email already exists — sign in instead.",
            beta_code="beta_account_exists",
        )
    if resp.status_code == 400:
        raise _auth_flow_error(
            "Enter a valid email and a password of at least 8 characters.",
            beta_code="beta_signup_invalid",
        )
    if resp.status_code == 429:
        raise _auth_flow_error(
            "Too many attempts. Please wait a few minutes and try again.",
            beta_code="beta_auth_rate_limited",
        )
    if not resp.is_success:
        raise _auth_flow_error(
            (
                f"Account creation failed ({resp.status_code})."
                if _exact_realtor_beta_active()
                else f"Account creation failed ({resp.status_code}): {resp.text[:200]}"
            ),
            beta_code="beta_auth_upstream_failed",
            beta_message=(
                "Elevation HQ could not create the account "
                f"(HTTP {resp.status_code})."
            ),
        )

    return _accept_hq_response(
        resp,
        email=email,
        starting_snapshot=starting_snapshot,
    )


def request_login_code(email: str) -> None:
    """POST /api/auth/login-code/request — HQ emails a one-time sign-in code."""
    base_url = backend_url()
    resp = _post_hq(
        base_url,
        "/api/auth/login-code/request",
        {"email": email},
    )
    if resp.status_code == 429:
        raise _auth_flow_error(
            "Too many code requests. Wait a few minutes and try again.",
            beta_code="beta_auth_rate_limited",
        )
    if not resp.is_success:
        raise _auth_flow_error(
            (
                f"Could not send code ({resp.status_code})."
                if _exact_realtor_beta_active()
                else f"Could not send code ({resp.status_code}): {resp.text[:200]}"
            ),
            beta_code="beta_auth_upstream_failed",
            beta_message=(
                "Elevation HQ could not send a sign-in code "
                f"(HTTP {resp.status_code})."
            ),
        )


def login_with_code(email: str, code: str, device_label: Optional[str] = None) -> License:
    """POST /api/auth/login-code/verify, persist license. Same outcome as
    login() but authenticated by a one-time emailed code instead of a password."""
    base_url = backend_url()
    starting_snapshot = _capture_explicit_auth_starting_snapshot()
    resp = _post_hq(
        base_url,
        "/api/auth/login-code/verify",
        {
            "email": email,
            "code": code,
            "device_label": device_label or os.uname().nodename,
        },
    )
    if resp.status_code == 402:
        raise _auth_flow_error(
            "No active subscription. Contact Elevation Real Estate HQ to activate Elevate.",
            beta_code="beta_subscription_inactive",
        )
    if resp.status_code == 401:
        raise _auth_flow_error(
            "Invalid or expired code.",
            beta_code="beta_login_code_invalid",
        )
    if not resp.is_success:
        raise _auth_flow_error(
            (
                f"Code sign-in failed ({resp.status_code})."
                if _exact_realtor_beta_active()
                else f"Code sign-in failed ({resp.status_code}): {resp.text[:200]}"
            ),
            beta_code="beta_auth_upstream_failed",
            beta_message=(
                "Elevation HQ could not complete code sign-in "
                f"(HTTP {resp.status_code})."
            ),
        )

    return _accept_hq_response(
        resp,
        email=email,
        starting_snapshot=starting_snapshot,
    )


def _refresh_exact_beta(lic: License) -> License:
    """Recoverable exact-Beta A -> B refresh under the shared process lock."""
    from elevate_cli import refresh_pending

    _validate_complete_beta_license(lic, require_current=False)
    root = _beta_profile_root().expanduser().absolute()
    preflight_beta_license_store(require_writable=True)

    try:
        with refresh_pending.refresh_lock(root) as lock_guard:
            preflight_beta_license_store(require_writable=True)
            current = read_verified_beta_license_snapshot(require_current=False)
            pending = refresh_pending.read_pending(root)

            if pending is not None and refresh_pending.is_initial_auth_pending(pending):
                # A complete signed snapshot is an authoritative later commit
                # and safely supersedes pre-license recovery state.
                lock_guard.assert_held()
                refresh_pending.remove_pending(root)
                pending = None

            if pending is not None:
                # A newer signed identity/session proves this attempt was
                # superseded. Remove only the old marker, never the new state.
                if (
                    current.license_id != pending.license_id
                    or current.refresh_token
                    not in (
                        pending.current_refresh_token,
                        pending.successor_refresh_token,
                    )
                ):
                    lock_guard.assert_held()
                    refresh_pending.remove_pending(root)
                    return current
                if current.refresh_token == pending.successor_refresh_token:
                    # Crash/restart after durable B but before marker removal.
                    try:
                        _validate_complete_beta_license(current, require_current=True)
                    except LicenseError as exc:
                        if exc.code != "beta_entitlement_assertion_not_current":
                            raise
                        # Historical signed B still proves durable persistence,
                        # but needs an exact A/B/I replay for a fresh assertion.
                    else:
                        sync_license_entitlements(current)
                        lock_guard.assert_held()
                        refresh_pending.remove_pending(root)
                        _reset_fail_count()
                        return current
            else:
                if not _same_beta_snapshot(current, lic):
                    return current
                lock_guard.assert_held()
                pending = refresh_pending.create_pending(
                    root,
                    license_id=current.license_id,
                    current_refresh_token=current.refresh_token,
                )

            # A matching marker is the sole request authority. The exact same
            # triplet is reused after timeouts, discarded responses, and 5xx.
            base_url = backend_url()
            lock_guard.assert_held()
            resp = _post_hq(
                base_url,
                "/api/license/refresh",
                {
                    "refresh_token": pending.current_refresh_token,
                    "next_refresh_token": pending.successor_refresh_token,
                    "refresh_attempt_id": pending.attempt_id,
                },
            )

            if resp.status_code in (401, 402):
                latest = read_verified_beta_license_snapshot(require_current=False)
                if not _same_beta_snapshot(latest, current):
                    lock_guard.assert_held()
                    refresh_pending.remove_pending(root)
                    return latest
                # These two statuses are the only definitive revocation lane.
                # Ambiguous 4xx, transport errors, and 5xx retain A/B/I.
                lock_guard.assert_held()
                _atomic_beta_replace(None)
                lock_guard.assert_held()
                refresh_pending.remove_pending(root)
                _reset_fail_count()
                message = (
                    "Subscription inactive — license revoked. Contact Elevation Real Estate HQ."
                    if resp.status_code == 402
                    else "Refresh token rejected. Sign in to Realtor Beta again."
                )
                raise LicenseError(message, code="beta_license_revoked")

            if not resp.is_success:
                if 400 <= resp.status_code < 500:
                    raise LicenseError(
                        "Elevation HQ rejected the recoverable refresh protocol. "
                        "The existing session and retry state were preserved; "
                        "Realtor Beta will not downgrade this attempt.",
                        code="beta_refresh_protocol_rejected",
                    )
                raise LicenseError(
                    f"Elevation HQ could not refresh the account session "
                    f"(HTTP {resp.status_code}).",
                    code="beta_auth_upstream_failed",
                )

            data = _response_json(resp)
            next_license = _license_from_auth_response(
                data,
                email=current.email,
                existing=current,
            )
            if next_license.refresh_token != pending.successor_refresh_token:
                raise LicenseError(
                    "Elevation HQ returned a refresh token that did not match "
                    "the protected Beta refresh attempt.",
                    code="beta_refresh_successor_mismatch",
                )

            latest = read_verified_beta_license_snapshot(require_current=False)
            if not _same_beta_snapshot(latest, current):
                if (
                    latest.license_id == pending.license_id
                    and latest.refresh_token == pending.successor_refresh_token
                ):
                    _validate_complete_beta_license(latest, require_current=True)
                    sync_license_entitlements(latest)
                lock_guard.assert_held()
                refresh_pending.remove_pending(root)
                return latest

            persisted = _persist_beta_refresh_snapshot(
                next_license,
                expected=current,
                lock_guard=lock_guard,
            )
            if persisted is None:
                raise LicenseError(
                    "A newer Realtor Beta account session superseded this refresh.",
                    code="beta_refresh_superseded",
                )
            lock_guard.assert_held()
            refresh_pending.remove_pending(root)
            _reset_fail_count()
            return persisted
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def refresh(lic: License) -> License:
    """POST /api/license/refresh. Rotates the refresh token."""
    if _exact_realtor_beta_active():
        return _refresh_exact_beta(lic)
    base_url = backend_url()
    resp = _post_hq(
        base_url,
        "/api/license/refresh",
        {"refresh_token": lic.refresh_token},
    )
    if resp.status_code == 402:
        # Subscription explicitly inactive — definitive answer from HQ, clear
        # immediately so the user is forced through `activate` after they
        # re-subscribe.
        _reset_fail_count()
        if _exact_realtor_beta_active():
            _invalidate_beta_snapshot_if_matches(
                lic,
                "Realtor Beta could not invalidate a revoked account snapshot.",
            )
        else:
            clear()
        raise _auth_flow_error(
            "Subscription inactive — license revoked. Contact Elevation Real Estate HQ.",
            beta_code="beta_license_revoked",
        )
    if resp.status_code == 401:
        if _exact_realtor_beta_active():
            _reset_fail_count()
            _invalidate_beta_snapshot_if_matches(
                lic,
                "Realtor Beta could not invalidate a rejected account snapshot.",
            )
            raise LicenseError(
                "Refresh token rejected. Sign in to Realtor Beta again.",
                code="beta_license_revoked",
            )
        # Refresh token *might* be invalid, but a single 401 also happens on
        # transient HQ blips (deploy mid-request, brief auth race after token
        # rotation). Require LICENSE_FAIL_THRESHOLD consecutive 401s before
        # nuking the file. Until then, raise the error so the caller can fall
        # back gracefully (CLI shows status, desktop keeps showing chat) but
        # leave license.json intact so the next attempt can recover.
        count = _bump_fail_count()
        if count >= LICENSE_FAIL_THRESHOLD:
            _reset_fail_count()
            clear()
            raise LicenseError(
                f"Refresh token rejected ({count} consecutive 401s). Run `elevate activate` to log in again.",
            )
        raise LicenseError(
            f"Refresh failed (HTTP 401, attempt {count}/{LICENSE_FAIL_THRESHOLD}). Will retry — session preserved.",
        )
    if not resp.is_success:
        raise _auth_flow_error(
            (
                f"Refresh failed ({resp.status_code})."
                if _exact_realtor_beta_active()
                else f"Refresh failed ({resp.status_code}): {resp.text[:200]}"
            ),
            beta_code="beta_auth_upstream_failed",
            beta_message=(
                "Elevation HQ could not refresh the account session "
                f"(HTTP {resp.status_code})."
            ),
        )

    _reset_fail_count()

    return _accept_hq_response(
        resp,
        email=lic.email,
        existing=lic,
    )


def ensure_valid() -> License:
    """Called on chat entry. Returns a fresh license or raises LicenseError."""
    reconciliation: DevicePendingReconciliation | None = None
    if _exact_realtor_beta_active():
        reconciliation = reconcile_device_pending()
    lic = reconciliation.license if reconciliation is not None else None
    if lic is None:
        lic = load()
    if not lic:
        raise LicenseError(
            "No Elevate subscription on this machine. Run `elevate activate` to log in.",
        )
    if lic.is_expired():
        lic = refresh(lic)
    if _exact_realtor_beta_active() and not beta_activation_complete(lic):
        raise LicenseError(
            "Realtor Beta must finish required skill setup before use.",
            code="beta_activation_incomplete",
        )
    return lic


def status_text(lic: Optional[License] = None) -> str:
    lic = lic or load()
    if not lic:
        return "Not activated. Run `elevate activate`."
    remaining = lic.expires_at - int(time.time())
    state = "expired" if remaining <= 0 else f"{remaining // 60}m left"
    return f"Subscribed: {lic.email} ({lic.tier}) — token {state}"


def activate_install(lic: License, *, sync_skills: bool = True) -> dict[str, Any]:
    """Complete local post-login activation for the current machine."""
    beta_active = _exact_realtor_beta_active()
    beta_bundle = None
    if beta_active:
        _validate_complete_beta_license(lic, require_current=True)
        try:
            from elevate_cli.beta_skill_bundle import load_exact_beta_skill_bundle

            beta_bundle = load_exact_beta_skill_bundle()
        except Exception as exc:
            raise LicenseError(
                "Realtor Beta could not verify its code-bundled skills.",
                code="beta_skill_bundle_invalid",
            ) from exc
    sync_license_entitlements(lic)
    result: dict[str, Any] = {
        "email": lic.email,
        "tier": lic.tier,
        "license_id": lic.license_id,
        "entitlements": list(lic.entitlements or []),
        "packs": {},
        "skills_path": None,
        "skill_count": 0,
        "skill_names": [],
        "skill_error": None,
        "skill_sync_warnings": [],
        "skill_bundle_sha256": None,
        "skill_bundle_file_count": 0,
        "skill_bundle_bytes": 0,
        "activation_complete": False,
    }

    try:
        from elevate_cli.access import dashboard_access_status

        result["packs"] = dashboard_access_status().get("packs", {})
    except Exception as exc:
        if _exact_realtor_beta_active():
            if isinstance(exc, LicenseError):
                raise
            raise LicenseError(
                "Realtor Beta could not verify local pack access.",
                code="beta_entitlement_persistence_mismatch",
            ) from exc
        result["access_error"] = str(exc)

    if beta_bundle is not None:
        skill_roots = sorted(
            {
                label.split("/", 2)[1]
                for label in beta_bundle.files
                if label.startswith("skills/") and label.count("/") >= 2
            }
        )
        result["skills_path"] = str(beta_bundle.skills_root)
        result["skill_count"] = len(skill_roots)
        result["skill_names"] = skill_roots
        result["skill_bundle_sha256"] = beta_bundle.sha256
        result["skill_bundle_file_count"] = beta_bundle.file_count
        result["skill_bundle_bytes"] = beta_bundle.total_bytes
    elif sync_skills:
        try:
            from elevate_cli import cloud_skills

            sync_result = cloud_skills.sync_all()
            result["skills_path"] = sync_result.get("path")
            result["skill_count"] = sync_result.get("skill_count", 0)
            result["skill_names"] = sync_result.get("skill_names", [])
            result["skill_sync_warnings"] = sync_result.get("errors", [])
        except Exception as exc:
            if beta_active:
                raise LicenseError(
                    "Realtor Beta could not finish installing its signed skills.",
                    code="beta_skill_sync_failed",
                ) from exc
            result["skill_error"] = str(exc)

    result["activation_complete"] = not bool(
        result.get("access_error")
        or result.get("skill_error")
        or result.get("skill_sync_warnings")
    )
    if beta_active and result["activation_complete"]:
        _mark_beta_activation_complete(
            lic,
            skill_bundle_sha256=beta_bundle.sha256,
        )
    return result


def _format_enabled_packs(packs: dict[str, Any]) -> str:
    labels = {
        "realEstateSales": "sales",
        "realEstateMarketing": "marketing",
        "realEstateAdmin": "admin",
        "realEstateCma": "CMA",
    }
    enabled = [label for key, label in labels.items() if packs.get(key)]
    return ", ".join(enabled) if enabled else "core only"


# --- CLI subcommand dispatch ---
# Wired from elevate_cli/main.py via activate / subscribe / license subparsers.

def cmd_activate(args) -> int:
    import getpass

    try:
        configure_backend_override(
            getattr(args, "backend_url", None),
            persist=True,
        )
    except LicenseError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2

    email = args.email or input("Email: ").strip()
    password = args.password or getpass.getpass("Password: ")
    sync_skills = (
        True
        if _exact_realtor_beta_active()
        else not getattr(args, "skip_skill_sync", False)
    )
    try:
        lic = login(email, password)
        activation = activate_install(lic, sync_skills=sync_skills)
    except LicenseError as e:
        if e.code == "license_error":
            print(f"login failed: {e}", file=sys.stderr)
        else:
            print(f"{e.code}: {e}", file=sys.stderr)
        return 1
    print(f"activated {lic.email} ({lic.tier}). license id: {lic.license_id}")
    print(f"dashboard packs: {_format_enabled_packs(activation.get('packs') or {})}")
    if sync_skills:
        if activation.get("skill_error"):
            print(f"paid skill sync warning: {activation['skill_error']}", file=sys.stderr)
        elif activation.get("skill_count"):
            print(f"paid skills ready: {activation['skill_count']} at {activation.get('skills_path')}")
        else:
            print("paid skills ready: none returned for this tier")
        for warning in activation.get("skill_sync_warnings") or []:
            print(f"paid skill warning: {warning}", file=sys.stderr)
    print("next: run `elevate` or `elevate dashboard`.")
    if not activation.get("activation_complete"):
        print("activation_incomplete: account saved but setup did not finish.", file=sys.stderr)
        return 1
    return 0


def cmd_subscribe(args) -> int:
    """Compatibility wrapper for older install docs and scripts."""
    return cmd_activate(args)


def cmd_license(args) -> int:
    action = getattr(args, "license_action", None) or "status"
    if action == "status":
        print(status_text())
        return 0
    if action == "logout":
        if clear():
            print("license cleared.")
        else:
            print("no license file to clear.")
        return 0
    if action == "refresh":
        try:
            lic = ensure_valid()
        except LicenseError as e:
            if e.code == "license_error":
                print(f"refresh failed: {e}", file=sys.stderr)
            else:
                print(f"{e.code}: {e}", file=sys.stderr)
            return 1
        print(status_text(lic))
        return 0
    print(f"unknown license action: {action}", file=sys.stderr)
    return 2


# --- Device-link flow (web-driven activation) ---

_BETA_DEVICE_PROTOCOL_VERSION = 3
_BETA_DEVICE_CLAIM_PROTOCOL_VERSION = 2
_BETA_DEVICE_GRANT_LIFETIME_SECONDS = 10 * 60
_BETA_DEVICE_MIN_POLL_INTERVAL_SECONDS = 1
_BETA_DEVICE_MAX_POLL_INTERVAL_SECONDS = 60
_BETA_DEVICE_USER_CODE = re.compile(
    r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-"
    r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}$"
)


@dataclass(frozen=True)
class _BetaDeviceAttempt:
    pending: Any
    starting_snapshot: _BetaLocalSnapshotState


@dataclass(frozen=True)
class _BetaDeviceStart:
    resumed: bool
    user_code: str | None
    verification_uri: str | None
    verification_uri_complete: str | None
    expires_in: int | None
    interval: int


def _new_beta_device_token() -> str:
    """Return one canonical, unpadded 256-bit Device credential."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def _beta_device_protocol_error(message: str) -> LicenseError:
    return LicenseError(message, code="beta_device_protocol_invalid")


def _beta_device_http_status(response: Any) -> int:
    status_code = getattr(response, "status_code", None)
    if type(status_code) is not int or not 100 <= status_code <= 599:
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device response status."
        )
    return status_code


def _beta_device_response_mapping(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except (
        AttributeError,
        TypeError,
        ValueError,
        RecursionError,
        json.JSONDecodeError,
    ):
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device response."
        ) from None
    if not isinstance(data, dict):
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device response."
        )
    return data


def _beta_device_interval(value: object) -> int:
    if (
        type(value) is not int
        or value < _BETA_DEVICE_MIN_POLL_INTERVAL_SECONDS
        or value > _BETA_DEVICE_MAX_POLL_INTERVAL_SECONDS
    ):
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device polling interval."
        )
    return value


def _parse_beta_device_start(
    response: Any,
    *,
    base_url: str,
    pending: Any,
) -> _BetaDeviceStart:
    """Strictly bind one exact-v3 start or credential-free resume response."""
    status_code = _beta_device_http_status(response)
    if status_code != 200:
        try:
            error_data = _beta_device_response_mapping(response)
        except LicenseError:
            error_data = None
        if status_code == 403 and error_data == {"error": "authorization_denied"}:
            raise LicenseError(
                "The Device sign-in request was denied on the web.",
                code="beta_device_link_denied",
            )
        if status_code == 410 and error_data == {"error": "expired_token"}:
            raise LicenseError(
                "The Device sign-in request expired.",
                code="beta_device_link_expired",
            )
        raise LicenseError(
            "Could not start device link through Elevation HQ "
            f"(HTTP {status_code}). The recovery state was preserved.",
            code=(
                "beta_device_link_conflict"
                if status_code == 409
                else "beta_device_link_upstream_failed"
            ),
        )

    data = _beta_device_response_mapping(response)

    if (
        type(data.get("protocol_version")) is not int
        or data.get("protocol_version") != _BETA_DEVICE_PROTOCOL_VERSION
    ):
        raise _beta_device_protocol_error(
            "Elevation HQ did not confirm the required Device protocol."
        )

    if data.get("status") == "resume_poll":
        if frozenset(data) != frozenset(
            {"protocol_version", "status", "grant_status", "interval"}
        ):
            raise _beta_device_protocol_error(
                "Elevation HQ returned an invalid Device resume response."
            )
        if data.get("grant_status") not in {"approved", "claimed"}:
            raise _beta_device_protocol_error(
                "Elevation HQ returned an invalid Device resume state."
            )
        return _BetaDeviceStart(
            resumed=True,
            user_code=None,
            verification_uri=None,
            verification_uri_complete=None,
            expires_in=None,
            interval=_beta_device_interval(data.get("interval")),
        )

    required = frozenset(
        {
            "protocol_version",
            "device_code",
            "user_code",
            "verification_uri",
            "verification_uri_complete",
            "expires_in",
            "interval",
        }
    )
    if frozenset(data) != required:
        raise _beta_device_protocol_error(
            "Elevation HQ returned an incomplete Device start response."
        )
    if data.get("device_code") != pending.device_code:
        raise _beta_device_protocol_error(
            "Elevation HQ returned a Device code that did not match this attempt."
        )
    user_code = data.get("user_code")
    if (
        not isinstance(user_code, str)
        or _BETA_DEVICE_USER_CODE.fullmatch(user_code) is None
    ):
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device confirmation code."
        )
    pinned_link = f"{base_url}/link"
    if (
        not base_url.startswith("https://")
        or data.get("verification_uri") != pinned_link
    ):
        raise _beta_device_protocol_error(
            "Elevation HQ returned an untrusted Device verification address."
        )
    complete_link = f"{pinned_link}?code={user_code}"
    if data.get("verification_uri_complete") != complete_link:
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device verification address."
        )
    expires_in = data.get("expires_in")
    if (
        type(expires_in) is not int
        or expires_in < 1
        or expires_in > _BETA_DEVICE_GRANT_LIFETIME_SECONDS
    ):
        raise _beta_device_protocol_error(
            "Elevation HQ returned an invalid Device expiry."
        )
    return _BetaDeviceStart(
        resumed=False,
        user_code=user_code,
        verification_uri=pinned_link,
        verification_uri_complete=complete_link,
        expires_in=expires_in,
        interval=_beta_device_interval(data.get("interval")),
    )


def _post_beta_device(
    base_url: str,
    path: str,
    payload: dict[str, Any],
) -> Any:
    """Make one Device request without exposing its credential-bearing body."""
    try:
        with httpx.Client(timeout=15.0) as client:
            return client.post(f"{base_url}{path}", json=payload)
    except httpx.HTTPError:
        raise LicenseError(
            "Elevation HQ could not be reached during Device sign-in. "
            "The recovery state was preserved.",
            code="beta_device_link_upstream_unavailable",
        ) from None


def _prepare_beta_device_attempt() -> License | _BetaDeviceAttempt:
    """Resume or durably create D/B/C/I while holding no network authority."""
    from elevate_cli import refresh_pending

    root = _beta_profile_root().expanduser().absolute()
    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(root) as lock_guard:
            preflight_beta_license_store(require_writable=True)
            lock_guard.assert_held()
            pending_refresh, pending = _read_beta_credential_markers_unlocked(root)
            del pending_refresh
            starting_snapshot = _read_beta_local_snapshot_state_unlocked()

            if pending is not None:
                if isinstance(starting_snapshot, _InvalidBetaSnapshotFingerprint):
                    # The seven-field marker deliberately contains no local
                    # predecessor fingerprint. After a restart there is no
                    # sound way to prove whether this corrupt artifact existed
                    # when D/B/C/I was created or is a later local winner.
                    # Retain both artifacts and require explicit repair rather
                    # than silently blessing the current bytes as predecessor.
                    raise LicenseError(
                        "Realtor Beta cannot safely resume Device sign-in while "
                        "the local account snapshot is invalid. The recovery "
                        "state was preserved.",
                        code="beta_device_predecessor_unverifiable",
                    )
                if isinstance(starting_snapshot, License):
                    if (
                        starting_snapshot.refresh_token
                        == pending.recovery_refresh_token
                    ):
                        try:
                            _validate_complete_beta_license(
                                starting_snapshot,
                                require_current=True,
                            )
                            sync_license_entitlements(starting_snapshot)
                        except LicenseError:
                            # A historical B/C snapshot or an incomplete mirror
                            # is still recoverable from the exact marker.
                            pass
                        else:
                            lock_guard.assert_held()
                            _remove_exact_device_pending_unlocked(
                                root,
                                pending,
                                failure_code="beta_auth_superseded",
                                failure_message=(
                                    "A newer Device authorization replaced the "
                                    "completed recovery state."
                                ),
                            )
                            return starting_snapshot
                    elif (
                        starting_snapshot.refresh_token
                        == pending.initial_refresh_token
                    ):
                        # B is deliberately provisional. Even a current,
                        # mirror-verified B keeps D/B/C/I so every process can
                        # converge on exact C through the idempotent recovery
                        # triplet rather than strand a concurrent server C.
                        pass
                    else:
                        # The marker does not persist its signed predecessor.
                        # After restart an unrelated A could be either the
                        # original snapshot this Device attempt intended to
                        # replace or a later explicit-auth winner. Returning A
                        # would let `cmd_link` falsely report this abandoned
                        # Device request as linked; clearing D/B/C/I would lose
                        # its recovery authority. Preserve both and fail closed.
                        raise LicenseError(
                            "Realtor Beta cannot prove whether the signed local "
                            "session predates this Device attempt. The recovery "
                            "state was preserved.",
                            code="beta_device_predecessor_unverifiable",
                        )

            if pending is None:
                lock_guard.assert_held()
                pending = refresh_pending.write_device_pending(
                    root,
                    device_code=_new_beta_device_token(),
                    initial_refresh_token=_new_beta_device_token(),
                    recovery_refresh_token=_new_beta_device_token(),
                    recovery_attempt_id=_new_beta_device_token(),
                )
            return _BetaDeviceAttempt(
                pending=pending,
                starting_snapshot=starting_snapshot,
            )
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _read_completed_beta_device_license_unlocked(
    pending: Any,
) -> License | None:
    """Recognize only durable final C left before marker cleanup."""
    current = _read_beta_local_snapshot_state_unlocked()
    if (
        not isinstance(current, License)
        or current.refresh_token != pending.recovery_refresh_token
    ):
        return None
    try:
        _validate_complete_beta_license(current, require_current=True)
        sync_license_entitlements(current)
    except LicenseError:
        # Historical C or an incomplete entitlement projection remains a
        # recovery predecessor, not completed activation. Signed B is never
        # considered here because it is provisional by definition.
        return None
    return current


def _terminalize_beta_device_attempt(
    attempt: _BetaDeviceAttempt,
) -> License | None:
    """CAS-clear a definitive denial/expiry, never a newer local winner."""
    from elevate_cli import refresh_pending

    root = _beta_profile_root().expanduser().absolute()
    try:
        with refresh_pending.refresh_lock(root) as lock_guard:
            lock_guard.assert_held()
            pending_refresh, current_pending = _read_beta_credential_markers_unlocked(
                root
            )
            del pending_refresh
            completed = _read_completed_beta_device_license_unlocked(attempt.pending)
            if completed is not None:
                if current_pending is not None and current_pending != attempt.pending:
                    raise LicenseError(
                        "A newer Device authorization superseded this result.",
                        code="beta_auth_superseded",
                    )
                if current_pending == attempt.pending:
                    lock_guard.assert_held()
                    _remove_exact_device_pending_unlocked(
                        root,
                        attempt.pending,
                        failure_code="beta_auth_superseded",
                        failure_message=(
                            "A newer Device authorization replaced the completed state."
                        ),
                    )
                return completed
            current_snapshot = _read_beta_local_snapshot_state_unlocked()
            if isinstance(
                current_snapshot, License
            ) and current_snapshot.refresh_token in {
                attempt.pending.initial_refresh_token,
                attempt.pending.recovery_refresh_token,
            }:
                raise LicenseError(
                    "Realtor Beta found an incomplete signed Device result. "
                    "The recovery state was preserved.",
                    code="beta_device_completion_incomplete",
                )
            if (
                current_pending != attempt.pending
                or not _same_beta_local_snapshot_state(
                    current_snapshot,
                    attempt.starting_snapshot,
                )
            ):
                raise LicenseError(
                    "A newer Realtor Beta session superseded Device sign-in.",
                    code="beta_auth_superseded",
                )
            lock_guard.assert_held()
            _remove_exact_device_pending_unlocked(
                root,
                attempt.pending,
                failure_code="beta_auth_superseded",
                failure_message=(
                    "A newer Device authorization replaced the terminal state."
                ),
            )
            return None
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _commit_beta_device_license(
    attempt: _BetaDeviceAttempt,
    lic: License,
    *,
    expected_refresh_token: str,
    final: bool,
) -> License:
    """Commit signed B provisionally or signed C as final Device state.

    This is intentionally separate from generic auth persistence: marker
    discovery after network could authorize a different Device attempt. The
    exact marker and full signed/corrupt/absent predecessor are revalidated
    under the shared lock immediately before local mutation. B never removes
    D/B/C/I: another process may already have rotated the server to C. C is the
    only final Device credential and may replace an exact local B under the
    still-matching marker.
    """
    from elevate_cli import refresh_pending

    if lic.refresh_token != expected_refresh_token:
        raise LicenseError(
            "Elevation HQ returned credentials that did not match the protected "
            "Device attempt.",
            code="beta_device_refresh_token_mismatch",
        )
    _validate_complete_beta_license(lic, require_current=True)
    root = _beta_profile_root().expanduser().absolute()
    try:
        preflight_beta_license_store(require_writable=True)
        with refresh_pending.refresh_lock(root) as lock_guard:
            preflight_beta_license_store(require_writable=True)
            lock_guard.assert_held()
            pending_refresh, current_pending = _read_beta_credential_markers_unlocked(
                root
            )
            del pending_refresh
            current_snapshot = _read_beta_local_snapshot_state_unlocked()
            current_device_snapshot = (
                current_snapshot
                if isinstance(current_snapshot, License)
                and current_snapshot.refresh_token
                in {
                    attempt.pending.initial_refresh_token,
                    attempt.pending.recovery_refresh_token,
                }
                else None
            )

            # Exact signed C is a newer successful result than every late B
            # response. A different live marker is nevertheless authoritative:
            # an old attempt must not report its C as the result of that newer
            # in-progress Device authorization.
            if (
                current_device_snapshot is not None
                and current_device_snapshot.refresh_token
                == attempt.pending.recovery_refresh_token
            ):
                if current_pending is not None and current_pending != attempt.pending:
                    raise LicenseError(
                        "A newer Device authorization superseded this result.",
                        code="beta_auth_superseded",
                    )
                try:
                    _validate_complete_beta_license(
                        current_device_snapshot,
                        require_current=True,
                    )
                    sync_license_entitlements(current_device_snapshot)
                except LicenseError:
                    if current_pending is None:
                        raise LicenseError(
                            "A newer Device authorization superseded this result.",
                            code="beta_auth_superseded",
                        ) from None
                    if not final:
                        raise LicenseError(
                            "Realtor Beta found an incomplete signed Device result. "
                            "The recovery state was preserved.",
                            code="beta_device_completion_incomplete",
                        ) from None
                    if (
                        current_device_snapshot.license_id != lic.license_id
                        or current_device_snapshot.email != lic.email
                        or current_device_snapshot.subject != lic.subject
                    ):
                        raise LicenseError(
                            "The recovered Realtor Beta account changed signed identity.",
                            code="beta_entitlement_response_mismatch",
                        ) from None
                    # With the exact marker still authoritative, fresh signed C
                    # may repair a historical C assertion or entitlement mirror.
                else:
                    if current_pending == attempt.pending:
                        lock_guard.assert_held()
                        _remove_exact_device_pending_unlocked(
                            root,
                            attempt.pending,
                            failure_code="beta_auth_superseded",
                            failure_message=(
                                "A newer Device authorization replaced the "
                                "completed state."
                            ),
                        )
                    return current_device_snapshot

            if current_pending != attempt.pending:
                raise LicenseError(
                    "A newer Device authorization superseded this result.",
                    code="beta_auth_superseded",
                )

            # A locally durable B under the exact marker is shared interim
            # state. A late/different signed-B response must preserve it; a C
            # response is authorized to advance it regardless of which process
            # originally captured the pre-B predecessor.
            if (
                current_device_snapshot is not None
                and current_device_snapshot.refresh_token
                == attempt.pending.initial_refresh_token
            ):
                if (
                    current_device_snapshot.license_id != lic.license_id
                    or current_device_snapshot.email != lic.email
                    or current_device_snapshot.subject != lic.subject
                ):
                    raise LicenseError(
                        "The recovered Realtor Beta account changed signed identity.",
                        code="beta_entitlement_response_mismatch",
                    )
                if not final:
                    try:
                        _validate_complete_beta_license(
                            current_device_snapshot,
                            require_current=True,
                        )
                        sync_license_entitlements(current_device_snapshot)
                    except LicenseError:
                        # A fresh signed-B response may repair an expired or
                        # incompletely projected B while D/B/C/I still matches.
                        pass
                    else:
                        return current_device_snapshot
            elif (
                current_device_snapshot is None
                or current_device_snapshot.refresh_token
                != attempt.pending.recovery_refresh_token
            ) and not _same_beta_local_snapshot_state(
                current_snapshot,
                attempt.starting_snapshot,
            ):
                raise LicenseError(
                    "A newer Realtor Beta session superseded Device sign-in.",
                    code="beta_auth_superseded",
                )

            if final and expected_refresh_token != attempt.pending.recovery_refresh_token:
                raise LicenseError(
                    "Realtor Beta rejected an invalid final Device credential.",
                    code="beta_device_protocol_invalid",
                )
            if not final and expected_refresh_token != attempt.pending.initial_refresh_token:
                raise LicenseError(
                    "Realtor Beta rejected an invalid interim Device credential.",
                    code="beta_device_protocol_invalid",
                )

            lock_guard.assert_held()
            _save_exact_beta_unlocked(
                lic,
                starting_snapshot=current_snapshot,
            )
            persisted = read_verified_beta_license_snapshot(require_current=True)
            if persisted.to_dict() != lic.to_dict():
                raise LicenseError(
                    "Realtor Beta could not verify its Device sign-in snapshot.",
                    code="beta_license_persistence_mismatch",
                )
            # The entitlement projection and its strict readback are part of
            # both provisional and final local durability.
            sync_license_entitlements(persisted)
            _verify_beta_entitlement_mirror(persisted, require_current=True)
            lock_guard.assert_held()
            if refresh_pending.read_device_pending(root) != attempt.pending:
                raise LicenseError(
                    "A newer Device authorization superseded this result.",
                    code="beta_auth_superseded",
                )
            if final:
                _remove_exact_device_pending_unlocked(
                    root,
                    attempt.pending,
                    failure_code="beta_auth_superseded",
                    failure_message=(
                        "A newer Device authorization replaced the completed state."
                    ),
                )
            return persisted
    except refresh_pending.RefreshPendingError as exc:
        raise LicenseError(str(exc), code=exc.code) from exc


def _recover_beta_device_claim(
    attempt: _BetaDeviceAttempt,
    *,
    base_url: str,
) -> License:
    """Replay exact B -> C/I after the bounded Device claim window."""
    # The seven-field cross-runtime marker intentionally has no phase bit.
    # B/C/I is already durable before Device start, and Refresh-v2 is exactly
    # replayable, so restart recovery reuses the same marker instead of a
    # misleading same-value marker replacement.
    response = _post_beta_device(
        base_url,
        "/api/license/refresh",
        {
            "refresh_token": attempt.pending.initial_refresh_token,
            "next_refresh_token": attempt.pending.recovery_refresh_token,
            "refresh_attempt_id": attempt.pending.recovery_attempt_id,
        },
    )
    status_code = _beta_device_http_status(response)
    if status_code != 200:
        # Even 401 is ambiguous here: B may have rotated to C before a lost
        # response. Preserve B/C/I so the identical request can be replayed.
        raise LicenseError(
            "Elevation HQ could not safely recover Device sign-in "
            f"(HTTP {status_code}). The recovery state was preserved.",
            code=(
                "beta_device_recovery_rejected"
                if 400 <= status_code < 500
                else "beta_device_link_upstream_failed"
            ),
        )
    data = _beta_device_response_mapping(response)
    lic = _license_from_auth_response(data, email="")
    return _commit_beta_device_license(
        attempt,
        lic,
        expected_refresh_token=attempt.pending.recovery_refresh_token,
        final=True,
    )


def _link_device_exact_beta(
    device_label: Optional[str],
    *,
    interval_override: Optional[int],
) -> License:
    base_url = backend_url()
    prepared = _prepare_beta_device_attempt()
    if isinstance(prepared, License):
        return prepared
    attempt = prepared
    label = device_label or os.uname().nodename

    start_response = _post_beta_device(
        base_url,
        "/api/device/start",
        {
            "protocol_version": _BETA_DEVICE_PROTOCOL_VERSION,
            "device_code": attempt.pending.device_code,
            "device_label": label,
            "proposed_refresh_token_hash": hashlib.sha256(
                attempt.pending.initial_refresh_token.encode("ascii")
            ).hexdigest(),
        },
    )
    try:
        start = _parse_beta_device_start(
            start_response,
            base_url=base_url,
            pending=attempt.pending,
        )
    except LicenseError as exc:
        if exc.code in {"beta_device_link_denied", "beta_device_link_expired"}:
            completed = _terminalize_beta_device_attempt(attempt)
            if completed is not None:
                return completed
        raise

    if interval_override is not None:
        interval = _beta_device_interval(interval_override)
    else:
        interval = start.interval

    if start.resumed:
        print()
        print("  Resuming the protected Device sign-in already in progress.")
        print()
        # The local marker predates the server grant, so its age is a safe
        # lower bound. Always permit one poll to discover claimed recovery.
        now = time.time()
        deadline = max(
            now + interval + 1,
            attempt.pending.created_at + _BETA_DEVICE_GRANT_LIFETIME_SECONDS,
        )
        deadline = min(deadline, now + _BETA_DEVICE_GRANT_LIFETIME_SECONDS)
    else:
        assert start.verification_uri is not None
        assert start.verification_uri_complete is not None
        assert start.user_code is not None
        assert start.expires_in is not None
        print()
        print(f"  1. Open: {start.verification_uri_complete}")
        print(f"  2. Sign in if prompted, then enter this code: {start.user_code}")
        print()
        print(f"  (waiting up to {start.expires_in // 60} min — Ctrl-C to cancel)")
        print()
        deadline = time.time() + start.expires_in
    sys.stdout.flush()

    while time.time() < deadline:
        time.sleep(interval)
        response = _post_beta_device(
            base_url,
            "/api/device/poll",
            {
                "device_code": attempt.pending.device_code,
                "refresh_token": attempt.pending.initial_refresh_token,
            },
        )
        status_code = _beta_device_http_status(response)
        data = _beta_device_response_mapping(response)

        if status_code == 403 and data == {
            "error": "access_denied",
            "status": "denied",
        }:
            completed = _terminalize_beta_device_attempt(attempt)
            if completed is not None:
                return completed
            raise LicenseError(
                "The Device sign-in request was denied on the web.",
                code="beta_device_link_denied",
            )
        if status_code == 410 and data == {
            "error": "expired_token",
            "status": "expired",
        }:
            completed = _terminalize_beta_device_attempt(attempt)
            if completed is not None:
                return completed
            raise LicenseError(
                "The Device sign-in request expired.",
                code="beta_device_link_expired",
            )
        if status_code == 410 and data == {
            "error": "claim_retry_expired",
            "status": "claimed",
        }:
            return _recover_beta_device_claim(attempt, base_url=base_url)
        if status_code == 401 and data.get("error") == "invalid_grant":
            return _recover_beta_device_claim(attempt, base_url=base_url)
        if status_code != 200:
            raise LicenseError(
                "Elevation HQ could not safely continue Device sign-in "
                f"(HTTP {status_code}). The recovery state was preserved.",
                code=(
                    "beta_device_link_protocol_rejected"
                    if 400 <= status_code < 500
                    else "beta_device_link_upstream_failed"
                ),
            )
        if data.get("status") == "pending":
            if frozenset(data) != frozenset({"status", "interval"}):
                raise _beta_device_protocol_error(
                    "Elevation HQ returned an invalid pending Device response."
                )
            server_interval = _beta_device_interval(data.get("interval"))
            if interval_override is None:
                interval = server_interval
            continue
        if (
            data.get("status") != "approved"
            or type(data.get("protocol_version")) is not int
            or data.get("protocol_version") != _BETA_DEVICE_CLAIM_PROTOCOL_VERSION
        ):
            raise _beta_device_protocol_error(
                "Elevation HQ returned an invalid Device approval response."
            )
        lic = _license_from_auth_response(data, email="")
        interim = _commit_beta_device_license(
            attempt,
            lic,
            expected_refresh_token=attempt.pending.initial_refresh_token,
            final=False,
        )
        if interim.refresh_token == attempt.pending.recovery_refresh_token:
            return interim
        return _recover_beta_device_claim(attempt, base_url=base_url)

    raise LicenseError(
        "Device sign-in is still incomplete. Run the link command again to resume it.",
        code="beta_device_link_timeout",
    )


def link_device(device_label: Optional[str] = None, *, interval_override: Optional[int] = None) -> License:
    """OAuth-style device-authorization grant.

    Asks the backend for a short code, prints it + the URL the user should
    visit, then polls until the user approves or denies on the web. Persists
    the resulting license locally just like cmd_activate.
    """
    if _exact_realtor_beta_active():
        return _link_device_exact_beta(
            device_label,
            interval_override=interval_override,
        )

    base_url = backend_url()
    starting_snapshot = _capture_explicit_auth_starting_snapshot()
    label = device_label or os.uname().nodename

    try:
        with httpx.Client(timeout=15.0) as client:
            start = client.post(
                f"{base_url}/api/device/start",
                json={"device_label": label},
            )
    except httpx.HTTPError as exc:
        if _exact_realtor_beta_active():
            raise LicenseError(
                "Elevation HQ could not start device sign-in.",
                code="beta_device_link_upstream_unavailable",
            ) from exc
        raise
    if not start.is_success:
        raise _auth_flow_error(
            (
                f"Could not start device link ({start.status_code})."
                if _exact_realtor_beta_active()
                else f"Could not start device link ({start.status_code}): {start.text[:200]}"
            ),
            beta_code="beta_device_link_upstream_failed",
            beta_message=(
                "Could not start device link through Elevation HQ "
                f"(HTTP {start.status_code})."
            ),
        )

    start_data = _response_json(start)
    try:
        if not isinstance(start_data, dict):
            raise TypeError("device start response is not an object")
        device_code = start_data["device_code"]
        user_code = start_data["user_code"]
        verification_uri = start_data.get("verification_uri") or f"{base_url}/link"
        verification_uri_complete = start_data.get("verification_uri_complete")
        expires_in = int(start_data.get("expires_in", 600))
        interval = int(interval_override or start_data.get("interval", 5))
    except (KeyError, TypeError, ValueError) as exc:
        if _exact_realtor_beta_active():
            raise LicenseError(
                "Elevation HQ returned an incomplete device sign-in response.",
                code="beta_license_response_invalid",
            ) from exc
        raise
    print()
    print(f"  1. Open: {verification_uri_complete or verification_uri}")
    print(f"  2. Sign in if prompted, then enter this code: {user_code}")
    print()
    print(f"  (waiting up to {expires_in // 60} min — Ctrl-C to cancel)")
    print()
    sys.stdout.flush()

    deadline = time.time() + expires_in
    try:
        with httpx.Client(timeout=15.0) as client:
            while time.time() < deadline:
                time.sleep(interval)
                resp = client.post(
                    f"{base_url}/api/device/poll",
                    json={"device_code": device_code},
                )
                if resp.status_code == 410:
                    raise _auth_flow_error(
                        "Device-link request expired or already used. Run `elevate link` again.",
                        beta_code="beta_device_link_expired",
                    )
                if resp.status_code == 403:
                    raise _auth_flow_error(
                        "Request was denied on the web.",
                        beta_code="beta_device_link_denied",
                    )
                if not resp.is_success:
                    # Soft errors (rate-limited, transient) — keep polling.
                    continue
                data = _response_json(resp)
                if not isinstance(data, dict):
                    if _exact_realtor_beta_active():
                        raise LicenseError(
                            "Elevation HQ returned an invalid device sign-in response.",
                            code="beta_license_response_invalid",
                        )
                    raise TypeError("device poll response is not an object")
                status = data.get("status")
                if status == "pending":
                    continue
                if status == "approved":
                    return _accept_authenticated_response(
                        data,
                        email=str(data.get("email") or ""),
                        starting_snapshot=starting_snapshot,
                    )
    except httpx.HTTPError as exc:
        if _exact_realtor_beta_active():
            raise LicenseError(
                "Elevation HQ device sign-in was interrupted.",
                code="beta_device_link_upstream_unavailable",
            ) from exc
        raise

    raise _auth_flow_error(
        "Device-link request timed out. Run `elevate link` again.",
        beta_code="beta_device_link_timeout",
    )


def cmd_link(args) -> int:
    try:
        configure_backend_override(
            getattr(args, "backend_url", None),
            persist=True,
        )
    except LicenseError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2

    label = getattr(args, "label", None)
    sync_skills = (
        True
        if _exact_realtor_beta_active()
        else not getattr(args, "skip_skill_sync", False)
    )

    try:
        lic = link_device(label)
    except KeyboardInterrupt:
        print("\ncanceled", file=sys.stderr)
        return 130
    except LicenseError as e:
        if e.code == "license_error":
            print(f"link failed: {e}", file=sys.stderr)
        else:
            print(f"{e.code}: {e}", file=sys.stderr)
        return 1
    try:
        activation = activate_install(lic, sync_skills=sync_skills)
    except LicenseError as e:
        if e.code == "license_error":
            print(f"link failed: {e}", file=sys.stderr)
        else:
            print(f"{e.code}: {e}", file=sys.stderr)
        return 1
    print(f"linked {lic.email} ({lic.tier}). license id: {lic.license_id}")
    print(f"dashboard packs: {_format_enabled_packs(activation.get('packs') or {})}")
    if sync_skills:
        if activation.get("skill_error"):
            print(f"paid skill sync warning: {activation['skill_error']}", file=sys.stderr)
        elif activation.get("skill_count"):
            print(f"paid skills ready: {activation['skill_count']} at {activation.get('skills_path')}")
        else:
            print("paid skills ready: none returned for this tier")
        for warning in activation.get("skill_sync_warnings") or []:
            print(f"paid skill warning: {warning}", file=sys.stderr)
    print("next: run `elevate` or `elevate dashboard`.")
    if not activation.get("activation_complete"):
        print("activation_incomplete: account saved but setup did not finish.", file=sys.stderr)
        return 1
    return 0
