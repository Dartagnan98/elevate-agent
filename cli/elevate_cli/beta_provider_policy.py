"""Fail-closed primary-model policy for the Realtor Beta channel.

This module deliberately depends only on the standard library.  In particular,
Beta onboarding must be able to inspect its own auth file without importing the
runtime credential pool, refreshing tokens, importing host credentials, or
performing network I/O.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping


BETA_PROVIDER_POLICY_VERSION = "realtor-beta-codex-v1"
BETA_ALLOWED_MODELS_VERSION = "2026-07-14-v1"
BETA_ALLOWED_PROVIDER = "openai-codex"
BETA_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
BETA_DEFAULT_MODEL = "gpt-5.5"
BETA_ALLOWED_MEMORY_PROVIDERS = ("", "holographic")
BETA_ALLOWED_MODELS = (
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
)

_BETA_ALLOWED_CONFIG_PLATFORMS = frozenset({"telegram", "api_server"})
_BETA_ENV_CONFIG_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class BetaProviderPolicyError(ValueError):
    """A Beta primary-provider invariant was violated."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "policyVersion": BETA_PROVIDER_POLICY_VERSION,
            "allowedProvider": BETA_ALLOWED_PROVIDER,
            "allowedModelsVersion": BETA_ALLOWED_MODELS_VERSION,
        }


def beta_provider_policy_active(environ: Mapping[str, str] | None = None) -> bool:
    """Return true only for the explicit, exact Beta release-channel value."""
    env = os.environ if environ is None else environ
    return env.get("ELEVATE_RELEASE_CHANNEL") == "beta"


def canonical_beta_provider(value: Any, *, source: str = "provider") -> str:
    """Map empty/auto to Codex and reject every non-Codex Beta provider."""
    provider = str(value or "").strip().lower()
    if provider in {"", "auto", BETA_ALLOWED_PROVIDER}:
        return BETA_ALLOWED_PROVIDER
    raise BetaProviderPolicyError(
        f"Realtor Beta does not allow {source} {provider!r}; use OpenAI Codex.",
        code="beta_provider_not_allowed",
    )


def beta_model_or_default(value: Any, *, source: str = "model") -> str:
    """Return the Beta default for empty input or validate an allowed model."""
    model = str(value or "").strip()
    if not model:
        return BETA_DEFAULT_MODEL
    if model not in BETA_ALLOWED_MODELS:
        raise BetaProviderPolicyError(
            f"Realtor Beta does not allow {source} {model!r}.",
            code="beta_model_not_allowed",
        )
    return model


def validate_beta_memory_provider(
    value: Any,
    *,
    environ: Mapping[str, str] | None = None,
    source: str = "memory provider",
) -> str:
    """Normalize a memory provider and reject nonlocal providers in Beta."""
    provider = str(value or "").strip().lower()
    if (
        beta_provider_policy_active(environ)
        and provider not in BETA_ALLOWED_MEMORY_PROVIDERS
    ):
        raise BetaProviderPolicyError(
            "Realtor Beta keeps memory local and does not allow external "
            f"{source} {provider!r}. Use built-in memory or Holographic.",
            code="beta_memory_provider_not_allowed",
        )
    return provider


def _beta_memory_embeddings_enabled(config: Mapping[str, Any]) -> bool:
    """Return the Holographic embedding toggle using its runtime semantics."""
    plugins = config.get("plugins")
    if not isinstance(plugins, Mapping):
        return False
    memory_store = plugins.get("elevate-memory-store")
    if not isinstance(memory_store, Mapping):
        return False
    value = memory_store.get("embedding_enabled")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def _validate_beta_memory_config(
    config: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Keep automatic Realtor Beta memory local and inference-free."""
    memory = config.get("memory")
    provider_value = memory.get("provider") if isinstance(memory, Mapping) else ""
    validate_beta_memory_provider(provider_value, environ=environ)
    if _beta_memory_embeddings_enabled(config):
        raise BetaProviderPolicyError(
            "Realtor Beta keeps memory local and does not allow embedding-based recall.",
            code="beta_memory_embeddings_not_allowed",
        )


def _beta_truthy(value: Any) -> bool:
    """Interpret config booleans without importing the wider runtime."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def _validate_beta_runtime_config(config: Mapping[str, Any]) -> None:
    """Reject mutable config that can reopen unsigned Beta runtime lanes.

    ``config.yaml`` is bridged into several long-lived runtime subsystems.  In
    Stable it intentionally supports operator-defined shell commands, remote
    terminal backends, platform adapters, and SSRF opt-outs.  Realtor Beta has
    signed product surfaces for those decisions instead, so neither the raw
    editor nor the normalized config API may silently re-enable them.
    """
    for raw_key, value in config.items():
        key = str(raw_key or "")
        if _BETA_ENV_CONFIG_KEY_RE.fullmatch(key) and value not in (None, ""):
            raise BetaProviderPolicyError(
                "Realtor Beta does not allow config.yaml to inject runtime environment settings.",
                code="beta_direct_env_config_not_allowed",
            )

    if config.get("quick_commands") not in (None, "", (), [], {}):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow config-defined quick commands.",
            code="beta_quick_commands_not_allowed",
        )

    if config.get("hooks") not in (None, "", (), [], {}):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow config-defined shell hooks.",
            code="beta_shell_hooks_not_allowed",
        )
    if _beta_truthy(config.get("hooks_auto_accept")):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow automatic shell-hook approval.",
            code="beta_shell_hooks_not_allowed",
        )

    if config.get("command_allowlist") not in (None, "", (), [], {}):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow permanent dangerous-command approvals.",
            code="beta_command_allowlist_not_allowed",
        )

    approvals = config.get("approvals")
    if approvals not in (None, "", {}):
        if not isinstance(approvals, Mapping):
            raise BetaProviderPolicyError(
                "Realtor Beta approval settings must be a mapping.",
                code="beta_approval_config_invalid",
            )
        mode_value = approvals.get("mode", "manual")
        if isinstance(mode_value, bool):
            mode = "off" if mode_value is False else "manual"
        else:
            mode = str(mode_value or "manual").strip().lower()
        if mode != "manual":
            raise BetaProviderPolicyError(
                "Realtor Beta requires human review and does not allow automatic approval modes.",
                code="beta_approval_mode_not_allowed",
            )
        permission_mode = str(
            approvals.get("permission_mode") or "default"
        ).strip()
        if permission_mode == "bypassPermissions":
            raise BetaProviderPolicyError(
                "Realtor Beta does not allow bypassing action permissions.",
                code="beta_permission_mode_not_allowed",
            )
        cron_mode = str(approvals.get("cron_mode") or "deny").strip().lower()
        if cron_mode != "deny":
            raise BetaProviderPolicyError(
                "Realtor Beta does not allow unattended jobs to approve dangerous commands.",
                code="beta_cron_approval_not_allowed",
            )

    terminal = config.get("terminal")
    if terminal not in (None, "", {}):
        if not isinstance(terminal, Mapping):
            raise BetaProviderPolicyError(
                "Realtor Beta terminal settings must be a mapping.",
                code="beta_terminal_config_invalid",
            )
        backend = str(
            terminal.get("backend") or terminal.get("env_type") or "local"
        ).strip().lower()
        if backend != "local":
            raise BetaProviderPolicyError(
                "Realtor Beta uses its local terminal harness and does not allow a remote terminal backend.",
                code="beta_terminal_backend_not_allowed",
            )

    for section_name in ("security", "browser"):
        section = config.get(section_name)
        if section in (None, "", {}):
            continue
        if not isinstance(section, Mapping):
            raise BetaProviderPolicyError(
                f"Realtor Beta {section_name} settings must be a mapping.",
                code="beta_url_safety_config_invalid",
            )
        if _beta_truthy(section.get("allow_private_urls")):
            raise BetaProviderPolicyError(
                "Realtor Beta does not allow disabling private-network URL protection.",
                code="beta_private_urls_not_allowed",
            )

    platforms = config.get("platforms")
    if platforms not in (None, "", {}):
        if not isinstance(platforms, Mapping):
            raise BetaProviderPolicyError(
                "Realtor Beta platform settings must be a mapping.",
                code="beta_platform_config_invalid",
            )
        unsupported = sorted(
            str(name)
            for name in platforms
            if str(name) not in _BETA_ALLOWED_CONFIG_PLATFORMS
        )
        if unsupported:
            raise BetaProviderPolicyError(
                "Realtor Beta supports only its in-app surface and Telegram pairing; "
                f"unsupported platform config: {', '.join(unsupported)}.",
                code="beta_platform_not_allowed",
            )
        for platform_name, platform_config in platforms.items():
            if not isinstance(platform_config, Mapping):
                raise BetaProviderPolicyError(
                    f"Realtor Beta {platform_name} platform settings must be a mapping.",
                    code="beta_platform_config_invalid",
                )
            if any(
                str(platform_config.get(secret_key) or "").strip()
                for secret_key in ("token", "api_key")
            ):
                raise BetaProviderPolicyError(
                    "Realtor Beta stores channel credentials only through its signed setup flow.",
                    code="beta_platform_credential_not_allowed",
                )
            extra = platform_config.get("extra")
            if (
                isinstance(extra, Mapping)
                and extra.get("agent_bots") not in (None, "", (), [], {})
            ):
                raise BetaProviderPolicyError(
                    "Realtor Beta loads signed agent Telegram bots only from its profile credential store.",
                    code="beta_platform_credential_not_allowed",
                )


def _validate_beta_inference_block(value: Any, *, source: str) -> None:
    """Keep auxiliary and delegated inference on the signed Codex lane."""
    if value in (None, "", {}):
        return
    if not isinstance(value, Mapping):
        raise BetaProviderPolicyError(
            f"Realtor Beta {source} settings must be a mapping.",
            code="beta_auxiliary_config_invalid",
        )

    provider = str(value.get("provider") or "auto").strip().lower()
    if provider not in {"auto", BETA_ALLOWED_PROVIDER}:
        raise BetaProviderPolicyError(
            f"Realtor Beta does not allow {source} provider {provider!r}.",
            code="beta_auxiliary_provider_not_allowed",
        )
    model = str(value.get("model") or value.get("default") or "").strip()
    if model and model not in BETA_ALLOWED_MODELS:
        raise BetaProviderPolicyError(
            f"Realtor Beta does not allow {source} model {model!r}.",
            code="beta_auxiliary_model_not_allowed",
        )
    base_url = str(value.get("base_url") or "").strip().rstrip("/")
    if base_url and base_url != BETA_CODEX_BASE_URL.rstrip("/"):
        raise BetaProviderPolicyError(
            f"Realtor Beta does not allow a custom {source} endpoint.",
            code="beta_auxiliary_endpoint_not_allowed",
        )
    if any(
        str(value.get(key) or "").strip()
        for key in ("api_key", "key_env")
    ):
        raise BetaProviderPolicyError(
            f"Realtor Beta {source} uses profile-local Codex auth, not API keys.",
            code="beta_auxiliary_api_key_not_allowed",
        )
    for key in ("fallback_model", "fallback_providers", "credential_pool"):
        if value.get(key) not in (None, "", (), [], {}):
            raise BetaProviderPolicyError(
                f"Realtor Beta does not allow {source} provider fallback.",
                code="beta_auxiliary_fallback_not_allowed",
            )


def _validate_beta_inference_config(config: Mapping[str, Any]) -> None:
    if config.get("providers") not in (None, "", (), [], {}):
        raise BetaProviderPolicyError(
            "Realtor Beta stores Codex authentication in its profile auth store, not config providers.",
            code="beta_provider_registry_not_allowed",
        )
    if config.get("credential_pool_strategies") not in (None, "", (), [], {}):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow inference credential pools.",
            code="beta_credential_pool_not_allowed",
        )

    auxiliary = config.get("auxiliary")
    if auxiliary not in (None, "", {}):
        if not isinstance(auxiliary, Mapping):
            raise BetaProviderPolicyError(
                "Realtor Beta auxiliary settings must be a mapping.",
                code="beta_auxiliary_config_invalid",
            )
        for task_name, task_config in auxiliary.items():
            _validate_beta_inference_block(
                task_config,
                source=f"auxiliary {task_name}",
            )

    _validate_beta_inference_block(config.get("delegation"), source="delegation")


def validate_beta_config_for_persistence(
    config: Mapping[str, Any],
    auth_status: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Reject Beta provider escape hatches before a config write.

    Empty primary-model state is valid while onboarding is incomplete.  Once
    any primary provider/model transport state is present, it must describe
    the current-profile Codex lane and that profile must already have usable
    Codex auth.  The function is read-only and deliberately does not
    canonicalize hostile input: rejected writes must leave state byte-identical.
    """
    if not beta_provider_policy_active(environ):
        return
    if not isinstance(config, Mapping):
        raise BetaProviderPolicyError(
            "Realtor Beta configuration must be a mapping.",
            code="beta_config_invalid",
        )

    _validate_beta_runtime_config(config)
    _validate_beta_inference_config(config)
    _validate_beta_memory_config(config, environ=environ)

    for key in ("fallback_model", "fallback_providers"):
        value = config.get(key)
        if value not in (None, "", (), [], {}):
            raise BetaProviderPolicyError(
                "Realtor Beta does not allow cross-provider model fallback.",
                code="beta_fallback_not_allowed",
            )

    custom_providers = config.get("custom_providers")
    if custom_providers not in (None, "", (), [], {}):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow custom inference providers.",
            code="beta_custom_provider_not_allowed",
        )

    model_config = config.get("model")
    if model_config in (None, "", {}):
        return
    if not isinstance(model_config, Mapping):
        raise BetaProviderPolicyError(
            "Realtor Beta primary model configuration must include its Codex provider.",
            code="beta_model_configuration_incomplete",
        )

    provider = str(model_config.get("provider") or "").strip().lower()
    model = str(
        model_config.get("default")
        or model_config.get("model")
        or model_config.get("name")
        or ""
    ).strip()
    base_url = str(model_config.get("base_url") or "").strip().rstrip("/")
    api_mode = str(model_config.get("api_mode") or "").strip()
    api_key = str(model_config.get("api_key") or "").strip()
    key_env = str(model_config.get("key_env") or "").strip()

    if provider != BETA_ALLOWED_PROVIDER:
        if not provider:
            raise BetaProviderPolicyError(
                "Realtor Beta primary model configuration is missing its Codex provider.",
                code="beta_model_configuration_incomplete",
            )
        raise BetaProviderPolicyError(
            f"Realtor Beta does not allow configured provider {provider!r}.",
            code="beta_provider_not_allowed",
        )
    if model and model not in BETA_ALLOWED_MODELS:
        raise BetaProviderPolicyError(
            f"Realtor Beta does not allow configured model {model!r}.",
            code="beta_model_not_allowed",
        )
    if base_url and base_url != BETA_CODEX_BASE_URL.rstrip("/"):
        raise BetaProviderPolicyError(
            "Realtor Beta does not allow a custom primary-model endpoint.",
            code="beta_custom_endpoint_not_allowed",
        )
    if api_mode and api_mode != "codex_responses":
        raise BetaProviderPolicyError(
            "Realtor Beta primary inference must use the Codex Responses transport.",
            code="beta_api_mode_not_allowed",
        )
    if api_key or key_env:
        raise BetaProviderPolicyError(
            "Realtor Beta primary inference uses Beta-local Codex auth, not API keys.",
            code="beta_primary_api_key_not_allowed",
        )
    if not auth_status.get("logged_in"):
        raise BetaProviderPolicyError(
            "OpenAI Codex auth is required in the current Realtor Beta profile.",
            code="beta_codex_auth_required",
        )


def _jwt_expiry(access_token: str) -> float | None:
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + ("=" * (-len(parts[1]) % 4))
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    expiry = claims.get("exp") if isinstance(claims, dict) else None
    return float(expiry) if isinstance(expiry, (int, float)) else None


def _access_token_usable(value: Any, *, now: float) -> bool:
    token = str(value or "").strip()
    if not token:
        return False
    expiry = _jwt_expiry(token)
    return expiry is None or expiry > now


def read_beta_codex_auth_status(
    elevate_home: Path | str,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Purely inspect ``<current Beta home>/auth.json`` for usable Codex auth.

    The read has no locks with side effects, migrations, imports, token refresh,
    credential seeding, pool selection, network access, or writes.  Symlinks are
    rejected so a Beta profile cannot silently borrow another profile's store.
    """
    home = Path(elevate_home).expanduser()
    auth_path = home / "auth.json"
    result: dict[str, Any] = {
        "logged_in": False,
        "auth_store": str(auth_path),
        "source": None,
        "reason": "missing_auth_store",
    }
    try:
        if home.is_symlink():
            result["reason"] = "non_local_auth_store"
            return result
        if auth_path.is_symlink():
            result["reason"] = "non_local_auth_store"
            return result
        if not auth_path.is_file():
            return result
        if auth_path.resolve().parent != home.resolve():
            result["reason"] = "non_local_auth_store"
            return result
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result["reason"] = "invalid_auth_store"
        return result
    if not isinstance(payload, dict):
        result["reason"] = "invalid_auth_store"
        return result

    current_time = time.time() if now is None else float(now)
    # Deliberately do not accept credential_pool-only entries here.  The Beta
    # runtime skips pools to prevent imported/auto-seeded credentials from
    # bypassing the current profile's Codex provider state, so onboarding must
    # use the identical readiness rule and never advertise a false-ready state.
    providers = payload.get("providers")
    state = providers.get(BETA_ALLOWED_PROVIDER) if isinstance(providers, dict) else None
    tokens = state.get("tokens") if isinstance(state, dict) else None
    if isinstance(tokens, dict) and _access_token_usable(
        tokens.get("access_token"), now=current_time
    ) and str(tokens.get("refresh_token") or "").strip():
        result.update(logged_in=True, source="provider_state", reason=None)
        return result

    result["reason"] = "codex_auth_missing_or_expired"
    return result


def require_beta_codex_auth(elevate_home: Path | str) -> dict[str, Any]:
    """Return local Codex auth status or fail closed for Beta runtime use."""
    status = read_beta_codex_auth_status(elevate_home)
    if not status.get("logged_in"):
        raise BetaProviderPolicyError(
            "OpenAI Codex auth is required in the current Realtor Beta profile.",
            code="beta_codex_auth_required",
        )
    return status


def build_beta_primary_overlay(
    config: Mapping[str, Any] | None,
    auth_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the authoritative, public-safe primary item shown in Beta setup."""
    cfg = config if isinstance(config, Mapping) else {}
    model_cfg = cfg.get("model")
    model_cfg = model_cfg if isinstance(model_cfg, Mapping) else {}
    configured_provider = str(model_cfg.get("provider") or "").strip()
    configured_model = str(
        model_cfg.get("default") or model_cfg.get("model") or ""
    ).strip()

    blocked_reason: str | None = None
    if configured_provider and configured_provider != BETA_ALLOWED_PROVIDER:
        blocked_reason = "unsupported_beta_provider"
    elif configured_model and configured_model not in BETA_ALLOWED_MODELS:
        blocked_reason = "unsupported_beta_model"
    elif configured_model and not configured_provider:
        blocked_reason = "missing_beta_provider"

    selected_model = (
        configured_model
        if not blocked_reason and configured_model in BETA_ALLOWED_MODELS
        else BETA_DEFAULT_MODEL
    )
    auth_ready = bool(auth_status.get("logged_in"))
    ready = auth_ready and blocked_reason is None
    return {
        "status": "configured" if ready else "missing",
        "provider": BETA_ALLOWED_PROVIDER,
        "value": {
            "model": selected_model,
            "runtimeProvider": BETA_ALLOWED_PROVIDER,
            "apiKey": "",
            "secretPresent": auth_ready,
            "secretSource": "oauth" if auth_ready else None,
            "authReady": auth_ready,
            "authReason": auth_status.get("reason"),
            "policyVersion": BETA_PROVIDER_POLICY_VERSION,
            "allowedModelsVersion": BETA_ALLOWED_MODELS_VERSION,
            "policyBlocked": blocked_reason is not None,
            "blockedReason": blocked_reason,
            "configuredProvider": configured_provider,
            "configuredModel": configured_model,
        },
    }


def validate_beta_primary_item(
    item: Mapping[str, Any],
    auth_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and canonicalize one prospective Beta primary setup item."""
    value = item.get("value")
    value = dict(value) if isinstance(value, Mapping) else {}
    provider = str(item.get("provider") or "").strip()
    runtime_provider = str(value.get("runtimeProvider") or "").strip()

    # The current web form represents Codex OAuth as the display alias
    # ``openai`` plus the canonical runtimeProvider.  Accept that transport
    # shape, but never persist or materialize the alias.
    transport_alias = provider == "openai" and runtime_provider == BETA_ALLOWED_PROVIDER
    if provider != BETA_ALLOWED_PROVIDER and not transport_alias:
        raise BetaProviderPolicyError(
            "Realtor Beta supports only the OpenAI Codex provider.",
            code="beta_provider_not_allowed",
        )
    if runtime_provider and runtime_provider != BETA_ALLOWED_PROVIDER:
        raise BetaProviderPolicyError(
            "Realtor Beta primary runtime must be OpenAI Codex.",
            code="beta_runtime_provider_not_allowed",
        )

    model = str(value.get("model") or "").strip()
    if model not in BETA_ALLOWED_MODELS:
        raise BetaProviderPolicyError(
            f"Model {model or '(empty)'} is not allowed by the Realtor Beta policy.",
            code="beta_model_not_allowed",
        )
    if str(value.get("apiKey") or "").strip() or bool(value.get("usesEnvSecret")):
        raise BetaProviderPolicyError(
            "Realtor Beta primary inference uses Beta-local Codex auth, not API keys.",
            code="beta_primary_api_key_not_allowed",
        )
    if not auth_status.get("logged_in"):
        raise BetaProviderPolicyError(
            "Sign in to OpenAI Codex in this Beta profile before saving the primary model.",
            code="beta_codex_auth_required",
        )

    canonical = dict(item)
    canonical["status"] = "configured"
    canonical["provider"] = BETA_ALLOWED_PROVIDER
    canonical["value"] = {
        "model": model,
        "runtimeProvider": BETA_ALLOWED_PROVIDER,
        "apiKey": "",
        "usesEnvSecret": False,
    }
    return canonical
