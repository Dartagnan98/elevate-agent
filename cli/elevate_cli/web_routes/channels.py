"""Gateway and messaging-channel routes for the dashboard."""

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, List

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from elevate_cli.config import get_env_value, load_config, load_env, save_env_value
from elevate_cli.web_routes.channel_gateway import register_gateway_routes


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

    def _strip(v: Any) -> str:
        return str(v or "").strip()

    def _token_preview(token: str) -> str:
        """Mask all but the last 4 chars of a secret for safe display."""
        s = str(token or "")
        if len(s) <= 4:
            return "•" * len(s)
        return "•" * (len(s) - 4) + s[-4:]

    def _whatsapp_enabled() -> bool:
        env_value = (get_env_value("WHATSAPP_ENABLED") or "").strip().lower()
        if env_value in {"true", "1", "yes"}:
            return True
        try:
            platforms = load_config().get("platforms", {})
            whatsapp = platforms.get("whatsapp", {}) if isinstance(platforms, dict) else {}
            if not isinstance(whatsapp, dict):
                return False
            enabled = whatsapp.get("enabled")
            if isinstance(enabled, str):
                return enabled.strip().lower() in {"true", "1", "yes"}
            return bool(enabled)
        except Exception:
            return False

    register_gateway_routes(router, log=_log, spawn_elevate_action=spawn_elevate_action)

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
            _log.exception("Failed to spawn gateway restart during telegram pair start")
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
            _log.exception("Failed to list telegram pairings")
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
            _log.exception("Failed to approve telegram pairing")
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
            "tokenPreview": _token_preview(token),
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
            "tokenPreview": _token_preview(bot_token or existing_token),
            "allowedUsers": get_env_value("TELEGRAM_ALLOWED_USERS") or "",
            "homeChannel": get_env_value("TELEGRAM_HOME_CHANNEL") or "",
            "dmBehavior": get_env_value("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or "",
            "allowAllUsers": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").lower() == "true",
        }

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
            "tokenPreview": _token_preview(bot_token or get_env_value("DISCORD_BOT_TOKEN") or ""),
            "allowedUsers": get_env_value("DISCORD_ALLOWED_USERS") or "",
            "homeChannel": get_env_value("DISCORD_HOME_CHANNEL") or "",
        }

    @router.post("/api/channels/slack/configure")
    async def configure_slack(request: Request):
        """Mirror ``setup._setup_slack``."""
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
            "botTokenPreview": _token_preview(bot_token or get_env_value("SLACK_BOT_TOKEN") or ""),
            "appTokenPreview": _token_preview(app_token or get_env_value("SLACK_APP_TOKEN") or ""),
            "allowedUsers": get_env_value("SLACK_ALLOWED_USERS") or "",
        }

    @router.post("/api/channels/slack/test")
    def post_slack_test(payload: dict[str, Any] | None = Body(default=None)):
        """Send a one-shot test message to a Slack incoming webhook."""
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

    @router.post("/api/channels/imessage/bluebubbles/configure")
    async def configure_bluebubbles(request: Request):
        """Mirror ``setup._setup_bluebubbles``."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        server_url = _strip(body.get("server_url")).rstrip("/")
        password = _strip(body.get("password"))
        allowed = _strip(body.get("allowed_users"))
        home = _strip(body.get("home_channel"))

        if server_url:
            save_env_value("BLUEBUBBLES_SERVER_URL", server_url)
        if password:
            save_env_value("BLUEBUBBLES_PASSWORD", password)
        if allowed:
            save_env_value("BLUEBUBBLES_ALLOWED_USERS", allowed.replace(" ", ""))
        if home:
            save_env_value("BLUEBUBBLES_HOME_CHANNEL", home)

        if not get_env_value("BLUEBUBBLES_SERVER_URL") or not get_env_value("BLUEBUBBLES_PASSWORD"):
            raise HTTPException(
                status_code=400,
                detail="BlueBubbles server URL + password are required",
            )

        return {
            "ok": True,
            "serverUrl": get_env_value("BLUEBUBBLES_SERVER_URL") or "",
            "passwordSet": bool(get_env_value("BLUEBUBBLES_PASSWORD")),
            "allowedUsers": get_env_value("BLUEBUBBLES_ALLOWED_USERS") or "",
            "homeChannel": get_env_value("BLUEBUBBLES_HOME_CHANNEL") or "",
        }

    @router.post("/api/channels/whatsapp/configure")
    async def configure_whatsapp(request: Request):
        """Save WhatsApp mode + allowlist. Pairing streams separately."""
        require_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        mode = _strip(body.get("mode"))  # "bot" or "self-chat"
        allowed = _strip(body.get("allowed_users"))
        if mode and mode not in {"bot", "self-chat"}:
            raise HTTPException(status_code=400, detail="mode must be 'bot' or 'self-chat'")
        if mode:
            save_env_value("WHATSAPP_MODE", mode)
            save_env_value("WHATSAPP_ENABLED", "true")
        if allowed:
            save_env_value("WHATSAPP_ALLOWED_USERS", allowed.replace(" ", ""))

        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        has_node_modules = (bridge_dir / "node_modules").exists()
        bridge_present = (bridge_dir / "bridge.js").exists()
        session_dir = Path(os.path.expanduser("~/.elevate/whatsapp/session"))
        paired = (session_dir / "creds.json").exists()

        return {
            "ok": True,
            "mode": get_env_value("WHATSAPP_MODE") or "",
            "enabled": _whatsapp_enabled(),
            "allowedUsers": get_env_value("WHATSAPP_ALLOWED_USERS") or "",
            "bridgePresent": bridge_present,
            "bridgeInstalled": has_node_modules,
            "paired": paired,
        }

    @router.post("/api/channels/whatsapp/install")
    async def install_whatsapp_bridge(request: Request):
        """Run ``npm install`` inside the WhatsApp bridge directory."""
        require_token(request)
        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        if not (bridge_dir / "bridge.js").exists():
            raise HTTPException(status_code=404, detail=f"bridge.js not found at {bridge_dir}")

        npm = shutil.which("npm")
        if not npm:
            raise HTTPException(
                status_code=400,
                detail="npm not on PATH — install Node.js first (https://nodejs.org/)",
            )

        try:
            # npm install can take minutes — run it off the event loop so the
            # single-worker dashboard stays responsive to every other request.
            proc = await asyncio.to_thread(
                subprocess.run,
                [npm, "install", "--no-fund", "--no-audit", "--progress=false"],
                cwd=str(bridge_dir),
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="npm install timed out after 10 minutes")

        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-30:]) or "(no output)"
            raise HTTPException(status_code=500, detail=f"npm install failed:\n{tail}")

        return {
            "ok": True,
            "installed": (bridge_dir / "node_modules").exists(),
        }

    @router.get("/api/channels/whatsapp/status")
    async def whatsapp_status():
        """Lightweight status: is bridge installed, has session been paired."""
        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        session_dir = Path(os.path.expanduser("~/.elevate/whatsapp/session"))
        return {
            "bridgePresent": (bridge_dir / "bridge.js").exists(),
            "bridgeInstalled": (bridge_dir / "node_modules").exists(),
            "mode": get_env_value("WHATSAPP_MODE") or "",
            "enabled": _whatsapp_enabled(),
            "paired": (session_dir / "creds.json").exists(),
            "allowedUsers": get_env_value("WHATSAPP_ALLOWED_USERS") or "",
        }

    @router.get("/api/channels/whatsapp/pair/stream")
    async def whatsapp_pair_stream(request: Request):
        """Server-Sent Events stream of WhatsApp pairing progress."""
        require_token(request)
        bridge_dir = elevate_repo_root_func() / "scripts" / "whatsapp-bridge"
        bridge_script = bridge_dir / "bridge.js"
        if not bridge_script.exists():
            raise HTTPException(status_code=404, detail="bridge.js not found")
        if not (bridge_dir / "node_modules").exists():
            raise HTTPException(
                status_code=400,
                detail="WhatsApp bridge dependencies not installed — call /api/channels/whatsapp/install first",
            )
        node = shutil.which("node")
        if not node:
            raise HTTPException(status_code=400, detail="node not on PATH")

        session_dir = Path(os.path.expanduser("~/.elevate/whatsapp/session"))
        session_dir.mkdir(parents=True, exist_ok=True)
        # Re-pairing: clear stale session so Baileys emits a fresh QR.
        creds = session_dir / "creds.json"
        if creds.exists():
            try:
                shutil.rmtree(session_dir, ignore_errors=True)
                session_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        async def event_stream():
            proc = await asyncio.create_subprocess_exec(
                node,
                str(bridge_script),
                "--pair-only",
                "--qr-json",
                "--session",
                str(session_dir),
                cwd=str(bridge_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def kill_if_disconnected():
                while True:
                    if await request.is_disconnected():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        return
                    await asyncio.sleep(1.0)

            watcher = asyncio.create_task(kill_if_disconnected())
            try:
                assert proc.stdout is not None
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    # Only forward our JSON lines; ignore Baileys chatter.
                    if text.startswith("{") and text.endswith("}"):
                        try:
                            payload = json.loads(text)
                        except Exception:
                            yield f"data: {text}\n\n"
                            continue
                        # When the bridge sends a raw QR string, render it to
                        # a data URL server-side so the browser can drop it
                        # into an <img> tag without a JS QR library.
                        if payload.get("event") == "qr" and payload.get("qr"):
                            try:
                                import qrcode  # type: ignore[import-not-found]

                                img = qrcode.make(payload["qr"], box_size=6, border=2)
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                payload["dataUrl"] = (
                                    "data:image/png;base64,"
                                    + base64.b64encode(buf.getvalue()).decode("ascii")
                                )
                            except Exception:
                                # Browser can still render the raw QR with its
                                # own library if it ever wants to.
                                pass
                        yield f"data: {json.dumps(payload)}\n\n"
                rc = await proc.wait()
                yield f"data: {json.dumps({'event': 'exit', 'code': rc})}\n\n"
            finally:
                watcher.cancel()
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router
