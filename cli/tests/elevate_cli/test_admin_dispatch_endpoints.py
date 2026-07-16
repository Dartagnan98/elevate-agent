"""PR-2 Admin Hub dispatcher tests.

Covers the registry CRUD endpoints, the run-log endpoint, and the hook
into ``data.deals`` (move_deal_stage, set_deal_toggle).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    approve_action_run,
    complete_run_with_reviewed_manual_pdf,
    complete_admin_setup,
    connect,
    create_action,
    create_deal,
    drain_queued_action_runs,
    ensure_default_admin_actions,
    evaluate_dispatch,
    get_admin_setup,
    import_exp_agent_centre,
    list_action_runs,
    list_actions,
    move_deal_stage,
    mark_stale_action_runs,
    promote_profile_to_admin_deal,
    queue_action_run,
    record_date_trigger_firing,
    record_run_result,
    set_deal_toggle,
    update_admin_setup,
)
from elevate_cli.data._util import now_iso
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


def _configure_test_forms_provider(conn) -> None:
    get_admin_setup(conn)
    conn.execute(
        "UPDATE admin_setup_items SET status='configured', provider=?, value_json=? "
        "WHERE key='forms_provider'",
        (
            "test",
            json.dumps(
                {
                    "provider": "test",
                    "playbook": {
                        "provider": "test",
                        "loginUrl": "https://forms.example.test/login",
                        "accountEmail": None,
                        "sessionMode": "existing_session",
                    },
                }
            ),
        ),
    )


def _write_valid_pdf(path: Path, text: str = "Verified test artifact") -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def _document_reference(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _manual_export_claim(
    *,
    pdf: Path,
    deal_id: str,
    run_id: str,
    form_code: str,
    deal_reference: str,
    provider: str = "test",
    reviewer_name: str = "Test Realtor",
    receipt_id: str = "manual-export-test-1",
    version_status: str = "unverified",
    document_version: str | None = None,
    effective_date: str | None = None,
    version_verified_at: str | None = None,
) -> dict[str, object]:
    return {
        "schema": "elevate.manual-provider-export-claim.v1",
        "sourceVerified": False,
        "receiptId": receipt_id,
        "dealId": deal_id,
        "taskId": run_id,
        "formCode": form_code,
        "provider": provider,
        "reviewerName": reviewer_name,
        "artifactSha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "dealReference": _document_reference(deal_reference),
        "versionStatus": version_status,
        "documentVersion": document_version,
        "effectiveDate": effective_date,
        "versionVerifiedAt": version_verified_at,
    }


def _manual_completion_kwargs(
    *,
    pdf: Path,
    deal: dict,
    run: dict,
    kind: str,
    form_code: str,
    **receipt_overrides,
) -> dict[str, object]:
    provider = str(receipt_overrides.pop("provider", "test"))
    reviewer_name = str(receipt_overrides.pop("reviewer_name", "Test Realtor"))
    version_status = str(receipt_overrides.pop("version_status", "unverified"))
    document_version = receipt_overrides.pop("document_version", None)
    effective_date = receipt_overrides.pop("effective_date", None)
    version_verified_at = receipt_overrides.pop("version_verified_at", None)
    receipt = _manual_export_claim(
        pdf=pdf,
        deal_id=deal["id"],
        run_id=run["id"],
        form_code=form_code,
        deal_reference=deal.get("listingAddress") or deal["title"],
        provider=provider,
        reviewer_name=reviewer_name,
        version_status=version_status,
        document_version=document_version,
        effective_date=effective_date,
        version_verified_at=version_verified_at,
        **receipt_overrides,
    )
    return {
        "kind": kind,
        "file_path": str(pdf),
        "reviewed": True,
        "form_code": form_code,
        "provider": provider,
        "reviewer_name": reviewer_name,
        "version_status": version_status,
        "document_version": document_version,
        "effective_date": effective_date,
        "version_verified_at": version_verified_at,
        "source_receipt": receipt,
    }


def _set_fresh_forms_provider_proof(conn, *, available: bool) -> None:
    """Seed or revoke the identity-bound runtime proof used by exact Beta."""
    get_admin_setup(conn)
    provider = "WEBForms"
    value: dict[str, object] = {"provider": provider}
    if available:
        checked_at = now_iso()
        value["verification"] = {
            "checkedAt": checked_at,
            "verifiedBy": "forms_provider_task_receipt",
            "signals": ["Licensed forms provider MLC/CPS lookup verified"],
            "details": {
                "sourceId": "forms-signing",
                "receiptSchema": "elevate.forms-provider-proof.v1",
                "taskReceiptId": "test-provider-task-receipt",
                "probeKind": "licensed_forms_template_lookup",
                "probeStatus": "succeeded",
                "providerProof": True,
                "providerIdentity": "webforms",
                "lastCheckedAt": checked_at,
                "providerLookup": {
                    "mlcExactMatch": True,
                    "cpsExactMatch": True,
                    "matchedFormCodes": ["MLC", "CPS-res"],
                },
            },
        }
    conn.execute(
        """
        UPDATE admin_setup_items
        SET status='configured', provider=?, value_json=?
        WHERE key='forms_provider'
        """,
        (provider, json.dumps(value)),
    )


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
    assert body["skill"] == "real-estate-admin/marketing"
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
    _complete_admin_setup()
    with connect() as conn:
        return create_deal(
            conn,
            title="Test listing",
            side="listing",
            actor="human:test",
            current_stage=4,
            province="BC",
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
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert len(runs) == 1
    run = runs[0]
    assert run["registryId"] == action["id"]
    assert run["dealId"] == deal["id"]
    assert run["status"] == "running"
    assert run["cronJobId"]
    assert run["startedAt"]
    assert run["skill"] == "real-estate-admin/marketing"
    assert run["registryName"] == "just_listed entry"
    assert run["payload"]["toStage"] == 5
    assert run["payload"]["registryName"] == "just_listed entry"


def test_replaying_same_event_does_not_duplicate_action_run():
    deal = _new_listing_deal()
    with connect() as conn:
        action = create_action(
            conn,
            name="idempotent entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
        )
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)
        event = next(
            item for item in list_action_runs(conn, deal_id=deal["id"])
            if item["registryId"] == action["id"]
        )
        replay = evaluate_dispatch(
            conn,
            deal_id=deal["id"],
            deal_event_id=event["dealEventId"],
            trigger="stage_entry",
            actor="human:test",
            to_stage=5,
            create_cron_jobs=True,
        )
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert len(runs) == 1
    assert replay[0]["id"] == runs[0]["id"]


def test_admin_run_dispatch_waits_for_verified_admin_setup():
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Setup gated listing",
            side="listing",
            actor="human:test",
            current_stage=4,
        )
        create_action(
            conn,
            name="setup gated entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
        )
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)
        runs = list_action_runs(conn, deal_id=deal["id"])
        drained = drain_queued_action_runs(conn, actor="test-worker")

    assert drained == []
    assert len(runs) == 1
    assert runs[0]["status"] == "queued"
    assert runs[0]["cronJobId"] is None
    assert "admin setup is required" in runs[0]["payload"]["dispatchBlocked"]["message"]


def test_exact_beta_setup_blocked_run_becomes_visible_waiting_human(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Beta setup gated listing",
            side="listing",
            actor="human:test",
            current_stage=0,
        )
        queued = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/marketing",
            name="Beta setup gated action",
            create_cron_job=False,
            actor="human:test",
        )
        drain_queued_action_runs(conn, actor="test-worker")
        run = next(
            item
            for item in list_action_runs(conn, deal_id=deal["id"])
            if item["id"] == queued["id"]
        )

    assert run["status"] == "waiting_human"
    assert run["cronJobId"] is None
    assert run["humanPrompt"]["kind"] == "admin_setup"
    assert "admin setup is required" in run["humanPrompt"]["message"]
    assert run["errorMessage"] == run["humanPrompt"]["message"]


def test_exact_beta_mlc_and_cps_park_without_cron_token_or_success_bypass(
    monkeypatch,
):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )

    def unexpected_spawn(**_kwargs):
        raise AssertionError("live-provider-blocked runs must not create cron jobs")

    monkeypatch.setattr(dispatch_data, "_spawn_cron_job", unexpected_spawn)
    with connect() as conn:
        listing = create_deal(
            conn,
            title="Beta MLC provider gate",
            side="listing",
            actor="human:test",
            current_stage=2,
        )
        mlc_action = create_action(
            conn,
            name="Beta prepare MLC",
            trigger="manual",
            skill="real-estate-admin/mlc",
            side="listing",
            skill_args={
                "mode": "documents",
            },
        )
        mlc = next(
            run
            for run in evaluate_dispatch(
                conn,
                deal_id=listing["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if run["registryId"] == mlc_action["id"]
        )
        mlc_db = conn.execute(
            "SELECT callback_token_hash FROM admin_action_runs WHERE id=?",
            (mlc["id"],),
        ).fetchone()

        assert mlc["status"] == "waiting_human"
        assert mlc["cronJobId"] is None
        assert mlc_db["callback_token_hash"] is None
        assert mlc["humanPrompt"]["kind"] == "forms_provider"
        assert mlc["payload"]["requiresLiveFormsProvider"] is True
        assert mlc["payload"]["formsProviderCapability"]["available"] is False

        with pytest.raises(
            PermissionError,
            match="cannot terminally complete a run awaiting human action",
        ):
            record_run_result(
                conn,
                listing["id"],
                mlc["id"],
                status="succeeded",
                idempotency_key="must-not-bypass-forms-gate",
                artifacts=[],
                actor="skill:test",
            )
        callback = next(
            run for run in list_action_runs(conn, deal_id=listing["id"])
            if run["id"] == mlc["id"]
        )
        assert callback["status"] == "waiting_human"
        assert callback["result"] is None
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM deal_attachments WHERE source_run_id=?",
            (mlc["id"],),
        ).fetchone()["count"] == 0

        buyer = create_deal(
            conn,
            title="Beta CPS provider gate",
            side="buyer",
            actor="human:test",
            current_stage=1,
        )
        cps_action = create_action(
            conn,
            name="Beta prepare CPS",
            trigger="manual",
            skill="real-estate-admin/buyer-cps",
            side="buyer",
            approval_required=True,
        )
        cps = next(
            run
            for run in evaluate_dispatch(
                conn,
                deal_id=buyer["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if run["registryId"] == cps_action["id"]
        )
        cps = approve_action_run(conn, cps["id"], actor="human:test")
        cps_db = conn.execute(
            "SELECT callback_token_hash FROM admin_action_runs WHERE id=?",
            (cps["id"],),
        ).fetchone()

    assert cps["status"] == "waiting_human"
    assert cps["cronJobId"] is None
    assert cps_db["callback_token_hash"] is None
    assert cps["humanPrompt"]["kind"] == "forms_provider"


def test_exact_beta_writable_setup_receipt_cannot_unlock_provider_dispatch(
    monkeypatch,
):
    from elevate_cli.data import dispatch as dispatch_data
    from elevate_cli.data.admin_setup import forms_provider_capability

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )
    monkeypatch.setattr(
        dispatch_data,
        "_spawn_cron_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("writable setup proof must not unlock dispatch")
        ),
    )

    with connect() as conn:
        _set_fresh_forms_provider_proof(conn, available=True)
        capability = forms_provider_capability(conn)
        assert capability["available"] is False

        deal = create_deal(
            conn,
            title="Beta forms proof replay",
            side="listing",
            actor="human:test",
            current_stage=2,
        )
        action = create_action(
            conn,
            name="Beta proof-bound document run",
            trigger="manual",
            skill="real-estate-admin/mlc",
            side="listing",
            skill_args={
                "mode": "documents",
            },
        )
        run = next(
            item
            for item in evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if item["registryId"] == action["id"]
        )
        assert run["status"] == "waiting_human"
        assert run["cronJobId"] is None
        assert run["humanPrompt"]["kind"] == "forms_provider"


def test_exact_beta_forms_scaffold_status_cannot_mint_live_provider_proof(
    monkeypatch,
):
    from elevate_cli.data.admin_setup import sync_admin_setup_runtime

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with connect() as conn:
        setup = sync_admin_setup_runtime(
            conn,
            source_connectors={
                "connectors": [
                    {
                        "id": "forms-signing",
                        "label": "WEBForms",
                        "sourceExists": True,
                        "connected": True,
                        "state": "connected",
                        "lastCheckedAt": now_iso(),
                    }
                ]
            },
        )

    forms_item = next(item for item in setup["items"] if item["key"] == "forms_provider")
    assert forms_item["status"] == "missing"
    assert forms_item.get("value") is None
    assert setup["capabilities"]["formsProvider"]["available"] is False
    assert setup["capabilities"]["formsProvider"]["coordination"]["ready"] is False
    assert (
        setup["capabilities"]["formsProvider"]["reason"]
        == "live_forms_provider_not_verified"
    )


def test_exact_beta_forms_provider_playbook_is_password_free_and_cta_safe(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with connect() as conn:
        setup = update_admin_setup(
            conn,
            items=[
                {
                    "key": "forms_provider",
                    "status": "configured",
                    "provider": "WEBForms",
                    "value": {
                        "provider": "WEBForms",
                        "playbook": {
                            "provider": "WEBForms",
                            "loginUrl": "https://forms.example.test/login?from=beta#ignored",
                            "accountEmail": " REALTOR@EXAMPLE.COM ",
                            "sessionMode": "account_email",
                        },
                    },
                }
            ],
        )

    item = next(row for row in setup["items"] if row["key"] == "forms_provider")
    playbook = item["value"]["playbook"]
    assert playbook == {
        "provider": "WEBForms",
        "loginUrl": "https://forms.example.test/login?from=beta",
        "accountEmail": "realtor@example.com",
        "sessionMode": "account_email",
    }
    coordination = setup["capabilities"]["formsProvider"]["coordination"]
    assert coordination["ready"] is True
    assert coordination["loginUrl"] == playbook["loginUrl"]
    assert coordination["storesPassword"] is False


@pytest.mark.parametrize(
    "value",
    [
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "http://forms.example.test/login",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "javascript:alert(1)",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://user:pass@forms.example.test/login",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://127.0.0.1/login",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://192.168.1.5/login",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://forms.example.test:8443/login",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://forms.example.test/login",
                "accountEmail": "realtor@example.com",
                "sessionMode": "existing_session",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://forms.example.test/login",
                "sessionMode": "account_email",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://forms.example.test/login",
                "sessionMode": "existing_session",
                "password": "do-not-store",
            },
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://forms.example.test/login",
                "sessionMode": "existing_session",
            },
            "credentials": [{"password": "nested-smuggle"}],
        },
        {
            "provider": "WEBForms",
            "playbook": {
                "provider": "WEBForms",
                "loginUrl": "https://forms.example.test/login",
                "sessionMode": "existing_session",
                "unexpected": "value",
            },
        },
    ],
)
def test_exact_beta_forms_provider_playbook_rejects_unsafe_or_ambiguous_input(
    monkeypatch,
    value,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with connect() as conn:
        with pytest.raises(ValueError):
            update_admin_setup(
                conn,
                items=[
                    {
                        "key": "forms_provider",
                        "status": "configured",
                        "provider": "WEBForms",
                        "value": value,
                    }
                ],
            )


def test_exact_beta_manual_reviewed_pdf_closes_parked_semantic_run(
    monkeypatch,
    tmp_path,
):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )

    def unexpected_spawn(**_kwargs):
        raise AssertionError("manual Option-B run must never dispatch a provider worker")

    monkeypatch.setattr(dispatch_data, "_spawn_cron_job", unexpected_spawn)
    reviewed_pdf = _write_valid_pdf(
        tmp_path / "reviewed-mlc.pdf",
        "Multiple Listing Contract — 101 Exact Deal Street, Kamloops BC",
    )

    with connect() as conn:
        _configure_test_forms_provider(conn)
        deal = create_deal(
            conn,
            title="Manual reviewed MLC",
            side="listing",
            actor="human:test",
            current_stage=2,
            listing_address="101 Exact Deal Street, Kamloops BC",
        )
        action = create_action(
            conn,
            name="Prepare MLC document without optional flags",
            trigger="manual",
            skill="real-estate-admin/mlc",
            side="listing",
            skill_args={"mode": "documents"},
        )
        run = next(
            item
            for item in evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if item["registryId"] == action["id"]
        )
        assert run["status"] == "waiting_human"
        assert run["humanPrompt"]["requiredArtifactKind"] == "mlc_pdf"
        assert run["humanPrompt"]["formCode"] == "MLC"
        valid_kwargs = _manual_completion_kwargs(
            pdf=reviewed_pdf,
            deal=deal,
            run=run,
            kind="mlc_pdf",
            form_code="MLC",
        )

        with pytest.raises(PermissionError, match="human actor"):
            complete_run_with_reviewed_manual_pdf(
                conn,
                deal["id"],
                run["id"],
                **valid_kwargs,
                actor="skill:test",
            )
        with pytest.raises(ValueError, match="confirm that the PDF was reviewed"):
            complete_run_with_reviewed_manual_pdf(
                conn,
                deal["id"],
                run["id"],
                **{**valid_kwargs, "reviewed": False},
                actor="human:test",
            )
        with pytest.raises(ValueError, match="requires artifact kind mlc_pdf"):
            complete_run_with_reviewed_manual_pdf(
                conn,
                deal["id"],
                run["id"],
                **{**valid_kwargs, "kind": "cps_draft"},
                actor="human:test",
            )

        completed = complete_run_with_reviewed_manual_pdf(
            conn,
            deal["id"],
            run["id"],
            **valid_kwargs,
            summary="Reviewed against the licensed provider record.",
            actor="human:test",
        )
        replay = complete_run_with_reviewed_manual_pdf(
            conn,
            deal["id"],
            run["id"],
            **valid_kwargs,
            actor="human:test",
        )
        attachment = conn.execute(
            "SELECT * FROM deal_attachments WHERE source_run_id=?",
            (run["id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT payload_json FROM deal_events WHERE deal_id=? AND kind='run_result' "
            "ORDER BY created_at DESC LIMIT 1",
            (deal["id"],),
        ).fetchone()
        persisted_deal = conn.execute(
            "SELECT extra_toggles_json FROM deals WHERE id=?", (deal["id"],)
        ).fetchone()

    receipt = completed["result"]["manualFormsReviewReceipt"]
    assert completed["status"] == "succeeded"
    assert completed["cronJobId"] is None
    assert completed["result"]["requiredArtifactKinds"] == ["mlc_pdf"]
    assert receipt["schema"] == "elevate.manual-forms-review.v2"
    assert receipt["providerDispatch"] is False
    assert receipt["sourceVerified"] is False
    assert receipt["catalogCurrentVersionVerified"] is False
    assert receipt["dealId"] == deal["id"]
    assert receipt["taskId"] == run["id"]
    assert receipt["formCode"] == "MLC"
    assert receipt["reviewerName"] == "Test Realtor"
    assert receipt["reviewedBy"] == "human:test"
    assert len(receipt["sha256"]) == 64
    assert attachment["kind"] == "mlc_pdf"
    assert not (json.loads(persisted_deal["extra_toggles_json"] or "{}") or {}).get(
        "workflow_stage_2_complete"
    )
    assert json.loads(event["payload_json"])["manualFormsReviewReceipt"]["sha256"] == receipt["sha256"]
    assert replay["resultIdempotencyKey"] == completed["resultIdempotencyKey"]


def test_exact_beta_ad_hoc_and_next_task_semantics_cannot_bypass_forms_gate(
    monkeypatch,
):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )

    def unexpected_spawn(**_kwargs):
        raise AssertionError("semantic MLC/CPS child work must park before cron")

    monkeypatch.setattr(dispatch_data, "_spawn_cron_job", unexpected_spawn)
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Semantic next-task gate",
            side="buyer",
            actor="human:test",
            current_stage=1,
        )
        direct = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/buyer-cps",
            name="Ad hoc offer draft",
            create_cron_job=True,
            actor="skill:test",
        )
        assert direct["status"] == "waiting_human"
        assert direct["humanPrompt"]["requiredArtifactKind"] == "cps_draft"

        source = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/marketing",
            name="Safe parent task",
            create_cron_job=False,
            actor="skill:test",
        )
        record_run_result(
            conn,
            deal["id"],
            source["id"],
            status="succeeded",
            idempotency_key="semantic-next-task-parent",
            next_tasks=[
                {
                    "skill": "generic-document-worker",
                    "name": "Prepare CPS form",
                    "requiredArtifactKinds": ["cps_draft"],
                    "runNow": True,
                }
            ],
            actor="skill:test",
        )
        children = [
            item
            for item in list_action_runs(conn, deal_id=deal["id"])
            if item["id"] not in {direct["id"], source["id"]}
        ]

    assert len(children) == 1
    assert children[0]["status"] == "waiting_human"
    assert children[0]["humanPrompt"]["requiredArtifactKind"] == "cps_draft"


def test_exact_beta_manual_provider_claim_rejects_unrelated_wrong_form_wrong_deal_and_stale_receipts(
    monkeypatch,
    tmp_path,
):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(dispatch_data, "_admin_setup_dispatch_block_reason", lambda _conn: None)
    monkeypatch.setattr(
        dispatch_data,
        "_spawn_cron_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider-form coordination must park before cron")
        ),
    )
    address = "303 Correct Property Road, Kamloops BC"
    with connect() as conn:
        _configure_test_forms_provider(conn)
        deal = create_deal(
            conn,
            title="Same Client Portfolio",
            side="listing",
            actor="human:test",
            current_stage=2,
            listing_address=address,
        )
        action = create_action(
            conn,
            name="Prepare exact MLC",
            trigger="manual",
            skill="real-estate-admin/mlc",
            side="listing",
            skill_args={"mode": "documents", "formCode": "MLC"},
        )
        run = next(
            item
            for item in evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if item["registryId"] == action["id"]
        )

        random_pdf = _write_valid_pdf(
            tmp_path / "random.pdf",
            f"Quarterly market report for {address}",
        )
        wrong_form_pdf = _write_valid_pdf(
            tmp_path / "wrong-form.pdf",
            f"Contract of Purchase and Sale for {address}",
        )
        wrong_deal_pdf = _write_valid_pdf(
            tmp_path / "wrong-deal.pdf",
            "Multiple Listing Contract for 999 Other Property Road, Kamloops BC — Same Client Portfolio",
        )
        correct_pdf = _write_valid_pdf(
            tmp_path / "correct.pdf",
            f"Multiple Listing Contract for {address}",
        )

        for pdf, message in (
            (random_pdf, "does not identify the task-bound form MLC"),
            (wrong_form_pdf, "does not identify the task-bound form MLC"),
            (wrong_deal_pdf, "does not identify this deal"),
        ):
            with pytest.raises(ValueError, match=message):
                complete_run_with_reviewed_manual_pdf(
                    conn,
                    deal["id"],
                    run["id"],
                    **_manual_completion_kwargs(
                        pdf=pdf,
                        deal=deal,
                        run=run,
                        kind="mlc_pdf",
                        form_code="MLC",
                    ),
                    actor="human:test",
                )

        receipt_mismatch = _manual_completion_kwargs(
            pdf=correct_pdf,
            deal=deal,
            run=run,
            kind="mlc_pdf",
            form_code="MLC",
        )
        receipt_mismatch["source_receipt"] = {
            **receipt_mismatch["source_receipt"],
            "artifactSha256": "0" * 64,
        }
        with pytest.raises(ValueError, match="source receipt mismatch for artifactSha256"):
            complete_run_with_reviewed_manual_pdf(
                conn,
                deal["id"],
                run["id"],
                **receipt_mismatch,
                actor="human:test",
            )

        stale = _manual_completion_kwargs(
            pdf=correct_pdf,
            deal=deal,
            run=run,
            kind="mlc_pdf",
            form_code="MLC",
            version_status="verified",
            document_version="2024.1",
            version_verified_at=(
                datetime.now(timezone.utc) - timedelta(days=31)
            ).isoformat(),
        )
        with pytest.raises(ValueError, match="verification is stale"):
            complete_run_with_reviewed_manual_pdf(
                conn,
                deal["id"],
                run["id"],
                **stale,
                actor="human:test",
            )

        unverified_with_claim = _manual_completion_kwargs(
            pdf=correct_pdf,
            deal=deal,
            run=run,
            kind="mlc_pdf",
            form_code="MLC",
            version_status="unverified",
            version_verified_at=datetime.now(timezone.utc).isoformat(),
        )
        with pytest.raises(ValueError, match="unverified version must not claim"):
            complete_run_with_reviewed_manual_pdf(
                conn,
                deal["id"],
                run["id"],
                **unverified_with_claim,
                actor="human:test",
            )


@pytest.mark.parametrize(
    ("form_code", "form_title"),
    [
        ("BAEC", "Buyer Agency Exclusive Contract"),
        ("DORTS", "Disclosure of Representation in Trading Services"),
        ("PNC", "Privacy Notice and Consent"),
    ],
)
def test_exact_beta_task_bound_manual_completion_supports_onboarding_forms(
    monkeypatch,
    tmp_path,
    form_code,
    form_title,
):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(dispatch_data, "_admin_setup_dispatch_block_reason", lambda _conn: None)
    monkeypatch.setattr(
        dispatch_data,
        "_spawn_cron_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider-form coordination must park before cron")
        ),
    )
    title = f"Alex Client — {form_code} onboarding"
    pdf = _write_valid_pdf(tmp_path / f"{form_code}.pdf", f"{form_title} — {title}")
    with connect() as conn:
        _configure_test_forms_provider(conn)
        deal = create_deal(
            conn,
            title=title,
            side="buyer",
            actor="human:test",
            current_stage=0,
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/admin-agent",
            name=f"Coordinate {form_code}",
            payload={
                "formCode": form_code,
                "requiresLiveFormsProvider": True,
                "requiredArtifactKinds": ["provider_form_pdf"],
            },
            create_cron_job=True,
            actor="human:test",
        )
        assert run["status"] == "waiting_human"
        assert run["humanPrompt"]["formCode"] == form_code
        completed = complete_run_with_reviewed_manual_pdf(
            conn,
            deal["id"],
            run["id"],
            **_manual_completion_kwargs(
                pdf=pdf,
                deal=deal,
                run=run,
                kind="provider_form_pdf",
                form_code=form_code,
                receipt_id=f"manual-{form_code}-export",
            ),
            actor="human:test",
        )

    assert completed["status"] == "succeeded"
    receipt = completed["result"]["manualFormsReviewReceipt"]
    assert receipt["formCode"] == form_code
    assert receipt["sourceVerified"] is False
    assert receipt["versionStatus"] == "unverified"


def test_manual_reviewed_pdf_endpoint_uploads_and_completes_parked_cps(
    client,
    monkeypatch,
    tmp_path,
):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )
    monkeypatch.setattr(
        dispatch_data,
        "_spawn_cron_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("parked CPS must not dispatch")
        ),
    )
    pdf = _write_valid_pdf(
        tmp_path / "provider-cps.pdf",
        "Contract of Purchase and Sale — 202 Bound Offer Avenue, Kamloops BC",
    )
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Manual CPS endpoint",
            side="buyer",
            actor="human:test",
            current_stage=1,
            listing_address="202 Bound Offer Avenue, Kamloops BC",
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/buyer-cps",
            create_cron_job=True,
            actor="human:test",
        )
    source_receipt = _manual_export_claim(
        pdf=pdf,
        deal_id=deal["id"],
        run_id=run["id"],
        form_code="CPS-res",
        deal_reference=deal["listingAddress"],
    )

    response = client.post(
        f"/api/deals/{deal['id']}/runs/{run['id']}/manual-reviewed-document",
        json={
            "reviewed": True,
            "kind": "cps_draft",
            "formCode": "CPS-res",
            "provider": "test",
            "reviewerName": "Test Realtor",
            "versionStatus": "unverified",
            "sourceReceipt": source_receipt,
            "filename": "provider-cps.pdf",
            "contentB64": base64.b64encode(pdf.read_bytes()).decode("ascii"),
            "summary": "Realtor reviewed provider export.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["result"]["manualFormsReviewReceipt"]["reviewedBy"] == "human:web"
    assert body["result"]["manualFormsReviewReceipt"]["providerDispatch"] is False
    assert Path(body["outputPath"]).is_file()


def test_exact_beta_data_boundary_forces_bc_and_rejects_non_bc_promotions(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with connect() as conn:
        with pytest.raises(ValueError, match="British Columbia"):
            create_deal(
                conn,
                title="Alberta must fail",
                side="listing",
                actor="agent:test",
                province="AB",
                dispatch_initial_stage=False,
            )
        bc = create_deal(
            conn,
            title="Blank exact-Beta province becomes BC",
            side="listing",
            actor="agent:test",
            province="",
            dispatch_initial_stage=False,
        )
        with pytest.raises(ValueError, match="British Columbia"):
            promote_profile_to_admin_deal(
                conn,
                profile_id="profile-ab",
                side="buyer",
                actor="agent:test",
                province="AB",
                profile_context={"emails": ["buyer@example.test"]},
                dispatch_initial_stage=False,
            )

    assert bc["province"] == "BC"

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    with connect() as conn:
        stable = create_deal(
            conn,
            title="Stable Alberta remains available",
            side="listing",
            actor="agent:test",
            province="AB",
            dispatch_initial_stage=False,
        )
    assert stable["province"] == "AB"


def test_admin_profile_tool_cannot_bypass_exact_beta_bc_boundary(monkeypatch):
    import elevate_cli.data as data_module
    from tools.admin_profile_tool import _admin_profile_tool

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(data_module, "require_admin_setup_ready", lambda _conn: None)
    monkeypatch.setattr(
        data_module,
        "get_admin_setup",
        lambda _conn: {"profile": {"province": "BC"}},
    )
    result = _admin_profile_tool(
        {
            "profile_id": "tool-profile-ab",
            "side": "buyer",
            "province": "AB",
            "profile_context": {"emails": ["buyer@example.test"]},
        }
    )

    assert "British Columbia" in result
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM deals WHERE province='AB'"
        ).fetchone()["count"]
    assert count == 0


def test_forms_provider_gate_leaves_cma_and_stable_dispatch_unchanged(monkeypatch):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )
    monkeypatch.setattr(
        dispatch_data,
        "_spawn_cron_job",
        lambda **kwargs: f"cron-{kwargs['run_id']}",
    )

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    with connect() as conn:
        listing = create_deal(
            conn,
            title="Beta CMA remains available",
            side="listing",
            actor="human:test",
            current_stage=1,
        )
        cma_action = create_action(
            conn,
            name="Beta CMA manual",
            trigger="manual",
            skill="real-estate-admin/cma",
            side="listing",
        )
        cma = next(
            run
            for run in evaluate_dispatch(
                conn,
                deal_id=listing["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if run["registryId"] == cma_action["id"]
        )
    assert cma["status"] == "running"
    assert cma["cronJobId"]

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    with connect() as conn:
        stable_listing = create_deal(
            conn,
            title="Stable MLC remains available",
            side="listing",
            actor="human:test",
            current_stage=2,
        )
        stable_mlc_action = create_action(
            conn,
            name="Stable MLC manual",
            trigger="manual",
            skill="real-estate-admin/mlc",
            side="listing",
            skill_args={
                "mode": "documents",
                "requiresLiveFormsProvider": True,
            },
        )
        stable_mlc = next(
            run
            for run in evaluate_dispatch(
                conn,
                deal_id=stable_listing["id"],
                trigger="manual",
                actor="human:test",
                create_cron_jobs=True,
            )
            if run["registryId"] == stable_mlc_action["id"]
        )
    assert stable_mlc["status"] == "running"
    assert stable_mlc["cronJobId"]


def test_stale_running_action_runs_requeue_then_fail_with_visible_error():
    stale_at = "2026-05-01T00:00:00+00:00"
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Stale run listing",
            side="listing",
            actor="human:test",
            current_stage=2,
        )
        run = evaluate_dispatch(
            conn,
            deal_id=deal["id"],
            trigger="manual",
            actor="human:test",
        )
        if not run:
            action = create_action(
                conn,
                name="stale manual",
                trigger="manual",
                skill="marketing",
                side="listing",
            )
            run = evaluate_dispatch(
                conn,
                deal_id=deal["id"],
                trigger="manual",
                actor="human:test",
            )
        run_id = run[0]["id"]
        conn.execute(
            """
            UPDATE admin_action_runs
            SET status='running', started_at=?, updated_at=?
            WHERE id=?
            """,
            (stale_at, stale_at, run_id),
        )
        recovered = mark_stale_action_runs(conn, max_running_minutes=120, actor="test-worker")

    assert len(recovered) == 1
    assert recovered[0]["status"] == "queued"
    assert recovered[0]["payload"]["recovery"]["event"] == "stale_running_requeued"
    assert recovered[0]["payload"]["recovery"]["attempts"] == 1

    with connect() as conn:
        conn.execute(
            """
            UPDATE admin_action_runs
            SET status='running', started_at=?, updated_at=?
            WHERE id=?
            """,
            (stale_at, stale_at, run_id),
        )
        recovered = mark_stale_action_runs(conn, max_running_minutes=120, actor="test-worker", max_retries=1)

    assert len(recovered) == 1
    assert recovered[0]["status"] == "failed"
    assert "120 minute" in recovered[0]["errorMessage"]
    assert recovered[0]["payload"]["recovery"]["event"] == "stale_running_failed"
    assert recovered[0]["payload"]["recovery"]["attempts"] == 1


def test_worker_exit_without_callback_requeues_immediately_then_fails_retryably(monkeypatch):
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setattr(dispatch_data, "_request_agent_worker_wake", lambda **_kwargs: None)
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Missing callback",
            side="buyer",
            actor="human:test",
            current_stage=1,
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/buyer-cps",
            name="Draft CPS",
            create_cron_job=False,
            actor="human:test",
        )
        conn.execute(
            "UPDATE admin_action_runs SET status='running', cron_job_id='cron-one' WHERE id=?",
            (run["id"],),
        )
        recovered = dispatch_data.record_action_run_worker_exit(
            conn,
            run["id"],
            cron_job_id="cron-one",
            success=True,
            actor="test-scheduler",
            max_retries=1,
        )

    assert recovered["status"] == "queued"
    assert recovered["payload"]["recovery"]["event"] == "worker_exit_without_callback_requeued"
    assert recovered["payload"]["recovery"]["retryable"] is True
    assert recovered["payload"]["recovery"]["attempts"] == 1

    with connect() as conn:
        conn.execute(
            "UPDATE admin_action_runs SET status='running', cron_job_id='cron-two' WHERE id=?",
            (run["id"],),
        )
        stale_exit = dispatch_data.record_action_run_worker_exit(
            conn,
            run["id"],
            cron_job_id="cron-one",
            success=False,
            error="old worker failed late",
            actor="test-scheduler",
            max_retries=1,
        )
        assert stale_exit["status"] == "running"

        failed = dispatch_data.record_action_run_worker_exit(
            conn,
            run["id"],
            cron_job_id="cron-two",
            success=False,
            error="worker crashed",
            actor="test-scheduler",
            max_retries=1,
        )

    assert failed["status"] == "failed"
    assert failed["payload"]["recovery"]["event"] == "worker_exit_without_callback_failed"
    assert failed["payload"]["recovery"]["retryable"] is True
    assert "worker crashed" in failed["errorMessage"]


def test_agent_worker_uses_separate_conservative_stale_defaults(monkeypatch):
    from elevate_cli.agent_worker import _config

    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    config = _config({"agent_worker": {}})
    assert config["stale_handoff_running_minutes"] == 120
    assert config["stale_admin_running_minutes"] == 120

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    config = _config({"agent_worker": {}})
    assert config["stale_handoff_running_minutes"] == 120
    assert config["stale_admin_running_minutes"] == 120

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    config = _config({"agent_worker": {}})
    assert config["stale_handoff_running_minutes"] == 180
    assert config["stale_admin_running_minutes"] == 120

    legacy = _config({"agent_worker": {"stale_running_minutes": 9}})
    assert legacy["stale_handoff_running_minutes"] == 9
    assert legacy["stale_admin_running_minutes"] == 9

    split = _config(
        {
            "agent_worker": {
                "stale_handoff_running_minutes": 240,
                "stale_admin_running_minutes": 150,
            }
        }
    )
    assert split["stale_handoff_running_minutes"] == 240
    assert split["stale_admin_running_minutes"] == 150


def test_scheduler_missing_callback_recovery_is_exact_beta_only(monkeypatch):
    from cron.scheduler import _record_admin_action_worker_exit
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setattr(dispatch_data, "_request_agent_worker_wake", lambda **_kwargs: None)
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Scheduler callback truth",
            side="buyer",
            actor="human:test",
            current_stage=1,
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/buyer-cps",
            name="Scheduler CPS run",
            create_cron_job=False,
            actor="human:test",
        )
        conn.execute(
            "UPDATE admin_action_runs SET status='running', cron_job_id='admin-cron' WHERE id=?",
            (run["id"],),
        )
    job = {
        "id": "admin-cron",
        "origin": {"source": "admin_hub", "run_id": run["id"]},
    }

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    assert _record_admin_action_worker_exit(job, success=True, error=None) is None
    with connect() as conn:
        stable_run = next(
            item
            for item in list_action_runs(conn, deal_id=deal["id"])
            if item["id"] == run["id"]
        )
    assert stable_run["status"] == "running"

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    message = _record_admin_action_worker_exit(job, success=True, error=None)
    assert "retry 1/2 was queued" in str(message)
    with connect() as conn:
        beta_run = next(
            item
            for item in list_action_runs(conn, deal_id=deal["id"])
            if item["id"] == run["id"]
        )
    assert beta_run["status"] == "queued"


def test_scheduler_exit_hook_ignores_prior_recovery_after_successful_retry_callback(
    monkeypatch,
    tmp_path,
):
    from cron.scheduler import _record_admin_action_worker_exit
    from elevate_cli.data import dispatch as dispatch_data

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(dispatch_data, "_request_agent_worker_wake", lambda **_kwargs: None)
    monkeypatch.setattr(
        dispatch_data,
        "_admin_setup_dispatch_block_reason",
        lambda _conn: None,
    )
    monkeypatch.setattr(
        dispatch_data,
        "_spawn_cron_job",
        lambda **_kwargs: "admin-cron-retry",
    )

    with connect() as conn:
        deal = create_deal(
            conn,
            title="Successful callback after recovery",
            side="buyer",
            actor="human:test",
            current_stage=1,
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/marketing",
            name="Retry generic callback",
            create_cron_job=False,
            actor="human:test",
        )
        conn.execute(
            "UPDATE admin_action_runs SET status='running', cron_job_id='admin-cron-first' WHERE id=?",
            (run["id"],),
        )

    first_job = {
        "id": "admin-cron-first",
        "origin": {"source": "admin_hub", "run_id": run["id"]},
    }
    recovery_message = _record_admin_action_worker_exit(
        first_job,
        success=True,
        error=None,
    )
    assert "retry 1/2 was queued" in str(recovery_message)

    with connect() as conn:
        retried = dispatch_data.dispatch_action_run_to_cron(
            conn,
            run["id"],
            actor="test-worker",
        )
    assert retried["status"] == "running"
    assert retried["cronJobId"] == "admin-cron-retry"

    artifact = _write_valid_pdf(tmp_path / "retried-output.pdf", "Retried output")
    with connect() as conn:
        completed = record_run_result(
            conn,
            deal["id"],
            run["id"],
            status="succeeded",
            idempotency_key="retry-callback-success",
            artifacts=[{"kind": "supporting_document", "filePath": str(artifact)}],
            actor="skill:test",
        )
    assert completed["status"] == "succeeded"
    assert completed["payload"]["recovery"]["event"] == "worker_exit_without_callback_requeued"

    retry_job = {
        "id": "admin-cron-retry",
        "origin": {"source": "admin_hub", "run_id": run["id"]},
    }
    assert _record_admin_action_worker_exit(retry_job, success=True, error=None) is None


def test_same_stage_move_does_not_create_duplicate_action_run():
    deal = _new_listing_deal()
    with connect() as conn:
        create_action(
            conn,
            name="stage four entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=4,
        )
        move_deal_stage(conn, deal["id"], to_stage=4, actor="human:test")

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert runs == []


def test_create_deal_at_stage_creates_stage_entry_run_via_hook():
    _complete_admin_setup()
    with connect() as conn:
        action = create_action(
            conn,
            name="initial MLC intake",
            trigger="stage_entry",
            skill="mlc",
            side="listing",
            to_stage=1,
            skill_args={"mode": "intake"},
        )
        deal = create_deal(
            conn,
            title="New intake listing",
            side="listing",
            actor="human:test",
            current_stage=1,
        )

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert len(runs) == 1
    run = runs[0]
    assert run["registryId"] == action["id"]
    assert run["status"] == "running"
    assert run["cronJobId"]
    assert run["payload"]["toStage"] == 1
    assert run["payload"]["registryName"] == "initial MLC intake"


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
    assert runs[0]["cronJobId"]
    assert runs[0]["status"] == "running"
    assert runs[0]["payload"]["fieldKey"] == "multiple_offers"
    assert runs[0]["payload"]["fieldNew"] is True


def test_approval_required_action_does_not_spawn_cron_job(client):
    deal = _new_listing_deal()
    with connect() as conn:
        create_action(
            conn,
            name="approval gated entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
            approval_required=True,
        )

    with connect() as conn:
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert len(runs) == 1
    assert runs[0]["cronJobId"] is None
    assert runs[0]["status"] == "waiting_human"
    assert runs[0]["humanPrompt"]["skill"] == "real-estate-admin/marketing"
    assert runs[0]["payload"]["registryName"] == "approval gated entry"

    approved = client.post(f"/api/admin/action-runs/{runs[0]['id']}/approve", json={"approved": True})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "running"
    assert body["cronJobId"]
    assert body["skill"] == "real-estate-admin/marketing"
    assert body["registryName"] == "approval gated entry"


def test_seed_default_admin_actions_is_idempotent_and_keeps_cron_watchers_out(client):
    first = client.post("/api/admin/actions/defaults")
    assert first.status_code == 200, first.text
    body = first.json()
    created_skills = {item["skill"] for item in body["created"]}
    assert {
        "real-estate-admin/pre-cma-dashboard-setup",
        "real-estate-admin/lofty-crm-client-contacts",
        "real-estate-admin/cma",
        "real-estate-admin/mlc",
        "real-estate-admin/deal-matcher",
        "real-estate-admin/skyslope-sync",
        "real-estate-admin/property-lookup",
        "real-estate-admin/matrix-incomplete-listing",
        "real-estate-admin/photo-cleanup",
        "real-estate-admin/listing-build",
        "real-estate-admin/offer-review",
        "real-estate-admin/subject-removal",
        "real-estate-admin/closing-admin",
        "real-estate-admin/buyer-cps",
    }.issubset(created_skills)
    created_names = {item["name"]: item for item in body["created"]}
    # Pre-CMA (stage 0) now auto-launches dashboard setup + CRM contact verification.
    assert created_names["Pre-CMA: Set up listing dashboard"]["toStage"] == 0
    assert created_names["Pre-CMA: Verify CRM contact"]["toStage"] == 0
    # CMA generates at stage 1, MLC intake/documents land at Listing Intake (stage 2).
    assert created_names["CMA: Generate evaluation"]["toStage"] == 1
    assert created_names["CMA: Generate evaluation"]["skill"] == "real-estate-admin/cma"
    assert created_names["CMA: Generate evaluation"]["skillArgs"] == {
        "mode": "seller_evaluation",
        "requiredArtifactKinds": ["cma_report"],
    }
    assert created_names["Listing Intake: Collect MLC info"]["skillArgs"] == {"mode": "intake"}
    assert created_names["Listing Intake: Collect MLC info"]["toStage"] == 2
    assert created_names["Listing Intake: Prepare MLC documents"]["skillArgs"] == {
        "mode": "documents",
        "requiredArtifactKinds": ["mlc_pdf"],
        "requiresLiveFormsProvider": True,
    }
    # Matrix listing is drafted at SkySlope & Matrix Prep (3) and finished at Marketing Go (4).
    assert created_names["SkySlope & Matrix: Draft incomplete listing"]["skillArgs"] == {"mode": "draft"}
    assert created_names["SkySlope & Matrix: Draft incomplete listing"]["toStage"] == 3
    assert created_names["Marketing Go: Upload final photos to Matrix"]["skillArgs"] == {"mode": "photos"}
    assert created_names["Marketing Go: Upload final photos to Matrix"]["toStage"] == 4
    buyer_cps = created_names["Buyer Offer Prep: Prepare CPS draft"]
    assert buyer_cps["skill"] == "real-estate-admin/buyer-cps"
    assert buyer_cps["side"] == "buyer"
    assert buyer_cps["toStage"] == 1
    assert buyer_cps["approvalRequired"] is True
    assert buyer_cps["skillArgs"] == {
        "mode": "draft",
        "sendPolicy": "draft_only",
        "requiredArtifactKinds": ["cps_draft"],
        "requiresLiveFormsProvider": True,
    }
    # Buyer pipeline is wired across all four buyer stages.
    assert {item["toStage"] for item in body["created"] if item["side"] == "buyer"} == {1, 2, 3, 4}
    assert created_names["Buyer Accepted: Review offer package"]["skill"] == "real-estate-admin/offer-review"
    assert created_names["Buyer Subjects Off: Run closing admin"]["skill"] == "real-estate-admin/closing-admin"
    assert "gmail-doc-router" not in created_skills
    assert "seller-update" not in created_skills
    assert body["updated"] == []
    # Only the contract/signing sends are approval-gated; everything else runs unattended.
    approval_gated = {item["name"] for item in body["created"] if item["approvalRequired"]}
    assert approval_gated == {"Buyer Offer Prep: Prepare CPS draft", "Buyer Conditions: Sync signing"}

    second = client.post("/api/admin/actions/defaults")
    assert second.status_code == 200, second.text
    assert second.json()["created"] == []
    assert second.json()["updated"] == []
    assert second.json()["count"] == body["count"]


def test_seed_default_admin_actions_migrates_legacy_rows_in_place(client):
    # A pre-realignment row (old name, old stage) must be renamed in place —
    # same id, no duplicate — then corrected to the canonical stage/args.
    with connect() as conn:
        legacy = create_action(
            conn,
            name="S2 Prepare MLC package",
            trigger="stage_entry",
            skill="mlc",
            side="listing",
            to_stage=2,
            priority=1,
            approval_required=True,
        )
        legacy_id = legacy["id"]

    resp = client.post("/api/admin/actions/defaults")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    with connect() as conn:
        rows = {row["name"]: row for row in list_actions(conn)}
    # Old name retired, canonical name present, id preserved (run history intact).
    assert "S2 Prepare MLC package" not in rows
    migrated = rows["Listing Intake: Prepare MLC documents"]
    assert migrated["id"] == legacy_id
    assert migrated["toStage"] == 2
    assert migrated["priority"] == 85
    assert migrated["approvalRequired"] is False
    assert migrated["skillArgs"] == {
        "mode": "documents",
        "requiredArtifactKinds": ["mlc_pdf"],
        "requiresLiveFormsProvider": True,
    }
    # No stale "S-numbered" defaults survive the migration.
    assert not any(name.startswith("S1 ") or name.startswith("S9 ") for name in rows)


def test_seed_default_admin_actions_migrates_buyer_cps_stage_and_skill_in_place(client):
    with connect() as conn:
        legacy = create_action(
            conn,
            name="Buyer Offer Prep: Prepare CPS draft",
            trigger="stage_entry",
            skill="real-estate-admin/webforms",
            skill_args={"mode": "draft", "sendPolicy": "draft_only"},
            side="buyer",
            to_stage=0,
            priority=90,
            approval_required=True,
        )

    first = client.post("/api/admin/actions/defaults")
    assert first.status_code == 200, first.text
    updated = next(
        item
        for item in first.json()["updated"]
        if item["name"] == "Buyer Offer Prep: Prepare CPS draft"
    )
    assert updated["id"] == legacy["id"]
    assert updated["skill"] == "real-estate-admin/buyer-cps"
    assert updated["toStage"] == 1
    assert updated["skillArgs"] == {
        "mode": "draft",
        "sendPolicy": "draft_only",
        "requiredArtifactKinds": ["cps_draft"],
        "requiresLiveFormsProvider": True,
    }

    second = client.post("/api/admin/actions/defaults")
    assert second.status_code == 200, second.text
    assert second.json()["updated"] == []


def test_seeded_defaults_launch_matrix_and_buyer_stages():
    # Seed the canonical registry, then confirm the new wiring actually fires:
    # SkySlope & Matrix Prep (listing stage 3) and the buyer pipeline.
    _complete_admin_setup()
    with connect() as conn:
        ensure_default_admin_actions(conn)
        listing = create_deal(conn, title="Matrix listing", side="listing", actor="human:test", current_stage=2)
        move_deal_stage(conn, listing["id"], to_stage=3, actor="human:test", force=True)
        listing_skills = {run["skill"] for run in list_action_runs(conn, deal_id=listing["id"])}
    assert "real-estate-admin/skyslope-sync" in listing_skills
    assert "real-estate-admin/property-lookup" in listing_skills
    assert "real-estate-admin/matrix-incomplete-listing" in listing_skills

    with connect() as conn:
        buyer = create_deal(conn, title="Buyer deal", side="buyer", actor="human:test", current_stage=0)
        move_deal_stage(conn, buyer["id"], to_stage=1, actor="human:test", force=True)
        buyer_runs = list_action_runs(conn, deal_id=buyer["id"])
    assert any(run["skill"] == "real-estate-admin/buyer-cps" for run in buyer_runs)
    assert not any(run["skill"] == "real-estate-admin/offer-review" for run in buyer_runs)

    with connect() as conn:
        move_deal_stage(conn, buyer["id"], to_stage=2, actor="human:test", force=True)
        buyer_runs = list_action_runs(conn, deal_id=buyer["id"])
    assert any(run["skill"] == "real-estate-admin/offer-review" for run in buyer_runs)


def test_admin_deal_tool_finalizes_session_work_to_the_board(monkeypatch, tmp_path: Path):
    # A skill invoked in a live session finalizes the deal through the admin_deal
    # tool, mirroring the background run-result callback: the kanban card syncs
    # (fields + checklist + artifact) and the stage advances.
    import json

    monkeypatch.setattr("elevate_cli.access.is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    _complete_admin_setup()
    with connect() as conn:
        ensure_default_admin_actions(conn)
        deal = create_deal(
            conn,
            title="CMA in session",
            side="listing",
            actor="human:test",
            current_stage=1,
            province="BC",
        )
        did = deal["id"]

    cma_path = _write_valid_pdf(tmp_path / "cma.pdf", "CMA pricing analysis")

    # Entering CMA auto-launched a blocking run, so the gate is held.
    shown = json.loads(_admin_deal_handler({"action": "show", "deal_id": did}))
    assert shown["gate"]["stage"] == 1
    assert shown["gate"]["canAdvance"] is False

    # Agent gathers the list price in chat, writes it, then closes out the run.
    priced = json.loads(_admin_deal_handler({"action": "set_fields", "deal_id": did, "fields": {"listPrice": 799000}}))
    assert priced["applied"] == {"listPrice": 799000}

    done = json.loads(_admin_deal_handler({
        "action": "complete_run",
        "deal_id": did,
        "skill": "real-estate-admin/cma",
        "checklist_updates": [
            {"id": "cma_pdf_ready", "completed": True},
            {"id": "pricing_story_approved", "completed": True},
            {"id": "client_yes_to_listing", "completed": True},
            {"id": "workflow_cma_date_requested", "completed": True},
        ],
        "artifacts": [{"kind": "cma_report", "file_path": str(cma_path), "summary": "CMA"}],
    }))
    assert done["completedRun"]
    # The blocking run cleared and the card advanced CMA (1) -> Listing Intake (2).
    assert done["gate"]["stage"] == 2

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=did)
    cma = next(r for r in runs if r["skill"] == "real-estate-admin/cma")
    assert cma["status"] in {"succeeded", "completed"}


def test_admin_deal_tool_writes_sync_the_gate(monkeypatch):
    # set_checklist / set_fields write straight to the deal so the kanban gate
    # reflects them immediately — the in-session sync the realtor sees.
    import json

    monkeypatch.setattr("elevate_cli.access.is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    _complete_admin_setup()
    with connect() as conn:
        deal = create_deal(
            conn,
            title="Pre-CMA writes",
            side="listing",
            actor="human:test",
            current_stage=0,
            province="BC",
        )
        did = deal["id"]

    before = json.loads(_admin_deal_handler({"action": "show", "deal_id": did}))
    assert "pre_cma_dashboard_setup" in before["gate"]["missingChecklist"]
    assert "workflow_client_1_name" in before["gate"]["missingFields"]

    # A checklist write immediately drops that item from the gate's missing list.
    ticked = json.loads(_admin_deal_handler({"action": "set_checklist", "deal_id": did, "field": "pre_cma_dashboard_setup"}))
    assert ticked["success"] is True
    assert "pre_cma_dashboard_setup" not in ticked["gate"]["missingChecklist"]

    # set_fields auto-routes a workflow_* required "field" to the toggle path and
    # it leaves the missing-fields list too.
    filled = json.loads(_admin_deal_handler({"action": "set_fields", "deal_id": did, "fields": {"workflow_client_1_name": "Seller One"}}))
    assert filled["success"] is True
    assert "workflow_client_1_name" not in filled["gate"]["missingFields"]


def test_run_result_accepts_per_run_service_token_without_session(client):
    deal = _new_listing_deal()
    with connect() as conn:
        create_action(
            conn,
            name="tokened entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
        )
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)
        run = list_action_runs(conn, deal_id=deal["id"])[0]

    from cron.jobs import load_jobs
    from elevate_cli.web_server import app

    job = next(job for job in load_jobs() if job["id"] == run["cronJobId"])
    assert job["deliver"] == "telegram"
    assert job["agent"] == "admin"
    assert job["origin"]["agent"] == "admin"
    assert job["origin"]["telegram_lane"] == "admin-agent"
    assert job["skills"] == [
        "real-estate-admin/admin-agent",
        "real-estate-admin/deal-matcher",
        "real-estate-admin/marketing",
        "real-estate-admin/admin-result-writer",
    ]
    assert "Admin agent orchestration" in job["prompt"]
    assert "Admin Telegram handoff" in job["prompt"]
    assert f"POST http://127.0.0.1:9119/api/deals/{deal['id']}/runs/{run['id']}/result" in job["prompt"]
    assert "Report operational database changes only after the result callback succeeds" in job["prompt"]
    match = re.search(r"X-Elevate-Run-Token: (\S+)", job["prompt"])
    assert match, job["prompt"]

    unauthed = TestClient(app)
    resp = unauthed.post(
        f"/api/deals/{deal['id']}/runs/{run['id']}/result",
        headers={"X-Elevate-Run-Token": match.group(1)},
        json={"status": "completed", "idempotencyKey": "service-token-test"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "succeeded"


def test_dispatched_run_uses_configured_admin_telegram_lane(client, monkeypatch):
    monkeypatch.setenv("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", "admin-chat-123")
    deal = _new_listing_deal()
    with connect() as conn:
        create_action(
            conn,
            name="telegram lane entry",
            trigger="stage_entry",
            skill="marketing",
            side="listing",
            to_stage=5,
        )
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)
        run = list_action_runs(conn, deal_id=deal["id"])[0]

    from cron.jobs import load_jobs

    job = next(job for job in load_jobs() if job["id"] == run["cronJobId"])
    assert job["deliver"] == "telegram:admin-chat-123"


def test_dispatched_run_prompt_injects_deal_flow_and_province_memory(tmp_path):
    from elevate_cli.data.dispatch import _agent_run_context_for_prompt

    _complete_admin_setup()
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
        import_exp_agent_centre(conn, root=root)
        deal = create_deal(
            conn,
            title="Memory-backed listing",
            side="listing",
            actor="human:test",
            province="BC",
            current_stage=0,
        )
        create_action(
            conn,
            name="launch seller update",
            trigger="stage_entry",
            skill="seller-updates",
            side="listing",
            to_stage=1,
        )
        move_deal_stage(conn, deal["id"], to_stage=1, actor="human:test", force=True)
        run = list_action_runs(conn, deal_id=deal["id"])[0]
        context = _agent_run_context_for_prompt(conn, deal["id"])

    assert context["currentStageDocuments"]["stage"] == 1
    assert context["currentStageDocuments"]["documents"][0]["code"] == "MLC"

    from cron.jobs import load_jobs

    job = next(job for job in load_jobs() if job["id"] == run["cronJobId"])
    prompt = job["prompt"]
    assert "Injected source-of-truth context from the operational data store" in prompt
    assert "browserWorkflows" in prompt
    assert "photoProcessing" in prompt
    assert "SkySlope" in prompt
    assert "agentGuideMemory" in prompt
    assert "currentStageDocuments" in prompt
    assert "Use currentStageDocuments as the authoritative province-aware document set" in prompt
    assert "BC Listings & Sales" in prompt
    assert "Transaction Guide" in prompt
    assert "Multiple Listing Contract" in prompt
    assert '"packageKey": "ca.bc"' in prompt


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
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)

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
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)

    with connect() as conn:
        runs = list_action_runs(conn, deal_id=deal["id"])

    assert runs == []


def test_date_trigger_firing_ledger_is_unique():
    deal = _new_listing_deal()
    with connect() as conn:
        action = create_action(
            conn,
            name="subject reminder",
            trigger="time_offset",
            skill="seller-updates",
            side="listing",
        )
        first = record_date_trigger_firing(
            conn,
            deal_id=deal["id"],
            registry_id=action["id"],
            field_key="subjectRemovalDate",
            offset_days=-2,
            target_date="2026-06-01",
            actor="test",
        )
        second = record_date_trigger_firing(
            conn,
            deal_id=deal["id"],
            registry_id=action["id"],
            field_key="subjectRemovalDate",
            offset_days=-2,
            target_date="2026-06-01",
            actor="test",
        )

    assert first["created"] is True
    assert second["created"] is False
    assert second["id"] == first["id"]
