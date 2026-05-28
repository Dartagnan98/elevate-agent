"""Resolve real-estate portal credentials across onboarding and runtime.

Admin onboarding stores the human-facing browser playbook, while older portal
scripts still read env vars. Keep the alias map in one place so setup,
verification, and login automation agree on the same keys.
"""

from __future__ import annotations

from typing import Any, Mapping


PortalKey = str


PORTAL_ENV_ALIASES: dict[PortalKey, dict[str, tuple[str, ...]]] = {
    "mls": {
        "loginUrl": ("MLS_LOGIN_URL", "MATRIX_LOGIN_URL", "XPOSURE_LOGIN_URL"),
        "loginEmail": (
            "MLS_USERNAME",
            "MLS_USER",
            "MATRIX_USERNAME",
            "XPOSURE_USERNAME",
            "PARAGON_USERNAME",
        ),
        "loginPassword": (
            "MLS_PASSWORD",
            "MLS_PASS",
            "MATRIX_PASSWORD",
            "XPOSURE_PASSWORD",
            "PARAGON_PASSWORD",
        ),
    },
    "compliance": {
        "loginUrl": ("COMPLIANCE_LOGIN_URL", "SKYSLOPE_LOGIN_URL", "SKYSLOPE_URL"),
        "loginEmail": (
            "COMPLIANCE_USERNAME",
            "COMPLIANCE_USER",
            "SKYSLOPE_USERNAME",
            "SKYSLOPE_USER",
            "SKYSLOPE_EMAIL",
        ),
        "loginPassword": (
            "COMPLIANCE_PASSWORD",
            "COMPLIANCE_PASS",
            "SKYSLOPE_PASSWORD",
            "SKYSLOPE_PASS",
        ),
    },
    "showing": {
        "loginUrl": ("SHOWING_LOGIN_URL", "SHOWINGTIME_LOGIN_URL", "BROKERBAY_LOGIN_URL"),
        "loginEmail": (
            "SHOWING_USERNAME",
            "SHOWING_USER",
            "SHOWINGTIME_USERNAME",
            "SHOWINGTIME_USER",
            "BROKERBAY_USERNAME",
        ),
        "loginPassword": (
            "SHOWING_PASSWORD",
            "SHOWING_PASS",
            "SHOWINGTIME_PASSWORD",
            "SHOWINGTIME_PASS",
            "BROKERBAY_PASSWORD",
        ),
    },
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _provider_slug(value: Any) -> str:
    return _clean_text(value).lower().replace("_", "-").replace(" ", "-")


def _first_env_value(
    env_values: Mapping[str, Any] | None,
    keys: tuple[str, ...],
) -> tuple[str | None, str | None]:
    if not env_values:
        return None, None
    for key in keys:
        value = _clean_text(env_values.get(key))
        if value:
            return value, key
    return None, None


def resolve_portal_env(
    env_values: Mapping[str, Any] | None,
    portal: PortalKey,
) -> dict[str, str | bool | None]:
    """Return the first configured env values for one real-estate portal."""
    aliases = PORTAL_ENV_ALIASES.get(portal, {})
    login_url, login_url_env = _first_env_value(env_values, aliases.get("loginUrl", ()))
    login_email, login_email_env = _first_env_value(env_values, aliases.get("loginEmail", ()))
    login_password, login_password_env = _first_env_value(env_values, aliases.get("loginPassword", ()))
    return {
        "portal": portal,
        "loginUrl": login_url,
        "loginUrlEnv": login_url_env,
        "loginEmail": login_email,
        "loginEmailEnv": login_email_env,
        "loginPassword": login_password,
        "loginPasswordEnv": login_password_env,
        "hasLoginUrl": bool(login_url),
        "hasLoginEmail": bool(login_email),
        "hasLoginPassword": bool(login_password),
        "hasLoginSecret": bool(login_password),
        "configured": bool(login_url and login_email and login_password),
    }


def resolve_admin_portal_env(env_values: Mapping[str, Any] | None) -> dict[str, dict[str, str | bool | None]]:
    return {portal: resolve_portal_env(env_values, portal) for portal in PORTAL_ENV_ALIASES}


def portal_playbook_ready(playbook: Mapping[str, Any] | None) -> bool:
    """Return True when a browser playbook has enough data to attempt login.

    Notes alone are not a credential. A browser portal needs a provider, login
    URL, and either a credential reference or both username + password.
    """
    if not isinstance(playbook, Mapping):
        return False
    provider = _clean_text(playbook.get("provider"))
    login_url = _clean_text(playbook.get("loginUrl"))
    login_email = _clean_text(playbook.get("loginEmail"))
    login_password = _clean_text(playbook.get("loginPassword"))
    credential_ref = _clean_text(playbook.get("credentialRef"))
    return bool(provider and login_url and (credential_ref or (login_email and login_password)))


def portal_env_updates_from_playbooks(playbooks: Mapping[str, Any] | None) -> dict[str, str]:
    """Mirror onboarding browser playbooks into runtime env aliases.

    Empty fields never clear existing env values. SkySlope gets both the new
    canonical keys and the older SKYSLOPE_USER/SKYSLOPE_PASS aliases used by
    legacy browser scripts.
    """
    if not isinstance(playbooks, Mapping):
        return {}

    updates: dict[str, str] = {}

    def put(key: str, value: Any) -> None:
        text = _clean_text(value)
        if text:
            updates[key] = text

    mls = playbooks.get("mls") if isinstance(playbooks.get("mls"), Mapping) else {}
    put("MLS_LOGIN_URL", mls.get("loginUrl") if isinstance(mls, Mapping) else "")
    put("MLS_USERNAME", mls.get("loginEmail") if isinstance(mls, Mapping) else "")
    put("MLS_PASSWORD", mls.get("loginPassword") if isinstance(mls, Mapping) else "")

    compliance = playbooks.get("compliance") if isinstance(playbooks.get("compliance"), Mapping) else {}
    if isinstance(compliance, Mapping):
        provider_slug = _provider_slug(compliance.get("provider"))
        put("COMPLIANCE_LOGIN_URL", compliance.get("loginUrl"))
        put("COMPLIANCE_USERNAME", compliance.get("loginEmail"))
        put("COMPLIANCE_PASSWORD", compliance.get("loginPassword"))
        if "skyslope" in provider_slug:
            put("SKYSLOPE_LOGIN_URL", compliance.get("loginUrl"))
            put("SKYSLOPE_USERNAME", compliance.get("loginEmail"))
            put("SKYSLOPE_USER", compliance.get("loginEmail"))
            put("SKYSLOPE_PASSWORD", compliance.get("loginPassword"))
            put("SKYSLOPE_PASS", compliance.get("loginPassword"))

    showing = playbooks.get("showing") if isinstance(playbooks.get("showing"), Mapping) else {}
    if isinstance(showing, Mapping):
        provider_slug = _provider_slug(showing.get("provider"))
        put("SHOWING_LOGIN_URL", showing.get("loginUrl"))
        put("SHOWING_USERNAME", showing.get("loginEmail"))
        put("SHOWING_PASSWORD", showing.get("loginPassword"))
        if "showingtime" in provider_slug:
            put("SHOWINGTIME_LOGIN_URL", showing.get("loginUrl"))
            put("SHOWINGTIME_USERNAME", showing.get("loginEmail"))
            put("SHOWINGTIME_PASSWORD", showing.get("loginPassword"))
        if "brokerbay" in provider_slug:
            put("BROKERBAY_LOGIN_URL", showing.get("loginUrl"))
            put("BROKERBAY_USERNAME", showing.get("loginEmail"))
            put("BROKERBAY_PASSWORD", showing.get("loginPassword"))

    return updates


def _storage_password_env(portal: str, playbook: Mapping[str, Any]) -> str:
    provider_slug = _provider_slug(playbook.get("provider"))
    if portal == "mls":
        return "MLS_PASSWORD"
    if portal == "compliance":
        return "SKYSLOPE_PASSWORD" if "skyslope" in provider_slug else "COMPLIANCE_PASSWORD"
    if portal == "showing":
        if "showingtime" in provider_slug:
            return "SHOWINGTIME_PASSWORD"
        if "brokerbay" in provider_slug:
            return "BROKERBAY_PASSWORD"
        return "SHOWING_PASSWORD"
    return f"{portal.upper()}_PASSWORD"


def portal_playbooks_for_storage(playbooks: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return browser playbooks safe for SQLite storage.

    Raw passwords are mirrored into .env by ``portal_env_updates_from_playbooks``.
    The stored setup record keeps only an ``env:KEY`` reference so generated
    memory and runtime prompts never need to carry the secret value.
    """
    if not isinstance(playbooks, Mapping):
        return {}
    sanitized: dict[str, dict[str, Any]] = {}
    for portal, raw_playbook in playbooks.items():
        if not isinstance(raw_playbook, Mapping):
            continue
        playbook = dict(raw_playbook)
        login_password = _clean_text(playbook.pop("loginPassword", ""))
        if login_password and not _clean_text(playbook.get("credentialRef")):
            playbook["credentialRef"] = f"env:{_storage_password_env(str(portal), playbook)}"
        sanitized[str(portal)] = playbook
    return sanitized
