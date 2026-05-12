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
