---
name: pre-cma-operational-card
description: "Create a Pre-CMA pipeline card in Postgres from seller and property details. Use when the realtor gives seller names, contact info, an address, and property notes to open a new Pre-CMA row."
metadata:
  elevate:
    tags: [real-estate, pre-cma, admin-dashboard, postgres, seller-package]
---

# Pre-CMA Operational Card

Use when the realtor asks to add/open someone in the **Pre-CMA** section/pipeline and provides enough seller/property context to create the dashboard card. This is internal setup, not a client send.

## Inputs to capture

- Seller/client names, email, phone.
- Property address.
- Lead source if known. If source is uncertain, record the uncertainty instead of blocking, e.g. `email list; possible PCC lead to verify`.
- Motivation/timeline and property notes.
- Known property facts, e.g. beds, baths, lot size, year built, garages/carports.

## Create the operational card

Operational data lives in embedded Postgres, not SQLite. For direct Python access from the packaged desktop app, use the bundled runtime Python and CLI path:

```bash
CLI=/Users/admin/Library/Caches/com.elevationrealestate.elevate.ShipIt/update.Fx5lUgq/Elevate.app/Contents/Resources/cli
PY=$CLI/../runtime/python/bin/python3.12
PYTHONPATH=$CLI $PY /tmp/create_precma_card.py
```

Write the script with `write_file` first, then run it. Avoid putting raw client names with `&` directly in shell heredocs/commands because the terminal guard may treat it as backgrounding.

Skeleton:

```python
from elevate_cli.data import connect, upsert_contact, add_contact_note, create_deal, add_deal_contact, record_deal_activity
from elevate_cli.data._util import now_iso

with connect() as conn:
    # 1) Deduplicate by active deal title/address first.
    existing = conn.execute(
        "SELECT id,title,listing_address FROM deals WHERE status='active' AND (lower(title) LIKE ? OR lower(listing_address) LIKE ?) LIMIT 10",
        ('%surname%', '%address fragment%'),
    ).fetchall()
    if existing:
        print('EXISTS', [dict(r) for r in existing])
        raise SystemExit(0)

    # 2) Contact type must be 'listing', not 'seller'. The contacts_type_check allows:
    #    unclassified, buyer, listing, other.
    contact = upsert_contact(
        conn,
        display_name='Client Names',
        primary_email='email@example.com',
        primary_phone='250 000 0000',
        type='listing',
        stage='client',
        source_key='pre-cma:email@example.com',
    )
    add_contact_note(conn, contact['id'], 'Pre-CMA intake notes...', actor='assistant')

    # 3) Extra workflow/checklist facts can be stored in fields and appear via extraToggles.
    deal = create_deal(
        conn,
        title='Client Names - Property Address',
        side='listing',
        actor='assistant',
        province='BC',
        board='AOIR',
        market='Kamloops',
        current_stage=0,
        primary_contact_id=contact['id'],
        listing_address='Property Address, Kamloops, BC',
        source_key='pre-cma-manual-intake:property-address',
        source_label='Manual Pre-CMA intake from the realtor',
        source_synced_at=now_iso(),
        fields={
            'workflow_client_1_name': 'First Seller',
            'workflow_client_1_email': 'email@example.com',
            'workflow_client_1_phone': '250 000 0000',
            'workflow_client_2_name': 'Second Seller',
            'workflow_lead_source': 'Email list; source to verify',
            'workflow_cma_date_requested': 'No timeline / not requested',
            'workflow_property_address': 'Property Address, Kamloops, BC',
            'workflow_seller_goal': 'Downsize / move goal',
            'workflow_timeline': 'No timeline to move',
            'workflow_property_notes': 'Factual property and seller notes...',
            'pre_cma_dashboard_setup': True,
            'pre_cma_handoff': True,
            'lofty_contact_verified': False,
            'yearBuilt': 1993,
            'lotSizeSqft': 51401,
        },
        dispatch_initial_stage=True,
    )
    add_deal_contact(conn, deal['id'], role='seller', contact_id=contact['id'], notes='Pre-CMA seller lead.', actor='assistant')
    record_deal_activity(conn, deal['id'], actor='assistant', summary='Created Pre-CMA property card and saved handoff notes.', tools=['elevate_cli.data'], confidence=0.95)
    conn.commit()
    print('CREATED', deal['id'], contact['id'])
```

## Verify

After creation, read back the deal:

```python
from elevate_cli.data import connect, get_deal, list_deal_contacts, list_deal_events
with connect() as conn:
    deal = get_deal(conn, 'DEAL_ID')
    print({k: deal.get(k) for k in ['id','title','side','currentStage','status','listingAddress','yearBuilt','lotSizeSqft','primaryContactId']})
    print(deal.get('extraToggles', {}))
    print('contacts', len(list_deal_contacts(conn, 'DEAL_ID')))
    print('events', [(e['kind'], e.get('payload',{}).get('summary')) for e in list_deal_events(conn, 'DEAL_ID', limit=10)])
```

Acceptance criteria:
- Stage is `0` / Pre-CMA.
- Side is `listing`.
- `pre_cma_dashboard_setup` and `pre_cma_handoff` are true when the provided intake supports them.
- `lofty_contact_verified` stays false unless Lofty was actually verified/created.
- Seller/property notes are stored on both contact note and deal handoff fields.

## Seller package Mailjet note

When testing/sending the Pre-CMA seller package, verify the current API-visible template. Current route: `8055687` (`Pre-CMA Seller Package - Forever Real Estate`); older remembered template `14342651` returned 404 with the current Mailjet credentials.

Mailjet transactional template test sends do not render `[[data:field:"default"]]` placeholders. For proofs/client sends, fetch template content, manually replace placeholders such as `[[data:seller_names:"there"]]`, verify no `[[data:` or `[[UNSUB` placeholders remain, then send via `/v3.1/send`.

## Pitfalls

- Do not use sqlite3 or hunt for `.db` files. Operational contacts/deals are Postgres behind the Elevate data layer.
- Prefer gated `elevate_db.call` public helpers (`upsert_contact`, `create_deal`, `add_deal_contact`, `add_contact_note`, `record_deal_activity`) when they are available; fall back to bundled app Python only when the gated helper path is insufficient.
- Contact `type='seller'` violates `contacts_type_check`; use `type='listing'` for seller/listing contacts.
- If the provided seller email already exists on a different or test-looking Lofty-backed contact (example: a brand test address on display name `Lofty Test` with Lofty IDs), do not treat that as a clean Lofty verification and do not mark `lofty_contact_verified=true`. Create/link the human-provided seller contact to the Pre-CMA card, record the exact-email conflict in activity/audit, and leave Lofty verification as the Stage 0 blocker until reconciled or verified through the CRM workflow.
- `contact-audit.py` can return extra brokerage/realtor emails from Gmail alongside the queried seller email. Treat the user-provided seller email as the verifier when explicitly supplied, and record unrelated audit emails as context only, not replacement seller identity.
- Record uncertain lead source as a note/field instead of blocking the Pre-CMA card.
- Human approval is still needed before client-facing sends unless the realtor has explicitly approved that send workflow.
