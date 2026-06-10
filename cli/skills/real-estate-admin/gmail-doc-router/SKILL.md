---
name: gmail-doc-router
description: Cron skill for routing inbound email attachments to the correct deal file. Matches documents, attaches PDFs, and creates review tasks without sending messages.
metadata:
  elevate:
    tags: [real-estate, email, documents, cron]
    runtime:
      cron: true
      result_writer: admin-result-writer
---

# Gmail Doc Router

Use as a background cron skill for inbound document cleanup.

Scan recent Gmail or Outlook attachments through the connected email provider. Use `deal-matcher` before attaching anything. Route matched PDFs to the deal file, create document review tasks when confidence is low, and close through `admin-result-writer`.

Do not send email. Do not attach to a deal when MLS/address/contact verifiers conflict.

## Required Configuration

Read these from onboarding/profile settings, not hardcoded paths:

- Email provider: Gmail, Outlook, or another connected inbox.
- Storage provider: Drive, Dropbox, local folder, or compliance portal.
- Deal source: the operational store (per-account embedded Postgres, via `admin_deal` / the data layer).
- Document source rules: known senders, allowed file types, signature-image filters, and duplicate policy.
- Admin approval lane for unmatched or ambiguous docs.

If the inbox, storage provider, or deal database is not configured, close as `waiting_human` with the missing account names.

## Flow

1. Search recent inbox messages with attachments. Default lookback is 7 days for cron, or the requested backfill window for manual runs.
2. Skip newsletters, social/promotional mail, inline signature images, calendar files, and tiny image assets.
3. Extract identifiers from subject, sender, body snippet, attachment names, and PDF text when available.
4. Call `deal-matcher` with MLS, address, email, phone, sender, portal transaction ID, and any attachment metadata.
5. If matched, attach the document artifact to the deal and create review tasks for documents that need human inspection.
6. If unmatched, write an unmatched-doc task with sender, subject, attachment names, and suggested deal candidates.
7. Close through `admin-result-writer`.

## Duplicate Rules

- Do not create duplicate artifacts for the same message ID, attachment ID, provider file ID, or checksum.
- If the same file arrives again with a better match, update the existing artifact's deal link only after human confirmation.
- Never delete the source email or source file.

## Output Contract

```json
{
  "status": "succeeded|waiting_human|failed|skipped",
  "scanned": 0,
  "attached": [],
  "unmatched": [],
  "duplicates": [],
  "human_prompt": null
}
```

For each attached file, include the matched `deal_id`, artifact kind, source message ID, destination path or provider file ID, and the match fields used.
