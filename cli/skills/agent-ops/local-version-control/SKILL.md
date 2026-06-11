---
name: local-version-control
description: "Daily git snapshots of agent workspace changes. Stages files with safety checks, reviews diff for PII, commits with descriptive message. Never pushes automatically."
triggers: ["auto-commit", "git snapshot", "commit changes", "version control"]
external_calls: []
category: agent-ops
---

# Local Version Control

Daily snapshot of all agent workspace changes, committed with a two-layer safety review. Git itself runs through the terminal; the surrounding orchestration (scheduling, logging, memory, tasks) uses Elevate-native tools.

## When to Run

- On a daily schedule (register with the **cron** tool — see Config below)
- After major agent work sessions
- Before any destructive operations

## Workflow

### Step 1: Stage workspace changes with safety checks

Stage files from the agent's workdir using git, applying these safety checks before staging:
- Block `.env` files and credential files
- Block files over 10MB
- Block binary/temp files
- Respect `.gitignore` rules

```bash
git add -A
```

After staging, unstage anything that violates the rules above:
```bash
git reset HEAD <file>
```

There is no Elevate command that bundles staging + safety filtering into one step. Do the staging and the filtering explicitly with the terminal and the checks above.

### Step 2: Review the staged diff

```bash
git diff --cached
```

Check for:
- PII: names, emails, phone numbers in memory files
- Secrets: tokens, API keys, passwords
- Large diffs that look wrong
- Files that should not be committed

If anything looks sensitive, unstage it:
```bash
git reset HEAD <file>
```

### Step 3: Commit

Generate a descriptive commit message summarizing what changed:
```bash
git commit -m "daily: <summary of changes>"
```

Record that the snapshot ran by logging it via the **agent_bus** tool (action `log_event`), and note the commit in the agent's memory using the **memory** tool / `memory/<day>.md`.

### Step 4: Do NOT push

Auto-commit never pushes. The user or orchestrator decides when to push. If a push is genuinely needed, surface it through native **Approvals** rather than pushing automatically.

## Config

Enable the daily snapshot by registering a recurring run with the **cron** tool (do not edit files to schedule it). If this skill needs to be turned on for an agent's role or toolset, reconfigure the agent with **manage_agent** — never hand-edit agent config.

## Safety

- Never commits `.env` files
- Never commits files matching credential patterns
- Always reviews diff before committing
- Never pushes automatically
