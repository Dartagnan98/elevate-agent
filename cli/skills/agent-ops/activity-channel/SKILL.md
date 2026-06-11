---
name: activity-channel
description: "You have completed something significant and want the whole org — all agents and the user — to know about it. Or you need to broadcast a status update, a briefing summary, or a coordination announcement that is not directed at one specific agent. Use this skill any time the audience is the entire org rather than a single person or agent."
triggers: ["post activity", "activity channel", "broadcast", "announce to everyone", "org announcement", "post to channel", "notify all agents", "team update", "org-wide update", "let everyone know", "status broadcast", "announce completion", "briefing summary", "coordination update", "fleet announcement"]
external_calls: []
category: agent-ops
---

# Activity Channel

The activity channel is the shared org-wide feed every agent and the user can observe in real time. It surfaces in the dashboard Activity view. Use it for org-wide announcements, not for messages directed at one specific agent.

---

## Posting to the Activity Channel

Use the **agent_bus** tool (action `post_activity`). Pass the broadcast text as `event` (or `title`), and optionally a `category` (defaults to `action`) and `metadata`.

**When to use:**
- Announcing a major task completion that affects the whole org
- Broadcasting a status update during the day
- Sharing a briefing summary
- Announcing a system change (new agent online, agent reconfigured, etc.)

---

## Agent-to-Agent Messages Are Already Visible

When you message another agent through **agent_handoff** (or reply in **Comms**), that exchange is already recorded in the shared activity feed. You do not need to post an activity event separately for those — only broadcast when the audience is the whole org, not the one agent you handed off to.

---

## Direct Message vs Activity Channel

| Use case | Mechanism |
|----------|-----------|
| Reply to the user | Reply with the command shown in the incoming message header (see the `comms` skill) |
| Message to a specific agent | the **agent_handoff** tool, or reply in native **Comms** |
| Org-wide announcement | the **agent_bus** tool (action `post_activity`) |

---

## Examples

All of these are calls to the **agent_bus** tool with action `post_activity`:

- **Morning briefing summary** — `event`: "Morning briefing complete. Today's focus: <goals>. Active agents: <list>."
- **Major completion** — `event`: "researcher completed competitive analysis — 3 key findings in task <task_id>."  (find the task id via native **Tasks** or agent_bus `list_tasks`)
- **Agent coming online** — `event`: "analyst (sentinel) is online and running nightly metrics."
- **System change** — `event`: "New agent 'writer' is now online and onboarding." (agents are stood up / reconfigured via the **manage_agent** tool, never by editing files.)

Set `category` to match the kind of event when it helps the feed read clearly (e.g. `milestone` for a major completion, `action` for routine status).

---

## Keep It Signal, Not Noise

Post to the activity channel for things worth the whole org knowing. Don't post every small action — only significant events that affect coordination or that the user would want to see. Your own work is already captured by event logging and heartbeats; reserve broadcasts for what the rest of the org needs to act on or be aware of.
