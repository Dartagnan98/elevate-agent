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
      "expires_at": 1234567890
    }
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
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
        return payload


class LicenseError(Exception):
    """Raised when license is missing, revoked, or cannot be refreshed."""


def backend_url() -> str:
    """Return the configured Elevation HQ license/skill API origin."""
    if not BACKEND_URL:
        raise LicenseError(
            "Elevation Real Estate HQ backend URL is not configured. "
            "Set ELEVATE_BACKEND_URL before running `elevate activate`.",
        )
    return BACKEND_URL


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


def _extract_entitlements(data: dict[str, Any]) -> list[str] | None:
    for key in ("entitlements", "packs", "features"):
        if key in data:
            return _normalize_entitlements(data.get(key))
    return None


def sync_license_entitlements(lic: License) -> None:
    """Mirror server-granted paid packs into local dashboard entitlements."""
    if lic.entitlements is None:
        return
    try:
        from elevate_cli.access import REAL_ESTATE_ENTITLEMENTS, update_entitlement

        granted = set(lic.entitlements)
        for entitlement in REAL_ESTATE_ENTITLEMENTS:
            allowed = entitlement in granted
            update_entitlement(
                entitlement,
                status="active" if allowed else "locked",
                owned_snapshot=allowed,
            )
    except Exception:
        # Access sync should never make an otherwise valid login unusable.
        return


def load() -> Optional[License]:
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
    LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LICENSE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(lic.to_dict(), indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(LICENSE_PATH)


def clear() -> bool:
    if LICENSE_PATH.exists():
        LICENSE_PATH.unlink()
        return True
    return False


def login(email: str, password: str, device_label: Optional[str] = None) -> License:
    """POST /api/auth/login, persist license."""
    base_url = backend_url()
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{base_url}/api/auth/login",
            json={
                "email": email,
                "password": password,
                "device_label": device_label or os.uname().nodename,
            },
        )
    if resp.status_code == 402:
        raise LicenseError("No active subscription. Contact Elevation Real Estate HQ to activate Elevate.")
    if resp.status_code == 401:
        raise LicenseError("Invalid email or password.")
    if not resp.is_success:
        raise LicenseError(f"Login failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    lic = License(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        license_id=data["license_id"],
        tier=data.get("tier", "pro"),
        email=email,
        expires_at=_decode_jwt_exp(data["access_token"]),
        entitlements=_extract_entitlements(data),
    )
    save(lic)
    sync_license_entitlements(lic)
    return lic


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
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{base_url}/api/auth/signup",
            json={
                "email": email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name,
                "device_label": device_label or os.uname().nodename,
            },
        )
    if resp.status_code == 409:
        raise LicenseError("An account with this email already exists — sign in instead.")
    if resp.status_code == 400:
        raise LicenseError("Enter a valid email and a password of at least 8 characters.")
    if resp.status_code == 429:
        raise LicenseError("Too many attempts. Please wait a few minutes and try again.")
    if not resp.is_success:
        raise LicenseError(f"Account creation failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    lic = License(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        license_id=data["license_id"],
        tier=data.get("tier", "pro"),
        email=email,
        expires_at=_decode_jwt_exp(data["access_token"]),
        entitlements=_extract_entitlements(data),
    )
    save(lic)
    sync_license_entitlements(lic)
    return lic


def request_login_code(email: str) -> None:
    """POST /api/auth/login-code/request — HQ emails a one-time sign-in code."""
    base_url = backend_url()
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{base_url}/api/auth/login-code/request",
            json={"email": email},
        )
    if resp.status_code == 429:
        raise LicenseError("Too many code requests. Wait a few minutes and try again.")
    if not resp.is_success:
        raise LicenseError(f"Could not send code ({resp.status_code}): {resp.text[:200]}")


def login_with_code(email: str, code: str, device_label: Optional[str] = None) -> License:
    """POST /api/auth/login-code/verify, persist license. Same outcome as
    login() but authenticated by a one-time emailed code instead of a password."""
    base_url = backend_url()
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{base_url}/api/auth/login-code/verify",
            json={
                "email": email,
                "code": code,
                "device_label": device_label or os.uname().nodename,
            },
        )
    if resp.status_code == 402:
        raise LicenseError("No active subscription. Contact Elevation Real Estate HQ to activate Elevate.")
    if resp.status_code == 401:
        raise LicenseError("Invalid or expired code.")
    if not resp.is_success:
        raise LicenseError(f"Code sign-in failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    lic = License(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        license_id=data["license_id"],
        tier=data.get("tier", "pro"),
        email=email,
        expires_at=_decode_jwt_exp(data["access_token"]),
        entitlements=_extract_entitlements(data),
    )
    save(lic)
    sync_license_entitlements(lic)
    return lic


def refresh(lic: License) -> License:
    """POST /api/license/refresh. Rotates the refresh token."""
    base_url = backend_url()
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{base_url}/api/license/refresh",
            json={"refresh_token": lic.refresh_token},
        )
    if resp.status_code == 402:
        # Subscription explicitly inactive — definitive answer from HQ, clear
        # immediately so the user is forced through `activate` after they
        # re-subscribe.
        _reset_fail_count()
        clear()
        raise LicenseError("Subscription inactive — license revoked. Contact Elevation Real Estate HQ.")
    if resp.status_code == 401:
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
        raise LicenseError(f"Refresh failed ({resp.status_code}): {resp.text[:200]}")

    _reset_fail_count()

    data = resp.json()
    new_lic = License(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        license_id=lic.license_id,
        tier=lic.tier,
        email=lic.email,
        expires_at=_decode_jwt_exp(data["access_token"]),
        entitlements=_extract_entitlements(data)
        if any(key in data for key in ("entitlements", "packs", "features"))
        else lic.entitlements,
    )
    save(new_lic)
    sync_license_entitlements(new_lic)
    return new_lic


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
    }

    try:
        from elevate_cli.access import dashboard_access_status

        result["packs"] = dashboard_access_status().get("packs", {})
    except Exception as exc:
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
            result["skill_error"] = str(exc)

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

    backend = str(getattr(args, "backend_url", "") or "").strip().rstrip("/")
    if backend:
        global BACKEND_URL
        BACKEND_URL = backend
        os.environ["ELEVATE_BACKEND_URL"] = backend
        try:
            from elevate_cli.config import save_env_value

            save_env_value("ELEVATE_BACKEND_URL", backend)
        except Exception:
            pass

    email = args.email or input("Email: ").strip()
    password = args.password or getpass.getpass("Password: ")
    sync_skills = not getattr(args, "skip_skill_sync", False)
    try:
        lic = login(email, password)
    except LicenseError as e:
        print(f"login failed: {e}", file=sys.stderr)
        return 1
    activation = activate_install(lic, sync_skills=sync_skills)
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
            print(f"refresh failed: {e}", file=sys.stderr)
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

    with httpx.Client(timeout=15.0) as client:
        start = client.post(f"{base_url}/api/device/start", json={"device_label": label})
    if not start.is_success:
        raise LicenseError(f"Could not start device link ({start.status_code}): {start.text[:200]}")

    start_data = start.json()
    device_code = start_data["device_code"]
    user_code = start_data["user_code"]
    verification_uri = start_data.get("verification_uri") or f"{base_url}/link"
    verification_uri_complete = start_data.get("verification_uri_complete")
    expires_in = int(start_data.get("expires_in", 600))
    interval = int(interval_override or start_data.get("interval", 5))

    print()
    print(f"  1. Open: {verification_uri_complete or verification_uri}")
    print(f"  2. Sign in if prompted, then enter this code: {user_code}")
    print()
    print(f"  (waiting up to {expires_in // 60} min — Ctrl-C to cancel)")
    print()
    sys.stdout.flush()

    deadline = time.time() + expires_in
    with httpx.Client(timeout=15.0) as client:
        while time.time() < deadline:
            time.sleep(interval)
            resp = client.post(f"{base_url}/api/device/poll", json={"device_code": device_code})
            if resp.status_code == 410:
                raise LicenseError("Device-link request expired or already used. Run `elevate link` again.")
            if resp.status_code == 403:
                raise LicenseError("Request was denied on the web.")
            if not resp.is_success:
                # Soft errors (rate-limited, transient) — keep polling
                continue
            data = resp.json()
            status = data.get("status")
            if status == "pending":
                continue
            if status == "approved":
                lic = License(
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                    license_id=data["license_id"],
                    tier=data.get("tier", "pro"),
                    email=data.get("email", ""),
                    expires_at=_decode_jwt_exp(data["access_token"]),
                    entitlements=_extract_entitlements(data),
                )
                save(lic)
                sync_license_entitlements(lic)
                return lic

    raise LicenseError("Device-link request timed out. Run `elevate link` again.")


def cmd_link(args) -> int:
    backend = str(getattr(args, "backend_url", "") or "").strip().rstrip("/")
    if backend:
        global BACKEND_URL
        BACKEND_URL = backend
        os.environ["ELEVATE_BACKEND_URL"] = backend
        try:
            from elevate_cli.config import save_env_value
            save_env_value("ELEVATE_BACKEND_URL", backend)
        except Exception:
            pass

    label = getattr(args, "label", None)
    sync_skills = not getattr(args, "skip_skill_sync", False)

    try:
        lic = link_device(label)
    except KeyboardInterrupt:
        print("\ncanceled", file=sys.stderr)
        return 130
    except LicenseError as e:
        print(f"link failed: {e}", file=sys.stderr)
        return 1

    activation = activate_install(lic, sync_skills=sync_skills)
    print(f"linked {lic.email} ({lic.tier}). license id: {lic.license_id}")
    print(f"dashboard packs: {_format_enabled_packs(activation.get('packs') or {})}")
    if sync_skills:
        if activation.get("skill_error"):
            print(f"paid skill sync warning: {activation['skill_error']}", file=sys.stderr)
        elif activation.get("skill_count"):
            print(f"paid skills ready: {activation['skill_count']} at {activation.get('skills_path')}")
        else:
            print("paid skills ready: none returned for this tier")
    print("next: run `elevate` or `elevate dashboard`.")
    return 0
