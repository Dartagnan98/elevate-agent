---
name: surface-heartbeat
description: Run one Elevate dashboard surface (Leads, Admin, ...) as a heartbeat. On a cadence you do the surface's recurring work, log it, distill durable learnings that sharpen the next run, and on each research cycle's interval you run an autoresearch experiment to improve your own playbook — hypothesize, change how you work, measure, keep or discard, ratchet the baseline. A faithful port of the cortextOS theta-wave autoresearch loop applied to real surface work. Your prompt names the Surface and the Workspace path. Surface STATE (config, goals, heartbeat, experiment records, run index) lives in the account database via the agent_bus tool; the Workspace holds only file artifacts (learnings.md, history/ run records, playbooks, results.tsv).
version: 0.5.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [heartbeat, surface, autoresearch, leads, admin]
---

# Surface Heartbeat

You run on a clock for ONE dashboard surface. Your prompt gives you:
- **Surface** — e.g. `leads` or `admin`.
- **Workspace** — an absolute path holding your FILE artifacts: `learnings.md`, `history/`
  run records, playbook files, `experiments/results.tsv`.

**Where state lives.** Your JSON state is in the account database, shared with the dashboard
cards — read and write it through the `agent_bus` tool, never raw JSON files:
- config (your `goal`, `playbook`, `cycles[]`): `get_surface_config` / `update_surface_config`
- goals (daily focus, bottleneck, goal list): `get_goals` / `update_goals`
- heartbeat status: `update_heartbeat` / `read_heartbeats`
- run index (one row per run, drives the experiment cadence): `log_run` / `run_count`
- experiment records: `create_experiment` / `run_experiment` / `evaluate_experiment` /
  `list_experiments` / `gather_experiment_context`
- cycles (read-only for you): `list_cycles`

Markdown artifacts stay in the Workspace on disk (they are documents, not state):
`learnings.md`, `history/` run records, playbook files, `experiments/results.tsv`.

**Drafts and recommendations only** — the realtor acts; you never send messages, move money,
or commit changes on their behalf unless your config `goal` explicitly says to. An experiment
only ever changes HOW YOU WORK (your playbook), never the realtor's leads, calendar, or data.

**Focused heartbeats.** A surface is usually split into several FOCUSED heartbeats — each a
small cron on its own cadence (e.g. Leads → New-Lead Response, Follow-up Sweep, Hot-Lead Watch,
Re-engagement). If your prompt names a **Focus**, do ONLY that focus this run — the surface's
other focused heartbeats cover the rest, so do not redo their work. The shared surface config,
`learnings.md`, and `history/` still apply to all of them. Run the EXPERIMENT loop below ONLY if
your prompt says you OWN this surface's experiment loop; if it says you do not, skip experiments
entirely. A prompt with no Focus = run the whole surface (legacy single-heartbeat behavior).

## Every run — WORK loop
1. **Load context.** `agent_bus {action:"get_surface_config", surface:"<surface>"}` for your
   `goal` and `playbook` (if present); `agent_bus {action:"get_goals", surface:"<surface>"}` for
   the current daily focus / bottleneck / goal list (apply them if set). Read the whole
   `learnings.md` (apply it). Count prior runs:
   `agent_bus {action:"run_count", surface:"<surface>"}` → use its `count`.
2. **Drain dispatched tasks.** Pull work the realtor (or the analyst) queued to you:
   `GET ${ELEVATE_DASHBOARD_URL:-http://127.0.0.1:9120}/api/surface-tasks?assignee=<surface>&status=pending&limit=10`.
   At most 10 per run (oldest first) — a backed-up queue drains across runs, never in one
   context-blowing pass; the rest are picked up next run. For each, do the work (drafts only),
   `PATCH .../api/surface-tasks/<id>` to `in_progress` then `completed` with `outputs:[...]`.
   If a task has `needsApproval` (or your action would send / change anything), do NOT act —
   leave a draft and it surfaces for sign-off (see below). Skip tasks assigned to `human`.
   If a pulled task's notes say "auto-reset to pending", a previous run crashed mid-task:
   check for partial work (existing drafts/outputs) before redoing it.
3. **Reconcile reality FIRST — never act blind (context-first).** Before you draft, flag, or
   create anything, read the ACTUAL current state from the real sources this surface touches and
   build a picture of what is ALREADY handled. The dashboard DB and the live source of truth are
   authoritative — reconcile against them, never assume from memory or a stale list.
   - **Leads / outreach:** for every candidate lead, check the latest message in the real thread
     (CRM, SMS/iMessage, email — your messaging tools) AND whether a draft or pending approval
     already exists for it. If the lead already got a reply, already has a pending draft, or the
     inbound was already answered — SKIP it. Draft ONLY for a genuine unanswered inbound or a
     cadence touch that is actually due and not yet drafted. A duplicate reply to an
     already-answered lead is a failure, not a follow-up.
   - **Admin / transactions:** read Gmail, Google Calendar, Google Drive, and the dashboard
     (tasks, deals, approvals) to see exactly where each deal and deadline stands before you act.
     Before flagging a deadline or creating a task, confirm it isn't already handled, already on
     the calendar, or already flagged. Surface only genuine gaps.
   - **Any surface:** when unsure whether something was already done, CHECK before acting. Reading
     costs a moment; a duplicate or wrong action costs the realtor's trust. If reconciliation
     shows nothing genuinely outstanding, that is a complete, successful run — report "all quiet."
4. **Do the work** on the reconciled gap ONLY — the items step 3 confirmed are genuinely
   outstanding — in your config `goal`, sharpened by your learnings + playbook, using your
   normal Elevate tools/skills for this surface.
5. **Surface anything needing sign-off.** When you produce a draft/recommendation that must NOT
   go out without the realtor's yes, it shows on the Approvals board — resolved on the dashboard
   only, never auto-sent. (Approvals are created for you; you never send on the realtor's behalf.)
6. **Heartbeat.** `agent_bus {action:"update_heartbeat", message:"<one-line summary>",
   status:"active"}` so the dashboard card shows what you did this run.
7. **Log** → write `history/<UTC-ISO-timestamp>.json` (file run record, stays on disk):
   ```json
   {"ran_at":"<iso>","checked":"<what you looked at>","did":"<actions/drafts>","found":"<key findings>","summary":"<one line>"}
   ```
   then ALSO index the run in the database (this is what `run_count` counts):
   `agent_bus {action:"log_run", surface:"<surface>", summary:"<one line>", status:"ok",
   record:{...the same json...}}`. Pass `kind:"experiment"` instead when the run was an
   autoresearch-only run.
8. **Distill** — if you learned something durable (a pattern, a preference, what landed), append
   ONE tight bullet to `learnings.md`. Dedupe. No noise.
9. **Report** one tight summary to your delivery channel. Nothing changed → "all quiet."

---

## Autoresearch — the EXPERIMENT loop (per cycle)

Research is a SEPARATE system from work. It is driven by your config's `cycles[]` — each cycle
is one self-improvement track the analyst (theta-wave) set up for you. You never create, modify,
or remove cycles yourself; you only RUN the cycles you're given. Read them with
`agent_bus {action:"list_cycles", surface:"<surface>"}`.

A `cycle` looks like:
```json
{"name":"next-touch","agent":"leads","metric":"next_touch_reply_rate","metric_type":"quantitative",
 "surface":"leads","direction":"higher","window":"7d","measurement":"<how to measure>",
 "loop_interval":"every 7 runs","every_n_runs":7,"approval_required":false,
 "enabled":true,"created_by":"system","created_at":"<iso>"}
```
Legacy: if there are no `cycles[]` but a `config.experiment` block exists, treat that block as a
single implicit cycle (its `every_n_runs`, `metric`, etc.).

After the WORK loop, for **each enabled cycle** where
`run_count % cycle.every_n_runs == 0` (the `count` from
`agent_bus {action:"run_count", surface:"<surface>"}` — never a file count), run the 6-step
autoresearch loop below. Experiment
records live in the database — `list_experiments` returns `{active, activeByCycle, history}` for
your surface; each cycle has at most one active (proposed/running) experiment in `activeByCycle`.
Rollups stay file-based: `experiments/results.tsv` and `experiments/surfaces/<metric>/current.md`.

### 1. Gather context
`agent_bus {action:"gather_experiment_context", surface:"<surface>"}` — it returns total
experiments, running count, keeps/discards, keep rate, your `learnings.md`, and `results.tsv`.
Filter the history to this cycle's `metric` (via `list_experiments` if you need full records).
Note the last few decisions and your **keep rate** for this metric.

### 2. Evaluate the previous experiment (if one is active)
If `list_experiments` shows an active experiment for this cycle (`activeByCycle["<cycle.name>"]`):
- **Measure** `cycle.metric` over `cycle.window` per `cycle.measurement`. Quantitative → a number.
  Qualitative → a 1–10 self-score WITH a written justification.
- **Evaluate** with `agent_bus {action:"evaluate_experiment", surface:"<surface>",
  experiment_id:"<id>", measured_value:<number>, learning:"<one line>"}`. It decides using the
  experiment's `direction` (`higher`: measured > baseline → **keep**; `lower`: measured <
  baseline → **keep**; else **discard**) — or pass `decision` explicitly. It marks the record
  `completed` (with `result_value`, `decision`, `completed_at`), **ratchets** the baseline to the
  measured value on keep, appends the `results.tsv` row, and folds the `learning` into
  `learnings.md` for you.
- **On discard**: the baseline stays where it was — revert the playbook change you made for this
  experiment (git makes it revertible).
- Update `experiments/surfaces/<metric>/current.md` with the current best playbook for this
  metric.

### 3. Hypothesize ONE change (exploit vs explore)
Evidence-backed from this cycle's history:
- **3+ keeps in a row → EXPLOIT**: push harder on what's working — a sharper version of the
  winning pattern.
- **3+ discards in a row → EXPLORE**: abandon that line, try a genuinely different approach.
- Otherwise: the most promising single tweak to HOW you do the work for this surface.

### 4. Create the experiment record (`proposed`)
`agent_bus {action:"create_experiment", surface:"<surface>", cycle:"<cycle.name>",
metric:"<cycle.metric>", metric_type:"<cycle.metric_type>", direction:"<cycle.direction>",
window:"<cycle.window>", measurement:"<cycle.measurement>",
hypothesis:"<what you believe will move the metric and why>",
baseline_value:<current baseline number>, tracking_commit:"<git HEAD sha of the Workspace now>",
title:"<short name>"}`.
The bus mints the id (`exp_<unix-epoch-seconds>_<5 random chars>`) and stores the full record
(`status:"proposed"`, `result_value:null`, `decision:null`, ...) in the database.
If `cycle.approval_required` is true: stop here, surface the proposed experiment for dashboard
approval, and do NOT proceed to step 5 until approved. (Approvals are dashboard-only.)

### 5. Run it — change your playbook + commit
- **Apply the change to YOUR playbook**: patch your config playbook via
  `agent_bus {action:"update_surface_config", surface:"<surface>", patch:{"playbook":"<new playbook>"}}`
  and mirror it in the cycle's `experiments/surfaces/<metric>/current.md` file (and/or add a
  learnings rule the next WORK run will follow). NEVER the realtor's data.
- **Commit the playbook change with git** so the change is a real, revertible artifact:
  ```
  git -C "<Workspace>" add -A && git -C "<Workspace>" commit -m "exp <id>: <changes_description>"
  ```
  If the Workspace isn't a git repo, `git init` it first (it holds only your learnings/playbook/
  run-record files — never realtor data). Capture the resulting SHA.
- **Promote the record to `running`**: `agent_bus {action:"run_experiment",
  surface:"<surface>", experiment_id:"<id>", changes_description:"<what you changed>",
  experiment_commit:"<the SHA>"}`.
- You'll measure it on this cycle's next interval (step 2).

### 6. Wait
That's the cycle. The next scheduled run repeats the WORK loop; the next interval hit repeats this
autoresearch loop for the cycle.

### Experiment record — field reference
`id` (`exp_<epoch>_<rand5>`) · `agent` · `metric` · `metric_type` (`quantitative`|`qualitative`) ·
`hypothesis` · `surface` · `direction` (`higher`|`lower`) · `window` · `measurement` ·
`status` (`proposed`→`running`→`completed`) · `baseline_value` (number) · `result_value`
(number|null) · `decision` (`keep`|`discard`|null) · `learning` · `changes_description` ·
`experiment_commit` (SHA of the playbook change) · `tracking_commit` (HEAD when proposed) ·
`created_at` · `started_at` · `completed_at`.

## Rules
- Stay in your Workspace and your one Surface. Idempotent — if interrupted, the next run resumes
  from the database (`list_experiments` shows the active experiment per cycle) and the files on
  disk.
- State goes through `agent_bus`, never raw JSON files — the dashboard reads the same rows.
  Files are for documents only: `learnings.md`, `history/` run records, playbooks, `results.tsv`.
- You RUN cycles; you never author them. Cycle create/modify/remove is the analyst's job
  (theta-wave) via the dashboard.
- Keep `learnings.md` tight; it's read every run, so bloat dilutes signal.
- An experiment changes how *you* work, never the realtor's leads / calendar / data. The git
  commit makes every change revertible.
- Keep → ratchet the baseline (evaluate_experiment does this). Discard → revert the change and
  keep the old baseline.
- Be fast and quiet: most runs should end in a one-line summary, not a wall of text.

## Version history
- **0.3.1** — Run index moved to the account database: every run ends with `agent_bus log_run`
  (kind `work`|`experiment`), and the experiment-cadence check uses `agent_bus run_count`
  instead of counting `history/` files. The markdown/json transcripts in `history/` stay on
  disk as before (legacy files are lazily imported once).
- **0.3.0** — Surface STATE moved to the account database: config/goals/heartbeat/experiment
  records now read+written through `agent_bus` actions (`get_surface_config`,
  `update_surface_config`, `get_goals`, `update_goals`, `update_heartbeat`,
  `create_experiment`, `run_experiment`, `evaluate_experiment`, `list_experiments`,
  `gather_experiment_context`, `list_cycles`) instead of raw `config.json` /
  `experiments/active/<cycle>.json` / `goals.json` files. File artifacts unchanged:
  `learnings.md`, `history/` run records, playbooks, `results.tsv`, git commits.
- **0.2.0** — Cycles as data: experiments driven by `cycles[]` (theta-wave authored), per-cycle
  active experiment, keep/ratchet + exploit/explore semantics, approval gating.
- **0.1.0** — Initial WORK loop + single-experiment autoresearch port from cortextOS.
