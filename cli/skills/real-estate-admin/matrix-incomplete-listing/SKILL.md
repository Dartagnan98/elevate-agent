---
name: matrix-incomplete-listing
description: Create and finish a NEW listing in the configured MLS input platform (AOIR Matrix / Xposure). Mode "draft" builds the incomplete listing from signed-MLC property facts and Saves as Incomplete (stage 3). Mode "photos" uploads the final best-99 photos and finishes the listing (stage 4). Never clicks Submit — the realtor reviews and submits.
metadata:
  elevate:
    tags: [real-estate, mls, matrix, listing]
    runtime:
      approval_required: true
      result_writer: admin-result-writer
---

# Matrix / Xposure Incomplete Listing

Builds a brand-new MLS listing in the configured input platform from a signed MLC, in two passes that match the listing board:

- **`draft` (SkySlope & Matrix Prep, stage 3)** — create the incomplete listing from the property facts gathered after the MLC is signed, Save as Incomplete, capture the new MLS#, and surface the fields that still need input.
- **`photos` (Marketing Go, stage 4)** — once photos are cleaned, select the best 99, upload them to the listing, and finish it so it is ready for the realtor to Submit.

This is the new-listing sibling of the `relisting` skill. Relisting copies a prior MLS as a template; this skill fills a fresh listing from the deal's property facts. Both drive the same platform, so they share the same playbook and lessons.

## CRITICAL — read first

0. **Read `docs/playbooks/matrix-automation.md` FIRST.** Shared Matrix/Xposure playbook: platform split, login flow, `fillByLabel` helper, the JS-evaluate setter, room cards, listing-contract field rules, file-upload patterns, and the search-as-you-type picker taxonomy. Do not improvise selectors — this file codifies what was learned across many corrections.
1. **Read `lessons.md` BEFORE every run and append to it AFTER every run.** Matrix input IDs change between sessions — ALWAYS bind by visible label text, never a raw id. Log every correction the realtor gives. Format: `[date] | what happened | rule/insight`.
2. **Provider-neutral.** The input platform may be AOIR Matrix, Xposure, or another board set during onboarding. Treat the platform name, login URL, MLS area list, and field labels as tenant configuration. Never hardcode a board, realtor, or brokerage.
3. **Never click final Submit.** Both modes stop at Save as Incomplete / Save. The realtor reviews remaining fields and submits to make the listing live on the public board. State this in every handoff.

## What this skill does NOT do

- Does NOT Submit the listing or push it to the public MLS/REALTOR.ca.
- Does NOT invent property facts — it fills only from `property-lookup` output, the signed MLC, and the deal record. A fact it cannot source is surfaced as a missing field, never guessed.
- Does NOT touch the compliance portal (that is `skyslope-sync`) or the Drive folder structure.
- Does NOT edit photos (that is `photo-cleanup`) — `photos` mode only selects the best 99 and uploads.

---

## Mode: `draft` (stage 3)

Runs after the MLC is signed and `property-lookup` has gathered property context.

1. **Resolve inputs** from the deal + `property-lookup` output: address, property type, legal/PID, beds/baths, lot, year, sellers, list price, commission, planned dates. Map the property type to the platform's exact button text (see the playbook's type table). If a required identity fact (legal, PID, property type) is missing, write `waiting_human` naming it — do not guess.
2. **Open the platform** through Browser Use using the saved login state; fresh login if absent. Use a real Chrome channel, a wide viewport, and `slowMo` so the form's state keeps up (see playbook).
3. **Start a new listing** (Input → Add → property type). Do NOT use "Fill from Property" — this is a fresh listing, not a relist.
4. **Fill the listing-contract + property sections** from the resolved facts, using `fillByLabel` for every field and the search-picker helper for any type-as-you-search control. Never type raw text into a picker.
5. **Save as Incomplete.** Capture the new MLS# from the success page (`/Listing\s*#\s*(\d{8})/`). No regex match = NOT done: screenshot the form, surface the validation errors, do not retry blindly.
6. **Surface remaining required fields** from the post-save sidebar count (Title Tier, Map, Distribution, Showing, Remarks, etc.) so the realtor knows exactly what is left before photos.
7. **Close through `admin-result-writer`** with the new MLS# and the remaining-fields list.

Clears (only with evidence): `matrix_incomplete_listing_prepped`, `matrix_missing_fields_surfaced`. Writes `mlsNumber` when captured.

## Mode: `photos` (stage 4)

Runs after `photo-cleanup` has produced the cleaned, listing-ready export.

1. **Resolve the listing** by the MLS# captured in `draft` mode (or from the deal). If there is no incomplete Matrix listing yet, write `waiting_human` — `draft` must run first.
2. **Select the best 99.** If the cleaned export has more than 99 photos, choose the best 99 in a sensible order (exterior/front first, primary living spaces, then the rest). Record which were dropped.
3. **Upload** the selected photos to the listing through the platform's photo manager, in order, using the file-upload pattern in the playbook.
4. **Verify** the uploaded count and order read back from the platform — not just that upload() was called.
5. **Finish the listing** (Save) so every photo-dependent field is satisfied. Stop before Submit.
6. **Close through `admin-result-writer`** with the uploaded count and the dropped list.

Clears (only with evidence): `best_99_matrix_photos_selected`, `matrix_photos_uploaded`, `matrix_listing_finished_with_photos`.

---

## Completion Gate (run before reporting "done")

A script exiting cleanly is NOT the finish line. Report evidence for every applicable line:

- [ ] `draft`: "Input Succeeded" page returned AND a new MLS# captured via regex. Otherwise `partial` — name the validation errors.
- [ ] `draft`: each filled field read back and verified, not just "fill() was called".
- [ ] Any search picker touched returned `ok`. Every `ok:false` picker is named in the handoff as a manual field — never silently dropped.
- [ ] `photos`: uploaded count + order verified from the platform; dropped photos listed.
- [ ] Final action before close was Save as Incomplete / Save — never Submit.

Status is `done` only if every applicable line is verified. Otherwise `partial` — say "partial" and name the exact unfinished items.

## Rules

- Approval: surface the listing for the realtor's review before she submits; this skill never submits.
- Missing identity facts, picker failures, MFA/login, or upload failures are `waiting_human` / `partial` with the exact blocker — never a silent pass.
- Keep the platform's labels alongside the province-package labels in artifacts when they differ.
- Same finalization in any context: in a live session converse inline; on a stage trigger the conversation goes to the Admin agent lane. Always close through `admin-result-writer` so the kanban card reflects the outcome (see its "Where this writes").

## Output Contract

```json
{
  "workflow": "matrix-incomplete-listing",
  "mode": "draft|photos",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "platform": "",
  "mls_number": "",
  "fields_filled": [],
  "remaining_required_fields": [],
  "photos_uploaded": 0,
  "photos_dropped": [],
  "checklist_updates": [],
  "risks": []
}
```

## Lessons protocol

After every run: if anything was unclear, broken, or the realtor corrected → append to `lessons.md` immediately. If the platform UI changed (new buttons, field renames, id structure) → record the new selectors. If a new property type was listed → record the exact button text and quirks. This skill compounds value only if every correction is logged.
