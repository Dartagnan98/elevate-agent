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

from elevate_cli.data import (
    connect,
    create_action,
    create_deal,
    evaluate_dispatch,
    import_exp_agent_centre,
    list_action_runs,
    list_deal_attachments,
    list_deal_events,
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
    assert body["province"] == "BC"
    assert body["board"] is None
    assert body["market"] is None
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



def test_admin_jurisdiction_defaults_to_generic_and_deals_can_stamp_package_values(client):
    resp = client.get("/api/admin/jurisdiction")
    assert resp.status_code == 200, resp.text
    jurisdiction = resp.json()
    assert jurisdiction == {
        "country": "CA",
        "province": "",
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
    assert body["dealFlow"]["gate"]["stageName"] == "CMA"
    assert body["dealFlow"]["gate"]["canAdvance"] is False
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
    assert body["conditionalDocs"][0]["docCode"] == "strata_docs"
    assert any(item["kind"] == "strata_docs" for item in body["dealFlow"]["requiredDocs"])
    assert any(item["kind"] == "strata_docs" for item in body["dealFlow"]["gate"]["missingDocs"])


def test_advance_endpoint_blocks_until_package_gate_is_clear(client):
    deal = _create(title="Gate deal", current_stage=0)

    blocked = client.post(f"/api/deals/{deal['id']}/advance", json={})
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["message"] == "deal phase gate is blocked"
    assert any(item["id"] == "draft-cma-followup" for item in detail["gate"]["missingChecklist"])

    for item_id in ("draft-cma-followup", "pricing-recap", "missing-info-list"):
        ok = client.post(f"/api/admin/deals/{deal['id']}/toggle", json={"field": item_id, "value": True})
        assert ok.status_code == 200, ok.text
    attached = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "cma_report", "filePath": "/tmp/gate-cma.pdf"},
    )
    assert attached.status_code == 200, attached.text

    advanced = client.post(f"/api/deals/{deal['id']}/advance", json={})
    assert advanced.status_code == 200, advanced.text
    body = advanced.json()
    assert body["deal"]["currentStage"] == 1
    assert body["dealFlow"]["stageName"] == "Listing Intake"


def test_admin_tasks_endpoint_projects_phase_gate_and_ai_actions(client):
    deal = _create(title="Task Deal", side="listing", current_stage=0)

    resp = client.get("/api/admin/tasks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tasks = [item for item in body["items"] if item["dealId"] == deal["id"]]
    assert tasks
    assert any(item["type"] == "ai_action" and item["skill"] == "cma" for item in tasks)
    assert any(item["type"] == "checklist" and item["status"] == "open" for item in tasks)
    assert any(item["type"] == "document" and item["kind"] == "cma_report" for item in tasks)
    assert {item["packageKey"] for item in tasks} == {"generic.real-estate"}
    assert {item["stageName"] for item in tasks} == {"CMA"}

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


def test_admin_deals_requires_session_token():
    """Sanity: the auth middleware blocks unauthenticated calls."""
    from elevate_cli.web_server import app

    unauthed = TestClient(app)
    resp = unauthed.get("/api/admin/deals")
    assert resp.status_code in (401, 403)
