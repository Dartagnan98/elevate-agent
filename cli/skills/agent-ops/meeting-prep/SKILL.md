---
name: meeting-prep
description: "Prepare users before meetings and process notes/transcripts afterward. Updates CRM, tasks, and follow-up drafts."
category: agent-ops
---

# Meeting Prep and Processing Skill

## Before Meeting

For each upcoming meeting:

1. Pull event details.
2. Identify attendees and organizations.
3. Query CRM for each attendee.
4. Search recent email/message/task context (use the agent_bus tool, action list_tasks, plus the Comms history for prior messages).
5. Search configured meeting-note tools for prior calls.
6. Write a brief:

```markdown
# Meeting Brief: <title>

## Logistics
- Time:
- Location/link:
- Attendees:

## Relationship Context
- Who they are:
- History:
- Last interaction:

## Why This Meeting Matters

## Suggested Agenda

## Open Loops

## Follow-Up Candidates
```

7. Surface the brief at the configured time. Deliver it via agent_handoff and post a Comms message to the user; if the brief must arrive at a fixed time, schedule that surfacing with cron.

## After Meeting

When notes/transcripts are available:

1. Extract summary, decisions, commitments, and follow-ups.
2. Append CRM interactions for attendees.
3. Create follow-up records/tasks in native Tasks (or use the agent_bus tool, action update_task / complete_task, to move existing items).
4. Draft recap or next-step message if useful, and route it through native Comms. If it needs sign-off before going out, file it in native Approvals.
5. Save the transcript/summary under `meetings/<category>/<event-id>/` in the agent's workdir, and record the key takeaways with the memory tool (also append to the agent's MEMORY.md / memory/<day>.md).
6. Heartbeat the run so the meeting-processing loop is tracked: use the agent_bus tool, action update_heartbeat, and action log_event for notable decisions.

## Meeting Note Sources

Tool-agnostic. Supported patterns:

- Notion page/transcription search
- Fathom/Zoom/Granola/Fireflies exports
- Google Drive docs
- local transcript files
- manual user notes

If no transcript exists, create a summary from available context and mark it `summary_only: true`.

## Notes

- Goals for this loop live with the agent_bus tool (action get_goals / update_goals); use them to decide which meetings to prioritize.
- To change which toolsets, skills, or role this agent runs with, use manage_agent — never hand-edit agent config files.
- For isolated parallel work (e.g. processing several transcripts at once), use delegate_task / worker-agents.
- To inspect what tools are available in the current run, use /tools.
- Environment/identity (the agent's workdir, name, and org) come from the agent's own context — there are no shell env vars to read.
- If a step requires a meeting-note source or surfacing channel that has no Elevate mechanism, say so plainly and raise a [HUMAN] task rather than inventing a command.
