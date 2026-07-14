"""ACP auth helpers — detect the currently configured Elevate provider."""

from __future__ import annotations

from typing import Optional


def detect_provider() -> Optional[str]:
    """Resolve the active Elevate runtime provider, or None if unavailable."""
    # The Realtor Beta auth advertisement is intentionally a pure read of the
    # current profile.  Do not invoke the generic runtime resolver here: doing
    # so can refresh credentials, inspect provider pools, or discover an
    # alternate provider merely because an editor initialized its ACP client.
    from elevate_cli.beta_provider_policy import (
        BETA_ALLOWED_PROVIDER,
        beta_provider_policy_active,
        read_beta_codex_auth_status,
    )

    if beta_provider_policy_active():
        from elevate_constants import get_elevate_home

        status = read_beta_codex_auth_status(get_elevate_home())
        return BETA_ALLOWED_PROVIDER if status.get("logged_in") else None

    try:
        from elevate_cli.runtime_provider import resolve_runtime_provider
        runtime = resolve_runtime_provider()
        api_key = runtime.get("api_key")
        provider = runtime.get("provider")
        if isinstance(api_key, str) and api_key.strip() and isinstance(provider, str) and provider.strip():
            return provider.strip().lower()
    except Exception:
        return None
    return None


def has_provider() -> bool:
    """Return True if Elevate can resolve any runtime provider credentials."""
    return detect_provider() is not None
