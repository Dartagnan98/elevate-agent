---
name: surface-heartbeat-agentbus-config-fallback
description: "Read surface config via agent_bus when workspace config.json is missing. Use when the prompt says to read config via agent_bus(get_surface_config), or config.json is absent but learnings.md/history/experiments still exist during a surface-heartbeat run."
version: 0.1.0
---

# Surface heartbeat agent_bus config fallback

## Trigger
Use during a `real-estate/surface-heartbeat` run when:
- the prompt explicitly says to read the surface config via `agent_bus(action='get_surface_config')`, or
- `<workspace>/config.json` is missing or empty but the heartbeat workspace has `learnings.md`, `history/`, and `experiments/`.

## Steps
1. Call `agent_bus(action='get_surface_config', surface='<surface>')` first and treat the returned `goal`, `cycles`, and legacy `experiment` block as the authoritative config for this run.
2. Read `<workspace>/learnings.md`, count files in `<workspace>/history/`, and inspect `<workspace>/experiments/active/` / `experiments/history/` as usual.
3. Do not fail the heartbeat only because `config.json` is absent if `agent_bus` returned the surface config.
4. Continue the focused heartbeat scope only. Reconcile existing tasks/handoffs before creating new tasks, and write the normal `history/<UTC>.json` log.
5. If a cycle is due, run the surface-heartbeat experiment loop using the agent_bus-provided cycle definition.

## Pitfalls
- Missing `config.json` is not automatically a system-health failure in scheduled focused surface runs. The dashboard/agent_bus config can be the source of truth.
- Do not create duplicate escalations for known cron errors. Check existing human/platform tasks and handoffs first.
- If inbox ACK actions are unavailable in cron, reconcile through `agent_handoff(action='list')`, task sweeps, and Activity logs instead of failing the run.
