---
name: matrix-price-change
description: "Process a signed listing price amendment on Matrix/Xposure and update Admin records. Use when the realtor says update MLS #... from one price to another on an already-live listing, for a price reduction or increase."
metadata:
  elevate:
    tags: [real-estate, admin, mls, matrix, xposure, price-change]
    runtime:
      approval_required: true
---

# Matrix / Xposure Price Change

Use when the realtor asks to process a signed price amendment for an already-live AOIR Matrix/Xposure listing.

## Preconditions

1. Signed price amendment / MLC amendment is available as a local PDF or verified document source.
2. MLS number, address, old price, and new price are known from the signed amendment or user instruction.
3. The request itself is approval to process the price change only if it is explicit, e.g. “update MLS #... from $X to $Y.” If unclear, ask before clicking Submit.
4. Human approval is still required for unrelated external sends, signatures, listing activation/publication, or client-facing messages.

## Workflow

1. Verify the signed amendment artifact.
   - Confirm file exists.
   - Capture SHA-256 of the PDF.
   - If a page image exists, use vision to verify visible MLS number, property address, old/new price change language, signature/date.
   - If no page image exists, render page 1 to PNG first.

2. Locate or create Admin deal context.
   - Start with `deals_overview`.
   - If the live Admin store has no deal row, query contacts/deals through `elevate_db` to avoid duplicating known contacts.
   - Create or update the Admin card only through curated helpers / `admin_deal`, not raw SQL.
   - Attach the signed amendment PDF as a specific artifact kind such as `signed_mlc_price_amendment`.

3. Run the Matrix/Xposure price-change portal script from a Node project that has Playwright installed.
   - If the script lives outside the project directory, either run it with `NODE_PATH=<project-tools-dir>/node_modules` or place the script under `<project-tools-dir>/scripts`.
   - Use a saved storage state file (for example `<realtor-tools-dir>/data/aoir-state.json`) when available.
   - Load env from `<realtor-tools-dir>/.env`.
   - If login/MFA appears, fill MLS credentials from env and poll Gmail for the 6-digit code as existing Matrix scripts do.

4. Verify the target Matrix row before opening Price Change.
   - Open `https://matrix.interiorbc.ca/Matrix/Input`.
   - Find the row containing the exact MLS number.
   - Verify the row text contains the target address/unit and current old price.
   - Important: Matrix Input row may show `525 Nicola Street #703` rather than `703-525 Nicola Street`, and may omit city even when the MLS/address are correct. Do not block solely because city is not visible in the row; record `cityVisibleOnRow=false` and continue if MLS + street/unit + old price match.
   - Abort if the MLS row address does not match the signed amendment.

5. Submit the Matrix price change.
   - Open the row’s actions/kebab menu, not the main Edit form.
   - Click the exact `Price Change` menu item.
   - Fill the price field. Try labels in this order: `List/Sale Price`, `List Price`, `New List Price`, `New Price`, `Price`.
   - If label lookup fails, fall back to finding a visible numeric input currently holding the old price and replace it with the new price.
   - Capture screenshots before submit, after fill, and after submit.
   - Click Submit/Save/Update only after the MLS/address/old-price verification passes.

6. Verify the portal result.
   - Treat text like `Input Succeeded`, `successfully`, `saved`, or `Price updated` only as a submission signal, not final verification.
   - If Matrix returns validation/error/required text, capture the exact body text and screenshots and report `blocked_validation`.
   - Reopen the Matrix Input page and capture the final row text after a short cache wait. If the new price is visible in the row, record that as final verification. If the portal success text appeared but the row does not show price, report `submitted_check_needed`, not `updated`, with screenshots.
   - Before reporting `updated`, verify the new price in at least one durable source: Matrix Input row, live public/board MLS view, or a reopened edit form showing the new value. A success banner alone is not enough.
   - Write a JSON proof artifact under the deal/admin artifact folder containing: MLS, address verification, before row text, final row text, old price seen, new price visible, submit text sample, screenshots, and result status.

7. Upload/file the signed amendment in SkySlope / compliance as appropriate.
   - Use the listing/deal SkySlope file for the exact property and MLS number.
   - Upload the signed price amendment to the listing amendment / price-change checklist row when available, or the closest signed amendment/listing documents row.
   - If the SkySlope listing cannot be found, login blocks, or upload control is missing, report the exact blocker and do not claim filed.

8. Notify BC Listings when the board/listing workflow requires or benefits from direct processing.
   - Board-specific price-change workflows often require a notice lane to the board contact (e.g. BC Listings for AIR/AOIR boards); do not omit this lane silently if the realtor's board requires it. If it is not ready to send, explicitly report `bc_listings_notice_status: blocked` with the reason.
   - Verify the recipient before sending against the realtor's current source-of-truth or prior verified transaction notes; do not assume a remembered address is still correct.
   - Check Gmail/send records for duplicates before creating anything, using both sent and draft searches such as `to:<board-recipient> ("<address>" OR "<MLS>") newer_than:30d`, `in:sent ...`, and `in:drafts ...`. Also check Elevate operational records (`deal_events`, `deal_attachments`, `admin_action_runs`, and `send_queue`) for prior proof/status before saying it was not sent.
   - If the amendment is only sent for signature / DigiSign or SkySlope envelope is still `InProgress`, do not email the board contact unless the realtor explicitly approves sending before execution. Record the envelope id/status, who remains incomplete, and create or keep an Admin follow-up task to send/draft the board notice once the executed amendment and Matrix/SkySlope step are ready.
   - If the task explicitly asks to send/draft the board notice and the executed/signed amendment is available, send or draft a concise price-change email with the signed amendment attached. Include address, MLS number, seller name if known, old price, new price, and signed amendment date.
   - Prefer cc'ing the realtor's own brokerage email address when following her historical board-notice pattern.
   - After sending/drafting, verify the Gmail object by fetching metadata. Record message/draft id, thread id, labels/status, to/cc/subject/date, attachment path/filename, duplicate-check result, and recipient-verification sources in a proof JSON artifact.
   - If the Matrix/SkySlope processing is still failed or blocked, still return the board-notice proof/status alongside the portal status, and clearly mark the portal follow-up needed.

9. Update Admin records and scorecard.
   - Set `listPrice` / `list_price` to the new amount.
   - Ensure `mlsNumber` / `mls_number` matches the portal row.
   - Attach the signed amendment PDF and Matrix/SkySlope proof JSON/screenshots.
   - Record an event/activity noting old price, new price, MLS number, address verification, and portal status.
   - Verify with `admin_deal(show)` or targeted `elevate_db` queries before reporting.

## Output Contract

Return concise status with:

```json
{
  "workflow": "matrix-price-change",
  "status": "updated|submitted_check_needed|blocked_validation|waiting_human|failed",
  "mls_number": "",
  "address_verified": true,
  "old_price": 329900,
  "new_price": 324900,
  "signed_amendment_filed": "yes|no|blocked",
  "matrix_status": "updated|submitted_check_needed|blocked_validation|failed",
  "bc_listings_notice_status": "sent|drafted|not_needed|blocked|not_requested",
  "bc_listings_message_id_or_draft_id": "",
  "admin_update_status": "updated|blocked|not_applicable",
  "proof_artifacts": [],
  "blockers": []
}
```

## Pitfalls

- Running a copied script outside the project directory can fail with `Cannot find module 'playwright'`. Fix with `NODE_PATH=<project-tools-dir>/node_modules` or run from a script path under the project.
- Matrix Input row address ordering may differ from signed document formatting: `525 Nicola Street #703` equals `703-525 Nicola Street` for verification when MLS and price also match.
- Do not require city to appear on the Matrix Input row; many rows omit city.
- Matrix/Xposure may show a green `Property has been successfully updated` / `Input Succeeded` banner even when the edited price did not persist. This can happen if the script mutates a disabled auto-sync price field. Always read the input value after filling, screenshot it, submit, then reopen and verify the row or another durable MLS view shows the new price before calling it updated.
- If the Price Change form's price input is disabled, do not simply remove the `disabled` attribute and submit. That can create a false-positive success banner while the listing remains at the old price. Capture the field dump and report `submitted_check_needed` or investigate the proper editable workflow/source field.
- If the row remains at the old price after a success banner and cache wait, downgrade the result from `updated` to `submitted_check_needed` or `failed_verification`; do not update Admin price as if verified.
- Never update the price if the row only matches by MLS but the address/unit conflicts.
- Keep all portal proof artifacts under a property-specific admin artifact folder so they can be attached back to the deal.
