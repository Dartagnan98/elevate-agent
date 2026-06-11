---
name: auto-skill
description: "You just completed a complex task that required 8+ distinct tool calls, or you noticed you are solving the same type of problem for the third time. Create a skill candidate draft so this workflow can be reused in future sessions without rediscovery. Draft goes to skills/drafts/ — never auto-activates until the user approves."
triggers: ["create skill", "draft skill", "skill candidate", "auto-skill", "I've done this before", "skill from task", "save this workflow", "make this a skill", "approve skill", "reject skill", "activate skill"]
category: agent-ops
---

# Auto-Skill Creation

When you complete a complex task with 8+ tool calls, or recognise a repeating pattern, draft a skill candidate. Drafts stage in `skills/drafts/` until approved — they are never auto-loaded into live sessions.

---

## Step 1: Post-Task Detection Check

After completing any task, run this self-check:

1. **Tool call count**: Did this task require 8+ distinct tool calls for a coherent workflow?
2. **Recurrence**: Does your daily memory show this same task type appearing 3+ times across different dates? Check via the **memory** tool, or read your `MEMORY.md` / `memory/<day>.md` files in your workdir.
3. **Existing skill**: Does a skill for this already exist in `.claude/skills/`? Use **/tools** to list what's loaded. If it exists, stop — consider proposing a patch instead.
4. **Repeatability**: Is this task type likely to recur, or was it a one-off?

If yes to 1 or 2, AND no to 3, AND yes to 4 → create a draft.

**Do NOT draft for:**
- Routine heartbeat operations
- One-off research tasks
- Tasks already covered by existing skills
- Simple single-step operations

---

## Step 2: Draft the Skill

Create the draft at `skills/drafts/[skill-name]/SKILL.md`:

```bash
mkdir -p skills/drafts/[skill-name]
```

Use this template:

```markdown
---
name: skill-name-here
description: One sentence, max 100 chars. What this skill does and when to use it.
created: YYYY-MM-DD
created_by: auto
trigger: "Natural language description of when this skill fires"
source_task_id: TASK-ID-THAT-GENERATED-THIS
version: 1
status: draft
---

## Purpose

[What this skill does. 2-3 sentences max.]

## When to Use

[Specific conditions that should trigger this skill. Be concrete.]

## Inputs Required

- `PARAM_1` — description
- `PARAM_2` — description (optional)

## Steps

1. [Step 1 — specific, actionable]
2. [Step 2]
3. ...

## Output

[What gets created or sent when this skill completes.]

## Approval Gate

[Does any step require user approval? Specify exactly which step. Route via native Approvals.]

## Notes / Edge Cases

[Known failure modes, dedup considerations, platform quirks.]
```

Fill `source_task_id` from the originating task — look it up with the **agent_bus** tool (action `list_tasks`) or native **Tasks** if you don't have it on hand.

---

## Step 3: Self-Review Before Saving

Before writing the file, check:

- [ ] `description` is under 100 characters
- [ ] No skill with this name exists in `.claude/skills/` (confirm via **/tools**)
- [ ] All steps are actionable — no vague instructions like "handle errors appropriately"
- [ ] Any step requiring external actions (email, deploy, post, delete) routes through native **Approvals**
- [ ] `source_task_id` is filled in for traceability

If any check fails, revise before saving.

---

## Step 4: Log and Notify

After saving the draft:

1. **Log the creation** — use the **agent_bus** tool (action `log_event`) with action `skill_draft_created`, level `info`, and meta `{"skill":"[skill-name]","source_task":"[task_id]"}`. The bus stamps your agent identity automatically from your workdir.
2. **Notify the orchestrator** — use the **agent_handoff** tool to hand off to the orchestrator agent (or post a message in native **Comms**): "Skill candidate drafted: [skill-name] — source task [task_id]. Check skills/drafts/[skill-name]/SKILL.md. Awaiting review."

The orchestrator surfaces it for the user to review. The user replies `approve [skill-name]`, `reject [skill-name] [reason]`, or `revise [skill-name] [feedback]` — delivered to you via native **Comms** / your inbox.

---

## Step 5: Handling Approval Responses

When you receive a Comms message / inbox item with a skill decision (check via the **agent_bus** tool, action `check_inbox`):

### Approved

```bash
# Move from draft to active
mv skills/drafts/[skill-name]/ .claude/skills/[skill-name]/
```

Then:
- Update the `status: draft` line to `status: active` in `.claude/skills/[skill-name]/SKILL.md`.
- **Log activation** — use the **agent_bus** tool (action `log_event`): action `skill_activated`, level `info`, meta `{"skill":"[skill-name]"}`.
- **Notify the user** — post the activation note in native **Comms**: "Skill activated: [skill-name] is now live and will be used in future sessions."

If the skill should also be reachable as a loaded toolset for this or other agents, reconfigure the agent with the **manage_agent** tool — never hand-edit agent config files.

### Rejected

```bash
# Move to archive with reason recorded
mkdir -p skills/archive/[skill-name]
mv skills/drafts/[skill-name]/SKILL.md skills/archive/[skill-name]/SKILL.md
```

Then:
- Append the rejection reason and date to the archived `SKILL.md` (add a `## Rejection` section with `Reason:` and `Date:`).
- **Log** — use the **agent_bus** tool (action `log_event`): action `skill_rejected`, level `info`, meta `{"skill":"[skill-name]","reason":"[reason]"}`.

### Revise

- Apply the feedback and re-save the draft in place.
- Re-notify the orchestrator via the **agent_handoff** tool (or native **Comms**): "Skill candidate [skill-name] revised per feedback. Ready for re-review."

---

## Draft Lifecycle

| State | Location | Loaded at boot? |
|-------|----------|-----------------|
| draft | `skills/drafts/[name]/SKILL.md` | No |
| active | `.claude/skills/[name]/SKILL.md` | Yes |
| archived | `skills/archive/[name]/SKILL.md` | No |

Drafts older than 14 days with no action: move to `skills/archive/` and log `skill_expired` via the **agent_bus** tool (action `log_event`).

To run that 14-day sweep automatically, register a recurring job with the **cron** tool — don't rely on a manual pass.

---

## Critical Rules

1. **No automated commits** — skill files are never committed without explicit user approval
2. **Draft means invisible** — agents do NOT load or execute skills from `skills/drafts/`
3. **No self-modification** — skills never modify other skills (v2 feature)
4. **No external calls without gates** — any skill step with external side effects must route through native **Approvals**
