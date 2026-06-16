"""Phase B L2 — post-turn scorecard inference.

Exercises the real DB + gate + set_deal_toggle path. resolve_attributions is
patched so deal resolution is deterministic (not dependent on fuzzy-match
scoring); the aux call_llm is mocked so we control which cells it "satisfies".
"""
import json
import time
from types import SimpleNamespace

import pytest

import agent.turn_attribution as ta
from elevate_cli.data import connect, create_deal
from elevate_cli.data.deals import (
    deal_had_recent_inferred_ticks,
    deal_open_stage_cells,
    get_deal,
    human_controlled_checklist_cells,
    set_deal_toggle,
)


def _make_deal():
    with connect() as conn:
        return create_deal(
            conn, title="Maple Crescent Listing", side="listing", current_stage=0, actor="human:test"
        )


def _open_cell_ids(deal_id):
    with connect() as conn:
        deal = get_deal(conn, deal_id)
        return [c["id"] for c in deal_open_stage_cells(conn, deal)]


def _fake_llm(satisfied_ids, counter=None):
    def _call(*a, **k):
        if counter is not None:
            counter.append(1)
        content = json.dumps({"satisfied_ids": list(satisfied_ids)})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return _call


def _tc(name, args):
    return {"id": "x", "function": {"name": name, "arguments": json.dumps(args)}}


def _patch_deal(monkeypatch, deal_id, confidence=0.9):
    monkeypatch.setattr(
        ta, "resolve_attributions",
        lambda conn, turn, **k: [ta.Attribution("deal", deal_id, confidence, "Maple", [], "did stuff")],
    )


def _chat_turn(text="the pre-cma google form is filled now"):
    # Pure conversational turn — NO tool calls. This is exactly the case the
    # tool-gate trapdoor used to drop.
    return [
        {"role": "user", "content": "did we finish the google form?"},
        {"role": "assistant", "content": text},
    ]


def _toggle(deal_id, field, value, actor):
    with connect() as conn:
        set_deal_toggle(conn, deal_id, field=field, value=value, actor=actor)


def test_infers_and_ticks_on_chat_only_turn(monkeypatch):
    deal = _make_deal()
    cells = _open_cell_ids(deal["id"])
    assert cells, "stage 0 should have open required cells"
    target = cells[0]

    _patch_deal(monkeypatch, deal["id"])
    monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm([target]))

    applied = ta.run_scorecard_inference(_chat_turn())
    assert (deal["id"], target) in applied

    with connect() as conn:
        toggles = (get_deal(conn, deal["id"]) or {}).get("extraToggles") or {}
    assert toggles.get(target) is True


def test_skips_human_controlled_cell(monkeypatch):
    deal = _make_deal()
    cells = _open_cell_ids(deal["id"])
    assert len(cells) >= 2, "need >=2 open cells to test precedence"
    human_cell, agent_cell = cells[0], cells[1]

    # Realtor explicitly marked the first cell not-done.
    _toggle(deal["id"], human_cell, False, "human:realtor")
    assert human_cell in human_controlled_checklist_cells_for(deal["id"])

    _patch_deal(monkeypatch, deal["id"])
    # The model "satisfies" BOTH — the human-controlled one must still be skipped.
    monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm([human_cell, agent_cell]))

    applied = ta.run_scorecard_inference(_chat_turn())
    applied_cells = {c for _, c in applied}
    assert agent_cell in applied_cells
    assert human_cell not in applied_cells

    with connect() as conn:
        toggles = (get_deal(conn, deal["id"]) or {}).get("extraToggles") or {}
    assert toggles.get(human_cell) is not True
    assert toggles.get(agent_cell) is True


def test_no_open_cells_means_no_aux_call(monkeypatch):
    deal = _make_deal()
    cells = _open_cell_ids(deal["id"])
    # Tick every open cell so the stage has nothing pending.
    for c in cells:
        _toggle(deal["id"], c, True, "agent:test")

    _patch_deal(monkeypatch, deal["id"])
    calls: list[int] = []
    monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm([], counter=calls))

    applied = ta.run_scorecard_inference(_chat_turn())
    assert applied == []
    assert calls == [], "no open cells must short-circuit before the aux call"


def test_closed_set_guarantee_rejects_invented_id(monkeypatch):
    deal = _make_deal()
    _patch_deal(monkeypatch, deal["id"])
    monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm(["totally-made-up-cell"]))

    applied = ta.run_scorecard_inference(_chat_turn())
    assert applied == []


def test_low_confidence_deal_is_skipped(monkeypatch):
    deal = _make_deal()
    _patch_deal(monkeypatch, deal["id"], confidence=0.6)  # below SCORECARD_INFER_THRESHOLD
    calls: list[int] = []
    monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm([], counter=calls))

    applied = ta.run_scorecard_inference(_chat_turn())
    assert applied == []
    assert calls == []


def test_attribute_turn_safely_starts_l2_on_chat_only_turn(monkeypatch):
    """The actual trapdoor: attribute_turn_safely must START L2 on a turn with
    NO tool calls. Freshness logging is tool-gated; scorecard inference is not."""
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)

    seen: dict = {}

    def _spy(turn, **kwargs):
        seen["turn"] = list(turn)
        seen["kwargs"] = kwargs
        return []

    monkeypatch.setattr(ta, "run_scorecard_inference", _spy)

    # Run the spawned thread synchronously so the assertion is race-free.
    import threading

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
            self._t, self._a, self._k = target, args, kwargs or {}

        def start(self):
            self._t(*self._a, **self._k)

        def join(self, timeout=None):
            pass

    monkeypatch.setattr(threading, "Thread", _SyncThread)

    # Pure user/assistant turn — no tool calls anywhere.
    turn = [
        {"role": "user", "content": "did we finish the google form?"},
        {"role": "assistant", "content": "yes, the pre-cma google form is filled"},
    ]
    ta.attribute_turn_safely(turn, agent_id="admin", session_id="s1")

    assert "turn" in seen, "L2 was not started by attribute_turn_safely on a chat-only turn"
    assert not any(name for name, _ in ta._iter_tool_calls(seen["turn"])), "turn should have no tool calls"
    assert seen["kwargs"].get("session_id") == "s1"
    assert "sticky_ids" in seen["kwargs"]


# ── L3: board-sync nudge demoted to fallback ────────────────────────────────

def _nudge_msgs():
    # Prev turn worked a deal via a generic tool (build_turn_nudge requires the
    # last turn to have used a tool); current turn is the new user message.
    return [
        {"role": "user", "content": "work the maple deal"},
        {"role": "assistant", "content": "did stuff", "tool_calls": [_tc("draft_message", {})]},
        {"role": "user", "content": "thanks"},
    ]


def _patch_nudge_resolution(monkeypatch, deal_id, confidence=0.9):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    monkeypatch.setattr(
        ta, "resolve_attributions",
        lambda conn, turn, **k: [ta.Attribution("deal", deal_id, confidence, "Maple", [], "s")],
    )


def test_deal_had_recent_inferred_ticks_detects_and_ages_out():
    deal = _make_deal()
    cells = _open_cell_ids(deal["id"])
    with connect() as conn:
        assert deal_had_recent_inferred_ticks(conn, deal["id"]) is False
    _toggle(deal["id"], cells[0], True, "agent:inferred")
    with connect() as conn:
        assert deal_had_recent_inferred_ticks(conn, deal["id"]) is True
        # within_seconds=0 -> the tick is already in the past -> aged out.
        assert deal_had_recent_inferred_ticks(conn, deal["id"], within_seconds=0) is False


def test_nudge_suppressed_when_inferred_and_no_open_cells(monkeypatch):
    deal = _make_deal()
    _patch_nudge_resolution(monkeypatch, deal["id"])
    monkeypatch.setattr(
        "elevate_cli.data.deals.deal_had_recent_inferred_ticks", lambda conn, did, **k: True
    )
    monkeypatch.setattr("elevate_cli.data.deals.deal_open_stage_cells", lambda conn, deal: [])
    assert ta.build_turn_nudge(_nudge_msgs(), current_user_idx=2) is None


def test_nudge_kept_when_open_cells_remain(monkeypatch):
    deal = _make_deal()
    _patch_nudge_resolution(monkeypatch, deal["id"])
    monkeypatch.setattr(
        "elevate_cli.data.deals.deal_had_recent_inferred_ticks", lambda conn, did, **k: True
    )
    monkeypatch.setattr(
        "elevate_cli.data.deals.deal_open_stage_cells", lambda conn, deal: [{"id": "x", "label": "x"}]
    )
    nudge = ta.build_turn_nudge(_nudge_msgs(), current_user_idx=2)
    assert nudge and "Maple" in nudge


def test_nudge_kept_when_l2_did_nothing(monkeypatch):
    deal = _make_deal()
    _patch_nudge_resolution(monkeypatch, deal["id"])
    monkeypatch.setattr(
        "elevate_cli.data.deals.deal_had_recent_inferred_ticks", lambda conn, did, **k: False
    )
    nudge = ta.build_turn_nudge(_nudge_msgs(), current_user_idx=2)
    assert nudge and "Maple" in nudge


# ── bounded drain: async by default, sync-on-demand for one-shot exits ───────

def test_attribute_turn_safely_wait_true_ticks_before_return(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    deal = _make_deal()
    target = _open_cell_ids(deal["id"])[0]
    monkeypatch.setattr(
        ta, "resolve_attributions",
        lambda conn, turn, **k: [ta.Attribution("deal", deal["id"], 0.9, "X", [], "s")],
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm([target]))

    ta.attribute_turn_safely(
        _chat_turn(), agent_id="admin", session_id="s", wait=True, wait_timeout=10
    )
    # No sleep: wait=True must have drained the tick before returning.
    with connect() as conn:
        tg = (get_deal(conn, deal["id"]) or {}).get("extraToggles") or {}
    assert tg.get(target) is True


def test_attribute_turn_safely_default_is_async_and_quick(monkeypatch):
    from elevate_cli import access

    monkeypatch.setattr(access, "is_entitlement_active", lambda *a, **k: True)
    deal = _make_deal()
    target = _open_cell_ids(deal["id"])[0]
    monkeypatch.setattr(
        ta, "resolve_attributions",
        lambda conn, turn, **k: [ta.Attribution("deal", deal["id"], 0.9, "X", [], "s")],
    )

    def _slow_llm(*a, **k):
        time.sleep(2.0)  # if attribution were synchronous this would block the turn
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"satisfied_ids": [target]})))])

    monkeypatch.setattr("agent.auxiliary_client.call_llm", _slow_llm)

    start = time.monotonic()
    ta.attribute_turn_safely(_chat_turn(), agent_id="admin", session_id="s")  # wait=False default
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"interactive turn must not block on the aux call (took {elapsed:.2f}s)"

    # Still running async -> not ticked yet.
    with connect() as conn:
        tg = (get_deal(conn, deal["id"]) or {}).get("extraToggles") or {}
    assert tg.get(target) is not True

    # Join the async thread (healthy interpreter) and confirm it lands the tick.
    import threading

    for th in threading.enumerate():
        if th.name == ta._INFERENCE_THREAD_NAME:
            th.join(timeout=8)
    with connect() as conn:
        tg = (get_deal(conn, deal["id"]) or {}).get("extraToggles") or {}
    assert tg.get(target) is True


def test_should_wait_for_inference_defaults_to_true(monkeypatch):
    # One-shot / short-lived runs (no persistent marker) drain inline.
    monkeypatch.delenv(ta._PERSISTENT_PROCESS_ENV, raising=False)
    assert ta.should_wait_for_inference() is True


def test_persistent_marker_makes_inference_async(monkeypatch):
    monkeypatch.setenv(ta._PERSISTENT_PROCESS_ENV, "1")
    assert ta.should_wait_for_inference() is False


def test_mark_persistent_process_sets_flag():
    import os

    had = os.environ.pop(ta._PERSISTENT_PROCESS_ENV, None)
    try:
        assert ta.should_wait_for_inference() is True
        ta.mark_persistent_process()
        assert os.environ.get(ta._PERSISTENT_PROCESS_ENV) == "1"
        assert ta.should_wait_for_inference() is False
    finally:
        os.environ.pop(ta._PERSISTENT_PROCESS_ENV, None)
        if had is not None:
            os.environ[ta._PERSISTENT_PROCESS_ENV] = had


# helper kept out of the way of pytest collection
def human_controlled_checklist_cells_for(deal_id):
    with connect() as conn:
        return human_controlled_checklist_cells(conn, deal_id)
