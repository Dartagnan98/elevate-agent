"""PR-2 Admin Hub dispatcher tests.

Covers the registry CRUD endpoints, the run-log endpoint, and the hook
into ``data.deals`` (move_deal_stage, set_deal_toggle).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    connect,
    create_action,
    create_deal,
    list_action_runs,
    move_deal_stage,
    set_deal_toggle,
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


# ── Endpoint auth ────────────────────────────────────────────────────────


def test_admin_actions_requires_session_token():
    from elevate_cli.web_server import app

    unauthed = TestClient(app)
    resp = unauthed.get("/api/admin/actions")
    assert resp.status_code in (401, 403)
    resp2 = unauthed.get("/api/admin/action-runs")
    assert resp2.status_code in (401, 403)


# ── Registry CRUD ────────────────────────────────────────────────────────


def test_create_action_returns_normalized_row(client):
    resp = client.post(
        "/api/admin/actions",
        json={
            "name": "Listed → marketing/just_listed",
            "trigger": "stage_entry",
            "skill": "marketing",
            "side": "listing",
            "toStage": 5,
            "skillArgs": {"phase": "just_listed"},
            "provinceFilter": ["BC"],
            "priority": 10,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Listed → marketing/just_listed"
    assert body["trigger"] == "stage_entry"
    assert body["skill"] == "marketing"
    assert body["side"] == "listing"
    assert body["toStage"] == 5
    assert body["skillArgs"] == {"phase": "just_listed"}
    assert body["provinceFilter"] == ["BC"]
    assert body["enabled"] is True
    assert body["version"] == 1


def test_list_actions_filters_by_trigger(client):
    with connect() as conn:
        create_action(
            conn,
            name="entry rule",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
        )
        create_action(
            conn,
            name="toggle rule",
            trigger="toggle_change",
            skill="webforms",
            field_key="multiple_offers",
        )

    resp = client.get("/api/admin/actions?trigger=toggle_change")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["fieldKey"] == "multiple_offers"


def test_update_action_bumps_version(client):
    with connect() as conn:
        action = create_action(
            conn,
            name="orig",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
            priority=0,
        )

    resp = client.patch(
        f"/api/admin/actions/{action['id']}",
        json={"priority": 99, "enabled": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["priority"] == 99
    assert body["enabled"] is False
    assert body["version"] == 2


def test_delete_action_removes_row(client):
    with connect() as conn:
        action = create_action(
            conn,
            name="doomed",
            trigger="stage_entry",
            skill="marketing",
            to_stage=3,
        )

    resp = client.delete(f"/api/admin/actions/{action['id']}")
    assert resp.status_code == 200, resp.text

    follow = client.get("/api/admin/actions")
    assert action["id"] not in {a["id"] for a in follow.json()["items"]}


# ── Validation -----------------------------------------------------------


def test_create_action_rejects_invalid_trigger(client):
    resp = client.post(
        "/api/admin/actions",
        json={"name": "bad", "trigger": "phase_entry", "skill": "marketing"},
    )
    assert resp.status_code == 400


def test_create_action_requires_field_key_for_toggle_change(client):
    resp = client.post(
        "/api/admin/actions",
        json={"name": "bad", "trigger": "toggle_change", "skill": "webforms"},
    )
    assert resp.status_code == 400


# ── Hooks: stage move + toggle flip create run rows ----------------------


def _new_listing_deal():
    with connect() as conn:
        return create_deal(
            conn,
            title="Test listing",
            side="listing",
            actor="human:test",
            current_stage=4,
        )


def test_move_deal_stage_creates_action_run_via_hook():
    deal = _new_listing_deal()
    with connect() as conn:
        action = create_action(
            conn,
            name="just_listed entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
            skill_args={"phase": "just_listed"},
        )

    with connect() as conn:
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test")

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert len(runs) == 1
    run = runs[0]
    assert run["registryId"] == action["id"]
    assert run["dealId"] == deal["id"]
    assert run["status"] == "queued"
    assert run["payload"]["toStage"] == 5
    assert run["payload"]["registryName"] == "just_listed entry"


def test_toggle_change_creates_action_run_via_hook():
    deal = _new_listing_deal()
    with connect() as conn:
        create_action(
            conn,
            name="multiple offers",
            trigger="toggle_change",
            skill="webforms",
            field_key="multiple_offers",
            condition={"multiple_offers": True},
        )

    with connect() as conn:
        set_deal_toggle(
            conn,
            deal["id"],
            field="multiple_offers",
            value=True,
            actor="human:test",
        )

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert len(runs) == 1
    assert runs[0]["payload"]["fieldKey"] == "multiple_offers"
    assert runs[0]["payload"]["fieldNew"] is True


def test_evaluate_skips_when_action_disabled():
    deal = _new_listing_deal()
    with connect() as conn:
        create_action(
            conn,
            name="disabled rule",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
            enabled=False,
        )

    with connect() as conn:
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test")

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert runs == []


def test_evaluate_respects_province_filter():
    deal = _new_listing_deal()  # province defaults to BC
    with connect() as conn:
        create_action(
            conn,
            name="AB-only rule",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
            province_filter=["AB"],
        )

    with connect() as conn:
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test")

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert runs == []
