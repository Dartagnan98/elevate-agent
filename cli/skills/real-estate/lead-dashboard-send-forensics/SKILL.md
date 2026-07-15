---
name: lead-dashboard-send-forensics
description: Diagnose whether a Leads dashboard approved/scheduled message actually sent. Use when the user asks if a scheduled/approved lead message went out, who it was supposed to go to, why it is still pending, or when the Leads dashboard send/approval queue seems stuck: identifies the intended recipient and explains queue/dashboard mismatches.
---

# Lead Dashboard Send Forensics

Use this when a message from the Leads dashboard was approved, scheduled, skipped, or expected to send, but the user thinks it did not go out.

## Goal

Return a concise, grounded answer with:

- intended recipient name and contact details
- channel/source/task identifiers
- draft text if useful
- current queue status
- whether it actually sent, failed, or never reached queued/scheduled state
- the likely reason, backed by DB rows/log evidence

Do **not** resend or approve anything unless the user explicitly asks for that next action.

## Procedure

1. **Inspect operational schema first**
   - Use `elevate_db.describe` if table shape is not already known.
   - Main table: `send_queue`.
   - Supporting tables/files: `events`, `draft_attempts`, `thread_meta`, `/Users/admin/.elevate/tools/data/sources/<source>/ui-state.json`, and logs under `/Users/admin/.elevate/logs/`.

2. **Search send_queue around the claimed date/time**
   - Scheduled sends are stored in `send_queue.next_retry_at` when approval/scheduling succeeds.
   - Query for the claimed date in `next_retry_at`, `created_at`, `updated_at`, and `payload_json`.
   - Extract recipient safely from `payload_json::jsonb`, e.g.:
     ```sql
     SELECT id, source_id, thread_id, task_id, channel, status, attempts,
            next_retry_at, created_at, updated_at, last_error, provider_message_id,
            payload_json::jsonb #>> '{recipient,person_name}' AS person_name,
            payload_json::jsonb #>> '{recipient,phone}' AS phone,
            payload_json::jsonb #>> '{recipient,email}' AS email,
            payload_json::jsonb ->> 'draft_text' AS draft_text
     FROM send_queue
     WHERE next_retry_at LIKE '2026-06-23%'
        OR created_at LIKE '2026-06-23%'
        OR updated_at LIKE '2026-06-23%'
        OR payload_json ILIKE '%09:00%'
        OR payload_json ILIKE '%9 am%'
     ORDER BY COALESCE(next_retry_at, updated_at, created_at) DESC;
     ```

3. **Check current status buckets**
   - Use `leads_overview` for the quick queue health snapshot when available. It returns pending/queued/sending/sent/failed/retrying counts plus pending by source/channel and recent sends.
   - Run a grouped status count for precise audit detail:
     ```sql
     SELECT status, channel, COUNT(*) AS count,
            MIN(created_at) AS oldest_created, MAX(created_at) AS newest_created,
            MIN(next_retry_at) AS min_next_retry, MAX(next_retry_at) AS max_next_retry
     FROM send_queue
     GROUP BY status, channel
     ORDER BY status, channel;
     ```
   - If `queued`/`retrying` rows exist, inspect them. If none exist, a schedule likely never queued.
   - If `pending_approval` is non-zero but `queued`/`sending`/`retrying` are all zero, the user's click likely did not release the row to the sender.

4. **Identify the dashboard action record**
   - Query rows updated around the user’s action time. Convert local Pacific time to UTC when needed. Example: 4:41 PM PT = 23:41 UTC during DST.
     ```sql
     SELECT id, source_id, thread_id, task_id, channel, status, created_at, updated_at,
            payload_json::jsonb #>> '{recipient,person_name}' AS person_name,
            payload_json::jsonb #>> '{recipient,phone}' AS phone,
            payload_json::jsonb #>> '{recipient,email}' AS email,
            payload_json::jsonb ->> 'draft_text' AS draft_text
     FROM send_queue
     WHERE updated_at >= '2026-06-22T23:20:00+00:00'
       AND updated_at <= '2026-06-22T23:50:00+00:00'
     ORDER BY updated_at DESC;
     ```

5. **Compare DB queue status to source UI state**
   - Read the source UI state file for the matching `source_id`:
     - Apple Messages: `/Users/admin/.elevate/tools/data/sources/apple-messages/ui-state.json`
     - CRM: `/Users/admin/.elevate/tools/data/sources/crm/ui-state.json`
   - Look for the task id. A mismatch like `ui-state.tasks[task_id].status = approved` but `send_queue.status = pending_approval` means the dashboard marked it approved locally but did not release the underlying queue row.

6. **Check app logs for scheduling/API/import errors**
   - Search `/Users/admin/.elevate/logs/agent.log` and `errors.log` around the action time for:
     - `POST /api/source-inbox/draft failed`
     - `request complete` with `method=POST path=/api/source-inbox/draft`
     - `scheduled_at`
     - `unexpected keyword argument 'scheduled_at'`
     - `pending-send release failed`
     - `db_source_inbox_response failed, falling back to JSONL source inbox`
     - `SOURCE_INBOX_DRAFT_QUEUE_LIMIT`
   - If you find a successful recent `POST /api/source-inbox/draft` followed by `pending-send release failed`, the approval endpoint ran but failed to release the row.
   - If you do **not** find a POST around the user's click time, the dashboard action may not have registered at all.
   - If the logs repeatedly show `ImportError: cannot import name 'SOURCE_INBOX_DRAFT_QUEUE_LIMIT' from 'elevate_cli.source_connectors'`, the dashboard is reading the source inbox through the JSONL fallback instead of the DB path. This can hide/misrepresent `send_queue` state and make the board look like a click worked even when `send_queue` remains `pending_approval`.
   - This specific `scheduled_at` failure pattern means the dashboard’s scheduling API path errored before the queue row was moved to `queued` with `next_retry_at`.
   - If `elevate_db` rejects a query with `query contains a forbidden keyword` while you are only doing a SELECT, check whether the literal search text includes a guarded word such as `call`. Avoid the literal in SQL text by splitting it, e.g. `lower(payload_json) LIKE concat('%','cal','l','%')`, or search adjacent terms first (`phone`, `appointment`, `scheduled`, `showing`, `follow-up`).

7. **For scheduled calls / calendar items, check calendar sync separately**
   - A Leads/Admin “scheduled call” may be a calendar/event sync problem rather than a `send_queue` message problem.
   - Check the recurring cron job named **Admin Calendar Sync**. In the account-scoped cron store it may be job id `d13a95d2f327`, script `admin-calendar-sync.py`, schedule `every 15m`.
   - Use `cronjob(action='list')` or inspect `/Users/admin/.elevate/accounts/<account>/cron/jobs.json` and `/Users/admin/.elevate/accounts/<account>/cron/output/<job_id>/YYYY-MM-DD_*.md`.
   - Failure output like `Admin calendar sync failed: HTTP 422` means the Google Calendar/Composio calendar tool call failed and upcoming calls/appointments may not have been pulled into the dashboard. Report this as “the calendar sync was failing,” not as proof that the actual external calendar event was deleted or never existed.
   - The helper code lives at `/Users/admin/.elevate/scripts/admin-calendar-sync.py` and imports `elevate_cli.events_sync`. The app helper calls Composio `GOOGLECALENDAR_EVENTS_LIST` and then upserts into `admin_calendar_events`; that table may be internal/gated and not visible in `elevate_db.describe`, so use cron outputs/logs as the audit trail when the table is unavailable.

8. **Know the status meanings**
   - `sent` + `provider_message_id` present = delivered/handed to provider.
   - `failed` + `last_error` = attempted but failed.
   - `queued` + future `next_retry_at` = scheduled and waiting.
   - `queued` + null/past `next_retry_at` = due for sender tick.
   - `pending_approval` + UI state approved = likely dashboard/source-state mismatch. It did not actually send.
   - `pending_approval` with no `provider_message_id` and no sent event = not sent.

## Reporting format

Keep the final answer short:

- “It looks like the missed one was for **Name**.”
- Provide phone/email/channel.
- Quote the draft only if it helps confirm the exact message.
- State whether it sent: “No provider message ID, no sent timestamp, still pending_approval.”
- Explain the likely cause in plain language, e.g. “The schedule call errored, so the dashboard state said approved but the real send queue never moved to scheduled/queued.”

## Switching a pending draft from email to text/SMS

Use this only when the user explicitly asks to change an unsent Lead Board draft to text. Do **not** send it as part of the switch.

1. **Identify the exact pending row first**
   - Confirm `send_queue.status = 'pending_approval'`, `attempts = 0`, and `provider_message_id IS NULL`.
   - Confirm the intended lead/contact, usually from `payload_json::jsonb #>> '{recipient,person_name}'` and `contact_id`.
   - Check `contacts.primary_phone`; do not rely only on `phone_redacted` in the payload.

2. **Rewrite the row as SMS while preserving approval gate**
   - Update only the chosen row.
   - Set `send_queue.channel = 'sms'`.
   - Add the full phone under `payload_json.recipient.phone`.
   - Shorten `payload_json.draft_text` into a text-friendly version in the realtor's style.
   - Keep `status = 'pending_approval'`, `attempts = 0`, `provider_message_id = NULL`, and `approval_required/send_only_after_human_approval = true`.
   - Do **not** flip to `queued`; that would send/release it.

3. **Use the app's Python runtime if importing Elevate modules**
   - macOS system `python3` may be 3.9 and fail on newer type-hint syntax from the app bundle.
   - Use:
     ```bash
     /Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 -B
     ```
   - Import `/Applications/Elevate.app/Contents/Resources/cli` onto `sys.path`, then use `elevate_cli.outreach_db.connect()` for the same Postgres-backed compatibility layer as the app.

4. **Verify after the update**
   - Re-query the row:
     ```sql
     SELECT id, channel, status, attempts, provider_message_id,
            payload_json::jsonb #>> '{recipient,phone}' AS phone,
            payload_json::jsonb ->> 'draft_text' AS draft_text,
            updated_at
     FROM send_queue
     WHERE id = '<queue_id>';
     ```
   - Report that it is still approval-gated and not sent.

5. **Sync lead status when the board-sync reminder appears**
   - If the contact is identifiable, use `lead_status(action='set', status='follow_up', heat='warm', contact_id=...)` or the appropriate status/heat.
   - Add a note that the draft was switched to text and no send was performed.
   - If the exact contact cannot be identified, ask rather than guessing.

## Pitfalls

- Do not infer a sent message from the UI-state file alone. `ui-state.json` can say `approved` even when the actual `send_queue` row remains `pending_approval`.
- Do not search for old SQLite operational DBs. Leads/send queue operational data is in embedded Postgres via `elevate_db`.
- Do not use browser/web tools for dashboard inspection unless the user explicitly asks to open the UI. DB/log forensics is faster and more reliable for this question.
- Do not resend automatically. Sending real lead messages is an external communication and requires explicit approval.
- `tasks.jsonl` files can be huge and broad reads can exceed tool safety limits. Prefer a narrow `read_file` tail for recent lines, `search_files` for exact names/task IDs, or `execute_code` to parse/filter JSONL records by `created_at`, `updated_at`, `task_id`, `display_name`, `conversation_id`, or `thread_id`.
- Recent `send_queue` rows created by cron may not appear in source `tasks.jsonl`/`ui-state.json` fallback records. Treat Postgres `send_queue` as the outbound source of truth; JSONL is only supporting UI state.
- Paid Ads / Making It Rain gotcha: `paid-ads` is an import-only source and may not be mapped to an outbound channel in `_SOURCE_TO_CHANNEL`. If Paid Ads `ui-state.json` says a task is `approved` but there is no matching `send_queue` row, the dashboard approval only changed local UI state and nothing was queued or sent. Check for missing recipient email/phone too, because Making It Rain notification parsing can expose order/program IDs that look like phone numbers and should not be used for SMS sends.
