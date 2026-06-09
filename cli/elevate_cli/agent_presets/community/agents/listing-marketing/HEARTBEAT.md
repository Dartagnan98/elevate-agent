# Heartbeat Checklist - EXECUTE EVERY STEP. SKIP NOTHING.

This runs on your heartbeat cron (every 6 hours). Execute every step in order. The dashboard monitors your compliance.

## Step 1 — Update heartbeat
Call agent_bus `update_heartbeat` with a one-sentence summary of launch status. Do this first.

## Step 2 — Load state
Call agent_bus `get_goals` and `get_surface_config`, then `list_tasks` for pending and in_progress work. Claim the highest-priority item with `claim_task`; complete or update anything stale.

## Step 3 — Advance every launch checklist
For each active or upcoming listing, walk its launch checklist: facts gathered, MLS copy drafted, photos scheduled/delivered, staging coordinated, listing live, promo prepared. Create tasks with owners and dates for every gap. A new listing without a checklist gets one now.

## Step 4 — Draft copy and promo
Write or refine MLS remarks, feature copy, and open-house promo drafts that are due. Verify every factual claim against the listing file. Route every public-facing or vendor-facing draft through `create_approval`; never publish or send.

## Step 5 — Chase coordination
Check photo, staging, and measurement tasks for slippage. Draft chase messages where a vendor or date is slipping and gate them behind approvals. Flag any launch date at risk.

## Step 6 — Report and hand off
Post a launch-status summary with `post_activity` (per listing: stage, blockers, next milestone). Hand finished assets and recurring creative needs to Marketing, social angles to Social Media, cross-domain items to the Executive Assistant via handoff. Write one `write_memory` entry with what you learned about this market's launch patterns.

## Step 7 — Experiments
Call `list_cycles`. If a cycle is due this run, execute its experiment loop with `create_experiment` / `evaluate_experiment`, honoring approval_required. Good candidates: copy angles vs showing requests, promo timing vs open-house turnout.

A heartbeat with no activity post and no memory write means you did nothing visible.
