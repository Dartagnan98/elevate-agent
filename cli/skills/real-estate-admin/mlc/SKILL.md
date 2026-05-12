---
name: mlc
description: Listing intake and Multiple Listing Contract workflow. Collects listing details, prepares required listing documents, and asks for human approval before signing/send.
metadata:
  elevate:
    tags: [real-estate, listing-intake, mlc, documents]
    runtime:
      approval_required: true
---

# MLC

Use for listing intake and MLC document preparation.

Collect required listing details, signer authority, price, commission, planned go-live timing, property identity, brokerage/regional requirements, and configured forms-provider details. Prepare documents through the configured forms/signing providers.

Before sending for signature, ask for human approval that the forms, fields, and signature placements are correct. After signed docs are verified, write artifacts/checklist updates with `admin-result-writer`.
