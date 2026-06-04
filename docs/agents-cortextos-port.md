# Porting cortextOS agent-quality to Elevate (review + plan, 2026-06-04)

> Goal (Dartagnan): bring the things that make cortextOS agents good into Elevate's
> agents — **experiments separated from work**, **per-agent `SOUL.md` + context bundle**,
> **day/night automation**, and the way cortextOS **separates agents properly**. Add the
> stuff the agents actually use.

## 1. How cortextOS does it (the patterns worth porting)

Each agent is a **directory** under `orgs/<org>/agents/<name>/` that fully owns its identity,
config, and state. The daemon launches a **thin** session prompt — *"Read AGENTS.md and all
bootstrap files listed there"* — and the agent **self-loads** its own context. That's the
core move: separation by directory + a bootstrap index, not one giant shared prompt.

**The per-agent context bundle** (each a small focused file):
- `SOUL.md` — behavioral DNA / voice. (gary's: "Data first, then strategy. No em dashes.
  No sycophancy. Breakdown Effect before any pause." — real operating rules, not fluff.)
- `IDENTITY.md` — name, role, emoji, vibe, work-style, hard boundaries ("strategy only,
  never touches the account").
- `GOALS.md` / `goals.json` — objectives + north star.
- `HEARTBEAT.md` — the recurring checklist the agent runs each beat.
- `LEARNINGS.md` — accumulated, compounding insight (read every run).
- `MEMORY.md`, `USER.md`, `SYSTEM.md`, `TOOLS.md`, `LOADOUT.md`, `local/PROTOCOL.md`,
  `AGENTS.md` (the bootstrap index), `ONBOARDING.md` (first-boot protocol).

**`config.json` per agent** drives behavior:
- `day_mode_start` / `day_mode_end` + `timezone` — the **day/night window**.
- `approval_rules` — `always_ask` (external-comms, financial, deployment, data-deletion) /
  `never_ask`.
- `communication_style`, `model`, `runtime`, `crons`, `max_session_seconds`, `telegram_polling`.

**Day/night automation** — `detectDayNightMode(timezone)` → `day` (08–22) | `night`. The
daemon checks the agent's window every beat; behavior is gated by mode (day = active/proactive,
night = quiet — no proactive pings; the natural window for maintenance/experiments).

**Experiments are a SEPARATE system** (this is the big one):
- `experiments/{config.json (cycles[]), history/, learnings.md, surfaces/}` per agent.
- Skills `theta-wave` (system-level review the analyst orchestrates — challenge, evaluate which
  agents are improving vs stuck, propose changes) + `autoresearch` (an agent's own research/
  experiment cycle).
- Engine `src/bus/experiment.ts` + `bus/{create,run,evaluate,list}-experiment.sh`.
- `experiments/config.json` = `{approval_required, cycles:[]}` — experiments have their **own
  approval gate**, their own history, their own learnings — fully decoupled from work output.

**Isolation** — per-agent `.mcp.json` (scoped MCPs), `.env`/`.ctrl-flow-token`/`.cortextos-env`
(scoped creds), `--add-dir` work-repo access, output `redact.ts`. Plus **handoff** docs (restart
with memory intact) and crash recovery.

## 2. What Elevate has today

- **One account-level agent** (`run_agent.py`) + cron jobs (the surface heartbeats + the
  surface automations we just shipped).
- It already loads `~/.elevate/SOUL.md` as primary identity + `AGENTS.md`/`.cursorrules` via
  `build_context_files_prompt` (run_agent.py:4725, 4839). So the **SOUL + bootstrap-index
  pattern already exists** — but at the ACCOUNT level (one soul for everything).
- Surface workspaces already exist: `accounts/<key>/heartbeats/<surface>/{config.json,
  learnings.md, history/, experiments/}`. Config has goal + cadence + an `experiment` block.
- **Gaps vs cortextOS:** (a) no per-surface `SOUL`/`IDENTITY`/`GOALS`/`PROTOCOL` — surfaces share
  the account soul + a generic skill; (b) **experiments are COMBINED into the
  `surface-heartbeat` skill's loop**, not a separate system; (c) no day/night; (d) `config.json`
  lacks approval_rules / comms-style / model per surface.

## 3. The port — phased

### Phase 1 — Per-surface context bundle (the "soul + little things")
Give each surface (Leads, Admin, + future) its own bundle inside its workspace dir:
```
accounts/<key>/heartbeats/<surface>/
  AGENTS.md      # bootstrap index: "you are the <surface> agent, read these in order"
  SOUL.md        # voice + operating rules for THIS surface (Leads ≠ Admin)
  IDENTITY.md    # name, role, boundaries (drafts-only, never sends)
  GOALS.md       # the surface's north star + this-week focus
  PROTOCOL.md    # step-by-step of the work loop (moved out of the skill)
  config.json    # (extended — see Phase 3/4)
  learnings.md   history/   experiments/   (already exist)
```
- Seed defaults in the repo (`cli/skills/real-estate/surface-heartbeat/seeds/<surface>/`) so every
  realtor gets them; the home dir is the live editable copy. Realtor identity stays
  de-hardcoded (`{agent_name}`/`{brokerage}` filled from `admin_setup_profile`).
- The `surface-heartbeat` skill's first step becomes: "Read `<workspace>/AGENTS.md` and the
  bundle it lists" — exactly the cortextOS bootstrap move. `run_agent` already supports SOUL +
  context-file loading; point it at the surface dir for surface runs.

### Phase 2 — Separate the experiment loop from work (the priority)
Today the `surface-heartbeat` skill does WORK + EXPERIMENT in one fire. Split them:
- **Work skill** (`surface-heartbeat`) — only does the surface's job, logs `history/`, distills
  `learnings.md`. No experiment logic.
- **Experiment skill** (new `surface-experiment`, mirrors cortextOS `autoresearch`) — runs on its
  OWN cadence (e.g. weekly, not every beat), reads `experiments/config.json` cycles, evaluates the
  active experiment (keep/discard against the metric), writes `experiments/history/<id>.json`,
  folds the learning into `learnings.md`, hypothesizes + activates the next. Its own
  `approval_required` gate, separate from work.
- A separate cron job per surface for the experiment cycle (`origin.type="surface-experiment"`),
  seeded paused like the rest.

### Phase 3 — Day/night automation
- Add `timezone` + `day_mode_start`/`day_mode_end` to each surface `config.json` (default
  08:00–22:00, realtor's TZ from `admin_setup_profile`).
- A small `is_day_mode(surface)` helper (port `detectDayNightMode`) the scheduler checks before a
  surface beat. Design choice for what night gates: **night = quiet** (queue drafts, don't surface
  them to the realtor until morning) and **night = the experiment/maintenance window** (run the
  separate experiment cycle overnight so it never competes with daytime work or pings the realtor).

### Phase 4 — Richer per-surface `config.json`
Bring it to cortextOS parity: `approval_rules` (always_ask: send-message/financial; never_ask),
`communication_style`, per-surface `model` override, `max_session_seconds`. Surface these in the
Heartbeat UI cards next to the existing enable toggle.

### Phase 5 — System-level "theta wave" review
A weekly account-level cron (mirrors `theta-wave`): scan every surface's `experiments/history/` +
`learnings.md`, evaluate which surfaces are improving vs stuck, surface a short "fleet review" to
the realtor (drafts-only), and propose which experiments to keep/kill. The analyst/orchestrator
loop over the per-surface experiment loops.

## 4. Decisions / open questions
- **Granularity:** surfaces (Leads/Admin) as the "agents," or also split sub-agents (e.g. Outreach
  vs Follow-up within Leads)? Start at surface level.
- **One model or per-surface model?** cortextOS sets `model` per agent; Elevate could let Admin run
  a cheaper model than Leads.
- **Night behavior:** quiet-only, or quiet + experiment-window? (Recommend the latter.)
- **Where souls live:** repo seeds (ship to all) + home-dir live copy (realtor-editable), same
  split as the heartbeat workspaces. Keep realtor identity de-hardcoded.
- Reference implementations: cortextOS `src/daemon/agent-process.ts` (bootstrap prompt),
  `src/bus/heartbeat.ts` (`detectDayNightMode`), `src/bus/experiment.ts` + `community/skills/
  {theta-wave,autoresearch}` (separate experiment loop).
