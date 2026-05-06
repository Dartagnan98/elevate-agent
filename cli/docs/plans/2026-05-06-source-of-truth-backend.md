# Source-of-Truth Backend — Plan

Date: 2026-05-06
Status: planning

## Why this exists

The Skyleigh Admin Hub kanban (PR-3) shows 10 stages × 2 sides with checklists,
toggles, and conditions. Stage entry already fires `action_runs` rows via
`evaluate()` in `elevate_cli/data/dispatch.py:507`, and the runtime hands those
off to cron jobs that launch Codex with the named skill.

The skill library is deep (CMA, MLC, DigiSign, marketing, seller-updates,
showing-time, webforms, property-lookup, etc.). The browser-use harness exists
(`elevate_cli/harness/`) with durable runs, checkpointing, allowed-domains
sandboxing, and content-hashed source snapshots.

The pieces are there. What's missing is the spine that lets a stage move on the
board cause an agent to actually run a skill, attach what it produced to the
deal, and either flip the next checklist item or wait for human approval — all
without anything getting lost.

This plan is that spine.

## What we already have (don't rebuild)

**Backend**
- `operational.db` with `contacts`, `conversations`, `events`, `deals`,
  `action_runs`, `templates`, `deal_events`
- Action registry + run rows (PR-2)
- `evaluate()` dispatcher with `stage_entry` and `toggle_change` triggers
- Cron handoff to Codex with skill name + args
- Browser-use harness with `harness_runs`, `harness_events`, `source_snapshots`
- 25+ real-estate skills under `~/.elevate/skills/skyleigh/`
- Real APIs already in use: Gmail (Composio), Mailjet, Buffer, Lofty CRM

**Frontend**
- Admin Hub kanban (PR-3): 10 stages × 2 sides, checklists, toggles, drag-and-drop
- New deal dialog with contact picker, property fields, notes auto-fill
- /leads approval queue pattern (reusable for action_runs)

## The actual gap

1. **No deal context blob.** Skills start from scratch every run.
2. **No callback.** `action_runs` sit `queued` forever; nothing closes the loop.
3. **No standard skill output.** Every skill ad-libs.
4. **No place for outputs.** No `deal_attachments` table.
5. **No date fields on deals.** Can't track subject removal / completion / possession.
6. **No date-based trigger.** Half the checklist is calendar-driven.
7. **No co-contact roles.** Lawyer, lender, inspector, photographer have nowhere to live.
8. **No approval inbox** for action_runs in `waiting_human`.
9. **No bridge between `action_runs` and `harness_runs`** — browser jobs can't be spawned by stage moves.
10. Three real APIs not yet wired: **Google Calendar**, **Twilio SMS**, **Authentisign**.

## The plan

Five tracks, ordered by what unlocks the most checkboxes per unit of work.

### Track 1 — Schema (1 day)

Migration to grow the deal record into the source of truth.

**`deals` adds columns:**
- Dates: `listing_date`, `offer_date`, `subject_removal_date`, `deposit_due_date`,
  `completion_date`, `possession_date`, `anniversary_date`
- Money: `list_price`, `offer_price`, `deposit_amount`, `commission_pct`
- Property: `mls_number`, `legal_description`, `lot_size_sqft`, `year_built`
- Status timestamps: `deposit_in_trust_at`, `listing_published_at`,
  `offer_accepted_at`, `subjects_removed_at`, `completed_at`

**New tables:**
- `deal_contacts` — `deal_id`, `role` (lawyer/lender/inspector/photographer/strata/coop_agent/spouse), `contact_id`, `notes`
- `deal_attachments` — `deal_id`, `kind` (mlc_pdf, signed_envelope, cma_report, listing_photos, offer_pdf, deposit_receipt, inspection_report, strata_docs, lawyer_package), `file_path`, `source_run_id`, `source_snapshot_id` (links to harness snapshots), `created_at`
- Add `harness_run_id` column to `action_runs` for the bridge

**Data helpers in `elevate_cli/data/deals.py`:**
- `add_deal_contact(deal_id, role, contact_id, notes)`
- `list_deal_contacts(deal_id, role=None)`
- `add_deal_attachment(deal_id, kind, file_path, source_run_id=None, source_snapshot_id=None)`
- `list_deal_attachments(deal_id, kind=None)`
- `set_deal_dates(deal_id, **dates)` / `set_deal_money(deal_id, **fields)`

### Track 2 — The two endpoints (1 day)

The whole runtime collapses to two HTTP calls every skill makes.

**`GET /api/deals/:id/context`** → single blob:
```json
{
  "deal": { "id", "side", "currentStage", "title", "address", ...all date/money/status fields },
  "primaryContact": { ...full contact },
  "coContacts": [ { role, contact } ],
  "conditions": { signing_authority, listing_type, multiple_offers, ... },
  "checklist": { stageNumber: { itemId: completed }, ... },
  "attachments": [ { kind, file_path, created_at } ],
  "priorRuns": [ { skill, status, completed_at, artifacts } ]
}
```

**`POST /api/deals/:id/runs/:run_id/result`** with:
```json
{
  "status": "completed | failed | waiting_human | waiting_external",
  "artifacts": [ { kind, file_path, summary } ],
  "next_tasks": [ { skill, args, scheduled_for? } ],
  "human_prompt": { "title", "body", "fields"? },
  "error"?: "..."
}
```

This single endpoint:
- Flips the run row status
- Attaches artifacts to `deal_attachments`
- Inserts new queued action_runs from `next_tasks`
- Routes `waiting_human` to the approval inbox
- Logs to `deal_events`

### Track 3 — Bridge action_runs ↔ harness_runs (0.5 day)

`_spawn_cron_job` in `data/dispatch.py:602` becomes `_spawn_run`:
- Look up skill metadata (cron_skill vs browser_skill)
- For cron skills: existing path, hand to `cron.jobs.create_job`
- For browser skills: create `HarnessRun` with allowed_domains + account_context from the skill manifest, input from the deal context blob, link `action_run.harness_run_id`
- Either way, the run-result endpoint closes both kinds of runs identically

Skill manifest gets one new field:
```yaml
runtime: cron | browser
allowed_domains: [skyslope.com, showingtime.com, ...]   # browser only
```

### Track 4 — Approval inbox + date sweeper (1 day)

**Approval inbox** — new tab in Admin Hub, reads:
```sql
SELECT * FROM action_runs WHERE status IN ('waiting_human', 'failed')
```
Reuse `/leads` row pattern. Approve / edit / reject buttons resolve the run via the same write endpoint.

**Date sweeper** — daily cron job that scans deal date fields, evaluates date-relative rules, queues runs:
- New trigger type `date_relative` in the registry
- Schema: `{ field: 'subject_removal_date', offset_days: -3 }` → fires 3 days before
- One sweep per day at 6am Pacific covers the whole pipeline

### Track 5 — Three real APIs (incremental, post-spine)

In order of unlock value:

1. **Google Calendar OAuth** — open houses, showings, inspections, walkthroughs, key handoffs (5 stages depend on it)
2. **Twilio SMS** — every "send seller / send buyer" item that isn't email
3. **Authentisign** — S3 listing bottleneck, every listing flows through here

These slot in as cron-runtime skills with the same input/output contract as everything else. No runtime changes needed.

## Build order with rough estimates

| Track | Days | Unlocks |
|---|---|---|
| 1. Schema | 1 | ~30% of checklist items become storable |
| 2. Two endpoints | 1 | Every existing skill becomes deal-aware |
| 3. Bridge | 0.5 | Browser skills spawnable from stage moves |
| 4. Approval + date sweeper | 1 | Human-in-the-loop + calendar-driven flows |
| **Spine total** | **3.5 days** | — |
| 5a. Calendar | 0.5 | 5 stages worth of scheduling |
| 5b. Twilio | 0.5 | SMS comms channel |
| 5c. Authentisign | 1 | S3 listing unblock |
| **APIs total** | **2 days** | — |

Spine first, APIs second. After the spine, every new connector or skill is incremental.

## Dogfood plan

Once spine ships, run one full listing-side flow end-to-end on a test deal:

1. Create deal in dialog → primary contact pulled from CRM
2. Move S0 → S1: agent fires `cma-collect` skill, returns CMA report PDF, attaches to deal, queues `cma-pdf` next
3. Move S1 → S2: `mlc-intake` skill collects names/dates/price, writes back to deal record
4. Move S2 → S3: `mlc-fill` produces MLC PDF (browser skill if SkySlope-hosted, otherwise PDF skill), `digisign-send` queues for human approval before send
5. Approve the DigiSign envelope in the inbox → DocuSign sends → webhook resolves the waiting_external run → S3 checklist clears → S4 fires marketing skills
6. Date sweeper notices `subject_removal_date - 3` → fires reminder draft

If that round-trip works on one deal, we know the spine is right.

## Open questions

- **Skill manifest format.** Today skills are markdown SKILL.md only. Adding `runtime` + `allowed_domains` either as YAML frontmatter in SKILL.md or a sidecar `manifest.yaml`. Frontmatter is less invasive.
- **Per-user vs per-deal calendar.** Skyleigh's calendar vs deal calendar. Probably user calendar with deal-tagged events.
- **Webhook ingress for Authentisign / DocuSign.** Need a public endpoint. Tunnel via cortextos infra or stand up a small public webhook receiver?
- **What about the buyer side first?** Listing-side dogfood is heavier (paperwork, marketing). Buyer-side might be a faster first pass since it's mostly comms + scheduling.
