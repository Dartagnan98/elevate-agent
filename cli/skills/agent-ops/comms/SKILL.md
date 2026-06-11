---
name: comms
description: "A message has just arrived in your session from the fast-checker daemon — you see a block starting with === TELEGRAM or === AGENT MESSAGE. Read it, decide what action to take, and reply using the command shown in the message header. If it is from the user, they are waiting for your response right now. If it is from another agent, they may be blocked on your reply. Handle all messages before returning to other work."
triggers: ["=== TELEGRAM", "=== AGENT MESSAGE", "message received", "incoming message", "reply to", "telegram from", "agent message from", "fast-checker", "message injected", "respond to message", "handle message", "incoming telegram", "message block"]
external_calls: []
category: agent-ops
---

# Handling Incoming Messages

Messages arrive in real time and appear in your input as formatted blocks. Read each one, decide what to do, and respond using the matching Elevate tool described below.

## Message Format

```
=== TELEGRAM from <name> (chat_id:<id>) ===
<message text>
Reply with: the Comms tool (reply to chat_id <id>)

=== AGENT MESSAGE from <agent> [msg_id: <id>] ===
<message text>
Reply with: the agent_handoff tool to <agent> (reference msg_id <id>)
```

## What To Do

1. Read every message block in the injected content.
2. For each message, take action or respond:
   - **From the user (Telegram):** reply with the native **Comms** tool, addressed to the `chat_id` shown in the header.
   - **From another agent:** reply with the **agent_handoff** tool addressed to the sending agent. Reference the `msg_id` so the conversation threads correctly. To see queued agent messages, use the **agent_bus** tool (action `check_inbox`).
3. Temp file cleanup is handled for you — you do not need to manage inbox files.

## Priority

- **Urgent messages:** handle immediately. Save your current work state first (use the **memory** tool, and update your `MEMORY.md` / `memory/<day>.md`).
- **Callback queries (inline button presses):** process the `callback_data` and acknowledge with the **Comms** tool.
- **Photos:** a local file path is provided in the block — read it directly.

## Waiting for a Response

If you send a Telegram message that asks a question and you need the answer before continuing, you MUST end your current response entirely (stop all tool execution, produce no more output). The user's reply will be injected as your next turn. If you keep executing tools after asking the question, the reply gets queued and you will not see it until your turn ends. End your turn, and the reply arrives.

## Related Comms Actions

- **Heartbeats / liveness:** use the **agent_bus** tool — action `update_heartbeat` to post your status, action `read_heartbeats` to see the fleet.
- **Activity log:** use the **agent_bus** tool (action `log_event`) to record a notable event.
- **Tasks tied to a message:** view/create work via the native **Tasks** tool. For programmatic task ops use the **agent_bus** tool — actions `list_tasks`, `update_task`, `complete_task`. To hand isolated parallel work to a worker, use **delegate_task**.
- **Approvals:** route anything needing sign-off through the native **Approvals** tool. Check pending items with the **agent_bus** tool (action `list_approvals`).
- **Human follow-ups:** surface a `[HUMAN]` task and check outstanding ones with the **agent_bus** tool (action `check_human_tasks`).
- **Goals:** read/update with the **agent_bus** tool — actions `get_goals`, `update_goals`.
- **Recurring comms checks:** schedule with the **cron** tool.
- **Reconfiguring an agent** (toolsets, skills, role) — use the **manage_agent** tool. Never edit agent config files by hand.
- **Available tools:** run **/tools** to see what you can call.
- Your workdir and identity (org, agent name) come from your session context — reference them directly; there are no shell environment lookups.

## Done

After handling all messages, return to your current task or wait for the next message.
