from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes import channel_discord


def make_client(require_token=lambda _request: None):
    app = FastAPI()
    router = APIRouter()
    channel_discord.register_discord_routes(
        router,
        require_token=require_token,
        token_preview=lambda token: f"preview:{token[-4:]}",
    )
    app.include_router(router)
    return TestClient(app)


def test_discord_configure_saves_token_allowlist_and_home(monkeypatch):
    env = {}
    monkeypatch.setattr(channel_discord, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_discord, "save_env_value", lambda key, value: env.__setitem__(key, value))

    resp = make_client().post(
        "/api/channels/discord/configure",
        json={
            "bot_token": "discord-secret-bot",
            "allowed_users": " <@!123>, user:456, 789 ",
            "home_channel": "C123",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "tokenPreview": "preview:-bot",
        "allowedUsers": "123,456,789",
        "homeChannel": "C123",
    }
    assert env["DISCORD_BOT_TOKEN"] == "discord-secret-bot"
    assert env["DISCORD_ALLOWED_USERS"] == "123,456,789"
    assert env["DISCORD_HOME_CHANNEL"] == "C123"
    assert env["DISCORD_CHANNEL_ID"] == "C123"


def test_discord_configure_requires_bot_token(monkeypatch):
    monkeypatch.setattr(channel_discord, "get_env_value", lambda _key: "")

    resp = make_client().post("/api/channels/discord/configure", json={})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "bot_token is required"
