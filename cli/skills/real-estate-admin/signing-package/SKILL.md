---
name: signing-package
description: Provider-neutral e-sign package orchestration for listing, MLC, offer, subject-removal, and closing documents. Can use DigiSign, DocuSign, Authentisign, or another configured provider.
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
