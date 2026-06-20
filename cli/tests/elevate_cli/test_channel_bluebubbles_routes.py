from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes import channel_bluebubbles


def make_client(require_token=lambda _request: None):
    app = FastAPI()
    router = APIRouter()
    channel_bluebubbles.register_bluebubbles_routes(router, require_token=require_token)
    app.include_router(router)
    return TestClient(app)


def test_bluebubbles_configure_saves_settings(monkeypatch):
    env = {}
    monkeypatch.setattr(channel_bluebubbles, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_bluebubbles, "save_env_value", lambda key, value: env.__setitem__(key, value))

    resp = make_client().post(
        "/api/channels/imessage/bluebubbles/configure",
        json={
            "server_url": "https://bluebubbles.example.com/",
            "password": "secret",
            "allowed_users": " +15551212, +15553434 ",
            "home_channel": "+15550000",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "serverUrl": "https://bluebubbles.example.com",
        "passwordSet": True,
        "allowedUsers": "+15551212,+15553434",
        "homeChannel": "+15550000",
    }
    assert env["BLUEBUBBLES_SERVER_URL"] == "https://bluebubbles.example.com"
    assert env["BLUEBUBBLES_PASSWORD"] == "secret"
    assert env["BLUEBUBBLES_ALLOWED_USERS"] == "+15551212,+15553434"
    assert env["BLUEBUBBLES_HOME_CHANNEL"] == "+15550000"


def test_bluebubbles_configure_requires_server_url_and_password(monkeypatch):
    monkeypatch.setattr(channel_bluebubbles, "get_env_value", lambda _key: "")

    resp = make_client().post("/api/channels/imessage/bluebubbles/configure", json={})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "BlueBubbles server URL + password are required"
