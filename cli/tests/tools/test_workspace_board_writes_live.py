"""End-to-end proof that the agent can actually work its own board.

Everything else in this package proves the POLICY is right. This file proves
the product is: it drives the real registry entries through the real atomic
shadow boundary (``execute_shadow`` — the same chokepoint every agent-loop
lane traverses), under exact Realtor Beta, with the policy a realtor's own
``default`` permission mode actually produces, against the live embedded
operational store.

For each board write it asserts three things, because two of them alone would
not be enough:

1. the call is AUTHORIZED (the ceiling admits it),
2. the row actually CHANGED in the store (the write really happened), and
3. a terminal effect RECEIPT exists naming the exact effect set (the A3
   broker claimed it, so it is durably evidenced and single-winner).
"""

from __future__ import annotations

import json

import pytest

import tools.effect_broker as effect_broker
from elevate_cli import access as access_module
from elevate_cli.data import connection as connection_module
from elevate_state import SessionDB
from tools.approval import (
    ExecutionPolicyMode,
    execution_policy_for_permission_mode,
    reset_current_execution_policy,
    set_current_execution_policy,
)
from tools.registry import ToolCallContext, registry

# Import for registration side effects: these modules register the board tools.
import tools.admin_deal_tool  # noqa: F401
import tools.kanban_tools  # noqa: F401
import tools.lead_status_tool  # noqa: F401
import tools.working_state_tool  # noqa: F401


@pytest.fixture
def beta(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")


@pytest.fixture
def broker_db(tmp_path, monkeypatch) -> SessionDB:
    db = SessionDB(tmp_path / "state.db")
    monkeypatch.setattr(effect_broker, "_store_override", db)
    monkeypatch.setattr(effect_broker, "_initialized_store_keys", set())
    return db


@pytest.fixture
def entitled(monkeypatch):
    monkeypatch.setattr(access_module, "is_entitlement_active", lambda *a, **k: True)


@pytest.fixture
def realtor_policy(beta):
    """Exactly what a realtor's shipped config produces.

    ``approvals.permission_mode: default`` -> the Beta clamp -> WORKSPACE.
    A ceiling that only lifted in some opt-in mode would not be a fix, so the
    proof deliberately starts from the default.
    """
    policy = execution_policy_for_permission_mode("turn-live-board", "default")
    assert policy.mode is ExecutionPolicyMode.WORKSPACE
    return policy


def _context(invocation_id: str) -> ToolCallContext:
    return ToolCallContext(
        session_id="session-live-board",
        invocation_id=invocation_id,
        accepted_turn_id="turn-live-board",
        policy_revision=1,
    )


def _run(tool: str, args: dict, policy, invocation_id: str):
    """Dispatch one tool the way the gateway does.

    The policy is BOUND for the duration, not just passed: ``server.py``
    wraps the whole turn in ``set_current_execution_policy`` before any tool
    runs, and the severances inside the data layer read that binding. A test
    that only passes ``execution_policy=`` authorizes correctly but leaves the
    handler running with no ambient policy, so every severance falls through
    to its legacy branch and the test proves less than it appears to.
    """
    token = set_current_execution_policy(policy, policy_revision=1)
    try:
        return registry.execute_shadow(
            tool, args, context=_context(invocation_id), execution_policy=policy
        )
    finally:
        reset_current_execution_policy(token)


def _receipt(broker_db: SessionDB, outcome):
    assert outcome.effect_receipt is not None, "board write produced no claim"
    receipt = broker_db.get_tool_effect_receipt(outcome.effect_receipt.claim_id)
    assert receipt is not None
    return receipt


# ---------------------------------------------------------------------------
# Leads board
# ---------------------------------------------------------------------------


def test_agent_can_label_a_lead_on_its_own_board(
    realtor_policy, broker_db, entitled, monkeypatch
):
    monkeypatch.setattr(
        "tools.lead_status_tool._crm_mirror_reachable_for_set", lambda: False
    )
    from elevate_cli.data import upsert_contact

    contact_id = "live-board-lead-1"
    with connection_module.connect() as conn:
        upsert_contact(
            conn,
            contact_id=contact_id,
            display_name="Live Board Lead",
            type="buyer",
            stage="warm",
        )

    outcome = _run(
        "lead_status",
        {"action": "heat", "contact_id": contact_id, "label": "hot"},
        realtor_policy,
        "call-lead-heat",
    )

    # 1. authorized and executed
    assert outcome.started is True
    payload = json.loads(outcome.result)
    assert payload["success"] is True
    assert payload["heat"] == "hot"

    # 2. the store really changed
    with connection_module.connect() as conn:
        row = conn.execute(
            "SELECT heat_label FROM contacts WHERE id=?", (contact_id,)
        ).fetchone()
    assert row[0] == "hot"

    # 3. durably receipted, naming the exact effects
    receipt = _receipt(broker_db, outcome)
    assert receipt["status"] == "succeeded"
    assert receipt["effect_set"] == ["read:leads", "write_local:leads"]
    assert receipt["tool_name"] == "lead_status"
    assert receipt["session_id"] == "session-live-board"


def test_agent_can_set_a_pipeline_status_while_the_crm_mirror_is_off(
    realtor_policy, broker_db, entitled, monkeypatch
):
    monkeypatch.setattr(
        "tools.lead_status_tool._crm_mirror_reachable_for_set", lambda: False
    )
    from elevate_cli.data import upsert_contact

    contact_id = "live-board-lead-2"
    with connection_module.connect() as conn:
        upsert_contact(
            conn,
            contact_id=contact_id,
            display_name="Live Status Lead",
            type="buyer",
            stage="warm",
        )

    outcome = _run(
        "lead_status",
        {"action": "set", "contact_id": contact_id, "status": "follow_up"},
        realtor_policy,
        "call-lead-set",
    )

    assert outcome.started is True
    assert json.loads(outcome.result)["success"] is True
    with connection_module.connect() as conn:
        row = conn.execute(
            "SELECT pipeline_status FROM contacts WHERE id=?", (contact_id,)
        ).fetchone()
    assert row[0] == "follow_up"
    assert _receipt(broker_db, outcome)["status"] == "succeeded"


def test_the_same_status_change_is_refused_when_it_would_reach_the_crm(
    realtor_policy, broker_db, entitled, monkeypatch
):
    """Same tool, same action, same board — refused because it would leave.

    This is the whole point of the design: the line is drawn by what the call
    physically does, not by which tool made it.
    """
    monkeypatch.setattr(
        "tools.lead_status_tool._crm_mirror_reachable_for_set", lambda: True
    )
    from elevate_cli.data import upsert_contact

    contact_id = "live-board-lead-3"
    with connection_module.connect() as conn:
        upsert_contact(
            conn,
            contact_id=contact_id,
            display_name="Mirrored Lead",
            type="buyer",
            stage="warm",
        )
        before = conn.execute(
            "SELECT pipeline_status FROM contacts WHERE id=?", (contact_id,)
        ).fetchone()[0]

    outcome = _run(
        "lead_status",
        {"action": "set", "contact_id": contact_id, "status": "dead"},
        realtor_policy,
        "call-lead-set-mirrored",
    )

    assert outcome.started is False, "a refused effect must not run the handler"
    with connection_module.connect() as conn:
        after = conn.execute(
            "SELECT pipeline_status FROM contacts WHERE id=?", (contact_id,)
        ).fetchone()[0]
    assert after == before, "the local write must not happen either"


# ---------------------------------------------------------------------------
# Working-state journal
# ---------------------------------------------------------------------------


def test_agent_can_write_its_own_where_we_left_off_note(
    realtor_policy, broker_db, entitled
):
    from elevate_cli.data import upsert_contact

    contact_id = "live-board-ws-1"
    with connection_module.connect() as conn:
        upsert_contact(
            conn,
            contact_id=contact_id,
            display_name="Journal Contact",
            type="buyer",
            stage="warm",
        )

    outcome = _run(
        "working_state",
        {
            "action": "update",
            "entity_kind": "contact",
            "entity_id": contact_id,
            "body": "Left a voicemail; waiting on a callback before pricing.",
            "status": "pending_external",
            "blocked_on": "the buyer's callback",
        },
        realtor_policy,
        "call-ws-update",
    )

    assert outcome.started is True
    assert json.loads(outcome.result)["success"] is True

    recall = _run(
        "working_state",
        {"action": "recall", "entity_kind": "contact", "entity_id": contact_id},
        realtor_policy,
        "call-ws-recall",
    )
    assert "voicemail" in recall.result

    receipt = _receipt(broker_db, outcome)
    assert receipt["status"] == "succeeded"
    assert receipt["effect_set"] == [
        "read:working_state",
        "write_local:working_state",
    ]


# ---------------------------------------------------------------------------
# Deal board
# ---------------------------------------------------------------------------


def test_agent_can_tick_a_checklist_cell_on_a_real_deal(
    realtor_policy, broker_db, entitled
):
    from elevate_cli.data import create_deal

    with connection_module.connect() as conn:
        deal = create_deal(
            conn, title="14 Rosewood Dr", side="listing", actor="test",
        )
    deal_id = deal["id"]

    outcome = _run(
        "admin_deal",
        {
            "action": "set_fields",
            "deal_id": deal_id,
            "fields": {"listPrice": 915000},
        },
        realtor_policy,
        "call-deal-fields",
    )

    assert outcome.started is True
    assert json.loads(outcome.result)["success"] is True

    with connection_module.connect() as conn:
        row = conn.execute(
            "SELECT list_price FROM deals WHERE id=?", (deal_id,)
        ).fetchone()
    assert int(row[0]) == 915000

    receipt = _receipt(broker_db, outcome)
    assert receipt["status"] == "succeeded"
    assert receipt["effect_set"] == [
        "read:deals",
        "write_local:deals",
        "write_local:working_state",
    ]


def test_a_live_stage_move_never_hands_work_to_cron_and_stamps_the_row(
    realtor_policy, broker_db, entitled, monkeypatch
):
    """The severance, proven through the real tool against real matching rules.

    Care is needed to make this trip-wire able to FIRE at all: every seeded
    entry in ``_DEFAULT_ADMIN_ACTIONS`` is a ``stage_entry`` trigger, so a
    ``set_checklist`` call (``toggle_change``) matches zero rules, creates zero
    runs, and can never reach ``_spawn_cron_job`` no matter what the severance
    does. So this drives a real stage transition into stage 0, which two
    seeded listing rules match.

    It asserts both halves: cron was never handed the work, AND the surviving
    queued rows carry the durable ``spawnWithheld`` stamp — the half that
    makes the cut outlive this call stack.
    """
    from elevate_cli.data import create_deal, dispatch as dispatch_module
    from elevate_cli.data.deals import move_deal_stage

    def _must_not_run(*_a, **_k):
        raise AssertionError("a board write handed work to cron")

    monkeypatch.setattr(dispatch_module, "_spawn_cron_job", _must_not_run)

    with connection_module.connect() as conn:
        dispatch_module.ensure_default_admin_actions(conn)
        deal = create_deal(
            conn, title="9 Alder Ct", side="listing", actor="test",
        )
        deal_id = deal["id"]
        # Position the card ahead of stage 0 OUTSIDE any policy, so the tool
        # call below is a backward move: no phase gate to satisfy, and
        # stage_entry(to_stage=0) matches the two seeded Pre-CMA rules.
        move_deal_stage(conn, deal_id, to_stage=1, actor="test", force=True)
        conn.execute("DELETE FROM admin_action_runs WHERE deal_id=?", (deal_id,))

    outcome = _run(
        "admin_deal",
        {"action": "move", "deal_id": deal_id, "to_stage": 0},
        realtor_policy,
        "call-deal-move",
    )

    assert outcome.started is True
    assert json.loads(outcome.result)["success"] is True

    with connection_module.connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM admin_action_runs WHERE deal_id=?",
            (deal_id,),
        ).fetchall()

    assert rows, (
        "no action runs were created — the trip-wire cannot prove anything; "
        "check that the seeded stage_entry rules still match stage 0"
    )
    for row in rows:
        payload = dispatch_module._decode_json(row[0])
        assert dispatch_module._spawn_is_withheld(payload), (
            "a run created by a board write was not stamped, so a later "
            "unpoliced drain could hand it to cron"
        )


# ---------------------------------------------------------------------------
# Every board write is receipted; every outward reach is still refused
# ---------------------------------------------------------------------------


def test_no_board_write_can_be_silently_unreceipted(realtor_policy, broker_db):
    """Beyond-read means claim-required, so a receipt always exists."""
    from tools.effect_broker import claim_required_for_effects

    for tool, args in (
        ("kanban_create", {"title": "x", "assignee": "y"}),
        ("kanban_complete", {"task_id": "t", "summary": "s"}),
        ("kanban_comment", {"task_id": "t", "body": "b"}),
        ("lead_status", {"action": "heat", "contact_id": "c"}),
        ("admin_deal", {"action": "set_checklist", "deal_id": "d"}),
        ("working_state", {
            "action": "update", "entity_kind": "contact",
            "entity_id": "c", "body": "b",
        }),
    ):
        effects = registry.resolve_effects(tool, args)
        assert claim_required_for_effects(effects) is True, tool


def test_outbound_tools_are_still_refused_under_the_realtor_policy(realtor_policy):
    """The containment that matters is untouched: nothing reaches a client."""
    from tools.approval import authorize_effects

    for tool, args in (
        ("send_message", {"to": "+15550001111", "body": "hi"}),
        ("send_message", {"to": "someone@example.com", "body": "hi"}),
    ):
        entry = registry.get_entry(tool)
        if entry is None:  # pragma: no cover — tool not registered in this build
            continue
        effects = registry.resolve_effects(tool, args)
        assert authorize_effects(realtor_policy, effects).allowed is False, tool
