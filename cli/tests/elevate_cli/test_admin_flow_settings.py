"""Per-install Admin deal-flow preference switches.

Two behaviours a customer asked us to change are *preferences*, not bugs, so
they are per-install settings instead of a code fork:

  * ``admin.auto_advance_enabled`` (default true) — checklist/gate-driven
    auto-advance of a deal card.
  * ``admin.buyer_agency_agreement_required`` (default true) — the BAEC item
    in the buyer "Client Onboarding" checklist.

Both default to mainline behaviour and are resolved at *call* time, so an
install can flip them in ``config.yaml`` without a code reload. Every test
below writes the config file *after* the modules under test were imported,
which is what proves the call-time resolution.
"""

from __future__ import annotations

import pytest
import yaml

from elevate_cli.admin_deal_flow import (
    BUYER_AGENCY_CHECKLIST_ID,
    resolve_admin_deal_flow,
)
from elevate_cli.config import get_config_path
from elevate_cli.data import (
    connect,
    create_deal,
    get_deal,
    move_deal_stage,
    queue_action_run,
    record_run_result,
    set_deal_toggle,
)
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _write_admin_config(**admin: object) -> None:
    """Write ``admin.*`` keys into the per-test ELEVATE_HOME config.yaml."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"admin": dict(admin)}), encoding="utf-8")


# Buyer "Client Onboarding" (stage 0) is the cheapest gate in the BC pack:
# checklist items plus one required field, no required documents.
_BUYER_ONBOARDING_ITEMS = ("dorts-pnc", "fintrac-id", "pre-approval")


def _buyer_deal_at_onboarding(conn, title: str) -> str:
    deal = create_deal(
        conn,
        title=title,
        side="buyer",
        actor="human:test",
        current_stage=0,
        province="BC",
    )
    return deal["id"]


def _clear_the_onboarding_gate(conn, deal_id: str, *, include_buyer_agency: bool) -> None:
    """Satisfy every buyer-onboarding requirement except the final write."""
    items = list(_BUYER_ONBOARDING_ITEMS)
    if include_buyer_agency:
        items.insert(0, BUYER_AGENCY_CHECKLIST_ID)
    # preApprovalAmount is a package-required field carried on the deal's
    # checklist/extra toggles, not a first-class deal column.
    set_deal_toggle(conn, deal_id, field="preApprovalAmount", value=750000, actor="human:test")
    for item in items:
        set_deal_toggle(conn, deal_id, field=item, value=True, actor="human:test")


# ── admin.buyer_agency_agreement_required ────────────────────────────────


def test_buyer_agency_item_is_present_by_default():
    flow = resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)
    items = flow["checklistItems"]
    assert [item["id"] for item in items] == [
        BUYER_AGENCY_CHECKLIST_ID,
        *_BUYER_ONBOARDING_ITEMS,
    ]
    assert items[0]["label"] == "Buyer's Agency Agreement signed (BAEC)"


def test_buyer_agency_item_is_omitted_when_the_setting_is_false():
    _write_admin_config(buyer_agency_agreement_required=False)
    flow = resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)
    assert [item["id"] for item in flow["checklistItems"]] == list(_BUYER_ONBOARDING_ITEMS)


def test_buyer_agency_setting_is_read_at_call_time():
    # Same process, same already-imported module: flipping the file flips the
    # resolved checklist with no reload.
    assert BUYER_AGENCY_CHECKLIST_ID in {
        item["id"] for item in resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)["checklistItems"]
    }
    _write_admin_config(buyer_agency_agreement_required=False)
    assert BUYER_AGENCY_CHECKLIST_ID not in {
        item["id"] for item in resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)["checklistItems"]
    }
    _write_admin_config(buyer_agency_agreement_required=True)
    assert BUYER_AGENCY_CHECKLIST_ID in {
        item["id"] for item in resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)["checklistItems"]
    }


def test_buyer_agency_setting_does_not_touch_other_stages_or_the_listing_side():
    listing_before = resolve_admin_deal_flow(package_key="ca.bc", side="listing", stage=0)
    buyer_stage_1_before = resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=1)
    _write_admin_config(buyer_agency_agreement_required=False)
    assert resolve_admin_deal_flow(package_key="ca.bc", side="listing", stage=0) == listing_before
    assert resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=1) == buyer_stage_1_before


# ── admin.auto_advance_enabled ───────────────────────────────────────────


def test_completed_checklist_auto_advances_by_default():
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Auto-advance default")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        assert get_deal(conn, deal_id)["currentStage"] == 1


def test_completed_checklist_does_not_auto_advance_when_the_setting_is_false():
    _write_admin_config(auto_advance_enabled=False)
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Auto-advance disabled")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        # Gate is fully clear — the card simply waits for a human to move it.
        deal = get_deal(conn, deal_id)
        assert deal["currentStage"] == 0


def test_auto_advance_setting_is_read_at_call_time():
    _write_admin_config(auto_advance_enabled=False)
    with connect() as conn:
        held = _buyer_deal_at_onboarding(conn, "Held card")
        _clear_the_onboarding_gate(conn, held, include_buyer_agency=True)
        assert get_deal(conn, held)["currentStage"] == 0

        # Flip the file mid-process; the next deal write picks it up.
        _write_admin_config(auto_advance_enabled=True)
        advanced = _buyer_deal_at_onboarding(conn, "Advancing card")
        _clear_the_onboarding_gate(conn, advanced, include_buyer_agency=True)
        assert get_deal(conn, advanced)["currentStage"] == 1


@pytest.mark.parametrize("raw,expected_stage", [("false", 0), ("no", 0), ("off", 0), ("true", 1), (0, 0), (1, 1)])
def test_auto_advance_accepts_hand_edited_yaml_spellings(raw, expected_stage):
    _write_admin_config(auto_advance_enabled=raw)
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, f"Spelling {raw!r}")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        assert get_deal(conn, deal_id)["currentStage"] == expected_stage


def test_unreadable_admin_config_falls_back_to_the_shipped_default():
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("admin: [this is not a mapping]\n", encoding="utf-8")
    flow = resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)
    assert BUYER_AGENCY_CHECKLIST_ID in {item["id"] for item in flow["checklistItems"]}
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Broken config")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        assert get_deal(conn, deal_id)["currentStage"] == 1


def _complete_a_run_at_onboarding(conn, deal_id: str) -> None:
    """Run the real completed-run callback path (record_run_result)."""
    run = queue_action_run(
        conn,
        deal_id=deal_id,
        skill="real-estate-admin/buyer-onboarding",
        payload={"currentStage": 0},
        actor="human:test",
    )
    record_run_result(conn, deal_id, run["id"], status="succeeded", actor="skill:test")


def test_completed_run_auto_advances_by_default():
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Completed run default")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        # The gate-clearing write already advanced it; put it back so the run
        # callback is the thing under test.
        move_deal_stage(conn, deal_id, to_stage=0, actor="human:test")
        _complete_a_run_at_onboarding(conn, deal_id)
        assert get_deal(conn, deal_id)["currentStage"] == 1


def test_completed_run_does_not_auto_advance_when_the_setting_is_false():
    _write_admin_config(auto_advance_enabled=False)
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Completed run disabled")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        assert get_deal(conn, deal_id)["currentStage"] == 0
        _complete_a_run_at_onboarding(conn, deal_id)
        assert get_deal(conn, deal_id)["currentStage"] == 0


def test_manual_stage_move_still_works_with_auto_advance_disabled():
    # The switch only disables *automatic* movement. A human (or the agent
    # acting on an explicit instruction) can still move the card.
    _write_admin_config(auto_advance_enabled=False)
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Manual move")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=True)
        assert get_deal(conn, deal_id)["currentStage"] == 0
        moved = move_deal_stage(conn, deal_id, to_stage=1, actor="human:test")
        assert moved["currentStage"] == 1


def test_both_settings_off_is_skyleighs_install():
    # Her install: no auto-advance, no BAEC item. The onboarding gate clears
    # on three items and the card still waits for her to move it.
    _write_admin_config(auto_advance_enabled=False, buyer_agency_agreement_required=False)
    flow = resolve_admin_deal_flow(package_key="ca.bc", side="buyer", stage=0)
    assert [item["id"] for item in flow["checklistItems"]] == list(_BUYER_ONBOARDING_ITEMS)
    with connect() as conn:
        deal_id = _buyer_deal_at_onboarding(conn, "Skyleigh install")
        _clear_the_onboarding_gate(conn, deal_id, include_buyer_agency=False)
        assert get_deal(conn, deal_id)["currentStage"] == 0
