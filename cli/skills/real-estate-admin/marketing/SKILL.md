---
name: marketing
description: Listing marketing workflow for live listings. Creates launch assets, seller-facing drafts, and marketing tasks only after listing-live inputs exist.
metadata:
  elevate:
    tags: [real-estate, marketing, listing-live]
    runtime:
      approval_required: true
---

# Listing Marketing

Use once the listing is live or approved for launch.

Require address, MLS number, live date, price, approved photos, and open-house/signage inputs before creating assets. Create drafts/tasks for social posts, email blasts, listing updates, and seller communications.

Never post or send directly. Missing launch inputs should produce `waiting_human` with the exact required fields.

## Required Inputs

- Property address.
- MLS number.
- Listing price.
- Live date or approved launch date.
- Approved main exterior photo and at least two supporting photos.
- Open-house details or confirmation that there is no open house.
- Sign/order and coming-soon timing when applicable.
- Approved listing copy or listing-build artifact.
- Social/email scheduler configuration.

## Phase Map

| Phase | Output | Human Checkpoint |
| --- | --- | --- |
| inputs | Validated listing-launch inputs. | Missing photos, price, dates, MLS, open-house decision. |
| render | Social/email graphics or asset tasks. | Blank/incorrect image review. |
| copy | Captions, email copy, hashtags, and launch notes. | Copy approval before scheduling. |
| social | Scheduler drafts or tasks. | Required before publish. |
| email | Gmail/ESP drafts. | Required before send. |
| log | Launch summary attached to the deal. | Remaining manual follow-ups. |

## Rules

- This skill starts after listing-live readiness, not before MLC/signing/photo approval.
- Never publish, schedule, or send without human approval.
- If photos or copy are not approved, create tasks instead of launch assets.
- Close with `admin-result-writer` so the Admin board reflects drafts, artifacts, and launch gaps.

## Output Contract

```json
{
  "workflow": "marketing",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "graphics": [],
  "copy": [],
  "social_drafts": [],
  "email_drafts": [],
  "missing_inputs": [],
  "risks": []
}
```
