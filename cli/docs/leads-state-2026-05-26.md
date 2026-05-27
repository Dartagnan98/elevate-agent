# /leads State-of-the-System Audit
**Date:** 2026-05-26
**Scope:** Every surface, table, endpoint, sync path, and UI component touching "leads" in the Elevate CLI.
**DB:** Embedded Postgres at `~/.elevate/pgdata/` (database `elevate_operational`). The legacy 340MB `~/.elevate/state.db` SQLite file is **archive only** for session state — every lead-related row lives in PG.

---

## Executive summary

The /leads pipeline runs but ships three structural cracks. (1) The identity merge engine in `walk_jsonl_source` is correct, but only `crm`, `apple-messages`, `composio-gmail`, and `composio-instagram` route through it; the `xposure-pcs` ingest writes 1,070 contacts straight into `contacts` with **zero identity rows**, so 1,015 verifiable lead_signal/CRM duplicates never merge. (2) Apple-messages identities (`+1604/+1250`) have **zero phone-value overlap** with CRM identities of the same area codes — the actual phone strings just don't intersect, leaving every channel in its own island (0 Lofty contacts with non-CRM conversations). (3) The drawer is finally DB-backed (commit `864b2534c`) and the prefix bug is patched (`cd33284a5`), but the activity card surfaces 534,966 `lifecycle_change` events almost all emitted by `legacy_backfill` (CRM tombstones titled "Lofty lead synced via Other" / "Auto Text Outbound"), drowning real signal. Drafts/sends still route through tasks.jsonl + outreach.db (separate from operational PG). Three /leads sections render but have no live cron data (Gmail Doc Router, Seller Update, Market Stats Watcher are all `enabled=false`, never run).

The user's prior "1,253 orphan conversations" figure does NOT reproduce — only **2 conversations** point to a contact with no identity rows. The real orphan story is at the **contact** layer, not the conversation layer.

---

## 1. Data model — live counts

### 1.1 Headline row counts

| Table | Rows | Notes |
|---|---|---|
| `contacts` | 4,842 | |
| `conversations` | 4,340 | |
| `identities` | 10,023 | |
| `events` | 758,661 | 70% are `lifecycle_change` tombstones |
| `tasks` (PG) | 0 | task work lives in `kanban_tasks` (also 0) and `tasks.jsonl` per-source |
| `kanban_tasks` | 0 | |
| `send_queue` | 188 | **VIEW** over `outreach_send_queue` |
| `outreach_send_queue` | 188 | base table |
| `identity_conflicts` | 12 | **0 resolved** |
| `draft_attempts` | 189 | |
| `lead_signals` | 1,080 | all graduated |
| `pcs_buyers` | 1,080 | xposure-pcs addendum |
| `deals` | 21 | |
| `deal_contacts` | 0 | unused link table |
| `notes` (PG) | 0 | notes live in `events` + `lead-events.jsonl` |
| `thread_meta` / `outreach_thread_meta` | 0 / 0 | |
| `lane_config` / `outreach_lane_config` | 0 / 0 | |
| `lead_inquiries` / `lead_properties` | 0 / 0 | unused |

### 1.2 events by kind

| kind | count |
|---|---|
| lifecycle_change | 534,966 |
| inbound | 133,809 |
| outbound | 87,999 |
| note | 1,691 |
| draft | 196 |

99.99% of `lifecycle_change` rows have actor `legacy_backfill` (534,959). Only 5 are `operator:leads-ui`. **Top 8 lifecycle payload titles** are:

- `Lofty lead synced` (16,750+ rows across "Other" / "expmakingitrain" / "Website" / "Other (Bri Sanderson)" / "Other (Perry Volaine)" variants)
- `Auto Text Outbound` (1,728)
- `Text Outbound` (964)
- `Have You Heard Of Our App?` (609)

These are Lofty CRM activity-log tombstones, not lifecycle stage transitions. They are the noise the drawer surfaces in "Property activity."

### 1.3 send_queue / outreach_send_queue by status

| status | count |
|---|---|
| pending_approval | 182 |
| sent | 5 |
| cancelled | 1 |

All 182 pending are `source_id='crm'`. The 5 sent are `apple-messages` (all `stub-sms-*` provider IDs — sender is in stub mode).

### 1.4 draft_attempts by status

| status | count |
|---|---|
| pending_approval | 182 |
| draft_pending_approval | 5 |
| drafted | 1 |
| cancelled | 1 |

Two parallel status taxonomies (`pending_approval` and `draft_pending_approval`) — same lifecycle, different wording from different writers.

### 1.5 identity_conflicts (12 total, 0 resolved)

All 12 are unresolved. **Schema bug surfaced**: 6 of the 12 rows have `kind='phone'` but `value` is an email address (`ashley.b.fields@icloud.com`, `curtisdujoy@icloud.com`, `morganluvshockey@gmail.com`, `patriciodartagnan@gmail.com`, `enclave.media@icloud.com`, `+18666692373`). Source is `apple_contacts_backfill._record_phone_collision` — it always writes `kind='phone'` regardless of whether the handle was an email or a phone number. (`apple_contacts_backfill.py:169-181`).

### 1.6 Per-source breakdown

#### conversations by source_id

| source | count |
|---|---|
| crm | 2,479 |
| apple-messages | 1,190 |
| composio-gmail | 639 |
| composio-instagram | 32 |

#### identities by source_id

| source | count |
|---|---|
| crm | 6,438 |
| apple-messages | 3,335 |
| composio-gmail | 176 |
| composio-instagram | 64 |
| xposure-pcs | 10 |

#### identities by kind

| kind | count |
|---|---|
| phone | 2,612 |
| email | 2,570 |
| lofty_id | 2,479 |
| apple_handle | 1,129 |
| apple_chat_id | 1,018 |
| apple_addressbook_id | 183 |
| instagram_id | 32 |

#### contacts by `source_key` prefix

| prefix | count |
|---|---|
| `crm:lofty-lead:*` | 2,443 |
| `apple-messages:apple-handle:*` | 1,110 |
| `xposure-pcs:*` | 1,080 |
| `composio-gmail:email:*` | 176 |
| `composio-instagram:instagram_id:*` | 32 |

(`crm` + `apple-messages` + `xposure-pcs` + `composio-gmail` + `composio-instagram` = 4,841 ≈ contacts total).

### 1.7 Lofty enrichment population

Defined as: `COUNT(DISTINCT contacts.id JOIN identities ON kind='lofty_id')`. Total Lofty contacts = **2,445**.

| field | populated | % |
|---|---|---|
| `lead_score` | 2,445 | 100.0% |
| `tags_json` | 2,445 | 100.0% |
| `lead_source` | 2,444 | 100.0% |
| `assigned_agent` | 2,444 | 100.0% |
| `crm_stage` | 2,444 | 100.0% |
| `pond_id` | 2,444 | 100.0% |
| `lead_types_json` | 2,444 | 100.0% |
| `crm_user_id` | 2,444 | 100.0% |
| `selling_time_frame` | 1,801 | 73.7% |
| `with_listing_agent` | 1,801 | 73.7% |
| `mortgage_status` | 1,801 | 73.7% |
| `buy_house_intent` | 1,801 | 73.7% |
| `segments_json` | 1,289 | 52.7% |
| `pre_qual_status` | 74 | 3.0% |
| `buying_time_frame` | 61 | 2.5% |
| `has_house_to_sell` | 60 | 2.5% |
| `first_time_home_buyer` | 55 | 2.2% |
| `with_buyer_agent` | 53 | 2.2% |
| `opportunity` | 0 | 0.0% |
| `referred_by` | 0 | 0.0% |
| `pond_name` | 0 | 0.0% |

The 73.7% / 2.5% split = the qualification fields Lofty fills for **listing** leads vs **buyer** leads. `opportunity`, `referred_by`, `pond_name` are dead columns — never populated.

### 1.8 Orphan conversations

- Conversations whose `contact_id` has **NO identity rows at all**: **2** (both `apple-messages`).
- Conversations with `contact_id IS NULL`: **0**.
- Conversations whose contact has no identity matching the conversation's own `source_id`: **2** (same 2 rows).

The 1,253 figure does not reproduce. The real number is 2.

### 1.9 Soft-orphan: contacts with no email/phone identity

- Contacts with no email AND no phone identity: **1,380**
- Apple-only contacts (have `apple_handle` etc., no email/phone): **120**
- Apple contacts colliding by phone with another contact: **0** (the merge code's intended trigger — never fires)
- Apple contacts that DON'T also carry a `lofty_id`: **1,107** (i.e. 99.7% of Apple contacts are not linked to CRM)
- Lofty contacts with NO non-CRM conversation: **2,443** (all 2,443)
- Lofty contacts WITH any non-CRM conversation: **0**
- `xposure-pcs` contacts with NO identity rows at all: **1,070** of 1,080

### 1.10 Multi-channel contacts

| distinct sources | contact count |
|---|---|
| 1 | 3,729 |
| 2 | **3** |

Three contacts in the entire system have conversations from more than one source. Everything else is in a per-channel silo.

### 1.11 Cross-source identity overlap (the merge-eligible set the merger isn't seeing)

| overlap | count |
|---|---|
| Phones in BOTH `crm` AND `apple-messages` (same string) | 0 |
| Emails in BOTH `crm` AND `composio-gmail` (same string) | 0 |
| Phone values appearing in `identities` from >1 source | 0 |
| Email values appearing in `identities` from >1 source | 0 |
| Lead_signals emails that match a CRM email identity | **1,015** |
| Lead_signals phones that match a CRM phone identity | 0 |

The CRM ↔ Apple/Gmail miss is a normalization gap (different formatting of the same phone/email). The CRM ↔ xposure-pcs miss is structural: the xposure-pcs ingest path **does not call `add_identity` at all** — it goes through `upsert_lead_signal` → `graduate_lead_signal` (`elevate_cli/data/lead_signals.py`), which writes a row to `contacts` but never writes identity rows for the email/phone it has on hand. That's why xposure shows up with 10 identities for 1,080 contacts.

---

## 2. Sync pipeline

### 2.1 What runs at what cadence

From `~/.elevate/cron/jobs.json` (10 jobs):

| name | schedule | script | last run | status |
|---|---|---|---|---|
| Memory maintenance benchmark | weekly Sun 03:00 | LLM prompt | 2026-05-20 22:09 | ok |
| Elevate memory maintenance smoke | daily 02:00 | LLM prompt | 2026-05-26 02:01 | ok |
| New Outreach | daily 08:00 | `new-outreach-wrapper.sh` | 2026-05-26 08:08 | ok |
| Hot Leads Watcher | daily 08:00 | LLM prompt | 2026-05-26 08:05 | ok |
| Social Content Engine | weekly Mon 07:00 | LLM prompt | 2026-05-25 19:44 | ok |
| Follow-ups | 10:00 + 15:00 daily | LLM prompt | 2026-05-25 15:07 | ok |
| Private Searches | daily 03:00 | `pcs-pipeline-wrapper.sh` | 2026-05-26 03:36 | ok |
| Gmail Doc Router | weekly Mon 09:00 | LLM prompt | **never run** | **disabled** |
| Seller Update | weekdays 16:00 | LLM prompt | **never run** | **disabled** |
| Market Stats Watcher | weekly Mon 07:00 | LLM prompt | **never run** | **disabled** |

Wrapper scripts live at `~/.elevate/scripts/` and shell into `/Users/dartagnanpatricio/elevate-premium/scripts/outreach/` (separate `elevate-premium` repo).

### 2.2 Per-source connector paths

For each source the ingest writes JSONL files to `~/.elevate/tools/data/sources/<source>/` and a downstream `walk_jsonl_source(conn, source_dir)` syncs them into PG. The `walk_jsonl_source` step is the only place `add_identity` and `resolve_identity` get called (outside of `apple_contacts_backfill`).

| connector | api → jsonl path | jsonl → PG | calls `add_identity`? | last sync |
|---|---|---|---|---|
| `crm` (Lofty) | elevate-premium scripts → `sources/crm/*.jsonl` | `walk_jsonl_source` via `composio_inbound.py:919` writethrough on next pull | ✅ yes, `migrate.py:799` | latest event 2026-05-26 15:31 |
| `apple-messages` | chat.db reader → `sources/apple-messages/*.jsonl` | `walk_jsonl_source` (and `apple_contacts_backfill._add_identity` for the secondary handle/addressbook merge) | ✅ yes, both paths | latest event 2026-05-24 06:01 |
| `composio-gmail` | `composio_inbound.pull_toolkit('gmail')` → `sources/composio-gmail/*.jsonl` | `walk_jsonl_source` via `composio_inbound.py:919` | ✅ yes | latest event 2026-05-23 11:05 |
| `composio-instagram` | `composio_inbound.pull_toolkit('instagram')` | `walk_jsonl_source` | ✅ yes | latest event 2026-05-16 00:28 |
| `xposure-pcs` | Playwright scrape in `elevate-premium/scripts/xposure/` → server push | `upsert_lead_signal` + `graduate_lead_signal` (`lead_signals.py:73,170`) | ❌ **NO** — graduates into `contacts` directly without writing identity rows | last ingest_run 2026-05-23 10:12 |
| `outreach-first-touch` (cron) | n/a — writes drafts to `send_queue` + 177 `events.kind=draft` rows | direct DB write via `outreach_db` | n/a | 2026-05-26 |
| `outreach-nurture-cron` | n/a | direct DB | n/a | 2026-05-22 17:11 |
| `ui:lifecycle` | operator clicks in dashboard | direct DB | n/a | 2026-05-15 02:08 |
| `apple-contacts` (Mac AddressBook) | `apple_contacts.py` reader → augments existing apple-messages identities | runs from `apple_contacts_backfill.py:219 run()` | ✅ yes via `_add_identity` (lines 281/308/333/356/367/387) | (manual `elevate` CLI, no cron) |
| `twilio` | declared in capability matrix, not connected | n/a | — | — |
| `whatsapp`, `telegram`, `facebook` | declared in `_SOURCE_TO_HANDLE_KIND` (`migrate.py:299-300`) | not connected | — | — |

### 2.3 ingest_runs table

Only 2 rows exist:
- `pcs-20260523T100214Z` — xposure-pcs, completed, 1,080 seen / 1,080 written.
- `outreach-first-touch-2026-05-26` — outreach-first-touch, completed, 2,475 seen / 177 written.

The other connectors don't write to `ingest_runs` — they update `~/.elevate/tools/data/sources/<source>/status.json` instead. No central "last sync per source" view.

### 2.4 status.json snapshots

- `sources/crm/status.json`: `last_imported_at` = 2026-05-19 03:38, counts: 2,474 contacts, 15,455 lead_events, 2,059 tasks, 822 notes, 5,548 lofty_tasks, **2,580 errors**.
- `sources/apple-messages/status.json`: `last_imported_at` = 2026-05-19 03:59, 1,105 contacts, 1,178 conversations, 222,627 messages.
- `sources/composio-gmail/cursors.json` last updated 2026-05-19 03:55 (only Composio account `ca_TM51zsI6Ijw9`).
- `composio-gmail/messages.jsonl` is 70 MB — last modified 2026-05-18 20:55.

---

## 3. Identity matching — deep dive

### 3.1 `add_identity` / `resolve_identity` call sites (outside `identities.py`)

| caller | file:line | source(s) | kinds written | verified? |
|---|---|---|---|---|
| `walk_jsonl_source` (canonical) | `data/migrate.py:799` | every JSONL source: crm, apple-messages, composio-gmail, composio-instagram | email, phone, lofty_id, apple_handle, apple_chat_id, instagram_id, plus anything in row.identities[] | `verified=True` only when `kind == crm_identity_kind` (i.e. `lofty_id`); everything else `False` |
| `apple_contacts_backfill._add_identity` | `apple_contacts_backfill.py:123` (called from 281, 308, 333, 356, 367, 387) | apple-messages secondary backfill | phone, email, apple_handle, apple_chat_id, apple_addressbook_id | always `verified=0` (hardcoded at line 148) |
| `web_server.py:4297` | `web_server.py:4297` | UI conflict-resolver | `resolve_identity_conflict` only (not add) | — |
| `migrate.py:_resolve_via_identities` | `data/migrate.py:425` | read-only resolver invoked by all walk_jsonl_source rows before upsert | — | — |

### 3.2 Where contacts get CREATED

Single chokepoint: `upsert_contact` in `data/contacts.py:222`. Every connector that runs through `walk_jsonl_source` calls it with `contact_id=resolved_id` (the merge target) or `source_key=<new>` (new contact). The merge logic at `migrate.py:715-789` is correct in principle: gather candidates → resolve → reuse-or-create.

**Bypass: `lead_signals.graduate_lead_signal`** (`data/lead_signals.py:170`). This calls `upsert_contact(conn, contact_id=signal_id_as_contact_id, ...)` directly without first resolving identities. The xposure-pcs ingest goes through this path and writes 1,080 contacts with **zero identity rows** (verified: 1,070 of those 1,080 have no `identities` row at all). 1,015 of those `lead_signals.email` values DO match an existing CRM `identities` row (`kind='email', source_id='crm'`) — guaranteed dupes.

### 3.3 The user's "1,253 orphan conversations" figure

**Cannot reproduce.** Live DB shows:
- Conversations whose contact has zero identities: **2**
- Conversations with `contact_id IS NULL`: **0**

The number that's close to 1,253 is **1,107** (apple-messages contacts with no `lofty_id` identity = potential merge candidates) or **1,070** (xposure-pcs contacts with zero identity rows = genuine orphans from the identity graph). Neither is a "conversation" count — both are at the contact layer.

### 3.4 Post-ingest reconciliation sweep

**Does not exist.** Searched `elevate_cli/`, `cron/`, `plugins/`. No code re-runs identity resolution against historical conversations after a later sync adds a new identity. If Lofty pulled a lead first as `+1.604.555.0100` and apple-messages later writes it as `+16045550100`, nothing ever notices.

`apple_contacts_backfill.py` is the closest thing: it's a manual CLI re-run that walks `chat.db` and writes new identities for handles it discovers, but it doesn't re-link existing conversations either.

### 3.5 identity_match_runs telemetry table

**Does not exist.** There's `ingest_runs` (source-level counts) but nothing per-merge. No way to answer "how many candidates did we evaluate, how many merged, how many conflicted" except by diffing `identities` and `identity_conflicts` row counts over time.

---

## 4. /leads UI — frontend

### 4.1 Top-level structure

`web/src/pages/RealEstateHubPages.tsx` (3,937 lines). The /leads route renders the `LeadProfilesWorkbench` (line 210) which wraps a 4-tab bar:

```ts
const LEAD_TABS = [
  { id: "action-board", label: "Action Board", icon: Radar },
  { id: "profiles",     label: "Profiles",     icon: Users },
  { id: "templates",    label: "Templates",    icon: BookText },
  { id: "sent",         label: "Sent",         icon: Send },
];
```
(`RealEstateHubPages.tsx:2844-2849`)

### 4.2 Tabs and what each renders

| tab | rendered by | data sources |
|---|---|---|
| Action Board | `ActionBoard` (in `real-estate-hub/_shared/action-board.tsx`) → `LeadPipelineBoard` (line 1519) | `data.sourceInbox.threads` (from `/api/source-inbox`), `data.cronJobs`, `data.sourceInbox.buyers` |
| Profiles | `LeadProfilesListPage` (line 525) → `LeadBoardRow` | `data.sourceInbox.profiles` |
| Templates | `TemplatesPanel` (line 3039) | `/api/leads/templates`, `/api/leads/outreach/lanes` |
| Sent | `SentMessagesBoard` (line 3503) | `/api/source-inbox/sent` |

`LeadPipelineBoard` (line 1519) further sub-tabs into:
- **hot** → `HotLeadsList` (line 1486)
- **followups** → `FollowUpThreadsList` (line 1569)
- **buyers** → `PrivateSearchBuyersList` (line 1603)

(`RealEstateHubPages.tsx:1544-1567`). New Outreach is on a separate workbench surface ("New Outreach" tab in the workflow strip).

### 4.3 Sections that render empty in production

- **Outreach Lanes overview** (`OutreachLanesGrid`, line 2305) — pulls `lane_config` rows. `lane_config` and `outreach_lane_config` are both **empty (0 rows)**. The grid falls through to a "no lanes configured" state.
- **Gmail Doc Router / Seller Update / Market Stats Watcher** lanes — these cron jobs exist in `jobs.json` but `enabled=false` and `last_run_at=null`. Any UI that lists them shows zero throughput.
- **Notes card** in the drawer when only PG-side notes are checked — `notes` (PG) is empty; real notes come from `lead-events.jsonl` (1,691 `event.kind='note'` rows in PG are also there but filtered separately by the drawer builder which reads only the JSONL).
- **Tasks card** in the drawer — `kanban_tasks` is empty; tasks come from `lead-events.jsonl` (event_type='lofty_task') and only show for Lofty leads with task records.

### 4.4 The drawer (`thread-drawer.tsx`, 651 lines)

`ThreadContextSidebar` (line 364) renders five sections, all from `/api/source-inbox/thread/{source_id}/{thread_id}` response:

| card | field read | backend source |
|---|---|---|
| Lead score | `meta.score ?? lead.score` + `meta.label ?? lead.stage ?? lead.leadSource` (line 388-389) | `lead.score` comes from `contacts.lead_score` (Lofty 0-100) or `contacts.heat_score` fallback (`reads.py:705-709`); `meta.score` from `outreach_db.get_thread_meta` (outreach.db SQLite) |
| Contact | `lead.phones`, `lead.emails` (line 465-474) | `contacts.primary_email`, `contacts.primary_phone` (`reads.py:670-675`) |
| Notes | `context.notes` (line 383) | `sources/<source_id>/lead-events.jsonl` filtered to `event_type='lofty_note'` (`reads.py:802-841`) |
| Tasks | `context.tasks` | same JSONL, `event_type='lofty_task'` |
| Property activity | `context.activity` | TWO sources merged: PG `events.kind IN (...)` for this contact (`reads.py:622-635`) AND lead-events.jsonl entries not matching note/task |
| Send history | `sends` prop | `outreach_db.list_sends_by_thread` (outreach.db, separate from PG) |

The drawer is now DB-first (commit `864b2534c`, 2026-05-?). Fallback to JSONL `build_thread_context_response` happens only on a real DB error (`web_routes/source_connectors.py:101-109`).

### 4.5 Prefix bug + fix

`db_thread_context_response` strips `<source_id>:` if the incoming `thread_id` starts with it (`reads.py:537-539`). This was added by commit `cd33284a5`. It works for `crm:lofty-lead:...` URLs where the profile's `threadIds[0]` was built as `"<source_id>:<thread_key>"`. **Buyer-search panel calls `drawer.openThread(matchedSourceId, matchedThreadId)`** (`RealEstateHubPages.tsx:1757`) — `matchedThreadId` comes from `profile.threadIds[0]`, so it has the same prefix shape and is correctly handled by the strip logic on the backend.

---

## 5. Backend endpoints — `/api/source-inbox*`

Defined in `elevate_cli/web_routes/source_connectors.py:27-228`. Builders live in `elevate_cli/source_connectors.py` (legacy JSONL, 5,946 lines) and `elevate_cli/data/reads.py` (DB, lines 256-870).

| endpoint | builder | data source | shape |
|---|---|---|---|
| `GET /api/source-connectors` | `source_connectors.build_source_connectors_response` | JSONL `status.json` for each source dir | source list with connected/blocked flags |
| `GET /api/source-connectors/{id}/records` | `build_source_records_response` | `sources/<id>/messages.jsonl` (last N) | raw record list |
| `GET /api/source-inbox` | `shadow_read` between `build_source_inbox_response` (JSONL) and `db_source_inbox_response` (PG) | both | threads + profiles + buyers + sources |
| `GET /api/source-inbox/thread/{source_id}/{thread_id}` | `db_thread_context_response` with JSONL fallback | PG `conversations`, `contacts`, `events` + JSONL `lead-events.jsonl`, `tasks.jsonl` + outreach.db `sends`/`meta` | composite |
| `POST /api/source-inbox/thread` | `update_source_thread_state` (JSONL ui-state.json) | `sources/<id>/ui-state.json` | acks |
| `POST /api/source-inbox/profile` | `update_profile_state` | JSONL profile-state.json (source-root) | acks |
| `POST /api/source-inbox/draft` | `update_source_task_state` | `sources/<id>/tasks.jsonl` + ui-state.json | acks |
| `GET /api/source-inbox/draft/{src}/{thread}/{task}/send-status` | `sender.status_for_task` | send_queue VIEW (outreach_send_queue) | queue row or none |
| `GET /api/source-inbox/sent` | `outreach_db.list_recent_sends` | outreach_send_queue (PG) | up to 100, status=sent by default |
| `POST /api/sender/tick` | `sender.tick` | reads outreach_send_queue, calls platform senders | |
| `GET /api/sender/stats` | `outreach_db.send_queue_stats` | outreach_send_queue | |

### 5.1 What each block of the thread response pulls from

`db_thread_context_response` return value (`reads.py:853-869`):

| key | source |
|---|---|
| `sourceId`, `threadId`, `source` | derived |
| `personName` | `contacts.display_name` |
| `messages` | PG `events` where `conversation_id=conv.id AND kind IN ('inbound','outbound')`, limit 200 |
| `lastInboundAt`/`lastOutboundAt` | `conversations` row |
| `pendingDraft` | scan `sources/<id>/tasks.jsonl` head-N (commit `0b1caf5f7` — was scanning tail before) for matching unconsumed task, build via `_draft_from_task` |
| `sends` | `outreach_db.list_sends_by_thread` (outreach_send_queue, max 50) |
| `meta` | `outreach_db.get_thread_meta` (outreach.db sqlite-era, possibly migrated) |
| `lead` | dict built straight from `contacts` row (24 fields, mostly Lofty enrichment) |
| `notes` | `sources/<id>/lead-events.jsonl` tail 4000, filtered `event_type='lofty_note'` + `contact_id == thread_id` |
| `tasks` | same JSONL, `event_type='lofty_task'` |
| `activity` | merged from PG `events.kind IN ('classified','parked','unparked','lifecycle_change','note','merge','merge_conflict','pcs_activity','reply_attributed')` AND the same JSONL stream (anything not note/task) |

### 5.2 Hardcoded stubs / empty arrays

- `tasks` (PG `kanban_tasks`) is unused for /leads — drawer reads only from JSONL.
- `notes` (PG `notes` table) is empty — drawer reads only from JSONL.
- `pendingDraft` always sourced from JSONL — there is no PG draft staging table.
- `lane_config`, `outreach_lane_config`, `outreach_thread_meta`, `thread_meta`, `lead_inquiries`, `lead_properties` — all 0 rows, all wired into code paths but never written.
- `deal_contacts` — 0 rows despite 21 deals. The deal↔contact link is on `deals.primary_contact_id` and `deals.lofty_contact_id` directly, not via the link table.

---

## 6. Recent commits — trend analysis

Last 30 commits touching `source_connectors.py`, `reads.py`, `RealEstateHubPages.tsx`, `thread-drawer.tsx`:

```
0b1caf5f7  fix(leads-inbox): scan tasks.jsonl head, not tail, for message drafts
cd33284a5  fix(leads-drawer): strip source-prefix from incoming thread_id
864b2534c  leads: drawer reads from DB (source of truth), not JSONL slice
57c455a5f  leads: per-contact stream lead-events for drawer activity
1b32c1ebb  leads: persist + surface Lofty lead profile (drawer empty-card fix)
efb33245c  elevate_cli/data/reads: overlay private-search buyers JSONL onto DB walk
f224df8f1  composio inbound: retry transient 5xx + explicit fallback-draft flags
8110597ee  0.12.7: tag-driven buyer search panel + Run search trigger
dcb0a3358  0.12.5: /leads profile list pagination (20/50/100)
5e521c851  0.12.4: unblock /leads profile cap (hardcoded 100 → safe_limit)
9a0a072cc  release 0.12.1: Lofty 3-phase sync + iMessage/SMS send routing
8873fe292  leads: per-profile status dropdown replaces skill-handoff buttons
de7958fee thread-drawer: render full email body, not 200-char snippet
3bbcbf7bd ui: thread-drawer modal taller — fixed viewport-relative height
82ab7fd8d S57: thread drawer -> centered modal matching admin kanban
ac5cae235 polish(leads+today): strip 8 border-left accent stripes from RealEstateHubPages
c6ba97cae leads: filter automated senders, preserve drafts across CRM resync, wire Lofty data into detail panel
```

Trend, oldest → newest:
1. **Phase 1 (older)**: cosmetic polish, modal sizing, line-clamping.
2. **Phase 2** (`c6ba97cae`, `1b32c1ebb`, `57c455a5f`, `864b2534c`): the drawer kept rendering empty for fully-enriched Lofty leads. Root cause: legacy JSONL builder did a 4,000-line tail scan that missed older contacts. Fix iteration moved the drawer to DB source-of-truth.
3. **Phase 3** (`cd33284a5`, `0b1caf5f7`): edge cases — prefix duplication from buyer panel, tasks.jsonl head-vs-tail scanning direction.

What keeps breaking:
- **JSONL/DB straddle**. Every "empty card" bug has been a builder reading the wrong layer. The drawer now reads PG for everything except `notes`, `tasks`, `pendingDraft`, `sends`, `meta` — those still hit JSONL or outreach.db, and that boundary is fragile.
- **Source-key prefix on profile-derived thread IDs**. Two different consumers (search-buyers panel + profile list) build `<source>:<thread_key>` strings, the backend has to defensively strip the prefix.

---

## 7. Gaps and rough spots

### 7.1 Identity layer

- **No post-ingest re-link sweep.** Once a conversation is bound to a contact, a later identity addition for a different contact that should have absorbed it never triggers re-linking. (No code searches for this.)
- **xposure-pcs ingest bypasses `add_identity`.** 1,070 of 1,080 contacts have zero identity rows. 1,015 of those have an email matching an existing CRM identity. `lead_signals.graduate_lead_signal` calls `upsert_contact` directly (`lead_signals.py:170-200`).
- **CRM↔Apple phone overlap is zero across same area codes.** 157 apple +1604 vs 213 crm +1604 phones, 26 apple +1250 vs 745 crm +1250, but zero value overlap. Either phone normalization differs between connectors (`+1 604 555-0100` vs `+16045550100`) or these really are different people. Need to spot-check the canonicalizer (`elevate_cli/data/identities.py::_canonicalize`).
- **`identity_conflicts` schema bug.** 6 of 12 rows have `kind='phone'` storing email values (`apple_contacts_backfill.py:169-181` always writes `'phone'`).
- **0 conflicts resolved.** All 12 are open. There's a `POST /api/identity-conflicts/{id}/resolve` endpoint (`web_server.py:4297`) but no UI exposes it (audited the /leads page — no link, no action).
- **No `identity_match_runs` telemetry.** Cannot answer "how many merges happened today" without a diff.
- **`apple_contacts_backfill._add_identity`** never sets `verified=1` even for AddressBook-confirmed handles (line 148, hardcoded `0`).

### 7.2 Activity / events

- **Activity card surfaces tombstone noise.** 534,824 of 534,966 `lifecycle_change` events come from `legacy_backfill` with payload titles like `"Lofty lead synced via Other"` and `"Auto Text Outbound"`. The drawer query (`reads.py:622-635`) doesn't filter on actor — every contact's "Property activity" is buried under CRM tombstones.
- **No pcs_activity rollup.** `pcs_activity` is in the drawer's activity filter set but the events table has **zero rows** with `kind='pcs_activity'`. The xposure-pcs scrape writes `pcs_buyers.searches_json` and `matching_listings_json` but doesn't emit per-listing-view events.

### 7.3 Drafts / sends

- **Drafts pipeline still JSONL-first.** `pendingDraft` is read from `sources/<id>/tasks.jsonl`, not from PG. Recent commit `0b1caf5f7` changed scan direction (head vs tail). `outreach_send_queue` is PG but the upstream draft staging is not.
- **Two parallel status taxonomies in `draft_attempts`**: `pending_approval` (182) and `draft_pending_approval` (5) for the same lifecycle stage.
- **`send_queue` is a VIEW of `outreach_send_queue`** — the table doubling came from the embedded-PG migration and the view still exists for backwards-compat. Either is fine, but the duplicated name in code is a footgun.

### 7.4 Unused tables (0 rows, code-referenced)

`tasks` (PG), `kanban_tasks`, `notes` (PG), `thread_meta`, `outreach_thread_meta`, `lane_config`, `outreach_lane_config`, `lead_inquiries`, `lead_properties`, `deal_contacts`. Each is either over-scoped (built ahead of need) or replaced by an alternate path.

### 7.5 Inactive cron jobs (defined, never run)

`Gmail Doc Router`, `Seller Update`, `Market Stats Watcher` — `enabled=false`, `last_run_at=null`. Any UI that references them shows empty.

### 7.6 UI

- **Buyer-search panel** (`PrivateSearchBuyersList`, line 1603) — works, no prefix bug visible. `lookupProfile` matches by email-then-phone against the in-memory `sourceInbox.profiles`. 1,080 buyers vs 10 xposure identities means most buyers won't match a profile and the row falls back to expand-on-click instead of drawer-open (line 1755).
- **Profile lookups** are O(n) per-frame because `useProfileLookups` (line 1454) builds Maps from `data.sourceInbox.profiles`. Acceptable at current scale.
- **`OutreachLanesGrid`** (line 2305) — reads `lane_config` (empty). Renders "no lanes" state in production.
- **`TemplatesPanel`** (line 3039) — separate fetch from `/api/leads/templates`, not via hub data.

---

## Recommendations (appendix — opinions, not facts)

Ranked by impact-per-token, things I would actually do:

1. **Fix the xposure-pcs identity gap.** In `lead_signals.graduate_lead_signal`, call `_gather_identity_candidates` on the signal's `email`/`phone`/`name` and either (a) `_resolve_via_identities` first and reuse a matched contact, or (b) at minimum write the email/phone as identity rows so the next cross-source pull can merge. Closes 1,015 known dupes.
2. **Filter `legacy_backfill` lifecycle tombstones from the drawer's Activity card.** One-line `AND actor <> 'legacy_backfill'` in `reads.py:622-635`. Activity will go from 99% noise to actual operator-and-AI actions.
3. **Spot-check the phone canonicalizer.** Pull 5 contacts where the Lofty CRM phone and the apple-messages phone are obviously the same person (compare display_name) and confirm `_canonicalize('phone', x)` returns the same string for both. If not, fix the canonicalizer — that single change collapses thousands of duplicate contacts.
4. **Fix `_record_phone_collision` mis-labeling.** `apple_contacts_backfill.py:173` always writes `'phone'`. Inspect the handle shape (`@` → `email`, else `phone`) before insert.
5. **Add a one-shot `identity_relink` migration**: walk every `conversations` row whose contact has an identity that ALSO appears (canonicalized) on a different contact. Don't auto-merge — write to `identity_conflicts` for operator review. Two-row sample is fine as a smoke test before running across 4,340 conversations.
6. **Drop the unused tables OR populate them.** `lane_config`, `outreach_lane_config`, `lead_inquiries`, `lead_properties`, `deal_contacts`, `thread_meta`, `outreach_thread_meta`. Easier to drop than to wire — they're not on the critical path.
7. **Add an `identity_match_runs` table.** One row per `walk_jsonl_source` pass with `source_id`, `candidates`, `merged`, `created_new`, `conflicts_recorded`. Lets the drawer's status pill show "12 leads merged from Lofty in last sync."
8. **Collapse `pending_approval` vs `draft_pending_approval`** in `draft_attempts.status` to one canonical value. Either is fine — pick one and migrate the other.
9. **Decide JSONL vs PG for drafts and notes**. Either move tasks.jsonl/lead-events.jsonl writes into PG (so the drawer is fully PG-backed) or accept the straddle and document it. The current "PG for some cards, JSONL for others" is the source of every recent drawer regression.
