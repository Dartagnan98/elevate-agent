"""Fail-closed credential and messaging policy for exact Realtor Beta."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Callable

from elevate_cli.beta_provider_policy import beta_provider_policy_active


_BETA_BLOCKED_ENV_KEYS = frozenset(
    {
        "BROWSER_USE_API_KEY",
        "BROWSER_USE_PROVIDER",
        "ELEVATE_BACKEND_URL",
        "ELEVATE_HOME",
        "ELEVATE_INFERENCE_PROVIDER",
        "ELEVATE_PROFILE",
        "ELEVATE_RELEASE_CHANNEL",
        "ELEVATE_UPDATE_CHANNEL",
        "EMBEDDINGS_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_EMBEDDING_MODEL",
        "OPENAI_MODEL",
    }
)
_BETA_BLOCKED_ENV_PREFIXES = (
    "API_SERVER_",
    "GATEWAY_PROXY_",
    "WEBHOOK_",
)
_BETA_BLOCKED_ENV_SUFFIXES = ("_ALLOW_ALL_USERS",)
_BETA_EXCLUDED_PACK_ITEMS = frozenset(
    {
        "browser_use_tools",
        "memory_embeddings",
        "model_provider",
        "update_channel",
    }
)
_BETA_EXECUTIVE_TELEGRAM_ALIAS_GROUPS = (
    (
        "TELEGRAM_BOT_TOKEN",
        "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN",
    ),
    (
        "TELEGRAM_HOME_CHANNEL",
        "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL",
    ),
)
_TELEGRAM_AGENT_TOKEN_RE = re.compile(
    r"^ELEVATE_AGENT_([A-Z0-9_]+)_TELEGRAM_BOT_TOKEN$"
)
_TELEGRAM_AGENT_CHANNEL_RE = re.compile(
    r"^ELEVATE_AGENT_[A-Z0-9_]+_TELEGRAM_CHANNEL$"
)
_TELEGRAM_TARGET_RE = re.compile(
    r"^(?:telegram:)?(?:-?\d+|@[A-Za-z][A-Za-z0-9_]{4,31})(?::\d+)?$",
    re.IGNORECASE,
)
_BETA_TELEGRAM_CLOSED_ACCESS_ENV = {
    "GATEWAY_ALLOW_ALL_USERS": "false",
    "GATEWAY_ALLOWED_USERS": "",
    "TELEGRAM_ALLOW_ALL_USERS": "false",
    "TELEGRAM_GROUP_ALLOWED_USERS": "",
}


def _beta_policy_error(code: str, message: str) -> Exception:
    # FastAPI belongs to the optional web surface.  Gateway config imports
    # this policy for pack metadata and must remain usable in the lean CLI
    # environment where FastAPI is intentionally absent.
    from fastapi import HTTPException

    return HTTPException(status_code=409, detail={"code": code, "message": message})


def beta_active_pack_env_metadata() -> dict[str, dict[str, Any]]:
    """Return credentials declared by currently active signed pack contracts."""
    if not beta_provider_policy_active():
        return {}
    try:
        from elevate_cli.access import is_entitlement_active, load_access_config
        from elevate_cli.data.pack_onboarding import PACK_SPECS

        access = load_access_config()
        if not isinstance(access, Mapping):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for pack in PACK_SPECS:
            if not is_entitlement_active(pack.entitlement, dict(access)):
                continue
            for item in pack.items:
                if item.key in _BETA_EXCLUDED_PACK_ITEMS:
                    continue
                for env_key in item.env_keys:
                    result.setdefault(
                        env_key,
                        {
                            "description": f"{pack.label}: {item.label}. {item.description}",
                            "url": None,
                            "category": (
                                "messaging"
                                if item.category == "communication"
                                else "account"
                            ),
                            "is_password": env_key.endswith(
                                ("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET", "_PASS")
                            ),
                            "tools": [],
                            "advanced": False,
                        },
                    )
        return result
    except Exception:
        # Access/pack discovery is authorization logic and must fail closed.
        return {}


def beta_known_pack_env_metadata() -> dict[str, dict[str, Any]]:
    """Return every credential declared by a shipped Beta pack contract.

    This broader roster is used only for safe cleanup after a pack is locked or
    revoked. It must never authorize writes, reveals, or runtime activation.
    """
    if not beta_provider_policy_active():
        return {}
    try:
        from elevate_cli.data.pack_onboarding import PACK_SPECS

        result: dict[str, dict[str, Any]] = {}
        for pack in PACK_SPECS:
            for item in pack.items:
                if item.key in _BETA_EXCLUDED_PACK_ITEMS:
                    continue
                for env_key in item.env_keys:
                    result.setdefault(env_key, {})
        return result
    except Exception:
        return {}


def beta_env_key_allowed(
    key: object,
    *,
    pack_metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Whether exact Beta may display, write, remove, or reveal one env key."""
    raw = str(key or "").strip()
    text = raw.upper()
    if raw != text:
        return False
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", text):
        return False
    if text in _BETA_BLOCKED_ENV_KEYS:
        return False
    if text.startswith(_BETA_BLOCKED_ENV_PREFIXES):
        return False
    if text.endswith(_BETA_BLOCKED_ENV_SUFFIXES):
        return False
    allowed = (
        pack_metadata
        if pack_metadata is not None
        else beta_active_pack_env_metadata()
    )
    return text in allowed


def enforce_beta_env_key(key: object, *, allow_inactive_cleanup: bool = False) -> None:
    """Reject a credential name outside the active exact-Beta pack contract."""
    allowed = (
        beta_env_key_allowed(key, pack_metadata=beta_known_pack_env_metadata())
        if allow_inactive_cleanup
        else beta_env_key_allowed(key)
    )
    if not beta_provider_policy_active() or allowed:
        return
    raise _beta_policy_error(
        "beta_env_key_not_allowed",
        (
            "That credential or runtime setting is not available in this Realtor "
            "Beta profile. Configure an unlocked realtor account from onboarding."
        ),
    )


def enforce_beta_env_store_local() -> None:
    """Reject managed, symlinked, or cross-profile exact-Beta env stores."""
    if not beta_provider_policy_active():
        return
    try:
        from elevate_cli.config import get_elevate_home, get_env_path, is_managed
    except Exception as exc:
        raise _beta_policy_error(
            "beta_env_store_unavailable",
            "Realtor Beta could not verify its local credential store. Reopen the app and try again.",
        ) from exc

    try:
        managed = is_managed()
    except Exception as exc:
        raise _beta_policy_error(
            "beta_env_store_unavailable",
            "Realtor Beta could not verify its local credential store. Reopen the app and try again.",
        ) from exc

    if managed:
        raise _beta_policy_error(
            "beta_env_store_managed",
            "This managed Realtor Beta profile must receive credentials from its deployment configuration.",
        )

    try:
        home = get_elevate_home().expanduser()
        env_path = get_env_path().expanduser()
        unsafe = home.is_symlink() or env_path.is_symlink()
        if home.exists() and not home.is_dir():
            unsafe = True
        if env_path.exists():
            unsafe = unsafe or not env_path.is_file()
            unsafe = unsafe or env_path.resolve().parent != home.resolve()
            unsafe = unsafe or env_path.stat().st_nlink != 1
    except Exception as exc:
        raise _beta_policy_error(
            "beta_env_store_unavailable",
            "Realtor Beta could not verify its local credential store. Reopen the app and try again.",
        ) from exc
    if unsafe:
        raise _beta_policy_error(
            "beta_env_store_not_local",
            "Realtor Beta will not read or modify a linked credential store. Reopen the local Beta profile.",
        )


def _reject_unsafe_env_value_expansion(value: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        safe = False
    else:
        from elevate_cli.config import _sanitize_env_lines

        candidate = f"TELEGRAM_BOT_TOKEN={value}\n"
        safe = _sanitize_env_lines([candidate]) == [candidate]
    if not safe:
        raise _beta_policy_error(
            "beta_env_value_not_allowed",
            (
                "That credential contains text that could be interpreted as another "
                "runtime setting. Copy only the credential value and try again."
            ),
        )


def canonicalize_beta_env_value(
    key: str,
    value: str,
    *,
    looks_like_telegram_bot_token: Callable[[Any], bool],
    allow_empty: bool = False,
) -> str:
    """Validate exact-Beta env values using the runtime's accepted formats."""
    if not beta_provider_policy_active():
        return value
    _reject_unsafe_env_value_expansion(value)
    text = str(value or "").strip()
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _beta_policy_error(
            "beta_env_value_non_ascii",
            "That credential contains unsupported characters. Copy the original account value and try again.",
        ) from exc

    if allow_empty and not text:
        return ""

    if key == "TELEGRAM_ALLOWED_USERS":
        values = [part.strip() for part in text.split(",") if part.strip()]
        if not values or any(not re.fullmatch(r"\d{1,20}", part) for part in values):
            raise _beta_policy_error(
                "beta_telegram_allowlist_invalid",
                "Enter one or more numeric Telegram user IDs. Wildcards are not allowed in Realtor Beta.",
            )
        return ",".join(dict.fromkeys(values))

    if key == "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR":
        normalized = text.lower()
        if normalized not in {"pair", "ignore"}:
            raise _beta_policy_error(
                "beta_telegram_dm_policy_invalid",
                "Realtor Beta supports only pairing or ignoring unknown Telegram users.",
            )
        return normalized

    if key == "TELEGRAM_BOT_TOKEN" or _TELEGRAM_AGENT_TOKEN_RE.fullmatch(key):
        normalized_token = text
        if normalized_token.lower().startswith("telegram:"):
            normalized_token = normalized_token.split(":", 1)[1]
        if not normalized_token or not looks_like_telegram_bot_token(
            normalized_token
        ):
            raise _beta_policy_error(
                "beta_telegram_token_invalid",
                "That bot token does not match Telegram's BotFather format.",
            )
        return normalized_token

    if key == "TELEGRAM_HOME_CHANNEL" or _TELEGRAM_AGENT_CHANNEL_RE.fullmatch(key):
        if not text or not _TELEGRAM_TARGET_RE.fullmatch(text):
            raise _beta_policy_error(
                "beta_telegram_target_invalid",
                "Enter a numeric Telegram chat ID, @username, or chat ID with a numeric topic ID.",
            )
        return text

    if not text:
        raise _beta_policy_error(
            "beta_env_value_required",
            "Enter the account value before saving this Realtor Beta setting.",
        )
    if text[0] in {"\"", "'"} or text[-1] in {"\"", "'"}:
        raise _beta_policy_error(
            "beta_env_value_not_allowed",
            "That account value begins or ends with a quote. Copy the value itself without surrounding quotation marks.",
        )
    return text


def beta_env_alias_group(key: str) -> tuple[str, ...]:
    """Return the exact-Beta shared/Executive Telegram fields updated together."""
    for group in _BETA_EXECUTIVE_TELEGRAM_ALIAS_GROUPS:
        if key in group:
            return group
    return (key,)


def beta_env_key_is_telegram(key: str) -> bool:
    """Return whether a pack credential participates in Beta Telegram setup."""
    return key in {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR",
        "TELEGRAM_HOME_CHANNEL",
    } or bool(
        _TELEGRAM_AGENT_TOKEN_RE.fullmatch(key)
        or _TELEGRAM_AGENT_CHANNEL_RE.fullmatch(key)
    )


def beta_telegram_safety_updates(
    env_values: Mapping[str, Any],
) -> dict[str, str]:
    """Return the closed remote-access state persisted with every Beta setup."""
    updates = dict(_BETA_TELEGRAM_CLOSED_ACCESS_ENV)
    raw_allowed = str(env_values.get("TELEGRAM_ALLOWED_USERS") or "").strip()
    allowed = [part.strip() for part in raw_allowed.split(",") if part.strip()]
    updates["TELEGRAM_ALLOWED_USERS"] = (
        ",".join(dict.fromkeys(allowed))
        if allowed and all(re.fullmatch(r"\d{1,20}", part) for part in allowed)
        else ""
    )
    dm_behavior = str(
        env_values.get("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or ""
    ).strip().lower()
    updates["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] = (
        dm_behavior if dm_behavior in {"pair", "ignore"} else "pair"
    )
    return updates


def beta_telegram_unsafe_access_sources(
    *env_sources: Mapping[str, Any],
) -> list[str]:
    """Name stale open-access settings without exposing their values."""
    unsafe: set[str] = set()
    for env_values in env_sources:
        for key in ("GATEWAY_ALLOW_ALL_USERS", "TELEGRAM_ALLOW_ALL_USERS"):
            if str(env_values.get(key) or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }:
                unsafe.add(key)
        for key in ("GATEWAY_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_USERS"):
            if str(env_values.get(key) or "").strip():
                unsafe.add(key)
        raw_allowed = str(env_values.get("TELEGRAM_ALLOWED_USERS") or "").strip()
        allowed = [part.strip() for part in raw_allowed.split(",") if part.strip()]
        if allowed and any(not re.fullmatch(r"\d{1,20}", part) for part in allowed):
            unsafe.add("TELEGRAM_ALLOWED_USERS")
        dm_behavior = str(
            env_values.get("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or ""
        ).strip().lower()
        if dm_behavior and dm_behavior not in {"pair", "ignore"}:
            unsafe.add("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR")
    return sorted(unsafe)


def _beta_telegram_token_lane(key: str) -> str | None:
    if key in {
        "TELEGRAM_BOT_TOKEN",
        "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN",
    }:
        return "EXECUTIVE_ASSISTANT"
    match = _TELEGRAM_AGENT_TOKEN_RE.fullmatch(key)
    return match.group(1) if match else None


def enforce_beta_telegram_token_unique(
    key: str,
    value: str,
    env_values: Mapping[str, Any],
) -> None:
    """Prevent one BotFather identity from authorizing two Beta agent lanes."""
    if not beta_provider_policy_active():
        return
    lane = _beta_telegram_token_lane(key)
    candidate = str(value or "").strip()
    if lane is None or not candidate:
        return
    for existing_key, existing_value in env_values.items():
        existing_lane = _beta_telegram_token_lane(str(existing_key))
        if (
            existing_lane is not None
            and existing_lane != lane
            and str(existing_value or "").strip() == candidate
        ):
            raise _beta_policy_error(
                "beta_telegram_token_reused",
                "That Telegram bot already belongs to another Realtor Beta agent. Create a separate bot in BotFather.",
            )


def reject_unsupported_beta_channel(channel: str) -> None:
    """Keep exact Realtor Beta on its signed Telegram messaging lane."""
    normalized = channel.strip().lower()
    if not beta_provider_policy_active() or normalized == "telegram":
        return
    label = {
        "imessage": "iMessage",
        "whatsapp": "WhatsApp",
    }.get(normalized, normalized.title())
    raise _beta_policy_error(
        "beta_channel_not_available",
        f"{label} setup is not available in this Realtor Beta. Use the Telegram approval lane.",
    )
