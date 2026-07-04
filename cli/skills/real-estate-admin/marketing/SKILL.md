---
name: marketing
description: "Create launch assets, seller-facing drafts, and marketing tasks for a live listing. Use when a listing goes live or is approved for launch, or the realtor says 'market this listing', 'draft the launch posts', or 'make the just-listed assets'. Not for building the MLS package — use listing-build; not for the per-listing landing page — use marketing-landing. Requires address, MLS, price, live date, approved photos; never posts or sends directly."
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

## Buffer Notes

- Buffer's older wrapper fails with `Field "images" is not defined by type "AssetInput"` — use direct Buffer GraphQL assets: `[{"image": {"url": …}}]` with the required `schedulingType`/`mode` and `saveToDraft`.
- Superseded drafts get NEW post IDs and need a fresh approval — a repaired draft invalidates the old approval. If the user says they fixed the asset themselves, cancel any in-flight repair delegations.

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

## Fair housing & copy boundaries

- Fair housing is absolute: never write, imply, or optimize copy around protected classes (race, color, religion, sex, disability, familial status, national origin, or local additions such as age or source of income). Describe the property and its features, never the neighbors or "who this home is for." "Great for young families" fails; "4 beds, fenced yard, two blocks to the elementary school" passes.
- Targeting and scoring follow the same line: no audience filters, lead scores, or send/skip decisions keyed on protected classes or their proxies.
- Never lift another agent's listing copy, photos, or brand phrasing. Other listings are data (facts, price, days on market), not copy to reuse. Write from the property record and the owner's materials; when quoting a document such as an inspection, attribute it.
