# System Context

**Organization:** {{org_name}}
**Description:** Agentic CRM personal assistant template
**Timezone:** {{timezone}}
**Orchestrator:** {{orchestrator_agent}}
**Dashboard:** {{dashboard_url}}
**Communication Style:** {{communication_style}}
**Day Mode:** {{day_mode_start}} - {{day_mode_end}}
**Framework:** Elevate

## Team Roster

For the live roster:

```bash
agent_bus list-agents
```

## Agent Health

```bash
agent_bus read-all-heartbeats
```

## Communication

- Agent-to-agent: `agent_bus send-message <agent> <priority> "<text>"`
- Telegram to user: `agent_bus send-telegram <chat_id> "<text>"`
- Check inbox: `agent_bus check-inbox`
