---
name: leads-hot-lead-watch-board-sync
description: "Stamp lead_status on reviewed Hot-Lead Watch rows so board-sync stops re-flagging them. Use when a hot inbound, stage move, or placeholder lead (\"No Name\", \"Paid Ad\") was reviewed but no draft or task was created."
version: 0.1.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [leads, hot-lead-watch, board-sync, lead-status]
---

# Leads Hot-Lead Watch Board-Sync Cleanup

Use this whenever a focused Leads · Hot-Lead Watch run reviews a hot signal, stage move, or placeholder lead row and does not create a new draft/task.

## Rule

A reviewed lead must get an explicit `lead_status` disposition before the run ends. If it was touched but not stamped, board-sync can re-flag it as worked-but-unhandled on the next run.

## Steps

1. Reconcile first.
   - Check whether the lead already has a pending approval/send_queue draft, active working-state draft, recent outbound, or completed new-lead/follow-up run covering the same signal.
   - Do not create duplicate drafts when coverage exists.

2. Stamp covered hot movement.
   - If a hot inbound/stage move is already covered by an approval-gated draft, set:
     - `status='new_lead'` or `status='follow_up'`, based on current lane.
     - `heat='hot'` for strong buyer/seller intent, `heat='warm'` for weaker but real movement.
     - Notes must include the coverage evidence, e.g. send_queue id, task id, next-follow-up date.

3. Stamp placeholder rows that were reviewed.
   - “No Name” with no email/phone and no usable signal: `status='dead'`, `heat='cold'`, note no usable identity/channel/context.
   - “Paid Ad” stale placeholder with no email/phone and no fresh signal: `status='dead'`, `heat='cold'`, note stale/no-channel/no-signal.
   - “Paid Ad Lead” or similar paid-ad placeholder with a usable email/phone but no fresh hot movement: `status='follow_up'`, `heat='warm'`, note paid-ad source and that follow-up lane can review without a hot-watch duplicate.

4. Verify.
   - Re-read the lead_status response or contact row.
   - If the tool ignores a requested heat label, make sure the pipeline status and notes still record the disposition.

## Example

```python
lead_status(
  action='set',
  contact_id='<contact_id>',
  status='follow_up',
  heat='warm',
  notes='Hot-Lead Watch reviewed placeholder paid-ad row; usable email exists but no fresh hot movement. Marked handled so follow-up lane can review without duplicate hot-watch alerts.'
)
```

## Pitfalls

- Do not mark a paid-ad placeholder dead if it has a usable email/phone and could still be followed up.
- Do not leave reviewed placeholders unstamped just because no draft was created.
- Do not use broad contact.updated_at/CRM sync noise as hot movement by itself.
