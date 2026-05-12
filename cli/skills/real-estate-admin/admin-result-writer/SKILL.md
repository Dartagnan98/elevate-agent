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
