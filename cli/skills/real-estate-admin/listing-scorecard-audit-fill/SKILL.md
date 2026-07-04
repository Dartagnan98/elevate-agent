---
name: listing-scorecard-audit-fill
description: "Audit Admin listing scorecards for missing or stale fields, then backfill verified facts. Use when the realtor says listing cards/scorecards are missing information, asks to audit or fill cards, or is onboarding/importing active listings, covering property identity, seller/MLC status, MLS/Matrix status, and marketing fields. Uses property-card-truth-sync for the actual write."
metadata:
  elevate:
    tags: [real-estate-admin, admin-dashboard, listing-scorecards, property-card, audit, onboarding, backfill]
---

# Listing Scorecard Audit + Fill

Use this skill when Admin listing/property scorecards are missing important information or when importing/onboarding listings into the dashboard. The goal is to make every active/relevant listing card a usable source of truth, not a blank checklist.

This skill is the batch audit wrapper around `real-estate-admin/property-card-truth-sync`.

## Hard rules

- Do not guess values. Only fill fields from verified sources or mark them as missing with source/status metadata.
- Do not overwrite user-corrected values with inferred/older portal data.
- No external sends, signatures, MLS publish, price/copy approvals, or phase overrides from this skill.
- For any online portal, web search, portal preview, download, or login flow, use the account's configured browser-automation path rather than ad hoc curl for online work.
- If a workflow discovers a fact, immediately write it to the Admin property card via `property-card-truth-sync` before closing the run.

## Scope

Audit these Admin deals/cards unless the realtor names a narrower set:

1. Active Listing / Listing Live
2. Pre-CMA / CMA / Seller appointment pipeline cards
3. Signed MLC / Listing Build / Marketing Go cards
4. Accepted-offer listing cards when listing facts remain relevant

Exclude:

- Closed deals, unless the realtor explicitly asks for closed-card cleanup.
- Buyer-only cards, unless the missing fields are transaction/deadline scorecard fields.
- Mock/test cards unless the task is explicitly a test.

## Required scorecard field groups

Check each card for visible field values and source/status metadata in these groups when applicable:

### Core property identity
- Civic address, unit, city, province, postal code
- PID
- Legal description
- Property type/style
- Year built
- Bedrooms/bathrooms
- Finished floor area and source
- Lot size/dimensions and source
- Taxes/year
- Zoning
- Strata number, strata fees, strata docs/order status when applicable

### Seller/client and listing contract
- Seller names and preferred contact details
- Seller address when required for forms
- MLC/listing agreement status
- List price
- Commission fields
- Included/excluded items
- Possession or preferred dates if known
- Listing start/end dates
- eXp/SkySlope transaction status if already created

### MLS / Matrix / Xposure
- MLS number if live or drafted
- Matrix/Xposure draft/live status
- Publish/activation status
- Showing instructions and lockbox status
- Room measurements/floor-plan source
- Public remarks/private remarks approval status, if present

### Marketing / listing launch
- Photos received/approved status
- Floor plans received status
- Feature sheet/landing page/video/social/Buffer/Mailjet artifact links when present
- Brand/copy approval status
- Seller update cadence/status for live listings

### Accepted offer / deadlines when applicable
- Accepted offer status
- Buyer agent/name if verified
- Offer price
- Acceptance date
- Subject removal date(s)
- Deposit amount/due/receipt status
- Closing/completion/possession dates
- Conveyancer and payout status

## Procedure

1. Load current Admin pipeline snapshot.
   - Use `deals_overview` first for a broad view.
   - If more detail is needed, use `elevate_db.describe` and read only the relevant Postgres tables with SELECTs.

2. Identify target cards.
   - Filter to active/relevant listing-side cards.
   - Record deal id, address, stage, side, contacts, MLS number, last activity, and current missing-field count.

3. Read each card's current visible fields and metadata.
   - Read `deals.extra_toggles_json` or the current Admin card info-field storage used by the dashboard.
   - Preserve any fields marked user-corrected or manually approved.

4. Build a missing-field audit.
   - Classify each missing/stale field as:
     - `fillable_from_card/run`: already available in Admin records, attachments, events, or prior run artifacts.
     - `fillable_from_local_docs`: likely in downloaded PDFs, Drive-synced files, local forms, parsed data, or attachments.
     - `requires_portal_check`: requires Xposure/Matrix/SkySlope/BC Assessment/Drive online lookup.
     - `human_needed`: cannot be verified from available sources.
   - Keep one concise missing-info prompt per card if human input is needed.

5. Fill from safe available sources first.
   - Use existing Admin records, attachments, run artifacts, parsed PDFs, and local files before portal checks.
   - If using online sources, drive them only through local Browser Use CLI.
   - Keep source excerpts/URLs/file paths for every value.

6. Sync values to the card.
   - Load and follow `real-estate-admin/property-card-truth-sync`.
   - Write both visible field keys and required alias keys.
   - Normalize select-field values to the exact dashboard option values, otherwise the database can be filled while the visible scorecard still looks blank:
     - `core.propertyType`: one of `detached`, `townhouse`, `condo`, `manufactured home`, `land`.
     - `core.tenureTitleType`: one of `freehold`, `strata`, `leasehold`, `manufactured home on pad/site`.
     - `mlc.listingStatus`: one of `prep`, `signed`, `Matrix incomplete`, `Marketing Go`, `live`, `accepted offer`, `firm`, `closed`.
     - `seller.signingAuthority`, `seller.lawyerChosen`, and `mlc.occupancy` must also use the exact visible option strings when known.
   - Do not write broad source labels like `Residential`, `Strata Apartment - Hi-Rise`, or `Single Family - Detached` into select fields. Preserve those as subtype/source notes, but write the visible select key as `condo`, `detached`, etc.
   - Write/update:
     - `propertyCardTruthSources`
     - `propertyCardTruthStatus`
     - `propertyCardTruthLastSyncedAt`
     - `propertyCardTruthLastSyncedBy`
     - `propertyCardTruthSyncSummary`
   - If the scorecard has section checklist items, update the checklist state so stalled sections show clearly.

7. Verify.
   - Read each updated deal back from Postgres.
   - Confirm expected keys are present and metadata timestamp changed.
   - If the local Admin UI is available, verify the visible dashboard card/modal fields, not only the database row.
   - Specifically open each target card and confirm select fields render with non-blank values after a page reload. If `PROPERTY TYPE`, `TENURE/TITLE TYPE`, or `LISTING STATUS` are blank in the modal, the field was not normalized correctly and the run is not complete.
   - For exact-card requests, verify the readback includes only the named deal IDs and that `current_stage` did not change.

8. Report concise results.
   - Include counts only:
     - cards audited
     - cards updated
     - fields filled
     - cards still waiting on human info
   - List only the cards needing human input and the exact missing items.
   - Do not include a long process breakdown unless the realtor asks.

## Field-write lessons

- When updating scorecard fields directly in Admin data, preserve `extra_toggles_json` wholesale and patch only the specific keys. Do not replace the whole JSON object from a hand-built payload.
- Write both dotted visible keys and bare aliases where the UI may read either, for example `core.pid` + `pid`, `core.legalDescription` + `legalDescription`, `mlc.expiryDate` + `mlcExpiryDate` + `expiryDate`, `listDate` + `listingDate`, `currentListPrice`, seller dotted keys + bare seller aliases, and workflow/status aliases if an older key exists.
- Before writing, inspect existing truth status and skip keys marked `user-corrected`.
- Use local Admin attachments/events, local Drive-synced PDFs, text extracted by `pdftotext`, local assessment/property reports, active-listing snapshots, and contact table cross-checks before doing any portal work.
- If two verified sources conflict, prefer the most current source tied to the target MLS/current relist and record the stale/conflicting value as a note instead of overwriting with it. Examples: current MLS sqft over older marketing sqft, current signed price reduction over old MLC price.
- Never store bogus non-values from reports. For strata cards, if land size is blank/NaN/not applicable, keep direct `lot_size_sqft` null and mark the card lot-size field as strata/not applicable with metadata.
- For exact-card audits, write a `deal_events` audit entry with from/to stage equal to the existing stage and payload flags confirming no external sends, no signatures, no MLS publish, and no phase override.
- After the first write, run a small alias/status repair pass if readback shows stale visible aliases still disagree with direct columns or verified facts.

## Done criteria

- Every in-scope listing scorecard has been audited.
- Verified facts have been written to the property card, not just mentioned in notes.
- Missing-but-required fields are marked with clear status/source metadata.
- Human-needed gaps are surfaced as short card prompts.
- No external send/publish/signature/phase override happened.

## Related skills

- `real-estate-admin/property-card-truth-sync` for the actual field write + metadata contract.
- `real-estate-admin/deal-matcher` if card identity is uncertain.
- `real-estate-admin/admin-result-writer` if this runs inside an Admin action/run.
- `real-estate-admin/admin-listing-import` when a signed listing package is being imported into Admin.
- `agent-ops/agent-browser` or `browser-use-cli-local-only` for Browser Use CLI execution patterns.
