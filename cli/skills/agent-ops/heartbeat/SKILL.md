---
name: heartbeat
description: "Your heartbeat cron has fired and you need to run your beat: update your status so the dashboard shows you alive, sweep your inbox, check your tasks and goals, and log what you did. Or you are checking whether another agent is responsive before sending work, or an agent looks offline/stale and you need to investigate. A dead heartbeat means the system thinks you are down — update it proactively and run your full beat every cycle."
triggers: ["heartbeat", "update heartbeat", "check health", "agent health", "fleet health", "agent status", "is agent alive", "agent offline", "agent stale", "read heartbeats", "heartbeat cron", "i'm alive", "prove alive", "agent not responding", "stale agent", "check fleet", "fleet status", "who is online", "agent last seen"]
external_calls: []
category: agent-ops
---

# Heartbeat (Elevate-native)

The heartbeat is how the dashboard and the other agents know you are alive and
working. If you stop updating it, you appear **DEAD**. Everything here uses your
**Elevate tools** — the `agent_bus` tool, Tasks, `agent_handoff`/Comms, Approvals,
memory, and your own workdir files. **Never** call external daemons, PM2, PTY
injection, or shell agent CLIs — this is the Elevate app.

---

## When your heartbeat cron fires

Your heartbeat cron (default every 4h) fires with the prompt "Read HEARTBEAT.md and
follow its instructions." **`HEARTBEAT.md` in your working directory is the source of
truth** — it lists the full 10-step beat for you specifically. Read it and run every
step. This skill is the reference for the tool calls those steps use.

---

## Core actions (the `agent_bus` tool)

- **Update your status** (do this FIRST, every beat, and on session start):
  `agent_bus` action `update_heartbeat`, with a one-sentence summary of what you are
  doing right now. This refreshes the "alive" status the dashboard reads.
- **Log a heartbeat event:** `agent_bus` action `log_event`
  (event_type `heartbeat`, name `agent_heartbeat`, level `info`). This appends to the
  activity feed — the audit log, separate from the status string above. Aim for ≥ 2
  events per cycle; invisible work is wasted work.
- **Read fleet heartbeats:** `agent_bus` action `read_heartbeats` — returns each
  agent's status, last-update time, and current task. **Stale threshold:** an agent
  silent > 5h should be investigated. (Fleet health is the Executive Assistant's job
  every beat; other agents only read this when deciding whether to hand work to a peer.)

## The rest of the beat (see HEARTBEAT.md for your exact list)

- **Inbox:** check incoming handoffs/messages addressed to you (`agent_handoff` /
  Comms) and act on each — nothing should sit unanswered.
- **Tasks:** `agent_bus` `list_tasks` (yours, pending then in_progress) +
  `check_stale_tasks`; `update_task` to in_progress, `complete_task` with a result.
  Anything in_progress > 2h: finish or note it.
- **Goals:** `agent_bus` `get_goals` (or your `GOALS.md`). Stale > 24h or empty →
  message the Executive Assistant for fresh goals; don't idle.
- **Memory:** append your daily block to `memory/<today>.md` (or `agent_bus`
  `write_memory`); persist cross-session learnings to `MEMORY.md`. Elevate indexes
  memory into the knowledge base automatically — there is no manual ingest call.
- **Blocked work:** raise an Approval or a [HUMAN] task rather than stalling. Anything
  client-facing is drafts-only.

---

## Rules

- **Never claim a status you haven't verified.** To confirm your heartbeat cron is
  active, check the Agent Hub (your Workflows tab) — the `heartbeat` job shows its next
  fire time. Cron jobs survive restarts.
- Keep it native: `agent_bus` + Tasks + Comms/`agent_handoff` + Approvals + memory +
  your files. No external daemons, PM2, PTY, or shell agent CLIs.
- A heartbeat with 0 events logged and 0 memory updates means you did nothing visible.
  Target ≥ 2 events and ≥ 1 memory update per cycle.
