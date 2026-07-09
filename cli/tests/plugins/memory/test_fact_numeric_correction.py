"""C3 regression — a numeric/value correction ("$500k" → "$750k") must
supersede the old fact, not silently keep it while telling the agent it saved.
"""
from plugins.memory.holographic import HolographicMemoryProvider
from plugins.memory.holographic.store import _strip_value_tokens


def _provider(tmp_path):
    provider = HolographicMemoryProvider(config={
        "db_path": str(tmp_path / "memory.db"),
        "embedding_enabled": "false",
        "turn_journal_enabled": "false",
        "organize_on_session_end": "false",
        "organize_every_n_turns": "0",
    })
    provider.initialize("session-c3")
    return provider


def test_strip_value_tokens_detects_numeric_only_divergence():
    # Same shape, only the number differs → strip-equal (a correction).
    assert _strip_value_tokens("Client Jane budget is $500,000") == _strip_value_tokens(
        "Client Jane budget is $750,000"
    )
    assert _strip_value_tokens("budget is 500k") == _strip_value_tokens("budget is 750k")
    # Genuinely different content → NOT strip-equal (stays reinforcement).
    assert _strip_value_tokens("Jane likes red") != _strip_value_tokens("Jane likes blue")


def test_merge_supersedes_numeric_correction(tmp_path):
    # The near-dup DETECTION fires with embeddings on (semantic 0.92); this
    # tests the MERGE itself directly, which is where the value was dropped.
    provider = _provider(tmp_path)
    store = provider._store
    store.add_fact("Client Jane max budget is 500000", category="client", explicit=True)
    existing = dict(
        store._read_all(
            "SELECT fact_id, content, tags FROM facts WHERE content LIKE '%500000%'"
        )[0]
    )

    store._merge_duplicate_fact(existing, "Client Jane max budget is 750000")

    updated = store._read_all(
        "SELECT content FROM facts WHERE fact_id = ?", (existing["fact_id"],)
    )[0]["content"]
    assert "750000" in updated, "numeric correction must supersede the old value"
    assert "500000" not in updated, "the stale value must not survive the merge"


def test_merge_keeps_old_on_genuine_non_numeric_diff(tmp_path):
    # A non-numeric near-dup that isn't strictly more specific stays as
    # reinforcement (old content kept) — we only supersede numeric corrections.
    provider = _provider(tmp_path)
    store = provider._store
    store.add_fact("Jane prefers red listings", category="client", explicit=True)
    existing = dict(
        store._read_all("SELECT fact_id, content, tags FROM facts WHERE content LIKE '%red%'")[0]
    )
    store._merge_duplicate_fact(existing, "Jane prefers red homes")  # shorter/same, non-numeric
    updated = store._read_all(
        "SELECT content FROM facts WHERE fact_id = ?", (existing["fact_id"],)
    )[0]["content"]
    assert updated == "Jane prefers red listings", "non-numeric near-dup should not supersede"
