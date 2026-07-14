from __future__ import annotations

import pytest

from elevate_cli import data, outreach_db
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_enqueue_send_reuses_existing_idempotency_key():
    with outreach_db.connect() as conn:
        first = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-1",
            task_id="task-1",
            channel="sms",
            payload={"text": "hello"},
        )
        second = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-1",
            task_id="task-1",
            channel="sms",
            payload={"text": "hello"},
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM send_queue WHERE idempotency_key=?",
            (first["idempotencyKey"],),
        ).fetchone()[0]

    assert second["id"] == first["id"]
    assert count == 1


def test_repeated_mark_sent_does_not_duplicate_outbound_event():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="Ava Buyer")
        conversation = data.get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id="crm",
            channel="sms",
            thread_key="thread-1",
        )

    with outreach_db.connect() as conn:
        send = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-1",
            task_id="task-1",
            channel="sms",
            payload={"text": "hello"},
        )

    outreach_db.mark_sent(send["id"], "provider-message-1")
    outreach_db.mark_sent(send["id"], "provider-message-1")

    with data.connect() as conn:
        rows = conn.execute(
            "SELECT event_hash FROM events "
            "WHERE conversation_id=? AND kind='outbound'",
            (conversation["id"],),
        ).fetchall()

    assert len(rows) == 1


def test_claim_send_by_id_claims_only_the_selected_row_once():
    with outreach_db.connect() as conn:
        first = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-1",
            task_id="task-1",
            channel="sms",
            payload={"draft_text": "first"},
        )
        second = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-2",
            task_id="task-2",
            channel="sms",
            payload={"draft_text": "second"},
        )

    claimed = outreach_db.claim_send_by_id(second["id"])

    assert claimed is not None
    assert claimed["id"] == second["id"]
    assert claimed["status"] == outreach_db.SEND_STATUS_SENDING
    assert outreach_db.claim_send_by_id(second["id"]) is None
    assert outreach_db.get_send_by_task("crm", "thread-1", "task-1")["status"] == outreach_db.SEND_STATUS_QUEUED


def test_stale_sending_without_provider_proof_becomes_visible_unknown_outcome():
    with outreach_db.connect() as conn:
        send = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-stale",
            task_id="task-stale",
            channel="sms",
            payload={"draft_text": "maybe sent"},
        )
        conn.execute(
            "UPDATE send_queue SET status=?, updated_at=? WHERE id=?",
            (outreach_db.SEND_STATUS_SENDING, "2020-01-01T00:00:00+00:00", send["id"]),
        )

    recovered = outreach_db.recover_stale_sends(stale_after_seconds=30)
    row = outreach_db.get_send_by_task("crm", "thread-stale", "task-stale")

    assert recovered["failed"] == 1
    assert row["status"] == outreach_db.SEND_STATUS_FAILED
    assert "outcome unknown" in row["lastError"]


def test_stale_sending_with_durable_provider_id_finishes_sent():
    with outreach_db.connect() as conn:
        send = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-proven",
            task_id="task-proven",
            channel="sms",
            payload={"draft_text": "provider accepted"},
        )
        conn.execute(
            """
            UPDATE send_queue
               SET status=?, provider_message_id=?, updated_at=?
             WHERE id=?
            """,
            (
                outreach_db.SEND_STATUS_SENDING,
                "provider-123",
                "2020-01-01T00:00:00+00:00",
                send["id"],
            ),
        )

    recovered = outreach_db.recover_stale_sends(stale_after_seconds=30)
    row = outreach_db.get_send_by_task("crm", "thread-proven", "task-proven")

    assert recovered["sent"] == 1
    assert row["status"] == outreach_db.SEND_STATUS_SENT


def test_fresh_sending_row_is_not_recovered_early():
    with outreach_db.connect() as conn:
        send = outreach_db.enqueue_send(
            conn,
            source_id="crm",
            thread_id="thread-fresh",
            task_id="task-fresh",
            channel="sms",
            payload={"draft_text": "in flight"},
        )
        conn.execute(
            "UPDATE send_queue SET status=?, updated_at=? WHERE id=?",
            (outreach_db.SEND_STATUS_SENDING, outreach_db._now(), send["id"]),
        )

    recovered = outreach_db.recover_stale_sends(stale_after_seconds=300)
    row = outreach_db.get_send_by_task("crm", "thread-fresh", "task-fresh")

    assert recovered == {"sent": 0, "failed": 0}
    assert row["status"] == outreach_db.SEND_STATUS_SENDING
