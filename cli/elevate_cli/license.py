"""
Elevate subscription license gate.

Lives alongside (but independent of) the BYOK auth system. That system
handles LLM provider credentials. This module handles the paid
subscription to the CTRL Strategies skill library.

Flow:
    elevate subscribe         -> POST /api/auth/login, stores license.json
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
from typing import Optional

import httpx

DEFAULT_BACKEND = "https://elevate.ctrlstrategies.com"
BACKEND_URL = os.environ.get("ELEVATE_BACKEND_URL", DEFAULT_BACKEND).rstrip("/")

LICENSE_PATH = Path(os.environ.get("ELEVATE_HOME") or Path.home() / ".elevate") / "license.json"

# Refresh when <5 minutes of access-token life remain.
REFRESH_MARGIN_SECONDS = 300


@dataclass
class License:
    access_token: str
    refresh_token: str
    license_id: str
    tier: str
    email: str
    expires_at: int

    def is_expired(self, margin: int = REFRESH_MARGIN_SECONDS) -> bool:
        return time.time() > (self.expires_at - margin)

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "license_id": self.license_id,
            "tier": self.tier,
            "email": self.email,
            "expires_at": self.expires_at,
        }


class LicenseError(Exception):
    """Raised when license is missing, revoked, or cannot be refreshed."""


def _decode_jwt_exp(token: str) -> int:
    """Extract exp claim without verifying signature. The server is authoritative."""
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        return int(payload.get("exp", 0))
    except Exception:
        return 0


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
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{BACKEND_URL}/api/auth/login",
            json={
                "email": email,
                "password": password,
                "device_label": device_label or os.uname().nodename,
            },
        )
    if resp.status_code == 402:
        raise LicenseError("No active subscription. Subscribe at ctrlstrategies.com/elevate.")
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
    )
    save(lic)
    return lic


def refresh(lic: License) -> License:
    """POST /api/license/refresh. Rotates the refresh token."""
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{BACKEND_URL}/api/license/refresh",
            json={"refresh_token": lic.refresh_token},
        )
    if resp.status_code == 402:
        clear()
        raise LicenseError("Subscription inactive — license revoked. Visit ctrlstrategies.com/elevate.")
    if resp.status_code == 401:
        clear()
        raise LicenseError("Refresh token rejected. Run `elevate subscribe` to log in again.")
    if not resp.is_success:
        raise LicenseError(f"Refresh failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    new_lic = License(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        license_id=lic.license_id,
        tier=lic.tier,
        email=lic.email,
        expires_at=_decode_jwt_exp(data["access_token"]),
    )
    save(new_lic)
    return new_lic


def ensure_valid() -> License:
    """Called on chat entry. Returns a fresh license or raises LicenseError."""
    lic = load()
    if not lic:
        raise LicenseError(
            "No Elevate subscription on this machine. Run `elevate subscribe` to log in.",
        )
    if lic.is_expired():
        lic = refresh(lic)
    return lic


def status_text(lic: Optional[License] = None) -> str:
    lic = lic or load()
    if not lic:
        return "Not subscribed. Run `elevate subscribe`."
    remaining = lic.expires_at - int(time.time())
    state = "expired" if remaining <= 0 else f"{remaining // 60}m left"
    return f"Subscribed: {lic.email} ({lic.tier}) — token {state}"


# --- CLI subcommand dispatch ---
# Wired from elevate_cli/main.py via a `subscribe` / `license` argparse subparser.

def cmd_subscribe(args) -> int:
    import getpass

    email = args.email or input("Email: ").strip()
    password = args.password or getpass.getpass("Password: ")
    try:
        lic = login(email, password)
    except LicenseError as e:
        print(f"login failed: {e}", file=sys.stderr)
        return 1
    print(f"logged in as {lic.email} ({lic.tier}). license id: {lic.license_id}")
    return 0


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
