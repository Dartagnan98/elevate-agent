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
