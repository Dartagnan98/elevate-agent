from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    bump_conversation_counters,
    connect,
    get_or_create_conversation,
    record_inbound,
    record_outbound,
    upsert_contact,
)
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data.today import build_today_activity


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _record_inbound(conn, contact, conv, *, body: str, ts: datetime) -> None:
    iso = ts.isoformat()
    record_inbound(
        conn,
        contact_id=contact["id"],
        conversation_id=conv["id"],
        channel="sms",
        body=body,
        source_id="sms-provider",
        thread_key=conv["threadKey"],
        ts=iso,
    )
    bump_conversation_counters(conn, conv["id"], direction="inbound", ts=iso)


def _record_outbound(conn, contact, conv, *, body: str, ts: datetime) -> None:
    iso = ts.isoformat()
    record_outbound(
        conn,
        contact_id=contact["id"],
        conversation_id=conv["id"],
        channel="sms",
        body=body,
        source_id="sms-provider",
        thread_key=conv["threadKey"],
        ts=iso,
    )
    bump_conversation_counters(conn, conv["id"], direction="outbound", ts=iso)


def test_today_activity_counts_events_and_actual_response_time():
    now = datetime(2026, 5, 27, 18, 0, tzinfo=timezone.utc)
    with connect() as conn:
        contact = upsert_contact(
            conn,
            display_name="Cora Client",
            primary_phone="+15550000001",
            source_key="sms:cora",
        )
        conv = get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id="sms-provider",
            channel="sms",
            thread_key="cora-thread",
        )
        _record_inbound(conn, contact, conv, body="Can we see it?", ts=now - timedelta(minutes=30))
        _record_outbound(conn, contact, conv, body="Yes, I can book that.", ts=now - timedelta(minutes=5))

        waiting_contact = upsert_contact(
            conn,
            display_name="Willa Waiting",
            primary_phone="+15550000002",
            source_key="sms:willa",
        )
        waiting_conv = get_or_create_conversation(
            conn,
            contact_id=waiting_contact["id"],
            source_id="sms-provider",
            channel="sms",
            thread_key="willa-thread",
        )
        _record_inbound(conn, waiting_contact, waiting_conv, body="Any update?", ts=now - timedelta(minutes=10))

        activity = build_today_activity(conn, pending_drafts_count=2, now=now)

    pulse = {item["label"]: item for item in activity["pulse"]}
    assert pulse["Leads in today"]["rawValue"] == 2
    assert pulse["Replies out today"]["rawValue"] == 1
    assert pulse["Drafts waiting"]["rawValue"] == 2
    assert pulse["Threads waiting on you"]["rawValue"] == 1
    assert pulse["Median response"]["value"] == "25m"

    current_day = activity["dayBuckets"][-1]
    assert current_day["leadsIn"] == 2
    assert current_day["repliesOut"] == 1

    inbound_hour = (now - timedelta(minutes=30)).hour
    outbound_hour = (now - timedelta(minutes=5)).hour
    assert activity["hourBuckets"][inbound_hour]["leadsIn"] >= 1
    assert activity["hourBuckets"][outbound_hour]["repliesOut"] == 1


def test_today_endpoint_returns_page_snapshot():
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    client = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    response = client.get("/api/today")
    assert response.status_code == 200, response.text
    body = response.json()
    for key in (
        "pulse",
        "hourBuckets",
        "dayBuckets",
        "priority",
        "scheduled",
        "live",
        "running",
        "todayWindow",
    ):
        assert key in body
    assert len(body["hourBuckets"]) == 24
    assert len(body["dayBuckets"]) == 7
