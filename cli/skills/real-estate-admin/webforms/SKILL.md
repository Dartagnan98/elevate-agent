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

## Required Inputs

- Deal ID or enough identifiers for `deal-matcher`.
- Property address.
- MLS number when the form imports listing data.
- Form name or code.
- Side/role: listing, buyer, seller, both, or transaction admin.
- Province package form guidance.
- Configured forms provider and login route.

If a form code or role is missing, stop and ask. Do not guess from the stage name.

## Flow

1. Match the deal.
2. Open the configured forms provider through the configured connector or Browser Use.
3. Create or open the transaction using MLS/property data when available.
4. Select the exact form/template requested by the province package or human.
5. Download or save the editable PDF/draft artifact.
6. Attach the draft to the deal and request review before signing/send.

## Provider Rules

- MFA and portal login prompts are human blockers, not failures.
- If a native download is blocked, use a configured download-capture helper only when available.
- Keep provider transaction IDs and form IDs in the run result so future syncs can find the same file.
- Never send forms externally from this skill. Send belongs to `signing-package` after human approval.

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
  "pdf_path": "",
  "risks": []
}
```
