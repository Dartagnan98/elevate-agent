"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import base64
import json
import os
import re
import hashlib
import sqlite3
import urllib.parse
import urllib.request
from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.config import (
    get_config_path,
    get_elevate_home,
    get_env_path,
    load_config,
    load_env,
    save_config,
    save_env_value,
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

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

SOURCE_CONNECTION_BLUEPRINTS: tuple[JsonRecord, ...] = (
    {
        "id": "apple-messages",
        "source": "Apple Messages",
        "category": "messages",
        "informationNeeded": "Mac user, included handles, conversation scope, read permission, and reply policy.",
        "connectionLayer": "Local bridge or export writes normalized conversations, messages, lead events, and approval tasks.",
        "uiDestination": "Outreach threads, Leads, Today follow-ups, and approval queues for draft replies.",
        "successSignal": "A synced iMessage/SMS conversation appears as a thread with a lead event and reply-needed task.",
    },
    {
        "id": "sms-provider",
        "source": "SMS Provider",
        "category": "messages",
        "informationNeeded": "Provider name, numbers, webhook/API/export access, contact matching, and send approval policy.",
        "connectionLayer": "Webhook, poller, or import adapter maps provider records into Elevate message and lead files.",
        "uiDestination": "Live lead inbox, Outreach, Today hot replies, and source health in Settings.",
        "successSignal": "A new inbound provider text creates a message record, lead event, and follow-up task without manual copying.",
    },
    {
        "id": "android-device",
        "source": "Android Device SMS",
        "category": "messages",
        "informationNeeded": "Export method, device owner approval, included numbers, backup format, and sync cadence.",
        "connectionLayer": "Optional mobile helper, backup export, or manual import turns device messages into normalized source records.",
        "uiDestination": "Same SMS UI path as provider texts: Outreach, Leads, Today, and approval tasks.",
        "successSignal": "Imported Android messages show source confidence and do not claim live sync unless a helper exists.",
    },
    {
        "id": "rcs",
        "source": "RCS",
        "category": "messages",
        "informationNeeded": "Whether this is business RCS/provider messaging or personal device RCS, plus webhook/export access.",
        "connectionLayer": "Business/provider RCS uses a connector; personal RCS becomes a setup blocker unless export access exists.",
        "uiDestination": "Provider-style message threads and lead events when connected; setup blockers in Settings when not connectable.",
        "successSignal": "RCS is labeled connected, import-only, or blocked instead of being folded into generic SMS.",
    },
    {
        "id": "crm",
        "source": "CRM",
        "category": "leads",
        "informationNeeded": "CRM name, auth method, stage meanings, reliable fields, activity types, and owner mapping.",
        "connectionLayer": "CRM adapter maps contacts, stages, notes, activities, and exposed messages into Elevate records.",
        "uiDestination": "Leads, Admin, Outreach context, Today pipeline, and stale-follow-up queues.",
        "successSignal": "A CRM stage or activity change updates the lead/admin view and creates the right next action.",
    },
    {
        "id": "social",
        "source": "Composio Social Accounts",
        "category": "messages",
        "informationNeeded": "Composio account/MCP URL, connected social apps, metrics scope, DM/comment scope, lead definition, and reply workflow.",
        "connectionLayer": "Composio is the account hub. Elevate uses the local MCP/tool connection to read social posts, metrics, DMs, comments, and lead moments into normalized local records.",
        "uiDestination": "Social Media pulse, Leads from DMs/comments, content tasks, and approvals for drafted replies.",
        "successSignal": "A connected Composio social app can produce a local social metric, content task, lead event, or reply approval record.",
    },
    {
        "id": "email",
        "source": "Email",
        "category": "messages",
        "informationNeeded": "Mailbox, folders/labels, search terms, attachment policy, and storage destination.",
        "connectionLayer": "Read-only mailbox adapter or export importer creates conversations, lead events, and document tasks.",
        "uiDestination": "Leads, Outreach, document intake, admin tasks, and Today reply-needed rows.",
        "successSignal": "A website lead or referral email appears with source thread, summary, and next-step task.",
    },
    {
        "id": "skills",
        "source": "Skill Outputs",
        "category": "operations",
        "informationNeeded": "Skill name, artifact folders, refresh cadence, record shape, and which UI lane should consume it.",
        "connectionLayer": "Artifact reader ingests JSON, JSONL, markdown, PDFs, screenshots, and exports from the tools/data root.",
        "uiDestination": "Admin, seller updates, market stats, document routing, admin queues, and source activity.",
        "successSignal": "A fresh skill artifact shows in the correct dashboard lane with timestamp, source, and actionability.",
    },
    {
        "id": "market-stats",
        "source": "Market Stats",
        "category": "operations",
        "informationNeeded": "Market regions, property types, stats source, refresh cadence, and client-facing summary needs.",
        "connectionLayer": "Board, MLS, report, CSV, spreadsheet, or manual import writes dashboard-ready stats and artifacts.",
        "uiDestination": "Admin, Today prep, Social content, later Ads work, and market-report tasks.",
        "successSignal": "A fresh market artifact appears with period, region, metrics, source files, and next operator step.",
    },
    {
        "id": "admin-requirements",
        "source": "Admin Requirements",
        "category": "admin",
        "informationNeeded": "Jurisdiction, brokerage rules, transaction stages, required forms, deadlines, and human-only checks.",
        "connectionLayer": "Checklist or source import writes required items and generated admin tasks.",
        "uiDestination": "Admin, Today admin queue, Tasks, documents, and approvals.",
        "successSignal": "A deal stage exposes required docs, missing items, deadlines, and owner tasks without hardcoded brokerage rules.",
    },
    {
        "id": "document-storage",
        "source": "Document Storage",
        "category": "admin",
        "informationNeeded": "Storage provider/root, folder naming, document categories, permissions, and dry-run routing policy.",
        "connectionLayer": "Local or cloud indexer writes document-index records and routing tasks.",
        "uiDestination": "Admin, Today admin queue, document intake, and source activity.",
        "successSignal": "A sample document record appears with category, deal/listing match, confidence, status, and next action.",
    },
    {
        "id": "forms-signing",
        "source": "Forms & Signing",
        "category": "forms",
        "informationNeeded": "Form provider, blank forms/templates, recipient roles, field map, and approval policy.",
        "connectionLayer": "Provider-neutral form map and packet index writes dry-run packet records and approval tasks.",
        "uiDestination": "Admin, Today admin queue, approvals, and document routing.",
        "successSignal": "A packet draft appears as a dry-run artifact and every send/signing action is gated behind approval.",
    },
)

OWNER_BY_SOURCE = {
    "apple-messages": "Outreach",
    "sms-provider": "Outreach",
    "android-device": "Outreach",
    "rcs": "Outreach",
    "crm": "Outreach",
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

CONNECTION_CONTRACT = """Build this as an Elevate Agent connection layer, not a standalone note:

- Read the customer tools root from sources.tools_root or ELEVATE_TOOLS_ROOT.
- Create or update data/sources/<source-id> inside the customer tools root.
- Write source.json with provider, account_label, connection_type, auth_status, sync_mode, owner_agent, enabled_ui_surfaces, setup_status, last_sync_at, and setup_notes.
- Write status.json with connected, import_only, blocked, last_error, next_operator_step, and last_checked_at.
- Normalize people into contacts.jsonl, threads into conversations.jsonl, inbound/outbound items into messages.jsonl, qualified moments into lead-events.jsonl, and human work into tasks.jsonl.
- Store provider exports, screenshots, PDFs, reports, or raw files under artifacts/.
- Add or document the repeatable connector entrypoint: webhook route, polling command, import command, or local bridge command.

Start read-only. Do not send messages, submit forms, move files, change permissions, upload data, or create persistent API keys unless the operator explicitly approves that action."""

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
    skyleigh_tmp = get_elevate_home() / "tmp" / "skyleigh-tools"
    if env_root:
        return _expand_path(env_root)
    if configured:
        return _expand_path(configured)
    if skyleigh_tmp.exists():
        return skyleigh_tmp
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
    elif (get_elevate_home() / "tmp" / "skyleigh-tools").exists():
        root_source = "detected-skyleigh-tools"
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
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def _record_timestamp(record: JsonRecord) -> str:
    for key in ("timestamp", "last_message_at", "last_seen_at", "last_sync_at", "day"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _read_jsonl_records(path: Path, *, limit: int = 12, tail: bool = False) -> list[JsonRecord]:
    safe_limit = max(1, min(int(limit or 12), 100))
    if not path.exists():
        return []

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
    return sorted(records, key=_record_timestamp, reverse=True)


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
        "record": record,
    }


def _task_key(record: JsonRecord) -> str:
    for key in ("task_id", "source_record_id", "id", "conversation_id", "contact_id", "title"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return hashlib.sha1(json.dumps(record, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _draft_text_for_task(record: JsonRecord) -> str:
    for key in ("draft_text", "draft", "message", "proposed_text", "reply_text", "text"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return str(record.get("summary") or "").strip()


def _is_message_draft_task(record: JsonRecord) -> bool:
    haystack = " ".join(
        _tag_text(record.get(key))
        for key in ("task_type", "title", "summary", "tags", "channel", "target_ui_surfaces")
    )
    if "connector_setup" in haystack:
        return False
    if record.get("approval_required") is True:
        return True
    return any(
        token in haystack
        for token in (
            "message_draft",
            "draft reply",
            "reply draft",
            "follow_up",
            "follow-up",
            "text message",
            "dm reply",
            "comment reply",
            "outreach",
        )
    )


def _draft_recipient(record: JsonRecord, fallback: str = "Client") -> str:
    return _record_person_name(record) or fallback


def _fallback_draft_for_thread(thread: JsonRecord) -> str:
    name = str(thread.get("personName") or "there").strip()
    first = name.split()[0] if name and name.lower() not in {"client", "conversation"} else "there"
    source = str(thread.get("sourceLabel") or thread.get("channel") or "your message").strip()
    if str(thread.get("sourceId") or "").lower() in SOCIAL_SOURCE_IDS or "instagram" in source.lower() or "facebook" in source.lower():
        return (
            f"Hi {first}, thanks for reaching out. Are you looking for more details on a specific property, "
            "or are you starting to explore buying or selling?"
        )
    if str(thread.get("sourceId") or "").lower() == "crm":
        return f"Hi {first}, just checking in. Are you still looking for help with your next real estate step?"
    return f"Hi {first}, thanks for the message. What would be the most helpful next step for you right now?"


def _draft_from_task(source: JsonRecord, record: JsonRecord, state: JsonRecord | None = None) -> JsonRecord:
    state = state or {}
    source_id = str(source.get("id") or record.get("source_id") or "").strip()
    task_id = _task_key(record)
    draft_text = str(state.get("draft_text") or _draft_text_for_task(record)).strip()
    return {
        "id": f"{source_id}:{task_id}",
        "sourceId": source_id,
        "sourceLabel": str(source.get("label") or source_id),
        "taskId": task_id,
        "threadId": _thread_key(record),
        "contactId": record.get("contact_id"),
        "conversationId": record.get("conversation_id") or record.get("source_record_id"),
        "personName": _draft_recipient(record),
        "channel": _channel_label(source_id, source, record),
        "title": str(record.get("title") or "Review draft follow-up").strip(),
        "draftText": draft_text or "Draft text has not been generated yet.",
        "context": str(record.get("summary") or record.get("latest_text") or record.get("text") or "").strip(),
        "latestAt": _record_timestamp(record),
        "status": str(state.get("status") or record.get("status") or "pending"),
        "approvalRequired": bool(record.get("approval_required", True)),
        "generated": False,
        "record": record,
    }


def _draft_from_thread(source: JsonRecord, thread: JsonRecord) -> JsonRecord:
    source_id = str(thread.get("sourceId") or source.get("id") or "").strip()
    thread_id = str(thread.get("threadId") or _thread_key(_as_dict(thread.get("record"))))
    return {
        "id": f"{source_id}:thread-draft:{thread_id}",
        "sourceId": source_id,
        "sourceLabel": str(thread.get("sourceLabel") or source.get("label") or source_id),
        "taskId": f"thread-draft:{thread_id}",
        "threadId": thread_id,
        "contactId": thread.get("contactId"),
        "conversationId": thread.get("conversationId"),
        "personName": str(thread.get("personName") or "Client"),
        "channel": str(thread.get("channel") or _channel_label(source_id, source, _as_dict(thread.get("record")))),
        "title": "Draft follow-up",
        "draftText": _fallback_draft_for_thread(thread),
        "context": str(thread.get("latestText") or "").strip(),
        "latestAt": str(thread.get("latestAt") or ""),
        "status": "pending",
        "approvalRequired": True,
        "generated": True,
        "record": thread.get("record") or {},
    }


def _source_record_counts(source: JsonRecord) -> dict[str, int]:
    counts = source.get("recordCounts")
    return counts if isinstance(counts, dict) else {}


def _source_has_inbox_records(source: JsonRecord) -> bool:
    counts = _source_record_counts(source)
    return any(int(counts.get(key) or 0) > 0 for key in ("messages", "conversations", "contacts"))


def _string_values(value: Any) -> list[str]:
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_string_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for key in ("value", "phone", "email", "number", "address", "name", "label", "id"):
            if key in value:
                values.extend(_string_values(value.get(key)))
        return values
    text = str(value or "").strip()
    return [text] if text else []


def _phone_key(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 7:
        return None
    return f"phone:{digits[-10:] if len(digits) >= 10 else digits}"


def _email_key(value: str) -> str | None:
    text = value.strip().lower()
    if "@" not in text or "." not in text.split("@")[-1]:
        return None
    return f"email:{text}"


def _name_key(value: str) -> str | None:
    normalized = " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
    if len(normalized) < 4 or normalized in {"client conversation", "lofty lead", "apple messages conversation"}:
        return None
    return f"name:{normalized}"


def _profile_match_keys(record: JsonRecord, thread: JsonRecord) -> list[str]:
    candidates: list[str] = []
    for field in ("phones", "phone", "handle", "chat_identifier", "participant_handles"):
        for value in _string_values(record.get(field)):
            key = _phone_key(value) or _email_key(value)
            if key:
                candidates.append(key)
    for field in ("emails", "email"):
        for value in _string_values(record.get(field)):
            key = _email_key(value)
            if key:
                candidates.append(key)
    name = str(thread.get("personName") or record.get("display_name") or "").strip()
    name_match = _name_key(name)
    if name_match:
        candidates.append(name_match)
    seen: set[str] = set()
    return [key for key in candidates if not (key in seen or seen.add(key))]


def _profile_contact_values(record: JsonRecord) -> tuple[list[str], list[str]]:
    phones: list[str] = []
    emails: list[str] = []
    for field in ("phones", "phone", "handle", "chat_identifier", "participant_handles"):
        for value in _string_values(record.get(field)):
            if _phone_key(value):
                phones.append(value)
            elif _email_key(value):
                emails.append(value)
    for field in ("emails", "email"):
        for value in _string_values(record.get(field)):
            if _email_key(value):
                emails.append(value)
    return sorted(set(phones)), sorted(set(emails))


SOCIAL_SOURCE_IDS = {"social", "instagram", "facebook", "facebook-messenger", "meta", "tiktok", "linkedin"}
SOCIAL_INTENT_WORDS = (
    "buy",
    "buyer",
    "sell",
    "seller",
    "home",
    "house",
    "condo",
    "listing",
    "showing",
    "mortgage",
    "preapproved",
    "pre-approved",
    "relocate",
    "moving",
    "price",
    "valuation",
    "cma",
    "realtor",
    "agent",
)


def _is_social_intent(source: JsonRecord, thread: JsonRecord) -> bool:
    haystack = " ".join(
        str(value or "").lower()
        for value in (
            source.get("id"),
            source.get("label"),
            thread.get("channel"),
            thread.get("latestText"),
        )
    )
    is_social = any(source_id in haystack for source_id in SOCIAL_SOURCE_IDS)
    return is_social and any(word in haystack for word in SOCIAL_INTENT_WORDS)


def _profile_label(score: int) -> str:
    if score >= 76:
        return "hot"
    if score >= 54:
        return "warm"
    if score >= 35:
        return "watch"
    return "normal"


def _merge_profile(profile: JsonRecord, source: JsonRecord, thread: JsonRecord) -> None:
    record = _as_dict(thread.get("record"))
    phones, emails = _profile_contact_values(record)
    profile["sources"] = sorted({*profile.get("sources", []), str(thread.get("sourceLabel") or source.get("label") or "")})
    profile["sourceIds"] = sorted({*profile.get("sourceIds", []), str(thread.get("sourceId") or source.get("id") or "")})
    profile["channels"] = sorted({*profile.get("channels", []), str(thread.get("channel") or "")})
    profile["phones"] = sorted({*profile.get("phones", []), *phones})
    profile["emails"] = sorted({*profile.get("emails", []), *emails})
    profile["threadIds"] = sorted({*profile.get("threadIds", []), str(thread.get("id") or "")})
    profile["threadCount"] = len(profile["threadIds"])
    profile["hasConversation"] = True
    source_id = str(thread.get("sourceId") or source.get("id") or "")
    if source_id == "crm" or "crm" in str(thread.get("sourceLabel") or "").lower():
        profile["hasCrm"] = True
        profile["crmStage"] = record.get("stage") or profile.get("crmStage")
        profile["leadSource"] = record.get("lead_source") or record.get("source") or profile.get("leadSource")
    if _is_social_intent(source, thread):
        profile["isPotentialLead"] = True
    score = max(_safe_int(profile.get("heatScore")), _safe_int(thread.get("heatScore")))
    profile["heatScore"] = score
    profile["heatLabel"] = _profile_label(score)
    latest = _parse_record_dt(thread.get("latestAt"))
    current_latest = _parse_record_dt(profile.get("latestAt"))
    if latest and (not current_latest or latest >= current_latest):
        profile["latestAt"] = thread.get("latestAt")
        profile["latestText"] = thread.get("latestText")
    if not profile.get("displayName") or str(profile.get("displayName")) == "Client conversation":
        profile["displayName"] = thread.get("personName") or profile.get("displayName")
    tags = _string_values(record.get("tags"))
    profile["tags"] = sorted({*profile.get("tags", []), *tags})[:12]


def _profiles_from_threads(threads: list[JsonRecord], source_by_id: dict[str, JsonRecord]) -> list[JsonRecord]:
    profiles: dict[str, JsonRecord] = {}
    key_to_profile: dict[str, str] = {}
    for thread in threads:
        source = source_by_id.get(str(thread.get("sourceId") or ""), {})
        record = _as_dict(thread.get("record"))
        keys = _profile_match_keys(record, thread)
        profile_id = next((key_to_profile[key] for key in keys if key in key_to_profile), "")
        if not profile_id:
            profile_id = keys[0] if keys else f"thread:{thread.get('id')}"
        profile = profiles.setdefault(
            profile_id,
            {
                "id": profile_id,
                "displayName": thread.get("personName") or "Client conversation",
                "sources": [],
                "sourceIds": [],
                "channels": [],
                "phones": [],
                "emails": [],
                "threadIds": [],
                "threadCount": 0,
                "latestText": thread.get("latestText"),
                "latestAt": thread.get("latestAt"),
                "heatScore": thread.get("heatScore") or 0,
                "heatLabel": thread.get("heatLabel") or "normal",
                "hasCrm": False,
                "hasConversation": False,
                "isPotentialLead": False,
                "crmStage": None,
                "leadSource": None,
                "tags": [],
            },
        )
        for key in keys:
            key_to_profile[key] = profile_id
        _merge_profile(profile, source, thread)
    return sorted(
        profiles.values(),
        key=lambda item: (
            1 if item.get("hasCrm") else 0,
            _safe_int(item.get("heatScore")),
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )


def _replace_jsonl(path: Path, records: list[JsonRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp_path.replace(path)


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


def _apple_messages_chat_db_path() -> Path:
    override = os.getenv("ELEVATE_APPLE_MESSAGES_CHAT_DB", "").strip()
    if override:
        return _expand_path(override)
    return Path.home() / "Library" / "Messages" / "chat.db"


def _apple_dt(raw_value: Any) -> datetime | None:
    try:
        value = int(raw_value)
    except Exception:
        return None
    if value <= 0:
        return None
    seconds = value / 1_000_000_000 if value > 10_000_000_000 else value
    return APPLE_EPOCH + timedelta(seconds=seconds)


def _sqlite_uri(path: Path) -> str:
    return "file:" + urllib.parse.quote(str(path)) + "?mode=ro"


def _init_apple_index_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            source_record_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            handle TEXT NOT NULL,
            channel TEXT NOT NULL,
            first_seen_at TEXT,
            last_seen_at TEXT,
            total_messages INTEGER NOT NULL DEFAULT 0,
            inbound_count INTEGER NOT NULL DEFAULT 0,
            outbound_count INTEGER NOT NULL DEFAULT 0,
            last_text TEXT,
            target_ui_surfaces_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            source_record_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            channel TEXT NOT NULL,
            participant_handles_json TEXT NOT NULL,
            first_message_at TEXT,
            last_message_at TEXT,
            total_messages INTEGER NOT NULL DEFAULT 0,
            inbound_count INTEGER NOT NULL DEFAULT 0,
            outbound_count INTEGER NOT NULL DEFAULT 0,
            message_day_count INTEGER NOT NULL DEFAULT 0,
            last_text TEXT,
            target_ui_surfaces_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_days (
            source_record_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            day TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            inbound_count INTEGER NOT NULL DEFAULT 0,
            outbound_count INTEGER NOT NULL DEFAULT 0,
            first_message_at TEXT,
            last_message_at TEXT,
            summary TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            source_record_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            contact_id TEXT,
            person_key TEXT NOT NULL,
            direction TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            day TEXT NOT NULL,
            text TEXT,
            service TEXT,
            handle TEXT,
            chat_identifier TEXT,
            is_from_me INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_day ON messages(conversation_id, day);
        CREATE INDEX IF NOT EXISTS idx_messages_contact ON messages(contact_id);
        CREATE INDEX IF NOT EXISTS idx_conversation_days_conversation ON conversation_days(conversation_id);
        """
    )
    for table in ("contacts", "conversations", "conversation_days", "messages"):
        conn.execute(f"DELETE FROM {table}")
    return conn


def _load_chat_participants(conn: sqlite3.Connection) -> dict[int, list[str]]:
    try:
        rows = conn.execute(
            """
            SELECT chj.chat_id AS chat_id, h.id AS handle
            FROM chat_handle_join chj
            JOIN handle h ON h.ROWID = chj.handle_id
            WHERE h.id IS NOT NULL AND h.id != ''
            ORDER BY chj.chat_id, h.id
            """
        )
        participants: dict[int, list[str]] = {}
        for row in rows:
            chat_id = int(row["chat_id"])
            participants.setdefault(chat_id, [])
            handle = str(row["handle"])
            if handle not in participants[chat_id]:
                participants[chat_id].append(handle)
        return participants
    except sqlite3.Error:
        return {}


def _update_span(stats: JsonRecord, timestamp: str) -> None:
    if not stats.get("first_seen_at") or timestamp < str(stats["first_seen_at"]):
        stats["first_seen_at"] = timestamp
    if not stats.get("last_seen_at") or timestamp > str(stats["last_seen_at"]):
        stats["last_seen_at"] = timestamp


def _write_blocked_apple_messages_source(source_dir: Path, chat_db: Path, error: str) -> JsonRecord:
    now = _now()
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    surfaces = UI_BY_SOURCE["apple-messages"]
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "apple-messages",
            "provider": "Apple Messages",
            "account_label": "Mac Messages",
            "connection_type": "macos_messages_chat_db",
            "auth_status": "needs_full_disk_access",
            "sync_mode": "manual_snapshot",
            "owner_agent": OWNER_BY_SOURCE["apple-messages"],
            "enabled_ui_surfaces": surfaces,
            "setup_status": "blocked",
            "last_sync_at": None,
            "setup_notes": "Elevate needs local read access to the Mac Messages database before it can build the message index.",
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": True,
            "last_error": error,
            "next_operator_step": (
                "Grant Full Disk Access to the terminal/app running Elevate, make sure Messages are synced "
                f"to this Mac at {chat_db}, then click Initialize again."
            ),
            "last_checked_at": now,
        },
    )
    _replace_jsonl(source_dir / "contacts.jsonl", [])
    _replace_jsonl(source_dir / "conversations.jsonl", [])
    _replace_jsonl(source_dir / "messages.jsonl", [])
    _replace_jsonl(source_dir / "message-days.jsonl", [])
    _replace_jsonl(source_dir / "lead-events.jsonl", [])
    _replace_jsonl(source_dir / "tasks.jsonl", [])
    return connector_view(source_dir.parent, "apple-messages") or {}


def initialize_apple_messages_source(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "apple-messages")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    chat_db = _apple_messages_chat_db_path()
    surfaces = UI_BY_SOURCE["apple-messages"]
    now = _now()

    if not chat_db.exists():
        return _write_blocked_apple_messages_source(
            source_dir,
            chat_db,
            f"Mac Messages database was not found at {chat_db}",
        )

    try:
        read_conn = sqlite3.connect(_sqlite_uri(chat_db), uri=True, timeout=10)
        read_conn.row_factory = sqlite3.Row
        chat_participants = _load_chat_participants(read_conn)
        query = """
            SELECT
                m.ROWID AS message_rowid,
                m.guid AS message_guid,
                m.date AS message_date,
                m.text AS message_text,
                m.is_from_me AS is_from_me,
                m.service AS service,
                h.id AS handle_id,
                c.ROWID AS chat_rowid,
                c.guid AS chat_guid,
                c.chat_identifier AS chat_identifier,
                c.display_name AS chat_display_name
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE m.date IS NOT NULL
            ORDER BY m.date ASC, m.ROWID ASC
        """
        rows = read_conn.execute(query)
    except Exception as exc:
        try:
            read_conn.close()  # type: ignore[name-defined]
        except Exception:
            pass
        return _write_blocked_apple_messages_source(source_dir, chat_db, str(exc))

    index_path = source_dir / "elevate-messages.sqlite"
    write_conn = _init_apple_index_db(index_path)
    contacts: dict[str, JsonRecord] = {}
    conversations: dict[str, JsonRecord] = {}
    days: dict[str, JsonRecord] = {}
    imported = 0
    inbound = 0
    outbound = 0

    messages_tmp = source_dir / "messages.jsonl.tmp"
    try:
        with messages_tmp.open("w", encoding="utf-8") as message_fh:
            for row in rows:
                dt = _apple_dt(row["message_date"])
                if not dt:
                    continue
                timestamp = dt.isoformat()
                day = dt.date().isoformat()
                text = str(row["message_text"] or "").strip()
                is_from_me = bool(row["is_from_me"])
                direction = "outbound" if is_from_me else "inbound"
                if direction == "inbound":
                    inbound += 1
                else:
                    outbound += 1

                chat_rowid = row["chat_rowid"]
                handle = str(row["handle_id"] or "").strip()
                chat_identifier = str(row["chat_identifier"] or "").strip()
                chat_display = str(row["chat_display_name"] or "").strip()
                participants = chat_participants.get(int(chat_rowid), []) if chat_rowid is not None else []
                if handle and handle not in participants:
                    participants = [*participants, handle]

                conversation_id = (
                    f"apple-chat:{chat_rowid}"
                    if chat_rowid is not None
                    else f"apple-handle:{handle or chat_identifier or 'unknown'}"
                )
                conversation_label = chat_display or chat_identifier or ", ".join(participants) or handle or "Apple Messages conversation"
                external_handle = handle or (participants[0] if len(participants) == 1 else "")
                contact_id = f"apple-handle:{external_handle}" if external_handle else None
                person_key = "me" if is_from_me else (external_handle or "unknown")
                message_id = f"apple-message:{row['message_rowid']}:{chat_rowid or external_handle or 'direct'}"

                message_record = {
                    "source_id": "apple-messages",
                    "source_record_id": message_id,
                    "conversation_id": conversation_id,
                    "contact_id": contact_id,
                    "display_name": conversation_label,
                    "person_key": person_key,
                    "channel": "apple-messages",
                    "direction": direction,
                    "timestamp": timestamp,
                    "day": day,
                    "text": text,
                    "service": row["service"],
                    "handle": external_handle or None,
                    "chat_identifier": chat_identifier or None,
                    "confidence": 0.95,
                    "tags": ["apple-messages", "local-import"],
                    "target_ui_surfaces": surfaces,
                }
                message_fh.write(json.dumps(message_record, ensure_ascii=False) + "\n")
                write_conn.execute(
                    """
                    INSERT OR REPLACE INTO messages (
                        source_record_id, conversation_id, contact_id, person_key, direction,
                        timestamp, day, text, service, handle, chat_identifier, is_from_me
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        contact_id,
                        person_key,
                        direction,
                        timestamp,
                        day,
                        text,
                        row["service"],
                        external_handle,
                        chat_identifier,
                        1 if is_from_me else 0,
                    ),
                )

                if contact_id:
                    contact = contacts.setdefault(
                        contact_id,
                        {
                            "source_id": "apple-messages",
                            "source_record_id": contact_id,
                            "display_name": external_handle,
                            "channel": "apple-messages",
                            "handle": external_handle,
                            "confidence": 0.82,
                            "tags": ["apple-messages", "message-contact"],
                            "target_ui_surfaces": surfaces,
                            "total_messages": 0,
                            "inbound_count": 0,
                            "outbound_count": 0,
                            "first_seen_at": timestamp,
                            "last_seen_at": timestamp,
                            "last_text": text,
                        },
                    )
                    contact["total_messages"] = int(contact["total_messages"]) + 1
                    contact[f"{direction}_count"] = int(contact[f"{direction}_count"]) + 1
                    contact["last_text"] = text or contact.get("last_text")
                    _update_span(contact, timestamp)

                convo = conversations.setdefault(
                    conversation_id,
                    {
                        "source_id": "apple-messages",
                        "source_record_id": conversation_id,
                        "display_name": conversation_label,
                        "channel": "apple-messages",
                        "participant_handles": participants,
                        "confidence": 0.9,
                        "tags": ["apple-messages", "message-conversation"],
                        "target_ui_surfaces": surfaces,
                        "total_messages": 0,
                        "inbound_count": 0,
                        "outbound_count": 0,
                        "message_day_count": 0,
                        "first_message_at": timestamp,
                        "last_message_at": timestamp,
                        "last_text": text,
                    },
                )
                convo["total_messages"] = int(convo["total_messages"]) + 1
                convo[f"{direction}_count"] = int(convo[f"{direction}_count"]) + 1
                convo["last_text"] = text or convo.get("last_text")
                if participants:
                    existing = list(convo.get("participant_handles") or [])
                    convo["participant_handles"] = sorted({*existing, *participants})
                _update_span(convo, timestamp)

                day_id = f"{conversation_id}:{day}"
                day_record = days.setdefault(
                    day_id,
                    {
                        "source_id": "apple-messages",
                        "source_record_id": day_id,
                        "conversation_id": conversation_id,
                        "display_name": conversation_label,
                        "channel": "apple-messages",
                        "day": day,
                        "message_count": 0,
                        "inbound_count": 0,
                        "outbound_count": 0,
                        "first_message_at": timestamp,
                        "last_message_at": timestamp,
                        "target_ui_surfaces": surfaces,
                    },
                )
                day_record["message_count"] = int(day_record["message_count"]) + 1
                day_record[f"{direction}_count"] = int(day_record[f"{direction}_count"]) + 1
                _update_span(day_record, timestamp)
                imported += 1
    except Exception as exc:
        write_conn.close()
        read_conn.close()
        if messages_tmp.exists():
            messages_tmp.unlink()
        return _write_blocked_apple_messages_source(source_dir, chat_db, str(exc))

    read_conn.close()
    messages_tmp.replace(source_dir / "messages.jsonl")

    contact_records = sorted(contacts.values(), key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    conversation_records = sorted(conversations.values(), key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    day_records = sorted(days.values(), key=lambda item: (str(item.get("day") or ""), str(item.get("conversation_id") or "")), reverse=True)

    for conversation in conversation_records:
        conversation_days = [item for item in day_records if item["conversation_id"] == conversation["source_record_id"]]
        conversation["message_day_count"] = len(conversation_days)
        write_conn.execute(
            """
            INSERT OR REPLACE INTO conversations (
                source_record_id, display_name, channel, participant_handles_json,
                first_message_at, last_message_at, total_messages, inbound_count,
                outbound_count, message_day_count, last_text, target_ui_surfaces_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation["source_record_id"],
                conversation["display_name"],
                conversation["channel"],
                json.dumps(conversation.get("participant_handles") or []),
                conversation.get("first_seen_at") or conversation.get("first_message_at"),
                conversation.get("last_seen_at") or conversation.get("last_message_at"),
                conversation["total_messages"],
                conversation["inbound_count"],
                conversation["outbound_count"],
                conversation["message_day_count"],
                conversation.get("last_text"),
                json.dumps(surfaces),
            ),
        )

    for contact in contact_records:
        write_conn.execute(
            """
            INSERT OR REPLACE INTO contacts (
                source_record_id, display_name, handle, channel, first_seen_at,
                last_seen_at, total_messages, inbound_count, outbound_count,
                last_text, target_ui_surfaces_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact["source_record_id"],
                contact["display_name"],
                contact["handle"],
                contact["channel"],
                contact["first_seen_at"],
                contact["last_seen_at"],
                contact["total_messages"],
                contact["inbound_count"],
                contact["outbound_count"],
                contact.get("last_text"),
                json.dumps(surfaces),
            ),
        )

    for day_record in day_records:
        summary = (
            f"{day_record['message_count']} messages with {day_record['display_name']} "
            f"on {day_record['day']}."
        )
        day_record["summary"] = summary
        write_conn.execute(
            """
            INSERT OR REPLACE INTO conversation_days (
                source_record_id, conversation_id, day, message_count, inbound_count,
                outbound_count, first_message_at, last_message_at, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day_record["source_record_id"],
                day_record["conversation_id"],
                day_record["day"],
                day_record["message_count"],
                day_record["inbound_count"],
                day_record["outbound_count"],
                day_record["first_seen_at"],
                day_record["last_seen_at"],
                summary,
            ),
        )

    write_conn.commit()
    write_conn.close()

    _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
    _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
    _replace_jsonl(source_dir / "message-days.jsonl", day_records)
    _replace_jsonl(
        source_dir / "lead-events.jsonl",
        [
            {
                "source_id": "apple-messages",
                "source_record_id": f"apple-messages-import:{now}",
                "type": "message_database_imported",
                "display_name": "Apple Messages import",
                "channel": "apple-messages",
                "timestamp": now,
                "summary": (
                    f"Imported {imported} messages across {len(contact_records)} people, "
                    f"{len(conversation_records)} conversations, and {len(day_records)} conversation-days."
                ),
                "confidence": 0.95,
                "tags": ["apple-messages", "local-import"],
                "target_ui_surfaces": surfaces,
            }
        ],
    )
    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": "apple-messages",
                "source_record_id": f"apple-messages-review:{now}",
                "display_name": "Apple Messages",
                "timestamp": now,
                "title": "Review imported message clients and conversations",
                "status": "open",
                "approval_required": False,
                "owner_agent": OWNER_BY_SOURCE["apple-messages"],
                "summary": "Confirm which imported conversations should be treated as real estate clients or leads.",
                "counts": {
                    "contacts": len(contact_records),
                    "conversations": len(conversation_records),
                    "messages": imported,
                    "conversation_days": len(day_records),
                },
                "target_ui_surfaces": ["Leads", "Outreach", "Today"],
            }
        ],
    )
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "apple-messages",
            "provider": "Apple Messages",
            "account_label": "Mac Messages",
            "connection_type": "macos_messages_chat_db_snapshot",
            "auth_status": "local_read_ok",
            "sync_mode": "manual_snapshot",
            "owner_agent": OWNER_BY_SOURCE["apple-messages"],
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected",
            "last_sync_at": now,
            "setup_notes": "Local read-only snapshot imported from Mac Messages chat.db.",
            "database_path": str(index_path),
            "source_database_path": str(chat_db),
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "messages": imported,
                "message_days": len(day_records),
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": True,
            "import_only": True,
            "blocked": False,
            "last_error": None,
            "next_operator_step": "Click Refresh/Re-import to update the local message database. Live background sync is not enabled yet.",
            "last_checked_at": now,
            "last_imported_at": now,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "messages": imported,
                "inbound": inbound,
                "outbound": outbound,
                "message_days": len(day_records),
            },
        },
    )
    view = connector_view(source_root, "apple-messages")
    if view is None:
        raise RuntimeError("Apple Messages import finished but could not be read")
    return view


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


def _blueprint(source_id: str) -> JsonRecord | None:
    return next((item for item in SOURCE_CONNECTION_BLUEPRINTS if item["id"] == source_id), None)


def source_prompt_for(source_id: str) -> str:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return ""
    surfaces = ", ".join(UI_BY_SOURCE.get(source_id, ["Settings"]))
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    extra_contract = f"\n\n{COMPOSIO_SOCIAL_CONTRACT}" if source_id == "social" else ""
    return (
        f"You are wiring {blueprint['source']} into Elevate Agent.\n\n"
        f"Connection goal:\nCreate a read-only local source first. Use source_id={source_id}. "
        "If credentials, OAuth, exports, webhook approval, or app review are needed, mark status.json as needs_operator with the exact next step.\n\n"
        f"Information Elevate needs:\n{blueprint['informationNeeded']}\n\n"
        f"{CONNECTION_CONTRACT}{extra_contract}\n\n"
        f"Connector behavior:\n- owner_agent={owner}\n- target UI surfaces: {surfaces}\n"
        "- include source_id, source_record_id, source_url when available, display_name, channel, direction, timestamp, text or summary, confidence, tags, and target_ui_surfaces.\n"
        "- put outbound work in tasks.jsonl with approval_required=true unless the operator explicitly authorizes sending.\n\n"
        f"Done when:\n{blueprint['successSignal']}\n"
    )


def _initialize_behavior(source_id: str) -> str:
    if source_id == "apple-messages":
        return "local_messages_import"
    if source_id == "social":
        return "composio_social_setup"
    return "agent_setup_task"


def connector_view(source_root: Path, source_id: str) -> JsonRecord | None:
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

    return {
        "id": source_id,
        "label": label,
        "category": blueprint.get("category", "operations"),
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
        "ownerAgent": owner_agent or OWNER_BY_SOURCE.get(source_id, "Executive Assistant"),
        "enabledUiSurfaces": [str(item) for item in enabled_surfaces if str(item).strip()],
        "connected": bool(status and status.get("connected") is True),
        "importOnly": bool(status and status.get("import_only") is True),
        "blocked": bool(status and status.get("blocked") is True),
        "lastError": str(status.get("last_error") or "").strip() if isinstance(status, dict) and status.get("last_error") else None,
        "nextOperatorStep": (
            str(status.get("next_operator_step") or "").strip()
            if isinstance(status, dict) and status.get("next_operator_step")
            else (
                "Initialize this source to create the connector files."
                if state == "not_configured"
                else None
            )
        ),
        "lastCheckedAt": status.get("last_checked_at") if isinstance(status, dict) else None,
        "recordCounts": record_counts,
        "prompt": source_prompt_for(source_id),
    }


def build_source_connectors_response(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]))) is not None
    ]
    return {
        **info,
        "blueprints": [dict(item, prompt=source_prompt_for(str(item["id"]))) for item in SOURCE_CONNECTION_BLUEPRINTS],
        "promptCategories": list(SOURCE_PROMPT_CATEGORIES),
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
    safe_limit = max(1, min(int(limit or 16), 500))
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]))) is not None
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

        for record in _candidate_records_for_source(source_dir, source, 100):
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

        for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=100):
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
        if len(drafts) >= 24:
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
        task_id = f"thread-draft:{thread.get('threadId')}"
        state = _as_dict(task_state_by_source.get(source_id, {}).get(task_id))
        status = str(state.get("status") or "").lower()
        if status in {"approved", "skipped", "done", "archived", "cancelled"}:
            continue
        generated_id = f"{source_id}:{task_id}"
        if generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
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
    return {
        **info,
        "limit": safe_limit,
        "recordCounts": totals,
        "hiddenCounts": hidden_counts,
        "sources": connectors,
        "profiles": profiles[:safe_limit],
        "threads": visible_threads,
        "drafts": drafts[:safe_limit],
        "skippedDrafts": skipped_drafts[: max(safe_limit, 50)],
    }


def _resolve_source_view(source_root: Path, source_id: str) -> JsonRecord | None:
    view = connector_view(source_root, source_id)
    if view is not None:
        return view
    if source_id.startswith("composio-"):
        return _composio_connector_view(source_root, source_id)
    return None


def _message_for_thread(record: JsonRecord) -> JsonRecord | None:
    text = ""
    for key in ("text", "body", "message", "summary", "title"):
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

    raw_messages = _read_jsonl_records(source_dir / "messages.jsonl", limit=2000, tail=True)
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

    lead_record: JsonRecord | None = None
    for record in _read_jsonl_records(source_dir / "contacts.jsonl", limit=2000):
        if str(record.get("contact_id") or record.get("id") or "").strip() == thread_id:
            lead_record = record
            if not person_name:
                person_name = _record_person_name(record)
            break

    activity_records: list[JsonRecord] = []
    for record in _read_jsonl_records(source_dir / "lead-events.jsonl", limit=2000):
        if str(record.get("contact_id") or record.get("conversation_id") or "").strip() != thread_id:
            continue
        activity_records.append(
            {
                "id": str(record.get("source_record_id") or record.get("id") or ""),
                "type": record.get("type") or record.get("event_type") or "event",
                "title": record.get("title") or record.get("summary") or record.get("text"),
                "summary": record.get("summary") or record.get("text"),
                "timestamp": record.get("timestamp") or record.get("created_at") or record.get("last_seen_at"),
            }
        )
    activity_records.sort(
        key=lambda a: _parse_record_dt(a.get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    activity_records = activity_records[:20]

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
        "notes": [],
        "activity": activity_records,
        "stubs": {
            "notes": "Notes endpoint not yet wired (planned: GET /api/contacts/{id}/notes).",
            "activity": "Property activity endpoint not yet wired (planned: GET /api/contacts/{id}/activity).",
        },
    }


def update_source_thread_state(
    source_id: str,
    thread_id: str,
    action: str,
    config: dict[str, Any] | None = None,
) -> JsonRecord:
    config = config or load_config()
    if not _blueprint(source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"done", "archive", "restore", "open"}:
        raise ValueError("Unsupported thread action")

    info = get_source_root_info(config)
    source_dir = _source_dir(Path(info["sourceRoot"]), source_id)
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
    return build_source_inbox_response(config)


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


def update_source_task_state(
    source_id: str,
    task_id: str,
    action: str,
    *,
    draft_text: str | None = None,
    config: dict[str, Any] | None = None,
) -> JsonRecord:
    config = config or load_config()
    if not _blueprint(source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"approve", "edit", "skip", "restore", "open"}:
        raise ValueError("Unsupported draft action")

    info = get_source_root_info(config)
    source_dir = _source_dir(Path(info["sourceRoot"]), source_id)
    state = _read_source_ui_state(source_dir)
    tasks = _as_dict(state.get("tasks"))

    if normalized in {"restore", "open"}:
        tasks.pop(task_id, None)
        state["tasks"] = tasks
        _write_source_ui_state(source_dir, state)
        return build_source_inbox_response(config)

    status = "approved" if normalized == "approve" else "skipped" if normalized == "skip" else "pending"
    existing = _as_dict(tasks.get(task_id))
    existing.update({"status": status, "updated_at": _now()})
    if draft_text is not None:
        existing["draft_text"] = str(draft_text)
    tasks[task_id] = existing
    state["tasks"] = tasks

    if normalized == "approve":
        _approve_atomic(source_id, task_id, existing, source_dir, state)
    else:
        _write_source_ui_state(source_dir, state)

    return build_source_inbox_response(config)


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

    thread_id = str(task_record.get("thread_id") or task_record.get("threadId") or task_id)
    draft_text = str(task_record.get("draft_text") or "").strip()
    payload = {
        "draft_text": draft_text,
        "recipient": {
            "person_name": task_record.get("person_name") or task_record.get("personName"),
            "contact_id": task_record.get("contact_id"),
            "conversation_id": task_record.get("conversation_id") or task_record.get("source_record_id"),
            "phone": task_record.get("phone") or task_record.get("recipient_phone"),
            "email": task_record.get("email") or task_record.get("recipient_email"),
            "social_handle": task_record.get("social_handle") or task_record.get("recipient_handle"),
        },
        "channel_meta": {
            "toolkit": task_record.get("toolkit"),
            "account_id": task_record.get("composio_account_id"),
        },
        "source_id": source_id,
        "thread_id": thread_id,
        "task_id": task_id,
    }
    attempt_id = task_record.get("attempt_id") or task_record.get("attemptId")

    with outreach_db.connect() as conn:
        with outreach_db.transaction(conn):
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


def _lofty_lead_name(lead: JsonRecord) -> str:
    full = str(lead.get("name") or lead.get("fullName") or lead.get("leadName") or "").strip()
    if full:
        return full
    first = str(lead.get("firstName") or "").strip()
    last = str(lead.get("lastName") or "").strip()
    return " ".join(part for part in (first, last) if part).strip() or "Lofty lead"


def _lofty_timestamp(lead: JsonRecord) -> str:
    for key in ("updatedAt", "lastActivityTime", "lastModified", "createdAt", "created", "updated"):
        parsed = _parse_record_dt(lead.get(key))
        if parsed:
            return parsed.isoformat()
    return _now()


def _list_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _tag_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        if isinstance(item, dict):
            raw = item.get("name") or item.get("tagName") or item.get("label") or item.get("value")
        else:
            raw = item
        text = str(raw or "").strip()
        if text:
            tags.append(text)
    return tags


def _extract_lead_records(payload: Any) -> list[JsonRecord]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("workingLeads", "leads", "people", "contacts", "data", "items", "results", "records", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _basic_auth_header(api_key: str) -> str:
    encoded = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _build_crm_auth(crm: JsonRecord, api_key: str) -> tuple[dict[str, str], str | None]:
    """Return (headers, query_param_override). headers always include Accept/Content-Type."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth_type = str(crm.get("auth_type") or "header").lower()
    if auth_type == "query":
        return headers, str(crm.get("auth_query_param") or "api_key")
    if auth_type == "basic":
        headers["Authorization"] = _basic_auth_header(api_key)
        return headers, None
    header_name = str(crm.get("auth_header") or "Authorization")
    prefix = str(crm.get("auth_prefix") or "")
    headers[header_name] = f"{prefix}{api_key}"
    return headers, None


def _generic_crm_get(
    crm: JsonRecord,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    base = str(crm.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("CRM base URL is not set")
    headers, query_param = _build_crm_auth(crm, api_key)
    url = f"{base}/{path.lstrip('/')}"
    merged_params = dict(params or {})
    if query_param:
        merged_params[query_param] = api_key
    if merged_params:
        query = urllib.parse.urlencode(
            {key: value for key, value in merged_params.items() if value is not None}
        )
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _generic_crm_write(
    crm: JsonRecord,
    api_key: str,
    path: str,
    body: JsonRecord,
    method: str = "POST",
) -> Any:
    base = str(crm.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("CRM base URL is not set")
    headers, query_param = _build_crm_auth(crm, api_key)
    url = f"{base}/{path.lstrip('/')}"
    if query_param:
        url = f"{url}?{urllib.parse.urlencode({query_param: api_key})}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _provider_label(provider: str) -> str:
    return {
        "followupboss": "Follow Up Boss",
        "sierra": "Sierra Interactive",
        "boldtrail": "BoldTrail",
        "brivity": "Brivity",
    }.get(provider.lower(), provider.title() if provider else "CRM")


def sync_generic_crm_source(
    config: dict[str, Any] | None = None, *, limit: int = 50
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

    _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
    _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
    _replace_jsonl(source_dir / "messages.jsonl", [])
    _replace_jsonl(source_dir / "message-days.jsonl", [])
    _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
    preserved_tasks = [
        r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
        if str(r.get("task_type") or "").lower() != "lead_follow_up"
    ]
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
    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError(f"{label} source could not be read")
    return view


def _lofty_headers(env_values: dict[str, str]) -> tuple[dict[str, str], str]:
    access_token = str(env_values.get("LOFTY_ACCESS_TOKEN") or "").strip()
    api_key = str(env_values.get("LOFTY_API_KEY") or "").strip()
    if access_token:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }, "oauth_access_token"
    if api_key:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"token {api_key}",
        }, "api_key"
    return {"Accept": "application/json", "Content-Type": "application/json"}, "missing"


def _lofty_get(path: str, env_values: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    headers, _auth_type = _lofty_headers(env_values)
    if headers.get("Authorization") is None:
        raise RuntimeError("LOFTY_API_KEY or LOFTY_ACCESS_TOKEN is not set")
    base = "https://api.lofty.com"
    url = f"{base}/{path.lstrip('/')}"
    if params:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _lofty_write(
    path: str,
    env_values: dict[str, str],
    body: JsonRecord,
    method: str = "POST",
) -> Any:
    headers, _auth_type = _lofty_headers(env_values)
    if not headers.get("Authorization"):
        raise RuntimeError("LOFTY_API_KEY or LOFTY_ACCESS_TOKEN is not set")
    base = "https://api.chime.me"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


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
    provider = str(crm.get("provider") or "lofty").lower()
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


def sync_lofty_crm_source(config: dict[str, Any] | None = None, *, limit: int = 50) -> JsonRecord:
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

    leads: list[JsonRecord] = []
    attempted: list[str] = []
    errors: list[str] = []
    for path, params in (
        ("/v2.0/working-leads", {"aiStage": "HIGH_PRIORITY", "limit": min(limit, 100), "offset": 0, "sort": "UpdateTime", "desc": "true"}),
        ("/v1.0/leads", {"limit": min(limit, 100), "offset": 0}),
    ):
        attempted.append(path)
        try:
            payload = _lofty_get(path, env_values, params)
            extracted = _extract_lead_records(payload)
            if extracted:
                leads.extend(extracted)
        except Exception as exc:
            errors.append(f"{path}: {exc}")

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
    for lead in deduped:
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
            "assigned_user": lead.get("assignedUser") or lead.get("assignedAgent"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, "lofty-crm", "crm-lead"],
            "confidence": 0.86,
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
                "title": "Lofty lead synced",
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

    _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
    _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
    _replace_jsonl(source_dir / "messages.jsonl", [])
    _replace_jsonl(source_dir / "message-days.jsonl", [])
    _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
    preserved_tasks = [
        r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
        if str(r.get("task_type") or "").lower() != "lead_follow_up"
    ]
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
                else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
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
    if errors:
        _write_json(artifacts_dir / "last-sync-errors.json", {"checked_at": now, "errors": errors})
    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError("Lofty CRM sync finished but could not be read")
    return view


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


DEFAULT_CRM = {
    "provider": "custom",
    "label": "CRM",
    "api_key_env": "CRM_API_KEY",
    "base_url": "",
    "auth_type": "header",
    "auth_header": "Authorization",
    "auth_prefix": "Bearer ",
    "auth_query_param": "api_key",
    "db_columns": {
        "lead_id": "crm_lead_id",
        "stage": "crm_stage",
        "tags": "crm_tags",
    },
    "endpoints": {
        "leads": "/v1/leads",
        "lead": "/v1/leads/:id",
        "notes": "/v1/leads/:id/notes",
    },
}


def _merge_crm(raw: Any) -> JsonRecord:
    merged = deepcopy(DEFAULT_CRM)
    raw_dict = _as_dict(raw)
    for key, value in raw_dict.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _crm_to_ui(crm: JsonRecord, env_values: dict[str, str]) -> JsonRecord:
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    key_value = env_values.get(env_key) or ""
    return {
        "provider": str(crm.get("provider") or "custom"),
        "label": str(crm.get("label") or "CRM"),
        "apiKeyEnv": env_key,
        "hasApiKey": bool(key_value),
        "apiKeyPreview": f"{key_value[:4]}...{key_value[-4:]}" if len(key_value) > 8 else ("set" if key_value else None),
        "baseUrl": str(crm.get("base_url") or ""),
        "authType": str(crm.get("auth_type") or "header"),
        "authHeader": str(crm.get("auth_header") or "Authorization"),
        "authPrefix": str(crm.get("auth_prefix") or "Bearer "),
        "authQueryParam": str(crm.get("auth_query_param") or "api_key"),
        "dbColumns": {
            "leadId": str(_as_dict(crm.get("db_columns")).get("lead_id") or "crm_lead_id"),
            "stage": str(_as_dict(crm.get("db_columns")).get("stage") or "crm_stage"),
            "tags": str(_as_dict(crm.get("db_columns")).get("tags") or "crm_tags"),
        },
        "endpoints": {
            "leads": str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads"),
            "lead": str(_as_dict(crm.get("endpoints")).get("lead") or "/v1/leads/:id"),
            "notes": str(_as_dict(crm.get("endpoints")).get("notes") or "/v1/leads/:id/notes"),
        },
    }


def get_integration_settings(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    env_values = _combined_env(config)
    if env_values.get("LOFTY_API_KEY") and not str(crm.get("base_url") or "").strip():
        crm.update(
            {
                "provider": "lofty",
                "label": "Lofty CRM",
                "api_key_env": "LOFTY_API_KEY",
                "base_url": "https://api.lofty.com",
                "auth_type": "header",
                "auth_header": "Authorization",
                "auth_prefix": "token ",
                "endpoints": {
                    **_as_dict(crm.get("endpoints")),
                    "leads": "/v1.0/leads",
                    "lead": "/v1.0/leads/:id",
                    "notes": "/v2.0/leads/:id/activities",
                },
            }
        )
    return {
        "configPath": str(get_config_path()),
        "secretsPath": str(get_env_path()),
        "sourceRoot": get_source_root_info(config)["sourceRoot"],
        "crm": _crm_to_ui(crm, env_values),
    }


def _ui_crm_to_config(form: JsonRecord) -> JsonRecord:
    db_columns = _as_dict(form.get("dbColumns"))
    endpoints = _as_dict(form.get("endpoints"))
    return {
        "provider": str(form.get("provider") or "custom"),
        "label": str(form.get("label") or "CRM"),
        "api_key_env": str(form.get("apiKeyEnv") or "CRM_API_KEY"),
        "base_url": str(form.get("baseUrl") or "").rstrip("/"),
        "auth_type": str(form.get("authType") or "header"),
        "auth_header": str(form.get("authHeader") or "Authorization"),
        "auth_prefix": str(form.get("authPrefix") or "Bearer "),
        "auth_query_param": str(form.get("authQueryParam") or "api_key"),
        "db_columns": {
            "lead_id": str(db_columns.get("leadId") or "crm_lead_id"),
            "stage": str(db_columns.get("stage") or "crm_stage"),
            "tags": str(db_columns.get("tags") or "crm_tags"),
        },
        "endpoints": {
            "leads": str(endpoints.get("leads") or "/v1/leads"),
            "lead": str(endpoints.get("lead") or "/v1/leads/:id"),
            "notes": str(endpoints.get("notes") or "/v1/leads/:id/notes"),
        },
    }


def save_integration_settings(form: JsonRecord) -> JsonRecord:
    config = load_config()
    next_config = deepcopy(config)
    next_config.setdefault("integrations", {})
    next_config["integrations"]["crm"] = _ui_crm_to_config(form)
    api_key = str(form.get("apiKey") or "")
    if api_key:
        save_env_value(str(next_config["integrations"]["crm"]["api_key_env"]), api_key)
    save_config(next_config)
    return get_integration_settings(load_config())


def test_crm_connection(form: JsonRecord) -> JsonRecord:
    crm = _ui_crm_to_config(form)
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(form.get("apiKey") or _combined_env(load_config()).get(env_key) or "")
    base_url = str(crm.get("base_url") or "").rstrip("/")
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")
    if not base_url:
        return {"success": False, "error": "CRM base URL is required"}
    if not api_key:
        return {"success": False, "error": f"{env_key} is not set"}

    url = f"{base_url}/{leads_path.lstrip('/')}"
    headers = {"Accept": "application/json"}
    auth_type = str(crm.get("auth_type") or "header").lower()
    if auth_type == "query":
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        query[str(crm.get("auth_query_param") or "api_key")] = [api_key]
        url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
    elif auth_type == "basic":
        headers["Authorization"] = _basic_auth_header(api_key)
    else:
        headers[str(crm.get("auth_header") or "Authorization")] = f"{crm.get('auth_prefix') or ''}{api_key}"

    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1024 * 1024)
            status = response.status
        parsed = json.loads(raw.decode("utf-8") or "{}")
        count = 0
        if isinstance(parsed, list):
            count = len(parsed)
        elif isinstance(parsed, dict):
            for key in ("leads", "data", "items", "results", "records"):
                value = parsed.get(key)
                if isinstance(value, list):
                    count = len(value)
                    break
        return {"success": True, "status": status, "message": f"Connection worked. Saw {count} lead record(s)."}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
