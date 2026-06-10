# Elevate 1.2.4 — release notes

The fleet rebuild. Every agent is rebuilt from a strong baseline into a real
specialist with a pre-loaded skill loadout, the two worker boards (Admin and
Leads) get focused, context-first heartbeats wired to the realtor's own systems
of record, and the Executive Assistant + Analyst finally get the heartbeats they
were missing. This release **completely replaces** the prior fleet (beta).

## The 7 super-agents (rebuilt)
- **Executive Assistant** — orchestrator/chief-of-staff. Now carries its full
  heartbeat doctrine in-prompt: fleet-health sweep, approval/human-task
  escalation (on the dashboard, never Telegram), morning goal-cascade + evening
  summary, per-cycle accountability targets. 20 skills.
- **Admin · Transaction Coordinator** — province-transaction-guide as source of
  truth (jurisdiction-driven, never US-hardcoded), form completion (WEBForms),
  signatures, conditions/subjects, document routing, brokerage compliance file,
  closing. Reads the realtor's **connected transaction-management platform**
  (SkySlope / Lone Wolf / dotloop — whatever they set at onboarding, never
  assumed). 18 skills.
- **Inside Sales Agent** (renamed from ISA Agent) — speed-to-lead, cadences,
  hot-lead watch, re-engagement, real discovery (upfront contract, SPIN/Gap/
  Sandler), objection handling, **appointment setting**, and **CRM write-back**
  to the realtor's connected CRM (Lofty / FUB / GHL / kvCore / BoldTrail — never
  assumed). 13 skills.
- **Marketing & Ads** — offer-first (Hormozi value equation, grand-slam offers,
  lead magnets), paid acquisition (Breakdown Effect, tracking-as-infrastructure,
  Core Four / Rule of 100), and lifecycle email (segment over broadcast, exit
  conditions, consent as infrastructure). 16 skills.
- **Social Media** — retention-first, platform-native, short-video shot-list
  direction (3-second hook, beats-to-audio, muted captions). 11 skills.
- **Analyst** — pipeline analytics + market/CMA support, plus in-prompt
  heartbeat: system-health + agent-liveness monitoring + metrics. 10 skills.
- **Theta Wave** — full system-review loop (scan → classify → author/propose
  cycles within policy). 7 skills.

## Context-first focused heartbeats
Each worker board runs **focused** heartbeat units (not one mega-pass), each
reconciling real state before acting (skip what's already handled) and surfacing
only genuine changes/questions — **notify-on-change**.
- **Admin (5 units):** Transaction Board Review (morning, reads their TM
  platform) · Inbox & Message Triage · Document Routing · Stage/Deadline/
  Condition Watch (walks deals by board stage + province-guide checklist) ·
  Agenda & Conflicts.
- **Leads (5 units):** New-Lead Response · Follow-up Sweep · Hot-Lead Watch ·
  Appointment & Showing Confirmation · Re-engagement.
- **New:** Executive Assistant (4 units) and Analyst (3 units) heartbeats —
  these surfaces previously had **no firing heartbeat**. Cortext cadence
  (fleet-health 4h, approvals 2h, AM/PM review; analyst system-health 4h,
  usage pulse 2h, nightly metrics). All ship **opt-in / OFF** — turn them on
  from the Heartbeat page.

## Complete replacement (beta)
On upgrade, each account runs a **one-time** reset: the old stored agents, the
old surface heartbeat/automation crons, and the surface registry are purged, then
the new fleet + heartbeats reseed clean. Sentinel-gated (runs once; never wipes a
customization made after the upgrade). No leftover/conflicting heartbeats.

_Everything stays draft-only and approval-gated; external sends, deletions, and
financial/legal/credential actions still require sign-off._
