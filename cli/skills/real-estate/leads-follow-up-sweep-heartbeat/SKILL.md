---
name: leads-follow-up-sweep-heartbeat
version: 0.1.0
description: "Run the Leads follow-up-cadence heartbeat and stage approval-only reminder drafts. Use when checking cadence-due contacts, reconciling pending drafts, resolving 'No Name'/'Paid Ad' placeholder leads, or stamping lead_status during a Leads heartbeat."
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [leads, heartbeat, follow-up, outreach, real-estate]
---

# Leads · Follow-up Sweep Heartbeat

Use when running a focused Leads surface heartbeat whose scope is follow-up cadence only. Drafts only. Never send externally.

## Steps

1. **Load heartbeat context**
   - Read surface config with `agent_bus(action='get_surface_config', surface='leads')`.
   - Read the workspace `learnings.md` and recent `history/` count.
   - Pull pending `agent_bus(action='list_tasks', status='pending')` and filter for Leads/Outreach follow-up, cadence, next-touch, or overdue-follow-up tasks.

2. **Reconcile before drafting**
   - Query due contacts from the operational store: `contacts.needs_follow_up=1` with a dated `next_follow_up_at <= now`.
   - Do not draft from `needs_follow_up=1` alone when `next_follow_up_at` is blank.
   - For each due contact, check:
     - active/pending `send_queue` rows by `contact_id`, `thread_id`, recipient email, phone, or name,
     - active contact working-state drafts if available,
     - existing task coverage.
   - If pending coverage exists, log it as covered/review-blocked and do not duplicate.

3. **Handle placeholder paid-ad identities**
   - If a paid-ad/Lofty contact is named `No Name`, `Paid Ad`, or `Paid Ad Lead`, try to resolve a safe first name from Lofty sync/event summaries, e.g. `Rick from Lofty is in New Leads via fb`.
   - Use the resolved first name in the greeting and recipient context only when supported by source evidence.
   - Do not invent a last name. Add a context note that the placeholder was resolved from sync/event evidence and the last name remains unknown.

4. **Stage approval-only cadence drafts**
   - Use the user's tone: `Hi <Name> :)`, short, warm, one simple question, space before `?`, no em dashes.
   - Run the thread reader before drafting. If it returns no readable thread, do not claim prior familiarity; fall back only to verified contact ownerNotes, CRM fields, conversation metadata, and source evidence.
   - For seller-side direct-text contacts that appear `closed` / `closed_seller`, do not auto-skip when ownerNotes or CRM context proves an active seller appointment, property address, or a next step from the realtor. Draft a short text grounded in that property/next step; otherwise classify as non-lead hygiene.
   - For sparse paid-ad context, keep the draft neutral and do not say `again` unless the thread proves a prior substantive exchange.
   - Insert `send_queue` with `status='pending_approval'`, `approval_required=true`, and `send_only_after_human_approval=true`.
   - Record a draft attempt if the workflow normally does so.
   - Move the contact's next touch forward so the next sweep does not redraft while approval is pending.

5. **Stamp lead status for every reviewed contact**
   - Use `lead_status(action='set', contact_id=..., status='follow_up'|'new_lead'|'ghosting'|'dead', heat='warm'|'hot'|'cold', notes=...)`.
   - Stamp placeholder contacts too. If no usable contact info or no next-touch context exists, mark `new_lead` with cold heat and explain the limitation.
   - For a cadence draft staged for review, mark `follow_up` with warm heat and include the queue id / next-touch date in notes.

6. **Close routed tasks and verify**
   - Complete the routed agent task with outputs listing queue ids, contact ids, next follow-up date, and that no external send occurred.
   - Re-query due contacts and confirm any remaining due rows are covered by pending approval/working-state drafts.
   - Write `history/<UTC timestamp>-follow-up-sweep.json` with checked/did/found/summary.

7. **Autoresearch cycle**
   - If due, evaluate the active experiment using the configured metric.
   - Keep/discard based on baseline and direction.
   - Start the next playbook-only experiment if applicable, stage only relevant files, commit, and verify `git status --short`.

## Pitfalls

- Pending approval drafts may omit `contact_id`; match by recipient email/phone/name before deciding a dated-due contact needs a new cadence draft.
- In some cron runtimes `agent_bus(action='list_active_working_state')` is unavailable; use `elevate_cli.data.connect()` + `list_active_working_state(entity_kinds=('contact',))` as the fallback before drafting.
- Repeated `crm_lead_synced` rows are audit noise, not fresh replies.
- `lead_status` needs `action='set'`; a default/empty call errors.
- `needs_review` is not a valid working-state status; use `pending_external` for realtor-review-only drafts.
- A contact can be `closed_seller` in the Leads lane but still have a real post-appointment follow-up due. Check ownerNotes/property/appointment evidence before treating closed status as a skip.


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
