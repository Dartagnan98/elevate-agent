"""Telegram channel setup and pairing routes."""

import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from elevate_cli.beta_env_policy import (
    beta_env_alias_group,
    beta_telegram_safety_updates,
    beta_telegram_unsafe_access_sources,
    canonicalize_beta_env_value,
    enforce_beta_env_key,
    enforce_beta_env_store_local,
    enforce_beta_telegram_token_unique,
)
from elevate_cli.beta_provider_policy import beta_provider_policy_active
from elevate_cli.config import get_env_value, load_env, save_env_value, save_env_values

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
    def require_telegram_runtime_available() -> None:
        """Keep exact Beta messaging setup honest while its gateway is disabled."""
        if not beta_provider_policy_active():
            return
        raise HTTPException(
            status_code=409,
            detail={
                "code": "beta_messaging_runtime_unavailable",
                "message": (
                    "Telegram pairing is not enabled in this Realtor Beta build. "
                    "Use in-app chat while the messaging runtime is being hardened."
                ),
                "configurationSaved": False,
                "restartStarted": False,
            },
        )

    def telegram_env_value(key: str) -> str:
        if beta_provider_policy_active():
            return str(load_env().get(key) or "")
        return str(get_env_value(key) or "")

    def save_telegram_values(
        updates: dict[str, str],
        *,
        allow_empty_keys: set[str] | None = None,
        stable_alias_keys: set[str] | None = None,
    ) -> None:
        """Persist one Telegram update, atomically in exact Realtor Beta."""
        if not beta_provider_policy_active():
            aliases = stable_alias_keys or set()
            for key, value in updates.items():
                if key in aliases:
                    sync_executive_telegram_aliases(key, value)
                save_env_value(key, value)
            return

        enforce_beta_env_store_local()
        allow_empty = allow_empty_keys or set()
        env_on_disk = load_env()
        expanded = beta_telegram_safety_updates(env_on_disk)
        for key, raw_value in updates.items():
            if key == "GATEWAY_ALLOW_ALL_USERS":
                if raw_value != "false":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "beta_allow_all_not_allowed",
                            "message": "Realtor Beta never allows every remote user.",
                        },
                    )
                expanded[key] = "false"
                continue
            enforce_beta_env_key(key)
            value = canonicalize_beta_env_value(
                key,
                raw_value,
                looks_like_telegram_bot_token=looks_like_telegram_bot_token,
                allow_empty=key in allow_empty,
            )
            enforce_beta_telegram_token_unique(key, value, env_on_disk)
            for alias_key in beta_env_alias_group(key):
                expanded[alias_key] = value
        save_env_values(expanded)

    @router.post("/api/telegram/pair/start")
    async def start_telegram_pairing(request: Request):
        """Save bot token, switch unauthorized DMs to pairing, restart gateway."""
        require_token(request)
        require_telegram_runtime_available()
        try:
            body = await request.json()
        except Exception:
            body = {}
        bot_token = str(body.get("bot_token") or "").strip()
        if not bot_token:
            raise HTTPException(status_code=400, detail="bot_token is required")
        if (
            not beta_provider_policy_active()
            and not looks_like_telegram_bot_token(bot_token)
        ):
            raise HTTPException(
                status_code=400,
                detail="Token doesn't match Telegram's BotFather format (<id>:<secret>)",
            )

        save_telegram_values(
            {
                "TELEGRAM_BOT_TOKEN": bot_token,
                "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR": "pair",
            },
            stable_alias_keys={"TELEGRAM_BOT_TOKEN"},
        )

        try:
            proc = spawn_elevate_action(["gateway", "restart"], "gateway-restart")
        except Exception as exc:
            log.exception("Failed to spawn gateway restart during telegram pair start")
            if beta_provider_policy_active():
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "beta_gateway_restart_not_started",
                        "message": (
                            "Telegram was saved securely, but the agent restart did not start. "
                            "Retry the connection to start it."
                        ),
                        "configurationSaved": True,
                        "restartStarted": False,
                    },
                )
            raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")

        return {
            "ok": True,
            "action": "gateway-restart",
            "pid": proc.pid,
        }

    @router.get("/api/telegram/pair/pending")
    async def list_telegram_pairings():
        """Return pending pairing codes plus already-approved users."""
        enforce_beta_env_store_local()
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
        require_telegram_runtime_available()
        try:
            body = await request.json()
        except Exception:
            body = {}
        code = str(body.get("code") or "").strip()
        set_home = bool(body.get("set_home"))
        if not code:
            raise HTTPException(status_code=400, detail="code is required")
        enforce_beta_env_store_local()

        authorization_saved = False

        def save_pairing_authorization(result: dict[str, Any]) -> None:
            nonlocal authorization_saved
            user_id = canonicalize_beta_env_value(
                "TELEGRAM_ALLOWED_USERS",
                str(result.get("user_id") or ""),
                looks_like_telegram_bot_token=looks_like_telegram_bot_token,
            )
            existing = telegram_env_value("TELEGRAM_ALLOWED_USERS").strip()
            existing_ids = [v.strip() for v in existing.split(",") if v.strip()]
            updates: dict[str, str] = {}
            if user_id not in existing_ids:
                existing_ids.append(user_id)
                updates["TELEGRAM_ALLOWED_USERS"] = ",".join(existing_ids)
            updates["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] = "ignore"
            if set_home:
                updates["TELEGRAM_HOME_CHANNEL"] = user_id
            save_telegram_values(
                updates,
                stable_alias_keys={"TELEGRAM_HOME_CHANNEL"},
            )
            authorization_saved = True

        try:
            from gateway.pairing import PairingStore
            store = PairingStore()
            if beta_provider_policy_active():
                result = store.approve_code(
                    "telegram",
                    code,
                    before_commit=save_pairing_authorization,
                )
            else:
                result = store.approve_code("telegram", code)
        except Exception as exc:
            log.exception("Failed to approve telegram pairing")
            if beta_provider_policy_active() and authorization_saved:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "beta_pairing_record_not_saved",
                        "message": (
                            "The user is authorized, but Elevate could not finish recording "
                            "the pairing. Retry to reconcile the record."
                        ),
                        "authorizationSaved": True,
                        "pairingRecorded": False,
                    },
                )
            if beta_provider_policy_active():
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "beta_pairing_authorization_not_saved",
                        "message": (
                            "Elevate could not authorize this user. The pairing code was not "
                            "consumed; fix the local profile and retry."
                        ),
                        "authorizationSaved": False,
                        "pairingRecorded": False,
                        "retryable": True,
                    },
                )
            raise HTTPException(status_code=500, detail=str(exc))
        if result is None:
            raise HTTPException(status_code=404, detail="Code not found or expired")

        user_id = str(result.get("user_id") or "").strip()
        user_name = str(result.get("user_name") or "").strip()

        if user_id and not beta_provider_policy_active():
            existing = telegram_env_value("TELEGRAM_ALLOWED_USERS").strip()
            existing_ids = [v.strip() for v in existing.split(",") if v.strip()]
            updates: dict[str, str] = {}
            if user_id not in existing_ids:
                existing_ids.append(user_id)
                updates["TELEGRAM_ALLOWED_USERS"] = ",".join(existing_ids)
            updates["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] = "ignore"
            if set_home:
                updates["TELEGRAM_HOME_CHANNEL"] = user_id
            save_telegram_values(
                updates,
                stable_alias_keys={"TELEGRAM_HOME_CHANNEL"},
            )

        return {
            "ok": True,
            "user_id": user_id,
            "user_name": user_name,
        }

    @router.get("/api/channels/telegram/status")
    async def telegram_status():
        """Return the currently-wired Telegram bot's identity + env config."""
        enforce_beta_env_store_local()
        unsafe_access_sources = (
            beta_telegram_unsafe_access_sources(load_env(), os.environ)
            if beta_provider_policy_active()
            else []
        )
        token = telegram_env_value("TELEGRAM_BOT_TOKEN")
        if not token:
            status = {
                "configured": False,
                "tokenPreview": "",
                "allowedUsers": "",
                "homeChannel": "",
                "dmBehavior": "",
                "allowAllUsers": bool(unsafe_access_sources),
            }
            if beta_provider_policy_active():
                status["unsafeAccessSources"] = unsafe_access_sources
            return status

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

        status = {
            "configured": True,
            "tokenPreview": token_preview(token),
            "allowedUsers": telegram_env_value("TELEGRAM_ALLOWED_USERS"),
            "homeChannel": telegram_env_value("TELEGRAM_HOME_CHANNEL"),
            "dmBehavior": telegram_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"),
            "allowAllUsers": bool(unsafe_access_sources)
            if beta_provider_policy_active()
            else telegram_env_value("GATEWAY_ALLOW_ALL_USERS").lower() == "true",
            **bot_info,
        }
        if beta_provider_policy_active():
            status["unsafeAccessSources"] = unsafe_access_sources
        return status

    @router.post("/api/channels/telegram/configure")
    async def configure_telegram(request: Request):
        """Mirror ``setup._setup_telegram``."""
        require_token(request)
        require_telegram_runtime_available()
        try:
            body = await request.json()
        except Exception:
            body = {}
        bot_token = _strip(body.get("bot_token"))
        allowed = _strip(body.get("allowed_users"))
        home = _strip(body.get("home_channel"))
        dm_behavior = _strip(body.get("dm_behavior")).lower()
        allow_all = bool(body.get("allow_all_users"))

        enforce_beta_env_store_local()
        if beta_provider_policy_active() and allow_all:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "beta_allow_all_not_allowed",
                    "message": "Realtor Beta never allows every remote user.",
                },
            )

        existing_token = telegram_env_value("TELEGRAM_BOT_TOKEN")
        updates: dict[str, str] = {}
        allow_empty_keys: set[str] = set()
        if bot_token:
            if (
                not beta_provider_policy_active()
                and not looks_like_telegram_bot_token(bot_token)
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Token doesn't match Telegram's BotFather format (<id>:<secret>)",
                )
            updates["TELEGRAM_BOT_TOKEN"] = bot_token
        elif not existing_token:
            raise HTTPException(status_code=400, detail="bot_token is required")

        # "allowed_users":"" is an explicit clear, "allowed_users": None is leave-as-is.
        if allowed is not None and body.get("allowed_users") is not None:
            updates["TELEGRAM_ALLOWED_USERS"] = allowed.replace(" ", "")
            allow_empty_keys.add("TELEGRAM_ALLOWED_USERS")
        if body.get("home_channel") is not None:
            _hc = (home or "").strip()
            if (
                not beta_provider_policy_active()
                and _hc
                and not (_hc.lstrip("-").isdigit() or _hc.startswith("@"))
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "home_channel must be a numeric chat id or an @username — "
                        f"got {home!r} (looks like a pairing code, not a chat id)."
                    ),
                )
            updates["TELEGRAM_HOME_CHANNEL"] = home
            allow_empty_keys.add("TELEGRAM_HOME_CHANNEL")
        if dm_behavior:
            if (
                not beta_provider_policy_active()
                and dm_behavior not in {"pair", "ignore", "open"}
            ):
                raise HTTPException(
                    status_code=400,
                    detail="dm_behavior must be one of: ignore, open, pair",
                )
            updates["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] = dm_behavior
        if beta_provider_policy_active():
            updates["GATEWAY_ALLOW_ALL_USERS"] = "false"
        elif allow_all:
            updates["GATEWAY_ALLOW_ALL_USERS"] = "true"
        elif body.get("allow_all_users") is False:
            updates["GATEWAY_ALLOW_ALL_USERS"] = "false"

        save_telegram_values(
            updates,
            allow_empty_keys=allow_empty_keys,
            stable_alias_keys={"TELEGRAM_BOT_TOKEN"},
        )

        return {
            "ok": True,
            "tokenPreview": token_preview(bot_token or existing_token),
            "allowedUsers": telegram_env_value("TELEGRAM_ALLOWED_USERS"),
            "homeChannel": telegram_env_value("TELEGRAM_HOME_CHANNEL"),
            "dmBehavior": telegram_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"),
            "allowAllUsers": telegram_env_value("GATEWAY_ALLOW_ALL_USERS").lower() == "true",
        }
