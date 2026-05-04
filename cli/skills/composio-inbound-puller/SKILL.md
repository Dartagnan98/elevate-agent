---
name: composio-inbound-puller
description: Pull DMs / replies / messages from connected Composio toolkits (Gmail, Outlook, Slack, etc.) into the source-inbox so /leads can show inbound across every connected channel.
version: 1.0.0
metadata:
  elevate:
    tags: [composio, inbound, leads, polling]
    related_skills: [outreach-lanes, outreach-send]
steps:
  - id: capability_gate
    tier: utility
    description: Read composio_capabilities.json. Skip toolkits whose inbound.supported is False.
  - id: enumerate_accounts
    tier: utility
    description: Paginate /api/v3/connected_accounts for the toolkit. Skip if zero accounts.
  - id: pull_pages
    tier: utility
    description: Call execute_tool(slug=inbound.slug) per account, page until next_cursor empties or max_pages hit.
  - id: dedupe_and_persist
    tier: utility
    description: Dedupe by provider_message_id, normalize to source-inbox shape, append to messages.jsonl.
  - id: persist_cursor
    tier: utility
    description: Bump per-account cursor in cursors.json only after the page is durably written.
---

# Composio inbound puller

You are the inbound twin of the Composio outbound sender. Your job is to bring messages
from every user-connected Composio toolkit into the local source-inbox so the rest of
`/leads` (autopilot lanes, hot-leads watcher, follow-ups) can see them as plain
inbound records — same shape it already understands.

You **never run as an LLM-driven skill at runtime.** You exist as the documented
contract for the background ticker in `gateway/run.py` (which calls
`composio_inbound.pull_all_supported()` every 10 minutes) and as the surface the
user inspects on `/leads → Settings → Inbound`. This SKILL.md is the source of
truth for what the puller does so anyone (human or LLM) reading the codebase
understands the behavior without reading Python.

## Capability matrix is the gate

`elevate_cli/composio_capabilities.json` is the single source of truth for which
toolkits we attempt to poll. Each toolkit entry has:

```jsonc
{
  "inbound": {
    "supported": true | false,
    "slug": "GMAIL_FETCH_EMAILS",
    "required_args": ["query"],
    "verification": "verified_live" | "documented_unverified" | "unverified_external_claim" | "unsupported"
  }
}
```

Rules:

- `inbound.supported === false` → **skip silently with a banner reason**. Never silently fail.
- `verification === "unverified_external_claim"` or `"unsupported"` → **do not enable** until a live `execute_tool` round-trip passes against a real account.
- `verification === "documented_unverified"` → safe to poll once the user has connected an account; first successful tick promotes it informally to verified-in-this-deployment (the matrix file isn't auto-bumped; the user updates `verification` after watching one tick land).
- The UI on `/leads → Settings → Inbound` MUST surface the verification level next to each toolkit so the user knows what's known vs. claimed.

`rate_limit_budget.fail_closed_when_unknown: true` — if a toolkit isn't in the
matrix at all, treat it as unsupported. Don't guess.

## Per-toolkit, per-account behavior

For each connected account on a supported toolkit:

1. Load the per-account cursor from `data/sources/composio-<toolkit>/cursors.json`.
2. Call `execute_tool(inbound.slug, account_id, {limit: 50, cursor: <cursor or omitted>})`.
3. Pull up to `max_pages` pages (default 5) — `composio_inbound.pull_toolkit()` caps this so a single tick can't pin the gateway thread.
4. For each item, normalize via `_normalize()` to:

```json
{
  "provider_message_id": "<stable id>",
  "id": "<same id, mirrored>",
  "thread_id": "<thread or fallback to message id>",
  "direction": "inbound",
  "from": "<sender>",
  "body": "<text/snippet>",
  "ts": "<ISO timestamp>",
  "toolkit": "<toolkit slug>",
  "connected_account_id": "<acct id>",
  "raw": { ...original payload },
  "ingested_at": "<ISO now>"
}
```

5. Dedupe against `messages.jsonl` (last 10k messages) by `provider_message_id`. Skip already-seen.
6. Append new records, then bump the cursor.

Cursor persistence is **append-then-cursor-bump**, never the reverse. A crash mid-tick
leaves the next tick re-pulling the last page (it dedups), not skipping over messages.

## Default cadence

10 minutes per `composio_capabilities.json:rate_limit_budget.default_poll_interval_minutes`.
The gateway ticker handles this — `INBOUND_TICK_EVERY = 10` at the 60s base interval.

`max_users_per_toolkit_at_default_interval: 50` — once any toolkit crosses 50 connected
accounts in this deployment, we either bump the interval or shard accounts across ticks.
Don't do this preemptively; the matrix says when.

## Source ID convention

Every Composio toolkit gets its own source-inbox source id of the shape
`composio-<toolkit_slug>`. The directory layout is:

```
data/sources/composio-gmail/
  messages.jsonl
  cursors.json
data/sources/composio-slack/
  messages.jsonl
  cursors.json
```

Lane skills (`outreach-lanes`) treat these like any other source — `outboundCount` /
`inboundCount` math just works once the records land in the standard shape.

## Failure modes

- `execute_tool` returns `ok: False` with HTTP 408/429/5xx → log warning, **stop iteration for that account**, leave cursor unchanged. The 10-minute cadence retries naturally.
- Other 4xx → same: log + stop. Don't burn cursor; don't mark anything failed.
- No connected accounts for the toolkit → return `{ok: True, skipped: True, reason: "no connected accounts"}`. The wizard tells the user to connect one.
- `COMPOSIO_API_KEY` missing → upstream client returns `{ok: False, error: "COMPOSIO_API_KEY is not configured"}` and the puller skips cleanly. The wizard tells the user to set it.

## What this skill is NOT

- **Not a webhook receiver.** Composio doesn't promise webhook coverage across all toolkits. Polling-only by design (Phase 5 plan rule).
- **Not a sender.** That's `outreach-send` + `composio_dispatcher()` in `sender.py`. The execute_tool chokepoint is the same; the direction is the only thing different.
- **Not LLM-mediated.** No tier-routed step actually calls a model. The `tier: utility` declarations exist so the runtime can attribute compute and so the wizard's readiness gate has something to grade. The actual code path is Python only.

## Verification ladder

Before flipping any new toolkit's `inbound.supported` from `false` → `true` in the matrix:

1. User connects a real account for that toolkit.
2. Run `python -c "from elevate_cli import composio_inbound; print(composio_inbound.pull_toolkit('<slug>'))"` once by hand.
3. Confirm `messages.jsonl` got at least one record with a non-empty `provider_message_id` and `body`.
4. Bump `verification` from `unverified_external_claim` (or `documented_unverified`) to `verified_live` and commit `composio_capabilities.json`.

This is the only safe path. Don't promote a toolkit on the strength of docs alone.
