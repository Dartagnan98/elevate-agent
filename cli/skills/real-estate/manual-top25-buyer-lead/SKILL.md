---
name: manual-top25-buyer-lead
description: Adds a manual buyer lead to the Leads dashboard's Top 25/buyer-search lane. Use when the realtor says to add a new buyer lead to Top 25, hot leads, buyer search, or the Leads dashboard and provides at least a name plus email/phone.
---

# Manual Top 25 Buyer Lead

## When to use

Use this when the realtor asks to add a buyer/prospect to **Top 25**, **Hot Leads**, **buyer-search**, or the **Leads dashboard** from a manual name/email/phone.

Do **not** send outreach from this workflow. This workflow only creates/surfaces the lead.

## Key lesson

Creating an Admin buyer deal/card alone does **not** guarantee the person appears in the Leads dashboard Top 25/buyer-search lane. The dashboard buyer-search list is driven by `contacts.buyer_search_active` and/or a `pcs_buyers` row, with lead-source inbox verification through `db_source_inbox_response`. For manual Top 25 adds, write both the contact flags and the PCS buyer addendum.

## Procedure

1. **Check for an existing contact first**
   - Use `elevate_db(action="query")` against `contacts` by email and display name.
   - Example:
     ```sql
     SELECT id, display_name, primary_email, type, stage, buyer_search_active,
            pipeline_status, heat_label, heat_score
     FROM contacts
     WHERE lower(primary_email)=lower('EMAIL')
        OR lower(display_name)=lower('NAME')
     LIMIT 20
     ```

2. **Create or update the contact**
   - Use `elevate_db(action="call", function="upsert_contact", kwargs={...})`.
   - Required shape:
     ```json
     {
       "display_name": "NAME",
       "primary_email": "EMAIL",
       "primary_phone": "PHONE if provided",
       "type": "buyer",
       "stage": "active",
       "source_key": "manual:lead:EMAIL_OR_NAME",
       "enrichment": {
         "lead_source": "Manual / realtor request",
         "lead_types_json": "[\"buyer\"]",
         "tags_json": "[\"Top 25\",\"buyer lead\"]"
       }
     }
     ```

3. **Set Leads-dashboard flags/status**
   - Use `update_flags` to place them in buyer-search/hot lead sections:
     ```json
     {
       "contact_id": "CONTACT_ID",
       "actor": "executive-assistant:telegram-request",
       "buyerSearchActive": true,
       "heatLabel": "hot",
       "heatScore": 90,
       "heatReason": "Manually added by the realtor to Top 25 buyer leads.",
       "needsFollowUp": true
     }
     ```
   - Use `set_pipeline_status`:
     ```json
     {
       "contact_id": "CONTACT_ID",
       "status": "new_lead",
       "set_by": "operator",
       "actor": "executive-assistant:telegram-request"
     }
     ```

4. **Add a note for traceability**
   - Use `add_contact_note` with a short note: `Added manually by the realtor to Top 25 buyer leads on YYYY-MM-DD. Email verifier: ...`.

5. **Create the Lead Signal + PCS buyer addendum so the buyer-search lane renders them**
   - Create a manual lead signal:
     ```json
     {
       "function": "upsert_lead_signal",
       "kwargs": {
         "source_id": "manual-top25",
         "source_native_id": "EMAIL_OR_PHONE_OR_NAME",
         "name": "NAME",
         "email": "EMAIL if provided",
         "phone": "PHONE if provided",
         "last_activity_at": "ISO timestamp",
         "payload": {
           "manualTop25": true,
           "name": "NAME",
           "email": "EMAIL",
           "phone": "PHONE",
           "source": "Manual / realtor request"
         }
       }
     }
     ```
   - Graduate the signal to the contact:
     ```json
     {
       "function": "graduate_lead_signal",
       "kwargs": {
         "signal_id": "SIGNAL_ID",
         "contact_id": "CONTACT_ID",
         "actor": "executive-assistant:telegram-request"
       }
     }
     ```
   - Add/update the PCS buyer row:
     ```json
     {
       "function": "upsert_pcs_buyer",
       "kwargs": {
         "contact_id": "CONTACT_ID",
         "lead_signal_id": "SIGNAL_ID",
         "analyzer_record": {
           "score": 100,
           "tier": "HOT",
           "days": 0,
           "searches": ["Manual Top 25 buyer lead added by the realtor"],
           "matchingListings": [],
           "lastActivity": "ISO timestamp",
           "profileUrl": null
         }
       }
     }
     ```

6. **Optional Admin card**
   - If the realtor specifically expects it on the Admin buyer board too, create an Admin `deals` card with `side="buyer"`, `current_stage=0`, `primary_contact_id=CONTACT_ID`, and `dispatch_initial_stage=false` so offer-prep automation does not launch for a simple lead add.
   - Title format: `Buyer: NAME`.
   - Do not trigger buyer offer-prep unless the realtor asked for offer prep.

7. **Verify it appears in the actual Leads dashboard data path**
   - Do not rely only on `deals_overview`; that verifies Admin, not Leads.
   - The `elevate_db.call` wrapper currently may reject `db_source_inbox_response` because it injects a positional connection into a function that takes keyword-only args.
   - Use the Elevate venv Python instead:
     ```bash
     /Applications/Elevate.app/Contents/Resources/cli/.venv/bin/python - <<'PY'
     from elevate_cli.data.reads import db_source_inbox_response
     res = db_source_inbox_response(limit=50)
     for i, b in enumerate(res.get('privateSearchBuyers', [])[:20], 1):
         print(i, b.get('name'), b.get('email'), b.get('score'), b.get('tier'), b.get('contactId'))
     print('buyer_search count', res.get('leadSections',{}).get('buyer_search',{}).get('count'))
     PY
     ```
   - Confirm the new person appears in `privateSearchBuyers`, ideally near the top with score `100` / tier `HOT`.

## Pitfalls

- `deals_overview` showing the buyer card is not enough. The realtor may still not see them in Leads/Top 25.
- `contacts.buyer_search_active=true` helps section counts, but the visible buyer-search table is more reliable when a `pcs_buyers` row exists.
- Do not create a generic outreach draft just because a lead was added. Review profile/history first before any future outreach.
- Avoid using raw SQLite. Operational data is embedded Postgres accessed via `elevate_db` or `elevate_cli.data`.
