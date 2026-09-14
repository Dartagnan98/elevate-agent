from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from elevate_cli.config import get_env_value, load_env, save_env_value


_AGENT_TELEGRAM_BOT_TOKEN_RE = re.compile(r"^ELEVATE_AGENT_([A-Z0-9_]+)_TELEGRAM_BOT_TOKEN$")
_TELEGRAM_BOT_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN"
_EXECUTIVE_TELEGRAM_CHANNEL_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL"


def _looks_like_telegram_bot_token(value: Any) -> bool:
    text = str(value or "").strip()
    if text.lower().startswith("telegram:"):
        text = text.split(":", 1)[1]
    return bool(_TELEGRAM_BOT_TOKEN_RE.fullmatch(text))


def _agent_segment_is_executive(segment: str) -> bool:
    return segment.strip().upper() == "EXECUTIVE_ASSISTANT"


def _executive_telegram_token() -> str:
    return str(
        get_env_value(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY)
        or get_env_value("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()


def _non_executive_duplicate_agent_token(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    for key, existing in load_env().items():
        match = _AGENT_TELEGRAM_BOT_TOKEN_RE.fullmatch(key)
        if not match or _agent_segment_is_executive(match.group(1)):
            continue
        if str(existing or "").strip() == candidate:
            return key
    return ""


def _reject_shared_agent_token(segment: str, value: str) -> None:
    executive_token = _executive_telegram_token()
    if executive_token and value.strip() == executive_token and not _agent_segment_is_executive(segment):
        raise HTTPException(
            status_code=400,
            detail=(
                "This token already belongs to the Executive Telegram bot. "
                "Create a separate bot token for this agent in BotFather."
            ),
        )


def _sync_executive_telegram_aliases(key: str, value: str) -> list[str]:
    """Keep legacy gateway Telegram keys and the Executive agent lane aligned."""
    old_shared_token = str(get_env_value("TELEGRAM_BOT_TOKEN") or "").strip()
    old_shared_channel = str(get_env_value("TELEGRAM_HOME_CHANNEL") or "").strip()
    old_executive_token = str(get_env_value(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY) or "").strip()
    old_executive_channel = str(get_env_value(_EXECUTIVE_TELEGRAM_CHANNEL_KEY) or "").strip()
    synced: list[str] = []

    if key == "TELEGRAM_BOT_TOKEN":
        if _non_executive_duplicate_agent_token(value):
            raise HTTPException(
                status_code=400,
                detail=(
                    "This token is already assigned to another agent. "
                    "Each non-Executive Telegram agent needs its own BotFather token."
                ),
            )
        if value and (not old_executive_token or old_executive_token == old_shared_token):
            save_env_value(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY, value)
            synced.append(_EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY)
    elif key == _EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY:
        if _non_executive_duplicate_agent_token(value):
            raise HTTPException(
                status_code=400,
                detail=(
                    "This token is already assigned to another agent. "
                    "Each non-Executive Telegram agent needs its own BotFather token."
                ),
            )
        if value and (not old_shared_token or old_shared_token == old_executive_token):
            save_env_value("TELEGRAM_BOT_TOKEN", value)
            synced.append("TELEGRAM_BOT_TOKEN")
    elif key == "TELEGRAM_HOME_CHANNEL":
        if value and (not old_executive_channel or old_executive_channel == old_shared_channel):
            save_env_value(_EXECUTIVE_TELEGRAM_CHANNEL_KEY, value)
            synced.append(_EXECUTIVE_TELEGRAM_CHANNEL_KEY)
    elif key == _EXECUTIVE_TELEGRAM_CHANNEL_KEY:
        if value and (not old_shared_channel or old_shared_channel == old_executive_channel):
            save_env_value("TELEGRAM_HOME_CHANNEL", value)
            synced.append("TELEGRAM_HOME_CHANNEL")

    return synced
