---
name: real-estate-first-touch-outreach-run
description: "Run the real-estate first-touch outreach cron workflow. Use when a scheduled or manual task asks to \"run outreach,\" \"pull fresh leads,\" or \"create first-touch drafts\": pull fresh inbound leads from CRM/SMS/email/social sources, conservatively qualify real-estate leads, enrich with CRM/property context, and create approval-only drafts without sending or marking touched."
version: 1.0.0
metadata:
  elevate:
    tags: [outreach, real-estate, first-touch, composio, source-inbox, approval]
    related_skills: [composio-inbound-puller]
---

# Real-estate first-touch outreach run

Use this when a scheduled or manual task asks to “run outreach,” “pull fresh leads,” or “create first-touch drafts” for real-estate leads across connected sources.

## Hard rules

- Do **not** send outbound messages.
- Do **not** mark a lead as touched until a human approves/sends the draft.
- Treat Composio connected account IDs, tokens, API keys, and raw provider identifiers as sensitive; do not expose or persist them in reports.
- Prefer conservative qualification over volume. Skip automated/bulk/newsletter senders and non-real-estate conversations.
- For cron jobs, produce a final report only; do not use `send_message`.

## Environment

On this deployment, Elevate CLI code lives at:

```bash
~/.elevate/elevate/cli
```

Run Python from that directory with:

```bash
PYTHONPATH=.
```

Source inbox data normally lives under the configured source root, commonly:

```bash
~/.elevate/tools/data/sources/
```

Do not broad-search all of the home directory for databases; it can time out. Use the Elevate code/config helpers first.

## Recommended workflow

1. Refresh inbound sources.

```python
from elevate_cli import composio_inbound
summary = composio_inbound.pull_all_supported()
```

2. Build the source inbox/profile view.

```python
from elevate_cli.source_connectors import build_source_inbox_response
inbox = build_source_inbox_response(limit=500)
```

3. Filter candidates.

Eligible candidates should usually satisfy all of these:

- Inbound/recent source thread.
- No first-touch/outbound in the last 14 days.
- Real-estate lead-like content: listing inquiry, REALTOR.ca/website lead, showing request, buyer/seller intent, property address/MLS, or comparable direct real-estate question.
- Not an automated sender, newsletter, transaction notification, vendor email, or generic business/service inquiry.

CRM / Lofty first-touch filtering notes:

- Refresh CRM with `scaffold_source('crm')` or the configured sync path, then inspect `crm/contacts.jsonl`, `crm/lead-events.jsonl`, and `crm/tasks.jsonl` directly when the inbox summary is too broad.
- Do not treat the synthetic current CRM snapshot event itself as a fresh inbound signal; require recent `:activity:` or `:note:` rows within 14 days.
- Dedupe against existing pending first-touch tasks by name/email/thread/contact, and against recent CRM notes whose summary contains `first-touch`.
- Keep CRM first-touch conservative: usually require `stage == 'New Leads'`, usable email/phone, high-intent source/tag (`expmakingitrain`, fb/Facebook, Website, Listing Page, Avenue_PPC, or `mir-*` tags), plus real property/search activity such as `Browsed ...`, `City: ...`, `Purchase Type`, address, MLS, showing/viewing, or other market-area context specific to the tenant's region.
- Skip fake/test/placeholder names, contacts without usable contact info, old generic Zapier snapshots with no property/search activity, and transaction/admin notes such as fully executed listing paperwork or uploaded signed copies.
- For CRM-only property lookup, record `property_lookup.status='local_crm_activity_parse'` and include the parsed activity details; do not invent MLS/price details.
- When parsing Lofty CRM activity rows like `Browsed 450 Main Street, City, Province Lead Name from Lofty is in New Leads via ...`, strip the repeated lead/source suffix before drafting. A naive regex over `title + text` can capture the trailing `... Province LeadName from Lofty...` and produce awkward draft copy. Prefer the `title` field alone when present, or trim at `\s+[A-Z][a-z]+ .* from Lofty` / ` from Lofty is in ` after extracting the address.

4. Enrich from available context.

Use source inbox profile fields, CRM/profile information, and property/listing details already present in the source body. For REALTOR.ca HTML emails, extract useful details directly with stdlib regex + `html.unescape` if BeautifulSoup is not installed:

- lead name
- reply email from `mailto:` links
- phone
- property address
- MLS number
- price
- preferred showing date/time
- message/buyer intent

For Making It Rain / CampaignConnect Gmail lead-alert emails, do not rely only on the source inbox thread summary — multiple lead notifications can share the same Gmail thread and the inbox may show “No preview text yet.” Inspect `composio-gmail/messages.jsonl` directly and parse the email body.

Some MIR emails arrive as HTML/meta tags, but others are ASCII table dumps. Handle both:

- HTML/meta fields such as `meta name="lead_name" content="..."`, `meta name="lead_email" content="..."`, `meta name="lead_phone" content="..."`
- ASCII table labels such as `First name | Clint |`, `Last name | Chrystall |`, `Email | ...`, `Phone number | ...`
- buyer form fields such as sell-before-buy, pre-approval, neighborhood, and search stage

Parsing pitfall: the ASCII table repeats generic labels like `for | Yes | ... a mortgage`; do not use a naive `get_field('for')` globally unless it is anchored near `a mortgage`. Similarly, anchor neighborhood near `What neighborhood are you ... interested in` and stage near `Where are you in your home ... search process`; otherwise drafts may fall back to generic “Kamloops / starting your search” even though the lead gave a specific area/stage.

Deduplicate these by lead email/name, not by Gmail `thread_id`, because several distinct leads can arrive in one notification thread. When checking whether a MIR lead already has first-touch, only count existing approval tasks/draft attempts with `first-touch` or `new-outreach` markers; do not let generic CRM `lead_follow_up` rows suppress a true first-touch draft. Use source facts only for property lookup when no MLS/address is present; record `property_lookup.status='no_specific_property_in_source'` rather than inventing a property.

MIR parsing lessons from production runs:

- Gmail can contain paired MIR rows a few seconds apart for the same lead: one huge/truncated HTML-ish row and one shorter ASCII/table-render row. Prefer the shorter row only when it has concrete email/phone and form fields; otherwise fall back to the HTML `<meta name="lead_*">` and table `<div>` content.
- The Gmail `thread_id` can group many different buyer leads across days, so never suppress a fresh MIR lead just because a previous first-touch task exists in the same thread. Suppress only if the same recipient email/name/source message already appears in existing first-touch/new-outreach tasks or clear outreach notes.
- When parsing table dumps, avoid printing or storing the full split-cell list in logs/reports; the final cell can contain the entire embedded HTML email and produce massive output. Extract only named fields and short snippets.
- Useful MIR buyer-form fields for draft personalization are: `Do you need to sell a current home before buying`, `Have you been pre approved for a mortgage`, `What neighborhood are you interested in`, and `Where are you in your home search process`. Normalize values like `actively_looking_now` and `thinking_about_buying_in_the_next_3_6_months` into human wording in the draft.
- If CRM enrichment finds an exact Lofty contact by email/name, include CRM stage/source/tags in task `context.crm_enrichment`; if no exact match exists, write `crm_enrichment: null` rather than using a partial/fuzzy name match.

5. Draft only on the original channel.

Use `elevate_cli.outreach_db` and the source inbox task mechanism to create a `new-outreach` draft/task for human approval. The draft should be personalized and short, using the same channel the lead came in on.

Draft pattern for REALTOR.ca showing requests:

```text
Hi {first_name}, thanks for reaching out about {property_address}. I saw you’d like to book a showing for {preferred_time}. I can help with that. For context, I have it noted as {price} / MLS® {mls}. Are you already working with an agent, and is there a specific time that works best for you?
```

6. Verify visibility.

After creating attempts/tasks, rebuild the source inbox and confirm the expected `first-touch:` task(s) are visible and `pending`.

`build_source_inbox_response()` returns pending approval cards under the `drafts` key, not `tasks`, in current builds. If `inbox.get('tasks', [])` is empty, do not conclude drafts are missing; inspect `inbox['drafts']` and match on `taskId`, `sourceId`, `threadId`, and `status='pending'`. Use a high limit such as `build_source_inbox_response(limit=5000)` for verification.

CRM / Lofty visibility pitfall: `crm/tasks.jsonl` can contain thousands of generated `lead_follow_up` rows, and the inbox builder reads from the top of the file. If you append first-touch `message_draft` rows to the end, they may exist but not appear in the approval inbox. Keep preserved approval-needed `message_draft` rows before generated `lead_follow_up` rows, or rewrite `tasks.jsonl` so the new `first-touch-crm:*` records are near the top. Then rebuild `build_source_inbox_response(limit=5000)` and verify each `sourceId='crm'`, `taskId` starting with `first-touch-crm:`, `status='pending'` is visible in `inbox['drafts']`. A CRM sync via `scaffold_source('crm')` preserves non-`lead_follow_up` tasks, so run it after creating/reordering drafts to confirm they survive refresh.

Also verify no send queue rows were created for the drafted task ids:

```python
from elevate_cli import outreach_db
with outreach_db.connect() as conn:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM send_queue WHERE task_id IN (%s)" % ",".join("?" for _ in task_ids),
        task_ids,
    ).fetchone()
    assert row["n"] == 0
```

7. Report the result.

Include:

- pull summary by source
- number of eligible leads
- number of drafts created
- lead names/source/channel/property context when safe
- skipped source limitations, e.g. no connected accounts, Facebook page not selected, unsupported LinkedIn inbound
- explicit confirmation that nothing was sent and leads were not marked touched

## Nurture / follow-up mode

Use this when the scheduled/manual task asks for “nurture mode,” “follow up open threads,” or “last outbound 3+ days ago without a reply.” This is different from first-touch mode: do not limit yourself to newly inbound leads, and use the `follow-ups` lane rather than `new-outreach`.

1. Refresh inbound sources as usual, then rebuild the inbox/profile view.
2. Inspect `messages.jsonl` by source and group messages by `thread_id` / `conversation_id`.
3. For each thread, identify:
   - last message timestamp and direction
   - last outbound timestamp/text
   - whether any inbound reply occurred after that outbound
   - channel/source to preserve the same contact channel
   - relationship history from prior messages
   - CRM stage, when a configured CRM source/profile is available
   - for Composio Instagram, do not blindly trust `direction` in `messages.jsonl`; some imports label all rows `inbound`. Infer outbound when `from.username` is the connected account (commonly the realtor's personal handle or brokerage/team handle) and inbound otherwise.
4. Eligible nurture candidates usually satisfy either:
   - open thread where the latest message is outbound, last outbound is 3+ days old, and no later inbound exists; or
   - CRM stage/tag explicitly indicates nurture/follow-up.
5. Keep the filter conservative. Skip newsletters, automated/vendor threads, peer-agent/social chatter, and very old/ambiguous threads unless there is clear real-estate lead context (buyer/seller/rent intent, property/listing/viewing discussion, address, REALTOR.ca link, CRM nurture stage, etc.).
6. Draft a short context-aware follow-up on the same channel, using the relationship history and last touch as the angle. Examples:
   - Prior property/listing curiosity: “Circling back from our earlier chat about {property/context} — are you still keeping an eye out for properties like that, or was that a one-off curiosity?”
   - Buyer nurture: “Are you still thinking about {area/type}, or has your timing changed?”
   - Seller nurture: “Are you still considering a move, or would a quick market check be helpful?”
7. Queue approval-only tasks in the source’s `tasks.jsonl` with `task_type='message_draft'`, `approval_required=true`, `status='pending'`, `owner_agent='Outreach'`, `channel` set to the original channel, and tags including `outreach`, `nurture`, `follow-up`, `approval-required`, `not-sent`.
8. Record template usage with `outreach_db.record_use(..., lane='follow-ups', source_id, thread_id, task_id)` and include `template_id`, `template_name`, and `attempt_id` in task `context`.
9. Verify by rebuilding the source inbox and confirming the new draft is visible/pending; also confirm `send_queue` did not receive a row.
10. Report candidates/drafts created and explicitly state that nothing was sent and no leads were marked touched.

## Monitor / hot-leads watcher mode

Use this when the scheduled/manual task asks for “monitor mode,” “hot signals,” “top 10 hottest leads,” or “scan every connected source for inbound replies, viewing requests, repeat opens, CRM stage moves, listing alerts.” This is different from first-touch/nurture: the primary deliverable is a ranked heat report, and drafts should be created only for brand-new direct human inbound messages that clearly need a same-channel reply.

Recommended monitor workflow:

1. Refresh supported sources first, but avoid unbounded long refreshes. If a full Lofty/Composio refresh hangs, fall back to the existing local source inbox under `<tools_root>/data/sources/` and report the limitation.
2. Read every available source directory under `data/sources/` directly when `build_source_inbox_response()` does not surface discovered Composio directories. Include at least: `messages.jsonl`, `conversations.jsonl`, `lead-events.jsonl`, and `tasks.jsonl`.
3. Use the previous monitor watermark from `<tools_root>/data/outreach/monitor_state.json` (`last_run_at`) to detect brand-new signals. Update it only after final verification and cleanup.
4. Normalize thread direction carefully:
   - For Composio Instagram, infer outbound when `from.username` is the connected account (the realtor's personal handle or brokerage/team handle); do not treat blank/self-account rows as inbound leads.
   - For Apple Messages, be conservative with masked phone/hash display names and empty text. Do not draft unless the latest inbound text clearly contains real-estate intent and needs a reply.
5. Score threads with explicit reasons. Useful factors:
   - + recent latest activity
   - + brand-new human inbound since last run
   - + latest message is inbound
   - + real-estate/property context (MLS, listing, showing, open house, property address, buyer/seller/rent intent)
   - + showing/viewing/request/appointment urgency
   - + repeat engagement in the same thread
   - + listing/showing alerts as hot signals, but not necessarily reply-needed leads
   - + CRM stage/status moves from `lead-events.jsonl` when present
   - + repeat opens/clicks only when actual open/click events exist; do not infer from marketing email content.
6. Treat these as hot signals but usually not reply drafts:
   - ShowingTime/SentriLock showing notifications.
   - Own listing/open-house campaigns from the realtor's own brokerage/team.
   - transaction/admin document requests unless they are client-facing and need an admin/document follow-up rather than outreach.
   - board/vendor/newsletter/training emails, even when they contain real-estate words.
   - delivery failures / bounce notifications.
7. Queue same-channel drafts only for brand-new direct human inbound messages with clear lead/client intent and a pending question/request. Use lane `hot-leads-watcher`; `task_type='message_draft'`; `approval_required=true`; `status='pending'`; `owner_agent='Outreach'`; tags include `outreach`, `hot-leads-watcher`, `monitor`, `approval-required`, `not-sent`.
8. Record template use with `outreach_db.record_use(..., lane='hot-leads-watcher', source_id, thread_id, task_id)` when a template is chosen. If a false-positive draft is removed, also delete the matching `draft_attempts` row and decrement the template `uses` count.
9. Verify before final report:
   - only qualified monitor drafts remain in `tasks.jsonl`
   - no matching rows were inserted into `send_queue`
   - `monitor_state.json` reflects the final cleaned result

## False-positive cleanup

If the first pass creates drafts for weak candidates, remove them before reporting. Common false positives:

- Apple Messages threads with only masked phone/hash display names, empty text, or vague/personal context.
- Gmail newsletter/vendor/admin messages misclassified as warm leads.
- ShowingTime/SentriLock notifications: hot operational signals, but not direct leads needing a drafted reply.
- Own brokerage/team listing/open-house/seller-package/monthly-market campaign emails: useful listing alerts/context, not inbound leads. Treat senders like the realtor's own team/brokerage marketing address as self-marketing even when the sender is not a no-reply address.
- Board/association/training emails with real-estate keywords but no client lead intent.
- Delivery failures / bounce notifications.
- Instagram/social chatter without a clear real-estate inquiry; for Composio Instagram, correct self-account direction before scoring.
- Nurture mode: old threads where the last outbound is 3+ days old but the content is personal/peer-agent/vendor chatter rather than lead intent.

Cleanup should remove both the source inbox task record and corresponding `draft_attempts` row, and decrement template usage if applicable. Then rebuild/re-read the source inbox and verify only qualified `first-touch:`, nurture, or `hot-leads:` drafts remain.

## Known pitfalls

- In cron first-touch runs, a valid result can be **no new drafts created** even when the inbox already has many pending first-touch/new-outreach drafts. Do not respond `[SILENT]` if the run performed work and found source limitations or existing approval drafts. Report: pull summary, CRM screening counts, existing pending first-touch/new-outreach draft count, newly-created draft count, and verification that `send_queue` remains 0 and no leads were marked touched.
- If `composio_inbound.pull_all_supported()` returns HTTP 401 for Composio toolkits, treat the live pull as degraded and continue with the local source cache only for conservative verification. Do not create new Gmail/social first-touch drafts from broad stale keyword scans in cached messages; only draft when there is a formal lead source or a clearly fresh direct human real-estate inquiry that is not already represented by a pending first-touch/new-outreach task.
- `skills_list(category='outreach')` may not show local project skills even though files exist under the Elevate CLI tree; use direct file/code inspection if needed.
- Broad `search_files` calls over `/Users/admin` or `.` can time out. Narrow to `~/.elevate/elevate/cli` or `~/.elevate/tools/data/sources`.
- BeautifulSoup may not be installed; use regex + `html.unescape` for REALTOR.ca lead emails.
- `composio_inbound.pull_all_supported()` can report `new: 0` while still having existing unreviewed eligible inbound leads in source inbox.
- After Composio pull, inspect source files directly for recent lead alerts when the inbox summary is too broad. For example, read `composio-gmail/messages.jsonl`, filter recent rows by `ts`, sender/subject (`Making It Rain`, `Lead@realtor.ca`, `New Lead Submitted`, `Showing request`), and parse only qualifying rows.
- Making It Rain emails may come in paired duplicate-ish rows in the same Gmail thread: one truncated/HTML-wide row and one ASCII-table row. Prefer the ASCII-table row with extractable `First name`, `Last name`, `Email`, `Phone number`, sell-before-buy, pre-approval, neighborhood, and search-stage fields. Deduplicate by lead email, not Gmail thread or sender.
- Before creating a first-touch draft, dedupe against existing pending/prior `first-touch` or `new-outreach` tasks across source `tasks.jsonl` files, using both recipient email and source message id where available. Also dedupe against CRM notes/summaries that clearly indicate prior first-touch or human outreach, such as `first-touch`, `iMessage sent`, `email sent`, or `text sent`. Do not let generic CRM `lead_follow_up` tasks suppress first-touch, but do skip if a real first-touch/new-outreach draft or outreach note already exists.
- `tasks.jsonl` rows are not perfectly uniform: some rows have `context` as a JSON object, while older/imported rows may have `context` as a plain string. When deduping existing tasks, guard with `ctx = row.get('context') if isinstance(row.get('context'), dict) else {}` before reading nested fields; otherwise a cron run can crash with `AttributeError: 'str' object has no attribute 'get'` before creating drafts.
- Monitor-mode can create legitimate first-touch-style pending drafts with IDs like `monitor-lead:*` for brand-new MIR/Gmail leads. During a first-touch run, do not create duplicates for those contacts. Instead, if they are still pending and not sent, reclassify/enrich them in place as first-touch/new-outreach: set `context.lane='new-outreach'`, `context.mode='first-touch'`, add `first-touch`/`new-outreach` tags, set `property_lookup.status='no_specific_property_in_source'` when no address/MLS exists, attach exact-email CRM enrichment when available, and verify the original task remains visible/pending. Keep the old task ID to preserve approval continuity.
- Direct human Gmail replies that are not formal REALTOR.ca/MIR lead forms can still be first-touch eligible when they contain clear real-estate intent (e.g. “someone is looking for a townhome…send details”, “there’s a place we’re interested in”, or “the listing link didn’t work”). For these, match CRM enrichment by exact sender email first, preserve the original Gmail channel/thread, and draft a short clarification/help reply rather than forcing form-specific fields. If the reply references a listing/update thread, parse the quoted source email for a concrete listing/address/MLS and record `property_lookup.status='parsed_from_source_email'`; if no MLS/address/link is present, set `property_lookup.status='no_specific_property_in_source'` and ask for the specific area/listing plus basic search criteria. Do not infer the property from unrelated nearby newsletter/self-marketing emails in the same inbox.
- When scanning Gmail directly, do not use a broad keyword match over all imported messages. Require either a fresh/recent timestamp/message id from the current pull, a formal lead source (REALTOR.ca/MIR/CampaignConnect), or a clearly human direct reply with property intent. Exclude self-marketing, board/vendor/admin emails, newsletters, ShowingTime/SentriLock, SkySlope, eXp training, accounting/bookkeeping/vendor senders, and peer-agent marketing even if they contain words like listing, property, home, open house, or Kamloops.
- Before reporting, verify the newly-created task ids specifically, not just aggregate draft counts. Check: (1) created task ids are visible/pending in `build_source_inbox_response(limit=5000)`, (2) matching `send_queue` count is 0, and (3) sampled latest pull rows were not automated/vendor/newsletter content. If a script accidentally creates weak Gmail/CRM drafts, remove the bad source `tasks.jsonl` rows and matching `draft_attempts` rows, decrement template usage if needed, then rebuild the inbox and confirm no bad task ids remain before final report.
- Do not trust `/Users/admin/elevate-premium/tmp_first_touch_run.py` as a one-shot writer when Composio live pull is degraded. It has previously over-selected cached Gmail rows and created false positive first-touch drafts for Skool/noreply, vendor/lender, eXp peer-agent, and ShowingTime notification emails. If you use it at all, run a dry-run/manual sample first or immediately QA every created task and clean false positives before reporting.
- When the live Composio pull is degraded (especially HTTP 401) do a dry-run candidate list before writing tasks. Do not create Gmail first-touch tasks from a broad real-estate keyword/address regex over cached messages. Explicitly exclude peer-agent/brokerage emails (`exprealty.net`, board/realtor association), training communities (Skool/eXp University), vendors/bookkeepers/accountants/banks, GoDaddy/Intuit/service providers, sign/order/admin notifications, and self-marketing emails. A valid cached Gmail candidate should be a formal lead form (REALTOR.ca email-a-realtor/showing request, MIR/CampaignConnect parsed lead) or a clearly human direct reply with property intent, and it must survive manual sample inspection before task creation.
- If the run needs a custom Python screening/writer script, create it with `write_file` (or a real file edit), not a shell heredoc inside `terminal`. The terminal guard can reject heredoc commands when the Python code contains set intersections or other `&` characters, mistaking them for shell backgrounding. Then run the saved script with `PYTHONPATH=. python /path/to/script.py` from `~/.elevate/elevate/cli`.
- If no dedicated property lookup is possible for a buyer-form lead, do not invent property details. Record `property_lookup.status='no_specific_property_in_source'` and use parsed form context such as neighborhood, search stage, sell-first, and pre-approval in the draft.
- In first-touch CRM runs, run `elevate sync crm` before screening and again after writing/reordering CRM draft tasks to verify the drafts survive the CRM task-file rewrite. A successful sync may print `state=connected (no rows)` and still refresh current contact snapshots/timestamps; do not treat `Lofty lead synced` snapshot rows as fresh inbound activity. Require recent non-snapshot `crm_activity` rows, usually `Browse` or `Search`, within the 14-day window before creating new CRM first-touch drafts.
- When Composio live pull is degraded with HTTP 401, it is still okay to create first-touch drafts from a freshly synced CRM source if the CRM activity is recent and conservative. Do not create new Gmail/social drafts from cached Composio data in that degraded state unless the cached row is a formal lead form or clearly fresh direct human real-estate inquiry and passes manual sample QA.
- `build_source_inbox_response()` may show created drafts with `displayName=null` even though the task file has `display_name`; verify visibility by matching `taskId`, `sourceId`, and `status='pending'`, not by display name alone.
- Running `elevate sync apple-messages` can update `status.json` to blocked when Full Disk Access is missing (`unable to open database file`). Report the exact `next_operator_step`; do not treat old imported Apple Messages data as freshly synced SMS.
- The Python module form `python -m elevate_cli sync crm` is invalid (`elevate_cli` has no `__main__`). Use the installed CLI command `elevate sync crm` from `~/.elevate/elevate/cli` instead.
- LinkedIn inbound may be unsupported by the current Composio connector.
- Facebook can be skipped when no pages are selected in Composio settings.
- Gmail OAuth2, Outlook, and Slack may be skipped when no connected accounts exist.
