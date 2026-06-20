"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import fcntl
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from elevate_cli.config import (
    get_config_path,
    get_elevate_home,
    get_env_path,
    load_config,
    load_env,
    save_config,
    save_env_value,
)
from elevate_cli.source_connector_modules.prompts import (
    _local_counts_command,
    _local_python_prefix,
    _local_sync_command,
    _render_apple_messages_agent_prompt,
    _render_buyer_brief_agent_prompt,
    _render_social_agent_prompt,
    _render_xposure_pcs_agent_prompt,
    _render_xposure_pcs_views_agent_prompt,
    _source_file_count_commands,
)


JsonRecord = dict[str, Any]

JSONL_FILES = (
    "contacts.jsonl",
    "conversations.jsonl",
    "messages.jsonl",
    "message-days.jsonl",
    "lead-events.jsonl",
    "tasks.jsonl",
)
_JSONL_COUNT_CACHE: dict[str, tuple[int, int, int]] = {}
_JSONL_RECORD_CACHE: dict[tuple[str, int, bool], tuple[int, int, list[JsonRecord]]] = {}

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _candidate_tools_root(config: dict[str, Any]) -> Path:
    sources_cfg = _as_dict(config.get("sources"))
    integrations_cfg = _as_dict(config.get("integrations"))
    env_root = os.getenv("ELEVATE_TOOLS_ROOT", "").strip()
    configured = str(sources_cfg.get("tools_root") or integrations_cfg.get("tools_root") or "").strip()
    client_tools_tmp = get_elevate_home() / "tmp" / "client-tools"
    if env_root:
        return _expand_path(env_root)
    if configured:
        return _expand_path(configured)
    if client_tools_tmp.exists():
        return client_tools_tmp
    return get_elevate_home() / "tools"


def get_source_root_info(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    sources_cfg = _as_dict(config.get("sources"))
    tools_root = _candidate_tools_root(config)
    source_root = tools_root / "data" / "sources"
    if os.getenv("ELEVATE_TOOLS_ROOT", "").strip():
        root_source = "env"
    elif sources_cfg.get("tools_root"):
        root_source = "config"
    elif (get_elevate_home() / "tmp" / "client-tools").exists():
        root_source = "detected-client-tools"
    else:
        root_source = "default-local"

    return {
        "toolsRoot": str(tools_root),
        "toolsRootSource": root_source,
        "toolsRootIo": "local",
        "sourceRoot": str(source_root),
    }


def _source_dir(source_root: Path, source_id: str) -> Path:
    return source_root / source_id


def _read_json(path: Path) -> JsonRecord | None:
    try:
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _write_json(path: Path, value: JsonRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _count_jsonl(path: Path) -> int:
    try:
        stat = path.stat()
        cache_key = str(path)
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = _JSONL_COUNT_CACHE.get(cache_key)
        if cached and cached[:2] == signature:
            return cached[2]
        with path.open("r", encoding="utf-8") as fh:
            count = sum(1 for line in fh if line.strip())
        _JSONL_COUNT_CACHE[cache_key] = (signature[0], signature[1], count)
        return count
    except FileNotFoundError:
        return 0
    except Exception:
        try:
            _JSONL_COUNT_CACHE.pop(str(path), None)
        except Exception:
            pass
        return 0


def _record_timestamp(record: JsonRecord) -> str:
    for key in ("timestamp", "last_message_at", "last_seen_at", "last_sync_at", "day"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _read_jsonl_records(path: Path, *, limit: int = 12, tail: bool = False) -> list[JsonRecord]:
    # No upper clamp here — callers explicitly pass small limits (UI preview reads ~12-100)
    # or large limits (rewrite-preserve operations need 5000+). Earlier 100-row ceiling
    # silently dropped preserved tasks/drafts past row 100 on every CRM sync.
    safe_limit = max(1, int(limit or 12))
    try:
        stat = path.stat()
    except FileNotFoundError:
        return []
    except Exception:
        return []
    cache_key = (str(path), safe_limit, bool(tail))
    cached = _JSONL_RECORD_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return [dict(record) for record in cached[2]]

    raw_lines: list[str]
    try:
        if tail:
            recent: deque[str] = deque(maxlen=safe_limit)
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        recent.append(line)
            raw_lines = list(recent)
        else:
            raw_lines = []
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    raw_lines.append(line)
                    if len(raw_lines) >= safe_limit:
                        break
    except Exception:
        return []

    records: list[JsonRecord] = []
    for line in raw_lines:
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            records.append(value)
    records = sorted(records, key=_record_timestamp, reverse=True)
    _JSONL_RECORD_CACHE[cache_key] = (
        stat.st_mtime_ns,
        stat.st_size,
        [dict(record) for record in records],
    )
    return records


def _find_jsonl_record_by_id(
    path: Path,
    target_id: str,
    *,
    id_keys: tuple[str, ...] = ("id", "contact_id", "source_record_id"),
) -> JsonRecord | None:
    """Stream a JSONL file and return the last row whose id matches ``target_id``.

    Unbounded by file size and uses constant memory — designed for the thread
    drawer's contact/lead lookup, which previously used a 2000-row preview read
    and silently dropped any record past that mark. Returns the LAST matching
    row so an updated record (re-synced contact) wins over a stale earlier one.
    """
    target = (target_id or "").strip()
    if not target or not path.exists():
        return None
    match: JsonRecord | None = None
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if not isinstance(value, dict):
                    continue
                for key in id_keys:
                    candidate = value.get(key)
                    if candidate is None:
                        continue
                    if str(candidate).strip() == target:
                        match = value
                        break
    except OSError:
        return match
    return match


def _stream_jsonl_records_by_id(
    path: Path,
    target_id: str,
    *,
    id_keys: tuple[str, ...] = ("contact_id", "conversation_id"),
) -> list[JsonRecord]:
    """Stream a JSONL file and return every row whose id matches ``target_id``.

    Unlike :func:`_find_jsonl_record_by_id` (which returns a single contact
    row), this returns the full event list for a given conversation — used by
    the thread drawer for notes/tasks/activity. Streams the whole file so it
    doesn't drop events for older leads on long-running CRMs (the prior
    `tail=True, limit=4000` read silently dropped activity for any contact
    whose events were ingested earlier than the last 4000 rows; with 2474
    Lofty leads and 15455 lifetime events, every contact past line 11455 had
    an empty Property Activity panel).
    """
    target = (target_id or "").strip()
    matches: list[JsonRecord] = []
    if not target or not path.exists():
        return matches
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except Exception:
                    continue
                if not isinstance(value, dict):
                    continue
                for key in id_keys:
                    candidate = value.get(key)
                    if candidate is None:
                        continue
                    if str(candidate).strip() == target:
                        matches.append(value)
                        break
    except OSError:
        return matches
    return matches


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _parse_record_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        number = int(raw)
        if number > 10_000_000_000:
            number = number // 1000
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except Exception:
            return None
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _tag_text(value: Any) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.extend(str(v) for v in item.values() if isinstance(v, (str, int, float)))
            else:
                parts.append(str(item))
        return " ".join(parts).lower()
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float))).lower()
    return str(value or "").lower()


def _source_ui_state_path(source_dir: Path) -> Path:
    return source_dir / "ui-state.json"


def _read_source_ui_state(source_dir: Path) -> JsonRecord:
    state = _read_json(_source_ui_state_path(source_dir))
    if not state:
        return {"threads": {}}
    threads = state.get("threads")
    if not isinstance(threads, dict):
        state["threads"] = {}
    return state


def _write_source_ui_state(source_dir: Path, state: JsonRecord) -> None:
    state["updated_at"] = _now()
    _write_json(_source_ui_state_path(source_dir), state)


# Profile-level statuses set by the operator from the /leads UI. These
# describe where the lead is in the pipeline so cron-pulled queues can
# skip cold/closed people. Distinct from thread-level status which only
# tracks open/done/archived.
PROFILE_STATUS_VALUES: tuple[str, ...] = (
    "new_lead",
    "follow_up",
    "ghosting",
    "dead",
    "closed_seller",
    "closed_buyer",
)


def _profile_state_path(source_root: Path) -> Path:
    return source_root / "profile-state.json"


def _read_profile_state(source_root: Path) -> JsonRecord:
    state = _read_json(_profile_state_path(source_root))
    if not isinstance(state, dict):
        return {"profiles": {}}
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        state["profiles"] = {}
    return state


def _write_profile_state(source_root: Path, state: JsonRecord) -> None:
    state["updated_at"] = _now()
    _write_json(_profile_state_path(source_root), state)


def _thread_key(record: JsonRecord) -> str:
    for key in ("conversation_id", "source_record_id", "contact_id", "handle", "chat_identifier"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return "unknown-thread"


def _record_person_name(record: JsonRecord) -> str:
    for key in ("display_name", "name", "full_name", "contact_name", "handle", "chat_identifier", "conversation_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return "Client conversation"


def _channel_label(source_id: str, source: JsonRecord, record: JsonRecord) -> str:
    service = str(record.get("service") or "").strip()
    if service:
        return service
    raw_channel = str(record.get("channel") or "").strip()
    if raw_channel == "apple-messages":
        return "Messages"
    if raw_channel.lower().replace("-", " ") == "lofty crm":
        return "Lofty CRM"
    if raw_channel:
        return raw_channel.replace("-", " ").title()
    return str(source.get("label") or source_id).strip() or source_id


def _latest_text(record: JsonRecord) -> str:
    for key in ("last_text", "text", "summary", "title"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return "No preview text yet."


_AUTOMATED_LOCALPARTS = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "do_not_reply",
    "mailer-daemon", "mailerdaemon", "postmaster", "bounce", "bounces", "notification",
    "notifications", "alerts", "alert", "info", "infoalerts", "newsletter", "news",
    "marketing", "promotions", "promo", "promos", "deals", "offers", "updates",
    "update", "system", "auto", "automated", "noreplies", "support", "help",
    "hello", "team", "service", "services", "billing", "receipts", "orders", "order",
    "shipping", "ship", "tracking", "account", "accounts", "security", "feedback",
    "reply", "replies", "customersupport", "customer-support", "customerservice",
    "customer-service", "care", "reminders", "reminder", "verify", "verification",
    "confirm", "confirmation", "receipt", "invoice", "invoices", "members",
    "membership", "subscriptions", "subscribe", "unsubscribe", "list", "lists",
    "broadcast", "campaign", "campaigns", "digest", "weekly", "daily", "drop",
    "drops",
}

_AUTOMATED_DOMAIN_HINTS = (
    "accounts.google.com", "google.com", "googlemail.com", "mail-noreply",
    "scotiabank.com", "scotiabank.ca", "rbc.com", "td.com", "amazon.com",
    "amazonses.com", "shopify.com", "mailchimp.com", "sendgrid.net", "klaviyomail.com",
    "klaviyo.com", "mailerlite.com", "constantcontact.com", "hubspot.com",
    "intercom-mail.com", "linkedin.com", "facebookmail.com", "instagram-mail.com",
    "twittermail.com", "stripe.com", "squareup.com", "uber.com", "doordash.com",
    "shipstation.com", "ups.com", "fedex.com", "usps.com", "canadapost.ca",
    "ticketmaster.com", "eventbrite.com", "zoom.us", "calendly.com", "github.com",
    "githubmail.com", "atlassian.net", "notion.so", "figma.com", "slack.com",
    "spotify.com", "netflix.com", "apple.com", "appleid.apple.com", "youtube.com",
    "discord.com", "patreon.com", "medium.com", "substack.com", "wix.com",
    "squarespace.com", "wordpress.com", "godaddy.com", "namecheap.com",
)


def _extract_email(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(text))
    return match.group(0).lower() if match else ""


def _is_automated_email(email: str) -> bool:
    """Heuristic: is this sender a noreply / newsletter / transactional source?"""
    if not email or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    local = local.lower().strip()
    domain = domain.lower().strip()
    if not local or not domain:
        return False
    # Strong patterns in the localpart
    if "noreply" in local or "no-reply" in local or "donotreply" in local or "do-not-reply" in local:
        return True
    if local in _AUTOMATED_LOCALPARTS:
        return True
    # Common bulk-mail subdomain hints
    for hint in _AUTOMATED_DOMAIN_HINTS:
        if domain == hint or domain.endswith("." + hint):
            return True
    if domain.startswith(("mail.", "email.", "newsletter.", "news.", "alerts.", "notify.", "notifications.", "updates.", "promo.", "send.", "sender.", "delivery.")):
        return True
    # Domain ends with -mail.com / -email.com / -mailer.* (transactional ESP patterns)
    if re.search(r"-(mail|email|mailer|notify|sender)\.[a-z]{2,}$", domain):
        return True
    return False


def _is_automated_sender_record(record: JsonRecord) -> bool:
    """Inspect a normalized message/contact record and decide if the sender is automated."""
    candidates: list[str] = []
    for key in ("from", "sender", "display_name", "personName", "handle", "email"):
        val = record.get(key)
        if isinstance(val, dict):
            for sub in ("email", "address", "value", "id"):
                if val.get(sub):
                    candidates.append(str(val[sub]))
        elif isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, str):
                    candidates.append(item)
        elif val:
            candidates.append(str(val))
    for raw in candidates:
        email = _extract_email(raw)
        if email and _is_automated_email(email):
            return True
    return False


def _heat_score_for_record(record: JsonRecord) -> tuple[int, str]:
    if _is_automated_sender_record(record):
        return 0, "normal"
    explicit = record.get("heat_score") or record.get("lead_score") or record.get("score")
    score = _safe_int(explicit, 35 if explicit is None else 0)
    haystack = " ".join(
        _tag_text(record.get(key))
        for key in ("ai_stage", "stage", "status", "priority", "tags", "source", "summary", "title")
    )
    if any(word in haystack for word in ("high_priority", "hot", "urgent", "overdue", "new lead", "needs follow")):
        score += 34
    if any(word in haystack for word in ("warm", "active", "prospecting", "ai_prospecting", "buyer", "seller")):
        score += 18
    if record.get("direction") == "inbound":
        score += 16
    score += min(_safe_int(record.get("inbound_count")), 18)

    latest = _parse_record_dt(_record_timestamp(record))
    if latest:
        age = datetime.now(timezone.utc) - latest
        if age <= timedelta(hours=24):
            score += 16
        elif age <= timedelta(days=7):
            score += 8

    score = max(0, min(score, 100))
    if score >= 76:
        label = "hot"
    elif score >= 54:
        label = "warm"
    elif score >= 35:
        label = "watch"
    else:
        label = "normal"
    return score, label


def _thread_from_record(source: JsonRecord, record: JsonRecord, status: str | None = None) -> JsonRecord:
    source_id = str(source.get("id") or record.get("source_id") or "").strip()
    thread_id = _thread_key(record)
    heat_score, heat_label = _heat_score_for_record(record)
    return {
        "id": f"{source_id}:{thread_id}",
        "sourceId": source_id,
        "sourceLabel": str(source.get("label") or source_id),
        "sourceState": source.get("state"),
        "threadId": thread_id,
        "conversationId": record.get("conversation_id") or record.get("source_record_id"),
        "contactId": record.get("contact_id"),
        "personName": _record_person_name(record),
        "channel": _channel_label(source_id, source, record),
        "latestText": _latest_text(record),
        "latestAt": _record_timestamp(record),
        "direction": str(record.get("direction") or "").strip() or None,
        "messageCount": _safe_int(record.get("total_messages") or record.get("message_count"), 1),
        "inboundCount": _safe_int(record.get("inbound_count")),
        "outboundCount": _safe_int(record.get("outbound_count")),
        "heatScore": heat_score,
        "heatLabel": heat_label,
        "status": status or "open",
        "record": _list_record_snapshot(record),
    }


from elevate_cli.source_connector_modules.record_snapshots import (
    _LIST_RECORD_FIELDS,
    _compact_list_text,
    _list_record_snapshot,
)

from elevate_cli.source_connector_modules.draft_helpers import (
    _TEMPLATE_TOKEN_RE,
    _draft_from_task,
    _draft_from_thread,
    _draft_recipient,
    _draft_text_for_task,
    _fallback_draft_for_thread,
    _first_name_from_person,
    _is_message_draft_task,
    _outreach_lane_for_thread,
    _record_field,
    _render_outreach_template,
    _select_thread_template,
    _task_key,
    _template_channel_for_thread,
    _template_values_for_thread,
    _templated_draft_for_thread,
)

from elevate_cli.source_connector_modules.profile_helpers import (
    SOCIAL_INTENT_WORDS,
    SOCIAL_SOURCE_IDS,
    _email_key,
    _is_social_intent,
    _merge_profile,
    _merge_profile_verifiers,
    _name_key,
    _phone_key,
    _profile_contact_values,
    _profile_label,
    _profile_match_keys,
    _profile_verifiers,
    _profiles_from_threads,
    _source_has_inbox_records,
    _source_record_counts,
    _string_values,
)


def _replace_jsonl(path: Path, records: list[JsonRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp_path.replace(path)
    path_key = str(path)
    for cache_key in list(_JSONL_RECORD_CACHE):
        if cache_key[0] == path_key:
            _JSONL_RECORD_CACHE.pop(cache_key, None)
    _JSONL_COUNT_CACHE.pop(path_key, None)


# ─── Snapshot lock (cross-file consistency) ───────────────────────────────
#
# A CRM sync rewrites four files (contacts.jsonl, conversations.jsonl,
# lead-events.jsonl, tasks.jsonl) and a leads request reads all four. Per
# Codex audit P1 (2026-05-05) the per-file ``Path.replace`` is atomic
# alone but readers can still see torn snapshots between renames. The
# shared lock below brackets the writer's full multi-file rewrite and
# any reader that needs cross-file consistency. Best-effort — fcntl is
# advisory; nothing crashes if a caller forgets to use it.

@contextlib.contextmanager
def _snapshot_writer_lock(source_dir: Path):
    """Exclusive lock for a multi-file CRM snapshot rewrite. Wrap the
    full block of ``_replace_jsonl`` calls that should land together."""
    source_dir.mkdir(parents=True, exist_ok=True)
    lock_path = source_dir / ".snapshot.lock"
    lock_path.touch(exist_ok=True)
    fh = lock_path.open("a+")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass  # Best-effort: never block sync on lock failure.
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


@contextlib.contextmanager
def _snapshot_reader_lock(source_dir: Path):
    """Shared lock for cross-file reads. Wrap the block where a request
    reads multiple JSONL files that must agree (e.g. ``_read_source_inbox``)."""
    if not source_dir.exists():
        # Nothing written yet — no torn-snapshot risk.
        yield
        return
    lock_path = source_dir / ".snapshot.lock"
    if not lock_path.exists():
        # Writer hasn't run yet, nothing to coordinate with.
        yield
        return
    fh = lock_path.open("r")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        except OSError:
            pass
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def _configured_composio_server(config: dict[str, Any]) -> JsonRecord | None:
    servers = _as_dict(config.get("mcp_servers"))
    for name, raw_server in servers.items():
        server = _as_dict(raw_server)
        args = server.get("args")
        haystack_parts = [
            str(name),
            str(server.get("url") or ""),
            str(server.get("command") or ""),
            " ".join(str(item) for item in args) if isinstance(args, list) else str(args or ""),
        ]
        if "composio" not in " ".join(haystack_parts).lower():
            continue
        return {
            "name": str(name),
            "transport": "http" if server.get("url") else "stdio",
            "url": str(server.get("url") or ""),
            "command": str(server.get("command") or ""),
        }
    return None


from elevate_cli.source_connector_modules.apple_messages import (
    APPLE_EPOCH,
    _apple_dt,
    _apple_messages_chat_db_path,
    _apple_messages_source_dir,
    _init_apple_index_db,
    _load_chat_participants,
    _looks_like_fda_denied,
    _sqlite_uri,
    _update_span,
    _write_blocked_apple_messages_source,
    _write_paused_apple_messages_source,
    get_apple_messages_directions,
    initialize_apple_messages_source,
    set_apple_messages_directions,
)


def _state_from_status(source_exists: bool, status: JsonRecord | None) -> str:
    if not source_exists and not status:
        return "not_configured"
    if not status:
        return "needs_operator"
    if status.get("blocked") is True:
        return "blocked"
    if status.get("connected") is True:
        return "connected"
    if status.get("import_only") is True:
        return "import_only"
    if str(status.get("last_error") or "").strip():
        return "error"
    return "needs_operator"


def _connector_recovery(
    *,
    source_id: str,
    state: str,
    owner_agent: str,
    last_error: str | None,
    next_operator_step: str | None,
) -> JsonRecord:
    """Classify the operator-facing recovery path for connector rows."""
    if state in {"connected", "import_only"}:
        return {
            "recoveryKind": "ready",
            "recoverySeverity": "none",
            "recoveryOwner": owner_agent,
            "recoveryAction": "",
        }
    if next_operator_step:
        action = next_operator_step
    elif source_id == "social":
        action = (
            "Open the Composio panel, verify the API key and connected accounts, "
            "then run the Social connector again."
        )
    elif state == "not_configured":
        action = "Open setup chat to create this connector's source files."
    elif state == "blocked":
        action = "Resolve the listed permission or credential blocker, then click Refresh."
    elif state == "error":
        action = "Review the last connector error, fix the upstream service or credential, then run again."
    else:
        action = "Open setup chat or copy the prompt for the owner agent to finish this connector."

    if state == "not_configured":
        kind = "missing_config"
        severity = "info"
    elif state == "blocked":
        kind = "operator_blocked"
        severity = "warning"
    elif state == "error":
        kind = "upstream_error"
        severity = "warning"
    else:
        kind = "needs_operator"
        severity = "info"

    return {
        "recoveryKind": kind,
        "recoverySeverity": severity,
        "recoveryOwner": owner_agent,
        "recoveryAction": action,
        "recoveryError": last_error or "",
    }


def _blueprint(source_id: str) -> JsonRecord | None:
    return next((item for item in SOURCE_CONNECTION_BLUEPRINTS if item["id"] == source_id), None)


def _mutable_source_exists(source_root: Path, source_id: str) -> bool:
    return bool(
        _blueprint(source_id)
        or (
            source_id.startswith("composio-")
            and "/" not in source_id
            and "\\" not in source_id
            and _source_dir(source_root, source_id).is_dir()
        )
    )


# ─── Per-source operational prompts ────────────────────────────────────
#
# Each prompt describes the EXACT code path that runs when the operator
# clicks "Run prompt" for that source. For wired sources (apple-messages,
# crm, social) it's a deterministic shell call; for not-yet-built sources
# it's the canonical contract an agent should follow to build it.
#
# Update these whenever the implementation changes — they are the
# operator/agent-facing source of truth for what this connector does.


PromptRenderer = Callable[[], str]


_WIRED_SOURCE_PROMPTS: dict[str, str | PromptRenderer] = {
    "apple-messages": _render_apple_messages_agent_prompt,

    "crm": "__CRM_DYNAMIC__",  # rendered at runtime by _render_crm_prompt()

    "social": _render_social_agent_prompt,

    "xposure-pcs": _render_xposure_pcs_agent_prompt,

    "buyer-brief": _render_buyer_brief_agent_prompt,

    "xposure-pcs-views": _render_xposure_pcs_views_agent_prompt,
}


def _render_crm_prompt() -> str:
    """Build a task-first CRM prompt with live state baked in.

    Resolves the configured provider (admin profile → config fallback) and
    peeks at last sync + contact count. The job is always the same: run
    `elevate sync crm` to backfill the operator's CRM into operational Postgres.
    Provider + credential are read from disk by the CLI — don't ask the user.
    """
    config = load_config()
    provider, _api_key, crm, _env = _resolve_crm_context(config)
    provider_label = _provider_label(provider) if provider else "CRM"

    last_sync = None
    contact_count = 0
    try:
        info = get_source_root_info(config)
        source_root = Path(info["sourceRoot"])
        source_dir = _source_dir(source_root, "crm")
        source_meta = _read_json(source_dir / "source.json")
        if isinstance(source_meta, dict):
            last_sync = source_meta.get("last_sync_at")
        contact_count = _count_jsonl(source_dir / "contacts.jsonl")
    except Exception:
        pass

    sync_cmd = _local_sync_command("crm")
    file_cmd = _source_file_count_commands("crm")
    counts_cmd = _local_counts_command({
        "contacts": "SELECT COUNT(*) AS n FROM contacts",
        "lifecycle_events": (
            "SELECT COUNT(*) AS n FROM events WHERE kind = 'lifecycle_change'"
        ),
        "conversations": "SELECT COUNT(*) AS n FROM conversations",
        "identities": "SELECT COUNT(*) AS n FROM identities",
        "identity_conflicts_pending": (
            "SELECT COUNT(*) AS n FROM identity_conflicts WHERE resolved_at IS NULL"
        ),
    })

    return (
        "TASK\n"
        f"Backfill the operator's {provider_label} CRM into Elevate's operational Postgres DB,\n"
        f"then VERIFY the sync actually succeeded end-to-end. Don't trust the CLI's\n"
        f"exit code alone — check the resulting data with your own eyes. Do not ask\n"
        f"the operator for the API key; the CLI reads it from ~/.elevate/.env. If\n"
        f"the CLI raises a missing-key error, surface that error verbatim and stop.\n\n"
        "CURRENT STATE (snapshot at render time — verify against live values)\n"
        f"  provider:       {provider_label} ({provider or 'unset'})\n"
        f"  contacts in source snapshot: {contact_count}\n"
        f"  last sync:      {last_sync or 'never'}\n\n"
        "DO THIS (every step. Don't skip the verification steps.)\n"
        f"1. Run the local sync command:\n   `{sync_cmd}`\n"
        "2. Wait for it to finish (paginated full backfill — may take a few minutes).\n"
        "   Watch stderr for HTTP 4xx/5xx, rate-limit, or auth errors. Do not silently\n"
        "   ignore non-zero exit codes.\n"
        "3. VERIFY the source files were written (jsonl, fresh timestamps):\n"
        "   ```bash\n"
        f"{file_cmd}\n"
        "   ```\n"
        "   Note: jsonl line counts may be lower than source.json record_counts because\n"
        "   the jsonl is the latest snapshot (may be incremental), while record_counts\n"
        "   is cumulative across all syncs. Use record_counts for the totals.\n"
        "4. VERIFY the walker wrote rows into the operational Postgres DB (real schema —\n"
        "   these are the only tables the walker actually populates):\n"
        "   ```bash\n"
        f"{counts_cmd}\n"
        "   ```\n"
        "   Counts should be > 0 and roughly match source.json record_counts. If DB\n"
        "   is empty but jsonl is populated, the writethrough is broken — flag it loudly.\n"
        "   NOTE: there is no `tasks` table by design — tasks live as JSONL only\n"
        "   (see reads.py). Don't query it. There is no `lead_events` table either —\n"
        "   lead lifecycle changes are stored in `events` with kind='lifecycle_change'.\n"
        "   DO NOT touch ~/.elevate/data/operational.db — that SQLite file is deprecated.\n"
        "5. Spot-check 2 real rows are coherent (use REAL column names):\n"
        "   ```bash\n"
        f"{_local_python_prefix()} - <<'PY'\n"
        "from elevate_cli.data import connect\n"
        "with connect() as conn:\n"
        "    rows = conn.execute(\"\"\"\n"
        "        SELECT id, display_name, primary_phone, primary_email\n"
        "        FROM contacts\n"
        "        ORDER BY updated_at DESC\n"
        "        LIMIT 2\n"
        "    \"\"\").fetchall()\n"
        "    for row in rows:\n"
        "        print(dict(row))\n"
        "PY\n"
        "   ```\n"
        "   Both rows should have a real display_name plus primary_phone OR primary_email.\n"
        "   If they're empty strings or duplicates, the adapter mapping is broken — flag it.\n"
        "6. Report back with a CSV-style summary (use REAL table/column names):\n"
        "     contacts_jsonl=N, conversations_jsonl=N, lead_events_jsonl=N, tasks_jsonl=N,\n"
        "     contacts_db=N, lifecycle_events_db=N, conversations_db=N, identities_db=N,\n"
        "     identity_conflicts_pending=N, last_sync_at=<iso>, record_counts_total=N,\n"
        "     errors=<count or 'none'>\n"
        "   Plus a one-line verdict: HEALTHY / DEGRADED / FAILED and what the operator\n"
        "   should look at next (e.g. 'review N identity_conflicts before merging').\n\n"
        "OUTCOME\n"
        "  Success = both the source jsonl files and operational Postgres tables hold the\n"
        "  same row counts (within rounding), the dashboard's /leads, /admin, /today\n"
        "  surfaces show live data, and any cross-CRM duplicates land in\n"
        "  identity_conflicts for human merge (NEVER auto-merge —\n"
        "  merge_contacts requires actor.startswith(\"human\"))."
    )


def source_prompt_for(source_id: str) -> str:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return ""
    surfaces = ", ".join(UI_BY_SOURCE.get(source_id, ["Settings"]))
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")

    wired = _WIRED_SOURCE_PROMPTS.get(source_id)
    if wired:
        # CRM is rendered live so the agent gets current provider + credential
        # state, not a generic stub.
        if source_id == "crm":
            wired_text = _render_crm_prompt()
        elif callable(wired):
            wired_text = wired()
        else:
            wired_text = wired

        if source_id in AGENT_SESSION_SOURCE_IDS:
            return (
                f"{blueprint['source']} — owner_agent={owner}, surfaces: {surfaces}\n\n"
                f"{wired_text}"
            )

        # Live inline source — describe exactly what runs. Append the canonical
        # contract so the agent / operator still sees the universal storage
        # layout and identity rules.
        return (
            f"{blueprint['source']} — owner_agent={owner}, surfaces: {surfaces}\n\n"
            f"{wired_text}\n\n"
            f"Canonical contract (applies to every Elevate source):\n{CONNECTION_CONTRACT}\n"
        )

    # Not-yet-wired source — emit the agent build brief that follows the
    # canonical pattern, with apple-messages / crm / social pointed at as
    # working reference implementations.
    extra_contract = f"\n\n{COMPOSIO_SOCIAL_CONTRACT}" if source_id == "social" else ""
    return (
        f"You are wiring {blueprint['source']} into Elevate Agent.\n"
        f"source_id={source_id}, owner_agent={owner}, target UI surfaces: {surfaces}\n\n"
        "STATUS: No live pull code exists for this source yet. This prompt creates a\n"
        "tasks.jsonl entry with `task_type=connector_setup` and `agent_prompt` embedded.\n"
        "An agent (Jimmy via dispatch-bridge, or the operator) reads this prompt and\n"
        "builds the real connector following the canonical contract below.\n\n"
        f"Information Elevate needs:\n{blueprint['informationNeeded']}\n\n"
        "Reference implementations to mirror:\n"
        "- Local-file source (chat.db / AddressBook): see `initialize_apple_messages_source`\n"
        "  in `elevate_cli/source_connectors.py` + `elevate_cli/apple_contacts.py`.\n"
        "- API source with pagination + enrichment: see `sync_lofty_crm_source` and the\n"
        "  generic adapter pattern in `elevate_cli/crm_adapters/`.\n"
        "- Messages-only source needing synthesized contacts/conversations: see\n"
        "  `elevate_cli/composio_inbound.py:synthesize_canonical_files`.\n\n"
        f"{CONNECTION_CONTRACT}{extra_contract}\n\n"
        "When the connector is built:\n"
        f"- If the source is deterministic, add a tuple to `elevate_cli/sync_scheduler.py:_JOBS`\n"
        f"  so `elevate db init` installs the recurring launchd plist on every fresh install.\n"
        f"  If it launches an AI/browser agent, register it in app Automations instead.\n"
        f"- Add `{source_id}` to the routing block in\n"
        f"  `elevate_cli/web_server.py:update_source_connector` so the UI Run button fires it.\n"
        f"- Add the relevant identity kind to the `_SOURCE_TO_HANDLE_KIND`,\n"
        f"  `_CRM_PROVIDER_TO_IDENTITY_KIND`, or `_TOOLKIT_TO_HANDLE_KIND` registry —\n"
        f"  do NOT branch in walker code.\n\n"
        f"Done when:\n{blueprint['successSignal']}\n"
        "- And: clicking Run on the connector card pulls live records into\n"
        "  the operational Postgres DB on a fresh install with no manual steps beyond providing\n"
        "  the operator's credential / file path.\n"
    )


def _initialize_behavior(source_id: str) -> str:
    if source_id == "apple-messages":
        return "local_messages_import"
    if source_id == "social":
        return "composio_social_setup"
    return "agent_setup_task"


def connector_view(
    source_root: Path,
    source_id: str,
    *,
    include_prompt: bool = True,
) -> JsonRecord | None:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return None
    source_dir = _source_dir(source_root, source_id)
    source_path = source_dir / "source.json"
    status_path = source_dir / "status.json"
    artifacts_dir = source_dir / "artifacts"
    source = _read_json(source_path)
    status = _read_json(status_path)
    source_exists = bool(source)
    state = _state_from_status(source_exists, status)
    record_counts = {
        file_name.removesuffix(".jsonl"): _count_jsonl(source_dir / file_name)
        for file_name in JSONL_FILES
    }
    enabled_surfaces = source.get("enabled_ui_surfaces") if isinstance(source, dict) else None
    if not isinstance(enabled_surfaces, list):
        enabled_surfaces = UI_BY_SOURCE.get(source_id, [])
    owner_agent = ""
    if isinstance(source, dict):
        owner_agent = str(source.get("owner_agent") or "").strip()
    label = blueprint["source"]
    if isinstance(source, dict):
        label = str(source.get("provider") or source.get("account_label") or label).strip() or label
    owner_agent = owner_agent or OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    last_error = (
        str(status.get("last_error") or "").strip()
        if isinstance(status, dict) and status.get("last_error")
        else None
    )
    next_operator_step = (
        str(status.get("next_operator_step") or "").strip()
        if isinstance(status, dict) and status.get("next_operator_step")
        else (
            "Initialize this source to create the connector files."
            if state == "not_configured"
            else None
        )
    )
    recovery = _connector_recovery(
        source_id=source_id,
        state=state,
        owner_agent=owner_agent,
        last_error=last_error,
        next_operator_step=next_operator_step,
    )

    return {
        "id": source_id,
        "label": label,
        "category": blueprint.get("category", "admin"),
        "description": blueprint.get("description") or "",
        "wired": source_id in WIRED_SOURCE_IDS,
        "state": state,
        "sourceExists": source_exists,
        "sourceDir": str(source_dir),
        "sourcePath": str(source_path),
        "statusPath": str(status_path),
        "artifactsDir": str(artifacts_dir),
        "connectionType": source.get("connection_type") if isinstance(source, dict) else None,
        "syncMode": source.get("sync_mode") if isinstance(source, dict) else None,
        "authStatus": source.get("auth_status") if isinstance(source, dict) else None,
        "initializeBehavior": _initialize_behavior(source_id),
        "runMode": (
            "agent_session"
            if source_id in AGENT_SESSION_SOURCE_IDS
            else ("server_inline" if source_id in WIRED_SOURCE_IDS else "agent_setup_task")
        ),
        "ownerAgent": owner_agent,
        "enabledUiSurfaces": [str(item) for item in enabled_surfaces if str(item).strip()],
        "connected": bool(status and status.get("connected") is True),
        "importOnly": bool(status and status.get("import_only") is True),
        "blocked": bool(status and status.get("blocked") is True),
        "lastError": last_error,
        "nextOperatorStep": next_operator_step,
        **recovery,
        "lastCheckedAt": status.get("last_checked_at") if isinstance(status, dict) else None,
        "recordCounts": record_counts,
        "prompt": source_prompt_for(source_id) if include_prompt else "",
    }


def build_source_connectors_response(
    config: dict[str, Any] | None = None,
    *,
    include_prompts: bool = True,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(
            source_root,
            str(item["id"]),
            include_prompt=include_prompts,
        )) is not None
    ]
    return {
        **info,
        "blueprints": [
            dict(
                item,
                prompt=source_prompt_for(str(item["id"])) if include_prompts else "",
            )
            for item in SOURCE_CONNECTION_BLUEPRINTS
        ],
        "promptCategories": list(SOURCE_PROMPT_CATEGORIES),
        "categories": [dict(c) for c in SOURCE_CATEGORIES],
        "connectors": connectors,
    }


def build_source_records_response(
    source_id: str,
    *,
    config: dict[str, Any] | None = None,
    limit: int = 12,
) -> JsonRecord:
    """Return normalized local source records for an operator-facing dashboard.

    This is intentionally record-shaped, not connector-shaped: pages such as
    Leads should be able to render the latest client messages without exposing
    backend setup internals.
    """
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source = connector_view(source_root, source_id)
    if source is None:
        raise ValueError(f"Unknown source connector: {source_id}")

    source_dir = _source_dir(source_root, source_id)
    safe_limit = max(1, min(int(limit or 12), 100))
    # Shared lock so this multi-file read sees a consistent snapshot
    # against any in-flight CRM sync (Codex audit P1, 2026-05-05).
    with _snapshot_reader_lock(source_dir):
        records = {
            "contacts": _read_jsonl_records(source_dir / "contacts.jsonl", limit=safe_limit),
            "conversations": _read_jsonl_records(source_dir / "conversations.jsonl", limit=safe_limit),
            "messages": _read_jsonl_records(source_dir / "messages.jsonl", limit=safe_limit, tail=True),
            "messageDays": _read_jsonl_records(source_dir / "message-days.jsonl", limit=safe_limit),
            "leadEvents": _read_jsonl_records(source_dir / "lead-events.jsonl", limit=safe_limit),
            "tasks": _read_jsonl_records(source_dir / "tasks.jsonl", limit=safe_limit),
        }
    return {
        **info,
        "sourceId": source_id,
        "source": source,
        "limit": safe_limit,
        "records": records,
    }


def _combined_env(config: dict[str, Any]) -> dict[str, str]:
    values = dict(load_env())
    tools_env = _candidate_tools_root(config) / ".env"
    try:
        if tools_env.exists():
            for line in tools_env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key and key not in values:
                    values[key] = value.strip().strip("\"'")
    except Exception:
        pass
    return values


def _candidate_records_for_source(source_dir: Path, source: JsonRecord, safe_limit: int) -> list[JsonRecord]:
    records = _read_jsonl_records(source_dir / "conversations.jsonl", limit=safe_limit)
    if not records and str(source.get("category") or "") == "leads":
        records = _read_jsonl_records(source_dir / "contacts.jsonl", limit=safe_limit)
    if not records:
        records = _read_jsonl_records(source_dir / "messages.jsonl", limit=safe_limit, tail=True)
    return records


def _composio_connector_view(source_root: Path, source_id: str) -> JsonRecord | None:
    """Synthesize a connector_view-shaped record for a composio-<toolkit> dir.

    The composio inbound puller writes per-toolkit dirs (composio-gmail,
    composio-slack, etc.) that aren't in SOURCE_CONNECTION_BLUEPRINTS. The
    inbox builder iterates the static blueprints, so without this synthetic
    view those messages never reach /leads.
    """
    source_dir = _source_dir(source_root, source_id)
    if not source_dir.exists():
        return None
    record_counts = {
        file_name.removesuffix(".jsonl"): _count_jsonl(source_dir / file_name)
        for file_name in JSONL_FILES
    }
    if not any(record_counts.values()):
        return None
    toolkit = source_id.removeprefix("composio-") or source_id
    return {
        "id": source_id,
        "label": f"Composio — {toolkit}",
        "category": "messages",
        "state": "connected",
        "sourceExists": True,
        "sourceDir": str(source_dir),
        "sourcePath": str(source_dir / "source.json"),
        "statusPath": str(source_dir / "status.json"),
        "artifactsDir": str(source_dir / "artifacts"),
        "connectionType": "composio",
        "syncMode": "poll",
        "authStatus": None,
        "initializeBehavior": "composio_social_setup",
        "runMode": "server_inline",
        "ownerAgent": OWNER_BY_SOURCE.get("social", "Executive Assistant"),
        "enabledUiSurfaces": UI_BY_SOURCE.get("social", []),
        "connected": True,
        "importOnly": False,
        "blocked": False,
        "lastError": None,
        "nextOperatorStep": None,
        "lastCheckedAt": None,
        "recordCounts": record_counts,
        "prompt": "",
    }


def _discover_composio_views(source_root: Path) -> list[JsonRecord]:
    """List synthetic views for every composio-<toolkit> dir on disk."""
    if not source_root.exists():
        return []
    views: list[JsonRecord] = []
    for child in sorted(source_root.iterdir()):
        if not child.is_dir() or not child.name.startswith("composio-"):
            continue
        view = _composio_connector_view(source_root, child.name)
        if view is not None:
            views.append(view)
    return views


def build_source_inbox_response(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 16,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    safe_limit = max(1, min(int(limit or 16), 5000))
    draft_limit = max(safe_limit, SOURCE_INBOX_DRAFT_QUEUE_LIMIT)
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]), include_prompt=False)) is not None
    ]
    # Fold in the composio per-toolkit dirs so messages pulled by the
    # inbound puller surface in /leads alongside Apple Messages and CRM.
    existing_ids = {str(view.get("id") or "") for view in connectors}
    for extra in _discover_composio_views(source_root):
        if str(extra.get("id") or "") in existing_ids:
            continue
        connectors.append(extra)

    threads: list[JsonRecord] = []
    drafts: list[JsonRecord] = []
    skipped_drafts: list[JsonRecord] = []
    skipped_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    hidden_counts = {"done": 0, "archived": 0}
    totals = {
        "sources": 0,
        "threads": 0,
        "messages": 0,
        "conversations": 0,
        "contacts": 0,
        "hotThreads": 0,
        "drafts": 0,
    }
    seen: set[str] = set()
    seen_drafts: set[str] = set()
    # Canonical key: (source_id, thread_id) → "this thread already has a
    # real persisted draft, don't stack a fallback on top." Codex audit
    # P1 (2026-05-05): real AI drafts must supersede fallback drafts.
    seen_thread_drafts: set[tuple[str, str]] = set()
    task_state_by_source: dict[str, JsonRecord] = {}

    # Phase 6: enrich each thread with lead-scorer meta (score / label / reason)
    # so lane skills + dashboard see scorer state alongside heatLabel. Bulk-load
    # BEFORE we walk records — we need the dead label to short-circuit
    # enumeration so dead threads don't pollute the hotThreads counter or the
    # default leads view. Dashboard still shows them via /api/threads/meta?label=dead.
    try:
        from elevate_cli import outreach_db as _odb
        _meta_by_key: dict[tuple[str, str], dict[str, Any]] = {
            (m["sourceId"], m["threadId"]): m for m in _odb.list_thread_meta(limit=1000)
        }
    except Exception:
        _meta_by_key = {}

    for source in connectors:
        counts = _source_record_counts(source)
        totals["sources"] += 1 if _source_has_inbox_records(source) else 0
        totals["messages"] += _safe_int(counts.get("messages"))
        totals["conversations"] += _safe_int(counts.get("conversations"))
        totals["contacts"] += _safe_int(counts.get("contacts"))
        source_id = str(source.get("id") or "")
        source_dir = _source_dir(source_root, source_id)
        ui_state = _read_source_ui_state(source_dir)
        thread_states = _as_dict(ui_state.get("threads"))
        task_states = _as_dict(ui_state.get("tasks"))
        task_state_by_source[source_id] = task_states

        for record in _candidate_records_for_source(source_dir, source, safe_limit):
            thread_id = _thread_key(record)
            state = _as_dict(thread_states.get(thread_id))
            status = str(state.get("status") or "open")
            if status in ("done", "archived"):
                hidden_counts[status] = hidden_counts.get(status, 0) + 1
                continue
            thread = _thread_from_record(source, record, status=status)
            if thread["id"] in seen:
                continue

            # Attach scorer meta and short-circuit dead threads BEFORE the
            # hotThreads counter so the dashboard total reflects actionable leads.
            _meta = _meta_by_key.get((str(thread.get("sourceId") or ""), str(thread.get("threadId") or "")))
            if _meta:
                thread["score"] = _meta.get("score")
                thread["leadLabel"] = _meta.get("label")
                thread["scoreReason"] = _meta.get("reason")
                thread["scoredAt"] = _meta.get("scoredAt")
            else:
                thread["score"] = None
                thread["leadLabel"] = None
                thread["scoreReason"] = None
                thread["scoredAt"] = None

            if thread.get("leadLabel") == "dead":
                continue

            seen.add(thread["id"])
            if thread["heatLabel"] == "hot":
                totals["hotThreads"] += 1
            threads.append(thread)

        # 2026-05-26: drop tail=True. The CRM sync's tasks.jsonl rewrite
        # preserves drafts at the HEAD of the file (preserved_tasks +
        # task_records, source_connectors.py:3799) and then appends fresh
        # lead_follow_up rows. tail=True was the right pick before the
        # preserve change landed (c6ba97cae) — at that point drafts were
        # always at the bottom because the file was rewritten from scratch.
        # Now the opposite is true: tail=True reads only follow-up
        # tombstones and silently drops every message_draft. In a large Lofty
        # workspace this previously meant 182 pending drafts -> 0 in the inbox.
        # Bump the limit so a head-scan still picks them all up even after
        # several sync cycles.
        for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
            if not _is_message_draft_task(record):
                continue
            task_id = _task_key(record)
            state = _as_dict(task_states.get(task_id))
            status = str(state.get("status") or record.get("status") or "pending").lower()
            thread_meta = _meta_by_key.get((source_id, _thread_key(record)))
            if status == "skipped":
                updated_dt = _parse_record_dt(state.get("updated_at"))
                if updated_dt and updated_dt >= skipped_cutoff:
                    draft = _draft_from_task(source, record, state)
                    draft["skippedAt"] = state.get("updated_at")
                    if thread_meta:
                        draft["score"] = thread_meta.get("score")
                        draft["leadLabel"] = thread_meta.get("label")
                        draft["scoreReason"] = thread_meta.get("reason")
                    skipped_drafts.append(draft)
                continue
            if status in {"approved", "done", "archived", "cancelled"}:
                continue
            draft = _draft_from_task(source, record, state)
            if thread_meta:
                draft["score"] = thread_meta.get("score")
                draft["leadLabel"] = thread_meta.get("label")
                draft["scoreReason"] = thread_meta.get("reason")
            if draft["id"] in seen_drafts:
                continue
            seen_drafts.add(draft["id"])
            # Mark this thread as already having a real draft — fallback
            # generation below must skip it (Codex P1, 2026-05-05).
            persisted_thread_id = str(draft.get("threadId") or "").strip()
            if persisted_thread_id:
                seen_thread_drafts.add((source_id, persisted_thread_id))
            drafts.append(draft)

    threads.sort(
        key=lambda item: (
            _safe_int(item.get("heatScore")),
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    source_by_id = {str(source.get("id") or ""): source for source in connectors}
    for thread in threads:
        if len(drafts) >= draft_limit:
            break
        if str(thread.get("direction") or "") != "inbound":
            continue
        if str(thread.get("heatLabel") or "") not in {"hot", "warm"} and not _is_social_intent(
            source_by_id.get(str(thread.get("sourceId") or ""), {}),
            thread,
        ):
            continue
        if _is_automated_sender_record(_as_dict(thread.get("record")) or thread):
            continue
        source_id = str(thread.get("sourceId") or "")
        thread_id_str = str(thread.get("threadId") or "")
        # Canonical key: if a real persisted draft already covers this
        # (source_id, thread_id), skip the fallback regardless of how
        # Codex chose to name the task_id (Codex P1, 2026-05-05).
        if thread_id_str and (source_id, thread_id_str) in seen_thread_drafts:
            continue
        task_id = f"thread-draft:{thread_id_str}"
        state = _as_dict(task_state_by_source.get(source_id, {}).get(task_id))
        status = str(state.get("status") or "").lower()
        if status in {"approved", "skipped", "done", "archived", "cancelled"}:
            continue
        generated_id = f"{source_id}:{task_id}"
        if generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
        if thread_id_str:
            seen_thread_drafts.add((source_id, thread_id_str))
        generated_draft = _draft_from_thread(source_by_id.get(source_id, {}), thread)
        if state.get("draft_text"):
            generated_draft["draftText"] = str(state.get("draft_text"))
        generated_draft["score"] = thread.get("score")
        generated_draft["leadLabel"] = thread.get("leadLabel")
        generated_draft["scoreReason"] = thread.get("scoreReason")
        drafts.append(generated_draft)

    drafts.sort(
        key=lambda item: (
            1 if item.get("generated") is False else 0,
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    profiles = _profiles_from_threads(threads, source_by_id)
    profile_state_entries = _as_dict(_read_profile_state(source_root).get("profiles"))
    # SQLite contacts.pipeline_status is the source of truth when a profile
    # has a linked contactId; fall back to the legacy JSON state file
    # otherwise (e.g. composio inbox threads with no CRM contact yet).
    db_status_by_contact: dict[str, dict[str, Any]] = {}
    try:
        from elevate_cli.data import connect as _db_connect
        contact_ids: list[str] = []
        for p in profiles:
            for cid in p.get("contactIds") or []:
                cid_s = str(cid or "").strip()
                if cid_s:
                    contact_ids.append(cid_s)
        if contact_ids:
            with _db_connect() as _conn:
                placeholders = ",".join("?" for _ in contact_ids)
                cur = _conn.execute(
                    f"SELECT id, pipeline_status, pipeline_status_set_at "
                    f"FROM contacts WHERE id IN ({placeholders})",
                    contact_ids,
                )
                for row in cur.fetchall():
                    db_status_by_contact[row["id"]] = {
                        "status": row["pipeline_status"],
                        "updated_at": row["pipeline_status_set_at"],
                    }
    except Exception:
        db_status_by_contact = {}
    for profile in profiles:
        db_entry: dict[str, Any] | None = None
        for cid in profile.get("contactIds") or []:
            entry = db_status_by_contact.get(str(cid))
            if entry and entry.get("status"):
                db_entry = entry
                break
        if db_entry is not None:
            profile["status"] = db_entry.get("status")
            profile["statusUpdatedAt"] = db_entry.get("updated_at")
        else:
            entry = _as_dict(profile_state_entries.get(str(profile.get("id") or "")))
            profile["status"] = entry.get("status")
            profile["statusUpdatedAt"] = entry.get("updated_at")
    visible_threads = threads[:safe_limit]
    totals["threads"] = len(threads)
    totals["drafts"] = len(drafts)
    totals["people"] = len(profiles)
    totals["crmPeople"] = sum(1 for profile in profiles if profile.get("hasCrm"))
    totals["conversationPeople"] = sum(1 for profile in profiles if profile.get("hasConversation"))
    totals["potentialLeads"] = sum(1 for profile in profiles if profile.get("isPotentialLead") and not profile.get("hasCrm"))
    skipped_drafts.sort(
        key=lambda item: _parse_record_dt(item.get("skippedAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    private_search_buyers = _read_private_search_buyers(source_root, limit=max(safe_limit, 50))
    # Real Apple Messages direction state + health for the /leads toggles and
    # the source-access banner. The banner must reflect REAL status (not a
    # hardcoded mock) and only nag when inbound is actually enabled: FDA is
    # only needed to READ chat.db, never to SEND.
    am_dirs = get_apple_messages_directions(config)
    am_status = _read_json(_source_dir(source_root, "apple-messages") / "status.json") or {}
    apple_messages = {
        "inbound": bool(am_dirs.get("inbound", True)),
        "outbound": bool(am_dirs.get("outbound", True)),
        "blocked": bool(am_dirs.get("inbound", True)) and bool(am_status.get("blocked")),
        "note": str(am_status.get("next_operator_step") or ""),
    }
    return {
        **info,
        "limit": safe_limit,
        "recordCounts": totals,
        "hiddenCounts": hidden_counts,
        "sources": connectors,
        "appleMessages": apple_messages,
        "profiles": profiles[:safe_limit],
        "threads": visible_threads,
        "drafts": drafts[:draft_limit],
        "skippedDrafts": skipped_drafts[: max(draft_limit, 50)],
        "privateSearchBuyers": private_search_buyers,
    }


def _collect_drafts_for_db_inbox(
    *,
    source_root: Path,
    connectors: list[JsonRecord],
    threads: list[JsonRecord],
    skipped_cutoff: datetime,
    max_drafts: int = SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
) -> tuple[list[JsonRecord], list[JsonRecord]]:
    """Build the same drafts/skippedDrafts buckets as
    :func:`build_source_inbox_response`, but driven by externally-provided
    ``connectors`` and ``threads`` lists (so the DB-primary builder can
    reuse the legacy draft pipeline without re-walking source dirs for
    threads).

    Codex audit P0 (2026-05-05): the DB readers were returning empty
    ``drafts`` / ``skippedDrafts`` arrays, which broke the /leads queue
    under ``ELEVATE_DATA_PRIMARY=db``. This helper collapses the
    persisted-draft + fallback-draft logic into a single shared codepath.
    """
    drafts: list[JsonRecord] = []
    skipped_drafts: list[JsonRecord] = []
    max_drafts = max(1, int(max_drafts or SOURCE_INBOX_DRAFT_QUEUE_LIMIT))
    seen_drafts: set[str] = set()
    seen_skipped_drafts: set[str] = set()
    seen_thread_drafts: set[tuple[str, str]] = set()
    task_state_by_source: dict[str, JsonRecord] = {}

    try:
        from elevate_cli import outreach_db as _odb
        _meta_by_key: dict[tuple[str, str], dict[str, Any]] = {
            (m["sourceId"], m["threadId"]): m for m in _odb.list_thread_meta(limit=1000)
        }
    except Exception:
        _meta_by_key = {}

    source_by_id = {str(s.get("id") or ""): s for s in connectors}

    for source in connectors:
        source_id = str(source.get("id") or "")
        source_dir = _source_dir(source_root, source_id)
        ui_state = _read_source_ui_state(source_dir)
        task_states = _as_dict(ui_state.get("tasks"))
        task_state_by_source[source_id] = task_states

        # 2026-05-26: drop tail=True. The CRM sync's tasks.jsonl rewrite
        # preserves drafts at the HEAD of the file (preserved_tasks +
        # task_records, source_connectors.py:3799) and then appends fresh
        # lead_follow_up rows. tail=True was the right pick before the
        # preserve change landed (c6ba97cae) — at that point drafts were
        # always at the bottom because the file was rewritten from scratch.
        # Now the opposite is true: tail=True reads only follow-up
        # tombstones and silently drops every message_draft. In a large Lofty
        # workspace this previously meant 182 pending drafts -> 0 in the inbox.
        # Bump the limit so a head-scan still picks them all up even after
        # several sync cycles.
        for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
            if not _is_message_draft_task(record):
                continue
            task_id = _task_key(record)
            state = _as_dict(task_states.get(task_id))
            status = str(state.get("status") or record.get("status") or "pending").lower()
            thread_meta = _meta_by_key.get((source_id, _thread_key(record)))
            if status == "skipped":
                updated_dt = _parse_record_dt(state.get("updated_at"))
                if updated_dt and updated_dt >= skipped_cutoff:
                    draft = _draft_from_task(source, record, state)
                    draft["skippedAt"] = state.get("updated_at")
                    if thread_meta:
                        draft["score"] = thread_meta.get("score")
                        draft["leadLabel"] = thread_meta.get("label")
                        draft["scoreReason"] = thread_meta.get("reason")
                    seen_skipped_drafts.add(str(draft.get("id") or ""))
                    skipped_drafts.append(draft)
                continue
            if status in {"approved", "done", "archived", "cancelled"}:
                continue
            draft = _draft_from_task(source, record, state)
            if thread_meta:
                draft["score"] = thread_meta.get("score")
                draft["leadLabel"] = thread_meta.get("label")
                draft["scoreReason"] = thread_meta.get("reason")
            if draft["id"] in seen_drafts:
                continue
            seen_drafts.add(draft["id"])
            persisted_thread_id = str(draft.get("threadId") or "").strip()
            if persisted_thread_id:
                seen_thread_drafts.add((source_id, persisted_thread_id))
            drafts.append(draft)

    def send_queue_draft(send: JsonRecord, *, skipped: bool = False) -> JsonRecord | None:
        source_id = str(send.get("sourceId") or "")
        thread_id_str = str(send.get("threadId") or "")
        if not source_id or not thread_id_str:
            return None
        source = source_by_id.get(source_id) or {"id": source_id, "label": source_id}
        payload = _as_dict(send.get("payload"))
        recipient = _as_dict(payload.get("recipient"))
        person_name = (
            str(recipient.get("person_name") or "").strip()
            or str(payload.get("person_name") or "").strip()
            or "Client"
        )
        draft_text = str(payload.get("draft_text") or "").strip() or "Draft text has not been generated yet."
        queue_id = str(send.get("id") or "")
        task_id = str(send.get("taskId") or queue_id)
        channel = str(send.get("channel") or "")
        draft: JsonRecord = {
            "id": f"{source_id}:send-queue:{queue_id}",
            "sourceId": source_id,
            "sourceLabel": str(source.get("label") or source_id),
            "taskId": task_id,
            "threadId": thread_id_str,
            "contactId": recipient.get("contact_id") or payload.get("contact_id"),
            "conversationId": recipient.get("conversation_id"),
            "personName": person_name,
            "channel": channel,
            "title": f"Approve first-touch draft for {person_name}",
            "draftText": draft_text,
            "context": "",
            "latestAt": str(send.get("updatedAt") or send.get("createdAt") or ""),
            "status": "skipped" if skipped else "pending",
            "approvalRequired": True,
            "generated": False,
            "fallback": False,
            "record": {},
        }
        if skipped:
            draft["skippedAt"] = str(send.get("updatedAt") or send.get("createdAt") or "")
        thread_meta = _meta_by_key.get((source_id, thread_id_str))
        if thread_meta:
            draft["score"] = thread_meta.get("score")
            draft["leadLabel"] = thread_meta.get("label")
            draft["scoreReason"] = thread_meta.get("reason")
        return draft

    # Source of truth: any send_queue row in pending_approval that isn't
    # already represented by a tasks.jsonl entry. Crons that write directly
    # to send_queue (e.g. run_fresh_first_touch_cron.py) sometimes race with
    # the tasks.jsonl append, or the jsonl head-of-file gets shadowed by
    # thousands of older lead_follow_up rows. Reading the PG table here
    # makes the /leads inbox self-healing.
    try:
        pending_sends = _odb.list_recent_sends(
            statuses=("pending_approval",), limit=max_drafts * 4
        )
    except Exception:
        pending_sends = []

    for send in pending_sends:
        if len(drafts) >= max_drafts:
            break
        synthesized = send_queue_draft(send)
        if not synthesized:
            continue
        source_id = str(synthesized.get("sourceId") or "")
        thread_id_str = str(synthesized.get("threadId") or "")
        if (source_id, thread_id_str) in seen_thread_drafts:
            continue
        generated_id = str(synthesized.get("id") or "")
        if not generated_id or generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
        seen_thread_drafts.add((source_id, thread_id_str))
        drafts.append(synthesized)

    try:
        skipped_sends = _odb.list_recent_sends(
            statuses=("skipped",), limit=max_drafts * 4
        )
    except Exception:
        skipped_sends = []

    for send in skipped_sends:
        updated_dt = _parse_record_dt(send.get("updatedAt"))
        if updated_dt and updated_dt < skipped_cutoff:
            continue
        synthesized = send_queue_draft(send, skipped=True)
        if not synthesized:
            continue
        generated_id = str(synthesized.get("id") or "")
        if not generated_id or generated_id in seen_skipped_drafts:
            continue
        seen_skipped_drafts.add(generated_id)
        skipped_drafts.append(synthesized)

    for thread in threads:
        if len(drafts) >= max_drafts:
            break
        if str(thread.get("direction") or "") != "inbound":
            continue
        if str(thread.get("heatLabel") or "") not in {"hot", "warm"} and not _is_social_intent(
            source_by_id.get(str(thread.get("sourceId") or ""), {}),
            thread,
        ):
            continue
        if _is_automated_sender_record(_as_dict(thread.get("record")) or thread):
            continue
        source_id = str(thread.get("sourceId") or "")
        thread_id_str = str(thread.get("threadId") or "")
        if thread_id_str and (source_id, thread_id_str) in seen_thread_drafts:
            continue
        task_id = f"thread-draft:{thread_id_str}"
        state = _as_dict(task_state_by_source.get(source_id, {}).get(task_id))
        status = str(state.get("status") or "").lower()
        if status in {"approved", "skipped", "done", "archived", "cancelled"}:
            continue
        generated_id = f"{source_id}:{task_id}"
        if generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
        if thread_id_str:
            seen_thread_drafts.add((source_id, thread_id_str))
        generated_draft = _draft_from_thread(source_by_id.get(source_id, {}), thread)
        if state.get("draft_text"):
            generated_draft["draftText"] = str(state.get("draft_text"))
        generated_draft["score"] = thread.get("score")
        generated_draft["leadLabel"] = thread.get("leadLabel")
        generated_draft["scoreReason"] = thread.get("scoreReason")
        drafts.append(generated_draft)

    drafts.sort(
        key=lambda item: (
            1 if item.get("generated") is False else 0,
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    skipped_drafts.sort(
        key=lambda item: _parse_record_dt(item.get("skippedAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    return drafts, skipped_drafts


from elevate_cli.source_connector_modules.private_search import (
    _PCS_BUYER_TAGS,
    _is_pcs_tag,
    _norm_email,
    _norm_phone,
    _pcs_tagged_crm_buyers,
    _read_private_search_buyers,
)


def _resolve_source_view(source_root: Path, source_id: str) -> JsonRecord | None:
    view = connector_view(source_root, source_id)
    if view is not None:
        return view
    if source_id.startswith("composio-"):
        return _composio_connector_view(source_root, source_id)
    return None


def _message_for_thread(record: JsonRecord) -> JsonRecord | None:
    # Thread drawer is the full-detail view — prefer `body` (untruncated)
    # over `text` (200-char snippet written by composio_inbound for the
    # inbox preview). Falls through to text/message/summary/title for
    # sources that don't split full vs preview.
    text = ""
    for key in ("body", "text", "message", "summary", "title"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            break
    sender = ""
    sender_payload = record.get("from") or record.get("sender") or {}
    if isinstance(sender_payload, dict):
        sender = str(sender_payload.get("name") or sender_payload.get("id") or "").strip()
    elif isinstance(sender_payload, str):
        sender = sender_payload.strip()
    direction = str(record.get("direction") or "").strip().lower() or None
    timestamp = _record_timestamp(record)
    if not text and not sender and not timestamp:
        return None
    return {
        "id": str(record.get("id") or record.get("source_record_id") or ""),
        "direction": direction or ("inbound" if sender else "outbound"),
        "sender": sender or None,
        "text": text,
        "timestamp": timestamp,
    }


def build_thread_context_response(
    source_id: str,
    thread_id: str,
    *,
    config: dict[str, Any] | None = None,
    limit: int = 200,
) -> JsonRecord:
    """Aggregate everything we know about a single thread for the drawer view.

    Pulls messages (filtered to this thread), the latest pending draft, prior
    sends from the queue, lead-scorer meta, and stub buckets for notes/activity
    so the UI can render placeholders until those endpoints land.
    """
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source = _resolve_source_view(source_root, source_id)
    if source is None:
        raise ValueError(f"Unknown source connector: {source_id}")

    safe_limit = max(20, min(int(limit or 200), 500))
    source_dir = _source_dir(source_root, source_id)

    # Frontend profiles emit threadIds as ``<source_id>:<thread_key>`` (see
    # ``_thread_from_record`` above). When the buyer-search drawer forwards
    # that string as the URL ``thread_id``, we end up looking for
    # ``crm:lofty-lead:1138...`` against contacts/conversations stored as
    # ``lofty-lead:1138...``. Strip the prefix defensively so both shapes
    # resolve.
    if thread_id.startswith(f"{source_id}:"):
        thread_id = thread_id[len(source_id) + 1 :]

    # Snapshot reader lock — keep messages/contacts/lead-events consistent
    # against any in-flight CRM sync (Codex audit P1, 2026-05-05).
    # 2026-05-26 fix: per-contact streaming for lead-events. Prior code did
    # `tail=True, limit=4000` which silently dropped activity/notes/tasks
    # for any contact whose events were ingested earlier than the last 4000
    # rows. With 2474 Lofty leads and 15455 lifetime events, every contact
    # past line ~11455 had an empty Property Activity panel.
    with _snapshot_reader_lock(source_dir):
        raw_messages = _read_jsonl_records(source_dir / "messages.jsonl", limit=2000, tail=True)
        # Targeted contact lookup: stream the whole file once and keep only
        # the row whose contact_id/id matches this thread. The prior
        # `_read_jsonl_records(limit=2000)` silently dropped any contact past
        # row 2000, breaking the Lead Score / Stage / Tags panel for hot
        # leads on CRMs with >2000 contacts (one Lofty workspace hit this at
        # 2474 contacts — every hot lead appended after row 2000 returned
        # `lead: null` in the drawer). Streaming a single-row pluck is O(n)
        # but unbounded by file size and uses constant memory.
        lead_record: JsonRecord | None = _find_jsonl_record_by_id(
            source_dir / "contacts.jsonl",
            thread_id,
            id_keys=("contact_id", "id", "source_record_id"),
        )
        lead_events_iter = _stream_jsonl_records_by_id(
            source_dir / "lead-events.jsonl",
            thread_id,
            id_keys=("contact_id", "conversation_id"),
        )

    messages: list[JsonRecord] = []
    person_name = ""
    for record in raw_messages:
        rec_thread = str(record.get("thread_id") or record.get("conversation_id") or "").strip()
        if rec_thread != thread_id:
            continue
        normalized = _message_for_thread(record)
        if normalized is None:
            continue
        if not person_name and normalized["direction"] == "inbound" and normalized.get("sender"):
            person_name = str(normalized["sender"])
        messages.append(normalized)
    messages.sort(key=lambda m: _parse_record_dt(m.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc))
    messages = messages[-safe_limit:]

    if lead_record is not None and not person_name:
        person_name = _record_person_name(lead_record)

    activity_records: list[JsonRecord] = []
    notes_records: list[JsonRecord] = []
    tasks_records: list[JsonRecord] = []
    for record in lead_events_iter:
        if str(record.get("contact_id") or record.get("conversation_id") or "").strip() != thread_id:
            continue
        event_type = str(record.get("type") or record.get("event_type") or "event").strip()
        timestamp = record.get("timestamp") or record.get("created_at") or record.get("last_seen_at")
        rec_id = str(record.get("source_record_id") or record.get("id") or "")
        if event_type in {"crm_note", "lofty_note"}:
            notes_records.append(
                {
                    "id": rec_id,
                    "title": record.get("title") or "Note",
                    "summary": record.get("summary") or record.get("text") or "",
                    "author": record.get("author"),
                    "timestamp": timestamp,
                }
            )
            continue
        if event_type in {"crm_task", "lofty_task"}:
            tasks_records.append(
                {
                    "id": rec_id,
                    "title": record.get("title") or "Task",
                    "summary": record.get("summary") or record.get("text") or "",
                    "status": record.get("status") or "open",
                    "dueAt": record.get("dueAt") or record.get("due_at"),
                    "timestamp": timestamp,
                }
            )
            continue
        activity_records.append(
            {
                "id": rec_id,
                "type": event_type,
                "subtype": record.get("subtype"),
                "title": record.get("title") or record.get("summary") or record.get("text"),
                "summary": record.get("summary") or record.get("text"),
                "address": record.get("address"),
                "timestamp": timestamp,
            }
        )

    def _by_ts_desc(rows: list[JsonRecord]) -> list[JsonRecord]:
        rows.sort(
            key=lambda a: _parse_record_dt(a.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc),
            reverse=True,
        )
        return rows

    activity_records = _by_ts_desc(activity_records)[:30]
    notes_records = _by_ts_desc(notes_records)[:30]
    tasks_records = _by_ts_desc(tasks_records)[:30]

    lead: JsonRecord | None = None
    if lead_record is not None:
        emails_raw = lead_record.get("emails") or lead_record.get("email")
        phones_raw = lead_record.get("phones") or lead_record.get("phone")
        if isinstance(emails_raw, (list, tuple)):
            emails = [str(e) for e in emails_raw if e]
        elif emails_raw:
            emails = [str(emails_raw)]
        else:
            emails = []
        if isinstance(phones_raw, (list, tuple)):
            phones = [str(p) for p in phones_raw if p]
        elif phones_raw:
            phones = [str(phones_raw)]
        else:
            phones = []
        tags_raw = lead_record.get("tags") or []
        if isinstance(tags_raw, (list, tuple)):
            tags_clean = [str(t) for t in tags_raw if t]
        else:
            tags_clean = [str(tags_raw)] if tags_raw else []
        score_val = lead_record.get("score")
        score_int: int | None
        try:
            score_int = int(score_val) if score_val is not None else None
        except (TypeError, ValueError):
            score_int = None
        lead = {
            "leadId": lead_record.get("lead_id") or lead_record.get("contact_id"),
            "displayName": lead_record.get("display_name") or person_name,
            "stage": lead_record.get("stage"),
            "leadSource": lead_record.get("lead_source") or lead_record.get("source"),
            "assignedUser": lead_record.get("assigned_user"),
            "score": score_int,
            "tags": tags_clean,
            "summary": lead_record.get("summary") or lead_record.get("text"),
            "emails": emails,
            "phones": phones,
            "channel": lead_record.get("channel"),
            "timestamp": lead_record.get("timestamp") or lead_record.get("last_seen_at"),
            "lastSeenAt": lead_record.get("last_seen_at"),
        }

    pending_draft: JsonRecord | None = None
    ui_state = _read_source_ui_state(source_dir)
    task_states = _as_dict(ui_state.get("tasks"))
    for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=200):
        if not _is_message_draft_task(record):
            continue
        if _thread_key(record) != thread_id:
            continue
        task_id = _task_key(record)
        state = _as_dict(task_states.get(task_id))
        status = str(state.get("status") or record.get("status") or "pending").lower()
        if status in {"approved", "done", "archived", "cancelled", "skipped"}:
            continue
        pending_draft = _draft_from_task(source, record, state)
        break

    sends: list[JsonRecord] = []
    meta: JsonRecord | None = None
    try:
        from elevate_cli import outreach_db as _odb
        sends = _odb.list_sends_by_thread(source_id, thread_id, limit=50)
        meta = _odb.get_thread_meta(source_id, thread_id)
    except Exception:
        sends = []
        meta = None

    last_inbound = next((m for m in reversed(messages) if m.get("direction") == "inbound"), None)
    last_outbound = next((m for m in reversed(messages) if m.get("direction") == "outbound"), None)

    return {
        "sourceId": source_id,
        "threadId": thread_id,
        "source": {
            "id": source.get("id"),
            "label": source.get("label"),
            "category": source.get("category"),
            "ownerAgent": source.get("ownerAgent"),
            "connected": source.get("connected"),
        },
        "personName": person_name or "Client",
        "messageCount": len(messages),
        "messages": messages,
        "lastInboundAt": (last_inbound or {}).get("timestamp"),
        "lastOutboundAt": (last_outbound or {}).get("timestamp"),
        "pendingDraft": pending_draft,
        "sends": sends,
        "meta": meta,
        "lead": lead,
        "notes": notes_records,
        "tasks": tasks_records,
        "activity": activity_records,
    }


def update_profile_state(
    profile_id: str,
    status: str | None,
    config: dict[str, Any] | None = None,
    *,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set pipeline status for a profile.

    Writes ``contacts.pipeline_status`` in the operational DB via
    :func:`set_pipeline_status` (migration 0014). Picking
    ``closed_seller`` / ``closed_buyer`` from the dropdown also calls
    :func:`close_to_admin` so the contact lands on /admin in the same
    transaction. By default returns the refreshed /leads response so legacy
    callers can rerender without a second fetch; HTTP routes pass
    ``return_inbox=False`` and build the DB-primary response once.

    Falls back to the legacy ``profile-state.json`` writer when the
    profile is not a contact UUID (e.g. composio thread-derived profiles
    that don't have a contacts row yet); the AI sweep eventually merges
    them, at which point the SQLite path takes over.
    """
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")
    normalized = str(status or "").strip().lower()
    if normalized == "none":
        normalized = ""
    if normalized and normalized not in PROFILE_STATUS_VALUES:
        raise ValueError(f"Unsupported profile status: {status}")

    config = config or load_config()

    # Primary path: write to contacts.pipeline_status in SQLite. The UI
    # passes the source-inbox profile id (e.g. "email:foo@bar.com" or
    # "phone:+15551234567") so we resolve to a contacts row by either UUID
    # or verifier match.
    try:
        from elevate_cli.data import connect, get_contact, set_pipeline_status
        with connect() as conn:
            contact_id: str | None = None
            if get_contact(conn, pid) is not None:
                contact_id = pid
            elif ":" in pid:
                kind, _, value = pid.partition(":")
                kind = kind.strip().lower()
                value = value.strip()
                if value:
                    if kind == "email":
                        row = conn.execute(
                            "SELECT id FROM contacts WHERE LOWER(primary_email) = LOWER(?) LIMIT 1",
                            (value,),
                        ).fetchone()
                    elif kind == "phone":
                        row = conn.execute(
                            "SELECT id FROM contacts WHERE primary_phone = ? LIMIT 1",
                            (value,),
                        ).fetchone()
                    else:
                        row = None
                    if row is not None:
                        contact_id = row["id"]
            if contact_id:
                set_pipeline_status(
                    conn,
                    contact_id,
                    status=normalized or None,
                    actor="operator:leads-ui",
                    set_by="operator",
                )
                return build_source_inbox_response(config) if return_inbox else {"ok": True}
    except ValueError:
        raise
    except Exception:
        # Fall through to the legacy JSON writer if the data module can't
        # accept this profile_id (e.g. composio thread profile without a
        # contacts row yet).
        pass

    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    state = _read_profile_state(source_root)
    profiles = _as_dict(state.get("profiles"))
    if not normalized:
        profiles.pop(pid, None)
    else:
        profiles[pid] = {"status": normalized, "updated_at": _now()}
    state["profiles"] = profiles
    _write_profile_state(source_root, state)
    return build_source_inbox_response(config) if return_inbox else {"ok": True}


def update_profile_favorite(
    profile_id: str,
    *,
    favorite: bool,
    contact_id: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set /leads favorite flag for a profile."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")

    from elevate_cli.data import connect, set_lead_profile_favorite

    with connect() as conn:
        set_lead_profile_favorite(
            conn,
            pid,
            favorite=bool(favorite),
            contact_id=contact_id,
            actor="operator:leads-ui",
        )
    return build_source_inbox_response(config or load_config()) if return_inbox else {"ok": True}


def update_source_thread_state(
    source_id: str,
    thread_id: str,
    action: str,
    config: dict[str, Any] | None = None,
    *,
    return_inbox: bool = True,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    if not _mutable_source_exists(source_root, source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"done", "archive", "restore", "open"}:
        raise ValueError("Unsupported thread action")

    source_dir = _source_dir(source_root, source_id)
    state = _read_source_ui_state(source_dir)
    threads = _as_dict(state.get("threads"))
    if normalized in {"restore", "open"}:
        threads.pop(thread_id, None)
    else:
        threads[thread_id] = {
            "status": "archived" if normalized == "archive" else "done",
            "updated_at": _now(),
        }
    state["threads"] = threads
    _write_source_ui_state(source_dir, state)
    try:
        from elevate_cli.data import connect

        db_thread_id = thread_id
        if db_thread_id.startswith(f"{source_id}:"):
            db_thread_id = db_thread_id[len(source_id) + 1:]
        db_status = "open" if normalized in {"restore", "open"} else (
            "archived" if normalized == "archive" else "done"
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET status = ?, updated_at = ?
                WHERE source_id = ? AND thread_key = ?
                """,
                (db_status, _now(), source_id, db_thread_id),
            )
    except Exception:
        # Keep the legacy UI-state write available for rows that have not
        # been merged into operational DB yet. DB-primary routes will still
        # show the row until it has a matching conversation to update.
        pass
    return build_source_inbox_response(config) if return_inbox else {"ok": True}


_SOURCE_TO_CHANNEL = {
    "apple-messages": "sms",
    "sms-provider": "sms",
    "android-device": "sms",
    "rcs": "sms",
    "email": "email",
    "social": "social_dm",
    "crm": "crm_note",
}


def _channel_for_source(source_id: str) -> str | None:
    """Return the outbound channel for a source_id, or None if the source has
    no outbound (skills/market-stats/etc are read-only inputs, not channels).
    """
    return _SOURCE_TO_CHANNEL.get(source_id)


def _source_view_for_state(source_id: str, source_dir: Path) -> JsonRecord:
    source = _read_json(source_dir / "source.json") or {}
    blueprint = _blueprint(source_id) or {}
    source.setdefault("id", source_id)
    source.setdefault("label", blueprint.get("source") or source_id)
    source.setdefault("source", blueprint.get("source") or source.get("label") or source_id)
    source.setdefault("category", blueprint.get("category") or "messages")
    return source


def _thread_draft_template_state(source_id: str, task_id: str, source_dir: Path) -> JsonRecord:
    prefix = "thread-draft:"
    if not task_id.startswith(prefix):
        return {}
    thread_id = task_id[len(prefix):].strip()
    if not thread_id:
        return {}
    source = _source_view_for_state(source_id, source_dir)
    for record in _candidate_records_for_source(source_dir, source, 5000):
        if _thread_key(record) != thread_id:
            continue
        thread = _thread_from_record(source, record, status="open")
        template_draft = _templated_draft_for_thread(source, thread)
        if not template_draft:
            return {}
        return {
            "draft_text": template_draft.get("draftText"),
            "template_id": template_draft.get("templateId"),
            "template_name": template_draft.get("templateName"),
            "template_channel": template_draft.get("templateChannel"),
            "outreach_lane": template_draft.get("outreachLane"),
        }
    return {}


def _fire_approve_tick(task_id: str) -> None:
    """Drain the sender ONCE, in the current process, right after an approve.

    Runs in a daemon thread so the HTTP response isn't blocked on the send
    (10-90s). CRITICAL: this must run inside the Elevate app (dashboard)
    process, where macOS Automation→Messages can be granted — the launchd
    gateway daemon cannot send via Messages (no GUI prompt for Automation), so
    the app must own the actual delivery. Disable with ELEVATE_APPROVE_AUTO_TICK=0.
    """
    if os.getenv("ELEVATE_APPROVE_AUTO_TICK", "1") in ("0", "false", "no"):
        return
    import threading

    def _tick() -> None:
        try:
            from elevate_cli import sender as _sender

            _sender.tick(batch=int(os.getenv("ELEVATE_APPROVE_TICK_BATCH", "1")))
        except Exception:
            import traceback

            traceback.print_exc()

    threading.Thread(target=_tick, name=f"approve-tick-{str(task_id)[:24]}", daemon=True).start()


def update_source_task_state(
    source_id: str,
    task_id: str,
    action: str,
    *,
    draft_text: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    if not _mutable_source_exists(source_root, source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"approve", "edit", "skip", "restore", "open"}:
        raise ValueError("Unsupported draft action")

    source_dir = _source_dir(source_root, source_id)
    state = _read_source_ui_state(source_dir)
    tasks = _as_dict(state.get("tasks"))

    if normalized in {"restore", "open"}:
        tasks.pop(task_id, None)
        state["tasks"] = tasks
        _write_source_ui_state(source_dir, state)
        try:
            from elevate_cli import outreach_db

            outreach_db.restore_skipped_send(source_id, task_id)
        except Exception:
            logging.getLogger(__name__).warning(
                "restore: pending-send restore failed for %s/%s", source_id, task_id,
                exc_info=True,
            )
        return build_source_inbox_response(config) if return_inbox else {"ok": True}

    status = "approved" if normalized == "approve" else "skipped" if normalized == "skip" else "pending"
    existing = _as_dict(tasks.get(task_id))
    existing.update({"status": status, "updated_at": _now()})
    # Only overwrite the stored draft when a NON-EMPTY draft is supplied. The
    # /leads Approve button calls this with draftText="" (the api default), and a
    # blanking overwrite here strips the real draft — the send then fails with
    # "messages-native: payload missing draft_text". An explicit empty edit can't
    # be sent anyway, so guarding on truthiness is safe.
    if draft_text:
        existing["draft_text"] = str(draft_text)
    if task_id.startswith("thread-draft:"):
        template_state = _thread_draft_template_state(source_id, task_id, source_dir)
        for key in ("template_id", "template_name", "template_channel", "outreach_lane"):
            if template_state.get(key) and not existing.get(key):
                existing[key] = template_state[key]
        if template_state.get("draft_text") and not existing.get("draft_text"):
            existing["draft_text"] = template_state["draft_text"]
    tasks[task_id] = existing
    state["tasks"] = tasks

    if normalized == "approve":
        # Outbound pause: if this is a native Mac Messages send (channel "sms")
        # and the Apple Messages outbound toggle is OFF, hold the approval —
        # don't release to the sender, don't fire. The card stays in the queue
        # (status kept pending) so nothing leaves until outbound is turned back
        # on. Inbound/banner are unaffected (different toggle).
        if _channel_for_source(source_id) == "sms" and not get_apple_messages_directions(
            config
        ).get("outbound", True):
            existing["status"] = "pending"
            tasks[task_id] = existing
            state["tasks"] = tasks
            _write_source_ui_state(source_dir, state)
            return build_source_inbox_response(config) if return_inbox else {
                "ok": False,
                "held": True,
                "reason": "apple_messages_outbound_disabled",
            }
        # Most /leads drafts are send_queue rows in pending_approval (a cron wrote
        # them straight to the DB), surfaced with id "<source>:send-queue:<id>".
        # For those, approval means RELEASE the existing row to 'queued' so the
        # sender delivers it — NOT insert a fresh source-dir send. Try that first;
        # fall back to the source-dir task path only if there's no pending row.
        flipped = None
        try:
            from elevate_cli import outreach_db

            flipped = outreach_db.approve_pending_send(source_id, task_id, draft_text=draft_text or None)
        except Exception:
            logging.getLogger(__name__).warning(
                "approve: pending-send release failed for %s/%s", source_id, task_id,
                exc_info=True,
            )
        if flipped is not None:
            _write_source_ui_state(source_dir, state)
            # Send NOW, in THIS process. The approve API runs inside the Elevate
            # app (dashboard), which can hold macOS Automation→Messages — the
            # launchd gateway daemon CANNOT (no GUI prompt), so leaving the send
            # to the gateway's periodic tick fails the permission check. Firing
            # here keeps the send in the app context. Best-effort + threaded so
            # the HTTP response isn't blocked.
            _fire_approve_tick(task_id)
        else:
            _approve_atomic(source_id, task_id, existing, source_dir, state)
    else:
        # An edit (Save) must also land on the underlying send_queue row — where
        # the real outbound payload lives — not just the source-dir UI state, or
        # a later Approve would still send the original template.
        if normalized == "edit" and draft_text:
            try:
                from elevate_cli import outreach_db

                outreach_db.update_pending_send_draft(source_id, task_id, draft_text)
            except Exception:
                logging.getLogger(__name__).warning(
                    "edit: pending-send draft update failed for %s/%s", source_id, task_id,
                    exc_info=True,
                )
        # Skip must ALSO flip the underlying send_queue row out of
        # pending_approval. The Approve queue is built from pending_approval
        # send_queue rows (build_source_inbox_response), NOT from ui-state — so
        # writing only status=skipped here leaves the DB row pending and it
        # reappears on the next refresh (the "Skip does nothing" bug).
        if normalized == "skip":
            try:
                from elevate_cli import outreach_db

                outreach_db.skip_pending_send(source_id, task_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "skip: pending-send skip failed for %s/%s", source_id, task_id,
                    exc_info=True,
                )
        _write_source_ui_state(source_dir, state)

    return build_source_inbox_response(config) if return_inbox else {"ok": True}


def _approve_atomic(
    source_id: str,
    task_id: str,
    task_record: dict[str, Any],
    source_dir: Path,
    state: dict[str, Any],
) -> None:
    """Atomically pair: insert send_queue row + flip task status to approved.

    Order: open SQLite IMMEDIATE txn, insert queue row, write UI JSON,
    commit SQLite. If the JSON write fails, the SQLite insert is rolled back.
    Idempotent on (source_id, thread_id, task_id) so repeat clicks don't
    create duplicate sends.

    Sources with no outbound channel (skills, market-stats, etc.) just write
    the JSON state — they can't be sent, only acknowledged.
    """
    from elevate_cli import outreach_db

    channel = _channel_for_source(source_id)
    if not channel:
        _write_source_ui_state(source_dir, state)
        return

    # ui-state's task entry only carries {status, updated_at, draft_text}.
    # The recipient (phone/email/handle) lives in the original tasks.jsonl
    # record. Merge it in so the queue payload has what the dispatcher needs;
    # ui-state values win when present (user-edited draft_text).
    merged: dict[str, Any] = {}
    for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
        if _task_key(record) == task_id:
            merged.update(record)
            break
    for k, v in (task_record or {}).items():
        if v not in (None, ""):
            merged[k] = v

    thread_id = str(merged.get("thread_id") or merged.get("threadId") or task_id)
    if thread_id == task_id and task_id.startswith("thread-draft:"):
        thread_id = task_id.removeprefix("thread-draft:")
    draft_text = str(merged.get("draft_text") or _draft_text_for_task(merged) or "").strip()
    payload = {
        "draft_text": draft_text,
        "recipient": {
            "person_name": merged.get("person_name") or merged.get("personName") or merged.get("display_name"),
            "contact_id": merged.get("contact_id"),
            "conversation_id": merged.get("conversation_id") or merged.get("source_record_id"),
            "phone": merged.get("phone") or merged.get("recipient_phone") or (merged.get("phones") or [None])[0],
            "email": merged.get("email") or merged.get("recipient_email") or (merged.get("emails") or [None])[0],
            "social_handle": merged.get("social_handle") or merged.get("recipient_handle"),
        },
        "channel_meta": {
            "toolkit": merged.get("toolkit"),
            "account_id": merged.get("composio_account_id"),
        },
        "source_id": source_id,
        "thread_id": thread_id,
        "task_id": task_id,
    }
    attempt_id = merged.get("attempt_id") or merged.get("attemptId")
    template_id = merged.get("template_id") or merged.get("templateId")
    outreach_lane = merged.get("outreach_lane") or merged.get("outreachLane") or merged.get("lane")
    if template_id:
        payload["template_id"] = template_id
        payload["templateId"] = template_id
    if outreach_lane:
        payload["outreach_lane"] = outreach_lane
        payload["outreachLane"] = outreach_lane

    with outreach_db.connect() as conn:
        with outreach_db.transaction(conn):
            if template_id and not attempt_id:
                try:
                    attempt_id = outreach_db.record_use_in_transaction(
                        conn,
                        str(template_id),
                        lane=str(outreach_lane or "new-outreach"),
                        source_id=source_id,
                        thread_id=thread_id,
                        task_id=task_id,
                    )
                    task_record["attempt_id"] = attempt_id
                except Exception:
                    attempt_id = None
            if attempt_id:
                payload["attempt_id"] = attempt_id
                payload["attemptId"] = attempt_id
            outreach_db.enqueue_send(
                conn,
                source_id=source_id,
                thread_id=thread_id,
                task_id=task_id,
                channel=channel,
                payload=payload,
                attempt_id=attempt_id,
            )
            _write_source_ui_state(source_dir, state)

    # Fire the sender immediately so the UI experience is "click → sent."
    _fire_approve_tick(task_id)


from elevate_cli.source_connector_modules.crm_helpers import (
    _LOFTY_LIST_KEYS,
    _basic_auth_header,
    _build_crm_auth,
    _extract_lead_records,
    _generic_crm_get,
    _generic_crm_write,
    _list_text,
    _lofty_epoch_ms_to_iso,
    _lofty_extract_list,
    _lofty_get,
    _lofty_get_activities,
    _lofty_get_first_ok,
    _lofty_get_notes,
    _lofty_get_tasks,
    _lofty_headers,
    _lofty_lead_name,
    _lofty_listing_address,
    _lofty_normalize_activity,
    _lofty_normalize_note,
    _lofty_normalize_task,
    _lofty_timestamp,
    _lofty_write,
    _provider_label,
    _stable_hash_id,
    _tag_names,
)


def sync_generic_crm_source(
    config: dict[str, Any] | None = None, *, limit: int = 5000
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = _combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    provider = str(crm.get("provider") or "custom")
    label = str(crm.get("label") or _provider_label(provider))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")

    if not api_key or not str(crm.get("base_url") or "").strip():
        _write_json(
            source_dir / "source.json",
            {
                "source_id": "crm",
                "provider": label,
                "account_label": label,
                "connection_type": f"{provider}_api",
                "auth_status": "missing_secret",
                "sync_mode": "crm_lead_snapshot",
                "owner_agent": owner,
                "enabled_ui_surfaces": surfaces,
                "setup_status": "needs_operator",
                "last_sync_at": None,
                "setup_notes": f"Add {env_key} to ~/.elevate/.env and confirm the {label} base URL.",
            },
        )
        _write_json(
            source_dir / "status.json",
            {
                "connected": False,
                "import_only": False,
                "blocked": False,
                "last_error": None,
                "next_operator_step": f"Add the {label} API key, then sync CRM again.",
                "last_checked_at": now,
            },
        )
        for file_name in JSONL_FILES:
            _replace_jsonl(source_dir / file_name, [])
        view = connector_view(source_root, "crm")
        if view is None:
            raise RuntimeError(f"{label} source could not be read")
        return view

    leads: list[JsonRecord] = []
    attempted: list[str] = [leads_path]
    errors: list[str] = []
    pagination_params: dict[str, Any] = {"limit": min(limit, 100)}
    if provider == "followupboss":
        pagination_params = {"limit": min(limit, 100), "sort": "-updated"}
    elif provider == "sierra":
        pagination_params = {"page": 1, "pageSize": min(limit, 100)}
    elif provider == "boldtrail":
        pagination_params = {"limit": min(limit, 100), "sort": "-updated_at"}
    elif provider == "brivity":
        pagination_params = {"page": 1, "per_page": min(limit, 100)}
    try:
        payload = _generic_crm_get(crm, api_key, leads_path, pagination_params)
        leads = _extract_lead_records(payload)
    except Exception as exc:
        errors.append(f"{leads_path}: {exc}")

    deduped: list[JsonRecord] = []
    seen_ids: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("id") or lead.get("leadId") or lead.get("lead_id") or "").strip()
        if not lead_id:
            lead_id = f"unknown-{len(seen_ids) + 1}"
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        deduped.append(lead)

    contact_records: list[JsonRecord] = []
    conversation_records: list[JsonRecord] = []
    lead_events: list[JsonRecord] = []
    task_records: list[JsonRecord] = []
    for lead in deduped:
        lead_id = str(lead.get("id") or lead.get("leadId") or lead.get("lead_id") or "").strip()
        record_id = f"{provider}-lead:{lead_id or len(contact_records) + 1}"
        name = _lofty_lead_name(lead)
        timestamp = _lofty_timestamp(lead)
        stage = str(
            lead.get("stage") or lead.get("status") or lead.get("leadType") or lead.get("aiStage") or ""
        ).strip()
        source = str(
            lead.get("source") or lead.get("leadSource") or lead.get("origin") or ""
        ).strip()
        tags = _tag_names(lead.get("tags"))
        score = _safe_int(lead.get("score") or lead.get("leadScore"), 45)
        summary = (
            f"{name} from {label}"
            + (f" is in {stage}" if stage else "")
            + (f" via {source}" if source else "")
            + "."
        )
        base_record = {
            "source_id": "crm",
            "source_record_id": record_id,
            "conversation_id": record_id,
            "contact_id": record_id,
            "display_name": name,
            "channel": label,
            "timestamp": timestamp,
            "last_seen_at": timestamp,
            "last_message_at": timestamp,
            "text": summary,
            "summary": summary,
            "lead_id": lead_id or None,
            "stage": stage or None,
            "lead_source": source or None,
            "assigned_user": lead.get("assignedUser") or lead.get("assignedAgent") or lead.get("assigned_to"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, f"{provider}-crm", "crm-lead"],
            "confidence": 0.82,
            "target_ui_surfaces": surfaces,
        }
        contact_records.append(base_record)
        conversation_records.append(
            {
                **base_record,
                "total_messages": _safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
                "inbound_count": 0,
                "outbound_count": 0,
                "last_text": summary,
            }
        )
        lead_events.append(
            {
                **base_record,
                "type": "crm_lead_synced",
                "title": f"{label} lead synced",
            }
        )
        heat_score, heat_label = _heat_score_for_record(base_record)
        if heat_label in {"hot", "warm"}:
            task_records.append(
                {
                    **base_record,
                    "source_record_id": f"{record_id}:follow-up",
                    "title": f"Review {name}",
                    "status": "open",
                    "task_type": "lead_follow_up",
                    "approval_required": False,
                    "owner_agent": owner,
                    "summary": f"{name} looks {heat_label} in {label}. Review source, stage, notes, and next outreach step.",
                    "heat_score": heat_score,
                    "target_ui_surfaces": ["Leads", "Today", "Outreach"],
                }
            )

    # Atomic multi-file rewrite (Codex audit P1, 2026-05-05).
    with _snapshot_writer_lock(source_dir):
        preserved_tasks = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": label,
            "account_label": label,
            "connection_type": f"{provider}_api",
            "auth_status": f"{str(crm.get('auth_type') or 'header')}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": f"Read-only {label} lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                if deduped
                else f"{label} auth was found, but no lead rows were returned. Check the API key scope, then sync again."
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
            },
        },
    )
    # Continuous DB writethrough — Codex audit P0 (2026-05-05).
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough: {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": now, "error": str(exc)},
        )

    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError(f"{label} source could not be read")
    return view


# ── CRM write layer (create, note, stage update) ──────────────────────────────


def _sierra_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Sierra-ApiKey": api_key,
        "Sierra-OriginatingSystemName": "elevate",
    }


def _sierra_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_sierra_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _sierra_get(path: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    request = urllib.request.Request(url, headers=_sierra_headers(api_key), method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _brivity_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token token={api_key}",
    }


def _brivity_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://www.brivity.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_brivity_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _resolve_crm_context(
    config: dict[str, Any],
) -> tuple[str, str, JsonRecord, dict[str, str]]:
    """Return (provider, api_key, crm_config, env_values)."""
    env_values = _combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    # Honor whatever CRM was picked at onboarding/config — never assume Lofty.
    provider = _canonical_crm_provider(crm.get("provider"))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    if not api_key and provider == "lofty":
        api_key = str(env_values.get("LOFTY_API_KEY") or env_values.get("LOFTY_ACCESS_TOKEN") or "").strip()
    return provider, api_key, crm, env_values


def crm_find_lead(
    email: str = "",
    config: dict[str, Any] | None = None,
    *,
    phone: str = "",
) -> JsonRecord | None:
    """Find a CRM lead by email (or phone fallback). Returns normalized {id, stage, tags} or None."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    def _normalize_lofty(lead: JsonRecord) -> JsonRecord:
        return {
            "id": str(lead.get("leadId") or ""),
            "stage": str(lead.get("stage") or ""),
            "tags": [t.get("tagName") for t in (lead.get("tags") or []) if t.get("tagName")],
            "raw": lead,
        }

    if provider == "lofty":
        if email:
            payload = _lofty_get(f"v1.0/leads?email={urllib.parse.quote(email)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        if phone:
            payload = _lofty_get(f"v1.0/leads?phone={urllib.parse.quote(phone)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        return None

    if provider == "followupboss":
        if email:
            payload = _generic_crm_get(crm, api_key, "v1/people", {"email": email, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        if phone:
            payload = _generic_crm_get(crm, api_key, "v1/people", {"phone": phone, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        return None

    if provider == "sierra":
        if email:
            payload = _sierra_get("leads", api_key, {"email": email, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        if phone:
            payload = _sierra_get("leads", api_key, {"phone": phone, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        return None

    if provider == "brivity":
        # Brivity has no public search endpoint -- caller must track ids externally
        return None

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_find_lead not yet implemented for provider: {provider}")


def crm_create_lead(
    contact: JsonRecord,
    config: dict[str, Any] | None = None,
) -> str:
    """Create a lead in the CRM. contact = {firstName, lastName, email, phone, source, stage, tags}.
    Returns the new lead's CRM id."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)
    first = str(contact.get("firstName") or "")
    last = str(contact.get("lastName") or "")
    email = str(contact.get("email") or "")
    phone = str(contact.get("phone") or "")
    source = str(contact.get("source") or "elevate")
    stage = str(contact.get("stage") or "New Leads")
    tags = list(contact.get("tags") or [])

    if provider == "lofty":
        body: JsonRecord = {"firstName": first, "lastName": last, "source": source, "stage": stage, "tags": tags}
        if email:
            body["emails"] = [email]
        if phone:
            body["phones"] = [phone]
        result = _lofty_write("v1.0/leads", env_values, body, method="POST")
        return str(result.get("leadId") or result.get("id") or "")

    if provider == "followupboss":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["emails"] = [{"value": email, "type": "work"}]
        if phone:
            body["phones"] = [{"value": phone, "type": "mobile"}]
        result = _generic_crm_write(crm, api_key, "v1/people", body, method="POST")
        lead_id = str(result.get("id") or result.get("person", {}).get("id") or "")
        if lead_id and stage and stage != "New Leads":
            _generic_crm_write(crm, api_key, f"v1/people/{lead_id}", {"stage": stage}, method="PUT")
        return lead_id

    if provider == "sierra":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if tags:
            body["tags"] = tags
        if stage:
            body["leadType"] = stage  # Sierra uses leadType on create, status on update
        note_text = str(contact.get("note") or "")
        if note_text:
            body["note"] = note_text
        result = _sierra_write("leads", api_key, body, method="POST")
        return str((result.get("data") or {}).get("id") or "")

    if provider == "brivity":
        # Brivity uses snake_case and encodes notes in description
        body = {"source": source}
        if first:
            body["first_name"] = first
        if last:
            body["last_name"] = last
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if stage:
            # Brivity status enum: new, unqualified, watch, nurture, hot, archived
            body["status"] = stage.lower()
        note_text = str(contact.get("note") or "")
        if note_text:
            body["description"] = note_text
        result = _brivity_write("api/v2/leads", api_key, body, method="POST")
        return str((result.get("lead") or result).get("id") or "")

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_create_lead not yet implemented for provider: {provider}")


def crm_add_note(
    lead_id: str,
    note: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """Add a note to an existing CRM lead. Returns True on success."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        try:
            _lofty_write(f"v1.0/leads/{lead_id}/notes", env_values, {"content": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        try:
            _generic_crm_write(crm, api_key, "v1/notes", {"personId": int(lead_id), "body": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "sierra":
        try:
            _sierra_write(f"leads/{lead_id}/note", api_key, {"message": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no notes endpoint -- notes must go into description at create time
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_add_note not yet implemented for provider: {provider}")


def sync_pending_notes_to_lofty(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 25,
    max_attempts: int = 5,
) -> JsonRecord:
    """Push every ``notes`` row with ``crm_sync_state='pending'`` to
    Lofty. Returns a summary ``{pushed, skipped, failed, errors[]}``.

    Skip rules (counted in ``skipped``, not retried):
      * non-Lofty CRM provider — caller picked the wrong source.
      * Contact has no ``lofty_id`` identity — we have nowhere to POST.

    Failure rules:
      * 4xx → ``mark_lofty_failed(permanent=True)`` — payload bad, retry
        won't fix it. Operator can re-trigger by editing the body.
      * 5xx / timeout / unknown → ``mark_lofty_failed(permanent=False)`` —
        attempt counter bumps; row stays ``pending`` until ``max_attempts``.

    Content prefix: ``[AI/{author_name}] {body}`` — so the operator can
    skim Lofty's note feed and know what wrote each line.
    """
    config = config or load_config()
    provider, _api_key, _crm, env_values = _resolve_crm_context(config)

    summary: JsonRecord = {
        "provider": provider,
        "pushed": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    if provider != "lofty":
        # Future: dispatch to followupboss / sierra / etc. For now only
        # Lofty is wired — others fall through silently to keep the cron
        # safe to run regardless of which CRM the operator connected.
        return summary

    headers, _auth_type = _lofty_headers(env_values)
    if not headers.get("Authorization"):
        summary["errors"].append("LOFTY_API_KEY / LOFTY_ACCESS_TOKEN not set")
        return summary

    from elevate_cli.data import (
        connect as _db_connect,
        list_pending_lofty_notes,
        mark_lofty_synced,
        mark_lofty_failed,
    )

    with _db_connect() as conn:
        pending = list_pending_lofty_notes(conn, limit=limit, max_attempts=max_attempts)
        for note in pending:
            note_id = note["id"]
            contact_id = note["contactId"]
            # Resolve the contact's Lofty lead id via the identities table.
            lofty_row = conn.execute(
                "SELECT value FROM identities "
                "WHERE contact_id=? AND kind='lofty_id' LIMIT 1",
                (contact_id,),
            ).fetchone()
            if lofty_row is None or not lofty_row["value"]:
                # No Lofty linkage — permanently fail. If a Lofty identity
                # gets added later, the operator can re-trigger by editing
                # the note body (which moves it back to pending).
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error="contact has no lofty_id identity",
                    permanent=True,
                )
                summary["skipped"] += 1
                continue
            lead_id = str(lofty_row["value"])
            content = f"[AI/{note['authorName']}] {note['body']}"

            try:
                resp = _lofty_write(
                    f"v1.0/leads/{lead_id}/notes",
                    env_values,
                    {"content": content},
                    method="POST",
                )
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=True,
                    )
                    summary["failed"] += 1
                else:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=False,
                    )
                    summary["errors"].append(f"{note_id}: HTTP {exc.code}")
                continue
            except Exception as exc:
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error=str(exc)[:500],
                    permanent=False,
                )
                summary["errors"].append(f"{note_id}: {exc}")
                continue

            lofty_note_id = None
            if isinstance(resp, dict):
                # Lofty returns either {"noteId": …} or wraps the row under
                # "data". Probe both shapes.
                raw = resp.get("noteId") or resp.get("id")
                if raw is None and isinstance(resp.get("data"), dict):
                    raw = resp["data"].get("noteId") or resp["data"].get("id")
                if raw is not None:
                    lofty_note_id = str(raw)

            if lofty_note_id:
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=lofty_note_id)
                summary["pushed"] += 1
            else:
                # POST succeeded (no exception) but we couldn't parse the
                # id. Mark synced with a placeholder so we don't double-post,
                # but flag in errors so the operator can investigate.
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=f"unknown:{note_id}")
                summary["pushed"] += 1
                summary["errors"].append(
                    f"{note_id}: posted but noteId missing from response"
                )

    return summary


def crm_update_stage(
    lead_id: str,
    stage: str,
    tags: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    """Update a CRM lead's stage and optionally merge tags. Returns True on success."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        body: JsonRecord = {"stage": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _lofty_write(f"v1.0/leads/{lead_id}", env_values, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        body = {"stage": stage}
        try:
            _generic_crm_write(crm, api_key, f"v1/people/{lead_id}", body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "sierra":
        # Sierra status enum: New, Qualify, Active, Prime, Pending, Closed, Archived, Junk, DoNotContact, Watch, Blocked
        body = {"status": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _sierra_write(f"leads/{lead_id}", api_key, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no status-update endpoint -- re-POST with status to upsert by email
        # Caller should use crm_create_lead with status set instead
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_update_stage not yet implemented for provider: {provider}")


# Lofty enrichment is the dominant cost of `elevate sync crm`: 3 HTTP calls
# per lead (activities + notes + tasks). To prevent a slow tenant from hanging
# the whole sync, enrichment runs in parallel with a per-call ceiling and
# checkpoints to disk every N leads so a killed run resumes instead of restarting.
_LOFTY_ENRICHMENT_WORKERS = 8
_LOFTY_ENRICHMENT_TIMEOUT_S = 10
_LOFTY_ENRICHMENT_CHECKPOINT_EVERY = 5


def _lofty_load_enrichment_progress(
    artifacts_dir: Path,
) -> tuple[set[str], list[JsonRecord], dict[str, int]]:
    """Load the prior enrichment checkpoint so a resumed sync skips already-
    enriched lead_ids. Missing/corrupt file = clean start, never raises."""
    path = artifacts_dir / "enrichment_progress.json"
    if not path.exists():
        return set(), [], {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        return set(), [], {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    completed = {str(x) for x in (payload.get("completed_lead_ids") or []) if x}
    events = [e for e in (payload.get("events") or []) if isinstance(e, dict)]
    summary = payload.get("summary") or {}
    base_summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    for key in base_summary:
        base_summary[key] = int(summary.get(key, 0) or 0)
    return completed, events, base_summary


def _lofty_save_enrichment_progress(
    artifacts_dir: Path,
    *,
    completed_lead_ids: set[str],
    events: list[JsonRecord],
    summary: dict[str, int],
    total_leads: int,
    status: str,
) -> None:
    """Atomic checkpoint write — same readers/writers can see partial
    enrichment without a torn file."""
    payload = {
        "checkpointed_at": _now(),
        "status": status,
        "completed_lead_ids": sorted(completed_lead_ids),
        "completed_count": len(completed_lead_ids),
        "total_leads": total_leads,
        "summary": summary,
        "events": events,
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tmp = artifacts_dir / "enrichment_progress.json.tmp"
    final = artifacts_dir / "enrichment_progress.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)


def _lofty_enrich_one_lead(
    *,
    lead_id: str,
    record_id: str,
    base_record: JsonRecord,
    fallback_timestamp: str,
    env_values: dict[str, str],
    timeout: int,
) -> tuple[str, list[JsonRecord], dict[str, int]]:
    """Worker called from a thread pool. Pulls activities + notes + tasks
    for one lead and returns the typed lead_events + a per-lead summary
    delta. Never raises — endpoint errors increment the error counter so
    one slow lead can't block the whole pool."""
    events: list[JsonRecord] = []
    summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}

    try:
        activity_payload = _lofty_get_activities(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        activity_payload = []
        summary["errors"] += 1
    for raw_act in activity_payload:
        norm = _lofty_normalize_activity(raw_act, lead_id)
        act_id = norm["id"] or _stable_hash_id(
            norm["subtype"], norm["title"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:activity:{act_id}",
                "type": "crm_activity",
                "provider": "lofty",
                "subtype": norm["subtype"],
                "title": norm["title"],
                "summary": norm["summary"],
                "address": norm["address"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["activities"] = len(activity_payload)

    try:
        notes_payload = _lofty_get_notes(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        notes_payload = []
        summary["errors"] += 1
    for raw_note in notes_payload:
        norm = _lofty_normalize_note(raw_note, lead_id)
        note_id = norm["id"] or _stable_hash_id(
            norm["title"], norm["summary"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:note:{note_id}",
                "type": "crm_note",
                "provider": "lofty",
                "title": norm["title"] or "Note",
                "summary": norm["summary"],
                "author": norm["author"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["notes"] = len(notes_payload)

    try:
        tasks_payload = _lofty_get_tasks(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        tasks_payload = []
        summary["errors"] += 1
    tasks_payload = [t for t in tasks_payload if not t.get("deleteFlag")]
    for raw_task in tasks_payload:
        norm = _lofty_normalize_task(raw_task, lead_id)
        task_id = norm["id"] or _stable_hash_id(
            norm["title"], norm["summary"], norm["dueAt"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:task:{task_id}",
                "type": "crm_task",
                "provider": "lofty",
                "title": norm["title"],
                "summary": norm["summary"],
                "status": norm["status"],
                "task_subtype": norm["type"],
                "assignedUser": norm["assignedUser"],
                "dueAt": norm["dueAt"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["tasks"] = len(tasks_payload)

    return lead_id, events, summary


def sync_lofty_crm_source(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 5000,
    enrichment_limit: int = 5000,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = _combined_env(config)
    headers, auth_type = _lofty_headers(env_values)

    if not headers.get("Authorization"):
        _write_json(
            source_dir / "source.json",
            {
                "source_id": "crm",
                "provider": "Lofty CRM",
                "account_label": "Lofty CRM",
                "connection_type": "lofty_api",
                "auth_status": "missing_secret",
                "sync_mode": "crm_lead_snapshot",
                "owner_agent": owner,
                "enabled_ui_surfaces": surfaces,
                "setup_status": "needs_operator",
                "last_sync_at": None,
                "setup_notes": "Add LOFTY_API_KEY or LOFTY_ACCESS_TOKEN to ~/.elevate/.env or the tools root .env.",
            },
        )
        _write_json(
            source_dir / "status.json",
            {
                "connected": False,
                "import_only": False,
                "blocked": False,
                "last_error": None,
                "next_operator_step": "Add the Lofty API key, then initialize/sync CRM again.",
                "last_checked_at": now,
            },
        )
        for file_name in JSONL_FILES:
            _replace_jsonl(source_dir / file_name, [])
        view = connector_view(source_root, "crm")
        if view is None:
            raise RuntimeError("Lofty CRM source could not be read")
        return view

    # Lofty caps page size at 100. For limit>100 we paginate via offset.
    # The two endpoints are tried in fall-through order: v2.0/working-leads
    # returns the high-priority slice, v1.0/leads returns everything.
    leads: list[JsonRecord] = []
    attempted: list[str] = []
    errors: list[str] = []
    page_size = 100
    for path, base_params in (
        ("/v2.0/working-leads", {"aiStage": "HIGH_PRIORITY", "sort": "UpdateTime", "desc": "true"}),
        ("/v1.0/leads", {}),
    ):
        attempted.append(path)
        offset = 0
        endpoint_pulled = 0
        while endpoint_pulled < limit:
            params = {
                **base_params,
                "limit": min(page_size, limit - endpoint_pulled),
                "offset": offset,
            }
            try:
                payload = _lofty_get(path, env_values, params)
            except Exception as exc:
                errors.append(f"{path}@offset={offset}: {exc}")
                break
            extracted = _extract_lead_records(payload)
            if not extracted:
                break  # exhausted this endpoint
            leads.extend(extracted)
            endpoint_pulled += len(extracted)
            offset += len(extracted)
            if len(extracted) < page_size:
                break  # short page = last page

    deduped: list[JsonRecord] = []
    seen_ids: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("leadId") or lead.get("id") or lead.get("lead_id") or "").strip()
        if not lead_id:
            lead_id = f"unknown-{len(seen_ids) + 1}"
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        deduped.append(lead)

    contact_records: list[JsonRecord] = []
    conversation_records: list[JsonRecord] = []
    lead_events: list[JsonRecord] = []
    task_records: list[JsonRecord] = []
    pending_enrichments: list[JsonRecord] = []
    enrichment_summary: dict[str, int] = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    max_enriched = max(0, int(enrichment_limit or 0))
    for index, lead in enumerate(deduped):
        lead_id = str(lead.get("leadId") or lead.get("id") or lead.get("lead_id") or "").strip()
        record_id = f"lofty-lead:{lead_id or len(contact_records) + 1}"
        name = _lofty_lead_name(lead)
        timestamp = _lofty_timestamp(lead)
        stage = str(lead.get("stage") or lead.get("aiStage") or lead.get("status") or "").strip()
        source = str(lead.get("source") or lead.get("leadSource") or "").strip()
        tags = _tag_names(lead.get("tags"))
        score = _safe_int(lead.get("score") or lead.get("leadScore"), 45)
        summary = (
            f"{name} from Lofty"
            + (f" is in {stage}" if stage else "")
            + (f" via {source}" if source else "")
            + "."
        )
        # Carry the full Lofty lead profile through to JSONL so the
        # migrate.py writethrough can enrich the contacts row. Pre-0012
        # this only carried name/email/phone/stage and the drawer rendered
        # blank cards. See migration 0012_lofty_lead_metadata.sql for the
        # column list and _CONTACT_ENRICHMENT_KEY_MAP in migrate.py for
        # accepted aliases.
        def _lead_get(*keys: str) -> Any:
            for key in keys:
                if key in lead:
                    value = lead.get(key)
                    if value not in (None, ""):
                        return value
            return None

        base_record = {
            "source_id": "crm",
            "source_record_id": record_id,
            "conversation_id": record_id,
            "contact_id": record_id,
            "display_name": name,
            "channel": "Lofty CRM",
            "timestamp": timestamp,
            "last_seen_at": timestamp,
            "last_message_at": timestamp,
            "text": summary,
            "summary": summary,
            "lead_id": lead_id or None,
            "stage": stage or None,
            "lead_source": source or None,
            "assigned_user": _lead_get("assignedUser", "assignedAgent"),
            "assignedUser": _lead_get("assignedUser", "assignedAgent"),
            "assignedUserId": _lead_get("assignedUserId", "assigned_user_id"),
            "leadUserId": _lead_get("leadUserId", "lofty_lead_user_id"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, "lofty-crm", "crm-lead"],
            "confidence": 0.86,
            "target_ui_surfaces": surfaces,
            # --- Lofty enrichment (migration 0012) ---
            "pondId": _lead_get("pondId", "pond_id"),
            "pondName": _lead_get("pondName", "pond_name"),
            "referredBy": _lead_get("referredBy", "referred_by"),
            "opportunity": _lead_get("opportunity"),
            "buyingTimeFrame": _lead_get("buyingTimeFrame", "buying_time_frame"),
            "sellingTimeFrame": _lead_get("sellingTimeFrame", "selling_time_frame"),
            "preQual": _lead_get("preQual", "preQualStatus", "pre_qual_status"),
            "mortgage": _lead_get("mortgage", "mortgageStatus", "mortgage_status"),
            "fthb": _lead_get("fthb", "firstTimeHomeBuyer", "first_time_home_buyer"),
            "hasHouseToSell": _lead_get("hasHouseToSell", "has_house_to_sell", "houseToSell"),
            "withBuyerAgent": _lead_get("withBuyerAgent", "with_buyer_agent"),
            "withListingAgent": _lead_get("withListingAgent", "with_listing_agent"),
            "buyHouseIntent": _lead_get("buyHouseIntent", "buy_house_intent", "buyHouse"),
            "leadTypes": lead.get("leadTypes") or lead.get("lead_types") or [],
            "segments": lead.get("segments") or [],
            "cannotText": _lead_get("cannotText", "cannot_text"),
            "cannotCall": _lead_get("cannotCall", "cannot_call"),
            "cannotEmail": _lead_get("cannotEmail", "cannot_email"),
            "unsubscribed": _lead_get("unsubscribed", "unsubscription"),
            "hidden": _lead_get("hidden", "hiddenFlag"),
        }
        contact_records.append(base_record)
        conversation_records.append(
            {
                **base_record,
                "total_messages": _safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
                "inbound_count": 0,
                "outbound_count": 0,
                "last_text": summary,
            }
        )
        lead_events.append(
            {
                **base_record,
                "type": "crm_lead_synced",
                "title": "Lofty lead synced",
            }
        )

        # Phase 2 enrichment runs in parallel after Phase 1 writes the
        # lead snapshot to disk. Stash everything we need to enrich this
        # lead later so the thread pool has self-contained job inputs.
        if lead_id and index < max_enriched:
            pending_enrichments.append(
                {
                    "lead_id": lead_id,
                    "record_id": record_id,
                    "base_record": base_record,
                    "fallback_timestamp": timestamp,
                }
            )

        heat_score, heat_label = _heat_score_for_record(base_record)
        if heat_label in {"hot", "warm"}:
            task_records.append(
                {
                    **base_record,
                    "source_record_id": f"{record_id}:follow-up",
                    "title": f"Review {name}",
                    "status": "open",
                    "task_type": "lead_follow_up",
                    "approval_required": False,
                    "owner_agent": owner,
                    "summary": f"{name} looks {heat_label} in Lofty. Review source, stage, notes, and next outreach step.",
                    "heat_score": heat_score,
                    "target_ui_surfaces": ["Leads", "Today", "Outreach"],
                }
            )

    # === PHASE 1 — Lead snapshot to disk + writethrough to operational Postgres ===
    # Write the lead snapshot before enrichment so even if Phase 2 hangs or
    # gets killed, downstream readers (operational Postgres, /leads UI, thread
    # drawer) already see the 21 leads with stage/score/source. Enrichment
    # in Phase 2 only adds the activity/note/task lead_events.
    base_lead_events = list(lead_events)
    with _snapshot_writer_lock(source_dir):
        preserved_tasks_phase1 = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", base_lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks_phase1 + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": "Lofty CRM",
            "account_label": "Lofty CRM",
            "connection_type": "lofty_api",
            "auth_status": f"{auth_type}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": "Read-only Lofty lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "enrichment_status": "pending" if pending_enrichments else "skipped",
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(base_lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Lead snapshot written. Enrichment running in background — refresh in a minute for activities/notes."
                if pending_enrichments
                else (
                    "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                    if deduped
                    else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
                )
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(base_lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough (phase 1): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": _now(), "phase": 1, "error": str(exc)},
        )

    # === PHASE 2 — Parallel enrichment with checkpointing ===
    # Each lead needs 3 HTTP calls (activities + notes + tasks). Running
    # them serially × 21 leads × 18s timeout = 19 min worst case. Running
    # in parallel (8 workers, 10s timeout each) brings this to 1-3 min for
    # 21 leads. Checkpoints every N completed leads so a killed run
    # resumes from where it left off.
    enrichment_status = "skipped"
    if pending_enrichments:
        prior_completed, prior_events, prior_summary = _lofty_load_enrichment_progress(artifacts_dir)
        # Keep prior summary so resumed runs surface cumulative counts.
        for key in enrichment_summary:
            enrichment_summary[key] = prior_summary.get(key, 0)
        completed_lead_ids: set[str] = set(prior_completed)
        enrichment_events: list[JsonRecord] = [
            e for e in prior_events
            if str((e.get("lead_id") or "")).strip() in completed_lead_ids
        ]
        to_enrich = [
            job for job in pending_enrichments
            if job["lead_id"] not in completed_lead_ids
        ]
        total = len(pending_enrichments)
        done = len(completed_lead_ids)
        if to_enrich:
            print(
                f"[crm] enrichment phase: {done}/{total} already done, "
                f"enriching {len(to_enrich)} leads with {_LOFTY_ENRICHMENT_WORKERS} workers"
                f" (timeout={_LOFTY_ENRICHMENT_TIMEOUT_S}s/call)",
                file=sys.stderr,
                flush=True,
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=_LOFTY_ENRICHMENT_WORKERS,
                thread_name_prefix="lofty-enrich",
            ) as executor:
                futures = {
                    executor.submit(
                        _lofty_enrich_one_lead,
                        lead_id=job["lead_id"],
                        record_id=job["record_id"],
                        base_record=job["base_record"],
                        fallback_timestamp=job["fallback_timestamp"],
                        env_values=env_values,
                        timeout=_LOFTY_ENRICHMENT_TIMEOUT_S,
                    ): job["lead_id"]
                    for job in to_enrich
                }
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        lead_id, events, delta = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        enrichment_summary["errors"] += 1
                        errors.append(f"enrichment worker crashed: {exc}")
                        continue
                    completed_lead_ids.add(lead_id)
                    enrichment_events.extend(events)
                    for key, val in delta.items():
                        enrichment_summary[key] = enrichment_summary.get(key, 0) + int(val or 0)
                    done = len(completed_lead_ids)
                    if done % _LOFTY_ENRICHMENT_CHECKPOINT_EVERY == 0 or done == total:
                        # Atomic checkpoint: lead-events.jsonl + progress file
                        # both reflect the same partial state. Resume picks
                        # up from the union of base + checkpoint events.
                        with _snapshot_writer_lock(source_dir):
                            _replace_jsonl(
                                source_dir / "lead-events.jsonl",
                                base_lead_events + enrichment_events,
                            )
                        _lofty_save_enrichment_progress(
                            artifacts_dir,
                            completed_lead_ids=completed_lead_ids,
                            events=enrichment_events,
                            summary=enrichment_summary,
                            total_leads=total,
                            status="in_progress" if done < total else "complete",
                        )
                        print(
                            f"[crm] enriched {done}/{total} leads "
                            f"(activities={enrichment_summary['activities']}, "
                            f"notes={enrichment_summary['notes']}, "
                            f"tasks={enrichment_summary['tasks']}, "
                            f"errors={enrichment_summary['errors']})",
                            file=sys.stderr,
                            flush=True,
                        )
        # Always include prior + new events in the final lead_events list
        lead_events = base_lead_events + enrichment_events
        enrichment_status = "complete" if done >= total else "partial"

    # === PHASE 3 — Final atomic rewrite + writethrough ===
    # Atomic multi-file rewrite — readers holding _snapshot_reader_lock
    # see either the pre-sync snapshot or the post-sync snapshot, never
    # a torn one. Codex audit P1 (2026-05-05).
    with _snapshot_writer_lock(source_dir):
        preserved_tasks = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": "Lofty CRM",
            "account_label": "Lofty CRM",
            "connection_type": "lofty_api",
            "auth_status": f"{auth_type}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": "Read-only Lofty lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "enrichment_status": enrichment_status,
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                if deduped
                else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    if errors:
        _write_json(artifacts_dir / "last-sync-errors.json", {"checked_at": now, "errors": errors})

    # Continuous ingest into operational Postgres so DB-primary readers see
    # tonight's Lofty data without a manual ``elevate migrate-data`` rerun.
    # Codex audit P0 (2026-05-05): JSONL-only sync left the DB stale.
    # Phase 1 already ran a writethrough for the bare snapshot; this Phase 3
    # writethrough lands the enrichment lead_events.
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        # Never let the DB writethrough fail the sync; legacy JSONL is
        # still the canonical store under DB shadow-read mode.
        if errors is not None:
            errors.append(f"db writethrough (phase 3): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": now, "phase": 3, "error": str(exc)},
        )
    # Mark enrichment checkpoint complete so a subsequent run doesn't
    # re-enrich leads already finalized.
    if enrichment_status in {"complete", "partial"}:
        try:
            _lofty_save_enrichment_progress(
                artifacts_dir,
                completed_lead_ids=set(completed_lead_ids) if pending_enrichments else set(),
                events=[e for e in lead_events if e.get("type") != "crm_lead_synced"],
                summary=enrichment_summary,
                total_leads=len(pending_enrichments),
                status=enrichment_status,
            )
        except Exception:  # noqa: BLE001
            pass

    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError("Lofty CRM sync finished but could not be read")
    return view


def _walk_jsonl_into_pg(source_dir: Path) -> dict[str, Any]:
    """Replay the just-written JSONL snapshot through the operational
    Postgres walker so DB-primary readers see fresh data without a
    manual ``elevate migrate-data`` rerun. Idempotent — every helper
    underneath ``walk_jsonl_source`` is keyed on source_key /
    event_hash / etc."""
    from elevate_cli.data import connect as _data_connect
    from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source

    stats = BackfillStats()
    with _data_connect() as conn:
        walk_jsonl_source(source_dir, conn=conn, stats=stats, dry_run=False)
    return stats.to_dict()


def scaffold_composio_social_source(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    blueprint = _blueprint("social")
    if not blueprint:
        raise RuntimeError("Composio social connector blueprint is missing")

    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "social")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = _now()
    surfaces = UI_BY_SOURCE["social"]
    owner = OWNER_BY_SOURCE["social"]
    prompt = source_prompt_for("social")
    prompt_path = artifacts_dir / "composio-social-setup-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    composio_server = _configured_composio_server(config)
    has_server = composio_server is not None
    next_step = (
        "Add Instagram, Facebook, LinkedIn, YouTube, TikTok, or other social apps inside Composio, "
        "then run the social sync/import agent prompt so Elevate can write local metrics, messages, lead events, and tasks."
        if has_server
        else (
            "Connect Composio MCP in Settings/config first, add the social apps inside Composio, "
            "then refresh this setup and run the social sync/import agent prompt."
        )
    )

    _write_json(
        source_dir / "source.json",
        {
            "source_id": "social",
            "provider": "Composio Social Accounts",
            "account_label": "Composio Social Hub",
            "connection_type": "composio_mcp" if has_server else "composio_mcp_setup",
            "auth_status": "composio_mcp_configured" if has_server else "needs_composio_account",
            "sync_mode": "composio_social_setup",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "needs_social_accounts" if has_server else "needs_composio_mcp",
            "last_sync_at": now,
            "setup_notes": (
                "Composio is the social account hub. Elevate reads through the local MCP/tool connection "
                "and writes normalized local source records; outbound replies remain approval-gated."
            ),
            "agent_setup_prompt_path": str(prompt_path),
            "composio_server": composio_server,
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": None,
            "next_operator_step": next_step,
            "last_checked_at": now,
        },
    )

    for file_name in JSONL_FILES:
        _replace_jsonl(source_dir / file_name, [])

    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": "social",
                "source_record_id": f"social-composio-setup:{now}",
                "display_name": "Composio Social Accounts",
                "timestamp": now,
                "title": "Connect social accounts in Composio",
                "status": "open",
                "task_type": "connector_setup",
                "approval_required": False,
                "owner_agent": owner,
                "summary": next_step,
                "agent_prompt_path": str(prompt_path),
                "agent_prompt": prompt,
                "confidence": 0.9,
                "tags": ["connector-setup", "composio", "social-media"],
                "target_ui_surfaces": ["Settings", "Social Media", "Leads", "Tasks"],
            }
        ],
    )
    _write_json(
        artifacts_dir / "setup-checklist.json",
        {
            "source_id": "social",
            "owner_agent": owner,
            "created_at": now,
            "steps": [
                "Connect the operator's Composio account in Elevate Settings/config.",
                "Add approved social apps inside Composio.",
                "Confirm read scopes for metrics, posts, comments, and DMs.",
                "Run the social sync/import agent prompt to write local records.",
                "Keep outbound replies and posts approval-gated.",
            ],
        },
    )
    view = connector_view(source_root, "social")
    if view is None:
        raise RuntimeError("Composio social scaffold was written but could not be read")
    return view


def scaffold_source(source_id: str, config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    blueprint = _blueprint(source_id)
    if not blueprint:
        raise ValueError(f"Unknown source connector: {source_id}")

    if source_id == "apple-messages":
        return initialize_apple_messages_source(config)
    if source_id == "social":
        return scaffold_composio_social_source(config)
    if source_id == "crm":
        integrations = _as_dict(config.get("integrations"))
        crm = _merge_crm(integrations.get("crm"))
        provider = str(crm.get("provider") or "").lower()
        env_values = _combined_env(config)
        if provider == "lofty" or (not provider and env_values.get("LOFTY_API_KEY")):
            return sync_lofty_crm_source(config)
        if provider in {"followupboss", "sierra", "boldtrail", "brivity", "custom"}:
            return sync_generic_crm_source(config)
        return sync_lofty_crm_source(config)
    if source_id == "xposure-pcs":
        # Real scraper + canonical writethrough lives in its own module
        # (the source_connectors file is already 5,800 lines and the
        # scraper is replaceable — keep it isolated).
        from elevate_cli.xposure_pcs_connector import sync_xposure_pcs_source

        # skip_scraper honored via env so cron + manual /api/source-
        # connectors/{id}/run can choose to reuse the latest snapshot
        # without burning a Lofty session.
        skip = bool(os.getenv("ELEVATE_XPOSURE_SKIP_SCRAPER"))
        return sync_xposure_pcs_source(config, skip_scraper=skip)
    if source_id == "buyer-brief":
        from elevate_cli.xposure_pcs_enrichment import run_enrichment

        return run_enrichment(config)
    if source_id == "xposure-pcs-views":
        # Per-listing engagement scrape (one-way mirror Client View).
        # Reuses the same Lofty/Xposure session as xposure-pcs but runs
        # on its own 48h cadence so we can re-fetch view counts without
        # re-running the criteria scrape every time.
        from elevate_cli.xposure_pcs_views import run_views_sync

        skip = bool(os.getenv("ELEVATE_XPOSURE_VIEWS_SKIP_SCRAPER"))
        views_cfg = _as_dict(config.get("xposure_pcs_views")) or config
        return run_views_sync(views_cfg, skip_scraper=skip)

    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, source_id)
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = _now()
    surfaces = UI_BY_SOURCE.get(source_id, ["Settings"])
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    prompt = source_prompt_for(source_id)
    prompt_path = artifacts_dir / "agent-setup-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    _write_json(
        source_dir / "source.json",
        {
            "source_id": source_id,
            "provider": blueprint["source"],
            "account_label": f"{blueprint['source']} setup",
            "connection_type": "agent_setup_task",
            "auth_status": "needs_agent_or_operator",
            "sync_mode": "agent_build_required",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "needs_agent_setup",
            "last_sync_at": now,
            "setup_notes": (
                "No live account is connected yet. Elevate created a local setup prompt and task "
                "for the agent/operator to build the real webhook, poller, import command, or local bridge."
            ),
            "agent_setup_prompt_path": str(prompt_path),
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": None,
            "next_operator_step": (
                f"Run the agent setup prompt at {prompt_path} to build the {blueprint['source']} "
                "connector. No records are imported until that connector exists."
            ),
            "last_checked_at": now,
        },
    )

    _replace_jsonl(source_dir / "contacts.jsonl", [])
    _replace_jsonl(source_dir / "conversations.jsonl", [])
    _replace_jsonl(source_dir / "messages.jsonl", [])
    _replace_jsonl(source_dir / "message-days.jsonl", [])
    _replace_jsonl(source_dir / "lead-events.jsonl", [])
    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": source_id,
                "source_record_id": f"{source_id}-agent-setup:{now}",
                "display_name": blueprint["source"],
                "timestamp": now,
                "title": f"Build {blueprint['source']} connector",
                "status": "open",
                "task_type": "connector_setup",
                "approval_required": False,
                "owner_agent": owner,
                "summary": (
                    "Use the generated setup prompt to create the real read-only connector, "
                    "then write normalized source records for the Hub."
                ),
                "agent_prompt_path": str(prompt_path),
                "agent_prompt": prompt,
                "confidence": 0.86,
                "tags": ["connector-setup", "agent-build-required"],
                "target_ui_surfaces": ["Settings", "Tasks"],
            }
        ],
    )
    _write_json(
        artifacts_dir / "setup-checklist.json",
        {
            "source_id": source_id,
            "owner_agent": owner,
            "created_at": now,
            "steps": [
                "Confirm provider/account and allowed data scope.",
                "Choose webhook, poller, import command, or local bridge.",
                "Create read-only credentials or export path.",
                "Normalize contacts, conversations, messages, lead events, and tasks.",
                "Mark status.json as connected, import_only, blocked, or needs_operator with exact next step.",
            ],
        },
    )
    view = connector_view(source_root, source_id)
    if view is None:
        raise RuntimeError("Connector scaffold was written but could not be read")
    return view


from elevate_cli.source_connector_modules.integration_settings import (
    DEFAULT_CRM,
    _CRM_PROVIDER_ALIASES,
    _CRM_PROVIDER_ENV_DEFAULTS,
    _canonical_crm_provider,
    _crm_to_ui,
    _merge_crm,
    _provider_from_admin_profile,
    _ui_crm_to_config,
    get_integration_settings,
    save_integration_settings,
    test_crm_connection,
)
