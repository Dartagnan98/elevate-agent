"""Tests for the write-time quality gate of the holographic memory store:

- durability classifier (pure rules, real junk/good examples)
- durability gate at the add_fact choke point (extraction vs explicit)
- dedup-at-write (normalized exact, Jaccard fallback, embedding cosine, merge)
- TTL decay pass (archive-only, token-gated, never touches durable/explicit)
- extraction-pass throttle (entity minting + relation cap)
- memory_tool explicit-save durability warning
"""

from __future__ import annotations

import json

import pytest

from plugins.memory.holographic import HolographicMemoryProvider
from plugins.memory.holographic.quality import (
    EphemeralFactSkipped,
    classify_fact_durability,
    entity_mint_allowed,
    is_entity_skippable,
    token_jaccard,
)
from plugins.memory.holographic.store import DAILY_MAINTENANCE_TOKEN


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
    provider.initialize("session-q")
    return provider


def _tool(provider, args):
    return json.loads(provider.handle_tool_call("fact_store", args))


def _active_facts(provider, limit=200):
    return _tool(provider, {"action": "list", "limit": limit})["facts"]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

# Real junk observed in the production account (must classify ephemeral).
EPHEMERAL_EXAMPLES = [
    "User wants to just run a test",
    "User wants to make a skill for X",
    "User wants to run a quick test",
    "User asked to check the logs",
    "User is testing the dashboard right now",
    "User needs the deploy fixed",
    "User is asking to try the export again",
]

# Real durable shapes from the production account (must classify durable).
DURABLE_EXAMPLES = [
    "CMA skill convention: leave-behind PDFs must be audited before delivery",
    "Chrome executable path is /Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "User prefers alert responses to lead with the metric",
    "User always geotargets by postal code for Skyleigh campaigns",
    "Project decision: we decided to say classes, not cohorts",
    "Elevate Demo uses Telegram for quick testing",
    "Square revenue reports use Pacific timezone and net sales, never gross",
    "Elevation HQ backend runs on Hetzner 5.78.46.234 under PM2 elevation-hq",
]


@pytest.mark.parametrize("content", EPHEMERAL_EXAMPLES)
def test_classifier_flags_real_junk_as_ephemeral(content):
    result = classify_fact_durability(content)
    assert result["durability"] == "ephemeral", (content, result)
    assert result["task_framed"] is True


@pytest.mark.parametrize("content", DURABLE_EXAMPLES)
def test_classifier_keeps_real_facts_durable(content):
    result = classify_fact_durability(content)
    assert result["durability"] == "durable", (content, result)


def test_classifier_defaults_durable_with_no_signals():
    result = classify_fact_durability("the sky is blue today")
    assert result["durability"] == "durable"
    assert result["confidence"] == 0.5


def test_entity_helpers():
    assert is_entity_skippable("x", frozenset())
    assert is_entity_skippable("the", frozenset({"the"}))
    assert not is_entity_skippable("Skyleigh", frozenset({"the"}))
    assert entity_mint_allowed("Skyleigh")
    assert entity_mint_allowed("config.yaml")
    assert entity_mint_allowed("acct_65f")
    assert not entity_mint_allowed("deploy")
    assert not entity_mint_allowed("testing")


# ---------------------------------------------------------------------------
# Durability gate at the choke point
# ---------------------------------------------------------------------------

def test_gate_refuses_non_explicit_ephemeral_add(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    with pytest.raises(EphemeralFactSkipped):
        store.add_fact("User wants to just run a gatecheck trial", category="user_pref")
    assert all(
        "gatecheck trial" not in f["content"] for f in _active_facts(provider)
    )


def test_gate_warns_but_saves_explicit_ephemeral_add(tmp_path):
    provider = _provider(tmp_path)
    result = _tool(provider, {
        "action": "add",
        "content": "User wants to just run a test",
        "category": "user_pref",
    })
    assert result["status"] == "added"
    assert result["durability"] == "ephemeral"
    assert "warning" in result
    facts = _active_facts(provider)
    saved = [f for f in facts if "just run a test" in f["content"]]
    assert len(saved) == 1
    # Explicit-save flag wins over the default 'manual' source_type.
    assert saved[0]["source_type"] == "explicit"


def test_gate_passes_durable_add_and_tags_metadata(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    fact_id = store.add_fact(
        "CMA skill convention: leave-behind PDFs must be audited before delivery",
        category="project",
    )
    assert fact_id > 0
    row = store._conn.execute(
        "SELECT durability, durability_confidence FROM memory_facts WHERE fact_id = ?",
        (fact_id,),
    ).fetchone()
    assert row["durability"] == "durable"
    assert float(row["durability_confidence"]) > 0


def test_organize_journal_gates_task_chatter_keeps_it_in_journal(tmp_path):
    provider = _provider(tmp_path)
    # pref-pattern extraction turns this into "User wants to just run a quick test"
    provider.sync_turn(
        "I want to just run a quick test.",
        "On it.",
        session_id="session-q",
    )
    result = provider._organize_journal(session_id="session-q")
    assert result["promoted"] == 0
    assert result["gated_ephemeral"] >= 1
    # The turn stays available in the journal (gated facts are not lost).
    row = provider._store._conn.execute(
        "SELECT COUNT(*) AS n FROM memory_turn_journal WHERE session_id = ?",
        ("session-q",),
    ).fetchone()
    assert int(row["n"]) >= 1


def test_organize_journal_still_promotes_explicit_and_durable(tmp_path):
    provider = _provider(tmp_path)
    provider.sync_turn(
        "Remember this: Elevate Demo uses Telegram for quick testing.",
        "Saved.",
        session_id="session-q",
    )
    provider.sync_turn(
        "I always geotarget by postal code for Skyleigh campaigns.",
        "Noted.",
        session_id="session-q",
    )
    result = provider._organize_journal(session_id="session-q")
    assert result["promoted"] >= 2
    contents = [f["content"] for f in _active_facts(provider)]
    assert any("Telegram" in c for c in contents)
    assert any("postal code" in c for c in contents)


# ---------------------------------------------------------------------------
# Dedup-at-write
# ---------------------------------------------------------------------------

def _facts_containing(store, marker):
    rows = store._conn.execute(
        "SELECT fact_id, content, status FROM facts WHERE content LIKE ? AND COALESCE(status,'active') = 'active'",
        (f"%{marker}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def test_distinct_facts_both_insert(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    id_a = store.add_fact("Uppercuts Willowbrook qg1 deal: haircut $10 off")
    id_b = store.add_fact("Eco Spa Vancouver Island qg1 shows offer $3,000 off")
    assert id_a != id_b
    assert len(_facts_containing(store, "qg1")) == 2


def test_near_duplicate_merges_into_older_fact(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    original = "Qg2 CMA leave-behind convention: exported PDFs must be audited before delivery"
    reworded = "Qg2 CMA leave-behind convention: exported PDFs must be audited before delivery happens"
    assert token_jaccard(original, reworded) >= 0.88

    id_a = store.add_fact(original, category="project")
    detailed = store.add_fact_detailed(reworded, category="project")
    assert detailed["outcome"] == "merged"
    assert detailed["fact_id"] == id_a
    assert len(_facts_containing(store, "Qg2")) == 1

    row = store._conn.execute(
        "SELECT reinforced_count FROM memory_facts WHERE fact_id = ?", (id_a,)
    ).fetchone()
    assert int(row["reinforced_count"]) >= 1

    events = store.recent_memory_events(limit=20)
    assert any(e["event"] == "memory.fact.merged" for e in events)


def test_merge_updates_content_only_when_strictly_more_specific(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store
    base = "Qg3 CMA review convention: comparable listings must be validated before send"
    more_specific = base + " to Skyleigh"
    id_a = store.add_fact(base, category="project")
    detailed = store.add_fact_detailed(more_specific, category="project")
    assert detailed["outcome"] == "merged"
    facts = _facts_containing(store, "Qg3")
    assert len(facts) == 1
    assert facts[0]["content"] == more_specific

    # Less specific rewording does NOT overwrite the kept content.
    detailed2 = store.add_fact_detailed(base, category="project")
    assert detailed2["outcome"] == "merged"
    assert _facts_containing(store, "Qg3")[0]["content"] == more_specific


def test_exact_duplicate_returns_existing_and_reinforces(tmp_path):
    provider = _provider(tmp_path, dedup_enabled="false")
    store = provider._store
    content = "Qg4 Square revenue reports use Pacific timezone and net sales"
    id_a = store.add_fact(content)
    detailed = store.add_fact_detailed(content)
    assert detailed["fact_id"] == id_a
    assert detailed["outcome"] in ("duplicate", "merged")
    assert len(_facts_containing(store, "Qg4")) == 1


def test_embedding_cosine_dedup_with_hash_backend(tmp_path):
    provider = _provider(
        tmp_path,
        embedding_enabled="true",
        embedding_provider="hash",
        dedup_similarity_threshold="0.9",
    )
    store = provider._store
    assert store.embedding_client is not None
    id_a = store.add_fact(
        "Skyleigh listing playbook: subject removals happen before the Clifford CMA review"
    )
    detailed = store.add_fact_detailed(
        "Skyleigh listing playbook: subject removals happen before the Clifford CMA review session"
    )
    assert detailed["outcome"] == "merged"
    assert detailed["fact_id"] == id_a
    assert detailed["merged_with_similarity"] >= 0.9


# ---------------------------------------------------------------------------
# TTL decay (archive) pass
# ---------------------------------------------------------------------------

def test_archive_requires_daily_maintenance_token(tmp_path):
    provider = _provider(tmp_path)
    with pytest.raises(PermissionError):
        provider._store.archive_ephemeral_facts(daily_maintenance_token=object())


def test_archive_ephemeral_backlog_never_touches_durable_or_explicit(tmp_path):
    # Gate disabled to simulate the historical backlog that got in pre-gate.
    provider = _provider(tmp_path, durability_gate_enabled="false")
    store = provider._store

    junk_id = store.add_fact("User wants to just run a qg5 trial", category="user_pref")
    durable_id = store.add_fact(
        "Chrome executable path is /Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    explicit_id = store.add_fact(
        "User wants to make a qg5 skill for X", source_type="explicit"
    )

    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN
    )
    assert result["ran"] is True
    archived_ids = {c["fact_id"] for c in result["candidates"]}
    assert junk_id in archived_ids
    assert durable_id not in archived_ids
    assert explicit_id not in archived_ids

    remaining = {f["fact_id"] for f in _active_facts(provider)}
    assert junk_id not in remaining
    assert durable_id in remaining
    assert explicit_id in remaining

    # Archived, not deleted — the row still exists with archived status.
    row = store._conn.execute(
        "SELECT status FROM facts WHERE fact_id = ?", (junk_id,)
    ).fetchone()
    assert row["status"] == "archived"

    events = store.recent_memory_events(limit=20)
    assert any(e["event"] == "memory.fact.ephemeral_archived" for e in events)


def test_archive_old_unrecalled_task_framed_fact(tmp_path):
    provider = _provider(tmp_path, durability_gate_enabled="false")
    store = provider._store
    # Task-framed but below the high-confidence ephemeral bar (proper noun).
    fact_id = store.add_fact("User is reviewing the Skyleigh qg6 listing")
    cls = classify_fact_durability("User is reviewing the Skyleigh qg6 listing")
    assert cls["task_framed"] is True

    # Fresh: not archived (age guard).
    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN, min_confidence=1.1
    )
    assert fact_id not in {c["fact_id"] for c in result["candidates"]}

    # Backdate 40 days, still unrecalled -> archived.
    store._conn.execute(
        "UPDATE facts SET created_at = CURRENT_TIMESTAMP - INTERVAL '40 days' WHERE fact_id = ?",
        (fact_id,),
    )
    store._conn.commit()
    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN, min_confidence=1.1
    )
    assert fact_id in {c["fact_id"] for c in result["candidates"]}


def test_archive_skips_recalled_task_framed_fact(tmp_path):
    provider = _provider(tmp_path, durability_gate_enabled="false")
    store = provider._store
    fact_id = store.add_fact("User is reviewing the Skyleigh qg7 listing")
    store._conn.execute(
        "UPDATE facts SET created_at = CURRENT_TIMESTAMP - INTERVAL '40 days', retrieval_count = 3 WHERE fact_id = ?",
        (fact_id,),
    )
    store._conn.commit()
    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN, min_confidence=1.1
    )
    assert fact_id not in {c["fact_id"] for c in result["candidates"]}


def test_archive_skips_heavily_recalled_ephemeral_fact(tmp_path):
    # A fact recalled past max_retrieval_count is earning its keep no matter
    # how task-shaped its phrasing is (real-account examples sat at 100+).
    provider = _provider(tmp_path, durability_gate_enabled="false")
    store = provider._store
    fact_id = store.add_fact("User wants to just run a qg9 trial")
    store._conn.execute(
        "UPDATE facts SET retrieval_count = 239 WHERE fact_id = ?", (fact_id,)
    )
    store._conn.commit()
    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN
    )
    assert fact_id not in {c["fact_id"] for c in result["candidates"]}

    # Below the guard it archives as usual.
    store._conn.execute(
        "UPDATE facts SET retrieval_count = 3 WHERE fact_id = ?", (fact_id,)
    )
    store._conn.commit()
    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN
    )
    assert fact_id in {c["fact_id"] for c in result["candidates"]}


def test_archive_dry_run_does_not_write(tmp_path):
    provider = _provider(tmp_path, durability_gate_enabled="false")
    store = provider._store
    junk_id = store.add_fact("User wants to just run a qg8 trial")
    result = store.archive_ephemeral_facts(
        daily_maintenance_token=DAILY_MAINTENANCE_TOKEN, dry_run=True
    )
    assert result["dry_run"] is True
    assert junk_id in {c["fact_id"] for c in result["candidates"]}
    assert junk_id in {f["fact_id"] for f in _active_facts(provider)}


# ---------------------------------------------------------------------------
# Extraction-pass throttle
# ---------------------------------------------------------------------------

def test_relation_cap_limits_new_relations_per_pass(tmp_path):
    provider = _provider(tmp_path, dedup_enabled="false")
    store = provider._store
    store.begin_extraction_pass(relation_cap=1, minting_throttle=False)
    try:
        # Four capitalized entities -> C(4,2)=6 candidate relations.
        fact_id = store.add_fact(
            "Antonio Hub syncs Square Payments with Ghl Pipeline and Uppercuts Willowbrook"
        )
    finally:
        report = store.end_extraction_pass()
    assert report["relations_created"] == 1
    assert report["relations_skipped"] >= 1
    # Scope the row count to THIS fact (xdist workers share the embedded PG).
    row = store._conn.execute(
        "SELECT COUNT(*) AS n FROM memory_relations WHERE source_type = 'fact' AND source_id = ?",
        (fact_id,),
    ).fetchone()
    assert int(row["n"]) == 1


def test_minting_throttle_blocks_lowercase_prose_entities(tmp_path):
    provider = _provider(tmp_path, dedup_enabled="false")
    store = provider._store
    before = int(
        store._conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
    )
    store.begin_extraction_pass(relation_cap=40, minting_throttle=True)
    try:
        # Unique lowercase nonsense tokens so no other test's facts corroborate them.
        store.add_fact("the zorvex flumelet should miniaturise grobblets during transitflux")
    finally:
        report = store.end_extraction_pass()
    after = int(
        store._conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
    )
    assert after == before  # no lowercase prose entities minted
    assert report["entities_skipped"] >= 1


def test_minting_throttle_allows_proper_nouns_and_existing_entities(tmp_path):
    provider = _provider(tmp_path, dedup_enabled="false")
    store = provider._store
    # Outside a pass: lowercase entities mint normally (document path parity).
    store.add_fact("the workflow should always export to staging first")
    existing = {
        r["name"]
        for r in store._conn.execute("SELECT name FROM entities").fetchall()
    }
    store.begin_extraction_pass(relation_cap=40, minting_throttle=True)
    try:
        store.add_fact("Skyleigh Mccallum should always export to staging first")
    finally:
        store.end_extraction_pass()
    names = {
        r["name"]
        for r in store._conn.execute("SELECT name FROM entities").fetchall()
    }
    assert "Skyleigh Mccallum" in names  # proper noun minted inside the pass
    assert existing <= names             # existing entities untouched


def test_organize_pass_reports_throttle(tmp_path):
    provider = _provider(tmp_path, relation_pass_cap="2")
    provider.sync_turn(
        "Remember this: Antonio Hub syncs Square Payments with Uppercuts Willowbrook and Walnut Grove.",
        "Saved.",
        session_id="session-q",
    )
    result = provider._organize_journal(session_id="session-q")
    assert result["promoted"] >= 1
    assert result["throttle"]["relations_created"] <= 2


# ---------------------------------------------------------------------------
# memory_tool explicit-save warning
# ---------------------------------------------------------------------------

def test_memory_tool_warns_on_ephemeral_but_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    from tools.memory_tool import MemoryStore as FileMemoryStore

    store = FileMemoryStore()
    store.load_from_disk()
    result = store.add("memory", "User wants to just run a test")
    assert result["success"] is True
    assert "durability_warning" in result

    result2 = store.add(
        "memory",
        "CMA skill convention: leave-behind PDFs must be audited before delivery",
    )
    assert result2["success"] is True
    assert "durability_warning" not in result2
