---
name: marketing
description: Listing marketing workflow for live listings. Creates launch assets, seller-facing drafts, and marketing tasks only after listing-live inputs exist.
metadata:
  elevate:
    tags: [real-estate, marketing, listing-live]
    runtime:
      approval_required: true
---

# Listing Marketing

Use once the listing is live or approved for launch.

Require address, MLS number, live date, price, approved photos, and open-house/signage inputs before creating assets. Create drafts/tasks for social posts, email blasts, listing updates, and seller communications.

Never post or send directly. Missing launch inputs should produce `waiting_human` with the exact required fields.
