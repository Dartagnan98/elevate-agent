---
name: mailjet-send-verification
description: "Verify whether a Mailjet email actually sent, without sending or modifying anything. Use when the realtor asks \"did this email go out\", wants the exact status or timestamp, needs the template/campaign/message ID, or wants send_queue proof for an accepted-offer checklist send."
metadata:
  elevate:
    tags: [real-estate, admin, mailjet, send-verification, send-queue, audit]
    runtime:
      approval_required: false
      writes_deal: false
      result_writer: null
---

# Mailjet Send Verification

Use this to answer: “did this Mailjet email go out?”, “what status did Mailjet return?”, “which template/campaign/message id was used?”, or “verify against Admin/send_queue/Mailjet-visible records.”

This is read-only. Do **not** send, resend, queue, retry, or modify a deal/checklist unless the realtor explicitly asks for that separate action.

## Verification order

1. **Identify the Admin deal and contact.**
   - Start with `deals_overview` when a property/client/deal is named.
   - Confirm with `admin_deal(action='show', deal_id=...)` if needed.
   - Pull contact email/phone from `contacts` or deal contacts when the recipient is named.

2. **Check `send_queue`, but do not stop there.**
   - Query by recipient email, recipient name, deal/property keywords, idempotency key, source/thread/task ids, `payload_json`, template id/name, and terms like `mailjet`, `accepted`, `checklist`.
   - Important pitfall: transactional Admin/Mailjet sends may have **zero matching `send_queue` rows** because the send was executed/recorded directly as Admin proof. Report `send_queue: 0 matching rows` but continue to Admin events/attachments.

3. **Check Admin deal events and attachments.**
   - `deal_events`: search the target `deal_id` for `payload_json`, `new_value_json`, and `field_name` containing `mailjet`, `email`, `accepted`, `checklist`, the recipient email/name, or template id.
   - `deal_attachments`: search the target `deal_id` for kind/path values like `mailjet_sent_proof`, `email_sent_proof`, `mailjet`, `accepted-offer`.
   - Treat `agent_activity` summaries as leads, not sole proof. Prefer the attached proof JSON path when present.

4. **Read the attached proof JSON.**
   - Use `read_file` on the `mailjet_sent_proof` path.
   - Extract and report:
     - `status`
     - `startedAtUtc` / `finishedAtUtc`
     - `recipient`
     - `subject`
     - `templateId`
     - `templateName`
     - campaign/list fields such as `broadListOrCampaignUsed`, `templateLanguageUsed`, campaign id if present
     - `mailjetSend.httpStatus`, `mailjetSend.ok`
     - `mailjetSend.response.Messages[].Status`
     - `CustomID`
     - `MessageUUID`
     - `MessageHref`
     - exact `MessageID`
   - **Mailjet MessageID precision pitfall:** Mailjet MessageID can exceed JavaScript safe integer range. If proof has `messageIDExactFromHref` or `MessageHref`, use that exact string. If the numeric `MessageID` differs from the href/body prefix, say the exact ID is from `messageIDExactFromHref` / `MessageHref`.

5. **Verify template identity carefully.**
   - Buyer accepted-offer checklist template and seller accepted-offer checklist template are usually two distinct Mailjet template IDs on the account; confirm the actual configured IDs rather than assuming.
   - If the realtor asks about an accepted-offer checklist but the side is ambiguous, state which template actually went out instead of assuming seller vs buyer.

6. **Optional Mailjet-visible live check.**
   - Only if local/Admin proof is missing or the realtor specifically asks for live portal/API visibility.
   - Mailjet is online, so this check must go through the account's configured browser-automation path rather than ad hoc curl/HTTP.
   - Live check must be read-only. Search by `MessageUUID`, exact `MessageID` from href, recipient email, and CustomID.

## Useful Postgres query patterns

Use `elevate_db(action='query', sql=...)`; do not use sqlite/psql/filesystem DB hunting.

```sql
-- Recipient/contact discovery
SELECT id, display_name, primary_email, primary_phone, type, stage, created_at, updated_at
FROM contacts
WHERE lower(coalesce(display_name,'')) LIKE '%<name fragment>%'
   OR lower(coalesce(primary_email,'')) LIKE '%<name fragment>%'
ORDER BY updated_at DESC
LIMIT 20;
```

```sql
-- send_queue check, recipient/name/template/property terms
SELECT id, idempotency_key, source_id, thread_id, task_id, channel, status, attempts,
       last_error, provider_message_id, attempt_id, created_at, updated_at,
       left(payload_json, 2500) AS payload_preview
FROM send_queue
WHERE lower(coalesce(payload_json,'')) LIKE '%recipient@example.com%'
   OR lower(coalesce(payload_json,'')) LIKE '%recipient name%'
   OR lower(coalesce(payload_json,'')) LIKE '%mailjet%'
   OR lower(coalesce(payload_json,'')) LIKE '%8056191%'
   OR lower(coalesce(payload_json,'')) LIKE '%8059471%'
   OR lower(coalesce(payload_json,'')) LIKE '%accepted%'
   OR lower(coalesce(payload_json,'')) LIKE '%checklist%'
ORDER BY created_at DESC
LIMIT 100;
```

```sql
-- Admin event proof search
SELECT id, kind, actor, field_name,
       left(coalesce(new_value_json,''),1000) AS new_value,
       left(coalesce(payload_json,''),2500) AS payload,
       created_at
FROM deal_events
WHERE deal_id = '<deal_id>'
  AND (
    lower(coalesce(payload_json,'')) LIKE '%mailjet%'
    OR lower(coalesce(payload_json,'')) LIKE '%email%'
    OR lower(coalesce(payload_json,'')) LIKE '%checklist%'
    OR lower(coalesce(payload_json,'')) LIKE '%accepted%'
    OR lower(coalesce(new_value_json,'')) LIKE '%mailjet%'
    OR lower(coalesce(field_name,'')) LIKE '%email%'
  )
ORDER BY created_at DESC
LIMIT 100;
```

```sql
-- Attached proof files
SELECT id, deal_id, kind, file_path, source_run_id, created_at
FROM deal_attachments
WHERE deal_id = '<deal_id>'
  AND (
    lower(coalesce(kind,'')) LIKE '%mailjet%'
    OR lower(coalesce(file_path,'')) LIKE '%mailjet%'
    OR lower(coalesce(file_path,'')) LIKE '%accepted-offer%'
  )
ORDER BY created_at DESC
LIMIT 50;
```

## Response format

Return concise exact status. Include:

- `Found: Yes/No`
- recipient
- status and timestamp
- subject
- template id/name
- CustomID / campaign id if any
- MessageUUID
- exact MessageID and MessageHref
- source of proof: send_queue row, Admin event id, Admin attachment id/path, or Mailjet-visible lookup
- if `send_queue` has zero rows, explicitly say so
- confirm no send/resend happened

Do not overstate deliverability. A Mailjet `success` send proof means Mailjet accepted/sent the message, not necessarily recipient opened/read it unless open/click tracking records were separately checked.