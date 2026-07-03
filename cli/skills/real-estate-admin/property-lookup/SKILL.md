---
name: property-lookup
description: "Gather prior MLS and property context after MLC is signed. Use when prepping for listing-build, or when the realtor says 'look up the property history', 'pull the old listing on [address]', or 'get the property facts'. Collects facts, old remarks, features, tax/assessment, and PID/legal, each with source and confidence. Unsupported claims never flow into public listing copy; uncertain MLS access or address identity asks for human review."
metadata:
  elevate:
    tags: [real-estate, mls, property-research]
---

# Property Lookup

Use after MLC is signed, before listing-build.

Use the configured MLS/board portal and property sources to gather prior listing context, property facts, tax/assessment notes, room/features context, and old MLS remarks. Keep source notes and confidence.

Do not copy unsupported claims into public listing copy. If MLS access or address identity is uncertain, ask for human review.

## Required Configuration

- Province and served market.
- MLS login or property-data provider.
- Assessment/public-record source for the province.
- Optional municipal/zoning source if configured.
- Storage destination for property reports.

Do not hardcode boards, cities, or portals. A realtor may work multiple boards; use the configured area sources and fall back to manual review when a source is unavailable.

## Flow

1. Match the deal and confirm signed MLC is present or manually confirmed.
2. Normalize the address, including unit/strata/rural formats.
3. Pull prior MLS/listing history when access is configured.
4. Pull assessment/property facts and legal/PID data where available.
5. Pull zoning/municipal facts only from configured or public sources.
6. Produce a property context artifact for `listing-build`.

## Output Contract

```json
{
  "status": "done|partial|waiting_human|failed",
  "address": "",
  "pid": "",
  "legal_description": "",
  "assessment_value": null,
  "zoning": "",
  "jurisdiction": "",
  "prior_mls": [],
  "report_path": "",
  "sources": [],
  "risks": []
}
```

Partial results are useful. If zoning fails but MLS and assessment succeed, write the handoff with a zoning risk instead of blocking the whole listing.

## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
