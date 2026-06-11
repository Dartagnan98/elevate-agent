---
name: community-publish
description: "Package a local skill, agent, or org template for community sharing. Strips PII, scans for secrets, prepares a clean submission, and opens a PR to the community catalog."
triggers: ["publish skill", "share skill", "community submit", "package for sharing", "contribute"]
external_calls: ["github.com"]
category: agent-ops
---

# Community Publish

Package a local skill, agent template, or org template for sharing with the community. Strips all personal data and opens a PR.

## When to Run

- When user asks to share a skill
- When the analyst identifies a well-built custom skill worth sharing
- Suggest proactively for skills that have been stable and useful

## Workflow

### Step 1: Identify and stage the source

Locate the item to package under the agent's workdir:

- skill: a skill directory (e.g. `skills/morning-review`)
- agent: an agent template/config (reconfigure or inspect with the **manage_agent** tool — NEVER hand-edit agent files)
- org: an org template

Copy the source into a clean staging directory under the agent's workdir (use **/tools** to confirm which file/terminal tools are available before manipulating files). Do not stage from a path you can't read.

### Step 2: Scan for PII and secrets

Scan the staged files for:
- Email addresses
- Phone numbers
- API keys and tokens
- Chat IDs
- User names
- Company names
- Deployment URLs

Use **/tools** to find the available secret/PII scanner or a grep-capable file tool, then run it over the staging directory. There is no single `prepare-submission` command in Elevate — assemble the scan from the file tools you have. If no scanner tool is available, [HUMAN] task: ask Dartagnan which scanner to use before anything leaves the machine.

If PII is found, manually clean the staged files before submitting.

### Step 3: Get user approval

Approvals are dashboard-only — create the request through the native **Approvals** surface (do not request approval over Telegram). Include:
- What is being shared
- Files included
- Any PII warnings

Wait for an explicit approval decision in Approvals before continuing. Do not submit on an unresolved approval.

### Step 4: Submit to community

There is no `submit-community-item` command in Elevate. Do the contribution with the agent's git/`gh` access via the terminal tool (confirm it's in your loadout with **/tools**):

**Local catalog only (no PR):**
1. Copy the clean staged files into the community/ directory.
2. Add an entry to catalog.json (item name, type, description, author = the agent's identity).

**Full contribution (branch + push + PR):**
1. Create a git branch `community/<item-name>`.
2. Copy clean files to the community/ directory.
3. Add an entry to catalog.json.
4. Commit and push the branch to `origin` (your fork).
5. Open a PR against `upstream` (the canonical community catalog repo) via `gh` CLI.

### Step 5: Report

Tell the user the PR URL and that it is awaiting community review. Log the submission with the **memory** tool (and append a note to the agent's MEMORY.md / memory/<day>.md), and record the activity via the **agent_bus** tool (action log_event).

## Config

Gate this behavior on the agent's role/toolset. Enable or restrict it with the **manage_agent** tool — do not edit config files by hand. If community publishing should run on a schedule, register it with **cron**.

## Prerequisites

- The agent's workdir must have a fork of the community catalog repo configured as `origin`
- `upstream` remote must point to the canonical community catalog repo
- `gh` CLI must be authenticated (`gh auth login`)
- The agent's loadout must include terminal/git access (verify with **/tools**)

## Safety

- NEVER submits without an explicit approval decision in the native Approvals surface
- ALWAYS runs the PII/secret scan first
- ALWAYS reviews the staged files before real submission
- User reviews every file before it leaves their machine
