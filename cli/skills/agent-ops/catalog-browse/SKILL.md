---
name: catalog-browse
description: "Browse the community catalog for new skills, agent templates, and org templates. Discover what is available and recommend useful items to the user."
triggers: ["catalog", "browse skills", "community", "find skill", "new skills available", "what skills"]
external_calls: []
category: agent-ops
---

# Catalog Browse

Discover new skills, agent templates, and org templates from the community catalog. Recommend useful items to the user and install with approval.

## When to Run

- On a recurring schedule (set up a weekly recurring run with **cron**)
- When user asks about available skills
- When an agent needs a capability that might exist in the catalog

## Workflow

### Step 1: Browse the catalog

Elevate does not ship a built-in community-catalog browser tool. There is no native mechanism to list/search a remote community catalog of skills, agent templates, and org templates.

- Inspect what the agent already has loaded with **/tools** (lists the agent's active toolsets and skills).
- If you genuinely need to discover and pull new community items and no Elevate tool exists for it, do NOT invent a command. Raise a `[HUMAN]` task describing the desired catalog source so it can be wired up or fetched manually.

### Step 2: Review results

When reviewing any candidate item (from /tools, a shared list, or a human-provided source), note:
- Item name, description, author
- Type (skill, agent, org)
- Tags and dependencies
- Whether it is already available to the agent (check **/tools**)

### Step 3: Recommend to user

For items that look useful:
- Explain what the skill does
- Which agent would benefit
- Send the recommendation to the user via the agent's normal **Comms** channel (or hand it off with **agent_handoff** if another agent owns the follow-up)

### Step 4: Install (with approval)

Installing/enabling a capability for an agent in Elevate means changing that agent's configuration, not running a shell installer.

- To enable a new skill, toolset, or change an agent's role, use **manage_agent**. NEVER hand-edit agent config files.
- Gate the change behind approval: create the request in native **Approvals** and only apply it via **manage_agent** once the user approves.

## Config

This skill is enabled/disabled through the agent's configuration. Toggle it with **manage_agent** rather than editing files by hand.

## Notes

- If a desired catalog source or item cannot be reached through an existing Elevate tool, raise a `[HUMAN]` task instead of inventing a command — there is no native catalog-fetch mechanism.
- Verify what's already available with **/tools** before recommending anything.
- Route capability changes through native **Approvals** + **manage_agent** so every install is reviewed before it takes effect.
