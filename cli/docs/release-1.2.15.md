# Elevate 1.2.15 — release notes

Delegation goes non-blocking. The headline of the reliability arc that started
in 1.2.14.

## What's new

- **Hand a task to an agent and keep working.** When you ask the assistant to
  delegate something — research, a CMA pull, a multi-step build — it now sets
  the work running in the background and comes right back to you: "Sent it to
  <agent>, here's what I set up, I'll ping you when it's done — anything else?"
  You're no longer stuck staring at "Working…" while a subagent grinds. The
  result arrives on its own as a new message the moment it's ready, and the
  sidebar dot clears.
- **The answer comes back in full.** The completed work drops into the chat as
  its own message and stays in the conversation, so your next instruction can
  build on it directly.

## Under the hood

Top-level delegation in the app is now non-blocking: the child runs on its own
thread and its result returns as a new turn via a completion sink, instead of
the parent turn blocking until the child finishes. This also removes the old
"parent hangs on Working after the child is already done" case.

Scope and safety: only interactive app sessions dispatch non-blocking; CLI and
cron runs still complete synchronously (they need the result inline), as do
nested orchestrators. There's an operator kill switch
(`delegation.async_enabled: false`) that restores the old blocking behavior if
ever needed.

Carries the full 1.2.14 baseline (steer-mid-answer fix, long-running
subagents, live subagent drill-in, single-orchestrator handoffs, session
reaper, Telegram fixes, per-agent pairing) and the 1.2.13 toolkit + keyless
web search.
