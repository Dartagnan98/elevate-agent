---
name: property-card-truth-sync
description: "Write newly discovered property/deal facts straight onto the Admin property card. Use when a Pre-CMA, CMA, MLC, signing package, property lookup, SkySlope, Matrix/Xposure, Marketing Go, accepted-offer, subject-removal, closing, Gmail-doc-routing, or seller-update workflow learns a fact, or before finishing any property workflow so the realtor never catches a card gap after the fact."
metadata:
  elevate:
    tags: [real-estate-admin, admin-dashboard, property-card, source-of-truth, deal-facts]
---

# Property Card Truth Sync

Use this skill any time an Admin workflow obtains or verifies property/deal facts for a card, including Pre-CMA, CMA, MLC, signing package, property lookup, SkySlope, Matrix/Xposure, Marketing Go, accepted offer, subject removal, closing, Gmail doc routing, or seller updates.

Rule: if we learn a fact for a property, fill the associated spot on the Admin card immediately. The card is the reusable truth, not a side note buried in a run file.

## Required behaviour

1. Identify the matching `deals.id` before writing.
   - Match by explicit deal id first.
   - Otherwise match by property address, MLS number, seller emails/phones, or source run id.
   - Use `deal-matcher` if identity is not obvious.
2. Read current card values before writing.
   - Do not overwrite a `user-corrected` value with an inferred value.
   - Verified source can replace missing, stale, or inferred values.
3. Map every discovered fact into the dashboard info field key if a key exists.
4. Write both:
   - the visible card field key, for example `core.pid` or `mlc.listingPrice`
   - any alias key used by existing code, for example `pid` or `mlcListingPrice`
5. Store source/status metadata for downstream skills:
   - `propertyCardTruthSources`
   - `propertyCardTruthStatus`
   - `propertyCardTruthLastSyncedAt`
   - `propertyCardTruthLastSyncedBy`
   - `propertyCardTruthSyncSummary`
6. Verify by reading the deal back and confirming the expected keys are present.
7. Only ask the realtor for fields that remain missing after checking the card, Drive/run files, BC Assessment/eValueBC, Xposure/Matrix, SkySlope/DigiSign, and Gmail/doc attachments.

## Field key map

### Core Property Section

Visible field keys:

- `core.propertyAddress`
- `core.unitNumber`
- `core.city`
- `core.province`
- `core.postalCode`
- `core.mlsNumber`
- `core.pid`
- `core.legalDescription`
- `core.rollFolioNumber`
- `core.propertyType`
- `core.tenureTitleType`
- `core.listingDriveFolderLink`
- `core.skySlopeFileLink`
- `core.matrixXposureDraftLink`
- `core.liveListingUrl`
- `core.landingPageUrl`

Useful aliases to also set when relevant:

- `pid`
- `rollFolioNumber`
- `folioNumber`
- `rollNumber`
- `propertyType`
- `tenureTitleType`
- `listingDriveFolderLink`
- `driveFolderUrl`
- `skySlopeFileLink`
- `matrixXposureDraftLink`
- `liveListingUrl`
- `landingPageUrl`

Supported deal detail fields to set through `set_deal_fields` when available:

- `listPrice`
- `mlsNumber`
- `legalDescription`
- `lotSizeSqft`
- `yearBuilt`
- date/money fields such as `listingDate`, `completionDate`, `possessionDate`, `depositAmount`, etc.

Set `listing_address`, `province`, and `market` directly only when needed because current `set_deal_fields` does not accept those names.

### Seller Information Section

Visible field keys:

- `seller.legalNames`
- `seller.preferredNames`
- `seller.emails`
- `seller.phones`
- `seller.mailingAddress`
- `seller.residencyStatus`
- `seller.signingLocationProvince`
- `seller.signingAuthority`
- `seller.preferredSigningEmail`
- `seller.lawyerChosen`
- `seller.lawyerName`
- `seller.lawyerFirm`
- `seller.lawyerEmail`
- `seller.lawyerPhone`
- `seller.lawyerCityProvince`

Useful aliases:

- `sellerLegalNames`
- `sellerPreferredNames`
- `sellerEmails`
- `sellerPhones`
- `sellerMailingAddress`
- `sellerResidencyStatus`
- `signingLocationProvince`
- `signingAuthority`
- `preferredSigningEmail`
- `sellerLawyerChosen`
- `sellerLawyerName`
- `sellerLawyerFirm`
- `sellerLawyerEmail`
- `sellerLawyerPhone`
- `sellerLawyerCityProvince`

### Listing Contract / MLC Section

Visible field keys:

- `mlc.listingPrice`
- `mlc.commissionTerms`
- `mlc.cooperatingBrokerageCommission`
- `mlc.contractEffectiveDate`
- `mlc.expiryDate`
- `mlc.plannedMlsLiveDate`
- `mlc.comingSoonDate`
- `mlc.listingStatus`
- `mlc.includedItems`
- `mlc.excludedItems`
- `mlc.tenancyDetails`
- `mlc.sellerInstructions`
- `mlc.occupancy`
- `mlc.showingInstructions`
- `mlc.lockboxCodeStatus`
- `mlc.signRiderStatus`

Useful aliases:

- `mlcListingPrice`
- `mlcCommissionTerms`
- `mlcCooperatingBrokerageCommission`
- `mlcContractEffectiveDate`
- `mlcExpiryDate`
- `mlcPlannedMlsLiveDate`
- `mlcComingSoonDate`
- `mlcListingStatus`
- `mlcIncludedItems`
- `mlcExcludedItems`
- `mlcTenancyDetails`
- `mlcSellerInstructions`
- `mlcOccupancy`
- `mlcShowingInstructions`
- `mlcLockboxCodeStatus`
- `mlcSignRiderStatus`

## UI-visible select normalization

Some Admin info fields are `<select>` controls. The database may contain a human label such as `Residential`, `Strata`, `Freehold`, or `Active`, but the visible card will still look blank unless the stored value exactly matches the option value. Normalize select values before closing any scorecard/card repair.

Common normalized values:

- `core.propertyType` / `propertyType`: `detached`, `townhouse`, `condo`, `manufactured home`, `land`
- `core.tenureTitleType` / `tenureTitleType`: `freehold`, `strata`, `leasehold`, `manufactured home on pad/site`
- `mlc.listingStatus` / `mlcListingStatus` / `listingStatus`: `prep`, `signed`, `Matrix incomplete`, `Marketing Go`, `live`, `accepted offer`, `subject removal`, `collapsed`, `closed`

Repair pattern for normalization-only fixes:

1. Read the deal from the packaged runtime/Postgres store that serves the visible Admin UI.
2. Preserve all existing `propertyCardTruthSources`, `propertyCardTruthStatus`, `propertyCardTruthLastSyncedAt`, `propertyCardTruthLastSyncedBy`, and `propertyCardTruthSyncSummary` unless the task explicitly asks to update source metadata.
3. If any target key is marked `user-corrected` with a conflicting non-blank value, stop rather than overwriting it.
4. Merge the normalized values into `extra_toggles_json` directly when you must preserve dotted visible keys like `core.propertyType` or `mlc.listingStatus`. Current helper paths may strip some dotted namespaces, which can update an alias while leaving the UI-visible dotted key stale.
5. Write aliases at the same time (`propertyType`, `tenureTitleType`, `mlcListingStatus`, `listingStatus`) so older code paths and the current UI agree.
6. Insert a same-stage `toggle_change` audit event with `from_stage == to_stage`, `field_name='scorecard_select_normalization'`, and payload flags confirming no external sends, no signatures, no MLS publish, and no phase override.
7. Verify twice: read back the exact keys from the deal, then reload/open the local Admin card with Browser Use CLI and inspect `.abm-info-field` values. The visible select values must be non-blank and match the normalized option values.

Example Browser Use CLI verification after reload/opening a card:

```bash
browser-use --json --session admin-scorecard-verify eval '(() => Array.from(document.querySelectorAll(".abm-info-field")).map(f => ({label:(f.innerText||"").split("\\n")[0], value:f.querySelector("input,select,textarea")?.value || ""})).filter(x => /PROPERTY TYPE|TENURE|LISTING STATUS/i.test(x.label)))()'
```

## Status values

Use compact status strings in `propertyCardTruthStatus`:

- `verified` — source document/system or realtor-confirmed
- `user-corrected` — the realtor corrected it, highest priority
- `inferred` — reasonable inference, not final
- `missing` — confirmed still missing
- `stale` — old value kept for history but should not be used

If a value comes from ID evidence, save only the needed transaction fact. Do not expose/transcribe extra ID PII in chat.

## Postgres write pattern

First confirm which runtime is serving the visible dashboard. If the dashboard process is the packaged Electron app runtime, for example:

```bash
/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 -m elevate_cli.main dashboard --port 9120
```

then run the write script with that packaged Python runtime. Writing with `/Users/admin/.elevate/elevate/cli/.venv/bin/python` can update the source checkout store while the visible dashboard still shows old values. This exact runtime split caused a backfill verification to fail on one property until the same updates were rerun with the packaged runtime.

If the live dashboard is served from the source checkout, run from `/Users/admin/.elevate/elevate/cli` with the local venv:

```bash
cd /Users/admin/.elevate/elevate/cli
.venv/bin/python - <<'PY'
from elevate_cli.data import connect
from elevate_cli.data.deals import set_deal_fields, set_deal_toggle
from elevate_cli.data._util import now_iso
import json

DEAL_ID = '<deal id>'
ACTOR = 'assistant:property-card-truth-sync'
now = now_iso()

visible_updates = {
    'core.propertyAddress': '<street address>',
    'core.city': '<city>',
    'core.province': 'BC',
    'core.postalCode': '<postal code>',
    'core.pid': '<pid>',
    'core.legalDescription': '<legal>',
    'seller.legalNames': '<seller legal names>',
    'mlc.listingPrice': '$<price>',
}
alias_updates = {
    'pid': visible_updates.get('core.pid'),
    'sellerLegalNames': visible_updates.get('seller.legalNames'),
    'mlcListingPrice': visible_updates.get('mlc.listingPrice'),
}
source_map = {
    '<source name>': 'field list / evidence summary',
}
status_map = {k: 'verified' for k in visible_updates if visible_updates[k]}

with connect() as conn:
    # Use only supported detail fields here.
    detail_fields = {}
    if visible_updates.get('mlc.listingPrice'):
        detail_fields['listPrice'] = visible_updates['mlc.listingPrice'].replace('$', '').replace(',', '')
    if visible_updates.get('core.legalDescription'):
        detail_fields['legalDescription'] = visible_updates['core.legalDescription']
    if detail_fields:
        set_deal_fields(conn, DEAL_ID, actor=ACTOR, fields=detail_fields)

    # listing_address/province/market are not currently supported by set_deal_fields.
    if visible_updates.get('core.propertyAddress'):
        full_address = ', '.join(p for p in [
            visible_updates.get('core.propertyAddress'),
            visible_updates.get('core.city'),
            visible_updates.get('core.province'),
            visible_updates.get('core.postalCode'),
        ] if p)
        conn.execute('UPDATE deals SET listing_address=?, updated_at=? WHERE id=?', (full_address, now, DEAL_ID))

    for key, value in {**visible_updates, **alias_updates}.items():
        if value not in (None, ''):
            set_deal_toggle(conn, DEAL_ID, field=key, value=value, actor=ACTOR)
    for key, value in {
        'propertyCardTruthLastSyncedAt': now,
        'propertyCardTruthLastSyncedBy': ACTOR,
        'propertyCardTruthSources': source_map,
        'propertyCardTruthStatus': status_map,
        'propertyCardTruthSyncSummary': 'Updated card truth fields from verified workflow facts.',
    }.items():
        set_deal_toggle(conn, DEAL_ID, field=key, value=value, actor=ACTOR)
    conn.commit()

    row = conn.execute('SELECT id,title,extra_toggles_json FROM deals WHERE id=?', (DEAL_ID,)).fetchone()
    extra = json.loads(row['extra_toggles_json'] or '{}')
    print(json.dumps({k: extra.get(k) for k in visible_updates}, indent=2))
PY
```

## Scorecard / workflow-stage backfill pattern

When the realtor asks to fill out a property scorecard/card “as far as we have taken this property,” do not only update factual info fields. Also reconcile the visible workflow scorecard against the evidence already created by earlier runs.

1. Match the deal in the operational store and read the current `current_stage`, `extra_toggles_json`, attachments, and recent events.
2. Check reusable artifacts before asking the realtor: listing data packet, signed docs folder, Matrix/Xposure handoff, SkySlope run result/checklist URL, property lookup outputs, photo manifests/contact sheets, and marketing run summaries.
3. Mark stage/checklist keys complete only when the evidence exists. Common listing keys include:
   - `workflow_stage_1_complete` for CMA/evaluation complete.
   - `workflow_stage_2_complete`, `signed_listing_docs_saved`, `listing_docs_approval` when signed listing docs are saved.
   - `workflow_stage_3_complete`, `skyslope_file_created`, `matrix_incomplete_listing_prepped`, `matrix_missing_fields_surfaced` when SkySlope + Matrix prep is complete.
   - Marketing Go prep keys such as `marketing_go_started`, `photo_cleanup_complete`, `landing_page_ready`, `coming_soon_assets_ready`, `launch_copy_social_email_ready`, and `marketing_package_ready_for_approval` may be true while final approvals remain false.
4. Keep approval-gated items false until approved. For example, do not mark `matrix_photos_uploaded`, `matrix_listing_finished_with_photos`, MLS publish, Buffer scheduling, Mailjet sends, or final photo approval complete unless the evidence and approval exist.
5. If the workflow stage should advance based on completed evidence, use the operational helpers and verify the card moved. For local scripted access, use the packaged Elevate runtime Python with `elevate_cli.data` helpers, for example `/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python`; do not use SQLite or old local DB files.
6. Clean stale downstream artifacts discovered during the sync if they would mislead the next worker, such as old “MLC still in signing” notes after signed docs are received, preview landing URLs when the custom URL is now known, or banned copy terms like “you guys.”
7. Surface remaining blockers explicitly on the card, for example `goLiveBlockers`, `listingBuildOutstanding`, and a concise status field, so the next workflow can continue without reconstructing the audit.

## Xposure current-listing verification pattern

When filling a property card from AOIR Xposure/Matrix, do not rely only on old saved MLS PDFs or local property-data reports. Saved PDFs can be prior/stale listing numbers after a relist or price amendment. Use this repeatable pattern:

1. Use the local/free Browser Use CLI only. Preferred login path is `https://iam.interiorbc.ca/idp/login`; direct `https://xposure.ca/` can hit `ERR_CERT_COMMON_NAME_INVALID` and should be avoided unless it works.
2. After IAM login, open the authenticated Xposure full-search URL directly if the AOIR Xposure tile click times out:
   `https://interiorrealtors.xposureapp.com/portal/air/MlsFullSearch?listingType=mls&firsttime=true`
3. Search the MLS number on the MLS® Number tab. If multiple MLS numbers exist on the deal, treat the number shown by the current active Xposure result and recent seller-update digest as current; preserve older numbers in `priorMlsNumbers` rather than leaving aliases pointed at stale MLS numbers.
4. On the Xposure result grid, first extract the DataTables row with Browser Use `eval` so you have a compact machine-readable source for current price/status/MLS/year/beds/baths/PID/listing id/xpid:
   ```js
   (() => $('#DataTables_Table_0').DataTable().rows().data().toArray())()
   ```
5. For full property/card facts, select the row checkbox, open Actions → Print Preview, choose `Complete: Full`, then switch to the new `PrintEmail?automaticPrint=0&mlsId=...` tab. Capture `document.body.innerText` to a local proof artifact and attach it to the deal as a `property_card_truth_source` when useful.
6. Prefer the current Xposure print view for live card-facing listing facts: current MLS number, status, current/original price, date listed, expiry, price-change date, DOM/CDOM, beds/baths, finished area, property type/subtype, title tiers, taxes, zoning, services, parking, mobile/manufactured-home details, and Xposure public URL/xpid.
7. Use Drive/title/MLC/amendments to cross-check and enrich: PID, legal description, owners/seller names, original MLC dates, signed price amendments, roll/folio/assessment facts. Where old MLC/title address differs from current MLS city/postal, surface the source conflict in `propertyCardTruthSyncSummary` rather than silently choosing one.
8. Update both supported detail fields through `set_deal_fields` and visible/alias keys in `extra_toggles_json`. If no helper exists for arbitrary card keys in the active packaged runtime, merge `extra_toggles_json` directly with the packaged Elevate Python, then insert a `toggle_change` deal event with the source summary. Never use SQLite or old disk DBs.
9. Mark values blank on the Xposure print view as `missing` in `propertyCardTruthStatus` / `propertyCardTruthMissing`, especially possession, foundation, exterior construction, lot dimensions, inclusions, and exclusions.

## Verification checklist

Before final response, verify:

- The correct deal id was updated.
- Expected visible field keys are present in `extra_toggles_json`.
- Alias keys are present when downstream code depends on them.
- `propertyCardTruthLastSyncedAt` changed.
- Missing values are marked missing, not silently ignored, when they are needed for the current stage.
- The visible dashboard modal reflects the write, not just the database row. Open `http://127.0.0.1:9120/admin`, click the card, and inspect `.abm-info-field` input/select/textarea values. A good browser-console check is:

```js
Array.from(document.querySelectorAll('.abm-info-field')).map(f => ({
  label: f.innerText.split('\n')[0],
  value: f.querySelector('input,select,textarea')?.value || ''
}))
```

This check has previously caught a runtime mismatch on a real property: the source venv row was updated, but the UI still showed blank PID/legal/MLC fields until the packaged app runtime store was updated.

## Lesson learned

A property card has previously needed a manual backfill after the realtor flagged missing data post-workflow. Future property workflows must fill the card during the workflow itself, not after the realtor catches a gap.
