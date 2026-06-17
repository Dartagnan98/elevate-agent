---
name: delegation-matrix
effort: low
description: "Orchestrator/agent/Codex delegation matrix. Reference this when scoping a task to determine who owns what. Covers three Codex modes: reviewer-only (default), implementer+reviewer, and no Codex."
triggers: ["who owns", "delegation", "codex or agent", "should codex", "task scoping", "who does this", "delegation matrix", "codex mode"]
category: agent-ops
---

# Delegation Matrix

> Reference when scoping any task. Dividing line: **execution-heavy → Codex (if configured as implementer). Judgment-heavy → Agent always.**

Codex is a configurable option. Pick the mode that matches your setup:

| Mode | Codex role | When to use |
|------|-----------|-------------|
| **Mode 1** (default) | Reviewer only | Out of the box — Codex reviews Agent output before PR |
| **Mode 2** | Implementer + reviewer | Codex is set up and trusted for implementation |
| **Mode 3** | Not used | No Codex in your stack — Agent handles everything |

---

## Ownership Matrix

| Work type | Orchestrator | Agent | Codex (Modes 1+2) |
|-----------|-------------|-------|-------------------|
| Requirement intake from user | **owns** | — | — |
| Task decomposition + dispatch | **owns** | consults | — |
| Briefings and status to user | **owns** | input | — |
| Architecture decisions | — | **owns** | — |
| Spec writing + acceptance criteria | — | **owns** | — |
| Security and domain modeling | — | **owns** | — |
| Ambiguous / judgment calls | routes | **owns** | — |
| PR decisions (file, scope, merge) | — | **owns** | — |
| First-pass implementation (clear spec) | — | **owns** (Modes 1+3) / delegates (Mode 2) | **owns** (Mode 2) |
| Mechanical refactors and migrations | — | **owns** (Modes 1+3) / delegates (Mode 2) | **owns** (Mode 2) |
| Repetitive multi-file edits | — | **owns** (Modes 1+3) / delegates (Mode 2) | **owns** (Mode 2) |
| Test drafting and fixture setup | — | **owns** (Modes 1+3) / delegates (Mode 2) | **owns** (Mode 2) |
| Code review before PR | — | **owns** (Mode 3) | **owns** (Modes 1+2) |

---

## Default Coding Workflow by Mode

### Mode 1 — Codex as reviewer (default, out of box)

1. **Orchestrator** receives task, dispatches to Agent
2. **Agent** implements
3. **Agent** passes output to Codex for review
4. **Agent** applies Codex feedback, opens PR

### Mode 2 — Codex as implementer + reviewer

For tasks >~20 lines or touching multiple files:

1. **Orchestrator** receives task, dispatches to Agent
2. **Agent** designs the approach, writes a tight spec (what to build, file paths, expected behavior, edge cases)
3. **Agent** calls Codex with the full spec — Codex implements
4. **Agent** reviews Codex output for correctness and architectural fit
5. **Agent** opens the PR

### Mode 3 — No Codex

1. **Orchestrator** receives task, dispatches to Agent
2. **Agent** designs and implements directly
3. **Agent** opens the PR

For **one-liners and config changes**: Agent writes directly in all modes.

---

## When to Keep Implementation with Agent (Modes 1+2)

Even in Mode 2, some work stays with the Agent:
- Correct behavior is unclear and requires judgment
- Security, auth, or trust-boundary code
- Design is still open — spec isn't settled yet
- Output shown directly to users or external systems

---

## Mechanics — how delegation actually happens in Elevate

When the matrix above says "dispatch," "delegate," "review," or "hand off," use the Elevate-native mechanism. There is no daemon, IPC, PM2, or PTY layer — these are all tool calls and native surfaces.

- **Dispatch / decompose work into tasks** — native **Tasks** surface for the canonical task record. You can also read and update the same tasks programmatically with the **agent_bus** tool (action `list_tasks`, action `update_task`, action `complete_task`).
- **Hand a task to another agent / pass output for review** — the **agent_handoff** tool, paired with native **Comms** for the conversation/thread that travels with the handoff.
- **Run isolated parallel work** (e.g. Codex implements a spec while the Agent keeps designing) — **delegate_task** to a worker-agent. Each worker runs in its own context and reports back.
- **Approvals before merge / before user-facing output** — native **Approvals** surface. Do not approve your own trust-boundary or external-facing work; route it through Approvals.
- **Reconfigure an agent's role, toolsets, or skills** (e.g. flip an agent into "implementer" Mode 2, grant Codex toolsets) — the **manage_agent** tool. Never edit agent config files by hand.
- **Recurring delegation** (scheduled review passes, nightly migrations) — the **cron** tool.
- **Discover what tools/toolsets an agent has** before scoping who can own a step — run **/tools**.
- **Status / heartbeat / event logging** as work moves through the matrix — the **agent_bus** tool: action `update_heartbeat`, action `read_heartbeats`, action `log_event`.
- **Goals that frame the work** — the **agent_bus** tool, action `get_goals` and action `update_goals`.
- **Human gates / waiting-human items** (e.g. requirement intake answers, an approval only a person can give) — the **agent_bus** tool, action `check_human_tasks`, plus a `[HUMAN]` task on the Tasks surface.
- **Inbox / incoming messages** the orchestrator is waiting on — the **agent_bus** tool, action `check_inbox`.
- **Memory** captured while delegating (decisions, specs, learnings) — the **memory** tool, persisted to the agent's `MEMORY.md` / `memory/<day>.md`. Persisted facts retrievable via the **agent_bus** tool, action `write_memory`.
- **Identity / workspace** — the orchestrator and each agent know their own name and working directory from the agent's identity and workdir; reference those, not environment variables.

If a step in your delegation plan has no Elevate mechanism above, do not invent a command. Say so plainly and raise a `[HUMAN]` task on the Tasks surface describing what's missing.

---

## Subagent Dispatch Contract

When using `delegate_task`, route by owner and brief the child as if it has never seen the conversation.

- Set `agent` for specialist-owned work. Use `agent="admin"` for Admin/deal/transaction work, full Admin-board CMA runs, Admin Hub CMA cards, SkySlope, WEBForms, MLC, signing packages, subject removal, closing, checklists, and admin-result-writer closure. Use `agent="analyst"` for research, market-support packets, system health, pipeline analytics, and pricing-trend evidence that does not mutate Admin deal records or attach reports.
- Put the exact operating brief in `context`: user intent, selected deal title/id, address/MLS/contact if known, loaded skill/workflow name, test-vs-client-delivery mode, no-send or approval constraints, expected artifact/record updates, fallback behavior, and what counts as done.
- For Admin-board skill tests, if the initially selected test deal lacks property identity, instruct Admin to choose a real non-mock board deal with sufficient data and run the full workflow unless the user explicitly required that exact deal.
- Treat subagent summaries as self-reports. Verify returned IDs, file paths, attachments, and record changes before telling the user the work succeeded.

---

*Deployment note: replace "Orchestrator" / "Agent" with your actual agent names.*
