"""BlueBubbles channel configuration routes."""

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from elevate_cli.config import get_env_value, save_env_value

RequireToken = Callable[[Request], None]


def _strip(value: Any) -> str:
    return str(value or "").strip()


def register_bluebubbles_routes(
    router: APIRouter,
    *,
    require_token: RequireToken,
) -> None:
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
