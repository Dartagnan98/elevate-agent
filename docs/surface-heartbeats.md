# Surface Heartbeats — theta-wave structure for Elevate heartbeats (design, 2026-06-03)

> Goal (Dartagnan): give each dashboard **surface** (Admin, Leads first) its own heartbeat
> that **does the surface's work on a cadence AND periodically experiments to improve how it
> does it** — compounding via accumulated learnings. Mirror cortextOS theta-wave
> (`config → run → history → learnings`, plus the experiment keep/discard loop), but
> Elevate-native (no `cortextos bus` CLI — the agent manages state via files).
> Decisions: **loop = Both** (work + experiment), **surfaces = Admin + Leads** to start.

## Where it sits today
- An Elevate heartbeat is already a cron job tagged `origin.type === "heartbeat"`
  (`HeartbeatPage.tsx`): interval + instructions → agent wakes in a fresh session → reports
  to the feed. That IS the work-loop half, minus structure/history/learnings.
- cortextOS theta-wave (`autoresearch` skill): cycles in `experiments/config.json`,
  loop = gather-context → evaluate-previous → hypothesize (exploit/explore) → create → run →
  measure → keep/discard → learn. State in `experiments/{config.json, active.json, history/}`
  + `learnings.md`. Dashboard scans `orgs/*/agents/*/experiments/`.

## File structure (per account, per surface)
```
accounts/<key>/heartbeats/<surface>/         # <surface> = admin | leads
  config.json        # cadence, surface goal, experiment cadence + cycle (metric/direction/window/measurement)
  learnings.md       # accumulated work + experiment learnings — injected into every run's prompt
  history/<ts>.json  # one per WORK run: {ran_at, checked, did, found, actions, summary}
  experiments/
    active.json      # the running experiment: {id, hypothesis, surface_change, baseline, started_at, window}
    history/<id>.json# completed: {hypothesis, baseline, result, decision: keep|discard, learning, ts}
```
Seeds shipped in the repo (so every realtor gets Admin+Leads heartbeats on onboarding); the
home dir is the live per-account copy.

## The loop (what the runner skill does each fire)
**Work loop (every cadence):**
1. Read `config.json` (goal) + `learnings.md` (what's worked).
2. Do the surface's work — the agent already has the surface's tools/skills:
   - **Leads**: new/changed leads since last run → surface hot ones + why; overdue follow-ups +
     today's showings; draft (never send) next-touch for anyone gone quiet.
   - **Admin**: calendar + tasks → flag deadlines/conflicts/anything needing the realtor;
     reconcile today's agenda.
3. Append `history/<ts>.json` (structured: what it checked/did/found).
4. Distill durable insight into `learnings.md` (capped, deduped).
5. Deliver a tight summary to the feed (the existing heartbeat delivery).

**Experiment loop (every `experiment_every_n_runs`):**
1. Gather context: read `experiments/history/` (keeps build on, discards avoid) + keep rate.
2. If `active.json` exists: measure the metric (config measurement), decide keep/discard,
   write `experiments/history/<id>.json`, fold the learning into `learnings.md`, clear active.
3. Hypothesize an improvement to HOW the heartbeat works (exploit a 3×-kept pattern, or
   explore after 3× discards). Evidence-backed.
4. Apply the change to the surface heartbeat's own playbook (a field in `config.json` or a
   prompt fragment — NOT the realtor's data), set `active.json`, measure next cycle.

Metrics per surface (the dependent variable): Leads → next-touch reply rate / hot-lead
catch latency; Admin → tasks-slipped count / agenda accuracy. Start qualitative (1–10
self-score with justification) until real metrics wire in.

## Cron integration
Two jobs, `origin.type === "surface-heartbeat"`, `origin.surface ∈ {admin, leads}`, each
invoking the **`surface-heartbeat` skill** with its surface. Stays off the power-cron page,
shows in the Heartbeat surface. Per-account-scoped like all cron (rides the scoping work).

## Build phases
1. **Scaffold** the `heartbeats/{admin,leads}/` structure + default `config.json` + seed
   `learnings.md`. (DONE this session — Dartagnan's account.)
2. **`surface-heartbeat` skill** — the loop above, Elevate-native, parameterized by surface.
   (NEXT — the meaty piece.)
3. **Cron jobs** — Admin + Leads heartbeats invoking the skill on their cadence.
4. **Seeding** — on account onboarding, seed both surfaces so every realtor gets them
   ("good for everyone").
5. **UI** — Heartbeat page → per-surface cards: cadence, last run (history), learnings,
   active/recent experiments + keep rate. (Mirror cortextOS experiments page.)

## Open choices (sane defaults chosen, change freely)
- Cadence: Leads 2×/day (08:00, 15:00), Admin 1×/day (07:30). Experiment every 7 runs.
- Experiments tune the heartbeat's OWN behavior, never auto-touch the realtor's leads/data.
- Approval gate off by default (drafts only; nothing sent without the realtor).
