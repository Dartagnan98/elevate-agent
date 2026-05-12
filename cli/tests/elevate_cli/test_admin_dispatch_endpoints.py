"""PR-2 Admin Hub dispatcher tests.

Covers the registry CRUD endpoints, the run-log endpoint, and the hook
into ``data.deals`` (move_deal_stage, set_deal_toggle).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    complete_admin_setup,
    connect,
    create_action,
    create_deal,
    drain_queued_action_runs,
    evaluate_dispatch,
    get_admin_setup,
    import_exp_agent_centre,
    list_action_runs,
    move_deal_stage,
    mark_stale_action_runs,
    record_date_trigger_firing,
    set_deal_toggle,
    update_admin_setup,
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
    _complete_admin_setup()
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
    assert run["skill"] == "marketing"
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


def test_stale_running_action_runs_fail_with_visible_error():
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
    assert recovered[0]["status"] == "failed"
    assert "120 minute" in recovered[0]["errorMessage"]
    assert recovered[0]["payload"]["recovery"]["event"] == "stale_running_failed"


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
    assert runs[0]["humanPrompt"]["skill"] == "marketing"
    assert runs[0]["payload"]["registryName"] == "approval gated entry"

    approved = client.post(f"/api/admin/action-runs/{runs[0]['id']}/approve", json={"approved": True})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "running"
    assert body["cronJobId"]
    assert body["skill"] == "marketing"
    assert body["registryName"] == "approval gated entry"


def test_seed_default_admin_actions_is_idempotent_and_keeps_cron_watchers_out(client):
    first = client.post("/api/admin/actions/defaults")
    assert first.status_code == 200, first.text
    body = first.json()
    created_skills = {item["skill"] for item in body["created"]}
    assert {"mlc", "photo-cleanup", "listing-build", "offer-review", "subject-removal", "closing-admin"}.issubset(created_skills)
    created_names = {item["name"]: item for item in body["created"]}
    assert created_names["S1 Collect listing info for MLC"]["skillArgs"] == {"mode": "intake"}
    assert created_names["S2 Prepare MLC package"]["skillArgs"] == {"mode": "documents"}
    assert "gmail-doc-router" not in created_skills
    assert "seller-update" not in created_skills
    assert body["updated"] == []
    assert all(item["approvalRequired"] is False for item in body["created"])

    second = client.post("/api/admin/actions/defaults")
    assert second.status_code == 200, second.text
    assert second.json()["created"] == []
    assert second.json()["updated"] == []
    assert second.json()["count"] == body["count"]


def test_seed_default_admin_actions_updates_stale_default_rows(client):
    with connect() as conn:
        create_action(
            conn,
            name="S2 Prepare MLC package",
            trigger="stage_entry",
            skill="mlc",
            side="listing",
            to_stage=2,
            priority=1,
            approval_required=True,
        )

    resp = client.post("/api/admin/actions/defaults")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    updated = {item["name"]: item for item in body["updated"]}
    assert updated["S2 Prepare MLC package"]["priority"] == 90
    assert updated["S2 Prepare MLC package"]["approvalRequired"] is False
    assert updated["S2 Prepare MLC package"]["skillArgs"] == {"mode": "documents"}


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
    assert job["skills"] == ["admin-agent", "deal-matcher", "marketing", "admin-result-writer"]
    assert "Admin agent orchestration" in job["prompt"]
    assert "Admin Telegram handoff" in job["prompt"]
    assert f"POST http://127.0.0.1:9119/api/deals/{deal['id']}/runs/{run['id']}/result" in job["prompt"]
    assert "Report SQLite changes only after the result callback succeeds" in job["prompt"]
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
            current_stage=4,
        )
        create_action(
            conn,
            name="launch seller update",
            trigger="stage_entry",
            skill="seller-updates",
            side="listing",
            to_stage=5,
        )
        move_deal_stage(conn, deal["id"], to_stage=5, actor="human:test", force=True)
        run = list_action_runs(conn, deal_id=deal["id"])[0]

    from cron.jobs import load_jobs

    job = next(job for job in load_jobs() if job["id"] == run["cronJobId"])
    prompt = job["prompt"]
    assert "Injected source-of-truth context from SQLite" in prompt
    assert "browserWorkflows" in prompt
    assert "photoProcessing" in prompt
    assert "SkySlope" in prompt
    assert "agentGuideMemory" in prompt
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
