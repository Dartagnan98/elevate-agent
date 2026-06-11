---
name: cron-management
description: "Manage persistent recurring scheduled tasks with the cron tool. Crons survive agent restarts and session boundaries. Use this skill for all cron CRUD: create, update, remove, list, and inspect. Never use /loop for persistent recurring work — that is session-only and dies on restart."
triggers: ["remind me", "every day", "every hour", "every week", "schedule", "recurring", "daily", "weekly", "cron", "loop", "check regularly", "monitor", "keep an eye on", "set up a reminder", "repeat every", "run every", "automate", "schedule task", "list crons", "show crons", "fire cron now", "test cron", "cron log", "cron history", "scheduled task", "cron not firing", "persist cron"]
external_calls: []
category: agent-ops
---

# Cron Management

Crons are persistent recurring scheduled tasks managed by the **cron** tool. They survive agent restarts and session boundaries. The cron tool is the source of truth — use it for all CRUD operations. Never use `/loop` for persistent recurring work (it is session-only and dies on restart).

---

## Listing your crons

Use the **cron** tool (action `list`) to see your scheduled tasks. It returns each cron's name, schedule, last/next fire times, and prompt.

Read each entry to confirm the schedule, the prompt, and whether the cron is enabled.

---

## Adding a recurring cron

Use the **cron** tool (action `create`) with a name, a schedule, and the prompt to run.

**Interval form** — for simple repeated intervals:
- name `heartbeat`, schedule `6h`, prompt "Read HEARTBEAT.md and follow its instructions."
- name `health-check`, schedule `30m`, prompt "Check system health and report anomalies."
- name `daily-sweep`, schedule `1d`, prompt "Run the full daily workflow."

**Cron expression form** — for calendar-anchored schedules (specific time of day, weekdays only, etc.):
- name `morning-report`, schedule `0 9 * * 1-5`, prompt "Generate and send the daily analytics report."
- name `weekly-summary`, schedule `0 17 * * 5`, prompt "Compile and deliver the weekly summary."

Optionally include a human-readable description. After creating, confirm with the cron tool (action `list`). No restart is needed — the cron tool registers it immediately.

---

## Updating a cron

Use the **cron** tool (action `update`) with the cron name and the fields you want to change. You can change the schedule (interval or 5-field cron expression), the prompt, the description, or the enabled state. Multiple fields can change in one update.

- Change the interval: update `heartbeat` with schedule `4h`.
- Switch to a cron expression: update `heartbeat` with schedule `0 */4 * * *`.
- Update the prompt: update `heartbeat` with prompt "Read HEARTBEAT.md, follow instructions, then log state."
- Disable a cron (stops firing without removing it): update `heartbeat` with enabled `false`.
- Re-enable: update `heartbeat` with enabled `true`.

---

## Removing a cron

Use the **cron** tool (action `delete`) with the cron name. Then confirm it is gone with the cron tool (action `list`).

---

## Testing a cron immediately

Elevate's cron tool runs scheduled prompts on the agent's own schedule; there is no manual "fire now into a PTY" mechanism. To verify a cron's prompt works correctly before relying on the schedule, run the prompt directly in your current session (just do the work the cron prompt describes) and confirm it produces the expected result. Once verified, leave the cron to fire on its schedule.

If you specifically need an on-demand trigger for a recurring task and the cron tool does not expose one, that is a gap — do not invent a command. Raise a `[HUMAN]` task describing the need.

---

## Inspecting execution history

Use the **cron** tool (action `list`) to see each cron's last and next fire times. To inspect what a cron actually did when it ran, review your own activity and memory for that run:
- Recent runs are recorded in the activity stream (native **Activity**).
- Anything the cron prompt was told to persist lands in the **memory** tool and the agent's `MEMORY.md` / `memory/<day>.md`.

If you need richer per-execution telemetry (per-run status/duration/error) and the cron tool does not surface it, that is a gap — do not invent a command. Raise a `[HUMAN]` task.

---

## One-shot reminders (gap)

The cron tool is for recurring schedules. For a true one-time, fire-once reminder, prefer a native **Task**: create a task (native **Tasks**, also reachable via the **agent_bus** tool with action `update_task` / `complete_task` and `list_tasks`) with the reminder content and a due date, so it shows up as work to be done at the right time rather than as a recurring schedule.

If you need a precise fire-once timed trigger and neither the cron tool nor a dated task fits, that is a gap — do not invent a command. Raise a `[HUMAN]` task describing the one-shot reminder and when it must fire.

---

## Troubleshooting

**Cron not firing on schedule**
1. Use the cron tool (action `list`) — confirm the next fire time is in the future and the cron is not disabled.
2. Check native **Activity** for the cron's recent runs and any errors.
3. If the next fire time looks stale or wrong, update the cron (cron tool action `update`) to re-set the schedule, then re-list to confirm it recomputed.

**Cron failing repeatedly**
- Review native **Activity** and the **memory** tool for what the failing run produced.
- Common causes: a prompt that asks for something the agent cannot do, a permission issue, or a dependency unavailable. Fix the prompt with the cron tool (action `update`).
- If the failure is environmental (a tool the agent lacks), reconfigure the agent's toolsets/skills with **manage_agent** — never edit config files by hand.

**Just-added cron not appearing**
- The cron tool registers crons immediately. If a newly created cron does not appear, re-run the cron tool (action `list`) to refresh, then re-create it (cron tool action `create`) if it is genuinely missing.

**Disabling without deleting**
- Use the cron tool (action `update`) with enabled `false` to pause a cron. It stays defined and can be re-enabled later with enabled `true`.

**Cron prompt needs different capabilities or a different agent**
- To change which toolsets, skills, or role a cron's agent has, use **manage_agent**. Never edit agent files directly.
- For isolated, parallel one-off work that should run in its own context rather than on a schedule, use **delegate_task** / a worker-agent instead of a cron.

---

## Examples

### Add a heartbeat cron every 6 hours

Use the cron tool (action `create`): name `heartbeat`, schedule `6h`, prompt "Read HEARTBEAT.md and follow its instructions." Confirm with the cron tool (action `list`).

### Schedule a weekday 9am report

Use the cron tool (action `create`): name `morning-report`, schedule `0 9 * * 1-5`, prompt "Generate and send the daily analytics report." Confirm with the cron tool (action `list`).

### Verify a cron's prompt before relying on the schedule

Run the cron's prompt directly in your current session and confirm it produces the expected result. Then leave the cron (cron tool action `list` to confirm it is enabled and scheduled) to fire on its own.

### Debug why a cron is not firing on schedule

1. Use the cron tool (action `list`) — confirm the cron exists, is enabled, and its next fire time is in the future.
2. Check native **Activity** for recent runs and errors.
3. If the schedule looks wrong, update it with the cron tool (action `update`), then re-list to confirm it recomputed.
4. Run the cron's prompt directly in your session to verify the work itself succeeds.
