import logging

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli import outreach_db, sender
from elevate_cli.web_routes.source_sender import register_sender_routes


def make_client():
    app = FastAPI()
    router = APIRouter()
    register_sender_routes(router, log=logging.getLogger(__name__))
    app.include_router(router)
    return TestClient(app)


def test_sender_tick_clamps_batch(monkeypatch):
    calls = []

    def fake_tick(*, batch):
        calls.append(batch)
        return {"ok": True, "batch": batch}

    monkeypatch.setattr(sender, "tick", fake_tick)

    resp = make_client().post("/api/sender/tick?batch=250")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "batch": 100}
    assert calls == [100]


def test_sender_stats_returns_queue(monkeypatch):
    monkeypatch.setattr(outreach_db, "send_queue_stats", lambda: {"queued": 2, "sent": 5})

    resp = make_client().get("/api/sender/stats")

    assert resp.status_code == 200
    assert resp.json() == {"queue": {"queued": 2, "sent": 5}}
