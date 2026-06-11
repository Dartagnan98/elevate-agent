---
name: calendar-management
description: "Tool-agnostic calendar management: schedule review, conflict detection, protected time, meeting prep chaining, and follow-up creation."
category: agent-ops
---

# Calendar Management Skill

Use the calendar provider configured in `TOOLS.md`. See your available providers with `/tools`.

## Morning Review

1. List today's events and tomorrow's early events.
2. Check protected time from `USER.md`.
3. Identify conflicts, unclear locations, missing links, or no-prep meetings.
4. Chain to `meeting-prep` for meetings in the next 24h.
5. Send a concise summary if configured — deliver via native Comms (or the `agent_handoff` tool to route it to another agent/the user).

## Evening Review

1. List tomorrow's events.
2. Prepare briefs for tomorrow's meetings.
3. Identify decisions needed from the user.
4. Create follow-up tasks for unresolved items via native Tasks (or the `agent_bus` tool, action `update_task`, to mark progress on existing items).

## Scheduling Rules

Before creating or moving an event:

- Check protected blocks.
- Check all configured calendars.
- Apply buffer rules.
- Prefer configured meeting windows.
- If a conflict exists, propose alternatives.

Creating, moving, or deleting events requires approval unless setup says calendar writes are autonomous. Route approval requests through native Approvals; check pending items with the `agent_bus` tool (action `list_approvals`).

## Meeting Prep Chain

For each meeting:

- identify attendees
- query CRM
- inspect relevant emails/messages/tasks
- search meeting notes if available — store and recall durable context with the `memory` tool and the agent's `MEMORY.md` / `memory/<day>.md`
- write a brief under `meetings/<category>/<event-id>/brief.md` in the agent's workdir
- create the reminder/delivery: a one-off task via native Tasks, or a recurring delivery via the `cron` tool

## Notes

- Recurring reviews (morning/evening): schedule with the `cron` tool.
- Heartbeat/status reporting: use the `agent_bus` tool (actions `update_heartbeat`, `read_heartbeats`, `log_event`).
- Goals context: use the `agent_bus` tool (actions `get_goals`, `update_goals`).
- Human-required steps (e.g. confirming a meeting by phone, approving a calendar write when writes are not autonomous): raise a `[HUMAN]` task via native Tasks; check outstanding human items with the `agent_bus` tool (action `check_human_tasks`).
- To reconfigure which calendar/CRM toolsets or skills this agent has, use the `manage_agent` tool — never edit config files directly.
- For isolated parallel work (e.g. prepping many briefs at once), use `delegate_task` / worker-agents.
- If a step needs a mechanism Elevate does not provide, say so plainly and raise a `[HUMAN]` task rather than inventing a command.
