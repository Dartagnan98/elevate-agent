---
name: admin-listing-import
description: "Import a signed listing package into Admin as a deal with contacts, artifacts, and stage. Use when the realtor says a listing's paperwork is signed and wants it imported from a local MLC/marketing run tree, or says listings are missing from the dashboard and only local signed docs/CPS files exist to import from."
metadata:
  elevate:
    tags: [real-estate, admin, sqlite, listing-import]
---

# Admin Listing Import

Use this when a realtor says a listing's paperwork is signed and wants the listing data imported into Admin, especially when the source artifacts already exist under a local MLC-run and marketing-run tree such as `<local-tools-root>/data/mlc/runs/...` and `<local-tools-root>/data/marketing/runs/...`.

## Goal

Create or update a listing deal in `~/.elevate/data/operational.db` from local signed MLC and marketing-prep artifacts, without marking downstream phases complete before evidence exists.

## Prerequisites

1. Locate source artifacts:
   - MLC run: `<local-tools-root>/data/mlc/runs/<run-id>/deal.json`
   - Signed docs: `/signed/*.pdf`
   - Loopback/signing status: `loopback-status.json`
   - Marketing run: `<local-tools-root>/data/marketing/runs/<run-id>/inputs.json`
2. Verify the Admin DB exists:
   - `~/.elevate/data/operational.db`
3. Inspect schema before writing if unsure:
   - `sqlite3 ~/.elevate/data/operational.db '.schema deals'`
   - `sqlite3 ~/.elevate/data/operational.db '.schema deal_attachments'`
   - `sqlite3 ~/.elevate/data/operational.db '.schema admin_action_runs'`

## Recommended workflow

1. Search for existing deal first; do not duplicate if it already exists:
   - Match by `source_key = <local-tools>:mlc:<mlc-run-id>`
   - Or by normalized address in `title` / `listing_address`.
2. Upsert seller contacts:
   - Use `lofty:lead:<id>` when `lofty_lead_id` exists.
   - Otherwise use `<local-tools>:mlc:<run-id>:seller:<n>`.
   - Mark `type='listing'`, `stage='active'`, and `listing_active=1`.
3. Create/update the `deals` row:
   - `side='listing'`, `status='active'`.
   - Set `province`, `board`, and `market` from the realtor's onboarding configuration for this board/MLS.
   - Set key values from MLC and marketing inputs: listing address, list price, go-live/listing date, signed date, expiry date, legal description, PID/roll in extra JSON, beds/baths in extra JSON if schema has no columns.
4. Stage selection:
   - If paperwork is signed and photos are pending, set `current_stage=3` = `Photos Ready`.
   - Do not mark `workflow_photos_in_drive` or `workflow_stage_3_complete` true until photo evidence exists.
   - If photos are already in Drive and approved, proceed to stage 4 / listing build instead.
5. Attach artifacts in `deal_attachments`:
   - `signed_envelope` for signed MLC.
   - `signed_document` for signed PNC and DORT.
   - `title_search`, `property_report`, `property_data` when present.
   - `marketing_inputs`, `marketing_posts`, and `landing_page` for marketing prep artifacts.
   - Use `source_run_id` and avoid duplicates by `(deal_id, source_run_id, kind, file_path)`.
6. Link `deal_contacts` as role `seller` and insert `deal_events` audit rows for created/updated, attachments, and linked contacts.
7. Queue or normalize the relevant admin action run:
   - Look up the current stage-3 photo-cleanup registry row id for this box (`admin_action_registry` where `to_stage=3` and `skill` matches the photo-prep skill) rather than assuming a fixed id.
   - If photos are pending, set/create the run as `waiting_external`, with payload saying it is waiting for listing photos / Drive `FULL_RES` folder.
8. Ensure post-signed-document automation exists and backfill current files when needed:
   - When `workflow_stage_2_complete` flips true (meaning listing docs are signed and saved to Drive), Admin should automatically trigger two prep-only portal tasks without human approval:
     1. `skyslope-sync` with mode `create_listing_transaction` / provider `skyslope` / `requiresSignedDocsInDrive=true` to create/open the SkySlope listing file/transaction. SkySlope is editable later, so this prep step does not need human approval after signed docs are saved.
     2. `matrix-incomplete-listing` with mode `create_incomplete_listing` / provider the realtor's MLS/Matrix board / `saveAs=incomplete` / `publishPolicy=never_publish` to create the MLS draft and save it incomplete only. Matrix publish/activation still requires human approval.
   - Registry rows for this pattern are typically named `auto_s2_skyslope_create_listing_after_signed_drive` and `auto_s2_matrix_incomplete_after_signed_drive`.
   - Both should have `approval_required=0` for prep-only runs. If a deal was imported before these triggers existed, create/update `admin_action_runs` with `status='queued'`, no `human_prompt_json`, and payload noting `approvalPolicy='automatic_after_signed_docs_saved'`.
9. When a Drive photo folder arrives after import:
   - Locate or create a manifest for the Drive folder, with `source_folder`, `image_count`, `folder_count`, and item paths.
   - Attach the manifest to Admin as `deal_attachments.kind='listing_photos'` and update deal extras: `workflow_photos_in_drive=true`, `photosDriveFolderId`, `photosDriveFolderUrl`, `photosImageCount`, `photosManifestPath`, and `photosReceivedAt`.
   - Queue/advance S3 photo cleanup. After listing-ready photos and Matrix upload are verified, mark S3 succeeded, set `workflow_stage_3_complete=true`, move the deal to S4 / MLS Entry, and queue S4 `property-lookup` + `listing-build`.
   - Attach downstream artifacts: `matrix_photo_upload`, `listing_build_package`, `feature_sheet_inputs`, `marketing_go_summary`, `marketing_launch_checklist`, and `marketing_handoff`.
   - Keep listing-build/marketing-go outputs as draft/prep only until human approval for MLS publish, landing deploy, social scheduling/posting, email send, or paid campaign activation.

## Ad-hoc dashboard listing imports from local docs

Use this when the realtor says listings are missing from the Admin dashboard but does not provide a full local MLC run. Do not create vague cards only from shorthand names. Import the card, then immediately enrich it enough that Accepted Offer / Subject Removal can unambiguously identify the deal later.

1. Search existing Admin deals first to avoid duplicates:
   - `sqlite3 ~/.elevate/data/operational.db "SELECT id,title,listing_address,current_stage,status FROM deals WHERE side='listing' ORDER BY current_stage,title;"`
   - Match by normalized address, unit number, business name, and aliases.
2. Search known local file roots for source documents:
   - the Elevate cache documents folder
   - the realtor's tools-data listings folder for this property slug
   - any shared team-drive client-files root, under the realtor's own listing-files subfolder
   - the Downloads folder only when recent signed/CPS files are likely there
3. Extract identifiers from PDFs with PyMuPDF when possible:
   - `python3 - <<'PY' ... import fitz ... page.get_text() ... PY`
   - Pull: full civic address with unit, postal code, PID, legal description, seller names, listing dates, expiry date, offer price/deposit if a CPS is already on file.
4. Upsert the deal in `deals` with precise identity fields:
   - `title` should include full property/business label and seller names when known.
   - `listing_address` must include unit number and postal code when available.
   - `property_subtype`, `transaction_type`, `listing_type`, and `corporate` should distinguish residential, strata, manufactured/mobile, and business/commercial listings.
   - `legal_description`, `listing_date`, `expiration_date`, `offer_price`, and `deposit_amount` should be filled from source docs when found.
   - `source_key` should be a stable normalized listing key, not just `manual-dashboard-import`.
   - `source_label` should name the docs/folder used.
5. Store identifiers and aliases in `extra_toggles_json` as valid JSON, for example:
   - `property_aliases`: all shorthand names the realtor may use for the property.
   - `pid`
   - `seller_names`
   - `business_name` / `aka` for business listings.
   - `source_documents`: absolute paths to source PDFs/images.
   - `dashboard_identifier`: note any ambiguity, such as unit number conflicts.
   - `verification_status`: short source-backed status.
6. Attach all source docs in `deal_attachments` as `kind='source_document'`; use deterministic ids like `<deal-id>-source-<n>` for idempotent updates.
7. Add an audit `deal_events` row as `kind='run_result'` because the schema only allows: `created`, `stage_transition`, `toggle_change`, `run_result`, `attachment_added`, `contact_linked`. Put `result_type='property_identifiers_verified'` in `payload_json`; do not invent new event kinds or SQLite will fail the CHECK constraint.
8. Verify after updating:
   - `SELECT id,title,listing_address,property_subtype,legal_description,offer_price,deposit_amount,source_key FROM deals WHERE id IN (...);`
   - `SELECT deal_id,COUNT(*) FROM deal_attachments WHERE deal_id IN (...) GROUP BY deal_id;`
   - Confirm imported listings remain in the intended dashboard stage, usually Listing Live stage 6 for already activated listings.

When multiple properties share a similar shorthand (for example the same street name with different unit numbers, or the same building housing distinct residential and business/commercial listings), keep every alias in `property_aliases` and verify PID/legal description before treating two shorthand mentions as the same deal.

## Python/API pitfalls learned

- The Elevate CLI data helpers are preferable when importable (`elevate_cli.data.connection`, `deals`, `contacts`), but the local Python may be too old or missing dependencies.
- Some macOS system Python builds fail importing the CLI because code uses `Path | None` syntax; a newer local interpreter may get past that but still fail on a missing dependency such as `yaml`.
- When helper imports fail, use direct SQLite writes, but preserve the same contracts:
  - enable `PRAGMA foreign_keys=ON` and `PRAGMA busy_timeout=5000`;
  - use UUID hex ids;
  - insert `deal_events` audit rows;
  - keep `extra_toggles_json` valid JSON;
  - do not bypass evidence gates by setting completion toggles true.

## Verification

After import, run a compact verification query:

```bash
sqlite3 ~/.elevate/data/operational.db "
select id,title,listing_address,current_stage,status,list_price,agreement_signed_date,listing_date,source_key
from deals
where source_key='<local-tools>:mlc:<mlc-run-id>';
select kind,count(*) from deal_attachments where deal_id='<deal-id>' group by kind;
select status,payload_json from admin_action_runs where deal_id='<deal-id>' order by created_at desc limit 5;
"
```

Expected for signed paperwork + photos pending:

- Deal exists once.
- `current_stage=3` / Photos Ready.
- Signed documents and marketing-prep artifacts are attached.
