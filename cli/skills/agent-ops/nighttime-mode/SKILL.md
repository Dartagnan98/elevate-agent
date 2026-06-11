---
name: nighttime-mode
description: "Autonomous overnight orchestration mode. Active outside day hours. Dispatch and monitor deep work across agents while user sleeps. Internal building only — no external actions."
triggers: ["nighttime mode", "overnight mode", "night mode", "overnight orchestration", "nighttime protocol"]
external_calls: []
category: agent-ops
---

# Nighttime Mode

> Orchestrate deep work across agents while the user sleeps.
> Dispatch tasks, monitor progress, prepare morning briefing.

---

## Hard Guardrails — NEVER Cross

1. **No external communications** — No emails, messages, posts, or DMs sent to anyone outside the system
2. **No purchases or transactions** — No buying, no transfers, no commitments
3. **No permanent deletes** — All actions must be reversible
4. **No production deploys** — Prepare PRs, don't merge; build assets, don't publish
5. **No commitments on user's behalf** — No promises, deadlines, or agreements
6. **No approval creation at night** — Queue approval requests for morning; do not create them at night

**When in doubt:** Document it, present in morning review.

---

## What TO Do Overnight

| Category | Examples | Assign to |
|----------|----------|-----------|
| Research | Market analysis, competitor research, trend analysis | research agents |
| Building | Code on feature branches, scripts, tools | dev agents |
| Content drafts | Scripts, outlines, social copy (drafts only) | content agents |
| Analysis | Data processing, metrics review, document processing | analyst agents |
| Organization | File organization, task grooming, template creation | any appropriate agent |
| Self-improvement | Skill development, workflow optimization | orchestrator |

For deep, isolated parallel work, spin up a worker-agent with **delegate_task** rather than tying up a long-lived agent.

---

## Quick Start Loop

```
1. CHECK: use the agent_bus tool (action list_tasks, status in_progress)
   → Any overnight tasks dispatched?

2. IF tasks are running:
   a. Check agent heartbeats: use the agent_bus tool (action read_heartbeats)
   b. Check for completion reports: use the agent_bus tool (action check_inbox)
      and review native Comms
   c. Process completions, dispatch next tasks if queue has more
   d. GOTO step 1

3. IF no tasks pending:
   a. Begin preparing morning briefing data
   b. Update heartbeat: use the agent_bus tool (action update_heartbeat,
      message "preparing morning briefing")
```

---

## Overnight Orchestration Protocol

### Step 1: Check approved queue

- Use the **agent_bus** tool (action `list_tasks`, status `in_progress`) to see what's running. The native **Tasks** surface shows the same board if you want the UI view.
- Use the **agent_bus** tool (action `read_heartbeats`) to see which agents are alive and what they're working on.

### Step 2: Monitor agent progress

- Check heartbeats regularly (every ~1h): use the **agent_bus** tool (action `read_heartbeats`).
- Check for completion reports: use the **agent_bus** tool (action `check_inbox`), and review the native **Comms** surface for any agent_handoff messages addressed to you.

### Step 3: Process completions

When an agent reports task completion:

1. **Complete the task** — use the **agent_bus** tool (action `complete_task`) with the task ID and a result note describing what was produced. The native **Tasks** surface reflects the same state change.
2. **Log the event** — use the **agent_bus** tool (action `log_event`, type `task`, event `task_completed`) with meta `{"task_id":"<id>","agent":"<completing_agent>"}`.
3. **Write to memory** — use the **memory** tool to record the completion, and append a line to today's working log at `memory/<YYYY-MM-DD>.md` (and your `MEMORY.md` for durable facts): `COMPLETED: <task_id> - <description> (by <agent>)`.
4. **Dispatch next task** — use the **agent_bus** tool (action `list_tasks`, status `pending`) to find the next queued item, then hand it off.

### Step 4: Handle blockers

When an agent reports a blocker:

1. **Log the blocker** — use the **memory** tool and append to `memory/<YYYY-MM-DD>.md`: `BLOCKED: <task_id> - <reason> (agent: <name>)`.
2. **Try to unblock** — send the unblocking info or a reassignment via the **agent_handoff** tool (or post it in native **Comms** to the agent). To reassign or re-scope the task itself, use the **agent_bus** tool (action `update_task`).
3. **If you cannot unblock**, queue it for morning review: append `MORNING REVIEW NEEDED: Blocker - <task_id> - <reason>` to `memory/<YYYY-MM-DD>.md`. Do NOT create an Approval at night (see guardrail 6) — surface it in the morning briefing instead.

---

## Heartbeat During Nighttime

Update regularly to show overnight activity — use the **agent_bus** tool (action `update_heartbeat`) with a status message like:

> `nighttime mode - X/Y tasks complete, monitoring agents`

---

## Before Morning: Prepare Briefing Data

Before the morning review run fires, ensure this data is ready in today's memory:

1. What was completed (by which agent, key deliverables with file paths)
2. What needs user review or decision
3. Blockers discovered that need morning attention
4. Recommended priorities for today

Use the **memory** tool and append a summary block to `memory/<YYYY-MM-DD>.md`:

```
## Overnight Summary - <HH:MM:SS>

### Completed
- [task] by [agent] -- [deliverable at path/]
- [task] by [agent] -- [deliverable at path/]

### Blocked (needs morning attention)
- [task] -- [reason]

### Needs User Review
- [item needing decision]

### Agent Status at Morning
[list each agent: status, last heartbeat — pull from agent_bus read_heartbeats]
```

Then update your status — use the **agent_bus** tool (action `update_heartbeat`) with `morning briefing data ready - overnight complete`.

Note: if the morning review needs to fire on its own schedule, that's a **cron** job — set it up with the **cron** tool, don't hand-roll a timer.

---

## Event Logging

Use the **agent_bus** tool (action `log_event`) at these points. Your identity (the `agent` field) comes from your own agent identity — you don't pass it manually.

- **Starting nighttime mode** — action `log_event`, type `action`, event `nighttime_mode_start`.
- **Task completions** — action `log_event`, type `task`, event `task_completed`, meta `{"task_id":"<id>","agent":"<completing_agent>"}`.
- **Morning ready** — action `log_event`, type `action`, event `morning_briefing_ready`, meta `{"tasks_completed":"X","tasks_blocked":"Y"}`.

---

## Reconfiguring Agents

If an agent needs a different toolset, skill, or role to do overnight work, use the **manage_agent** tool. Never edit an agent's config files by hand.

---

## Philosophy

> Lower risk, higher autonomy. No external actions — internal building only.

The night is for making the user's next day easier. Dispatch, monitor, and coordinate — never act externally without them. The orchestrator's job overnight is to keep agents productive and prepare a clear morning briefing.

---

*This is the single source of truth for nighttime mode.*
