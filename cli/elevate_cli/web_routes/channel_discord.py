"""Discord channel configuration routes."""

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from elevate_cli.config import get_env_value, save_env_value

RequireToken = Callable[[Request], None]
TokenPreview = Callable[[str], str]


def _strip(value: Any) -> str:
    return str(value or "").strip()


def register_discord_routes(
    router: APIRouter,
    *,
    require_token: RequireToken,
    token_preview: TokenPreview,
) -> None:
    @router.post("/api/channels/discord/configure")
    async def configure_discord(request: Request):
        """Mirror ``setup._setup_discord``."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        bot_token = _strip(body.get("bot_token"))
        allowed = _strip(body.get("allowed_users"))
        home_channel = _strip(body.get("home_channel"))
        if not bot_token and not get_env_value("DISCORD_BOT_TOKEN"):
            raise HTTPException(status_code=400, detail="bot_token is required")

        if bot_token:
            save_env_value("DISCORD_BOT_TOKEN", bot_token)
        if allowed:
            cleaned = []
            for uid in allowed.replace(" ", "").split(","):
                uid = uid.strip()
                if uid.startswith("<@") and uid.endswith(">"):
                    uid = uid.lstrip("<@!").rstrip(">")
                if uid.lower().startswith("user:"):
                    uid = uid[5:]
                if uid:
                    cleaned.append(uid)
            save_env_value("DISCORD_ALLOWED_USERS", ",".join(cleaned))
        if home_channel:
            save_env_value("DISCORD_HOME_CHANNEL", home_channel)
            # Legacy alias the agent-setup overlay reads.
            save_env_value("DISCORD_CHANNEL_ID", home_channel)

        return {
            "ok": True,
            "tokenPreview": token_preview(bot_token or get_env_value("DISCORD_BOT_TOKEN") or ""),
            "allowedUsers": get_env_value("DISCORD_ALLOWED_USERS") or "",
            "homeChannel": get_env_value("DISCORD_HOME_CHANNEL") or "",
        }
