---
name: outreach-lanes
description: Run an outreach lane (new outreach, hot leads watcher, follow-ups). Pull leads from connected sources, pick a template, draft an approval-gated message, log the attempt for outcome learning.
version: 1.1.0
metadata:
  elevate:
    tags: [outreach, leads, sales, real-estate]
    related_skills: [outreach-send, gmail-doc-router, property-lookup]
steps:
  - id: pull_state
    tier: utility
    description: Enumerate profiles, threads, and signals from connected source connectors.
  - id: pick_template
    tier: utility
    description: Epsilon-greedy selection from active templates for the firing lane.
  - id: fill_template
    tier: draft
    description: Fill {first_name}, {city}, {topic}, {source}, {area}, {signal} from lead profile.
  - id: write_draft
    tier: draft
    description: Write the final message in the user's voice. Strip un-fillable variables cleanly.
  - id: orchestrate
    tier: orchestrator
    description: QC each draft. No CTA pivot, no invented facts, no emojis unless template has them.
  - id: log_attempt
    tier: utility
    description: Record attempt to outreach_db so outcome tracker can match the reply later.
---

# Outreach skill

You run one of three lanes for the user's lead desk. Each lane has its own job. You **never auto-send** — you draft, you log the attempt, and the human approves on `/leads`.

## Inputs

The cron prompt tells you which lane is firing:

- `new-outreach` — outbound to fresh leads from connected sources that have never been contacted.
- `hot-leads-watcher` — short, time-sensitive nudge to leads showing a live signal (just replied, just opened, just viewed, CRM stage moved).
- `follow-ups` — re-touch on threads that went cold (no inbound for 5+ days).

Default lane if not specified: `new-outreach`.

## Workflow

### 1. Pull state

Use the source connectors / inbox tools available in your runtime to enumerate:

- Profiles (cross-channel deduped contacts) and their thread counts.
- Threads with `outboundCount`, `inboundCount`, `direction`, `lastInboundAt`, `lastOutboundAt`, `heatLabel`.
- The CRM source — was outreach already logged for this contact?
- The SMS / email source — did a message actually go out?

A contact is **uncontacted** if `outboundCount === 0` across every connected channel for that profile.
A contact is **hot** if it has `heatLabel === "hot"` OR an inbound in the last 24h that we haven't replied to.
A thread is **cold** if `lastInboundAt` is more than 5 days ago and `outboundCount > 0`.

### 2. Filter to the lane's targets

| Lane | Target set |
|---|---|
| new-outreach | profiles with `outboundCount === 0` everywhere AND no draft already pending |
| hot-leads-watcher | threads matching the "hot" rule above with no draft pending |
| follow-ups | cold threads with no draft pending |

Cap each lane at 20 targets per run. More than that and the user can't approve it all.

#### 2a. First-run backfill iterator

When the lane cron has `backfill_pending: true` (set on the cron job at lane Start), you are in **backfill mode**. The eligible-target pool is the entire history, not just "new since last run." The same 20/run cap still applies — you process 20 per day until the pool is exhausted.

At end of run, report progress via `POST /api/cron/jobs/{job_id}/backfill/progress` with:

```json
{
  "queued_today": 17,
  "eligible_remaining": 312,
  "total_estimate": 410
}
```

The backend bumps `backfill_state.day` and clears `backfill_pending` automatically when `eligible_remaining` reaches 0. Subsequent runs use the incremental window (only new since last run), which is the default behavior when `backfill_pending` is false.

### 3. Pick a template

For each target, call:

```
outreach_templates(action="pick", lane="<lane-id>", channel="<sms|email|dm|any>")
```

It returns one template via epsilon-greedy selection (untried first, then best win-rate, occasional exploration). Only templates with `status='active'` are eligible — `pending_approval` and `archived` templates are excluded automatically. If `template` is `null`, there are no active templates for that lane — stop and tell the user to add or approve one in the Templates tab on `/leads`.

### 4. Fill the template

Templates use `{first_name}`, `{city}`, `{topic}`, `{source}`, `{area}`, `{signal}`. Fill them from the lead's profile / latest thread message. If a variable has nothing reasonable to fill in, rewrite the surrounding sentence so it still reads naturally — never leave `{first_name}` literal in the final draft, and never leave a sentence that obviously had its variable stripped.

Keep the template's voice. Don't rewrite the whole message. The point of templates is the user controls voice; you fill blanks.

### 5. Write the draft

Use the source-inbox draft tool to write the message as `task_type=message_draft` for that source + thread. The user approves it from `/leads`.

### 6. Record the attempt

```
outreach_templates(
  action="record_use",
  template_id="<id from step 3>",
  lane="<lane-id>",
  source_id="<source>",
  thread_id="<thread>",
  task_id="<draft task id>"
)
```

Save the returned `attemptId` somewhere durable (note in the draft body metadata or in `data/outreach/attempts/`) so the outcome tracker can find it later.

### 7. Wrap up

Tell the user, in one short paragraph: how many drafts were created, on which lane, what templates were used, anything skipped (no template, no fillable variables, etc.). Nothing more. The user reads detail on `/leads`.

## Rules

- **Never send.** You only draft. The user approves.
- **One draft per thread per run.** If a draft already exists for that thread, skip it.
- **No CTAs that don't fit.** If the lead just sent chitchat, the follow-up draft mirrors that — don't pivot to "free for a call?"
- **No inventing facts.** If the template references a feature, listing, or detail you can't verify in the lead's profile or latest thread, drop that line rather than fake it.
- **No emojis** unless the template body already has them.
- If `outreach_templates` returns nothing and the user has zero active templates for the lane, surface a Telegram-friendly note: "No active templates for `<lane>` — add or approve one in the Templates tab on /leads and re-run." Pending-approval templates do not count; the human has to approve them on the dashboard before they can be used.

## Failure modes

- If the SMS / email / CRM source is `blocked` or `not_configured`, don't draft for that channel. Note it in your wrap-up so the user knows to reconnect in Settings.
- If you hit a rate limit reading source records, save partial progress and exit cleanly.
- If a template fill produces a draft under 12 characters, scrap it — something went wrong with variable filling.

## Outcome tracking (next run)

Outcome recording is on a 7-day window. A separate scheduled job (or your next run) reads attempts older than 7 days and matches against inbound replies to update `outreach_templates(action="record_outcome", ...)`. Don't try to do this inline during a draft run.

## Template lifecycle (status field)

Templates carry a `status` field:

- `active` — eligible for `pick_template`. Counts toward `best`/`worst` rankings on `/leads` once it has 5+ uses.
- `pending_approval` — generated by the suggester (LLM or heuristic) and waiting for the human to Approve / Reject in the Templates tab. Not eligible for picking. Shown in a banner inside the lane's card on `/leads`.
- `archived` — rejected or retired. Not eligible.

The dashboard surfaces:

- **Best** template per lane (highest reply rate, ≥5 uses).
- **Weakest** template per lane (lowest reply rate, ≥5 uses).
- **Drift** alert if a template's last-30-day reply rate drops more than 30% below its all-time rate.
- **Suggest variant** button per lane — calls the suggester, which writes a new `pending_approval` template anchored to (a) the lane's current best template and (b) the user's voice from `~/.elevate/SOUL.md`. Falls back to a heuristic copy of the anchor if no Anthropic key is configured. Either way, the human approves before it ships.

You don't need to invoke the suggester from inside this skill. It runs on demand from `/leads`. Your job is still: pick from active, draft, log.
