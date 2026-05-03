"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
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
        "source": "Social DMs",
        "category": "messages",
        "informationNeeded": "Business inboxes, account type, provider/API/export path, lead definition, and reply workflow.",
        "connectionLayer": "Official webhook, provider export, or manual import turns business DMs into conversations and lead events.",
        "uiDestination": "Lead inbox, Outreach, nurture tasks, and approvals for drafted replies.",
        "successSignal": "A qualified DM becomes a lead with channel, source URL, confidence, and an owner task.",
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
    "social": "Outreach",
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


def _replace_jsonl(path: Path, records: list[JsonRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp_path.replace(path)


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
    return (
        f"You are wiring {blueprint['source']} into Elevate Agent.\n\n"
        f"Connection goal:\nCreate a read-only local source first. Use source_id={source_id}. "
        "If credentials, OAuth, exports, webhook approval, or app review are needed, mark status.json as needs_operator with the exact next step.\n\n"
        f"Information Elevate needs:\n{blueprint['informationNeeded']}\n\n"
        f"{CONNECTION_CONTRACT}\n\n"
        f"Connector behavior:\n- owner_agent={owner}\n- target UI surfaces: {surfaces}\n"
        "- include source_id, source_record_id, source_url when available, display_name, channel, direction, timestamp, text or summary, confidence, tags, and target_ui_surfaces.\n"
        "- put outbound work in tasks.jsonl with approval_required=true unless the operator explicitly authorizes sending.\n\n"
        f"Done when:\n{blueprint['successSignal']}\n"
    )


def _initialize_behavior(source_id: str) -> str:
    if source_id == "apple-messages":
        return "local_messages_import"
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

    return {
        "id": source_id,
        "label": blueprint["source"],
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


def scaffold_source(source_id: str, config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    blueprint = _blueprint(source_id)
    if not blueprint:
        raise ValueError(f"Unknown source connector: {source_id}")

    if source_id == "apple-messages":
        return initialize_apple_messages_source(config)

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
    return {
        "configPath": str(get_config_path()),
        "secretsPath": str(get_env_path()),
        "sourceRoot": get_source_root_info(config)["sourceRoot"],
        "crm": _crm_to_ui(crm, load_env()),
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
    api_key = str(form.get("apiKey") or load_env().get(env_key) or "")
    base_url = str(crm.get("base_url") or "").rstrip("/")
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")
    if not base_url:
        return {"success": False, "error": "CRM base URL is required"}
    if not api_key:
        return {"success": False, "error": f"{env_key} is not set"}

    url = f"{base_url}/{leads_path.lstrip('/')}"
    headers = {"Accept": "application/json"}
    if crm.get("auth_type") == "query":
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        query[str(crm.get("auth_query_param") or "api_key")] = [api_key]
        url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
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
