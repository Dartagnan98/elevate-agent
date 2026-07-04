---
name: paid-ads-gmail-lead-import
description: Import Gmail paid-ad lead notifications into a separate, no-outreach Paid Ads source lane. Use when the user wants paid-ad leads (especially Making It Rain / CampaignConnect) imported into the Leads dashboard separately from Lofty/CRM/message sources, needs Paid Ads leads deduped/synced into Lofty, or is recovering approved Paid Ads drafts that never sent.
triggers:
  - paid ad leads
  - Making It Rain lead emails
  - campaignconnect.ai
  - import leads from email
  - Paid Ads source
  - lead program lookup
category: real-estate
---

## Purpose

Create or maintain an automation that watches Gmail for paid-ad lead notifications and imports them into the `/leads` **Paid Ads** source lane without sending, approving, or auto-drafting outreach.

The realtor specifically wants paid-ad leads kept separate from Lofty CRM, Apple Messages, Gmail/social conversations, and other organic lead sources.

## Hard rules

- Do **not** send outreach automatically.
- Do **not** approve or queue messages automatically.
- Do **not** expose raw source/campaign labels in client-facing copy.
- If the notification email does not clearly identify the ad/listing/program, import the lead anyway and mark/store internal program-lookup metadata.
- Keep the lead visible under the **Paid Ads** source/filter in Leads.
- Paid Ads / Making It Rain leads should also be verified against Lofty CRM by email before outreach work: if an exact email match already exists, use Lofty's `firstName` / `lastName` as the display name in the Paid Ads source row and record the Lofty lead id; if no exact match exists and a valid email is present, create the Lofty lead with source `Making It Rain paid ads` and tags such as `Paid Ads` / `Making It Rain`. Do **not** create a Lofty lead from a parsed phone alone unless the phone is verified from the dashboard/contact page, because Making It Rain notification parsing can mistake program/order IDs for phone numbers.
- Normalize Paid Ads display names before drafting or showing them: strip trailing digits from email-handle fallbacks, split obvious compact first/last handles when safe, prefer Lofty first/last names when available, and fall back to `there` in greetings rather than exposing ugly handles like `Randy55Kemp`, `Williamcarpenter77`, or `chrisolsenmail`.
- Create approval-gated draft tasks for imported Paid Ads leads after CRM storage is checked. Dedupe drafts by person/email so one person does not get multiple drafts from repeated notification emails. Drafts stay pending; never auto-send or mark touched.
- Dashboard send-forensics gotcha: `paid-ads` is import-only and is not mapped to an outbound sender channel in `_SOURCE_TO_CHANNEL`. A Paid Ads `ui-state.json` task with `status: approved` does **not** prove a message sent. Always verify a matching `send_queue` row with `sent` status/provider id. If the user wants approved Paid Ads drafts to actually send, first convert them into real outbound `send_queue` rows with valid recipient email/phone, then send only after approval.
- Recovery pattern for Paid Ads approvals that looked approved but did not send:
  1. Identify approved source-only tasks in `/Users/admin/.elevate/tools/data/sources/paid-ads/ui-state.json` and confirm there is no matching `send_queue` row/provider id.
  2. Resolve the intended outbound channel from the user's ask. If texts are wanted, use the Making It Rain notification email's **labeled** `Phone number` field, not Lofty-only and not a broad 10-digit scan. The importer helper should parse only the bounded segment after `Phone number` / `Phone` / `Mobile` and before the next known field label, because order/program ids in the same email are phone-shaped. If email is wanted, resolve valid email from `contacts.jsonl` using the original `gmail_message_id`.
  3. Archive the old source-only/local task rows and stale `ui-state` approvals so they do not remain as false positives.
  4. Insert a real `send_queue` row with `source_id='paid-ads'`, `status='pending_approval'`, the cleaned draft text, and the chosen real send channel: `channel='sms'` with `payload_json.recipient.phone` for text approvals, or `channel='email'` with `payload_json.recipient.email` for email approvals.
  5. Add a matching `message_draft` row in `tasks.jsonl` with the same `task_id`, matching `channel` (`SMS` or `Email`), the matching recipient field (`recipient_phone` or `recipient_email`), and `linked_send_queue_id`, then run `walk_jsonl_source` migration.
  6. Verify both: the dashboard/source inbox shows the remade drafts as pending with the correct channel, and `send_queue` has the same count with the chosen `channel` and `status='pending_approval'`. Do not approve/send them yourself unless the user explicitly asks.

## Current installed paths in this environment

- Paid Ads source root:
  `/Users/admin/.elevate/tools/data/sources/paid-ads`
- Making It Rain Gmail importer:
  `/Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/import_making_it_rain_gmail.py`
- Manual paid-ads CSV importer:
  `/Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/import_paid_ads_csv.py`
- Cron wrapper:
  `/Users/admin/.elevate/scripts/making_it_rain_paid_ads_import.sh`
- Cron job installed during 2026-06-23 work:
  `a9b2216263d8`, name `Making It Rain paid ads lead import`, schedule `every 10m`, `no_agent=true`.

## Implementation pattern

1. **Create/verify the Paid Ads source connector**
   - Source id: `paid-ads`
   - Label: `Paid Ads`
   - Category: `leads`
   - Owner agent: `Outreach`
   - UI surfaces: `Leads`, `Outreach`, `Today`, `Approvals`
   - Source metadata should be in:
     - `source.json`
     - `status.json`
   - Set it as connected/import-only:
     - `connected: true`
     - `import_only: true`
     - `sync_mode: import_only`

2. **Read Gmail lead notifications with `gws`**
   - Use local CLI, not browser/API ad hoc calls:
     ```bash
     gws gmail users messages list \
       --params '{"userId":"me","q":"from:makingitrain@makingitrain.campaignconnect.ai newer_than:30d -in:trash","maxResults":50}' \
       --format json
     ```
   - Fetch messages with:
     ```bash
     gws gmail users messages get \
       --params '{"userId":"me","id":"MESSAGE_ID","format":"full"}' \
       --format json
     ```
   - If `gws` fails with token-cache/decryption/auth errors, do not fake success. Mark status blocked/needs reauth and surface that Gmail auth needs repair.

3. **Parse lead fields defensively**
   - Extract from plaintext and HTML MIME parts.
   - Handle labels like `Name`, `Full Name`, `Email`, `Phone`, `Mobile`, `Program`, `Campaign`, `Ad Set`, `Ad`, `Listing`, `Property`, `City`, `Message`, `Comments`, `Notes`.
   - Extract links from HTML `href=` plus visible URLs.
   - For Making It Rain/CampaignConnect, notification emails may not clearly name the exact program if multiple listing promotion ads are running. Store:
     - `program: Needs program lookup`
     - `program_lookup_required: true`
     - `program_lookup_url` when present
   - Keep campaign/program data internal only.

4. **Write source JSONL records**
   - Update these files under `paid-ads/`:
     - `contacts.jsonl`
     - `conversations.jsonl`
     - `messages.jsonl`
     - `lead-events.jsonl`
     - `tasks.jsonl` only if approval/task rows should truly appear.
   - For paid-ad imports, prefer **no source tasks** by default because `/leads` treats source tasks as draft/approval cards.
   - Put program lookup metadata on the conversation and lead-event records instead.

5. **Important Gmail threading pitfall**
   - Gmail can thread many Making It Rain notifications together.
   - Do **not** use Gmail `threadId` as the Paid Ads conversation key unless you want many distinct leads collapsed into one card.
   - Use the Gmail **message id** as the Paid Ads source thread key:
     ```python
     conv_id = f"making-it-rain-thread:{gmail_message_id}"
     ```

6. **Migrate JSONL into operational DB**
   - The DB-primary Leads dashboard uses operational DB rows.
   - Use `walk_jsonl_source` with a `BackfillStats` instance. Newer Elevate versions require `stats=` explicitly:
     ```python
     from pathlib import Path
     from elevate_cli.data import connect
     from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source

     stats = BackfillStats()
     with connect() as conn:
         walk_jsonl_source(
             Path('/Users/admin/.elevate/tools/data/sources/paid-ads'),
             conn=conn,
             stats=stats,
             limit=50000,
             dry_run=False,
         )
         conn.commit()
     print(stats.to_dict())
     ```

7. **Suppress generic fallback outreach drafts**
   - DB inbox/draft helpers can synthesize generic fallback drafts from source threads.
   - For Paid Ads imports, suppress generic fallback drafts until context/program is reviewed.
   - Write `ui-state.json` task statuses for generated `thread-draft:{thread_id}` as `archived`.
   - Do not create `tasks.jsonl` `program_lookup` rows unless the user explicitly wants those displayed as approval/draft-like cards.

8. **Sync Paid Ads leads into Lofty and create approval drafts when requested**
   - When the user asks for Making It Rain / Paid Ads leads to be stored in Lofty, dedupe imported paid-ad contacts by valid email first. Do not create one Lofty lead per repeated notification email.
   - Check Lofty by exact email before creating. If found, write the Lofty lead id back to the Paid Ads JSONL row using an explicit identity such as `{"kind":"lofty_id","value":"<lead_id>"}` and migrate the source rows again.
   - If no exact Lofty match exists and the Paid Ads contact has a valid email, create the Lofty lead with source `Making It Rain paid ads`, stage `New Leads`, and tags such as `Paid Ads` / `Making It Rain`; add broad tags like `Buyer Lead` or `Listing Lead` only when the program type is clear.
   - Do **not** create Lofty leads from the parsed `phone` field unless it has been verified from the Making It Rain dashboard/contact page. The notification email parser can mistake program/order ids for phone numbers. In a past run, repeated false-phone prefixes included values like `3887442763`, `3789023234`, and `3949808947`; treat repeated phone values across many unrelated contacts as parser artifacts and scrub them before DB migration.
   - When the user asks for drafts for all Paid Ads leads, create one pending approval `message_draft` per unique person/email, not one per duplicate notification. Leave `status: pending`; never send, approve, or mark the lead touched.
   - If older listing-specific SMS draft rows are present, `build_source_inbox_response()` may hide some of them when the matching conversation thread is not visible. Create replacement `paid-ads-first-touch:<email_hash>` draft rows for those unique emails if needed, then archive duplicate pending rows so the visible inbox has exactly one pending draft per unique email.
   - Use conservative first-touch wording for broad Paid Ads programs unless the exact listing and listing status are verified. Keep raw campaign/program labels and postal codes out of client-facing copy.
   - After drafting, verify all three counts: unique valid-email Paid Ads contacts, unique contacts with Lofty ids, and visible pending Paid Ads drafts. The acceptance target is `lofty_synced_unique_emails == unique_valid_email_contacts`, `missing_draft_emails == 0`, `duplicate_pending_email_count == 0`, and `postal_remaining == 0`.

9. **Schedule the watcher**
   - Use a `no_agent=true` cron with a shell wrapper.
   - Recommended wrapper shape:
     ```bash
     #!/usr/bin/env bash
     set -euo pipefail
     cd /Users/admin/Elevation
     exec /Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 \
       /Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/import_making_it_rain_gmail.py \
       --limit 50 \
       --lookback 30d
     ```
   - `no_agent=true` should print nothing when no new leads are imported, so the user is not pinged every run.
   - On auth/script failure, non-zero exit should alert.

## Verification checklist

Run these checks after changes:

```bash
/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 -m py_compile \
  /Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/import_making_it_rain_gmail.py
```

Run one import/check:

```bash
/Users/admin/.elevate/scripts/making_it_rain_paid_ads_import.sh
```

Verify source status/counts:

```bash
/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 - <<'PY'
import json
from pathlib import Path
from elevate_cli.data import db_source_inbox_response
status=json.loads(Path('/Users/admin/.elevate/tools/data/sources/paid-ads/status.json').read_text())
r=db_source_inbox_response(limit=5000)
print({
  'status_counts': status.get('counts'),
  'paid_threads': sum(1 for t in r['threads'] if t.get('sourceId')=='paid-ads'),
  'paid_drafts': sum(1 for d in r['drafts'] if d.get('sourceId')=='paid-ads'),
})
PY
```

Expected safe result:
- `paid_threads` increases for imported leads.
- `paid_drafts` remains `0` unless explicit human-approved drafting was requested.
- `status_counts.contacts/conversations/messages/lead_events` reflect imports.
- No sends, approvals, or queued outreach are created.

## Program lookup extension

If the user wants exact program matching from Making It Rain/CampaignConnect links:

1. Use the stored `program_lookup_url` from the lead event/conversation.
2. Open/log in with local/free Browser Use CLI through `terminal` only.
3. Find the matching lead/program/listing promotion.
4. Write the verified program internally on the Paid Ads event/conversation.
5. Do not expose the campaign/program name in client-facing outreach unless the user explicitly says to.

Installed support files from a past Making It Rain workflow build-out:

- Program mapping file:
  `/Users/admin/.elevate/tools/data/sources/paid-ads/program_mappings.json`
  - Keyed by Making It Rain `program_id`.
  - Use fields like `program_name`, `program_type`, `listing_address`, `city`, `source`, `lookup_url`, `updated_at`.
  - A `listing_address` is required before listing-specific draft copy is created.
- Browser Use lookup helper:
  `/Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/lookup_making_it_rain_programs_browser_use.py`
  - Uses local `browser-use` CLI with `--session mir --profile=Default`.
  - Opens direct URLs like `https://mirdashboard.exprealty.com#/architecture/{architecture_id}/programs/{program_id}`.
  - If Okta login/password appears, it records `needs_login: true` in `making-it-rain-program-lookup-state.json` and exits safely.
  - Do not claim program lookup is working until the user has completed the one-time Making It Rain/Okta login in that local browser profile.
- Cron wrapper should run lookup best-effort before import:
  `/Users/admin/.elevate/scripts/making_it_rain_paid_ads_import.sh`
  - Run lookup with `|| true`, then run Gmail import, so a login blocker does not stop new lead ingestion.

### Listing-promotion draft rule

When the verified Making It Rain program is one of the user's listing-promotion programs **and** an exact listing address is known, create an approval-gated `message_draft` task only, never send automatically. Use the user's requested feedback framing:

```text
Hi {first_name} ! Noticed you viewed our listing at {address}. I am always eager to hear feedback that could help the seller find the perfect buyer. Do you feel like the list price is off, or are there missing pieces of information that would be helpful ?
```

Keep the draft pending approval. Do not create this listing-specific draft from a vague campaign name alone. If the address is missing, import the lead and keep `program_lookup_required: true` instead.

## Lessons learned

- `gws` may be available even when a setup-check script is not used, but auth can fail with keyring/decryption errors. Test a harmless Gmail list call first.
- Making It Rain email subjects can carry the visible program name, e.g. `New Lead Submitted for "KC - Buyer Leads From Listings"`. Parse this subject text before falling back to `Needs program lookup`.
- Extract `program_id`, `architecture_id`, and `mir_contact_id` from unquoted `mirdashboard.exprealty.com#/architecture/.../programs/...` and dashboard contact URLs. AWS/Suprsend tracking links may contain the same direct URLs percent-encoded.
- DB source inbox is DB-primary, so JSONL-only writes may not show until migrated via `walk_jsonl_source`.
- `walk_jsonl_source` requires `BackfillStats` in current Elevate builds.
- Gmail `threadId` collapses multiple ad leads into one card. Use Gmail message id for lead-level conversation keys.
- Source `tasks.jsonl` records surface as draft/approval cards. Do not use them for internal program lookup unless that UI behavior is desired. Use `lead-events.jsonl` and mapping metadata for internal lookup state.
- If old rows were imported before program id parsing was added, run a one-off repair over `lead-events.jsonl`/`contacts.jsonl`/`conversations.jsonl`/`messages.jsonl` to backfill `program`, `program_id`, `architecture_id`, and `program_lookup_required` from subject/link fields before using Browser Use lookup.
- Making It Rain Okta login uses the realtor's exp realty email address. Do not store or print the password in the skill/memory/logs; use credentials only from the active user turn or secure credential file.
- Program links inside notification emails can be permission-scoped/stale and may show `You don't have permission to view program with ID ...` after successful Okta login. When this happens, open the lead detail/contact URL from the same email, then follow the visible **Source Program** link. That link resolves to the account-accessible `#/architecture/<resolved_architecture>/programs/<resolved_program>` URL.
- Do not treat `KC - Buyer Leads From Listings` as a listing-specific program. It is a broad buyer-lead program, so import the lead and do not create the listing-feedback draft.
- For `Listing eXposure - Custom Listing` / copy programs, the page may not expose the listing address in DOM text. Use local Browser Use screenshots/visual review of the ad preview plus active Admin listing context to verify the exact listing before saving `program_mappings.json`. In one past run, the listing eXposure programs were verified/mapped to a specific unit address; do not generalize this mapping to future unrelated programs unless the program id matches the saved mapping.
- Distinguish verification levels before writing lead-specific language: raw Making It Rain notification emails may prove only program/order attribution; a saved `program_mappings.json` entry proves the program-to-listing mapping; only the live lead detail/dashboard can prove an individual lead viewed a specific property. If live Browser Use verification is blocked by Okta/login, report the blocker and avoid overstating individual behaviour in drafts.
- When the user is actively working through wording/strategy, do not harden those draft experiments into this skill or importer logic unless they explicitly ask to save/update the skill. It is okay to edit the current pending draft rows as a working version, but keep reusable skill rules separate until approved.
- Imported display names may initially fall back to email handles like `Randy55Kemp` or `chrisolsenmail`. Before creating client-facing drafts, use the Making It Rain lead table/contact page names when available, and sanitize greetings to a human first name or `there` rather than using ugly email handles.
- If the user says only one Making It Rain program's leads are visible, run a full Gmail-backlog import rather than only the default cron window: `/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12 /Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/import_making_it_rain_gmail.py --limit 500 --lookback 6m` after a dry-run check. A dry run may show `found: 458` and `new_to_process: 0`; that still proves the full backlog is already present and the real run can still apply saved program mappings / migration refresh. This imports every paid-program notification found in Gmail into the Paid Ads source, then migrates to the operational DB.
- For verification, prefer `elevate_cli.data.db_source_inbox_response(limit=5000)` over the legacy `build_source_inbox_response(limit=5000)`. Current app-bundle `SOURCE_CONNECTION_BLUEPRINTS` may not list `paid-ads`, so the legacy JSONL source list can show `paid_ads: 0` even though DB-primary `/leads/source` has the Paid Ads threads. Count `sourceId == 'paid-ads'` inside `db_source_inbox_response()['threads']` and confirm `conversations.source_id='paid-ads'` in Postgres. It is normal for `sources` metadata to omit a friendly Paid Ads connector label while the actual source inbox threads are present.
- Do not use `leads_overview.pendingBySource` to verify Paid Ads source-inbox visibility. That overview reports outreach/send-queue pending approvals, so it can show only `apple-messages` or `crm` even when hundreds of `paid-ads` source inbox threads exist. Verify Paid Ads import with JSONL file counts, `conversations where source_id='paid-ads'`, `db_source_inbox_response()['threads']`, and explicit `send_queue` / `outreach_send_queue` zero-count checks for safety.
- The importer's `status.json` `counts` can lag after `refresh_existing_rows_from_program_mappings()` creates additional pending listing drafts because `update_status()` may use the pre-refresh `result['counts']`. When reporting final counts, read the JSONL files directly and query DB conversations/send queues, do not rely only on `status.json`.
- The program lookup helper uses Browser Use session `mir`, not arbitrary ad-hoc sessions. If it reports `needs_login: true` while another Browser Use session is logged in, log into Making It Rain in session `mir` using local/free Browser Use CLI, then rerun `/Users/admin/.elevate/tools/data/sources/paid-ads/artifacts/lookup_making_it_rain_programs_browser_use.py --limit 50`. After lookup, call `refresh_existing_rows_from_program_mappings(dry_run=False)` and rerun DB migration so existing rows get better program/listing metadata.
- Cron timeout repair pattern from a past run: job `a9b2216263d8` runs under the scheduler's 120s script cap, so the wrapper must never run Browser Use enrichment before Gmail import. Keep `/Users/admin/.elevate/scripts/making_it_rain_paid_ads_import.sh` ordered as source-of-truth Gmail import first, bounded to about 85s, then best-effort Making It Rain program lookup second, bounded to about 25s and limited to a tiny batch. If `making-it-rain-program-lookup-state.json` has recent `needs_login: true`, skip lookup for a cooldown window instead of repeatedly opening the portal. The import should fail loudly only when Gmail/GWS/import/DB migration fails; browser lookup timeout/login should be logged to `making-it-rain-cron-run.log` and must not prevent paid-ad leads from entering the pipeline.
