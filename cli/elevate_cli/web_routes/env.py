"""Environment variable routes for the dashboard."""

import logging
import re
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from elevate_cli.config import (
    OPTIONAL_ENV_VARS,
    load_env,
    remove_env_value,
    save_env_value,
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
        env_on_disk = load_env()
        result = {}
        for var_name, info in OPTIONAL_ENV_VARS.items():
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
        for var_name, value in env_on_disk.items():
            if var_name in result:
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
            key = str(body.key or "").strip()
            value = str(body.value or "").strip()
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
            if token_match:
                reject_shared_agent_token(token_match.group(1), value)
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
            removed = remove_env_value(body.key)
            if not removed:
                raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
            return {"ok": True, "key": body.key}
        except HTTPException:
            raise
        except Exception:
            _log.exception("DELETE /api/env failed")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post("/api/env/reveal")
    async def reveal_env_var(body: EnvVarReveal, request: Request):
        """Return the real value of a single env var after token and rate checks."""
        require_token(request)

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
