import json
import logging

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli import outreach_db, sender
from elevate_cli.data import connect as data_connect, upsert_contact
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.web_routes.source_inbox_sends import register_source_inbox_send_routes


@pytest.fixture(autouse=True)
def _fresh_operational_store(_hermetic_environment):
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def make_client():
    app = FastAPI()
    router = APIRouter()
    register_source_inbox_send_routes(router, log=logging.getLogger(__name__))
    app.include_router(router)
    return TestClient(app)


def enqueue_retry_candidate(
    *,
    status=outreach_db.SEND_STATUS_FAILED,
    current_phone="+16045550123",
    recipient_phone="+16045550999",
    payload_override=None,
):
    with data_connect() as conn:
        contact = upsert_contact(
            conn,
            display_name="Retry Lead",
            primary_phone=current_phone,
            primary_email="retry@example.com",
            source_key="test:retry-lead",
        )
    payload = {
        "draft_text": "Can we reconnect?",
        "recipient": {
            "person_name": "Retry Lead",
            "contact_id": contact["id"],
            "phone": recipient_phone,
        },
    }
    if payload_override is not None:
        payload = payload_override
    with outreach_db.connect() as conn:
        with outreach_db.transaction(conn):
            row = outreach_db.enqueue_send(
                conn,
                source_id="crm",
                thread_id="retry-thread",
                task_id="retry-task",
                channel="sms",
                payload=payload,
            )
            conn.execute(
                """
                UPDATE send_queue
                   SET status=?, attempts=3, last_error='old failure',
                       next_retry_at='2026-07-14T00:00:00+00:00'
                 WHERE id=?
                """,
                (status, row["id"]),
            )
    return row["id"], contact["id"]


def queue_row(queue_id):
    with outreach_db.connect() as conn:
        return conn.execute("SELECT * FROM send_queue WHERE id=?", (queue_id,)).fetchone()


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


def test_source_inbox_not_sent_uses_exact_affected_statuses(monkeypatch):
    calls = []

    def fake_list_recent_sends(*, statuses, limit):
        calls.append((statuses, limit))
        return []

    monkeypatch.setattr(outreach_db, "list_recent_sends", fake_list_recent_sends)

    resp = make_client().get("/api/source-inbox/not-sent?limit=9")

    assert resp.status_code == 200
    assert calls == [
        (
            (
                outreach_db.SEND_STATUS_FAILED,
                outreach_db.SEND_STATUS_RETRYING,
            ),
            9,
        )
    ]


def test_retry_resolves_nested_current_phone_and_dispatches_only_selected(
    monkeypatch,
):
    queue_id, _contact_id = enqueue_retry_candidate(
        status=outreach_db.SEND_STATUS_FAILED,
        current_phone="+16045550123",
        recipient_phone="+16045550999",
    )
    dispatched = []

    def fake_dispatch(row):
        dispatched.append(row)
        return outreach_db.mark_sent(row["id"], "provider-retry-1")

    monkeypatch.setattr(sender, "dispatch_one", fake_dispatch)
    monkeypatch.setattr(
        sender,
        "tick",
        lambda **_kwargs: pytest.fail("retry must not drain the global queue"),
    )

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == outreach_db.SEND_STATUS_SENT
    assert resp.json()["phone"] == "+16045550123"
    assert [item["id"] for item in dispatched] == [queue_id]
    assert dispatched[0]["payload"]["recipient"]["phone"] == "+16045550123"
    saved = queue_row(queue_id)
    assert json.loads(saved["payload_json"])["recipient"]["phone"] == "+16045550123"
    assert saved["status"] == outreach_db.SEND_STATUS_SENT
    assert saved["attempts"] == 0
    assert saved["last_error"] is None
    assert saved["next_retry_at"] is None


def test_retry_with_legacy_top_level_contact_writes_nested_phone(monkeypatch):
    queue_id, contact_id = enqueue_retry_candidate(current_phone="+12505550123")
    with outreach_db.connect() as conn:
        conn.execute(
            "UPDATE send_queue SET payload_json=? WHERE id=?",
            (
                json.dumps({
                    "draft_text": "Legacy payload",
                    "contact_id": contact_id,
                    "recipient": {"person_name": "Retry Lead"},
                }),
                queue_id,
            ),
        )
    monkeypatch.setattr(sender, "dispatch_one", lambda row: outreach_db.mark_sent(row["id"], "legacy-1"))

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 200
    assert json.loads(queue_row(queue_id)["payload_json"])["recipient"]["phone"] == "+12505550123"


def test_retry_missing_current_phone_is_rejected_without_mutation(monkeypatch):
    queue_id, _contact_id = enqueue_retry_candidate(
        current_phone=None,
        recipient_phone="+16045550999",
    )
    before = dict(queue_row(queue_id))
    monkeypatch.setattr(
        sender,
        "dispatch_one",
        lambda _row: pytest.fail("missing-phone retry must not dispatch"),
    )

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 409
    assert "still has no phone" in resp.json()["detail"]
    after = dict(queue_row(queue_id))
    assert after == before


def test_retry_sms_is_refused_while_outbound_is_off_without_mutation(monkeypatch):
    queue_id, _contact_id = enqueue_retry_candidate()
    before = dict(queue_row(queue_id))
    monkeypatch.delenv("ELEVATE_OUTREACH_SANDBOX", raising=False)
    monkeypatch.setattr(sender, "apple_messages_outbound_enabled", lambda config=None: False)
    monkeypatch.setattr(
        sender,
        "dispatch_one",
        lambda _row: pytest.fail("disabled SMS retry must not dispatch"),
    )

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 409
    assert resp.json()["detail"] == sender.APPLE_MESSAGES_OUTBOUND_DISABLED_ERROR
    assert dict(queue_row(queue_id)) == before


@pytest.mark.parametrize(
    "starting_status",
    [
        outreach_db.SEND_STATUS_SENT,
        outreach_db.SEND_STATUS_SKIPPED,
        outreach_db.SEND_STATUS_QUEUED,
        outreach_db.SEND_STATUS_SENDING,
        outreach_db.SEND_STATUS_RETRYING,
    ],
)
def test_retry_rejects_nonterminal_or_delivered_states(monkeypatch, starting_status):
    queue_id, _contact_id = enqueue_retry_candidate(status=starting_status)
    before = dict(queue_row(queue_id))
    monkeypatch.setattr(
        sender,
        "dispatch_one",
        lambda _row: pytest.fail("rejected retry must not dispatch"),
    )

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 409
    assert dict(queue_row(queue_id)) == before


@pytest.mark.parametrize(
    "bad_payload",
    ["not-json", json.dumps(["not", "an", "object"]), json.dumps({"recipient": "not-an-object"})],
)
def test_retry_rejects_malformed_payload_without_mutation(monkeypatch, bad_payload):
    queue_id, _contact_id = enqueue_retry_candidate()
    with outreach_db.connect() as conn:
        conn.execute("UPDATE send_queue SET payload_json=? WHERE id=?", (bad_payload, queue_id))
    before = dict(queue_row(queue_id))
    monkeypatch.setattr(
        sender,
        "dispatch_one",
        lambda _row: pytest.fail("malformed retry must not dispatch"),
    )

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 422
    assert dict(queue_row(queue_id)) == before


def test_retry_unknown_id_is_404(monkeypatch):
    monkeypatch.setattr(
        sender,
        "dispatch_one",
        lambda _row: pytest.fail("unknown retry must not dispatch"),
    )

    resp = make_client().post("/api/source-inbox/retry-send/missing")

    assert resp.status_code == 404


def test_retry_response_reports_dispatch_failure_truth(monkeypatch):
    queue_id, _contact_id = enqueue_retry_candidate()

    def fake_dispatch(row):
        return outreach_db.mark_retrying(
            row["id"],
            error="provider unavailable",
            next_retry_at="2026-07-14T00:01:00+00:00",
        )

    monkeypatch.setattr(sender, "dispatch_one", fake_dispatch)

    resp = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == outreach_db.SEND_STATUS_RETRYING
    assert resp.json()["lastError"] == "provider unavailable"
    assert resp.json()["providerMessageId"] is None


def test_retry_claim_blocks_a_second_dispatch_while_first_is_sending(monkeypatch):
    queue_id, _contact_id = enqueue_retry_candidate()
    dispatched = []

    def hold_sending(row):
        dispatched.append(row["id"])
        return row

    monkeypatch.setattr(sender, "dispatch_one", hold_sending)

    first = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")
    second = make_client().post(f"/api/source-inbox/retry-send/{queue_id}")

    assert first.status_code == 200
    assert first.json()["status"] == outreach_db.SEND_STATUS_SENDING
    assert second.status_code == 409
    assert dispatched == [queue_id]
