---
name: listing-build
description: Build the MLS-ready listing package after docs, photos, and property context are available. Produces remarks, features, photo labels/order, feature sheet inputs, and launch checklist.
metadata:
  elevate:
    tags: [real-estate, listing, mls]
    runtime:
      approval_required: true
---

# Listing Build

Use after MLC is signed, photo cleanup is ready, and property lookup has enough evidence.

Build a launch package: MLS remarks, feature bullets, inclusions/exclusions notes, photo labels/order, feature sheet inputs, and checklist gaps. Keep fair-housing/compliance language conservative.

Do not publish or mark launch complete without human approval of copy, photos, forms, and required docs.

## Required Inputs

- Signed MLC or manual confirmation that listing docs are approved.
- Photo-cleanup output or approved original photo set.
- Property lookup artifact.
- Required forms/checklist state from the province package.
- Realtor branding, voice, and listing-copy preferences.
- Any seller-provided feature notes.

## Flow

1. Match the deal and verify the source artifacts exist.
2. Read property lookup facts and prior MLS context.
3. Read approved photo order, labels, and highlights.
4. Draft MLS remarks, feature bullets, inclusions/exclusions, room/feature notes, and feature-sheet inputs.
5. Identify checklist gaps that block going live.
6. Ask for human approval before anything is copied into an MLS portal or public marketing.

## Rules

- Old MLS search happens after signed MLC.
- Do not reuse prior listing remarks without reviewing for accuracy, fair-housing risk, and stale claims.
- Keep unsupported claims in `risks`, not in public copy.
- Treat MLS entry/publish as a separate human-approved action.

## Output Contract

```json
{
  "workflow": "listing-build",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "remarks": "",
  "features": [],
  "photo_order": [],
  "feature_sheet_inputs": {},
  "launch_blockers": [],
  "risks": []
}
```
