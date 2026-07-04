---
name: leads-hot-watch-db-timestamps
description: "Guard Hot-Lead Watch DB reads against text-timestamp and backfill noise. Use when comparing events.ts, conversations.updated_at, or lead_signals.updated_at against the last watermark, filtering new inbound replies or stage moves, or a raw e.ts > '<watermark>' comparison risks making old paid-ad backfill rows look newer than they are."
version: 0.1.0
---

# Leads Hot-Lead Watch DB Timestamp Guard

Use this during focused Leads · Hot-Lead Watch when querying Elevate operational data directly via `elevate_db`.

## Trigger

- You need to compare `events.ts`, `conversations.updated_at`, or `lead_signals.updated_at` against the last Hot-Lead Watch history watermark.
- You are filtering for new inbound replies, viewing requests, repeat opens/search activity, or stage moves since the prior run.

## Procedure

1. Read the latest `*-hot-lead-watch.json` history file and use its `ran_at` as the watermark.
2. For `events`, never compare raw `e.ts` lexicographically. It is a text column and can contain both ISO timestamps and RFC-style values like `Wed, 6 May 2026 14:33:01 +0000`.
3. Query with casts:
   - `WHERE e.ts::timestamptz > '<watermark>'::timestamptz`
   - `ORDER BY e.ts::timestamptz DESC`
4. Group or filter event noise before drafting:
   - Ignore `agent_activity` rows.
   - Ignore `crm` / `legacy_backfill` lifecycle sync rows unless paired with a real inbound body, viewing request, repeat open/search signal, or human/operator stage move.
   - Treat non-real-estate Instagram/Composio backfill chatter as not lead movement.
5. Reconcile coverage before alerting or drafting:
   - Check `send_queue` for matching `payload_json->>'contact_id'`, recipient email, phone, or name.
   - If a hot signal/stage move is already covered by a pending approval, do not create a duplicate draft.
   - Still stamp `lead_status(action='set', ...)` with a note naming the pending approval so board-sync sees it handled.
6. Log the run to `history/<UTC>-hot-lead-watch.json` and include whether any signals were covered by existing approval-gated drafts.

## Pitfall

A raw condition like `e.ts > '2026-07-02T23:13:30Z'` can make old paid-ad backfill rows look newer than they are, or distort the current signal set. Always cast `events.ts` to `timestamptz` for watermark logic.
