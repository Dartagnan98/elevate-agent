---
name: research-quality-review
description: "Audit source quality, scoring performance, duplicate patterns, source failures, stale config, and tuning opportunities."
category: agent-ops
---

# Research Quality Review

Run weekly, after a few research cycles, or whenever the briefs feel noisy. To put it on a recurring cadence, set up a **cron** schedule instead of relying on memory.

## Inputs

Read these from the agent's workdir (the directory you launched in):

- `research/output/`
- `research/topic-briefings/`
- `research/sources.json`
- `research/scoring-rubric.json`
- `research/db/signals.db` if available
- recent user feedback — pull via the **memory** tool and check **Comms** (use **agent_handoff** for anything routed to you) plus open **Tasks** (also via agent_bus action `list_tasks`)

## Review Checklist

1. Source failures:
   - repeated timeouts
   - rate limits
   - empty sources
   - auth failures
2. Source quality:
   - high-volume low-signal sources
   - sources that never produce selected items
   - missing source categories
3. Scoring quality:
   - obvious good signals below threshold
   - noisy signals above threshold
   - over-weighted platform bonuses
   - stale or too-broad keywords
4. Deduplication:
   - repeated same story across platforms
   - old items resurfacing without new evidence
5. Delivery quality:
   - too much detail in summaries
   - weak source attribution
   - unclear recommended actions
6. Topic briefing quality:
   - options too similar
   - low evidence topics
   - weak why-now framing

## Output

Write the review to your workdir:

```text
research/output/YYYY-MM-DD/research-quality-review.md
```

Use this format:

```markdown
# Research Quality Review -- YYYY-MM-DD

## Summary
[What is working / not working.]

## Source Changes Recommended
- Keep:
- Add:
- Remove:
- Watch:

## Scoring Changes Recommended
- [Specific rubric edit and why]

## Workflow Changes Recommended
- [Cron, delivery, topic briefing, output format changes]

## Human Decisions Needed
- [Decision and tradeoff]
```

## Logging and follow-up

When the review is written:

- Record what you found and decided in the **memory** tool and the agent's `MEMORY.md` / `memory/<day>.md`.
- Update your heartbeat so the run is visible: use the **agent_bus** tool (action `update_heartbeat`); to see fleet state use **agent_bus** (action `read_heartbeats`). For a discrete event record, use **agent_bus** (action `log_event`).
- For each recommended workflow or follow-up action, create a native **Task** (or use the **agent_bus** tool, action `create`/`update_task`/`complete_task`) so it is tracked, not lost in the doc.
- If the review needs another agent's input, route it through **agent_handoff** and native **Comms** rather than any file inbox. To check what has been routed to you, use the **agent_bus** tool (action `check_inbox`).
- If a recommendation maps to a stated goal, reconcile it via the **agent_bus** tool (actions `get_goals` / `update_goals`).

## Human decisions and approvals

Do not edit source/scoring config automatically unless the user asks. Propose changes first.

- Surface anything that needs sign-off through native **Approvals**; to review what is pending use the **agent_bus** tool (action `list_approvals`).
- For work that must be done by a person (e.g. a credential rotation behind a failing auth source), raise a `[HUMAN]` task via native **Tasks** and check the human-task queue with the **agent_bus** tool (action `check_human_tasks`).

## Acting on the recommendations

- To change THIS agent's own config (toolsets, skills, role, scoring behavior) use **manage_agent** — never hand-edit agent config files.
- To run an isolated, parallel sub-investigation (e.g. re-scoring a large source set without blocking this review) use **delegate_task** / a worker-agent.
- To make the review recur on a schedule, use **cron**.
- The full tool list is available at any time via **/tools**.

If any step here has no matching Elevate mechanism, do not invent a command — note the gap in the "Human Decisions Needed" section and raise a `[HUMAN]` task.
