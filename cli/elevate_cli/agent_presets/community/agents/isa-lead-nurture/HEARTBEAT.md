# Heartbeat Checklist - EXECUTE EVERY STEP. SKIP NOTHING.

This runs on your heartbeat cron (every 2 hours during the day). Execute every step in order. The dashboard monitors your compliance.

## Step 1 — Update heartbeat
Call agent_bus `update_heartbeat` with a one-sentence lane summary. Do this first.

## Step 2 — Load state
Call agent_bus `get_goals` and `get_surface_config` for the leads surface, then `list_tasks` for pending and in_progress work. Claim the highest-priority item with `claim_task`; complete or update anything stale.

## Step 3 — New-lead lane
Find leads with no response draft. For each, read their inquiry and context, then write a personalized first-response draft that answers what they asked. Route it through `create_approval`. Create the lead's cadence task with a next-touch date.

## Step 4 — Cadence lane
Find leads whose next touch is due. Draft each touch with something useful in it (answer, listing, market fact), gate it behind an approval, and set the next touch date. Rest or re-angle any lead that has ignored 3 consecutive touches.

## Step 5 — Hot lane
Review every hot lead: new activity, replies, timing signals. Draft the advancing touch where warranted. Any lead that replied, qualified, or asked for the realtor hands off to Outreach now with full context.

## Step 6 — Re-engagement (weekly)
Once per week, batch-draft revival touches for leads quiet 30+ days, anchored to something current. Gate the batch behind approvals and note it in Activity.

## Step 7 — Report and remember
Post a lane-health summary with `post_activity` (new drafted, touches due/done, hot movements, approvals waiting too long). Write one `write_memory` entry: reply patterns, angles that worked, timing learnings.

## Step 8 — Experiments
Call `list_cycles`. If a cycle is due this run, execute its experiment loop with `create_experiment` / `evaluate_experiment`, honoring approval_required. Good candidates: first-touch angle vs reply rate, cadence spacing vs revival rate.

A heartbeat with no activity post and no memory write means you did nothing visible.
