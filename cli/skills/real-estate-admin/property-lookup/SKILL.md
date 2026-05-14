---
name: property-lookup
description: Look up prior MLS/property context after MLC is signed. Feeds listing-build with property facts, prior remarks, features, and safe verification notes.
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
