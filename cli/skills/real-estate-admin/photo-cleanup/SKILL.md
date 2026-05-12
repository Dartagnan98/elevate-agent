---
name: photo-cleanup
description: Bulk listing photo cleanup after signed MLC. Uses the configured Drive/Dropbox source and configured image-processing provider, then prepares a listing-ready export for human approval.
metadata:
  elevate:
    tags: [real-estate, photos, listing]
    runtime:
      approval_required: true
---

# Photo Cleanup

Use after MLC is signed and listing photos exist in the configured Drive, Dropbox, or storage folder.

Match the deal, collect the source photo folder, clean/order/name images with the configured provider or manual workflow, and export a listing-ready set. Mark photo checklist items only after outputs exist.

Final photo approval remains human. If source folder, provider, or listing identity is missing, return `waiting_human`.
