---
name: knowledge-base
description: "You are about to research a topic, answer a factual question about the org, or look up context about a person, project, or tool. Before searching the web or asking the user, query the knowledge base first — the answer may already exist from a previous research session. After you complete any substantial research, ingest your findings so future agents do not repeat the same work. The KB is the org's shared memory across all agents."
triggers: ["knowledge base", "kb", "search knowledge", "query knowledge", "ingest", "rag", "semantic search", "what do we know about", "check knowledge", "save to kb", "index documents", "search docs", "look up", "query kb", "kb query", "kb ingest", "store research", "preserve findings", "check existing knowledge", "has anyone researched", "kb setup", "initialize knowledge base"]
category: agent-ops
---

# Knowledge Base

The knowledge base is the org's shared memory across agents — research notes, facts about people/projects/tools, and durable findings. Query it before searching externally. Persist what you learn so future agents don't repeat the work.

In Elevate, this memory lives in two places that work together:
- The **memory** tool — semantic recall/store across the agent's and org's memory. This is the closest thing to a semantic search index; use it for "what do we know about X" lookups and to store durable findings.
- The agent's own files — `MEMORY.md` and `memory/<day>.md` in the agent's workdir. These are the canonical, human-readable record of what the agent has learned.

---

## Query (before starting research)

Use the **memory** tool to recall what's already known before doing any new research.

Query memory:
- Before starting any research task — check if knowledge already exists
- When referencing named entities (people, projects, tools) — check for existing context
- When answering factual questions about the org — recall before searching externally

Also read the agent's `MEMORY.md` (and recent `memory/<day>.md` entries) in its workdir, which hold the canonical record of prior findings.

---

## Ingest (after completing research)

After completing substantive research, persist your findings so they survive into future sessions:

- Use the **memory** tool to store the finding for semantic recall (this is the shared, searchable layer).
- Write the durable, human-readable version into the agent's `MEMORY.md` (for facts that should always be loaded) or `memory/<day>.md` (for dated session notes) in the agent's workdir.

Persist after:
- Completing substantive research (always record your findings)
- Updating `MEMORY.md`
- Learning important facts about the org, users, or systems

There is no separate "shared vs private collection" toggle in Elevate. The memory tool's scope is the agent and its org; `MEMORY.md`/`memory/` are the agent's own files. Store the durable summary, not raw dumps.

---

## Sharing findings with other agents

If a finding is relevant to another agent or the team, surface it where they'll see it:
- **agent_handoff** + native **Comms** to pass context to a specific agent.
- A native **Task** (Tasks) if the finding implies follow-up work, optionally tracked via the **agent_bus** tool (action `list_tasks` / `update_task` / `complete_task`).

---

## Workflow Pattern

```
1. User asks question about <topic>
2. Recall via the memory tool + read MEMORY.md — check existing knowledge
3. If found → answer from memory, cite the source
4. If not found → research externally (web tools, etc.)
5. After research → store findings via the memory tool + write to MEMORY.md / memory/<day>.md
6. Answer the user with fresh knowledge now persisted
```

---

## Note on a dedicated semantic index

Elevate has no separate standalone RAG/vector-collection service the way some other systems do — the **memory** tool plus the agent's `MEMORY.md`/`memory/` files ARE the knowledge layer. If a workflow genuinely needs a dedicated external vector store or document index that Elevate doesn't provide, don't invent a command for it — raise a `[HUMAN]` task describing what's needed.
