---
name: property-lookup
description: Look up prior MLS/property context after MLC is signed. Feeds listing-build with property facts, prior remarks, features, and safe verification notes.
metadata:
  elevate:
    tags: [real-estate, mls, property-research]
---

# Property Lookup

Use the full MLS/marketing property lookup after MLC is signed, before listing-build.

Current title, PID/legal verification and seller/owner reconciliation are an exception: perform those during Listing Intake, before MLC draft approval, following the MLC title phase. Do not use the post-signing timing to skip the title needed to prepare the listing contract.

Use the configured MLS/board portal and property sources to gather prior listing context, property facts, tax/assessment notes, room/features context, and old MLS remarks. Keep source notes and confidence.

Do not copy unsupported claims into public listing copy. If MLS access or address identity is uncertain, ask for human review.

## Required Configuration

- Province and served market.
- MLS login or property-data provider.
- Assessment/public-record source for the province.
- Optional municipal/zoning source if configured.
- Storage destination for property reports.

Do not hardcode boards, cities, or portals. A realtor may work multiple boards; use the configured area sources and fall back to manual review when a source is unavailable.

## Flow

1. Match the deal and confirm signed MLC is present or manually confirmed.
2. Normalize the address, including unit/strata/rural formats.
3. Pull prior MLS/listing history when access is configured.
4. Pull assessment/property facts and legal/PID data where available.
5. Pull zoning/municipal facts only from configured or public sources.
6. Produce a property context artifact for `listing-build`.

## BC listing report handoff

For BC listing preparation, obtain the actual BC Assessment PDF and Property Information Report PDF for the matched property. Save and verify both in the existing listing Google Drive folder, retaining source, date, property identifiers and Drive file IDs/paths in the property-context artifact. Reuse current verified copies; a facts summary does not replace either PDF. Locate the current title PDF and any supplied floor-plan PDF as part of the same handoff.

Pass these files to the [Matrix document/link checklist](../matrix-incomplete-listing/references/documents-and-links.md). If a report is unavailable, identify it and its source/access blocker explicitly; complete the independent research rather than calling the missing PDF delivered.

## Output Contract

```json
{
  "status": "done|partial|waiting_human|failed",
  "address": "",
  "pid": "",
  "legal_description": "",
  "assessment_value": null,
  "zoning": "",
  "jurisdiction": "",
  "prior_mls": [],
  "report_path": "",
  "sources": [],
  "risks": []
}
```

Partial results are useful. If zoning fails but MLS and assessment succeed, write the handoff with a zoning risk instead of blocking the whole listing.

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

- After retrieving the actual title PDF, upload it to the matched property Drive folder with `gws drive +upload`; verify the returned Drive file ID/name and save the Drive folder/file link in `listingTitleVerification`. An internal artifact alone is not a completed title filing.
