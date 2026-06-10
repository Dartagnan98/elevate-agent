---
name: seller-update
description: Cron skill for active listing updates. Pulls showing feedback/activity, writes a digest to the deal, and creates a seller-update email draft. Never sends directly.
metadata:
  elevate:
    tags: [real-estate, seller-update, showing-feedback, cron]
    runtime:
      cron: true
      approval_required: true
---

# Seller Update

Use for active listings after the listing is live.

Pull showing feedback and listing activity from the configured showing platform/browser workflow. Match each listing to a deal with MLS number first, then address and contact verifiers. Write the digest to the deal record in the operational store and create a seller-update Gmail/Outlook draft.

Never send directly. If listing identity, MLS number, showing-platform access, or email draft access is missing, close as `waiting_human`.

## What This Covers

This is the consolidated active-listing update workflow. It covers ShowingTime-style feedback, seller-hub/listing stats, buyer-demand/prospecting signals, relevant seller message context, listing report PDFs, and seller email drafts.

Use one skill name: `seller-update`.

## Required Configuration

- Showing/feedback source, usually a browser workflow through the realtor's MLS or showing platform.
- Listing stats source, if available.
- Email draft account.
- Storage destination for seller-update PDFs.
- Admin Telegram lane for missing inputs and approvals.

## Phase Map

| Phase | Output |
| --- | --- |
| data | Fresh showing feedback, listing stats, demand signals, and message context. |
| report | Per-listing PDF/report plus JSON sidecar facts. |
| email | Gmail/Outlook seller-update drafts with report PDFs attached. |
| feedback | Optional pending-feedback requests and received feedback loopback. |

## Rules

- MLS number is the primary matcher for active listing updates. Address/contact verifiers are secondary.
- Never send seller emails directly. Create drafts and a human approval prompt.
- If seller email matching is weak, ask for confirmation before drafting.
- Pull only stale pieces for the day when possible; do not rerun slow browser steps if today's source file already exists.
- Use message history only for context and tone. Showing/stats facts must come from source data.

## Output Contract

```json
{
  "workflow": "seller-update",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "mls": "",
  "reports": [],
  "drafts": [],
  "feedback_pending": [],
  "checklist_updates": [],
  "risks": []
}
```
