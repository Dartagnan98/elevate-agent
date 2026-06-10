---
name: offer-review
description: Review accepted offer documents, extract key dates/terms, create human review tasks, and prepare the deal for subject removal.
metadata:
  elevate:
    tags: [real-estate, offer, documents]
    runtime:
      approval_required: true
---

# Offer Review

Use when an offer is accepted or accepted-offer documents arrive.

Match the deal, extract accepted offer date, subject removal date, deposit, completion, possession, inclusions/exclusions, buyer/lawyer info, and special terms. Attach extracted artifacts and create a human review task before moving forward.

Do not advance the phase until the extracted terms are reviewed.

## Required Inputs

- Accepted offer document or provider transaction record.
- Matched deal ID.
- Province package for required forms/tasks.
- Deposit handling rules and trust/deposit contact if configured.

## Extracted Fields

Capture these as deal facts in the operational store (via `admin_deal` / the result writer) and human-review fields:

- Accepted offer date.
- Subject removal date and all condition deadlines.
- Deposit amount, due date, and holder.
- Completion date.
- Possession date.
- Adjustment date if present.
- Inclusions and exclusions.
- Buyer, buyer agent, lawyer/notary, and brokerage contact details.
- Special terms, strata/doc deadlines, inspection clauses, financing clauses, sale-of-buyer-property clauses, and any unusual obligations.

## Rules

- Do not treat OCR as final. Create a human review prompt before the phase moves forward.
- Preserve page references or source snippets in the artifact summary when available.
- If dates conflict across documents, ask for human review and do not update important dates.

## Output Contract

```json
{
  "workflow": "offer-review",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "dates": {},
  "terms": {},
  "contacts": [],
  "artifacts": [],
  "review_required": true,
  "risks": []
}
```
