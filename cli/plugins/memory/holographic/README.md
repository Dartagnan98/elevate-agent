# Holographic Memory Provider

Local SQLite fact store with FTS5 search, optional semantic embeddings, trust
scoring, entity resolution, and HRR-based compositional retrieval.

Elevate Memory Core uses one provider with internal lanes:

- Recent session: short recall from the local turn journal, scoped by session/day.
- Durable facts: recurring preferences, project decisions, and stable facts.
- Semantic recall: embedding-assisted search over promoted durable facts.
- Graph wiki: entity pages and backlinks rendered as `[[Entity]]` links.

## Requirements

None for the local store — uses Python's built-in SQLite. NumPy is optional for
HRR algebra.

Semantic embeddings are optional:

- OpenAI uses the core `openai` dependency already installed with Elevate.
- Ollama uses a local HTTP server such as `mxbai-embed-large`.
- OpenAI-compatible endpoints can be configured with a custom base URL.

## Setup

```bash
elevate memory setup    # select "holographic"
```

Or manually:
```bash
elevate config set memory.provider holographic
```

## Config

Config in `config.yaml` under `plugins.elevate-memory-store`:

| Key | Default | Description |
|-----|---------|-------------|
| `db_path` | `$ELEVATE_HOME/memory_store.db` | SQLite database path |
| `auto_extract` | `false` | Auto-extract facts at session end |
| `turn_journal_enabled` | `true` | Record completed turns locally for later memory organization |
| `organize_on_session_end` | `true` | Organize pending turn-journal entries when a session ends |
| `organize_every_n_turns` | `0` | Also organize pending journal entries every N turns; `0` disables periodic organization |
| `daily_organize_enabled` | `true` | Gateway runs a local day-end journal organization pass even when sessions stay open |
| `daily_organize_hour` | `23` | Local hour for the day-end organization pass |
| `daily_organize_minute` | `55` | Local minute for the day-end organization pass |
| `daily_organize_max_batches` | `50` | Max organization batches in one daily pass |
| `turn_journal_max_chars` | `8000` | Max characters saved per user/assistant side of a turn |
| `organize_batch_limit` | `20` | Max pending turns to organize in one pass |
| `layered_prefetch_enabled` | `true` | Inject recent/durable/graph lanes instead of one flat memory list |
| `recent_recall_enabled` | `true` | Include recent same-session journal recall |
| `graph_recall_enabled` | `true` | Include wiki-style entity graph recall |
| `recent_recall_limit` | `4` | Max recent turns in memory prefetch |
| `durable_recall_limit` | `4` | Max durable facts in memory prefetch |
| `graph_recall_limit` | `2` | Max entity wiki pages in memory prefetch |
| `recent_turn_max_chars` | `240` | Max characters per recent turn in prefetch |
| `default_trust` | `0.5` | Default trust score for new facts |
| `hrr_dim` | `1024` | HRR vector dimensions |
| `embedding_enabled` | `false` | Enable semantic embeddings |
| `embedding_provider` | `openai` | `openai`, `ollama`, `openai_compatible`, or optional `local_minilm` |
| `embedding_model` | `text-embedding-3-small` | Provider model name |
| `embedding_dimensions` | empty | Optional dimensions override |
| `embedding_base_url` | empty | Provider base URL for Ollama/custom endpoints |
| `embedding_api_key_env` | `OPENAI_API_KEY` | Environment variable for cloud provider key |
| `embedding_cache_dir` | empty | Optional model cache folder for `local_minilm` |

Example:

```yaml
memory:
  provider: holographic
plugins:
  elevate-memory-store:
    embedding_enabled: true
    embedding_provider: openai
    embedding_model: text-embedding-3-small
    embedding_api_key_env: OPENAI_API_KEY
    turn_journal_enabled: true
    organize_on_session_end: true
    organize_every_n_turns: 6
    daily_organize_enabled: true
    daily_organize_hour: 23
    daily_organize_minute: 55
    layered_prefetch_enabled: true
    recent_recall_limit: 4
    durable_recall_limit: 4
    graph_recall_limit: 2
```

`local_minilm` uses `sentence-transformers/all-MiniLM-L6-v2` locally with
384-dimensional vectors. It is opt-in and requires the optional
`sentence-transformers` package; Elevate will not download this model during a
normal install unless the user explicitly selects that provider.

## Tools

| Tool | Description |
|------|-------------|
| `fact_store` | add, search, probe, related, reason, contradict, embedding_status, embedding_backfill, journal_status, organize_journal, recent, wiki, layered_recall, update, remove, list |
| `fact_feedback` | Rate facts as helpful/unhelpful (trains trust scores) |

`journal_status` reports global counts plus `active_session_count`,
`session_segment_count`, and per-session/day rows. A long-running session that
continues after midnight keeps the same `session_id` but appears as a new
`session_day` segment.

`layered_recall` returns the same memory surface used by automatic prefetch:
`Recent Session`, `Durable + Semantic`, and `Graph Wiki`.

The gateway also checks `elevate memory daily` in-process. That command drains
pending journal batches once per local day, so sessions that never end still
get organized without spending model tokens on a scheduled prompt.
