import logging
import sys
import types
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes import channel_telegram


def make_client(
    *,
    spawn=lambda _args, _action: SimpleNamespace(pid=4321),
    validator=lambda _token: True,
    sync=lambda _key, _value: [],
    require_token=lambda _request: None,
    raise_server_exceptions=True,
):
    app = FastAPI()
    router = APIRouter()
    channel_telegram.register_telegram_routes(
        router,
        log=logging.getLogger(__name__),
        require_token=require_token,
        spawn_elevate_action=spawn,
        looks_like_telegram_bot_token=validator,
        sync_executive_telegram_aliases=sync,
        token_preview=lambda token: f"preview:{token[-4:]}",
    )
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_telegram_pair_start_saves_token_and_restarts_gateway(monkeypatch):
    env = {}
    syncs = []
    spawns = []

    monkeypatch.setattr(channel_telegram, "save_env_value", lambda key, value: env.__setitem__(key, value))

    def spawn(args, action):
        spawns.append((args, action))
        return SimpleNamespace(pid=9876)

    resp = make_client(spawn=spawn, sync=lambda key, value: syncs.append((key, value))).post(
        "/api/telegram/pair/start",
        json={"bot_token": "123456:ABCDEF"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "gateway-restart", "pid": 9876}
    assert env["TELEGRAM_BOT_TOKEN"] == "123456:ABCDEF"
    assert env["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] == "pair"
    assert syncs == [("TELEGRAM_BOT_TOKEN", "123456:ABCDEF")]
    assert spawns == [(["gateway", "restart"], "gateway-restart")]


def test_telegram_configure_saves_settings(monkeypatch):
    env = {}
    syncs = []
    monkeypatch.setattr(channel_telegram, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_telegram, "save_env_value", lambda key, value: env.__setitem__(key, value))

    resp = make_client(sync=lambda key, value: syncs.append((key, value))).post(
        "/api/channels/telegram/configure",
        json={
            "bot_token": "123456:ABCDEF",
            "allowed_users": " 111, 222 ",
            "home_channel": "@home",
            "dm_behavior": "pair",
            "allow_all_users": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "tokenPreview": "preview:CDEF",
        "allowedUsers": "111,222",
        "homeChannel": "@home",
        "dmBehavior": "pair",
        "allowAllUsers": False,
    }
    assert env["TELEGRAM_BOT_TOKEN"] == "123456:ABCDEF"
    assert env["TELEGRAM_ALLOWED_USERS"] == "111,222"
    assert env["TELEGRAM_HOME_CHANNEL"] == "@home"
    assert env["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] == "pair"
    assert env["GATEWAY_ALLOW_ALL_USERS"] == "false"
    assert syncs == [("TELEGRAM_BOT_TOKEN", "123456:ABCDEF")]


def test_telegram_status_unconfigured(monkeypatch):
    monkeypatch.setattr(channel_telegram, "get_env_value", lambda _key: "")

    resp = make_client().get("/api/channels/telegram/status")

    assert resp.status_code == 200
    assert resp.json() == {
        "configured": False,
        "tokenPreview": "",
        "allowedUsers": "",
        "homeChannel": "",
        "dmBehavior": "",
        "allowAllUsers": False,
    }


def test_telegram_approve_adds_allowed_user_and_home(monkeypatch):
    env = {"TELEGRAM_ALLOWED_USERS": "111"}
    syncs = []

    class Store:
        def approve_code(self, platform, code):
            assert platform == "telegram"
            assert code == "abc123"
            return {"user_id": "222", "user_name": "Ada"}

    gateway_module = types.ModuleType("gateway")
    gateway_module.__path__ = []
    pairing_module = types.ModuleType("gateway.pairing")
    pairing_module.PairingStore = Store
    monkeypatch.setitem(sys.modules, "gateway", gateway_module)
    monkeypatch.setitem(sys.modules, "gateway.pairing", pairing_module)
    monkeypatch.setattr(channel_telegram, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(channel_telegram, "save_env_value", lambda key, value: env.__setitem__(key, value))

    resp = make_client(sync=lambda key, value: syncs.append((key, value))).post(
        "/api/telegram/pair/approve",
        json={"code": "abc123", "set_home": True},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "user_id": "222", "user_name": "Ada"}
    assert env["TELEGRAM_ALLOWED_USERS"] == "111,222"
    assert env["TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"] == "ignore"
    assert env["TELEGRAM_HOME_CHANNEL"] == "222"
    assert syncs == [("TELEGRAM_HOME_CHANNEL", "222")]


def test_exact_beta_telegram_configure_is_unavailable_without_mutation(monkeypatch):
    from elevate_cli.config import get_env_path, load_env, save_env_value

    token = "123456:ABCDEFGHIJKLMNOPQRSTUVWX"
    save_env_value("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", token)
    env_path = get_env_path()
    before_bytes = env_path.read_bytes()
    before = dict(load_env())
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    resp = make_client().post(
        "/api/channels/telegram/configure",
        json={
            "bot_token": token,
            "allowed_users": "123456",
            "dm_behavior": "ignore",
            "allow_all_users": False,
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "beta_messaging_runtime_unavailable",
        "message": (
            "Telegram pairing is not enabled in this Realtor Beta build. "
            "Use in-app chat while the messaging runtime is being hardened."
        ),
        "configurationSaved": False,
        "restartStarted": False,
    }
    assert load_env() == before
    assert env_path.read_bytes() == before_bytes


def test_exact_beta_telegram_configure_stops_before_any_writer(monkeypatch):
    from elevate_cli.config import get_env_path, load_env

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    env_path = get_env_path()
    before_bytes = env_path.read_bytes() if env_path.exists() else None
    before = dict(load_env())

    def fail_write(_updates):
        raise OSError("injected durable-write failure")

    monkeypatch.setattr(channel_telegram, "save_env_values", fail_write)
    resp = make_client(raise_server_exceptions=False).post(
        "/api/channels/telegram/configure",
        json={
            "bot_token": "123456:ABCDEFGHIJKLMNOPQRSTUVWX",
            "allowed_users": "123456",
            "home_channel": "-1001234567890",
            "dm_behavior": "ignore",
            "allow_all_users": False,
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "beta_messaging_runtime_unavailable"
    assert load_env() == before
    assert (env_path.read_bytes() if env_path.exists() else None) == before_bytes


def test_exact_beta_pair_start_is_unavailable_without_mutation(monkeypatch):
    from elevate_cli.config import load_env, save_env_values

    save_env_values(
        {
            "GATEWAY_ALLOW_ALL_USERS": "true",
            "GATEWAY_ALLOWED_USERS": "*",
            "TELEGRAM_ALLOW_ALL_USERS": "true",
            "TELEGRAM_ALLOWED_USERS": "*",
            "TELEGRAM_GROUP_ALLOWED_USERS": "*",
            "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR": "open",
        }
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    before = dict(load_env())

    resp = make_client().post(
        "/api/telegram/pair/start",
        json={"bot_token": "123456:ABCDEFGHIJKLMNOPQRSTUVWX"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "beta_messaging_runtime_unavailable"
    assert load_env() == before


def test_exact_beta_pair_start_never_spawns_the_disabled_gateway(monkeypatch):
    from elevate_cli.config import load_env

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    def fail_spawn(_args, _action):
        raise OSError("injected spawn failure")

    resp = make_client(spawn=fail_spawn).post(
        "/api/telegram/pair/start",
        json={"bot_token": "123456:ABCDEFGHIJKLMNOPQRSTUVWX"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "beta_messaging_runtime_unavailable",
        "message": (
            "Telegram pairing is not enabled in this Realtor Beta build. "
            "Use in-app chat while the messaging runtime is being hardened."
        ),
        "configurationSaved": False,
        "restartStarted": False,
    }
    env = load_env()
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR" not in env


def test_exact_beta_pair_approval_is_unavailable_without_consuming_code(monkeypatch):
    consumed = []

    class Store:
        def approve_code(self, platform, code, before_commit=None):
            assert platform == "telegram"
            assert code == "abc123"
            before_commit({"user_id": "222", "user_name": "Ada", "agent_id": ""})
            consumed.append(code)
            return {"user_id": "222", "user_name": "Ada", "agent_id": ""}

    gateway_module = types.ModuleType("gateway")
    gateway_module.__path__ = []
    pairing_module = types.ModuleType("gateway.pairing")
    pairing_module.PairingStore = Store
    monkeypatch.setitem(sys.modules, "gateway", gateway_module)
    monkeypatch.setitem(sys.modules, "gateway.pairing", pairing_module)
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        channel_telegram,
        "save_env_values",
        lambda _updates: (_ for _ in ()).throw(OSError("injected durable-write failure")),
    )

    resp = make_client().post(
        "/api/telegram/pair/approve",
        json={"code": "abc123", "set_home": True},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "beta_messaging_runtime_unavailable"
    assert consumed == []


def test_exact_beta_pair_approval_stops_before_pairing_store_lookup(monkeypatch):
    consumed = []

    class Store:
        def approve_code(self, platform, code, before_commit=None):
            before_commit({"user_id": "*", "user_name": "Mallory", "agent_id": ""})
            consumed.append((platform, code))
            return {"user_id": "*", "user_name": "Mallory", "agent_id": ""}

    gateway_module = types.ModuleType("gateway")
    gateway_module.__path__ = []
    pairing_module = types.ModuleType("gateway.pairing")
    pairing_module.PairingStore = Store
    monkeypatch.setitem(sys.modules, "gateway", gateway_module)
    monkeypatch.setitem(sys.modules, "gateway.pairing", pairing_module)
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    resp = make_client().post(
        "/api/telegram/pair/approve",
        json={"code": "abc123"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "beta_messaging_runtime_unavailable"
    assert consumed == []


def test_exact_beta_status_reports_stale_open_access_sources(monkeypatch):
    from elevate_cli.config import save_env_values

    save_env_values(
        {
            "GATEWAY_ALLOW_ALL_USERS": "true",
            "TELEGRAM_GROUP_ALLOWED_USERS": "*",
            "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR": "pair",
        }
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    resp = make_client().get("/api/channels/telegram/status")

    assert resp.status_code == 200
    assert resp.json()["allowAllUsers"] is True
    assert resp.json()["unsafeAccessSources"] == [
        "GATEWAY_ALLOW_ALL_USERS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
    ]
