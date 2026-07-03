---
name: "cma-generator"
description: "Generate a comparative market analysis from MLS data and local comps. Use when the realtor asks to 'run a CMA', 'price this listing', 'pull comps for [address]', or an Admin-board deal reaches the CMA stage. Not the canonical engine — this delegates to the top-level cma workflow; call cma directly for a standalone CMA outside the Admin deal file. Every comp and stat cites its MLS number and date; human approval is required before client delivery."
category: "real-estate-marketing"
tags: ["real-estate", "pricing"]
access:
  entitlement: "real_estate_cma"
---

# CMA Generator

Use the `cma` workflow for full comparative market analysis: collect property facts, pull comparable listings from the configured MLS/CMA source, analyze condition and market stats, produce pricing guidance, render the report, and require human approval before client delivery.

## Admin-board test runs

If the realtor asks to test the full CMA workflow from the Admin board, use a real non-mock listing with a usable address or MLS number. If the initially selected test deal lacks property identity, choose another real Admin board deal with enough data and continue the full workflow, unless the user explicitly required that exact deal.

## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
