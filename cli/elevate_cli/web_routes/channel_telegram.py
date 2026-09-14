"""Telegram channel setup and pairing routes."""

import logging
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from elevate_cli.config import get_env_value, save_env_value

RequireToken = Callable[[Request], None]
SpawnElevateAction = Callable[[list[str], str], Any]
TelegramTokenValidator = Callable[[Any], bool]
TelegramAliasSync = Callable[[str, str], list[str]]
TokenPreview = Callable[[str], str]


def _strip(value: Any) -> str:
    return str(value or "").strip()


def register_telegram_routes(
    router: APIRouter,
    *,
    log: logging.Logger,
    require_token: RequireToken,
    spawn_elevate_action: SpawnElevateAction,
    looks_like_telegram_bot_token: TelegramTokenValidator,
    sync_executive_telegram_aliases: TelegramAliasSync,
    token_preview: TokenPreview,
) -> None:
    @router.post("/api/telegram/pair/start")
    async def start_telegram_pairing(request: Request):
        """Save bot token, switch unauthorized DMs to pairing, restart gateway."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        bot_token = str(body.get("bot_token") or "").strip()
        if not bot_token:
            raise HTTPException(status_code=400, detail="bot_token is required")
        if not looks_like_telegram_bot_token(bot_token):
            raise HTTPException(
                status_code=400,
                detail="Token doesn't match Telegram's BotFather format (<id>:<secret>)",
            )

        sync_executive_telegram_aliases("TELEGRAM_BOT_TOKEN", bot_token)
        save_env_value("TELEGRAM_BOT_TOKEN", bot_token)
        save_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", "pair")

        try:
            proc = spawn_elevate_action(["gateway", "restart"], "gateway-restart")
        except Exception as exc:
            log.exception("Failed to spawn gateway restart during telegram pair start")
            raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")

        return {
            "ok": True,
            "action": "gateway-restart",
            "pid": proc.pid,
        }

    @router.get("/api/telegram/pair/pending")
    async def list_telegram_pairings():
        """Return pending pairing codes plus already-approved users."""
        try:
            from gateway.pairing import PairingStore
            store = PairingStore()
            pending = store.list_pending("telegram")
            approved = store.list_approved("telegram")
        except Exception as exc:
            log.exception("Failed to list telegram pairings")
            raise HTTPException(status_code=500, detail=str(exc))
        return {"pending": pending, "approved": approved}

    @router.post("/api/telegram/pair/approve")
    async def approve_telegram_pairing(request: Request):
        """Approve a pairing code minted by the bot."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        code = str(body.get("code") or "").strip()
        set_home = bool(body.get("set_home"))
        if not code:
            raise HTTPException(status_code=400, detail="code is required")

        try:
            from gateway.pairing import PairingStore
            store = PairingStore()
            result = store.approve_code("telegram", code)
        except Exception as exc:
            log.exception("Failed to approve telegram pairing")
            raise HTTPException(status_code=500, detail=str(exc))
        if result is None:
            raise HTTPException(status_code=404, detail="Code not found or expired")

        user_id = str(result.get("user_id") or "").strip()
        user_name = str(result.get("user_name") or "").strip()

        if user_id:
            existing = str(get_env_value("TELEGRAM_ALLOWED_USERS") or "").strip()
            existing_ids = [v.strip() for v in existing.split(",") if v.strip()]
            if user_id not in existing_ids:
                existing_ids.append(user_id)
                save_env_value("TELEGRAM_ALLOWED_USERS", ",".join(existing_ids))
            save_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", "ignore")
            if set_home:
                sync_executive_telegram_aliases("TELEGRAM_HOME_CHANNEL", user_id)
                save_env_value("TELEGRAM_HOME_CHANNEL", user_id)

        return {
            "ok": True,
            "user_id": user_id,
            "user_name": user_name,
        }

    @router.get("/api/channels/telegram/status")
    async def telegram_status():
        """Return the currently-wired Telegram bot's identity + env config."""
        token = get_env_value("TELEGRAM_BOT_TOKEN") or ""
        if not token:
            return {
                "configured": False,
                "tokenPreview": "",
                "allowedUsers": "",
                "homeChannel": "",
                "dmBehavior": "",
                "allowAllUsers": False,
            }

        bot_info: dict[str, Any] = {}
        try:
            import json as _json
            import urllib.request as _ur

            req = _ur.Request(
                f"https://api.telegram.org/bot{token}/getMe",
                headers={"User-Agent": "elevate-wizard"},
            )
            with _ur.urlopen(req, timeout=5) as resp:
                payload = _json.loads(resp.read().decode("utf-8"))
            if payload.get("ok") and isinstance(payload.get("result"), dict):
                r = payload["result"]
                bot_info = {
                    "botId": r.get("id"),
                    "botUsername": r.get("username") or "",
                    "botName": (r.get("first_name") or "").strip(),
                    "canJoinGroups": bool(r.get("can_join_groups")),
                    "canReadAllGroupMessages": bool(r.get("can_read_all_group_messages")),
                }
        except Exception as exc:
            bot_info = {"error": str(exc)[:200]}

        return {
            "configured": True,
            "tokenPreview": token_preview(token),
            "allowedUsers": get_env_value("TELEGRAM_ALLOWED_USERS") or "",
            "homeChannel": get_env_value("TELEGRAM_HOME_CHANNEL") or "",
            "dmBehavior": get_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or "",
            "allowAllUsers": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").lower() == "true",
            **bot_info,
        }

    @router.post("/api/channels/telegram/configure")
    async def configure_telegram(request: Request):
        """Mirror ``setup._setup_telegram``."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        bot_token = _strip(body.get("bot_token"))
        allowed = _strip(body.get("allowed_users"))
        home = _strip(body.get("home_channel"))
        dm_behavior = _strip(body.get("dm_behavior")).lower()
        allow_all = bool(body.get("allow_all_users"))

        existing_token = get_env_value("TELEGRAM_BOT_TOKEN") or ""
        if bot_token:
            if not looks_like_telegram_bot_token(bot_token):
                raise HTTPException(
                    status_code=400,
                    detail="Token doesn't match Telegram's BotFather format (<id>:<secret>)",
                )
            sync_executive_telegram_aliases("TELEGRAM_BOT_TOKEN", bot_token)
            save_env_value("TELEGRAM_BOT_TOKEN", bot_token)
        elif not existing_token:
            raise HTTPException(status_code=400, detail="bot_token is required")

        # "allowed_users":"" is an explicit clear, "allowed_users": None is leave-as-is.
        if allowed is not None and body.get("allowed_users") is not None:
            save_env_value("TELEGRAM_ALLOWED_USERS", allowed.replace(" ", ""))
        if body.get("home_channel") is not None:
            _hc = (home or "").strip()
            if _hc and not (_hc.lstrip("-").isdigit() or _hc.startswith("@")):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "home_channel must be a numeric chat id or an @username — "
                        f"got {home!r} (looks like a pairing code, not a chat id)."
                    ),
                )
            save_env_value("TELEGRAM_HOME_CHANNEL", home)
        if dm_behavior:
            if dm_behavior not in {"pair", "ignore", "open"}:
                raise HTTPException(
                    status_code=400,
                    detail="dm_behavior must be one of: pair, ignore, open",
                )
            save_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR", dm_behavior)
        if allow_all:
            save_env_value("GATEWAY_ALLOW_ALL_USERS", "true")
        elif body.get("allow_all_users") is False:
            save_env_value("GATEWAY_ALLOW_ALL_USERS", "false")

        return {
            "ok": True,
            "tokenPreview": token_preview(bot_token or existing_token),
            "allowedUsers": get_env_value("TELEGRAM_ALLOWED_USERS") or "",
            "homeChannel": get_env_value("TELEGRAM_HOME_CHANNEL") or "",
            "dmBehavior": get_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or "",
            "allowAllUsers": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").lower() == "true",
        }
