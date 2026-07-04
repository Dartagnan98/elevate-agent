---
name: property-memory-reset
description: "Erase recalled memory for one property address and, only if asked, its workflow artifacts. Use when the realtor says to forget, erase memory, or reset a property workflow for a specific address, or adds \"and anything you added to our systems from that workflow.\""
---

# Property Memory / Workflow Reset

Use when the realtor asks to erase memory, forget, reset, remove a property workflow, or restart fresh with a specific property address.

## Goal

Clear property-specific recalled memory and local workflow traces without accidentally deleting broad workflow preferences or unrelated client/contact history.

Important distinction:
- **Memory reset only** = remove recalled facts/context about the property.
- **Operational cleanup** = remove dashboard/deal data, run artifacts, drafts, contact properties, send logs, and local files added by the workflow.

If the realtor says something like “remove this from your memory **and anything you added to our systems from that workflow**,” treat that as approval to clean property-specific operational artifacts too. Do **not** delete the underlying person/contact/client record unless it was created solely by that workflow or the realtor explicitly asks.

## Steps

1. Normalize address/search variants.
   - Include street number, joined/spaced street names, alternate casing, slug forms, and client/email if known.
   - Example for `450 Main Street`: search `450`, `Main`, `450-main`, and `450 Main Street`.

2. Search durable fact memory first.
   - Use `fact_store(action="search")` with the address variants.
   - Use `fact_store(action="probe")` for the full address/entity if useful.
   - Remove only fact IDs whose content/tags explicitly name the property or workflow-specific contact/property artifact.
   - Do **not** remove broad workflow preferences/rules just because semantic search returns them.
   - Verify with another `fact_store(action="search")` using the property/address variants.

3. Search session recall for context before deleting operational data.
   - Use `session_search` for address variants if the cleanup scope is unclear.
   - Session transcripts/logs are historical audit records. Do not try to purge all transcripts unless the realtor explicitly asks for transcript/log deletion.

4. Search local filesystem artifacts created by the workflow.
   - Use `search_files`, not shell `find/grep`.
   - Common locations:
     - `<project-tools-dir>/data/listings/<property-slug>/...`
     - `<project-tools-dir>/tmp/`
     - `/Users/admin/.elevate/cache/documents/<property-slug>/...`
     - `/Users/admin/.elevate/cache/outbox/*<property-slug>*`
     - `/Users/admin/.elevate/cache/documents/skyslope-<property-slug>-delete-check/` or other one-off portal/debug folders
     - `/tmp/elevate-admin-artifacts/<deal_id>/`
     - `/tmp/*<deal_id>*`
     - `/Users/admin/.elevate/cron/output/<job_id>/`
   - Remove only property-specific folders/scripts/artifacts after confirming they are workflow outputs, not source files.
   - Use `terminal` only for the actual `rm -rf` after exact paths are identified, then verify each path no longer exists.
   - Preserve unrelated accounting/rental/business-address records that share the same property address unless the realtor explicitly asks to remove those too.

5. Check operational Admin data through Postgres-backed tools only.
   - The operational source of truth is embedded Postgres exposed by `deals_overview` and `elevate_db`.
   - Do **not** use sqlite paths or `sqlite3` for Admin data.
   - Use `deals_overview` first for broad dashboard/pipeline lookup.
   - Use `elevate_db(action="query")` for exact matches in:
     - `deals`
     - `deal_contacts`
     - `deal_attachments`
     - `deal_events`
     - `admin_action_runs` joined to `admin_action_registry` if accessible
   - Query by exact deal IDs from discovered artifacts/logs and by `title` / `listing_address` variants.

6. Remove or archive operational records according to the user’s wording.
   - If the user only asks to “forget” or “remove from memory,” report any operational records found and ask one clear follow-up before changing them.
   - If the user explicitly asks to remove “anything added to our systems from that workflow,” clean workflow-specific operational records as allowed by available curated write APIs.
   - If the cleanup request targets an active Admin card/deal created solely by the workflow, remove its dependent rows first (`admin_action_runs`, `deal_attachments`, `deal_events`, `deal_contacts`), then the `deals` row, then verify all counts are zero. If the normal `elevate_db` tool only exposes read-only queries and no suitable curated delete exists, use the local `elevate_cli.data.connection.connect` transaction helper from the trusted Elevate CLI environment rather than sqlite or filesystem DB hunting.
   - For workflow-created local contact rows, delete only the exact row created by the workflow, keyed by the discovered `contact_id` / `source_key` / deal linkage. Preserve other rows for the same person/email that predate or are unrelated to the workflow.
   - Prefer reversible archive/status changes for active dashboard cards unless the user says delete/remove anything added by the workflow.
   - If exact workflow deal records are already absent, verify counts for `deals`, `deal_contacts`, `deal_events`, `deal_attachments`, and action runs are zero and report that.

7. Roll back external-system properties added by the workflow.
   - Mailjet: if the workflow added a contact property such as `seller_names`, use Mailjet contactdata endpoints to inspect and remove only that property while preserving pre-existing fields.
     - `GET contact?Email=<email>` to get contact ID.
     - `GET contactdata/<contact_id>` to inspect properties.
     - `PUT contactdata/<contact_id>` with the preserved prior properties, omitting the workflow-added property.
     - Verify with another `GET contactdata/<contact_id>`.
   - If Mailjet contactdata has no workflow-specific property, leave the contact unchanged and report that nothing needed rollback there.
   - Do **not** delete the Mailjet contact, Lofty contact, CRM lead, or historical client record unless the realtor explicitly asks and it was not pre-existing.
   - Campaigns/transactional sends that already went out cannot be unsent. Remove drafts/scheduled sends only if they are workflow-specific and unsent.

8. Clean source/staging records only when they were created solely by the workflow.
   - Check active CRM source/staging files for exact workflow identifiers, for example Lofty lead ID, property address, property slug, and notes like `Pre-CMA test workflow`.
   - Common files:
     - `/Users/admin/.elevate/tools/data/sources/crm/tasks.jsonl`
     - `/Users/admin/.elevate/tools/data/sources/crm/lead-events.jsonl`
     - `/Users/admin/.elevate/tools/data/sources/crm/contacts.jsonl`
     - `/Users/admin/.elevate/tools/data/sources/crm/conversations.jsonl`
     - `/Users/admin/.elevate/tools/data/sources/crm/artifacts/enrichment_progress.json`
     - old `.bak-before-*cleanup` backups if they contain the exact workflow-created record
   - Remove only exact JSONL lines / JSON objects tied to the workflow-created lead/contact. Do not strip unrelated source CRM, Gmail, QuickBooks, rental, or accounting records that merely mention the same address.

9. Cron/admin run cleanup.
   - Use `cronjob(action="list")` to find active/scheduled jobs. Remove only one-off property-specific jobs still present.
   - Remove stale local cron output folders for one-off property-specific job IDs only after the jobs are no longer active.
   - Do not remove recurring global watchers.

10. Remove property-specific references from procedural skill memory when appropriate.
   - Sometimes a workflow run leaves a reusable lesson in a skill file (for example CMA/MFA/headless automation notes) that names the property used for the test.
   - If the lesson itself is still valuable, generalize the address/client wording instead of deleting the lesson.
   - Verify the active skill directory no longer contains the property variants, while preserving the general procedure.

11. Verification checklist before reporting done.
   - `fact_store` search for property variants returns no explicit active property fact.
   - Listing data/tmp folders for the property are gone or intentionally preserved.
   - Operational Admin queries return no active/property-specific deal records or action traces left within the requested cleanup scope.
   - External contact properties added by the workflow are removed and verified or confirmed absent.
   - Cron job list has no remaining active one-off jobs for the property.
   - Source/staging files and procedural skill memory have no remaining exact workflow-created record/property references, except unrelated accounting/rental/business/source history intentionally preserved.

## Reporting template

Report briefly:

- Durable memory facts removed or confirmed absent.
- Local artifact folders/scripts removed.
- Operational Admin database verification result.
- External-system rollback result, for example Mailjet property removed.
- Anything intentionally not deleted, for example pre-existing client/contact records or historical transcripts/logs.

## Pitfalls

- Semantic memory search returns broad workflow rules. Do not delete generic CMA, Pre-CMA, Mailjet, Lofty, Matrix, Marketing Go, or dashboard rules unless they explicitly name the property.
- A property workflow reset is not the same as deleting the client from Lofty/Mailjet/CRM.
- Do not purge logs/session transcripts as part of normal cleanup. They are audit history unless the user explicitly asks to delete historical logs/transcripts too.
- Do not use outdated sqlite/operational.db instructions. Admin data is Postgres-backed and reachable through `deals_overview` / `elevate_db`.
- If a workflow sent an email, it cannot be unsent. Only remove artifacts, drafts/scheduled unsent items, and added personalization/contact properties.