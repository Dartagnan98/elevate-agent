---
name: photo-cleanup
description: "Bulk-clean, order, and name listing photos into a listing-ready export. Use when MLC is signed and photos exist, or when the realtor says 'clean up the listing photos', 'sort the photos for [address]', or 'prep the photo set'. Pulls from the configured Drive/Dropbox, de-dupes and labels hero/exterior/interior/detail, and keeps originals untouched. Final photo approval stays human; missing source, provider, or listing identity returns waiting_human."
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

## Required Configuration

- Source folder: Google Drive, Dropbox, local folder, or another storage provider.
- Processing provider: configured image tool, Nano Banana, Higgsfield, manual editor, or no-op organizer.
- Export destination for listing-ready photos.
- Naming/order convention.

## Flow

1. Confirm signed MLC and match the deal.
2. Find the source photo folder.
3. De-duplicate, sort, and identify hero/exterior/interior/detail photos.
4. Process only with the configured provider and keep originals untouched.
5. Export a listing-ready set with clear names and a manifest.
6. Create a human approval prompt with before/after location and any questionable edits.

## Rules

- Photo cleanup starts after signed MLC.
- Never overwrite original photos.
- Do not mark final photo approval complete. Human approval is required.
- If the provider is not configured, organize and manifest what exists, then ask for the provider/approval.

## Output Contract

```json
{
  "workflow": "photo-cleanup",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "source_folder": "",
  "export_folder": "",
  "manifest_path": "",
  "photo_count": 0,
  "approval_required": true,
  "risks": []
}
```
