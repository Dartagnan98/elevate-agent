---
name: cma
description: CMA workflow router for Canadian realtors. Collects MLS/property data, compares active/sold comps, analyzes photos and market stats, produces pricing guidance, renders the CMA report, and requires human approval before client delivery.
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
