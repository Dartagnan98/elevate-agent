---
name: relationship-review
description: "Review relationship health, stale contacts, follow-up opportunities, and CRM completeness."
category: agent-ops
---

# Relationship Review Skill

Run on the configured cadence. To make this recurring, register it with the **cron** tool rather than relying on any external scheduler.

## Review Inputs

- `crm/contacts.json` (in the agent's workdir)
- `crm/interactions.jsonl`
- `crm/followups.jsonl`
- Calendar meetings
- Recent message/inbox interactions — read via the **Comms** surface (and `agent_handoff` if another agent has routed context to you)
- User priorities from `USER.md`

## Process

1. Identify VIPs and high-priority contacts.
2. Compute days since last meaningful contact.
3. Find overdue follow-ups.
4. Find commitments without owner/due date.
5. Find relationships with missing context.
6. Suggest warm follow-ups.
7. Create drafts/tasks for approved categories:
   - Create tasks via the native **Tasks** surface (or the **agent_bus** tool, action `update_task` / `complete_task`, and action `list_tasks` to read existing ones).
   - Route anything needing sign-off through the native **Approvals** surface — do not send without approval.
   - If a draft needs to be handed to another agent for execution, use the **agent_handoff** tool.
8. Write a review note to memory: use the **memory** tool, and append a dated entry to the agent's `MEMORY.md` / `memory/<day>.md`. Log the run itself with the **agent_bus** tool (action `log_event`), and refresh your liveness with **agent_bus** (action `update_heartbeat`).

## Goals & Cadence

- Read current goals with the **agent_bus** tool (action `get_goals`); update them with action `update_goals` if this review changes priorities.
- If the review surfaces work that must be picked up by a person, create a task assigned to that human via the native **Tasks** surface and post it to Approvals where sign-off is required.

## Notes on tooling

- This skill needs no toolset, skill, or role changes to run. If a reconfiguration is genuinely required, use the **manage_agent** tool — never edit agent config files by hand.
- For isolated parallel passes (e.g. reviewing many contacts at once), spin off work with **delegate_task** / worker-agents.
- To inspect available tools at any point, use **/tools**.
- The agent's workdir and identity (root, agent name, org) are available from the runtime environment — read files relative to the workdir; do not assume any external root path.

## Output Format

```markdown
# Relationship Review

## Needs Attention
- <person>: why, suggested action

## Follow-Ups Due
- <person>: due date, context

## CRM Hygiene
- missing fields / duplicates / stale records

## Suggested Drafts
- <recipient>: one-line purpose
```

Do not send messages without approval.
