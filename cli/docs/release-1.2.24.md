# Elevate 1.2.24 — release notes

Background sub-agents grow up, agent skills come back, and Telegram agent bots
get their menus.

## Important fix: agent skills were silently missing (1.2.22 / 1.2.23)

A migration in 1.2.22 left the skill-sync ledger believing 58 agent skills
(tasks, comms, memory, heartbeat, and the rest of the agent-ops set) had been
deliberately deleted — so they were never installed, and agents ran their
scheduled jobs without their instructions ("Skill(s) not found and skipped…").
This release heals itself: on first launch the missing skills re-install
automatically. If your agents' scheduled runs seemed shallow or off lately,
this was why.

## Background sub-agents

- **No more fake "you" message.** A finished background task no longer posts
  its result as if you typed it.
- **The agent follows up on its own work.** When a sub-agent finishes, the main
  agent wakes, evaluates the result, and replies in its own voice — or, if you
  were mid-conversation, folds the result into its next reply instead of
  talking over you.
- **A clean completion card, inline and in sequence.** "Sub-agent completed"
  with a green (or red) status dot paints the moment the result lands, with the
  agent's take following beneath it.
- **Parallel tasks report individually.** Spawn two sub-agents and each reports
  the moment IT finishes — no more waiting for the slowest one, no more two
  tasks reading as one completion.
- **Honest statuses.** Sub-agent sessions now record when they actually ended —
  no more "Running" forever after a finished (or interrupted) run, no
  running→done→running flicker, one card per sub-agent, and the running card is
  always openable.
- **The chat keeps up.** Queued messages send themselves when the agent frees
  up, results paint in place within seconds even if the live stream hiccups,
  and a stuck "Working…" indicator clears itself — no more leaving the chat and
  coming back to see what happened.

## Telegram

- **Agent bots now show slash commands.** Typing "/" in any agent's bot chat
  pops the full command menu (previously only the primary bot had one).
- **New agents appear without a restart.** Pair a new agent's bot and it
  connects — menu included — within a minute.
- **Token-cap message tells the truth.** On messaging platforms the daily cap
  is per conversation and clears as usage rolls off — the old "start a new
  chat" advice only ever worked on the desktop. The default daily cap is also
  raised 2M → 5M tokens (real workflows were hitting 2M legitimately).

## Also

- Composer drafts are per-chat: half-typed text stays in the chat you typed it
  in instead of following you to the next one.
- Carries the full 1.2.23 baseline (database-migration fix + cortextOS scrub).
