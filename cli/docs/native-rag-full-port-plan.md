# Native Elevate RAG Full Port Plan

Goal: port the useful LightRAG and RAG-Anything architecture into Elevate's existing holographic memory layer without adding Graphify, Mem0, or an external LightRAG/RAG-Anything runtime dependency.

## Reference repos inspected

- HKUDS/LightRAG — MIT License.
- HKUDS/RAG-Anything — MIT License.

The licenses allow reuse, but Elevate should not vendor the full apps blindly. Elevate already has state, tools, gateway, memory, facts, documents, chunks, embeddings, journal, and entity graph. The right move is to port the RAG layers into those primitives.

## Layers ported

### 1. Query engine

LightRAG pattern:
- `kg_query()` routes local/global/hybrid/mix modes.
- Query params include `mode`, `only_need_context`, `only_need_prompt`, `response_type`, `conversation_history`, top-k/budget controls, and bypass mode.
- Extract high-level and low-level keywords.
- Build query context through four stages:
  1. search
  2. budget/truncation
  3. merge/dedupe chunks and graph evidence
  4. build final context + prompt + raw metadata
- Return context, prompt, generated answer, streaming result, and raw citations depending on query params.

Elevate port:
- `fact_store(action='rag_query')` is the native query engine.
- Modes:
  - `naive`: document/chunk search only.
  - `local`: entity/fact/neighborhood recall.
  - `global`: community/cluster summaries.
  - `hybrid`: local + global.
  - `mix`: local + global + chunks + recent turns.
  - `bypass`: no retrieval; returns a prompt shell when requested.
- Deterministic high/low keyword extraction is returned in `keywords` and `raw_data.keywords`.
- Token-budgeted context packing is handled by `_pack_rag_sections(...)`.
- `only_need_context` returns packed evidence context.
- `only_need_prompt` returns a LightRAG-style answer prompt built from context, optional `conversation_history`, and `response_type`.
- `raw_data` includes sections, score breakdown, citations, budget metadata, result counts, and latency telemetry.

### 2. Community/global memory

LightRAG has graph/community-oriented global retrieval and visualization support.

Elevate already has:
- `memory_clusters`
- `memory_cluster_members`
- co-recall clustering
- cluster maintenance

Elevate port:
- Durable community reports are stored over clusters.
- Reports store summary, top entities, supporting fact/chunk IDs, tags, source IDs, weight, and timestamps.
- `rag_query mode='global'` uses community reports as first-class context.

### 3. Entity/relation graph ingestion

LightRAG pattern:
- extract entities and relationships from content
- merge nodes and edges
- query entities/relations separately
- merge graph evidence with chunks

Elevate port:
- Document ingestion extracts entity links from every chunk.
- Chunks are linked to entities via `memory_chunk_entities`.
- Fact/chunk co-occurrence edges are stored in `memory_relations`.
- `relation_backfill` reprocesses existing facts/chunks so old Plaud/document imports populate the native graph.
- `graph_reprocess` canonicalizes duplicate entities, classifies generic nodes into business/realtor-aware types, retypes generic co-occurrence edges into typed relations, prunes weak/noisy edges, and records a before/after report.
- Fact/document entities are merged into one native graph surfaced by `wiki`, `rag_query`, and Hub.

### 4. Rerank and context packing

LightRAG pattern:
- rerank retrieved chunks/entities/relations
- apply max entity/relation/total token budgets
- merge chunks after graph filtering

Elevate port:
- Deterministic rerank uses query-token overlap plus existing retriever/semantic/trust scores.
- Document search diversifies results by document so one Plaud transcript does not crowd out the whole answer.
- `_pack_rag_sections(...)` dedupes and packs multimodal query inputs, communities, facts, chunks, recent turns, and graph pages under the requested character budget.
- Optional model rerank can be added later if configured, but the production path does not require a second model call.

### 5. Multimodal/document ingestion and query

RAG-Anything pattern:
- parser pipeline
- context extractor by page/chunk/token
- image/table/equation/generic modal processors
- direct multimodal content insertion
- VLM-enhanced query path when vision model exists

Elevate port:
- `document_add` accepts `modal_assets` / `assets` for parsed PDF/image/table/equation/page artifacts.
- `memory_modal_assets` stores modality type, locator, summary, text content, and metadata.
- Modal assets with text/captions are converted into searchable chunks.
- `rag_query` accepts `modal_assets` or `multimodal_content`, normalizes images/tables/equations into text-backed query evidence, includes those assets in context, and augments retrieval with their captions/body/equation text.
- Raw files are referenced by source URI/path, not copied into memory.
- Full OCR/VLM parsing remains tool-facing: callers can pass parsed/captioned assets from OCR/vision pipelines without adding a RAG-Anything runtime dependency.

### 6. Document operations/status

LightRAG pattern:
- track document processing status
- list/index documents
- delete by document/source

Elevate port:
- `document_status` returns document counts, chunk counts, indexed chunk counts, modal asset counts, and processed/indexing status.
- `document_delete` removes a document plus chunks, chunk embeddings, modal assets, and native graph relations.

### 7. Caching/observability

LightRAG/RAG-Anything pattern:
- query cache keys
- callback hooks
- raw_data metadata

Elevate port:
- Existing memory events and injection logs remain the source of truth.
- RAG queries record `memory.rag_query.complete` with mode, counts, latency, citation count, context chars, source type, and budget.
- `raw_data.telemetry` returns the same information to callers for Hub/debugging.
- Benchmarks cover hit counts, duplicate rate, and smoke queries.

## Implementation order/status

1. Community reports/global mode — done.
2. Entity/relation chunk ingestion — done.
3. Query engine search/truncate/merge/context stages — done.
4. Rerank and token-budget packing — done.
5. Multimodal parse hooks — done as native `modal_assets` ingestion and `multimodal_content` query hooks.
6. LightRAG query-param parity — done for `mode`, `bypass`, `only_need_context`, `only_need_prompt`, `response_type`, and `conversation_history`.
7. Document status/delete operations — done.
8. Tests + benchmark + gateway/live smoke — local tests/benchmarks done; live tool path verified for `rag_query`; gateway reload still required after schema changes in deployments.
9. Hub import: expose the native RAG memory graph in the Agent Hub snapshot, not just old fact/entity links — done.
10. Existing-data processing: run `relation_backfill` against Plaud/document chunks so old imports get graph edges — done for local store.
11. Graph reprocessing: run `graph_reprocess` to canonicalize/merge entity nodes, classify node types, convert generic co-occurrence edges into typed business relations, and produce an auditable before/after report — done for local store.

## Hub graph status

The Agent Hub memory graph now reads the native RAG/memory graph primitives from the local SQLite store:

- facts and entities
- documents and chunks
- chunk/entity links
- community reports / global RAG summaries
- explicit entity relations
- multimodal asset placeholders

The Hub summary also exposes counts for documents, chunks, indexed chunks, community reports, relations, and modal assets. The visual graph remains bounded for dashboard performance.

## Guardrails

- No Graphify dependency.
- No Mem0 dependency.
- No external LightRAG service dependency.
- No external RAG-Anything runtime dependency.
- Do not expose secrets in logs, docs, or tests.
- Reuse Elevate's existing SQLite state and memory abstractions.
- Preserve current `fact_store` actions and backwards compatibility.
