---
name: system-diagnostics
description: "Something in the system feels stuck or wrong — tasks are not moving, an agent has gone quiet, goals have not been updated in days, or the orchestrator has asked for a system health report. You need to run a structured check: stale tasks, stale goals, overdue human tasks, fleet heartbeat status, and metrics. This is your diagnostic toolkit. Run it on every heartbeat (orchestrator) and whenever something seems off."
triggers: ["system health", "health check", "stale tasks", "stale goals", "fleet health", "system status", "what's stuck", "blocked tasks", "overdue tasks", "goal staleness", "collect metrics", "metrics", "system check", "something seems wrong", "agent not progressing", "work stalled", "nothing moving", "check everything", "full health check", "morning health check", "diagnose system", "task stuck", "goals not updated"]
external_calls: []
category: agent-ops
---

# System Diagnostics

Use these to detect and surface problems before they become crises.

---

## Stale Task Detection

Find tasks that have been in-progress too long or pending without action. Use the **agent_bus** tool (action `list_tasks`) to pull the current task set, or the native **Tasks** surface, then flag by age:

- `in_progress` for more than 2 hours
- `pending` for more than 24 hours
- Human tasks with no update in 48 hours
- Tasks past their due date

When you find a stuck task, correct it with the **agent_bus** tool (action `update_task` to re-assign / re-prioritize / move state, or action `complete_task` if it is actually done) or edit it directly on the native **Tasks** board.

**When to run:** Every heartbeat (orchestrator), on suspicion of stuck work (all agents).

---

## Goal Staleness Check

Detect agents whose goals haven't been updated recently. Read goals with the **agent_bus** tool (action `get_goals`) and compare the last-updated timestamp against your threshold (default 7 days; tighten to 3 when an agent seems directionless).

If goals are stale, refresh them with the **agent_bus** tool (action `update_goals`).

**When to run:** Weekly, or when an agent seems directionless.

---

## Human Task Monitoring

Check for human-assigned tasks that are waiting too long with the **agent_bus** tool (action `check_human_tasks`). It surfaces overdue [HUMAN] items so you can chase them.

For anything genuinely blocked on a person, escalate through the native **Approvals** surface or notify via native **Comms** rather than letting it sit. Run daily (orchestrator) or when blocked waiting on a human.

---

## Fleet Health Summary

Read all agent heartbeats at once with the **agent_bus** tool (action `read_heartbeats`). Each agent reports its own beat via the **agent_bus** tool (action `update_heartbeat`).

Stale threshold: an agent that hasn't updated in >6h = investigate. If an agent has gone quiet, reach it through native **Comms** or hand work off with **agent_handoff**; if it needs to be reconfigured (toolsets / skills / role), use **manage_agent** — never edit agent config files by hand.

---

## Metrics Collection

Record a system metrics snapshot — task counts, completion rates, agent activity — by logging an event with the **agent_bus** tool (action `log_event`). For deeper recurring captures, schedule the collection with **cron** (e.g. a nightly analyst run).

Run nightly.

---

## Full Health Check Sequence

Run this during morning review or when something feels off. Walk the checks in order using the **agent_bus** tool actions:

1. **Fleet heartbeats** — agent_bus (action `read_heartbeats`)
2. **Stale tasks** — agent_bus (action `list_tasks`), then flag by the age rules above
3. **Stale goals** — agent_bus (action `get_goals`), compared against your staleness threshold
4. **Human tasks** — agent_bus (action `check_human_tasks`)

Record the run with the **agent_bus** tool (action `log_event`) so the snapshot is captured, and write anything worth remembering across sessions to your **memory** (the `memory` tool, plus your `MEMORY.md` / `memory/<day>.md`).

Surface critical findings to the user via native **Comms**. If a finding has no Elevate mechanism to resolve it, do not invent one — raise it as a `[HUMAN]` task and route it through the native **Approvals** surface.
