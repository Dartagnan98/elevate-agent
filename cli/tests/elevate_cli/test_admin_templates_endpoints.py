"""Sprint 5B — /admin/templates endpoint tests.

Covers the five HTTP endpoints from Sprint 5B:

* ``GET  /api/admin/templates`` (tab=live|proposed|retired)
* ``POST /api/admin/templates/{id}/approve``
* ``POST /api/admin/templates/{id}/reject``
* ``POST /api/admin/templates/{id}/edit``
* ``POST /api/admin/templates/{id}/retire``
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    approve_template,
    connect,
    propose_template,
    retire_template,
)
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


def _propose(name="t", lane="new-outreach", body="hi", channel="any"):
    with connect() as conn:
        return propose_template(
            conn, lane=lane, name=name, body=body, channel=channel,
            origin="ai_oneoff", actor="agent:claude",
        )


def _approve(template_id):
    with connect() as conn:
        return approve_template(conn, template_id, actor="human:dartagnan")


def _retire(template_id):
    with connect() as conn:
        return retire_template(conn, template_id, actor="human:dartagnan")


# ─── GET /api/admin/templates ──────────────────────────────────────────


def test_get_templates_live_returns_leaderboard_buckets(client):
    proposed = _propose(name="for-live")
    _approve(proposed["id"])

    resp = client.get("/api/admin/templates?tab=live")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tab"] == "live"
    assert "authoritative" in body
    assert "trial" in body
    # Brand-new live template lands in trial.
    trial_ids = {r["lineageRootId"] for r in body["trial"]}
    assert proposed["id"] in trial_ids


def test_get_templates_default_tab_is_live(client):
    resp = client.get("/api/admin/templates")
    assert resp.status_code == 200
    assert resp.json()["tab"] == "live"


def test_get_templates_proposed_returns_unapproved(client):
    proposed = _propose(name="awaiting")
    resp = client.get("/api/admin/templates?tab=proposed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tab"] == "proposed"
    ids = {t["id"] for t in body["items"]}
    assert proposed["id"] in ids


def test_get_templates_retired_returns_only_retired(client):
    live_proposed = _propose(name="will-retire")
    live = _approve(live_proposed["id"])
    _retire(live["id"])
    still_live_proposed = _propose(name="alive")
    _approve(still_live_proposed["id"])

    resp = client.get("/api/admin/templates?tab=retired")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tab"] == "retired"
    ids = {t["id"] for t in body["items"]}
    assert live["id"] in ids
    assert still_live_proposed["id"] not in ids


def test_get_templates_unknown_tab_returns_400(client):
    resp = client.get("/api/admin/templates?tab=nonsense")
    assert resp.status_code == 400


# ─── POST /api/admin/templates/{id}/approve ────────────────────────────


def test_approve_endpoint_flips_proposed_to_live(client):
    proposed = _propose(name="approve-me")
    resp = client.post(f"/api/admin/templates/{proposed['id']}/approve")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "live"
    assert body["active"] is True
    assert body["approvedBy"] == "human:web"


def test_approve_endpoint_404_for_missing_template(client):
    resp = client.post("/api/admin/templates/does-not-exist/approve")
    assert resp.status_code == 404


def test_approve_endpoint_400_when_already_retired(client):
    proposed = _propose(name="dead-on-arrival")
    live = _approve(proposed["id"])
    _retire(live["id"])
    resp = client.post(f"/api/admin/templates/{live['id']}/approve")
    assert resp.status_code == 400


# ─── POST /api/admin/templates/{id}/reject ─────────────────────────────


def test_reject_endpoint_marks_retired_with_reason(client):
    proposed = _propose(name="rejectable")
    resp = client.post(
        f"/api/admin/templates/{proposed['id']}/reject",
        json={"reason": "tone is off"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "retired"
    assert body["active"] is False
    assert "tone is off" in (body["rationale"] or "")


def test_reject_endpoint_400_on_empty_reason(client):
    proposed = _propose(name="needs-reason")
    resp = client.post(
        f"/api/admin/templates/{proposed['id']}/reject",
        json={"reason": "   "},
    )
    assert resp.status_code == 400


def test_reject_endpoint_404_for_missing_template(client):
    resp = client.post(
        "/api/admin/templates/no-such-id/reject",
        json={"reason": "x"},
    )
    assert resp.status_code == 404


# ─── POST /api/admin/templates/{id}/edit ───────────────────────────────


def test_edit_endpoint_bumps_version_and_supersedes(client):
    proposed = _propose(name="for-edit", body="v1")
    live = _approve(proposed["id"])
    resp = client.post(
        f"/api/admin/templates/{live['id']}/edit",
        json={"body": "v2 body"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["body"] == "v2 body"
    assert body["status"] == "live"
    assert body["version"] == live["version"] + 1
    assert body["parentTemplateId"] == live["id"]
    # Old row should now be superseded.
    with connect() as conn:
        from elevate_cli.data import get_template
        old = get_template(conn, live["id"])
    assert old["status"] == "superseded"


def test_edit_endpoint_400_on_empty_body(client):
    proposed = _propose(name="empty-edit")
    live = _approve(proposed["id"])
    resp = client.post(
        f"/api/admin/templates/{live['id']}/edit",
        json={"body": ""},
    )
    assert resp.status_code == 400


def test_edit_endpoint_404_for_missing_template(client):
    resp = client.post(
        "/api/admin/templates/missing/edit",
        json={"body": "x"},
    )
    assert resp.status_code == 404


# ─── POST /api/admin/templates/{id}/retire ─────────────────────────────


def test_retire_endpoint_soft_deprecates(client):
    proposed = _propose(name="old-template")
    live = _approve(proposed["id"])
    resp = client.post(f"/api/admin/templates/{live['id']}/retire")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "retired"
    assert body["active"] is False


def test_retire_endpoint_404_for_missing_template(client):
    resp = client.post("/api/admin/templates/nope/retire")
    assert resp.status_code == 404


# ─── Auth gating ───────────────────────────────────────────────────────


def test_admin_templates_requires_session_token():
    """Sanity: the auth middleware blocks unauthenticated calls."""
    from elevate_cli.web_server import app

    unauthed = TestClient(app)
    resp = unauthed.get("/api/admin/templates")
    assert resp.status_code in (401, 403)
