# Elevate 1.2.18 — release notes

Critical stability fix (app could become "damaged") + heartbeat memory in chat.

## Critical: "Elevate is damaged" fix

Some installs hit a macOS "'Elevate' is damaged and can't be opened" error. Cause:
the background gateway service launched the bundled Python without redirecting its
bytecode cache, so Python wrote `.pyc` files *into* the signed app bundle, breaking
the code signature. The gateway's launchd service now sets `PYTHONPYCACHEPREFIX`
(cache lives under `~/.elevate/cache`, never in the bundle), matching what the app
already did for its own processes. On update, an out-of-date gateway service is
rewritten and reloaded automatically so existing installs self-heal.

If your app is already showing "damaged," reinstall this version fresh (download +
replace the app) — the new build keeps the signature intact going forward.

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
