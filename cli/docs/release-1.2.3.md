# Elevate 1.2.3 — release notes

The fleet release: agents now have real loadouts, an orchestrator can hand work
to named specialists, leads/deals update themselves as the agent works, and the
subagent chat experience is first-class. Plus onboarding, persona, and heartbeat
fixes.

## Agents & the fleet
- **Picking an agent loads its real tools.** Selecting Executive Assistant,
  Admin, Outreach, etc. now binds that agent's full toolset — no more falling
  back to a generic set and reverse-engineering the database.
- **Orchestrator → specialists.** The primary agent can spawn a subagent that
  runs AS a named specialist (Admin with `admin_deal`, Outreach with
  `lead_status`, …) — with that specialist's persona, full loadout, and skills,
  even tools the parent doesn't have.
- **Subagent chat is first-class.** Drill into any subagent's own thread from
  Background tasks: it shows a glowing "In subagent · <Agent>" badge, a "Back to
  chat" button, only its own clean task (not your raw prompt), the right
  working/settled state, and one card per delegation.
- The agent picker menu opens reliably (was clipped).

## Leads & Admin intelligence
- **The board updates itself.** When the agent works a deal/contact, an activity
  marker + freshness bump lands automatically; a board-sync nudge reminds it to
  record stage/checklist changes (deals) or label a lead's status.
- **lead_status tool** lets the agent set a lead's pipeline status, heat, and
  follow-up as it works it — and the next heartbeat skips leads it already
  handled (and sees the status it left them in).

## Onboarding & persona
- **Stronger SOUL.md** — the agent is empowered to take a password/2FA and log
  into the realtor's own accounts to do the work, instead of handing it back.
  It now also names its **sources of truth** (the ADMIN/LEADS onboarding memory
  + USER.md/MEMORY.md) and treats them as authoritative — no re-asking for setup
  details that are already recorded. **This persona upgrade reaches existing
  installs**, not just fresh ones (an unmodified default is upgraded; a
  hand-edited SOUL.md is left untouched).
- **Agent roster in context** — every agent's prompt now carries a dynamic
  "who does what" list of the account's fleet, so the orchestrator knows which
  specialist owns a request and delegates to it (`delegate_task(agent=<id>)`).
- **CRM is whatever you picked** at onboarding (never assumes Lofty), and
  CRM-status-push is now a profile fact surfaced in `ADMIN_ONBOARDING.md`.
- **LEADS_ONBOARDING.md** — the leads peer of the admin onboarding doc, so the
  outreach agent finally knows how this realtor's lead flow is set up.

## Heartbeats
- The focused-heartbeat split now applies to **existing** installs, not just
  fresh ones — old monolithic Leads/Admin heartbeats are retired and replaced by
  the focused units (state carried over).

## Housekeeping
- Empty draft "General session" rows no longer clutter the sidebar.
- A subagent session is its own conversation (its own lineage root), so opening
  it loads its thread instead of bouncing to the orchestrator.

_Known minor: while a turn's reasoning streams live it can briefly show twice;
it self-corrects on reload (the stored data is correct)._
