---
name: gmail-doc-router-api-preflight-guard
description: "Force real function preflight before any shell fallback in Gmail Doc Router cron runs. Use it for scheduled runs watching \"Envelope Completed\" mail so in-hours ticks cannot skip straight to terminal/gws."
metadata:
  elevate:
    tags: [real-estate, admin, gmail, cron, preflight]
---

# Gmail Doc Router API Preflight Guard

Use alongside `real-estate-admin/gmail-doc-router` for scheduled/API cron runs that watch Gmail `Envelope Completed` messages.

## Trigger

Load this guard when running or reviewing `gmail-doc-router` in an API/focused cron session where first-class function tools may be loaded, especially `functions.composio`, `functions.deals_overview`, or `functions.elevate_db`.

## Hard transcript rule

After the Pacific-hours clock check, if the time is inside 09:00 through 21:50 Pacific, the **next assistant action must be actual first-class function preflight**, not commentary and not terminal.

Valid next action, preferably in one parallel call:

1. `functions.composio({"action":"status"})`
2. `functions.composio({"action":"accounts","toolkit":"gmail"})`
3. `functions.deals_overview()` or `functions.elevate_db({"action":"describe"})`

Only after those function tool results appear may the run call terminal for `gws`, Gmail REST, command discovery, Python imports, `_elevate_db_handler`, or any shell fallback.

## Learned failure pattern

A run can check the Pacific clock, then emit a blank commentary placeholder and use `terminal` to import/call `tools.composio_tool.composio_tool` plus `_elevate_db_handler` as a shell fallback before Gmail search. It then runs live `gws`, verifies every trigger ID is already present in `inbound_seen`, and returns `[SILENT]`.

The all-seen idempotency evidence can be correct, but the transcript is still invalid because the actual loaded first-class function tools were skipped. Shell-importing the same backend helpers does **not** satisfy the first-class preflight requirement when the function tools are available.

## Self-repair

If any of these happen after an in-hours clock and before first-class function preflight:

- blank/empty assistant commentary placeholder
- `terminal` command discovery
- `terminal` `gws` Gmail search
- `terminal` Python import of Composio/Admin helper modules
- `_elevate_db_handler` shell fallback
- browser/CDP Gmail inspection

then final `[SILENT]` is forbidden until the run self-repairs:

1. Call the first-class function tools directly: `composio(status)`, `composio(accounts gmail)`, and `deals_overview()` or `elevate_db(describe)`.
2. Rerun the live Gmail `Envelope Completed` trigger search.
3. Rerun parsed `inbound_seen` coverage for the fresh returned message IDs.
4. Return exactly `[SILENT]` only if the live search is empty or every returned ID is seen and there are no blockers.

## Minimal valid no-op sequence

1. `terminal`: `TZ=America/Vancouver date ...` only.
2. First-class preflight function calls, directly or through `multi_tool_use.parallel`.
3. `terminal`: live Gmail `gws gmail users messages list` search for `subject:"Envelope Completed" newer_than:7d has:attachment`.
4. Approved Postgres/elevate data-layer `inbound_seen` check for every returned Gmail message ID.
5. Final exactly `[SILENT]` only when every returned ID is already processed or the search returns zero messages.
