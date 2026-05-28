# Elevate Memory Upgrade Status

## Summary

Elevate's local `holographic` memory provider has been upgraded with a more complete recall pipeline. This was additive: Elevate already had SQLite facts, FTS5, embeddings, HRR/compositional recall, entity graph/wiki recall, trust feedback, layered recall, and turn journaling.

Changed files:

- `plugins/memory/holographic/store.py`
- `plugins/memory/holographic/retrieval.py`
- `plugins/memory/holographic/__init__.py`
- `plugins/memory/holographic/embeddings.py`
- `agent/context_compressor.py`
- `elevate_cli/memory_benchmark.py`
- `tests/plugins/memory/test_holographic_journal.py`
- `tests/agent/test_context_compressor.py`
- `docs/memory-upgrade-status.md`

## Implemented

### 1. Retrieval usage tracking

- Added `MemoryStore.record_retrieval_events()`.
- `FactRetriever.search/probe/related/reason/_score_facts_by_vector()` increments retrieval counts for surfaced facts.

### 2. Source-aware memory records

`facts` now supports provenance and scoping fields:

- `source_type`
- `source_uri`
- `source_excerpt`
- `observed_at`
- `memory_space`
- `status`
- `superseded_by`

`fact_store(action='add')` and `fact_store(action='update')` can write/update source and space fields.

### 3. Chunk-level document/Plaud RAG

New local RAG tables:

- `memory_documents`
- `memory_chunks`
- `memory_chunks_fts`

Actions:

- `document_add`
- `document_search`
- `import_plaud_archive`

Imported Plaud archive into local chunk recall:

- Documents: `114`
- Chunks: `3345`
- Source: `~/.elevate/imports/plaud-transcripts-chronological.jsonl`

Chunk search has FTS fallback, so it still works when semantic chunk embeddings are unavailable.

### 4. Recall router

Action:

- `recall_route`

Routes into lanes:

- `plaud` — meetings/calls/transcripts/chunks
- `ads` — campaign/ad memory
- `project` — code/files/skills/project chunks
- default — durable, recent, graph

### 5. Memory event ledger

New durable tables/logging:

- `memory_events`
- JSONL audit log under `~/.elevate/logs/memory-events-YYYY-MM-DD.jsonl`

Action:

- `memory_events`

Events now cover provider init, injections, retrieval maintenance, supersession, gaps, topic extraction, and replay/profile use.

### 6. Session injection dedupe + replay

New table:

- `memory_injections`

Actions:

- `memory_replay`
- `memory_profile`

Prefetch records injected fact/chunk IDs per session. The verifier avoids re-injecting the same fact repeatedly into the same session.

### 7. Cheap relevance verifier

Layered prefetch now runs deterministic verification before injection:

- token overlap
- retriever score
- trust score
- session dedupe

Rejected candidates are tracked for maintenance and gap logging.

### 8. Post-retrieval maintenance loop

New maintenance logic:

- verified facts get a small trust boost
- rejected/noisy facts get a tiny trust decay
- empty/low-confidence recall writes memory-gap records
- maintenance events are logged

The latest memory follow-up added the remaining lifecycle pieces:

- co-relevance clustering into `memory_clusters` and `memory_cluster_members`
- deterministic cluster naming from member facts
- inferred tags merged back into related facts
- explicit `confidence_maintenance` action for boost/decay/archive
- active low-confidence pruning archives facts instead of hard-deleting them

Actions:

- `cluster`
- `auto_tag`
- `confidence_maintenance`

### 9. Topic-change extraction

Topic extraction is opt-in with config flags:

- `topic_extraction_enabled`
- `topic_change_threshold`
- `topic_extract_min_turns`
- `periodic_extract_interval`

When enabled, topic shifts can trigger journal organization instead of waiting for fixed turn counts.

### 10. Memory profiler

Action:

- `memory_profile`

Reports active facts, documents, chunks, event count, injections, gap count, approximate injected token count, large chunk count, cluster count, cluster member count, and rough journal/injection token estimates.

### 10b. Context-limit auto-recovery hook

`agent/context_compressor.py` now has memory-pipeline context-limit recovery helpers:

- `ContextCompressor.is_context_limit_error(error)`
- `ContextCompressor.compact_for_retry(messages, error)`

This lets the agent compact immediately after provider context errors and retry the same turn instead of failing the session.

### 10c. Runtime log pruning

Action:

- `prune_logs`

Prunes old memory events/injections/gaps from SQLite with a retention window while preserving facts, documents, chunks, and supersession auditability.

### 10d. Benchmark harness

New local benchmark harness:

- `elevate_cli/memory_benchmark.py`
- `fact_store(action='benchmark')`

Reports query latency, hit counts, top fact IDs, total latency, and duplicate rate for quick recall-quality smoke checks.

Smoke run against the local memory DB:

```text
Instructor coaching -> 3 hits in 1.57ms, top_fact_ids [22, 35, 40]
Google Ads search campaigns -> 3 hits in 0.47ms, top_fact_ids [27, 28, 29]
duplicate_rate 0.0
```

### 11. Supersession / contradiction lifecycle

Action:

- `supersede`

Superseded facts are marked `status='superseded'` and linked to the replacement instead of hard-deleted. Retrieval, graph wiki, and fact listing exclude superseded facts by default.

### 12. Background prefetch cache

- `queue_prefetch()` builds a bounded background cache.
- `prefetch()` consumes the matching session/query cache.
- Falls back to live retrieval if the cache is missing or stale.

## Verification

Commands run:

```bash
python3 -m py_compile plugins/memory/holographic/store.py plugins/memory/holographic/retrieval.py plugins/memory/holographic/__init__.py
python3 -m py_compile plugins/memory/holographic/store.py plugins/memory/holographic/__init__.py agent/context_compressor.py elevate_cli/memory_benchmark.py
pytest -q tests/plugins/memory/test_holographic_journal.py tests/plugins/test_holographic_embeddings.py tests/agent/test_context_compressor.py
```

Latest result:

```text
74 passed, 11 warnings in 3.51s
```

Previous focused memory-only result:

```text
21 passed, 11 warnings in 1.17s
```

Live Plaud chunk import verification from earlier pass:

```text
documents 114
chunks 3345
plaud_docs 114
plaud_chunks 3345
```

## Current caveat

Resolved for Plaud chunks: clean batch backfill now loads env safely and indexed all existing Plaud chunks with OpenAI embeddings.

Latest verification:

```text
BEFORE indexed_chunks 0 / chunks 3345
RESULT indexed 3345, skipped 0, batch_size 64, provider openai, model text-embedding-3-small
AFTER indexed_chunks 3345 / chunks 3345, missing_or_stale_chunks 0
SECONDS 57.76
```

A new `chunk_embedding_backfill` action backs this:

```text
fact_store(action='chunk_embedding_backfill', source_type='plaud', batch_size=64)
```

Note: the current in-chat `fact_store` tool schema may not expose the new action until the gateway/tool schema reloads, but the local provider code and DB are updated and verified.

## Guardrails preserved

- No secrets printed.
- External business stores remain read-only.
- Raw transcripts are not placed into always-on memory.
- Plaud is retrieved through chunk RAG, not injected wholesale.
- Supersession demotes stale facts instead of deleting history.
