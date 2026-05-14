---
name: closing-admin
description: Final conveyance and closeout workflow: conveyancer package, mortgage instructions, insurance binder, sign-down, funds, commission, compliance close, and nurture handoff.
metadata:
  elevate:
    tags: [real-estate, closing, conveyance]
    runtime:
      approval_required: true
---

# Closing Admin

Use after subjects are removed and the deal is moving toward completion.

Track conveyancer package, mortgage instructions, insurance binder, sign-down, funds release, commission, compliance closeout, review/gift/nurture handoff, and final important dates.

Do not mark closeout complete unless the required evidence is attached or manually confirmed.

## Required Inputs

- Firm deal/subject-removal confirmation.
- Completion, possession, and adjustment dates.
- Conveyancer/lawyer/notary contacts.
- Deposit and funds status.
- Commission instructions.
- Compliance portal status.
- Client nurture/review/gift preferences from onboarding or memory.

## Flow

1. Build closeout tasks from the deal facts and province package.
2. Track conveyancer package, mortgage instructions, insurance binder, sign-down, funds release, commission, keys/possession, compliance close, and client handoff.
3. Attach inbound documents through `gmail-doc-router` or manual upload.
4. Sync compliance status through `skyslope-sync` or the configured portal.
5. Create human prompts for missing approvals, dates, funds, or final compliance evidence.

## Rules

- Keep important dates visible and write changes back to SQLite.
- Do not close a deal just because the date passed.
- Closeout is evidence-driven: attached docs, portal status, or explicit human confirmation.

## Output Contract

```json
{
  "workflow": "closing-admin",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "important_dates": {},
  "documents": [],
  "tasks": [],
  "closeout_ready": false,
  "risks": []
}
```
