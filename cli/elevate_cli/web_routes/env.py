"""Environment variable routes for the dashboard."""

import logging
import re
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from elevate_cli.beta_env_policy import (
    beta_active_pack_env_metadata,
    beta_env_alias_group,
    beta_env_key_is_telegram,
    beta_env_key_allowed,
    beta_telegram_safety_updates,
    canonicalize_beta_env_value,
    enforce_beta_env_key,
    enforce_beta_env_store_local,
    enforce_beta_telegram_token_unique,
)
from elevate_cli.config import (
    OPTIONAL_ENV_VARS,
    load_env,
    remove_env_value,
    remove_env_values,
    save_env_value,
    save_env_values,
    redact_key,
)


RequireToken = Callable[[Request], None]
LooksLikeTelegramBotToken = Callable[[Any], bool]
RejectSharedAgentToken = Callable[[str, str], None]
SyncExecutiveTelegramAliases = Callable[[str, str], list[str]]

_AGENT_TELEGRAM_CHANNEL_RE = re.compile(r"^ELEVATE_AGENT_([A-Z0-9_]+)_TELEGRAM_CHANNEL$")
_AGENT_TELEGRAM_BOT_TOKEN_RE = re.compile(r"^ELEVATE_AGENT_([A-Z0-9_]+)_TELEGRAM_BOT_TOKEN$")
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30
_reveal_timestamps: list[float] = []


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


def create_env_router(
    *,
    require_token: RequireToken,
    looks_like_telegram_bot_token: LooksLikeTelegramBotToken,
    reject_shared_agent_token: RejectSharedAgentToken,
    sync_executive_telegram_aliases: SyncExecutiveTelegramAliases,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build routes for environment variable reads, writes, and reveal."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/env")
    async def get_env_vars():
        from elevate_cli.beta_provider_policy import beta_provider_policy_active

        realtor_beta = beta_provider_policy_active()
        if realtor_beta:
            enforce_beta_env_store_local()
        pack_metadata = beta_active_pack_env_metadata() if realtor_beta else {}
        if realtor_beta and not pack_metadata:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "beta_env_policy_unavailable",
                    "message": "Realtor Beta could not verify its unlocked account packs. Reopen the app and try again.",
                },
            )
        env_on_disk = load_env()
        result = {}
        for var_name, info in OPTIONAL_ENV_VARS.items():
            if realtor_beta and not beta_env_key_allowed(
                var_name,
                pack_metadata=pack_metadata,
            ):
                continue
            value = env_on_disk.get(var_name)
            result[var_name] = {
                "is_set": bool(value),
                "redacted_value": redact_key(value) if value else None,
                "description": info.get("description", ""),
                "url": info.get("url"),
                "category": info.get("category", ""),
                "is_password": info.get("password", False),
                "tools": info.get("tools", []),
                "advanced": info.get("advanced", False),
            }
        if realtor_beta:
            for var_name, info in pack_metadata.items():
                if var_name in result or not beta_env_key_allowed(
                    var_name,
                    pack_metadata=pack_metadata,
                ):
                    continue
                value = env_on_disk.get(var_name)
                result[var_name] = {
                    "is_set": bool(value),
                    "redacted_value": redact_key(value) if value else None,
                    **info,
                }
        for var_name, value in env_on_disk.items():
            if var_name in result:
                continue
            if realtor_beta:
                continue
            if not re.match(r"^ELEVATE_AGENT_[A-Z0-9_]+_TELEGRAM_(BOT_TOKEN|CHANNEL)$", var_name):
                continue
            is_token = var_name.endswith("_BOT_TOKEN")
            result[var_name] = {
                "is_set": bool(value),
                "redacted_value": redact_key(value) if value else None,
                "description": "Telegram bot token" if is_token else "Telegram chat or topic routed to this agent",
                "url": "https://t.me/BotFather" if is_token else None,
                "category": "messaging",
                "is_password": is_token,
                "tools": [],
                "advanced": False,
            }
        return result

    @router.put("/api/env")
    async def set_env_var(body: EnvVarUpdate):
        try:
            from elevate_cli.beta_provider_policy import beta_provider_policy_active

            key = str(body.key or "").strip()
            value = str(body.value or "").strip()
            realtor_beta = beta_provider_policy_active()
            if realtor_beta:
                enforce_beta_env_store_local()
                enforce_beta_env_key(key)
                value = canonicalize_beta_env_value(
                    key,
                    value,
                    looks_like_telegram_bot_token=looks_like_telegram_bot_token,
                )
            if key == "TELEGRAM_HOME_CHANNEL" and looks_like_telegram_bot_token(value):
                raise HTTPException(
                    status_code=400,
                    detail="That looks like a Telegram bot token. Paste it into the Bot token field, not the home chat field.",
                )
            channel_match = _AGENT_TELEGRAM_CHANNEL_RE.fullmatch(key)
            if channel_match and looks_like_telegram_bot_token(value):
                raise HTTPException(
                    status_code=400,
                    detail="That looks like a Telegram bot token. Paste it into the Bot token field, not the chat/topic field.",
                )
            token_match = _AGENT_TELEGRAM_BOT_TOKEN_RE.fullmatch(key)
            if token_match and not realtor_beta:
                reject_shared_agent_token(token_match.group(1), value)
            if realtor_beta:
                alias_group = beta_env_alias_group(key)
                env_on_disk = load_env()
                enforce_beta_telegram_token_unique(key, value, env_on_disk)
                updates = (
                    beta_telegram_safety_updates(env_on_disk)
                    if beta_env_key_is_telegram(key)
                    else {}
                )
                updates.update({alias_key: value for alias_key in alias_group})
                save_env_values(updates)
                synced = [alias_key for alias_key in alias_group if alias_key != key]
            else:
                synced = sync_executive_telegram_aliases(key, value)
                save_env_value(key, value)
            return {"ok": True, "key": key, "synced": synced}
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            _log.exception("PUT /api/env failed")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete("/api/env")
    async def remove_env_var(body: EnvVarDelete):
        try:
            from elevate_cli.beta_provider_policy import beta_provider_policy_active

            realtor_beta = beta_provider_policy_active()
            key = str(body.key or "").strip()
            if realtor_beta:
                enforce_beta_env_store_local()
                enforce_beta_env_key(key, allow_inactive_cleanup=True)
                alias_group = beta_env_alias_group(key)
                removed_keys = remove_env_values(alias_group)
                removed = bool(removed_keys)
            else:
                alias_group = (key,)
                removed_keys = [key] if remove_env_value(key) else []
                removed = bool(removed_keys)
            if not removed:
                raise HTTPException(status_code=404, detail=f"{key} not found in .env")
            return {
                "ok": True,
                "key": key,
                "synced": [removed_key for removed_key in removed_keys if removed_key != key],
            }
        except HTTPException:
            raise
        except Exception:
            _log.exception("DELETE /api/env failed")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post("/api/env/reveal")
    async def reveal_env_var(body: EnvVarReveal, request: Request):
        """Return the real value of a single env var after token and rate checks."""
        require_token(request)
        enforce_beta_env_store_local()
        enforce_beta_env_key(body.key)

        now = time.time()
        cutoff = now - _REVEAL_WINDOW_SECONDS
        _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
        if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
            raise HTTPException(status_code=429, detail="Too many reveal requests. Try again shortly.")
        _reveal_timestamps.append(now)

        env_on_disk = load_env()
        value = env_on_disk.get(body.key)
        if value is None:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")

        _log.info("env/reveal: %s", body.key)
        return {"key": body.key, "value": value}

    return router
