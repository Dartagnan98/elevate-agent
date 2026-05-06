"""Sprint 3 — lifecycle UX endpoint tests.

Covers the eight HTTP endpoints added in Sprint 3:

* ``POST /api/contacts/{id}/classify``
* ``POST /api/contacts/{id}/park``
* ``POST /api/contacts/{id}/unpark``
* ``GET  /api/contacts/active``
* ``GET  /api/admin/contacts``
* ``GET  /api/admin/conflicts``
* ``POST /api/admin/conflicts/{id}/resolve``
* ``GET  /api/admin/signals``
* ``POST /api/admin/signals/{id}/graduate``

Hermetic: ``conftest.py`` redirects ``ELEVATE_HOME`` to a tmp dir so each
test starts with an empty operational.db. The auth middleware requires
``X-Elevate-Session-Token`` — ``_client`` injects the right header.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    add_identity,
    connect,
    record_identity_conflict,
    upsert_contact,
    upsert_lead_signal,
)
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def client():
    """Return a FastAPI TestClient pre-authenticated with the session
    token. Yields so we can clean up app.state between tests."""
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    yield c
    if hasattr(app.state, "bound_host"):
        del app.state.bound_host


def _make_contact(**overrides):
    """Insert a contact via the data module and return its dict."""
    with connect() as conn:
        return upsert_contact(
            conn,
            display_name=overrides.get("display_name", "Test Buyer"),
            primary_email=overrides.get("primary_email", "buyer@example.com"),
            primary_phone=overrides.get("primary_phone"),
            type=overrides.get("type", "unclassified"),
            stage=overrides.get("stage", "cold"),
            source_key=overrides.get("source_key", "lofty-default:lead-1"),
        )


# ─── POST /api/contacts/{id}/classify ──────────────────────────────────


def test_classify_happy_path(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/contacts/{contact['id']}/classify",
        json={"type": "buyer"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == contact["id"]
    assert body["type"] == "buyer"
    assert body["classifiedAt"] is not None


def test_classify_invalid_type_returns_400(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/contacts/{contact['id']}/classify",
        json={"type": "spam"},
    )
    assert resp.status_code == 400
    assert "invalid type" in resp.json()["detail"]


def test_classify_unknown_contact_returns_404(client):
    resp = client.post(
        "/api/contacts/does-not-exist/classify",
        json={"type": "buyer"},
    )
    assert resp.status_code == 404


# ─── POST /api/contacts/{id}/park & unpark ─────────────────────────────


def test_park_happy_path(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/contacts/{contact['id']}/park",
        json={"reason": "wrong number"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stage"] == "parked"
    assert body["parkedReason"] == "wrong number"


def test_park_empty_reason_returns_400(client):
    contact = _make_contact()
    resp = client.post(
        f"/api/contacts/{contact['id']}/park",
        json={"reason": "   "},
    )
    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"]


def test_park_unknown_contact_returns_404(client):
    resp = client.post(
        "/api/contacts/does-not-exist/park",
        json={"reason": "wrong number"},
    )
    assert resp.status_code == 404


def test_unpark_returns_active(client):
    contact = _make_contact(stage="parked")
    # ``upsert_contact`` doesn't set parked_reason; use park first to seed it.
    client.post(
        f"/api/contacts/{contact['id']}/park",
        json={"reason": "duplicate"},
    )
    resp = client.post(f"/api/contacts/{contact['id']}/unpark")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stage"] == "active"
    assert body["parkedReason"] is None


def test_unpark_unknown_contact_returns_404(client):
    resp = client.post("/api/contacts/does-not-exist/unpark")
    assert resp.status_code == 404


# ─── GET /api/contacts/active ──────────────────────────────────────────


def test_active_filters_to_active_and_first_touched(client):
    a = _make_contact(display_name="A", stage="active", source_key="src:a")
    b = _make_contact(display_name="B", stage="first_touched", source_key="src:b")
    c = _make_contact(display_name="C", stage="cold", source_key="src:c")
    d = _make_contact(display_name="D", stage="parked", source_key="src:d")

    resp = client.get("/api/contacts/active")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert a["id"] in ids
    assert b["id"] in ids
    assert c["id"] not in ids
    assert d["id"] not in ids
    assert body["count"] == len(body["items"])


def test_active_respects_limit(client):
    for i in range(5):
        _make_contact(display_name=f"Lead {i}", stage="active", source_key=f"src:{i}")
    resp = client.get("/api/contacts/active?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


# ─── GET /api/admin/contacts ───────────────────────────────────────────


def test_admin_contacts_default_returns_all(client):
    _make_contact(display_name="A", source_key="src:a")
    _make_contact(display_name="B", type="buyer", source_key="src:b")
    _make_contact(display_name="C", type="listing", source_key="src:c")
    resp = client.get("/api/admin/contacts")
    assert resp.status_code == 200
    assert resp.json()["count"] == 3


def test_admin_contacts_buyers_tab(client):
    _make_contact(type="unclassified", source_key="src:a")
    _make_contact(type="buyer", source_key="src:b")
    _make_contact(type="buyer", source_key="src:c")
    _make_contact(type="listing", source_key="src:d")
    resp = client.get("/api/admin/contacts?tab=buyers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert all(item["type"] == "buyer" for item in body["items"])
    assert body["tab"] == "buyers"


def test_admin_contacts_parked_tab(client):
    _make_contact(stage="active", source_key="src:a")
    _make_contact(stage="parked", source_key="src:b")
    resp = client.get("/api/admin/contacts?tab=parked")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["stage"] == "parked"


def test_admin_contacts_unknown_tab_returns_400(client):
    resp = client.get("/api/admin/contacts?tab=ghosts")
    assert resp.status_code == 400


def test_admin_contacts_explicit_filters_override_tab(client):
    _make_contact(type="buyer", stage="active", source_key="src:a")
    _make_contact(type="buyer", stage="dead", source_key="src:b")
    # Tab=buyers narrows to type=buyer; ?stage=dead narrows further.
    resp = client.get("/api/admin/contacts?tab=buyers&stage=dead")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["stage"] == "dead"


# ─── GET /api/admin/conflicts + resolve ────────────────────────────────


def _seed_conflict():
    """Create two contacts whose email collides → one identity_conflict."""
    with connect() as conn:
        a = upsert_contact(
            conn, display_name="A", primary_email="dup@example.com",
            source_key="lofty-default:dup-a",
        )
        b = upsert_contact(
            conn, display_name="B", primary_email="dup@example.com",
            source_key="lofty-default:dup-b",
        )
        # Attach the colliding email to A first, then attempt B → records conflict
        add_identity(
            conn, contact_id=a["id"], kind="email",
            value="dup@example.com", source_id="lofty-default",
        )
        add_identity(
            conn, contact_id=b["id"], kind="email",
            value="dup@example.com", source_id="lofty-default",
        )
        # add_identity already records conflict on the second collision; if it
        # didn't (e.g. dedup logic), explicitly seed one for the test.
        rows = conn.execute(
            "SELECT id FROM identity_conflicts WHERE resolved_at IS NULL"
        ).fetchall()
        if not rows:
            record_identity_conflict(
                conn, kind="email", value="dup@example.com",
                candidate_contact_ids=[a["id"], b["id"]],
                reason="multiple_matches",
            )
            rows = conn.execute(
                "SELECT id FROM identity_conflicts WHERE resolved_at IS NULL"
            ).fetchall()
        return a, b, rows[0]["id"]


def test_admin_conflicts_lists_open(client):
    _seed_conflict()
    resp = client.get("/api/admin/conflicts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    assert body["items"][0]["resolvedAt"] is None


def test_admin_conflict_resolve_kept_separate(client):
    _, _, conflict_id = _seed_conflict()
    resp = client.post(
        f"/api/admin/conflicts/{conflict_id}/resolve",
        json={"resolution": "kept_separate"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolution"] == "kept_separate"
    assert body["resolvedAt"] is not None


def test_admin_conflict_resolve_invalid_returns_400(client):
    _, _, conflict_id = _seed_conflict()
    resp = client.post(
        f"/api/admin/conflicts/{conflict_id}/resolve",
        json={"resolution": "fight_to_the_death"},
    )
    assert resp.status_code == 400


def test_admin_conflict_resolve_unknown_returns_404(client):
    resp = client.post(
        "/api/admin/conflicts/no-such-id/resolve",
        json={"resolution": "kept_separate"},
    )
    assert resp.status_code == 404


# ─── GET /api/admin/signals + graduate ─────────────────────────────────


def _seed_signal(source_id: str = "pcs", native_id: str = "buyer-7", **payload):
    with connect() as conn:
        signal = upsert_lead_signal(
            conn,
            source_id=source_id,
            source_native_id=native_id,
            payload=payload or {"score": 81, "tier": "HOT"},
            name=payload.get("name", "Test PCS"),
        )
        return signal


def test_admin_signals_lists_open(client):
    _seed_signal()
    resp = client.get("/api/admin/signals")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["graduatedAt"] is None


def test_admin_signals_filters_by_source(client):
    _seed_signal(source_id="pcs", native_id="buyer-1")
    _seed_signal(source_id="lofty-default", native_id="buyer-2")
    resp = client.get("/api/admin/signals?sourceId=pcs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["sourceId"] == "pcs"


def test_signal_graduate_happy_path(client):
    contact = _make_contact()
    signal = _seed_signal()
    resp = client.post(
        f"/api/admin/signals/{signal['id']}/graduate",
        json={"contactId": contact["id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["graduatedAt"] is not None
    assert body["graduatedToContactId"] == contact["id"]


def test_signal_graduate_unknown_signal_returns_404(client):
    contact = _make_contact()
    resp = client.post(
        "/api/admin/signals/no-such-signal/graduate",
        json={"contactId": contact["id"]},
    )
    assert resp.status_code == 404


def test_signal_graduate_unknown_contact_returns_404(client):
    signal = _seed_signal()
    resp = client.post(
        f"/api/admin/signals/{signal['id']}/graduate",
        json={"contactId": "ghost"},
    )
    assert resp.status_code == 404


def test_signal_graduate_missing_contact_id_returns_400(client):
    signal = _seed_signal()
    resp = client.post(
        f"/api/admin/signals/{signal['id']}/graduate",
        json={"contactId": ""},
    )
    assert resp.status_code == 400


# ─── Auth gating ───────────────────────────────────────────────────────


def test_no_token_returns_401():
    """Sanity check — the auth middleware refuses unauthenticated calls
    to a Sprint 3 endpoint. Uses a bare TestClient with no session header."""
    from elevate_cli.web_server import app

    naked = TestClient(app)
    resp = naked.get("/api/admin/contacts")
    assert resp.status_code == 401
