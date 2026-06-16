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
            conn, title="Scorecard Deal", side=side, current_stage=stage, actor="human:test"
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
