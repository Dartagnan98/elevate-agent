---
name: seller-update
description: Cron skill for active listing updates. Pulls showing feedback/activity, writes a digest to the deal, and creates a seller-update email draft. Never sends directly.
metadata:
  elevate:
    tags: [real-estate, seller-update, showing-feedback, cron]
    runtime:
      cron: true
      approval_required: true
---

# Seller Update

Use for active listings after the listing is live.

Pull showing feedback and listing activity from the configured showing platform/browser workflow. Match each listing to a deal with MLS number first, then address and contact verifiers. Write the digest to SQLite and create a seller-update Gmail/Outlook draft.

Never send directly. If listing identity, MLS number, showing-platform access, or email draft access is missing, close as `waiting_human`.
