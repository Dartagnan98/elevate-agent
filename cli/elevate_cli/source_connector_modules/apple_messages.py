"""Apple Messages source connector helpers."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.config import load_config


JsonRecord = dict[str, Any]

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _now() -> str:
    return _source_connectors()._now()


def get_source_root_info(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return _source_connectors().get_source_root_info(config)


def _source_dir(source_root: Path, source_id: str) -> Path:
    return _source_connectors()._source_dir(source_root, source_id)


def _read_json(path: Path) -> JsonRecord | None:
    return _source_connectors()._read_json(path)


def _write_json(path: Path, value: JsonRecord) -> None:
    _source_connectors()._write_json(path, value)


def _replace_jsonl(path: Path, records: list[JsonRecord]) -> None:
    _source_connectors()._replace_jsonl(path, records)


def _walk_jsonl_into_pg(source_dir: Path) -> dict[str, Any]:
    return _source_connectors()._walk_jsonl_into_pg(source_dir)


def connector_view(source_root: Path, source_id: str) -> JsonRecord | None:
    return _source_connectors().connector_view(source_root, source_id)


def _ui_by_source(source_id: str) -> list[str]:
    return list(_source_connectors().UI_BY_SOURCE[source_id])


def _owner_by_source(source_id: str) -> str:
    return str(_source_connectors().OWNER_BY_SOURCE[source_id])


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


def _apple_messages_source_dir(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    info = get_source_root_info(config)
    return _source_dir(Path(info["sourceRoot"]), "apple-messages")


def get_apple_messages_directions(config: dict[str, Any] | None = None) -> dict[str, bool]:
    """Read the inbound/outbound enable flags for the Apple Messages source.

    - inbound  = read the Mac ``chat.db`` as a lead source. Needs Full Disk
      Access granted to the app (the source of the FDA banner).
    - outbound = send approved texts through Messages. Does NOT need FDA.

    The two are independent on purpose: a realtor can send outreach to new
    numbers (outbound) without ever importing their personal message history
    (inbound). Defaults: both enabled, preserving prior behavior."""
    try:
        data = _read_json(_apple_messages_source_dir(config) / "directions.json") or {}
    except Exception:
        data = {}
    return {
        "inbound": bool(data.get("inbound", True)),
        "outbound": bool(data.get("outbound", True)),
    }


def set_apple_messages_directions(
    *,
    inbound: bool | None = None,
    outbound: bool | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Persist the Apple Messages inbound/outbound flags. Only the flags passed
    (non-None) are changed; the other keeps its current value."""
    current = get_apple_messages_directions(config)
    if inbound is not None:
        current["inbound"] = bool(inbound)
    if outbound is not None:
        current["outbound"] = bool(outbound)
    source_dir = _apple_messages_source_dir(config)
    source_dir.mkdir(parents=True, exist_ok=True)
    _write_json(source_dir / "directions.json", {**current, "updated_at": _now()})
    return current


def _write_paused_apple_messages_source(source_dir: Path) -> JsonRecord:
    """Inbound reading is toggled OFF: write a NON-blocked status so the FDA
    banner never shows. Sending (outbound) is unaffected."""
    now = _now()
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "inbound_disabled": True,
            "last_error": None,
            "next_operator_step": (
                "Inbound Apple Messages import is turned off. Turn it on in Leads to "
                "read replies as leads (requires Full Disk Access)."
            ),
            "last_checked_at": now,
        },
    )
    return connector_view(source_dir.parent, "apple-messages") or {}


def _looks_like_fda_denied(error: str) -> bool:
    """True when a chat.db open error is a Full Disk Access / TCC denial of the
    CALLING process (the file is there, this process just isn't allowed to open
    it) rather than a genuine missing/corrupt database."""
    e = (error or "").lower()
    return (
        "unable to open database file" in e
        or "authorization denied" in e
        or "operation not permitted" in e
        or "permission denied" in e
    )


def _write_blocked_apple_messages_source(source_dir: Path, chat_db: Path, error: str) -> JsonRecord:
    now = _now()
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    surfaces = _ui_by_source("apple-messages")
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "apple-messages",
            "provider": "Apple Messages",
            "account_label": "Mac Messages",
            "connection_type": "macos_messages_chat_db",
            "auth_status": "needs_full_disk_access",
            "sync_mode": "manual_snapshot",
            "owner_agent": _owner_by_source("apple-messages"),
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
                "Open System Settings → Privacy & Security → Full Disk Access, "
                "turn ON Elevate (click + and add it if it's not listed), then quit and "
                "reopen Elevate."
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
    surfaces = _ui_by_source("apple-messages")
    now = _now()

    # Inbound reading toggled OFF: don't touch chat.db at all (so we never
    # trip the FDA wall) and write a non-blocked status so the banner stays
    # hidden. Outbound sending is independent and unaffected.
    if not get_apple_messages_directions(config).get("inbound", True):
        return _write_paused_apple_messages_source(source_dir)

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
        # A process WITHOUT Full Disk Access (e.g. the launchd gateway running a
        # non-FDA python3.11) gets "unable to open database file" even when the
        # app CAN read chat.db. Don't let such a process stomp the source to
        # blocked and flip the /leads banner back on. If the file exists and the
        # source was already proven readable (prior status not blocked), preserve
        # that status — only a process that can actually read may flip the flag.
        if chat_db.exists() and _looks_like_fda_denied(str(exc)):
            prior = _read_json(source_dir / "status.json") or {}
            if prior.get("blocked") is False:
                logging.getLogger(__name__).info(
                    "apple-messages: this process can't read chat.db (no FDA); "
                    "preserving prior non-blocked status instead of stomping blocked."
                )
                return connector_view(source_dir.parent, "apple-messages") or {}
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
                "owner_agent": _owner_by_source("apple-messages"),
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
            "owner_agent": _owner_by_source("apple-messages"),
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
    # Continuous DB writethrough — same pattern as Lofty/CRM sync (Codex
    # audit P0, 2026-05-05). Pushes the just-written JSONL into
    # operational Postgres so identity-first resolution sees the apple-messages
    # handles immediately, no manual ``elevate migrate-data`` needed.
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        _write_json(
            source_dir / "artifacts" / "last-db-writethrough-error.json",
            {"checked_at": now, "error": str(exc)},
        )
    view = connector_view(source_root, "apple-messages")
    if view is None:
        raise RuntimeError("Apple Messages import finished but could not be read")
    return view
