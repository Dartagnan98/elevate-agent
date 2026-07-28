# Agent attribution for Elevate usage + storage

## Goal

Start attributing Elevate resource usage to the agent that caused it, so we can answer questions like:

- Which agent is using tokens/cost?
- Which agent triggered a cron/gateway run?
- Which agent owns generated artifacts, temp files, logs, and cache growth?
- What can be cleaned up safely without touching live operational state?

This starts from the current disk-usage finding: Elevate-related files take ~15.8 GiB, with major buckets in `~/.elevate`, `~/.hermes`, the `~/elevate` repo, the Electron app, and stale diagnostic/worktree folders.

## Current context

Relevant existing code:

- `cli/elevate_cli/data/migrations_pg/0004_usage_ledger.sql`
  - Postgres-backed `turn_usage` table.
  - Already records source, session, model, tokens, tool profile, cost, latency, status.
  - Does **not** yet include a first-class `agent_id` column.

- `cli/elevate_cli/data/usage_ledger.py`
  - Inserts and reads `turn_usage` rows.
  - `_INSERT_COLUMNS` needs to be extended when schema changes.

- `cli/gateway/usage_ledger.py`
  - Builds metadata-only usage rows.
  - Safe pattern: no prompt/response/tool arguments/secrets.
  - Right place to normalize/capture `agent_id`.

- `cli/gateway/run.py`
  - Calls `record_gateway_turn(...)` around lines ~7028 and ~7328.
  - Already has `source`, `session_key`, `event.message_id`, `session_entry.session_id`.
  - `_parse_session_key(...)` already extracts `agent_id` from agent-scoped session keys.
  - `_source_delivery_metadata(...)` already reads `source.agent_id` into metadata for delivery.

- `cli/gateway/guardrails.py`
  - Uses usage ledger for token caps.
  - Needs compatibility if attribution filters are added later.

Potential reporting surface:

- CLI `/insights` / `elevate insights`
- Dashboard analytics panel later
- A small helper command/script first is fine for dogfooding

## Proposed approach

Do this in two layers:

1. **Run attribution** — first-class `agent_id` on usage ledger rows.
2. **Storage attribution** — periodic scanner that attributes disk growth to agent/session/job where possible, and marks the rest as shared/runtime/unknown.

Do not try to perfectly attribute every byte on day one. Start with reliable attribution for gateway/cron/subagent turns, then layer in storage ownership.

## Phase 1 — Usage ledger agent attribution

### 1. Schema migration

Add a new Postgres migration after `0004_usage_ledger.sql`, likely:

- `cli/elevate_cli/data/migrations_pg/0005_turn_usage_agent_id.sql`

Changes:

```sql
ALTER TABLE turn_usage
    ADD COLUMN IF NOT EXISTS agent_id TEXT;

CREATE INDEX IF NOT EXISTS idx_turn_usage_agent
    ON turn_usage(agent_id, timestamp DESC);
```

If legacy SQLite schema still needs mirrored compatibility, add the matching fallback migration/schema update in the legacy `elevate_state.py` path only if tests require it. Do not treat SQLite as operational source of truth.

Acceptance criteria:

- Existing databases migrate without losing rows.
- New rows can be inserted with or without `agent_id`.
- Queries by `agent_id` are indexed.

### 2. Extend Postgres insert helper

File:

- `cli/elevate_cli/data/usage_ledger.py`

Change:

- Add `"agent_id"` to `_INSERT_COLUMNS` in the same order as schema.
- Keep missing/null values safe as `None` or empty string.
- Do not introduce prompt/response content.

Acceptance criteria:

- Existing `record_turn(row)` tests pass.
- Rows missing `agent_id` still insert.
- Rows with `agent_id` insert and read back.

### 3. Build `agent_id` into gateway rows

File:

- `cli/gateway/usage_ledger.py`

Change `build_turn_usage_row(...)` to accept:

```python
agent_id: str | None = None
```

Resolution order:

1. Explicit `agent_id` argument.
2. `agent_result.get("agent_id")`.
3. Parse `session_key` using the same logic as `gateway.run._parse_session_key(...)`, or add a local safe helper to avoid circular imports.
4. Empty string if unknown.

Normalize:

- lowercase
- strip whitespace
- replace `_` with `-`
- map `orchestrator`, `executive`, `executive-assistant` to `executive-assistant`

Acceptance criteria:

- Agent-scoped Telegram/session keys populate `agent_id`.
- Plain user chat rows remain blank or `executive-assistant` only when that is truly the running agent.
- Failed-turn rows also get attribution.

### 4. Pass `agent_id` from gateway run path

File:

- `cli/gateway/run.py`

At the successful `record_gateway_turn(...)` call:

- Try `getattr(source, "agent_id", "")` first.
- Fall back to parsed `session_key` agent marker.
- Pass `agent_id=...` into `record_gateway_turn(...)`.

At the failed-turn `record_gateway_turn(...)` call:

- Use the same attribution helper.

Acceptance criteria:

- Success and failure rows attribute to the same agent for the same session.
- Ledger write remains fail-open. Attribution failure must never block message delivery.

### 5. Tests for attribution

Likely files:

- `cli/tests/gateway/test_usage_ledger.py`
- Add or update migration/data tests if available for `elevate_cli.data.usage_ledger`.

Test cases:

1. `build_turn_usage_row(..., agent_id="admin")` stores `admin`.
2. `build_turn_usage_row(..., session_key="agent:main:telegram:thread:123:agent:outreach")` stores `outreach`.
3. underscores normalize: `executive_assistant` -> `executive-assistant`.
4. missing agent stays empty and does not fail insert.
5. Postgres helper includes `agent_id` in insert columns.

Run:

```bash
cd /Users/dartagnanpatricio/elevate/cli
source .venv/bin/activate || source venv/bin/activate
pytest tests/gateway/test_usage_ledger.py -q
```

Then run any targeted migration/data tests found near usage-ledger tests.

## Phase 2 — Attribution reporting

### 1. Add grouped query helper

File:

- `cli/elevate_cli/data/usage_ledger.py`

Add a helper like:

```python
def usage_by_agent(*, since: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
    ...
```

Group by:

- `agent_id`
- total turns
- total tokens
- input/output/cache/reasoning tokens
- estimated cost
- failed turns
- avg latency
- top tool profiles optionally

Acceptance criteria:

- Returns `unknown` bucket for blank agent ids.
- Bounded query. No unbounded dashboard load.

### 2. CLI / insights surface

Start small. Add one command/report:

```bash
elevate insights --agents --days 7
```

or extend existing `/insights` with an agent section.

Output example:

```text
Agent usage, last 7 days
admin                 42 turns   1.2M tokens   $3.81   2 failed
outreach              18 turns   420K tokens   $1.02   0 failed
executive-assistant   96 turns   2.4M tokens   $7.10   1 failed
unknown               9 turns    80K tokens    $0.18   0 failed
```

Acceptance criteria:

- User can see per-agent usage without querying DB manually.
- Unknown bucket makes attribution gaps visible.

## Phase 3 — Storage attribution scanner

This is separate from the token/cost ledger because disk usage is filesystem-based.

### 1. Create scanner module

Candidate file:

- `cli/elevate_cli/data/storage_attribution.py`

Scan known roots only:

- `~/.elevate/sessions`
- `~/.elevate/tmp`
- `~/.elevate/cache`
- `~/.elevate/logs`
- `~/.elevate/backups`
- selected stale workdirs under home only when explicitly included

Never scan secrets broadly. Never hash or read file contents. Use path, size, mtime, and inferred labels only.

Attribution rules:

1. Session path/session id -> join to session metadata where possible.
2. Cron/job path -> job id -> agent id if present.
3. Handoff/task artifact path -> task/agent id if present.
4. Agent-named path segments -> agent id only if exact roster match.
5. Else bucket as `shared-runtime`, `repo`, `app-cache`, `legacy-hermes`, or `unknown`.

Acceptance criteria:

- Read-only scan by default.
- Produces deterministic JSON/dict summary.
- Does not follow symlinks outside allowed roots.

### 2. Optional persisted snapshots

Create table only after the scanner is useful:

```sql
CREATE TABLE storage_usage_snapshots (...)
CREATE TABLE storage_usage_items (...)
```

Start with summary-only output. Persist later when we want trends.

### 3. Reporting

Add command/report:

```bash
elevate storage-usage --by-agent
```

Output buckets:

- agent-owned
- shared runtime
- legacy Hermes
- app cache
- repo/dev dependencies
- unknown
- cleanup candidates

Acceptance criteria:

- Can answer “what does each agent take up?”
- Can identify safe cleanup candidates separately from live Postgres/session data.

## Phase 4 — Dashboard surface

After CLI/reporting is stable, add dashboard cards:

- Usage by agent: tokens/cost/turns/errors.
- Disk by owner: agent/shared/unknown.
- Cleanup candidates: cache/temp/stale workdirs with reversible actions.

Guardrails:

- Dashboard cleanup actions must require approval.
- Never delete `~/.elevate/pgdata` from UI.
- Prefer “Move to Trash / archive” over hard delete.

## Files likely to change

First implementation slice:

- `cli/elevate_cli/data/migrations_pg/0005_turn_usage_agent_id.sql`
- `cli/elevate_cli/data/usage_ledger.py`
- `cli/gateway/usage_ledger.py`
- `cli/gateway/run.py`
- `cli/tests/gateway/test_usage_ledger.py`

Second slice:

- `cli/elevate_cli/data/usage_ledger.py`
- `cli/cli.py` or `cli/elevate_cli/main.py` depending on where insights command is wired
- tests for grouped query/reporting

Third slice:

- `cli/elevate_cli/data/storage_attribution.py`
- CLI/reporting command file
- tests for scanner classification

## Validation

Minimum validation for Phase 1:

```bash
cd /Users/dartagnanpatricio/elevate/cli
source .venv/bin/activate || source venv/bin/activate
pytest tests/gateway/test_usage_ledger.py -q
```

Then run the nearest data/migration tests discovered by search.

Manual verification:

1. Trigger an agent-scoped gateway turn.
2. Query usage rows grouped by `agent_id`.
3. Confirm agent id is present and no message content is stored.
4. Trigger/inspect a failed turn path if practical.

## Risks and tradeoffs

- `agent_id` may be absent for older or generic sessions. Keep an explicit `unknown` bucket.
- Session-key parsing can drift. Prefer one shared helper if import cycles allow it.
- Do not over-attribute shared runtime folders. Mark them shared unless there is strong evidence.
- Storage attribution should not become a broad filesystem crawler. Keep it scoped.
- Ledger failures must remain non-blocking.
- No prompt/response/tool-argument content should enter attribution tables.

## Recommended first task

Implement Phase 1 only:

> Add first-class `agent_id` attribution to the Postgres `turn_usage` ledger, including migration, row builder support, gateway success/failure write paths, and targeted tests.

That gives us useful attribution quickly without touching cleanup logic yet.
