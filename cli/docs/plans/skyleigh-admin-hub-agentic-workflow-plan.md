# Skyleigh Admin Hub — Agentic Workflow Plan

> Companion to `skyleigh-admin-hub-bc-gap-analysis.md`. The gap doc lists what
> *should* fire per stage. This plan describes the **runtime** that makes those
> per-stage actions actually happen, grounded in what Elevate already has.

---

## 0. Repo / runtime split (read this first)

Three locations, two repos. Don't conflate them:

| Location | What it is | Owns |
|---|---|---|
| `Dartagnan98/elevate-agent` at `~/elevate/` | **Agent shell** — generic across clients. The repo this doc lives in. | `AdminKanbanBoard` UI, FastAPI server (`web_server.py`), cron (`cli/cron/`), CRM source connectors, generic skills (`cli/skills/`), the SQLite store + `/api/admin/*` REST + dispatcher + registry **schema** that this plan adds. |
| `Dartagnan98/skyleigh-tools` at `~/skyleigh-tools/` | **Skyleigh client bundle** — per-tenant content. | All 47 skyleigh skills under `.claude/skills/` (`marketing` router + `marketing-mailjet/buffer/render/copy/log/inputs`, `cma` router + 7 sub-skills, `mlc` router + 7 sub-skills, `digisign`, `webforms`, `seller-update-*`, `outreach-*`, `property-lookup`, etc.). Master sheet, BC knowledge, blank forms, mcp-digisign. |
| `~/.elevate/` | **Runtime install dir** (state, not code) | Materialized skill bundle at `skills/skyleigh/`, working dir `tmp/skyleigh-tools/data/marketing/runs/<run>/`, the new `data/skyleigh.db` SQLite store, `cron/jobs.json`, sessions, auth. |

When this plan says "already implemented" — verify which repo. The marketing
chain and DigiSign integration ship in **skyleigh-tools**; the kanban + dispatcher
work ships in **elevate-agent**. Elevate loads skyleigh-tools at runtime via
`skills_hub.py`.

---

## 1. What's actually built (verified, not aspirational)

### Content layer ✅
- 9 provinces normalized to identical layout under
  `~/skyleigh-tools/knowledge/exp-agent-centre/transaction-guide-{prov}/`
- BC = full content. AB/SK/MB/ON/QC/NB/NL/YT mirror the structure.
- Each guide: flat `checklist-*.md` files, `best-practices-topics/`,
  `forms/<slug>/README.md`, `forms/inventory.json` (machine-readable form picker).

### UI layer 🟡
- Admin Hub kanban shipped at
  `cli/web/src/pages/RealEstateHubPages.tsx → AdminKanbanBoard` (line 5490).
- **Target shape:** 2 lanes (Listing / Buyer) × 10 stages per side (Stage 0
  CMA/Lead → Stage 9 Closed), matching Skyleigh's master sheet. The current
  3-swimlane × 5-phase layout is being replaced; `Other Items` swimlane is
  killed and TOP 25 stays as a cross-lane filter strip.
- Card detail panel with collapsible per-stage checklists.
- **Missing:** cards live in local `useState` only. `handleMoveToNext` mutates
  client state; no persistence, no event emission. The kanban does not know the
  server exists.

### Capability layer ✅
- 30+ generic skills under `cli/skills/`.
- **Skyleigh-specific skills already pipelined** at `~/.elevate/skills/skyleigh/`,
  organized as routers + sub-skills with a shared run directory:
  - **`marketing` router** → `marketing-inputs` → `marketing-render` (Playwright)
    → `marketing-copy` → `marketing-buffer` (social) + `marketing-mailjet`
    (email; `MAILJET_API_KEY/SECRET` already wired) → `marketing-log` (Lofty
    note + `knowledge/listings/<slug>-launch.md`).
    Working dir: `~/.elevate/tmp/skyleigh-tools/data/marketing/runs/<run>/`.
  - **`cma` router** → `cma-collect` → `cma-comps` → `cma-photo-analysis` →
    `cma-pricing` → `cma-pdf` → `cma-audit`.
  - **`mlc` router** → `mlc-intake` → `mlc-folder` → `mlc-fill` → `mlc-send` →
    `digisign` → `mlc-loopback` (signed PDF returns).
  - `webforms` (BCREA: DORTS, PNC, BAEC, MLC envelope), `digisign` (DigiSign
    via SkySlope API for signed delivery), `outreach-send` (iMessage + Lofty
    note), `seller-update-*` (5 sub-skills, weekly seller PDFs +
    `seller-update-email`), `property-lookup`, `gmail-doc-router`,
    `showing-time`, `relisting`, `weekly-listing`.
- `cli/elevate_cli/skills_hub.py`, `skill_steps.py`, `template_suggester.py`
  invoke them.
- `cli/elevate_cli/source_connectors.py → sync_lofty_crm_source()` pulls the
  Lofty graph (contacts, leads, threads, activity).

### Execution layer ✅
- Cron storage: `cli/cron/jobs.py` (jobs.json), runner: `cron/scheduler.py`.
- Output: `~/.elevate/cron/output/{job_id}/{ts}.md`.
- Auth gating runs through `auth.py` / `runtime_provider.py`.
- LLM drafts via `template_suggester.py`; fallback drafts via
  `_fallback_draft_for_thread()`.

### External pipelines ✅ (separate process, not yet integrated)
- PCS hot-leads: `~/skyleigh-tools/scripts/`
  (`pcs-leads-scraper.cjs`, `pcs-hot-leads-analyzer.cjs`, `pcs-hot-leads-pdf.cjs`).
- Writes to Lofty, generates PDF. Does **not** create Admin Hub cards.

### Conspicuously missing (none of these exist) ❌
- Card store / Admin Hub server API
- Stage-change / deal-event bus
- Workspace-level `province` setting
- Province-aware content router (`getGuide(province, slug)`)
- Trigger registry (entry / exit / recurring / event)
- Skill invocation bridge from kanban events
- Approval queue surfaced inside card detail
- Adapters for: SkySlope, ShowingTime, DigiSign, MLC pre-fill,
  CMA generator, inspection scheduler, lender notifier

---

## 2. The agent loop we're aiming for

```
┌───────────────────────────────────────────────────────────────┐
│  TRIGGER          ROUTER             SKILL          OUTPUT    │
│  ───────          ──────             ─────          ──────    │
│                                                                │
│  card moves S1→S2 ─┐                                           │
│  cron fires (Mon)  ├─→ stage_action_  ─→ skill run ─→ artifact│
│  Lofty event       │   registry            (cron job)   (.md) │
│  PCS hot-lead      │                                      │   │
│  manual run        │                                      ▼   │
│                    │                              ┌──────────┐│
│  workspace.        │                              │ approval ││
│  province ─────────┘                              │  queue   ││
│  (BC | AB | …)                                    └────┬─────┘│
│                                                        ▼      │
│                                                  card detail  │
│                                                  panel updates│
└───────────────────────────────────────────────────────────────┘
```

Six primitives we need to build (everything else is wiring):

| # | Primitive | Where it lives |
|---|---|---|
| A | **Workspace settings** with `province: "BC"` + brokerage/agent fields | `~/.elevate/state/workspace.json` + UI in `ConfigPage.tsx` |
| B | **Deal store** — SQLite + JSONL event log | `~/.elevate/data/skyleigh.db` + `~/.elevate/data/deal-events.jsonl` |
| C | **Card store API** | new `cli/elevate_cli/admin_cards.py` + REST under `/api/admin/deals`, `/api/admin/deals/:id/move`, `/api/admin/deals/:id/toggle` |
| D | **Stage action registry** | SQLite-backed (`admin_action_registry` table); YAML kept only as seed/dev fixture. Each row keys on `(side, stage, trigger, condition)` |
| E | **Province content router** | new `cli/elevate_cli/province_guide.py` — `get_lifecycle_steps`, `get_form`, `get_conditional_docs(toggles)` reads from SQLite reference tables seeded from `~/skyleigh-tools/knowledge/exp-agent-centre/transaction-guide-{prov}/` and the master sheet |
| F | **Action dispatcher** | new `cli/elevate_cli/admin_actions/dispatch.py` — producer of `admin_action_runs` rows + cron jobs (via `cron.jobs.create_job(...)`). Not a second skill runner. |

The kanban changes from "local React state" to "thin client over the deal store with optimistic updates". Every stage change, toggle change, or pending-item completion emits an event into `deal_events`, which the dispatcher consumes.

---

## 3. Trigger taxonomy (per-stage action types)

Each entry in the action registry has `{side, stage, trigger, condition, skill, inputs, output_target}`.

| Trigger | Fires on | Example |
|---|---|---|
| `stage_entry` | deal stage advances to N | Stage 1 entry → DORTS+PNC+MLC Webforms envelope sent |
| `stage_exit` | deal leaves stage N | Stage 3 exit → AI photo analysis fires |
| `toggle_change` | a deal toggle flips | `multiple_offers = Yes` → BCFSA Multiple Offer Acknowledgement queued |
| `recurring` | cron schedule + deal-in-stage filter | Mon 9am for every Stage 5 deal → ShowingTime digest |
| `time_offset` | "X days before/after a date field" | subject-removal -7d → reminder; possession +1d → key handover ping |
| `external_event` | webhook or polled signal | Webforms signed → flip pending_item to Done |
| `manual` | button in card detail panel | "Run CMA follow-up draft" |

**Toggle set on each deal (19 fields, drives Conditional Docs)**:
- Enums (7): `signing_authority`, `fintrac_form_type`, `listing_track`, `property_subtype`, `estate_status`, `transaction_type`, `listing_type`
- Yes/No (12): `pep`, `tenanted`, `poa_signing`, `corporate`, `has_suite`, `multiple_offers`, `family_member`, `dual_rep`, `unrepresented_other_side`, `lockbox`, `delayed_offer`, `sale_of_buyers_property`

When a toggle flips, dispatcher reads `conditional_docs` for `(province, trigger_key, trigger_value)` and queues the matching docs/actions as `pending_items` on that deal.

Conditions can read: any toggle field, `deal.province`, `deal.side`, `deal.current_stage`, contact tags, Lofty stage. Lets one registry serve all 9 provinces — only the **content references** swap (E), not the actions.

---

## 4. Phased build (3 phases, ~2 weeks each at current pace)

### Phase A — Make the kanban real (foundation, no agentic value yet)
**Goal:** cards persist, server knows stages, every stage change emits an event.

1. `deals` + `deal_events` tables in `$ELEVATE_HOME/data/operational.db` (the
   central app DB; see `data/migrations/0003_admin_hub_deals.sql`). Mirrors
   the templates/contacts pattern already in `data/`.
2. REST: `GET/POST /api/admin/deals`, `POST /api/admin/deals/:id/move`,
   `POST /api/admin/deals/:id/toggle`.
3. Replace `ADMIN_CARDS_SEED` + `setCards` with `useAdminDeals()` hook.
4. Workspace settings UI: province dropdown (defaults to BC for Skyleigh).
5. `province_guide.py` — `get_checklist(province, slug) → markdown`,
   `get_form(province, code) → {name, pages, image_urls}`,
   `list_best_practices(province) → [...]`. Resolves the customer tools root
   via existing `sources.tools_root` config (not a hardcoded `~/skyleigh-tools`).
6. Card detail panel renders **live** checklist from `province_guide` instead
   of `ADMIN_PHASE_CHECKLISTS` constant. Same UI, content now province-aware.

**Exit criteria:** Skyleigh can open the kanban in two browsers, move a card,
both reflect the change. Province dropdown swaps the checklist content.

### Phase B — Action dispatcher + first 3 high-leverage triggers
**Goal:** events drive skills. Real automation surfaces in the card.

> **Email tooling note:** the master sheet says "Flodesk" on Coming Soon, Just Listed, Moving Checklist, and Sold blasts. Skyleigh's Flodesk subscription was canceled (see `subscription-audit-2026-04-27.md`). Email is now **Mailjet via the Elevate `marketing` skill** — the seed script normalizes lifecycle_steps rows where `tool_or_form = 'Flodesk'` to `marketing skill (Mailjet)`. Templates (Coming Soon, Just Listed, Moving Checklist, Sold) live inside the marketing skill, not in a separate ESP.

7. `admin_action_registry` table — declarative trigger definitions. Each row
   keys on `(side, stage, trigger, condition_json)` and maps to a **router
   skill** + skill_args_json (e.g. `marketing` with
   `{"phase":"just_listed"}` — `phase` here is the marketing skill's existing
   sub-mode arg name, not the registry primary key). YAML is kept as a
   seed/dev fixture only; runtime mutations go through `/api/admin/actions/*`.
   Dispatcher does NOT call sub-skills directly — routers already chain
   their children via the shared `run/` directory pattern.
8. `admin_actions/dispatch.py` — listens for `deal_events`, evaluates
   conditions, persists `admin_action_runs` rows, then spawns cron jobs via
   `cron.jobs.create_job(skills=[router_skill], prompt=rendered_deal_context,
   repeat=1, deliver="local", workdir=...)` (one-shot for
   `stage_entry`/`stage_exit`/`toggle_change`/`time_offset`/`external_event`/`manual`,
   persistent for `recurring`). Each run pins a `run_id` back onto the event
   so the kanban Outputs tab can link to `data/marketing/runs/<run>/` etc.
9. **Three triggers live first** (highest impact, all skills already exist):
    - **Stage 4 → Stage 5 entry → `marketing` router with `phase=just_listed`.**
      Chains `marketing-inputs → marketing-render → marketing-copy →
      marketing-buffer + marketing-mailjet → marketing-log`. Closes the loop:
      buffer schedules social, mailjet schedules email blast, log writes
      Lofty note + `knowledge/listings/<slug>-launch.md`.
    - **Stage 0 entry (CMA requested) → `cma` router.** Full chain produces
      cma-pdf and audits it. Existing `cma-audit` already enforces Skyleigh's
      pricing review rules.
    - **Stage 5+ recurring (weekly) → `seller-update-report` → `seller-update-email`.**
      Per-listing PDF for the seller. Already integrates ShowingTime + Xposure
      prospecting + Lofty messages where available; falls back gracefully when
      ShowingTime API isn't there yet.
10. Each router run lands its artifacts in the deal's "Outputs" tab (new
    sub-tab in `AdminCardDetailPanel`) keyed off `run_id`. Outbound comms
    drafts (mailjet, outreach-send) hit the existing approval queue when
    `approval_required: true`. Internal artifacts (CMA PDF, seller-update PDF,
    launch-log) auto-publish to the card.

**Exit criteria:** Drop a card into Stage 0 (CMA requested) and see a CMA
draft appear in that card's Outputs tab within 60 seconds. Approve or edit,
send. (Stage numbers in the registry must match the 10-stage UI model;
"S0" / Stage 0 is the same row everywhere.)

### Phase C — Wire remaining routers + add the missing adapters
**Goal:** every stage transition has a router-mapped action; gaps get filled.

11. **Stage 1 entry → `mlc` router** (which calls `mlc-fill` → `mlc-send` →
    `digisign`). Already implemented via `digisign` skill (DigiSign through
    SkySlope API, fills BCREA forms with deal data). Just wire the trigger.
12. **Toggle-driven `webforms` runs.** When `pep=Yes`, `corporate=Yes`,
    `poa_signing=Yes`, etc. flips on a deal, dispatcher calls `webforms`
    with the matching form code from `conditional_docs` table.
13. **Stage 7 (subject removal) → `marketing` with `phase=moving_checklist`**
    (mailjet only, no buffer). +1d auto.
14. **Stage 9 entry → `marketing` with `phase=sold_update`** (full chain:
    Sold graphic + email + log).
15. **SkySlope adapter** — read-only first (poll missing-docs list, surface
    as `pending_items` on the deal). Write later.
16. **Possession-date timer set** — schedules Stage 9+ follow-ups (key
    handoff, +7d check-in, +30d archive, +1yr anniversary). Uses existing
    `outreach-send` for the +1yr message.

---

## 5. Open decisions (need Dartagnan's call)

| # | Decision | Why it matters |
|---|---|---|
| 1 | **Action registry format** — YAML vs Python decorators | YAML is editable by non-devs (Skyleigh could tune triggers later); decorators give type-safety and refactor support. Default: YAML. |
| 2 | **Card store backend** — JSONL append log vs Supabase | JSONL matches existing `lead-events.jsonl` pattern, zero new infra. Supabase is multi-device but adds auth complexity. Default: JSONL for Skyleigh-only; revisit if RAgent multi-tenant lands. |
| 3 | ~~E-sign vendor~~ | **RESOLVED**: `webforms` skill handles BCREA form fill, `digisign` skill (DigiSign via SkySlope API) handles signed delivery. Already implemented at `~/.elevate/skills/skyleigh/{webforms,digisign}/`. No vendor decision needed. |
| 4 | **Approval gate default** — every output gated, or only outbound comms | Drafts → always gated (matches `/leads` pattern). Internal artifacts (CMA comp tables, deal summaries) → auto-publish to card. Default: gate outbound only. |
| 5 | **PCS card-spawn dedupe** — one card per buyer, or one per active search | Buyer-level (one card, multi-search children) reduces clutter. Default: buyer-level. |

---

## 6. Province portability checkpoint

Once Phase A ships, onboarding a second-province agent (e.g. an Alberta agent)
costs:
- New workspace, set `province: "AB"`. Done.

Onboarding a province where the registry needs province-specific actions
(rare — most are content-driven) costs:
- Add `province: ["AB"]` filter on registry entries that differ.

The shape of the kanban doesn't change. That's the point.

---

## 7. What would unblock the build right now

- **Codex auth** (still broken — blocks `template_suggester` LLM calls in cron).
- **eXp e-sign vendor confirmation** from Skyleigh (Webforms vs DigiSign vs Authentisign).
- **Decision on registry format** (Q1 above) — small but blocks Phase B start.
- **One concrete entry point** to start Phase A: do we start with the card
  store API, or with the workspace `province` setting + content router? Both
  are independent and ~1 day each — recommend doing them in parallel.
