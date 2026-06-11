# Elevate 1.2.19 — release notes

Long-running delegated tasks no longer get cut off early.

## What's fixed

- **A long task could abort with "API call sequence exceeded the per-turn
  wall-clock budget."** A safety timeout meant to catch a single hung API call
  was instead measuring the *entire* multi-step turn, so a legitimately long
  job — e.g. a 10-minute delegated SkySlope extraction making dozens of quick
  calls — hit the 600-second ceiling and was killed even though nothing was
  actually stuck (0 retries). The timeout now resets per step, so it still
  catches a genuinely hung call but lets long, productive work run to
  completion. (Pairs with the 1.2.14 fix that already raised the delegated-task
  cap to 4 hours.)

## Under the hood

`api_turn_deadline` (default 600s) is re-anchored at the start of each agentic
iteration, bounding one API call + its retries rather than the cumulative turn.
The agent loop remains bounded by `max_iterations` and `max_session_seconds`.

Carries the full 1.2.18 baseline (per-agent heartbeats, orchestrator crons,
heartbeat→chat continuity, and the "app is damaged" / PYTHONPYCACHEPREFIX fix).
