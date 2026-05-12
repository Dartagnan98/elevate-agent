---
name: webforms
description: Provider-neutral forms workflow for brokerage/board documents. Uses the configured forms provider, exact form names/codes, deal identity, and human approval before external send.
metadata:
  elevate:
    tags: [real-estate, forms, documents]
    runtime:
      approval_required: true
---

# Forms Workflow

Use when a deal run needs a form from the configured forms provider.

Require deal identity, property address, MLS number when relevant, form name/code, role/side, and province package guidance. Do not create placeholder documents when any required input is missing.

Prepare the form, attach drafts/evidence, and request human review before any external send.
