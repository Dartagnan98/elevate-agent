---
name: obsidian-log
effort: low
description: "Write key decisions, project milestones, and feedback rules back to the Obsidian vault. Use this after confirming any architectural decision, project milestone, or durable feedback rule — keeps the vault current with agent memory."
triggers: ["obsidian", "write to vault", "log decision", "save to obsidian", "update vault", "obsidian log", "decision log", "vault write-back", "milestone logged", "write back", "obsidian write"]
category: agent-ops
---

# Obsidian Log Skill

> Write agent decisions and milestones back to the Obsidian vault so it stays current with agent memory. Use after confirming any significant decision, project milestone, or durable feedback rule.

---

## When to Use

Trigger this skill when you:
- Confirm an architectural or product decision (e.g. "we decided X approach for Y")
- Complete a project milestone and want it recorded (e.g. "feature Z shipped")
- Receive and confirm a durable feedback rule (e.g. "always do X, never do Y")
- Finish an onboarding or knowledge distillation session

Do NOT log every task or message — only decisions and milestones that should persist across agents and sessions.

---

## CLI Reference

The Obsidian CLI writes directly to vault notes. Replace `[VAULT_NAME]` with your configured vault name.

### Create or overwrite a note
```bash
obsidian vault=[VAULT_NAME] create path="<note-path>" content="<content>" overwrite
```

### Append to an existing note
```bash
obsidian vault=[VAULT_NAME] append path="<note-path>" content="<content>"
```

Use your own identity (workdir / agent identity) wherever a step says `[AGENT_NAME]`.

---

## Workflow

### 1. Log a decision (daily decisions log)

Decisions go to `01-Memory/decisions-YYYY-MM-DD.md`. Append so the daily file accumulates entries:

```bash
TODAY=$(date +%Y-%m-%d)
obsidian vault=[VAULT_NAME] append \
  path="01-Memory/decisions-${TODAY}.md" \
  content="
## [HH:MM] <Decision title>

**Decision:** <What was decided>
**Why:** <Reasoning or constraint that drove it>
**Impact:** <What changes as a result>
**Agent:** [AGENT_NAME]
"
```

If the daily file does not exist yet, use `create` instead of `append`:

```bash
TODAY=$(date +%Y-%m-%d)
obsidian vault=[VAULT_NAME] create \
  path="01-Memory/decisions-${TODAY}.md" \
  content="# Decisions — ${TODAY}

## [HH:MM] <Decision title>

**Decision:** <What was decided>
**Why:** <Reasoning or constraint that drove it>
**Impact:** <What changes as a result>
**Agent:** [AGENT_NAME]
" overwrite
```

Also persist the decision to durable agent memory so it survives across sessions: use the **memory** tool to record it, and append the same entry to your `MEMORY.md` / `memory/<day>.md`. For a fleet-visible decision, post it with the **agent_bus** tool (action `log_event`).

### 2. Log a project milestone

Project milestones append to `02-Projects/<project-name>.md`:

```bash
obsidian vault=[VAULT_NAME] append \
  path="02-Projects/<project-name>.md" \
  content="
## Milestone — $(date +%Y-%m-%d)

**What shipped:** <Feature or deliverable>
**Status:** Complete
**Notes:** <Any relevant context>
"
```

If the milestone closes out tracked work, also mark the matching task done in native **Tasks** (or use the **agent_bus** tool, action `complete_task` / `update_task`). If the milestone advances a stated objective, reflect it with the **agent_bus** tool (action `update_goals`; read current state first with action `get_goals`).

### 3. Log a durable feedback rule

Feedback rules that should persist append to `01-Memory/agent-feedback.md`:

```bash
obsidian vault=[VAULT_NAME] append \
  path="01-Memory/agent-feedback.md" \
  content="
## $(date +%Y-%m-%d) — <Rule title>

**Rule:** <The feedback rule>
**Why:** <Reason given by user or inferred>
**Agent:** [AGENT_NAME]
"
```

Record the same rule in durable agent memory with the **memory** tool, and append it to your `MEMORY.md` so it loads automatically next session. If the rule changes how an agent should be configured (its toolsets, skills, or role), apply that with **manage_agent** — never hand-edit agent config files. If a rule should fire on a schedule, set it up with **cron**.

---

## Keep the KB Current

After writing to the vault, surface the updated memory so other agents can find it:
- Record the entry with the **memory** tool — this is what agent recall reads.
- For fleet visibility, broadcast it with the **agent_bus** tool (action `log_event`), or hand it to a specific agent with **agent_handoff** plus a message via native **Comms**.

To keep this automatic, set up a recurring run with **cron** that re-records the day's memory entries on a schedule (e.g. daily) — point it at this skill so it ingests `01-Memory/` and logs the result.

> Note: Elevate has no `kb-ingest` command. Durable recall is served by the **memory** tool + the agent's `MEMORY.md` / `memory/<day>.md`, not a separate KB ingest step. If you specifically need a standalone searchable KB beyond the memory tool, there is no built-in Elevate mechanism for it — raise a **[HUMAN]** task describing the need rather than inventing a command.

---

## Checklist Before Writing

- [ ] Is this a decision, milestone, or feedback rule — not just a task update?
- [ ] Does the vault path match the correct date / project name?
- [ ] Use `append` if the file exists, `create` with `overwrite` if starting fresh for the day
- [ ] Also persist it to durable memory (the **memory** tool + `MEMORY.md`) so recall reflects the new entry
- [ ] If it touches tasks/goals/config/schedule, mirror it via **Tasks**, **agent_bus** `update_goals`, **manage_agent**, or **cron** as appropriate

---

*Deployment note: replace `[VAULT_NAME]` and `[AGENT_NAME]` with your actual values. Add the vault path to your agent's TOOLS.md so it is available at session start. To see the tools referenced above (agent_bus, agent_handoff, memory, manage_agent, cron, Tasks, Approvals, Comms), run `/tools`.*
