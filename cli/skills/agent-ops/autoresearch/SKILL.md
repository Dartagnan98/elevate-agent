---
name: autoresearch
description: "The analyst has assigned you a research cycle, or you have identified a metric you want to improve through systematic experimentation. You will form a hypothesis, make a targeted change, measure the outcome against a baseline, and decide whether to keep or discard the change. You repeat this loop until the metric improves or you exhaust viable hypotheses. This is not ad-hoc research — it is structured scientific iteration with a defined metric, a hypothesis, and a measurable result."
triggers: ["experiment", "autoresearch", "hypothesis", "research cycle", "optimize", "improve metric", "run experiment", "test hypothesis", "measure improvement", "scientific loop", "iteration cycle", "theta wave research", "baseline measurement", "keep or discard", "research assignment"]
external_calls: []
category: agent-ops
---

# Autoresearch

You are a scientist. Autoresearch is how you systematically improve specific aspects of your work by running experiments, measuring results, and learning from outcomes.

## What It Is

You have research cycles assigned to you (check `experiments/config.json` in your workdir). Each cycle has:
- A **metric** you are optimizing (the dependent variable)
- A **surface** you are experimenting on (the independent variable - what you change)
- A **direction** (higher or lower = better)
- A **measurement window** (how long to wait before measuring)
- A **measurement method** (how to get the metric value)

You cannot autonomously modify your own cycle configuration. If the user asks you to modify a cycle, you can. Otherwise, the analyst (via theta wave) is the one who creates, modifies, or removes cycles. You CAN and SHOULD run experiments within your assigned cycles.

## The Experiment Loop

When your experiment cron fires, execute these steps:

### Step 1: Gather Context

Pull together everything you know about this cycle before forming a hypothesis:
- Read your accumulated learnings with the **memory** tool, and review your `MEMORY.md` and `memory/<day>.md` files for prior experiment notes.
- Check past experiment records in your workdir (`experiments/log/` or the active cycle's history).
- Review your tasks and goals: use the **agent_bus** tool (action `list_tasks`) and the **agent_bus** tool (action `get_goals`).

Pay attention to:
- What experiments have been tried before
- What was kept (these patterns work - build on them)
- What was discarded (these approaches failed - avoid repeating)
- Your current keep rate and trajectory

### Step 2: Evaluate Previous Experiment
If there is an active experiment (check `experiments/active.json`):
- Compare ALL relevant aspects: the surface changes you made, the context around those changes, and the output metric
- Measure the metric using the configured measurement method (see Measurement Methods below)
- Record the result: write the measured value, justification, and keep/discard decision into the experiment record (`experiments/active.json` → moved to `experiments/log/<experiment_id>.json`) and capture the learning with the **memory** tool.

For qualitative metrics, record a 1-10 score with a written justification in the same record.

### Step 3: Hypothesize
Based on accumulated learnings:
- Review what worked (keeps) and what failed (discards)
- Identify patterns - what themes appear in successful experiments?
- Consider untested approaches
- Form a specific, testable hypothesis
- Your hypothesis must be evidence-backed (cite past results or research)

**Exploit vs Explore:** If something has been kept 3+ times in a row, exploit that pattern further. If you have been discarding 3+ times, try something more radically different.

### Step 4: Create Experiment
Open a new experiment record in your workdir. Write `experiments/active.json` with:
- a unique `experiment_id`, the `metric_name`, your `hypothesis`, the `surface` path, the `direction` (higher|lower), the `window` (duration), and a `baseline` value (the current metric measurement).

If `approval_required` is true in `experiments/config.json`, you must get approval before proceeding. File an approval through the native **Approvals** workflow describing the experiment (cycle, metric, surface, hypothesis) and block until it is approved. Approvals are resolved in the dashboard — do NOT send a Telegram approval request. Once approved, continue to Step 5.

### Step 5: Make Changes and Run
Apply your hypothesized changes to the surface file. Then commit them so they can be cleanly reverted if the experiment fails:
```bash
git add <surface_path>
git commit -m "experiment <experiment_id>: <short description of what you changed>"
```
Record the resulting commit hash in `experiments/active.json` as `experiment_commit`. If this surface is not under git, note that in the record so you can revert manually.

### Step 6: Wait
The cycle ends. Your next cron trigger picks up at Step 1, where you will evaluate this experiment.

## Measurement Methods

### Quantitative (scripted)
A script returns a number. Example: API scrape for engagement rate.
```bash
bash connectors/measure-instagram.sh
# Output: metric_value: 3.2
```

### Quantitative (computed)
You calculate from existing data. Example: task completion rate. Use the **agent_bus** tool (action `list_tasks`) to pull your tasks, then compute:
- `completed` = count of your tasks with status completed
- `total` = count of all your tasks
- `rate` = completed / total * 100

### Qualitative (subjective)
You evaluate output quality on a 1-10 scale. You MUST write a justification, e.g. "Output is more concise and actionable than baseline, but loses some nuance." Record the score and justification in the experiment record.

### Qualitative (comparative)
You compare baseline vs experiment output side by side and score 1-10.

## Setting Up a Cycle

If the user asks you to set up autoresearch, collect these 8 things:
1. **Metric** — what to optimize (e.g., "engagement_rate", "task_completion_rate", "briefing_quality")
2. **Metric type** — quantitative (a number you can script/compute) or qualitative (a 1-10 score you evaluate)
3. **Surface** — the file to experiment on (e.g., `experiments/surfaces/engagement/current.md` for a prompt, or your behavior/identity file in your workdir)
4. **Direction** — higher or lower is better
5. **Measurement** — how to get the metric value (a script, computed from tasks, or self-evaluation)
6. **Window** — how long to wait before measuring the result (e.g., `24h`, `48h`)
7. **Loop interval** — how often to run the experiment loop (the cron frequency — often same as window)
8. **Approval** — should you need approval before running each experiment?

Then create the cycle config and surface directory in your workdir:
```bash
# Create surface directory and baseline file
mkdir -p "experiments/surfaces/<metric>"
cat > "experiments/surfaces/<metric>/current.md" << 'EOF'
# <metric> — Baseline

[Describe the current approach being tested]
EOF
```

Record the cycle definition in `experiments/config.json` (metric, metric-type, surface, direction, window, measurement, loop-interval, approval_required). Default `approval_required` to true unless the user explicitly says no approval is needed.

Then schedule the experiment loop with the **cron** tool, set to the loop interval, with a prompt like: "Read the autoresearch skill and execute the experiment loop for cycle `<metric_name>`." The cron schedule persists across restarts.

To modify a cycle when the user asks, edit the cycle's entry in `experiments/config.json` (window, loop-interval, enabled) and update its **cron** schedule if the loop interval changed. Set `enabled: false` to pause a cycle without deleting it.

## Important Rules

1. Never autonomously modify your own cycle config. If the user asks you to, you can.
2. You MUST log learnings for EVERY experiment, including failures (use the **memory** tool). Negative learnings are equally valuable.
3. You MUST respect the measurement window - do not evaluate early.
4. If `approval_required` is true, WAIT for native Approval before running.
5. Never repeat a hypothesis that was already discarded. Find a new angle.
6. Keep experiments focused - change one thing at a time when possible.
