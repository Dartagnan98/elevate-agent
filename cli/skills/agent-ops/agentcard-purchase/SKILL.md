---
name: agentcard-purchase
description: "You need to make a purchase on behalf of the user — buy a SaaS subscription, pay for an API, purchase a domain, or any transaction requiring a credit card. Use this skill to request approval, issue a scoped virtual Visa card via AgentCard, and complete the purchase autonomously. Requires the AgentCard MCP server to be configured."
triggers: ["buy", "purchase", "pay for", "subscribe to", "need a credit card", "make a payment", "sign up for paid plan", "buy a domain", "purchase API credits", "pay invoice", "need to pay", "financial transaction", "virtual card", "agentcard"]
external_calls: ["mcp.agentcard.sh", "api.agentcard.sh"]
category: agent-ops
---

# AgentCard Purchase

Issue a scoped, single-use virtual Visa card to complete a purchase. Cards are funded on demand, capped at the approved amount, and auto-close after one transaction.

Requires: AgentCard MCP server configured via `agent-cards setup-mcp` (CLI: `npm i -g agentcard`).

---

## When to Use

You need to spend real money on behalf of the user. Examples:
- Buy a domain name
- Subscribe to a paid API or SaaS tool
- Purchase credits (OpenAI, cloud compute, etc.)
- Pay an invoice that was sent to the org

---

## Workflow

### Step 1: Request approval

Never create a card before getting approval. Use the native **Approvals** system with the `financial` category.

Create the approval in Approvals with:
- Title: `Purchase: <VENDOR> — <AMOUNT> for <REASON>`
- Category: `financial`
- Detail: `Vendor: <VENDOR> | Amount: $<AMOUNT> | Justification: <REASON>`

Then mark your current task blocked: use the **agent_bus** tool (action `update_task`) to set the task status to `blocked`, or update it in native **Tasks**.

The approval request surfaces in the dashboard Approvals queue. Do not send the request over Telegram — approvals are dashboard-only.

Wait for the decision. Do not proceed until the approval resolves to `approved`. Poll the **Approvals** queue (or use the **agent_bus** tool, action `list_approvals`) to read the decision. If the human needs to act and there is nothing further you can do, raise a `[HUMAN]` task in **Tasks** so it is visible to the user.

### Step 2: Create the virtual card

After approval, issue a card scoped to the purchase amount. Amount is in cents.

Use the AgentCard MCP tools:

```
mcp__agent-cards__create_card(amount_cents: NUMBER, sandbox: false)
```

Example for a $15 purchase:

```
mcp__agent-cards__create_card(amount_cents: 1500)
```

The tool returns: card ID, last4, expiry, balance, and billing address.

### Step 3: Get card details for checkout

```
mcp__agent-cards__get_card_details(card_id: "CARD_ID")
```

Returns full PAN, CVV, expiry month/year, and billing address. Use these to fill checkout forms.

### Step 4: Complete the purchase

Use the card details to complete checkout. For web purchases, use browser automation or fill forms via API. The billing address is:

```
2261 Market Street #4242
San Francisco, CA 94114, US
```

### Step 5: Verify and close

Check that the transaction went through:

```
mcp__agent-cards__list_transactions(card_id: "CARD_ID")
```

Cards auto-close after one transaction. If the purchase failed or you no longer need the card:

```
mcp__agent-cards__close_card(card_id: "CARD_ID")
```

### Step 6: Log the result

Mark the task complete with the result: use the **agent_bus** tool (action `complete_task`) on `<TASK_ID>` with a result like `Purchased <VENDOR> for $<AMOUNT>. Card ****<LAST4>. Transaction: <STATUS>`, or complete it in native **Tasks**.

Record the purchase as an audit entry: use the **agent_bus** tool (action `log_event`) with type `task`, name `purchase_completed`, level `info`, and meta `{"vendor":"<VENDOR>","amount_cents":<AMOUNT_CENTS>,"card_last4":"<LAST4>"}`.

Persist a durable note of the purchase for future recall: use the **memory** tool, and append a line to the agent's `MEMORY.md` / `memory/<day>.md`.

---

## Limits (Free Tier)

| Limit | Value |
|-------|-------|
| Cards per month | 5 |
| Max per card | $50 |
| Card lifetime | 7 days (unused) |
| Transactions per card | 1 (single-use) |

Upgrade to Basic ($15/mo) for 15 cards/month and $500 max per card: `agent-cards plan upgrade`.

---

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `create_card` | Issue a new virtual card (amount_cents, sandbox) |
| `list_cards` | List all cards with status |
| `get_card_details` | Get PAN, CVV, expiry for checkout |
| `check_balance` | Check remaining balance (no sensitive data) |
| `close_card` | Permanently close a card |
| `list_transactions` | View transactions for a card |

---

## Critical Rules

1. **Approval first, always.** Never create a card without an approved `financial` approval in the native Approvals system.
2. **Scope the amount.** Create the card for the exact purchase amount, not more. If a $12 domain, create a $12 card (1200 cents).
3. **One card per purchase.** Do not reuse cards across transactions.
4. **Close unused cards.** If the purchase fails or is cancelled, close the card immediately.
5. **Never log full PAN/CVV.** Only reference cards by last4 in task results, events, and memory.
6. **Sandbox for testing.** Use `sandbox: true` when testing the flow without real charges.
