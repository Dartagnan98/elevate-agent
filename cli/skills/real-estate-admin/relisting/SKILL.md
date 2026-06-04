---
name: "relisting"
description: "Relist a previously cancelled or expired property in AOIR Matrix using the prior MLS# as a template. Reuses photos, description, legal/PID, sellers, and most fields from the old listing \u2014 only changes Contract Effective Date, Expiration Date, List Price, and Buyer Agency Commission. Trigger on \"relist [address]\", \"re-list [address]\", \"create a new listing for [address] using the old MLS as template\", \"open Matrix and copy from MLS [number]\", or any request to relist a property that was previously listed and cancelled."
category: "real-estate-admin"
access:
  entitlement: "real_estate_admin"
---

# Relisting — Matrix Template Flow

the realtor's standard process for putting a cancelled or expired listing back on the market without rebuilding everything from scratch.

## CRITICAL — read first

0. **Read `docs/playbooks/matrix-automation.md` FIRST.** Synthesized playbook with Matrix vs Xposure split, login flow, fillByLabel helper, JS-evaluate setter, room cards, listing-contract field rules, file-upload patterns, picker-control taxonomy. Codifies what the lessons.md learned across 25+ corrections.
1. **Read `lessons.md` BEFORE every run.** Apply every lesson. The Matrix UI has session-specific input IDs that change between runs — ALWAYS bind by visible label text, never raw id.
2. **Add to lessons.md AFTER every run.** If anything is unclear, broken, or the realtor corrects, append the lesson immediately. Format: `[date] | what happened | rule/insight`. the realtor's instruction at skill creation: *"any recommendations should be added to lessons.md so we can rely on the flow"* — this skill compounds value only if we record what we learn.
3. **the realtor's Matrix relist rule (durable):** only Contract Effective Date, Expiration Date, List Price, and Buyer Agency Commission change on a relist. Photos, remarks, legal, PID, sellers, and everything else carry from the prior listing. Do NOT modify other fields without explicit instruction.

## What this skill does

1. Logs into AOIR Matrix via members.interiorbc.ca → Favorites → AOIR Matrix card.
2. Navigates to Input (Listing Manager) → clicks Add → picks property type.
3. Types the prior MLS# in the autocomplete, picks the autocomplete result.
4. Selects "Fill from Property" radio → Continue. Form pre-fills from old listing (drops required-fields count by ~60%).
5. Navigates to Listing Contract section.
6. Fills the four fields that always change on a relist:
   - Contract Effective Date (today, MM/DD/YYYY)
   - Expiration Date (today + 90 days, MM/DD/YYYY)
   - List Price (number with no commas)
   - Buyer Agency Commission (3 unless overridden)
7. Clicks "Save as Incomplete" → Matrix returns the new MLS# on the success page.
8. Captures the new MLS# and updates `docs/listings/cancelled-listings.md` and `active-listings.md`.
9. Surfaces the remaining required fields to the realtor (Title Tier 1/2, Number of Titles, Map fields, Distribution, Showing, Remarks) — these don't carry from the template and need her input before she clicks Submit to make the listing live.

## What this skill does NOT do

- Does NOT click final "Submit" — only "Save as Incomplete". the realtor reviews + submits manually.
- Does NOT change photos or remarks — those reuse from the prior listing automatically and shouldn't be touched.
- Does NOT touch SkySlope (use the existing SkySlope upload flow for the new transaction's checklist).
- Does NOT update the Drive folder structure — the relist Drive folder gets created separately when the new MLC is signed.

---

## Step 1 — Resolve inputs

Before launching:

- **Address** — required.
- **Prior MLS#** — if not given:
  1. `grep -i "<address>" docs/listings/cancelled-listings.md`
  2. If no match, ask the realtor OR launch Matrix search and find the cancelled record.
- **New price** — if not given, ASK the realtor. Never guess. Common pattern: drop the prior listing price 2-5%.
- **Property type** — if not given, infer from the cancelled-listings entry (`Type` field) or ask. Map to Matrix's exact button text:
  - SFD / Single Family / Detached → `Residential (No Manufactured Homes)`
  - Manufactured / mobile / park model → `Manufactured Home (Freehold/Leasehold) or Park Model`
  - Farm with house → `Farm with Residence`
  - Bare lot → `Land Only (Residential / Commercial)`
  - 5+ unit building → `Multifamily / Income (5+ Units)`
  - Commercial → `Commercial Sale` or `Commercial Lease`
  - Strata: still `Residential (No Manufactured Homes)` (Matrix's Residential bucket includes strata; the Strata sub-fields appear later in the form)
- **Expiry days** — default 90. the realtor can override.

## Step 2 — Run the Playwright flow

Reference script: `scripts/matrix-relist-walk12.js` (last working version as of 2026-04-30, walked end-to-end on 1872 Red Tail → new MLS 10385575).

The skill should generate a fresh script (or call a parameterized version) — do not blindly re-run the walk script with hardcoded Red Tail values.

Key requirements for the script:
- `channel: 'chrome'` (NOT bundled Chromium — Cloudflare blocks it)
- Viewport `{ width: 1600, height: 1000 }` so all sidebar/inputs are visible
- `slowMo: 200` to let Matrix's React state catch up
- Storage state at `data/aoir-state.json` — fresh login if not present
- All field setters use the `fillByLabel()` helper (label-walk-to-input via JS evaluate) — Matrix input IDs change per session
- For any **Type-4 search-as-you-type picker** (Street Type, City, MLS Area, Title Tier, Property Sub Type, Style, etc.) use `fillSearchPicker` from `scripts/lib/matrix-pickers.js` — never type raw text into them (prefix-matches the wrong tag). Relists rarely hit these (Fill from Property carries them), but if one is blank, the helper handles it; an `ok:false` return goes to the manual-fields handoff. See matrix-automation.md §12.
- `waitForEvent('page')` to capture the popup that opens when AOIR Matrix card is clicked from members portal

## Step 3 — Completion Gate (run before reporting "done")

the realtor's #1 complaint (2026-05-20): the skill *"only did partial stuff"* — a
script exiting cleanly is NOT the finish line. Run the full Completion Gate in
`docs/playbooks/matrix-automation.md` §15 and report evidence for every line:

- [ ] "Input Succeeded" page returned AND a new MLS# was captured via
  `/Listing\s*#\s*(\d{8})/`. No regex match = NOT done — screenshot the form,
  surface the validation errors to the realtor, do not retry blindly.
- [ ] Each of the 4 relist fields (Effective Date, Expiration Date, List Price,
  Buyer Agency Commission) was read back and verified — not just "fill() was
  called".
- [ ] Any Type-4 picker the script touched: `fillSearchPicker` returned `ok`.
  Every `ok:false` picker is named in the Step 5 handoff as a manual field —
  never silently dropped.
- [ ] Final action before `browser.close()` was Save as Incomplete.
- [ ] Records updated (Step 4).

Status is `done` only if every applicable line is `verified`. Otherwise it is
`partial` — say "partial" and name the exact unfinished items.

## Step 4 — Update records

After successful save:

1. **`docs/listings/cancelled-listings.md`** — flip the `[ ] RELIST` checkbox to `[x]`, append the new MLS# + save timestamp + Matrix Save-as-Incomplete state.

2. **`docs/listings/active-listings.md`** — add a new entry with the new MLS#, new price, listing date, expiry date. Mark status as "Incomplete in Matrix — pending field completion + submit".

3. **Per-listing markdown** (`docs/listings/<short>.md`) — keep the old file. Update its top section to show the new MLS# + relist date.

4. **Drive folder** — make sure the relist folder (`<Address> (Relist <date>)`) exists with the signed MLC + reused PNC/DORTS/Title PDFs. Create if missing.

## Step 5 — Hand off to the realtor

Send Telegram with:
- ✓ New MLS# captured
- The 4 fields the skill filled
- The remaining required fields she needs to complete (extract from the sidebar count post-save) before clicking Submit
- A reminder that the listing is INCOMPLETE in Matrix and will not appear on REALTOR.ca until she clicks Submit

## Coupling with other skills

- **After Submit** → the realtor launches `marketing` skill ("Just Listed" / "Back on Market" graphics + Buffer + email)
- **SkySlope side** → already handled by the relist's SkySlope upload flow (signed MLC + PNC + DORTS + Title to checklist items 1, 3, 4, 6)
- **PDS** → if no PDS exists, the realtor sends new PDS template to sellers + DigiSigns. Once signed, attach to SkySlope checklist item 5.

---

## Files

| File | Purpose |
|------|---------|
| `.claude/skills/relisting/SKILL.md` | This file |
| `.claude/skills/relisting/lessons.md` | Corrections + Matrix UI gotchas — READ FIRST |
| `scripts/matrix-relist-walk12.js` | Working reference script (1872 Red Tail, 2026-04-30) |
| `data/aoir-state.json` | Saved AOIR/members.interiorbc.ca login state |

## Lessons protocol

After every run of this skill:
1. If anything was unclear, broken, or the realtor corrected → append to `lessons.md` immediately
2. If the Matrix UI changed (new buttons, field renames, ID structure changes) → update `lessons.md` with the new selectors
3. If a new property type was relisted → record the exact button text and any quirks in `lessons.md`
4. **the realtor's standing instruction:** every recommendation she gives during a relist gets logged to `lessons.md` so the next run is smarter. This is non-negotiable.

## Workflow Handoff

Relisting is a workflow even when it uses one main Matrix script. Write:

`data/relisting/runs/<run>/handoffs/relisting.handoff.json`

Required fields:

- prior MLS number and new MLS/listing status.
- old data reused: photos, remarks, legal/PID, sellers.
- changed data: list price, effective date, expiry, commission.
- SkySlope checklist uploads performed.
- PDS/DigiSign status.
- risks: Matrix field uncertainty, missing prior listing, upload failures.
