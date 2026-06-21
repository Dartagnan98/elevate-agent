"""PR-1 Admin Hub deals endpoint tests.

Covers the first deal endpoints:

* ``GET  /api/admin/deals``
* ``POST /api/admin/deals``
* ``POST /api/admin/deals/{id}/move``
* ``POST /api/admin/deals/{id}/toggle``
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    add_deal_contact,
    add_deal_attachment,
    complete_admin_setup,
    connect,
    create_action,
    create_deal,
    evaluate_dispatch,
    get_admin_setup,
    import_listing_workflow_csv,
    import_exp_agent_centre,
    list_action_runs,
    list_deal_attachments,
    province_coverage,
    list_deal_events,
    sync_admin_setup_runtime,
    update_admin_setup,
    upsert_contact,
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
    _complete_admin_setup()
    yield c
    if hasattr(app.state, "bound_host"):
        del app.state.bound_host


def _complete_admin_setup():
    def item_payload(item):
        value = None
        if item["key"] in {"approval_channel", "email", "calendar", "drive", "crm"}:
            value = {
                "verification": {
                    "checkedAt": "2026-05-07T00:00:00+00:00",
                    "signals": ["test connector verified"],
                }
            }
        elif item["key"] == "browser_workflows":
            value = {
                "mode": "browser-use",
                "notes": "Use saved browser profile for portal tests.",
                "playbooks": {
                    "mls": {"provider": "Matrix", "loginUrl": "https://mls.example", "credentialRef": "test"},
                    "compliance": {"provider": "SkySlope", "loginUrl": "https://skyslope.example", "credentialRef": "test"},
                    "showing": {"provider": "ShowingTime", "loginUrl": "https://showing.example", "credentialRef": "test"},
                },
            }
        elif item["key"] == "photo_processing":
            value = {"provider": "Drive + Nano Banana", "source": "google-drive"}
        return {
            "key": item["key"],
            "status": "manual" if item["key"] == "fintrac_workflow" else "configured",
            "provider": "test",
            "value": value,
        }

    with connect() as conn:
        setup = get_admin_setup(conn)
        update_admin_setup(
            conn,
            profile={
                "realtorLegalName": "Test Realtor",
                "brokerageName": "Test Brokerage",
                "province": "BC",
                "approvalChannel": "telegram:test",
                "regionalMemory": {"notes": "Test regional memory"},
            },
            items=[
                item_payload(item)
                for item in setup["items"]
                if item["required"]
            ],
        )
        complete_admin_setup(conn)


def test_admin_setup_gate_blocks_deal_creation_until_ready():
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    resp = c.post("/api/admin/deals", json={"title": "Blocked", "side": "listing"})
    assert resp.status_code == 409
    body = resp.json()
    assert "Admin setup" in body["detail"]["message"]
    assert body["detail"]["setup"]["complete"] is False


def test_admin_setup_complete_requires_browser_workflow_contract():
    """Post ``9a4d1a349``: runtime-verification double-gate is dropped, so
    typed-only "configured" rows for email/calendar/drive/crm count as
    ready. The browser_workflows item still requires a playbook contract
    (provider + access hint per portal), and missing that blocks
    completion."""
    with connect() as conn:
        setup = get_admin_setup(conn)
        update_admin_setup(
            conn,
            profile={
                "realtorLegalName": "Test Realtor",
                "brokerageName": "Test Brokerage",
                "province": "BC",
                "approvalChannel": "telegram:test",
                "regionalMemory": {"notes": "Test regional memory"},
            },
            items=[
                {
                    "key": item["key"],
                    "status": "manual" if item["key"] == "fintrac_workflow" else "configured",
                    "provider": "typed-only",
                }
                for item in setup["items"]
                if item["required"]
            ],
        )
        unverified = get_admin_setup(conn)
        assert unverified["missingRequiredKeys"] == ["browser_workflows"]
        readiness = {item["key"]: item for item in unverified["readiness"]}
        assert readiness["browser_workflows"]["state"] == "incomplete_browser_playbook"
        assert readiness["identity_profile"]["ready"] is True
        assert readiness["email"]["ready"] is True
        with pytest.raises(ValueError):
            complete_admin_setup(conn)


def test_admin_setup_browser_workflows_require_login_secret():
    """Portal notes/usernames are not enough to mark login automation ready."""
    with connect() as conn:
        setup = get_admin_setup(conn)
        update_admin_setup(
            conn,
            profile={
                "realtorLegalName": "Test Realtor",
                "brokerageName": "Test Brokerage",
                "province": "BC",
                "approvalChannel": "telegram:test",
                "regionalMemory": {"notes": "Test regional memory"},
            },
            items=[
                {
                    "key": item["key"],
                    "status": "manual" if item["key"] == "fintrac_workflow" else "configured",
                    "provider": "typed-only",
                    "value": {
                        "mode": "browser-use",
                        "notes": "MFA is sometimes required.",
                        "playbooks": {
                            "mls": {
                                "provider": "Matrix",
                                "loginUrl": "https://mls.example",
                                "loginEmail": "agent@example.test",
                                "notes": "Use saved profile.",
                            },
                            "compliance": {
                                "provider": "SkySlope",
                                "loginUrl": "https://skyslope.example",
                                "loginEmail": "agent@example.test",
                                "notes": "Use saved profile.",
                            },
                            "showing": {
                                "provider": "ShowingTime",
                                "loginUrl": "https://showing.example",
                                "loginEmail": "agent@example.test",
                                "notes": "Use saved profile.",
                            },
                        },
                    }
                    if item["key"] == "browser_workflows"
                    else None,
                }
                for item in setup["items"]
                if item["required"]
            ],
        )
        unverified = get_admin_setup(conn)
        assert unverified["missingRequiredKeys"] == ["browser_workflows"]
        readiness = {item["key"]: item for item in unverified["readiness"]}
        assert readiness["browser_workflows"]["action"].startswith("Add provider")
        with pytest.raises(ValueError):
            complete_admin_setup(conn)


def test_admin_setup_runtime_sync_builds_browser_playbook_from_env_credentials():
    with connect() as conn:
        setup = sync_admin_setup_runtime(
            conn,
            env_values={
                "MLS_LOGIN_URL": "https://mls.example",
                "MLS_USERNAME": "mls-user",
                "MLS_PASSWORD": "mls-secret",
                "SKYSLOPE_LOGIN_URL": "https://skyslope.example",
                "SKYSLOPE_USERNAME": "sky-user",
                "SKYSLOPE_PASSWORD": "sky-secret",
                "SHOWINGTIME_LOGIN_URL": "https://showing.example",
                "SHOWINGTIME_USERNAME": "show-user",
                "SHOWINGTIME_PASSWORD": "show-secret",
            },
        )

    by_key = {item["key"]: item for item in setup["items"]}
    assert by_key["mls"]["status"] == "configured"
    assert by_key["compliance_platform"]["status"] == "configured"
    assert by_key["showing_platform"]["status"] == "configured"
    assert by_key["browser_workflows"]["status"] == "configured"
    playbooks = by_key["browser_workflows"]["value"]["playbooks"]
    assert playbooks["compliance"]["credentialRef"] == "env:SKYSLOPE_PASSWORD"
    assert "sky-secret" not in str(by_key["browser_workflows"]["value"])


def test_admin_setup_endpoint_mirrors_skyslope_portal_credentials_to_env():
    from elevate_cli.config import get_env_value
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    resp = c.put(
        "/api/admin/setup",
        json={
            "items": [
                {
                    "key": "browser_workflows",
                    "status": "configured",
                    "provider": "browser-use",
                    "value": {
                        "mode": "browser-use",
                        "playbooks": {
                            "mls": {
                                "provider": "Matrix",
                                "loginUrl": "https://mls.example",
                                "loginEmail": "mls-user",
                                "loginPassword": "mls-secret",
                            },
                            "compliance": {
                                "provider": "SkySlope",
                                "loginUrl": "https://skyslope.example",
                                "loginEmail": "sky-user",
                                "loginPassword": "sky-secret",
                            },
                            "showing": {
                                "provider": "ShowingTime",
                                "loginUrl": "https://showing.example",
                                "loginEmail": "show-user",
                                "loginPassword": "show-secret",
                            },
                        },
                    },
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert get_env_value("SKYSLOPE_USERNAME") == "sky-user"
    assert get_env_value("SKYSLOPE_USER") == "sky-user"
    assert get_env_value("SKYSLOPE_PASSWORD") == "sky-secret"
    assert get_env_value("SKYSLOPE_PASS") == "sky-secret"
    browser_item = next(item for item in resp.json()["items"] if item["key"] == "browser_workflows")
    playbooks = browser_item["value"]["playbooks"]
    assert playbooks["compliance"]["credentialRef"] == "env:SKYSLOPE_PASSWORD"
    assert "sky-secret" not in str(browser_item["value"])


def test_admin_setup_runtime_sync_marks_real_connector_signals():
    with connect() as conn:
        setup = sync_admin_setup_runtime(
            conn,
            source_connectors={
                "connectors": [
                    {"id": "crm", "label": "Lofty", "connected": True, "state": "connected"},
                    {"id": "forms-signing", "label": "WEBForms + signing", "sourceExists": True, "state": "needs_operator"},
                ],
            },
            composio_accounts={
                "ok": True,
                "data": {
                    "items": [
                        {"status": "ACTIVE", "toolkit": {"slug": "gmail"}},
                    ],
                },
            },
            env_values={
                "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN": "token",
                "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL": "12345",
            },
        )

    by_key = {item["key"]: item for item in setup["items"]}
    assert by_key["approval_channel"]["status"] == "connected"
    assert by_key["approval_channel"]["provider"] == "telegram"
    assert by_key["email"]["status"] == "connected"
    assert by_key["crm"]["status"] == "connected"
    assert by_key["forms_provider"]["status"] == "configured"
    assert by_key["signing_provider"]["status"] == "configured"


def test_admin_setup_writes_sanitized_agent_memory_snapshot():
    _complete_admin_setup()

    with connect() as conn:
        setup = update_admin_setup(
            conn,
            items=[
                {
                    "key": "photo_processing",
                    "status": "configured",
                    "provider": "Drive + Nano Banana",
                    "value": {
                        "provider": "Drive + Nano Banana",
                        "source": "google-drive",
                        "notes": "api_key=banana-secret",
                    },
                }
            ],
        )

    memory = setup["memory"]
    assert memory["synced"] is True
    path = Path(memory["path"])
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Admin onboarding memory" in content
    assert "Embedded Postgres is the operational source of truth" in content
    assert "Matrix" in content
    assert "SkySlope" in content
    assert "ShowingTime" in content
    assert "Drive + Nano Banana" in content
    assert "[redacted secret reference]" in content
    assert "banana-secret" not in content


def test_admin_setup_verify_endpoint_uses_agent_telegram_env(monkeypatch):
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "12345")
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    resp = c.post("/api/admin/setup/verify")
    assert resp.status_code == 200, resp.text
    by_key = {item["key"]: item for item in resp.json()["items"]}
    assert by_key["approval_channel"]["status"] == "connected"
    assert by_key["approval_channel"]["provider"] == "telegram"


def _create(title="Deal", side="listing", current_stage=0, dispatch_initial_stage=True):
    with connect() as conn:
        return create_deal(
            conn,
            title=title,
            side=side,
            current_stage=current_stage,
            actor="human:test",
            dispatch_initial_stage=dispatch_initial_stage,
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
                "mlsNumber": "10345678",
                "listPrice": 799000,
                "yearBuilt": 2014,
                "rush_file": "yes",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "123 Main Listing"
    assert body["side"] == "listing"
    assert body["status"] == "active"
    assert body["province"] == "BC"
    assert body["board"] is None
    assert body["market"] is None
    assert body["currentStage"] == 1
    assert body["listingAddress"] == "123 Main St"
    assert body["loftyContactId"] == "lofty-123"
    assert body["pep"] is True
    assert body["signingAuthority"] == "seller"
    assert body["mlsNumber"] == "10345678"
    assert body["listPrice"] == 799000
    assert body["yearBuilt"] == 2014
    assert body["extraToggles"] == {"rush_file": "yes"}

    with connect() as conn:
        events = list_deal_events(conn, body["id"])
    assert len(events) == 1
    assert events[0]["kind"] == "created"
    assert events[0]["actor"] == "human:web"
    assert events[0]["payload"]["fields"]["rush_file"] == "yes"


def test_create_deal_can_suppress_initial_stage_dispatch_for_imports(client):
    with connect() as conn:
        create_action(
            conn,
            name="stage four entry",
            trigger="stage_entry",
            skill="listing-build",
            side="listing",
            to_stage=4,
        )

    suppressed = client.post(
        "/api/admin/deals",
        json={
            "title": "Imported live listing",
            "side": "listing",
            "currentStage": 4,
            "suppressInitialDispatch": True,
        },
    )
    assert suppressed.status_code == 200, suppressed.text

    with connect() as conn:
        assert list_action_runs(conn, deal_id=suppressed.json()["id"]) == []

    live_create = client.post(
        "/api/admin/deals",
        json={
            "title": "Intentional live listing",
            "side": "listing",
            "currentStage": 4,
        },
    )
    assert live_create.status_code == 200, live_create.text

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=live_create.json()["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["cronJobId"]
    assert runs[0]["payload"]["toStage"] == 4


def test_admin_deal_scorecard_surfaces_active_run_state(client):
    with connect() as conn:
        create_action(
            conn,
            name="Live card action",
            trigger="stage_entry",
            skill="listing-build",
            side="listing",
            to_stage=2,
        )

    created = client.post(
        "/api/admin/deals",
        json={"title": "Live card deal", "side": "listing", "currentStage": 2},
    )
    assert created.status_code == 200, created.text

    listed = client.get("/api/admin/deals")
    assert listed.status_code == 200, listed.text
    item = next(row for row in listed.json()["items"] if row["id"] == created.json()["id"])
    scorecard = item["scorecard"]
    assert scorecard["activeRunCount"] == 1
    assert scorecard["runningRunCount"] == 1
    assert scorecard["waitingHumanCount"] == 0
    assert scorecard["activeRunLabel"] == "Live card action"
    assert scorecard["activeRunStatus"] == "running"


def test_admin_jurisdiction_defaults_to_generic_and_deals_can_stamp_package_values(client):
    resp = client.get("/api/admin/jurisdiction")
    assert resp.status_code == 200, resp.text
    jurisdiction = resp.json()
    assert jurisdiction == {
        "country": "CA",
        "province": "BC",
        "market": "",
        "packageKey": "generic.real-estate",
    }

    created = client.post(
        "/api/admin/deals",
        json={"title": "Calgary request", "side": "listing", "province": "AB", "board": "CREB", "market": "Calgary"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["province"] == "AB"
    assert body["board"] == "CREB"
    assert body["market"] == "Calgary"

    switched = client.get("/api/admin/deals?province=AB")
    assert switched.status_code == 200, switched.text
    assert switched.json()["count"] == 1

    context = client.get(f"/api/deals/{body['id']}/context")
    assert context.status_code == 200, context.text
    assert context.json()["dealFlow"]["packageKey"] == "ca.ab"
    assert context.json()["dealFlow"]["localOverrides"]["provinceLabel"] == "Alberta"


def test_admin_jurisdiction_update_sets_default_flow_for_new_deals(client):
    updated = client.put("/api/admin/jurisdiction", json={"province": "ON", "market": "Toronto"})
    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "country": "CA",
        "province": "ON",
        "market": "Toronto",
        "packageKey": "ca.on",
    }

    created = client.post("/api/admin/deals", json={"title": "Toronto seller", "side": "listing"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["province"] == "ON"
    assert body["market"] == "Toronto"

    context = client.get(f"/api/deals/{body['id']}/context")
    assert context.status_code == 200, context.text
    assert context.json()["dealFlow"]["packageKey"] == "ca.on"
    assert context.json()["dealFlow"]["localOverrides"]["provinceLabel"] == "Ontario"

    pei = client.put("/api/admin/jurisdiction", json={"province": "PEI", "market": ""})
    assert pei.status_code == 200, pei.text
    assert pei.json()["packageKey"] == "ca.pei"
    assert pei.json()["province"] == "PEI"


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


def test_move_deal_endpoint_blocks_incomplete_forward_stage_move(client):
    deal = _create(title="Move me", current_stage=1)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/move",
        json={"toStage": 3},
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["message"] == "deal phase gate is blocked"
    assert detail["gate"]["stage"] == 1
    # Stage 1 is CMA / Evaluation — its recommended list price gates the advance.
    assert any(item["field"] == "listPrice" for item in detail["gate"]["missingFields"])


def test_move_deal_endpoint_reports_clear_gate_skip_as_wrong_target(client):
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Skip me",
            side="listing",
            current_stage=1,
            actor="human:test",
            fields={
                "cma_pdf_ready": True,
                "pricing_story_approved": True,
                "client_yes_to_listing": True,
                "workflow_cma_date_requested": "2026-05-01",
            },
            dispatch_initial_stage=False,
        )
        add_deal_attachment(
            conn,
            deal["id"],
            kind="cma_report",
            file_path="/tmp/cma.pdf",
            summary="CMA ready",
            actor="human:test",
        )
        conn.execute("UPDATE deals SET list_price=? WHERE id=?", (799000, deal["id"]))

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/move",
        json={"toStage": 3},
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["message"] == "deal must move through the next phase gate"
    assert detail["gate"]["stage"] == 1
    assert detail["gate"]["canAdvance"] is True
    assert detail["gate"]["nextStage"] == 2
    assert detail["gate"]["targetStage"] == 3


def test_force_move_deal_endpoint_persists_stage_and_audits_override(client):
    deal = _create(title="Force move me", current_stage=1)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/move",
        json={"toStage": 3, "force": True},
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
    assert events[0]["payload"]["force"] is True


def test_collapse_listing_deal_resets_offer_state_and_buyer_memory(client):
    with connect() as conn:
        buyer = upsert_contact(
            conn,
            display_name="Ava Buyer",
            primary_email="ava@example.com",
            type="buyer",
            stage="active",
        )
        deal = create_deal(
            conn,
            title="Accepted seller deal",
            side="listing",
            current_stage=6,
            actor="human:test",
            listing_address="700 Collingwood Drive",
            fields={
                "offerPrice": 650000,
                "depositAmount": 20000,
                "offerAcceptedAt": "2026-06-01",
                "completionDate": "2026-07-15",
                "buyer_memory_note": "Clear this after collapse",
                "accepted_offer_summary": "Clear this too",
            },
            dispatch_initial_stage=False,
        )
        add_deal_contact(conn, deal["id"], role="buyer", contact_id=buyer["id"], actor="human:test")

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/collapse",
        json={"side": "listing"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["targetStage"] == 5
    assert body["removedBuyerContacts"] == 1
    assert set(body["removedExtraKeys"]) == {"accepted_offer_summary", "buyer_memory_note"}
    collapsed = body["deal"]
    assert collapsed["currentStage"] == 5
    assert collapsed["offerPrice"] is None
    assert collapsed["depositAmount"] is None
    assert collapsed["offerAcceptedAt"] is None
    assert collapsed["completionDate"] is None
    assert collapsed["extraToggles"]["deal_collapsed"] is True
    assert collapsed["extraToggles"]["collapsed_reset_target_stage"] == 5
    assert "buyer_memory_note" not in collapsed["extraToggles"]

    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM deal_contacts WHERE deal_id=?", (deal["id"],)).fetchone()[0] == 0
        events = list_deal_events(conn, deal["id"])
    assert any(
        event["kind"] == "stage_transition"
        and event["fromStage"] == 6
        and event["toStage"] == 5
        for event in events
    )
    assert any(
        event["kind"] == "toggle_change"
        and event["fieldName"] == "deal_collapsed_reset"
        and event["payload"]["removedBuyerContacts"]
        for event in events
    )


def test_collapse_buyer_deal_resets_property_state_to_top_25(client):
    with connect() as conn:
        buyer = upsert_contact(
            conn,
            display_name="Liam Buyer",
            primary_email="liam@example.com",
            type="buyer",
            stage="active",
        )
        deal = create_deal(
            conn,
            title="Buyer accepted offer",
            side="buyer",
            current_stage=2,
            actor="human:test",
            listing_address="742 Mockingbird Lane",
            source_row_id="mls-row-1",
            fields={
                "mlsNumber": "10300001",
                "legalDescription": "Lot 1 Plan TEST",
                "listPrice": 700000,
                "offerPrice": 690000,
                "subjectRemovalDate": "2026-06-10",
                "property_notes": "Clear property-specific memory",
            },
            dispatch_initial_stage=False,
        )
        add_deal_contact(conn, deal["id"], role="buyer", contact_id=buyer["id"], actor="human:test")

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/collapse",
        json={"side": "buyer"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["targetStage"] == 0
    assert body["newTitle"] == "Buyer: Liam Buyer"
    assert body["removedBuyerContacts"] == 0
    assert body["removedExtraKeys"] == ["property_notes"]
    collapsed = body["deal"]
    assert collapsed["title"] == "Buyer: Liam Buyer"
    assert collapsed["currentStage"] == 0
    assert collapsed["listingAddress"] is None
    assert collapsed["sourceRowId"] is None
    assert collapsed["mlsNumber"] is None
    assert collapsed["legalDescription"] is None
    assert collapsed["listPrice"] is None
    assert collapsed["offerPrice"] is None
    assert collapsed["subjectRemovalDate"] is None
    assert collapsed["extraToggles"]["collapsed_reset_target_stage"] == 0
    assert "property_notes" not in collapsed["extraToggles"]


def test_current_workflow_stage_complete_toggle_does_not_bypass_gate(client):
    deal = _create(title="Auto move me", current_stage=4)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "workflow_stage_4_complete", "value": True},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["currentStage"] == 4
    assert body["extraToggles"]["workflow_stage_4_complete"] is True

    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    assert any(event["kind"] == "toggle_change" and event["fieldName"] == "workflow_stage_4_complete" for event in events)
    assert not any(event["kind"] == "stage_transition" for event in events)


def _clear_stage_four_gate(client, deal_id: str):
    # Marketing Go (stage 4): every checklist item + AI/photo fields + photos doc.
    for item_id in (
        "marketing_go_started",
        "photographer_drive_link_received",
        "marketing_go_questions_answered",
        "photo_cleanup_complete",
        "cleaned_photos_saved_to_drive",
        "best_99_matrix_photos_selected",
        "matrix_photos_uploaded",
        "matrix_listing_finished_with_photos",
        "coming_soon_assets_ready",
        "landing_page_ready",
        "launch_copy_social_email_ready",
        "marketing_package_ready_for_approval",
    ):
        ok = client.post(f"/api/admin/deals/{deal_id}/toggle", json={"field": item_id, "value": True})
        assert ok.status_code == 200, ok.text
    for field, value in {
        "workflow_photo_shoot_date": "2026-05-05",
        "workflow_ai_garage_carport": "Garage",
        "workflow_ai_suite_detected": "Not detected",
        "workflow_ai_ac_heat_pump": "Heat pump",
        "workflow_ai_appliances_listed": "Fridge, stove",
        "workflow_ai_flooring_types": "Laminate",
    }.items():
        ok = client.post(f"/api/admin/deals/{deal_id}/toggle", json={"field": field, "value": value})
        assert ok.status_code == 200, ok.text
    attached = client.post(
        f"/api/deals/{deal_id}/attachments",
        json={"kind": "listing_photos", "filePath": "/tmp/listing-photos.zip"},
    )
    assert attached.status_code == 200, attached.text


def test_current_workflow_stage_complete_advances_when_gate_is_clear(client):
    deal = _create(title="Gate clear stage four", current_stage=4)
    _clear_stage_four_gate(client, deal["id"])

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "workflow_stage_4_complete", "value": True},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 5
    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    transition = next(event for event in events if event["kind"] == "stage_transition")
    assert transition["fromStage"] == 4
    assert transition["toStage"] == 5


def test_non_current_workflow_stage_complete_does_not_jump_deal(client):
    deal = _create(title="Stay put", current_stage=5)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "workflow_stage_4_complete", "value": True},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 5
    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    assert not any(event["kind"] == "stage_transition" for event in events)


def test_listing_live_stage_complete_does_not_move_without_accepted_offer(client):
    deal = _create(title="Still active listing", current_stage=5)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "workflow_stage_5_complete", "value": True},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 5
    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    assert not any(event["kind"] == "stage_transition" for event in events)


def _clear_stage_five_gate(client, deal_id: str):
    for field, value in {
        "workflow_just_listed_blast_sent": True,
        "workflow_social_posts_published": True,
        "workflow_flodesk_mailout_sent": True,
        "workflow_lofty_text_blast_sent": True,
        "workflow_stage_5_complete": True,
        "workflow_order_sign_up_date": "2026-05-06",
        "workflow_coming_soon_posts_date": "2026-05-05",
    }.items():
        ok = client.post(f"/api/admin/deals/{deal_id}/toggle", json={"field": field, "value": value})
        assert ok.status_code == 200, ok.text
    fields = client.post(
        f"/api/deals/{deal_id}/fields",
        json={"fields": {"mlsNumber": "10345678", "listingPublishedAt": "2026-05-06"}},
    )
    assert fields.status_code == 200, fields.text


def test_accepted_offer_signal_waits_for_current_phase_gate(client):
    deal = _create(title="Offer accepted", current_stage=5)

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "workflow_accepted_offer_date", "value": "2026-05-06"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 5
    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    assert not any(event["kind"] == "stage_transition" for event in events)


def test_accepted_offer_signal_advances_live_listing_when_gate_is_clear(client):
    deal = _create(title="Offer accepted clear", current_stage=5)
    _clear_stage_five_gate(client, deal["id"])

    resp = client.post(
        f"/api/admin/deals/{deal['id']}/toggle",
        json={"field": "workflow_accepted_offer_date", "value": "2026-05-06"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 6
    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    transition = next(event for event in events if event["kind"] == "stage_transition")
    assert transition["fromStage"] == 5
    assert transition["toStage"] == 6


def test_accepted_offer_detail_field_advances_live_listing_when_gate_is_clear(client):
    deal = _create(title="Offer accepted detail", current_stage=5)
    _clear_stage_five_gate(client, deal["id"])

    resp = client.post(
        f"/api/deals/{deal['id']}/fields",
        json={"fields": {"offerAcceptedAt": "2026-05-06"}},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 6
    assert resp.json()["offerAcceptedAt"] == "2026-05-06"


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


def test_profile_promotion_requires_phone_or_email_verifier(client):
    resp = client.post(
        "/api/admin/profile-promotions",
        json={
            "profileId": "profile-no-verifier",
            "side": "listing",
            "displayName": "No Verifier",
            "profileContext": {"id": "profile-no-verifier", "displayName": "No Verifier"},
            "verifiers": [],
            "dispatchInitialStage": False,
        },
    )

    assert resp.status_code == 400
    assert "phone or email verifier" in resp.json()["detail"]


def test_profile_promotion_creates_and_updates_same_admin_deal(client):
    payload = {
        "profileId": "profile-seller-1",
        "side": "listing",
        "displayName": "Morgan Seller",
        "workflow": "seller-cma",
        "profileContext": {
            "id": "profile-seller-1",
            "displayName": "Morgan Seller",
            "contactIds": ["source-contact-1"],
            "conversationIds": ["conversation-1"],
            "threadIds": ["thread-1"],
            "sourceIds": ["gmail:1"],
            "sources": ["gmail"],
            "channels": ["email"],
            "phones": ["(250) 555-0101"],
            "emails": ["morgan@example.com"],
            "latestText": "Can we meet about selling next week?",
            "latestAt": "2026-05-08T10:00:00+00:00",
            "heatScore": 92,
            "heatLabel": "hot",
            "tags": ["seller", "appointment-booked"],
        },
        "verifiers": [
            {"kind": "phone", "value": "(250) 555-0101", "key": "phone:2505550101"},
            {"kind": "email", "value": "morgan@example.com", "key": "email:morgan@example.com"},
        ],
        "dispatchInitialStage": False,
    }

    created = client.post("/api/admin/profile-promotions", json=payload)
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["action"] == "created"
    deal = created_body["deal"]
    assert deal["title"] == "Seller: Morgan Seller"
    assert deal["side"] == "listing"
    assert deal["province"] == "BC"
    assert deal["primaryContactId"] is None
    assert deal["extraToggles"]["sourceProfileId"] == "profile-seller-1"
    assert deal["extraToggles"]["sourceAdminSide"] == "listing"
    assert deal["extraToggles"]["workflow"] == "seller-cma"
    assert "phone:2505550101" in deal["extraToggles"]["profileVerifierKeys"]

    payload["profileContext"] = {
        **payload["profileContext"],
        "latestText": "Updated appointment context",
    }
    updated = client.post("/api/admin/profile-promotions", json=payload)
    assert updated.status_code == 200, updated.text
    updated_body = updated.json()
    assert updated_body["action"] == "updated"
    assert updated_body["matchReason"] == "source_profile"
    assert updated_body["deal"]["id"] == deal["id"]
    assert updated_body["deal"]["extraToggles"]["profileLatestText"] == "Updated appointment context"


def test_profile_promotion_matches_existing_deal_by_verifier(client):
    first = {
        "profileId": "profile-old",
        "side": "buyer",
        "displayName": "Casey Buyer",
        "workflow": "buyer-admin",
        "profileContext": {
            "id": "profile-old",
            "displayName": "Casey Buyer",
            "phones": ["604-555-0199"],
            "emails": ["casey@example.com"],
        },
        "verifiers": [{"kind": "email", "value": "casey@example.com", "key": "email:casey@example.com"}],
        "dispatchInitialStage": False,
    }
    created = client.post("/api/admin/profile-promotions", json=first)
    assert created.status_code == 200, created.text
    deal_id = created.json()["deal"]["id"]

    second = {
        **first,
        "profileId": "profile-merged",
        "profileContext": {
            **first["profileContext"],
            "id": "profile-merged",
            "latestText": "Same person, merged source profile.",
        },
    }
    updated = client.post("/api/admin/profile-promotions", json=second)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["action"] == "updated"
    assert body["matchReason"] == "verifier"
    assert body["deal"]["id"] == deal_id
    assert body["deal"]["extraToggles"]["sourceProfileId"] == "profile-merged"
    assert body["deal"]["extraToggles"]["sourceProfileIds"] == ["profile-old", "profile-merged"]


def test_deal_context_endpoint_returns_source_of_truth_blob(client):
    with connect() as conn:
        primary = upsert_contact(
            conn,
            display_name="Seller One",
            primary_email="seller@example.com",
            type="listing",
            stage="active",
        )
        lawyer = upsert_contact(
            conn,
            display_name="Lawyer One",
            primary_email="lawyer@example.com",
            type="other",
            stage="active",
        )
        deal = create_deal(
            conn,
            title="Context Deal",
            side="listing",
            actor="human:test",
            province="BC",
            primary_contact_id=primary["id"],
            fields={"property_subtype": "strata", "draft-cma-followup": True},
        )

    fields = client.post(
        f"/api/deals/{deal['id']}/fields",
        json={"fields": {"subjectRemovalDate": "2026-06-01", "listPrice": 799000}},
    )
    assert fields.status_code == 200, fields.text
    assert fields.json()["subjectRemovalDate"] == "2026-06-01"
    assert fields.json()["listPrice"] == 799000

    linked = client.post(
        f"/api/deals/{deal['id']}/contacts",
        json={"role": "lawyer", "contactId": lawyer["id"], "notes": "Seller lawyer"},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["role"] == "lawyer"

    attached = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "cma_report", "filePath": "/tmp/cma.pdf", "summary": "CMA ready"},
    )
    assert attached.status_code == 200, attached.text

    resp = client.get(f"/api/deals/{deal['id']}/context")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deal"]["id"] == deal["id"]
    assert body["deal"]["province"] == "BC"
    assert body["primaryContact"]["displayName"] == "Seller One"
    assert body["conditions"]["property_subtype"] == "strata"
    assert body["checklist"]["draft-cma-followup"] is True
    assert body["dealFlow"]["packageKey"] == "ca.bc"
    assert body["dealFlow"]["gate"]["stageName"] == "Pre-CMA"
    assert body["dealFlow"]["gate"]["canAdvance"] is False
    assert {item["skill"] for item in body["dealFlow"]["backgroundAutomations"]} == {
        "gmail-doc-router",
        "seller-update",
    }
    assert body["coContacts"][0]["role"] == "lawyer"
    assert body["attachments"][0]["kind"] == "cma_report"


def test_province_guide_import_feeds_deal_context_and_conditional_docs(client, tmp_path):
    root = tmp_path / "exp-agent-centre"
    pages = root / "pages"
    pages.mkdir(parents=True)
    pages.joinpath("bc-listings-sales.md").write_text(
        "---\nurl: https://example.test/bc-listings-sales\ntitle: BC Listings & Sales\n---\n"
        "# BC Listings & Sales\n\n## Transactions\n- Transaction Guide\n",
        encoding="utf-8",
    )
    guide = root / "transaction-guide-bc"
    forms = guide / "forms"
    forms.mkdir(parents=True)
    guide.joinpath("common-forms.md").write_text(
        "---\nurl: https://example.test/forms\ntitle: Common Forms\n---\n# Common Forms\n",
        encoding="utf-8",
    )
    forms.joinpath("inventory.json").write_text(
        '{"MLC":{"name":"Multiple Listing Contract","category":"Listing","code":"MLC","pageCount":9,"annotationCount":32}}',
        encoding="utf-8",
    )

    with connect() as conn:
        imported = import_exp_agent_centre(conn, root=root)
        deal = create_deal(
            conn,
            title="Strata offer",
            side="listing",
            actor="human:test",
            province="BC",
            current_stage=6,
            fields={"property_subtype": "strata"},
        )

    assert imported["pages"] == 1
    assert imported["checklists"] == 1
    assert imported["forms"] == 1
    assert imported["conditionalDocs"] == 4

    coverage = client.get("/api/admin/province-guides")
    assert coverage.status_code == 200, coverage.text
    assert coverage.json()["items"][0]["province"] == "BC"
    assert coverage.json()["items"][0]["hasTransactionGuide"] is True

    context = client.get(f"/api/deals/{deal['id']}/context")
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["provinceGuide"]["coverage"]["forms"] == 1
    assert body["provinceGuide"]["forms"][0]["code"] == "MLC"
    assert body["agentGuideMemory"]["coverage"]["forms"] == 1
    assert body["agentGuideMemory"]["referencePages"][0]["title"] == "BC Listings & Sales"
    assert "Transaction Guide" in body["agentGuideMemory"]["referencePages"][0]["excerpt"]
    assert body["conditionalDocs"][0]["docCode"] == "strata_docs"
    assert any(item["kind"] == "strata_docs" for item in body["dealFlow"]["requiredDocs"])
    assert any(item["kind"] == "strata_docs" for item in body["dealFlow"]["gate"]["missingDocs"])


def test_province_guide_import_defaults_to_product_onboarding_choices(tmp_path):
    root = tmp_path / "exp-agent-centre"
    pages = root / "pages"
    pages.mkdir(parents=True)
    pages.joinpath("alberta.md").write_text("# Alberta\n", encoding="utf-8")
    pages.joinpath("bc-listings-sales.md").write_text("# BC Listings\n", encoding="utf-8")

    with connect() as conn:
        imported = import_exp_agent_centre(conn, root=root)
        coverage = province_coverage(conn)

    assert imported["provinces"] == ["AB", "BC"]
    assert [item["province"] for item in coverage] == ["AB", "BC"]


def test_province_guide_targeted_import_does_not_prune_without_explicit_flag(tmp_path):
    root = tmp_path / "exp-agent-centre"
    pages = root / "pages"
    pages.mkdir(parents=True)
    pages.joinpath("alberta.md").write_text("# Alberta\n", encoding="utf-8")
    pages.joinpath("bc-listings-sales.md").write_text("# BC Listings\n", encoding="utf-8")

    with connect() as conn:
        import_exp_agent_centre(conn, root=root)
        imported = import_exp_agent_centre(conn, root=root, province="British Columbia")
        coverage = province_coverage(conn)

    assert imported["provinces"] == ["BC"]
    assert [item["province"] for item in coverage] == ["AB", "BC"]


def test_province_guide_invalid_prune_fails_closed(tmp_path):
    root = tmp_path / "exp-agent-centre"
    pages = root / "pages"
    pages.mkdir(parents=True)
    pages.joinpath("bc-listings-sales.md").write_text("# BC Listings\n", encoding="utf-8")

    with connect() as conn:
        import_exp_agent_centre(conn, root=root)
        with pytest.raises(ValueError):
            import_exp_agent_centre(
                conn,
                root=root,
                province="British Columbia typo",
                prune_other_provinces=True,
            )
        coverage = province_coverage(conn)

    assert [item["province"] for item in coverage] == ["BC"]


def test_admin_jurisdiction_uses_onboarded_setup_profile(client):
    with connect() as conn:
        update_admin_setup(
            conn,
            profile={"country": "CA", "province": "ON", "market": "Toronto"},
            actor="human:test",
        )

    response = client.get("/api/admin/deals")
    assert response.status_code == 200, response.text
    assert response.json()["jurisdiction"]["province"] == "ON"
    assert response.json()["jurisdiction"]["market"] == "Toronto"


def test_advance_endpoint_blocks_until_package_gate_is_clear(client):
    deal = _create(title="Gate deal", current_stage=0)

    blocked = client.post(f"/api/deals/{deal['id']}/advance", json={})
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["message"] == "deal phase gate is blocked"
    assert any(item["id"] == "pre_cma_dashboard_setup" for item in detail["gate"]["missingChecklist"])

    # Clear the Pre-CMA gate: setup checklist + lead/contact fields (no docs required).
    for item_id in ("pre_cma_dashboard_setup", "lofty_contact_verified", "pre_cma_handoff"):
        ok = client.post(f"/api/admin/deals/{deal['id']}/toggle", json={"field": item_id, "value": True})
        assert ok.status_code == 200, ok.text
    for field, value in {
        "workflow_client_1_name": "Seller One",
        "workflow_client_1_email": "seller@example.com",
        "workflow_lead_source": "Referral",
        "workflow_cma_date_requested": "2026-05-01",
    }.items():
        ok = client.post(f"/api/admin/deals/{deal['id']}/toggle", json={"field": field, "value": value})
        assert ok.status_code == 200, ok.text

    context = client.get(f"/api/deals/{deal['id']}/context")
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["deal"]["currentStage"] == 1
    assert body["dealFlow"]["stageName"] == "CMA / Evaluation"

    next_advance = client.post(f"/api/deals/{deal['id']}/advance", json={})
    assert next_advance.status_code == 409, next_advance.text
    assert next_advance.json()["detail"]["gate"]["stage"] == 1


def test_admin_tasks_endpoint_projects_phase_gate_and_ai_actions(client):
    # CMA / Evaluation (stage 1) is where the cma ai_action and cma_report doc live.
    deal = _create(title="Task Deal", side="listing", current_stage=1)

    resp = client.get("/api/admin/tasks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tasks = [item for item in body["items"] if item["dealId"] == deal["id"]]
    assert tasks
    assert any(item["type"] == "ai_action" and item["skill"] == "cma" for item in tasks)
    assert any(item["type"] == "checklist" and item["status"] == "open" for item in tasks)
    assert any(item["type"] == "document" and item["kind"] == "cma_report" for item in tasks)
    assert {item["packageKey"] for item in tasks} == {"generic.real-estate"}
    assert {item["stageName"] for item in tasks} == {"CMA / Evaluation"}

    ai_task = next(item for item in tasks if item["type"] == "ai_action")
    queued = client.post(
        "/api/admin/tasks/run",
        json={
            "dealId": deal["id"],
            "skill": ai_task["skill"],
            "title": ai_task["title"],
            "sourceTaskId": ai_task["id"],
            "runNow": False,
        },
    )
    assert queued.status_code == 200, queued.text
    run = queued.json()
    assert run["dealId"] == deal["id"]
    assert run["status"] == "queued"
    assert run["payload"]["trigger"] == "task_board"
    assert run["payload"]["sourceTaskId"] == ai_task["id"]


def test_workflow_import_cells_drive_listing_phase_gate(client):
    headers = [
        "Row ID", "Property Address", "Date Created", "Current Stage",
        "Google Drive Folder URL", "Signing Authority", "FINTRAC Form Type",
        "Politically Exposed Person?", "Listing Track", "Property Sub-Type",
        "Tenanted Property?", "Estate / Probate Status", "POA Signing?",
        "Corporate Seller?", "Client 1 Name", "Client 1 Email", "Client 1 Phone",
        "Client 2 Name", "Client 2 Email", "Client 2 Phone", "Lead Source",
        "CMA Date Requested", "Lofty Contact URL", "Listing Price",
        "Commission Rate (%)", "Planned Go-Live Date", "Open House Date",
        "Listing Type", "Has Suite?", "Stage 1 Complete ✓", "Documents Sent Date",
        "Documents Signed Date", "Title Ordered?", "Sign Ordered?",
        "SkySlope Transaction URL", "Stage 2 Complete ✓", "Photo Shoot Date",
        "Photos in Drive?", "AI: Garage / Carport", "AI: Suite Detected",
        "AI: AC / Heat Pump", "AI: Appliances Listed", "AI: Flooring Types",
        "Jeff Photo Review ✓", "Stage 3 Complete ✓", "eValue BC Age Verified",
        "MLS Input Started Date", "Listing Description Approved",
        "Feature Sheet Uploaded", "AI-Edited Photos Labelled",
        "Realtor Tour Scheduled", "Stage 4 Complete ✓", "MLS Listing URL",
        "Live Date (Actual)", "Order Sign Up Date", "Coming Soon Posts Date",
        "Just Listed Blast Sent", "Social Posts Published", "Kijiji Posted",
        "Kamloops Classifieds Posted", "Flodesk Mailout Sent",
        "Lofty Text Blast Sent", "Stage 5 Complete ✓",
    ]
    row = {
        "Row ID": "1",
        "Property Address": "17-750 Cedar Drive, Vancouver, BC",
        "Date Created": "2026-04-28",
        "Current Stage": "Stage 5 — Listing Live",
        "Google Drive Folder URL": "https://drive.example/folder",
        "Signing Authority": "Individual",
        "FINTRAC Form Type": "Standard",
        "Politically Exposed Person?": "No",
        "Listing Track": "MLS",
        "Property Sub-Type": "Mobile",
        "Tenanted Property?": "No",
        "Estate / Probate Status": "None",
        "POA Signing?": "No",
        "Corporate Seller?": "No",
        "Client 1 Name": "Jenna Hutchinson",
        "Client 1 Email": "jenna@example.com",
        "Lead Source": "Referral",
        "CMA Date Requested": "2026-03-01",
        "Lofty Contact URL": "https://app.lofty.com/contact/1145885890673237",
        "Listing Price": "$179,900",
        "Commission Rate (%)": "3.50%",
        "Planned Go-Live Date": "2026-03-07",
        "Listing Type": "Mobile",
        "Has Suite?": "No",
        "Stage 1 Complete ✓": "TRUE",
        "Documents Sent Date": "2026-03-07",
        "Documents Signed Date": "2026-03-07",
        "Title Ordered?": "TRUE",
        "Sign Ordered?": "TRUE",
        "SkySlope Transaction URL": "https://skyslope.example/tx",
        "Stage 2 Complete ✓": "TRUE",
        "Photo Shoot Date": "2026-03-05",
        "Photos in Drive?": "TRUE",
        "Jeff Photo Review ✓": "TRUE",
        "Stage 3 Complete ✓": "TRUE",
        "eValue BC Age Verified": "TRUE",
        "MLS Input Started Date": "2026-03-07",
        "Listing Description Approved": "TRUE",
        "Feature Sheet Uploaded": "TRUE",
        "AI-Edited Photos Labelled": "TRUE",
        "Stage 4 Complete ✓": "TRUE",
        "MLS Listing URL": "https://interiorrealtors.xposureapp.com/portal/listings/10378203",
        "Live Date (Actual)": "2026-03-07",
        "Order Sign Up Date": "2026-03-07",
        "Coming Soon Posts Date": "2026-03-05",
        "Just Listed Blast Sent": "TRUE",
        "Social Posts Published": "TRUE",
        "Flodesk Mailout Sent": "TRUE",
        "Lofty Text Blast Sent": "FALSE",
        "Stage 5 Complete ✓": "TRUE",
    }
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["IDENTIFIERS"] + [""] * (len(headers) - 1))
    writer.writerow(headers)
    writer.writerow(["instructions"] * len(headers))
    writer.writerow([row.get(header, "") for header in headers])
    csv_text = buf.getvalue()
    with connect() as conn:
        imported = import_listing_workflow_csv(conn, csv_text, province="BC")
        context = conn.execute("SELECT id FROM deals").fetchone()
        assert context is not None
        deal_id = context["id"]

    assert imported["created"] == 1
    resp = client.get(f"/api/deals/{deal_id}/context")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    flow = body["dealFlow"]
    assert flow["stageName"] == "Listing Live / Marketing"
    checklist_ids = {item["id"] for item in flow["checklistItems"]}
    assert "workflow_stage_5_complete" in checklist_ids
    assert "workflow_just_listed_blast_sent" in checklist_ids
    assert flow["gate"]["completedChecklist"] == 4
    assert any(item["id"] == "workflow_lofty_text_blast_sent" for item in flow["gate"]["missingChecklist"])


def test_workflow_import_stage_update_uses_audited_stage_transition(client):
    headers = ["Row ID", "Property Address", "Current Stage"]

    def csv_text(stage: str) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["IDENTIFIERS", "", ""])
        writer.writerow(headers)
        writer.writerow(["instructions"] * len(headers))
        writer.writerow(["1", "42 Source Truth Ave", stage])
        return buf.getvalue()

    with connect() as conn:
        imported = import_listing_workflow_csv(conn, csv_text("Stage 1 — Listing Intake"), province="BC")
        deal_id = imported["items"][0]["id"]
        action = create_action(
            conn,
            name="import stage two entry",
            trigger="stage_entry",
            skill="mlc",
            side="listing",
            to_stage=2,
        )
        updated = import_listing_workflow_csv(conn, csv_text("Stage 2 — MLC / Documents"), province="BC")
        events = list_deal_events(conn, deal_id)
        runs = list_action_runs(conn, deal_id=deal_id)

    assert updated["updated"] == 1
    transition = next(event for event in events if event["kind"] == "stage_transition")
    assert transition["fromStage"] == 1
    assert transition["toStage"] == 2
    assert transition["payload"]["force"] is True
    assert any(run["registryId"] == action["id"] for run in runs)


def test_run_result_callback_updates_run_and_attaches_artifacts(client):
    deal = _create(title="Run result deal", current_stage=1)
    with connect() as conn:
        action = create_action(
            conn,
            name="CMA on stage",
            trigger="stage_entry",
            skill="cma:collect",
            side="listing",
            to_stage=1,
        )
        runs = evaluate_dispatch(
            conn,
            deal_id=deal["id"],
            trigger="stage_entry",
            actor="human:test",
            to_stage=1,
        )
    assert runs and runs[0]["registryId"] == action["id"]
    run_id = runs[0]["id"]

    resp = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "run-result-test",
            "artifacts": [
                {"kind": "cma_report", "filePath": "/tmp/context-cma.pdf", "summary": "PDF generated"}
            ],
            "next_tasks": [{"skill": "cma:pdf", "args": {"deal_id": deal["id"]}}],
            "checklist_updates": [{"id": "pricing-recap", "completed": True}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["outputPath"] == "/tmp/context-cma.pdf"

    replay = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "run-result-test",
            "artifacts": [
                {"kind": "cma_report", "filePath": "/tmp/context-cma.pdf", "summary": "PDF generated"}
            ],
            "next_tasks": [{"skill": "cma:pdf", "args": {"deal_id": deal["id"]}}],
            "checklist_updates": [{"id": "pricing-recap", "completed": True}],
        },
    )
    assert replay.status_code == 200, replay.text

    context = client.get(f"/api/deals/{deal['id']}/context").json()
    assert context["attachments"][0]["sourceRunId"] == run_id
    assert context["checklist"]["draft-cma-followup"] is True
    assert context["checklist"]["pricing-recap"] is True
    assert any(run["payload"].get("result", {}).get("nextTasks") for run in context["priorRuns"])
    with connect() as conn:
        queued = list_action_runs(conn, deal_id=deal["id"])
        attachments = list_deal_attachments(conn, deal["id"])
    assert any(run["payload"].get("trigger") == "next_task" for run in queued)
    assert len([item for item in attachments if item["sourceRunId"] == run_id]) == 1


def test_run_result_stage_complete_update_requires_human_not_skill_callback(client):
    deal = _create(title="AI auto move", current_stage=1)
    with connect() as conn:
        create_action(
            conn,
            name="Listing initiated action",
            trigger="stage_entry",
            skill="mlc:intake",
            side="listing",
            to_stage=1,
        )
        runs = evaluate_dispatch(
            conn,
            deal_id=deal["id"],
            trigger="stage_entry",
            actor="human:test",
            to_stage=1,
        )
    run_id = runs[0]["id"]

    resp = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "stage-complete-auto-move",
            "checklist_updates": [{"id": "workflow_stage_1_complete", "completed": True}],
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "workflow_stage_1_complete" in body["result"]["protectedChecklistSkipped"]
    context = client.get(f"/api/deals/{deal['id']}/context")
    assert context.status_code == 200, context.text
    assert context.json()["deal"]["currentStage"] == 1
    assert "workflow_stage_1_complete" not in context.json()["checklist"]


def test_run_result_clearing_phase_gate_advances_without_stage_complete_flag(client):
    # A CMA run that clears the CMA / Evaluation gate (stage 1) advances the deal
    # to Listing Intake (stage 2) without any explicit stage-complete toggle.
    deal = _create(title="Gate clear auto move", current_stage=1)
    priced = client.post(
        f"/api/deals/{deal['id']}/fields",
        json={"fields": {"listPrice": 799000}},
    )
    assert priced.status_code == 200, priced.text
    with connect() as conn:
        create_action(
            conn,
            name="CMA gate action",
            trigger="stage_entry",
            skill="cma",
            side="listing",
            to_stage=1,
        )
        runs = evaluate_dispatch(
            conn,
            deal_id=deal["id"],
            trigger="stage_entry",
            actor="human:test",
            to_stage=1,
        )
    run_id = runs[0]["id"]

    resp = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "gate-clear-auto-move",
            "artifacts": [
                {"kind": "cma_report", "filePath": "/tmp/gate-clear-cma.pdf", "summary": "CMA report"}
            ],
            "checklist_updates": [
                {"id": "cma_pdf_ready", "completed": True},
                {"id": "pricing_story_approved", "completed": True},
                {"id": "client_yes_to_listing", "completed": True},
                {"id": "workflow_cma_date_requested", "completed": True},
            ],
        },
    )

    assert resp.status_code == 200, resp.text
    context = client.get(f"/api/deals/{deal['id']}/context")
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["deal"]["currentStage"] == 2
    assert "workflow_stage_0_complete" not in body["checklist"]


def test_admin_deals_requires_session_token():
    """Sanity: the auth middleware blocks unauthenticated calls."""
    from elevate_cli.web_server import app

    unauthed = TestClient(app)
    resp = unauthed.get("/api/admin/deals")
    assert resp.status_code in (401, 403)


def test_plugin_api_routes_require_session_token():
    from elevate_cli.web_server import app

    unauthed = TestClient(app)
    resp = unauthed.get("/api/plugins/example/status")
    assert resp.status_code in (401, 403)
