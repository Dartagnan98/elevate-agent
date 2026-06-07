# CortextOS Agent Hub Replacement Map

Elevate keeps CortextOS agent concepts inside native app systems. Do not port
or re-create a second daemon, IPC service, PM2 process graph, PTY injection
path, file inbox, or workflow store.

## Replacements

| CortextOS concept | Elevate native replacement |
| --- | --- |
| Agent registry config | `agent_hub.agents` in Elevate config |
| Daemon lifecycle | Dashboard backend, Agent Hub state, and agent worker ticks |
| IPC server | HTTP/WebSocket dashboard APIs plus SQLite-backed stores |
| PM2 ecosystem | Desktop/gateway process plus cron and heartbeat scheduling |
| PTY injection | Prompt contracts, tool contracts, and Agent Hub runtime defaults |
| File inbox | Comms, `agent_handoffs`, Tasks, Activity, and memory providers |
| Agent-to-agent task routing | `agent_handoffs` with routing policy and worker drain |
| Cron loops | Existing cron jobs with optional agent ownership |
| Heartbeat loops | Existing heartbeat/surface loops and `AgentLoops` UI |
| Human approvals | `surface_approvals` and `waiting_human` handoffs |
| Context restart/handoff | Context pressure events plus native continuation handoffs |
| Long-running memory | Native memory providers, scoped by agent memory policy |

## Compatibility Rules

- Cortext-shaped agent keys may be accepted at import or API boundaries, but
  Elevate stores canonical Agent Hub fields.
- Markdown files such as `IDENTITY.md`, `SOUL.md`, `GOALS.md`, and `MEMORY.md`
  are import sources only. After import, Elevate config, memory, tasks, and
  handoffs own the data.
- Raw Telegram tokens, API keys, PM2 settings, daemon options, IPC endpoints,
  PTY settings, and file-inbox paths must not be returned by Agent Hub APIs.
- `dangerously_skip_permissions` is preserved only as compatibility metadata.
  It does not bypass Elevate approval gates.
- Future parity work should add visibility or policy inside the existing
  stores, not introduce duplicate `/agents` pages or duplicate workflow state.
