# Central Data Model — Design Doc

**Status:** design only, no code written
**Owner:** Dartagnan
**Date:** 2026-05-05
**Scope:** unify per-source JSONL inboxes + scattered SQLite DBs into one
contact-centric central store, callable from both UI and AI cron.

## Why this exists

Elevate is the realtor's central CRM-of-record. Sources (Lofty, FUB, Sierra,
Brivity, BoldTrail, Apple Messages, Twilio SMS, Composio Gmail/IG/FB/WA,
Telegram, MLS PCS) are pluggable inputs. The realtor's truth — who is a
buyer, who is a listing, who replied last Tuesday — lives **centrally**, not
in any one source.

Today that's not the case:
- Per-source `contacts.jsonl` means a person who emails you and texts you
  shows up as two different records.
- 10 scattered `.db` files at `~/.elevate/` root, each owning a slice of
  state. No single place to ask "what's Wayne's lifecycle status?"
- Outreach DB has clean tables (`templates`, `draft_attempts`, `thread_meta`)
  but `thread_meta` is empty — nothing populates the cross-source state cache.
- UI and cron read JSONL directly, so any classification done in the UI
  (e.g., "this is a buyer") would be invisible to the cron and vice versa.

## Target architecture

Schema lives in **one** SQLite file: `~/.elevate/data/operational.db`.
Every read/write goes through one Python module: `elevate_cli/data/`.
Both the FastAPI routes (`/api/...`) and the cron skills/agent code call
the same functions — no direct SQL, no direct JSONL pokes.

### Tables

#### `contacts` — source of truth, deduped

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | UUIDv4 |
| `display_name` | TEXT | normalized |
| `primary_email` | TEXT | for fast lookup; canonical entry in `identities` |
| `primary_phone` | TEXT | E.164 normalized |
| `type` | TEXT | `unclassified` \| `buyer` \| `listing` \| `other` |
| `stage` | TEXT | freeform; e.g. `cold`, `first_touched`, `active`, `parked`, `dormant`, `won`, `dead` |
| `owner_notes` | TEXT | manual notes from realtor |
| `created_at` | TEXT ISO | first time we saw them on any channel |
| `classified_at` | TEXT ISO | when buyer/listing was set |
| `parked_reason` | TEXT | nullable, set when stage=`parked` |
| `last_activity_at` | TEXT ISO | denormalized roll-up of latest event ts |
| `source_key` | TEXT | `<source_id>:<source_native_id>` for the connector that first seeded the row; `UNIQUE(source_key)` so re-imports collide instead of duplicating |
| `ingest_run_id` | TEXT FK→ingest_runs | which ingest run created this row, nullable for human-created |

#### `identities` — every way we can address them

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | |
| `contact_id` | TEXT FK→contacts | |
| `kind` | TEXT | `email` \| `phone` \| `instagram_id` \| `facebook_id` \| `lofty_id` \| `apple_handle` \| `telegram_id` \| ... |
| `value` | TEXT | the address itself (canonical form per kind) |
| `source_id` | TEXT | which connector first saw this identity |
| `verified` | INTEGER | 1 if confirmed by reply, 0 if scraped/imported |
| `created_at` | TEXT ISO | |

`UNIQUE (kind, value)` — same email can't belong to two contacts. If a
collision happens during ingest, we merge.

#### `conversations` — one per (contact, source, channel, thread)

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | |
| `contact_id` | TEXT FK→contacts | |
| `source_id` | TEXT | connector instance, e.g. `lofty-default`, `apple-messages`, `composio-gmail-primary` |
| `channel` | TEXT | `email` \| `sms` \| `imessage` \| `messenger` \| `instagram` \| `whatsapp` \| `telegram` \| `voice` \| `crm` |
| `thread_key` | TEXT | the source's native thread ID (for re-fetching) |
| `status` | TEXT | `open` \| `done` \| `archived` |
| `inbound_count` | INTEGER | |
| `outbound_count` | INTEGER | |
| `last_inbound_at` | TEXT ISO | |
| `last_outbound_at` | TEXT ISO | |
| `heat_score` | INTEGER | |
| `heat_label` | TEXT | `hot` \| `warm` \| `watch` \| `normal` |
| `created_at` | TEXT ISO | |

`UNIQUE (source_id, thread_key)` — never duplicate a conversation.

#### `ingest_runs` — every connector run is a tracked unit

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | UUIDv4 |
| `source_id` | TEXT | which connector |
| `started_at` | TEXT ISO | |
| `completed_at` | TEXT ISO | nullable until done |
| `status` | TEXT | `running` \| `completed` \| `failed` \| `partial` |
| `rows_seen` | INTEGER | input rows processed |
| `rows_written` | INTEGER | rows that successfully landed in the DB |
| `rows_quarantined` | INTEGER | rows that failed DB write and stayed in JSONL with `ingest_status='retry'` |
| `error` | TEXT | error message if `status='failed'` |

Every row imported via a connector points back at one `ingest_runs.id`.
That gives us replay (re-run a single ingest) and rollback (delete every
row from a single run).

#### `identity_conflicts` — quarantine for ambiguous merges

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | |
| `kind` | TEXT | which identity kind tripped the conflict |
| `value` | TEXT | the canonical value |
| `candidate_contact_ids` | TEXT JSON | array of contact ids that all matched |
| `reason` | TEXT | `multiple_matches` \| `non_deterministic_merge_blocked` \| `cross_kind_mismatch` |
| `created_at` | TEXT ISO | |
| `resolved_at` | TEXT ISO | nullable |
| `resolved_by` | TEXT | actor (`human` or `agent:*`) |
| `resolution` | TEXT | `merged_into:<contact_id>` \| `kept_separate` \| `discarded` |

Identities flagged here do not trigger AI outreach until resolved — the
data module excludes any contact whose identity is in an open conflict
row from the picker's eligible pool.

#### `lead_signals` — cold MLS / scrape data, not yet a contact

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | |
| `source_id` | TEXT | e.g. `mls-private-search` |
| `source_native_id` | TEXT | scraper's id for this signal |
| `payload_json` | TEXT | full scraped record |
| `name`, `email`, `phone` | TEXT | as scraped, may be empty |
| `created_at`, `updated_at`, `last_activity_at` | TEXT ISO | |
| `graduated_at` | TEXT ISO | when promoted to a real contact |
| `graduated_to_contact_id` | TEXT FK→contacts | nullable until graduation |

`UNIQUE (source_id, source_native_id)`. Lead signals do **not** auto-create
contacts — they sit in this table until either (a) a verified identity
match graduates them or (b) a human classify/respond action does. This
keeps `/admin/contacts` from filling with cold MLS prospects.

#### `data_parity_snapshots` — Sprint 2 cutover safety

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | |
| `endpoint` | TEXT | e.g. `GET /api/source-inbox` |
| `request_args_json` | TEXT | normalized query args |
| `jsonl_response_hash` | TEXT | hash of legacy JSONL-derived response |
| `db_response_hash` | TEXT | hash of new operational.db-derived response |
| `diff_json` | TEXT | nullable; populated only on mismatch |
| `captured_at` | TEXT ISO | |

Written by the dual-read middleware during shadow mode. Sprint 2's gate
is "N requests with zero diffs," not "we ran a diff once."

#### `events_summary` — nightly rollup, kept lean for stats

Materialized from `events` so leaderboard / template stats queries don't
full-scan the full event log. One row per `(template_id, day)` and one
per `(contact_id, day)`. Refreshed nightly. If stale, fall back to live
`events` query — never block on it.

#### `events` — append-only audit log

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | |
| `contact_id` | TEXT FK→contacts | always set |
| `conversation_id` | TEXT FK→conversations | nullable (e.g., classification events) |
| `kind` | TEXT | frozen enum, see below |
| `channel` | TEXT | nullable (classify events have no channel) |
| `source_id` | TEXT | which connector or which UI/cron emitted it; e.g. `ui:web` / `cron:follow-ups` |
| `actor` | TEXT | `system` \| `human` \| `agent:claude` \| `agent:codex` |
| `template_id` | TEXT FK→templates | nullable, denormalized from payload for fast aggregation, indexed |
| `payload_json` | TEXT | inline body if ≤16KB; metadata only if larger |
| `payload_ref` | TEXT | nullable; relative path under `~/.elevate/data/payloads/` for oversize payloads |
| `ingest_run_id` | TEXT FK→ingest_runs | nullable; set when event came from a connector run |
| `event_hash` | TEXT | `sha256(source_id + thread_key + ts + body_hash)`; `UNIQUE` so re-imports don't duplicate |
| `ts` | TEXT ISO | |

**Frozen `events.kind` enum** (CHECK constraint, no new values without a
migration):

```
inbound, outbound, draft, approval, send, bounce, reply_attributed,
classified, parked, unparked, pcs_activity, lifecycle_change, note,
merge, merge_conflict, template_candidate, template_approved,
template_rejected, attribution_ambiguous,
ingest_run_started, ingest_run_completed
```

Every meaningful action — UI button click, cron draft, inbound webhook,
outbound send — writes one event row. This is "everything is marked."

#### `templates` — pool the picker draws from

Existing columns stay. Additions for V1:

| col | type | notes |
|---|---|---|
| `version` | INTEGER | bumped on edit; old version's stats stay read-only |
| `match_rules` | TEXT JSON | optional eligibility predicates for picker |
| `origin` | TEXT | `human` \| `ai_oneoff` \| `ai_pattern` \| `ai_failure_analysis` |
| `proposed_by_event_id` | TEXT FK→events | links back to event that triggered creation |
| `parent_template_id` | TEXT FK→templates | for variants/forks |
| `approved_at` | TEXT ISO | nullable |
| `approved_by` | TEXT | `human` only; data module rejects `agent:*` here |

**Approval invariant** (CHECK constraint):
```
status='live' REQUIRES approved_at IS NOT NULL AND approved_by IS NOT NULL
status='proposed' REQUIRES approved_at IS NULL
```
Plus a data-module-level rule: `approve_template` rejects any actor not
matching `human`. Cron/agent code can call `propose_template` only.

#### `draft_attempts`, `send_queue`, `inbound_seen` — moved from outreach.db

`draft_attempts.thread_id` becomes `draft_attempts.conversation_id` during
migration. Each gets a `source_key` UNIQUE column (CRM message id, send
queue job id, inbound message id) so re-imports never duplicate.

`draft_attempts` also gains `replied_at` ISO (filled by `mark_replied`)
and keeps the existing `outcome` column (`pending` / `sent` / `replied`
/ `bounced` / `dead`).

#### `pcs_buyers` — extra context for MLS-graduated contacts

Specialized addendum to `lead_signals` for MLS PCS rows that have
graduated into contacts. Holds the realtor-relevant analyzer output
(score / tier / searches / matching listings / profile_url). One row
per `contact_id`, nullable until graduation.

| col | type | notes |
|---|---|---|
| `contact_id` | TEXT PK FK→contacts | |
| `lead_signal_id` | TEXT FK→lead_signals | source row |
| `score`, `tier`, `days` | mixed | from analyzer |
| `searches_json`, `matching_listings_json` | TEXT | |
| `last_activity_at` | TEXT ISO | parsed from MLS `lastActivity` |
| `last_scraped_at` | TEXT ISO | |
| `profile_url` | TEXT | |

PCS activity changes (`last_activity_at` newer than last touch) emit a
`pcs_activity` event so the follow-up cron picks them up. Cold MLS rows
that never graduate live in `lead_signals` only.

### What goes away

- Per-source `contacts.jsonl` files become **input streams**, not state.
  Connectors still scrape into them as raw landing zones, but the central
  store is canonical. JSONL becomes "what the source said today" — wiped
  and rewritten on each sync.
- `state.db`, `orchestration.db`, `memory_store.db`, `response_store.db`,
  `messages.db`, `sessions.db` — keep these for runtime / agent state. They
  don't hold business truth. Don't touch.
- `ui-state.json`, `tasks.jsonl` — keep as ephemeral UI state. Not central.

## Identity resolution rules

When a connector ingests a record (e.g., a Lofty contact, an Apple Messages
thread, a Composio IG DM), the data layer does identity resolution before
inserting:

1. **Normalize identifiers**
   - Email: lowercase, strip whitespace
   - Phone: parse to E.164 (libphonenumber-py); discard if can't parse
   - Instagram: strip `@`, lowercase
   - Facebook ID: keep numeric ID

2. **Match against `identities` table**
   - For each normalized id on the inbound record, look up `(kind, value)`.
   - **Single match** → attach to that `contact_id`.
   - **No match** → create new `contact`, write each identifier to
     `identities`.
   - **Multiple matches** → never auto-merge. Write a row to
     `identity_conflicts` with all candidate ids and `reason='multiple_matches'`.
     Attach the inbound record to the OLDEST candidate but flag the contact
     as `has_open_conflict=1` so the picker excludes it from AI outreach.

3. **Auto-merge — deterministic only**
   - Auto-merge happens only when **both** sides share an identical,
     verified, high-uniqueness identifier:
     - same normalized email AND email is `verified=1` on both sides, OR
     - same E.164 phone AND phone is `verified=1` on both sides
   - Name similarity (Levenshtein, fuzzy match) is **not** sufficient on
     its own. Family members share phones, spouses share email aliases,
     CRM imports recycle numbers — all of these poison fuzzy auto-merge.
   - Anything outside the deterministic rule above → write
     `identity_conflicts` row with `reason='non_deterministic_merge_blocked'`.
     Both contacts stay separate. Conflict shows in `/admin/conflicts`.

4. **Verification**
   - Identity is `verified=1` if we received an inbound from it OR the
     realtor manually confirmed. Until then `verified=0` (scraped/imported).

5. **Conflict resolution UI** (Sprint 3, not deferred)
   - `/admin/conflicts` view lists open `identity_conflicts` rows.
     Realtor picks: merge into one (writes `merge` event, sets
     `resolved_at`), keep separate, or discard the conflict. AI outreach
     stays blocked until resolved.

## Function surface — the data module

`elevate_cli/data/__init__.py` re-exports all callable functions. Both
FastAPI routes and cron skills import from here. Direct SQL is not allowed
outside this module.

```python
# contacts
get_contact(contact_id) -> Contact
find_contacts(*, type=None, stage=None, owner=None, channel=None,
              last_activity_after=None, limit=50) -> list[Contact]
classify_contact(contact_id, type, *, actor) -> Contact
park_contact(contact_id, reason, *, actor) -> Contact
unpark_contact(contact_id, *, actor) -> Contact
update_contact_stage(contact_id, stage, *, actor) -> Contact
add_contact_note(contact_id, note, *, actor) -> None

# identities
add_identity(contact_id, kind, value, source_id, *, verified=False) -> Identity
resolve_identity(kind, value) -> Contact | None
merge_contacts(primary_id, duplicate_id, *, actor) -> Contact   # actor='human' required
record_identity_conflict(kind, value, candidate_contact_ids, reason) -> IdentityConflict
resolve_identity_conflict(conflict_id, resolution, *, actor) -> IdentityConflict
list_open_conflicts() -> list[IdentityConflict]

# conversations
get_or_create_conversation(contact_id, source_id, channel, thread_key) -> Conversation
update_conversation_status(conversation_id, status) -> None
get_conversations_for_contact(contact_id, *, channel=None) -> list[Conversation]

# events (append-only)
record_inbound(contact_id, conversation_id, channel, body, *, source_id, ts) -> Event
record_outbound(contact_id, conversation_id, channel, body, *,
                template_id=None, draft_attempt_id=None, source_id, ts) -> Event
record_draft(contact_id, conversation_id, body, template_id, *, actor, ts) -> Event
record_classification(contact_id, type, *, actor, ts) -> Event
record_pcs_activity(contact_id, mls_payload, *, ts) -> Event

# outreach
queue_send(conversation_id, payload) -> SendJob
mark_replied(draft_attempt_id) -> None
template_stats(template_id) -> TemplateStats                         # confident only
template_stats_with_ambiguous(template_id) -> TemplateStatsExtended  # full picture

# templates (proposal + approval; cron may propose, only human approves)
propose_template(body, lane, channel, *, origin, rationale,
                 proposed_by_event_id=None, parent_template_id=None,
                 actor) -> Template
approve_template(template_id, *, actor) -> Template     # rejects non-human actors
reject_template(template_id, reason, *, actor) -> Template
edit_template(template_id, new_body, *, actor) -> Template   # bumps version
list_proposed_templates() -> list[Template]
analyze_template_gaps() -> list[GapReport]

# ingest runs (every connector run gets one)
record_ingest_run_started(source_id) -> IngestRun
record_ingest_run_completed(ingest_run_id, *, status, rows_seen,
                            rows_written, rows_quarantined, error=None) -> None
rollback_ingest_run(ingest_run_id, *, actor) -> None

# lead signals (cold MLS data, not contacts yet)
upsert_lead_signal(scraped_record, *, source_id) -> LeadSignal
graduate_lead_signal(signal_id, *, contact_id, actor) -> Contact
detect_lead_signal_activity_change(signal_id) -> bool

# pcs (specialized addendum once graduated)
upsert_pcs_buyer(contact_id, analyzer_record, *, lead_signal_id) -> PcsBuyer

# parity (Sprint 1 deliverable, used by Sprint 2 cutover)
record_parity_snapshot(endpoint, request_args, jsonl_response, db_response) -> None
parity_diff_count(*, since=None) -> int   # gate for Sprint 2 flip
```

Every mutating call writes an `events` row internally. Callers don't need
to know — that's what makes "everything is marked" cheap to enforce.

## Connector ingest contract

Every connector (Lofty, FUB, Apple Messages, Composio, MLS PCS, Twilio,
Telegram) must follow exactly-once-or-quarantined semantics. Lossy is
not acceptable; replayable is.

1. **Open run** — call `record_ingest_run_started(source_id)`, get
   `ingest_run_id`. Fire `ingest_run_started` event.
2. **For each row from upstream**:
   a. Compute a stable `source_native_id` (CRM id, message id, thread id).
   b. Append the raw row to JSONL with a `row_hash` and `ingest_status='pending'`.
   c. Resolve identities, upsert into `contacts` / `conversations` / `events`
      via the data module. Every insert carries `ingest_run_id` and the
      `event_hash` UNIQUE.
   d. On success, update JSONL row to `ingest_status='ok'`.
   e. On failure, update to `ingest_status='retry'` and continue. The
      retry job re-runs failed rows on the next cycle.
3. **Close run** — call `record_ingest_run_completed(...)` with counts.
   Fire `ingest_run_completed` event.

This guarantees: (a) we never lose an upstream row, (b) we never duplicate
on replay (event_hash + source_key UNIQUEs catch it), (c) we can roll
back a single bad run without touching anything else.

## Payload policy

`events.payload_json` is capped at **16 KB**. Anything larger:
- `payload_json` holds a metadata-only summary (sender, kind, body length)
- full body is written to `~/.elevate/data/payloads/<event_id>.json`
- `events.payload_ref` holds the relative path

Retention: payloads older than 365 days move to
`~/.elevate/data/archived_payloads/<year>/<event_id>.json`. Event row stays;
payload becomes cold storage. Restore is opt-in via a CLI command.

The `events_summary` rollup table refreshes nightly so leaderboard /
template-stats queries don't full-scan the full event log. If the rollup
is stale, queries fall back to live `events` — never block on rollup.

## Templates: matching, attribution, stats

Templates aren't just text snippets — they're the unit we A/B and rank.
Every draft, every send, every reply gets stamped with the `template_id`
that produced it, so we can answer "which messages are landing?"

### How a template gets matched to a draft

The AI is the matcher, from day one. Rules only narrow the pool — the AI
picks the actual fit.

1. **Sanity filter — eligible pool**
   - `(lane, channel)` match (a first-touch SMS template never gets used
     for a follow-up email).
   - `templates.active = 1` and `status = 'live'`.
   - Optional hard predicates per template (`templates.match_rules` JSON,
     e.g. `{"min_outbound_count": 1, "max_days_since_inbound": 7}`).
   - This is just to keep the AI from considering nonsense. Cheap, deterministic.

2. **AI ranker — pick the best fit for this human**
   - The picker hands the AI: the eligible templates + the lead's full
     context (last inbound text, contact stage, conversation history,
     PCS search criteria if any, prior templates already tried with this
     contact, current per-template stats).
   - AI returns one pick + a one-line rationale that gets logged on the
     event. Rationale is for humans reviewing later, not for the system.
   - The AI weighs two things together:
     a) **Fit** — does this template match what this specific person said
        and where they are in their journey?
     b) **Track record** — what's this template's reply rate, and is it
        landing with people who looked like this one?
   - Templates the AI keeps picking and that keep landing get used more.
     Templates that the AI stops picking, or that get picked but ghost,
     fall out naturally. No manual ranking.

The picker lives at `pick_template(contact_id, conversation_id, lane, channel)
→ Template`. UI and cron both call this, so attribution is automatic.

The AI's pick + rationale gets written to the `draft` event. Over time we
can audit "why did the AI pick Warm Intro for Wayne?" by reading the event
log. That's the feedback loop — humans see the AI's reasoning, stats see
the outcome, AI uses both on the next pick.

### Attribution chain

The same `template_id` follows a message through its whole life:

```
pick_template()         → returns Template
record_draft(...)       → events.payload_json.template_id  +  draft_attempts.template_id
record_outbound(...)    → events.payload_json.template_id  +  draft_attempt_id FK
record_inbound(...)     → if matched to a prior outbound on same conversation,
                          fire reply_attributed event with template_id
mark_replied(...)       → draft_attempts.outcome = 'replied', closes the loop
```

Every mutation that touches a draft/send/reply carries `template_id`.
That's what powers the stats query.

Schema additions for attribution:

| change | where | why |
|---|---|---|
| `templates.match_rules` TEXT JSON | templates | optional eligibility predicates |
| `events.template_id` TEXT (nullable, indexed) | events | denormalized from payload for fast aggregation |
| `draft_attempts.outcome` already exists | draft_attempts | values: `pending`, `sent`, `replied`, `bounced`, `dead` |
| `draft_attempts.replied_at` TEXT ISO | draft_attempts | filled by mark_replied; powers reply latency |

`events.template_id` indexed because every report query filters/groups
by it.

### Reply attribution rules

When `record_inbound()` writes a new inbound event, attribution runs in
**two tiers** — confident, and ambiguous.

**Confident attribution (counts toward `template_stats`)**:
1. Exactly one `outbound` event on the same `conversation_id` within the
   last 30 days.
2. The reply arrives on the same channel as the outbound (no SMS-replies-
   to-email cross-channel mush).
3. The conversation is one-to-one (not a group thread).

If all three hold: write a `reply_attributed` event with the outbound's
`template_id`, call `mark_replied(draft_attempt_id)`. This is the clean
signal that drives `template_stats`.

**Ambiguous attribution (logged, excluded from clean stats)**:
- Multiple eligible outbounds in the window
- Cross-channel candidate (e.g., outbound on email, inbound on SMS)
- Group thread / multiple inbound participants
- Reply arrives after the 30-day window

Each ambiguous case writes an `attribution_ambiguous` event with all
candidate `template_id`s + the reason. These do **not** call
`mark_replied`. They show up in `template_stats_with_ambiguous` for
context but never poison the clean leaderboard.

This protects the loop. A noisy attribution model would let lucky-but-
ambiguous templates climb the leaderboard, the AI would prefer them,
the picker would entrench them — failure mode that looks like success.
Two-tier attribution makes the noise visible instead of silent.

### Stats query surface

```python
template_stats(template_id) -> TemplateStats
# Confident attributions only. This is what the picker reads.
# {
#   "uses": 22,
#   "replies": 6,            # confident only
#   "reply_rate": 0.273,
#   "median_reply_hours": 4.2,
#   "wins": 1, "win_rate": 0.045,
#   "bounces": 0, "deads": 3,
# }

template_stats_with_ambiguous(template_id) -> TemplateStatsExtended
# Above + ambiguous_replies, ambiguous_reply_share. For human review,
# never for picker decisions.

template_leaderboard(*, lane=None, channel=None, since=None) -> list[TemplateStats]
# Ranked by reply_rate. Templates with fewer than 50 sends OR less than
# 30 days in service do NOT appear; they show in a separate "Trial" tab.
# Versioned templates: leaderboard rolls up versions of the same lineage.
```

Powers a `/admin/templates` view: leaderboard, per-template detail
(inbound replies preview, win attribution, bounce log), and a
"Trial" tab for templates still in their min sample window.

### Picker exploration policy

Sprint 4 picker doesn't naively pick the highest reply_rate — that
entrenches early winners and starves new templates. Instead:

- **Thompson sampling.** For each eligible template, draw a sample from
  `Beta(replies + 1, sends - replies + 1)`. Pick the highest sampled
  score. New templates with no data get a wide distribution and
  occasional wins; proven templates with tight distributions usually win
  but don't monopolize.
- **Per-contact cooldown.** A template just sent to contact X can't be
  re-picked for X for 7 days. Prevents the "send the same warm intro
  three times" failure mode.
- **Min sample window for leaderboard.** Templates appear in the public
  leaderboard only after **50 sends OR 30 days**, whichever first.
  Below that they're "Trial" — picker can still pick them via Thompson,
  but their stats don't get displayed as authoritative.
- **Versioning.** Editing a live template bumps `version`. New sends go
  to current version. Old version's stats stay read-only. The leaderboard
  rolls up a template's lineage but per-version detail is available.

### Template versioning rules

When `edit_template(template_id, new_body, *, actor)` is called:
1. Bump `templates.version` by 1.
2. Old version's stats stay queryable but its `status` flips to
   `superseded` (read-only, picker ignores).
3. New version inherits `match_rules`, `lane`, `channel`, `origin`, but
   resets `uses`/`replies`/`approved_at`. New version starts in
   `proposed` if `actor` is `agent:*`, in `live` if `actor='human'`
   (skip approval since they edited it themselves).

### Template generation — AI invents new ones too

Picking from existing templates only takes us so far. The AI also writes
new templates when the data shows a gap.

**Where new templates come from:**

1. **AI-drafted one-offs that land.** When the AI can't find a good fit
   in the eligible pool, it writes a fresh draft from scratch (no
   `template_id`). That draft still gets logged to events. If it gets
   sent and gets a reply, the AI flags it as a **template candidate** —
   "this exact pattern landed, save it for next time?"

2. **Pattern detection across replies.** Periodic job (weekly cron) reads
   the event log: "we got 8 replies in the last 30 days where the inbound
   was 'is this still available?' — what drafts landed best?" If a clear
   pattern shows up that no existing template covers, the AI proposes a
   new template.

3. **Failure analysis.** Inverse — if a lane/channel has low reply rates
   across all current templates, the AI proposes alternatives based on
   what's actually getting replies in adjacent contexts.

**Lifecycle of a generated template:**

```
status='proposed'  →  human reviews in /admin/templates  →  status='live'
                                  ↓
                              status='rejected' (kept for learning, not used)
```

New templates never go straight to `live`. They sit in `proposed` until
pilot realtor approves. The /admin/templates view shows proposed templates
with the rationale ("AI noticed pattern X, suggests this") and the
candidate body inline-editable.

**Schema additions for generation:**

| change | where | why |
|---|---|---|
| `templates.status` already exists | templates | add values: `proposed`, `live`, `rejected`, `retired` |
| `templates.origin` TEXT | templates | `human` \| `ai_oneoff` \| `ai_pattern` \| `ai_failure_analysis` |
| `templates.proposed_by_event_id` TEXT (nullable) | templates | links back to the event that triggered creation, so we can show "this template was suggested because Wayne's reply to draft X landed" |
| `templates.parent_template_id` TEXT (nullable) | templates | for variants/forks of an existing template |
| `templates.created_at`, `approved_at`, `approved_by` | templates | audit |

**Function surface additions:**

```python
propose_template(body, lane, channel, *, origin, rationale,
                 proposed_by_event_id=None, parent_template_id=None) -> Template
approve_template(template_id, *, actor) -> Template
reject_template(template_id, reason, *, actor) -> Template
list_proposed_templates() -> list[Template]
analyze_template_gaps() -> list[GapReport]   # what's the cron output that proposes new ones?
```

**Loop closes itself:**

- AI picks template → drafts → sends → reply lands → stats update.
- AI sees gaps in the data → proposes new template → human approves → it
  enters the pool → AI starts picking it → stats grow → either it earns
  its spot or gets retired.
- AI writes a one-off → it lands → AI flags it as a candidate → human
  approves → now it's a real template with its first win already logged.

The realtor never has to write a template from scratch. They review,
approve, and edit. The AI does the wordsmithing. The data decides what
survives.

### Open question on templates

- **Variant tracking:** when a template gets edited, do we treat the
  edit as a new template (clean stats, fresh start) or amend the existing
  one (continuous stats, dirty)? **Lean: bump a `version` column,
  attribute new sends to current version, keep old version's stats
  read-only. Two-line schema change, no data lost.**

- **Auto-promote threshold?** Should a `proposed` template that's been
  approved-and-landed N times skip review and go straight to `live` next
  time the AI proposes a similar variant? **Lean: no for v1. Always
  human-in-the-loop on new templates. Revisit when we see how often the
  AI actually proposes good ones.**

## Production install paths (the pilot realtor's Mac)

```
~/.elevate/                                # ELEVATE_HOME (env override)
├── config.toml                            # global config
├── auth.json                              # CRM keys, OAuth tokens (mode 0600)
├── data/
│   ├── operational.db                     # central truth (this whole doc)
│   └── sessions.db                        # AI session history (separate, log-ish)
├── sources/                               # raw landing zones per connector
│   ├── crm/                               # contacts.jsonl, lead-events.jsonl
│   ├── apple-messages/
│   ├── composio-gmail/
│   ├── composio-instagram/
│   └── mls-private-search/
├── skills/                                # shared library
├── cache/                                 # ephemeral
└── logs/
```

Single-realtor install — flat, no `agents/<slug>/` nesting. Nesting only on
Dartagnan's dev box where multiple realtor sandboxes coexist.

`ELEVATE_HOME` env var overrides `~/.elevate/`. All paths derived from one
`paths.py` module so nothing hardcodes a slug or absolute path.

## Migration plan (one-time, on first upgrade)

```
elevate migrate-data
```

Single command. Idempotent. On first run:

1. **Create new layout** — `~/.elevate/data/`, `~/.elevate/sources/`,
   `~/.elevate/logs/`. Initialize `operational.db` from schema.

2. **Move source data** — rename `~/.elevate/tmp/client-tools/data/sources/`
   → `~/.elevate/sources/`. Leave a forwarding symlink at the old path
   for one release so any cron job not yet updated still works.

3. **Backfill from JSONL → SQLite**
   - Iterate every `<source>/contacts.jsonl` → identity-resolve → upsert
     `contacts` + `identities`
   - Iterate every `<source>/lead-events.jsonl` → resolve to `contact_id`
     and `conversation_id` → insert `events`
   - Iterate `mls-private-search/buyers.jsonl` → upsert `pcs_buyers`,
     identity-resolve to `contact_id`

4. **Move outreach.db tables**
   - `ATTACH DATABASE '~/.elevate/tmp/.../outreach.db' AS old`
   - `INSERT INTO templates SELECT * FROM old.templates`
   - `INSERT INTO draft_attempts SELECT ... FROM old.draft_attempts`
     (rename `thread_id` → `conversation_id` via lookup)
   - `INSERT INTO send_queue SELECT * FROM old.send_queue`
   - `INSERT INTO inbound_seen SELECT * FROM old.inbound_seen`

5. **Quarantine the rest** — leave `~/.elevate/state.db`, `orchestration.db`,
   etc. untouched. They're runtime state, not business truth.

6. **Write `MIGRATED_AT` to operational.db.meta** — block re-runs.

7. **Print migration report** — N contacts created, M conversations,
   K identities. Realtor sees what moved.

After migration, the cron and UI both call the data module functions.
Old code paths reading JSONL directly get deprecated and removed in a
follow-up release.

## What's NOT in scope for v1

- Cross-device sync/write-through — gated behind `--cloud-backup`
  config flag, ship later
- Multi-agent isolation (`agents/<slug>/`) — Dartagnan's dev box uses
  `ELEVATE_HOME` to switch between the pilot realtor's and a future realtor's
  sandbox; production CLI is single-tenant
- Manual merge UI — start with auto-merge only, ship merge UI when we
  see real duplicates accumulate
- Identity verification flow — start simple (verified flag), ship
  challenge-response (e.g., reply-with-code) later

## Open decisions

1. **`operational.db` or split further?** Templates + draft_attempts could
   live in `outreach.db` (the existing file, reused) and contacts/
   conversations/events in a new `operational.db`. Two files, cleaner
   separation. Or one file, simpler. **Lean: one file, simpler.**

2. **Hard delete vs. soft delete on contacts?** "Dead" contacts shouldn't
   resurface, but we don't want to lose history. **Lean: soft delete via
   `stage='dead'`, never DROP.**

3. **PCS buyer = contact, or PCS buyer = signal that creates a contact?**
   ✅ **Resolved.** Cold MLS rows live in `lead_signals`, not `contacts`.
   Graduation to a real contact requires either (a) a verified identity
   match (the same email or E.164 phone shows up on a real channel) or
   (b) a manual classify/respond action by the realtor. `/admin/contacts`
   defaults to hiding signal-only rows so the contact list stays clean.

4. **Where does "out of rotation" map?** Stage `parked` (manual), stage
   `dormant` (auto, no activity 90+ days). Both filtered out of cron lanes
   by default. Surfaced in /admin as a "Parked / Dormant" tab.

## Risk / unknowns

- **Identity resolution false positives** — auto-merging two real different
  people with similar names + shared phone (e.g., shared family number) is
  a real risk. Mitigation: require email match for auto-merge, fall back
  to "flag for manual review" otherwise.
- **Codex auth still broken** (separate issue) — even with this central
  store, AI drafts won't generate until that's fixed. This work is parallel.
- **Schema migrations after v1** — once shipped, schema changes need a
  proper migration framework (Alembic for SQLAlchemy, or a hand-rolled
  versioned migration runner). Not solved here. **Lean: hand-rolled
  numbered migrations under `data/migrations/0001_init.sql` etc., applied
  by the data module on startup.**
