# Elevate 1.2.16 — release notes

Per-agent heartbeats. Every agent now wakes up, checks in, and works on its own.

## What's new

- **Each agent has its own heartbeat.** Like the cortextOS fleet model: every
  worker agent (Executive Assistant, Admin, Outreach, Marketing, Social Media,
  Analyst) gets its own `HEARTBEAT.md` — a 10-step beat it runs each cycle: update
  its status so the dashboard shows it alive, sweep its inbox, check its tasks and
  goals, work the top item, log what it did, and update its memory. The Executive
  Assistant also runs fleet health (flags any agent that's gone quiet).
- **You turn each one on per agent.** Heartbeats ship OFF (opt-in). Open an agent in
  the Agent Hub → Workflows tab: its `heartbeat` cron (every 4h) is right there to
  enable, and you can view/edit that agent's HEARTBEAT.md inline.
- **Native, not the old daemon.** The beat runs entirely on Elevate's own tools
  (agent bus, Tasks, Comms, Approvals, memory) — the previous heartbeat instructions
  still referenced the cortextOS daemon, which doesn't exist in the app. Rewritten.

## Under the hood

Three decoupled parts, mirroring the upstream model: an agent-bound `heartbeat` cron
(the schedule), `HEARTBEAT.md` + the heartbeat skill (the execution checklist), and
the heartbeat status store the dashboard reads (the state). Seeded automatically on
this release for every installed agent — paused — plus companion docs
(GOALS/MEMORY/GUARDRAILS) in each agent's workspace. An agent's edited HEARTBEAT.md
is never overwritten.

Carries the full 1.2.15 baseline (non-blocking delegation) and everything before it.
