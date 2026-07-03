---
name: signing-package
description: "Orchestrate a provider-neutral e-sign package for any transaction document. Use when the realtor asks to 'send documents for signature' and the provider is unspecified or is DocuSign/Authentisign, or you need one flow across mixed signing tools for listing, MLC, offer, subject-removal, or closing docs. Not for SkySlope-specific envelopes — use digisign; not for preparing WEBForms — use webforms. Confirms document set, signers, order, and placements; sends only after human approval."
metadata:
  elevate:
    tags: [real-estate, documents, signing]
    runtime:
      approval_required: true
      result_writer: admin-result-writer
---

# Signing Package

Prepare signing packages through the configured signing provider. Keep this provider-neutral: DigiSign, DocuSign, Authentisign, or a brokerage signing tool are implementation details.

Before sending externally, confirm the document set, signer names, signing order, signature/initial/date placements, and required witness/broker fields. Ask for human approval before send.

After signing status changes, attach signed documents and update checklist cells only when the signed files or status evidence exists.

## Required Inputs

- Verified deal ID.
- Document set and form names.
- Signer names, emails, roles, and signing order.
- Signing provider configured during onboarding.
- Placement map or provider-native fields for signatures, initials, dates, checkboxes, and full-name fields.
- Email subject/body if the provider sends an external envelope.

## Provider-Neutral Placement Rules

- Filled text must not overlap form labels or existing text.
- Signature, initial, date, and full-name fields must be assigned to the correct signer.
- Do not infer witness, managing broker, or second-signer fields without context.
- Render or preview the package when the provider supports it.
- Ask for human approval before the envelope is sent outside Elevate.

## Browser Procedure Notes

Editor mechanics learned in the DigiSign editor; most apply to any browser-driven signing editor:

- The PDF pane is an internal scroll container — generic scroll commands will not reach the signature area. Scroll the viewer element via synchronous JS (async/Promise eval snippets serialize as `{}`/None in browser drivers — use sync JS, or verify through state and screenshots).
- Field placement is two clicks: toolbar field type, then a PDF coordinate. A first click may select an existing block — press Escape and retry.
- Switch signer via the left-panel dropdown BEFORE each signer's placements.
- A disabled Send button means fields are still missing.
- An adjacent envelope row's "Completed" badge can sit directly above your target — tie status to the exact row/name.

## Flow

1. Verify deal identity with `deal-matcher` unless run context already proves `deal_id`.
2. Verify every source document exists.
3. Prepare the provider package or draft envelope.
4. Validate placements and signer assignments.
5. Create a human approval prompt with document list, signer list, and preview/artifact links.
6. After approval, send or hand off according to the provider.
7. On completion, attach executed documents and update the deal.

## Output Contract

```json
{
  "provider": "",
  "status": "drafted|sent|completed|waiting_human|failed",
  "envelope_id": "",
  "documents": [],
  "recipients": [],
  "placements_validated": true,
  "signed_artifacts": [],
  "risks": []
}
```
