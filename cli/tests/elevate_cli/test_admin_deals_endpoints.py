"""PR-1 Admin Hub deals endpoint tests.

Covers the first deal endpoints:

* ``GET  /api/admin/deals``
* ``POST /api/admin/deals``
* ``POST /api/admin/deals/{id}/move``
* ``POST /api/admin/deals/{id}/toggle``
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import connect, create_deal, list_deal_events
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def client():
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    yield c
    if hasattr(app.state, "bound_host"):
        del app.state.bound_host


def _create(title="Deal", side="listing", current_stage=0):
    with connect() as conn:
        return create_deal(
            conn,
            title=title,
            side=side,
            current_stage=current_stage,
            actor="human:test",
        )


def test_create_deal_endpoint_returns_normalized_row_and_event(client):
    resp = client.post(
        "/api/admin/deals",
        json={
            "title": "123 Main Listing",
            "side": "listing",
            "province": "BC",
            "currentStage": 1,
            "listingAddress": "123 Main St",
            "loftyContactId": "lofty-123",
            "fields": {
                "pep": True,
                "signing_authority": "seller",
                "rush_file": "yes",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "123 Main Listing"
    assert body["side"] == "listing"
    assert body["status"] == "active"
    assert body["currentStage"] == 1
    assert body["listingAddress"] == "123 Main St"
    assert body["loftyContactId"] == "lofty-123"
    assert body["pep"] is True
    assert body["signingAuthority"] == "seller"
    assert body["extraToggles"] == {"rush_file": "yes"}

    with connect() as conn:
        events = list_deal_events(conn, body["id"])
    assert len(events) == 1
    assert events[0]["kind"] == "created"
    assert events[0]["actor"] == "human:web"
    assert events[0]["payload"]["fields"]["rush_file"] == "yes"


def test_get_deals_filters_by_side(client):
    listing = _create(title="Listing deal", side="listing")
    buyer = _create(title="Buyer deal", side="buyer")

    resp = client.get("/api/admin/deals?side=buyer")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    ids = {d["id"] for d in body["items"]}
    assert buyer["id"] in ids
    assert listing["id"] not in ids


def test_move_deal_endpoint_persists_stage_and_event(client):
    deal = _create(title="Move me", current_stage=1)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/move",
        json={"toStage": 3},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == deal["id"]
    assert body["currentStage"] == 3

    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    assert events[0]["kind"] == "stage_transition"
    assert events[0]["actor"] == "human:web"
    assert events[0]["fromStage"] == 1
    assert events[0]["toStage"] == 3


def test_toggle_deal_endpoint_persists_named_and_checklist_fields(client):
    deal = _create(title="Toggle me")

    named = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "multiple_offers", "value": True},
    )
    assert named.status_code == 200, named.text
    assert named.json()["multipleOffers"] is True

    checklist = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "draft-cma-followup", "value": True},
    )
    assert checklist.status_code == 200, checklist.text
    assert checklist.json()["extraToggles"]["draft-cma-followup"] is True

    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    toggle_events = [event for event in events if event["kind"] == "toggle_change"]
    assert len(toggle_events) == 2
    assert {event["fieldName"] for event in toggle_events} == {
        "multiple_offers",
        "draft-cma-followup",
    }


def test_move_and_toggle_unknown_deal_return_404(client):
    move = client.post("/api/admin/deals/no-such-deal/move", json={"toStage": 2})
    toggle = client.post(
        "/api/admin/deals/no-such-deal/toggle",
        json={"field": "multiple_offers", "value": True},
    )

    assert move.status_code == 404
    assert toggle.status_code == 404


def test_get_deals_invalid_side_returns_400(client):
    resp = client.get("/api/admin/deals?side=tenant")
    assert resp.status_code == 400


def test_create_deal_invalid_side_returns_400(client):
    resp = client.post(
        "/api/admin/deals",
        json={"title": "Bad deal", "side": "tenant"},
    )
    assert resp.status_code == 400


def test_admin_deals_requires_session_token():
    """Sanity: the auth middleware blocks unauthenticated calls."""
    from elevate_cli.web_server import app

    unauthed = TestClient(app)
    resp = unauthed.get("/api/admin/deals")
    assert resp.status_code in (401, 403)
