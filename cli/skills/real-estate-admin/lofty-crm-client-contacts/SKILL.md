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
- When using `elevate_db.call(function='upsert_contact', ...)`, pass all contact arguments inside `kwargs` (for example `kwargs={"contact_id":"...","display_name":"...","primary_email":"...","enrichment":{...}}`). Do **not** put function parameters at the top level of the `elevate_db` tool call; the dispatcher ignores them and can create a blank contact. If a blank/accidental contact is created, immediately park it with a clear reason and continue from the verified existing contact.
- Same finalization in any context: in a live session converse inline; on a stage trigger the conversation goes to the Admin agent lane. Always close through `admin-result-writer` so the kanban card reflects the outcome (see its "Where this writes").

## API Notes (Lofty/Chime)

- The `q=` search is unreliable (returns recent/unrelated leads) — treat hits as candidates only. Confirm by normalized email or last-10-digit phone match, and prefer a known lead ID when one is stored (`source_key` `crm:lofty-lead:<id>` → `GET /v1.0/leads/<id>`).
- For Lofty, keep `leadId` and `leadUserId` distinct. `leadId` is the CRM lead/contact identifier used for lookup URLs, notes, and result summaries. `leadUserId` is the value that belongs in Elevate contact enrichment column `contacts.lofty_lead_user_id`. If you first update enrichment with `leadId`, immediately read `GET /v1.0/leads/<leadId>` and correct `lofty_lead_user_id` to the returned `leadUserId` before claiming the contact is linked.
- Notes endpoint is `POST /v1.0/notes` with `{leadId, content}` — `POST /v1.0/leads/{id}/notes` 404s.

## Operational-store fallback learned from cron runs

When this runs from cron/stage-entry, the result callback URL may be unreachable from the session (for example `127.0.0.1:9119` connection refused). Do not leave the run open.

1. First verify/create/match the CRM contact using the configured CRM helpers.
2. Link the CRM result back to the existing Elevate contact:
   - add a verified `lofty_id` identity for the Lofty `leadId`;
   - add/confirm verified `email` and `phone` identities when present;
   - update the contact enrichment fields (`lofty_lead_user_id`, `crm_stage`, `lead_source`, `assigned_agent`, `lead_score`, `tags_json`, consent flags) from the Lofty response.
3. If the waiting card already has `human_prompt_json.providedAnswers`, first read back `deals.extra_toggles_json`, `contacts`, `identities`, and `deal_contacts` by the provided email/name before doing any new CRM/browser work. A sibling/self-heal run may already have created/linked the contact. If exact email + verified `lofty_id` + seller `deal_contacts` row exist, treat the contact as verified and only close the current run with the checklist update and audit.
4. Do not try to write CRM/linkage fields with `admin_deal.set_fields` unless the field is known supported; current Admin detail fields reject raw CRM columns such as `primary_contact_id`, `crm_lead_id`, `crm_provider`, and `lofty_contact_id`. Use the actual contact/link evidence (`contacts`, `identities`, `deal_contacts`) and the result writer/checklist closure instead.
5. Write a small local markdown audit artifact summarizing the match evidence. `record_run_result` attaches artifacts through `add_deal_attachment`, so each artifact must include a real local `filePath`; an external-only artifact will fail with `file_path is required`.
6. If the HTTP callback fails, close the run via `admin_deal.complete_run` when available, or `elevate_db.call(function='record_run_result', ...)` with the same stable idempotency key, checklist update `lofty_contact_verified=true`, the local audit artifact, and no human prompt when the match is confident.
7. Read back both the deal gate and the action run before reporting success. Success means the run is `succeeded`, the result/checklist update is stored, a verified audit artifact is attached to the current `source_run_id`, and the gate no longer lists `lofty_contact_verified` as missing. The UI may keep `canAdvance=false` briefly while sibling re-run tasks are still running; do not treat that alone as contact-verification failure if missing fields/docs/checklist are empty.
8. If the callback returns unreachable but a concurrent worker has already recorded the run, `admin_deal.complete_run` may return `action run result has already been recorded`. Treat that as a retry/readback condition, not a failure: query/read back the run, verify its status, idempotency key, checklist update, and artifact. If the recorded result is correct, do not overwrite or duplicate it; just report the verified card state.
   - `admin_deal.set_fields` may reject structural columns such as `primary_contact_id` or `lofty_contact_id`; do not keep retrying unsupported fields. Prefer verified `deal_contacts` seller linkage plus existing contact identities/enrichment as the CRM linkage evidence, then close the run through `complete_run` / `record_run_result`.
   - After `lofty_contact_verified` clears, `admin_deal show` may still report `canAdvance=false` for a moment because sibling “re-run after info resolved” jobs were spawned. If missing checklist/fields/docs are empty, treat the CRM-contact run as complete and report the CRM outcome only; let sibling runs handle their own completion rather than forcing advancement from this worker.

## Archived duplicate Pre-CMA card

If the current run is on an archived duplicate Pre-CMA deal/card but the same seller/address has an active deal that already carries the verified CRM evidence, do **not** re-run Lofty or try to complete checklist cells on the archived card.

**Do this archived-duplicate check before any write.** A primary contact with verified Lofty evidence on the archived card is not by itself permission to copy Pre-CMA fields, add `deal_contacts`, attach artifacts, or set `lofty_contact_verified` on the archived deal. First search for same-address / same-primary-contact active deals; if one exists, treat the archived run as reconciliation-only and leave the archived card gate untouched.

1. Read back the current run, the archived deal row, matching active deals by normalized address/email/name, the active deal gate, `contacts`, `identities`, and `deal_contacts`.
2. Treat the active deal as already verified only when it has strong evidence: exact seller email or contact id, verified `lofty_id` identity, CRM enrichment such as `source_key=crm:lofty-lead:<leadId>` / `lofty_lead_user_id`, and a seller `deal_contacts` row on the active deal.
3. Close the archived duplicate run as `skipped` with a stable idempotency key like `lofty-crm-client-contacts:<archived_deal_id>:<run_id>:archived-duplicate-active-deal-verified`. Use no checklist updates, no human prompt, and no artifact unless you create a real local audit file and verify it was attached.
4. If the callback port refuses, use `admin_deal.complete_run` and read back the run plus both deal gates. The archived deal may still show missing Pre-CMA fields/checklist; that is expected and should not be forced because the live work is on the active deal.
5. If there is no new user-facing blocker beyond the active deal already being in its next stage, final cron delivery should be `[SILENT]`.

## SEARCH BEFORE YOU ASK (mandatory, Skyleigh 2026-08-21)

A name with no email or phone is **not** a reason to go straight to `waiting_human`. Work this ladder in order and stop at the first confident hit. Only ask her when all four come up empty or ambiguous.

1. **Elevation contacts (our own store, and the source of truth).** Exact email, then last-10-digit phone, then exact `display_name`. This is done for you in code at deal-create time (`match_contact_for_intake`), but re-check it here in case the card was made another way. A UNIQUE name match is good enough; two people with the same name is a miss, never a guess.
2. **Her macOS Contacts.** Also wired into `match_contact_for_intake` (`apple_contacts.cached_index().lookup_by_name`). Unique exact-name match only. Read-only.
3. **Her Gmail.** `gws gmail users messages list` for the person's name; pull the counterparty address off a real thread. Only accept an address that appears in a message clearly involving that person. Never accept a bulk-sender or no-reply address.
4. **The CRM (Lofty).** Confirm by normalized email or last-10-digit phone, or a stored lead id. Remember `?q=` is IGNORED by Lofty and returns unrelated recent leads — page the full list at `limit=100` and filter locally. **A name-only CRM search is NOT a safe match** and must not be used to link or create a record.

**When you find contact details, WRITE THEM TO THE DEAL** — `workflow_client_1_email`, `workflow_client_1_phone`, plus `prospectEmails` / `prospectPhones` (listing) or `buyerEmails` / `buyerPhones` (buyer). Writing `workflow_client_1_email` / `prospectEmails` fires the registered `toggle_change` resume rule, which finishes the Pre-CMA seller-package send. That is how a stalled card completes itself.

**Report what is missing as a problem, not as silence.** If the ladder fails, the run parks `waiting_human` with a card naming exactly what you could not find and where you looked. Never close quiet, and never let a superseded/declined sibling card mean the work is abandoned — see the seller-package skill's "Resuming after the info arrives".

## Name-only Pre-CMA intake blocker

Only after the SEARCH ladder above has failed. If a stage-entry Pre-CMA deal has only a seller name in deal `extra` (for example `workflow_client_1_name` / `clientName`) and no primary contact, email, phone, stored Lofty lead id, or CRM contact verifier, do **not** create or link a CRM contact from the name alone. A broad name search can return unrelated Lofty leads, and name + property address without email/phone/contact ID is not a safe match for this workflow.

Close the run as `waiting_human` instead:

1. Read back the deal row, primary contact join, and the current action run first.
2. Write a small local markdown audit artifact naming the available facts and why verification cannot proceed safely.
3. Try the HTTP result callback. If localhost refuses, use `admin_deal.complete_run` or the `record_run_result` fallback with the same idempotency key, the audit artifact, **no** `lofty_contact_verified` checklist update, and a concise human prompt.
4. Required fields should be short and actionable: `client email` (or `client phone` when that is the only possible verifier -- either one satisfies the gate). NEVER ask for `lead source` or `requested CMA date`; both are optional enrichment and neither blocks a card. Do NOT ask for `requested CMA date` — it was removed from the Pre-CMA gate on 2026-08-20 because a card is only in Pre-CMA when a walkthrough is already booked. Say where you already looked ("not in Elevation contacts, your phone contacts, Gmail or the CRM") so she knows the ask is a last resort. If a phone number is the only possible verifier needed, ask for `client phone` too.
5. Read back `admin_action_runs`, `admin_deal show`, and recent `deal_attachments` before reporting. Success for this path means the run is `waiting_human`, the audit artifact is attached to the current `source_run_id`, and the deal gate still shows `lofty_contact_verified` missing.

If a sibling/self-heal Pre-CMA run updates intake after this run already recorded a `waiting_human` prompt (for example it writes `workflow_client_1_email` and clears `pre_cma_dashboard_setup` / `pre_cma_handoff`), do not keep retrying `complete_run` to rewrite the locked prompt. Read the current deal `extra_toggles_json`, current gate, recent same-deal runs, and attachment rows; then deliver only the remaining missing fields from the live gate. If the active run still has the older prompt, treat it as a locked card prompt and avoid duplicate artifacts or repeated callback attempts unless you have a genuinely new, safe artifact to attach separately.

Do not report callback/port mechanics in the delivered Telegram line. Use the normal one-line blocker wording, narrowed to the live gate: `Info needed for <address>: client email (not in your contacts, Gmail or CRM). Fill the card or reply with it and I will finish the seller package.`

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
