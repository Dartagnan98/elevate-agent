---
name: skyslope-sync
description: Sync configured compliance-platform transaction status and documents to an Elevate deal file. Works with SkySlope or another brokerage compliance portal via browser workflow.
metadata:
  elevate:
    tags: [real-estate, compliance, documents]
    runtime:
      result_writer: admin-result-writer
---

# Compliance Platform Sync

Use after MLC/listing paperwork begins and during closeout.

Open the configured compliance platform playbook, match the deal, pull transaction status and available documents, and write missing-document tasks back to the deal. This skill is provider-neutral; SkySlope is one possible configured portal.

Do not guess document status. If portal access, transaction identity, or document names conflict, ask for human review.

## Provider-Neutral Scope

This skill syncs the configured brokerage compliance portal. The portal may be SkySlope or another provider set during onboarding. Treat the portal name, login URL, and checklist labels as tenant configuration.

## Flow

1. Match the deal by portal transaction ID, MLS, address, or contact verifiers.
2. Open the configured compliance portal through Browser Use or provider connector.
3. Pull transaction status, checklist status, required/missing documents, comments, and available files.
4. Attach downloaded files to the deal when the match is proven.
5. Write missing-document tasks back to the deal record in the operational store.
6. Close through `admin-result-writer`.

## Rules

- Do not mark a compliance checklist complete unless the portal says complete or the file/status evidence is attached.
- If portal labels differ from the province package, keep both labels in the artifact/task.
- MFA/login needed is `waiting_human`, not a silent failure.

## Filing signed / completed documents to the deal's Drive folder — SEPARATE PDFs, one per document

When completed/signed documents must be mirrored into the deal's Google Drive folder (the card **Documents** tab, i.e. the `cps-drive-save.py` target), file **EACH document as its own separate PDF**. Skyleigh's hard rule: never file the single merged DigiSign "Envelope completed" PDF as the deal's documents — that produces one combined file she cannot work with. The docs went to DigiSign separate and must come back separate.

Use the live SkySlope session (no DigiSign API bearer token needed — scheduled runs do not have one):

1. Open the active SkySlope transaction/listing checklist for the matched deal; verify the header first.
2. Enumerate every **Completed** checklist row with an attached signed document (CPS, Buyer's Agency, DORTS, PNC, FINTRAC, Deal Sheet/TRS, PDS, MLS Sheet, remuneration disclosure, subject removal, etc.).
3. Download **each row's** signed PDF individually via the per-row SkySlope download flow (the `__EVENTTARGET` postback on the row's `lnkFileName` → `DocumentView.aspx` → signed S3 URL; decompress if bytes start with gzip magic `1f 8b`).
4. Verify each (`pdfinfo`/`pdftotext`).
5. File each separately: `python3 scripts/cps-drive-save.py --address "<street>" --file "<tmp>:<DocType>"` using the real document name as `<DocType>`. One call per document — never concatenate.
6. Record each in `documents_attached`.
7. Fallback only: if SkySlope is unreachable, do not silently file the merged Gmail attachment as the finished docs — return `partial`/`waiting_human`, or file a merged copy clearly labelled `<Address> - COMBINED envelope (split pending)` and flag it for a later per-document replacement.

## Output Contract

```json
{
  "workflow": "compliance-sync",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "provider": "",
  "transaction_id": "",
  "documents_attached": [],
  "missing_document_tasks": [],
  "portal_status": "",
  "risks": []
}
```
