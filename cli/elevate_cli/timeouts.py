from __future__ import annotations

import math
from typing import Any


def _coerce_timeout(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        return None
    return timeout


def _provider_config_timeout(
    provider_config: object,
    model: str | None,
    *,
    stale: bool,
) -> float | None:
    if not isinstance(provider_config, dict):
        return None

    model_config = _get_model_config(provider_config, model)
    if model_config is not None:
        model_key = "stale_timeout_seconds" if stale else "timeout_seconds"
        timeout = _coerce_timeout(model_config.get(model_key))
        if timeout is not None:
            return timeout

    provider_key = "stale_timeout_seconds" if stale else "request_timeout_seconds"
    return _coerce_timeout(provider_config.get(provider_key))


def _provider_base_url(provider_config: object) -> str:
    if not isinstance(provider_config, dict):
        return ""
    return str(
        provider_config.get("api")
        or provider_config.get("url")
        or provider_config.get("base_url")
        or ""
    ).strip().rstrip("/")


def resolve_provider_timeout_policy(
    provider_id: str,
    model: str | None = None,
    *,
    base_url: str = "",
    fallback_provider_id: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve request/stale timeouts together with their policy identity.

    Native runtimes may canonicalize a saved provider name (for example,
    ``custom:gov-bedrock``) before the client is built.  Matching the exact
    saved endpoint lets the runtime retain that entry's timeout bounds instead
    of silently falling back to the canonical provider defaults.  Conflicting
    saved entries for the same endpoint fail closed because choosing either
    bound would be nondeterministic.
    """
    if config is None:
        try:
            from elevate_cli.config import load_config
        except ImportError:
            return {
                "request_timeout": None,
                "request_provider": "",
                "stale_timeout": None,
                "stale_provider": "",
                "policy_provider": "",
            }
        config = load_config()
    providers = config.get("providers", {}) if isinstance(config, dict) else {}
    if not isinstance(providers, dict):
        providers = {}

    raw_provider = str(provider_id or "").strip()
    fallback_provider = str(fallback_provider_id or "").strip()
    candidate_keys: list[str] = []

    def _add_candidate(candidate: str) -> None:
        if candidate and candidate not in candidate_keys:
            candidate_keys.append(candidate)

    # A named policy is authoritative when it is still available.  Explicit
    # ``custom:<key>`` selectors address the same providers mapping entry.
    if raw_provider and raw_provider != fallback_provider:
        _add_candidate(raw_provider)
        if raw_provider.lower().startswith("custom:"):
            _add_candidate(raw_provider.split(":", 1)[1])

    normalized_base_url = str(base_url or "").strip().rstrip("/")
    matching_endpoint_keys: list[str] = []
    if normalized_base_url:
        for key, entry in providers.items():
            if _provider_base_url(entry) == normalized_base_url:
                matching_endpoint_keys.append(str(key))

    if len(matching_endpoint_keys) > 1:
        endpoint_policies = {
            (
                _provider_config_timeout(providers.get(key), model, stale=False),
                _provider_config_timeout(providers.get(key), model, stale=True),
            )
            for key in matching_endpoint_keys
        }
        if len(endpoint_policies) > 1:
            raise ValueError(
                "Conflicting timeout policies are configured for the same provider endpoint"
            )
    for key in matching_endpoint_keys:
        _add_candidate(key)

    _add_candidate(raw_provider)
    _add_candidate(fallback_provider)

    request_timeout = None
    request_provider = ""
    stale_timeout = None
    stale_provider = ""
    policy_provider = candidate_keys[0] if candidate_keys else ""
    for key in candidate_keys:
        provider_config = providers.get(key)
        if request_timeout is None:
            request_timeout = _provider_config_timeout(
                provider_config,
                model,
                stale=False,
            )
            if request_timeout is not None:
                request_provider = key
        if stale_timeout is None:
            stale_timeout = _provider_config_timeout(
                provider_config,
                model,
                stale=True,
            )
            if stale_timeout is not None:
                stale_provider = key
        if request_timeout is not None and stale_timeout is not None:
            break

    return {
        "request_timeout": request_timeout,
        "request_provider": request_provider,
        "stale_timeout": stale_timeout,
        "stale_provider": stale_provider,
        "policy_provider": policy_provider,
    }


def get_provider_request_timeout(
    provider_id: str, model: str | None = None
) -> float | None:
    """Return a configured provider request timeout in seconds, if any."""
    if not provider_id:
        return None

    try:
        from elevate_cli.config import load_config
    except ImportError:
        return None

    config = load_config()
    providers = config.get("providers", {}) if isinstance(config, dict) else {}
    provider_config = (
        providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    )
    return _provider_config_timeout(provider_config, model, stale=False)


def get_provider_stale_timeout(
    provider_id: str, model: str | None = None
) -> float | None:
    """Return a configured non-stream stale timeout in seconds, if any."""
    if not provider_id:
        return None

    try:
        from elevate_cli.config import load_config
    except ImportError:
        return None

    config = load_config()
    providers = config.get("providers", {}) if isinstance(config, dict) else {}
    provider_config = (
        providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    )
    return _provider_config_timeout(provider_config, model, stale=True)


def _get_model_config(
    provider_config: dict[str, object], model: str | None
) -> dict[str, object] | None:
    if not model:
        return None

    models = provider_config.get("models", {})
    model_config = models.get(model, {}) if isinstance(models, dict) else {}
    if isinstance(model_config, dict):
        return model_config
    return None
