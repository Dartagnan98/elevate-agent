---
name: subject-removal
description: "Work the subject-removal admin on an active accepted offer. Use when subjects are being removed, or the realtor says 'start subject removal', 'subjects come off [date]', or 'prep the deposit receipt and sold rider'. Covers condition docs, deposit receipt, lawyer info, sold rider/sign tasks, and title-charge checks. Not for extracting the offer terms first — use offer-review; not for final closeout — use closing-admin. The phase closes only on human confirmation."
metadata:
  elevate:
    tags: [real-estate, subjects, closing]
    runtime:
      approval_required: true
---

# Subject Removal

Use after an accepted offer is active and subject-removal work starts.

Prepare subject-removal document tasks, deposit receipt checks, lawyer info, sold rider/sign needs, and title charge review notes. Keep important dates on the deal record in the operational store.

Human confirmation is required before the subject-removal phase is marked complete.

## Required Inputs

- Reviewed accepted-offer facts.
- Subject/condition list and deadlines.
- Required subject-removal forms for the province package.
- Deposit status and receipt when applicable.
- Lawyer/notary info.
- Sold rider/signage requirements.
- Title charge or compliance checks when required.

## Flow

1. Confirm accepted-offer review is complete.
2. Build the subject-removal checklist from deal conditions and province package.
3. Prepare document tasks and signing tasks.
4. Track deposit receipt and lawyer info.
5. Create human prompts for approvals and missing conditions.
6. Mark subject-removal phase complete only after human confirmation.

## Rules

- Date deadlines are move-forward signals. Keep them in the deal's important dates in the operational store.
- If a condition is waived/removed manually, record the human confirmation as evidence.
- Do not mark the deal sold/firm unless the required subject-removal evidence exists or the human explicitly confirms.

## Form Semantics and Placement

- Notice of Condition Waiver semantics: "Additional Subject Clause(s) remain in effect" = PARTIAL removal; "All conditions are hereby Declared Fulfilled, and this contract is now Unconditional" = FINAL. Partial drafts populate only the waived clause and must NOT select the unconditional option.
- Buyers signed via e-sign with blank seller lines = place seller fields only in seller areas.
- F7205 final subject removal: no witness blocks, no Section B; one shared date.
- CPS: some initial boxes near the immigration/rescission/acknowledgment sections are buyer-only — seller fields only on seller-labelled lines.
- Addendum pages can print buyer lines ABOVE seller lines near the bottom — go by line labels, not position.
- The Section 28 final-acceptance date needs a tight DateSigned block on the underline, or it covers the sentence below.

## Output Contract

```json
{
  "workflow": "subject-removal",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "conditions": [],
  "dates": {},
  "documents": [],
  "deposit_status": "",
  "review_required": true,
  "risks": []
}
```
