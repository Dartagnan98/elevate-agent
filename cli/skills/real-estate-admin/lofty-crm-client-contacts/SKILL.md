---
name: lofty-crm-client-contacts
description: "Verify or create the seller's CRM contact and link it to the deal. Use when running Pre-CMA (stage 0), or when the realtor says 'add this seller to the CRM', 'is this seller in Lofty', or 'link the contact to this listing'. Provider-neutral (Lofty or the tenant CRM); matches by email, then phone, then name+address before creating, and two plausible matches become waiting_human, never a duplicate. Reads/writes the contact only — never messages the client."
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

## API Notes (Lofty/Chime)

- The `q=` search is unreliable (returns recent/unrelated leads) — treat hits as candidates only. Confirm by normalized email or last-10-digit phone match, and prefer a known lead ID when one is stored (`source_key` `crm:lofty-lead:<id>` → `GET /v1.0/leads/<id>`).
- Notes endpoint is `POST /v1.0/notes` with `{leadId, content}` — `POST /v1.0/leads/{id}/notes` 404s.

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
