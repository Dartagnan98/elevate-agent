---
name: skyslope-sync
description: "Sync a compliance portal's transaction status and documents onto an Elevate deal. Use when the realtor says 'sync SkySlope', 'check the compliance status', or 'pull the transaction docs', or during MLC/closeout when portal state must match the deal. Provider-neutral (SkySlope or another configured portal); files missing-document tasks and attaches files only on a proven match. Conflicting status or MFA asks for human review, never a guess."
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

## SkySlope Portal Automation Notes

Apply these when the configured portal is SkySlope:

- ASP.NET legacy pages: controls are anchors styled as buttons — prefer exact IDs (`#ContentPlaceHolder1_ibtnNext`, `#ContentPlaceHolder1_Escrow_CmdSave`). Never call `WebForm_DoPostBackWithOptions('…ibtnNext', …)` unless the element actually exists in the DOM.
- The React dashboard (agent.skyslope.com) often ignores index clicks, and direct `.aspx` deep links can 404 — trigger buttons via page JS from the logged-in dashboard.
- Login: the integrated login has a top-level flow plus a background `auth.skyslope.com` iframe — use the visible flow first; if iframe typing is flaky, use CDP isolated-world injection. Input-replace beats type-append on the username field. After login an older browser target can stay active (especially when MLS SSO also opened) — activate the right target explicitly. Use the brokerage email for login, not a personal address.
- Manage Listings ≠ Manage Transactions: an active listing file may not appear in Manage Transactions at all, and the search box can appear to do nothing — inspect the active/cancelled/closed lists directly for duplicates.
- Checklist verification: row status "In Review" is not document-completeness proof. Truncated names resolve via `ShowTransactionDocuments.aspx` and each PDF's S3 `response-content-disposition` filename. Paperclip/View links have three behaviors (ShowDocuments.aspx, S3 popup, same-tab nav) — handle all three.
- Uploads: checklist row → the "Upload Documents To <row>" page exposes a hidden `input#file-uploader` — attach to the file input directly, then reload and read the checklist back.
- "Subject Removal & Appointment of Conveyancer" and "Waiver of Subjects form" are SEPARATE checklist rows; partial notices belong on the former.
- Create Listing: the final control is "Create Listing"; persist `ListingCheckList.aspx?id=<numeric>` as the canonical listing reference.
- Contacts tab: the "At least one contact is required… Buyer's/Seller's Lawyer" banner can be informational — do not stall on it when the user said there is no lawyer info.
- Pending-transaction scrape: rows carry `data-href="/TransactionChecklist.aspx?…"` — fetch each with `credentials: 'include'` + DOMParser and read the labeled fields (CLOSE OF DEAL, SALE PRICE, BUYER, SELLER, ACCEPTANCE DATE); import with `source_key="skyslope:<transaction_id>"`.

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
