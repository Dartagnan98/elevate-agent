---
name: seller-package
description: Draft the pre-appointment seller package email after a listing appointment is booked. Creates a draft or approval task; never sends without human approval.
metadata:
  elevate:
    tags: [real-estate, seller, email, pre-listing]
    runtime:
      approval_required: true
---

# Seller Package

Use after a seller appointment is booked and before the Admin listing pipeline starts.

Draft the seller package email using the realtor profile, brokerage details, appointment context, property address if known, and any local/regional memory. Create a Gmail/Outlook draft or a human approval task. Do not send directly.

If deal context exists, keep the `deal_id` and close with `admin-result-writer`. If key context is missing, request only the missing items needed to draft safely.
