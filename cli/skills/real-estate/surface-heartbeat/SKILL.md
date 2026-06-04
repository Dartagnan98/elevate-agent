---
name: surface-heartbeat
description: Run one Elevate dashboard surface (Leads, Admin, ...) as a heartbeat. On a cadence you do the surface's recurring work, log it, distill durable learnings that sharpen the next run, and every Nth run you run an experiment to improve your own playbook — hypothesize, change how you work, measure, keep or discard. The theta-wave loop applied to real surface work. Your prompt names the Surface and the Workspace path.
version: 0.1.0
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
`config.json.goal` explicitly says to.

## Every run — WORK loop
1. **Load context.** Read `config.json` (your `goal`) and the whole `learnings.md` (apply it).
   Count prior runs: `ls "<Workspace>/history" | wc -l`.
2. **Do the work** in `config.json.goal`, sharpened by your learnings, using your normal Elevate
   tools/skills for this surface.
3. **Log** → write `history/<UTC-ISO-timestamp>.json`:
   ```json
   {"ran_at":"<iso>","checked":"<what you looked at>","did":"<actions/drafts>","found":"<key findings>","summary":"<one line>"}
   ```
4. **Distill** — if you learned something durable (a pattern, a preference, what landed), append
   ONE tight bullet to `learnings.md`. Dedupe. No noise.
5. **Report** one tight summary to your delivery channel. Nothing changed → "all quiet."

## Every Nth run — EXPERIMENT loop
Only when `config.experiment` exists AND `(history count) % config.experiment.every_n_runs == 0`.

1. **Gather** — read `experiments/history/`. Keeps = patterns that work (build on them); discards =
   avoid; note your keep rate.
2. **Close active** — if `experiments/active.json` exists: measure `config.experiment.metric` via
   `config.experiment.measurement` (qualitative → a 1–10 self-score with written justification),
   decide **keep**/**discard** (did it move in `direction`?), write `experiments/history/<id>.json`
   `{hypothesis, baseline, result, decision, learning, ts}`, fold the learning into `learnings.md`,
   delete `active.json`.
3. **Hypothesize** ONE improvement to HOW you do the work, evidence-backed from keeps/discards.
   Exploit a 3×-kept pattern; explore something new after 3× discards.
4. **Activate** — apply the change to YOUR playbook (a `playbook` field in `config.json`, or a
   learnings entry the next run follows) — **NEVER the realtor's data**. Write
   `experiments/active.json` `{id, hypothesis, surface_change, baseline, started_at, window}`;
   measure it next experiment run. If `config.experiment.approval_required`, request approval and
   wait first.

## Rules
- Stay in your Workspace and your one Surface. Idempotent — if interrupted, the next run resumes
  from the files on disk.
- Keep `learnings.md` tight; it's read every run, so bloat dilutes signal.
- The experiment changes how *you* work, never the realtor's leads / calendar / data.
- Be fast and quiet: most runs should end in a one-line summary, not a wall of text.
