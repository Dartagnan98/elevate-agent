# Elevate Agent-OS — faithful port of CTRL Flow's `/ai/*` (2026-06-04)

> Source of truth: the CTRL Flow Next.js app at `~/claudeclaw/app/src/app/ai/*` +
> `~/claudeclaw/app/src/cortex/*` (the agent-management UI for the cortextOS fleet). This is
> a **faithful** map (real schemas/routes/components), not a paraphrase.
> Already in Elevate (skip): skills-per-agent, crons, heartbeats.
> Porting: **Experiments page · Goals · Settings + model picker · Tasks (dispatch) · Approvals/Decisions kanban**.

## Architecture decision

CTRL Flow stores everything as **JSON files in agent dirs**, caches them in **SQLite via `sync.ts`**,
and writes by shelling **`bus/*.sh`** + **IPC daemon wake**. Elevate does NOT carry any of that over:
- **"Agent" = dashboard surface** (Admin, Leads, …). Data lives under `accounts/<key>/heartbeats/<surface>/`.
- **Storage**: per-account scoping you already have (`elevate_op_<account_key>` SQLite for tasks/approvals; the
  surface dirs for experiments/goals/config — those are already files, keep them).
- **Writes**: direct FastAPI handlers in `web_server.py`. No shell scripts, no IPC, no daemon wake — a
  surface's heartbeat loop is the consumer (it drains queued work on its next scheduled run; drafts-only).
- **Read stats are always computed at read time, never persisted** (CTRL Flow rule — keep it).
- **Nav**: a new top-level **"Agents"** (or "Fleet") section with pages: Surfaces, Experiments, Goals, Tasks,
  Approvals, Settings. "Experiments needs its own page" → a dedicated route, not a tab on Heartbeat.

---

## 1. Experiments page  (#1 ask — read-only, data already exists)

**CTRL Flow:** `experiments/{config.json (approval_required + cycles[]), history/<exp_id>.json, learnings.md}`
per agent. `GET /api/ai/experiments` = `scanExperiments()` walks every agent, reads config+history+learnings,
**computes** stats (`total/running/proposed/completed/kept/discarded`, `keepRate=round(kept/(kept+discarded)*100)`).
UI: 5 StatTiles (Cycles/Running/Completed/Keep Rate/Total) + 3 tabs **By Agent · Timeline · Learnings**. No writes.

**Experiment record** (`history/<id>.json`): `id (exp_<ts>_<b36>), agent, metric, hypothesis, surface, direction
(higher|lower), window, measurement, status (proposed|running|completed|crashed|discarded), baseline_value,
result_value, decision (keep|discard|null), learning, changes_description, experiment_commit, tracking_commit,
created_at, started_at, completed_at`.

**Elevate port** — the surface-heartbeat skill already writes this exact shape under
`accounts/<key>/heartbeats/<surface>/experiments/`. So:
- **FastAPI** `GET /api/heartbeats/experiments[?surface=]` (web_server.py): glob
  `<account_data_dir>/heartbeats/*/experiments/`, read config cycles + history/*.json (sort `created_at` desc) +
  learnings.md, compute the same stats, return `{ surfaces:[{surface, cycles, experiments, learnings, stats}], summary }`.
  Read-only. (Writes stay owned by the heartbeat EXPERIMENT loop.)
- **React** `ExperimentsPage.tsx`: 5 stat tiles + 3 tabs. Port helpers verbatim: `timeAgo`, `StatusChip`,
  `DecisionChip`, `metricDelta` (direction-aware coloring), keep-rate tone bands (≥70 sage / ≥40 amber / coral).
- **This finishes "separate the experiment loop"**: the experiment data already lives apart from the work
  history; this just gives it its own page instead of being buried in the heartbeat card.

## 2. Goals  (per-surface)

**CTRL Flow:** two systems — org-level rich (`goals.json`: `{north_star, daily_focus, bottleneck, goals:[{id,
title, progress 0-100, order}]}`, drag-reorder, server actions add/update/delete/reorder) and per-agent flat
(`{focus, goals:string[], bottleneck}` via `GoalsTab`, PATCH regenerates `GOALS.md`). Goal history derived from
the event log.

**Elevate port** — per-surface, use the **rich Goal[] model** (progress bars + reorder fit a dashboard):
- File `accounts/<key>/heartbeats/<surface>/goals.json` = `{bottleneck, daily_focus, daily_focus_set_at,
  goals:[{id,title,progress,order}], updated_at}` (tolerant reader: coerce legacy string entries).
- **FastAPI** `GET /api/heartbeats/surfaces/{surface}/goals`; `PATCH …/goals` (replace goals[] / set bottleneck /
  daily_focus; validate title ≤200, clamp progress 0-100, order=max+1 on add, atomic write, stamp updated_at).
  History: append `goals_history.jsonl` per write (Elevate has no event bus).
- **React**: port `GoalsList` + `GoalItem` (title + 0-100 slider + delete; drag-reorder needs `@dnd-kit` — ship
  v1 without reorder to skip the dep) + `GoalProgress`/`GoalProgressList` for read-only surface-card summaries.
- Heartbeat runs READ goals.json as the surface's north-star (feeds the work loop).

## 3. Settings + model picker  (extends the config work already shipped)

**CTRL Flow:** per-agent `config.json` edited by the Settings tab. Editable allowlist: `timezone,
day_mode_start, day_mode_end, communication_style, approval_rules{always_ask,never_ask}, max_session_seconds,
max_crashes_per_day, startup_delay, model, ctx_warning_threshold, ctx_handoff_threshold`. PATCH validates
(HH:MM, approval shape), allowlist-merges, writes, notifies agent. **`model` is FREE TEXT — no picker.**
UI: two cards (Operational config + Agent config), each saves independently. `approval_rules` categories:
`['external-comms','financial','deployment','data-deletion']` with mutual-exclusion checkboxes.

**Elevate port** — extend `accounts/<key>/heartbeats/<surface>/config.json` (already has goal/cadence/experiment/
enabled). ADD: `model, timezone, day_mode_start, day_mode_end, communication_style, approval_rules`.
- **FastAPI** `GET /api/heartbeats/surfaces/{surface}/config` (already partly there) + `PATCH …/config`
  (allowlist-merge — preserve goal/experiment/playbook; validate HH:MM + approval shape + `model ∈` known list).
  **`GET /api/models`** returning Elevate's model metadata (`agent/model_metadata.py`: id, label, context len) —
  so Elevate ships a **real model dropdown** the cortex UI never had.
- **React** `SurfaceSettings`: Operational card (timezone, day/night HH:MM, comms style, two approval checkbox
  groups) + Agent card (model `<select>` from `/api/models`, max_session). Keep the two-section independent-save
  + HH:MM/approval validation. Surface it from the Heartbeat surface card → "Settings".
- This also delivers **day/night**: `day_mode_start/end` here; the scheduler checks `is_day_mode(surface)` (port
  `detectDayNightMode`) and gates night = quiet + the experiment/maintenance window.

## 4. Tasks  (give tasks to surfaces)

**CTRL Flow:** JSON file per task `orgs/<org>/tasks/<id>.json` synced to SQLite. Schema: `id, title,
description, status(pending|in_progress|blocked|completed), priority(urgent|high|normal|low), assignee, project,
needs_approval, created_at, updated_at, completed_at, notes, outputs[]`. Dispatch (`task-dispatch.ts`):
create-task file → IPC `start-agent` + `wake`. UI: 4-column kanban (Pending/In Progress/Blocked/Completed Today,
**click-only, not drag**) + CreateTaskDialog (Title/Description/Assignee-from-live-agents/Priority/Project/
NeedsApproval) + TaskCard (avatar, priority badge, deliverables count, approval badge).

**Elevate port** — per-account SQLite table `surface_tasks` (no JSON files, no IPC):
- Columns: `id, title, description, status, priority, assignee(=surface or 'human'), project, needs_approval,
  created_at, updated_at, completed_at, notes, outputs(json)`. Same lifecycle enum + kanban columns.
- **FastAPI** `GET/POST /api/surface-tasks`, `GET/PATCH/DELETE /api/surface-tasks/{id}`. **Dispatch = enqueue**:
  POST inserts a row assigned to a surface; that surface's next heartbeat WORK run drains pending tasks
  (drafts-only). `assignee='human'` = punt to the operator (shows in Approvals "Your Tasks"). No daemon/IPC.
- **React** `TasksPage`: Board/List toggle, `KanbanBoard` (4 cols, click-to-open), `TaskCard`,
  `CreateTaskDialog` (assignee dropdown = surfaces + human), `TaskDetailSheet` (status change + delete).

## 5. Approvals / Decisions kanban  (dashboard-only)

**CTRL Flow:** JSON per approval in `approvals/{pending,resolved}/<id>.json`. Schema: `id, title,
category(deployment|cost|access|other), description, status(pending|approved|rejected), requesting_agent,
created_at, resolved_at, resolved_by, resolution_note`. PATCH resolve → bus moves file pending→resolved. UI: 3
tabs **Your Tasks · Approvals · History**, `ApprovalCard` w/ inline Approve/Reject; an experiment JSON can be
embedded in `description` and rendered via `ExperimentContext`. Approve→execute exists in the bridge path
(`/api/cortextos/approvals/[id]/apply` actually sends).

**Elevate port** — reuse the **drafts-only** model (surfaces already propose, human approves):
- SQLite `surface_approvals`: `id, title, category, description, status(pending|approved|rejected), surface,
  created_at, resolved_at, resolved_by, resolution_note`. Created internally by a heartbeat run when it produces
  something needing sign-off (not a public POST).
- **FastAPI** `GET /api/surface-approvals?status=pending|resolved` (+surface/category) + `PATCH …/{id}`
  `{decision, note}`. **Approve→execute**: model on `.../apply` — on approve, dispatch the drafted side-effect
  via Elevate's existing send path; on reject, discard. DRY_RUN/drafts-only stays the default.
- **React** `ApprovalsPage`: 3 tabs, `ApprovalCard` + `ApprovalDetailDialog`, keep the embedded-experiment render
  (surfaces run EXPERIMENT loops). Badge count on the nav.
- **Constraint:** MEMORY `feedback_no_telegram_approvals` — **dashboard only**. Badge + optional web-push;
  NO Telegram approve/reject.

---

## Build order (recommended)

1. **Experiments page** — read-only, data exists; smallest + the #1 ask. Proves the "separate experiments" goal.
2. **Settings + model picker + day/night** — extends the surface `config.json` already shipped; unlocks day/night.
3. **Goals** — per-surface goals.json + GoalsList UI.
4. **Tasks** — `surface_tasks` table + kanban + dispatch-to-surface (heartbeat drains).
5. **Approvals/Decisions** — `surface_approvals` + 3-tab page; approve→execute on the drafts pipeline.
6. **Nav shell** — the "Agents" section tying the pages together (do alongside #1).

## Reference files (CTRL Flow)
- Experiments: `app/ai/experiments/page.tsx`, `cortex/lib/experiment-utils.ts`, `api/ai/experiments/route.ts`.
- Goals: `cortex/lib/{actions,data}/goals.ts`, `cortex/components/strategy/{goals-list,goal-item}.tsx`,
  `api/ai/agents/[name]/goals/route.ts`.
- Settings/model: `cortex/components/agents/settings-tab.tsx`, `api/ai/agents/[name]/config/route.ts`,
  `cortex/lib/markdown-parser.ts`.
- Tasks: `app/ai/tasks/page.tsx`, `cortex/components/tasks/{kanban-board,task-card,create-task-dialog}.tsx`,
  `cortex/lib/task-dispatch.ts`, `api/ai/tasks/route.ts`, `cortex/lib/{sync,data/tasks}.ts`.
- Approvals: `app/ai/approvals/page.tsx`, `cortex/components/approvals/{approval-card,experiment-context}.tsx`,
  `api/ai/approvals/[id]/route.ts`, `api/cortextos/approvals/[id]/apply/route.ts`.
- Elevate landing points: `web_server.py:6245` (`get_heartbeat_surfaces`), `HeartbeatPage.tsx`,
  `cli/agent/model_metadata.py`, `cli/cron/jobs.py`, `cli/elevate_cli/data/{dispatch,review}.py`.
