---
name: analyst-system-health-regression-triage
description: "Triage a regressed cron or connector finding without duplicating existing coverage. Use when an Analyst System Health heartbeat sees a previously recovered integration fail again, sees newer failure evidence on an already-covered issue, or must decide if a human portal-login blocker is separate from a system/import/runtime blocker."
version: 1.0.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [analyst, heartbeat, system-health, cron, triage]
---

# Analyst System Health Regression Triage

Use this when an Analyst · System Health & Liveness heartbeat sees a cron, connector, or integration that was previously covered or recovered but now has new failure evidence.

## Workflow

1. **Reconcile current state first**
   - Pull current heartbeats, pending tasks, approvals, handoffs, cron status, `deals_overview`, `leads_overview`, and any gated DB evidence needed.
   - Check prior heartbeat history for the last classification and coverage handle.
   - Verify that any copied coverage handle is still pending/open before relying on it.

2. **Classify the signal**
   - `covered_known`: same failure class, same or older evidence, active owner/human task exists.
   - `covered_known_newer_evidence`: same failure class, newer run evidence, active owner task exists, update it.
   - `materially_updated_recovered`: prior failure now shows `last_status=ok`; update existing task to narrow or downgrade the blocker.
   - `materially_updated_regressed_after_recovery`: a recovered integration is failing again, or the new failure class differs from the old blocker.
   - `new`: no active coverage exists.
   - `noise/history_only`: old failed rows with no new count, deadline, or owner gap.

3. **Separate failure classes instead of over-deduping**
   - Do not treat a human portal login/reauth task as coverage for a system/runtime/import timeout.
   - Example: Making It Rain portal login/enrichment is a human blocker; Making It Rain paid-ad Gmail import timing out after 85s is an EA/system repair blocker.
   - If the class differs, create or refresh one owner repair task even if a related human task exists.

4. **Create/update exactly one coverage task**
   - Include: cron/job id, job name, latest run time, latest status, timeout/error text, related human task id if any, and why it is separate.
   - Add explicit constraints: draft-only, no external sends, no portal login, no import retry unless the owner intentionally investigates.
   - If `agent_bus(action='create_task')` strips outputs, immediately call `update_task` with notes and machine-readable outputs, then verify the returned task contains them.

5. **Log and report only material changes**
   - Write the workspace `history/<timestamp>.json` with a compact reconciliation ledger: signal, classification, coverage handle, and action.
   - Log `metrics_collected` and `anomaly_detected` agent_bus events.
   - Notify the user only for `new` or `materially_updated_*` findings; suppress covered-known/noise runs.

## Pitfalls

- A prior recovery note can become stale quickly. Re-check the live cron job and account `cron/jobs.json` if the `cronjob list` snapshot looks inconsistent.
- Human approval/login tasks are not blanket system-health coverage. Match coverage to the exact failure class.
- Do not retry browser/portal/import jobs from the Analyst heartbeat unless explicitly instructed. Analyst creates repair visibility, not external changes.
- Preserve memory-worthy learnings in workspace `learnings.md` if durable memory is unavailable in cron.

## Acceptance criteria

- No duplicate tasks for already covered same-class failures.
- One clear owner task exists for each genuinely new or materially changed failure class.
- The task has enough evidence for the owner to act without rerunning the entire heartbeat.
- The final cron report is short and only mentions important changes.
