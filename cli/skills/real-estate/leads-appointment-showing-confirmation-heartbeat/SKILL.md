---
name: leads-appointment-showing-confirmation-heartbeat
description: Focused Leads heartbeat for appointment and showing confirmation. Use when checking booked lead appointments/showings in the next ~48 hours, drafting reminder/confirmation messages only when needed, and logging all-quiet runs.
version: 0.1.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [real-estate, leads, heartbeat, calendar, appointments, showings]
---

# Leads Appointment & Showing Confirmation Heartbeat

Use for the focused Leads heartbeat that only checks booked appointments and showings in the next ~48 hours. This workflow is draft-only: never send confirmations or change calendar events in cron.

## Steps

1. Load context.
   - Read the Leads surface config via `agent_bus(action='get_surface_config', surface='leads')`.
   - Read the account workspace `heartbeats/leads/learnings.md` for the user's account.
   - Drain pending tasks for `leads` and `outreach`; only handle tasks inside this appointment/showing focus.

2. Verify calendar context using Browser Use first.
   - Use the local/free Browser Use CLI through `terminal`, e.g. `browser-use --json open 'https://calendar.google.com/calendar/u/0/r/week/<date>'` then `browser-use --json state`.
   - If Browser Use is authenticated and calendar rows are readable, use the state output to identify appointment/showing/consult/tour events in the next ~48 hours.

3. Fallback when Browser Use cannot read calendar.
   - If Browser Use lands on Google sign-in or `extract` is unavailable, do not stall.
   - Use the existing local Google Workspace CLI OAuth fallback: `gws calendar calendarList list`, then query events with `gws calendar events list`.
   - Query primary plus appointment/admin calendars that commonly contain real-estate context: the user's primary calendar, `Lofty Appointment`, both `Lofty-Appointments` calendars, `Admin Calendar`, and `TC Calendar` when present.
   - Strip `Using keyring backend:` from `gws` output before JSON parsing.

4. Filter ruthlessly.
   - Keep only real lead appointments/showings/consults/tours/viewings in the next ~48 hours.
   - Exclude personal events and admin-only deal dates such as completion, adjustment, possession, subject removal, deposit, and TC/Admin deadline reminders.
   - Treat Lofty appointment calendars returning no events as valid evidence of no booked lead appointment.

5. Reconcile before drafting.
   - For each candidate appointment/showing, inspect the attendee/contact thread and existing approvals/send_queue/working-state context.
   - Skip anything already confirmed or already covered by an active pending approval/draft.
   - If not confirmed, stage a review-only confirmation/reminder draft. Never send.
   - Flag reschedule requests, missing attendee context, or calendar conflicts as human/EA tasks rather than guessing.

6. Log and report.
   - Write `history/<UTC-ISO-timestamp>.json` with what was checked, what was drafted, key findings, and one-line summary.
   - If there are no lead appointments/showings needing attention, final cron output should be `[SILENT]` in heartbeat report mode, but still log history and write an `agent_bus(action='heartbeat', agent_id='leads', surface='leads', status='ok', ...)` event.

## Pitfalls

- Browser Use may show a Google sign-in screen even though `gws` calendar OAuth is valid. Use `gws` fallback and log the reason.
- Do not confuse Admin deal dates, completion/possession reminders, or personal events with lead appointments.
- Do not run the broader Leads heartbeat work from this focused job. New-lead response, hot-lead watch, follow-up sweep, and re-engagement are covered by other focused heartbeats.
- External sends and calendar changes require approval. Drafts only in cron.
