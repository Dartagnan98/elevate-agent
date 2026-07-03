---
name: listing-build
description: "Build the MLS-ready listing package. Use when MLC is signed, photos are cleaned, and property lookup is done, or when the realtor says 'build the listing', 'write the MLS remarks', or 'prep [address] for MLS'. Produces remarks, feature bullets, photo labels and order, feature-sheet inputs, and the launch checklist. Not for post-launch marketing assets — use marketing. Fair-housing conservative; nothing publishes without human approval of copy, photos, and forms."
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

## Fair housing & copy boundaries

- Fair housing is absolute: never write, imply, or optimize copy around protected classes (race, color, religion, sex, disability, familial status, national origin, or local additions such as age or source of income). Describe the property and its features, never the neighbors or "who this home is for." "Great for young families" fails; "4 beds, fenced yard, two blocks to the elementary school" passes.
- Targeting and scoring follow the same line: no audience filters, lead scores, or send/skip decisions keyed on protected classes or their proxies.
- Never lift another agent's listing copy, photos, or brand phrasing. Other listings are data (facts, price, days on market), not copy to reuse. Write from the property record and the owner's materials; when quoting a document such as an inspection, attribute it.
