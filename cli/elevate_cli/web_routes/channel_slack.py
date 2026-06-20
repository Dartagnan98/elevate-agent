"""Slack channel configuration routes."""

import os
from typing import Any, Callable

from fastapi import APIRouter, Body, HTTPException, Request

from elevate_cli.config import get_env_value, load_env, save_env_value

RequireToken = Callable[[Request], None]
TokenPreview = Callable[[str], str]


def _strip(value: Any) -> str:
    return str(value or "").strip()


def register_slack_routes(
    router: APIRouter,
    *,
    require_token: RequireToken,
    token_preview: TokenPreview,
) -> None:
    @router.post("/api/channels/slack/configure")
    async def configure_slack(request: Request):
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        bot_token = _strip(body.get("bot_token"))
        app_token = _strip(body.get("app_token"))
        allowed = _strip(body.get("allowed_users"))
        if not bot_token and not get_env_value("SLACK_BOT_TOKEN"):
            raise HTTPException(status_code=400, detail="bot_token (xoxb-…) is required")

        if bot_token:
            save_env_value("SLACK_BOT_TOKEN", bot_token)
        if app_token:
            save_env_value("SLACK_APP_TOKEN", app_token)
        if allowed:
            save_env_value("SLACK_ALLOWED_USERS", allowed.replace(" ", ""))

        return {
            "ok": True,
            "botTokenPreview": token_preview(bot_token or get_env_value("SLACK_BOT_TOKEN") or ""),
            "appTokenPreview": token_preview(app_token or get_env_value("SLACK_APP_TOKEN") or ""),
            "allowedUsers": get_env_value("SLACK_ALLOWED_USERS") or "",
        }

    @router.post("/api/channels/slack/test")
    def post_slack_test(payload: dict[str, Any] | None = Body(default=None)):
        import httpx

        body = payload or {}
        webhook = str(body.get("webhook_url") or "").strip()
        if not webhook:
            try:
                file_env = load_env() or {}
            except Exception:
                file_env = {}
            webhook = (
                os.environ.get("SLACK_WEBHOOK_URL")
                or file_env.get("SLACK_WEBHOOK_URL")
                or ""
            ).strip()
        if not webhook:
            return {
                "ok": False,
                "status": 0,
                "detail": "No webhook URL provided and SLACK_WEBHOOK_URL is not set.",
            }

        text = str(body.get("text") or "").strip() or "elevate · test message from onboarding wizard"
        channel = str(body.get("channel") or "").strip()
        msg: dict[str, Any] = {"text": text}
        if channel:
            msg["channel"] = channel if channel.startswith("#") or channel.startswith("@") else f"#{channel}"
        try:
            resp = httpx.post(webhook, json=msg, timeout=10)
        except httpx.HTTPError as exc:
            return {"ok": False, "status": 0, "detail": f"{type(exc).__name__}: {exc}"}
        body_text = (resp.text or "").strip()
        return {
            "ok": resp.is_success and body_text.lower() in ("ok", ""),
            "status": resp.status_code,
            "detail": body_text or "delivered",
        }
