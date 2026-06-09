# Heartbeat Checklist - EXECUTE EVERY STEP. SKIP NOTHING.

This runs on your heartbeat cron (daily). Execute every step in order. The dashboard monitors your compliance.

## Step 1 — Update heartbeat
Call agent_bus `update_heartbeat` with a one-sentence program-status summary. Do this first.

## Step 2 — Load state
Call agent_bus `get_goals` and `get_surface_config`, then `list_tasks` for due touches and program work. Claim the highest-priority item with `claim_task`; complete or update anything stale.

## Step 3 — Anniversary and milestone lane
Scan the touch calendar for occasions inside the next 3 days. Draft each touch from the contact's real history (their home, their street, their timeline) and route it through `create_approval`. Where history is too thin to be personal, create a "needs detail" task for the realtor instead of drafting generic.

## Step 4 — Market updates and farm sequences
Advance any farm-sequence step due today and draft the monthly market update for any farm area whose window is open, sourcing numbers via handoff rather than inventing them. Every draft is approval-gated. Flag any sequence step that cannot run rather than skipping silently.

## Step 5 — Referral asks
Review recent closings, anniversaries, and warm replies for earned ask moments. Draft the ask naming the moment, gate it behind an approval. No earned moment, no ask.

## Step 6 — Handoffs and calendar hygiene
Hand any reply with buying/selling/referral intent to Outreach with full context. Verify every active contact still has a future touch with a date and a reason; repair gaps now. Flag date-tied drafts sitting unapproved before their occasion passes.

## Step 7 — Report and remember
Post a program-health summary with `post_activity`: touches drafted, asks queued, sequences advanced, gaps and stale approvals. Write one `write_memory` entry: which touch angles got warm replies, contact detail learned, farm response patterns.

## Step 8 — Experiments
Call `list_cycles`. If a cycle is due this run, execute its experiment loop with `create_experiment` / `evaluate_experiment`, honoring approval_required. Good candidates: touch angle vs warm-reply rate, farm cadence vs response, ask timing vs referrals landed.

A heartbeat with no activity post and no memory write means you did nothing visible.
