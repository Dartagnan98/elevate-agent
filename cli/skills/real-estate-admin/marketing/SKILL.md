---
name: marketing
description: Listing marketing workflow for live listings. Creates launch assets, seller-facing drafts, and marketing tasks only after listing-live inputs exist.
metadata:
  elevate:
    tags: [real-estate, marketing, listing-live]
    runtime:
      approval_required: true
---

## Listing stage trigger contract — September 9, 2026

For BC listing stage decisions, read the [shared stage trigger contract](../admin-result-writer/references/listing-stage-triggers.md). It supersedes older manual-only and workflow-completion advancement rules for the named triggers. Entry into a stage starts its workflow; completing work alone does not advance the card. Preserve buyer-stage behavior. Use the runtime invocation section for the supported trigger tool/CLI; distinguish queued workflows from completed work.


# Listing Marketing

Preserve explicit approvals already supplied in chat or with launch timing. “Send the coming-soons now; landing approved; video later” means execute the non-video launch and leave only video pending. Use the recorded-authorization handoff instead of creating another final-approval loop.

For Marketing Go draft review and approved continuation, read [references/review-approval.md](references/review-approval.md). Prepare the complete package before the ACTION NEEDED publishing approval. Register every final asset with the originating chat preview bar. Resume approved artifacts without rebuilding them.

Use once the listing is live or approved for launch.

Require address, MLS number, live date, price, approved photos, and open-house/signage inputs before creating assets. Create drafts/tasks for social posts, email blasts, listing updates, and seller communications.

Prepare first; publish or schedule only through the explicitly approved review continuation. Missing launch inputs should produce `waiting_human` with the exact required fields after independent preparation is complete. Route per-listing landing-page implementation to `marketing-landing` and retain its output in the same Marketing Go package.

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
