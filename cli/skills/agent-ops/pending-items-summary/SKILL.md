---
name: pending-items-summary
description: "Compile pending approvals, drafts, decisions, follow-ups, meeting prep gaps, and quick clears into one user-facing digest."
category: agent-ops
---

# Pending Items Summary Skill

## Inputs

- Pending tasks — pull via the **Tasks** tool, and cross-check with the agent_bus tool (action `list_tasks`) for anything assigned to you on the bus.
- Approvals — pull via the **Approvals** tool, or the agent_bus tool (action `list_approvals`).
- Drafts awaiting send/approval — read from your agent workdir (`drafts/`) and surface them through **Comms**.
- Follow-ups — `crm/followups.jsonl` in your workdir.
- Meeting prep gaps — meeting/calendar items with missing briefs.
- Inbox triage outputs — check incoming work with the agent_bus tool (action `check_inbox`); for direct handoffs from other agents use **agent_handoff** and reply through native **Comms**.
- Human-owed items — the agent_bus tool (action `check_human_tasks`) for anything blocked on a person.

## Summary Rules

- Batch low-urgency items.
- Rank by urgency and relationship importance.
- Ask for the smallest possible decision.
- Include quick clears separately.
- Do not include sensitive details beyond what is needed in the digest.

## Format

```text
Pending clears:

Urgent:
1. ...

Quick decisions:
1. ...

Relationship follow-ups:
1. ...

Drafts awaiting approval:
1. ...
```

If nothing is pending, say so briefly.

## After compiling

- Log the digest as an activity with the agent_bus tool (action `log_event`).
- Record any durable facts or open threads using the **memory** tool, and append context to your `MEMORY.md` / `memory/<day>.md`.
- If an item needs a human and there is no automated path to clear it, raise a `[HUMAN]` task via the **Tasks** tool (and the agent_bus tool, action `update_task`/`complete_task`, to keep the bus in sync). Do not invent a mechanism for steps Elevate cannot perform.
- If your own role, toolsets, or skills need to change to handle a recurring class of pending item, use **manage_agent** — never edit agent config files by hand. To run this digest on a schedule, use **cron**. To clear a large independent backlog in parallel, hand off isolated chunks via **delegate_task** to worker-agents.

To inspect what tools you currently have, run **/tools**.
