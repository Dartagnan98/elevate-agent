---
name: lofty-crm-client-contacts
description: Verify or create the seller contact in the configured CRM (Lofty or another tenant CRM) and link it to the deal. Confirms identity, dedupes, and pulls the CRM record onto the listing file during Pre-CMA (stage 0).
metadata:
  elevate:
    tags: [real-estate, crm, contacts]
    runtime:
      result_writer: admin-result-writer
---

# CRM Client Contact Verification

Use during **Pre-CMA (stage 0)** to make sure the seller exists once, cleanly, in the configured CRM and is linked to the deal. Provider-neutral: the CRM may be Lofty or another provider set during onboarding. Treat the CRM name, login URL, and field labels as tenant configuration.

A verified, deduped CRM contact is what lets every later stage (marketing, seller updates, nurture) reach the right person.

## Flow

1. **Match first.** Search the configured CRM by email, then phone, then name + address. The goal is to find an existing record before creating a new one — duplicates are the main failure here.
2. **Verify or create.**
   - If a confident match exists, confirm the core fields (name, email, phone, source) and reconcile any conflicts.
   - If no match exists, create the contact from the deal's intake facts.
   - If two plausible matches exist, do **not** guess — write `waiting_human` naming both records.
3. **Link.** Attach the CRM contact id / URL to the deal so other skills resolve the same person.
4. **Tag/source** per the tenant's CRM convention if one is configured. Do not invent tags.
5. **Close through `admin-result-writer`** with the checklist update below.

## Rules

- Profile-driven only. Never hardcode a CRM login, realtor identity, or contact. Pull from the tenant profile / deal; if something is missing, ask in the chat.
- Do not create a duplicate contact. Prefer matching an existing record. A possible-but-unconfirmed match is `waiting_human`, not a new record.
- MFA / login / blocked portal is `waiting_human` with the exact account and URL needed, never a silent failure.
- Do not mass-edit or merge CRM records beyond the one seller on this deal.
- This skill reads and writes the CRM contact only. It does not send the client anything.
- Same finalization in any context: in a live session converse inline; on a stage trigger the conversation goes to the Admin agent lane. Always close through `admin-result-writer` so the kanban card reflects the outcome (see its "Where this writes").

## Checklist Cell This Clears

- Checklist: `lofty_contact_verified` (set only once the contact is confirmed verified or freshly created and linked to the deal).

## Output Contract

```json
{
  "workflow": "crm-contact-sync",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "provider": "",
  "contact_id": "",
  "contact_url": "",
  "action": "matched|created|reconciled",
  "checklist_updates": [],
  "duplicates_flagged": [],
  "risks": []
}
```
