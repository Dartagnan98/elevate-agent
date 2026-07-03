---
name: gmail-doc-router
description: "Route inbound email attachments to the correct deal file. Use when a background cron sweeps recent Gmail/Outlook attachments, or the realtor says 'file the docs from my inbox' or 'sort these attachments into deals'. Runs deal-matcher, attaches matched PDFs, and creates review tasks; low-confidence or conflicting matches become an unmatched-doc task, never a guess. Never sends email."
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

## Query Building

- Unit-address rule: for unit-style titles like `<unit>-<civic> <street>`, address-backed Gmail queries must use the BASE civic phrase ("450 Main Street", not "12-450 Main Street") — the unit prefix breaks matching.
- Deals with a blank `listingAddress` but the address in the deal TITLE must still be included in address-backed scans.
- Deals with a canonical `subjectRemovalDate` belong in subject-removal scans even when their stage is unusual.
- A single street token matching boilerplate/thread text produces cross-deal false positives — verify the full civic phrase before treating a hit as a match.
- Senders vary wildly (assistants send "Please see attached signed subject removals") — never limit searches to "Signed MLC"/"Envelope completed" language.
- The user's own self-sent workflow/mockup emails match address terms and must be excluded.

## Duplicate Rules

- Do not create duplicate artifacts for the same message ID, attachment ID, provider file ID, or checksum.
- If the same file arrives again with a better match, update the existing artifact's deal link only after human confirmation.
- Never delete the source email or source file.

## Implementation Notes

- Data-layer shapes: `elevate_cli.data.list_deals` returns camelCase (`currentStage`, `listingAddress`, `mlsNumber`, `extraToggles`) while `elevate_db` SQL rows are snake_case — scan code must not mix them.
- `deal_events.kind` is a closed enum — invented kinds are rejected.
- `admin_deal(action='attach')` is NOT a harmless probe: it creates the attachment row even for a nonexistent `file_path` — verify the file exists first.
- Helper scripts require the app venv interpreter with the CLI on `PYTHONPATH`.
- macOS File-Provider (Drive) PDFs can pass `os.access`+size checks yet fail with `OSError: [Errno 11] Resource deadlock avoided` — materialize/download before reading.
- A corrupted `SSL_CERT_FILE` env makes gws fail with "no native root CA certificates found" — fix the env var; OAuth is fine.
- Image-only scanned letters defeat pdftotext — render + OCR before routing.

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
