---
name: admin-result-writer
description: Shared helper contract for writing Admin skill results back to SQLite deal runs with checklist updates, artifacts, next tasks, human prompts, and idempotency keys.
metadata:
  elevate:
    tags: [real-estate, admin, sqlite, callback]
    runtime:
      writes_deal: true
      requires_idempotency_key: true
---

# Admin Result Writer

Use this contract at the end of every Admin workflow run.

Write one result for one verified `deal_id` and `run_id`. Include a stable `idempotencyKey` so retries do not duplicate artifacts, checklist updates, or next tasks.

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
    "requiredFields": []
  }
}
```

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

On retry, reuse the same key so SQLite can update or ignore the existing result instead of duplicating artifacts or next tasks.

## Human Prompts

Use `waiting_human` when the next safe action depends on the realtor. The prompt should be short enough for Telegram and structured enough for the UI:

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
