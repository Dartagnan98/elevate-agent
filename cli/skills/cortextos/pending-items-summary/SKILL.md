---
name: pending-items-summary
description: "Compile pending approvals, drafts, decisions, follow-ups, meeting prep gaps, and quick clears into one user-facing digest."
category: cortextos
---

> Elevate compatibility: This skill was imported from CortextOS. Use Elevate-native Agent Hub, Heartbeats, Cron, Comms, Tasks, Approvals, Activity, memory providers, and agent_handoffs instead of CortextOS daemon, IPC, PM2, PTY injection, or file inbox commands. When a CortextOS command is named below, translate it to the matching Elevate UI/API/store or create a waiting-human item.

# Pending Items Summary Skill

## Inputs

- pending cortextOS tasks
- approvals
- `drafts/`
- `crm/followups.jsonl`
- meeting prep gaps
- inbox triage outputs

## Summary Rules

- Batch low-urgency items.
- Rank by urgency and relationship importance.
- Ask for the smallest possible decision.
- Include quick clears separately.
- Do not include sensitive details beyond what is needed on Telegram.

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
