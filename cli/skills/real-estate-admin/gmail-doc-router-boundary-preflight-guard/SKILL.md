---
name: gmail-doc-router-boundary-preflight-guard
description: "Enforce Pacific admin-hours boundaries and preflight order for gmail-doc-router runs. Use whenever a scheduled signed-document/Envelope-completed cron run lands right at or past the 09:00-21:50 Pacific window and must decide in-hours preflight versus outside-hours [SILENT]. Not for the actual scan/dedupe pass — use gmail-doc-router-bounded-silent-preflight for that."
metadata:
  elevate:
    tags: [real-estate, email, documents, cron, guard]
---

# Gmail Doc Router Boundary + Preflight Guard

Use alongside `gmail-doc-router` for signed-document / Envelope completed cron jobs.

## Trigger

Load/apply this when running or reviewing `real-estate-admin/gmail-doc-router`, especially scheduled API cron sessions.

## Learned failure pattern

A cron run can make only the Pacific clock call, land just past the admin window (for example `21:56` when the window ends at `21:50`), and return `[SILENT]`.

The important reusable lesson is the boundary: the Gmail doc router runs only during the configured admin-hours window (**09:00 through 21:50 Pacific** by default). A time just past that boundary is outside-hours. Outside-hours silence is valid only when the first terminal command was clock-only and no Gmail/Admin discovery occurred.

## Hard control-flow rule

After the Pacific clock, branch by exact local HH:MM:

1. If `09:00 <= HH:MM <= 21:50`, this is in-hours. The literal next tool call must be first-class preflight, before any terminal/Gmail/Admin discovery:
   - `composio(action='status')`
   - `composio(action='accounts', toolkit='gmail')`
   - `deals_overview()` or `elevate_db(action='describe')`
2. If `21:51 <= HH:MM <= 23:59` or `00:00 <= HH:MM <= 08:59`, this is outside-hours. Do not scan Gmail, do not run `gws`, do not query Admin/idempotency, and return exactly `[SILENT]` unless a credential/blocker state was already surfaced by the invocation itself.

## Pre-final audit

Before final `[SILENT]`, check the actual transcript, not intention:

- Outside-hours valid no-op: `clock-only date` → `[SILENT]`.
- In-hours valid no-op: `clock-only date` → first-class preflight → live Gmail trigger search → inbound_seen coverage for all returned IDs → `[SILENT]`.
- Invalid in-hours no-op: `date` → `[SILENT]`, or `date` → terminal Gmail/Admin discovery before first-class preflight.

If an in-hours transcript skipped first-class preflight, do not return `[SILENT]`; self-repair with the preflight calls, then rerun live Gmail search and inbound_seen coverage.