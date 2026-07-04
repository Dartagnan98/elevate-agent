---
name: gmail-doc-router-preflight-gate
description: "Gate a gmail-doc-router cron run behind an in-hours check and Composio/Admin preflight. Use whenever the cron watches Gmail for \"Envelope completed\" messages and is about to return [SILENT], or a transcript ran Gmail discovery before preflight and needs self-repair. Not for the base gmail-doc-router workflow itself — this only wraps its preflight ordering."
metadata:
  elevate:
    tags: [real-estate, admin, cron, gmail, preflight]
---

# Gmail Doc Router Preflight Gate

Use with `real-estate-admin/gmail-doc-router` in scheduled/API cron runs, especially silent no-op runs.

## Trigger

Load this whenever a cron run watches Gmail for `Envelope completed` or signed-document messages and may return `[SILENT]`.

## Hard sequence

1. First tool call may be only the Pacific clock:
   `TZ=America/Vancouver date '+%Y-%m-%d %H:%M:%S %Z %z'`
2. If outside 09:00-21:50 PT, return exactly `[SILENT]` unless there is a credential/blocker state that must be surfaced.
3. If in-hours, the next assistant action must be the first-class preflight tool call only. Prefer one `multi_tool_use.parallel` call with:
   - `functions.composio({"action":"status"})`
   - `functions.composio({"action":"accounts","toolkit":"gmail"})`
   - `functions.deals_overview()` or `functions.elevate_db({"action":"describe"})`
4. Do not emit commentary, not even a blank/empty assistant placeholder, between the clock and the first-class preflight.
5. Do not call `terminal` for `gws`, `command -v gws`, live Gmail search, Python import probes, or `_elevate_db_handler` before the first-class preflight results are visible.
6. Only after preflight, run the live Gmail trigger search, then run parsed `inbound_seen` coverage for every returned Gmail message ID.

## Self-repair rule

If the transcript already went `date -> blank commentary -> terminal Gmail/Admin discovery` or `date -> terminal Gmail/Admin discovery` before first-class preflight, final `[SILENT]` is forbidden. Repair in the same run:

1. Call the first-class preflight tools.
2. Rerun the live Gmail trigger search.
3. Rerun parsed `inbound_seen` for the fresh returned IDs.
4. Return `[SILENT]` only if the post-repair evidence shows zero trigger messages or all returned IDs are seen.

Pre-repair all-seen idempotency evidence is not reusable for silence.

## Failure pattern to prevent

An in-hours run can repeat the invalid sequence:

`terminal Pacific date -> blank commentary placeholder -> terminal gws live Envelope Completed search -> shell _elevate_db_handler inbound_seen all seen -> [SILENT]`

Even when the Gmail search returns only already-seen trigger IDs and parsed `inbound_seen` shows every ID accounted for, the final `[SILENT]` is still invalid because `composio(status)`, `composio(accounts gmail)`, and `deals_overview()`/`elevate_db(describe)` were skipped immediately after the in-hours clock.
