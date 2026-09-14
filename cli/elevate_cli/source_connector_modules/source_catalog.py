"""Static source connector catalog data."""

from __future__ import annotations

from typing import Any


JsonRecord = dict[str, Any]

JSONL_FILES = (
    "contacts.jsonl",
    "conversations.jsonl",
    "messages.jsonl",
    "message-days.jsonl",
    "lead-events.jsonl",
    "tasks.jsonl",
)

SOURCE_INBOX_DRAFT_QUEUE_LIMIT = 500

SOURCE_CONNECTION_BLUEPRINTS: tuple[JsonRecord, ...] = (
    {
        "id": "apple-messages",
        "source": "Apple Messages",
        "category": "messages",
        "description": "Reads the local Mac Messages database (chat.db + AddressBook) and indexes people, conversations, and messages for lead context.",
        "informationNeeded": "Mac user, included handles, conversation scope, read permission, and reply policy.",
        "connectionLayer": "Local bridge or export writes normalized conversations, messages, lead events, and approval tasks.",
        "uiDestination": "Outreach threads, Leads, Today follow-ups, and approval queues for draft replies.",
        "successSignal": "A synced iMessage/SMS conversation appears as a thread with a lead event and reply-needed task.",
    },
    {
        "id": "sms-provider",
        "source": "SMS Provider",
        "category": "messages",
        "description": "Webhook/poller adapter for an SMS provider (Twilio, Bandwidth, etc.) — pulls inbound texts into the unified inbox.",
        "informationNeeded": "Provider name, numbers, webhook/API/export access, contact matching, and send approval policy.",
        "connectionLayer": "Webhook, poller, or import adapter maps provider records into Elevate message and lead files.",
        "uiDestination": "Live lead inbox, Outreach, Today hot replies, and source health in Settings.",
        "successSignal": "A new inbound provider text creates a message record, lead event, and follow-up task without manual copying.",
    },
    {
        "id": "android-device",
        "source": "Android Device SMS",
        "category": "messages",
        "description": "Imports Android SMS via device export or a mobile helper, into the same inbox as Apple Messages.",
        "informationNeeded": "Export method, device owner approval, included numbers, backup format, and sync cadence.",
        "connectionLayer": "Optional mobile helper, backup export, or manual import turns device messages into normalized source records.",
        "uiDestination": "Same SMS UI path as provider texts: Outreach, Leads, Today, and approval tasks.",
        "successSignal": "Imported Android messages show source confidence and do not claim live sync unless a helper exists.",
    },
    {
        "id": "rcs",
        "source": "RCS",
        "category": "messages",
        "description": "Business or device RCS (Rich Communication Services) capture. Provider connector when available, blocker otherwise.",
        "informationNeeded": "Whether this is business RCS/provider messaging or personal device RCS, plus webhook/export access.",
        "connectionLayer": "Business/provider RCS uses a connector; personal RCS becomes a setup blocker unless export access exists.",
        "uiDestination": "Provider-style message threads and lead events when connected; setup blockers in Settings when not connectable.",
        "successSignal": "RCS is labeled connected, import-only, or blocked instead of being folded into generic SMS.",
    },
    {
        "id": "email",
        "source": "Email",
        "category": "messages",
        "description": "Read-only mailbox connector (IMAP, Gmail, or one-time export) for inbound leads, referrals, and document intake.",
        "informationNeeded": "Mailbox, folders/labels, search terms, attachment policy, and storage destination.",
        "connectionLayer": "Read-only mailbox adapter or export importer creates conversations, lead events, and document tasks.",
        "uiDestination": "Leads, Outreach, document intake, admin tasks, and Today reply-needed rows.",
        "successSignal": "A website lead or referral email appears with source thread, summary, and next-step task.",
    },
    {
        "id": "crm",
        "source": "CRM",
        "category": "crm",
        "description": "Pulls contacts, deals, stages, notes, and activity from the agent's CRM of record (Lofty, FUB, Sierra, Brivity, BoldTrail).",
        "informationNeeded": "CRM name, auth method, stage meanings, reliable fields, activity types, and owner mapping.",
        "connectionLayer": "CRM adapter maps contacts, stages, notes, activities, and exposed messages into Elevate records.",
        "uiDestination": "Leads, Admin, Outreach context, Today pipeline, and stale-follow-up queues.",
        "successSignal": "A CRM stage or activity change updates the lead/admin view and creates the right next action.",
    },
    {
        "id": "xposure-pcs",
        "source": "MLS Buyer Searches",
        "category": "mls",
        "description": "Scrapes Lofty/Xposure private-search (PCS) buyer criteria, writes pcs_buyers detail keyed to the canonical contact.",
        "informationNeeded": "Lofty member-area credentials, scrape cadence, allowed property-search domains, and CRM sync target.",
        "connectionLayer": "Headless browser run pulls private-search (PCS) buyer criteria, normalizes phones/emails, writes canonical contacts/conversations/messages JSONL plus the source-specific pcs_buyers rows. The walker hydrates identities + contacts + events through the same identity-first writethrough Apple Messages and CRM already use, so the same buyer collapses to one contact across sources.",
        "uiDestination": "Leads, Today buyer-search lane, and the outreach approval queue when high-intent triggers fire.",
        "successSignal": "A scraped MLS buyer search appears as an identity-resolved contact with pcs_buyers detail and (when matched) merges into the existing CRM contact instead of creating a duplicate row.",
    },
    {
        "id": "buyer-brief",
        "source": "Buyer Brief Enrichment",
        "category": "mls",
        "description": "Reads pcs_buyers rows already in Postgres and synthesizes a human-readable buyer brief on each contact. No external calls.",
        "informationNeeded": "Already-synced xposure-pcs rows. No external credentials — this connector only reads local PG.",
        "connectionLayer": "Reads pcs_buyers.searches_json for every contact, synthesizes a human-readable brief (price range, beds, neighborhoods, last-search recency, 90-day search volume) and writes it to contacts.enrichment_brief. Sets activity_tier + last_search_at + search_count_90d on the same upsert. Idempotent: keyed on contact_id, re-running refreshes the brief in place without touching display_name/notes/tags.",
        "uiDestination": "Leads drawer (buyer brief panel), activity-tier filter chips, and the outreach flagger which uses the same denormalized fields.",
        "successSignal": "Every xposure-pcs contact has a non-null enrichment_brief and activity_tier; the /leads drawer shows the brief instead of the generic 'buyer interested' line.",
    },
    {
        "id": "xposure-pcs-views",
        "source": "MLS Per-Listing Engagement",
        "category": "mls",
        "description": "Scrapes the Client View one-way mirror per saved search for per-listing view counts, favorites, removed, and last access. Feeds the activity flagger.",
        "informationNeeded": "Same Lofty/Xposure credentials as xposure-pcs (no new auth). Requires existing pcs_buyers rows so we know which buyers to scrape and which xposure search IDs to open.",
        "connectionLayer": "Headless browser walks the Client View one-way mirror per saved search (manageClients.manageResults). For each engaged buyer it captures per-listing view_count, last_viewed_at, view_state (new / pc / older / viewed / favorite / removed), plus parent-buyer summary counts (results/favorites/removed/queue + last_client_access). Snapshot semantics: upsert keyed on (contact_id, search_id, mls_id); listings that drop off get view_state='stale' rather than being deleted so the activity flagger can diff against the previous run.",
        "uiDestination": "Leads drawer engagement panel (top viewed listings, repeat-view spikes), Today outreach-trigger lane, and the activity flagger queue.",
        "successSignal": "pcs_listing_views has rows for every active/warm buyer with at least one saved search; pcs_buyers.{results_count,favorites_count,removed_count,queue_count,last_client_access,views_scraped_at} are populated and the /leads buyer drawer shows 'top views' instead of just the search criteria.",
    },
    {
        "id": "social",
        "source": "Composio Social Accounts",
        "category": "social",
        "description": "Composio is the account hub for IG, Facebook, LinkedIn, TikTok. Once connected, pulls posts, metrics, DMs, comments, and lead moments.",
        "informationNeeded": "Composio account/MCP URL, connected social apps, metrics scope, DM/comment scope, lead definition, and reply workflow.",
        "connectionLayer": "Composio is the account hub. Elevate uses the local MCP/tool connection to read social posts, metrics, DMs, comments, and lead moments into normalized local records.",
        "uiDestination": "Social Media pulse, Leads from DMs/comments, content tasks, and approvals for drafted replies.",
        "successSignal": "A connected Composio social app can produce a local social metric, content task, lead event, or reply approval record.",
    },
    {
        "id": "market-stats",
        "source": "Market Stats",
        "category": "social",
        "description": "Imports market stats (board exports, MLS reports, CSVs) for use in social content and seller/buyer reports.",
        "informationNeeded": "Market regions, property types, stats source, refresh cadence, and client-facing summary needs.",
        "connectionLayer": "Board, MLS, report, CSV, spreadsheet, or manual import writes dashboard-ready stats and artifacts.",
        "uiDestination": "Admin, Today prep, Social content, later Ads work, and market-report tasks.",
        "successSignal": "A fresh market artifact appears with period, region, metrics, source files, and next operator step.",
    },
    {
        "id": "skills",
        "source": "Skill Outputs",
        "category": "admin",
        "description": "Ingests structured outputs from skills (JSON, JSONL, markdown, PDFs, screenshots) into the operational store for downstream UI lanes.",
        "informationNeeded": "Skill name, artifact folders, refresh cadence, record shape, and which UI lane should consume it.",
        "connectionLayer": "Artifact reader ingests JSON, JSONL, markdown, PDFs, screenshots, and exports from the tools/data root.",
        "uiDestination": "Admin, seller updates, market stats, document routing, admin queues, and source activity.",
        "successSignal": "A fresh skill artifact shows in the correct dashboard lane with timestamp, source, and actionability.",
    },
    {
        "id": "admin-requirements",
        "source": "Admin Requirements",
        "category": "admin",
        "description": "Models brokerage/jurisdiction requirements per deal stage (required forms, deadlines, human-only checks).",
        "informationNeeded": "Jurisdiction, brokerage rules, transaction stages, required forms, deadlines, and human-only checks.",
        "connectionLayer": "Checklist or source import writes required items and generated admin tasks.",
        "uiDestination": "Admin, Today admin queue, Tasks, documents, and approvals.",
        "successSignal": "A deal stage exposes required docs, missing items, deadlines, and owner tasks without hardcoded brokerage rules.",
    },
    {
        "id": "document-storage",
        "source": "Document Storage",
        "category": "admin",
        "description": "Indexes deal-file documents from cloud storage (Drive, Dropbox, S3) or a local root, routes them by category and deal/listing match.",
        "informationNeeded": "Storage provider/root, folder naming, document categories, permissions, and dry-run routing policy.",
        "connectionLayer": "Local or cloud indexer writes document-index records and routing tasks.",
        "uiDestination": "Admin, Today admin queue, document intake, and source activity.",
        "successSignal": "A sample document record appears with category, deal/listing match, confidence, status, and next action.",
    },
    {
        "id": "forms-signing",
        "source": "Forms & Signing",
        "category": "admin",
        "description": "Form templates + signing packet routing (Authentisign, DocuSign, SkySlope). Drafts dry-run packets; every send is approval-gated.",
        "informationNeeded": "Form provider, blank forms/templates, recipient roles, field map, and approval policy.",
        "connectionLayer": "Provider-neutral form map and packet index writes dry-run packet records and approval tasks.",
        "uiDestination": "Admin, Today admin queue, approvals, and document routing.",
        "successSignal": "A packet draft appears as a dry-run artifact and every send/signing action is gated behind approval.",
    },
)


# Connectors with a live implementation. Settings "Run" opens a visible chat
# session for every wired connector so the operator can watch the command,
# browser work, verification steps, and failure messages in one transcript.
WIRED_SOURCE_IDS = frozenset({
    "apple-messages",
    "crm",
    "social",
    "xposure-pcs",
    "xposure-pcs-views",
    "buyer-brief",
})

AGENT_SESSION_SOURCE_IDS = WIRED_SOURCE_IDS

SERVER_INLINE_SOURCE_IDS = WIRED_SOURCE_IDS - AGENT_SESSION_SOURCE_IDS


SOURCE_CATEGORIES: tuple[JsonRecord, ...] = (
    {
        "id": "messages",
        "label": "Messages & inbox",
        "description": "Inbound conversations from phone, laptop, and email — Apple Messages, SMS providers, Android, RCS, mailbox.",
    },
    {
        "id": "crm",
        "label": "CRM",
        "description": "The agent's CRM of record. One per workspace. Contacts + deals + activity collapse here.",
    },
    {
        "id": "mls",
        "label": "MLS / Buyer intelligence",
        "description": "Lofty/Xposure private-search data, per-buyer briefs, per-listing engagement. Feeds the activity flagger.",
    },
    {
        "id": "social",
        "label": "Social",
        "description": "Composio social-account hub (IG, FB, LinkedIn, TikTok) plus market-stats imports for content + reporting.",
    },
    {
        "id": "admin",
        "label": "Operations & admin",
        "description": "Skill outputs, brokerage requirements, document storage, forms & signing — the back-office plumbing.",
    },
)

OWNER_BY_SOURCE = {
    "apple-messages": "Outreach",
    "sms-provider": "Outreach",
    "android-device": "Outreach",
    "rcs": "Outreach",
    "crm": "Outreach",
    "xposure-pcs": "Outreach",
    "buyer-brief": "Outreach",
    "xposure-pcs-views": "Outreach",
    "social": "Social Media",
    "email": "Outreach",
    "skills": "Executive Assistant",
    "market-stats": "Social Media",
    "admin-requirements": "Admin",
    "document-storage": "Admin",
    "forms-signing": "Admin",
}

UI_BY_SOURCE = {
    "apple-messages": ["Outreach", "Leads", "Today", "Approvals"],
    "sms-provider": ["Outreach", "Leads", "Today", "Settings"],
    "android-device": ["Outreach", "Leads", "Today", "Approvals"],
    "rcs": ["Outreach", "Leads", "Today", "Settings"],
    "crm": ["Leads", "Admin", "Outreach", "Today"],
    "xposure-pcs": ["Leads", "Today", "Outreach", "Approvals"],
    "buyer-brief": ["Leads", "Today", "Outreach"],
    "xposure-pcs-views": ["Leads", "Today", "Outreach", "Approvals"],
    "social": ["Leads", "Outreach", "Social Media", "Approvals"],
    "email": ["Leads", "Outreach", "Admin", "Today"],
    "skills": ["Admin", "Social Media", "Settings"],
    "market-stats": ["Admin", "Social Media", "Ads"],
    "admin-requirements": ["Admin", "Tasks", "Approvals", "Today"],
    "document-storage": ["Admin", "Documents", "Tasks", "Today"],
    "forms-signing": ["Admin", "Approvals", "Documents", "Today"],
}

SOURCE_PROMPT_CATEGORIES = (
    {"id": "all", "label": "All"},
    {"id": "messages", "label": "Messages"},
    {"id": "leads", "label": "Leads"},
    {"id": "operations", "label": "Market"},
    {"id": "admin", "label": "Admin"},
    {"id": "forms", "label": "Forms"},
)

CONNECTION_CONTRACT = """Canonical Elevate connector contract (every source MUST follow this — already enforced for apple-messages, crm, social):

Storage layout (all paths portable, work on any user's install):
- Operational DB — the embedded Postgres store managed by `elevate_cli.data.connect()`. Migrations auto-apply on first `data.connect()`; do not read or write deprecated local DB files.
- `<tools_root>/data/sources/<source-id>/` — per-source workspace. Holds `source.json`, `status.json`, `contacts.jsonl`, `conversations.jsonl`, `messages.jsonl`, `lead-events.jsonl`, `tasks.jsonl`, `artifacts/`.

Canonical 3-file write shape (REQUIRED — the walker depends on it):
- `contacts.jsonl` — one row per person, MUST include `source_record_id` and at least one of `phone` / `email` / `<channel>_handle` / `<provider>_id`.
- `conversations.jsonl` — one row per thread; `source_record_id` is the conversation id, `contact_id` links to a contacts row.
- `messages.jsonl` — one row per message; MUST include `contact_id` AND `conversation_id` (the synthesizer in `composio_inbound.synthesize_canonical_files` derives these for messages-only sources — copy that pattern).

Identity-first writethrough (handled for you by `elevate_cli/data/migrate.py:walk_jsonl_source`):
- E.164 normalize phones, lowercase emails.
- `_SOURCE_TO_HANDLE_KIND` + `_CRM_PROVIDER_TO_IDENTITY_KIND` + `_TOOLKIT_TO_HANDLE_KIND` registries map raw native ids to canonical identity kinds. Add a row to the right registry — do NOT branch in code.
- The same person collapses to one `contact_id` across every source. Cross-source duplicates land in `identity_conflicts` for operator review (never auto-merge — `merge_contacts` requires `actor.startswith("human")`).

Recurring sync:
- Deterministic source pulls can use `elevate_cli/sync_scheduler.py` launchd plists.
- AI/browser agent work belongs in the app Automations scheduler, not launchd, so its sessions keep cron metadata and stay out of the Chats sidebar.
- New deterministic sources auto-register by adding a tuple to `sync_scheduler._JOBS`.

Per-source files:
- `source.json` — provider, account_label, connection_type, auth_status, sync_mode, owner_agent, enabled_ui_surfaces, setup_status, last_sync_at, setup_notes.
- `status.json` — connected, import_only, blocked, last_error, next_operator_step, last_checked_at.
- `artifacts/` — raw exports, screenshots, PDFs, full payloads.

Safety: start read-only. Do not send messages, submit forms, move files, change permissions, upload data, or create persistent API keys unless the operator explicitly approves."""

COMPOSIO_SOCIAL_CONTRACT = """Use Composio as the social account hub:

- The operator connects their Composio account first.
- Social apps such as Instagram, Facebook, LinkedIn, YouTube, TikTok, X, or Threads are added inside Composio.
- Elevate reads through the configured local MCP/tool connection and writes normalized local source records.
- Metrics become Social Media pulse inputs; DMs/comments that look like leads become Leads records; outbound replies stay approval-gated.
- Write social DMs/comments as conversations.jsonl plus messages.jsonl records with platform, channel, display_name, participant_handles, direction, timestamp, text, permalink/source_url, lead_score or tags when available.
- Write reply drafts/follow-up recommendations into tasks.jsonl with task_type=message_draft or follow_up, approval_required=true, draft_text, channel, contact_id or conversation_id, and source_record_id.
- Never ask for raw social passwords. If an app is not connected in Composio, write the exact next operator step instead."""
