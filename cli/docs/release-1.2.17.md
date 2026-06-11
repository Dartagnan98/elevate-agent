# Elevate 1.2.17 — release notes

Completes the orchestrator (Executive Assistant) to match the cortextOS model.

## What's new

Builds on 1.2.16's per-agent heartbeats by giving the **Executive Assistant** its
full orchestrator rhythm:

- **Fleet health + goal cascade in its heartbeat.** The EA's HEARTBEAT.md now runs
  the orchestrator-specific steps each beat: check every agent's heartbeat (alert
  any that have gone quiet), ping you on approvals or [HUMAN] tasks that have sat
  too long, and — in the morning — set the day's focus and cascade goals to each
  agent (writing goals for any agent that has none).
- **The EA's coordination crons.** Five companion automations, seeded for the
  Executive Assistant (OFF by default — enable per agent in the Agent Hub →
  Workflows): `check-approvals` (every 2h), `morning-review` (8am), `evening-review`
  (6pm), `weekly-review` (Mon 8am), and `morning-brief` (daily). These mirror the
  cortextOS orchestrator set, running on Elevate's own tools.

## Under the hood

Diffed against the cortextOS source orchestrator template and closed the two gaps:
the EA heartbeat's Step 3 (fleet health) + Step 6 (org goals), and the companion
cron set. All EA-bound, seeded paused/opt-in, idempotent, and native (agent bus +
Tasks/Comms/Approvals + the EA's review skills — never the cortextOS daemon).

Carries the full 1.2.16 baseline (per-agent heartbeats) and everything before it.
