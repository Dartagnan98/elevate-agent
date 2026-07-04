---
name: collapse-sale
description: "Prepare, verify, or recover a BC/eXp collapsed-sale package and General Release forms. Use when the realtor says 'collapse the sale', asks to prepare a Collapse of Sale or General Release, needs a staged release package recovered after a worker crash, or wants a signed release sent/checked after an accepted offer falls through."
metadata:
  elevate:
    tags: [real-estate, admin, collapse-sale, general-release, signing, skyslope]
    runtime:
      approval_required: true
      result_writer: admin-result-writer
---

# Collapse Sale

Use when an Admin action run or the realtor asks to collapse a sale, prepare a collapse form, recover a staged General Release package, or send/check a release signing package after an accepted offer is not proceeding.

## Core rule

Do **not** mark a deal collapsed, sold/firm undone, archived, cancelled in SkySlope, submitted to MLS, or send a release for signature unless the required source evidence exists and human approval covers that exact external action.

Internal prep, verification, artifact attachment, and waiting-human closure are safe. External signature sends, SkySlope cancellations/uploads/final submits, MLS status changes, and client-facing messages are approval-gated.

## Source-of-truth order

1. Treat injected Admin run `deal_id` as proven for the card, but still verify any external document against the deal address/parties before filing or sending.
2. Use `deals_overview` first, then `elevate_db` / `admin_deal` / existing deal attachments and events. Do not use SQLite or old local DB files.
3. Verify accepted-offer/CPS evidence, subject-removal state, deposit state, seller/buyer parties, property address, MLS/MHR identity if applicable, and any existing SkySlope transaction/checklist evidence.
4. If a live portal check is needed, use local Browser Use CLI only and stop at approval blockers. Do not use built-in browser tools or hand-rolled browser automation.

## Form branch decision

Choose the form/process from evidence, not habit:

- **Subjects not removed and no deposit paid:** usually use Collapse of Sale / no-deposit collapse package, or General Release with the `No deposit was paid` option only when requested/appropriate for mutual release.
- **Subjects not removed but deposit was paid:** use the with-deposit collapse/release process and collect bank/details/receipt evidence before drafting payment directions.
- **Sale collapsed after conditions removed or after sale was reported:** use General Release and Authorization to Pay Deposit Funds plus any required MLS collapsed-sale report, with all required parties signing.
- **If the realtor explicitly asks for General Release:** prepare that form, but still record the reason and deposit basis.

If the evidence is ambiguous, close `waiting_human` with the exact missing fact, usually deposit-paid status, contract date, subject-removal status, or signer/recipient identity.

## Approved template/source rule

Use the approved BCREA/WEBForms/eXp form already in the system by default. Do not generate a substitute layout. If WEBForms fresh pull is blocked by Imperva/hCaptcha or MFA, use a previously approved clean local WEBForms/TransactionDesk shell only if you can verify the form name/version and remove all stale source data.

For reused shells, run negative checks for all prior-deal names/addresses and record the source-shell path plus portal blocker.

## Preparing or verifying a General Release package

1. Verify the accepted-offer source document with `pdfinfo`, `pdftotext -layout`, SHA-256, and page/signature evidence where relevant.
2. Resolve the contract date deliberately. Use the CPS/header/addendum contract date unless the realtor or the form clearly requires final acceptance. Record final acceptance separately if different.
3. Deposit handling:
   - If the realtor confirms no deposit was paid, select/check only `No deposit was paid`; leave deposit-holder/payment-direction fields blank.
   - If the CPS says deposit is due on subject removal and there is no deposit receipt/subject-removal evidence, treat no-deposit as supported only if the realtor or deal evidence confirms it.
   - Never invent disbursement directions.
4. Populate release parties by side:
   - Seller release section releases buyer and buyer-side designated agent(s)/brokerage.
   - Buyer release section releases seller and seller-side designated agent/brokerage.
   - For the realtor's buyer-side files, include her personal real estate corporation and team/brand name where the form has agent/team fields, with her brokerage as the brokerage of record.
5. Bake/flatten the clean PDF and verify:
   - `file` says PDF, plausible size.
   - `pdfinfo` confirms expected pages and `Form: none` after flattening.
   - `pdftotext -layout` confirms form title, property, seller, buyer, date, deposit option, and no stale source text.
   - SHA-256 recorded.
6. Create a signing plan and, if useful, a separate review-only placement preview clearly labelled `REVIEW ONLY` / `DO NOT SEND`. The clean PDF is the only upload/send candidate.
7. Attach artifacts to the deal with specific kinds: `general_release_staged_clean_pdf`, `general_release_verification`, `general_release_signing_plan`, `general_release_placement_preview`, `general_release_status`, or `workflow_audit`.

## Reconciliation-only pattern for existing staged artifacts

Use this when a scheduled Admin run fires, the `collapse-sale` worker was missing/skipped, a post-restart retest is queued, or artifacts already exist from a prior run.

If the run intent says to draft/send to DigiSign but an existing detailed approval for that exact send is still pending, do **not** create a draft envelope or touch DigiSign/SkySlope. Re-verify the clean PDF, signing plan, verification JSON, placement preview, and approval status; write a fresh audit note; then close the run as `waiting_human` through `admin-result-writer` with `human_prompt.previewPdf` pointing to the clean PDF. Include the pending approval ID and explicitly state that no envelope/send/upload/checklist completion/phase close happened.

1. Verify the current deal row with `deals_overview`; confirm the injected deal ID/title/side/stage match the intended property.
2. Read the existing status, verification, and signing-plan artifacts.
4. Mechanically verify the clean PDF and preview:
   - existence of clean PDF, preview, status note, verification JSON, and signing plan JSON;
   - clean PDF SHA-256 matches the verification/status note;
   - `file` / `pdfinfo` / `pdftotext` confirm PDF validity, page count, flattened form, title, parties, property/deposit option key text.
   - If `pdftotext` fails an exact civic-address phrase check because the form splits address fields across columns/spaces, do not treat that as a failure by itself. Re-check the address components separately (unit/civic number, street number, street name, city, postal-code pieces, MLS if present) and cite the extracted lines in the reconciliation note.
4. Write a compact reconciliation artifact under the same property artifact folder summarizing:
   - missing/available skill or reason for reconciliation;
   - verified artifact paths and hashes;
   - approval ID and superseded approval IDs if any;
   - exact decision needed;
   - every side effect not performed.
5. Close the Admin run through `admin-result-writer` as `waiting_human`, not `succeeded`, unless the release has already been approved, sent, and verified.
6. Attach/re-attach the audit plus the existing verified artifacts. Do not mark checklist items complete from reconciliation alone.
7. If callback `127.0.0.1:9119` refuses connection, retry the identical final payload and stable idempotency key on `127.0.0.1:9120`. Report operational writes only after a 2xx and then verify `admin_action_runs` plus `deal_attachments` rows.

Reusable idempotency key shape:

```text
collapse-sale:<deal_id>:<run_id>:missing-skill-reconciliation
collapse-sale:<deal_id>:<source-message-or-package-id>:general-release-staged
```

## Approval before send

Create or reuse a dashboard approval before any DigiSign/SkySlope send. The approval must name:

- clean PDF path and SHA-256;
- signer name/email and signing order;
- placement plan;
- source accepted-offer evidence;
- deposit and contract-date reasoning;
- guardrail: upload/use the clean PDF only, never the review-only overlay.

If approval is pending, result status is `waiting_human` and `envelope_id=null`. When you close the run `waiting_human` for a send approval, set `human_prompt.previewPdf` to the absolute local path of the **clean** General/Trust Release PDF (the same path as `clean_pdf_path`, never the review-only overlay). This drives the dashboard "Preview PDF ↗" button so the realtor reads the exact document on the card before Approve & re-run.

## Completion/sent verification

Only report `sent` or `done` after live provider verification proves:

- envelope exists with expected title;
- intended clean document was uploaded;
- intended recipient(s) match the approval;
- blocks are placed on the correct pages;
- status is sent or completed as applicable;
- proof JSON/PDF is attached back to the deal.

If the task was only to prepare or reconcile, explicitly state no envelope/send occurred.

### Do not trust provider “completed” labels without visual signature proof

A DigiSign/SkySlope/Gmail label such as “Envelope completed”, “Your document has been completed”, or “All parties have signed” is not enough by itself to call a General Release fully signed. Always inspect the actual PDF pages:

1. Use `pdftotext -layout`, `pdfinfo`, and SHA-256 to verify the PDF identity and parties/property.
2. Render the PDF pages with `pdftoppm -png` and visually confirm each required signer’s initials and signature lines, plus absence of green helper/placement text.
3. Compare every duplicate local copy by SHA-256. If Gmail attachment, forwarded duplicate, Drive copy, and router copy have the same SHA, one visual inspection covers all copies.
4. If the buyer signed but seller initials/signature are blank, report it as buyer-signed only even when DigiSign says completed. Attach a signed-status audit to the deal and do not mark the release fully executed.

49-2401 Ord lesson: the available `General-Release-49-2401-Ord-Rd.pdf` had DigiSign verified envelope `061577a0-9268-4204-8593-5c58ef59a0ce` and Gmail “completed” text, but visual inspection showed buyer initials/signature only (`BF` / Brett Friedel). Seller Curtis Mark Allen’s initials/signature lines were blank. The correct result was “not fully signed; need seller-signed version,” with an Admin deal audit attached.

## Live Gmail / SkySlope execution lessons

Use these when the realtor explicitly asks for the full end-to-end collapse closeout after a release is already completed:

1. **Browser profile guard:** before any Gmail or SkySlope portal action, confirm the active local Browser Use profile/account. `Default` may be another person. For the realtor's admin work use her configured Browser Use profile and verify Gmail shows her own address. If a session was opened with the wrong profile, close it and reopen with the correct profile before clicking anything.
2. **Completed envelope source:** a SkySlope/DigiSign “Envelope completed” Gmail result can be the clean fully signed source even if an older seller/buyer-side thread only had a partially signed release. Verify the completed-envelope PDF mechanically (`file`, `pdfinfo`, `pdftotext`, SHA-256) and against rendered pages before treating it as the send/upload candidate.
3. **Reply target:** if the buyer-side assistant is not present on the collapse thread, reply to the verified original collapse thread/sender rather than guessing a copied assistant address from unrelated accepted-offer threads. In one real collapse, the thread sender was the seller's personal address (e.g. `seller.personal@example.com`); the assistant address appeared on older accepted-offer package traffic but not the collapse thread.
4. **Gmail proof:** after sending the completed release back, read the thread back in Gmail and record the visible proof: sender, timestamp, recipient, body, and attached filename. Do not rely on a button-click result alone.

   **Recovery of an unsent Gmail reply draft:** if the task is to recover a failed General Release reply workflow and a Gmail draft may already exist, verify it with local Browser Use CLI rather than recreating or sending it from memory. Search Gmail for the requester + `General Release` + address, open the exact thread, and read back the visible draft body, recipient/context line, subject, and attached filename/size. Separately verify the attached clean signed PDF mechanically (`file`, `pdfinfo`, `pdftotext -layout`, SHA-256) and visually rendered pages for required seller/buyer initials/signatures and no green helper/placement overlays. Check native pending approvals before acting; if an external-comms approval is pending, leave the draft unsent, attach a recovery audit to the Admin deal, record a compact deal activity note, and report the approval ID as the blocker. In one real recovery, Browser Use showed an unsent Gmail reply draft in the General Release thread with `General Release - 450 Main Street - fully signed.pdf` attached; the external-comms approval remained pending, so no send/SkySlope/MLS/status/checklist action was performed.
5. **SkySlope transaction upload/cancel sequencing:** open SkySlope Manage Transactions with local Browser Use, search/open the exact property, and verify header values before upload or cancellation: property, deal number, transaction ID when visible/known, buyer, seller, sale price, close date, checklist type, subject-removal date, and reviewer comments. If the reviewer/comment says “has this collapsed?”, preserve that as evidence. Upload the signed release to an appropriate checklist/document row only after exact property verification; cancellation/removal of the accepted-offer transaction is a separate irreversible portal action and still needs explicit approval if not already covered by the user’s exact request.
6. **SkySlope upload proof pattern:** row refs/indexes change after every navigation. For the collapse form, click the current `Attach` control on the `Collapse Form` checklist row, verify the upload page says `Upload Documents To / Collapse Form`, then use `browser-use upload <current-file-input-index> <clean PDF>`. After upload, read the checklist row back and record `In Review`/status, document filename, checklist activity id, and document id from the row HTML if available. Do not rely on an older Browser Use element index, and do not use saved-cookie/request helpers unless the realtor explicitly approves the Browser Use fallback.
7. **Cancel modal gotcha:** SkySlope’s Cancel Transaction modal may default `REACTIVATE ORIGINAL LISTING?` to `Yes, reactivate it for me.` Before pressing the final `Cancel Transaction`, explicitly choose the intended radio option and document it. If the listing should not be reactivated from SkySlope, select `No, don't reactivate it.` first. After cancel, read back the header status, e.g. `Canceled/Pend`, as proof.

## Manual recovery when delegated Admin run crashes

If a delegated Admin specialist/background worker fails with an infrastructure/tool exception before doing useful work, for example `'dict' object has no attribute 'lstrip'`, do not keep re-dispatching the same workflow. Take ownership in the parent session and execute the collapse workflow manually with the same safeguards:

1. Run `deals_overview` first to verify the live deal, stage, MLS, and stale accepted-offer fields.
2. Query Admin evidence directly before re-running portals or re-dispatching: use `elevate_db` for `admin_action_runs`, `deal_attachments`, `deal_events`, and the exact `deals` row. Pull exact run IDs, attachment IDs, file paths, source run IDs, event IDs, statuses, and existing recovery artifacts. This is the fastest way to recover a failed status-check when the work may have already completed despite the wrapper crash.
3. If clean recovery/status artifacts already exist, read them, then independently verify their referenced files with `stat`, `shasum -a 256`, `file`, `pdfinfo`, and `pdftotext -layout`. Hash the audit/status artifacts too so the summary is verifiable. Do not rely on memory-only facts.
4. Check pending approvals natively (`agent_bus` approvals) before acting. If an external-comms approval is pending, report it as the blocker and do not send the Gmail draft, touch SkySlope, or advance/checklist-close the deal.
5. Use local Browser Use CLI sessions already open if they exist, but verify each session/account before relying on it:
   - `browser-use sessions`
   - Put global flags before the subcommand: `browser-use --session <name> --json state` and `browser-use --session <name> --json eval 'document.body.innerText'`. Do **not** use `browser-use --session <name> state --json`; that syntax errors and can hide useful page state.
   - `state` may truncate/omit deep checklist text. If a row is not found in `state`, use `eval 'document.body.innerText'`, then search the returned text for row names/statuses.
6. For Gmail proof, a visible thread readback is enough evidence that a reply was sent when it shows the realtor's sent message, timestamp, body, and attachment filename. For an unsent reply recovery, read back the draft body, recipient/context, subject, attachment filename/size, and approval ID, then stop.
7. For SkySlope proof, click/read the Documents tab and the Checklist tab after upload/cancel. Record header status, deal number, transaction email, document visible filename, upload timestamp, and Collapse Form row status. In B11 Dallas the reliable proof was: SkySlope deal `12606110`, status `Canceled/Pend`, Documents tab row `General_Release_-_B11-7155_Dallas_Drive_...` uploaded `2026-06-26 10:15:07 AM`, and Checklist tab row `36. Collapse Form` current status `Completed`. Do not freeze the status from an older audit: the row may move from `In Review` to `Completed`, so report the current Browser Use readback value.
8. Verify the signed release locally with `shasum -a 256`, `pdfinfo`, `pdftotext -layout`, and rendered-page visual checks. For `pdftotext`, write to a temp file before parsing rather than piping directly into a Python heredoc; the direct pipe can produce false negatives or SIGPIPE-style failures. For visual checks, convert pages with `pdftoppm -png` and inspect for signatures/initials and absence of green helper text.
9. When querying `elevate_db` for strings containing literal `%`/LIKE wildcards, prefer `strpos(lower(coalesce(col,'')), 'term') > 0` over `LIKE '%term%'` if the tool/driver interprets `%` as a placeholder and returns `ProgrammingError: query has placeholders but 0 parameters were passed`.
10. If the Admin board already returned the listing to Stage 5, clear stale active accepted-offer fields with `admin_deal(action='set_fields')` using camelCase field names (`offerDate`, `subjectRemovalDate`, `completionDate`, `possessionDate`, `offerPrice`, `depositAmount`, `offerAcceptedAt`, `subjectsRemovedAt`). Do not pass snake_case field names or `current_stage` through `admin_deal.set_fields`.
11. Attach both the signed release and a compact JSON/audit with `admin_deal(action='attach')`; the parameter is `file_path`, not `path`. Verify the attachment with an `elevate_db` readback before reporting completion.
12. Save durable deal facts in `fact_store` if the short memory store is full.

## Recovery for later "send me the General Release" requests from the other side

Use this when a buyer-side/seller-side assistant later asks for a copy of the completed release and a previous automation run failed or returned only an exit-code style status. The reusable goal is a verified operational status, not "script succeeded/failed."

1. Treat the request as an external-comms workflow. Prepare or verify the Gmail reply draft, but do **not** send without a dashboard approval or explicit realtor approval.
2. Use local Browser Use CLI only for Gmail/SkySlope. Verify the active account/profile first; for the realtor's admin work Gmail must show her own configured address.
3. In Gmail, live-read the exact thread and record:
   - subject and URL/thread id;
   - requester name/email;
   - latest request timestamp and wording;
   - draft recipient context, body, attachment filename/size, and whether the Send button is still visible.
   A visible Send button plus the draft text/attachment proves the message is **not sent**.
4. Re-verify the release PDF even if memory says it is completed:
   - `file`, `stat`, `shasum -a 256`, `pdfinfo`, `pdftotext -layout`;
   - render pages with `pdftoppm -png`;
   - visually inspect buyer/seller initials/signatures and absence of green helper/placement overlays;
   - run a basic green-helper-like pixel scan when useful.
5. Open SkySlope live and verify the matching property/transaction, not just a stored audit:
   - property header, status, buyer, seller, deal number, checklist type;
   - Documents tab visible General Release filename and upload timestamp;
   - Checklist row status for `Collapse Form`.
   Note that row status may later read `Completed` instead of the earlier `In Review`; report the current live value.
6. Write a compact verification JSON/audit under the property artifact folder and attach it to the Admin deal as `general_release_reply_verified_status` (or close equivalent). Also record a deal activity note with the approval id and side effects not performed.
7. Return status as `waiting_approval` when the draft is ready but approval is pending. Do not call it `sent` unless Gmail readback shows the realtor's sent message in the thread after clicking send.

## Output contract

Return or write through `admin-result-writer` with this content shape in normal prose/result JSON as appropriate:

```json
{
  "workflow": "collapse-sale",
  "status": "prepared|sent|completed|waiting_human|failed",
  "deal_id": "",
  "address": "",
  "form_branch": "collapse_of_sale|general_release_no_deposit|general_release_with_deposit|blocked",
  "clean_pdf_path": "",
  "verification_path": "",
  "signing_plan_path": "",
  "approval_id": "",
  "envelope_id": "",
  "sent_external": false,
  "artifacts": [],
  "decision_needed": "",
  "side_effects_not_performed": []
}
```

## Example: 49-2401 Ord Road / Brett Friedel lesson

A scheduled `Collapse Sale` run for deal `d212f06730154850af08e533883426f1` found the worker skill missing. The correct recovery was not to send or recreate the release. The safe path was to verify the existing staged clean General Release package under `/Users/admin/Elevation/admin_artifacts/collapse_release/49-2401-ord-brett/`, confirm the clean PDF SHA `665c5a85772effa50e58e1490388e48159b2691effe288713c46e6da799c9315`, read the verification/signing plan/status artifacts, write a missing-skill reconciliation note, attach the verified artifacts, and close the run as `waiting_human` asking whether to send the clean PDF to Brett via DigiSign/SkySlope. No envelope, external send, SkySlope/MLS cancellation, checklist completion, or phase close was performed.

Follow-up reconciliation nuance from the same file: if `admin_action_runs` shows `status='running'` but already has a `result_json`, `result_idempotency_key`, attached artifacts, or a human-prompt decision, do **not** post another callback or mutate around the existing result. Read back the run, current deal attachments, and native approvals first. If the native approval list still shows the send approval as pending, keep the signing/collapse task `waiting_human` even if an older `human_prompt_json` contains a decision-like nested value. Verify the PDF mechanically and visually, report the mismatch clearly, and leave the next action as approval/send reconciliation. This avoids duplicate callbacks and accidental DigiSign/SkySlope sends from inconsistent run state.

Post-approval retest nuance from the same file: if a later retest shows the approval was decisioned/attempted but the latest `human_prompt_json` reports a provider blocker such as SkySlope/DigiSign `401 Unauthorized`, treat that as a login/token-refresh blocker, not permission to send or rewrite the run. Verify there is still no envelope/send proof by checking the artifact folder, release-related deal attachments, and `send_queue` for the signer/address/release terms. If no proof exists, write a fresh readback audit artifact and attach it with `elevate_db.call(function='add_deal_attachment', kwargs={...})`, then report `waiting_human` for interactive SkySlope/DigiSign login refresh. Do not post a second run-result callback when `result_json` and `result_idempotency_key` are already present; the fresh audit attachment is the safe reconciliation artifact.

Later 49-2401 Ord lesson: do not trust a DigiSign/Gmail "Envelope completed" label by itself. The routed completed PDF (`General-Release-49-2401-Ord-Rd.pdf`, envelope `061577a0-9268-4204-8593-5c58ef59a0ce`) was mechanically valid and Gmail said all parties signed, but visual review showed buyer initials/signature only and seller Curtis Mark Allen's initials/signature lines were blank. Always render/visually inspect General Release pages before calling a release fully signed. If the realtor asks to proceed with a partially signed release because brokerage is asking where the file is, upload the clean partial PDF to the SkySlope `COLLAPSE FORM` checklist row and document the limitation clearly. For 49-2401 Ord, local Browser Use uploaded the partial PDF to SkySlope Tx `22356317` / deal `12606197`, row `50. COLLAPSE FORM`; row status became `In Review` with filename `General-Release-49-2401-Ord-Rd.pdf` and doc id `904277314`. Also reply in the existing Gmail/DigiSign thread to the seller agent requesting the seller-signed copy, then write and attach a compact audit note proving both the email follow-up and the SkySlope partial upload. Use Browser Use CLI for Gmail/SkySlope and do not expose credentials in logs or final output.

Same-file completion lesson: when the listing agent later emails the seller-signed copy, search Gmail via Browser Use for the agent/signed-release thread, open the message, download the attached PDF, and preserve it under the property artifact folder before uploading. Mechanically verify `pdfinfo`, `pdftotext -layout`, SHA-256, parties/property/deposit option, and render both pages for visual signature/helper-text review. For 49-2401 Ord, Cindy's attachment `Signed-General-Release-49-2401-Ord-Rd.pdf` was copied to `.../cindy-signed-2026-06-26/Signed-General-Release-49-2401-Ord-Rd-seller-signed-from-Cindy.pdf`, SHA `66783734ebb95f4371af4a1dac117f8d53ba00de02f91dcd7cc9ceaea14220a7`; visual review confirmed seller initials/signature and buyer initials/signature with no green helper text. Re-open SkySlope with Browser Use, attach the seller-signed PDF to the same `COLLAPSE FORM` row, then verify in the `DOCUMENTS` tab because the checklist row may only show a paperclip without filename after upload. Record the new document filename, upload time, document id, and document key. For 49-2401 Ord, the seller-signed upload appeared in Documents as `Signed-General-Release-49-2401-Ord-Rd-seller-signed-from-Cindy.pdf`, uploaded `2026-06-26 3:06:18 PM`, doc id `904366663`, key `b73ae9948cbc4d9d968b126ff875ea20`; row 50 returned to `In Review`. Attach both the fully signed PDF and an upload audit to the Admin deal.

Post-collapse dashboard/calendar cleanup lesson: when the realtor then approves archive cleanup, remove the buyer card from active Subject Removal / accepted-offer lanes and clear the Admin card's top-level date/offer fields (`offerDate`, `subjectRemovalDate`, `completionDate`, `possessionDate`, `offerPrice`, `depositAmount`, `offerAcceptedAt`, `subjectsRemovedAt`). To reset a collapsed BUYER card, call the built-in collapse endpoint `POST http://127.0.0.1:9120/api/admin/deals/{deal_id}/collapse` with body `{"side":"buyer"}`. This is the ONLY correct path: it strips every property/offer field, nulls the listing address, renames the card to `Buyer: <name>`, and moves the buyer to the reset stage (stage 0, top of the buyer pipeline / "top 25") so they stay ACTIVE and keep shopping. Do NOT force-move the card to stage 4 with `admin_deal(action='move', to_stage=4, force=true)` — that parks a dead property in the Subjects-Off lane (the exact bug this replaces). Do NOT attempt a raw `status=archived` write for a buyer collapse; buyers are reactivated, not archived. The endpoint requires an accepted-offer buyer stage (1-3); if it returns a stage-guard error the card is not in a collapsible state, so investigate rather than force. Remove associated Google Calendar events only through local Browser Use CLI. Search Google Calendar for the exact property/client (`49-2401 Ord Rd`, `Friedel`) and delete the file-specific deadline events (subject removal, park consent, deposit due, adjustment, completion, possession). Verify with fresh Calendar searches that the exact property/client returns `No events found`, then write/attach a cleanup audit to the Admin deal.