---
name: seller-package
description: Draft the pre-appointment seller package email after a listing appointment is booked, collect seller verifiers (name/email/phone/address), and on approved send promote the contact to the /admin listing kanban at stage 0 (CMA / Prospect). Never sends without human approval.
metadata:
  elevate:
    tags: [real-estate, seller, email, pre-listing, admin-entry]
    runtime:
      approval_required: true
      result_writer: admin-result-writer
      promotes_to_admin: true
      admin_side: listing
      admin_entry_stage: 0
---

# Seller Package

Use after a seller appointment is booked. This skill is the **entry point** for the /admin listing kanban — on approved send, the contact is promoted to listing-side stage 0 ("CMA / Prospect"). CMA work then runs against the new deal.

Draft the seller package email using the realtor profile, brokerage details, appointment context, property address, and any local/regional memory. Create a Gmail/Outlook draft or human approval task. Do not send directly.

## Position In Flow

```text
Lead in /leads (listing_active=1)
→ seller-package: collect verifiers + draft email
→ human approval
→ send seller package
→ close_to_admin(side='listing')   ← lands on /admin kanban stage 0
→ cma + listing-intake (stage 0 → 1)
→ MLC / listing paperwork (stage 2)
```

## Required Inputs

**Only these hard verifiers can block a draft** — they are what promote the contact to /admin:

- `contact_id` — the contact in /leads being closed into admin.
- `seller_names` — full legal name(s) of the seller(s).
- `seller_email` OR `seller_phone` — at least one reachable channel (both is better; either one is enough to draft).
- `listing_address` — property address (line + city + province + postal code if known).
- Realtor profile, brokerage, value proposition, and local proof points from memory/onboarding.
- Email account for draft creation.

**Optional — never block on these. Record if present, otherwise proceed and leave blank:**

- `appointment_date` — date/time of the listing appointment. A pre-CMA / pre-appointment package routinely has no appointment yet. Missing appointment_date is NOT a reason to park `waiting_human`; draft the package anyway.

Only return `status: "waiting_human"` when a hard verifier above (name, address, or a reachable email/phone) is genuinely missing AND cannot be enriched from Contacts/CRM/Gmail/iMessage. List only those in `requiredFields`. Never park a draft for a merely-nice-to-have field.

**Never fabricate a field to avoid parking.** Leaving an optional field (appointment date, etc.) blank is correct; inventing a value for it is a defect. Only write values that came from a real cited source (intake form, a CRM record you read, or the user). Never guess a name, email, phone, address, appointment, or date.

## Rules

- Draft only unless the human explicitly approves send.
- Do not promote to /admin until the seller package has been approved AND sent (or queued to send). Drafted-but-unsent does not move the contact off /leads.
- On approved send, the skill MUST:
  1. Update the contact verifiers on `contacts` (primary_email, primary_phone, display_name) using the collected inputs.
  2. Call `close_to_admin(contact_id, side='listing', listing_address=..., actor='seller-package', workflow='listing')` — this creates the listing deal at stage 0 and flips `contacts.stage='closed'` so the lane flags clear from /leads widgets.
  3. Record `deal_id` from the resulting deal on the run handoff.
- After admin promotion, attach the seller-package draft/sent artifact to the new deal_id through `admin-result-writer`.
- Do not create MLC/listing checklist completion from this step — that lives at stage 2.

## Output Contract

```json
{
  "workflow": "seller-package",
  "status": "drafted|waiting_human|sent|failed",
  "deal_id": "",
  "draft_id": "",
  "contact_id": "",
  "missing_fields": [],
  "approval_required": true,
  "admin_promoted": false,
  "admin_side": "listing",
  "admin_stage": 0
}
```

`admin_promoted` flips to `true` only after `close_to_admin` returns a deal_id. On `status: "sent"` without admin promotion, treat the run as incomplete and re-attempt the promotion before closing.

## Failure Modes

- **Missing verifier**: `status: "waiting_human"`, `requiredFields` lists which of seller_names/seller_email/seller_phone/listing_address are missing. Do not draft.
- **Contact already promoted**: if `contacts.stage='closed'` and a listing deal already exists for this contact, skip promotion, attach the new artifact to the existing deal, and return `admin_promoted: true` with the existing `deal_id`.
- **close_to_admin rejected (no verifier on contact row)**: this should not happen if required inputs are enforced; if it does, return `status: "failed"` with the rejection reason and do NOT mark the package as sent — the human has to fix the contact record first.
