---
name: human-tasks
description: "You have hit a blocker that is not a permission issue — it is a capability issue. You genuinely cannot complete the next step because it requires a human: making a payment, entering credentials for a service you cannot access, physical action, a decision that only the user can make, or anything else outside your capabilities. You need to create a clear [HUMAN] task with step-by-step instructions, block your own work on it, and notify the orchestrator so this surfaces in the next briefing."
triggers: ["human task", "need human", "can't do this myself", "requires human", "needs you to", "blocked by human", "human input needed", "waiting for human", "human only", "physical access", "payment required", "login required", "credentials I don't have", "needs human action", "only you can", "human decision", "manual step required", "create human task", "assign to human", "[HUMAN]"]
external_calls: []
category: agent-ops
---

# Human Tasks

A human task is for when you CANNOT do something — it requires human capability. This is different from an approval (where you can do it but need permission).

| Situation | Use |
|-----------|-----|
| "I can do this but need sign-off" | Approval (native Approvals — see approvals skill) |
| "I cannot do this at all — needs a human" | Human task (this skill) |

---

## Creating a Human Task

Three signals tell the dashboard to route this to "Your Tasks" — all three are required:
1. Title must start with `[HUMAN]`
2. Assignee = `human`
3. Project / list = `human-tasks`

**1. Create the human task with clear step-by-step instructions.**
Use the native **Tasks** surface to create the task. Set:
- title: `[HUMAN] <what needs to be done>`
- description: `<step-by-step instructions — be specific enough for the human to complete without asking you>`
- assignee: `human`
- priority: `normal`
- project/list: `human-tasks`

Keep the new task's id for the next steps. (If you create it via the agent_bus tool instead, the equivalent is `agent_bus` action `update_task` to manage it afterward — but creation belongs on the Tasks surface.)

**2. Block your own task on it.**
Use the **agent_bus** tool (action `update_task`) to set your own task's status to `blocked`. Then use the **agent_bus** tool (action `log_event`) to record the dependency, with event `task_blocked`, level `info`, and meta `{"task_id":"<your-task-id>","blocked_by":"<human-task-id>","reason":"human dependency"}`.

**3. Notify the orchestrator so it surfaces in the next briefing.**
Use the **agent_handoff** tool to hand the context to the orchestrator agent, with a message like: "Human task created: [HUMAN] <title> — needed before I can proceed with <your task title>." You can also drop a note in native **Comms** so the conversation is on the record.

**4. Notify the user directly if urgent.**
There is no Telegram send in Elevate. Use native **Comms** to post a user-visible note ("I need your help: [HUMAN] <title> — I've created a task with instructions, check your Tasks"), and the `[HUMAN]` task on the Tasks surface is what the user actually acts on. If you genuinely need a real-time push channel that Elevate does not provide, say so plainly rather than inventing a command — and that need itself is a [HUMAN] task.

---

## When Human Completes the Task

You receive a Comms/inbox message when the human task is marked complete (check via the **agent_bus** tool, action `check_inbox`, or watch native **Comms**). On receiving it:

Use the **agent_bus** tool (action `update_task`) to set your own task back to `in_progress` with a note "Human task completed — resuming", then resume the work. Don't wait — unblock immediately.

---

## Writing Good Human Task Instructions

The instructions field should be complete enough that the human can execute without coming back to ask you questions.

**Bad:** "Set up the API key"

**Good:** "1. Go to openai.com/account/api-keys. 2. Click 'Create new secret key'. 3. Name it 'elevate-myorg'. 4. Copy the key (starts with sk-...). 5. Add it to the agent's environment / config so I can use it (tell me once it's in and I'll pick it up)."

---

## Consequence

Leaving work undone without creating a human task = invisible blocker. The system stalls silently. Create the human task within 1 heartbeat of discovering you're blocked by a human dependency.
