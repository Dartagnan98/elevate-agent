# Elevate — product truth

What Elevate verifiably does today. Agents answer capability questions from
this file; anything not listed here is "I can't confirm that", never a promise.
Update this file in the same change that ships a user-facing capability.

## Surfaces
- macOS desktop app (auto-updating) wrapping a local dashboard; everything runs
  on the user's own Mac with their logins and data staying local.
- Chat with the Executive Assistant plus specialist agents (Admin/transaction
  coordination, Outreach/inside sales, Marketing & Ads, Social Media, Analyst,
  Theta Wave/fleet improvement) — per-agent lanes, handoffs, delegated runs.
- Agent Hub: per-agent identity and soul editing, skill loadouts, memory
  policies, heartbeats.

## Deal & transaction work
- Admin hub with deal kanban cards: province-aware stages, checklists, fields,
  attached artifacts, per-deal chat, and background runs that write results
  back to the card.
- CMA, offer-kit, and listing-kit wizards; clause picker; CPS flow.
- Agents provide facts and options, never legal or financial advice.

## Leads & outreach
- Leads lanes (new outreach, hot-lead watching, follow-ups) with a unified
  multi-channel inbox.
- AI-drafted replies and outreach that queue for the user's approval — agents
  never send outbound messages, spend money, or change pricing on their own.
- Connected CRM stays the system of record; interactions are written back.

## Channels
- iMessage/SMS through the user's own Mac number (native transport).
- WhatsApp via a paired bridge. Email through connected providers.

## Automation & memory
- Scheduled cron jobs and per-agent heartbeats that run without the user
  present and deliver results to chat, channels, or cards.
- Persistent memory across sessions with per-agent memory policies; long
  sessions compact automatically and continue.

## Execution
- Managed browser automation in a visible Chrome window cloned from the user's
  real profile (logins and MFA persist between runs).
- Native-app control on the Mac (screenshots + mouse + keyboard) when a
  browser can't reach the work.
- Document production: PDFs, presentations, diagrams, and graphics.
- Installable skill library, including real-estate packs.

## Known limits (state plainly when asked)
- macOS-first; agents run on the user's machine, not a cloud.
- No direct MLS API access — listing/portal data arrives through the managed
  browser under the user's own logins.
- Every outbound send, spend, and pricing change requires explicit approval.
