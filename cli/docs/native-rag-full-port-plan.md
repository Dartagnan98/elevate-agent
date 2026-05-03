# Native Elevate RAG Full Port Plan

Goal: port the useful LightRAG and RAG-Anything architecture into Elevate's existing holographic memory layer without adding Graphify, Mem0, or an external LightRAG runtime dependency.

## Reference repos inspected

- HKUDS/LightRAG — MIT License.
- HKUDS/RAG-Anything — MIT License.

The licenses allow reuse, but Elevate should not vendor the full apps blindly. Elevate already has state, tools, gateway, memory, facts, documents, chunks, embeddings, journal, and entity graph. The right move is to port the RAG layers into those primitives.

## Layers to port

### 1. Query engine

LightRAG pattern:
- `kg_query()` routes local/global/hybrid/mix modes.
- Extract high-level and low-level keywords.
- Build query context through four stages:
  1. search
  2. token truncation
  3. merge chunks
  4. build final context + raw metadata
- Return context, prompt, generated answer, streaming result, and raw citations depending on query params.

Elevate port:
- Expand `fact_store(action='rag_query')` into a full native query engine.
- Modes:
  - `naive`: document/chunk search only.
  - `local`: entity/fact/neighborhood recall.
  - `global`: community/cluster summaries.
  - `hybrid`: local + global.
  - `mix`: local + global + chunks + recent turns.
- Add high/low keyword extraction.
- Add token-budgeted context packing.
- Add raw_data metadata with facts/chunks/entities/relations/communities/citations.

### 2. Community/global memory

LightRAG has graph/community-oriented global retrieval and visualization support.

Elevate already has:
- `memory_clusters`
- `memory_cluster_members`
- co-recall clustering
- cluster maintenance

Elevate port:
- Add durable community reports over clusters.
- Store summary, top entities, top facts, top chunks, tags, source IDs, confidence, updated_at.
- Use community reports as first-class `global` RAG context.

### 3. Entity/relation graph ingestion

LightRAG pattern:
- extract entities and relationships from content
- merge nodes and edges
- query entities/relations separately
- merge graph evidence with chunks

Elevate port:
- Extend document ingestion to extract entities and relation candidates from every chunk.
- Link chunks to entities.
- Add explicit `memory_relations` if current fact co-entity links are not enough.
- Merge fact/document/turn entities into one native graph.

### 4. Rerank and context packing

LightRAG pattern:
- rerank retrieved chunks/entities/relations
- apply max entity/relation/total token budgets
- merge chunks after graph filtering

Elevate port:
- Deterministic rerank first: keyword overlap + semantic score + trust + recency + source quality + graph proximity.
- Optional model rerank later if configured.
- Pack final context under token budget with citations.

### 5. Multimodal/document ingestion

RAG-Anything pattern:
- parser pipeline
- context extractor by page/chunk/token
- image/table/equation/generic modal processors
- VLM-enhanced query path when vision model exists

Elevate port:
- Add generic document parse hooks for PDF/image/table/screenshot metadata.
- Store modality type and surrounding page/chunk context in `memory_documents` / `memory_chunks` metadata.
- For images/tables/equations: generate text captions/summaries when a vision/model tool is available, then index into chunks.
- Keep raw files referenced by source URI/path, not copied into memory.

### 6. Caching/observability

LightRAG/RAG-Anything pattern:
- query cache keys
- callback hooks
- raw_data metadata

Elevate port:
- Use existing memory events and injection logs.
- Add RAG query event records.
- Add cache keys for repeated RAG queries if needed.
- Expand benchmark to include mode coverage and duplicate/context quality metrics.

## Implementation order

1. Community reports/global mode.
2. Entity/relation chunk ingestion.
3. Query engine search/truncate/merge/context stages.
4. Rerank and token-budget packing.
5. Multimodal parse hooks.
6. Tests + benchmark + gateway reload + live real-memory smoke.
7. Hub import: expose the native RAG memory graph in the Agent Hub snapshot, not just old fact/entity links.

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
- Do not expose secrets in logs, docs, or tests.
- Reuse Elevate's existing SQLite state and memory abstractions.
- Preserve current `fact_store` actions and backwards compatibility.
