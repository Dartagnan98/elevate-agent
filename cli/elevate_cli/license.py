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
import json
import os
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


def _auth_flow_error(message: str, *, beta_code: str) -> LicenseError:
    """Keep Stable errors compatible while making every Beta path typed."""
    return LicenseError(
        message,
        code=beta_code if _exact_realtor_beta_active() else "license_error",
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
    for name in ("entitlements", "packs", "features"):
        if name not in raw:
            continue
        duplicate = _normalize_entitlements(raw.get(name))
        if duplicate != canonical.entitlements:
            raise LicenseError(
                "The Realtor Beta entitlement fields did not match their signed assertion.",
                code="beta_entitlement_response_mismatch",
            )


def _beta_license_from_mapping(raw: object) -> License:
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
    canonical = _beta_license_from_mapping(lic.to_dict())
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
    """Read a signature-verified, current local Beta snapshot or raise typed.

    ``require_current`` remains in the public signature for compatibility, but
    signed Realtor Beta assertions are never accepted outside their validity
    window.  An expired assertion requires a fresh sign-in instead of becoming
    a local identity oracle.
    """
    preflight_beta_license_store(require_writable=False)
    try:
        raw = json.loads(_read_beta_snapshot_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError(
            "The Realtor Beta account snapshot is missing or unreadable.",
            code="beta_license_snapshot_invalid",
        ) from exc
    lic = _beta_license_from_mapping(raw)
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


def _invalidate_beta_snapshot(message: str) -> None:
    """Remove all local paid state, raising typed if removal is unverified."""
    if not _exact_realtor_beta_active():
        return
    try:
        _atomic_beta_replace(None)
    except Exception as exc:
        raise LicenseError(
            message,
            code="beta_license_persistence_failed",
        ) from exc


def _invalidate_beta_snapshot_if_matches(lic: License, message: str) -> bool:
    """Remove only the Beta snapshot that produced a rejected refresh.

    Another process may already have rotated and persisted a new signed token
    pair.  A late 401 for the old pair must never erase that newer session.
    """
    if not _exact_realtor_beta_active():
        return False
    try:
        current = read_verified_beta_license_snapshot(require_current=True)
    except LicenseError:
        _invalidate_beta_snapshot(message)
        return True
    if (
        current.access_token != lic.access_token
        or current.refresh_token != lic.refresh_token
        or current.entitlement_assertion != lic.entitlement_assertion
    ):
        return False
    _invalidate_beta_snapshot(message)
    return True


def sync_license_entitlements(lic: License) -> None:
    """Mirror server-granted paid packs into local dashboard entitlements."""
    if _exact_realtor_beta_active():
        _validate_complete_beta_license(lic, require_current=True)
        persisted = read_verified_beta_license_snapshot(require_current=True)
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


def save(lic: License) -> None:
    if _exact_realtor_beta_active():
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
            _invalidate_beta_snapshot_if_matches(
                lic,
                "Realtor Beta could not save or invalidate its account snapshot."
            )
            if isinstance(exc, LicenseError):
                raise
            raise LicenseError(
                "Realtor Beta could not save its account snapshot.",
                code="beta_license_persistence_failed",
            ) from exc
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
        preflight_beta_license_store(require_writable=True)
        existed = LICENSE_PATH.exists()
        _atomic_beta_replace(None)
        return existed
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
        _validate_complete_beta_license(existing, require_current=True)
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


def _persist_authenticated_license(lic: License) -> None:
    save(lic)
    try:
        sync_license_entitlements(lic)
    except Exception:
        # A Beta login/refresh is not complete unless the just-written
        # snapshot can drive the exact same local access decision. Removing it
        # makes the failure Core-only instead of leaving a half-activated paid
        # session behind.
        if _exact_realtor_beta_active():
            _invalidate_beta_snapshot_if_matches(
                lic,
                "Realtor Beta could not roll back incomplete activation."
            )
        raise


def _accept_authenticated_response(
    data: object,
    *,
    email: str,
    existing: License | None = None,
) -> License:
    """Validate and persist one HQ success response, or invalidate Beta."""
    try:
        lic = _license_from_auth_response(data, email=email, existing=existing)
        _persist_authenticated_license(lic)
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
) -> License:
    """Decode an HQ HTTP success under the same fail-closed boundary."""
    data = _response_json(response)
    return _accept_authenticated_response(data, email=email, existing=existing)


def login(email: str, password: str, device_label: Optional[str] = None) -> License:
    """POST /api/auth/login, persist license."""
    base_url = backend_url()
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
            f"Login failed ({resp.status_code}): {resp.text[:200]}",
            beta_code="beta_auth_upstream_failed",
        )

    return _accept_hq_response(resp, email=email)


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
    base_url = backend_url()
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
            f"Account creation failed ({resp.status_code}): {resp.text[:200]}",
            beta_code="beta_auth_upstream_failed",
        )

    return _accept_hq_response(resp, email=email)


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
            f"Could not send code ({resp.status_code}): {resp.text[:200]}",
            beta_code="beta_auth_upstream_failed",
        )


def login_with_code(email: str, code: str, device_label: Optional[str] = None) -> License:
    """POST /api/auth/login-code/verify, persist license. Same outcome as
    login() but authenticated by a one-time emailed code instead of a password."""
    base_url = backend_url()
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
            f"Code sign-in failed ({resp.status_code}): {resp.text[:200]}",
            beta_code="beta_auth_upstream_failed",
        )

    return _accept_hq_response(resp, email=email)


def refresh(lic: License) -> License:
    """POST /api/license/refresh. Rotates the refresh token."""
    if _exact_realtor_beta_active():
        _validate_complete_beta_license(lic, require_current=True)
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
            f"Refresh failed ({resp.status_code}): {resp.text[:200]}",
            beta_code="beta_auth_upstream_failed",
        )

    _reset_fail_count()

    return _accept_hq_response(
        resp,
        email=lic.email,
        existing=lic,
    )


def ensure_valid() -> License:
    """Called on chat entry. Returns a fresh license or raises LicenseError."""
    lic = load()
    if not lic:
        raise LicenseError(
            "No Elevate subscription on this machine. Run `elevate activate` to log in.",
        )
    if lic.is_expired():
        lic = refresh(lic)
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
    if beta_active:
        _validate_complete_beta_license(lic, require_current=True)
        sync_skills = True
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

    if sync_skills:
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

    if beta_active and result.get("skill_sync_warnings"):
        raise LicenseError(
            "Realtor Beta could not verify every signed skill during activation.",
            code="beta_skill_sync_incomplete",
        )
    if beta_active:
        result["activation_complete"] = True
    else:
        # Stable historically treated skill failures as visible warnings and
        # still returned successful activation. Preserve that compatibility.
        result["activation_complete"] = True
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
    if _exact_realtor_beta_active() and not activation.get("activation_complete"):
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

def link_device(device_label: Optional[str] = None, *, interval_override: Optional[int] = None) -> License:
    """OAuth-style device-authorization grant.

    Asks the backend for a short code, prints it + the URL the user should
    visit, then polls until the user approves or denies on the web. Persists
    the resulting license locally just like cmd_activate.
    """
    base_url = backend_url()
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
            f"Could not start device link ({start.status_code}): {start.text[:200]}",
            beta_code="beta_device_link_upstream_failed",
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
    if _exact_realtor_beta_active() and not activation.get("activation_complete"):
        print("activation_incomplete: account saved but setup did not finish.", file=sys.stderr)
        return 1
    return 0
