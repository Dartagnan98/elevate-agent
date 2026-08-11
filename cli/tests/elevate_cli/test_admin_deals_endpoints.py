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
import zipfile

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
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


def _write_valid_pdf(path: Path, text: str = "Verified test artifact") -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def _valid_png_bytes() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
        "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _write_valid_png(path: Path) -> Path:
    path.write_bytes(_valid_png_bytes())
    return path


def _write_valid_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("listing-photo.png", _valid_png_bytes())
    return path


def _write_valid_docx(path: Path, text: str = "Verified contract") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            (
                "<w:document xmlns:w='urn:test'><w:body><w:p><w:r><w:t>"
                f"{text}"
                "</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return path


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
            province="BC",
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
    assert context.json()["dealFlow"]["available"] is False
    assert context.json()["dealFlow"]["localOverrides"]["provinceLabel"] == "Alberta"
    assert context.json()["dealFlow"]["requiredForms"] == []
    assert context.json()["dealFlow"]["backgroundAutomations"] == []
    assert "British Columbia" not in str(context.json()["dealFlow"])


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
    assert created.status_code == 409, created.text
    setup = client.get("/api/admin/setup")
    assert setup.status_code == 200, setup.text
    assert setup.json()["complete"] is False
    assert setup.json()["profile"]["completedAt"] is None

    pei = client.put("/api/admin/jurisdiction", json={"province": "PEI", "market": ""})
    assert pei.status_code == 200, pei.text
    assert pei.json()["packageKey"] == "ca.pei"
    assert pei.json()["province"] == "PEI"


def test_admin_setup_province_change_replaces_stale_implicit_package(client):
    from elevate_cli.config import load_config, save_config

    config = load_config()
    config["real_estate"] = {
        "country": "CA",
        "province": "BC",
        "market": "Kamloops",
        "package_key": "ca.bc",
    }
    save_config(config)

    updated = client.put(
        "/api/admin/setup",
        json={"profile": {"country": "CA", "province": "AB", "market": "Calgary"}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["profile"]["province"] == "AB"
    assert updated.json()["complete"] is False
    assert updated.json()["profile"]["completedAt"] is None
    assert {"jurisdiction", "forms_provider", "regional_memory"}.issubset(
        updated.json()["missingRequiredKeys"]
    )

    jurisdiction = client.get("/api/admin/jurisdiction")
    assert jurisdiction.status_code == 200, jurisdiction.text
    assert jurisdiction.json() == {
        "country": "CA",
        "province": "AB",
        "market": "Calgary",
        "packageKey": "ca.ab",
    }
    assert load_config()["real_estate"]["package_key"] == "ca.ab"


def test_unverified_province_package_exposes_no_bc_workflow_or_forms():
    from elevate_cli.admin_deal_flow import resolve_admin_deal_flow

    flow = resolve_admin_deal_flow(
        package_key="ca.on",
        side="buyer",
        stage=2,
    )

    assert flow["packageKey"] == "ca.on"
    assert flow["available"] is False
    assert flow["stageName"] == "Province workflow unavailable"
    assert flow["checklistItems"] == []
    assert flow["requiredFields"] == []
    assert flow["requiredForms"] == []
    assert flow["requiredDocs"] == []
    assert flow["automationTriggers"] == []
    assert flow["backgroundAutomations"] == []
    assert "Ontario" in flow["unavailableReason"]
    assert "BCFSA" not in str(flow)
    assert "CPS" not in str(flow)


def test_province_change_invalidates_only_province_derived_setup_and_playbook(
    monkeypatch,
    tmp_path,
):
    from elevate_cli.data import get_deal

    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path / "elevate-home"))
    _complete_admin_setup()
    evidence_file = _write_valid_pdf(
        tmp_path / "signed-existing-deal.pdf",
        "Signed historical deal evidence",
    )

    with connect() as conn:
        before = get_admin_setup(conn)
        email_before = next(item for item in before["items"] if item["key"] == "email")
        deal = create_deal(
            conn,
            title="Historical BC evidence",
            side="buyer",
            province="BC",
            actor="human:test",
            dispatch_initial_stage=False,
        )
        attachment = add_deal_attachment(
            conn,
            deal["id"],
            kind="cps_signed",
            file_path=str(evidence_file),
            actor="human:test",
        )
        playbook_path = Path(before["memory"]["path"]).with_name(
            "ADMIN_PROVINCE_PLAYBOOK.md"
        )
        assert playbook_path.exists()

        switched = update_admin_setup(
            conn,
            profile={"province": "AB", "market": "Calgary"},
        )

        assert switched["profile"]["province"] == "AB"
        assert switched["profile"]["completedAt"] is None
        assert switched["profile"]["regionalMemory"] == {}
        assert switched["complete"] is False
        assert switched["canStartAdmin"] is False
        scoped = {
            item["key"]: item
            for item in switched["items"]
            if item["key"] in {"jurisdiction", "forms_provider", "regional_memory"}
        }
        assert set(scoped) == {"jurisdiction", "forms_provider", "regional_memory"}
        assert all(item["status"] == "missing" for item in scoped.values())
        assert all(item["provider"] is None for item in scoped.values())
        assert all(item["value"] is None for item in scoped.values())
        email_after = next(item for item in switched["items"] if item["key"] == "email")
        assert email_after["status"] == email_before["status"]
        assert get_deal(conn, deal["id"])["province"] == "BC"
        assert list_deal_attachments(conn, deal["id"])[0]["id"] == attachment["id"]

    assert not playbook_path.exists()


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


def test_move_deal_endpoint_reports_clear_gate_skip_as_wrong_target(client, tmp_path):
    cma_path = _write_valid_pdf(tmp_path / "cma.pdf", "CMA ready")
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Skip me",
            side="listing",
            province="BC",
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
            file_path=str(cma_path),
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


def _clear_stage_four_gate(client, deal_id: str, photo_archive: Path):
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
        json={"kind": "listing_photos", "filePath": str(photo_archive)},
    )
    assert attached.status_code == 200, attached.text


def test_current_workflow_stage_complete_advances_when_gate_is_clear(client, tmp_path):
    deal = _create(title="Gate clear stage four", current_stage=4)
    photo_archive = _write_valid_zip(tmp_path / "listing-photos.zip")
    _clear_stage_four_gate(client, deal["id"], photo_archive)

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
    assert resp.json()["currentStage"] == 7
    with connect() as conn:
        events = list_deal_events(conn, deal["id"])
    transition = next(event for event in events if event["kind"] == "stage_transition")
    assert transition["fromStage"] == 5
    assert transition["toStage"] == 7


def test_accepted_offer_detail_field_advances_live_listing_when_gate_is_clear(client):
    deal = _create(title="Offer accepted detail", current_stage=5)
    _clear_stage_five_gate(client, deal["id"])

    resp = client.post(
        f"/api/deals/{deal['id']}/fields",
        json={"fields": {"offerAcceptedAt": "2026-05-06"}},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStage"] == 7
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


def test_deal_context_endpoint_returns_source_of_truth_blob(client, tmp_path):
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

    cma_path = _write_valid_pdf(tmp_path / "context-cma.pdf", "CMA ready")
    attached = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "cma_report", "filePath": str(cma_path), "summary": "CMA ready"},
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


def test_deal_attachment_rejects_missing_and_invalid_files_without_ghost_rows(
    client,
    tmp_path,
):
    deal = _create(title="No ghost attachments", dispatch_initial_stage=False)
    missing = tmp_path / "missing-contract.pdf"
    invalid = tmp_path / "invalid-contract.pdf"
    invalid.write_bytes(b"not a PDF")
    blank = tmp_path / "blank-contract.pdf"
    import fitz

    blank_document = fitz.open()
    blank_document.new_page()
    blank_document.save(blank)
    blank_document.close()
    empty_docx = tmp_path / "empty-contract.docx"
    with zipfile.ZipFile(empty_docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='urn:test'><w:body><w:p/></w:body></w:document>",
        )
    fake_media_docx = tmp_path / "fake-media-contract.docx"
    with zipfile.ZipFile(fake_media_docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='urn:test'><w:body><w:p/></w:body></w:document>",
        )
        archive.writestr("word/media/photo.jpg", b"not actually a jpeg")
    malformed_docx = tmp_path / "malformed-contract.docx"
    with zipfile.ZipFile(malformed_docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='urn:test'><w:body><w:p>broken",
        )
    unsupported = tmp_path / "contract.bin"
    unsupported.write_bytes(b"not a supported attachment")

    for path in (
        missing,
        invalid,
        blank,
        empty_docx,
        fake_media_docx,
        malformed_docx,
        unsupported,
    ):
        response = client.post(
            f"/api/deals/{deal['id']}/attachments",
            json={"kind": "contract", "filePath": str(path)},
        )
        assert response.status_code == 400, response.text

    manifest_only = tmp_path / "manifest-only.zip"
    with zipfile.ZipFile(manifest_only, "w") as archive:
        archive.writestr("photo-manifest.txt", "no actual listing photo")
    no_photos = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "listing_photos", "filePath": str(manifest_only)},
    )
    assert no_photos.status_code == 400, no_photos.text

    with connect() as conn:
        assert list_deal_attachments(conn, deal["id"]) == []
        events = list_deal_events(conn, deal["id"])
    assert not any(event["kind"] == "attachment_added" for event in events)


def test_listing_photo_zip_requires_image_magic_not_just_extension(client, tmp_path):
    deal = _create(title="Photo ZIP truth", dispatch_initial_stage=False)
    disguised = tmp_path / "disguised-photos.zip"
    with zipfile.ZipFile(disguised, "w") as archive:
        archive.writestr("listing-photo.jpg", b"plain text with a jpg name")

    rejected = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "listing_photos", "filePath": str(disguised)},
    )
    assert rejected.status_code == 400, rejected.text

    header_only = tmp_path / "header-only-photos.zip"
    with zipfile.ZipFile(header_only, "w") as archive:
        archive.writestr("listing-photo.jpg", b"\xff\xd8\xffnot a decodable jpeg")
    rejected = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "listing_photos", "filePath": str(header_only)},
    )
    assert rejected.status_code == 400, rejected.text

    valid = _write_valid_zip(tmp_path / "physical-photos.zip")
    accepted = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "listing_photos", "filePath": str(valid)},
    )
    assert accepted.status_code == 200, accepted.text


def test_required_document_kinds_enforce_compatible_substantive_formats(
    client,
    tmp_path,
):
    deal = _create(title="Required document contracts", dispatch_initial_stage=False)
    fake_cma = tmp_path / "cma-report.txt"
    fake_cma.write_text("This text is not a CMA PDF", encoding="utf-8")
    rejected = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "cma_report", "filePath": str(fake_cma)},
    )
    assert rejected.status_code == 400, rejected.text

    fake_sales_doc = tmp_path / "sales-report.doc"
    fake_sales_doc.write_text("not an Office binary", encoding="utf-8")
    rejected = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "sales_report", "filePath": str(fake_sales_doc)},
    )
    assert rejected.status_code == 400, rejected.text

    fake_signed_docs = tmp_path / "signed-documents.txt"
    fake_signed_docs.write_text("These are not signed PDF documents", encoding="utf-8")
    rejected = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "signed_docs", "filePath": str(fake_signed_docs)},
    )
    assert rejected.status_code == 400, rejected.text

    fake_contract = tmp_path / "contract.jpg"
    fake_contract.write_bytes(_valid_png_bytes())
    rejected = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "contract", "filePath": str(fake_contract)},
    )
    assert rejected.status_code == 400, rejected.text

    receipt = _write_valid_png(tmp_path / "deposit-receipt.png")
    accepted = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "deposit_receipt", "filePath": str(receipt)},
    )
    assert accepted.status_code == 200, accepted.text

    lawyer_email = tmp_path / "order-to-lawyer.eml"
    lawyer_email.write_text(
        "From: realtor@example.com\n"
        "To: lawyer@example.com\n"
        "Subject: Order to lawyer\n\n"
        "Please open the conveyance file.",
        encoding="utf-8",
    )
    accepted = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "order_to_lawyer", "filePath": str(lawyer_email)},
    )
    assert accepted.status_code == 200, accepted.text

    lawyer_docx = _write_valid_docx(
        tmp_path / "order-to-lawyer.docx",
        "Please open the conveyance file",
    )
    accepted = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "order_to_lawyer", "filePath": str(lawyer_docx)},
    )
    assert accepted.status_code == 200, accepted.text


def test_attachment_archive_and_file_validation_is_bounded(
    client,
    monkeypatch,
    tmp_path,
):
    import elevate_cli.data.deals as deals_data

    deal = _create(title="Bounded attachments", dispatch_initial_stage=False)
    text_file = tmp_path / "large.txt"
    text_file.write_bytes(b"12345")
    with monkeypatch.context() as bounded:
        bounded.setattr(deals_data, "_MAX_ATTACHMENT_FILE_BYTES", 4)
        response = client.post(
            f"/api/deals/{deal['id']}/attachments",
            json={"kind": "supporting_document", "filePath": str(text_file)},
        )
    assert response.status_code == 400, response.text

    too_many = tmp_path / "too-many.zip"
    with zipfile.ZipFile(too_many, "w") as archive:
        archive.writestr("one.png", _valid_png_bytes())
        archive.writestr("two.png", _valid_png_bytes())
    with monkeypatch.context() as bounded:
        bounded.setattr(deals_data, "_MAX_ARCHIVE_FILE_COUNT", 1)
        response = client.post(
            f"/api/deals/{deal['id']}/attachments",
            json={"kind": "listing_photos", "filePath": str(too_many)},
        )
    assert response.status_code == 400, response.text

    too_expanded = tmp_path / "too-expanded.zip"
    with zipfile.ZipFile(too_expanded, "w") as archive:
        archive.writestr("photo.png", _valid_png_bytes())
    with monkeypatch.context() as bounded:
        bounded.setattr(deals_data, "_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 4)
        response = client.post(
            f"/api/deals/{deal['id']}/attachments",
            json={"kind": "listing_photos", "filePath": str(too_expanded)},
        )
    assert response.status_code == 400, response.text

    valid_docx = _write_valid_docx(tmp_path / "valid-contract.docx")
    accepted = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "contract", "filePath": str(valid_docx)},
    )
    assert accepted.status_code == 200, accepted.text

    bounded_docx = _write_valid_docx(tmp_path / "bounded-contract.docx")
    with monkeypatch.context() as bounded:
        bounded.setattr(deals_data, "_MAX_DOCX_FILE_COUNT", 1)
        response = client.post(
            f"/api/deals/{deal['id']}/attachments",
            json={"kind": "contract", "filePath": str(bounded_docx)},
        )
    assert response.status_code == 400, response.text

    with monkeypatch.context() as bounded:
        bounded.setattr(deals_data, "_MAX_DOCX_UNCOMPRESSED_BYTES", 8)
        response = client.post(
            f"/api/deals/{deal['id']}/attachments",
            json={"kind": "contract", "filePath": str(bounded_docx)},
        )
    assert response.status_code == 400, response.text


def test_bounded_archive_metadata_counts_directories_and_rejects_ambiguity():
    import elevate_cli.data.deals as deals_data

    directory = zipfile.ZipInfo("photos/")
    member = zipfile.ZipInfo("photos/listing.png")

    class ArchiveMetadata:
        def __init__(self, infos):
            self._infos = infos

        def infolist(self):
            return self._infos

    with pytest.raises(ValueError, match="too many files"):
        deals_data._bounded_archive_infos(
            ArchiveMetadata([directory, member]),
            label="test ZIP",
            max_files=1,
            max_uncompressed_bytes=1024,
        )

    duplicate_a = zipfile.ZipInfo("same-name.png")
    duplicate_b = zipfile.ZipInfo("same-name.png")
    with pytest.raises(ValueError, match="duplicate member names"):
        deals_data._bounded_archive_infos(
            ArchiveMetadata([duplicate_a, duplicate_b]),
            label="test ZIP",
            max_files=2,
            max_uncompressed_bytes=1024,
        )

    encrypted = zipfile.ZipInfo("encrypted.png")
    encrypted.flag_bits |= 0x1
    with pytest.raises(ValueError, match="encrypted members"):
        deals_data._bounded_archive_infos(
            ArchiveMetadata([encrypted]),
            label="test ZIP",
            max_files=1,
            max_uncompressed_bytes=1024,
        )


def test_attachment_format_helpers_reject_disguised_and_malformed_artifacts(
    tmp_path,
):
    import elevate_cli.data.deals as deals_data

    signed_text = tmp_path / "signed-documents.txt"
    signed_text.write_text("not a signed PDF", encoding="utf-8")
    signed_path = Path(deals_data._validated_deal_attachment_path(str(signed_text)))
    with pytest.raises(ValueError, match="incompatible with kind signed_docs"):
        deals_data._validate_deal_attachment_kind("signed_docs", signed_path)

    fake_contract = tmp_path / "contract.jpg"
    fake_contract.write_bytes(_valid_png_bytes())
    contract_path = Path(
        deals_data._validated_deal_attachment_path(str(fake_contract))
    )
    with pytest.raises(ValueError, match="incompatible with kind contract"):
        deals_data._validate_deal_attachment_kind("contract", contract_path)

    malformed_docx = tmp_path / "malformed-contract.docx"
    with zipfile.ZipFile(malformed_docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='urn:test'><w:body><w:p>broken",
        )
    with pytest.raises(ValueError, match="document XML is malformed"):
        deals_data._validated_deal_attachment_path(str(malformed_docx))

    valid_docx = _write_valid_docx(tmp_path / "valid-contract.docx")
    validated_docx = Path(
        deals_data._validated_deal_attachment_path(str(valid_docx))
    )
    deals_data._validate_deal_attachment_kind("contract", validated_docx)

    receipt = _write_valid_png(tmp_path / "receipt.png")
    receipt_path = Path(deals_data._validated_deal_attachment_path(str(receipt)))
    deals_data._validate_deal_attachment_kind("deposit_receipt", receipt_path)


def test_listing_photo_zip_decode_work_is_bounded(monkeypatch, tmp_path):
    import elevate_cli.data.deals as deals_data

    assert deals_data._MAX_LISTING_PHOTO_DECODE_ATTEMPTS == 8
    assert deals_data._MAX_LISTING_PHOTO_MEMBER_BYTES == 25 * 1024 * 1024

    attempt_limited = tmp_path / "attempt-limited.zip"
    with zipfile.ZipFile(attempt_limited, "w") as archive:
        archive.writestr("first.png", b"not an image")
        archive.writestr("second.png", _valid_png_bytes())
    with monkeypatch.context() as bounded:
        bounded.setattr(deals_data, "_MAX_LISTING_PHOTO_DECODE_ATTEMPTS", 1)
        with pytest.raises(ValueError, match="no physically valid"):
            deals_data._validate_deal_attachment_kind(
                "listing_photos",
                attempt_limited,
            )

    member_limited = tmp_path / "member-limited.zip"
    valid_png = _valid_png_bytes()
    with zipfile.ZipFile(member_limited, "w") as archive:
        archive.writestr("listing.png", valid_png)
    with monkeypatch.context() as bounded:
        bounded.setattr(
            deals_data,
            "_MAX_LISTING_PHOTO_MEMBER_BYTES",
            len(valid_png) - 1,
        )
        with pytest.raises(ValueError, match="no physically valid"):
            deals_data._validate_deal_attachment_kind(
                "listing_photos",
                member_limited,
            )


def test_deleted_attachment_remains_history_but_no_longer_satisfies_gate(
    client,
    tmp_path,
):
    deal = _create(
        title="Deleted CMA evidence",
        current_stage=1,
        dispatch_initial_stage=False,
    )
    cma_path = _write_valid_pdf(tmp_path / "deleted-cma.pdf", "Current CMA")
    attached = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "cma_report", "filePath": str(cma_path)},
    )
    assert attached.status_code == 200, attached.text
    before = client.get(f"/api/deals/{deal['id']}/context").json()
    assert not any(
        item["kind"] == "cma_report"
        for item in before["dealFlow"]["gate"]["missingDocs"]
    )

    with connect() as conn:
        from elevate_cli.data import get_deal
        from elevate_cli.data.deals import deal_card_gate

        deal_row = get_deal(conn, deal["id"])
        before_card = deal_card_gate(conn, deal_row)

    cma_path.unlink()
    after = client.get(f"/api/deals/{deal['id']}/context").json()
    assert after["attachments"][0]["physicalAvailable"] is False
    assert any(
        item["kind"] == "cma_report"
        for item in after["dealFlow"]["gate"]["missingDocs"]
    )
    with connect() as conn:
        from elevate_cli.data import get_deal
        from elevate_cli.data.deals import deal_card_gate, deal_open_stage_cells
        from elevate_cli.admin_deal_flow import resolve_deal_phase
        from unittest.mock import patch

        deal_row = get_deal(conn, deal["id"])
        after_card = deal_card_gate(conn, deal_row)
        assert after_card["missingCount"] == before_card["missingCount"] + 1
        with patch(
            "elevate_cli.admin_deal_flow.resolve_deal_phase",
            wraps=resolve_deal_phase,
        ) as resolver:
            deal_open_stage_cells(conn, deal_row)
        assert resolver.call_args.kwargs["attachments"] == []


def test_legacy_remote_attachment_row_is_auditable_but_not_gate_evidence(
    client,
    tmp_path,
):
    deal = _create(
        title="Legacy remote reference",
        current_stage=1,
        dispatch_initial_stage=False,
    )
    local = _write_valid_pdf(tmp_path / "legacy-cma.pdf", "Imported CMA")
    attached = client.post(
        f"/api/deals/{deal['id']}/attachments",
        json={"kind": "cma_report", "filePath": str(local)},
    )
    assert attached.status_code == 200, attached.text
    with connect() as conn:
        conn.execute(
            "UPDATE deal_attachments SET file_path=? WHERE id=?",
            ("https://legacy.example/cma.pdf", attached.json()["id"]),
        )

    context = client.get(f"/api/deals/{deal['id']}/context").json()
    assert context["attachments"][0]["filePath"] == "https://legacy.example/cma.pdf"
    assert context["attachments"][0]["physicalAvailable"] is False
    assert any(
        item["kind"] == "cma_report"
        for item in context["dealFlow"]["gate"]["missingDocs"]
    )


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
            current_stage=7,
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
    assert {item["packageKey"] for item in tasks} == {"ca.bc"}
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


def test_run_result_callback_updates_run_and_attaches_artifacts(client, tmp_path):
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
    cma_path = _write_valid_pdf(tmp_path / "context-cma.pdf", "Generated CMA")

    resp = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "run-result-test",
            "artifacts": [
                {"kind": "cma_report", "filePath": str(cma_path), "summary": "PDF generated"}
            ],
            "next_tasks": [{"skill": "cma:pdf", "args": {"deal_id": deal["id"]}}],
            "checklist_updates": [{"id": "pricing-recap", "completed": True}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["outputPath"] == str(cma_path.resolve())
    context = client.get(f"/api/deals/{deal['id']}/context").json()
    assert context["attachments"][0]["sourceRunId"] == run_id
    assert context["checklist"]["draft-cma-followup"] is True
    assert context["checklist"]["pricing-recap"] is True
    assert any(
        run["payload"].get("result", {}).get("nextTasks")
        for run in context["priorRuns"]
    )

    # An idempotent callback is a receipt for the terminal result already
    # recorded. Cleanup after that result must not make the replay fail by
    # revalidating a path that no longer exists.
    cma_path.unlink()
    replay = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "run-result-test",
            "artifacts": [
                {"kind": "cma_report", "filePath": str(cma_path), "summary": "PDF generated"}
            ],
            "next_tasks": [{"skill": "cma:pdf", "args": {"deal_id": deal["id"]}}],
            "checklist_updates": [{"id": "pricing-recap", "completed": True}],
        },
    )
    assert replay.status_code == 200, replay.text

    after_cleanup = client.get(f"/api/deals/{deal['id']}/context").json()
    assert after_cleanup["attachments"][0]["physicalAvailable"] is False
    assert after_cleanup["checklist"]["pricing-recap"] is True
    with connect() as conn:
        queued = list_action_runs(conn, deal_id=deal["id"])
        attachments = list_deal_attachments(conn, deal["id"])
    assert any(run["payload"].get("trigger") == "next_task" for run in queued)
    assert len([item for item in attachments if item["sourceRunId"] == run_id]) == 1


def test_run_result_rejects_missing_artifact_without_closing_run_or_gate(
    client,
    tmp_path,
):
    deal = _create(
        title="Run result physical truth",
        current_stage=1,
        dispatch_initial_stage=False,
    )
    with connect() as conn:
        action = create_action(
            conn,
            name="Physical artifact callback",
            trigger="stage_entry",
            skill="cma:physical-proof",
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
    run = next(item for item in runs if item["registryId"] == action["id"])
    valid_first = _write_valid_pdf(
        tmp_path / "valid-first.pdf",
        "Must roll back when the second artifact is missing",
    )

    response = client.post(
        f"/api/deals/{deal['id']}/runs/{run['id']}/result",
        json={
            "status": "completed",
            "idempotencyKey": "missing-artifact-must-rollback",
            "artifacts": [
                {
                    "kind": "supporting_document",
                    "filePath": str(valid_first),
                },
                {
                    "kind": "cma_report",
                    "filePath": str(tmp_path / "never-created.pdf"),
                }
            ],
            "checklist_updates": [
                {"id": "pricing-recap", "completed": True}
            ],
        },
    )

    assert response.status_code == 400, response.text
    with connect() as conn:
        persisted = next(
            item
            for item in list_action_runs(conn, deal_id=deal["id"])
            if item["id"] == run["id"]
        )
        attachments = list_deal_attachments(conn, deal["id"])
    assert persisted["status"] not in {"succeeded", "completed"}
    assert not persisted.get("result")
    assert attachments == []
    context = client.get(f"/api/deals/{deal['id']}/context").json()
    assert context["checklist"].get("pricing-recap") is not True


def test_document_run_contract_rejects_empty_wrong_kind_wrong_deal_and_invalid_artifacts(
    client,
    tmp_path,
):
    deal = _create(
        title="Buyer CPS artifact truth",
        side="buyer",
        current_stage=1,
        dispatch_initial_stage=False,
    )
    other_deal = _create(
        title="Different buyer deal",
        side="buyer",
        current_stage=1,
        dispatch_initial_stage=False,
    )
    with connect() as conn:
        action = create_action(
            conn,
            name="CPS artifact contract",
            trigger="stage_entry",
            skill="real-estate-admin/buyer-cps",
            skill_args={
                "mode": "draft",
                "requiredArtifactKinds": ["cps_draft"],
            },
            side="buyer",
            to_stage=1,
        )
        run = next(
            item
            for item in evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="stage_entry",
                actor="human:test",
                to_stage=1,
            )
            if item["registryId"] == action["id"]
        )

    endpoint = f"/api/deals/{deal['id']}/runs/{run['id']}/result"
    empty = client.post(
        endpoint,
        json={"status": "completed", "idempotencyKey": "cps-empty"},
    )
    assert empty.status_code == 400, empty.text
    assert "cps_draft" in empty.text

    wrong_kind_pdf = _write_valid_pdf(tmp_path / "wrong-kind.pdf", "Different document")
    wrong_kind = client.post(
        endpoint,
        json={
            "status": "completed",
            "idempotencyKey": "cps-wrong-kind",
            "artifacts": [
                {"kind": "supporting_document", "filePath": str(wrong_kind_pdf)}
            ],
        },
    )
    assert wrong_kind.status_code == 400, wrong_kind.text
    assert "cps_draft" in wrong_kind.text

    invalid = client.post(
        endpoint,
        json={
            "status": "completed",
            "idempotencyKey": "cps-invalid",
            "artifacts": [
                {"kind": "cps_draft", "filePath": str(tmp_path / "missing.pdf")}
            ],
        },
    )
    assert invalid.status_code == 400, invalid.text

    malformed_pdf = tmp_path / "malformed-cps.pdf"
    malformed_pdf.write_bytes(b"not a real PDF")
    malformed = client.post(
        endpoint,
        json={
            "status": "completed",
            "idempotencyKey": "cps-malformed",
            "artifacts": [
                {"kind": "cps_draft", "filePath": str(malformed_pdf)}
            ],
        },
    )
    assert malformed.status_code == 400, malformed.text

    wrong_deal = client.post(
        f"/api/deals/{other_deal['id']}/runs/{run['id']}/result",
        json={"status": "completed", "idempotencyKey": "cps-wrong-deal"},
    )
    assert wrong_deal.status_code == 404, wrong_deal.text

    cps_pdf = _write_valid_pdf(tmp_path / "cps-draft.pdf", "Buyer CPS draft")
    valid = client.post(
        endpoint,
        json={
            "status": "completed",
            "idempotencyKey": "cps-valid",
            "artifacts": [
                {"kind": "cps_draft", "filePath": str(cps_pdf)}
            ],
        },
    )
    assert valid.status_code == 200, valid.text
    body = valid.json()
    assert body["status"] == "succeeded"
    assert body["result"]["requiredArtifactKinds"] == ["cps_draft"]
    assert body["result"]["verifiedArtifactKinds"] == ["cps_draft"]
    with connect() as conn:
        attachments = list_deal_attachments(conn, deal["id"])
    assert [(item["kind"], item["filePath"]) for item in attachments] == [
        ("cps_draft", str(cps_pdf.resolve()))
    ]


def test_mlc_document_run_contract_accepts_verified_mlc_pdf(client, tmp_path):
    deal = _create(
        title="Listing MLC artifact truth",
        side="listing",
        current_stage=2,
        dispatch_initial_stage=False,
    )
    with connect() as conn:
        action = create_action(
            conn,
            name="MLC artifact contract",
            trigger="stage_entry",
            skill="real-estate-admin/mlc",
            skill_args={
                "mode": "documents",
                "requiredArtifactKinds": ["mlc_pdf"],
            },
            side="listing",
            to_stage=2,
        )
        run = next(
            item
            for item in evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="stage_entry",
                actor="human:test",
                to_stage=2,
            )
            if item["registryId"] == action["id"]
        )

    wrong_extension = _write_valid_docx(
        tmp_path / "mlc.docx",
        "Multiple Listing Contract draft",
    )
    rejected = client.post(
        f"/api/deals/{deal['id']}/runs/{run['id']}/result",
        json={
            "status": "completed",
            "idempotencyKey": "mlc-wrong-extension",
            "artifacts": [
                {"kind": "mlc_pdf", "filePath": str(wrong_extension)}
            ],
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "incompatible with kind mlc_pdf" in rejected.text

    mlc_pdf = _write_valid_pdf(tmp_path / "mlc.pdf", "Multiple Listing Contract draft")
    response = client.post(
        f"/api/deals/{deal['id']}/runs/{run['id']}/result",
        json={
            "status": "completed",
            "idempotencyKey": "mlc-valid",
            "artifacts": [{"kind": "mlc_pdf", "filePath": str(mlc_pdf)}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["result"]["requiredArtifactKinds"] == ["mlc_pdf"]
    assert response.json()["result"]["verifiedArtifactKinds"] == ["mlc_pdf"]


def test_failed_run_cannot_attach_success_evidence(client, tmp_path):
    deal = _create(
        title="Failed run artifact",
        current_stage=1,
        dispatch_initial_stage=False,
    )
    with connect() as conn:
        action = create_action(
            conn,
            name="Failed artifact callback",
            trigger="stage_entry",
            skill="cma:failed-proof",
            side="listing",
            to_stage=1,
        )
        run = next(
            item
            for item in evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="stage_entry",
                actor="human:test",
                to_stage=1,
            )
            if item["registryId"] == action["id"]
        )
    artifact = _write_valid_pdf(tmp_path / "failed-run.pdf", "Failure evidence")

    response = client.post(
        f"/api/deals/{deal['id']}/runs/{run['id']}/result",
        json={
            "status": "failed",
            "idempotencyKey": "failed-run-cannot-attach",
            "artifacts": [
                {"kind": "cma_report", "filePath": str(artifact)}
            ],
            "error": "generation failed",
        },
    )

    assert response.status_code == 400, response.text
    with connect() as conn:
        assert list_deal_attachments(conn, deal["id"]) == []


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


def test_run_result_clearing_phase_gate_advances_without_stage_complete_flag(client, tmp_path):
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
    cma_path = _write_valid_pdf(tmp_path / "gate-clear-cma.pdf", "Gate clear CMA")

    resp = client.post(
        f"/api/deals/{deal['id']}/runs/{run_id}/result",
        json={
            "status": "completed",
            "idempotencyKey": "gate-clear-auto-move",
            "artifacts": [
                {"kind": "cma_report", "filePath": str(cma_path), "summary": "CMA report"}
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


def _configure_document_pack(pack_root: Path, *, realtor: str = "Current Realtor", brokerage: str = "Current Brokerage"):
    with connect() as conn:
        update_admin_setup(
            conn,
            profile={"realtorLegalName": realtor, "brokerageName": brokerage},
            items=[
                {
                    "key": "forms_provider",
                    "status": "configured",
                    "provider": "test document pack",
                    "value": {"documentPackRoot": str(pack_root)},
                }
            ],
        )


def test_offer_kit_path_is_contained_in_beta_root(monkeypatch, tmp_path):
    from elevate_cli.web_routes.admin_deals import _offer_kit_path

    beta_root = tmp_path / "Elevate Beta"
    monkeypatch.setenv("ELEVATE_HOME", str(beta_root))

    path = _offer_kit_path("../../outside-deal", "../outside-document")

    assert path.is_relative_to(beta_root.resolve())
    assert path.parent == (beta_root / "cache" / "documents" / "admin_artifacts" / "offer-kits").resolve()


def test_offer_kit_path_rejects_symlink_escape(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from elevate_cli.web_routes.admin_deals import _offer_kit_path

    beta_root = tmp_path / "Elevate Beta"
    outside = tmp_path / "outside"
    beta_root.mkdir()
    outside.mkdir()
    (beta_root / "cache").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("ELEVATE_HOME", str(beta_root))

    with pytest.raises(HTTPException) as raised:
        _offer_kit_path("deal", "document")

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "document_artifact_outside_profile"


def test_exact_beta_blocks_every_mutable_or_open_local_form_pack_route(
    client,
    monkeypatch,
):
    from elevate_cli.data import get_deal

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    deal = _create(
        title="Exact Beta local form routes",
        side="buyer",
        dispatch_initial_stage=False,
    )
    cps_body = {
        "umbrella": "residential",
        "clauses": [],
        "customClauses": [],
        "vars": {},
        "deal_id": deal["id"],
    }
    calls = [
        ("post", f"/api/admin/deals/{deal['id']}/offer-kit/build", None),
        (
            "post",
            f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/generate",
            None,
        ),
        (
            "post",
            f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/approve",
            {"status": "approved"},
        ),
        (
            "post",
            f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/field",
            {"key": "price", "value": "650000"},
        ),
        (
            "post",
            f"/api/admin/deals/{deal['id']}/kit-doc/add",
            {"templateId": "cps-residential"},
        ),
        ("get", f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential", None),
        ("post", "/api/admin/offer-prep/generate", cps_body),
        (
            "post",
            "/api/admin/offer-prep/form",
            {"form": "pnc", "deal_id": deal["id"]},
        ),
        ("post", "/api/admin/offer-prep/package", cps_body),
        (
            "post",
            f"/api/admin/deals/{deal['id']}/onboarding-doc",
            {"form": "agency"},
        ),
        ("post", f"/api/admin/deals/{deal['id']}/onboarding-sign", None),
    ]

    for method, path, payload in calls:
        response = client.request(method, path, json=payload)
        assert response.status_code == 409, (path, response.text)
        assert response.json()["detail"]["code"] == "local_reference_form_route_disabled"
        assert "licensed provider" in response.json()["detail"]["message"]

    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    assert "offerKit" not in stored["extraToggles"]


def test_offer_kit_build_does_not_mark_missing_pdfs_ready(client):
    from elevate_constants import get_elevate_home
    from elevate_cli.data import get_deal

    deal = _create(title="Truthful offer kit", side="buyer", dispatch_initial_stage=False)
    response = client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build")

    assert response.status_code == 200, response.text
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    docs = stored["extraToggles"]["offerKit"]["documents"]
    assert docs
    assert all(doc["ready"] is False for doc in docs)
    assert all(Path(doc["filePath"]).is_relative_to(get_elevate_home().resolve()) for doc in docs)


def test_generate_uses_current_admin_identity_and_file_backed_ready(client, monkeypatch, tmp_path):
    import json
    import subprocess
    from types import SimpleNamespace
    from elevate_constants import get_elevate_home
    from elevate_cli.data import get_deal

    pack = tmp_path / "configured-pack"
    forms = pack / "knowledge" / "deals" / "forms"
    forms.mkdir(parents=True)
    engine = forms / "fill-form-generic.py"
    template = forms / "cps-residential-fillable-template.pdf"
    engine.write_text("# configured test engine\n", encoding="utf-8")
    template.write_bytes(b"%PDF-1.4\n%%EOF\n")
    _configure_document_pack(pack, realtor="Profile Realtor", brokerage="Profile Brokerage")
    deal = _create(title="Identity form", side="buyer", dispatch_initial_stage=False)
    built = client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build")
    assert built.status_code == 200, built.text

    captured = {}
    captured_path = None

    def fake_run(args, **kwargs):
        nonlocal captured_path
        captured_path = Path(args[2])
        captured.update(json.loads(Path(args[2]).read_text(encoding="utf-8")))
        Path(args[4]).write_bytes(b"%PDF-1.4\n%%EOF\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    response = client.post(f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/generate")

    assert response.status_code == 200, response.text
    assert captured["agentName"] == "Profile Realtor"
    assert captured["officeName"] == "Profile Brokerage"
    assert captured_path.is_relative_to(get_elevate_home().resolve())
    assert not captured_path.exists()
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    cps = stored["extraToggles"]["offerKit"]["documents"][0]
    assert cps["ready"] is True
    assert Path(cps["filePath"]).is_file()


def test_missing_engine_fails_closed_without_ready_pdf(client, tmp_path):
    from elevate_cli.data import get_deal

    pack = tmp_path / "pack-without-engine"
    forms = pack / "knowledge" / "deals" / "forms"
    forms.mkdir(parents=True)
    (forms / "cps-residential-fillable-template.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    _configure_document_pack(pack)
    deal = _create(title="Missing engine", side="buyer", dispatch_initial_stage=False)
    built = client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build")
    assert built.status_code == 200, built.text

    response = client.post(f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/generate")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_asset_missing"
    assert response.json()["detail"]["asset"] == "formEngine"
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    assert stored["extraToggles"]["offerKit"]["documents"][0]["ready"] is False


def test_missing_listing_pull_asset_does_not_claim_started(client, tmp_path):
    from elevate_cli.data import get_deal

    pack = tmp_path / "pack-without-listing-pull"
    pack.mkdir()
    _configure_document_pack(pack)
    deal = _create(title="Missing listing pull", side="buyer", dispatch_initial_stage=False)

    response = client.post(
        f"/api/admin/deals/{deal['id']}/pull-listing",
        json={"mls": "1234567"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_asset_missing"
    assert response.json()["detail"]["asset"] == "listingPull"
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    assert "listingPullStatus" not in stored["extraToggles"]


def test_generate_does_not_treat_stale_pdf_as_new_output(client, monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from elevate_cli.data import get_deal

    pack = tmp_path / "configured-pack"
    forms = pack / "knowledge" / "deals" / "forms"
    forms.mkdir(parents=True)
    (forms / "fill-form-generic.py").write_text("# configured test engine\n", encoding="utf-8")
    (forms / "cps-residential-fillable-template.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    _configure_document_pack(pack)
    deal = _create(title="Stale generated form", side="buyer", dispatch_initial_stage=False)
    assert client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build").status_code == 200
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    output = Path(stored["extraToggles"]["offerKit"]["documents"][0]["filePath"])
    output.write_bytes(b"stale prior output")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    response = client.post(
        f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/generate"
    )

    assert response.status_code == 500
    assert "did not produce a valid new PDF" in response.json()["detail"]
    assert output.read_bytes() == b"stale prior output"
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
    assert stored["extraToggles"]["offerKit"]["documents"][0]["ready"] is False


def test_kit_document_serve_rejects_path_outside_profile(client, tmp_path):
    import json

    deal = _create(title="Contained kit file", side="buyer", dispatch_initial_stage=False)
    assert client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build").status_code == 200
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\nprivate\n%%EOF\n")
    with connect() as conn:
        row = conn.execute(
            "SELECT extra_toggles_json FROM deals WHERE id=?", (deal["id"],)
        ).fetchone()
        toggles = json.loads(row["extra_toggles_json"])
        toggles["offerKit"]["documents"][0]["filePath"] = str(outside)
        conn.execute(
            "UPDATE deals SET extra_toggles_json=? WHERE id=?",
            (json.dumps(toggles), deal["id"]),
        )

    response = client.get(
        f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_artifact_outside_profile"


def test_approve_rejects_missing_document(client):
    deal = _create(title="Missing approval PDF", side="buyer", dispatch_initial_stage=False)
    assert client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build").status_code == 200

    response = client.post(
        f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/approve",
        json={"status": "approved"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "kit document not generated yet"


def test_upload_rejects_non_pdf_without_adding_ready_document(client):
    import base64
    from elevate_cli.data import get_deal

    deal = _create(title="Invalid PDF upload", side="buyer", dispatch_initial_stage=False)
    assert client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build").status_code == 200
    with connect() as conn:
        before = get_deal(conn, deal["id"])
    before_count = len(before["extraToggles"]["offerKit"]["documents"])

    response = client.post(
        f"/api/admin/deals/{deal['id']}/kit-doc/add",
        json={
            "filename": "not-really.pdf",
            "contentB64": base64.b64encode(b"plain text").decode("ascii"),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "uploaded file is not a PDF"
    with connect() as conn:
        after = get_deal(conn, deal["id"])
    assert len(after["extraToggles"]["offerKit"]["documents"]) == before_count


def test_field_edit_invalidates_generated_document(client):
    import json
    from elevate_cli.data import get_deal

    deal = _create(title="Edited generated form", side="buyer", dispatch_initial_stage=False)
    assert client.post(f"/api/admin/deals/{deal['id']}/offer-kit/build").status_code == 200
    with connect() as conn:
        stored = get_deal(conn, deal["id"])
        toggles = stored["extraToggles"]
        cps = toggles["offerKit"]["documents"][0]
        Path(cps["filePath"]).write_bytes(b"%PDF-1.4\n%%EOF\n")
        cps["ready"] = True
        cps["status"] = "approved"
        conn.execute(
            "UPDATE deals SET extra_toggles_json=? WHERE id=?",
            (json.dumps(toggles), deal["id"]),
        )

    response = client.post(
        f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential/field",
        json={"key": "price", "value": "750000"},
    )

    assert response.status_code == 200, response.text
    with connect() as conn:
        updated = get_deal(conn, deal["id"])
    docs = updated["extraToggles"]["offerKit"]["documents"]
    assert all(doc["ready"] is False and doc["status"] == "draft" for doc in docs)
    served = client.get(f"/api/admin/deals/{deal['id']}/kit-doc/cps-residential")
    assert served.status_code == 409
    assert served.json()["detail"] == "regenerate this document before opening it"
