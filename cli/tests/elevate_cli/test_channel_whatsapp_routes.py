from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes import channel_whatsapp


def make_client(root, require_token=lambda _request: None):
    app = FastAPI()
    router = APIRouter()
    channel_whatsapp.register_whatsapp_routes(
        router,
        require_token=require_token,
        elevate_repo_root_func=lambda: root,
    )
    app.include_router(router)
    return TestClient(app)


def test_whatsapp_configure_reports_bridge_and_session_state(tmp_path, monkeypatch):
    env = {}
    bridge_dir = tmp_path / "scripts" / "whatsapp-bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "bridge.js").write_text("// bridge\n")
    (bridge_dir / "node_modules").mkdir()
    home = tmp_path / "home"
    session_dir = home / ".elevate" / "whatsapp" / "session"
    session_dir.mkdir(parents=True)
    (session_dir / "creds.json").write_text("{}")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(channel_whatsapp, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_whatsapp, "save_env_value", lambda key, value: env.__setitem__(key, value))
    monkeypatch.setattr(channel_whatsapp, "load_config", lambda: {"platforms": {"whatsapp": {"enabled": False}}})

    resp = make_client(tmp_path).post(
        "/api/channels/whatsapp/configure",
        json={"mode": "self-chat", "allowed_users": " +15551212, +15553434 "},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "mode": "self-chat",
        "enabled": True,
        "allowedUsers": "+15551212,+15553434",
        "bridgePresent": True,
        "bridgeInstalled": True,
        "paired": True,
    }
    assert env["WHATSAPP_MODE"] == "self-chat"
    assert env["WHATSAPP_ENABLED"] == "true"
    assert env["WHATSAPP_ALLOWED_USERS"] == "+15551212,+15553434"


def test_whatsapp_status_reads_config_enabled_flag(tmp_path, monkeypatch):
    env = {"WHATSAPP_MODE": "bot", "WHATSAPP_ALLOWED_USERS": "+15551212"}
    bridge_dir = tmp_path / "scripts" / "whatsapp-bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "bridge.js").write_text("// bridge\n")

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(channel_whatsapp, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_whatsapp, "load_config", lambda: {"platforms": {"whatsapp": {"enabled": True}}})

    resp = make_client(tmp_path).get("/api/channels/whatsapp/status")

    assert resp.status_code == 200
    assert resp.json() == {
        "bridgePresent": True,
        "bridgeInstalled": False,
        "mode": "bot",
        "enabled": True,
        "paired": False,
        "allowedUsers": "+15551212",
    }


def test_whatsapp_install_reports_missing_bridge(tmp_path):
    resp = make_client(tmp_path).post("/api/channels/whatsapp/install")

    assert resp.status_code == 404
    assert "bridge.js not found" in resp.json()["detail"]


def test_whatsapp_pair_stream_requires_installed_dependencies(tmp_path):
    bridge_dir = tmp_path / "scripts" / "whatsapp-bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "bridge.js").write_text("// bridge\n")

    resp = make_client(tmp_path).get("/api/channels/whatsapp/pair/stream")

    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "WhatsApp bridge dependencies not installed — call /api/channels/whatsapp/install first"
    )
