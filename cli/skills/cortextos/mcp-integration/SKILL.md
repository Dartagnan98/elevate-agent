---
name: mcp-integration
description: "Integrate Model Context Protocol (MCP) servers with Claude Code agents. Covers server setup, tool discovery, and multi-server orchestration."
homepage: https://modelcontextprotocol.io
tags: [mcp, integration, servers, tools]
category: cortextos
---

> Elevate compatibility: This skill was imported from CortextOS. Use Elevate-native Agent Hub, Heartbeats, Cron, Comms, Tasks, Approvals, Activity, memory providers, and agent_handoffs instead of CortextOS daemon, IPC, PM2, PTY injection, or file inbox commands. When a CortextOS command is named below, translate it to the matching Elevate UI/API/store or create a waiting-human item.

# MCP Integration

Connect Claude Code agents to external services via Model Context Protocol.

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

## Best Practices
- Use environment variables for secrets, never hardcode
- Test servers independently before connecting to agents
- Set timeouts on server connections
- Log all MCP calls for debugging
