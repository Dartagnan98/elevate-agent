# Elevate Harness

This is the product direction for making Elevate Agent feel like one coherent
local operating system instead of separate chat surfaces.

## Core Shape

Elevate should run as one local gateway/server. The CLI, Telegram, Agent Hub,
API server, and future desktop app all connect to that same gateway state.
No client should invent its own session, memory, cron, skill, or agent registry.

## Pieces Now Wired

- `elevate harness status` prints the compact local harness posture.
- `elevate harness benchmark` runs the static prompt/tool payload benchmark.
- `elevate harness adversarial` runs bounded hostile prompt/tool/schema probes.
- `/api/harness` exposes the same snapshot to the dashboard.
- `/api/agent-hub` includes the harness snapshot inline.
- Agent Hub now shows a Harness card with gateway/client posture, route labels,
  skill manifest mode, safety posture, and best/worst focused profile savings.
- Agent orchestration snapshots include a plan graph summary: ready, blocked,
  active, completed, dependency cycles, missing dependency IDs, and next-ready
  run IDs.
- Agent orchestration snapshots expose the recent durable event tail, giving
  the dashboard a lightweight status feed without starting hidden workers.
- Memory snapshots include a jcode-style pipeline posture: search, verify,
  inject, and maintain states derived from the local turn journal until a live
  memory sidecar event stream exists.

## Operating Rules

- Executive Assistant is the coordinator and final response owner.
- Specialist agents are visible lanes, not invisible random background work.
- Skills stay visible through a compact manifest; large skill bodies load only
  when the task needs them.
- Tool profile benchmarks must stay runnable without live model calls or tool
  execution.
- Memory retrieval should remain async and local-first: current turn writes and
  retrieval results should be available on the next turn or during daily
  organization, without blocking the main chat.
- Anything that sends to another human should have an approval posture before
  production use, even if the current runtime only enforces command approvals.

## Next Implementation Targets

1. Make the outbound communication approval queue enforceable for
   `send_message`, email, SMS, and social posting.
2. Add a dashboard review panel for queued external actions.
3. Teach task routing to create durable orchestration runs before execution,
   not only when `delegate_task` is used.
4. Add a lightweight status feed per agent: current tool intent, last event,
   result summary, and blocker.
5. Promote focused tool profiles from benchmark-only into live routing once the
   manifest view proves agents can still discover tools reliably.
6. Replace the derived memory pipeline with live per-turn memory events once
   retrieval, verification, injection, and daily maintenance all emit status.
