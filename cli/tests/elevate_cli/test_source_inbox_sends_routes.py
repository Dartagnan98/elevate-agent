import logging

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli import outreach_db, sender
from elevate_cli.web_routes.source_inbox_sends import register_source_inbox_send_routes


def make_client():
    app = FastAPI()
    router = APIRouter()
    register_source_inbox_send_routes(router, log=logging.getLogger(__name__))
    app.include_router(router)
    return TestClient(app)


def test_source_inbox_send_status_not_queued(monkeypatch):
    monkeypatch.setattr(sender, "status_for_task", lambda *_args: None)

    resp = make_client().get("/api/source-inbox/draft/source/thread/task/send-status")

    assert resp.status_code == 200
    assert resp.json() == {"queued": False, "status": None}


def test_source_inbox_send_status_queued(monkeypatch):
    monkeypatch.setattr(sender, "status_for_task", lambda *_args: {"status": "queued", "id": "send-1"})

    resp = make_client().get("/api/source-inbox/draft/source/thread/task/send-status")

    assert resp.status_code == 200
    assert resp.json() == {"queued": True, "status": "queued", "id": "send-1"}


def test_source_inbox_sent_uses_sent_only_by_default(monkeypatch):
    calls = []

    def fake_list_recent_sends(*, statuses, limit):
        calls.append((statuses, limit))
        return [{"id": "sent-1"}]

    monkeypatch.setattr(outreach_db, "list_recent_sends", fake_list_recent_sends)

    resp = make_client().get("/api/source-inbox/sent?limit=7")

    assert resp.status_code == 200
    assert resp.json() == {"items": [{"id": "sent-1"}], "limit": 7, "includePending": False}
    assert calls == [((outreach_db.SEND_STATUS_SENT,), 7)]


def test_source_inbox_sent_can_include_pending_statuses(monkeypatch):
    calls = []

    def fake_list_recent_sends(*, statuses, limit):
        calls.append((statuses, limit))
        return []

    monkeypatch.setattr(outreach_db, "list_recent_sends", fake_list_recent_sends)

    resp = make_client().get("/api/source-inbox/sent?limit=3&include_pending=true")

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "limit": 3, "includePending": True}
    assert calls == [
        (
            (
                outreach_db.SEND_STATUS_SENT,
                outreach_db.SEND_STATUS_SENDING,
                outreach_db.SEND_STATUS_QUEUED,
                outreach_db.SEND_STATUS_RETRYING,
                outreach_db.SEND_STATUS_FAILED,
            ),
            3,
        )
    ]
