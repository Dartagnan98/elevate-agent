---
name: cma
description: "Run the full comparative market analysis workflow for a Canadian realtor, end to end. Use when the realtor asks for a 'CMA', 'market evaluation', 'pricing opinion', 'comp review', or a listing/price-reduction pricing package: collect MLS/property facts, compare active/sold comps, analyze photos and market stats, produce pricing guidance, render the report, and get human approval before client delivery. Not for just generating the comps set as one step inside an Admin deal run — use real-estate-admin/cma-generator; this is the whole client-facing workflow, that is the comps-generation sub-step."
metadata:
  elevate:
    tags: [real-estate, cma, pricing, report]
    runtime:
      approval_required: true
      result_writer: admin-result-writer
---

# CMA Workflow

Use this as the entrypoint for comparative market analysis work after the realtor asks for a CMA, market evaluation, pricing opinion, or comp review.

The skill is provider-neutral. It can use a configured MLS portal through Browser Use, a CMA provider, stored property records, uploaded photos, and local market-stat files. Do not assume a specific board, portal, or brokerage. Read the realtor's onboarding settings for MLS login URL, CMA source, report template, served province, and approval lane.

## Required Inputs

Ask for only the missing pieces:

- Subject property address.
- Property type and approximate size if MLS/assessment lookup cannot verify it.
- CMA purpose: pricing appointment, listing presentation, price reduction, buyer offer, or informal estimate.
- Desired report destination: draft only, PDF, email draft, or admin deal attachment.
- Any known property upgrades, condition notes, or seller goals.

## Phase Map

| Phase | Output |
| --- | --- |
| collect | Subject property facts, assessment/MLS facts, photos, and known listing history. |
| comps | Active, sold, expired, and competing listings with source evidence. |
| photo-analysis | Condition/readiness notes from uploaded or MLS photos. |
| pricing | Conservative range, likely list strategy, and risk notes. |
| pdf | Branded CMA PDF or report artifact. |
| audit | Check math, stale data, unsupported claims, missing evidence, and formatting. |

## Workflow Rules

- Preserve partial outputs. If MLS, assessment, photos, or market stats fail, write a partial handoff and ask for the missing source.
- Do not invent sold prices, square footage, legal descriptions, upgrades, zoning, or DOM.
- Use market stats when they are configured, but never block the CMA only because a monthly market file is missing.
- The deliverable should explain the price story. Do not expose internal scoring math as if it is a legal valuation.
- Create a human approval prompt before delivering a client-facing PDF or email draft.
- For Admin-board test runs, use a real non-mock listing with a usable address or MLS number. If the initially selected test deal lacks property identity, choose another real Admin board deal with enough data and continue the full workflow, unless the user explicitly required that exact deal.

## Comps & subject verification

- Portal address search can bind a prior SOLD instance as the subject while an active MLS exists — verify the live listing separately before answering "is it overpriced". A subject MLS from an old/cancelled/sold record is historical — never write it to the deal's current `mls_number`.
- Saved-search modal lingers in the DOM after clicking a row — verify the post-click `/ViewListings?listId=…` URL and the "N listings found" count before extracting rows.
- `PLAYWRIGHT_NO_CDP=1` rescues `page.goto: Frame has been detached` when driving a shared CDP tab.

## Photos & PDF rendering

- RealtyServer photo-ID mapping: on saved-search result pages the row `checkedId` (decimal) converts to the photo prefix by uppercase hex (20088700 → 0132877C), giving `images.realtyserver.com/photo_server.php?...name=<HEX>.LNN` URLs — verify each comp photo against address+MLS before use.
- Branded PDFs rendering all-black/blank in some preview/email clients = renderer compatibility. Ship a flattened copy: pdftoppm pages → images → `sips -s format pdf` → pdfunite; verify page 1 renders before delivery.

## Recovery & fresh pulls

- Deleted artifacts may survive in the macOS Mail attachment cache (`~/Library/Mail/**/Attachments`) when they were ever emailed — search there before re-pulling portals.
- Fresh-pull zero-results: bounded retries only (normalized civic, Ave/Avenue variant, historical MLS), then `waiting_human` — never silently substitute stale comps for a requested fresh pull.

## Handoff Contract

Every phase should leave a compact handoff so the next run can resume without reading chat history:

```json
{
  "workflow": "cma",
  "phase": "collect|comps|photo-analysis|pricing|pdf|audit",
  "status": "done|partial|failed|waiting_human",
  "address": "",
  "outputs": [],
  "facts": {},
  "decisions": [],
  "risks": [],
  "next": { "skill": "cma", "phase": "" }
}
```

When attached to an Admin deal, close through `admin-result-writer` with artifacts, checklist updates, and any next tasks. If it is chat-only CMA work, report the artifact path and approval question in the conversation.

## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
