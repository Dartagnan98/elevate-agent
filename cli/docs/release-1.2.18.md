# Elevate 1.2.18 — release notes

Agents now remember what they did on their heartbeats when you ask in chat.

## What's fixed

- **Heartbeat work carries into the conversation.** Before, each heartbeat (and
  any cron run) executed in its own background session, so when you later asked an
  agent in chat "what did you do on your heartbeat?" it had no memory of it. Now
  every interactive turn quietly carries a digest of that agent's recent autonomous
  activity — its last heartbeat and recent events — so it answers with awareness.
  Ask the Executive Assistant and it sees the whole fleet's recent activity; ask a
  specialist and it sees its own.

## Under the hood

A compact recent-activity digest (from the activity feed + last heartbeat) is
prepended to the model's context on each interactive turn and is purely ephemeral —
it's never written into your chat history, and it's empty (zero token cost) when
there's no recent activity. Closes the cron-session ↔ interactive-session
continuity gap.

Carries the full 1.2.17 baseline (per-agent heartbeats + orchestrator completion)
and everything before it.
