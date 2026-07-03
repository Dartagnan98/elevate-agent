---
name: tool-discovery
description: "Detect which email, calendar, contacts, notes, browser, and CRM tools are available. Use when at setup, a workflow fails because a tool may be missing, or the user asks 'what tools do I have', 'is Gmail connected'. Not for wiring a new MCP server — use mcp-integration."
category: agent-ops
---


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
