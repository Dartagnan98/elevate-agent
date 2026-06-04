---
name: surface-heartbeat
description: Run one Elevate dashboard surface (Leads, Admin, ...) as a heartbeat. On a cadence you do the surface's recurring work, log it, distill durable learnings that sharpen the next run, and on each research cycle's interval you run an autoresearch experiment to improve your own playbook — hypothesize, change how you work, measure, keep or discard, ratchet the baseline. A faithful port of the cortextOS theta-wave autoresearch loop applied to real surface work. Your prompt names the Surface and the Workspace path.
version: 0.2.0
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
- **Workspace** — an absolute path holding `config.json`, `learnings.md`, `history/`, `experiments/`.

Everything you read/write lives in that Workspace. **Drafts and recommendations only** — the
realtor acts; you never send messages, move money, or commit changes on their behalf unless
`config.json.goal` explicitly says to. An experiment only ever changes HOW YOU WORK (your
playbook), never the realtor's leads, calendar, or data.

## Every run — WORK loop
1. **Load context.** Read `config.json` (your `goal`, your `playbook` if present) and the whole
   `learnings.md` (apply it). Count prior runs: `ls "<Workspace>/history" | wc -l`.
2. **Drain dispatched tasks.** Pull work the realtor (or the analyst) queued to you:
   `GET ${ELEVATE_DASHBOARD_URL:-http://127.0.0.1:9120}/api/surface-tasks?assignee=<surface>&status=pending`.
   For each, do the work (drafts only), `PATCH .../api/surface-tasks/<id>` to `in_progress` then
   `completed` with `outputs:[...]`. If a task has `needsApproval` (or your action would send /
   change anything), do NOT act — leave a draft and it surfaces for sign-off (see below). Skip
   tasks assigned to `human`.
3. **Do the work** in `config.json.goal`, sharpened by your learnings + playbook, using your
   normal Elevate tools/skills for this surface.
4. **Surface anything needing sign-off.** When you produce a draft/recommendation that must NOT
   go out without the realtor's yes, it shows on the Approvals board — resolved on the dashboard
   only, never auto-sent. (Approvals are created for you; you never send on the realtor's behalf.)
6. **Log** → write `history/<UTC-ISO-timestamp>.json`:
   ```json
   {"ran_at":"<iso>","checked":"<what you looked at>","did":"<actions/drafts>","found":"<key findings>","summary":"<one line>"}
   ```
7. **Distill** — if you learned something durable (a pattern, a preference, what landed), append
   ONE tight bullet to `learnings.md`. Dedupe. No noise.
8. **Report** one tight summary to your delivery channel. Nothing changed → "all quiet."

---

## Autoresearch — the EXPERIMENT loop (per cycle)

Research is a SEPARATE system from work. It is driven by `config.json.cycles[]` — each cycle is
one self-improvement track the analyst (theta-wave) set up for you. You never create, modify, or
remove cycles yourself; you only RUN the cycles you're given.

A `cycle` looks like:
```json
{"name":"next-touch","agent":"leads","metric":"next_touch_reply_rate","metric_type":"quantitative",
 "surface":"leads","direction":"higher","window":"7d","measurement":"<how to measure>",
 "loop_interval":"every 7 runs","every_n_runs":7,"approval_required":false,
 "enabled":true,"created_by":"system","created_at":"<iso>"}
```
Legacy: if there's no `cycles[]` but a `config.experiment` block exists, treat that block as a
single implicit cycle (its `every_n_runs`, `metric`, etc.).

After the WORK loop, for **each enabled cycle** where
`(history count) % cycle.every_n_runs == 0`, run the 6-step autoresearch loop below. Each cycle
keeps its own active experiment at `experiments/active/<cycle.name>.json`; records and rollups
are shared in `experiments/history/`, `experiments/results.tsv`, and
`experiments/surfaces/<metric>/current.md`.

### 1. Gather context
Read `experiments/results.tsv` and the cycle's recent `experiments/history/*.json` (filter to this
cycle's `metric`). Note the last few decisions and your **keep rate** for this metric.

### 2. Evaluate the previous experiment (if one is active)
If `experiments/active/<cycle.name>.json` exists:
- **Measure** `cycle.metric` over `cycle.window` per `cycle.measurement`. Quantitative → a number.
  Qualitative → a 1–10 self-score WITH a written justification.
- **Decide** using the cycle's `direction`:
  - `higher`: `measured > baseline_value` → **keep**, else **discard**.
  - `lower`:  `measured < baseline_value` → **keep**, else **discard**.
- **Write the completed record** to `experiments/history/<id>.json` (full shape below): set
  `status:"completed"`, `result_value`, `decision`, `completed_at`, and a one-line `learning`.
- **Ratchet** — on **keep**, the change earned its place: set this cycle's `baseline_value =
  measured` for the NEXT experiment (the bar goes up). On **discard**, baseline stays where it was
  and you revert the playbook change you made for this experiment.
- **Append** one row to `experiments/results.tsv` (`ts<TAB>cycle<TAB>metric<TAB>baseline<TAB>result<TAB>decision`)
  and fold the `learning` into `learnings.md`. Update `experiments/surfaces/<metric>/current.md`
  with the current best playbook for this metric. **Delete** `experiments/active/<cycle.name>.json`.

### 3. Hypothesize ONE change (exploit vs explore)
Evidence-backed from this cycle's history:
- **3+ keeps in a row → EXPLOIT**: push harder on what's working — a sharper version of the
  winning pattern.
- **3+ discards in a row → EXPLORE**: abandon that line, try a genuinely different approach.
- Otherwise: the most promising single tweak to HOW you do the work for this surface.

### 4. Create the experiment record (`proposed`)
Mint `id = exp_<unix-epoch-seconds>_<5 random base36 chars>` and write the FULL record to
`experiments/history/<id>.json`:
```json
{"id":"exp_1717000000_a1b2c","agent":"<cycle.agent>","metric":"<cycle.metric>","metric_type":"<cycle.metric_type>",
 "hypothesis":"<what you believe will move the metric and why>","surface":"<cycle.surface>",
 "direction":"<cycle.direction>","window":"<cycle.window>","measurement":"<cycle.measurement>",
 "status":"proposed","baseline_value":<current baseline number>,"result_value":null,"decision":null,
 "learning":null,"changes_description":null,"experiment_commit":null,"tracking_commit":"<git HEAD sha now>",
 "created_at":"<iso>","started_at":null,"completed_at":null}
```
If `cycle.approval_required` is true: stop here, surface the proposed experiment for dashboard
approval, and do NOT proceed to step 5 until approved. (Approvals are dashboard-only.)

### 5. Run it — change your playbook + commit
- **Apply the change to YOUR playbook**: edit `config.json.playbook` (or the cycle's entry in
  `experiments/surfaces/<metric>/current.md`) and/or add a learnings rule the next WORK run will
  follow. NEVER the realtor's data.
- **Commit the playbook change with git** so the change is a real, revertible artifact:
  ```
  git -C "<Workspace>" add -A && git -C "<Workspace>" commit -m "exp <id>: <changes_description>"
  ```
  If the Workspace isn't a git repo, `git init` it first (it holds only your config/learnings/
  experiment files — never realtor data). Capture the resulting SHA.
- **Promote the record to `running`**: set `status:"running"`, `started_at:"<iso>"`,
  `changes_description:"<what you changed>"`, `experiment_commit:"<the SHA>"`. Re-write
  `experiments/history/<id>.json` AND copy it to `experiments/active/<cycle.name>.json`.
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
  from the files on disk (active experiments live in `experiments/active/`).
- You RUN cycles; you never author them. Cycle create/modify/remove is the analyst's job
  (theta-wave) via the dashboard.
- Keep `learnings.md` tight; it's read every run, so bloat dilutes signal.
- An experiment changes how *you* work, never the realtor's leads / calendar / data. The git
  commit makes every change revertible.
- Keep → ratchet the baseline. Discard → revert the change and keep the old baseline.
- Be fast and quiet: most runs should end in a one-line summary, not a wall of text.
