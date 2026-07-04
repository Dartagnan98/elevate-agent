---
name: gmail-doc-router-preflight-guard
description: "Enforce Composio/Admin preflight before terminal Gmail discovery in a doc-router run. Use whenever a scheduled cron run checks Gmail for \"Envelope completed\" messages, right before returning [SILENT] for an already-seen trigger ID, or to self-repair a transcript that skipped preflight. Companion to gmail-doc-router-preflight-gate — both guard the same ordering."
metadata:
  elevate:
    tags: [real-estate, admin, gmail, cron, preflight]
---

# Gmail Doc Router Preflight Guard

Use this with `real-estate-admin/gmail-doc-router` in API/focused cron sessions, especially when returning `[SILENT]` for already-seen Gmail trigger messages.

## Trigger

Load/apply this guard when the task is a scheduled Gmail document router run and the run checks Gmail for `Envelope completed` document-completion messages.

## Mandatory sequence

1. First tool call may be only the Pacific clock guard:
   `TZ=America/Vancouver date '+%Y-%m-%d %H:%M:%S %Z %u'`
2. If the clock is inside 9:00 AM through 9:50 PM Pacific, the very next assistant action must be first-class preflight, not commentary and not terminal Gmail/Admin discovery.
3. Run the preflight with available first-class tools:
   - `composio(action='status')`
   - `composio(action='accounts', toolkit='gmail')`
   - `deals_overview()` or `elevate_db(action='describe')`
4. Only after those results are visible may you run terminal/gws Gmail searches, shell import probes, `_elevate_db_handler`, browser/CDP Gmail inspection, or runtime blocker classification.
5. Then run the live Gmail trigger search and `inbound_seen` coverage check for every returned Gmail message ID.
6. Return exactly `[SILENT]` only if the transcript shows the valid order above and either the live search returned zero messages or every returned message ID is already in `inbound_seen`.

## Hard failure pattern to catch

The following transcript is invalid even if all IDs are already seen:

`date -> blank commentary placeholder -> terminal live Gmail Envelope Completed search -> shell _elevate_db_handler inbound_seen all seen -> [SILENT]`

This failure has repeated across many reviewed runs: the live search returns already-seen IDs and parsed `inbound_seen` shows every ID accounted for, but `[SILENT]` is still invalid because first-class preflight was skipped immediately after the in-hours clock. Treat any repeat of this pattern as an immediate self-repair trigger, not as more evidence that the all-seen shortcut is safe.

## Self-repair

If any terminal Gmail/Admin discovery, browser/CDP Gmail inspection, `command -v gws`, shell import probe, or `_elevate_db_handler` call happens after the in-hours clock and before first-class preflight:

1. Do not finalize `[SILENT]`.
2. Immediately call the first-class preflight tools listed above.
3. Rerun the live Gmail trigger search.
4. Rerun parsed `inbound_seen` coverage for the returned IDs. If shell fallback returns a JSON string, parse it with `json.loads` before reading `rows`.
5. Only then decide final output.

## Pitfalls

- A blank or empty assistant/commentary turn after the clock is not harmless. Treat it as a failure state requiring repair.
- A successful `gws` search does not satisfy Composio/Admin preflight.
- Shell `_elevate_db_handler` idempotency is a fallback for `inbound_seen`, not a substitute for first-class Admin preflight.
- A CDP-visible Gmail tab is supplemental evidence only, not proof that first-class tools are unavailable.
- Before any runtime-access blocker report, call loaded first-class tools if present.
