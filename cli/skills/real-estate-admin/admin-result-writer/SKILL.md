---
name: admin-result-writer
description: Shared helper contract for writing Admin skill results back to operational-store deal runs with checklist updates, artifacts, next tasks, human prompts, and idempotency keys.
metadata:
  elevate:
    tags: [real-estate, admin, operational-store, callback]
    runtime:
      writes_deal: true
      requires_idempotency_key: true
---

# Admin Result Writer

Use this contract at the end of every Admin workflow, however it was invoked.

Write one result for one verified `deal_id`. Include a stable `idempotencyKey` so retries do not duplicate artifacts, checklist updates, or next tasks. `run_id` is optional: present for background/stage runs, absent for live sessions (see "Where this writes").

## Where this writes — the kanban board is the source of truth

The result always lands on the deal's kanban card. How it gets there depends on how the skill was invoked:

- **Background / stage run (has a `run_id`):** close the run through its result callback. The callback applies checklist updates, fields, and artifacts to the deal and advances the stage when the gate clears. Free-form questions reach the realtor on the Admin agent's async lane.
- **Live session (no `run_id`):** you are talking to the realtor directly. Hold the back-and-forth in that session — ask, confirm, iterate — then finalize through the **`admin_deal`** tool so the SAME result lands on the card: `set_fields` for named fields, `set_checklist` for cells, `attach` for artifacts, and `advance` when the gate is clear. If the deal entered the stage on its own it has a pending run that blocks the gate — close it with `admin_deal` `complete_run` (which applies checklist_updates + artifacts and auto-advances), not `force`. The card must reflect the outcome before you consider the work done.

Either way the end state is identical: the kanban shows the completed checklist cells, the attached artifacts, and the new stage. A session conversation that ends without syncing the deal is unfinished — never leave the result only in the chat.

Result shape:

```json
{
  "status": "succeeded | waiting_human | failed | skipped",
  "idempotencyKey": "skill:deal-id:stable-output",
  "summary": "what changed",
  "checklist_updates": [{ "id": "workflow_item_id", "completed": true }],
  "artifacts": [{ "kind": "document", "filePath": "/path/to/file", "summary": "what it is" }],
  "next_tasks": [{ "skill": "seller-update", "title": "Next safe task", "payload": {} }],
  "human_prompt": {
    "title": "Decision needed",
    "message": "Concise approval question",
    "requiredFields": [],
    "previewPdf": "/absolute/local/path/to/drafted.pdf"
  }
}
```


**`previewPdf` (approval-gated documents):** when the human prompt asks Skyleigh to approve a PDF you drafted (release form, MLC, CPS, amendment — anything that goes to DigiSign on approval), set `human_prompt.previewPdf` to the absolute local path of the **clean** PDF (the one that would actually be sent, not a placement-only overlay). The dashboard renders a "Preview PDF ↗" button on the waiting card from this field so Skyleigh can read the exact document before Approve & re-run. Must be a local `.pdf` that exists (not a `gdrive://` URI). Still attach the same file under `artifacts` for the record.

For unsafe or incomplete work, use `waiting_human`; do not mark checklist cells complete. For external sends, signatures, document approvals, price/listing copy approvals, and final photo approval, create a human prompt first.

## Idempotency

Build the idempotency key from stable facts, not a timestamp:

```text
<skill>:<deal_id>:<run_id or source id>:<output purpose>
```

Examples:

- `gmail-doc-router:deal123:gmail-msg-abc:accepted-offer-pdf`
- `seller-update:deal123:2026-05-13:weekly-digest`
- `mlc:deal123:filled-mlc-v1`

On retry, reuse the same key so the operational store can update or ignore the existing result instead of duplicating artifacts or next tasks.

## Human Prompts

Use `waiting_human` when the next safe action depends on the realtor. In a **live session**, ask the prompt inline and wait for the answer, then finalize. In a **background run**, the prompt surfaces on the dashboard (approvals + the deal card) and the realtor's answer comes back on the Admin agent's async lane. Keep it short enough for the lane and structured enough for the UI:

```json
{
  "title": "Confirm MLC before signing",
  "message": "Review the filled MLC and confirm the seller names, commission, dates, and signature placements are correct.",
  "requiredFields": ["seller approval", "signed-doc destination"]
}
```

Do not hide required context inside a long summary. Put required inputs in `requiredFields`.

## Artifact Rules

- Attach only files that exist or external IDs that were returned by the provider.
- Include a short summary for each artifact so the UI can display it without opening the file.
- Use provider-neutral kinds when possible: `form_draft`, `signed_document`, `seller_update_pdf`, `listing_photo_set`, `offer_pdf`, `deposit_receipt`, `compliance_status`, `gmail_draft`.
- If a portal generated something but the file could not be downloaded, write a human prompt and include the portal URL or external ID as evidence. Do not pretend the document is attached.


## Operator-supplied answers (fillable Waiting-on-you card)

When a run is re-dispatched after the operator filled the inline "Waiting on you" form, the run **payload** carries their typed answers:
- `payload.intake_answers` — a map of `{ required-field label -> the operator value }`.
- `payload.intake_answers_text` — the same as a readable block.

If these are present, **use them to fill the missing fields and proceed** — write them to the proper deal fields/contacts and continue the workflow. Do NOT re-ask for information the operator already provided in `intake_answers`. Only surface a new `waiting_human` prompt for items that are STILL genuinely missing after applying their answers.


## Concise missing-info prompts (no walls of text — reads on card AND Telegram)

When you surface a `waiting_human` because required intake is missing, keep it TIGHT. The same prompt renders on the fillable scorecard AND gets delivered to Skyleigh on Telegram, so verbosity there is confusing for any user.
- `title`: short, e.g. `Info needed: 1740 Clifford`.
- `message`: ONE short line, e.g. `To run the CMA I need a few details.` Optionally one hint line: `Reply with the answers (one per line) or fill them on the card.`
- `requiredFields`: the missing items as SHORT labels, one concept each (these become the fillable fields on the card and the `Need: …` list): e.g. `client email`, `lead source`, `requested CMA date`, `property notes`.
- Do NOT put internal context, file paths, run IDs, skill names, SHAs, reasoning, or "I did X / did not do Y" into `message`. Those belong in artifacts/audit, never the user prompt.

## Answering a missing-info prompt from Telegram / chat (easy reply)

If Skyleigh replies (Telegram or chat) with answers to a deal's missing-info prompt, do NOT re-ask. Find the matching `waiting_human` run for that deal (most recent if context is clear), map her reply to the `requiredFields` (one per line, or `field: value` pairs), and submit so the skill re-runs WITH the answers:
- Preferred: POST `http://127.0.0.1:9120/api/admin/action-runs/<run_id>/answer` with JSON `{ "answers": { "<field>": "<value>", ... }, "runNow": true }` (session token via header or `?token=`).
- Or set `payload.intake_answers` on the run and re-dispatch.
Then confirm briefly: `Got it — running the CMA now.` Only surface a new prompt for items STILL missing.


## The DELIVERED message (Telegram / home channel) must be ONE clean line

Whatever you say at the end of a run is delivered verbatim to Skyleigh on Telegram. Keep that final user-facing message to ONE short line — the same standard as the card prompt. Specifically:
- waiting_human (missing info): `Info needed for <address>: <item1>, <item2>, <item3>. Fill the card or reply with the answers.`
- done: `<address>: <one-line outcome>.`
- blocked: `<address> blocked: <one short reason>.`
NEVER narrate internal mechanics in the delivered message: no callback-port retries, no "readback verified", no "no checklist items marked / no sends happened", no skipped-skill warnings, no run IDs / file paths / SHAs. All of that goes into the audit artifact ONLY, never the message. If a normal user read the message, it should be instantly clear and contain zero plumbing.


## Concise must still be COMPLETE — the card has to be answerable on its own

CONCISE ≠ context-free. A user reading ONLY the card must understand what is being asked and be able to answer without any outside explanation. The 2026-06-22 failure: the card said "Which Lofty contact should I use for 1740 Clifford?" with a field "Lofty contact / seller email decision" — but never said a contact ALREADY EXISTED or what the choices were, so Skyleigh could not answer from the card.

Rules:
- If the prompt references a finding, conflict, or existing record, STATE it in the `message` in plain words — short, but include the decisive facts (e.g. "Found an existing Lofty contact for 1740 Clifford under skyleigh@hotmail.com.").
- For a DECISION, give the actual options. Prefer a STRUCTURED field so the card renders real choices:
  - `requiredFields` items may be objects: `{ "label": "...", "help": "one-line context", "type": "select", "options": ["Use existing skyleigh@hotmail.com", "Create new skyleigh.mccallum@gmail.com"] }`. Plain strings still work for free-text.
  - Use `type":"select"` + `options` whenever the answer is a choice among known values; use `help` to carry the one-line context for any field.
- Still no internal plumbing (paths, run IDs, callback ports). Concise + complete + plain-language — not terse-and-cryptic.
