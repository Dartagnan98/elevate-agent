"""Phase A — self-updating scorecards: live card gate + bulk checklist writes.

Covers:
- deal_card_gate(): the at-a-glance card scorecard (progress + gate state).
- admin_deal set_checklist: bulk `cells` map and the single-cell form.
"""
import json

from elevate_cli.data import connect, create_deal
from elevate_cli.data.deals import deal_card_gate, get_deal


def _make_deal(side="listing", stage=0):
    with connect() as conn:
        return create_deal(
            conn,
            title="Scorecard Deal",
            side=side,
            current_stage=stage,
            province="BC",
            actor="human:test",
        )


def test_deal_card_gate_reports_progress_and_gate():
    deal = _make_deal()
    with connect() as conn:
        row = get_deal(conn, deal["id"])
        card = deal_card_gate(conn, row)
    assert card["totalChecklist"] >= 1
    assert card["completedChecklist"] == 0
    assert card["progress"] == f"0/{card['totalChecklist']}"
    # Open cells on a fresh deal -> cannot advance, work remains.
    assert card["canAdvance"] is False
    assert card["missingCount"] >= 1
    assert card["blocked"] in (True, False)


def test_admin_deal_bulk_set_checklist(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)  # activate real_estate_admin
    from tools.admin_deal_tool import _admin_deal_handler

    deal = _make_deal()
    result = _admin_deal_handler(
        {
            "action": "set_checklist",
            "deal_id": deal["id"],
            "cells": {"workflow_alpha": True, "workflow_beta": True, "workflow_gamma": True},
        }
    )
    payload = json.loads(result)
    assert payload.get("success") is True
    assert set(payload["applied"].keys()) == {"workflow_alpha", "workflow_beta", "workflow_gamma"}

    with connect() as conn:
        row = get_deal(conn, deal["id"])
    toggles = row.get("extraToggles") or {}
    assert toggles.get("workflow_alpha") is True
    assert toggles.get("workflow_beta") is True
    assert toggles.get("workflow_gamma") is True


def test_admin_deal_single_cell_still_works(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    deal = _make_deal()
    result = _admin_deal_handler(
        {"action": "set_checklist", "deal_id": deal["id"], "field": "workflow_solo", "value": True}
    )
    payload = json.loads(result)
    assert payload.get("success") is True
    assert payload["applied"] == {"workflow_solo": True}


def test_admin_deal_set_checklist_requires_field_or_cells(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    deal = _make_deal()
    result = _admin_deal_handler({"action": "set_checklist", "deal_id": deal["id"]})
    payload = json.loads(result)
    assert payload.get("success") is not True
    assert "error" in payload


def test_admin_deal_cannot_self_record_human_approval(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    deal = _make_deal()
    result = _admin_deal_handler(
        {
            "action": "set_checklist",
            "deal_id": deal["id"],
            "field": "workflow_stage_0_complete",
            "value": True,
        }
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["error"] == "human_approval_required"

    with connect() as conn:
        row = get_deal(conn, deal["id"])
    assert (row.get("extraToggles") or {}).get("workflow_stage_0_complete") is not True


def test_admin_deal_never_advertises_or_accepts_force(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import ADMIN_DEAL_SCHEMA, _admin_deal_handler

    properties = ADMIN_DEAL_SCHEMA["function"]["parameters"]["properties"]
    assert "force" not in properties

    deal = _make_deal()
    result = _admin_deal_handler(
        {
            "action": "move",
            "deal_id": deal["id"],
            "to_stage": 5,
            "force": True,
        }
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["error"] == "human_gate_override_required"

    with connect() as conn:
        row = get_deal(conn, deal["id"])
    assert row["currentStage"] == 0


def test_admin_deal_prevalidates_bulk_approval_writes_atomically(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    deal = _make_deal()
    result = _admin_deal_handler(
        {
            "action": "set_checklist",
            "deal_id": deal["id"],
            "cells": {
                "workflow_safe_note_complete": True,
                "workflow_stage_0_complete": True,
            },
        }
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["error"] == "human_approval_required"

    with connect() as conn:
        row = get_deal(conn, deal["id"])
    toggles = row.get("extraToggles") or {}
    assert "workflow_safe_note_complete" not in toggles
    assert "workflow_stage_0_complete" not in toggles


def test_admin_deal_reports_persisted_provider_gate_status(monkeypatch):
    from elevate_cli import access
    from elevate_cli.data import queue_action_run

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    from tools.admin_deal_tool import _admin_deal_handler

    with connect() as conn:
        deal = create_deal(
            conn,
            title="Provider-gated tool run",
            side="buyer",
            current_stage=1,
            province="BC",
            actor="human:test",
            dispatch_initial_stage=False,
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/buyer-cps",
            payload={"mode": "draft"},
            create_cron_job=False,
            actor="human:test",
        )

    result = _admin_deal_handler(
        {
            "action": "complete_run",
            "deal_id": deal["id"],
            "run_id": run["id"],
            "status": "succeeded",
        }
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["status"] == "waiting_human"
    assert payload["taskCompleted"] is False
    assert payload["completedRun"] is None

    with connect() as conn:
        rows = conn.execute(
            "SELECT status, cron_job_id, callback_token_hash FROM admin_action_runs WHERE id=?",
            (run["id"],),
        ).fetchone()
    assert rows["status"] == "waiting_human"
    assert rows["cron_job_id"] is None
    assert rows["callback_token_hash"] is None


def test_admin_deal_cannot_complete_an_approval_waiting_run(monkeypatch):
    from elevate_cli import access
    from elevate_cli.data import create_action, list_action_runs

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    from tools.admin_deal_tool import _admin_deal_handler

    with connect() as conn:
        create_action(
            conn,
            name="Human approval required",
            trigger="stage_entry",
            skill="real-estate-admin/marketing",
            side="listing",
            to_stage=0,
            approval_required=True,
        )
        deal = create_deal(
            conn,
            title="Approval-gated tool run",
            side="listing",
            current_stage=0,
            province="BC",
            actor="human:test",
        )
        run = list_action_runs(conn, deal_id=deal["id"])[0]
    assert run["status"] == "waiting_human"

    result = _admin_deal_handler(
        {
            "action": "complete_run",
            "deal_id": deal["id"],
            "run_id": run["id"],
            "status": "succeeded",
        }
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert payload["error"] == "human_action_required"
    assert payload["status"] == "waiting_human"

    with connect() as conn:
        persisted = list_action_runs(conn, deal_id=deal["id"])[0]
    assert persisted["status"] == "waiting_human"
    assert persisted.get("result") is None


def test_external_callback_can_complete_waiting_external_run():
    from elevate_cli.data import queue_action_run, record_run_result

    with connect() as conn:
        deal = create_deal(
            conn,
            title="External import callback",
            side="listing",
            current_stage=0,
            province="BC",
            actor="human:test",
            dispatch_initial_stage=False,
        )
        run = queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="real-estate-admin/admin-listing-import",
            create_cron_job=False,
            actor="human:test",
        )
        parked = record_run_result(
            conn,
            deal["id"],
            run["id"],
            status="waiting_external",
            actor="skill:admin-listing-import",
        )
        completed = record_run_result(
            conn,
            deal["id"],
            run["id"],
            status="succeeded",
            idempotency_key="external-import-complete",
            actor="skill:web-callback",
        )

    assert parked["status"] == "waiting_external"
    assert completed["status"] == "succeeded"
