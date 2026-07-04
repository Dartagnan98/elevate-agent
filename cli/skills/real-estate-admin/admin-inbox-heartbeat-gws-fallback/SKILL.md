---
name: admin-inbox-heartbeat-gws-fallback
description: "Reconcile Admin inbox hits via local gws Gmail when Browser Use can't extract Gmail. Use when a heartbeat run finds Browser Use stuck on a Google sign-in page, gws Gmail commands still authenticate, or you need to check whether a SkySlope/DigiSign/WEBForms notice or a deposit/completion email is already covered by an existing task."
version: 0.1.0
platforms:
  - macos
  - linux
metadata:
  hermes:
    tags: [admin, inbox-triage, gmail, heartbeat, gws, reconciliation]
---

# Admin Inbox Heartbeat — gws fallback and sent-mail reconciliation

Use this as a supplement to `surface-heartbeat` for focused **Admin · Inbox & Message Triage** runs.

## Trigger
- Browser Use opens Gmail to Google sign-in or otherwise cannot extract the inbox during a cron run.
- Local `gws` Gmail commands still authenticate successfully.
- The heartbeat is draft/reconciliation-only and must not send, file, pay, upload, or change portal/deal state.

## Procedure
1. Load the normal Admin surface context first:
   - `agent_bus(action='get_surface_config', surface='admin')`
   - workspace `learnings.md`
   - recent Admin heartbeat `history/*.json`, especially same-day Inbox/Agenda/Stage/Transaction-board entries.
   - pending tasks and approvals via `agent_bus`, plus `deals_overview`.

2. Verify Browser Use state, but do not stall on login:
   - Open Gmail with Browser Use CLI per policy.
   - If it lands on Google sign-in, record that as extraction unavailable and switch to local `gws` rather than failing the heartbeat.

3. Pull Gmail candidates with `gws`:
   - Use metadata first, after the prior relevant Inbox heartbeat cutoff:
     `gws gmail users messages list --params '{"userId":"me","q":"after:YYYY/M/D -from:me","maxResults":100}'`
   - Fetch headers/snippets for candidates:
     `gws gmail users messages get --params '{"userId":"me","id":"<id>","format":"metadata","metadataHeaders":["From","To","Subject","Date"]}'`
   - Filter for Admin/deal terms: active property names/addresses, SkySlope, DigiSign, WEBForms, ShowingTime, Interac/e-Transfer, deposit, completion, possession, subject removal, lawyer/notary, conveyance, offer, amendment, General Release, BC Listings.

4. Reconcile before creating anything:
   - Same-day Admin heartbeat history may already have handled the item.
   - Check pending human/Admin tasks for matching Gmail id, thread, property, sender, amount, or vendor.
   - Fetch the full Gmail thread for any candidate that looks unanswered; if a later message in the thread has Gmail label `DRAFT` and the snippet shows the requested reply/document is already drafted, treat it as covered and do not create a duplicate blocker.
   - Check `deal_attachments` and `deal_events` for filed/routed evidence, especially completed-envelope messages.
   - Check `send_queue`/existing approval tasks for drafts or client-facing actions already awaiting review.

5. Handle approved external-send tasks carefully:
   - Before treating a reply/send as outstanding, search Gmail Sent with `gws`, scoped to recipient, subject/property, and date.
   - If an approved external-send task exists but Sent has no matching message, update that existing task with the sent-mail verification and leave it pending for the owning Admin action path.
   - Do **not** send or attach files from the heartbeat, even if approval is already resolved, unless the heartbeat config explicitly says to execute sends.

6. Classify covered noisy items:
   - Generic SkySlope/DigiSign cancellation notices can be covered by later completed-envelope routing or filed deal evidence. Do not create a new blocker if later evidence already resolves the signing path and a current task covers the remaining deal question.
   - Interac/RBC/legal-transfer receipts stay human bookkeeping/deal-match review unless the law firm, amount, and transaction match are explicit and already covered.
   - Vendor/account receipts, such as Lofty payment receipts, should be reconciled against existing tasks by purpose, not just vendor name. A Lofty security/login task does **not** cover a separate Lofty bookkeeping receipt. If no current bookkeeping/file-review task covers the receipt, create one human task and keep it strictly review/file-only.

7. Extract small Gmail receipt PDFs when useful:
   - For a fresh receipt/invoice email with an attachment, fetch the full message with `gws gmail users messages get --params '{"userId":"me","id":"<id>","format":"full"}'`, locate `body.attachmentId`, then fetch it with `gws gmail users messages attachments get --params '{"userId":"me","messageId":"<id>","id":"<attachmentId>"}'`.
   - Base64url-decode the returned `data` to a local temp PDF and run `pdftotext` when available. Extract only concise bookkeeping facts: vendor, receipt/invoice number, date, service period, amount, billed-to, and Gmail id. Do not file/upload the PDF from the heartbeat.
   - When creating the human review task, immediately call `agent_bus(action='update_task', task_id='<id>', outputs=[...])` after `create_task`; `create_task` may return with `outputs: []`. Verify the updated task contains the machine-readable Gmail and receipt evidence.

8. Log the run:
   - Write `history/<UTC>.json` with checked sources, what was reconciled, any task updates, and explicit no-side-effects wording.
   - If no fresh unaddressed Admin item remains, report only if an existing task was materially updated; otherwise return `[SILENT]`.

## Guardrails
- Never click payment links.
- Never send client-facing email or attach/send documents from the heartbeat.
- Never file receipts/documents or advance stages from a payment or generic portal notice alone.
- Prefer updating an existing current task over creating a duplicate blocker.
