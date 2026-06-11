---
name: event-logging
description: "You have just completed a task, started a session, dispatched work to another agent, finished a research cycle, or taken any significant action — and you need to record it so the dashboard activity feed shows your work. Without logging, you are invisible. Every session start, task completion, and major coordination action must produce at least one event. If you have been active but see no events in the dashboard, you have been logging nothing."
triggers: ["log event", "log activity", "activity feed", "event log", "track activity", "record event", "log completion", "log session", "no events", "invisible on dashboard", "dashboard empty", "nothing showing", "log task", "log coordination", "log research", "session start event", "task completed event", "log error", "log warning"]
external_calls: []
category: agent-ops
---

# Event Logging

Events are how the dashboard activity feed knows what you're doing. No events = you look dead. Log aggressively.

---

## How to log

Use the **agent_bus** tool with `action: log_event`. Pass the category, event name, severity, and a `meta` object.

| Parameter | Options |
|-----------|---------|
| category | `action` `task` `heartbeat` `message` `approval` `error` `metric` `milestone` |
| severity | `info` `warning` `error` `critical` |

Your identity (agent name, org, workdir) is known from your runtime and attributed automatically. Reference your own name in `meta` where it's useful for the reader, but the bus attributes the event to you automatically.

---

## Required Events (log every session)

### Session start
Use the agent_bus tool (action `log_event`) with category `action`, event `session_start`, severity `info`, and `meta: { agent: "<your name>" }`.

### Session end
Use the agent_bus tool (action `log_event`) with category `action`, event `session_end`, severity `info`, and `meta: { agent: "<your name>" }`.

### Task completed
Use the agent_bus tool (action `log_event`) with category `task`, event `task_completed`, severity `info`, and `meta: { task_id: "<id>", agent: "<your name>", summary: "<what was done>" }`. The task itself is closed through the native **Tasks** surface (or the agent_bus `complete_task` action) — this event records it on the activity feed.

### Heartbeat
Use the agent_bus tool (action `log_event`) with category `heartbeat`, event `agent_heartbeat`, severity `info`, and `meta: { agent: "<your name>", status: "active" }`. Liveness pings can also go through the agent_bus `update_heartbeat` action.

---

## Common Event Patterns

### Research completed
Use the agent_bus tool (action `log_event`) with category `action`, event `research_complete`, severity `info`, and `meta: { topic: "<topic>", findings: 3, agent: "<your name>" }`.

### Message dispatched to agent
Use the agent_bus tool (action `log_event`) with category `message`, event `message_sent`, severity `info`, and `meta: { to: "<agent>", priority: "normal", agent: "<your name>" }`. The actual message goes through **agent_handoff** (agent-to-agent) or native **Comms** (a thread on the board) — this event records that you reached out.

### Error encountered
Use the agent_bus tool (action `log_event`) with category `error`, event `<operation>_failed`, severity `error`, and `meta: { operation: "<what failed>", error: "<message>", agent: "<your name>" }`.

### Approval created
Use the agent_bus tool (action `log_event`) with category `action`, event `approval_created`, severity `info`, and `meta: { approval_id: "<id>", category: "<cat>", agent: "<your name>" }`. The approval itself is created through the native **Approvals** surface — this event records it on the feed.

---

## Orchestrator-Specific Events

### Task dispatched to specialist
Use the agent_bus tool (action `log_event`) with category `action`, event `task_dispatched`, severity `info`, and `meta: { to: "<agent>", task: "<title>", agent: "<your name>" }`. Dispatch the actual work via **delegate_task** / a worker-agent for isolated parallel work, or hand it off with **agent_handoff**.

### Status briefing sent to user
Use the agent_bus tool (action `log_event`) with category `action`, event `briefing_sent`, severity `info`, and `meta: { type: "status_update", agent: "<your name>" }`.

---

## Related surfaces

- **Tasks** (native + agent_bus `list_tasks` / `update_task` / `complete_task`) — task CRUD.
- **Approvals** (native) — request and resolve approvals.
- **Comms** (native) + **agent_handoff** — agent-to-agent and board conversation.
- **memory** tool + your `MEMORY.md` / `memory/<day>.md` — durable notes.
- **Goals** — agent_bus `get_goals` / `update_goals`.
- **cron** — recurring schedules. **manage_agent** — change your own toolsets/skills/role (never edit config files). **/tools** — list the tools available to you.

---

## Target

- Minimum 3 events per active session
- Every task completion = 1 event
- Every session start/end = 1 event each
- Every significant coordination action = 1 event
