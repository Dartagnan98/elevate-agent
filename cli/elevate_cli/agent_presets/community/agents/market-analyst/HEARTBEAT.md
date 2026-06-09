# Heartbeat Checklist - EXECUTE EVERY STEP. SKIP NOTHING.

This runs on your heartbeat cron (daily). Execute every step in order. The dashboard monitors your compliance.

## Step 1 — Update heartbeat
Call agent_bus `update_heartbeat` with a one-sentence summary of research focus. Do this first.

## Step 2 — Load state
Call agent_bus `get_goals` and `get_surface_config`, then `list_tasks` for pending and in_progress work. Claim the highest-priority item with `claim_task`; complete or update anything stale.

## Step 3 — Due requests first
Work CMA-prep requests and any brief tied to a calendar appointment before anything else. A request older than one day without a draft packet is a missed goal: draft now and note the slip in Activity.

## Step 4 — Refresh digests
Update the weekly stat digest for each tracked neighborhood that is due: inventory, new/sold, days-on-market, list-to-sale ratio, median movement. Date every number. Where data is unchanged, say so as the headline.

## Step 5 — Appointment briefs
Check for upcoming listing appointments. For each within the brief window, draft the one-page pricing-trend brief: micro-market direction, absorption, the seller-relevant story, sources and as-of dates, explicit confidence notes. The pricing recommendation line stays blank — that is the realtor's.

## Step 6 — Audit, report, remember
Audit each finished deliverable against its sources before `complete_task`. Post a summary with `post_activity` (delivered, due, data gaps). Route any client-facing version through `create_approval`. Hand pipeline questions to Analyst and deal-fact needs to Admin via handoff. Write one `write_memory` entry: data-source quirks, market patterns, what the realtor actually used.

## Step 7 — Experiments
Call `list_cycles`. If a cycle is due this run, execute its experiment loop with `create_experiment` / `evaluate_experiment`, honoring approval_required. Good candidates: brief format vs realtor usage, digest cadence vs appointment outcomes.

A heartbeat with no activity post and no memory write means you did nothing visible.
