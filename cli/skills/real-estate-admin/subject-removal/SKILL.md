---
name: subject-removal
description: "Handle subject-removal admin work: docs, deposit receipt, lawyer info, sold rider/sign tasks, title charge checks, and human confirmation before phase completion."
metadata:
  elevate:
    tags: [real-estate, subjects, closing]
    runtime:
      approval_required: true
---

# Subject Removal

Use after an accepted offer is active and subject-removal work starts.

Prepare subject-removal document tasks, deposit receipt checks, lawyer info, sold rider/sign needs, and title charge review notes. Keep important dates on the deal record in the operational store.

Human confirmation is required before the subject-removal phase is marked complete.

## Required Inputs

- Reviewed accepted-offer facts.
- Subject/condition list and deadlines.
- Required subject-removal forms for the province package.
- Deposit status and receipt when applicable.
- Lawyer/notary info.
- Sold rider/signage requirements.
- Title charge or compliance checks when required.

## Flow

1. Confirm accepted-offer review is complete.
2. Build the subject-removal checklist from deal conditions and province package.
3. Prepare document tasks and signing tasks.
4. Track deposit receipt and lawyer info.
5. Create human prompts for approvals and missing conditions.
6. Mark subject-removal phase complete only after human confirmation.

## Rules

- Date deadlines are move-forward signals. Keep them in the deal's important dates in the operational store.
- If a condition is waived/removed manually, record the human confirmation as evidence.
- Do not mark the deal sold/firm unless the required subject-removal evidence exists or the human explicitly confirms.

## Output Contract

```json
{
  "workflow": "subject-removal",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "conditions": [],
  "dates": {},
  "documents": [],
  "deposit_status": "",
  "review_required": true,
  "risks": []
}
```
