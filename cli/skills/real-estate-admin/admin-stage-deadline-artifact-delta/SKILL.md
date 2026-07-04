---
name: admin-stage-deadline-artifact-delta
description: "Reconcile deal deadline risk against newly filed attachments before opening a task. Use when a focused Admin Stage/Deadline/Condition-Watch heartbeat runs, or a subject-removal, deposit, completion, or possession gate needs rechecking against new evidence like signed proof or a calendar-sync confirmation."
version: 0.1.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [admin, heartbeat, deadlines, tasks, deal-files]
---

# Admin Stage/Deadline Artifact Delta

Use this when a focused Admin · Stage, Deadline & Condition Watch run checks active deals for subject-removal, deposit, completion, possession, expiration, or stage-gate risk.

## Reusable approach

1. Load the Admin surface context first.
   - Read the surface config/playbook and workspace `learnings.md`.
   - Count prior history rows and identify the most recent Stage/Deadline heartbeat when possible.

2. Build the current risk set.
   - Start with `deals_overview` active deals.
   - Prioritize overdue, today, two-day, and near-close risks: subject removal, deposit due, completion, possession, expiration, and stale accepted-offer gates.
   - For each risky deal, call `admin_deal(action='show', deal_id=...)` to get the current gate blocker before deciding anything.

3. Reconcile coverage before creating noise.
   - Pull current Admin and human tasks through `agent_bus`.
   - Match tasks by deal id, address, client name, MLS, and known blocker language.
   - Treat hidden/failed `admin_action_runs` as evidence only, not board-visible coverage.
   - Do not create a duplicate task if an existing task already covers the exact blocker and has current evidence.

4. Run the artifact-delta check.
   - Query `deal_attachments` and `deal_events` for the risky deals since the prior focused Stage/Deadline run or a conservative same-day cutoff.
   - Look for artifacts that narrow or confirm the blocker: accepted-offer verification, calendar sync proof, inspection/deposit checks, signed subject-removal evidence, portal/source status, recovery audits, newly routed docs, sent-proof artifacts, or completed checklist/outreach proof.
   - Compare the new artifact against the current `admin_deal` gate and existing task notes/outputs.
   - Re-run `admin_deal(action='show')` after fresh deal-event progress; the meaningful change may be a narrowed gate, not a cleared gate.

5. Refresh the exact covering task when evidence changed.
   - If a fresh artifact narrows or confirms the blocker, update the existing task instead of creating another one.
   - If the gate still has one remaining blocker, refresh that exact blocker task with the new proof, current gate, date/calendar coverage, and a no-external-action note.
   - Include a machine-readable `outputs` tuple with: `kind`, `at`, `deal_id`, `property`, `gate`, `new_evidence` or artifact path, `blocker`, `calendar_coverage` when relevant, and `disposition`.
   - Keep the task open when the gate still blocks; complete nothing unless the task is actually resolved.

6. Only escalate genuinely uncovered risk.
   - Create one concise Admin/human task only when no current task covers the exact blocker, or when the human ask materially changed.
   - Never send, upload, sign, edit calendars, change MLS/SkySlope, move money, or stage-advance from a heartbeat unless explicit approval and the surface goal authorize it.

7. Log and report tightly.
   - Write `history/<UTC>.json` with what was checked, what changed, risk dispositions, tasks updated/created, external actions, and summary.
   - If there is no new uncovered blocker and no meaningful change, suppress user-facing noise according to heartbeat report mode.

## Pitfalls

- A new internal artifact can make a task more current without clearing the gate. Refresh the existing task with the artifact path and narrower blocker instead of reporting a fresh blocker.
- `deals_overview` may show stale due dates after subject/removal or portal recovery evidence exists. Verify through `admin_deal show`, attachments/events, and current tasks before escalating.
- Current tasks can be stale if they predate fresh evidence. Update the exact task with a machine-readable evidence tuple so the next heartbeat can reconcile without rediscovery.
- Board-visible coverage matters. A failed action run, hidden prompt, or history row alone does not replace a current Admin/human task when a near deadline is still blocked.
