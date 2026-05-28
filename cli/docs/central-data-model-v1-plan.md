# Central Data Model — V1 Execution Plan

**Status:** plan only, no code written
**Owner:** Product
**Date:** 2026-05-05
**Companion to:** [central-data-model.md](./central-data-model.md)

## Goal

Ship a single-realtor production install that:
- Owns the truth in one SQLite (`~/.elevate/data/operational.db`)
- Routes all reads/writes through one Python data module (`elevate_cli/data/`)
- Supports AI-driven template matching + AI-generated template proposals
- Works for the pilot realtor's daily ops by default

## Out of scope for V1

- Hosted cloud sync/write-through
- Multi-realtor isolation (`agents/<slug>/`) on this CLI
- Identity challenge-response verification (e.g., reply-with-code)
- Auto-promote of `proposed` templates (always human-in-the-loop)
- Fuzzy auto-merge on names — V1 is deterministic-only, conflicts go to
  `/admin/conflicts` quarantine UI (which IS in V1)

## Sprint 1 — Foundation (data layer)

Build the spine, paranoid edition. No UX changes. Existing `/leads` keeps
running on JSONL throughout.

Sprint 1 is bigger than originally scoped because the irreversible parts
(migration, identity merge, replay) need their safety surfaces built
before the canonical DB exists, not after.

### 1A — Pre-flight (foundational safety)

Land **before** Sprint 1 core work begins.

- **Source-natural-key inventory.** Document every imported row's
  source-natural key in `docs/source-keys.md`:
  - `contacts.source_key = '<source_id>:<source_native_id>'` UNIQUE
  - `events.event_hash = sha256(source_id + thread_key + ts + body_hash)` UNIQUE
  - `draft_attempts.source_key`, `send_queue.source_key`,
    `inbound_seen.source_key`, `lead_signals(source_id, source_native_id)`
  - For each source (Lofty, FUB, Apple Messages, Composio Gmail/IG/FB,
    MLS PCS, Twilio, Telegram), pin which upstream id we use. If the
    source doesn't have a stable id, we hash `(source_id, channel,
    sender, ts, first_64_chars_of_body)` as a fallback.
- **Frozen `events.kind` enum** as a CHECK constraint in 0001_init.sql.
  Every kind a connector or skill might emit is listed; new kinds
  require a numbered migration.
- **Approval invariant** as a CHECK constraint:
  `templates.status='live'` requires `approved_at IS NOT NULL AND
  approved_by IS NOT NULL`. `approve_template` in the data module
  rejects any actor not matching `human`.
- **No-SQL-outside-module enforcement test.** New file
  `tests/test_data_module_isolation.py` greps the codebase for
  `import sqlite3`, `cursor.execute`, raw `.db` paths, and direct
  `.jsonl` writes outside `elevate_cli/data/` and `elevate_cli/connectors/`.
  Fails CI if any are found. Add to lint pre-commit.
- **Dry-run + backup + rollback** for `elevate migrate-data`:
  - `elevate migrate-data --dry-run` writes a report to
    `~/.elevate/logs/migration-dryrun-<ts>.json` (rows that would be
    created, conflicts detected, identity collisions flagged). No DB
    writes.
  - Real migration auto-creates a backup at
    `~/.elevate/backups/pre-migration-<ts>/` covering everything under
    `~/.elevate/` except `cache/`. Backup is mandatory; refuse to run
    if backup fails.
  - `elevate migrate-data --rollback <ts>` restores from a backup and
    deletes `operational.db`.

### 1B — Schema + migration runner

- New file: `elevate_cli/data/migrations/0001_init.sql`
  - Full schema from design doc: contacts, identities, conversations,
    events, ingest_runs, identity_conflicts, lead_signals, pcs_buyers,
    data_parity_snapshots, events_summary (rollup), templates (with
    `version`, `match_rules`, `origin`, `proposed_by_event_id`,
    `parent_template_id`, `approved_at`, `approved_by`), draft_attempts
    (with `replied_at`, `source_key`), send_queue, inbound_seen
  - Indexes: `events(template_id)`, `events(contact_id)`, `events(ts)`,
    `events(event_hash)` UNIQUE, `events(ingest_run_id)`,
    `conversations(contact_id)`, `conversations(source_id, thread_key)`
    UNIQUE, `identities(kind, value)` UNIQUE,
    `lead_signals(source_id, source_native_id)` UNIQUE
  - CHECK constraints: events.kind enum, templates approval invariant
- New module: `elevate_cli/data/migrations.py` — applies numbered SQL
  files in order, tracks applied version in `_migrations` table
- New module: `elevate_cli/data/paths.py` — `ELEVATE_HOME` env
  override, single source of truth for every path

### 1C — Data module skeleton

New package: `elevate_cli/data/`

- `__init__.py` — re-exports public API
- `connection.py` — SQLite connection, WAL mode, `foreign_keys=ON`, pragmas
- `contacts.py` — `get_contact`, `find_contacts`, `classify_contact`,
  `park_contact`, `unpark_contact`, `update_contact_stage`,
  `add_contact_note`
- `identities.py` — `add_identity`, `resolve_identity`, `merge_contacts`
  (rejects non-human actors), `record_identity_conflict`,
  `resolve_identity_conflict`, `list_open_conflicts`, normalizers
  (email/phone/IG/FB)
- `conversations.py` — `get_or_create_conversation`,
  `update_conversation_status`, `get_conversations_for_contact`
- `events.py` — `record_inbound`, `record_outbound`, `record_draft`,
  `record_classification`, `record_pcs_activity`,
  `record_attribution_ambiguous`. Enforces frozen kind enum, writes
  `event_hash`, attaches `ingest_run_id` if present, handles payload
  spillover (>16KB → `payload_ref`)
- `ingest.py` — `record_ingest_run_started`,
  `record_ingest_run_completed`, `rollback_ingest_run`
- `templates.py` — placeholder, filled Sprint 4
- `lead_signals.py` — `upsert_lead_signal`, `graduate_lead_signal`,
  `detect_lead_signal_activity_change`
- `parity.py` — `record_parity_snapshot`, `parity_diff_count` (used by
  Sprint 2 cutover gate)

Every mutating function writes its own `events` row. No SQL allowed
outside this package. Direct JSONL writes outside `elevate_cli/connectors/`
are forbidden (enforced by the 1A grep test).

### 1D — Shadow-read + parity tooling

Built in Sprint 1, used in Sprint 2.

- New middleware in the FastAPI app: when `ELEVATE_DATA_SHADOW_READ=1`,
  every `GET /api/source-inbox` and `GET /api/threads/<id>` runs both
  the JSONL-derived path (returned to client) and the operational.db
  path (logged to `data_parity_snapshots`).
- Snapshot row hashes both responses and stores a diff if they don't
  match.
- `elevate parity-report` CLI summarizes the last N snapshots, lists
  endpoints with the most diffs, and shows representative diff payloads.

### 1E — Backfill migration

- `elevate migrate-data` (idempotent, requires backup)
- Steps:
  1. Take backup → `~/.elevate/backups/pre-migration-<ts>/`
  2. Create `~/.elevate/data/`, `~/.elevate/sources/`, `~/.elevate/logs/`
  3. Initialize `operational.db` from migration 0001
  4. Move `~/.elevate/tmp/client-tools/data/sources/` →
     `~/.elevate/sources/`, leave backwards-compat symlink for one release
  5. Open one synthetic ingest_run per source (so backfilled rows have a
     real `ingest_run_id`)
  6. Iterate `<source>/contacts.jsonl` → resolve identities (deterministic
     auto-merge or write to `identity_conflicts`) → upsert contacts +
     identities with `source_key`
  7. Iterate `<source>/lead-events.jsonl` → resolve to contact +
     conversation → insert events with `event_hash` UNIQUE
  8. Iterate `mls-private-search/buyers.jsonl` → upsert into
     `lead_signals` (NOT auto-create contacts)
  9. ATTACH old `outreach.db`, INSERT INTO new templates / draft_attempts
     / send_queue / inbound_seen, deduping via source_key
  10. Close synthetic ingest_runs
  11. Print report: N contacts, M conversations, K identities,
      C conflicts, S signals
- **`--force` semantics**: replay-safe reconciliation, not "insert again."
  Re-runs identity resolution against current `identities` table, re-links
  events via `event_hash`, never duplicates. `event_hash` UNIQUE makes
  duplicate inserts a no-op even if the run is interrupted halfway.

### Done when

- `elevate migrate-data --dry-run` produces a clean report
- Real migration runs on the pilot realtor's Mac with backup created first
- SQLite file exists with data + `identity_conflicts` rows for ambiguous merges
- `/leads` page still works (still reading old JSONL)
- Tests pass against `:memory:` DB
- `tests/test_data_module_isolation.py` passes (no rogue SQL/JSONL writes)
- `elevate parity-report` works, even though it has nothing to compare yet

---

## Sprint 2 — Switch reads to data module

Cut UI + cron over to operational.db. JSONL becomes input-only. Cutover
is gated on logged parity, not first-time testing.

### 2.1 Connectors adopt the ingest contract

Every connector follows the exactly-once-or-quarantined pattern from the
design doc's "Connector ingest contract" section:

- Open ingest_run → process rows → close ingest_run.
- For each row: write to JSONL with `row_hash` and `ingest_status='pending'`,
  upsert via data module (events get `event_hash` and `ingest_run_id`),
  flip JSONL row to `ingest_status='ok'` on success, `'retry'` on failure.
- Retry job re-runs failed rows on next cycle.
- `_heat_score_for_record` runs against `operational.db` conversations,
  not JSONL records.

### 2.2 API routes (shadow mode first)

- Phase A — **shadow mode** with `ELEVATE_DATA_SHADOW_READ=1`:
  serve legacy JSONL response to client, run new SQLite path in parallel,
  log every diff to `data_parity_snapshots`. Run for at least one full
  pilot realtor ops cycle (~7 days of normal usage).
- Phase B — **flip** once `parity_diff_count(since=last_7d) == 0` for at
  least 3 days. UI now reads from `operational.db`. Old JSONL path stays
  available behind `ELEVATE_DATA_LEGACY_READ=1` for one release.
- Phase C — remove legacy path next release.

Routes: `GET /api/source-inbox`, `GET /api/threads/<id>`. Filters
(heatLabel, channel, stage, etc.) become SQL WHERE clauses.

### 2.3 Validation

- Phase A → B gate: zero parity diffs across N requests for ≥3 days
- Phase B verification: `/leads` page renders identically, no
  user-visible change
- Rollback path: flip `ELEVATE_DATA_LEGACY_READ=1` if anything regresses

### Done when

- UI reads from `operational.db` after passing the parity gate
- Cron writes through data module via the ingest contract
- JSONL files are decorative (still written for replay, never read by UI)

---

## Sprint 3 — Lifecycle UX (the daily-value surfaces)

What pilot realtor actually sees and uses every day.

### 3.1 Classify button

- On thread/lead detail panel: Buyer / Listing / Other buttons
- Calls `classify_contact(contact_id, type, actor='human')`
- Writes a `classified` event, updates `contacts.type` + `classified_at`
- After classify, lead falls out of `/leads` rotation by default and shows
  in `/admin`

### 3.2 Park / unpark

- "Park" button with reason picker (Wrong number, Not interested, Already
  represented, Bad fit, Other)
- `park_contact(contact_id, reason, actor='human')` — stage→`parked`,
  event written
- `/admin/parked` view shows them with Unpark button

### 3.3 Active leads section on /leads

- New right-column section between Hot leads and Pipeline tabs
- Shows contacts where `stage IN ('first_touched', 'active')` —
  conversation is alive
- Sorted by `last_activity_at DESC`

### 3.4 /admin contact list

- New page: `/admin/contacts`
- Filters: type (all / buyer / listing / unclassified / other), stage,
  channel, last activity range, source
- Tabs: All / Buyers / Listings / Parked / Dormant / Dead
- **Default hides signal-only rows** (cold MLS lead_signals) — toggle
  to show them
- Each row links to thread detail or contact detail panel

### 3.5 /admin/conflicts (identity quarantine UI)

- New page: `/admin/conflicts` — lists rows from `identity_conflicts`
  where `resolved_at IS NULL`
- Each row shows: the disputed identity (kind + value), candidate
  contacts side by side, reason, the inbound that triggered it
- Three actions per row: Merge into one (writes `merge` event,
  reassigns identities), Keep separate (records resolution, removes
  block), Discard the disputed identity
- AI outreach stays blocked on contacts with open conflicts until
  resolved here

### 3.6 Lead signal graduation

- Background job: when an inbound (email/SMS/etc.) matches an identity
  on a `lead_signals` row, auto-graduate the signal → contact
- Manual graduate button on `/admin/signals` for cold MLS rows the
  realtor wants to start working

### Done when

- pilot realtor can classify a lead in `/leads` → it moves to `/admin/buyers`
- Park works
- Active section renders correctly
- `/admin/conflicts` shows any quarantined identity merges and lets her
  resolve them
- A cold MLS lead that suddenly emails pilot realtor auto-graduates from
  `lead_signals` to `contacts`

---

## Sprint 4 — Template picker + attribution chain

Wire `template_id` end-to-end. AI ranker comes online (or deterministic
fallback if Codex auth still broken). Picker uses Thompson sampling so
proven templates win without starving new ones.

### 4.1 Template picker (eligibility + Thompson + cooldown)

- New function: `pick_template(contact_id, conversation_id, lane, channel) → Template`
- **Eligibility filter** (stage 1): pool by
  `(lane, channel, active=1, status='live', match_rules predicates pass)`
  AND cooldown not active for this contact
- **Per-contact cooldown**: a template just sent to contact X cannot be
  re-picked for X for 7 days. Prevents repeat-send failure mode.
- **Thompson sampling** (stage 2 default, used when AI unavailable): for
  each eligible template, draw a sample from
  `Beta(replies + 1, sends - replies + 1)`. Pick the highest sample.
  New templates with no data get a wide distribution and occasional
  exploration; proven templates with tight distributions usually win.
- **AI ranker** (stage 2 when Codex auth healthy): hand eligible + lead
  context + per-template Thompson scores to the model. Model returns one
  pick + a one-line rationale. The AI is allowed to override Thompson
  for fit reasons but the rationale is logged.
- Pick + rationale + Thompson scores logged on the `draft` event for
  later auditing.

### 4.2 Two-tier attribution chain

- `record_draft(... template_id ...)` — required (or explicit None for
  one-offs)
- `record_outbound(... template_id ...)` — carries from draft
- `record_inbound(...)` — runs the attribution rules from the design doc:
  - **Confident**: exactly one outbound in 30d window, same channel,
    one-to-one thread → fire `reply_attributed`, call `mark_replied`,
    counts toward `template_stats`
  - **Ambiguous**: any condition fails → fire `attribution_ambiguous`
    event listing all candidate `template_id`s + the reason. Does NOT
    call `mark_replied`. Counts only toward `template_stats_with_ambiguous`.
- Index `events.template_id` for fast aggregation.

### 4.3 Stats surface

- `template_stats(template_id) → TemplateStats` — confident attributions
  only. This is what the picker reads and what the leaderboard shows.
- `template_stats_with_ambiguous(template_id) → TemplateStatsExtended` —
  full picture including `ambiguous_replies` and `ambiguous_reply_share`.
  For human review only.
- `template_leaderboard(lane=None, channel=None, since=None) → list[TemplateStats]`
  - **Min sample window**: a template appears on the leaderboard only
    after **50 sends OR 30 days**, whichever first. Below that it shows
    on a separate "Trial" tab (still picker-eligible via Thompson, just
    not authoritative on the leaderboard).
  - Versioned templates roll up by lineage (parent_template_id chain).

### 4.4 Template versioning

- `edit_template(template_id, new_body, *, actor)` bumps `version`,
  sets the previous row's `status='superseded'` (read-only, picker
  ignores), creates a new row inheriting `lane`/`channel`/`match_rules`/
  `origin`.
- New version starts in `proposed` if `actor` is `agent:*`, in `live`
  with `approved_at` set if `actor='human'` (the realtor edited it
  themselves).
- Old version's stats stay queryable forever — never lost.

### Done when

- Send templated message via UI → reply lands → `template_stats(id).replies`
  increments within 60s of inbound
- Picker doesn't repeat-send the same template to the same contact
  within 7 days
- Editing a live template creates a new `version` row; old version
  becomes read-only
- Cross-channel reply (e.g., outbound on email, reply on SMS) emits
  `attribution_ambiguous`, NOT `reply_attributed`

---

## Sprint 5 — AI template generation + /admin/templates

AI starts proposing new templates. pilot realtor approves them. Approval is
enforced at the schema layer (CHECK) and the data-module layer (actor
gate) — there is no path for an AI-proposed template to enter the live
pool without a human approval action.

### 5.1 One-off detector

- When `pick_template` finds no good fit (eligible pool empty OR AI
  explicitly says "none of these fit"), AI writes a fresh draft.
  `template_id=NULL` on the draft event.
- If that one-off gets sent and gets a confident reply, fire a
  `template_candidate` event with the draft body + context. The
  candidate is NOT auto-promoted; it shows on `/admin/templates`'s
  Proposed tab.

### 5.2 Pattern + failure detection

- Weekly cron: `analyze_template_gaps() → list[GapReport]`
  - Read events from last 30 days
  - Find clusters of inbounds where no eligible template fit
  - Find lanes/channels where all current templates have
    `reply_rate < 5%` (using the min sample window from Sprint 4)
  - For each gap, AI drafts a candidate and calls
    `propose_template(..., actor='agent:claude', origin='ai_pattern' or
    'ai_failure_analysis')`. Schema CHECK refuses to set `status='live'`
    without `approved_at` + `approved_by`.

### 5.3 /admin/templates

- New page. Three tabs: Live / Proposed / Retired
- **Live**: sortable by `reply_rate`, `uses`, `win_rate`. Edit (bumps
  version) / retire / fork. Versioned templates roll up by lineage with
  a "show all versions" expand.
- **Proposed**: card per proposal showing the AI's rationale, the body
  (inline editable), origin (`ai_oneoff` / `ai_pattern` /
  `ai_failure_analysis`), Approve / Reject buttons.
  - Approve → `approve_template(id, actor='human')`. CHECK constraint
    requires the approval audit fields. Status flips to `live`.
  - Reject → `reject_template(id, reason, actor='human')`. Status flips
    to `rejected` (kept for learning).
- **Retired**: read-only history, stats preserved.

### 5.4 Approval invariant test

- Test in `tests/test_template_approval_invariant.py`:
  - Direct SQL `INSERT INTO templates (status='live', approved_at=NULL)`
    must fail (CHECK)
  - `propose_template(actor='agent:claude')` followed by
    `approve_template(id, actor='agent:claude')` must raise (data-module
    actor gate)
  - Only `actor='human'` can approve

### Done when

- AI proposes a template after a one-off lands or pattern detection runs
- pilot realtor sees it on `/admin/templates`, approves
- Next `pick_template` call's eligible pool includes it
- Approval invariant test passes (no path for AI to bypass approval)

---

## Cross-cutting

- **Tests:** every data-module function has a test against in-memory
  SQLite (`:memory:`). Dedicated test files for identity resolution
  (collision / quarantine / merge), reply attribution (confident /
  ambiguous boundary cases), template versioning, and ingest run
  rollback. `tests/test_data_module_isolation.py` runs in CI.
- **Logging:** every mutation logs to `~/.elevate/logs/data.log` with
  contact_id, event kind, actor, ingest_run_id (if any).
- **Payload spillover:** events with `payload_json > 16KB` write to
  `~/.elevate/data/payloads/<event_id>.json` and store `payload_ref`.
  Nightly job archives payloads older than 365 days under
  `archived_payloads/`.
- **events_summary rollup**: nightly job writes per-template-per-day and
  per-contact-per-day aggregates so leaderboard queries don't full-scan
  events. Stale rollup falls back to live query, never blocks.
- **Docs:** `docs/central-data-model.md` is the spec; this plan tracks
  execution; add `docs/data-module-api.md` as function reference once
  implemented; `docs/source-keys.md` (Sprint 1A) pins source-natural
  keys per connector.
- **Codex auth:** unblocks AI ranker override (Sprint 4) + AI generation
  (Sprint 5). Thompson sampling is the deterministic default that ships
  regardless. AI overrides flip on when auth is healthy.

## Order of execution

```
Sprint 1A — pre-flight: source keys, frozen enum, isolation test,
            dry-run / backup / rollback             (paranoia first)
Sprint 1B — schema + migration runner               (foundation)
Sprint 1C — data module skeleton                    (function surface)
Sprint 1D — shadow-read + parity tooling            (Sprint 2 safety net)
Sprint 1E — backfill migration                      (one-time data move)
Sprint 2  — connectors adopt ingest contract +
            shadow-mode parity → flip               (zero UX change)
Sprint 3  — classify / park / active / /admin /
            conflicts queue / signal graduation     (the pilot realtor's daily UX)
Sprint 4  — picker (Thompson + cooldown + AI) +
            two-tier attribution + versioning       (loop closes)
Sprint 5  — template generation + /admin/templates +
            approval invariant test                 (self-improving)
```

Each sprint ships to the pilot realtor's Mac before the next starts. Sprint 1's
sub-stages (1A→1E) ship as one bundle since they're all foundation.

## Validation gates

| Sprint | Gate |
|---|---|
| 1 | `migrate-data --dry-run` reports clean. Real migration creates backup, lands schema, populates `identity_conflicts` for ambiguous merges, lead_signals for cold MLS rows. `tests/test_data_module_isolation.py` passes. /leads still works on legacy reads. |
| 2 | Shadow mode runs ≥7 days. `parity_diff_count(since=last_7d) == 0` for ≥3 days. After flip: /leads renders identically, rollback flag works. |
| 3 | Classify → /admin/buyers. Park → /admin/parked. `/admin/conflicts` shows ambiguous merges and lets pilot realtor resolve them. Cold MLS lead that emails pilot realtor auto-graduates to a contact. |
| 4 | Templated send → confident reply → stats reflect within 60s. Cross-channel reply emits `attribution_ambiguous`, doesn't poison clean stats. Picker doesn't repeat the same template to same contact within 7 days. Edit a live template → new version row, old marked `superseded`. |
| 5 | AI proposes template after pattern detection → pilot realtor approves in `/admin/templates` → next pick eligible-pool includes it. `agent:*` actors cannot bypass approval (CHECK constraint + data-module-level enforcement). |

## Risks

- **Sprint 2 cutover** — still the biggest risk, now mitigated by
  shadow-mode parity logging built in Sprint 1 and a ≥3-day zero-diff
  gate before flip. Rollback flag stays available for one release.
- **Deterministic-only auto-merge** — by design we'll generate more
  `identity_conflicts` rows than a fuzzy auto-merge would. That's the
  correct trade. Risk: if the conflict queue grows unmanageable,
  pilot realtor ignores it and AI outreach stays blocked on those contacts.
  Mitigation: `/admin/conflicts` ergonomics matter; default to surfacing
  the count in the global nav as an unread-style badge.
- **Codex auth broken** — Thompson sampling is the deterministic
  default; AI overrides flip on when auth is healthy. No blocker for
  shipping Sprint 4 or 5.
- **Event log size** — `events_summary` rollup + payload spillover keep
  the main `events` table query-fast and small. Partitioning still
  deferred to V2; the rollup buys runway.
- **Lead signal stagnation** — cold MLS rows that never graduate could
  pile up in `lead_signals` indefinitely. Acceptable for V1 (it's
  cheap storage); add a "purge signals not active in 18 months" job
  in V2 if it becomes noise.
- **Migration aborts mid-run** — `event_hash` UNIQUE makes a partial
  run safe to re-run; backup makes a worst-case rollback possible.
  Mitigation: run `--dry-run` first, then real run with backup, only
  delete backup once pilot realtor has used the new system for a week.

## Sprint progress log

- **Sprint 1** (1A–1E) — DONE. Schema, migration runner, data module,
  shadow-read + parity tooling, backfill migration. 44 tests green.
- **Sprint 2** (2A–2D) — DONE. `db_source_inbox_response` /
  `db_thread_context_response` in `data/reads.py`,
  `ELEVATE_DATA_PRIMARY=db` flip flag + `ELEVATE_DATA_FALLBACK=jsonl`
  rollback in `data/shadow.py`, `web_server.py` wires `db_fn` for both
  source-inbox endpoints. 13 new tests (57 total). The actual cutover
  flip stays gated on a 3-day clean parity window — operator action,
  cannot run in-session.
- **Sprint 3** (3A–3E) — DONE backend. Eight HTTP endpoints in
  `web_server.py`: classify / park / unpark, `/api/contacts/active`,
  `/api/admin/contacts` (with tab presets), `/api/admin/conflicts` +
  resolve, `/api/admin/signals` + manual graduate. `find_contacts`
  extended with `stage_in` filter. 26 new tests (109 total). Frontend
  wiring (Next.js buttons/pages) and the auto-graduation hook on
  inbound (3.6 background) are deferred to dedicated tasks.
- **Sprint 4** (4A–4D) — DONE. `data/picker.py` (eligibility +
  per-contact 7-day cooldown + Thompson on Beta(wins+1, uses-wins+1) +
  AI ranker hook with eligibility guard), `data/attribution.py`
  (two-tier reply attribution: confident vs five ambiguous shapes,
  30-day window), `template_leaderboard()` in `data/templates.py`
  (lineage rollup by `parent_template_id` chain, authoritative vs trial
  buckets gated on uses≥50 OR age>30d, sorted by win-rate then uses).
  24 new tests (133 total elevate_cli/). The AI ranker call site is
  reserved — outreach worker will pass a callable when Codex auth is
  back; until then Thompson is the deterministic fallback.
- **Sprint 5** (5A–5E) — DONE. `/admin/templates` HTTP surface +
  one-off candidate detector + weekly gap analysis + approval-invariant
  hardening. Five endpoints in `web_server.py`
  (`GET /api/admin/templates?tab=live|proposed|retired`,
  `POST .../{id}/approve|reject|edit|retire`) all attributing to
  `human:web` and gated by the existing session-token middleware.
  `data/attribution.py` now seeds a `proposed` template (origin
  `ai_oneoff`, idempotent via `proposed_by_event_id`) whenever a
  confident-channel reply lands on a freehand outbound, and writes a
  `template_candidate` event under actor `agent:oneoff_detector`.
  New `data/gaps.py` exposes `analyze_template_gaps()` with two gap
  shapes: `low_reply_rate` (every cleared live template in a
  lane/channel under 5%) and `no_template_fit` (inbound in lookback
  window with no same-conversation templated outbound within 24h,
  grouped by channel + source_id). Approval invariant locked down at
  schema layer (CHECK rejects raw `status='live'` without
  `approved_at`/`approved_by`) and module layer (`approve_template` and
  `edit_template` reject any actor not starting with `human:`).
  39 new tests (172 total `tests/elevate_cli/`). The AI drafting hook
  upstream of `_seed_oneoff_candidate` (Claude/Codex producing the
  candidate body for `low_reply_rate` / `no_template_fit` gaps) stays
  reserved until Codex auth returns — until then the realtor
  hand-writes candidates from the gap report. `/admin/templates`
  Next.js UI is the only remaining piece and is tracked separately
  from the central data model V1.
