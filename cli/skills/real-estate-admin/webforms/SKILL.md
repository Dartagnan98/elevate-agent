---
name: webforms
requires_onboarding: [forms_provider]
description: "Pull or draft BCREA/CREA WEBForms transaction forms via TransactionDesk. Use when the realtor asks for 'WEBForms', 'TransactionDesk', 'a CPS/listing/amendment PDF', 'a forms transaction from an MLS number', or an AuthentiSign envelope built from a WEBForms deal. Pre-imports MLS data and prepares the editable forms. Not for sending SkySlope envelopes — use digisign; not for provider-neutral signing — use signing-package. Login/MFA pauses for the user."
metadata:
  elevate:
    tags: [real-estate, forms, documents, webforms, transactiondesk]
    runtime:
      approval_required: true
---

# WEBForms

Use this skill for authenticated WEBForms / TransactionDesk work. It prepares or pulls the editable forms. DigiSign or AuthentiSign owns signature send. SkySlope owns final transaction filing.

## Required Inputs

- Deal ID or enough identifiers to match the deal.
- Property address.
- MLS number when importing listing data.
- Form or template name/code.
- Side/role: buyer, seller, listing, both, or transaction admin.
- Desired output: editable PDF, draft transaction, or AuthentiSign envelope draft.

If form code, role, address, or MLS number is missing for a create/import task, stop and ask. Do not guess.

## Auth Rules

- Use the configured forms provider login from onboarding.
- Do not print, store, or hardcode WEBForms passwords, MFA codes, cookies, or full download URLs.
- If MFA appears, use the available human-approved email-code flow or pause for the user.
- MFA can offer WebAuthn/TouchID that automation cannot pass — pick "Try another method" and use the email code.
- Login can also be walled by Imperva/hCaptcha. Stop and report `waiting_human`; never substitute a self-designed form layout for the real form.
- Treat login/MFA as a human blocker, not as a failed forms workflow.

## Browser Rules (read before opening anything)

- Drive WEBForms with the built-in `browser_*` tools ONLY (`browser_navigate`,
  `browser_snapshot`, `browser_click`, `browser_type`, ...). On a desktop they
  automatically provision a VISIBLE Chrome window cloned from the user's real
  profile over CDP — it is already persistent (cookies and "remember this
  browser" survive across sessions) and already logged into whatever the user
  is logged into. You do not need to build persistence yourself.
- NEVER hand-roll browser automation through the terminal: no Selenium, no
  chromedriver, no raw CDP websocket scripts, no launching Chrome binaries
  with `--remote-debugging-port`, no custom `--user-data-dir` profiles. That
  path burns the session fighting ports/profiles and bypasses the managed
  logged-in window that already solves MFA persistence.
- If the `browser_*` tools are NOT available in this session, STOP. Report
  that the browser engine is not installed on this machine (fix:
  `elevate doctor`, or `npm install -g agent-browser && agent-browser
  install`). That is an environment blocker to surface to the user, not
  something to work around with terminal scripts.
- MFA "remember this browser" checkboxes: tick them inside the managed
  window — the managed profile persists, so the code prompt should not
  return on the next run.

## Pull Editable Form PDF

1. Match the deal.
2. Open WEBForms / TransactionDesk.
3. Create or open the matching transaction.
4. Choose the exact template and source board.
5. Import MLS/property data when available.
6. Open the Forms tab and select the requested form.
7. Save or download the editable PDF.
8. Verify the local file exists, is a PDF, and has a plausible size/page count.
9. Return the PDF path and transaction/form IDs in the result.

## Create AuthentiSign Envelope From Existing WEBForms Deal

Use this path when the user asks to make an envelope from WEBForms for one of the current deals.

1. Match the current deal from Elevate deals/Postgres.
2. Open the existing WEBForms transaction by address/MLS.
3. Go to the Signings tab.
4. Click Add AuthentiSign.
5. Name the envelope clearly:
   `<Address> - <Document Set> Envelope`.
6. In AuthentiSign, add documents/forms from the WEBForms transaction.
7. Add signers only when seller/buyer names and emails are available.
8. If seller/buyer fields are blank, save the draft and report that signers could not be added until contact data is supplied.
9. Verify the Signings list shows the draft envelope title, modified timestamp, and document count/status.

## Template Hints

- Buyer-side in BC is often called Selling Agent in WEBForms.
- Seller-side is usually Listing Agent.
- Source must be selected before the MLS input may appear.
- CPS Strata can use a strata template while the main downloaded form may still be titled CPS - Residential. Name output files by actual form content, not the template title.

## Form-Fill Rules

- Every BCREA/CREA/board form with property-ID fields gets the full identity block (civic address, legal description, PID, other PIDs) even when a parent contract already has them. Source priority: title PDF → BC Assessment/lookup → SkySlope Property tab → original CPS/MLC.
- Manufactured homes on rented pads use the MHR identity (registration number, pad/park, serial, year/make/model) instead of a land PID.
- Execution/signing dates are the day the envelope is SENT, not a future effective date.

### BC Collapse Scenarios

Verify against the brokerage's ops doc before treating this tree as a hard default, and never default to a General Release before verifying deposit/subject status from the deal and the CPS:

- Subjects NOT removed + NO deposit → Collapse of Sale form + cancel the transaction.
- Subjects not removed + deposit PAID → the Collapse-with-Deposit path (bank details/void cheque for the deposit return; FINTRAC Receipt of Funds on buyer files).
- Collapsed AFTER conditions were removed / sale reported → General Release & Authorization to Pay Deposit Funds + MLS Collapsed Sales Report.

## Provider Rules

- If native download is swallowed by the browser, use the configured browser-download helper or a CDP download path.
- If browser-to-localhost upload hangs, allow browser downloads and navigate directly to the captured TransactionDesk download API URL, then verify the downloaded file.
- Do not send, sign, submit, publish, or file compliance documents unless the user separately approves that exact external action.
- Fake/test documents must be visibly marked fake and must stop before any signing/send/compliance submission.

## Completion Gate

Before reporting `done`, verify every applicable item:

- Correct deal/address/MLS.
- Correct transaction/template/form.
- MLS/property data imported when expected.
- Editable PDF exists locally when requested.
- Envelope draft exists when requested.
- Signer availability was checked before adding recipients.
- The result includes transaction/form/envelope IDs when available.

If any required item is not verified, report `partial` and name the exact missing step.

## Output Contract

```json
{
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "address": "",
  "mls": "",
  "form_code": "",
  "role": "",
  "provider_transaction_id": "",
  "provider_form_id": "",
  "envelope_id": "",
  "pdf_path": "",
  "verified": [],
  "risks": []
}
```
