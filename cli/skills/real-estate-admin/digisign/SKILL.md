---
name: digisign
requires_onboarding: [identity_profile, signing_provider]
description: Send real estate forms for electronic signature through SkySlope DigiSign, place signer blocks, verify delivery, and route signed PDFs back into the transaction record. Use when the realtor asks to send documents for signing, create a DigiSign envelope, get seller or buyer signatures, send listing paperwork, or pull signed documents back from DigiSign.
metadata:
  elevate:
    tags: [real-estate, signatures, skyslope, digisign, forms]
    runtime:
      approval_required: true
---

# DigiSign

Use this skill for SkySlope DigiSign e-signature work in a real estate transaction.

This skill owns the signing envelope path. WEBForms prepares or pulls the editable forms. DigiSign sends them for signature. SkySlope stores the signed result on the correct transaction checklist row.

## Required Inputs

- Deal ID or enough identifiers to match the deal.
- Property address.
- Form names or local PDF paths.
- Sender side: listing, buyer, seller, both, or transaction admin.
- Signer names and emails.
- Whether the envelope should be drafted only or sent after review.

If a signer name, signer email, deal, or exact document is missing, stop and ask. Do not guess recipients.

## Auth Rules

- Use the configured signing provider credentials from onboarding.
- Do not print, store, or put passwords, bearer tokens, or full session headers into chat, logs, memory, or handoffs.
- If SkySlope asks for MFA or the session is stale, pause for human login rather than treating it as a failed automation.

## Flow

1. Match the deal and confirm the exact documents to send.
2. Open SkySlope / DigiSign through the configured browser session.
3. Create a new envelope with a clear title:
   `<Address> - <Document Set> - <Date>`.
4. Upload the prepared PDFs.
5. Add recipients from the deal record or from explicit user instruction.
6. Place signature, initials, date, and full-name blocks only on the correct signer lines.
7. Review the envelope before send.
8. Send only after the user has approved send, unless the task explicitly included approval.
9. Verify envelope status and recipients after send.
10. When documents are completed, download the signed PDF and attach it back to the correct SkySlope checklist row, not just the generic Documents tab.

## Placement Rules

- DigiSign coordinates use top-left origin.
- Use form-specific saved coordinates when available.
- Never place a block over body text or over another signer line.
- Managing broker lines must receive the managing broker recipient when the form requires it.
- Listing-side amendments, cancellations, and brokerage forms must be checked for managing broker / authorized signatory language before sending.

## Completion Gate

Before reporting `done`, verify every applicable item:

- Envelope exists with the expected title.
- All intended documents are attached.
- Recipients match the deal/user-provided signer list.
- Signature/initial/date/name blocks are placed on the correct pages.
- Envelope was sent or intentionally left as draft.
- Signed PDF was downloaded when completion was requested.
- Signed PDF is attached to the correct SkySlope checklist row when filing was requested.

If any required item is not verified, report `partial` and name the exact missing step.

## Output Contract

```json
{
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "address": "",
  "envelope_id": "",
  "envelope_status": "",
  "sent": false,
  "signed_pdf_path": "",
  "skyslope_checklist_item": "",
  "verified": [],
  "risks": []
}
```
