---
name: mlc
description: Listing intake and Multiple Listing Contract workflow. Collects listing details, prepares required listing documents, and asks for human approval before signing/send.
metadata:
  elevate:
    tags: [real-estate, listing-intake, mlc, documents]
    runtime:
      approval_required: true
---

## Listing stage trigger contract — September 9, 2026

For BC listing stage decisions, read the [shared stage trigger contract](../admin-result-writer/references/listing-stage-triggers.md). It supersedes older manual-only and workflow-completion advancement rules for the named triggers. Entry into a stage starts its workflow; completing work alone does not advance the card. Preserve buyer-stage behavior. Use the runtime invocation section for the supported trigger tool/CLI; distinguish queued workflows from completed work.


# MLC

Use for listing intake and MLC document preparation.

Collect required listing details, signer authority, price, commission, planned go-live timing, property identity, brokerage/regional requirements, and configured forms-provider details. Prepare documents through the configured forms/signing providers.

Before sending for signature, ask for human approval that the forms, fields, and signature placements are correct. After signed docs are verified, write artifacts/checklist updates with `admin-result-writer`.

## Intake and document modes

Respect the dispatched `skillArgs.mode`:

- `intake`: normalize the seller/property facts already available and prepare the listing file. A seller name, one reachable contact channel, and the property address are enough to start. Save useful progress before asking for anything. Record unresolved contract terms for document preparation; their absence does not prevent intake work or property/title research.
- `documents`: use the saved intake to prepare MLC drafts. Reuse existing drafts and ask only for information required by the selected forms that is still missing. If another MLC run for this deal already owns the same missing-information prompt, reuse that handoff rather than creating a second card. Once intake answers arrive, continue document preparation or queue it once if no documents run is active; do not assume a previously skipped documents run will restart itself.

Stage-advance requirements are not prerequisites for starting either mode. Keep the card in its current stage until the shared stage trigger contract is satisfied.

## Resolve facts before asking

Read the injected `deal`, `checklist`, `primaryContact`, `conditions`, and `adminSetup`. Refresh `/api/deals/<deal_id>/context` when needed. Saved facts may be in `deal.extraToggles` / `checklist`: `sellerLegalNames`, `onboardingSellers`, `workflow_client_1_*`, `workflow_client_2_*`, `listingCommission`, `listingDate`, and `expiryDate`. Use the saved `deal.listPrice`; do not replace it with a newly inferred CMA price. A stored name is not proof of ownership or authority: reconcile that separately with title/authority evidence.

On a resumed run, apply `currentRun.humanPrompt.providedAnswers` (or the run's stored `human_prompt_json.providedAnswers`) before checking for missing facts. Write supported answers to the deal/Listing Kit fields and read them back. Preserve detailed commission wording in `listingCommission`; do not squeeze tiered or cooperating-brokerage terms into one percentage. A contract effective date and a planned MLS go-live date are different facts; keep them separate and do not overwrite one with the other.

Resolve province, package, forms provider, and signing provider from Admin setup and the selected Listing Kit forms. Check `/api/admin/kit-preferences` for saved preparation preferences. Preferences may suggest a draft value but are not evidence of seller agreement. Ask about provider setup only when absent or an actual connection/login failure prevents the next operation.

## Listing preparation defaults

- Default to the seller signing personally. Do not include a signing-authority or “Who will sign?” question in routine intake. Preserve any saved exception; if the realtor identifies a power of attorney, corporate/estate representative, or title evidence conflicts, handle that specific exception and its supporting evidence. A seller-signing default is a preparation instruction, not a claim that title has been verified.
- Save signing capacity through `POST /api/admin/deals/<deal_id>/toggle` with `field: "signing_authority"` and the actual capacity (normally `seller`). Read back `deal.signingAuthority`. Do not write only the camelCase `signingAuthority` checklist cell and then ask the realtor again because the detail field is blank.
- Leave `listingType` blank unless the realtor supplies a value. Omit listing type from both required and optional intake questions. Blank listing type does not prevent intake or MLC drafts. Never ask the realtor to repeat an answer to work around a field-storage mismatch.
- Read account-scoped `/api/admin/kit-preferences` before generating a commission question. Prefill an editable commission textarea using the saved `listingCommission` and, when present, `buyerAgencyComp` wording. Use a field object's `defaultValue` string; a placeholder or help text does not populate the answer. Prefer exact deal-specific terms and previously provided exact answers over general defaults. Do not replace an explicit edited value with the default.
- When the realtor says “normal terms” or “usual commission”, resolve that against the saved preparation preferences. If preferences exist, show their exact wording for editing instead of requesting that the realtor type it out again. Ask for the wording only if neither exact deal terms nor saved preferences are available.
- On submission, save listing remuneration in `listingCommission` and cooperating remuneration in `buyerAgencyComp` separately. Detailed tiered commission satisfies the commission-information requirement; `commissionPct` is only for a numeric rate and must never contain “normal terms” or tiered prose. Keep preferences separate from seller-agreed transaction facts and retain the document-review checkpoint.

## Missing-information card

Explain what is already known, what preparation has been done, and which next step needs the answers. Ask only for unresolved facts relevant to that step:

- Seller legal names/contact details only if absent or conflicting. Apply the seller-signing default above; ask about authority only for an identified exception.
- Agreed listing price if absent or unconfirmed, editable prefilled commission terms, contract effective date, and expiry date for MLC document preparation. Reuse saved dates instead of asking again.
- Inclusions, exclusions, or special terms for the selected form. For initial preparation they may remain blank/pending; before final document approval, resolve any material terms instead of assuming “none.”

Use separate, clearly labelled fields; use `type: date` for each date, `select` for a bounded decision, and `textarea` for commission or special terms. Never combine legal names with authority, or three dates in one text box. Put genuinely optional questions in `human_prompt.optionalFields` (or mark `required: false`), and explain why they are optional. Planned go-live timing may be recorded if known; it is not a prerequisite for intake or initial drafts unless the selected form specifically requires it. Do not add photos/Drive links to MLC intake: those belong to the workflow that consumes the photos.

Do not fabricate dates, commission, ownership, seller agreement, or terms to clear a gate. Convert relative dates to absolute dates before creating forms. Missing-input answers authorize continued preparation; sending for signature still uses the existing document-review checkpoint.

## Phase Map

| Phase | Output | Human Checkpoint |
| --- | --- | --- |
| intake | Normalized deal/listing facts and unresolved document terms. | Missing seller identity, reachable contact, or property address. |
| folder | Listing folder and property lookup artifacts. | Storage/provider connection missing. |
| title/legal | PID, legal description, ownership facts, title risk notes. | Legal identity uncertainty. |
| fill | Filled MLC/listing document drafts and validation result. | Required before signing send. |
| send | Signing envelope draft or sent status. | Required before external send. |
| loopback | Signed docs attached to deal and storage. | Required before marking signed docs complete. |

## Rules

- Listing intake and MLC are the same workflow at different depth: intake gathers the facts; MLC creates the documents.
- Title/legal/ownership and assessment research needed to prepare the MLC may occur before signing. MLS publication and marketing/photo-cleanup stages remain after verified signed MLC.
- Do not send signing packages until the realtor approves document contents and signature/initial/date placements.
- When signed documents return, attach the executed PDFs and update only the checklist cells supported by evidence.
- If a provider blocks on MFA or login, write `waiting_human` with the exact portal/account needed.

## Output Contract

```json
{
  "workflow": "mlc",
  "phase": "intake|folder|title|fill|send|loopback",
  "status": "done|partial|failed|waiting_human",
  "deal_id": "",
  "artifacts": [],
  "checklist_updates": [],
  "missing_fields": [],
  "next_tasks": []
}
```

## Listing Intake documents on the scorecard

- Intake completion means facts were saved; never describe it as documents ready. Continue the documents-mode run after intake, preserving its mode and sourceIntakeRunId; a skipped run must be resumed once without replacing its history.
- Use the Listing Kit build and document-generation endpoints for every selected form. Save PDFs in `deal.extraToggles.listingKit.documents`; these are the same records shown in the scorecard's Listing Intake document section, the document editor, and the approval popup. Loose files or chat links alone do not satisfy the handoff.
- Require a real, current PDF for every selected form (MLC, DORTS, PNC and the applicable PDS by default), render and inspect them, and attach draft artifacts to the deal. Keep seller disclosures and unverified title/ownership claims unresolved rather than filling invented answers.
- Finish preparation with the shared `document_review_prompt` from `elevate_cli.mlc_handoff` through the result callback. It binds approval to the current PDF bytes and inputs. Rebuilding, changing terms or changing selected forms requires renewed review; do not carry forward a previous approval.
- The document-review decision authorizes signature setup only. Prepare the signature/initial/date placements and obtain a separate explicit send approval before any envelope is sent. Never treat intake answers as authority to send.

## Current title and seller verification are required during Listing Intake

- Run the title phase during intake, before treating the MLC drafts as ready for approval. Do not defer title research until the MLC is signed. The broader post-signing property/marketing lookup is separate.
- First locate a recent current title for this parcel in deal storage and LTSA orders. If absent, search the exact PID through the configured title provider and obtain the current registered title. Do not substitute historical MLS, assessment, a cancelled title, or masked search-result names for the actual current title. Ask for a new paid order only when existing session authorization does not already cover the charge; show the exact order and fee.
- For LTSA verification, prefer email/backup email when offered and retrieve the current verification message through the connected inbox. Do not retain one-time codes.
- Save and attach the actual title PDF, search timestamp, title number, PID, legal description, registered owners, mailing addresses and source. Reconcile every seller/signing party against title. Surface any additional owner, name discrepancy, representative authority or relevant title restriction before approval; do not infer sole ownership from a CRM name.
- Persist `listingTitleVerification` with `filePath`, `sha256`, `searchedAt`, `titleNumber`, `pid`, `registeredOwners`, `matchedSellerNames`, `ownerMatch`, and `status`. Use `verified`/true only after reconciling all sellers. Record conflicts as pending with exact next steps. The approval guard checks this receipt and the current seller names/PID.
- Save the independently sourced seller mailing address in `sellerMailingAddress` and its source in `sellerMailingAddressSource`. Use it in the MLC top-left seller block. The listing address is not automatically the seller's mailing address.
- Fill all four remuneration fields, including the listing brokerage's retained share in Section 5 D(ii). For clearly matching tiers, subtract cooperating remuneration from total remuneration tier by tier; preserve the tax basis. Save any explicitly agreed exception in `listingBrokerageRetained`. Never leave a calculable retained share blank. For unmatched/custom terms, request the missing wording.
- Preserve draft preview links while title/seller corrections are pending, but do not offer an actionable document approval until the current title, seller reconciliation, mailing address and retained commission are complete. Refresh the review after corrections and regeneration.

## Listing Intake title purchase approval belongs on the Action Board

This applies to every future listing intake and to `mode: listing_intake_title`. The title is needed **before MLC approval** to establish every registered seller's full legal spelling. A CRM name, nickname, historical MLS or masked title-search result is insufficient.

- Intake completion automatically queues a dedicated `property-lookup` run with `mode: listing_intake_title`. That mode does only the pre-signing title/owner work and bypasses the full lookup's signed-MLC prerequisite. Reuse this run; do not create a second purchase request in chat.
- Search saved title documents and recent provider orders first. If a paid current title is needed, stop at the exact order summary and publish the charge through `POST /api/admin/deals/{deal_id}/title-order-review` with `pid`, `titleNumber`, `totalCad` (decimal string including all fees/tax), `quotedAt` (ISO timestamp with timezone), and optional `runId` of the dedicated title run. Never pass an MLC documents run as the title run.
- In a local worker, the equivalent is `elevate_cli.listing_title.prepare_title_order(conn, deal_id, quote, run_id)` inside `elevate_cli.data.connect()`. It saves the durable Action Board/scorecard approval. Report `waiting_human` with its returned `humanPrompt` through the result callback. **A chat-only fee question does not satisfy this checkpoint.**
- The card must say **Approve title purchase**, identify the current registered title/PID, and show the exact total. It must remain distinct from **Approve listing drafts**. Board consent applies only to this title and amount; do not re-ask in chat after board approval.
- On resumption read `currentRun.humanPrompt.titleOrder` and `decision.titleOrderHash`. Reopen the exact current order, recheck its PID/title and live all-in fee, then call `POST /api/admin/action-runs/{run_id}/claim-title-order` with the live `pid`, `titleNumber`, `totalCad`, and `quotedAt`, or `claim_title_order(conn, run_id, quote)` locally. Commit that claim before clicking Purchase. A changed amount/parcel/title needs a new board quote. A prior claim means check the provider inbox/receipt and reconcile the first attempt; do not purchase twice.
- Retrieve the actual PDF, attach it in the existing listing documents, and record the verified title receipt. Copy every owner's full legal spelling into the saved seller legal names; preserve contact email/phone. Name differences or additional owners require explicit reconciliation. Keep owner identity separate from representative signing authority, retaining supporting evidence where needed.
- Regenerate the MLC with those verified legal names in its seller and seller-signature blocks. The backend compares actual PDF field values with the verified names; setting a receipt's status alone does not clear the MLC gate. Rebuild the other affected forms, inspect the rendered PDFs, and use the same pending draft-review run. Title-task success automatically queues that document preparation; it does not approve the documents.
- Keep title requests, missing-access questions, discrepancies and status on the Action Board and Listing Intake documents. These title runs use local delivery; do not send a separate Telegram/email/SMS notice or require the realtor to monitor chat.

- After retrieving the actual title PDF, file it in the matched property Drive folder and save its Drive file ID/link with `listingTitleVerification`; do not leave the title only in an internal artifact directory.
