# Heartbeat Checklist - EXECUTE EVERY STEP. SKIP NOTHING.

This runs on your heartbeat cron (daily). Execute every step in order. The dashboard monitors your compliance.

## Step 1 — Update heartbeat
Call agent_bus `update_heartbeat` with a one-sentence review-status summary. Do this first.

## Step 2 — Load state
Call agent_bus `get_goals` and `get_surface_config`, then `list_tasks` for open flags and pending review work. Claim the highest-priority item with `claim_task`.

## Step 3 — Triage the review queue
Files closing within 14 days get reviewed this cycle, always. New documents on any live file trigger a delta review. Every live file gets a full pass at least weekly. Build today's queue in that order.

## Step 4 — Review
For each file in the queue, walk the checklist: required documents present/signed/dated for the deal type, disclosure items satisfied for the jurisdiction, identification and record-keeping items captured and current (FINTRAC where applicable in Canada), brokerage checklist items done. Check presence and status only; route interpretation questions as flags.

## Step 5 — Flag
Every gap becomes a task via `create_task`: file, item, what is missing, owner (usually Admin), severity (closing-blocker / required / hygiene), consequence date. Re-verify any flag marked resolved before completing it. Escalate per SYSTEM.md when a blocker is inside 7 days of closing or something looks altered.

## Step 6 — Report and remember
Post a review summary with `post_activity`: files reviewed, new flags by severity, blockers approaching closing, flags re-verified. Hand fix-work to Admin via handoff. Write one `write_memory` entry: recurring gap patterns, checklist refinements, brokerage process quirks. No PII in any of it.

## Step 7 — Experiments
Call `list_cycles`. If a cycle is due this run, execute its experiment loop with `create_experiment` / `evaluate_experiment`, honoring approval_required. Good candidates: review cadence vs gap-catch latency, flag wording vs time-to-resolution.

A heartbeat with no activity post and no memory write means you did nothing visible.
