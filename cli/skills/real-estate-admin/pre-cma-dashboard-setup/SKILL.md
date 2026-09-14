---
name: pre-cma-dashboard-setup
description: "Pre-CMA intake: turn a raw seller lead into a clean, CMA-ready deal (stage 0). Use when a new seller lead lands on the listing board, the realtor says 'set up the dashboard', 'prep this lead for the CMA', or the Pre-CMA intake form needs confirming and normalizing. Confirms the intake, normalizes client/property facts, saves the CMA handoff notes. Does not price, contact the client, or make docs. Not for running the CMA itself — use cma; not for the MLC paperwork — use mlc."
metadata:
  elevate:
    tags: [real-estate, listing-intake, pre-cma]
    runtime:
      result_writer: admin-result-writer
---

## Listing stage trigger contract — September 9, 2026

For BC listing stage decisions, read the [shared stage trigger contract](../admin-result-writer/references/listing-stage-triggers.md). It supersedes older manual-only and workflow-completion advancement rules for the named triggers. Entry into a stage starts its workflow; completing work alone does not advance the card. Preserve buyer-stage behavior. Use the runtime invocation section for the supported trigger tool/CLI; distinguish queued workflows from completed work.


# Pre-CMA Dashboard Setup

Use when a new seller lead enters the listing board at **Pre-CMA (stage 0)**, before any CMA work begins. This skill turns a raw lead into a clean, CMA-ready deal: it confirms the intake form is complete, normalizes the seller and property facts, and writes the handoff notes the CMA skill picks up at stage 1.

It does not price anything, does not contact the client, and does not create documents. It prepares the file.

## Required Inputs

**Hard requirements — the ONLY fields that may block this skill:**

- Client 1 legal name, plus at least one reachable channel (email or phone).
- Client 2 name if it is a co-owned property.
- Property address.

**Optional enrichment — record if available, otherwise proceed and leave blank. These NEVER block and NEVER trigger a `waiting_human` card on their own:**

- Client 2 email/phone.
- Lead source (where the seller came from).
- Requested CMA date / timing.
- Any seller notes, motivation, or timeline already captured.

A raw seller lead with a name, a contact channel, and an address is enough to set up the Pre-CMA and move the file forward. Do not stall the workflow asking for lead source, CMA date, or notes — those are helpful context, not gate conditions. Convert relative dates to absolute dates when present.

**Never fabricate an optional field.** "Optional, proceed anyway" means LEAVE IT BLANK when you don't have it — it does NOT mean invent a plausible value. Do not guess a lead source, a CMA date, an appointment time, or a seller note/timeline. Only write a value that came from a real cited source (the intake form, a CRM record you actually read, or the user). A blank optional field is correct; a made-up one is a defect.

**Enrich before you ask.** Resolve seller name/email/phone/source from Contacts, Gmail, iMessage, prior session evidence, local proof artifacts, Xposure/PCS proof already created by earlier runs, and the CRM first, then prompt ONE concise card for only the genuinely missing hard fields. Re-dispatched runs carrying `human_prompt_json.providedAnswers` apply the answers instead of re-asking.

**Thread-supplied facts are authoritative intake.** If the realtor provides contact facts in chat, treat them as current intake evidence and immediately write them to the Pre-CMA scorecard/contact fields before asking for anything else. Do not leave the scorecard blank because a sibling/earlier run asked for a field that the thread already contains. Example pattern: user says a contact's email is in Xposure PCS, gives a phone number, source/relationship note, and says the CMA is for a named property/address. After the PCS lookup succeeds, write the retrieved email, supplied phone, source note (for example SOI/home inspector), and property address to the scorecard. Only ask if the property address or reachable channel is still genuinely absent after reading the current thread and deal evidence.

**Use prior verified proof when the card is sparse.** If the deal only has a name/address but no reachable channel, search recent sessions/artifacts for the same client/address before blocking. A prior verified Xposure saved-list send, Gmail CC proof, CRM/Xposure contact verification, or other already-created audit can satisfy the reachable-channel requirement if it names the client and email/phone clearly. Cite that proof in the handoff audit and write only the exact sourced values.

## Flow

1. **Read the intake.** Open the configured Pre-CMA intake (Google Form response, dashboard record, or whatever the tenant has wired). Treat the form name, URL, and field labels as tenant configuration, not constants.
2. **Check the hard requirements only.** Write `waiting_human` ONLY if a hard requirement (seller name, a reachable email/phone, or the property address) is missing and cannot be enriched from Contacts/CRM/Gmail/iMessage. Missing optional enrichment (lead source, CMA date, seller notes) is never a blocker — proceed with those blank. Do not invent answers, and do not park the card for nice-to-have fields.
3. **Normalize the facts.** Write the cleaned client 1/2 identity, lead source, address, and requested CMA date onto the deal.
4. **Save the CMA handoff.** Write a short, factual notes block (motivation, timeline, property quirks, anything the CMA should weigh) onto the deal so the CMA skill starts warm.
5. **Close through `admin-result-writer`** with the checklist updates below.

## Rules

- Profile-driven only. The realtor identity, brokerage, intake form, and CRM are tenant configuration. Never hardcode a name, email, or form URL. If a value the skill needs is not on the profile or the deal, ask in the chat.
- Set a checklist/field cell only when the evidence supports it. Do not flip `pre_cma_dashboard_setup` until the dashboard/intake is actually confirmed.
- Only a missing HARD requirement (seller name, reachable email/phone, or property address) that cannot be enriched → `waiting_human` with the exact blocker. Optional enrichment (lead source, CMA date, seller notes) missing → proceed anyway with those fields blank; never park the card just for those. This is the standing anti-over-gating rule: never stall automation waiting on information that is not required to do the step.
- Lead source and CMA date are optional enrichment and are NOT in the Pre-CMA gate (removed 2026-08-20/21). Never stall or ask for either. Close the Pre-CMA run as succeeded once name + a reachable channel (email OR phone) + property address are proven.
- This is internal setup. Nothing here is sent to the client, so no approval gate is required — but never message the seller from this skill.
- **Hand off to `seller-package`, which AUTO-SENDS on the Pre-CMA stage-entry trigger.** That skill owns the single send path for approved Mailjet template `8055687`; do not send a second copy from here, and do not tell it to draft-only. If this skill parks `waiting_human` for a missing seller email/phone, note in the handoff that the seller package is BLOCKED on that same verifier, so answering the card resumes the send rather than leaving the seller with nothing. (Restored 2026-08-21 after 426 Gleneagles went a full day with no package.)
- Same finalization in any context: in a live session converse inline; on a stage trigger the conversation goes to the Admin agent lane. Always close through `admin-result-writer` so the kanban card reflects the outcome (see its "Where this writes").

## Checklist + Field Cells This Clears

Write only the cells the evidence supports:

- Checklist: `pre_cma_dashboard_setup`, `pre_cma_handoff`
- Fields: `workflow_client_1_name`, `workflow_client_1_email`, `workflow_lead_source`, `workflow_cma_date_requested`

- Contact verification (`lofty_contact_verified`) is owned by the `lofty-crm-client-contacts` skill — do not set it here.

## Implementation notes from prior runs

- Treat `deals.extra_toggles_json` as valid existing deal evidence for workflow fields. If it already contains `workflow_client_1_name`, `workflow_client_1_email`/phone, and `workflow_lead_source`, read it back and cite it in the audit instead of re-asking.
- Cross-check sparse Pre-CMA cards against `contacts` when possible, especially `xposure_contact_id`, `source_key`, `display_name`, `primary_email`, and `primary_phone`. A matching Xposure PCS contact row can corroborate the reachable-channel requirement and source note without browser work.
- `admin_deal set_fields` accepts workflow/detail fields only; do not include raw deal columns such as `primary_contact_id` in that call. Linkage/contact-column updates require a supported curated helper, not a workflow field write. If the workflow fields are already present, write only supported fields and close the run.
- After any direct field write or result callback, read back the current action run, the audit attachment row with `source_run_id`, and `admin_deal show`. If another self-heal/result path already closed the run while you were preparing local evidence, use the stored result and readback as source of truth rather than creating duplicate artifacts.

## Superseded / sibling-run recovery

Stage-entry bursts can create sibling Pre-CMA, seller-package, CMA, and Lofty-contact runs. If your current run is superseded or cancelled while you are working, do not resurrect it or rewrite its result. Read back the active sibling prompt and the deal gate. If you found new safe evidence before noticing the supersession, you may still write safe deal fields/checklist cells directly through `admin_deal` when the evidence supports them, attach a small audit artifact to the deal, and verify the gate. Keep the active sibling's missing-info prompt as the visible blocker instead of creating a duplicate. If `admin_deal attach` drops `source_run_id`, add/read back the attachment through the curated `elevate_db` helper `add_deal_attachment` with `source_run_id` so provenance is preserved.

If the injected Stage 0 card is `archived` or otherwise not in the active pipeline, pause before writing fields or checklist cells. Use `deals_overview` / `admin_deal show` to check for an active same-address or same-contact deal first. When an active duplicate already exists and is ahead of Stage 0, close the archived run as `skipped` with a stable idempotency key like `pre-cma-dashboard-setup:<archived_deal_id>:<run_id>:archived-duplicate-active-deal-exists`, attach nothing, do not copy new fields onto the archived card, and final cron delivery should be `[SILENT]` unless the active card itself has a new human blocker.

If the injected run belongs to an archived/duplicate Pre-CMA deal, first search the live deal board for the same normalized address/contact. When a separate active deal already exists for the same seller/property and already has the hard Pre-CMA fields plus `pre_cma_dashboard_setup` / `pre_cma_handoff` evidence, do not copy those fields back to the archived duplicate and do not ask the human again. Close the archived run as `skipped` with a stable idempotency key such as `pre-cma-dashboard-setup:<archived_deal_id>:<run_id>:archived-duplicate-active-deal-exists`, then read back the run and active deal gate. If there is no new user-facing blocker, final cron delivery may be `[SILENT]`.

When a **"re-run after info resolved"** Pre-CMA dashboard run starts after a sibling CRM-contact run has filled the hard fields, do not ask again and do not redo portal/browser work. Read back the current run, the sibling run named in `payload_json.reranAfterRunId`, the deal gate, deal `extra_toggles_json`, and existing Pre-CMA/CRM audit attachments. If the deal already has `workflow_client_1_name`, a reachable `workflow_client_1_email` or phone, the property address, and the prior handoff evidence, close the current run with `pre_cma_dashboard_setup=true` and `pre_cma_handoff=true`, attach a small run-specific reconciliation audit under the current `source_run_id`, and leave unrelated sibling runs (for example seller-package) to their own workflow. If the HTTP callback is unavailable, use `admin_deal complete_run` with the same idempotency key and read back `admin_action_runs`, `admin_deal show`, and the current run's attachment row before reporting.

## Output Contract

```json
{
  "workflow": "pre-cma-setup",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "artifacts": [],
  "checklist_updates": [],
  "fields_written": [],
  "missing_fields": [],
  "next_tasks": []
}
```
