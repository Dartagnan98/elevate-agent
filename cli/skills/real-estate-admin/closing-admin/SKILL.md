---
name: closing-admin
description: "Run final conveyance and closeout on a deal moving to completion. Use when subjects are removed and the deal moves toward completion, or the realtor says 'close out this deal', 'prep the conveyancer package', or 'we're completing on [address]'. Covers conveyancer package, mortgage instructions, insurance binder, funds, commission, and compliance close. Not for removing subjects — use subject-removal. Evidence-driven; never close just because a date passed."
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

- Keep important dates visible and write changes back to the deal record in the operational store.
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

## Provenance contract

Every number and material fact in generated output carries its source inline, at the claim — not in a footer. Comp prices and statuses cite the MLS number ("$914,900, MLS R2891234, sold 2026-05-12"); subject-property facts cite the record or document they came from; market stats cite the dataset and date range ("HPI, Kamloops SFH, May 2026"). A claim you cannot source does not ship — verify it live, or mark it unverified and say why. Never round, blend, or restate a sourced number in a way the source no longer supports.
