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

## Required Inputs

Ask for missing items in one concise prompt when possible:

- Seller legal names, emails, phones, and signing authority.
- Property address.
- Listing price.
- Commission terms.
- Listing term, effective date, expiry date, and planned go-live date.
- Terms of sale and important exclusions/inclusions.
- Province package and required listing forms.
- Forms provider and signing provider.

Convert relative dates to absolute dates before creating forms.

## Phase Map

| Phase | Output | Human Checkpoint |
| --- | --- | --- |
| intake | Normalized deal/listing facts in the operational store. | Missing seller/property/price/commission fields. |
| folder | Listing folder and property lookup artifacts. | Storage/provider connection missing. |
| title/legal | PID, legal description, ownership facts, title risk notes. | Legal identity uncertainty. |
| fill | Filled MLC/listing document drafts and validation result. | Required before signing send. |
| send | Signing envelope draft or sent status. | Required before external send. |
| loopback | Signed docs attached to deal and storage. | Required before marking signed docs complete. |

## Rules

- Listing intake and MLC are the same workflow at different depth: intake gathers the facts; MLC creates the documents.
- Do not use old MLS lookup or photo cleanup before signed MLC is confirmed.
- Do not send signing packages until the realtor approves document contents and signature/initial/date placements.
- When signed documents return, attach the executed PDFs and update only the checklist cells supported by evidence.
- If a provider blocks on MFA or login, write `waiting_human` with the exact portal/account needed.

## Output Contract

```json
{
  "workflow": "mlc",
  "phase": "intake|folder|title|fill|send|loopback",
  "status": "done|partial|failed|waiting_human",
  "deal_id": "",
  "artifacts": [],
  "checklist_updates": [],
  "missing_fields": [],
  "next_tasks": []
}
```
