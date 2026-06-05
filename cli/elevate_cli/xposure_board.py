"""Per-account Xposure MLS board configuration.

The PCS pipeline + listing-views scraper target the Xposure MLS platform, which
is used by several BC real estate boards on distinct subdomains (e.g. Interior
BC = ``interiorrealtors.xposureapp.com`` / board code ``air``, Vancouver Island
VIVA = ``viva.xposureapp.com`` / board code ``viva``). The login/SSO entry point
also differs per board.

Everything used to be hardcoded to Interior BC. This reads the board from the
account env so each realtor hits THEIR own board, defaulting to Interior BC so
existing Interior accounts (e.g. Skyleigh) keep working unchanged.

Env (all optional; sensible Interior BC defaults):
  MLS_LOGIN_URL        SSO/login entry, e.g. https://viva.xposureapp.com/portal/viva/CreaSSOLanding
  XPOSURE_PORTAL_BASE  portal origin, e.g. https://viva.xposureapp.com
  XPOSURE_BOARD_CODE   path code, e.g. viva  (Interior = air)
  XPOSURE_MEMBERS_URL  members portal (Interior only), e.g. https://members.interiorbc.ca
"""

from __future__ import annotations

import os
from typing import Dict

_DEFAULTS = {
    "login_url": "https://iam.interiorbc.ca/idp/login",
    "members_url": "https://members.interiorbc.ca",
    "portal_base": "https://interiorrealtors.xposureapp.com",
    "board_code": "air",
}


def _derive_from_login(login_url: str) -> Dict[str, str]:
    """When MLS_LOGIN_URL points at an xposureapp.com subdomain (e.g. VIVA's
    ``https://viva.xposureapp.com/portal/viva/CreaSSOLanding``), derive the portal
    base + board code from it so a realtor self-configures from just their login
    URL. Interior BC logs in on a separate IAM host, so this returns {} for them
    and the Interior defaults stand."""
    try:
        rest = login_url.split("://", 1)[-1]
        host, _, path = rest.partition("/")
        if not host.endswith("xposureapp.com"):
            return {}
        out = {"portal_base": f"https://{host}"}
        segs = [s for s in path.split("/") if s]
        if "portal" in segs:
            i = segs.index("portal")
            if i + 1 < len(segs):
                out["board_code"] = segs[i + 1]
        return out
    except Exception:
        return {}


def board_config() -> Dict[str, str]:
    """Resolve the active account's Xposure board URLs from env (Interior BC defaults)."""
    login_url = (
        os.environ.get("MLS_LOGIN_URL")
        or os.environ.get("XPOSURE_LOGIN_URL")
        or _DEFAULTS["login_url"]
    ).strip()
    derived = _derive_from_login(login_url)
    portal_base = (
        os.environ.get("XPOSURE_PORTAL_BASE")
        or derived.get("portal_base")
        or _DEFAULTS["portal_base"]
    ).strip().rstrip("/")
    board_code = (
        os.environ.get("XPOSURE_BOARD_CODE")
        or derived.get("board_code")
        or _DEFAULTS["board_code"]
    ).strip().strip("/")
    members_url = (
        os.environ.get("XPOSURE_MEMBERS_URL") or _DEFAULTS["members_url"]
    ).strip().rstrip("/")
    return {
        "login_url": login_url,
        "members_url": members_url,
        "portal_base": portal_base,
        "board_code": board_code,
        "contacts_url": f"{portal_base}/portal/{board_code}/Contacts",
        "dologin_url": f"{portal_base}/pcs/{board_code}/DoLogin",
    }


def portal_host() -> str:
    """Bare host of the portal base, e.g. ``viva.xposureapp.com`` — for target matching."""
    base = board_config()["portal_base"]
    return base.split("://", 1)[-1].split("/", 1)[0]
