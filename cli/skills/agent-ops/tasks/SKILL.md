---
name: tasks
description: "Track a piece of work through its full task lifecycle so it's visible to the dashboard. Use when starting anything with a deliverable — 'create a task', 'start work', 'track this', 'mark in progress', 'complete task', 'this is blocked'. Create it, mark in_progress, complete with a result summary, log a task_completed event. Not for work that needs a human to act — assign a [HUMAN] task via human-tasks instead. Without a task, your work is invisible."
triggers: ["create task", "start task", "new task", "track work", "log work", "task system", "task workflow", "mark in progress", "complete task", "task blocked", "assign task", "list tasks", "task queue", "pending tasks", "my tasks", "work item", "deliverable", "project task", "task management", "task lifecycle"]
external_calls: []
category: agent-ops
---


# Task System

Every significant piece of work must have a corresponding task. Tasks enable coordination, accountability, and measurable progress.

## Task Types

- **Agent tasks** - Work executed autonomously by the assigned agent
- **Human tasks** - Requires human decision, input, or approval (assigned_to=human)

## Lifecycle

### 1. Create (BEFORE starting work)
```bash
agent_bus create-task "<title>" --desc "<description>" [--assignee <agent>] [--priority <p>] [--project <name>]
```

### 2. Mark in progress
```bash
agent_bus update-task <task_id> in_progress
```

### 3. Execute the work

### 4. Complete
```bash
agent_bus complete-task <task_id> --result "[output summary]"
```

### 5. Log KPI (if measurable)
```bash
agent_bus log-event task task_completed info --meta '{"task_id":"ID","kpi_key":"metric_name","value":1}'
```

## The `needs_approval` Field

**true** - external actions: sending emails, merging PRs, deploying, public announcements
**false** - internal work: research, drafts, feature branches, testing

Tasks with `needs_approval: true` create an approval item that must be reviewed before executing external actions.

## Script Reference

| Action | Command |
|--------|---------|
| Create | `agent_bus create-task "<title>" --desc "<desc>" [--assignee <a>] [--priority <p>]` |
| List | `agent_bus list-tasks [--status S] [--agent A] [--priority P]` |
| Update | `agent_bus update-task <id> <status>` |
| Complete | `agent_bus complete-task <id> --result "[summary]"` |
| Log event | `agent_bus log-event <category> <event> <severity> --meta '[json]'` |

**Statuses:** pending, in_progress, blocked, completed

**Priorities:** urgent, high, normal, low

**Tool vs shell:** the `agent_bus` commands above are the shell form. In API/chat sessions the shell command may not exist while the **agent_bus** TOOL does — call the tool with the matching action (`create_task`, `list_tasks`, `update_task`, `complete_task`, `log_event`) instead of treating the missing binary as a failure.

## Best Practices

- **Always create before starting** - ensures tracking and coordination
- **Be specific** - clear titles, descriptions with success criteria
- **Complete thoroughly** - include what was accomplished and where outputs are
- **Log KPIs** - when work advances a measurable goal
