---
name: gmail-doc-router-bounded-silent-preflight
description: "Run bounded Gmail trigger searches and decide when an all-seen result is truly [SILENT]. Use whenever a scheduled Gmail document-watcher tick checks for new accepted-offer/listing/Envelope-completed mail, after first-class preflight and inbound_seen dedupe across every unique Gmail ID. Not for the boundary/hours check — use gmail-doc-router-boundary-preflight-guard for that."
metadata:
  elevate:
    tags: [real-estate, admin, gmail, cron, documents]
---

# Gmail Doc Router bounded-scan silent preflight

Use alongside `gmail-doc-router` when a scheduled Gmail document watcher run is checking whether there is anything new to route.

## Trigger

The cron asks to watch Gmail for accepted-offer/listing document emails, route new deal documents, and return `[SILENT]` only if there is genuinely nothing new.

## Procedure

1. Before any terminal, `gws`, browser, helper import, file, or date check, run the first-class preflight tools directly:
   - `composio(status)`
   - `composio(accounts, toolkit='gmail')`
   - `deals_overview()` or `elevate_db(describe)`
2. Treat a revoked Composio Gmail account as a warning, not a blocker, if local `gws` is still authenticated and live Gmail searches work.
3. Run the required bounded Gmail searches with `gws`, including:
   - `subject:"Envelope completed" newer_than:7d has:attachment`
   - accepted-offer subject-removal safety-net terms
   - address-backed subject-removal rows for every active accepted/subject-dated deal.
4. For unit addresses, include both the full unit-civic form and the base civic phrase, for example `4-450 Main Street` plus `450 Main Street`.
5. Parse `gws` output defensively. It may include non-JSON keyring/status text or multiple JSON objects from `--page-all`; use raw JSON object decoding rather than assuming clean single JSON.
6. Deduplicate all Gmail IDs across query rows.
7. Check every unique ID against Postgres `inbound_seen` for `toolkit='gmail-doc-router'` in one query.
8. If every trigger ID is already seen and no scan errors or blockers remain, return exactly `[SILENT]`, with no extra text.

## Do not silence if

- Any bounded search failed or returned unparsable output.
- Any unique Gmail ID is not in `inbound_seen`.
- Address-backed searches were missing for a current active accepted/subject-dated deal.
- A candidate needs full fetch, PDF extraction, deal matching, attachment, task creation, or human review.

## Example of a genuinely clean run

A run scanned portal/envelope, subject-removal, and address-backed rows across several active deals. It found dozens of unique Gmail IDs, all already marked in `inbound_seen` for `gmail-doc-router`, so the correct delivery was exactly `[SILENT]`. Composio Gmail showed `REVOKED`, but local `gws` still worked and the run completed safely without external sends, deletes, uploads, signatures, submits, or marketing actions. A revoked Composio Gmail account alone does not block silence when local `gws` access is verified working.
