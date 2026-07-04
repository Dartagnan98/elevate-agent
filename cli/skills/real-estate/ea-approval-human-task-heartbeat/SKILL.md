---
name: ea-approval-human-task-heartbeat
version: 0.1.0
description: "Reconcile approvals, approval gates, and human-owned blockers without duplicate cards. Use whenever the Executive Assistant approval heartbeat runs, to count pending approvals older than about 1 hour, tasks flagged needsApproval, or [HUMAN] tasks older than about 4 hours, then post one escalation Activity instead of a new task."
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [executive-assistant, heartbeat, approvals, human-tasks, dashboard]
---

# EA Approval & Human-Task Heartbeat

Use this when running the focused `Executive Assistant · Approval & Human-Task Escalation` surface heartbeat.

## Purpose

Keep approvals and human-owned blockers visible on the dashboard without creating duplicate tasks or sending anything externally.

## Steps

1. **Load context first.**
   - Read surface config with `agent_bus(action='get_surface_config', surface='executive-assistant')`.
   - Read the workspace `learnings.md` and apply existing rules.
   - Refresh the EA heartbeat with `agent_bus(action='heartbeat', surface='executive-assistant', agent='executive-assistant', status='ok', metadata={...})`.

2. **Reconcile formal approvals.**
   - Call `agent_bus(action='list_approvals', status='pending')`.
   - If none are pending, record that clearly.
   - If approvals are pending and older than ~1h, check whether a matching human-assigned dashboard task already exists before creating or escalating anything.

3. **Reconcile task-level approval gates.**
   - Call `agent_bus(action='list_tasks', status='pending')` once and client-side filter tasks where `needsApproval` or `needs_approval` is true.
   - Count gates older than ~1h.
   - If `list_tasks` output is persisted to a temp file because it is large, read and parse that saved JSON instead of rerunning repeatedly.
   - A task-level approval gate assigned directly to `human` already counts as surfaced.

4. **Reconcile human-owned blockers.**
   - Use `agent_bus(action='check_human_tasks', older_than_days=0)` and/or the pending-task snapshot.
   - Count human-owned or `[HUMAN]` tasks older than ~4h.
   - Compare against the most recent EA approval/human-task Activity so you only flag newly crossed thresholds or meaningful changes.

5. **Do not use unsupported inbox actions.**
   - `agent_bus` currently does not expose generic inbox/message actions such as `list_messages`, `list_inbox`, `inbox`, or `messages` in cron contexts.
   - `agent_handoff(action='list')` may reject status filters such as `status='pending'`; avoid filtered handoff calls unless the valid status set has been verified in that run.
   - For inbox-like EA blockers, call `agent_handoff(action='list')` unfiltered, then client-side filter for `toAgentId='executive-assistant'` and open/running/waiting statuses. Pair that with recent `agent_bus(action='list_activity', surface='executive-assistant')`.
   - Treat waiting handoffs as already surfaced if a matching human task exists. If no filtered handoffs remain, record “no EA inbox/handoff ACK needed” instead of failing the heartbeat.

6. **Escalate by Activity, not duplicate tasks.**
   - If blockers are already dashboard-visible, post one concise dashboard Activity with the counts and top waiting items.
   - Use `agent_bus(action='log_event', category='approval_escalation', event='activity', message='...', metadata={...})`.
   - Put the text in `message`; using `summary` may create a blank Activity row.
   - Never send externally, approve, reject, or act on the realtor's behalf.

7. **Log the run.**
   - Write `history/<UTC timestamp>-approval-human-escalation.json` with `ran_at`, `checked`, `did`, `found`, and `summary`.
   - Call `agent_bus(action='log_run', surface='executive-assistant', kind='work', record={...})`.
   - Verify the history file and recent Activity if this run changed anything.

## Pitfalls

- Formal approvals can be clear while task-level approval gates still exist in pending tasks.
- `list_tasks` may return a very large persisted result; parse the saved file and compute ages locally.
- Do not create duplicate `[HUMAN]` tasks for gates already assigned to `human`.
- A newly crossed threshold is a meaningful change; an unchanged backlog can stay silent.
- This heartbeat is draft/escalation-only. External sends, portal actions, legal/financial actions, and approvals remain human-gated.
