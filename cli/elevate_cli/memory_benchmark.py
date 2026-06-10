"""Benchmark harness for Elevate holographic memory recall.

This is intentionally local and READ-ONLY. It exercises the same store used by
fact_store so we can measure recall quality, duplicate-injection risk, and
latency without mutating ads or external business systems.

What it produces (one JSON-safe score dict per run):

- ``recall_hit_rate``  — self-recall over a deterministic query set derived
  from the account's own facts: sample N facts (seeded), build a query from
  each fact's rarest content tokens, and check whether local recall returns
  the source fact in the top-k.
- ``duplicate_injection_rate`` — fraction of queries whose top-k contains at
  least one near-identical pair (token-Jaccard >= 0.9).
- ``latency_ms`` — median / p95 / total recall latency across queries.
- ``injected_token_estimate`` — rough tokens (len/4) a top-k prefetch would
  add to a prompt (mean / p95 per query + total).
- ``store`` — facts / entities / relations counts.

Runs are comparable: given the same seed and store contents, the query set
and all quality metrics are deterministic (only latency varies).

History: each recorded run appends one JSON line to
``<account_data_dir>/memory/benchmark_history.jsonl`` and posts a one-line
``memory_benchmark`` activity event so regressions are visible on the bus.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_SCHEMA_VERSION = 1
DEFAULT_SEED = 1337
DEFAULT_SAMPLE_N = 20
DEFAULT_TOP_K = 5
QUERY_TOKENS = 4
NEAR_DUP_JACCARD = 0.9
_FACT_FETCH_LIMIT = 10000

# Tokens too generic to identify a fact — never used to build a self-recall query.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have he her his i if in into is
    it its me my no not of on or our she so that the their them they this to up
    us was we were what when which who will with you your""".split()
)


# ─── Tokenizing / scoring helpers (pure, deterministic) ──────────────────────

def _tokenize(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _fact_text(fact: dict) -> str:
    return " ".join(str(fact.get(k) or "") for k in ("content", "tags", "category", "source_uri"))


def _estimate_tokens(text: str) -> int:
    """Cheap chars/4 token estimate — same heuristic the harness uses elsewhere."""
    text = str(text or "")
    return math.ceil(len(text) / 4) if text else 0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, math.ceil(pct * len(ordered)) - 1)
    return float(ordered[idx])


def build_self_recall_queries(
    facts: list[dict],
    *,
    sample_n: int = DEFAULT_SAMPLE_N,
    seed: int = DEFAULT_SEED,
    tokens_per_query: int = QUERY_TOKENS,
) -> list[dict]:
    """Build a deterministic self-recall query set from the store's own facts.

    Sample ``sample_n`` facts (seeded RNG over facts sorted by fact_id), then
    for each build a query from its rarest non-stopword content tokens (lowest
    document frequency across the store first — those are the tokens recall
    should be able to key on). Returns ``[{"query", "fact_id"}, ...]``.
    """
    eligible: list[tuple[int, list[str]]] = []
    for fact in facts:
        fid = fact.get("fact_id")
        if fid is None:
            continue
        tokens = [t for t in _tokenize(fact.get("content")) if t not in _STOPWORDS and len(t) > 2]
        if tokens:
            eligible.append((int(fid), tokens))
    eligible.sort(key=lambda item: item[0])
    if not eligible:
        return []

    # Document frequency over eligible facts (unique tokens per fact).
    df: dict[str, int] = {}
    for _, tokens in eligible:
        for tok in set(tokens):
            df[tok] = df.get(tok, 0) + 1

    rng = random.Random(int(seed))
    count = min(max(1, int(sample_n)), len(eligible))
    sampled = rng.sample(eligible, count)
    sampled.sort(key=lambda item: item[0])

    queries: list[dict] = []
    for fid, tokens in sampled:
        # Dedupe preserving first-appearance order, then take the rarest.
        seen: set[str] = set()
        ordered: list[tuple[int, int, str]] = []
        for idx, tok in enumerate(tokens):
            if tok in seen:
                continue
            seen.add(tok)
            ordered.append((df.get(tok, 1), idx, tok))
        ordered.sort()
        chosen = [tok for _, _, tok in ordered[: max(1, int(tokens_per_query))]]
        queries.append({"query": " ".join(chosen), "fact_id": fid})
    return queries


def _rank_facts(prepared: list[tuple[set, dict]], query: str, limit: int) -> list[dict]:
    """Local recall ranker: token overlap + trust, fact_id tie-break.

    Mirrors the store-side benchmark ranker but is fully deterministic and
    avoids external embedding calls. ``prepared`` is [(token_set, fact)].
    """
    q_tokens = set(_tokenize(query))
    scored: list[tuple[float, int, dict]] = []
    for tokens, fact in prepared:
        overlap = len(q_tokens & tokens)
        if not overlap:
            continue
        score = overlap + float(fact.get("trust_score") or 0.0)
        scored.append((-score, int(fact.get("fact_id") or 0), fact))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [fact for _, _, fact in scored[: max(1, int(limit))]]


def _near_duplicate_pairs(hits: list[dict], threshold: float = NEAR_DUP_JACCARD) -> int:
    """Count near-identical pairs (content token-Jaccard >= threshold) in top-k."""
    token_sets = [set(_tokenize(h.get("content"))) for h in hits]
    pairs = 0
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a, b = token_sets[i], token_sets[j]
            if not a or not b:
                continue
            union = len(a | b)
            if union and len(a & b) / union >= threshold:
                pairs += 1
    return pairs


# ─── Scoring core (pure given a fact list) ───────────────────────────────────

def evaluate_recall(
    facts: list[dict],
    *,
    limit: int = DEFAULT_TOP_K,
    sample_n: int = DEFAULT_SAMPLE_N,
    seed: int = DEFAULT_SEED,
    queries: list[str] | None = None,
) -> dict[str, Any]:
    """Score recall over ``facts``. Deterministic given (facts, seed, limit).

    When ``queries`` is None a self-recall set is derived from the facts and
    ``recall_hit_rate`` is computed; explicit queries skip self-recall (rate
    is None) but still measure duplicates / latency / injected tokens.
    """
    limit = max(1, int(limit))
    explicit = [str(q).strip() for q in (queries or []) if str(q).strip()]
    if explicit:
        specs = [{"query": q, "fact_id": None} for q in explicit]
    else:
        specs = build_self_recall_queries(facts, sample_n=sample_n, seed=seed)

    prepared = [(set(_tokenize(_fact_text(f))), f) for f in facts]

    rows: list[dict] = []
    latencies: list[float] = []
    injected: list[int] = []
    self_total = self_hits = 0
    dup_queries = 0
    seen_fact_ids: list[int] = []
    started = time.time()
    for spec in specs:
        q_start = time.time()
        hits = _rank_facts(prepared, spec["query"], limit)
        latency = (time.time() - q_start) * 1000
        latencies.append(latency)

        hit_ids = [int(h.get("fact_id") or 0) for h in hits]
        seen_fact_ids.extend(hit_ids)
        tokens = sum(_estimate_tokens(str(h.get("content") or "")) for h in hits)
        injected.append(tokens)
        dup_pairs = _near_duplicate_pairs(hits)
        if dup_pairs:
            dup_queries += 1

        row: dict[str, Any] = {
            "query": spec["query"],
            "hits": len(hits),
            "top_fact_ids": hit_ids,
            "latency_ms": round(latency, 2),
            "injected_tokens": tokens,
            "near_duplicate_pairs": dup_pairs,
        }
        if spec.get("fact_id") is not None:
            self_total += 1
            source_id = int(spec["fact_id"])
            row["source_fact_id"] = source_id
            row["self_hit"] = source_id in hit_ids
            row["rank"] = (hit_ids.index(source_id) + 1) if source_id in hit_ids else None
            if row["self_hit"]:
                self_hits += 1
        rows.append(row)

    query_count = len(specs)
    repeat_rate = 0.0
    if seen_fact_ids:
        repeat_rate = 1.0 - (len(set(seen_fact_ids)) / len(seen_fact_ids))
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "seed": int(seed),
        "k": limit,
        "sample_n": int(sample_n),
        "query_count": query_count,
        "query_mode": "explicit" if explicit else "self_recall",
        "recall_hit_rate": round(self_hits / self_total, 4) if self_total else None,
        "duplicate_injection_rate": round(dup_queries / query_count, 4) if query_count else 0.0,
        "repeat_fact_rate": round(repeat_rate, 4),
        "latency_ms": {
            "median": round(_percentile(latencies, 0.5), 2),
            "p95": round(_percentile(latencies, 0.95), 2),
            "total": round((time.time() - started) * 1000, 2),
        },
        "injected_token_estimate": {
            "mean_per_query": round(sum(injected) / query_count, 1) if query_count else 0.0,
            "p95_per_query": int(_percentile([float(x) for x in injected], 0.95)),
            "total": int(sum(injected)),
        },
        "queries": rows,
    }


# ─── Store wiring ────────────────────────────────────────────────────────────

def _store_size_stats(store: Any) -> dict[str, Any]:
    """Read-only counts of facts/entities/relations. Best-effort per table."""
    stats: dict[str, Any] = {}
    conn = getattr(store, "_conn", None)
    if conn is None:
        return stats
    counts = {
        "facts_active": "SELECT COUNT(*) AS n FROM facts WHERE COALESCE(status, 'active') = 'active'",
        "facts_total": "SELECT COUNT(*) AS n FROM facts",
        "entities": "SELECT COUNT(*) AS n FROM entities",
        "relations": "SELECT COUNT(*) AS n FROM memory_relations",
    }
    for key, sql in counts.items():
        try:
            row = conn.execute(sql).fetchone()
            if row is None:
                continue
            try:
                stats[key] = int(row["n"])
            except (TypeError, KeyError, IndexError):
                stats[key] = int(row[0])
        except Exception:
            continue
    return stats


def run_holographic_memory_benchmark(
    *,
    config: dict | None = None,
    queries: list[str] | None = None,
    limit: int = DEFAULT_TOP_K,
    sample_n: int = DEFAULT_SAMPLE_N,
    seed: int = DEFAULT_SEED,
    record: bool = False,
    history_path: Path | str | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Run the local holographic memory benchmark and return JSON-safe stats.

    READ-ONLY against the store. ``record=True`` additionally appends the
    score to the per-account history JSONL and posts a one-line activity
    event. ``store`` lets tests inject a fake store (must expose
    ``list_facts(min_trust=..., limit=...)``).
    """
    provider = None
    if store is None:
        if isinstance(config, dict):
            runtime_config = config
        else:
            try:
                from elevate_cli.config import load_config

                loaded = load_config()
                runtime_config = loaded if isinstance(loaded, dict) else {}
            except Exception:
                runtime_config = {}
        plugins = runtime_config.get("plugins") if isinstance(runtime_config, dict) else {}
        plugin_config = {}
        if isinstance(plugins, dict):
            plugin_config = plugins.get("elevate-memory-store") or {}
        if not isinstance(plugin_config, dict):
            plugin_config = {}
        plugin_config = dict(plugin_config)
        if not plugin_config.get("db_path"):
            plugin_config["db_path"] = "~/.elevate/memory_store.db"

        from plugins.memory.holographic import HolographicMemoryProvider

        provider = HolographicMemoryProvider(config=plugin_config)
        provider.initialize("memory-benchmark")
        store = provider._store
    try:
        facts = store.list_facts(min_trust=0.0, limit=_FACT_FETCH_LIMIT)
        result = evaluate_recall(facts, limit=limit, sample_n=sample_n, seed=seed, queries=queries)
        result["store"] = _store_size_stats(store)
        result["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        result["ran"] = True
        if record:
            try:
                path = record_benchmark_history(result, history_path=history_path)
                result["history_path"] = str(path)
            except Exception as exc:
                result["history_error"] = str(exc)
            result["activity_posted"] = post_benchmark_activity(result)
        return result
    finally:
        if provider is not None:
            provider.shutdown()


# ─── History + activity telemetry ────────────────────────────────────────────

def default_history_path() -> Path:
    from elevate_constants import get_account_data_dir

    return get_account_data_dir() / "memory" / "benchmark_history.jsonl"


def record_benchmark_history(result: dict, *, history_path: Path | str | None = None) -> Path:
    """Append one summary JSON line (per-query rows dropped) to the history file."""
    path = Path(history_path) if history_path else default_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {k: v for k, v in result.items() if k != "queries"}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, default=str) + "\n")
    return path


def summarize_benchmark(result: dict) -> str:
    """One-line human summary used for the activity event and CLI output."""
    hit = result.get("recall_hit_rate")
    hit_s = f"{hit:.0%}" if isinstance(hit, (int, float)) else "n/a"
    latency = result.get("latency_ms") or {}
    tokens = result.get("injected_token_estimate") or {}
    store = result.get("store") or {}
    return (
        f"memory benchmark: hit_rate {hit_s}, "
        f"dup_rate {float(result.get('duplicate_injection_rate') or 0):.0%}, "
        f"latency p50/p95 {latency.get('median', 0)}/{latency.get('p95', 0)}ms, "
        f"~{tokens.get('mean_per_query', 0)} tok/query, "
        f"{store.get('facts_active', '?')} facts / {store.get('entities', '?')} entities / "
        f"{store.get('relations', '?')} relations"
    )


def post_benchmark_activity(result: dict) -> bool:
    """Post the one-line score to the agent bus activity stream. Best-effort."""
    try:
        from elevate_cli.data import connect, surface_state

        metadata = {k: v for k, v in result.items() if k != "queries"}
        with connect() as conn:
            surface_state.append_activity(
                conn,
                "system",
                "memory_benchmark",
                message=summarize_benchmark(result),
                metadata=metadata,
            )
        return True
    except Exception:
        return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run Elevate holographic memory benchmark")
    parser.add_argument(
        "queries", nargs="*",
        help="Explicit queries to benchmark. Default: deterministic self-recall set from the store's own facts.",
    )
    parser.add_argument("--limit", "-k", type=int, default=DEFAULT_TOP_K, help="Top-k recall depth")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE_N, help="Self-recall facts to sample")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (same seed = same query set)")
    parser.add_argument("--no-record", action="store_true", help="Skip history append + activity event")
    args = parser.parse_args()
    result = run_holographic_memory_benchmark(
        queries=args.queries,
        limit=args.limit,
        sample_n=args.sample,
        seed=args.seed,
        record=not args.no_record,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
