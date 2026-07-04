---
name: "deal-onboarding"
description: "Build or refresh an accurate deal score card for every in-flight deal a user has. Use when the user says 'onboard my deals', 'set up my deal cards', 'import my deals', 'build score cards for my pipeline', or 'refresh my deal cards', or during the onboarding wizard's deal-population step. Discovers deals across the Master Sheet, CRM transactions, MLS active listings, Drive folders, and recently signed contracts; infers each deal's current stage from evidence; and populates score-card fields group-by-group using the admin deal API. Never guesses prices, dates, or legal info — leaves gaps blank and adds a card reminder instead."
category: "real-estate-admin"
access:
  entitlement: "real_estate_admin"
---

# Deal Onboarding — build accurate score cards for a user's in-flight deals

Stand up (or refresh) one score card per deal a user already has in flight, at whatever stage each deal is in — a brand-new CMA, a live listing, an accepted offer mid-subject-removal, a deal closing next week. This runs after the agent-onboarding wizard (`cli/web/src/pages/agent-onboarding/`) has the user set up; it complements that wizard by populating the deal cards.

## CRITICAL — read first

1. **Load the tenant's setup FIRST (Step 0).** `GET /api/admin/setup` and resolve this tenant's province/market/board, CRM, MLS, compliance, Drive, forms, signing providers + their logins, commission notes, regional memory, and approval policy. **Every downstream step uses THESE values, never hardcoded ones.** This skill must NOT assume any one realtor's specific sources — no hardcoded sheet ID, no hardcoded board, no hardcoded province default, no hardcoded CRM key, no hardcoded Drive folder — unless they come from this tenant's setup. The IDs/keys/board in `knowledge/deals/card-field-sources.md` are one realtor's instance shown as a worked example, not defaults.
2. **Read `lessons.md` BEFORE every run.** Apply every lesson. Append a new lesson AFTER every run or correction. Format: `[date] | what happened | rule/insight`.
3. **Read `knowledge/deals/card-field-sources.md` BEFORE populating any field.** It is the authoritative field → source map (one realtor's instance as a worked example — the actual source IDs/keys come from the tenant setup in Step 0). This skill references it group-by-group; do not improvise a source.
4. **Hard rules (durable):**
   - **Write extra-toggle fields under the BARE key the card reads** (`pid`, `bedrooms`, `checklistManual`, `skyslopeMissing`) -- NEVER a namespaced UI key (`core.pid`, `extra.checklistManual`). The backend stores the field name verbatim, so a prefixed write lands on a key the card cannot read and the value is invisible (this is what made fields look "wiped" off cards). See `card-field-sources.md` "Storage-key convention".
   - **Never fabricate a price, date, legal description, or PID.** Pull it verbatim from the signed document (CPS / MLC / SR / Title). If the doc isn't available, leave the field blank and add a card reminder naming the doc to pull. (See lessons.)
   - **Infer stage from evidence — never assume Stage 0.** A user onboarding mid-pipeline has live listings and firm deals. Use the stage-inference checklist (Step 3).
   - **Toggles drive required legal docs — never guess them.** Ask the Stage-1 branching questions (`coverage-audit.md` §2/§4). If unanswerable, set the conservative default (No / None / Individual / Standard) and flag.
   - **CRM-sync and Master-sheet-sync field groups are sync-managed, not intake.** Don't ask the user for a `crm_transaction_id` or invent a `source_row_id`.
   - **Login-gated data → `waiting_human`, never a silent blank.** Anything behind a login with no API (MLS year/lot/PID via the tenant's `mlsProvider` portal + MFA; compliance/SkySlope buyer-side money via `complianceProvider`; commission inside a signed MLC) must be surfaced as a `waiting_human` card item naming the exact source. Never leave it as an unflagged blank.
5. **Approval gate = explicit dry-run.** Build the proposed card for EVERY discovered deal (side, inferred stage, the fields it WOULD set + their sources, and the flagged gaps), present that summary for the user to confirm, and only write to the card DB AFTER they approve. Never bulk-write silently on a first run. Anything that would send/sign/email is out of scope here — flag it as a next task instead.

## What this skill does

1. Discovers every in-flight deal the user has, across all sources.
2. For each deal, infers `side` and `current_stage` from the evidence.
3. Creates (or updates) the deal card and populates its fields group-by-group from `card-field-sources.md`, using the admin deal API.
4. Sets the Stage-1 toggles by asking the branching questions when not derivable.
5. Leaves every unavailable field blank and records a reminder/waiting item rather than guessing.
6. Closes through `admin-result-writer`.

## What this skill does NOT do

- Does NOT send anything (no DigiSign, no email, no Buffer). Sends are surfaced as next tasks.
- Does NOT fabricate prices, dates, or legal info to "complete" a card.
- Does NOT push to the tenant's deal source or CRM — those flow the other way (read source → card). Sheet/CRM sync fields are written by their sync layers.
- Does NOT advance a deal past its real evidence-supported stage to look further along.

---

## Step 0 — Load the tenant's setup (ALWAYS FIRST)

Before discovery, before any source touch: `GET /api/admin/setup` and read the tenant's `AdminSetupDraft`. Resolve and hold these for the rest of the run — every downstream step uses THESE, never hardcoded values:

- **Jurisdiction:** `province`, `market`, `boardMemberships` (→ `board`), `regionalMemory`.
- **CRM:** `crmProvider` + how it's reached (its connector / API). The deal source for contacts and leads.
- **MLS:** `mlsProvider` + `mlsLoginUrl` / `mlsLoginEmail` / `mlsLoginPassword` (login-gated; needs MFA per `browserWorkflowNotes`).
- **Compliance:** `complianceProvider` + `complianceLoginUrl` / `complianceLoginEmail` / `complianceLoginPassword` (e.g. SkySlope — typically no API, portal-only).
- **Drive:** `driveProvider` + `defaultFolderPattern` (how this tenant's deal folders are named/structured).
- **Forms / signing:** `formsProvider`, `signingProvider`, `showingProvider` (+ its login), `fintracProvider`.
- **Money / policy:** `commissionNotes`, `servicesSchedule`, `approvalPolicy`, `approvalChannel`, `managingBrokerEmail`.
- **Identity:** `realtorLegalName`, `licenseName`, `brokerageName`, `teamName`.

**Rules:**
- Use these resolved values everywhere below. Do NOT assume a hardcoded sheet ID, a hardcoded board, a hardcoded province default, a hardcoded CRM key, or a hardcoded Drive folder name unless they come from THIS tenant's setup.
- If a provider field is blank/unconfigured, **skip that source and note it** (e.g. "no `complianceProvider` configured — compliance docs skipped"). A blank provider is not an error.
- `knowledge/deals/card-field-sources.md` is one realtor's instance as a worked example. Read it for the field → source *shape*, but substitute this tenant's resolved sources for every concrete ID/key/board/folder.

## Step 1 — Discover the user's in-flight deals

Sweep the tenant's configured sources (from Step 0) in order, dedup by address + MLS# + primary contact. These map to the 8-system shape in `knowledge/listings/data-sources.md`, but use the TENANT'S providers, not any one realtor's specific instance.

1. **The tenant's deal source / Master Sheet** — if the tenant has a master deal sheet/source configured, read its active-listing and buyer-deal rows. Each non-empty row is a candidate deal; the tab/side column tells you `side`. This is usually the richest single source — start here when present.
2. **The tenant's `crmProvider` (e.g. Lofty)** — pull the FULL contact/lead list with pagination (see Step 1a), not a shallow single batch. Any contact tagged as an active seller/buyer or carrying an in-flight transaction is a candidate. For Lofty, `?q=` is unreliable — pull all + filter locally.
3. **The tenant's `mlsProvider` (e.g. Xposure)** — the user's live listings under their MLS account (login-gated). Each active MLS# the user owns is a listing-side deal at ≥ Listing Live.
4. **The tenant's `driveProvider` folders** — address-based folders matching the tenant's `defaultFolderPattern`. A folder with signed docs (MLC / CPS) is a deal even if it's missing from the deal source.
5. **Recently signed contracts** (Gmail / the tenant's `signingProvider`) — recent inbound signed PDFs that don't map to a known card — surface as new deals.

If a source's provider is unconfigured (Step 0), skip it and note the skip; don't fail the run.

Build a deduped candidate list: `{ address, mls_number?, side, primary_contact?, source(s), evidence[] }`. Note which sources corroborate each — more corroboration = higher confidence in the stage inference.

### Step 1b — Reconcile sources against the board (find MISSING cards)

The audit is NOT just hydrating cards that already exist. It MUST reconcile **each source system against the existing cards** and create a card for anything that has a file/listing/folder but no card:

- **Match every candidate** (from SkySlope transactions, the `complianceProvider`/Drive folders, MLS active listings, the listings sheet, recent signed contracts) against the existing deals by MLS# then normalized address. **Anything present in a source but with NO matching card is a MISSING card** — create it (Step 4). Hydrating only the cards that already exist, without this source-vs-board sweep, is an INCOMPLETE audit (this is exactly how a real active listing with a Drive folder + an active MLS listing sat off the board in an earlier run).
- **Active/in-flight only.** A source entry only counts as a missing card if the deal is still **active/in-flight**. A SkySlope file or Drive folder for a deal that **closed in a prior year is NOT a missing card** (a listing that closed the prior year correctly does not get a current card). Check the transaction/listing status (active vs closed/expired) before flagging; if it's closed, skip it (or create it as `status='closed'` for archive only, never as active).

### Step 1a — Robust CRM contact matching (full scan, never one page)

Do NOT give up after one page of CRM results — a shallow single-batch search misses contacts (this exact bug missed a real contact plus 5 others in the first audit). Pull the FULL list and match each deal's client by name AND cross-check street address / email.

- **Lofty:** `GET https://api.chime.me/v1.0/leads`, header `Authorization: token <key>`, `pageSize=200`, paginate via `data._metadata.scrollId` until exhausted. Lead id field is `leadId`. Match each deal's client by name, then confirm with street address and/or email — names alone collide.
- **Other CRM providers:** use the tenant's `crmProvider` connector with the equivalent full-scan + cross-check (name + address + email). Never stop at the first page.

## Step 2 — Per deal: confirm the side

Read it off the source: Master Sheet tab (Active Listings = `listing`, Buyer Deals = `buyer`), or the CPS designated-agent block (who the user represents). If genuinely ambiguous, ask one short question. `side` is required to create the card.

## Step 3 — Per deal: infer the current stage from evidence

**Never default to Stage 0.** Map the strongest evidence present to a stage. Use the highest stage the evidence actually supports (don't over-advance).

### Listing side (0 CMA → 9 Closed)

| Evidence present | current_stage |
|---|---|
| Only an address + seller name, no MLS#, no signed MLC, maybe a CMA/appointment | 0 — CMA / Prospect |
| Listing appointment booked / seller package sent, engagement starting | 1 — Listing Initiated |
| Signed MLC / DORTS / PNC in Drive, no MLS# yet | 2 — Documents Signed |
| Photos in Drive `Photos/`, listing not yet on MLS | 3 — Photos Ready |
| Listing entered in Xposure but not live / incomplete | 4 — MLS Entry |
| Live MLS# resolves on Xposure, list price public | 5 — Listing Live |
| Fully-signed CPS in Drive (accepted offer), subjects still pending | 6 — Accepted Offer |
| Final Subject Removal form signed | 7 — Subject Removal |
| Subjects out + completion/possession dates set, pre-completion | 8 — Closing |
| Deal Sheet final, completed/possession passed | 9 — Closed (status → closed) |

### Buyer side (0 Buyer Lead → 9 Closed)

| Evidence present | current_stage |
|---|---|
| Lead exists, no pre-approval, no BAEC | 0 — Buyer Lead |
| Pre-approval / lender confirmed | 1 — Pre-Approval |
| Signed BAEC, actively searching | 2 — Active Search |
| CPS drafted (webforms) not yet sent | 3 — Offer Drafted |
| Offer sent to listing side, awaiting response | 4 — Offer Sent |
| Fully-signed CPS (accepted) | 5 — Accepted Offer |
| Final Subject Removal signed | 6 — Subject Removal |
| Subjects out, firm, conveyance started | 7 — Firm / Conveyance |
| Completion/possession set, pre-close | 8 — Closing |
| Completed | 9 — Closed (status → closed) |

Rule of thumb: **MLS# present ⇒ listing is ≥ Listing Live; signed CPS ⇒ ≥ Accepted Offer; signed final SR ⇒ ≥ Subject Removal.** Absence of a higher-stage artifact (e.g. no MLS#) is itself a signal — don't fill `mls_number` to force a stage.

## Step 4 — Per deal: create/update the card + populate fields

Use the admin deal API the bundle exposes (paths the board itself uses, so gates/timestamps stay consistent):

- **Create:** `POST /api/admin/deals` — body `{ title, side, province?, board?, market?, currentStage, primaryContactId?, loftyContactId?, listingAddress?, fields? }`. Returns the deal with `id`. (If a card already exists for this deal — refresh mode — skip create and update in place.)
- **Move stage:** `POST /api/admin/deals/{id}/move` — `{ "toStage": <n>, "force"?: bool }`. Use the inferred stage from Step 3. Honours phase gates (409 `DealPhaseGateBlocked` if a gate blocks the move — don't force past a real gate; record it as a reminder).
- **Set a toggle:** `POST /api/admin/deals/{id}/toggle` — `{ "field": "<toggle>", "value": <v> }`.
- **Write fields:** `POST /api/deals/{id}/fields` — `{ "fields": { ... } }` for dates/money/property/identity values. (Or pass `fields` on create.)
- **Status:** `POST /api/admin/deals/{id}/status` — `{ "status": "active|closed|archived" }`. New in-flight = `active`; only set `closed` for stage-9 completed deals.
- **Read context:** `GET /api/deals/{id}/context` for the per-stage required-document context (province-aware) when deciding what's still open.

Populate group-by-group, sourcing each field per `knowledge/deals/card-field-sources.md`:

1. **Group 1 — Identity/routing:** set on create (`title`, `side`, `province`, `board`, `market`, `listingAddress`, `primaryContactId`/`loftyContactId`). Pull `province` / `board` / `market` from the **Step 0 tenant setup** (`province`, `boardMemberships`, `market`) — never default to BC/AIR. `mls_number` only if the listing is entered.
2. **Group 2 — Toggles:** ask the Stage-1 branching questions (Step 5); set via `/toggle`. Derive `fintrac_form_type` from `signing_authority`.
3. **Group 3 — Dates:** pull verbatim from the signed CPS/MLC/SR/Title docs in the tenant's `driveProvider` / `complianceProvider`. DB-auto timestamps are never set by hand. Buyer-side money/dates that live only behind the `complianceProvider` portal (no API) are **`waiting_human`** items naming that portal — not silent blanks.
4. **Group 4 — Money:** `list_price` (MLS/MLC), `offer_price`/`deposit_amount` (CPS), `commission_pct` = the **total** listing rate (MLC/Deal Sheet). **`gci` = the commission WE KEEP, NEVER the total, and only once there's an accepted offer:** listing side = (total listing commission − the cooperating commission the MLC offers the buyer's brokerage) on the sale price; buyer side = the cooperating commission shown on the **MLS of the property bought** on the purchase price. Read the listing/cooperating split from the signed MLC (or eXp Deal Sheet) — never assume the split. The MLC is login-gated/inside a signed PDF; if it can't be read, the split is a **`waiting_human`** item naming the signed MLC, not a guess. No accepted offer ⇒ leave `gci` blank.
5. **Group 5 — Property:** `legal_description` verbatim from Title/MLS print; `lot_size_sqft`/`year_built` from MLS/Assessment (these are often login-gated behind the `mlsProvider` portal + MFA — if unread, flag `waiting_human`, don't blank-silently). **Normalize the sub-type first (Step 4a).** **Conditional fields by sub-type** (set via `/toggle`, render on the card per `card-field-sources.md`): for **strata** sub-types (`Strata` / `Bareland-Strata` / `Bareland-Strata-Mobile`) set `strataFee` + `strataPlan`; for **mobile/manufactured** sub-types (`Mobile` / `Bareland-Strata-Mobile`) set `padRent` + the MHR registry (`unitMake`, `unitModel`, `unitYear`, `serialNo`, `csaNo`, `mhrNo`, `parkName`). Strata fee + pad rent are the seller's at-listing figures — verify from strata docs (Form B) / Site Tenancy Agreement once there's an accepted offer; source registry data from the MHR / Manufactured-Home CPS, never invent a serial/MHR number.
6. **Group 6 — CRM sync** and **Group 7 — Master-sheet sync:** read-mostly, sync-managed. Don't hand-enter; leave to sync layers.

**Checklist completion — two mechanisms, do both.**

1. **Auto (data-driven — no action needed).** Setting the contact, MLS#, CMA, MLC/signed-docs, offer, subject-removal date, closing date, legal description/PID, or `extra.skyslopeMissing` automatically renders the matching stage-checklist items CHECKED on the card (live auto-conditions). You don't construct keys or tick these — just populate the fields accurately.

2. **Back-fill the completed stages (do this when you set the deal's stage).** A deal at `current_stage = N` has already passed stages `0 … N-1`, so that earlier checklist work is done. Write every checklist item for those **completed** phases into `extra.checklistManual` so they render checked — including the judgment-only items in those passed stages (the deal demonstrably cleared each gate to get here). Mechanics:
   - Item key format: **`${phaseId}:${idx}:${item}`** — `phaseId`+`stage` from `ADMIN_PIPELINE` / `ADMIN_BUYER_PIPELINE`, and the exact item string + its 0-based `idx` from `ADMIN_PHASE_DETAILS` / `ADMIN_BUYER_PHASE_DETAILS` in `admin-data.ts`.
   - Completed = phase `stage` number **strictly < `current_stage`**. Collect all those keys and write them as a JSON array to `extra.checklistManual`, **union-merged** with anything already there (persisted to `extra_toggles_json` via the same field path the info fields use).
   - **Only completed stages.** Never bulk-tick the current or future stages — those stay driven by the live auto-conditions (#1). A `current_stage = 0` deal back-fills nothing.

## Step 4a — Normalize the property sub-type

`property_subtype` often arrives as free text from the source ("strata apartment / condo", "manufactured/mobile on land", "residential detached"). **Record the verbatim value**, but ALSO derive the canonical bucket by keyword so the conditional card sections (Strata / Mobile-Home) and toggles fire correctly:

| Free-text contains (case-insensitive) | Canonical bucket |
|---|---|
| `strata`, `condo`, `apartment`, `townhouse` | Strata (+ `Bareland-Strata` if "bareland") |
| `mobile`, `manufactured`, `MHR`, `pad` | Mobile (+ `Bareland-Strata-Mobile` if also bareland-strata) |
| `lot`, `vacant land`, `acreage` (no dwelling) | Lot |
| `pre-con`, `pre-construction`, `assignment` | Pre-Con / Assignment |
| `rural`, `farm`, `agricultural` | Rural |
| else (house / detached / residential) | Residential |

Set the matching `/toggle` (`property_subtype`) from the derived bucket; keep the verbatim string on the card so the original wording isn't lost. The bucket — not the raw text — is what drives the Strata / Mobile conditional field sections in Group 5.

## Step 4b — Compliance (SkySlope) missing-documents check

For any deal that already has a compliance/transaction file open (the tenant's `complianceProvider` from Step 0 — e.g. SkySlope), pull its checklist and surface what's still outstanding onto the card, the same way the scheduled audit does:

1. Run the **`skyslope-sync`** skill (or the tenant's compliance connector) for the deal: open the file, read the checklist, and collect every row marked Required Attach / Incomplete / Missing / In Review / Revision Requested plus every blank required Transaction-tab field → a list of `{ doc, status }`.
2. Write that list to **`extra.skyslopeMissing`** (`[{doc,status}]`; an empty array means all required docs are attached) and **`extra.skyslopeCheckedAt`** (ISO timestamp of the check). These are the exact fields the card's **"SkySlope — Missing Documents"** section renders, and the same shape `scripts/skyslope-write-missing-to-cards.js` writes from the Mon/Wed audit — so onboarding and the cron stay consistent (never invent a second field).
3. **Login-gated (no API):** the compliance portal needs a login (`complianceLoginUrl`/`Email`/`Password`). If it can't be reached this run, do NOT write a stale or empty `skyslopeMissing` (an empty array would show a false "all clear") — instead flag a `waiting_human` item "run skyslope-sync on <address>". A deal with no compliance file yet (early stage) simply gets no `skyslopeMissing`, and the card shows "Not yet checked".
4. If `complianceProvider` is unconfigured for this tenant (Step 0), skip this step and note it.

## Step 5 — Set the toggles (intake branching questions)

For each deal, ask only the toggle questions that aren't derivable from evidence (`coverage-audit.md` §2/§4):

- Signing authority — Individual / POA / Estate Executor / Corporate? (→ `signing_authority`, derive `fintrac_form_type`)
- Politically Exposed Person? (→ `pep`)
- Listing track / source — MLS / Exclusive / Mere Posting / FSBO / Lease / Assignment? (→ `listing_track`)
- Property sub-type — Residential / Strata / Mobile / Bareland-Strata-Mobile / Rural / Lot / Pre-Con / Assignment? (confirm against MLS + Drive)
- Tenanted? Estate/probate status? POA signing? Corporate? Family member? Dual rep? Lockbox? Delayed offer? Buyer's sale-of-property subject (buyer side)?

Batch these per deal so the user answers once. If unanswerable, set the conservative default and add a reminder — a wrong toggle hides a required legal doc.

## Step 6 — Gaps: blank + flag, never guess

When a field's source is unavailable, **leave it blank** and add a card reminder / waiting item naming what to pull. **Data behind a login (no API) becomes a `waiting_human` item naming the exact source — never a silent blank.** Examples:

- No CPS yet on an accepted offer → blank `offer_price`/`subject_removal_date`/`completion_date` + reminder "pull from CPS when received".
- MLS `year_built`/`lot_size_sqft`/PID behind the tenant's `mlsProvider` portal (needs login + MFA) → `waiting_human` naming the portal.
- Buyer-side money/dates only in the `complianceProvider` portal (no API, e.g. SkySlope) → `waiting_human` naming it.
- Commission split inside a signed MLC that couldn't be read → `waiting_human` "pull commission split from signed MLC".
- No Deal Sheet → blank `commission_pct`/`gci` + reminder "pull commission split from Deal Sheet".
- No Title pulled → blank `legal_description` + reminder "pull title".
- Toggle unanswerable → conservative default + reminder to confirm.

Never invent a value to make a card look complete. A blank field with a reminder is correct; a fabricated one is a defect; a silent blank behind a known login is also a defect — flag it.

## Step 7 — Dry-run confirm, then write + close

**Dry-run gate (mandatory on a first run).** Before writing anything to the card DB, build the proposed card for EVERY discovered deal and present a single summary: per deal — `side`, inferred `current_stage`, the fields it WOULD set + their sources, and the flagged gaps (`waiting_human` items). Get the user's approval. Only after they confirm do you create cards / move stages / write fields. Never bulk-write silently on a first run. (Refresh mode: same dry-run, but diff against existing cards.)

After approval, close through `admin-result-writer`. For each deal write one result with a stable idempotency key:

```
deal-onboarding:<deal_id>:<source-key>:onboard
```

Result shape:

```json
{
  "status": "succeeded | waiting_human",
  "idempotencyKey": "deal-onboarding:<deal_id>:<source>:onboard",
  "summary": "Onboarded <address> at Stage <n> (<stage name>), populated <k> fields, <g> gaps flagged.",
  "checklist_updates": [],
  "artifacts": [],
  "next_tasks": [
    { "skill": "mlc", "title": "Pull title for <address>", "payload": {} }
  ],
  "human_prompt": {
    "title": "Confirm onboarded deals (dry-run)",
    "message": "Dry-run of <count> cards: per deal — side, inferred stage, fields I would set (+ sources), and flagged gaps. Approve before I write to the card DB.",
    "requiredFields": ["stage confirmation", "toggle answers", "any missing prices/dates"]
  }
}
```

- Use `waiting_human` when toggles or key fields couldn't be resolved and you need the user's input. Don't mark a deal fully onboarded with guessed data.
- Put missing inputs in `requiredFields`, not buried in the summary.
- Emit one `next_tasks` entry per real gap (pull title, request commission split, draft the next-stage doc) so the pipeline keeps moving.

## Notes

- Run per-deal so one bad source doesn't block the whole batch. A deal whose only source is a Drive folder still onboards (folder docs → stage + fields).
- Refresh mode (existing user): match each discovered deal to its existing card first (by deal_id / address / MLS#); update in place, never create a duplicate.
- The agent-onboarding wizard (`cli/web/src/pages/agent-onboarding/`) handles user/jurisdiction setup; this skill assumes that's done and reads `province`/`board`/`market` and all provider config from `GET /api/admin/setup` (Step 0), never from hardcoded per-realtor defaults.
