import logging

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli import source_connectors
from elevate_cli.web_routes.source_apple_messages import register_apple_messages_routes


def make_client():
    app = FastAPI()
    router = APIRouter()
    register_apple_messages_routes(router, log=logging.getLogger(__name__))
    app.include_router(router)
    return TestClient(app)


def test_get_apple_messages_directions(monkeypatch):
    monkeypatch.setattr(
        source_connectors,
        "get_apple_messages_directions",
        lambda _source_root=None: {"inbound": True, "outbound": False},
    )

    resp = make_client().get("/api/source-inbox/apple-messages/directions")

    assert resp.status_code == 200
    assert resp.json() == {"inbound": True, "outbound": False}


def test_set_apple_messages_directions_reinitializes(monkeypatch):
    calls = []

    def fake_set(*, inbound=None, outbound=None):
        calls.append(("set", inbound, outbound))
        return {"inbound": bool(inbound), "outbound": bool(outbound)}

    monkeypatch.setattr(source_connectors, "set_apple_messages_directions", fake_set)
    monkeypatch.setattr(source_connectors, "initialize_apple_messages_source", lambda: calls.append(("init",)))

    resp = make_client().post(
        "/api/source-inbox/apple-messages/directions",
        json={"inbound": True, "outbound": False},
    )

    assert resp.status_code == 200
    assert resp.json() == {"inbound": True, "outbound": False}
    assert calls == [("set", True, False), ("init",)]
