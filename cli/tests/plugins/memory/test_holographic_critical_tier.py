"""Tests for the critical/pinned recall tier of the holographic memory store:

- Phase 0: trust ratchet (ranking outcome no longer mutates trust by default,
  explicit fact_feedback still does).
- Phase 2: classifier emits critical/critical_reason; merge preserves critical
  metadata (CONSTRAINT 1).
- Phase 3: reserved "Must-Follow Rules" recall lane (low-trust critical fact
  surfaces; tier kill-switch; absent when no critical facts; FACT-45 replay;
  injected critical fact_ids logged in memory_injections — CONSTRAINT 2).
- Phase 1: 0033 columns exist on memory_facts and the `facts` view still works.
- Phase 5: backfill_critical dry-run report.
"""

from __future__ import annotations

import json

import pytest

from plugins.memory.holographic import HolographicMemoryProvider
from plugins.memory.holographic.quality import classify_fact_durability


def _provider(tmp_path, **overrides):
    config = {
        "db_path": str(tmp_path / "memory.db"),
        "embedding_enabled": "false",
        "turn_journal_enabled": "true",
        "organize_on_session_end": "false",
        "organize_every_n_turns": "0",
    }
    config.update(overrides)
    provider = HolographicMemoryProvider(config=config)
    provider.initialize("session-ct")
    return provider


def _tool(provider, args):
    return json.loads(provider.handle_tool_call("fact_store", args))


def _set_trust(store, fact_id, trust):
    store._conn.execute(
        "UPDATE memory_facts SET trust_score = ? WHERE fact_id = ?", (float(trust), int(fact_id))
    )
    store._conn.commit()


def _flag_critical(store, fact_id, *, critical=True, pinned=False, task_tags="", reason="compliance"):
    store._set_critical_metadata(
        fact_id, critical=critical, pinned=pinned, task_tags=task_tags, critical_reason=reason
    )


def _clear_all_critical(store):
    # The embedded test PG is shared across tests; for "absent"-section
    # assertions we neutralize any critical/pinned flags left by siblings.
    store._conn.execute(
        "UPDATE memory_facts SET critical = false, pinned = false WHERE critical OR pinned"
    )
    store._conn.commit()


def _fact_row(store, fact_id):
    row = store._conn.execute(
        "SELECT trust_score, helpful_count, critical, pinned, task_tags, critical_reason, status "
        "FROM memory_facts WHERE fact_id = ?",
        (int(fact_id),),
    ).fetchone()
    return dict(row)


# ---------------------------------------------------------------------------
# Phase 0 — trust ratchet
# ---------------------------------------------------------------------------

def test_ratchet_off_keeps_trust_and_helpful_unchanged(tmp_path):
    # trust_from_ranking_enabled defaults to false.
    provider = _provider(tmp_path)
    store = provider._store
    fid = store.add_fact("Some durable note about the Skyleigh listing process and naming")
    _set_trust(store, fid, 0.50)
    before = _fact_row(store, fid)

    # Simulate a fact that loses the top-N cut N times (rejected candidate).
    for _ in range(5):
        store.post_retrieval_maintenance(verified_ids=[], rejected_ids=[fid], query="zzz")

    after = _fact_row(store, fid)
    assert after["trust_score"] == before["trust_score"]
    assert after["helpful_count"] == before["helpful_count"]

    # A "winner" also does NOT gain trust/helpful_count under the ratchet-off
    # default (helpful_count must stay 0 so the fact isn't pruning-exempted).
    for _ in range(5):
        store.post_retrieval_maintenance(verified_ids=[fid], rejected_ids=[], query="zzz")
    after2 = _fact_row(store, fid)
    assert after2["trust_score"] == before["trust_score"]
    assert after2["helpful_count"] == before["helpful_count"]


def test_ratchet_on_restores_legacy_trust_mutation(tmp_path):
    provider = _provider(tmp_path, trust_from_ranking_enabled="true")
    store = provider._store
    fid = store.add_fact("Another durable note about Walnut Grove class scheduling rules")
    _set_trust(store, fid, 0.50)
    store.post_retrieval_maintenance(verified_ids=[fid], rejected_ids=[], query="zzz")
    after = _fact_row(store, fid)
    # +0.03 (post_retrieval) + 0.05 (confidence_maintenance verified) = +0.08.
    assert after["trust_score"] > 0.50
    assert after["helpful_count"] >= 1


def test_explicit_feedback_still_moves_trust_with_ratchet_off(tmp_path):
    provider = _provider(tmp_path)  # ratchet off (default)
    store = provider._store
    fid = store.add_fact("Durable note about the Maple Ridge booking funnel single deal path")
    _set_trust(store, fid, 0.50)

    res_up = store.record_feedback(fid, helpful=True)
    assert res_up["new_trust"] > 0.50
    assert res_up["helpful_count"] >= 1

    res_down = store.record_feedback(fid, helpful=False)
    assert res_down["new_trust"] < res_up["new_trust"]


# ---------------------------------------------------------------------------
# Phase 2 — classifier + merge
# ---------------------------------------------------------------------------

def test_classifier_marks_correction_and_compliance_critical_not_convention():
    comp = classify_fact_durability(
        "When uploading the accepted offer, verify initials and signatures for every named party."
    )
    assert comp["critical"] is True
    assert comp["critical_reason"] == "compliance"

    corr = classify_fact_durability("Actually, the brokerage is eXp, not Royal LePage.")
    assert corr["critical"] is True
    assert corr["critical_reason"] == "correction"

    # Conventions (should/must/never/always) are NOT auto-critical in v1 — they
    # are too common on real corpora (~25% of facts) and would dilute the
    # reserved Must-Follow lane. They stay durable + keep the "convention"
    # signal, but critical=False. Must-always behavior needs a deliberate pin.
    conv = classify_fact_durability("Convention: comps must always be validated before send.")
    assert conv["durability"] == "durable"
    assert conv["critical"] is False
    assert conv["critical_reason"] == ""
    assert "convention" in conv["signals"]


def test_classifier_never_marks_generic_workflow_critical():
    for content in [
        "The dashboard runs on port 9131 for local testing",
        "Square revenue reports use Pacific timezone and net sales",
        "The Plaud webhook posts transcripts to the local archive",
    ]:
        res = classify_fact_durability(content)
        assert res["critical"] is False, (content, res)
        assert res["critical_reason"] == ""


def test_merge_preserves_incoming_critical_metadata(tmp_path):
    # CONSTRAINT 1.
    provider = _provider(tmp_path)
    store = provider._store
    base = "Qz1 the dashboard widget renders the listing summary panel for the smith account view"
    # Non-critical original (generic workflow content).
    fid = store.add_fact(base, category="project")
    row0 = _fact_row(store, fid)
    assert not row0["critical"]

    # Near-duplicate (jaccard >= 0.88), strictly more specific, classifies
    # critical (compliance — "signature"). Explicit save, but explicit no
    # longer implies pinned (P1 fix).
    crit = base + " signature"
    detailed = store.add_fact_detailed(crit, category="project", explicit=True)
    assert detailed["outcome"] == "merged"
    assert detailed["fact_id"] == fid

    row1 = _fact_row(store, fid)
    assert row1["critical"] is True              # incoming critical merged in (OR)
    assert row1["pinned"] is False               # explicit saves no longer pin (P1 fix)
    assert "task:filing" in str(row1["task_tags"])  # task_tags unioned
    assert row1["critical_reason"]               # reason preserved/added


def test_merge_ors_pinned_metadata(tmp_path):
    # CONSTRAINT 1: a pre-pinned surviving fact keeps pinned through a merge
    # (pinned = old OR incoming), independent of the (now removed) explicit→pin.
    provider = _provider(tmp_path)
    store = provider._store
    base = "Zx9 the prospecting export job writes the weekly comparable digest for the jones account"
    fid = store.add_fact(base, category="project")
    _flag_critical(store, fid, critical=True, pinned=True, task_tags="task:cma", reason="compliance")

    more_specific = base + " always"
    detailed = store.add_fact_detailed(more_specific, category="project", explicit=True)
    assert detailed["fact_id"] == fid
    row = _fact_row(store, fid)
    assert row["pinned"] is True   # old pinned survives the merge (OR)
    assert row["critical"] is True


# ---------------------------------------------------------------------------
# Phase 3 — Must-Follow Rules recall lane
# ---------------------------------------------------------------------------

def test_low_trust_critical_fact_surfaces_in_must_follow(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    _clear_all_critical(store)
    fid = store.add_fact(
        "Accepted-offer rule: verify enough initials and signatures for every named party.",
        category="transaction",
        explicit=True,
    )
    _set_trust(store, fid, 0.30)
    _flag_critical(store, fid, critical=True, task_tags="task:accepted-offer", reason="compliance")

    ctx = provider._build_layered_context(
        "I'm about to upload the accepted offer for the Smith deal", session_id="session-ct"
    )
    assert "### Must-Follow Rules" in ctx
    assert "initials" in ctx


def test_must_follow_absent_when_tier_disabled(tmp_path):
    provider = _provider(tmp_path, critical_tier_enabled="false")
    store = provider._store
    fid = store.add_fact(
        "Accepted-offer rule: verify enough initials and signatures for every named party.",
        category="transaction",
        explicit=True,
    )
    _set_trust(store, fid, 0.30)
    _flag_critical(store, fid, critical=True, task_tags="task:accepted-offer", reason="compliance")

    ctx = provider._build_layered_context(
        "I'm about to upload the accepted offer for the Smith deal", session_id="session-ct"
    )
    assert "### Must-Follow Rules" not in ctx


def test_must_follow_absent_when_no_critical_facts(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    # Genuinely non-critical content (no convention/correction/compliance words).
    store.add_fact(
        "Qz2 the report export uses the Pacific region setting for the summary page",
        category="tool",
    )
    _clear_all_critical(store)  # neutralize sibling-test critical/pinned facts
    ctx = provider._build_layered_context(
        "Qz2 region setting export summary page", session_id="session-ct"
    )
    assert "### Must-Follow Rules" not in ctx


def test_fact45_replay_lands_in_injected_prompt(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    _clear_all_critical(store)
    fid = store.add_fact(
        "Real-estate accepted-offer document review: when there are multiple names on either "
        "the buyer side or seller side, verify there are enough initials/signatures for every "
        "named party before selecting or uploading the accepted offer.",
        category="transaction",
        explicit=True,
    )
    _set_trust(store, fid, 0.30)
    _flag_critical(store, fid, critical=True, task_tags="task:accepted-offer", reason="compliance")

    ctx = provider._build_layered_context(
        "Help me pick the accepted offer to upload for this deal", session_id="session-ct"
    )
    assert "### Must-Follow Rules" in ctx
    assert "initials/signatures" in ctx


def test_critical_fact_ids_logged_in_memory_injections(tmp_path):
    # CONSTRAINT 2 — prefetch path logs both critical + durable fact_ids.
    provider = _provider(tmp_path)
    store = provider._store
    _clear_all_critical(store)
    crit_id = store.add_fact(
        "Accepted-offer rule: verify enough initials and signatures for every named party.",
        category="transaction",
        explicit=True,
    )
    _set_trust(store, crit_id, 0.30)
    _flag_critical(store, crit_id, critical=True, task_tags="task:accepted-offer", reason="compliance")

    # A durable, high-overlap, NON-critical fact for the same query words.
    dur_id = store.add_fact(
        "Accepted offer uploads go through SkySlope for the transaction record",
        category="transaction",
    )
    _set_trust(store, dur_id, 0.80)

    ctx = provider.prefetch(
        "I'm about to upload the accepted offer for the Smith deal", session_id="session-ct"
    )
    assert "### Must-Follow Rules" in ctx
    logged = store.injected_memory_ids("session-ct").get("fact_ids", set())
    assert crit_id in logged
    # And _last_layered_facts carries the critical id (append, not overwrite).
    assert crit_id in {int(f.get("fact_id")) for f in provider._last_layered_facts}


def test_full_legacy_needs_both_tier_off_and_ratchet_on(tmp_path):
    # CONSTRAINT 4: tier off alone is NOT full legacy — ratchet must also be on.
    provider = _provider(tmp_path, critical_tier_enabled="false")
    assert provider._critical_tier_enabled is False
    # Default still has the ratchet OFF (not legacy).
    assert provider._trust_from_ranking_enabled is False
    assert provider._store.trust_from_ranking_enabled is False

    legacy = _provider(
        tmp_path, critical_tier_enabled="false", trust_from_ranking_enabled="true"
    )
    assert legacy._critical_tier_enabled is False
    assert legacy._store.trust_from_ranking_enabled is True


# ---------------------------------------------------------------------------
# Phase 1 — migration / view compatibility
# ---------------------------------------------------------------------------

def test_0033_columns_exist_and_facts_view_still_selects(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    cols = {
        r["column_name"]
        for r in store._conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'memory_facts'"
        ).fetchall()
    }
    for c in ("critical", "pinned", "task_tags", "critical_reason"):
        assert c in cols, c

    # The compat `facts` view still selects fine (unchanged column list).
    fid = store.add_fact("View-compat check fact about the Eco Spa Vancouver Island brief")
    row = store._conn.execute(
        "SELECT fact_id, content, trust_score FROM facts WHERE fact_id = ?", (fid,)
    ).fetchone()
    assert int(row["fact_id"]) == fid


# ---------------------------------------------------------------------------
# Phase 5 — backfill_critical dry-run
# ---------------------------------------------------------------------------

def test_backfill_critical_dry_run_reports_without_writing(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    # Disable the durability gate's classifier critical-write so backfill has work:
    # add as non-explicit by inserting directly, OR just verify the dry-run report
    # surfaces a compliance fact that wasn't pre-flagged.
    fid = store._conn.execute(
        "INSERT INTO facts (content, category, tags, trust_score, source_type, status) "
        "VALUES (?, ?, ?, ?, ?, 'active') RETURNING fact_id",
        (
            "Backfill check: signatures and initials must be verified before filing the accepted offer",
            "transaction",
            "",
            0.3,
            "",
        ),
    ).fetchone()["fact_id"]
    store._conn.commit()

    report = store.backfill_critical(dry_run=True)
    assert report["dry_run"] is True
    assert report["applied"] == 0
    affected_ids = {a["fact_id"] for a in report["affected"]}
    assert fid in affected_ids
    # Dry-run did not write.
    assert _fact_row(store, fid)["critical"] is False

    # Apply (force past the rate gate — this test exercises apply/idempotency,
    # not the >15% sanity threshold, and the shared test corpus runs hot).
    applied = store.backfill_critical(dry_run=False, force=True)
    assert applied["applied"] >= 1
    assert _fact_row(store, fid)["critical"] is True
    rerun = store.backfill_critical(dry_run=True)
    assert fid not in {a["fact_id"] for a in rerun["affected"]}


# ---------------------------------------------------------------------------
# P1 regression — explicit/manual saves must not pin or squat the lane
# ---------------------------------------------------------------------------

def test_explicit_manual_save_does_not_pin_or_squat_lane(tmp_path):
    # P1: an explicit/manual fact save must NOT become pinned, and a generic
    # non-critical preference must NOT occupy the Must-Follow Rules lane on an
    # unrelated task. Repro: the green-tea preference squatting an accepted-
    # offer query as "[must-follow pinned] User prefers green tea ...".
    provider = _provider(tmp_path, critical_recall_limit="5")
    store = provider._store
    _clear_all_critical(store)

    # 1. Generic explicit/manual NON-critical fact, saved via the real tool
    #    path (explicit=True). Must come back critical=false AND pinned=false.
    res = _tool(provider, {"action": "add", "content": "User prefers green tea with oat milk on weekends"})
    pref_id = int(res["fact_id"])
    pref_row = _fact_row(store, pref_id)
    assert not pref_row["critical"], "a generic preference must not classify critical"
    assert not pref_row["pinned"], "an explicit/manual save must NOT be pinned (P1 fix)"

    # 2. A genuinely matching critical compliance fact for accepted-offer filing.
    crit_id = store.add_fact(
        "Accepted-offer document review: verify every named seller and buyer has "
        "initials and a signature before filing the CPS"
    )
    _flag_critical(
        store, crit_id, critical=True, pinned=False,
        task_tags="task:accepted-offer,task:filing", reason="compliance",
    )

    # 3. Unrelated (to green tea) accepted-offer / filing query.
    ctx = provider._build_layered_context(
        "Process the accepted offer for 1127 Columbia and upload the CPS to SkySlope",
        session_id="session-ct",
    )

    assert "### Must-Follow Rules" in ctx
    must_follow = ctx.split("### Must-Follow Rules", 1)[1].split("###", 1)[0]
    # 3/4. The generic preference must NOT appear in the lane.
    assert "green tea" not in must_follow.lower(), "non-critical preference squatted the lane (P1)"
    # 5. The matching critical fact still appears.
    assert "initials and a signature" in must_follow


# ---------------------------------------------------------------------------
# Backfill critical-rate sanity threshold (great <10% / inspect 10-15% / stop >15%)
# ---------------------------------------------------------------------------

def test_backfill_rate_guard_blocks_above_15pct(tmp_path, monkeypatch):
    import plugins.memory.holographic.store as storemod
    provider = _provider(tmp_path)
    store = provider._store
    store.add_fact("Rate-guard probe fact about the listing admin process and naming rules")

    CRIT = {"durability": "durable", "confidence": 1.0, "task_framed": False,
            "signals": ["correction"], "critical": True, "critical_reason": "correction"}
    NONE = {"durability": "durable", "confidence": 0.5, "task_framed": False,
            "signals": [], "critical": False, "critical_reason": ""}

    # 100% critical -> rate 1.0 -> verdict 'stop' -> apply is BLOCKED (writes
    # nothing) unless force=True.
    monkeypatch.setattr(storemod.fact_quality, "classify_fact_durability", lambda c: dict(CRIT))
    dry = store.backfill_critical(dry_run=True)
    assert dry["verdict"] == "stop"
    assert dry["critical_rate"] > 0.15
    assert dry["critical_count"] == dry["active_total"]  # all active flagged

    blocked = store.backfill_critical(dry_run=False)
    assert blocked.get("blocked") is True
    assert blocked["applied"] == 0                 # nothing written while blocked
    assert "force" in blocked["reason"].lower()

    forced = store.backfill_critical(dry_run=False, force=True)
    assert not forced.get("blocked")               # force overrides the stop gate
    assert forced["applied"] >= 1
    _clear_all_critical(store)                      # undo the forced mass-flag

    # 0% critical -> rate 0 -> verdict 'great'.
    monkeypatch.setattr(storemod.fact_quality, "classify_fact_durability", lambda c: dict(NONE))
    great = store.backfill_critical(dry_run=True)
    assert great["verdict"] == "great"
    assert great["critical_rate"] < 0.10
