---
name: approvals
description: "Gate an external, irreversible, or high-stakes action behind user sign-off. Use when about to send email/messages to real people, deploy to production, post to social, make a purchase or financial commitment, delete data, merge to main, or publish anything — create an approval, block your task, notify the user, and wait for the decision. Not for a step you genuinely cannot do yourself (payment, credentials, physical action) — use human-tasks instead. Covers a thing you CAN do but need permission for."
triggers: ["need approval", "create approval", "request approval", "approval needed", "needs sign-off", "needs permission", "before deploying", "before sending email", "before deleting", "before posting", "external action", "irreversible action", "financial commitment", "purchase", "deploy to production", "merge to main", "send to real person", "publish", "approval workflow", "pending approval", "waiting for approval", "check approvals", "list approvals"]
external_calls: []
category: agent-ops
---

# Approvals

Before any external, irreversible, or high-stakes action — stop and create an approval. The user decides. You execute only after they approve.

---

## When to Use

| Action type | Requires approval? |
|-------------|-------------------|
| Sending emails to real people | YES |
| Deploying code to production | YES |
| Posting on social media | YES |
| Making financial commitments | YES |
| Deleting data (files, DB rows, records) | YES |
| Merging to main branch | YES |
| Any action visible to external parties | YES |
| Internal work (writing files, creating tasks, research) | NO |

---

## Full Workflow

### 1. Create the approval

Use the native **Approvals** tool to create the approval request. Give it:

- **Title** — what you want to do (short, specific)
- **Category** — `external-comms` | `financial` | `deployment` | `data-deletion` | `other`
- **Context** — the draft content, the target/recipient, and why it's needed so the user can decide without asking follow-ups

Keep the approval ID it returns — you'll reference it when blocking your task and acting on the decision.

### 2. Block your task on the approval

Set your task to blocked so the work isn't lost while you wait:

- Use the **agent_bus** tool (action `update_task`) to move the task to `blocked` status, referencing the approval ID as the blocker and "awaiting approval" as the reason.
- Use the **agent_bus** tool (action `log_event`) to record a `task_blocked` event with the task ID, the blocking approval ID, and the reason — so the timeline reflects why the task stalled.

### 3. Notify the user

Approvals surface in the dashboard's Approvals view. Don't push a separate Telegram message — per Dartagnan's rule, approvals are dashboard-only, no Telegram approvals. Creating the approval in step 1 is the notification.

### 4. Wait for the decision

The user approves or rejects in the dashboard Approvals view. The resolution lands in your inbox — read it with the **agent_bus** tool (action `check_inbox`). It carries:

```
approval_id: appr_xxx
decision: approved | rejected
note: <user's note>
```

### 5. Act on the decision

**Approved:**

- Use the **agent_bus** tool (action `update_task`) to move the task back to `in_progress` with a note like "Approval received — executing".
- Execute the action.
- Use the **agent_bus** tool (action `complete_task`) to close the task with a result describing what was done.

**Rejected:**

- Use the **agent_bus** tool (action `complete_task`) to close the task with a result like "Cancelled — approval rejected: <note>".

---

## Re-pinging

If an approval is still pending after 4 hours during day mode, surface it once more — re-state it in your next status update or as a fresh note on the existing approval in the **Approvals** tool. Do NOT spam: one re-ping, then wait.

Note: this is a manual, in-session re-ping. If you need an automatic timed reminder (e.g. "ping me if still pending in 4h" when you won't be running), schedule it with the **cron** tool.

---

## Listing Pending Approvals

Read pending approvals with the **agent_bus** tool (action `list_approvals`), or open the Approvals view in the dashboard.

---

## Critical Rules

1. **Create approval BEFORE starting the action** — never take the action first and ask forgiveness
2. **Always block your task** pointing to the approval ID — so work isn't lost while waiting
3. **Never assume approval** — if you don't have an inbox confirmation (agent_bus action `check_inbox`), you don't have approval
4. **One re-ping max** — after 4h, surface it once and wait
