# Heartbeat Checklist - EXECUTE EVERY STEP. SKIP NOTHING.

This runs on your heartbeat cron (every 4 hours). Execute every step in order. The dashboard monitors your compliance.

## Step 1 — Update heartbeat
Call agent_bus `update_heartbeat` with a one-sentence summary of the current deal focus. Do this first; without it you show as dead on the dashboard.

## Step 2 — Load state
Call agent_bus `get_goals` and `get_surface_config` for your surface, then `list_tasks` for pending and in_progress work. Claim the highest-priority pending task with `claim_task`. Update or complete anything stale.

## Step 3 — Walk the live deals
For each live deal: re-derive the timeline from the current contract dates, update the milestone checklist, and identify every condition or deadline inside the next 5 business days. Anything inside 48 hours with an open dependency is a risk item: create a task for it and include it in your activity post.

## Step 4 — Chase documents
For every outstanding document or signature, confirm it has an owner and a chase draft. Write any missing chase drafts now. Route each outbound draft through `create_approval` (or a task with `needs_approval`). Never send; approvals resolve on the dashboard.

## Step 5 — Closing runway
For any deal closing within 14 days, run the closing checklist: walkthrough scheduled, closing time/location confirmed with all parties, utility-transfer reminder drafted, wire-fraud warning drafted for the buyer, keys/access plan noted. Create tasks for gaps.

## Step 6 — Report and log
Post a concise risk summary with `post_activity` (deals at risk, deadlines inside 48h, blocked chases). Hand anything structural or ambiguous to Admin via handoff. Then write one memory entry with `write_memory` covering what moved and what you learned.

## Step 7 — Experiments
Call `list_cycles`. If a cycle is due this run (history count modulo its every_n_runs), run its experiment loop: `create_experiment` or `evaluate_experiment` per the cycle definition, honoring approval_required. Record the learning.

A heartbeat with no activity post and no memory write means you did nothing visible. Invisible work is wasted work.
