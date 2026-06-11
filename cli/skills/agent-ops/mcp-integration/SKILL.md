---
name: mcp-integration
description: "Integrate Model Context Protocol (MCP) servers with Elevate agents. Covers server setup, tool discovery, and multi-server orchestration."
homepage: https://modelcontextprotocol.io
tags: [mcp, integration, servers, tools]
category: agent-ops
---

# MCP Integration

Connect Elevate agents to external services via Model Context Protocol.

## Adding MCP Servers

In your agent's `.claude/settings.json`:
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-filesystem", "/path/to/dir"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-github"],
      "env": { "GITHUB_TOKEN": "ghp_..." }
    }
  }
}
```

If you need to change which MCP servers, toolsets, skills, or role an agent runs with, use the **manage_agent** tool — never edit an agent's config files by hand.

## Discovering Tools

To see the tools currently available to your agent (including those exposed by connected MCP servers), run **/tools**. Use this to confirm a server connected and its tools registered before you rely on them.

## Popular MCP Servers
- **filesystem** - Read/write local files
- **github** - Issues, PRs, repos
- **postgres** - Database queries
- **slack** - Send/read messages
- **brave-search** - Web search

## Building Custom Servers
```typescript
import { McpServer } from "@anthropic-ai/mcp";

const server = new McpServer({ name: "my-server" });

server.tool("my_tool", { description: "Does something" }, async (input) => {
  return { result: "done" };
});

server.run();
```

## Wiring MCP Tools Into Agent Workflows

MCP tools become useful once they feed Elevate's native primitives. Map the work to the right Elevate mechanism:

- **Heartbeats / liveness** — use the **agent_bus** tool (action `update_heartbeat`) to beat, and the **agent_bus** tool (action `read_heartbeats`) to check the fleet.
- **Activity / events** — use the **agent_bus** tool (action `log_event`) to record what an MCP call did.
- **Tasks** — read/create/inspect work via the native **Tasks** surface; for programmatic task ops use the **agent_bus** tool (actions `list_tasks`, `update_task`, `complete_task`).
- **Goals** — use the **agent_bus** tool (action `get_goals`) and (action `update_goals`).
- **Approvals** — route anything that needs sign-off through the native **Approvals** surface; list pending items via the **agent_bus** tool (action `list_approvals`). Don't approve in chat.
- **Human tasks** — check assigned human work with the **agent_bus** tool (action `check_human_tasks`).
- **Memory** — persist facts with the **memory** tool and in the agent's `MEMORY.md` / `memory/<day>.md`; write structured entries via the **agent_bus** tool (action `write_memory`).
- **Inbox / messaging** — pull queued messages with the **agent_bus** tool (action `check_inbox`); hand work between agents with **agent_handoff** and converse via the native **Comms** surface.
- **Recurring runs** — schedule repeated MCP-driven jobs with **cron**.
- **Isolated parallel work** — fan out independent MCP-heavy work with **delegate_task** / worker-agents so each runs in its own context.

The agent's working directory and identity (org, agent name, workspace root) are available from the agent's own workdir and identity context — reference those directly rather than expecting external environment shims.

## Best Practices
- Use environment variables for secrets, never hardcode
- Test servers independently before connecting to agents
- Set timeouts on server connections
- Log all MCP calls for debugging with the **agent_bus** tool (action `log_event`)

## When No Elevate Mechanism Exists

If an integration step has no matching Elevate tool or surface, do not invent a command or fall back to a shell daemon. State plainly that there is no Elevate mechanism for it and raise a [HUMAN] task so an operator can decide how to proceed.
