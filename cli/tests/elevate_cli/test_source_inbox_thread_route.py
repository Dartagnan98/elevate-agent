"""Route-level guard for the contact-card conversation timeline.

The DB builder is covered in ``tests/elevate_cli/data/test_reads.py``; this
suite pins the HTTP contract the card actually consumes, because the bug that
blanked 639 composio-gmail conversations on the 1.2.98 beta box surfaced as an
HTTP 404 ("Unknown source connector: composio-gmail") rather than as a bad
payload — the ValueError → 404 translation in ``source_inbox.py`` is the piece
that turned an empty on-disk connector dir into a dead thread.
"""

import logging

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.data import connect, get_or_create_conversation, record_inbound, upsert_contact
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.web_routes.source_inbox import register_source_inbox_routes


@pytest.fixture(autouse=True)
def _fresh_operational_store(_hermetic_environment):
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def make_client() -> TestClient:
    app = FastAPI()
    router = APIRouter()
    register_source_inbox_routes(router, log=logging.getLogger(__name__))
    app.include_router(router)
    return TestClient(app)


def seed_thread(*, source_id: str, thread_key: str, body: str) -> None:
    with connect() as conn:
        contact = upsert_contact(
            conn,
            display_name="Gmail Lead",
            primary_email="lead@example.com",
            source_key=f"{source_id}:{thread_key}",
        )
        conv = get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id=source_id,
            channel="email",
            thread_key=thread_key,
        )
        record_inbound(
            conn,
            contact_id=contact["id"],
            conversation_id=conv["id"],
            channel="email",
            body=body,
            source_id=source_id,
            thread_key=thread_key,
            ts="2026-07-01T09:00:00+00:00",
        )


def test_composio_thread_returns_200_without_an_on_disk_connector_dir():
    seed_thread(
        source_id="composio-gmail",
        thread_key="19e382b8249066ac",
        body="is the Canada listing still available?",
    )

    resp = make_client().get(
        "/api/source-inbox/thread/composio-gmail/19e382b8249066ac?limit=200",
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["messageCount"] == 1
    assert payload["messages"][0]["text"] == "is the Canada listing still available?"
    assert payload["source"]["label"] == "Composio — gmail"


def test_thread_route_still_404s_for_a_source_nothing_knows_about():
    resp = make_client().get(
        "/api/source-inbox/thread/composio-nowhere/no-such-thread?limit=200",
    )

    assert resp.status_code == 404
    assert "Unknown source connector" in resp.json()["detail"]
