---
name: analyst-system-health-covered-known-refresh
description: "Refresh evidence for a stale heartbeat or cron failure already covered by an owner task. Use when running an Analyst System Health & Liveness heartbeat and the signal is covered-known with nothing material changed, so delivery can stay silent."
version: 1.0.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [analyst, heartbeat, system-health, coverage, agent-bus]
---

# Analyst System Health Covered-Known Refresh

Use this when running a focused Analyst · System Health & Liveness heartbeat and the current signal is already covered by an existing owner task, EA coordinator-watch task, or human blocker.

## Pattern

1. **Reconcile before escalating**
   - Read current direct heartbeats with `agent_bus(action='list_heartbeats')`.
   - Pull pending tasks with `agent_bus(action='list_tasks', status='pending')`; if the payload is large, use the persisted output file and filter client-side.
   - Cross-check gated snapshots as needed: `deals_overview`, `leads_overview`, `ingest_runs`, `admin_action_runs`, `send_queue`, and enabled cron jobs.
   - Treat `agent_handoff(action='list')` as the safe handoff discovery path; do not invent unsupported status filters.

2. **Classify findings**
   - `new/materially updated`: no active coverage, a threshold newly crossed, a new failure appeared, or evidence materially worsened.
   - `covered-known`: an active owner/EA/human task already covers the same issue and current evidence is just fresher.
   - `noise/history-only`: outside recency gates, known skipped/cancelled rows, or no action path.

3. **For covered-known stale direct heartbeats, refresh BOTH sides**
   - Update the EA coordinator-watch task with latest `checked_at`, `last_heartbeat_at`, `age_hours`, `surface`, owner task id, and no-external-action constraints.
   - Update the owner heartbeat-write/nudge task with the same latest evidence.
   - Do not create duplicate owner or EA tasks unless the existing handle is closed/missing or the threshold newly crossed.

4. **For covered-known cron failures, refresh the existing repair task**
   - Include `cron_job_id`, `cron_name`, `last_status`, `last_run_at`, `next_run_at`, likely owner/action, and explicit no credential/calendar/portal change permission.
   - Example: Admin Calendar Sync `last_status=error` remains covered by the Google Calendar connector reauth/repair task.

5. **Log durable evidence**
   - Write the workspace `history/<timestamp>-system-health-liveness.json` with a compact reconciliation ledger.
   - Log at least `metrics_collected` and `anomaly_detected` Activity via `agent_bus(action='log_event')`, but do not rely on the returned message text being populated. Put durable detail in metadata and the history JSON.
   - Refresh the Analyst heartbeat with `agent_bus(action='heartbeat', agent_id='analyst', surface='analyst', metadata={...})`.

6. **Delivery rule**
   - Return `[SILENT]` when all findings are covered-known/noise and no human decision is newly needed.
   - Notify only for missing coverage, newly crossed thresholds, new failures, materially worse evidence, or a human decision.

## Pitfalls

- `agent_bus(action='log_event')` may normalize/ignore summary-like fields depending on runtime. Put evidence in `metadata` and the workspace history file.
- `agent_bus` inbox/list message actions may not exist in cron. Use handoffs, Activity, and task sweeps instead.
- `send_queue` and `admin_action_runs` failures older than the configured recency gate are history-only unless count-changing, deadline-blocking, or uncovered.
