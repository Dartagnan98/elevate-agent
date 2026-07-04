---
name: sales-report-and-buyer-title-processing
description: Process accepted-offer compliance rows for Signed Title by Buyer and Sales Report Form. Use when the realtor asks to find/process a buyer-signed title, check whether the buyer agent's side emailed it, or make an AOIR/eXp Sales Report Form for an accepted-offer Admin deal.
---

# Sales Report + Buyer-Signed Title Processing

Use this for accepted-offer / subject-removal compliance cleanup when the remaining SkySlope rows include `Signed Title by Buyer` and/or `Sales Report Form`.

## Hard gates

1. Use the active Admin deal only. Confirm the deal ID, active SkySlope transaction ID, listing ID, deal number, checklist type, and current stage before touching files.
2. Run/read a filing verification gate before claiming anything is complete. Do not say `done`, `uploaded`, `submitted`, `accepted`, `firm`, or `sold` unless the relevant verification object has `status: passed` for that exact action.
3. Online work must use the account's configured browser-automation path. Do not use ad hoc curl/HTTP for Gmail, SkySlope, Formstack, MLS, or other online portals.
4. Never upload/process a title document unless it visibly matches the property and is buyer-signed/initialled by the current buyer(s). A plain LTSA title search is not the same as `Signed Title by Buyer`.
5. Do not submit the Sales Report through AIR/Formstack or upload to SkySlope unless explicitly asked/approved and the form data is source-verified.

## Workflow

1. Load deal context.
   - Use `deals_overview` or `admin_deal(action='show', deal_id=...)`.
   - Use `elevate_db` for deal fields and current attachments.
   - Record active identifiers in the artifact manifest: Admin deal ID, SkySlope transaction/listing/deal numbers, stage, buyers, sellers, MLS, dates, list price, current sale price, deposit.

2. Search for an already-filed buyer-signed title.
   - Query `deal_attachments` for `title`, `signed`, `buyer`, `sales`, and `report` with regex `~` instead of SQL `LIKE '%...%'`, because `%` can be misread as DB-driver placeholders.
   - Confirm whether the only title on file is an LTSA title search. If so, do not count it as buyer-signed title.

3. Search Gmail/Mail evidence.
   - Prefer Browser Use CLI for Gmail live verification. Example:
     `browser-use --session <session> --profile <realtor-profile-name> open 'https://mail.google.com/mail/u/0/'`
     then enter searches such as:
     `newer_than:30d (450 OR "450 Main" OR "Main Street") (title OR "signed title" OR "Title by Buyer") has:attachment`
   - Save `browser-use state` output to the deal artifact folder as proof.
   - If local Apple Mail cache is useful for narrowing, search `.emlx` and attachment folders, but treat it as preliminary until the exact email/attachment is verified. Inspect message From/To/CC/Subject/Date and attachment names. Avoid unrelated property title files.
   - Do not assume every `pdf.pdf` or `Title` hit is the current buyer title, regardless of who sent it. A file literally named `pdf.pdf` from a buyer-agent's assistant can turn out to be a SkySlope subject-removal envelope rather than the signed title, while the actual most-recent email from that same sender contains only a `Condition Waiver.pdf`. Open and verify every candidate attachment's content before treating it as the buyer-signed title.

4. Verify a candidate buyer-signed title if found.
   - Use `pdfinfo`, `pdftotext`, rendered images, or visual review.
   - Verify exact property address/PID/MLS, current buyer names, current seller names where present, signature/initial evidence, and absence of green placement/helper text.
   - Copy the verified source PDF into `/Users/admin/Elevation/admin_artifacts/<property_slug>/...` with a stable filename and SHA256.
   - Attach internally only after the gate passes; upload to SkySlope only if the user asked and upload verification passes.

5. Build the Sales Report Form.
   - Resolve sale price from source documents before filling. If original CPS and later amendment conflict, use the completed signed amendment as the current sale price and cite both sources.
   - Source fields from accepted CPS, completed amendments, subject-removal reconciliation, and the Admin deal record:
     - listing office MLS ID / office if known
     - MLS number
     - list date and list price
     - property address, city/postal, PID
     - sellers and buyers
     - listing brokerage and listing salesperson
     - selling price
     - buyer postal code
     - purchase contract date
     - acceptance date
     - subject-removal / firm date
     - completion / change-of-title date
     - buyer agent and buyer brokerage
     - deposit where the chosen form/template asks for it
   - If a field such as occupied-on-closing or lease terms is not source-verified, leave it blank and state that limitation in the manifest.

6. PDF creation pattern for the AOIR PDF template.
   - Template candidate used successfully on one box: a blank Sales Report Form PDF supplied by the realtor's transaction-coordination vendor, typically filed under `/Users/admin/shared-team-brain/files/<TC vendor>/`. Search the shared-team-brain tree for `Sales Report Form` if the exact path is not already known.
   - The file may contain old sample text already flattened into the PDF. Use PyMuPDF (`fitz`) in the Elevate runtime to white-out only old sample-value rectangles, then insert the current values. Do not erase labels/rules.
   - Render the completed page to PNG for visual QA.
   - Save under the deal artifact folder, e.g.:
     `/Users/admin/Elevation/admin_artifacts/<property_slug>/title_sales_report_<date>/<property>-Sales-Report-Form-<date>.pdf`

7. Write a processing manifest.
   Include:
   - workflow name
   - deal/property identifiers
   - source files and source snippets/claims
   - generated Sales Report PDF path, render proof path, SHA256
   - buyer-title search proof path and result
   - verification object with `status: passed` only for the scoped internal action that actually passed
   - limitations and remaining blockers
   - explicit booleans for `external_board_formstack_submission_performed` and `skyslope_upload_performed_by_this_step`

8. Attach artifacts to Elevate.
   - Attach the Sales Report draft as `sales_report_form_draft`.
   - Attach the render proof as `sales_report_form_render_proof`.
   - Attach the manifest as `title_and_sales_report_processing_manifest`.
   - Read back `deal_attachments` to verify the attachment rows exist.
   - Do not mark checklist/stage complete if title, deposit, lawyer info, FINTRAC, remuneration disclosure, or deal-sheet gates still block advancement.

## Reporting format

Give the realtor a concise status:

- Buyer-signed title: found/processed, or not found and still a blocker.
- Sales Report Form: created path + status (`draft/internal only`, `submitted`, or `uploaded`, depending on actual verified action).
- Any fields left blank or source conflicts resolved.
- Remaining blockers from `admin_deal` gate and SkySlope rows.

If the buyer-signed title is missing, offer or draft a short request to the buyer agent/assistant, but do not send without approval unless the user explicitly says to send.

## Pitfalls learned

- `Signed Title by Buyer` means the buyer-side signed title acknowledgment/document, not the LTSA title search PDF already on file.
- Gmail search results can surface unrelated `Title` documents from other deals; verify property/address before using.
- Gmail result `pdf.pdf` can be a SkySlope/DigiSign envelope PDF and not a title.
- Old Sales Report PDF templates may include flattened sample values. If not removed/covered, those old values will remain on the output and corrupt the form.
- Sale price may change after original CPS. Use the latest completed signed amendment if it supersedes the CPS price.
- Browser Use CLI profile matters. Use `browser-use profile list` and select the realtor's own profile for the realtor's Gmail, not Chrome Default if that belongs to another account.
