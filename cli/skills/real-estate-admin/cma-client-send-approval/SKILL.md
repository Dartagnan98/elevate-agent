---
name: cma-client-send-approval
description: "Stage an Admin-dashboard approval for a client CMA email and block the send. Use when the realtor asks to prepare a CMA/Market Evaluation email for sellers or buyers and says not to send until approval, the action would email a real client, she can't see the dashboard draft, or she later confirms it was already sent/approved out of band."
version: 1.0.0
author: elevate
metadata:
  elevate:
    tags: [real-estate-admin, cma, client-email, approvals, admin-dashboard]
---

# CMA Client Send Approval

Use this when the realtor asks to prepare a client-facing CMA/Market Evaluation email for sellers or buyers and explicitly says not to send until approval, or when the action would send a CMA to a real client. This workflow stages the send on the Admin dashboard only. It does **not** send the email.

## Rules

- Client/external sends require Admin dashboard approval. Create the approval before any send attempt.
- Do not email, publish, sign, or otherwise contact the client while approval is pending or rejected.
- Use the realtor's client-facing writing style: warm greeting with the client's name, first person from the realtor, no em dashes, space before `!` / `?`, and CMA copy as a price story rather than a spreadsheet.
- For CMA emails, headline one recommended list price when the report has one. Do not create a new price range unless the report itself uses one.

## Steps

1. **Find the matching Admin deal**
   - Start with `deals_overview` and match by property/address/client names.
   - Record the `deal_id`, title, stage, list price, and `primaryContactId`.
   - If ambiguous, query `deals` through `elevate_db` with the address/client names.

2. **Verify client recipients from deal/contact records**
   - Query the primary contact and all `deal_contacts` for the deal through `elevate_db`.
   - Pull `display_name`, `primary_email`, `primary_phone`, role, and flags: `cannot_email`, `unsubscribed`, `hidden`.
   - If the record only has one shared email for a couple, use that single verified email and state that no separate individual addresses were present.
   - Block instead of staging approval if no verified email exists or any selected recipient has `cannot_email=1`, `unsubscribed=1`, or `hidden=1`.

3. **Select and verify the CMA PDF**
   - Query `deal_attachments` newest-first and prefer the newest actual `.pdf` CMA report row over proof JSON/contact sheets.
   - Prefer filenames/summary indicating `CLIENT-READY`, current recommended price, current date, `PROSPECTING` or the requested revision.
   - Verify the file locally with `terminal` or Python:
     - path exists and is a file
     - non-zero size
     - `file` reports PDF
     - `pdfinfo` if available: page count, not encrypted/broken, title/address if present

4. **Draft the client-facing email**
   - Subject: short and property-specific, e.g. `<Address> Market Evaluation`.
   - Body structure:
     1. Warm greeting using the client's actual name(s).
     2. State the Market Evaluation/CMA is attached.
     3. Summarize the price story in plain language: recent sales, property positioning, buyer demand, and why the recommended list price fits.
     4. Invite questions.
     5. Warm sign-off in the realtor's usual style.
   - Keep language client-ready. Avoid internal terms like acceptance gate, proof JSON, stale price, artifact path, visual QA, or workflow.

5. **Check for an existing approval before creating a new one**
   - Run `agent_bus(action='list_approvals', agent_id='admin')` and look for an approval matching the same deal/address/client-send decision.
   - If an existing approval is `pending`, do **not** create a duplicate. Re-verify the PDF, recipient flags, draft body, and blocked task, then attach a continuation proof to the deal.
   - If an existing approval is `approved`/granted, verify the resolved status and approval ID before any send. Only then proceed to the send step if the user requested sending.
   - If an existing approval is `rejected`, do not send or recreate automatically unless the realtor gives a new explicit instruction.
   - Also check `send_queue`, `draft_attempts`, and the contact's `conversations` for the recipient/address to confirm no prior client send occurred when continuing or recovering the workflow.

6. **Create the Admin dashboard approval when none exists**
   - Use `agent_bus(action='create_approval')` with:
     - `agent_id: 'admin'`
     - `category: 'external-comms'`
     - title like `Send <address> CMA PDF to <client names>`
     - description containing the full decision packet:
       - deal id/title
       - verified recipients and contact flags
       - PDF attachment path and verification results
       - draft subject
       - full draft body
       - explicit instruction: do not send unless this approval is approved in the dashboard
   - Save the returned approval ID and status.

7. **Create a blocked follow-up task**
   - Use `agent_bus(action='create_task')` assigned to `admin` with:
     - `status: 'blocked'`
     - `needs_approval: true`
     - high priority if client delivery is time-sensitive
     - notes starting with `Approval: <approval_id>` so approval resolution can unblock the workflow
     - attachment path, recipient, and deal id in the notes/description
   - Log an activity event with `agent_bus(action='log_event')` recording the deal id, approval id, blocked task id, recipient, and attachment path.

8. **Persist proof on the deal**
   - Write a Markdown proof file beside the CMA artifacts, e.g. under `proof/client-send-approval-email-draft-<timestamp>.md`, containing:
     - deal id/title
     - approval id/status
     - blocked task id
     - verified recipients and source
     - attachment path and verification
     - subject/body
     - send rule: no send until approval is approved
   - Attach that proof file to the Admin deal with `admin_deal(action='attach')`, kind `cma_client_send_approval`, and summary noting no client email was sent.

9. **If the realtor cannot see the dashboard draft, create a Gmail draft copy**
   - Trigger: the realtor says she cannot see the draft from chat/dashboard, asks to put it as a draft in her own Gmail, or asks to send it to her in the current channel.
   - A Gmail draft is allowed because it is not a client send, but still do **not** send the email.
   - Create the draft in the realtor's Gmail with the verified recipient(s), subject/body, and PDF attachment.
   - Use `gws gmail users drafts create` with RFC822 upload rather than putting the base64 message in `--json`; PDF attachments can make argv too long.
   - Pattern:
     1. Build an `EmailMessage` with `To`, `From`, `Subject`, body, and `add_attachment(PDF.read_bytes(), ...)`.
     2. Write it under the CMA run directory, e.g. `<run>/email_tmp/<client-cma-draft>.eml`.
     3. Run from that CMA run directory:
        `gws gmail users drafts create --params '{"userId":"me"}' --upload email_tmp/<client-cma-draft>.eml --upload-content-type message/rfc822 --format json`
     4. Verify with `gws gmail users drafts get --params '{"userId":"me","id":"<draft_id>","format":"metadata"}' --format json` and confirm label `DRAFT`, recipient, subject, and `multipart/mixed`.
   - Final response should include the Gmail draft ID, recipients, subject, and the draft body pasted in chat so the realtor can review without opening the dashboard.
   - If she asks to send it to her in the current channel, return the draft body in the final response and include the PDF as `MEDIA:/absolute/path.pdf`; do not client-send.

10. **Reconcile after the realtor confirms the CMA was sent/approved**
   - Trigger: the realtor says the client-send is already sent, approved, or otherwise complete.
   - Do **not** send or resend the email. Treat the confirmation as a human/external send reconciliation.
   - Verify the matching deal, pending approval, and blocked send task:
     - `deals_overview` for the exact CMA deal.
     - `agent_bus(action='list_approvals', status='pending')` for the approval ID.
     - `agent_bus(action='list_tasks')` if needed to find the blocked Admin send task. Narrowing by `assignee/status` may miss tasks if the tool's filter syntax is strict, so inspect the unfiltered result if necessary.
   - If `agent_bus` does not expose an approval-resolution action, use the local data helper from `terminal`:
     ```python
     from elevate_cli.data import connect, surface_tasks
     with connect() as conn:
         surface_tasks.resolve_approval(
             conn,
             approval_id,
             decision='approve',  # helper expects 'approve' or 'reject', not 'approved'
             note='Realtor confirmed out of band. Reconciled as human-approved and human-sent; no automated resend performed.',
             resolved_by='human:realtor',
         )
     ```
   - Close the blocked Admin send task with `surface_tasks.complete_task(...)`, result stating it was closed without automated send because the realtor confirmed it was already sent/approved.
   - Update the Admin deal extra fields with `deals.set_deal_toggle(...)` rather than `set_deal_fields(...)` for custom CMA/client-delivery fields. `set_deal_fields` rejects unsupported detail fields. Useful fields:
     - `cma_client_delivery_status = human_sent_confirmed`
     - `cma_client_delivery_approval_id = <approval_id>`
     - `cma_client_delivery_approved = true`
     - `cma_client_delivery_human_confirmation = <exact confirmation text>`
     - `cma_client_delivery_sent_by_human = true`
     - `cma_client_delivery_sent_by = realtor / human confirmed`
     - `cma_client_delivery_reconciled_at = <UTC ISO timestamp>`
     - `cma_client_delivery_human_confirmed_at = <UTC ISO timestamp>`
     - `cma_client_delivery_pdf_path = <verified PDF path>`
     - `cma_client_delivery_recipient = <verified recipient>`
     - `cma_client_delivery_subject = <subject>`
     - `cma_client_delivery_do_not_resend = true`
     - `cma_approved_by_realtor = true`
     - `cma_approved_human_confirmed_at = <UTC ISO timestamp>`
   - Write a compact `deals.record_deal_activity(...)` note summarizing approval resolution, task closure, CMA approval, human-send confirmation, and no resend.
   - Verify afterwards:
     - `agent_bus(action='list_approvals', status='approved')` shows the approval resolved.
     - `agent_bus(action='list_tasks', status='completed')` shows the blocked send task completed.
     - `elevate_db` confirms `extra_toggles_json` contains the reconciliation fields and `deal_events` contains the toggle/activity events.

11. **Final response to the realtor**
   - For a staged approval, return:
     - verified recipients
     - attachment path and verification summary
     - approval ID/status
     - blocked task ID if created
     - Gmail draft ID if created
     - draft subject and body
     - blockers
     - clearly state no email was sent.
   - For a reconciliation after human send/approval confirmation, return:
     - approval ID/status and resolved-by note
     - deal fields updated
     - blocked task ID completed
     - activity ID written
     - clearly state no automated resend was performed.

## Pitfalls

- Do not use `admin_deal()` without a `deal_id`; it requires an explicit deal id.
- `deal_contacts` may not have `is_primary`; inspect schema or query only existing columns.
- Newest `deal_attachments` rows are often proof JSON/contact sheets. Select the newest actual CMA PDF, not the newest row overall.
- The approval must contain the full email content and attachment path so the realtor can decide from the dashboard without asking follow-up questions.
- Dashboard-only approvals may not be visible from the realtor's current surface. When she asks to review the draft or says she cannot see it, either create a visible Gmail draft in her account with the verified attachment or paste the full draft text in chat. Do not rely on an Admin-dashboard-only draft for user review.
- Creating an approval is not the same as sending. Stop after approval/task/proof unless a later inbox/dashboard decision grants approval.
- After delegating a CMA client-send continuation to Admin, do not rely only on the subagent's narrative status. Immediately re-read `agent_bus(action='list_approvals')` and the matching task record because the approval may have been resolved while the worker was running. If the approval is reconciled as approved/human-sent, complete the blocked task as human-sent/no automated resend and report that Elevate did not resend.
- Board stage/checklist should not be advanced just because an approval was staged. For CMA Stage 1, `client_yes_to_listing` remains missing until the client actually says yes.

## Verification checklist

- Matching deal confirmed from `deals_overview` or `elevate_db`.
- Recipient email(s) verified from contacts/deal_contacts, with no email-blocking flags.
- Selected PDF exists, is non-empty, and passes basic PDF health checks.
- Approval created or existing matching approval verified on Admin dashboard; status recorded.
- Blocked follow-up task created or existing blocked task verified and references the approval ID.
- Proof or continuation proof file written and attached to the deal.
- Final answer says no email was sent and lists any blocker.
