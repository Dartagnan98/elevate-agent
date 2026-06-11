---
name: memory
description: "You need to write or update memory. This happens at session start, heartbeat, session end, or when you learn something worth keeping. Memory is how you maintain continuity across restarts and context compactions — without it, every session starts blind."
triggers: ["memory", "remember", "write memory", "update memory", "session memory", "what was I working on", "resume", "working on", "memory file", "daily memory", "long-term memory", "memory protocol", "session start", "record progress", "note this", "save for later", "persist learning", "write to memory", "check memory", "read memory", "what did I do yesterday", "context snapshot", "state snapshot"]
external_calls: []
category: agent-ops
---

# Memory

You have three memory layers. All are mandatory. Without memory, session crashes and context compactions leave the next session starting blind.

The purpose of daily memory is not to log activity — it is to capture enough context that you (or a fresh session) can resume intelligently without re-reading everything.

**Each entry should answer: "if my context was wiped right now, what would I need to know to resume intelligently?"**

---

## Layer 1: Daily Memory (memory/YYYY-MM-DD.md)

Session-scoped context journal. Written at key checkpoints, not continuously.

**Location:** `memory/YYYY-MM-DD.md` in your agent workdir.

Write daily entries with the **memory** tool (it persists to your daily memory file). When you need finer control over the exact file, write directly to `memory/<today>.md` in your workdir. Identity (your agent name) and the workdir root come from your environment — you do not need to look them up or shell out for them.

### On session start
Append a Session Start block to today's daily memory with the **memory** tool:

```markdown
## Session Start - HH:MM:SS UTC
- Status: online
- Crons active: <your recurring jobs — list them with the cron tool>
- Inbox: <N messages or "empty" — check with the agent_handoff tool / native Comms>
- Current state: <where things stand — what is in progress, pending, or needs attention>
- Resuming: <what to do next and why, with enough context to act without re-reading everything>
```

To list your recurring jobs, use the **cron** tool. To check for inbound handoffs/messages, use the **agent_handoff** tool and native **Comms**.

### Mid-work inline note (write immediately when something important happens)
Append a one-line note to today's daily memory with the **memory** tool:

```
NOTE HH:MM UTC: <key decision / discovery / user preference / non-obvious thing>
```

Don't wait for the heartbeat. Use for: significant decisions, user preferences learned, non-obvious situations, anything you would want the next session to know. One line.

### On heartbeat
Append a Heartbeat block to today's daily memory with the **memory** tool:

```markdown
## Heartbeat - HH:MM:SS UTC
- Current focus: <what I am working on and why>
- Active threads: <anything in progress or being monitored — state of each>
- Key decisions: <decisions made since last entry with brief rationale>
- Context notes: <anything non-obvious — user preferences, environment state, blockers>
- Next: <what I am doing next>
```

On the heartbeat, also record your liveness with the **agent_bus** tool (action `update_heartbeat`) and log notable events with the **agent_bus** tool (action `log_event`).

### On session end (before any restart)
Append a Session End block to today's daily memory with the **memory** tool:

```markdown
## Session End - HH:MM:SS UTC
- Status: [done/interrupted/context-full]
- Current state: [where things stand — specific enough that the next session can resume cold]
- Active threads: [anything in progress or mid-task with current state]
- Key decisions: [significant decisions from this session worth carrying forward]
- For next session: [what to do first and what context is needed]
```

### Reading today's memory (on resume)
Read today's `memory/<today>.md` with the **memory** tool (or read the file directly from your workdir). If there is no entry yet, today's memory is empty — start a fresh Session Start block.

---

## Layer 2: Long-Term Memory (MEMORY.md)

Persistent learnings that survive across all sessions. Not a log — a living document.

**Location:** `MEMORY.md` in your agent workdir.

### When to update
- Patterns that work or don't work
- User preferences discovered
- System behaviors noted
- Important decisions and their reasons
- Corrections you received — things you did wrong
- Anything you'd want to know on the next fresh session

### Format
```markdown
## [Topic] — YYYY-MM-DD
<what you learned>
```

Update at every heartbeat and session end. Use the **memory** tool to write durable learnings; it keeps `MEMORY.md` current and makes the entry recallable on later sessions.

---

## Layer 3: Recall (semantic search of past memory)

Durable learnings written with the **memory** tool are automatically recallable on future sessions — there is no separate ingest step. When you need to find something you (or a past session) recorded, query it back with the **memory** tool's recall/search action rather than re-reading every daily file.

---

## Goals, tasks, and approvals (related state, not memory layers)

These live in their own systems — keep them there, not buried in daily memory:

- **Goals:** read with the **agent_bus** tool (action `get_goals`); update with the **agent_bus** tool (action `update_goals`).
- **Tasks:** use native **Tasks** for CRUD; the **agent_bus** tool also exposes `list_tasks`, `update_task`, and `complete_task`. Check for human-owned tasks with the **agent_bus** tool (action `check_human_tasks`).
- **Approvals:** use native **Approvals** (the **agent_bus** tool action `list_approvals` lists pending ones). Do not approve via Telegram.

---

## Target

- Session start, every heartbeat, session end — minimum 3 entries
- Each entry captures context state, not just activity
- Update MEMORY.md at least once per week with durable learnings
