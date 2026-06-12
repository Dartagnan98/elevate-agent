# Elevate 1.2.25 — release notes

Chat becomes trustworthy under load, and the gateway learns to heal itself
after updates.

## Chat reliability overhaul

- **No more cross-chat bleed.** The recurring corruption where one chat's
  messages (user bubbles, delegation results, completion cards) rendered into
  another chat and then stuck there forever is closed at three layers: chat
  switches now genuinely wipe the previous view, a late session-create from an
  abandoned draft can no longer take over the chat you moved on to, and the
  transcript cache only persists under the session it actually belongs to.
- **Concurrent chats stream live.** Starting a second chat while the first is
  running no longer tears down the live view mid-turn — the URL pin re-run is
  now a zero-cost rebind, so tool cards, status, and the spinner stay painted
  continuously and there is no deaf gap or accidental third session.
- **Sub-agent drill-in shows the work.** Opening a running sub-agent's view
  now streams its thinking, tool calls, and lifecycle live instead of a blank
  page until the run finished.
- **Steering is honest.** "Steer now" no longer silently does nothing — it
  re-targets the actually-running session, forwards into a live delegation's
  child agents, and every steered message gets a status chip ("Steering —
  applies at the next tool result", "Queued — applies when the delegation
  returns") that flips to "Applied mid-run" the moment it lands. Failures
  show an error instead of vanishing.
- **Reconnect actually reconnects.** A dropped socket while idle now repairs
  itself within seconds (and immediately on your next send); queued messages
  drain in order, and a gateway restart no longer leaves the chat wedged in a
  permanent busy state.
- **Delegations are visible while they run.** A delegating turn now shows
  "Delegating — <goal>", the child's live thinking preview, real agent-step
  counts, and a token meter that includes the child's work — instead of
  "Planning · 0 out" for minutes.
- **Your sidebar is yours again.** Telegram/Discord gateway sessions no
  longer appear in the desktop session list — only chats you actually
  started there.

## The gateway heals itself after updates

Three silent-death modes from real customer incidents, all closed:

- **Stale code in memory.** After an auto-update swapped the app bundle, the
  long-running gateway kept executing the old code indefinitely. It now
  fingerprints the bundled code and restarts itself (between turns) when the
  bundle changes — covering Telegram-only customers who never open the app.
- **Unloaded launchd job.** An update could leave the gateway service booted
  out of launchd entirely, killing Telegram and cron until someone ran
  terminal commands. `elevate gateway install` now reloads an unloaded job,
  and the desktop app verifies plist + loaded + running on every launch and
  repairs whatever is missing.
- **Agents denied their own tools.** Onboarding had pinned the experimental
  "auto" tool profile into every install's config, so a per-message
  classifier sometimes stripped terminal/file/skill access on real work
  requests ("`.env` isn't available in this chat"). Config-pinned "auto" is
  retired; agents keep their configured capabilities.

## Cron and delegation, humanized

- **Deliveries read like a person.** "I ran 'Morning briefing' — here's what
  I found:" instead of the machine header with job IDs and stop-instructions.
- **The agent knows what it sent you.** Cron and heartbeat deliveries are now
  recorded into the chat they were delivered to, so a follow-up question
  lands in a conversation that actually contains the result.
- **Handoff chains roll up.** A 10-step pipeline delivers one summary
  message, not ten micro-updates — and the internal handoff jobs no longer
  clutter the Automations page.
- **Telegram delegations don't block the conversation.** Delegating from a
  platform chat returns instantly; the result folds into the agent's next
  reply (or it wakes and reports on its own), same as the dashboard.
- **No more "Skill(s) not found" spam.** Retired skill names left over in
  older agent definitions now skip silently instead of warning on every
  scheduled run.
