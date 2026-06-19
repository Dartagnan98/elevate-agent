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
