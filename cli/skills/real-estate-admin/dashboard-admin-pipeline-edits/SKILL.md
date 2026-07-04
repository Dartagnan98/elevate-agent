---
name: dashboard-admin-pipeline-edits
description: Edit the Admin dashboard's pipeline stages, sidebar labels, and skill lanes. Use when the realtor asks to move, rename, add, or clarify stages/tabs on the real-estate Admin dashboard, especially around Pre-CMA, CMA, Listing Intake, MLC, Lofty, or Google Form workflows.
metadata:
  elevate:
    tags: [real-estate, dashboard, admin, pipeline, cma, listing-intake]
---

# Dashboard Admin Pipeline Edits

Use when the realtor asks to move, rename, add, or clarify stages/tabs on the real-estate Admin dashboard, especially around Pre-CMA, CMA, Listing Intake, MLC, Lofty, or Google Form workflows.

## Quick operational pattern: add a manual Top 25 buyer lead

When the realtor asks to add a named buyer lead to Top 25 and provides a verifier such as email or phone, write the local dashboard records directly. Do **not** run outreach, send messages, or trigger buyer offer-prep automation unless she separately asks.

1. Run `leads_overview` first for current lead-board context, then check for an existing contact with `elevate_db(action='query')` against `contacts` by normalized email and/or display name. If the query wrapper does not pass params correctly, use a one-off literal-safe SELECT with the known provided value instead of guessing.
2. Create or refresh the contact with `elevate_db(action='call', function='upsert_contact', kwargs={...})`:
   - `display_name`: provided name
   - `primary_email` / `primary_phone`: provided verifier
   - `type='buyer'`, `stage='active'`
   - `source_key`: stable manual key such as `manual:lead:<email>`
   - `enrichment`: include `lead_source='Manual / realtor request'`, `lead_types_json='["buyer"]'`, and `tags_json='["Top 25","buyer lead"]'` when applicable.
3. Mark it as a Top 25/hot lead with `elevate_db(action='call', function='update_flags', kwargs={contact_id, buyerSearchActive: true, heatLabel: 'hot', heatScore: 90, heatReason: 'Manually added by the realtor to Top 25 buyer leads.', needsFollowUp: true, actor: ...})`.
4. Set the operator pipeline status with `elevate_db(action='call', function='set_pipeline_status', kwargs={contact_id, status: 'new_lead', set_by: 'operator', actor: ...})`.
5. Create the buyer Admin/Top 25 card with `elevate_db(action='call', function='create_deal', kwargs={title: 'Buyer: <Name>', side: 'buyer', current_stage: 0, province: 'BC', primary_contact_id, source_key, source_label: 'Request from the realtor', fields: {...}, dispatch_initial_stage: false})`.
   - `dispatch_initial_stage: false` is important for simple Top 25 lead additions because buyer stage 0 has offer-prep/deal-matcher automations. A plain new lead should not launch CPS/offer-prep work.
   - Include verifier metadata in `fields`, e.g. `profileEmails`, `profileVerifiers`, `profileVerifierKeys`, `profileHeatLabel`, `profileHeatScore`, and `workflow='top25-buyer-lead'`.
6. Verify with a SELECT joining `deals` to `contacts` and confirm: active buyer deal, `current_stage=0`, contact type buyer, `buyer_search_active=1`, `pipeline_status='new_lead'`, heat hot. Report the contact ID and deal/card ID.

## Quick operational pattern: update Pre-CMA contact + move to CMA / Evaluation

When the realtor gives a missing seller detail and asks to move a Pre-CMA card into CMA / Evaluation, do the board write directly instead of re-running the whole Pre-CMA workflow.

1. Identify the deal with `deals_overview` first. Confirm the target deal ID, primary contact ID, current stage, and title.
2. Read any duplicate/conflicting contacts only if the detail touches identity, email, phone, or Lofty linkage. Use `elevate_db(action='query')` against `contacts`; do not use raw SQL writes.
3. Update the primary contact with `elevate_db(action='call', function='upsert_contact', kwargs={contact_id, display_name, primary_email, primary_phone, type, stage})`. Preserve the existing primary email/source unless the realtor explicitly changes it.
4. Mirror the detail onto the Admin card using `admin_deal(action='set_fields')` with workflow fields where available, e.g. `workflow_seller_phone`, `workflow_contact_phone`, plus a short workflow note.
5. Move the card with `admin_deal(action='move', to_stage=1, force=true)` when the realtor explicitly asks to move from Pre-CMA to CMA / Evaluation. Stage 1 is CMA / Evaluation; stage 0 is Pre-CMA.
6. Record a deal activity with `elevate_db(action='call', function='record_deal_activity', ...)` and add a contact note if the changed detail is client/contact data.
7. Verify with `admin_deal(action='show')` and a SELECT joining `deals` to `contacts`. Report the new stage and any current gate blockers, usually `cma_pdf_ready`, `pricing_story_approved`, `client_yes_to_listing`, `listPrice`, and `cma_report`.

Pitfall: `admin_deal(action='show')` may show `canAdvance=false` even when missing lists are empty because the phase/run gate is not complete. If the realtor explicitly asked for the move, use `move` with `force=true` and verify the result instead of looping on the gate.

## Key Files

Current data access note: Admin dashboard operational data is Postgres-backed through the embedded Elevate data layer. Do not use old `sqlite3` / `operational.db` snippets unless you have explicitly verified a legacy checkout. For live data changes, first identify what is serving the visible dashboard. If the running process is the packaged app's own Python runtime running `elevate_cli.main dashboard --port 9120`, use that packaged Python runtime for data writes:

```bash
/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 - <<'PY'
from elevate_cli.data import connect
# query/mutate live dashboard data here
PY
```

Do not assume a source-checkout virtualenv's Python writes to the same live store; it can update the source checkout data while the visual dashboard continues reading the packaged app runtime data. Verify by querying `/api/admin/deals` from the logged-in dashboard/browser after the write. If the dashboard is being served from a source checkout instead of the packaged app, run scripts from that checkout's `cli` directory with its own `.venv/bin/python` and `from elevate_cli.data import connect`, or use the `elevate_db` tool when available.

### Safe live-runtime source overrides without editing the signed app bundle

When the packaged dashboard process is running from the app bundle's own Python runtime but a source checkout has the corrected wording/code, do **not** patch files inside the signed app bundle. Use a writable overlay instead:

```bash
OVERLAY=~/.elevate/runtime-overrides/elevate-cli-<short-reason>
SRC_APP=/Applications/Elevate.app/Contents/Resources/cli
SRC_CHECKOUT=<path-to-source-checkout>/cli
rm -rf "$OVERLAY"
mkdir -p "$(dirname "$OVERLAY")"
/usr/bin/rsync -a --delete "$SRC_APP/" "$OVERLAY/"
cp "$SRC_CHECKOUT/elevate_cli/admin_deal_flow.py" "$OVERLAY/elevate_cli/admin_deal_flow.py"
PYTHONPATH="$OVERLAY" /Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 -m elevate_cli.main dashboard --port 9120 --host 127.0.0.1 --no-open --tui
```

Verify imports and live data against the overlay before reporting success:

```bash
PYTHONPATH="$OVERLAY" /Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 - <<'PY'
import elevate_cli.admin_deal_flow as f
print(f.__file__)
PY
```

Then query the live dashboard API with the session token, using `/api/deals/<deal-id>/context` for full `dealFlow`/gate output. `/api/admin/deals` is a board summary and may omit the flow details.

```bash
token=$(tr -d '\n' < ~/.elevate/dashboard-session-token)
curl -fsS -H "X-Elevate-Session-Token: $token" \
  http://127.0.0.1:9120/api/deals/<deal-id>/context -o /tmp/deal-context.json
python3 - /tmp/deal-context.json <<'PY'
import json, sys
j=json.load(open(sys.argv[1]))
flow=j.get('dealFlow') or {}; gate=flow.get('gate') or {}
print('missing', [i.get('id') for i in gate.get('missingChecklist') or []])
print('checklist', [i.get('id') for i in flow.get('checklistItems') or []])
PY
```

Pitfall: importing the source checkout directly by putting `<elevate-checkout>/cli` first on `PYTHONPATH` can also change which data-layer/schema code is used and may make the same deal appear at a different stage than the packaged app. Prefer copying only the intended corrected file(s) into an overlay based on the packaged `Resources/cli`, then run the packaged Python with `PYTHONPATH=$OVERLAY`.

In `<next-dashboard-checkout>`:

- `dashboard/src/lib/realestate/command-center.ts`
  - `RealtorDealStage` union
  - `STAGES` order
  - `inferStage(...)`
  - `inferOwner(...)`
  - `nextAction(...)`
- `dashboard/src/app/(dashboard)/deals/page.tsx`
  - Admin board title/description
  - stage card/column descriptions
- `dashboard/src/lib/realestate/skill-artifacts.ts`
  - dashboard skill-operation lanes shown in the Admin/overview surface
- `dashboard/src/components/layout/sidebar.tsx`
  - desktop sidebar nav label
- `dashboard/src/components/layout/bottom-nav.tsx`
  - mobile bottom/more nav label

## Current Admin Pipeline Structure

The intended admin board structure is:

1. `Pre-CMA`
   - Google Form intake
   - Lofty contact verification/create/update
   - pre-CMA handoff before pricing work starts
2. `CMA / Evaluation`
   - CMA PDF
   - pricing evaluation
   - seller-facing price story
3. `Listing Intake`
   - client said yes to listing
   - triggers MLC intake
   - missing fields
   - document prep
   - the realtor approval before signing send

4. `SkySlope & Matrix Prep`
   - signed MLC/listing docs saved to Drive
   - SkySlope file creation/sync
   - Matrix/AOIR incomplete listing prep
   - verified checklist/status rows before moving on
5. `Marketing Go`
   - next step after SkySlope & Matrix Prep
   - automatically run photo cleanup first
   - ask the realtor for missing Marketing Go answers and the photographer Google Drive/photo link if not already provided
   - save cleaned photos into the listing Google Drive folder
   - select the best 99 Matrix photos if more than 99 were provided
   - upload/finalize photos in Matrix/AOIR while marketing assets are being created
   - coming-soon marketing
   - landing page
   - launch copy, social posts, emails, and listing assets
   - Matrix/MLS still must not be published without approval
5. `Listing Live / Marketing`
   - activated/live listings only
   - seller updates, live marketing, showing feedback, price changes, offer monitoring
6. `Re List`
   - sits between active listings and accepted offer
   - for cancelled/expired/relaunch listings that need relist strategy, refreshed launch assets, SkySlope relist file, and Matrix/Xposure relist draft checks
   - MLS publish / marketing send still requires the realtor approval

Important correction from the realtor: the separate `MLS Listing` / `MLS Entry` dashboard bucket should not appear in the Listing Admin pipeline. Activated listings belong directly in `Listing Live / Marketing`. If old data has listing deals in stage 5, move them to stage 6 instead of preserving an MLS Listing column.

## Moving an existing Pre-CMA card into CMA / Evaluation

Use this when the realtor asks to add a known property to the CMA/evaluation pipeline and the card may already exist in Pre-CMA or another staging bucket. Do **not** create a duplicate until you first check the live board.

1. Call `deals_overview` first and search the returned `deals` list for the address/title/source key. If an existing listing deal exists, move that card instead of creating a new one.
2. Stage mapping correction: listing stage `1` is `CMA / Evaluation`. Moving a listing card to stage 1 is approval to start the CMA/evaluation workflow or ask only CMA-blocking questions. Stage `2` is `Listing Intake` and triggers MLC/listing-intake work.
3. If the existing card is in a non-linear/terminal-looking stage such as `10` but represents a Pre-CMA/staging card, use the live packaged data runtime and `move_deal_stage(..., to_stage=1, actor='executive-assistant', force=True)` so the move records a `stage_transition` and dispatches stage-entry actions. Example:

```python
from elevate_cli.data import connect, get_deal, move_deal_stage, record_deal_activity, list_action_runs

DEAL_ID = '<existing-deal-id>'
with connect() as conn:
    before = get_deal(conn, DEAL_ID)
    if before is None:
        raise SystemExit(f'Deal not found: {DEAL_ID}')
    after = before if before.get('currentStage') == 1 else move_deal_stage(
        conn, DEAL_ID, to_stage=1, actor='executive-assistant', force=True
    )
    record_deal_activity(
        conn,
        DEAL_ID,
        actor='executive-assistant',
        summary='Moved existing property card to Listing CMA / Evaluation pipeline per the realtor request.',
        tools=['deals_overview', 'move_deal_stage'],
        confidence=1.0,
    )
    print(after.get('id'), after.get('title'), after.get('currentStage'), after.get('stageEnteredAt'))
    print(list_action_runs(conn, deal_id=DEAL_ID, limit=10))
```

4. If the title still says `Pre-CMA`, rename it to `CMA / Evaluation` after the move so the visible board matches the stage. Use an operational data update plus `record_deal_activity`; do not silently leave stale title wording.
5. Verify with a second `deals_overview`: the card should appear in `currentStage: 1`, `byStage['1']` should increase, and any previous staging bucket count should decrease. Also inspect/list action runs when available; stage-entry CMA actions may be queued/running. Never report the external CMA deliverable as complete unless the CMA skill/run has actually finished and produced verified artifacts.

## Answering Pipeline Workflow Breakdown Questions

Use this path when the realtor asks what happens workflow-wise in each Admin pipeline section or wants checklist logic for property scorecards.

Ground the answer before writing the breakdown:
1. Call `deals_overview` first to see the live stage numbers, stage distribution, buyer vs listing sides, and any unusual buckets.
2. Query the Admin action registry through `elevate_db`, not filesystem guesses:
   ```sql
   select name, side, from_stage, to_stage, trigger, field_key, skill, approval_required, enabled
   from admin_action_registry
   order by coalesce(to_stage,-1), enabled desc, name;
   ```
   This reveals which skills auto-run on stage entry or toggle changes.
3. If labels/descriptions are needed, inspect the dashboard source, especially:
   - `<next-dashboard-checkout>/dashboard/src/lib/realestate/command-center.ts` for `RealtorDealStage` and `STAGES`.
   - `<next-dashboard-checkout>/dashboard/src/app/(dashboard)/deals/page.tsx` for `STAGE_DESCRIPTIONS` shown on the Admin board.
4. Distinguish listing-side stages from buyer-side stages because the same numeric stage can mean different work by side. In the current registry, listing stages are roughly: 0 Pre-CMA, 1 CMA/Evaluation, 2 Listing Intake/MLC, 3 SkySlope & Matrix Prep, 4 Marketing Go, 5 Listing Live, 6 Accepted Offer, 7 Condition Removal, 8 Closed. Buyer stages are roughly: 0 Buyer Offer Prep, 1 Buyer Accepted, 2 Buyer Conditions, 3 Buyer Subjects Off / Closing Admin.
5. Mention any normalization findings instead of silently ignoring them. Example: active cards in a stage `10` bucket may be Pre-CMA imports that should be cleaned into the normal Pre-CMA stage.

Good response structure:
- Keep it practical and scorecard-oriented.
- For each stage, list: purpose, workflow that runs, checklist items, and move-forward rule.
- Include approval gates: MLS publish, client-facing sends, signature sends, photo approval, price/copy approval, and phase-complete overrides.
- For property scorecards, recommend fields for current section, current objective, auto-run workflows, checklist, blockers, next safe action, approval gates, and move-forward rule.

## Deal Cleanup From Claude-on-Mac / External Session Evidence

Use this path when the realtor says she completed admin work in Claude on the Mac, asks whether the dashboard pipeline is correct, or asks to update scorecards from work done outside Elevate.

Working pattern:
1. Pull the current Admin pipeline first with `deals_overview`. Do not infer the board from memory.
2. Search Claude local session logs before asking the realtor to repeat herself. Useful locations:
   - `~/.claude/projects/**/*.jsonl`
   - `~/Library/Application Support/Claude/**/local_*.json`
   - Recent EOD/midday heartbeat outputs can contain the most compact deal-state summaries.
3. Extract only verifiable deal facts: signed docs filed, SkySlope transaction IDs, Matrix/Xposure draft/listing numbers, subject-removal dates, deposit receipts, completion/possession amendments, MLS-live confirmation, co-op/other-side agent, and explicit seller decisions.
4. Apply safe dashboard updates through Admin tools only. Attach evidence/events when a field is not directly writable. Do not publish MLS, send emails, send signatures, or mark photo/copy/price approvals from transcript evidence alone.
5. Re-run `deals_overview` after changes and report: moved, correct as-is, uncertain/needs the realtor.

Stage rules learned from cleanup runs:
- Signed MLC + SkySlope file + Matrix/Xposure incomplete draft = `SkySlope & Matrix Prep`, not `Listing Intake`, and not `Listing Live` until MLS is actually live or the realtor confirms it is live.
- MLS-live confirmation from the realtor = move the listing to `Listing Live / Marketing`, set the listing/live date when clear, and create/queue a **draft-only** new listing alert task. Do not send the alert without approval and final MLS/list-price/photo/link details.
- Accepted offer with subjects still pending = `Accepted Offer` for listing-side deals and the buyer condition-tracking stage for buyer-side deals. Record subject-removal target, co-op/other-side agent, deposit due/received, and buyer checklist status if known.
- Subject removal/condition waiver + deposit receipt = `Condition Removal` / firm-tracking. Do not move to `Closed` until completion has actually occurred and closeout evidence is present.
- Future completion dates must not sit in `Closed`; move them back to `Condition Removal` even if a scorecard says “Subjects Off”.
- Closed/completed deals belong only in `Closed`. If the dashboard stage is Closed but raw status still says active and the Admin tool rejects status updates, report it as a backend/dashboard-close action needed rather than forcing a write.
- Buyer pipeline should start at `Offer Prep`; do not create earlier buyer intake/search/tour stages on the Admin board.
- **Top 25 is prospects only.** Never place active listings, accepted offers, under-contract buyers/sellers, or closed deals in Top 25. If the realtor asks to remove a Pre-CMA prospect card from the dashboard/Top 25, do a non-destructive move out of the visible Top 25/prospect stage rather than deleting the record.
- If evidence conflicts, leave the stage unchanged and add an event/note. Examples: a filed CPS at one price but a newer counter/offer pending, or a signed package but seller decision still unresolved.

Verification / portal limitations:
- A Claude transcript saying “SkySlope transaction created” is enough to add an evidence note, but not enough to claim the exact portal state unless a transaction ID/source key/checklist URL is present or SkySlope is directly checked.
- If a deal has no SkySlope `source_key`/transaction ID in Elevate, report SkySlope verification as blocked even if local evidence says a portal action happened.
- When the realtor corrects relationship context (for example, a spouse/past client appears on a deal card but title shows only one owner), record the relationship as context and do not treat that person as a seller/owner unless documents verify it.

## Score Card Workflow Checklist Revamp

Use this path when the realtor asks to revamp Admin dashboard property score cards, add checklists to each pipeline section, or make workflow progress visible when a section gets hung up.

For the current live Admin design shell, the score cards and modal checklist are split across these files:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/admin-data.ts
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/admin-mappers.ts
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/components/admin-board.tsx
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/components/deal-modal.tsx
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/admin.css
```

Implementation pattern:
1. In `admin-data.ts`, update `ADMIN_PHASE_DETAILS` so each listing pipeline phase has a concrete workflow checklist, not vague legacy labels. Include the associated workflow steps for Pre-CMA, CMA, MLC/Listing Intake, SkySlope/Matrix, Marketing Go, Live Listing, Accepted Offer, Subject Removal, Closing, and Closed.
2. Also update `ADMIN_PIPELINE[].next` and fallback `ADMIN_DEALS[].next` strings so cards read like workflow/checklist summaries, not old labels such as `Flodesk mailout sent` or `Pre-CMA Google Form filled`.
3. In `admin-mappers.ts`, update `LISTING_STAGE_NEXT` so live Postgres deal cards inherit the same checklist-oriented wording. Otherwise the UI can still show stale `Next` text even after `admin-data.ts` is patched.
4. In `components/admin-board.tsx`, change the small card label from `Next` to `Checklist` if the realtor is asking for score cards/checklists.
5. In `components/deal-modal.tsx`, make the phase accordion useful for completion tracking:
   - initialize `openPhases` with all pipeline phase IDs so every section's checklist is visible by default.
   - store checked item keys in localStorage per deal, for example `admin-scorecard-checklist:${deal.id}`.
   - calculate and render counts like `{checkedCount}/{detail.checklist.length}` for each phase and for the current phase gate.
   - render each checklist item as a button row with an `aria-pressed` state and a checked visual state, so items can be checked off while the workflow is being completed.
   - mark a phase `done` when all checklist items in that phase are checked, not merely because the phase index is behind the current stage.
6. In `admin.css`, add styling for `.abm-check-row`, `.abm-check-box[data-checked="true"]`, and a `.done` text state.

Example checklist items for listing phases:
- Pre-CMA: dashboard card created, Lofty seller verified, Mailjet seller list verified, pre-CMA notes saved, old Xposure/Matrix pulled, recent sold comps/photos pulled, CMA handoff ready.
- CMA: inputs verified, comparable set selected, prospecting-tool/property section confirmed with the realtor, CMA built in saved design, price story/list price approved, client said yes.
- Listing Intake: MLC triggered, missing fields surfaced, Drive docs checked before asking, docs prepared, signature placements ready, the realtor approval received before sending.
- SkySlope/Matrix: signed docs saved, docs matched to deal, SkySlope created/synced, incomplete Matrix/Xposure listing prepped, missing fields surfaced, draft ready but not published.
- Marketing Go: photo link received/requested, questions/blockers surfaced, photo cleanup complete, cleaned photos saved, best 99 selected if needed, Matrix photos uploaded, landing/social/email assets ready, package ready for approval but not sent/posted.

After edits, rebuild and sync the live app bundle if the realtor uses the desktop app:

```bash
cd <elevate-checkout>/cli/web
npm run build
SRC=<elevate-checkout>/cli/elevate_cli/web_dist
for dist in \
  /Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist \
  ~/Library/Caches/com.elevationrealestate.elevate.ShipIt/update.*/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist
 do
  [ -d "$dist" ] && rsync -a --delete "$SRC/" "$dist/"
done
```

Verify in the browser at `http://127.0.0.1:9120/admin`:

```js
document.body.innerText.includes('WORKFLOW CHECKLIST')
document.body.innerText.includes('Prospecting-tool/property section confirmed with the realtor')
```

Open a card, click one `.abm-check-row`, and verify the visible count changes from `0/N` to `1/N`. If `document.body.innerText` still shows old wording after a source patch, reload the page and confirm the built bundle was synced, because the Electron app may be serving cached `web_dist`.

## Score Card Reusable Info Sections

Use this path when the realtor asks for property card info sections that auto-fill during workflow review and can be referenced by other skills.

Current implementation lives in the Admin design-shell modal:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/components/deal-modal.tsx
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/admin.css
```

Implementation pattern:
1. Add `InfoFieldDef` / `InfoSectionDef` definitions near the top of `deal-modal.tsx`.
2. Define field lists for `CORE_PROPERTY_FIELDS` and `SELLER_INFORMATION_FIELDS`.
3. Store custom info values with `api.setAdminDealToggle(deal.id, field.key, value || null)`. This writes to deal `extraToggles`, making the values available to later admin skills through deal context.
4. Prefer auto-filled values from `ctx.deal`, `ctx.primaryContact`, `ctx.coContacts`, and existing `ctx.deal.extraToggles` before showing blank fields.
5. Render the info sections above the Phase Gate in the left Transaction File card. Core Property appears for all deals. Seller Information appears for listing-side deals only.
6. Keep sections collapsible and show `filled/total` counts so future stage-specific sections can unlock as the card moves through the dashboard.
7. Add CSS for `.abm-info-stack`, `.abm-info-section`, `.abm-info-head`, `.abm-info-grid`, `.abm-info-field`, and `.abm-info-placeholder` in `admin.css`.
8. Rebuild from `<elevate-checkout>/cli/web` and sync `web_dist` into the desktop app bundle/cache.

Initial sections the realtor requested:
- Core Property: property address, unit number, city, province, postal code, MLS number, PID, legal description, roll/folio number, property type, tenure/title type, Listing Drive folder link, SkySlope file link, Matrix/Xposure draft link, live listing URL, landing page URL.
- Seller Information: seller legal/preferred names, emails, phones, mailing address, residency status, signing location/province, signing authority, preferred signing email, lawyer/notary chosen, lawyer/notary name, firm, email, phone, city/province.
- Buyer Information: buyer legal/preferred names, emails, phones, mailing address, signing location/province, preferred signing email, signing order, buyer lawyer/notary chosen, lawyer/notary name/firm/email/phone/city/province, buyer agent name/email/phone/brokerage. Show for buyer-side cards and listing-side accepted offers.
- Listing Contract / MLC: unlock for listing-side cards at Listing Intake and later. Fields: listing price, commission terms, cooperating brokerage commission, contract effective date, expiry date, planned MLS/live date, coming-soon date, listing status, included/excluded items, tenancy details, seller instructions, occupancy, showing instructions, lockbox code/status, sign/rider status.
- Accepted Offer Terms: unlock at Accepted Offer and later for both sides. Fields: accepted offer PDF link, final acceptance date, accepted price, deposit amount/due timing/holder, completion date, possession date/time, adjustment date, subject removal date/time, rescission deadline if applicable, included/excluded items, special terms/addenda, subject-free flag, cleaning requirement, inspection access notes, repair/deficiency obligations, buyer/seller obligations.
- Subject / Condition: unlock at Accepted Offer/Conditions. Fields: financing, inspection, insurance, title review, PDS/document review, strata/BIR/park approval/RTB-10/site lease deadlines, sale-of-property condition, custom condition deadlines, status for each condition, and subject-removal document links.
- Documents + Compliance: unlock once docs begin and remain visible. Fields/checklist statuses with source links for CPS, signed MLC, DORT, PDS, title, MLS realtor sheet with commission, deal sheet/TRS, expected remuneration disclosure, assignment notice, subject removal, deposit receipt, tax notice, strata docs, BIR, MHR, RTB-10, park rules/site lease, lawyer info, SkySlope row status, missing/order-needed status.
- Calendar / Deadlines: unlock at Accepted Offer and later. Fields: duplicate-check status and created-event links/status for rescission, subject removal, deposit, inspection, BIR, strata/doc review, completion, possession, adjustment, cleaning coordination, lawyer/conveyancer reminders.
- Marketing / Listing Build: unlock at Marketing Go and later. Fields: photo link/status, cleaned photos, floor plans/measurements source, listing description, feature bullets, approved price, MLS remarks, landing page, social graphics, email blast, Buffer/Mailjet IDs, open house, signage/rider, launch approval.

Design intent from the realtor: these cards are not extra manual chores. They should be reusable source-of-truth deal facts that skills auto-populate from signed documents, Gmail/Drive, SkySlope, Matrix/Xposure, and the realtor notes, then read before asking her or re-extracting. Each field should carry value + source/status such as verified, inferred, missing, or user-corrected. If a workflow discovers a better verified value, update the card once so downstream skills inherit it.

For staged unlocks, add `minListingPhase` / `minBuyerPhase` to the section definition and filter `INFO_SECTIONS` by the current pipeline index. Keep future sections in the same shape so they can open up as a card moves through the dashboard.

## Skill Lane Expectations

`dashboard/src/lib/realestate/skill-artifacts.ts` should include dashboard operations for:

- `Pre-CMA Form` using skill slug `pre-cma-google-form`
- `CMA / Evaluation` using skill slug `cma`
- `Listing Intake / MLC` using skill slug `mlc`

These lanes should route to `/deals` along with property/CMA-related lanes.

## Admin Action Registry Expectations

The live dashboard stage labels and the Postgres-backed `admin_action_registry` triggers must agree. For listing-side cards:

- Stage `0` = Pre-CMA.
- Stage `1` = CMA / Evaluation and should trigger skill `cma`, not `mlc`.
- Stage `2` = Listing Intake and should trigger only `mlc` intake/doc prep.
- Stage `6` = Re List and should trigger skill `real-estate-admin/relisting`, not `offer-review`. Accepted Offer is stage `7` in the live Admin board.

Important correction learned from a past stage move: moving a property into the Re List dashboard section is approval to start the relisting workflow. If legacy/default registry rows exist for listing stage 6 named like `S6 Review accepted-offer package` or `Accepted Offer: Review package` with skill `offer-review`, disable them for stage 6, seed/enable a stage-entry row such as `Re List: Run relist workflow` using skill `real-estate-admin/relisting` and `skill_args={"mode":"dashboard-stage-entry"}`, then skip any wrong queued/running offer-review run and remove its one-shot cron job. If a duplicate relist run is accidentally queued while repairing the trigger, keep the newest/desired relist run, mark the duplicate action run `skipped`, and remove the duplicate cron job.

Important correction learned from a past stage move: moving a CMA-approved property into Listing Intake should not queue `signing-package` sync or `skyslope-sync`. Those belong after MLC/signing readiness or signed-doc evidence, not at Listing Intake entry. If legacy/default registry rows exist for listing stage 2 named like `S2 Sync signing status` or `S2 Check SkySlope opening docs`, disable them and skip any already-created queued runs for that deal.

Use the current Postgres data layer from `<elevate-checkout>/cli`, not old sqlite snippets:

```bash
cd <elevate-checkout>/cli
.venv/bin/python - <<'PY'
from elevate_cli.data import connect
from elevate_cli.data.deals import move_deal_stage, set_deal_fields, set_deal_toggle
from elevate_cli.data._util import now_iso
import json

DEAL_ID = '<deal id>'
ACTOR = 'assistant:dashboard-stage-correction'
APPROVED_PRICE = 949900  # set per property
now = now_iso()

with connect() as conn:
    # Record approved price / CMA completion before the stage move when available.
    set_deal_fields(conn, DEAL_ID, actor=ACTOR, fields={'listPrice': APPROVED_PRICE})
    set_deal_toggle(conn, DEAL_ID, field='cmaStatus', value=f'Complete - clients approved ${APPROVED_PRICE:,.0f} list price', actor=ACTOR)
    set_deal_toggle(conn, DEAL_ID, field='workflow', value='listing-intake', actor=ACTOR)
    set_deal_toggle(conn, DEAL_ID, field='workflowLabel', value='Listing Intake / MLC', actor=ACTOR)
    set_deal_toggle(conn, DEAL_ID, field='workflow_stage_1_complete', value=True, actor=ACTOR)
    set_deal_toggle(conn, DEAL_ID, field='workflow_stage_2_started', value=True, actor=ACTOR)

    # Move to Listing Intake (stage 2). Use force only when the stored card lagged behind
    # reality but the realtor explicitly confirms CMA is complete and price is approved.
    deal = move_deal_stage(conn, DEAL_ID, to_stage=2, actor=ACTOR, force=True)

    # Keep S2 clean: MLC is okay; signing/SkySlope are premature at Listing Intake entry.
    wrong = conn.execute("""
        SELECT id,name,skill FROM admin_action_registry
        WHERE side='listing' AND trigger='stage_entry' AND to_stage=2
          AND skill IN ('signing-package','skyslope-sync','real-estate-admin/signing-package','real-estate-admin/skyslope-sync')
    """).fetchall()
    reason = 'Skipped/corrected: Listing Intake should trigger MLC intake/doc prep only; signing and SkySlope belong after MLC/signature readiness or signed-doc evidence.'
    for row in wrong:
        conn.execute('UPDATE admin_action_registry SET enabled=0, updated_at=? WHERE id=?', (now, row['id']))
        conn.execute("""
            UPDATE admin_action_runs
            SET status='skipped', updated_at=?, completed_at=?, result_json=?
            WHERE deal_id=? AND status='queued' AND registry_id=?
        """, (now, now, json.dumps({'status': 'skipped', 'actor': ACTOR, 'reason': reason}), DEAL_ID, row['id']))

    conn.commit()
    print(deal['id'], deal['title'], 'stage', deal['currentStage'], 'listPrice', deal.get('listPrice'))
PY
```

After a stage move, do not assume the queued admin action actually produced a document. Immediately inspect the newly created `admin_action_runs` rows for that deal. If `status='queued'` but `payload_json` contains `dispatchBlocked` (for example `admin setup is required before starting admin work: browser_workflows`), the workflow did not run and no prepped doc exists yet. In that case:

1. Tell the realtor the exact blocker, not just that the run is queued.
2. Inspect `deal_attachments` for existing `form_draft` / `form_draft_json` artifacts before saying where the doc is.
3. If the MLC skill was blocked before creating its artifact, create a run-specific intake-prep artifact under `<elevate-home>/data/listings/<slug>/mlc/<slug>-mlc-intake-prep-<run_id>.md` plus JSON, attach them to `deal_attachments`, and update the affected queued `admin_action_runs` to `waiting_human` with `output_path`, `completed_at`, and `result_json` containing the missing fields and blocker. This avoids leaving the realtor with a phantom queued document.
4. Keep the artifact status clear: `waiting_human` / intake prep only, not a filled signature-ready package.

Example repair query pattern:

```bash
cd <elevate-checkout>/cli
.venv/bin/python - <<'PY'
from elevate_cli.data import connect
import json
DEAL_ID = '<deal id>'
with connect() as conn:
    runs = conn.execute("""
        SELECT r.*, a.name AS action_name, a.skill, a.to_stage
        FROM admin_action_runs r
        LEFT JOIN admin_action_registry a ON a.id=r.registry_id
        WHERE r.deal_id=%s
        ORDER BY r.created_at DESC
    """, (DEAL_ID,)).fetchall()
    attachments = conn.execute("""
        SELECT kind, file_path, summary, source_run_id, created_at
        FROM deal_attachments
        WHERE deal_id=%s
        ORDER BY created_at DESC
    """, (DEAL_ID,)).fetchall()
    print(json.dumps({'runs': [dict(r) for r in runs], 'attachments': [dict(a) for a in attachments]}, indent=2, default=str))
PY
```

If the realtor moves a card to CMA / Evaluation and asks why the CMA did not start, apply the same Postgres-backed pattern: verify `admin_action_registry` has listing stage 1 wired to `cma`, fix the row through `elevate_cli.data.connect()` if needed, then immediately create/run the CMA action for the already-moved deal. Do not wait for another user approval; the stage move is the trigger.

## Sidebar / Naming Pitfalls

There are two dashboard codepaths that can be confused:

1. `<next-dashboard-checkout>/dashboard/...` is the Next dashboard codebase.
2. The live dashboard launched by `elevate dashboard --port 9120` can come from `<elevate-checkout>/cli/web/src/App.tsx` and built assets under `cli/elevate_cli/web_dist`.

the realtor expects the sidebar label to be **Admin**, not **Deals**, even if the route remains `/deals` or redirects internally.

For the Next dashboard, verify:

- `dashboard/src/components/layout/sidebar.tsx`
- `dashboard/src/components/layout/bottom-nav.tsx`
- `dashboard/src/app/(dashboard)/deals/page.tsx` heading says `Admin`

For the live Elevate dashboard, the visible Admin board columns are in `<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx` under `ADMIN_COLUMNS`, `ADMIN_PHASE_AUTOMATIONS`, and `ADMIN_STAGE_CHECKLISTS`. After changing this live dashboard code, run `npm run build` from `<elevate-checkout>/cli/web` so `cli/elevate_cli/web_dist` is regenerated; otherwise the realtor may not see the new column in the running dashboard. Marketing Go should be the listing S4 column directly after S3 SkySlope & Matrix Prep. If the realtor says she only sees `Agent Hub`, `Tasks`, `Memory`, `Skills`, and `Automations`, check the active dashboard entitlement before assuming the sidebar label patch failed:

```bash
cd <elevate-checkout>/cli
<elevate-checkout>/cli/venv/bin/python - <<'PY'
from elevate_cli.access import dashboard_access_status
import json
print(json.dumps(dashboard_access_status()["packs"], indent=2))
PY
```

If this local beta dashboard should show Admin and `realEstateAdmin` is false/locked, restore the local entitlement carefully:

```bash
cd <elevate-checkout>/cli
<elevate-checkout>/cli/venv/bin/python - <<'PY'
from elevate_cli.access import update_entitlement, dashboard_access_status
for entitlement in ["real_estate_admin", "real_estate_cma"]:
    update_entitlement(entitlement, status="active", owned_snapshot=True)
import json
print(json.dumps(dashboard_access_status()["packs"], indent=2))
PY
```

Then verify the live UI with browser navigation to `http://127.0.0.1:9120/`; the sidebar should show **REAL ESTATE** with **Today** and **Admin** above the **AGENT** section. If the Real Estate section is collapsed, tell the realtor to click the `REAL ESTATE` header.

## Listing Pipeline MLS Bucket Removal

When the realtor asks to delete the MLS Listing / MLS Entry bucket from the live Admin dashboard:

1. Patch `<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx`.
2. Add/use a `visibleAdminStages(side)` helper that filters out stage `5` only for `side === "listing"`:
   - `return ADMIN_STAGE_NUMBERS.filter((stage) => !(side === "listing" && stage === 5));`
3. Update `adminNextStage(card)` so listing stage `4` advances directly to stage `6`:
   - `if (card.side === "listing" && card.stage === 4) return 6;`
4. In `AdminKanbanSwimlane`, derive `visibleStages = visibleAdminStages(side)` and use it for:
   - the listing pipeline order pills
   - `gridTemplateColumns`
   - the column map that renders `AdminKanbanColumn`
5. Move existing active listing deals out of stage 5:

```bash
sqlite3 "~/.elevate/data/operational.db" "
UPDATE deals
SET current_stage=6,
    stage_entered_at=datetime('now'),
    updated_at=datetime('now'),
    listing_published_at=COALESCE(listing_published_at, datetime('now'))
WHERE side='listing' AND current_stage=5 AND status='active';
"
```

6. Rebuild live dashboard assets from `<elevate-checkout>/cli/web`:

```bash
npm run build
```

7. Verify:

```bash
sqlite3 "~/.elevate/data/operational.db" "
SELECT current_stage, COUNT(*)
FROM deals
WHERE side='listing' AND status='active'
GROUP BY current_stage
ORDER BY current_stage;
SELECT id,title,current_stage
FROM deals
WHERE side='listing' AND current_stage=5;
"
```

Expected: no active listing deals remain in stage 5, and the rendered Listing Admin board skips the MLS Entry column.
2. Patch stage types/order and stage inference in `command-center.ts`.
3. Patch `nextAction(...)` so each new stage explains the correct next step.
4. Patch `deals/page.tsx` with short stage descriptions for user clarity.
5. Patch `skill-artifacts.ts` so skill lanes exist and point to `/deals`.
6. Patch sidebar and bottom nav labels if the user references the Admin tab.
7. If a workflow skill is missing, create/update it under `real-estate-admin`.

## Buyer Pipeline Starts at Offer Prep

the realtor does not want the Buyer Admin dashboard to show the early buyer nurture columns. The buyer section should start at `Offer Prep`, not `Intake`.

If the Next dashboard's Buyer / Offer Prep column is filled with random names, check `dashboard/src/lib/realestate/command-center.ts` before touching live deal data. `inferStage(...)` can falsely classify old contacts as `Offer Prep` if it scans `last_message` for generic words like `offer` from old CRM campaigns or notes. Keep Offer Prep inference narrow and metadata-driven, for example:

```ts
const metadata = [row.stage, row.tags].map(tokenize).join(' ');
const haystack = [metadata, row.last_message].map(tokenize).join(' ');
// ... specific accepted/subject/deposit checks can still inspect haystack ...
if (/\b(offer prep|buyer-cps|cps draft|contract of purchase and sale)\b/.test(metadata)) return 'Offer Prep';
```

Do not use `haystack.includes('offer')` for Offer Prep. It pulls in stale lead nurture/history rows and makes the buyer section look populated when there are no active Offer Prep deals.

If the realtor says nobody should be in Offer Prep right now, do not keep trying to reclassify those contacts. Add a temporary cleared-stage filter in `command-center.ts` so the dashboard data and counts exclude Offer Prep entirely until she asks to repopulate it:

```ts
const CLEARED_STAGES: RealtorDealStage[] = ['Offer Prep'];

function stageCounts(deals: RealtorDeal[]) {
  return STAGES.map((stage) => ({
    stage,
    count: CLEARED_STAGES.includes(stage) ? 0 : deals.filter((deal) => deal.stage === stage).length,
  }));
}

// inside getRealtorCommandCenter()
deals = leadResult.rows
  .map(leadToDeal)
  .filter((deal) => !CLEARED_STAGES.includes(deal.stage))
  .sort(...);
```

## Removing Prep-CMA / CMA Cards from the Admin Pipeline

Use this when the realtor asks to delete/remove a property from the Prep-CMA, CMA, or listing-admin pipeline. This is a dashboard/admin data removal, not an external SkySlope/Matrix delete unless she explicitly names those systems.

Current data access correction: operational Admin data is in embedded Postgres via `elevate_cli.data.connect()` or `elevate_db`, not sqlite. Do not use old `sqlite3 ~/.elevate/data/operational.db` snippets from past sessions.

Fast safe pattern, run from the CLI checkout root:

```bash
.venv/bin/python - <<'PY'
from elevate_cli.data import connect

# Each group is OR-within, AND-across. Include common spelling variants.
# Key each entry by the property's civic number/street so the match is
# specific to that one address.
TERMS = {
    '<civic-number> <street-name>': [['<civic-number>'], ['<street-name>', '<street-name-variant>']],
}
RELATED = ['admin_action_runs', 'deal_contacts', 'deal_attachments', 'deal_events']

with connect() as conn:
    rows = conn.execute("""
        SELECT id,title,side,current_stage,status,listing_address,extra_toggles_json,updated_at
        FROM deals
        ORDER BY updated_at DESC
    """).fetchall()
    candidates = []
    for row in rows:
        d = dict(row)
        blob = ' '.join(str(d.get(k) or '') for k in d).lower()
        for label, groups in TERMS.items():
            if all(any(term in blob for term in group) for group in groups):
                candidates.append((label, d))
                break

    print('CANDIDATES')
    for label, d in candidates:
        print(label, d['id'], '|', d['title'], '| stage', d['current_stage'], '|', d['status'], '|', d.get('listing_address'))

    for label, d in candidates:
        deal_id = d['id']
        for table in RELATED:
            conn.execute(f"DELETE FROM {table} WHERE deal_id=%s", (deal_id,))
        conn.execute("DELETE FROM deals WHERE id=%s", (deal_id,))
    conn.commit()

    remaining = []
    rows = conn.execute("""
        SELECT id,title,side,current_stage,status,listing_address,extra_toggles_json
        FROM deals
        ORDER BY updated_at DESC
    """).fetchall()
    for row in rows:
        d = dict(row)
        blob = ' '.join(str(d.get(k) or '') for k in d).lower()
        for label, groups in TERMS.items():
            if all(any(term in blob for term in group) for group in groups):
                remaining.append((label, d['id'], d['title'], d['status'], d['current_stage'], d.get('listing_address')))
    print('VERIFY_REMAINING_MATCHES', remaining if remaining else 'none')

    active_prep = conn.execute("""
        SELECT id,title,current_stage,status,listing_address
        FROM deals
        WHERE side='listing' AND status='active' AND current_stage IN (0,1)
        ORDER BY updated_at DESC
    """).fetchall()
    print('ACTIVE_PREP_CMA')
    for r in active_prep:
        print(dict(r))
PY
```

Notes:
- Search `title`, `listing_address`, and `extra_toggles_json`, not title only. Some archived/prep cards may have changed titles or slugs.
- Verify the current active stage 0/1 listing cards after deletion so the final answer can state what remains.
- If the query finds no candidates and verification also finds none, report that the properties were already absent rather than implying a deletion happened.
- Do not remove durable memories/facts for a property unless the realtor explicitly asks to remove memory/context too. Pipeline deletion and memory deletion are separate actions.

## Removing Active Deal Files from Admin / Top 25 Views

the realtor's correction: Top 25 is for prospects only. These are hot leads who have not written an offer and have not listed their property with the realtor yet. Active transaction files, accepted offers, condition-removal/conditions-off files, live listings, and closed files should stay only in their matching pipeline columns, not Top 25.

There are two Top 25 dashboard surfaces to patch/verify:

1. The design-shell strip labelled `Top 25 sellers` / `Top 25 buyers` in:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/components/admin-board.tsx
```

In `Top25Deals(...)`, filter to pinned prospects only:

```ts
const prospectPhases = mode === "buyer"
  ? new Set(["offer"])
  : new Set(["pre-cma", "cma"]);

return deals
  .filter((d) => d.primary && prospectPhases.has(d.phase))
  .sort((a, b) => score(b) - score(a))
  .slice(0, 25);
```

This removes listing `intake`, `skyslope`, `go`, `live`, `offer`, `conditions`, and `closed` cards from Top 25 while leaving them in the pipeline.

2. The kanban/pinned strip labelled `TOP 25` in:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx
```

Keep only pinned prospect stages:

```ts
function isTop25ProspectCard(card: AdminCard): boolean {
  if (!card.pinnedTop25) return false;
  if (card.side === "buyer") return card.stage === 0;
  return card.stage === 0 || card.stage === 1;
}

const pinned = cards.filter(isTop25ProspectCard);
```

After changing dashboard code, rebuild and sync into the running Electron app bundle/cache if the realtor is using the desktop app. If source already has the right Top 25 filter but the live dashboard still shows `later-stage first` or live deals in Top 25, the running app is serving a stale built bundle, not stale source. Rebuild and sync before doing any data edits:

```bash
cd <elevate-checkout>/cli/web
npm run build
SRC=<elevate-checkout>/cli/elevate_cli/web_dist
for dist in \
  /Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist \
  ~/Library/Caches/com.elevationrealestate.elevate.ShipIt/update.*/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist
 do
  [ -d "$dist" ] && rsync -a --delete "$SRC/" "$dist/"
done
```

Current dashboard should not require closing after Admin code/data changes: `App.tsx` polls `/?_elevate_bundle_check=...` every 15s while visible and reloads the page if the built asset signature changes; `useAdminDeals()` in `admin/index.tsx` silently refreshes Admin deals every 10s while visible and on window focus. If the realtor reports stale cards, verify those hooks still exist before telling her to close/reopen the dashboard.

Drag/drop stage moves must persist through backend gates. If a card visually moves and then snaps back, check the browser Network/console for `POST /api/admin/deals/:id/move` returning 409 `deal phase gate is blocked`. The UI drag handler should call `api.moveAdminDeal(dealId, toStage, { force: true })`, and `api.moveAdminDeal` in `src/lib/api.ts` should include `force` in the JSON body. A manual card drag is the realtor's approval to move that card into the target stage and trigger that stage's workflow. For Pre-CMA -> CMA specifically, verify the registry has listing stage 1 mapped to a CMA skill, not MLC.

Use browser tools against the live page:

```js
const txt = document.body.innerText;
txt.slice(txt.indexOf('Top 25'), txt.indexOf('PIPELINE VALUE'));
```

Active files may still appear later in the page under their pipeline columns, which is correct.

### Buyer Offer Prep Pipeline Should Exclude Top 25 Prospects

the realtor also clarified that Buyer Admin `Offer Prep` means actual buyer-side contract prep only. Top 25 buyer prospects should not show as cards inside the Offer Prep pipeline column. Keep them in Top 25 as prospects, but exclude pinned prospect cards from the buyer pipeline grouping in `components/admin-board.tsx`:

```ts
const pipelineDeals = useMemo(
  () => activeDeals.filter((d) => !(isBuyer && d.primary && d.phase === "offer")),
  [activeDeals, isBuyer],
);

const dealsByPhase = useMemo(() => {
  const m: Record<string, Deal[]> = {};
  for (const d of pipelineDeals) (m[d.phase] = m[d.phase] || []).push(d);
  return m;
}, [pipelineDeals]);
```

To avoid confusing prospects with CPS prep, have `adminDealToBuyerDeal(...)` in `admin-mappers.ts` display pinned Top 25 buyer cards with `badge: "Prospect"` and `next: "Follow up / qualify buyer"`, while keeping their phase as `offer` so Top 25 can still find them.

Verify on `http://127.0.0.1:9120/admin`: click Buyer admin and confirm `S0 Offer Prep` says `No deals in this stage`, while `Top 25 buyers` still shows prospect cards labelled `PROSPECT`.

## Listing Accepted Offer Section

the realtor expects seller/listing-side accepted offers to appear in the listing Admin dashboard under the `Accepted Offer` section, not only in Listing Live or Closing-style columns. If she names a listing that should be there, update the listing-side dashboard phase mapping and live deal data so the card renders in the accepted-offer lane.

Known correction from the realtor: specific accepted-offer listings she names by shorthand address belong under the listing-side `Accepted Offer` section even if the dashboard is currently showing them elsewhere.

Use the current Postgres-backed Elevate data layer for live data fixes, not old sqlite snippets. Prefer `deals_overview` for discovery and `elevate_db` or scripts from `<elevate-checkout>/cli` using `.venv/bin/python` + `from elevate_cli.data import connect` for curated updates. After dashboard code edits, rebuild from `<elevate-checkout>/cli/web` with `npm run build` and verify in the live UI.

## Closing / Possession Section Removal

the realtor also wants the S9 closing/possession section removed from both Admin pipelines. In the live Admin dashboard, hide stage `9` for both sides rather than renaming it. Keep S10 `Closed` visible, and update next-stage logic so S8 advances directly to S10.

Implementation pattern:

```ts
const ADMIN_HIDDEN_PIPELINE_STAGES = new Set<AdminStageNumber>([9]);

function visibleAdminStages(side: AdminSide): AdminStageNumber[] {
  return ADMIN_STAGE_NUMBERS.filter((stage) => {
    if (ADMIN_HIDDEN_PIPELINE_STAGES.has(stage)) return false;
    if (side === "listing") return stage !== 5;
    return stage >= 4;
  });
}

function adminNextStage(card: AdminCard): AdminStageNumber | null {
  const nextStage = visibleAdminStages(card.side).find((stage) => stage > card.stage);
  return nextStage ?? null;
}
```

Use `visibleAdminStages(card.side)` anywhere the UI renders the full stage list for a specific deal, including the detail panel stage sections. Use `visibleAdminStages(side)` in the New Deal starting-stage dropdown, and add a small effect to reset the selected stage when switching sides if the current stage is hidden.

After the patch, run `npm run build` from the live dashboard web directory.

## Admin Dashboard Closing / GCI KPI Edits

When the realtor asks to remove closing-tracking metric cards like `Avg time to close`, `Closed this month`, or `Stalled deals`, update the live Admin design shell KPI computation rather than the legacy `WorkflowStrip`.

Key files in the live Elevate dashboard:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/compute-admin-kpis.ts
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/components/admin-board.tsx
```

Implementation pattern:
1. In `compute-admin-kpis.ts`, remove the old KPI calculations and returned cards for:
   - `Closing this month`
   - `Avg time to close`
   - `Stalled deals`
2. Add helper functions for reusable financial metrics:

```ts
function dealPrice(d: AdminDeal): number {
  return d.offerPrice || d.listPrice || 0;
}

function dealGci(d: AdminDeal): number {
  const pct = (d.commissionPct ?? 2.5) / 100;
  return dealPrice(d) * pct;
}

function closedDate(d: AdminDeal): string | null | undefined {
  return d.completedAt ?? d.closedAt;
}
```

3. Add `GCI pending` from active deals that are under contract / closing-track. A practical current test is active deals with `completionDate`, `subjectsRemovedAt`, or `offerAcceptedAt`, plus listing stages `>= 7` and buyer stages `>= 4`, excluding stage `>= 10`.
4. Add YTD metrics using `completedAt ?? closedAt` within the current calendar year:
   - `GCI YTD`
   - `Closed YTD units`
   - `Closed YTD volume`
5. Keep useful existing cards like `Pipeline value`, `Active deals`, `In offer / conditions`, and `Key dates this week` unless the realtor explicitly asks to remove them.
6. In `components/admin-board.tsx`, update the loading fallback KPI labels to match the new labels so the UI does not flash old metric names before live data loads.
7. Rebuild from the live dashboard web directory:

```bash
cd <elevate-checkout>/cli/web
npm run build
```

When editing the live Admin dashboard at:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx
```

use `visibleAdminStages(side)` to hide buyer stages `0` through `3`:

```ts
function visibleAdminStages(side: AdminSide): AdminStageNumber[] {
  return ADMIN_STAGE_NUMBERS.filter((stage) => {
    if (side === "listing") return stage !== 5;
    return stage >= 4;
  });
}
```

This removes these visible Buyer Admin columns:
- `Intake`
- `Search Setup`
- `Tours`
- `Follow-Up`

Expected visible Buyer Admin columns after the change:
- S4 `Offer Prep`
- S5 `Accepted`
- S6 `Conditions`
- S7 `Conditions Removed`
- S10 `Closed`

S8 `Closing` and S9 `Possession` are intentionally hidden from the buyer pipeline. Seller S9 `Closing` is also hidden. Stage 7/8 should advance to the next visible stage, ending at S10 `Closed`.

Also update `ADMIN_SIDE_LABELS.buyer.description` if the visible end state changes. Rebuild from `<elevate-checkout>/cli/web` with `npm run build` after changing the live dashboard.

For the current Admin design shell, the visible kanban columns are also defined outside `index.tsx`:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/admin-data.ts
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/admin-mappers.ts
```

When the realtor says she can still see early buyer columns on the right side of the dashboard, patch `ADMIN_BUYER_PIPELINE` in `admin-data.ts`, not only `visibleAdminStages(...)` in `index.tsx`. Remove the buyer `intake`, `search`, `tours`, and `followup` entries so the array starts with `offer`. Also remove buyer `closing`/`possession` entries when the closing/possession section should stay hidden. Update `ADMIN_BUYER_DEALS` fallback seed data so any demo cards formerly in `intake`, `search`, or `tours` use `phase: "offer"` and badge `Offer Prep`.

In `admin-mappers.ts`, normalize live API buyer deals in old stages to visible phases:

```ts
const BUYER_STAGE_TO_PHASE: Record<number, string> = {
  0: "offer",
  1: "offer",
  2: "offer",
  3: "offer",
  4: "offer",
  5: "accepted",
  6: "conditions",
  7: "removed",
  8: "buyer-closed",
  9: "buyer-closed",
  10: "buyer-closed",
};
```

Do the matching badge/next-label cleanup so old hidden-stage deals do not disappear or show old names. For listing mappers, if S9 is hidden, map stage 9 to `closed` / `Closed` rather than `closing`.

## Auditing Buyer-Side Pipeline / Current Automations

Use this fast audit path when the realtor asks what the buyer-side Admin dashboard currently looks like or what automations/skills/workflows are set. Do not infer from memory only, because the dashboard has multiple data sources and the action registry may lag behind the UI.

Important correction learned from the realtor: if she says she can see a **Buyer Admin** side, trust the live dashboard view and audit the live Elevate dashboard path first. The Next dashboard (`<next-dashboard-checkout>/dashboard/...`) may show a shared Admin/Deals pipeline and can make it look like there is no buyer-specific Admin side. The live dashboard has explicit `Listing Admin` / `Buyer Admin` tabs in:

```bash
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx
```

1. Confirm the live Buyer Admin configuration first:

```bash
read_file <elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx
```

Check:
- `ADMIN_SIDE_LABELS` for `Buyer Admin`
- `ADMIN_COLUMNS` buyer labels for each S0-S10 stage
- `ADMIN_PHASE_AUTOMATIONS.buyer` for wired agents/background jobs
- `ADMIN_STAGE_CHECKLISTS.buyer` for checklist items shown on cards
- `visibleAdminStages(side)` if listing and buyer stage visibility differs

Current intended live Buyer Admin pipeline structure:
- S4 Offer Prep — Comps + offer paperwork
- S5 Accepted — Lender + docs
- S6 Conditions — Inspection + property review
- S7 Conditions Removed — Deposit + dates
- S8 Closing — Lawyer + walkthrough
- S9 Possession — Gift + follow-up
- S10 Closed — Archive + nurture

Hidden/skipped buyer columns:
- S0 Intake — Profile + budget
- S1 Search Setup — Criteria + MLS
- S2 Tours — Route + notes
- S3 Follow-Up — Feedback + fit

Common finding as of 2026-05-26: Buyer Admin exists visually with stage labels and checklists, but `ADMIN_PHASE_AUTOMATIONS.buyer` has empty `agents` and `background` arrays for all stages. Say “Buyer Admin exists, but buyer stage automations are not wired yet,” not “there is no buyer admin side.”

2. If needed, confirm the shared/Next dashboard stage definitions as a secondary check:

```bash
read_file <next-dashboard-checkout>/dashboard/src/lib/realestate/command-center.ts
```

Check:
- `RealtorDealStage` union
- `STAGES` order
- `inferStage(...)`
- `nextAction(...)`
- `inferOwner(...)`

3. Query the Admin action registry, especially buyer vs listing rules:

```bash
sqlite3 -header -column "~/.elevate/data/operational.db" "
SELECT id,name,side,from_stage,to_stage,trigger,field_key,condition_json,skill,skill_args_json,enabled,priority,approval_required
FROM admin_action_registry
ORDER BY side, trigger, to_stage, priority DESC;
"

sqlite3 -header -column "~/.elevate/data/operational.db" "
SELECT COALESCE(side,'both') AS side, trigger, COUNT(*) AS rules
FROM admin_action_registry
WHERE enabled=1
GROUP BY COALESCE(side,'both'), trigger
ORDER BY side, trigger;
"
```

3. Check active buyer deal staging in the operational DB:

```bash
sqlite3 -header -column "~/.elevate/data/operational.db" "
SELECT current_stage, COUNT(*) AS count, GROUP_CONCAT(title, '; ') AS deals
FROM deals
WHERE side='buyer' AND status='active'
GROUP BY current_stage
ORDER BY current_stage;
"
```

If this returns no rows, say there are no formal active buyer-side Admin deals staged, not that there are no buyer leads.

4. Check buyer lead/contact activity separately:

```bash
sqlite3 -header -column "~/.elevate/data/operational.db" "
SELECT stage, COUNT(*) AS count
FROM contacts
WHERE type='buyer'
GROUP BY stage
ORDER BY count DESC, stage;
"
```

5. List cron jobs to capture active workflows outside the registry:

```text
cronjob(action='list')
```

Buyer-relevant jobs are usually outreach lanes, hot-leads watcher, follow-ups, Private Searches/PCS, and signed-client-docs Gmail watcher. Report last status and enabled state. Distinguish listing-only jobs like Sunday Seller Updates from buyer workflows unless they share document routing skills.

6. If asked for “skills currently set,” combine:
- skills from `admin_action_registry.skill` where `enabled=1`
- skills attached to relevant cron jobs
- buyer-relevant available skills only if they are not wired as triggers, clearly labelled as available but not registered

Current buyer-side stage trigger expectation: when a buyer card enters S4 `Offer Prep`, `admin_action_registry` should trigger skill `buyer-cps` with `skill_args={"mode":"draft","sendPolicy":"draft_only"}`, `approval_required=true`, and `to_stage=4`. This prepares a draft Contract of Purchase and Sale only. It must not send/sign without a separate the realtor approval.

Check or seed the action from `<elevate-checkout>/cli` using Postgres-backed `elevate_cli.data.connect()`:

```bash
.venv/bin/python - <<'PY'
from elevate_cli.data import connect, ensure_default_admin_actions, list_actions
with connect() as conn:
    ensure_default_admin_actions(conn)
    print([a for a in list_actions(conn, trigger='stage_entry', side='buyer', skill='buyer-cps') if a.get('toStage') == 4])
PY
```

If missing, add/update `_DEFAULT_ADMIN_ACTIONS` in `elevate_cli/data/dispatch.py`:

```py
{
    "name": "Buyer S4 Prepare CPS draft",
    "trigger": "stage_entry",
    "skill": "buyer-cps",
    "skill_args": {"mode": "draft", "sendPolicy": "draft_only"},
    "side": "buyer",
    "to_stage": 4,
    "priority": 90,
    "approval_required": True,
}
```

Add/update the targeted dispatch test in `tests/elevate_cli/test_admin_dispatch_endpoints.py`, then run:

```bash
scripts/run_tests.sh tests/elevate_cli/test_admin_dispatch_endpoints.py::test_seed_default_admin_actions_is_idempotent_and_keeps_cron_watchers_out
```

If the wrapper fails because local `.venv` has no `pip`, run the same targeted test through the working `venv` and report the wrapper issue.

## Adding People to the Admin Top 25 Strip

Use this path when the realtor asks to add people to the dashboard Top 25. The live Admin Top 25 strip is not a separate list table; it renders Admin deal cards whose `extraToggles.pinnedTop25 === true` or `extraToggles.top25 === true` in `<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx`.

Do not ask for confirmation if she gives the names and the matching contacts are clear. Search contacts first, prefer the hotter verified buyer/contact profile if duplicates exist, then create/promote a buyer-side Admin deal and pin it.

Important current data access correction: operational data is in embedded Postgres through `elevate_cli.data.connect()`, not sqlite. First check which runtime exists. In the packaged app setup, `<elevate-checkout>/cli` may not exist; use `/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12` instead, which can import `elevate_cli.data` and writes to the live store. If a source checkout exists and is serving the dashboard, run scripts from that checkout with its `.venv/bin/python` (plain `python3` may miss `psycopg`). Do not use old sqlite snippets for this workflow.

Discovery pattern:

```bash
PY=/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12
# If a source checkout is definitely serving the dashboard, use:
# cd <elevate-checkout>/cli && PY=.venv/bin/python
$PY - <<'PY'
from elevate_cli.data import connect
names = ['matina', 'jennifer', 'leslie']
with connect() as conn:
    for n in names:
        rows = conn.execute(
            """
            SELECT id, display_name, primary_email, primary_phone, type, stage,
                   heat_label, heat_score, source_key, last_activity_at
            FROM contacts
            WHERE lower(display_name) LIKE ?
            ORDER BY updated_at DESC
            LIMIT 20
            """,
            (f'%{n}%',),
        ).fetchall()
        print(n, [dict(r) for r in rows])
PY
```

Pinning pattern:

```bash
PY=/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12
# If a source checkout is definitely serving the dashboard, use:
# cd <elevate-checkout>/cli && PY=.venv/bin/python
$PY - <<'PY'
from elevate_cli.data import connect
from elevate_cli.data.deals import promote_profile_to_admin_deal, set_deal_toggle, list_deals

ACTOR = 'assistant:top25-add'
people = [
    {
        'profile_id': '<hot buyer/contact id>',
        'primary_contact_id': '<same or linked contact id>',
        'display_name': 'Client Name',
        'emails': ['client@example.com'],
        'phones': ['2505551234'],
        'contact_ids': ['<contact ids to preserve linkage>'],
        'source_ids': ['<xposure/lofty/imessage source ids if known>'],
        'heat_score': 90,
        'heat_label': 'hot',
    },
]

with connect() as conn:
    for p in people:
        context = {
            'id': p['profile_id'],
            'displayName': p['display_name'],
            'contactIds': p['contact_ids'],
            'sourceIds': p['source_ids'],
            'sources': ['xposure-pcs', 'lofty-crm'],
            'channels': ['email'],
            'phones': p['phones'],
            'emails': p['emails'],
            'heatScore': p['heat_score'],
            'heatLabel': p['heat_label'],
            'tags': ['top-25'],
        }
        verifiers = [{'kind': 'email', 'value': e} for e in p['emails']] + [
            {'kind': 'phone', 'value': ph} for ph in p['phones']
        ]
        result = promote_profile_to_admin_deal(
            conn,
            profile_id=p['profile_id'],
            side='buyer',
            actor=ACTOR,
            province='BC',
            market='Kamloops',
            current_stage=0,
            display_name=p['display_name'],
            primary_contact_id=p['primary_contact_id'],
            workflow='top25',
            profile_context=context,
            verifiers=verifiers,
            fields={'pinnedTop25': True, 'top25': True, 'top25AddedBy': ACTOR},
            dispatch_initial_stage=False,
        )
        deal = result['deal']
        # Defensive: matched/updated deals may need explicit toggles refreshed.
        set_deal_toggle(conn, deal['id'], field='pinnedTop25', value=True, actor=ACTOR)
        deal = set_deal_toggle(conn, deal['id'], field='top25', value=True, actor=ACTOR)
        print(result['action'], deal['id'], deal['title'])

    pinned = []
    for d in list_deals(conn, status='active', limit=500):
        extra = d.get('extraToggles') or {}
        if extra.get('pinnedTop25') is True or extra.get('top25') is True:
            pinned.append((d['id'], d['title'], d['side'], d['currentStage']))
    print('PINNED', pinned)
PY
```

Pitfalls:
- Some people have duplicate CRM, PCS, and message contacts. Prefer the buyer/hot PCS row for `profile_id` when present, but include linked CRM/message contact ids in `profile_context.contactIds`.
- `promote_profile_to_admin_deal` requires at least one email or phone verifier. If no verifier exists, do not fabricate one; ask the realtor for the missing contact detail.
- Use `dispatch_initial_stage=False` for a Top 25 add unless the realtor asked to start a workflow. This avoids launching buyer stage automations just because the contact was pinned.
- Verify by listing active deals and checking `extraToggles.pinnedTop25` or `extraToggles.top25`; the UI strip filters from those fields. For a live dashboard API check, query `/api/admin/deals` with the dashboard session token and read `items` (not `deals`) from the JSON response, then match the card title or `extraToggles.top25Label`. Example:

```bash
token=$(tr -d '\n' < ~/.elevate/dashboard-session-token)
curl -fsS -H "X-Elevate-Session-Token: $token" http://127.0.0.1:9120/api/admin/deals -o /tmp/admin-deals.json
/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 - /tmp/admin-deals.json <<'PY'
import json, sys
data=json.load(open(sys.argv[1]))
items=data.get('items') or data.get('deals') or []
print([d for d in items if 'Gillian' in (d.get('title') or '')])
PY
```
- If the realtor corrects a matched identity (example: a nickname-only lead like "the buyer from the open house" was matched to the wrong contact record), update the Admin deal immediately: remove the wrong `primary_contact_id` and profile linkage fields from `extra_toggles_json`, keep the card pinned, and relabel it with a safe identifier like `Buyer: <first name> (Open House)`. Do not leave the card tied to the wrong contact.

### Adding “Looking For” Notes to Top 25 Cards

the realtor expects the Top 25 strip to show quick buyer criteria directly on the little card. The reusable storage key is `extraToggles.top25Note`; the UI can also fall back to `lookingFor`, `buyerCriteria`, or `profileCriteriaSummary`.

Live dashboard UI patch path:

```text
<elevate-checkout>/cli/web/src/pages/real-estate-hub/admin/index.tsx
```

Implementation pattern:
1. Add `top25Note?: string` to `AdminCard`.
2. In `adminCardFromDeal(...)`, derive:
   - `adminStringValue(deal.extraToggles?.top25Note)`
   - fallback to `lookingFor`, `buyerCriteria`, `profileCriteriaSummary`
3. In `AdminKanbanCard`, render `card.pinnedTop25 && card.top25Note` as a compact note box, labelled `Looking`, before the stage/next-action area.
4. Run `npm run build` from `<elevate-checkout>/cli/web` so `web_dist` is regenerated.

Populate notes from Xposure PCS where possible:

```bash
cd <elevate-checkout>/cli
.venv/bin/python - <<'PY'
import json
from elevate_cli.data import connect
from elevate_cli.data.deals import set_deal_toggle

ACTOR = 'assistant:top25-notes'
with connect() as conn:
    # Find pinned deals and their linked PCS ids.
    deals = conn.execute(
        "SELECT id,title,extra_toggles_json FROM deals WHERE extra_toggles_json LIKE ? ORDER BY title",
        ('%top25%',),
    ).fetchall()
    for d in deals:
        extra = json.loads(d['extra_toggles_json'] or '{}')
        pcs_ids = [sid.split(':')[-1] for sid in (extra.get('profileSourceIds') or []) if str(sid).startswith('xposure-pcs:')]
        # Read lead_signals.payload_json criteria/search titles for each pcs id, summarize manually.
        # Then write the short card note:
        # set_deal_toggle(conn, d['id'], field='top25Note', value='<short criteria>', actor=ACTOR)
PY
```

Good note style: short, practical, and human-readable, e.g.:
- `Kamloops residential, apartment or detached, 1+ bedroom, up to $600k.`
- `Saved searches: Kamloops, Okanagan, and Shuswap. Need tighter criteria confirmed.`
- `Open house lead. Last name unknown, add criteria after follow-up.`

If saved search criteria are blank, use a follow-up reminder note rather than guessing.

## White Theme / Remove Dark Mode Toggle

Use this path when the realtor asks for the dashboard to be a white theme. For the Next dashboard in `<next-dashboard-checkout>/dashboard`:

1. Force the global theme to light in `dashboard/src/app/layout.tsx`:

```tsx
<ThemeProvider attribute="class" defaultTheme="light" forcedTheme="light" enableSystem={false}>
```

2. Adjust the light tokens in `dashboard/src/app/globals.css` so the base UI is truly white while retaining light separators:
   - `--background: #FFFFFF`
   - `--secondary: #FFFFFF`
   - `--muted: #F2F2F0`
   - `--border: #E8E8E5`
   - `--input: #E8E8E5`
   - `--chart-5: #F2F2F0`
   - `--sidebar-border: #E8E8E5`

3. Remove the dark-mode toggle from `dashboard/src/components/layout/topbar.tsx`:
   - remove `useTheme`
   - remove `IconSun` / `IconMoon`
   - remove the toggle `<Button>` block

4. Remove the Dark Mode setting from `dashboard/src/components/settings/appearance-tab.tsx`:
   - remove `useTheme`
   - remove `Switch`
   - remove `isDark`
   - remove the Dark Mode settings row

Pitfall: after removing the dark setting, avoid leaving a `setMounted(true)` effect just to read localStorage. Targeted lint may flag `react-hooks/set-state-in-effect`. Use a lazy state initializer for `density` instead:

```tsx
const [density, setDensity] = useState<Density>(() => {
  if (typeof window === 'undefined') return 'comfortable';
  const saved = window.localStorage.getItem('ctx-density') as Density | null;
  return saved === 'compact' || saved === 'comfortable' ? saved : 'comfortable';
});
```

Then keep one effect that writes `ctx-density` and `document.documentElement.dataset.density` when density changes.

## Deal-collapse / accepted-offer button pitfall

When adding a button to accepted-offer property score cards, do not stop after creating the client component or API route. Verify that the component is actually rendered by the visible `/deals` page. A prior failure added `DealCollapsedButton`, `operational-deals.ts`, and `/api/realestate/deals/[id]/collapse`, but the visible Admin page still rendered only the inferred `RealtorDeal` pipeline, so the realtor could not see the button. Wire `getOperationalDealsOverview()` into `dashboard/src/app/(dashboard)/deals/page.tsx`, render live Admin/operational deal cards grouped by stage, and place `DealCollapsedButton` inside cards where `isCollapseEligible(deal)` is true. Then run `npx tsc --noEmit`, targeted eslint for changed files, and `npm run build` before reporting it visible.

## Verification

Run TypeScript from `<next-dashboard-checkout>/dashboard`:

```bash
npx tsc --noEmit
```

Run targeted dashboard lint from `<next-dashboard-checkout>/dashboard`:

```bash
npm exec eslint -- \
  src/app/layout.tsx \
  src/components/layout/topbar.tsx \
  src/components/settings/appearance-tab.tsx
```

Or swap in the exact files you changed.

Do not run `npx eslint ...` from the repo root for targeted dashboard lint: it may install/use a mismatched global ESLint version and fail with plugin API errors. Do not rely on full `npm --prefix dashboard run lint` as the only verification signal; the dashboard currently has unrelated pre-existing lint errors in other files. Use targeted lint for files changed plus TypeScript check.

## Related Skill Notes

- `pre-cma-google-form` captures Google Form intake and Lofty contact status before CMA work.
- Listing Stage 1 / CMA-Evaluation must route to the explicit categorized skill `real-estate-admin/cma`, not `real-estate-admin/cma-generator` and not bare `cma`. When reconciling this, update both the live `admin_action_registry` row and the source defaults in `elevate_cli/data/dispatch.py` so reseeding does not recreate the stale route. The enabled Stage 1 row should be `side=listing`, `trigger=stage_entry`, `to_stage=1`, `skill=real-estate-admin/cma`, usually with `skill_args={"mode":"seller_evaluation"}`.
- The dispatch canonicalizer `_ADMIN_WORKER_SKILL_REFS` must map bare `cma` to `real-estate-admin/cma`. Do not let it canonicalize to `real-estate-admin/cma-generator`.
- After registry route fixes, verify with `elevate_db` that no enabled Stage 1 listing `stage_entry` rows use `skill='real-estate-admin/cma-generator'` or `skill='cma'`, and return the exact row(s) changed. Do not run a CMA, send anything, or touch client-facing artifacts unless the realtor explicitly asks.
- `cma` should consume the Pre-CMA handoff first.
- `mlc` should trigger when a CMA/Evaluation card is moved into Listing Intake, but must still require the realtor approval before external signing send.

