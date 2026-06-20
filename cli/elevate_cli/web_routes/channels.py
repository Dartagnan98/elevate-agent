"""Gateway and messaging-channel routes for the dashboard."""

import logging
import subprocess
from pathlib import Path
from typing import Any, Callable, List

from fastapi import APIRouter, Request

from elevate_cli.web_routes.channel_bluebubbles import register_bluebubbles_routes
from elevate_cli.web_routes.channel_discord import register_discord_routes
from elevate_cli.web_routes.channel_gateway import register_gateway_routes
from elevate_cli.web_routes.channel_slack import register_slack_routes
from elevate_cli.web_routes.channel_telegram import register_telegram_routes
from elevate_cli.web_routes.channel_whatsapp import register_whatsapp_routes


SpawnElevateAction = Callable[[List[str], str], subprocess.Popen]
RequireToken = Callable[[Request], None]
TelegramTokenValidator = Callable[[Any], bool]
TelegramAliasSync = Callable[[str, str], list[str]]


def _elevate_repo_root() -> Path:
    """Locate the repo root that holds ``scripts/whatsapp-bridge``."""
    # channels.py lives at <repo>/cli/elevate_cli/web_routes/channels.py
    return Path(__file__).resolve().parents[2]


def create_channels_router(
    *,
    log: logging.Logger | None = None,
    require_token: RequireToken,
    spawn_elevate_action: SpawnElevateAction,
    looks_like_telegram_bot_token: TelegramTokenValidator,
    sync_executive_telegram_aliases: TelegramAliasSync,
    elevate_repo_root_func: Callable[[], Path] = _elevate_repo_root,
) -> APIRouter:
    """Build routes for gateway controls and messaging channel setup."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    def _token_preview(token: str) -> str:
        """Mask all but the last 4 chars of a secret for safe display."""
        s = str(token or "")
        if len(s) <= 4:
            return "•" * len(s)
        return "•" * (len(s) - 4) + s[-4:]

    register_gateway_routes(router, log=_log, spawn_elevate_action=spawn_elevate_action)
    register_telegram_routes(
        router,
        log=_log,
        require_token=require_token,
        spawn_elevate_action=spawn_elevate_action,
        looks_like_telegram_bot_token=looks_like_telegram_bot_token,
        sync_executive_telegram_aliases=sync_executive_telegram_aliases,
        token_preview=_token_preview,
    )
    register_discord_routes(router, require_token=require_token, token_preview=_token_preview)
    register_slack_routes(router, require_token=require_token, token_preview=_token_preview)
    register_bluebubbles_routes(router, require_token=require_token)
    register_whatsapp_routes(
        router,
        require_token=require_token,
        elevate_repo_root_func=elevate_repo_root_func,
    )

    return router
