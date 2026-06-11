# Tools Quick Reference

This template is tool-agnostic. The setup skill detects and records whichever tools are available.

## Required Elevate Tools

| Need | Command |
|---|---|
| Reply to user | `agent_bus send-telegram $CTX_TELEGRAM_CHAT_ID "<message>"` |
| Create task | `agent_bus create-task "<title>" --desc "<desc>"` |
| Update task | `agent_bus update-task <task_id> in_progress\|blocked\|completed` |
| Complete task | `agent_bus complete-task <task_id> --result "<summary>"` |
| Attach deliverable | `agent_bus save-output <task_id> <file> --label "<human-readable label>"` |
| Request approval | `agent_bus create-approval "<title>" <category> "<context>"` |
| Log event | `agent_bus log-event <category> <event> info --meta '<json>'` |
| Heartbeat | `agent_bus update-heartbeat "<status>"` |
| Crons | `agent_bus list-crons your agent name`, `agent_bus add-cron ...` |

## Optional Tool Classes

The setup skill writes exact commands here after discovery.

### Email

- Configured provider:
- Account(s):
- Search command:
- Read thread command:
- Draft command:
- Send command:

### Calendar

- Configured provider:
- Calendar(s):
- List events command:
- Create event command:
- Conflict-check command:

### Meeting Notes

- Configured provider:
- Search/list command:
- Transcript export command:

### External CRM

- Configured provider:
- Query command/API:
- Upsert command/API:
- Sync policy:

## Local CRM Store

Default local files:

- `crm/contacts.json`
- `crm/interactions.jsonl`
- `crm/followups.jsonl`
- `crm/relationship-health.json`
