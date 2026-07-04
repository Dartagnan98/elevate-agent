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

## Portal lookup procedures

Hard-won behaviors for board MLS portals (Xposure-style). Apply them instead of rediscovering them:

- Login is board-IAM-mediated — a direct portal login can loop to the CREA/Auth0 board selector or show a stale sign-in landing even after a successful IAM login. Go through the configured board IdP, and if the search page shows hidden Sign In links, follow that href directly rather than assuming failure.
- Results extraction: DataTables extraction (`$("#DataTables_Table_0").DataTable().rows().data().toArray()`) beats the accessibility tree; useful row fields include `rets_mls_number`, `status`, `price_current`, `pid_number`, `id`, `xpid`.
- "Last time on market" = the row's Relist History (`/portal/<board>/RelistHistory?id=<listing_id>` directly if the icon stalls). Sale/transfer history = the row's AutoProp redirect (`/portal/<board>/AutopropRedirector?mlsNumber=<listing_id>`) → Summary Sheet (PID/legal/assessments/Sales History). Always report MLS history separately from AutoProp transfer history.
- Agent-level detail (docs tab included) requires `searchResultsCommon.showDetailXposure(rowIdx, …, xpid, listingId, true)` from the results context — the public `/XposurePublic/<xpid>` page hides authenticated docs. Docs live in `tr[id^=fileRow]` with `/portal/<board>/ShowDocument.HTML?id=<docId>&download=true` links; Chrome renames spaces to `+` in downloads.
- Unit searches: the page carries many duplicate HIDDEN address inputs — fill the VISIBLE `unit_number`/`street_number`/`street_name`, or `.first()` fills the wrong controls.
- Neighbour lookups: set status "Search All"; expired rows won't show sold price — continue to AutoProp. The direct listing URL `/portal/listings/<MLS#>` can throw Internal System Error even logged in — use the MLS Number search tab.
- Old subject sales can poison automatic ± price filters on comp pulls — set explicit price bounds when the subject record is a stale sale. Prior Sold/Expired/Cancelled listings are the recovery source for room measurements and (via the listing's top-middle Tax button) the last posted tax amount/year.

### myLTSA title orders

- Search-result owner names are masked (JO*, R*), so owner-hint matching can fail — when the PID search unambiguously returns the parcel, select the first REGISTERED row.
- After Purchase → Confirm, no browser download may fire — the PDF lands in the myLTSA inbox (open the item → attachment/Download All), or capture `application/pdf` response bodies. Verify the `%PDF` magic before use.
- On MFA screens prefer the visible Submit/Verify/Continue over generic `#kc-login`-style selectors.
- Treat saved auth-state JSONs as secrets.
- On relists, check existing storage and recent LTSA orders before paying for a new title.

## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
