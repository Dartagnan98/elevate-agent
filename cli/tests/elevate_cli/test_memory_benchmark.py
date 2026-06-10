"""Tests for elevate_cli/memory_benchmark.py — deterministic scoring, self-recall
math, history persistence, and the fake-store end-to-end path."""

import json

import pytest

from elevate_cli import memory_benchmark as mb


def _fact(fact_id: int, content: str, trust: float = 0.7, **extra) -> dict:
    row = {
        "fact_id": fact_id,
        "content": content,
        "category": extra.pop("category", "test"),
        "tags": extra.pop("tags", ""),
        "source_uri": extra.pop("source_uri", ""),
        "trust_score": trust,
    }
    row.update(extra)
    return row


def _distinct_facts(n: int = 30) -> list[dict]:
    """Facts whose contents have unique, rare tokens so self-recall is exact."""
    words = [
        "zephyr", "quasar", "obsidian", "marigold", "tundra", "krypton",
        "lagoon", "vortex", "saffron", "glacier", "nebula", "falcon",
        "ember", "willow", "cobalt", "monsoon", "orchid", "pylon",
        "raven", "sequoia", "topaz", "umbra", "viper", "walnut",
        "xylem", "yonder", "zircon", "anchor", "boreal", "cinder",
    ]
    return [
        _fact(i + 1, f"the {words[i % len(words)]}{i} detail number{i} for client{i} project")
        for i in range(n)
    ]


# ─── Query derivation determinism ────────────────────────────────────────────

class TestBuildSelfRecallQueries:
    def test_same_seed_same_queries(self):
        facts = _distinct_facts(30)
        a = mb.build_self_recall_queries(facts, sample_n=10, seed=7)
        b = mb.build_self_recall_queries(facts, sample_n=10, seed=7)
        assert a == b
        assert len(a) == 10

    def test_different_seed_different_sample(self):
        facts = _distinct_facts(30)
        a = mb.build_self_recall_queries(facts, sample_n=10, seed=7)
        b = mb.build_self_recall_queries(facts, sample_n=10, seed=8)
        assert [q["fact_id"] for q in a] != [q["fact_id"] for q in b]

    def test_fact_order_does_not_matter(self):
        facts = _distinct_facts(30)
        a = mb.build_self_recall_queries(facts, sample_n=10, seed=7)
        b = mb.build_self_recall_queries(list(reversed(facts)), sample_n=10, seed=7)
        assert a == b

    def test_stopword_only_and_idless_facts_skipped(self):
        facts = [
            {"fact_id": None, "content": "zephyr quasar obsidian"},
            _fact(1, "the and of to in"),
            _fact(2, "marigold tundra krypton lagoon"),
        ]
        queries = mb.build_self_recall_queries(facts, sample_n=10, seed=1)
        assert [q["fact_id"] for q in queries] == [2]

    def test_empty_store(self):
        assert mb.build_self_recall_queries([], sample_n=5, seed=1) == []


# ─── Scoring math ────────────────────────────────────────────────────────────

class TestEvaluateRecall:
    def test_self_recall_perfect_on_distinct_store(self):
        facts = _distinct_facts(30)
        result = mb.evaluate_recall(facts, limit=5, sample_n=10, seed=42)
        assert result["query_mode"] == "self_recall"
        assert result["query_count"] == 10
        assert result["recall_hit_rate"] == 1.0
        for row in result["queries"]:
            assert row["self_hit"] is True
            assert row["rank"] == 1
            assert row["source_fact_id"] in row["top_fact_ids"]

    def test_deterministic_given_seed(self):
        facts = _distinct_facts(30)
        a = mb.evaluate_recall(facts, limit=5, sample_n=10, seed=42)
        b = mb.evaluate_recall(facts, limit=5, sample_n=10, seed=42)
        strip = lambda r: {  # noqa: E731 — latency is the only nondeterministic part
            k: v for k, v in r.items() if k != "latency_ms"
        } | {"queries": [{k: v for k, v in q.items() if k != "latency_ms"} for q in r["queries"]]}
        assert strip(a) == strip(b)

    def test_miss_lowers_hit_rate(self):
        # One sampled fact's tokens are shadowed by k higher-trust near-copies,
        # pushing the source out of top-1 when k=1.
        facts = _distinct_facts(10)
        target = facts[0]
        shadow = _fact(999, target["content"], trust=0.99)
        result = mb.evaluate_recall(facts + [shadow], limit=1, sample_n=10, seed=42)
        assert result["recall_hit_rate"] is not None
        assert result["recall_hit_rate"] < 1.0

    def test_duplicate_injection_detected(self):
        facts = [
            _fact(1, "zephyr quasar obsidian marigold detail"),
            _fact(2, "zephyr quasar obsidian marigold detail"),  # near-identical pair
            _fact(3, "tundra krypton lagoon vortex saffron"),
        ]
        result = mb.evaluate_recall(facts, limit=5, queries=["zephyr quasar obsidian"])
        assert result["duplicate_injection_rate"] == 1.0
        assert result["queries"][0]["near_duplicate_pairs"] == 1

    def test_no_duplicates_zero_rate(self):
        result = mb.evaluate_recall(_distinct_facts(20), limit=5, sample_n=10, seed=3)
        assert result["duplicate_injection_rate"] == 0.0

    def test_explicit_queries_skip_self_recall(self):
        result = mb.evaluate_recall(_distinct_facts(10), limit=5, queries=["zephyr0 detail"])
        assert result["query_mode"] == "explicit"
        assert result["recall_hit_rate"] is None
        assert result["query_count"] == 1
        assert "source_fact_id" not in result["queries"][0]

    def test_injected_token_estimate_positive(self):
        result = mb.evaluate_recall(_distinct_facts(20), limit=5, sample_n=10, seed=3)
        est = result["injected_token_estimate"]
        assert est["total"] > 0
        assert est["mean_per_query"] > 0
        assert est["p95_per_query"] >= est["mean_per_query"] * 0.5

    def test_latency_keys_present(self):
        result = mb.evaluate_recall(_distinct_facts(5), limit=3, sample_n=5, seed=1)
        assert set(result["latency_ms"]) == {"median", "p95", "total"}


# ─── History persistence ─────────────────────────────────────────────────────

class TestHistory:
    def test_append_creates_and_accumulates(self, tmp_path):
        result = mb.evaluate_recall(_distinct_facts(10), limit=5, sample_n=5, seed=1)
        path = tmp_path / "memory" / "benchmark_history.jsonl"
        out1 = mb.record_benchmark_history(result, history_path=path)
        out2 = mb.record_benchmark_history(result, history_path=path)
        assert out1 == out2 == path
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        row = json.loads(lines[0])
        assert row["recall_hit_rate"] == result["recall_hit_rate"]
        # Per-query detail stays out of the telemetry file.
        assert "queries" not in row

    def test_default_path_under_account_dir(self):
        from elevate_constants import get_account_data_dir

        assert mb.default_history_path() == (
            get_account_data_dir() / "memory" / "benchmark_history.jsonl"
        )


# ─── End-to-end against a fake store (read-only contract) ────────────────────

class _FakeStore:
    def __init__(self, facts):
        self._facts = facts
        self.calls = []

    def list_facts(self, category=None, min_trust=0.0, limit=50):
        self.calls.append(("list_facts", min_trust, limit))
        return list(self._facts)


class TestRunBenchmark:
    def test_run_with_injected_store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mb, "post_benchmark_activity", lambda result: True)
        store = _FakeStore(_distinct_facts(20))
        path = tmp_path / "history.jsonl"
        result = mb.run_holographic_memory_benchmark(
            store=store, limit=5, sample_n=10, seed=42, record=True, history_path=path,
        )
        assert result["ran"] is True
        assert result["recall_hit_rate"] == 1.0
        assert result["activity_posted"] is True
        assert result["history_path"] == str(path)
        assert len(path.read_text().strip().splitlines()) == 1
        # Only the read path was exercised.
        assert all(call[0] == "list_facts" for call in store.calls)

    def test_run_without_record_writes_nothing(self, tmp_path):
        store = _FakeStore(_distinct_facts(5))
        path = tmp_path / "history.jsonl"
        result = mb.run_holographic_memory_benchmark(
            store=store, limit=5, sample_n=5, seed=1, record=False, history_path=path,
        )
        assert result["ran"] is True
        assert not path.exists()
        assert "activity_posted" not in result

    def test_summary_is_one_line(self):
        store = _FakeStore(_distinct_facts(5))
        result = mb.run_holographic_memory_benchmark(store=store, sample_n=5, seed=1)
        line = mb.summarize_benchmark(result)
        assert "\n" not in line
        assert "hit_rate" in line and "dup_rate" in line
