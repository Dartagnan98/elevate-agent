---
name: agentic-crm-setup
description: "Full interactive setup for the agentic CRM personal assistant template. Use at first boot or whenever the user asks to configure/reconfigure the assistant."
category: agent-ops
---

# Agentic CRM Setup Skill

This skill turns the generic template into a user's assistant. It is intentionally a full onboarding, not a quick questionnaire.

## Setup Principles

- Ask questions in small batches. If the user is on Telegram, stop after each batch and wait for their reply.
- Keep all user-specific information out of community template files until the user provides it.
- Use tool discovery before asking the user to type credentials.
- Never ask for secrets in chat. Ask the user to authenticate through the relevant tool's connection/auth flow rather than pasting keys.
- Write every answer to the correct bootstrap or CRM file in the agent's workdir.

## Tuning Knobs to Collect

### Identity

- assistant name
- user preferred name
- user's role/context
- assistant tone
- message length and update style
- day/night hours
- timezone

### Scope

- "personal assistant" scope: inbox, calendar, meetings, personal commitments, travel, errands, finance reminders, family/personal admin
- CRM scope: personal contacts, family/friends, professional network, customers/clients, investors, partners, creators/community, vendors, referrals
- excluded domains: anything the assistant should never touch

### Privacy

- local CRM only vs external CRM sync
- what may be stored in memory
- what may be ingested into the knowledge base
- redaction requirements for outputs
- data retention preferences

### Approval Rules

- external email/message send
- calendar event creation/update/delete
- purchases/bookings/cancellations
- data deletion
- financial actions
- exception contacts or domains

### Tools

- email provider(s)
- calendar provider(s)
- meeting notes/transcript provider(s)
- contact source(s)
- external CRM, if any
- browser automation availability
- connected toolsets / MCP connectors

### Schedule and Crons

- inbox triage cadence
- morning calendar review time
- evening calendar review time
- pending-items digest time
- relationship review cadence
- meeting notes processing cadence
- quiet hours and emergency criteria

### CRM Schema

- contact categories
- relationship strength scale
- health/staleness rules
- VIP list
- follow-up cadence by category
- interaction types
- required fields
- custom tags

## Tool Discovery

Discover what is actually connected before asking the user to set anything up.

- Run `/tools` to list the toolsets currently enabled for this agent (email, calendar, notes, browser, memory, etc.).
- Confirm which providers are authenticated through their own connection flow. If a needed provider is not connected, ask the user to connect it through its auth flow (never paste secrets in chat).
- Record what is detected and configured in `TOOLS.md` in the agent's workdir.

If no email/calendar/notes tools are connected, create a human task with the native **Tasks** surface (also reflected via the agent_bus tool, action `update_task`/`complete_task` as work progresses):

> [HUMAN] Configure assistant tools — connect email, calendar, meeting notes, and an optional CRM for this agent. Do not paste secrets in chat; use each provider's connection/auth flow.

If a tool the user wants has no Elevate mechanism, say so plainly and raise a [HUMAN] task rather than inventing a command.

## File Writes

After gathering answers, update these files in the agent's workdir:

- `IDENTITY.md` — assistant name, role, vibe, work style
- `USER.md` — all user-specific preferences and tuning knobs
- `SOUL.md` — approval rules, autonomy, day/night mode, communication
- `GOALS.md` — initial operational goals (also push them via the agent_bus tool, action `update_goals`; read current goals with action `get_goals`)
- `SYSTEM.md` — org, timezone, communication style
- `TOOLS.md` — detected and connected toolsets
- `config.json` — timezone, day mode, cron cadence
- `crm/contacts.json` — seed contacts and categories
- `crm/relationship-health.json` — review cadence defaults
- `crm/followups.jsonl` — initial commitments if supplied
- `MEMORY.md` and `memory/<day>.md` — durable preferences only (also record durable facts with the **memory** tool)

To reconfigure the agent itself — its enabled toolsets, skills, or role — use **manage_agent**. Never hand-edit the agent's config to change those.

## Suggested Question Batches

### Batch 1: Identity and Scope

Ask:

1. What should I be called?
2. What should I call you?
3. What kind of personal assistant should I be for you?
4. Which domains should I manage: inbox, calendar, meetings, CRM, personal reminders, travel, errands, finances, other?
5. What should I never touch?

### Batch 2: Tools

Ask:

1. Which email/calendar/meeting notes/contact/CRM tools do you use?
2. Are they already connected as toolsets/MCP connectors, or do they still need their auth flow?
3. Should I use local structured CRM files as the source of truth, an external CRM, or local-first with sync?

### Batch 3: CRM

Ask:

1. What relationship categories do you want?
2. Who are the first VIPs I must never miss?
3. What counts as a relationship going stale?
4. What interaction types matter?
5. What tags or custom fields matter in your life/business?

### Batch 4: Schedule

Ask:

1. Working hours and quiet hours?
2. Protected time blocks?
3. Preferred meeting windows and buffer rules?
4. When should I send morning/evening/pending-items summaries?
5. How often should I do relationship reviews?

Set up the recurring jobs from these answers (inbox triage, morning/evening reviews, pending-items digest, relationship reviews, meeting-notes processing) with **cron**.

### Batch 5: Approval Rules

Ask:

1. What may I do autonomously?
2. What always requires approval?
3. Are there contacts/domains I may message without approval?
4. Should I create drafts automatically?
5. Should I create calendar holds autonomously or only propose them?

Route anything that needs sign-off through the native **Approvals** surface (check pending items with the agent_bus tool, action `list_approvals`). Surface any [HUMAN] tasks through native **Tasks** and check them with the agent_bus tool, action `check_human_tasks`.

## Working With Other Agents

- Send a message or pass context to another agent with **agent_handoff** and the native **Comms** surface (check your own inbox with the agent_bus tool, action `check_inbox`).
- For isolated parallel work, spin up a worker via **delegate_task** rather than doing it inline.

## Completion

When setup is complete:

- Mark this agent onboarded in its own state (write an `.onboarded` marker in the agent's workdir state directory).
- Post a heartbeat with the agent_bus tool, action `update_heartbeat`, message "setup complete; CRM assistant online" (read fleet heartbeats with action `read_heartbeats`).
- Log the milestone with the agent_bus tool, action `log_event` (action `onboarding_completed`, level `info`, with the template name in the metadata).

Send the user a concise summary:

- configured scope
- connected tools
- CRM source of truth
- cron schedule
- approval boundaries
- first three actions you will take
