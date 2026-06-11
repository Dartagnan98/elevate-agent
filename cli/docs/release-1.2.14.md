# Elevate 1.2.14 — release notes

Delegation, subagents, and chat reliability — a big reliability pass.

## What's fixed

- **Steering mid-answer no longer breaks the reply.** Sending a follow-up while
  the agent is still answering used to truncate the answer and strand your
  message above a duplicate bubble. Now the answer finishes in place and your
  steer lands as the next turn.
- **Subagents can run a long time without dying.** Long delegated work (deep
  research, multi-step builds, CMA pulls) was being killed at 10 minutes — the
  cap is now generous, and a subagent waiting out an API rate-limit is no longer
  mistaken for "stuck."
- **Opening a running subagent shows its live work.** Drilling into a subagent
  now streams its thinking + commands as it works, instead of a blank/frozen
  view until it finished.
- **One orchestrator, clean handoffs.** A subagent no longer spawns its own
  subagents — if it hits work for another specialist, it hands it back up and the
  main agent dispatches from there.
- **Abandoned chats get cleaned up.** Idle/never-finished sessions are now closed
  automatically instead of lingering open indefinitely.
- **Telegram delivery no longer crash-loops** on a bad chat target, and the
  channel setup screen rejects an invalid chat id up front.
- **Skills fail loudly, not silently.** If a skill can't load its tools for a
  turn, you now get a reason instead of nothing happening.

## Per-agent channel pairing

Each agent has its own Telegram bot, so pairing is now scoped per agent — the
"Pair a channel" panel lives in each agent's Telegram tab, and approving one
agent's bot no longer authorizes a user across all of them.

## Under the hood

Carries the 1.2.13 baseline (full agent toolkit + keyless web search). Async
non-blocking delegation (dispatch-and-keep-working with a completion ping) is in
progress and ships in a following release.
