---
name: leads-new-lead-response-quiet-checks
description: Finds genuinely new leads since the last focused run and drafts first responses. Use when running the Leads new-lead-response heartbeat, checking for quiet-run candidate discovery, or avoiding duplicate first-touch drafts amid board-sync/status noise.
version: 0.1.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [real-estate, leads, heartbeat, new-lead-response, outreach]
---

# Leads New-Lead Response Quiet Checks

Use this when running the focused `Leads · New-Lead Response` heartbeat and the goal is to find only genuinely new leads since the last focused run, draft first responses if needed, and avoid duplicate drafts.

## Pattern
1. Read the focused heartbeat context first:
   - `agent_bus(action='get_surface_config', surface='leads')`
   - workspace `learnings.md`
   - latest `*-new-lead-response.json` history file for the watermark.
2. Treat the last focused New-Lead Response `ran_at` as the primary watermark, not the latest generic Leads heartbeat.
3. Candidate discovery should start with creation/activity signals, not broad update stamps:
   - `contacts.created_at >= watermark`
   - `conversations.created_at >= watermark`
   - `lead_signals.created_at`, `updated_at`, or `last_activity_at >= watermark`
4. Avoid starting with a broad `contacts.updated_at OR conversations.updated_at` sweep. Board-sync, lead_status stamps, and other focused heartbeats can update many old leads and flood the result with already-handled contacts.
5. For each candidate, reconcile before drafting:
   - contact identity: name, email, phone, source_key/Gmail id when present
   - conversation/thread context and inbound/outbound counts
   - existing `send_queue` rows by `contact_id`, `thread_id`, recipient email/phone/name, and status `pending_approval` / active
   - existing draft attempts / working-state review cards if available
   - opt-out flags: `cannot_email`, `cannot_text`, `unsubscribed`, hidden contacts
6. Draft only if the lead is new, real-estate relevant, has no existing first-touch/approval coverage, and no opt-out conflict. Drafts stay approval-gated, never sent.
7. If no candidates remain after reconciliation, log the quiet check to `history/<UTC>-new-lead-response.json` and return `[SILENT]` in heartbeat report mode.

## When to broaden the search
Use broader `updated_at` checks only as a fallback when an explicit task, Admin/Gmail verifier, or source signal implies an import may have updated an existing paid-ad/contact row without creating a fresh contact/conversation.

## Pitfalls
- Making It Rain paid-ad imports can create repeated sync/status updates without a new lead. Do not treat those updates as new first-response opportunities.
- Lofty/CRM legacy backfill can flood `contacts.updated_at`, `last_activity_at`, and `events` after the focused watermark while the event body still represents old imported lead history. Before treating those rows as fresh, require `contacts.created_at`, a newly created/updated conversation, a fresh `lead_signals` row, or an ISO-timestamped real inbound event. Ignore `agent_activity` and broad `crm`/`legacy_backfill` lifecycle rows as first-touch candidates unless an explicit task/Admin verifier points to a specific lead.
- Follow-up Sweep cadence drafts in `send_queue` after the watermark are not New-Lead Response work. Count them as existing coverage or non-focus activity, not new first-touch output.
- If the focused heartbeat writes `agent_bus(action='heartbeat')`, verify how the tool records `surface` and `agent`; some contexts may persist the owning agent as the surface even when the metadata says `leads`.
- Do not treat newly created CRM conversation rows with `inbound_count=0`, `outbound_count=0`, placeholder names (`No Name`, `Paid Ad`, `Paid Ad Lead`), and only legacy/importer evidence as first-touch candidates by themselves. Reconcile against the contact-created set and event payloads first; if they are reviewed and are clearly unreachable placeholders/no-signal records, stamp them with `lead_status(action='set', status='dead', heat='cold', notes='<no-signal evidence>')` so board-sync does not keep surfacing them. If they have a real phone/email but are older paid-ad imports outside the focused watermark, do not draft in New-Lead Response; either leave them for the paid-ad/follow-up lane with a `follow_up`/warm status only when the next action is clear, or ask/escalate rather than guessing.
- `lead_status(action='heat')` expects `label='warm'|'hot'|'normal'|'watch'`, not `heat=...`. In this runtime, `lead_status(action='follow_up')` may not visibly populate `nextFollowUpAt`; verify after use and rely on working-state `pending_external` draft cards for the review artifact.


## Draft individuation (no mail-merge)

Before writing ANY first-touch or follow-up draft:

1. Read the lead's REAL context first. Run the thread reader:
   `python3 ~/elevate-tools/scripts/outreach/thread-context.py --phone "<phone>" --name "<full name>"`
   (phone is authoritative; the name fallback only matches a FULL name, never a bare first name). Ground the message in whatever is actually known -- the ad/listing they came through, city, saved search, or a real prior thread.

2. NEVER write the same paragraph to two people. If a lead has no captured specifics AND no readable history, keep it SHORT and vary the opener, wording, and the ONE question you ask. Do NOT paste a generic "I can absolutely help with the local buyer listings" block. If two drafts in a batch read the same, at least one is ungrounded -- rewrite it or hold it. Identical copy across different people is the #1 tell that the message is not real.

3. Never claim familiarity ("good to hear from you again", references to a past conversation) unless the reader returned a real thread for THIS person. A fuzzy name guess is not proof.


## Channel selection (text-first)

Default every outreach draft to TEXT (sms/iMessage) whenever the contact has a phone. Email is only a fallback.

1. Before setting the channel, resolve the phone: check the lead's `contacts.primary_phone` (Postgres) AND the source record's phone/phones. If ANY valid phone exists, set `channel='sms'` and populate `recipient.phone` with it. Do NOT leave recipient.phone empty when the contact row has a primary_phone -- that is the bug that silently downgrades real text leads to email.
2. Use `channel='email'` ONLY when there is genuinely no phone on the contact or source, OR after a text to that number has bounced/failed.
3. Paid-ad (Making It Rain) leads frequently DO have a phone on the contact even when the lead-form email looks junk -- always resolve primary_phone before defaulting to email.
