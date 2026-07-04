---
name: manual-top25-listing-lead
description: Adds a verified seller/listing prospect to the Leads Top 25/listing-active lane. Use when the realtor says to add a seller, listing-side prospect, or unsaved text/iMessage lead to Top 25 and provides or references enough history to verify name plus phone/email and property address.
---

# Manual Top 25 Listing Lead

## When to use

Use this when the realtor asks to add a manually found seller/listing prospect to **Top 25**, **hot leads**, **listing-side prospects**, or the **Leads dashboard**, especially from a recent text/iMessage/RCS/SMS thread.

Do **not** send outreach from this workflow. This workflow only verifies, creates/updates records, links source context, and makes the prospect visible on the Leads dashboard.

## Required safety bar

Before marking the person as Top 25/listing-active, verify:

1. There is source evidence that this person is a seller/listing prospect, not a buyer or unrelated contact.
2. You have at least one contact verifier: phone or email.
3. You have the property address or enough property context to distinguish the seller lead.
4. They are not already a signed/active/accepted-offer/closed Admin deal or current listing client.

If the source evidence is ambiguous, stop and ask the realtor instead of guessing.

## iMessage / Apple Messages extraction pattern

1. Load the Apple iMessage skill first if you are using `imsg`.
2. Search recent chats by time and name hints. For unsaved contacts, `imsg search --query NAME` may miss them because the name might only appear in contact labels or attributed message bodies.
3. Use `imsg chats --limit 100 --json` to find recent unsaved one-to-one chats, then inspect likely chats:

```bash
imsg history --chat-id CHAT_ID --limit 40 --json
```

4. For exact phone/contact details, query Apple Messages `chat.db` read-only:

```python
import os, sqlite3
con = sqlite3.connect(os.path.expanduser('~/Library/Messages/chat.db'))
con.row_factory = sqlite3.Row
row = con.execute('''
select h.id as phone, h.service, c.guid, c.chat_identifier
from chat c
join chat_handle_join chj on chj.chat_id=c.ROWID
join handle h on h.ROWID=chj.handle_id
where c.ROWID=?
limit 1
''', (CHAT_ID,)).fetchone()
```

5. Pitfall: raw `message.text` in `chat.db` may be NULL for current Messages because the text is inside attributed body. Use `imsg history --json` for decoded message text, and use `chat.db` only for exact handle/phone/service metadata.

## Safety checks in Elevate DB

Use the Elevate venv and `elevate_cli.data.connect()` or `elevate_db`; do **not** use operational SQLite.

Check existing contacts by exact email, normalized phone, name, and notes/address:

```sql
SELECT *
FROM contacts
WHERE lower(coalesce(primary_email,'')) = lower(?)
   OR regexp_replace(coalesce(primary_phone,''), '[^0-9]', '', 'g') = ANY(?)
   OR lower(coalesce(owner_notes,'')) LIKE lower(?)
   OR lower(coalesce(display_name,'')) IN ('nickname variant 1','nickname variant 2')
ORDER BY updated_at DESC NULLS LAST
LIMIT 20
```

Check Admin deals by property address, email, and normalized phone through both `deals.primary_contact_id` and `deal_contacts`:

```sql
SELECT d.id, d.title, d.side, d.current_stage, d.status, d.listing_address,
       d.primary_contact_id, c.display_name, c.primary_email, c.primary_phone
FROM deals d
LEFT JOIN contacts c ON c.id = d.primary_contact_id
LEFT JOIN deal_contacts dc ON dc.deal_id = d.id
LEFT JOIN contacts c2 ON c2.id = dc.contact_id
WHERE lower(coalesce(d.title,'')) LIKE lower(?)
   OR lower(coalesce(d.listing_address,'')) LIKE lower(?)
   OR lower(coalesce(c.primary_email,'')) = lower(?)
   OR lower(coalesce(c2.primary_email,'')) = lower(?)
   OR regexp_replace(coalesce(c.primary_phone,''), '[^0-9]', '', 'g') = ANY(?)
   OR regexp_replace(coalesce(c2.primary_phone,''), '[^0-9]', '', 'g') = ANY(?)
LIMIT 20
```

Block the Top 25 add if a match is already active/signed/accepted/closed or otherwise not a prospect.

## Create/update the contact

Use `upsert_contact` with a stable source key like `apple-messages:chat:CHAT_ID` when the lead came from Messages.

Recommended shape:

```python
from elevate_cli.data import connect, upsert_contact
import json

with connect() as conn:
    contact = upsert_contact(
        conn,
        contact_id=existing_contact_id_or_none,
        display_name='NAME',
        primary_email='EMAIL',
        primary_phone='PHONE',
        type='listing',
        stage='active',
        source_key='apple-messages:chat:CHAT_ID',
        enrichment={
            'lead_source': 'Apple Messages / direct text to the realtor',
            'tags_json': json.dumps([
                'Top 25', 'listing prospect', 'seller lead',
                'Apple Messages', 'direct seller inquiry'
            ]),
            'lead_types_json': json.dumps(['seller', 'listing']),
            'selling_time_frame': 'Now / exploring listing after realtor call',
            'with_listing_agent': 'No / looking for a realtor to work with',
            'opportunity': 'Seller CMA / listing appointment',
            'last_activity_at': latest_activity_iso,
        },
    )
```

## Set dashboard lane/status

Set listing-side Top 25 visibility through contact flags, not Admin deals:

```python
from elevate_cli.data import update_flags, set_pipeline_status

update_flags(
    conn,
    contact_id,
    actor='outreach:manual-top25-listing-lead',
    heatLabel='hot',
    heatScore=90,  # adjust based on source strength
    heatReason='Direct seller inquiry with property address and request for listing/CMA help.',
    needsFollowUp=True,
    nextFollowUpAt='ISO timestamp if known',
    buyerSearchActive=False,
    listingActive=True,
)
set_pipeline_status(
    conn,
    contact_id,
    status='new_lead',
    actor='outreach:manual-top25-listing-lead',
    set_by='operator',
)
```

For a strong direct seller text like “looking to sell my home” plus address and appointment, score around 90-95/hot.

## Add traceability

Append a contact note with:

- Source thread/chat ID and service.
- The extracted phone/email/address.
- Short quoted evidence from the thread.
- The safety check result.
- Any appointment/follow-up details.

Use `add_contact_note`; notes are append-only and update `contacts.owner_notes` plus a `kind='note'` lifecycle event.

### If the realtor asks whether the card has a visible/usable note section

The Leads profile drawer has a visible notes section (`▤ Notes`) in `profile-drawer.tsx`, but the drawer's `context.notes` array only populates from events whose payload has `legacyType == 'crm_note'` (or legacy `lead-events.jsonl` event_type `lofty_note`). A plain `add_contact_note` is stored and visible in the contact summary / activity trail, but it may not increment the drawer Notes count.

For a note that must be visible in the drawer's Notes section, also write a lifecycle note event with CRM-note shape:

```python
from elevate_cli.data import record_lifecycle

record_lifecycle(
    conn,
    contact_id=contact_id,
    kind='note',
    actor='agent:outreach',
    payload={
        'legacyType': 'crm_note',
        'title': 'Meeting note',
        'summary': 'The team assistant is meeting with the lead at noon on July 2.',
        'author': 'Inside Sales Agent',
    },
)
```

Then verify both storage and UI-read-path shape:

```sql
SELECT owner_notes FROM contacts WHERE id=?;
SELECT id, kind, payload_json, ts
FROM events
WHERE contact_id=? AND kind='note'
ORDER BY ts DESC LIMIT 5;
```

The drawer itself displays `▤ Notes <count>` and maps each note row using `n.title` and `n.summary` as the tooltip, so the section is visible/usable once a `legacyType='crm_note'` event exists.

## Create lead signal and property context

Create a manual `lead_signals` row and graduate it to the contact:

```python
signal = upsert_lead_signal(
    conn,
    source_id='apple-messages-manual',
    source_native_id=f'chat-{CHAT_ID}',
    name=name,
    email=email,
    phone=phone,
    last_activity_at=latest_activity_iso,
    payload={
        'manualTop25': True,
        'side': 'listing',
        'name': name,
        'email': email,
        'phone': phone,
        'propertyAddress': address,
        'source': 'Apple Messages / direct text to the realtor',
        'chatId': CHAT_ID,
        'evidenceSummary': heat_reason,
    },
)
graduate_lead_signal(conn, signal['id'], contact_id=contact_id, actor=actor)
```

Add/update `lead_properties` with `label_type='seller_property'`, `label='Home to sell'`, `listing_status='prospect'`, and a stable `source_record_id` like `apple-messages:chat:CHAT_ID:property`.

## Link the conversation for dashboard context

If there is no synced `conversations` row yet, create or update one:

- `source_id='apple-messages'`
- `thread_key='apple-chat:CHAT_ID'`
- `contact_id=contact_id`
- `status='open'`
- `heat_score` / `heat_label` matching the contact

Important pitfall: `conversations.channel` only accepts:

```text
email, sms, imessage, messenger, instagram, whatsapp, telegram, voice, crm
```

If Apple Messages service is `RCS`, map it to `sms`. Do not write raw `rcs` or the transaction will fail and roll back.

## Verify

Do not rely only on the contact row. Verify the Leads dashboard read path:

```python
from elevate_cli.data.reads import db_source_inbox_response
res = db_source_inbox_response(limit=500)
assert contact_id in res['leadSections']['listing_active']['contactIds']
assert contact_id in res['leadSections']['hot']['contactIds']
```

Also verify the property and signal rows:

```sql
SELECT street_address, city, state, label, label_type, listing_status
FROM lead_properties
WHERE contact_id=?;

SELECT id, source_id, source_native_id, name, email, phone, graduated_to_contact_id
FROM lead_signals
WHERE graduated_to_contact_id=?;
```

## Report back

Summarize:

- Extracted name, phone last 4, email, property address.
- Source/evidence from Messages.
- Safety check result.
- Contact ID, lead signal ID, conversation ID.
- Dashboard verification: listing_active/hot/follow_up.
- Confirm no outreach was sent.
