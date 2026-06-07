---
name: tool-discovery
description: "Discover available email, calendar, contacts, meeting notes, browser, and CRM tools for a tool-agnostic personal assistant."
category: cortextos
---

> Elevate compatibility: This skill was imported from CortextOS. Use Elevate-native Agent Hub, Heartbeats, Cron, Comms, Tasks, Approvals, Activity, memory providers, and agent_handoffs instead of CortextOS daemon, IPC, PM2, PTY injection, or file inbox commands. When a CortextOS command is named below, translate it to the matching Elevate UI/API/store or create a waiting-human item.

# Tool Discovery Skill

Use during setup and whenever a workflow fails because a tool may be missing.

## Discover Local CLIs

```bash
for cmd in gog gh agent-browser peekaboo sqlite3 jq rg; do
  if command -v "$cmd" >/dev/null; then
    echo "$cmd: $(command -v "$cmd")"
  fi
done
```

## Discover MCP/Connector Hints

```bash
test -f .mcp.json && cat .mcp.json
env | grep -E 'GMAIL|GOOGLE|OUTLOOK|NOTION|ZOOM|FATHOM|HUBSPOT|PIPEDRIVE|AIRTABLE|CRM' | sed 's/=.*/=<configured>/'
```

## Record Results

Append a `## Configured Tools` section to `TOOLS.md` with:

- provider
- command or connector name
- account identifier, if safe
- read/write capability
- approval requirement
- fallback path

Never write secrets to `TOOLS.md`.
