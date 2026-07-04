---
name: gmail-doc-router-preflight-order-guard
description: "Enforce first-class preflight before Gmail search in gmail-doc-router cron ticks. Use when a cron run checks Gmail for signed-document completion emails and may end in a silent no-op, or a prior run skipped preflight. Not for parsing scan-wrapper JSON output — use gmail-doc-router-scan-wrapper-json-guard instead."
metadata:
  elevate:
    tags: [real-estate, email, cron, documents, preflight]
---

# Gmail Doc Router Preflight Order Guard

Use with `real-estate-admin/gmail-doc-router` in scheduled/API cron runs, especially when the final output may be exactly `[SILENT]`.

## Trigger

Load/apply this guard when the run is checking the realtor's Gmail for `Envelope completed` document-completion emails and first-class tools like `composio`, `deals_overview`, or `elevate_db` are loaded.

## Mandatory sequence

1. First call may be `terminal` for the local clock only:
   ```bash
   TZ=America/Vancouver date '+%Y-%m-%d %H:%M:%S %Z (%u)'
   ```
   Do not combine the date with `pwd`, `command -v gws`, Gmail searches, import probes, or database checks.
2. If the time is outside admin hours, final may be exactly `[SILENT]` unless a credential/blocker must be surfaced.
3. If the time is in-hours, the **very next assistant action** must be first-class preflight only, preferably a `multi_tool_use.parallel` call with:
   - `functions.composio({"action":"status"})`
   - `functions.composio({"action":"accounts","toolkit":"gmail"})`
   - `functions.deals_overview()` or `functions.elevate_db({"action":"describe"})`
4. Only after those first-class results are visible may the run call `terminal` for `gws`, live Gmail search, shell `_elevate_db_handler`, or runtime discovery.
5. Valid no-op evidence for final `[SILENT]` is:
   - clock in-hours,
   - first-class preflight after the clock and before Gmail/Admin terminal discovery,
   - live Gmail trigger search, and
   - parsed `inbound_seen` coverage proving every returned Gmail message ID is already seen, or a live trigger search returning zero messages.

## Self-repair rule

If the transcript already went `date -> blank commentary -> terminal gws live search -> shell inbound_seen all seen`, or `date -> terminal gws search -> inbound_seen`, then final `[SILENT]` is invalid. Self-repair in the same run:

1. Call the first-class preflight tools listed above.
2. Rerun the live Gmail trigger search.
3. Rerun parsed `inbound_seen` coverage for the fresh returned IDs.
4. Only then return `[SILENT]` if all IDs are seen or the live search is empty.

Pre-repair all-seen evidence is not reusable for silence.

## Why this guard exists

Cron runs against this router have repeatedly followed an invalid no-op order: run the clock check, skip straight to a live Gmail search, find that every returned message ID is already in `inbound_seen`, then return `[SILENT]`. The Gmail/idempotency evidence in that path is correct, but the silent result is still invalid whenever the mandatory first-class preflight (`composio(status)`, `composio(accounts, toolkit='gmail')`, `deals_overview()`/`elevate_db(describe)`) was skipped immediately after the clock. This is the recurring failure pattern this guard exists to close: after the in-hours clock, treat first-class preflight as a literal next-tool constraint, not general guidance. If the main `gmail-doc-router` skill body is too large to patch directly, update this guard skill instead and keep it loaded/attached alongside the router cron job.

## Final audit before `[SILENT]`

Before returning exactly `[SILENT]`, scan the actual transcript, not the intended plan. If first-class preflight results do not appear after the clock and before Gmail/Admin terminal discovery, continue with self-repair instead of finalizing.
