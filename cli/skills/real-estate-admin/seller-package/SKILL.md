---
name: seller-package
description: Draft the pre-appointment seller package email after a listing appointment is booked. Creates a draft or approval task; never sends without human approval.
metadata:
  elevate:
    tags: [real-estate, seller, email, pre-listing]
    runtime:
      approval_required: true
---

# Seller Package

Use after a seller appointment is booked and before the Admin listing pipeline starts.

Draft the seller package email using the realtor profile, brokerage details, appointment context, property address if known, and any local/regional memory. Create a Gmail/Outlook draft or a human approval task. Do not send directly.

If deal context exists, keep the `deal_id` and close with `admin-result-writer`. If key context is missing, request only the missing items needed to draft safely.

## Position In Flow

Seller package is before the Admin listing pipeline. The normal sequence is:

1. Seller appointment booked.
2. Draft/send seller package for approval.
3. Meeting happens.
4. Photos/CMA/listing intake context is collected as needed.
5. Listing intake/MLC begins when the seller is moving forward.

## Required Inputs

- Seller name and contact.
- Appointment date/time.
- Property address if known.
- Realtor profile, brokerage, value proposition, and local proof points from memory/onboarding.
- Email account for draft creation.

## Rules

- Draft only unless the human explicitly approves send.
- Do not create MLC/listing checklist completion from this step.
- If the seller package creates or links to a deal, record the `deal_id` but keep the pipeline before MLC until the seller proceeds.

## Output Contract

```json
{
  "workflow": "seller-package",
  "status": "drafted|waiting_human|sent|failed",
  "deal_id": "",
  "draft_id": "",
  "missing_fields": [],
  "approval_required": true
}
```
