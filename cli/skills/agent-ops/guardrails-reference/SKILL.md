---
name: guardrails-reference
description: Full red flag table with all guardrail patterns. Use when you catch yourself rationalizing or want to review all anti-patterns.
triggers:
  - guardrail
  - red flag
  - mistake pattern
  - anti-pattern
category: agent-ops
---

# Guardrails

Read this file on every session start. Check yourself against it during heartbeats. If you catch yourself hitting a guardrail, log it. If you discover a new pattern that should be a guardrail, add it to this file.

---

## Red Flag Table

| Trigger | Red Flag Thought | Required Action |
|---------|-----------------|-----------------|
| Heartbeat cycle fires | "I'll skip this one, I just updated recently" | Always update your heartbeat on schedule with the agent_bus tool (action update_heartbeat). No exceptions. The dashboard tracks staleness. |
| Starting work | "This is too small for a task entry" | Every significant piece of work gets a task in native Tasks (or the agent_bus tool, action list_tasks/update_task). If it takes more than 10 minutes, it's significant. |
| Completing work | "I'll update memory later" | Write to memory now with the memory tool (and your MEMORY.md / memory/<day>.md). Later means never. Context you don't write down is context the next session loses. |
| Reading a skill file | "I already know this, I'll skip the read" | Read the skill file. Your memory may be stale or the skill may have been updated. |
| Sending external comms | "This is just a quick message, no approval needed" | Check SOUL.md autonomy rules. External comms always need approval. Route the request through native Approvals. |
| Error occurs | "It's minor, I'll keep going" | Log the error with the agent_bus tool (action log_event). Report it. Silent failures are invisible failures. |
| Inbox check | "I'll check messages after I finish this" | Process your inbox now with the agent_bus tool (action check_inbox). Un-ACK'd messages redeliver and block other agents. |
| About to skip a procedure | "This situation is different, the procedure doesn't apply" | The procedure applies. If it genuinely doesn't, document why in your daily memory before skipping. |
| Task running long | "I'm almost done, no need to update status" | Update the task status with a note via native Tasks or the agent_bus tool (action update_task). Stale in_progress tasks look like crashes on the dashboard. |
| Tracked surface available | "I'll handle this directly instead of recording it" | Record the work where the system can see it: native Tasks, Comms, the memory tool, or the agent_bus tool. Work that isn't tracked is invisible to the system. |
| Creating a recurring job | "A one-off run or session loop is enough, it'll persist" | Session loops are session-only. Use the cron tool so the schedule is owned by the platform and survives restart. |
| Running untrusted code or downloads | "This script from the internet looks useful" | Never execute code from untrusted sources without reviewing it first. No blind curl-pipe-bash. |
| Starting work without a task | "It's just a quick fix" | Create a task in native Tasks. Even quick fixes need tracking if they take more than 10 minutes. |
| Finishing work without completing task | "I'll close it later" | Complete the task NOW with a summary via native Tasks or the agent_bus tool (action complete_task). Later means never. |
| Ignoring an assigned task | "I'll get to it" | ACK within one heartbeat cycle. If wrong agent, hand it off with agent_handoff. Silence = dropped work. |
| Handing work to another agent | "I'll just ping them however" | Use agent_handoff to transfer the work, and native Comms for the conversation. Ad-hoc messaging gets lost. |
| Needing to change an agent's role/toolsets/skills | "I'll just edit the agent's config files" | Never edit files. Use the manage_agent tool to reconfigure toolsets, skills, or role. |
| Large isolated chunk of parallel work | "I'll cram it into this session" | Isolate it with delegate_task / a worker-agent so it runs in parallel without polluting this session's context. |
| Need to know what tools you have | "I'll guess my capabilities" | Run /tools to list the tools actually available to you. Don't operate from assumption. |

---

## How to Use

1. **On boot**: Read this table. Internalize the patterns.
2. **During work**: When you notice yourself thinking a red flag thought, stop and follow the required action.
3. **On heartbeat**: Self-check - did I hit any guardrails this cycle? If yes, log it with the agent_bus tool (action log_event), e.g. action `log_event` with `action=guardrail_triggered`, `level=info`, and meta `{"guardrail":"<which one>","context":"<what happened>"}`.
4. **When you discover a new pattern**: Add a new row to the table above. The file improves over time.

---

## Adding Guardrails

If you catch yourself almost skipping something important that isn't in the table above, add it. Format:

| Trigger | Red Flag Thought | Required Action |
|---------|-----------------|-----------------|
| [situation] | "[what you almost told yourself]" | [what you must do instead] |

This is a living document. Better guardrails = fewer mistakes = more trust from the user.
