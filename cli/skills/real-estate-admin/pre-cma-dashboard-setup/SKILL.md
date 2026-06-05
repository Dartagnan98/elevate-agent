---
name: pre-cma-dashboard-setup
description: Pre-CMA intake. Set up the listing dashboard for a new seller lead, confirm the Pre-CMA Google Form / intake is filled, normalize client and property facts, and save the handoff notes the CMA needs. First step of the listing pipeline (stage 0).
metadata:
  elevate:
    tags: [real-estate, listing-intake, pre-cma]
    runtime:
      result_writer: admin-result-writer
---

# Pre-CMA Dashboard Setup

Use when a new seller lead enters the listing board at **Pre-CMA (stage 0)**, before any CMA work begins. This skill turns a raw lead into a clean, CMA-ready deal: it confirms the intake form is complete, normalizes the seller and property facts, and writes the handoff notes the CMA skill picks up at stage 1.

It does not price anything, does not contact the client, and does not create documents. It prepares the file.

## Required Inputs

Ask for anything missing in one concise prompt. Pull what you can from the lead source (configured intake form / dashboard) before asking.

- Client 1 legal name and email (phone if available).
- Client 2 name/email if it is a co-owned property.
- Lead source (where the seller came from).
- Property address.
- Requested CMA date / timing.
- Any seller notes, motivation, or timeline already captured.

Convert relative dates to absolute dates.

## Flow

1. **Read the intake.** Open the configured Pre-CMA intake (Google Form response, dashboard record, or whatever the tenant has wired). Treat the form name, URL, and field labels as tenant configuration, not constants.
2. **Confirm the form is filled.** If the intake is missing or incomplete, surface exactly which fields are blank and write `waiting_human` with the form/account needed. Do not invent answers.
3. **Normalize the facts.** Write the cleaned client 1/2 identity, lead source, address, and requested CMA date onto the deal.
4. **Save the CMA handoff.** Write a short, factual notes block (motivation, timeline, property quirks, anything the CMA should weigh) onto the deal so the CMA skill starts warm.
5. **Close through `admin-result-writer`** with the checklist updates below.

## Rules

- Profile-driven only. The realtor identity, brokerage, intake form, and CRM are tenant configuration. Never hardcode a name, email, or form URL. If a value the skill needs is not on the profile or the deal, ask in the chat.
- Set a checklist/field cell only when the evidence supports it. Do not flip `pre_cma_dashboard_setup` until the dashboard/intake is actually confirmed.
- Missing form, missing access, or an intake that needs the seller to finish it → `waiting_human` with the exact blocker, never a silent pass.
- This is internal setup. Nothing here is sent to the client, so no approval gate is required — but never message the seller from this skill.
- Same finalization in any context: in a live session converse inline; on a stage trigger the conversation goes to the Admin agent lane. Always close through `admin-result-writer` so the kanban card reflects the outcome (see its "Where this writes").

## Checklist + Field Cells This Clears

Write only the cells the evidence supports:

- Checklist: `pre_cma_dashboard_setup`, `pre_cma_handoff`
- Fields: `workflow_client_1_name`, `workflow_client_1_email`, `workflow_lead_source`, `workflow_cma_date_requested`

Contact verification (`lofty_contact_verified`) is owned by the `lofty-crm-client-contacts` skill — do not set it here.

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
