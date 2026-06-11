---
name: delivery-routing
description: "Route research summaries to local markdown, Telegram, or Slack with approval gates and delivery-state updates."
category: agent-ops
---

# Delivery Routing

Send the run summary to the configured destination. Mark items as delivered only
after successful delivery.

---

## When to Use

After brief-generation writes the run summary.

---

## Input

- `research/output/YYYY-MM-DD/summary.md`
- `research/output/YYYY-MM-DD/signals-selected.json` (needed to mark `delivered_at` on success)
- `config.json` (delivery config)
- `research/db/signals.db` (to mark `delivered_at` after successful delivery)

## Output

- Message sent to configured destination, OR an approval request created through native Approvals
- `delivered_at` set on delivered items in `research/db/signals.db`
- Delivery status appended to `research/output/YYYY-MM-DD/run.log`

---

## Approval Gate

**Always check `research.delivery.requires_approval` before sending externally.**
External destinations are `telegram` and `slack`. `local_markdown` and `none` do
not leave the machine.

### If `true` (default)

Create an approval through native Approvals, write a local approval context file,
notify the user, and stop. Do not send externally until the approval is granted.

Every approval must have a parent task. If this delivery was started by a cron
or ad-hoc workflow and no task exists yet, create a run task first (native Tasks,
or the agent_bus tool action update_task to set it) and mark it `in_progress`.

```
research/output/YYYY-MM-DD/PENDING-APPROVAL.md
```

```markdown
# Delivery Pending Approval -- YYYY-MM-DD

Run complete. Summary ready but not sent (`research.delivery.requires_approval = true`).

**Approval:** Created through native Approvals.

**Summary path:** research/output/YYYY-MM-DD/summary.md
**Signals selected:** N
**Top signals:**
1. [Title] (score: X.X)
2. [Title] (score: X.X)
3. [Title] (score: X.X)
```

Use the normal approval workflow:

1. Create the approval in native Approvals (title "Send research summary for
   YYYY-MM-DD", category external-comms, with the destination and the
   summary/pending-context paths in the body). To read the result later, use the
   agent_bus tool (action list_approvals).
2. Notify the user. There is no Telegram send mechanism in Elevate — surface the
   pending approval through native Comms (or agent_handoff to the human) with the
   message: "Approval needed: research summary for YYYY-MM-DD is ready. Check the
   Approvals queue." Do not invent a Telegram command.
3. Record the event with the agent_bus tool (action log_event): action
   `approval_created`, level info, meta `{"approval_id": "...", "destination": "..."}`.

If this run has a parent task, block that task on the approval. If it was cron
started and has no parent task, create one (native Tasks) before requesting
approval, then block that task on the approval.

Log: `Delivery pending approval. Request at research/output/YYYY-MM-DD/PENDING-APPROVAL.md approval_id=<id>`

### If `false`

Send to configured destination automatically, then mark `delivered_at`.

---

## Destinations

### Telegram

Elevate has no native Telegram send mechanism. If a run is configured for
`telegram`, do NOT invent a command — deliver the summary through native Comms
(or agent_handoff to the human) instead, and raise a [HUMAN] task noting that
the config requested Telegram and a real transport needs to be wired or the
destination changed.

Message format: run date, signals collected vs. selected, top 3-5 titles with scores,
any source failures, path to full output folder. Keep under 4,096 characters; split
into two messages if longer.

### Slack

Use Slack only when the workspace webhook is configured and approval policy
allows external delivery.

```bash
curl -s -X POST "${SLACK_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -d '{"text": "MESSAGE"}'
```

### Local Markdown

Write `research/output/YYYY-MM-DD/DELIVERED-summary.md` as a copy of the summary.
No external HTTP calls.

### None

No delivery. Summary stays at `research/output/YYYY-MM-DD/summary.md`.

---

## Message Content

Send only the summary -- not full brief text. The full briefs live on disk at
`research/output/YYYY-MM-DD/briefs/`.

Minimum content:
- Run date and time
- Number of signals selected out of total collected
- Top 3-5 signals: title, score
- Any source failures from run.log
- Path to full output folder

---

## Error Handling

Retry up to 3 times with 5-minute intervals between attempts.

```python
import time

def deliver_with_retry(send_fn, max_retries=3, delay_seconds=300):
    for attempt in range(1, max_retries + 1):
        try:
            send_fn()
            return True
        except Exception as e:
            log(f"delivery_failure attempt={attempt} detail={e}")
            if attempt < max_retries:
                time.sleep(delay_seconds)
    return False
```

If all 3 attempts fail:
1. Write the summary to `research/output/YYYY-MM-DD/DELIVERY-FAILED-summary.md`.
2. Log: `delivery_fallback path=research/output/YYYY-MM-DD/DELIVERY-FAILED-summary.md`
3. Do not raise -- delivery failure is non-fatal to the run.

---

## Config Schema

Read delivery settings from `config.json`:

```json
{
  "research": {
    "delivery": {
      "destination": "local_markdown",
      "requires_approval": true,
      "summary_only": true
    }
  }
}
```

Supported destinations:
- `local_markdown`
- `telegram` (no native transport — see Telegram section; route through Comms + [HUMAN] task)
- `slack`
- `none`

## Mark delivered_at (After Successful Delivery Only)

After the message sends successfully, call `mark_delivered()`:

```python
import sqlite3, datetime as dt, json

def mark_delivered(db_path, selected_json_path):
    with open(selected_json_path) as f:
        selected = json.load(f)
    conn = sqlite3.connect(db_path)
    now = dt.datetime.utcnow().isoformat()
    for item in selected:
        conn.execute(
            "UPDATE items SET delivered_at=? WHERE canonical_key=?",
            (now, item["canonical_key"])
        )
        conn.execute(
            """UPDATE daily_brief_items
               SET delivered=1, delivered_at=?
               WHERE item_id = (SELECT id FROM items WHERE canonical_key = ?)""",
            (now, item["canonical_key"])
        )
    conn.commit()
    conn.close()
```

This ensures items are only suppressed from future runs if delivery actually succeeded.
If delivery failed, they remain eligible for the next run.
