---
name: "cma-generator"
description: "Generate a comparative market analysis from MLS + local comps."
category: "real-estate-marketing"
tags: ["real-estate", "pricing"]
access:
  entitlement: "real_estate_cma"
---

# CMA Generator

Use the `cma` workflow for full comparative market analysis: collect property facts, pull comparable listings from the configured MLS/CMA source, analyze condition and market stats, produce pricing guidance, render the report, and require human approval before client delivery.

## Admin-board test runs

If the realtor asks to test the full CMA workflow from the Admin board, use a real non-mock listing with a usable address or MLS number. If the initially selected test deal lacks property identity, choose another real Admin board deal with enough data and continue the full workflow, unless the user explicitly required that exact deal.
