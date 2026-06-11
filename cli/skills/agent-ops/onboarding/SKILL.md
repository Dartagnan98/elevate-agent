---
name: onboarding
description: "You have just booted for the first time — there is no .onboarded flag in your state directory — and you need to set up your identity, connect your Telegram bot, configure your goals, and establish yourself within the org. Or onboarding was previously interrupted and the user has asked you to run it again. This skill walks you through every step of becoming a functioning agent. Do not skip steps. Do not start normal operations until onboarding is complete."
triggers: ["onboarding", "/onboarding", "first boot", "run onboarding", "setup", "not onboarded", "configure agent", "set up identity", "establish identity", "set goals", "onboard me", "start onboarding", "redo onboarding", "onboarding interrupted", "first time setup", "initial setup", "agent setup"]
external_calls: []
category: agent-ops
---

# Onboarding

This skill runs on first boot or when explicitly triggered. It is the only thing you should do until it is complete.

---

## Step 0: Know your runtime

You are an Elevate agent running on Claude Code. Your skills live under `.claude/skills/<skill>/SKILL.md` and your slash-commands (`/loop`, `/usage`, `/compact`, `/tools`, etc.) come from the Claude Code harness. Run `/tools` to see the full toolset available to you in this session.

Your identity (name, role, org) and your working directory are fixed by how Elevate launched you — you don't need to detect a runtime. If anything about your identity looks wrong, that is a reconfiguration concern: use the **manage_agent** tool (never edit identity files by hand).

---

## Step 1: Check onboarding status

Check for the `.onboarded` flag in your agent's state directory (inside your workdir). If it exists, you are already onboarded — skip to normal session start and do not re-run onboarding unless the user explicitly requests it.

```bash
[[ -f "state/.onboarded" ]] && echo "ONBOARDED" || echo "NEEDS_ONBOARDING"
```

(Adjust the path to wherever your agent's state lives in your workdir if it differs.)

---

## Step 2: Read ONBOARDING.md

```bash
cat ONBOARDING.md
```

This file contains the full onboarding protocol for your specific agent role. Follow every step exactly. Do not improvise.

---

## Step 3: What onboarding establishes

Onboarding must complete all of the following before you are considered functional:

| Item | Where it lives |
|------|----------------|
| Your name, role, emoji, and identity | `IDENTITY.md` (set via **manage_agent**, never hand-edited) |
| Your behavior, autonomy rules, and mode | `SOUL.md` |
| Your current goals and focus | Goals — set with the **agent_bus** tool (action `update_goals`); read back with action `get_goals` |
| User preferences and context | `USER.md` |
| Guardrails and patterns to avoid | `GUARDRAILS.md` |
| Telegram bot connected and tested | `.env` (BOT_TOKEN, CHAT_ID) |
| Recurring workflows scheduled | the **cron** tool |
| First heartbeat posted | the **agent_bus** tool (action `update_heartbeat`) |
| .onboarded flag written | `state/.onboarded` in your workdir |

Where these write narrative state (goals, guardrails, user context), also persist anything you'll need to recall later with the **memory** tool, which is mirrored in your `MEMORY.md` / `memory/<day>.md`.

---

## Step 3b: Recurring Workflows (Cron)

Any workflow that must keep running across restarts is a **cron**, not a `/loop`. `/loop` is session-only — it dies when your session ends, so never use it for persistent scheduling.

Use the **cron** tool to create recurring jobs during onboarding. For example, a periodic heartbeat:

> Create a cron that runs every 6 hours: "Read HEARTBEAT.md and follow its instructions."

Cron jobs are managed by Elevate and survive restarts — once created they continue firing on schedule with no manual restoration. Use the **cron** tool's list/create/delete actions to inspect and adjust them.

If a workflow needs isolated, parallel execution rather than a schedule (e.g. a one-off background investigation), use **delegate_task** to spin up a worker-agent instead of a cron.

---

## Step 4: Mark complete

When all steps in ONBOARDING.md are done, write the `.onboarded` flag in your agent's state directory:

```bash
mkdir -p state
touch state/.onboarded
```

Post your first heartbeat with the **agent_bus** tool (action `update_heartbeat`) so the fleet knows you're live, then notify the user via Telegram that you are online and ready.

---

## If Onboarding Is Interrupted

If a session crash or restart interrupts onboarding mid-way:

1. Check which steps completed (look at which files exist and whether goals/heartbeat are set via the **agent_bus** tool)
2. Resume from the first incomplete step
3. Do NOT restart from the beginning if some steps already completed
4. Re-run `/onboarding` if needed to trigger this skill again

---

## Critical Rules

- Do NOT send a Telegram message claiming you are online until onboarding is complete
- Do NOT set up crons until IDENTITY.md is established and goals are set (via the **agent_bus** tool, action `update_goals`)
- Do NOT start processing user requests until `.onboarded` is written
- Never hand-edit identity/role/toolset/skill config — use the **manage_agent** tool
- If a step in ONBOARDING.md calls for a mechanism Elevate does not have, do not invent a command. Note it, skip it, and raise a `[HUMAN]` task describing what's needed
- The user is waiting — be efficient, but do not skip steps
