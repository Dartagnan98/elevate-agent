---
name: goal-management
description: "Daily goal lifecycle management. Use for: morning briefing goal cascade, setting daily focus, refreshing agent goals, reviewing goal progress. Triggered daily as part of morning review."
triggers: ["goals", "daily focus", "priorities", "what should we work on", "goal cascade", "set goals", "update goals", "goal management", "north star"]
external_calls: []
category: agent-ops
---

# Goal Management

The orchestrator owns the daily goal lifecycle. Goals flow from the user's daily focus down to agent-specific objectives and tasks.

## Hierarchy

```
North Star (org-level, rarely changes — set by user)
  → Daily Focus (what the user wants done TODAY — set each morning)
    → Agent goals (orchestrator writes role-specific goals for each agent)
      → Agent reads goals on its turn via the agent_bus tool (action get_goals)
        → Tasks (agents create from their goals via the native Tasks tool)
```

Goals are stored and read through the **agent_bus** tool (actions `get_goals` / `update_goals`), not files. There is no separate generated GOALS.md to maintain — when an agent's goals change, it picks them up via `get_goals`.

## Morning Goal Cascade

Run this every morning as part of briefing:

### 1. Read current org / your own goals

Use the agent_bus tool (action `get_goals`) to read the current north star and daily focus. This returns the org-level north star plus your daily focus and bottleneck.

### 2. Consult the user

Send a message to the user:
> "Good morning. Our north star is: [north_star from get_goals]. What's the focus for today?"

Wait for their response. They may give specific directives or say "continue yesterday's work."

### 3. Update goals with today's focus

Use the agent_bus tool (action `update_goals`) to set `daily_focus` to the user's stated focus (the action stamps the update time for you).

### 4. Set each agent's goals

For each active agent, based on their role and today's daily focus:

1. Determine 2-5 role-appropriate goals.
2. Use the agent_bus tool (action `update_goals`) targeting that agent, with:
   - `focus`: role-specific focus derived from the daily focus
   - `goals`: the 2-5 goals you determined
   - `bottleneck`: leave empty unless one is known
3. Notify the agent so it picks up the new goals and creates tasks. Use the **agent_handoff** tool (or native **Comms**) to send: "New goals for today. Read your goals via agent_bus get_goals and create tasks."

**If an agent's goals already show a daily-focus timestamp matching today (visible in `get_goals`): skip — don't overwrite.**

### 5. Set your own goals

Use the agent_bus tool (action `update_goals`) for yourself with:
- `focus`: "orchestrate today's work, cascade goals, monitor fleet"
- `goals`: ["cascade goals to all agents", "send morning briefing", "monitor progress", "route approvals"]
- `bottleneck`: empty

### 6. Confirm task plans

After each agent creates tasks from their new goals, review via the native **Tasks** tool (or agent_bus action `list_tasks`) for:
- Overlap (two agents doing the same thing)
- Missing coverage (daily focus items nobody picked up)
- Misaligned tasks (work unrelated to today's focus)

## New Agent Bootstrap

When a new agent comes online with empty goals, it will message you (via Comms / agent_handoff) requesting goals.

Handle by:
1. Checking the agent's role and identity (its workdir identity / role config — surfaced when you list agents, or ask the agent).
2. Using the agent_bus tool (action `update_goals`) targeting that agent with appropriate starter goals.
3. Replying with confirmation via agent_handoff or native Comms.

If the agent needs its toolsets, skills, or role changed before it can pursue those goals, use the **manage_agent** tool — never edit agent files directly.

## Evening Goal Update

At end of day:
1. Check each agent's task completion against their goals (native **Tasks** tool, or agent_bus action `list_tasks`).
2. Note what was achieved vs planned. Persist any durable learnings with the **memory** tool (and the agent's own `MEMORY.md` / `memory/<day>.md`).
3. Update each agent's goals `bottleneck` field if new blockers emerged, using the agent_bus tool (action `update_goals`) targeting that agent with the new `bottleneck` text.
4. Carry forward unfinished goals to tomorrow's morning discussion.

## North Star

The north star is org-level and set by the user; it rarely changes. Read it via the agent_bus tool (action `get_goals`). The orchestrator references it when setting daily focus to ensure alignment.

If the daily focus drifts from the north star, flag it to the user:
> "Today's focus on [X] is different from our north star of [Y]. Is this intentional?"

## Scheduling note

If you want this cascade to run automatically each morning rather than on demand, schedule it with the **cron** tool. To fan out heavy, isolated goal-planning work in parallel, use **delegate_task** / worker-agents.
