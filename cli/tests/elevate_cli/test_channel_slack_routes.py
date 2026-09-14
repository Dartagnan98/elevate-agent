from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes import channel_slack


def make_client(require_token=lambda _request: None):
    app = FastAPI()
    router = APIRouter()
    channel_slack.register_slack_routes(
        router,
        require_token=require_token,
        token_preview=lambda token: f"preview:{token[-4:]}",
    )
    app.include_router(router)
    return TestClient(app)


def test_slack_configure_saves_tokens_and_allowlist(monkeypatch):
    env = {}
    monkeypatch.setattr(channel_slack, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_slack, "save_env_value", lambda key, value: env.__setitem__(key, value))

    resp = make_client().post(
        "/api/channels/slack/configure",
        json={
            "bot_token": "xoxb-secret-bot",
            "app_token": "xapp-secret-app",
            "allowed_users": " U1, U2 ",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "botTokenPreview": "preview:-bot",
        "appTokenPreview": "preview:-app",
        "allowedUsers": "U1,U2",
    }
    assert env["SLACK_BOT_TOKEN"] == "xoxb-secret-bot"
    assert env["SLACK_APP_TOKEN"] == "xapp-secret-app"
    assert env["SLACK_ALLOWED_USERS"] == "U1,U2"


def test_slack_configure_requires_bot_token(monkeypatch):
    monkeypatch.setattr(channel_slack, "get_env_value", lambda _key: "")

    resp = make_client().post("/api/channels/slack/configure", json={})

    assert resp.status_code == 400
    assert "bot_token" in resp.json()["detail"]


def test_slack_test_without_webhook_reports_configuration_gap(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(channel_slack, "load_env", lambda: {})

    resp = make_client().post("/api/channels/slack/test", json={})

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "status": 0,
        "detail": "No webhook URL provided and SLACK_WEBHOOK_URL is not set.",
    }
