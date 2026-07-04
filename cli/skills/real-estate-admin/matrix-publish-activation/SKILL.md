---
name: matrix-publish-activation
description: "Run a human-approved MLS/Matrix listing publish attempt and record the exact outcome. Use when a signed-off listing build and photos are ready and the realtor says to publish, activate, or go live on MLS."
metadata:
  elevate:
    tags: [real-estate, mls, matrix, xposure, publish, activation]
    runtime:
      approval_required: true
---

# Matrix / Xposure Publish Activation

Use only after explicit human approval to activate/publish a listing that already exists as an AOIR Xposure/Matrix incomplete listing.

## Preconditions

1. Human approval for MLS activation/public listing is present in the current task context.
2. Existing Matrix listing number and deal ID are known.
3. Approved listing-build package and uploaded-photo evidence are available.
4. Do not invent missing legal, measurements, tax, room, or pick-list fields. If the portal blocks submit, return exact portal validation text.

## Flow

1. Verify package and prior upload artifacts locally.
2. Verify Matrix login/session with `node scripts/check-matrix-login-<property>.js` or equivalent. If login/MFA blocks, return `waiting_human`.
3. Open `https://matrix.interiorbc.ca/Matrix/Input` and confirm the target row still exists and current status.
4. Click the target row's exact `Edit` button (select the `tr` containing the MLS number, then `button[aria-label="Edit"]`). Avoid clicking global `Add` by mistake.
5. In the row action menu click `Residential (No Manufactured Homes)` (or the listing's actual property type form).
6. Capture a before-submit screenshot and DOM/text dump.
7. Compare portal header/address to approved package. If address/street type differs, treat as a high-risk blocker unless safely correctable from verified source and saveable.
8. Click the visible `Submit` control only after approval. Matrix may keep the listing incomplete and show validation errors instead of publishing.
9. Capture after-submit screenshot and DOM/text dump.
10. Determine result:
   - Live/success: capture portal confirmation and verify the Input list row status changed to Active/Live.
   - Blocked: capture exact text such as `There are validation errors. Please click on the bell to view.` and the full `is required` error list.
11. Write a JSON result artifact under the MLS run folder with status, live_status, MLS number, blockers, risks, and artifact paths.
12. Update Elevate's embedded Postgres records through `elevate_db` / approved Admin write helpers only. Do not look for sqlite files or `/Users/admin/.elevate/data/operational.db`.
   - If live: set/verify `deals.mls_number`, `listing_published_at`, `updated_at`, add a `deal_events.run_result`, and mark the relevant Admin run/task succeeded/completed through the supported tool path.
   - If blocked: set/retain `deals.mls_number` if known, leave `listing_published_at` NULL, add a `deal_events.run_result`, and mark the relevant run/task `waiting_human` with the result path/error message.
   - SQL gotcha: when querying through `elevate_db`, escape literal percent signs in `LIKE` / `ILIKE` patterns as `%%` inside the SQL string, e.g. `ilike '%%450 Main%%'`, otherwise psycopg treats `%4` as a placeholder and errors.
13. Re-open/list Matrix Input and verify final row status before reporting.

## Pitfalls / Lessons

- Matrix's row action menu appears only after clicking the target row's `Edit`; hidden/global Add controls can lead to the Add Listing form instead of editing the existing listing.
- Playwright `hasText` may not match `input` values for `Submit`; use page evaluation against `innerText || value` if needed.
- Portal validation errors may exist before clicking Submit; still capture after-submit state because Matrix adds `There are validation errors. Please click on the bell to view.`
- Matrix can display a bad street type in the header/body (e.g. `Main Gateway`) even when the approved package/source says a different street type (e.g. `Main Avenue`); do not publish with an unverified address mismatch.
- Uploaded photos do not mean the listing is publishable. Matrix may still require map pin, title tier, taxes, area/subarea, floor area, room measurements, strata/parking/restriction, utility, showing, and opt-out fields.
- If a scheduled Admin `next_task: matrix-publish-activation` fires while the deal gate still shows missing photo approval, `matrix_photos_uploaded`, `matrix_listing_finished_with_photos`, required AI/property fields, or the Matrix handoff says the listing is still saved as Incomplete, do not open Matrix or click Submit. Treat this as a safe precondition blocker: verify existing handoff/artifacts, close the run through `admin-result-writer` as `waiting_human`, attach the Matrix handoff/save screenshot/photo manifest/contact sheet, and ask for the exact missing fields plus explicit MLS publish approval.
- Bathroom-count compliance recovery: do not trust marketing copy or generated handoff text for bath totals when a detached shop/outbuilding has its own bathroom. Verify against portal-backed prior MLS/Xposure print previews, old MLS PDFs, room grids, signed docs/floor plans, and current Matrix/AOIR rules. If prior MLS shows 3 residential baths and remarks mention a separate shop bathroom, treat `4 bath` / `5 bed, 4 bath` as not publish-ready until the realtor or AOIR/Matrix confirms the detached shop bathroom may be counted in Bathrooms Total; otherwise publish the residential count and mention the shop bathroom only in remarks if allowed.
- Failed compliance-task recovery pattern: if a prior MLS compliance task failed/truncated, recover context before touching Matrix. Search recent sessions with exact address + distinctive fragments (photo/approval keywords, MLS/listing IDs), inspect large persisted session-search outputs with targeted parsing, query `deal_events` / `agent_handoffs` by deal id and address, and re-read canonical property files (`matrix/fill-input.json`, `matrix/handoffs/*.json`, `listing-build/*result.json`, launch package). Distinguish three facts in the report: (1) local files were corrected, (2) live Matrix/Xposure draft status is still unproven unless portal-verified, and (3) human blockers like photo/hero approval remain blockers before publication.
- Truncated human-prompt recovery: prior prompts often contain the missing compliance question in `deal_events.payload_json` or session-search dumps. A truncated fragment can be recovered from the original photo-approval prompt, e.g. "whether the photo set is approved for MLS/listing use," with required fields `photo approval` and `hero photo selection`. Return the exact recovered wording and proof path/source rather than guessing from the fragment.

## Output Contract

```json
{
  "workflow": "matrix-publish-activation",
  "status": "live|blocked_validation|waiting_human|failed",
  "deal_id": "",
  "provider": "AOIR Xposure MLS / Matrix",
  "matrix_listing_id": "",
  "live_status": "live|not_live|unknown",
  "portal_confirmation": null,
  "exact_portal_message": "",
  "blocking_validation_errors": [],
  "artifacts": [],
  "db_update_status": "updated|not_updated|failed"
}
```
