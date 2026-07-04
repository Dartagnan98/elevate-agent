---
name: analyst-liveness-usage-pulse
description: "Run the narrow Analyst heartbeat that checks agent liveness and usage/cost signals only. Use when a scheduled Analyst pulse needs to check heartbeat staleness (5h owner-nudge, 8h EA coordinator-watch) and Elevate usage/token trends, without duplicating existing task coverage. Not for full system-health or market-research sweeps — those are separate Analyst surfaces."
version: 0.1.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [analyst, heartbeat, liveness, usage, cron, real-estate]
---

# Analyst · Liveness & Usage Pulse

Use this for the focused Analyst heartbeat that checks agent liveness and usage/cost signals only. It is deliberately narrower than the full `surface-heartbeat` or Analyst system-health sweeps.

## Core workflow

1. Load the Analyst surface config with `agent_bus(action='get_surface_config', surface='analyst')` and read the workspace `learnings.md`.
2. Refresh the Analyst heartbeat with `agent_bus(action='heartbeat', agentId='analyst', agent_id='analyst', surface='analyst', ...)` and log a start event.
3. Reconcile before acting:
   - `agent_bus(action='list_heartbeats', surface='all')` for direct heartbeat ages.
   - `agent_bus(action='list_tasks', status='pending')` and, if needed, `status='in_progress'`, then client-side filter for heartbeat/usage/coordinator-watch coverage.
   - `agent_handoff(action='list')` and client-side filter for open Analyst-directed handoffs. Do not probe handoff actions with placeholder task values.
   - If inbox/list actions are unavailable in cron, record that and use handoff/task reconciliation instead of failing the heartbeat.
4. Collect usage:
   - First try account-scoped `ELEVATE_HOME=<account> elevate insights --days 1` and `--days 7`.
   - If account-scoped insights returns no sessions, rerun against the active/default Elevate home.
   - Do not pass `--source all`; omit `--source` for all-source overview.
   - If `--turns` is empty but overview exists, parse the overview and continue.
5. Classify usage:
   - Watch-only when messages/tool calls are high but processed tokens are steady or below the 7-day daily average.
   - Escalate/update EA coverage only when processed tokens materially worsen, roughly >40% over the 7-day daily average, a hard budget/cost signal appears, or high-volume patterns persist/worsen.
6. Classify liveness:
   - >5h stale direct heartbeat: owner nudge after deduping open tasks for that exact surface/agent.
   - >8h stale direct heartbeat: EA coordinator-watch after deduping open EA coverage.
   - If several surfaces newly cross >5h between pulses, create one separate owner nudge per surface after dedupe. This is report-worthy as a new threshold crossing even when usage is quiet.
   - If owner/EA coverage already exists and was refreshed only minutes earlier, do not churn the same tasks again. Refresh only if evidence is newer/materially worse, then log events and history.
7. Write `history/<UTC timestamp>-liveness-usage-pulse.json` with checked/did/found/summary/external_actions/notification_decision.
8. Finish heartbeat with metadata containing the history path, usage classification, stale surfaces, coverage status, and `external_actions=false`.

## Notification gate

Return `[SILENT]` when all findings are covered-known and usage is steady or improving. Notify only for:

- Missing owner or EA coverage for a stale heartbeat threshold.
- A newly crossed >5h or >8h heartbeat threshold.
- A new failed cron/run relevant to liveness or usage.
- Usage materially worsens or crosses the processed-token threshold.
- A human decision is required.

## Pitfalls

- Account-scoped insights can be empty in scheduled account-scoped cron runs even when the default active home has real usage data.
- `elevate insights --source all` is wrong in current CLI behavior because `all` is treated as a literal source filter.
- `agent_bus(action='list_inbox')` may be unavailable in cron. Do not fail the pulse for this alone.
- Re-updating already-refreshed owner/EA stale-heartbeat tasks creates noise. If coverage is fresh and still accurate, log a compact reconciliation ledger and stay silent.
- If prior history lists stale-heartbeat coverage task IDs that are no longer pending, recompute current direct heartbeat ages before escalating. The agent may have recovered and completed its owner/EA coverage; only create fresh coverage when the heartbeat is still past threshold and no active task remains.
- This focused pulse does not run full system-health, pipeline analytics, market research, or experiments.
