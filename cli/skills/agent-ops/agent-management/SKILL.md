---
name: agent-management
description: "You need to create a new agent, restart a crashed agent, change an agent's model or config, fix a Telegram bot token, troubleshoot why an agent is not responding, enable or disable an agent, spawn an agent for another user, reset crash limits, or do anything that touches an agent's lifecycle, configuration, or credentials. This is the definitive guide for every agent operation in Elevate."
triggers: ["new agent", "create agent", "spawn agent", "add agent", "restart", "soft restart", "hard restart", "disable agent", "enable agent", "change model", "switch model", "bot token", "BotFather", "agent not responding", "agent crashed", "agent down", "crash limit", "reset crashes", "agent health", "list agents", "heartbeat", "onboard", "setup agent", "configure agent", ".env", "config.json", "cross-org", "agent for someone else", "agent management", "agent lifecycle", "agent credentials", "telegram bot", "token not working"]
external_calls: ["api.telegram.org"]
category: agent-ops
---


## Elevate-native: use the `manage_agent` tool — do NOT edit files

In Elevate you reconfigure the fleet with the **`manage_agent` tool**, not by
editing files. It writes to the per-account agent store and applies to new/
restarted agent sessions. Everything below that says edit `.env` / `config.json` /
editing config files or running a process manager is NOT how Elevate works — ignore any such instruction.

- See valid toolset names: `manage_agent(action="available")`
- See every agent's current toolsets/skills: `manage_agent(action="list")`
- Give a toolset to one agent (or ALL): `manage_agent(action="add_toolset", agent="admin"|"all", toolset="composio")`
- Remove a toolset: `manage_agent(action="remove_toolset", agent=..., toolset=...)`
- Grant/remove a skill: `manage_agent(action="add_skill"|"remove_skill", agent=..., skill=...)`
- Change role/description/prompt/enabled: `manage_agent(action="set", agent=..., role=..., prompt=..., enabled=true|false)`
- Create / retire an agent: `manage_agent(action="create"|"retire", ...)`
- Goals are separate: use the agent_bus tool (`get_goals` / `update_goals`).

**NEVER** edit `config.yaml`, an agent's config, or — critically — ANY file inside
the app bundle (`.../Elevate.app/Contents/Resources/...`) or installed package
code. That is read-only, signed code; editing it corrupts the app ("Elevate is
damaged"). If a capability genuinely doesn't exist as a toolset, say so and create
a [HUMAN] task — don't patch code by hand.
