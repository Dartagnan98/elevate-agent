---
name: digisign
requires_onboarding: [identity_profile, signing_provider]
description: "Send forms for e-signature through SkySlope DigiSign. Use when the realtor says 'send this for signing', 'create a DigiSign envelope', 'get the sellers to sign', or 'pull the signed docs back'. Places signer blocks and routes signed PDFs back to the transaction. Not for provider-neutral signing — use signing-package; not for preparing the editable forms — use webforms. Sends only after human approval; SkySlope MFA pauses for login."
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

## API Token Capture

When direct DigiSign API calls need a bearer token:

- Load `https://agent.skyslope.com/` and capture the `Authorization` header from a fired DigiSign API request (for example `digisign3.skyslope.com/api/envelopesgraphql`).
- Do NOT navigate to `digisign3.skyslope.com` directly — it opens the Redoc API docs and creates no session. `forms.skyslope.com` redirects to the public Forms login and yields no token either.
- A logged-in dashboard alone is not enough: no token exists until a DigiSign request fires. Open "Recent DigiSign Envelopes / View All Envelopes" or `https://send.skyslope.com/envelopes?idp=prime` to trigger one.
- Fallback: `localStorage['com.skyslope.id.tokens']` holds `accessToken` / `globalAccessToken`. These can be NESTED OIDC objects, not strings — extract `(globalAccessToken || accessToken).accessToken`.
- Save only the raw JWT to a mode-600 file, decode `exp` and verify validity before use, and never print it.

## API Behaviors

- After document upload, `GET /envelopes/{id}` can briefly return an empty documents array even though the upload returned a document ID — do not immediately send or declare failure.
- Some accounts' GraphQL schema has no plural `envelopes` query. Use REST `GET /envelopes/{id}` for verification; capture the UI's own GraphQL shape rather than assuming documented examples.
- On some accounts `GET /envelopes/{id}` omits documents and `GET /documents` / `GET /documents/{id}/blocks` return 405. Record upload/block IDs from the create responses; do not treat the 405s alone as failure.
- `PATCH /envelopes/{id}/emailConfig?api-version=2.0` can return `UnsupportedApiVersion` while the envelope still sends fine — non-blocking if the default email text is acceptable.
- `PUT /envelopes/{id}/status` is the SEND trigger. Never call it without send approval.
- `pageNumber` in the blocks API is 0-indexed (PDF page 14 = `pageNumber: 13`).
- If Python urllib REST calls get Cloudflare `403 error code: 1010` even with a fresh token, retry via curl with a temp `--config` file carrying the bearer header, AccountId, a browser-like User-Agent, and `--http1.1`; delete the config file immediately.

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

## Correct and Resend an Existing Envelope (UI)

1. Open the envelope row menu "More envelope actions" (may need a DOM/coordinate click).
2. Accept the "Correct Envelope" warning — correction blocks recipient access and can force re-signing, so verify you have the right row first.
3. Documents step: click Next WITHOUT re-uploading.
4. Edit Recipient: change only the email. Typing into the outer combobox APPENDS to the old email — target the inner `input[placeholder="Email"]`, then verify `checkValidity()` and the signing-order card.
5. Review screen: same filename, same recipient card, new email visible, blocks intact.
6. Send → "Save time with smart emails" modal → "Send for Signatures". The confirmation URL contains the envelope UUID.

## Placement Rules

- DigiSign coordinates use top-left origin.
- Use form-specific saved coordinates when available.
- Never place a block over body text or over another signer line.
- Managing broker lines must receive the managing broker recipient when the form requires it.
- Listing-side amendments, cancellations, and brokerage forms must be checked for managing broker / authorized signatory language before sending.

## BC Package Composition

- Listing-intake drafts carry three documents uploaded SEPARATELY, never combined:
  - MLC: seller per-page initials + signatures + Resident-of-Canada initials; agent and managing-broker signatures per the local pattern.
  - PNC: seller page-1 initials, page-3 signature + date.
  - DORT Representation: agent professional-disclosure signature/date + seller consumer-acknowledgment initials/date at the bottom — NEVER a seller signature beside the agent's DORT signature.
- BCFSA Disclosure of Expected Remuneration: the consumer acknowledgment is on page 2. When the disclosure shows both original-offer and counter-offer columns, seller initials go in BOTH relevant columns.
- Accepted-offer CPS packages: information pages offset the printed page numbers — locate blocks by actual PDF page indices via rendered inspection, never by nominal CPS page numbers.

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
