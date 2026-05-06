"""Sprint 1E backfill — replay legacy JSONL + outreach.db into the
central operational store.

Public surface:

* :func:`run_backfill` — top-level orchestrator. Always takes a backup
  before writing (unless ``dry_run=True``); returns a :class:`BackfillStats`
  for the CLI to print.
* :func:`backup_operational_db` — snapshot the current operational DB
  to ``data.backups_root() / migrate-data-{label}-{ts}.db`` using
  sqlite's online backup so a WAL-mode source copies cleanly.
* :func:`restore_from_backup` — copy a backup back into place. The CLI
  exposes this as ``elevate migrate-data --rollback <path>``.
* :func:`walk_jsonl_source` / :func:`walk_outreach_db` — per-source
  walkers, broken out so tests can exercise them in isolation.

Idempotency story: every helper underneath this layer is keyed on
``source_key`` for contacts, ``(kind, value)`` for identities,
``(source_id, thread_key)`` for conversations, and ``event_hash`` for
events. Re-running ``migrate-data`` on the same source files therefore
produces zero new rows. That's what lets us run the backfill against
production a few times before flipping the cutover bit.

Out of scope for 1E: handling every legacy JSONL quirk (the
``source_connectors.py`` code is the source of truth for those — its
write side is what gets refactored in Sprint 2). This module only
covers the steady-state shapes we ship today: ``contacts.jsonl``,
``conversations.jsonl``, ``messages.jsonl``, ``lead-events.jsonl``,
and the legacy ``outreach.db`` ``templates`` table. Anything more
exotic (PCS scrape JSON, Composio nested payloads) gets a TODO and
falls through unchanged — the connector still writes those, the data
module just doesn't see them yet.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from elevate_cli.data import (
    add_identity,
    approve_template,
    bump_conversation_counters,
    connect,
    get_or_create_conversation,
    propose_template,
    record_inbound,
    record_lifecycle,
    record_outbound,
    upsert_contact,
)
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data.paths import backups_root, operational_db_path


_LOG = logging.getLogger(__name__)


# Map legacy ``channel`` strings (free-form across years of connectors)
# onto the V1 frozen enum: email/sms/imessage/messenger/instagram/
# whatsapp/telegram/voice/crm. Anything we can't map confidently falls
# back to ``crm`` — the catch-all bucket — rather than crashing the
# CHECK constraint mid-backfill.
_CHANNEL_MAP: dict[str, str] = {
    "email": "email",
    "gmail": "email",
    "composio-gmail": "email",
    "sms": "sms",
    "imessage": "imessage",
    "apple-messages": "imessage",
    "messenger": "messenger",
    "facebook": "messenger",
    "composio-facebook": "messenger",
    "instagram": "instagram",
    "composio-instagram": "instagram",
    "whatsapp": "whatsapp",
    "wa": "whatsapp",
    "telegram": "telegram",
    "voice": "voice",
    "crm": "crm",
    "lofty crm": "crm",
    "lofty": "crm",
    "fub": "crm",
    "sierra": "crm",
    "brivity": "crm",
    "boldtrail": "crm",
}


def _coerce_channel(value: Any) -> str:
    """Normalize a raw legacy channel string onto the frozen enum.
    Falls back to ``crm`` (the connector-side bucket) when we can't
    place it confidently — never raises."""
    s = (str(value) if value is not None else "").strip().lower()
    if not s:
        return "crm"
    return _CHANNEL_MAP.get(s, "crm")


@dataclass
class BackfillStats:
    """Counts of rows processed by a backfill run. Each field is a
    pair ``(written, skipped)`` so the CLI can summarize honestly even
    when most of the work is no-ops on a re-run."""
    contacts: int = 0
    contacts_skipped: int = 0
    identities: int = 0
    identities_skipped: int = 0
    conversations: int = 0
    conversations_skipped: int = 0
    messages: int = 0
    messages_skipped: int = 0
    lifecycle_events: int = 0
    templates: int = 0
    templates_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    backup_path: str | None = None
    sources_walked: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "contacts": {"written": self.contacts, "skipped": self.contacts_skipped},
            "identities": {"written": self.identities, "skipped": self.identities_skipped},
            "conversations": {"written": self.conversations, "skipped": self.conversations_skipped},
            "messages": {"written": self.messages, "skipped": self.messages_skipped},
            "lifecycle_events": self.lifecycle_events,
            "templates": {"written": self.templates, "skipped": self.templates_skipped},
            "errors": list(self.errors),
            "backupPath": self.backup_path,
            "sourcesWalked": list(self.sources_walked),
            "dryRun": self.dry_run,
        }


# ─── Backup / restore ──────────────────────────────────────────────────


def backup_operational_db(*, label: str = "migrate-data") -> Path:
    """Snapshot the current operational DB to ``backups_root()`` with
    a timestamped filename. Uses sqlite's online backup so a WAL-mode
    source copies cleanly even if a stray connection is still open.

    Returns the destination path. Returns a placeholder path *with no
    file on disk* when the operational DB doesn't exist yet — fresh
    install case; the caller treats it as a no-op rather than a
    failure."""
    src = operational_db_path()
    dest_dir = backups_root()
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"{label}-{ts}.db"

    if not src.exists():
        _LOG.info("backup: source %s does not exist; nothing to back up", src)
        return dest

    src_conn = sqlite3.connect(str(src))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            with dest_conn:
                src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()
    _LOG.info("backup: wrote %s", dest)
    return dest


def restore_from_backup(backup_path: Path) -> Path:
    """Copy ``backup_path`` over the operational DB. Resets the
    process-wide schema-cache so the next ``connect()`` re-runs the
    migration ledger against the restored file."""
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"backup not found: {backup_path}")
    dest = operational_db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, dest)
    _reset_schema_cache()
    _LOG.info("restore: copied %s over %s", backup_path, dest)
    return dest


# ─── JSONL walkers ─────────────────────────────────────────────────────


def _read_jsonl(path: Path, *, limit: int | None = None) -> Iterable[dict[str, Any]]:
    """Yield decoded rows from a newline-delimited JSON file. Skips
    blank lines and rows that fail to decode rather than aborting —
    legacy stores have a few corrupted lines and we don't want those
    to nuke a 10K-row backfill."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        count = 0
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                _LOG.warning("skipping malformed JSONL row in %s: %s", path, exc)
                continue
            count += 1
            if limit is not None and count >= limit:
                return


def _normalize_split(value: Any) -> list[str]:
    """Identity-list fields in JSONL are sometimes a list, sometimes
    a comma/semicolon-delimited string, sometimes None. Coerce to a
    list of stripped strings, skipping empties."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip()
    if not s:
        return []
    parts: list[str] = []
    for chunk in s.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _classify_message_kind(row: dict[str, Any]) -> str:
    """Decide whether a messages.jsonl row is inbound or outbound.
    Defaults to inbound when direction is missing — safer for lead
    tracking than the alternative."""
    direction = (row.get("direction") or row.get("kind") or "").strip().lower()
    if direction in ("outbound", "out", "sent"):
        return "outbound"
    return "inbound"


def _build_source_key(source_id: str, native: str) -> str:
    """Source-natural key shape: ``<source_id>:<native_id>``. Matches
    the contract documented in ``docs/source-keys.md``."""
    return f"{source_id}:{native}"


# Map CRM provider strings (read from sources/<id>/source.json) onto the
# matching identity kind in the schema. Used so the migrator can write
# the native CRM id (lofty lead id, FUB person id, …) as an identity —
# without it, the same person stays split across Lofty/iMessage/Gmail.
_CRM_PROVIDER_TO_IDENTITY_KIND: dict[str, str] = {
    "lofty": "lofty_id",
    "lofty crm": "lofty_id",
    "chime": "lofty_id",
    "fub": "fub_id",
    "follow up boss": "fub_id",
    "followup boss": "fub_id",
    "sierra": "sierra_id",
    "sierra interactive": "sierra_id",
    "boldtrail": "boldtrail_id",
    "kvcore": "boldtrail_id",
    "brivity": "brivity_id",
}


def _crm_identity_kind_for_source(source_dir: Path) -> str | None:
    """Inspect ``source.json`` to figure out which identity kind to use
    for the CRM-native contact id. Returns ``None`` if the source isn't
    a CRM or the provider isn't mapped."""
    candidates: list[Path] = []
    if source_dir.name == "crm":
        candidates.append(source_dir / "source.json")
    # Some source dirs sit under a label-based folder (lofty/, fub/, …);
    # check both shapes since legacy layouts varied.
    candidates.append(source_dir / "source.json")
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            continue
        provider = str(
            payload.get("provider")
            or payload.get("crm_provider")
            or payload.get("account_label")
            or ""
        ).strip().lower()
        if provider in _CRM_PROVIDER_TO_IDENTITY_KIND:
            return _CRM_PROVIDER_TO_IDENTITY_KIND[provider]
        # Fall through to the source-id-based heuristic below.
    if source_dir.name in _CRM_PROVIDER_TO_IDENTITY_KIND:
        return _CRM_PROVIDER_TO_IDENTITY_KIND[source_dir.name]
    return None


def walk_jsonl_source(
    source_dir: Path,
    *,
    conn: sqlite3.Connection,
    stats: BackfillStats,
    limit: int | None = None,
    dry_run: bool = False,
) -> None:
    """Replay one ``sources/<source_id>/`` directory through the data
    module. Caller controls the connection so multiple sources can
    share a transaction or be rolled back together.

    Rows that already exist (idempotent re-run) bump the ``*_skipped``
    counters via the upsert/event_hash UNIQUE behavior — we don't
    second-guess what the data module decides."""
    source_id = source_dir.name
    stats.sources_walked.append(source_id)

    contacts_path = source_dir / "contacts.jsonl"
    conversations_path = source_dir / "conversations.jsonl"
    messages_path = source_dir / "messages.jsonl"
    events_path = source_dir / "lead-events.jsonl"

    # Native-id → contact_id map (so subsequent JSONL files can
    # resolve contacts by their legacy native id).
    contact_by_native: dict[str, str] = {}
    # Native thread id → conversation_id, ditto for messages.
    conv_by_thread: dict[str, str] = {}

    # CRM-native id identity kind (lofty_id / fub_id / …). None for
    # non-CRM sources (gmail, imessage, social) — they get email/phone
    # identities only.
    crm_identity_kind = _crm_identity_kind_for_source(source_dir)

    # ─── Contacts ─────────────────────────────────────────────────
    for row in _read_jsonl(contacts_path, limit=limit):
        native = row.get("contact_id") or row.get("source_record_id")
        if not native:
            stats.contacts_skipped += 1
            continue
        source_key = _build_source_key(source_id, native)
        try:
            existing = conn.execute(
                "SELECT id FROM contacts WHERE source_key=?", (source_key,)
            ).fetchone()

            if dry_run:
                if existing:
                    stats.contacts_skipped += 1
                    contact_by_native[native] = existing["id"]
                else:
                    stats.contacts += 1
                    # Synthetic placeholder so subsequent walkers see
                    # this contact as resolved during the dry-run.
                    contact_by_native[native] = f"<dryrun>:{source_key}"
                continue

            contact = upsert_contact(
                conn,
                source_key=source_key,
                display_name=row.get("display_name") or row.get("name"),
            )
            contact_by_native[native] = contact["id"]
            if existing:
                stats.contacts_skipped += 1
            else:
                stats.contacts += 1

            # Identities — emails + phones (string OR list)
            for email in _normalize_split(row.get("emails") or row.get("email")):
                try:
                    out = add_identity(
                        conn,
                        contact_id=contact["id"],
                        kind="email",
                        value=email,
                        source_id=source_id,
                        verified=False,
                    )
                    if out is not None:
                        stats.identities += 1
                    else:
                        stats.identities_skipped += 1
                except Exception as exc:
                    stats.identities_skipped += 1
                    _LOG.debug("identity skip (email %s): %s", email, exc)
            for phone in _normalize_split(row.get("phones") or row.get("phone")):
                try:
                    out = add_identity(
                        conn,
                        contact_id=contact["id"],
                        kind="phone",
                        value=phone,
                        source_id=source_id,
                        verified=False,
                    )
                    if out is not None:
                        stats.identities += 1
                    else:
                        stats.identities_skipped += 1
                except Exception as exc:
                    stats.identities_skipped += 1
                    _LOG.debug("identity skip (phone %s): %s", phone, exc)

            # CRM native id (lofty_id / fub_id / …). The schema reserves
            # these kinds but the migrator was never writing them, so the
            # same human stayed split across Lofty + iMessage + Gmail.
            # Codex audit P1 (2026-05-05).
            if crm_identity_kind and native:
                try:
                    out = add_identity(
                        conn,
                        contact_id=contact["id"],
                        kind=crm_identity_kind,
                        value=str(native),
                        source_id=source_id,
                        verified=True,  # native CRM id is the workspace's source of truth
                    )
                    if out is not None:
                        stats.identities += 1
                    else:
                        stats.identities_skipped += 1
                except Exception as exc:
                    stats.identities_skipped += 1
                    _LOG.debug(
                        "identity skip (%s %s): %s",
                        crm_identity_kind,
                        native,
                        exc,
                    )
        except Exception as exc:
            stats.errors.append(f"{source_id}/contacts:{native}: {exc}")
            _LOG.exception("contact replay failed: %s", native)

    # ─── Conversations ────────────────────────────────────────────
    for row in _read_jsonl(conversations_path, limit=limit):
        thread_key = row.get("conversation_id") or row.get("source_record_id")
        contact_native = row.get("contact_id")
        if not thread_key or not contact_native:
            stats.conversations_skipped += 1
            continue
        contact_id = contact_by_native.get(contact_native)
        if not contact_id:
            stats.conversations_skipped += 1
            continue
        channel = _coerce_channel(row.get("channel") or source_id)
        try:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE source_id=? AND thread_key=?",
                (source_id, thread_key),
            ).fetchone()

            if dry_run:
                if existing:
                    stats.conversations_skipped += 1
                    conv_by_thread[thread_key] = existing["id"]
                else:
                    stats.conversations += 1
                    conv_by_thread[thread_key] = f"<dryrun>:{thread_key}"
                continue

            if existing:
                conv_by_thread[thread_key] = existing["id"]
                stats.conversations_skipped += 1
                continue

            conv = get_or_create_conversation(
                conn,
                contact_id=contact_id,
                source_id=source_id,
                channel=channel,
                thread_key=thread_key,
            )
            conv_by_thread[thread_key] = conv["id"]
            stats.conversations += 1
        except Exception as exc:
            stats.errors.append(f"{source_id}/conversations:{thread_key}: {exc}")

    # ─── Messages ─────────────────────────────────────────────────
    for row in _read_jsonl(messages_path, limit=limit):
        thread_key = row.get("conversation_id") or row.get("source_record_id")
        contact_native = row.get("contact_id")
        ts = row.get("timestamp") or row.get("ts")
        body = row.get("text") or row.get("body") or ""
        if not thread_key or not contact_native or not ts:
            stats.messages_skipped += 1
            continue
        contact_id = contact_by_native.get(contact_native)
        if not contact_id:
            stats.messages_skipped += 1
            continue

        # If the message references a thread we didn't see in
        # conversations.jsonl, lazily create one — legacy stores have
        # plenty of orphan messages without a conversation row.
        conv_id = conv_by_thread.get(thread_key)
        channel = _coerce_channel(row.get("channel") or source_id)
        kind = _classify_message_kind(row)

        try:
            if dry_run:
                stats.messages += 1
                continue

            if conv_id is None:
                # Lazy-create only on first appearance; check the DB
                # before calling the helper so we can tell new vs
                # existing rows for the stats counters.
                already = conn.execute(
                    "SELECT id FROM conversations "
                    "WHERE source_id=? AND thread_key=?",
                    (source_id, thread_key),
                ).fetchone()
                conv = get_or_create_conversation(
                    conn,
                    contact_id=contact_id,
                    source_id=source_id,
                    channel=channel,
                    thread_key=thread_key,
                )
                conv_id = conv["id"]
                conv_by_thread[thread_key] = conv_id
                if not already:
                    stats.conversations += 1

            recorder = record_outbound if kind == "outbound" else record_inbound
            try:
                recorder(
                    conn,
                    contact_id=contact_id,
                    conversation_id=conv_id,
                    channel=channel,
                    body=body,
                    source_id=source_id,
                    thread_key=thread_key,
                    ts=ts,
                    actor=row.get("actor") or "legacy_backfill",
                )
                stats.messages += 1
                # Bump the conversation counter the way the live path
                # would. The events_unique_event_hash UNIQUE keeps
                # replay safe; this counter is a best-effort estimate
                # that recomputes on Sprint 2 cutover.
                try:
                    bump_conversation_counters(
                        conn, conv_id, direction=kind, ts=ts,
                    )
                except Exception:
                    pass
            except sqlite3.IntegrityError:
                stats.messages_skipped += 1
        except Exception as exc:
            stats.errors.append(f"{source_id}/messages:{thread_key}@{ts}: {exc}")

    # ─── Lifecycle events ─────────────────────────────────────────
    # Lifecycle events lack a thread_key, so the data module's
    # event_hash fallback uses the event's own UUID — that's the
    # right call for live lifecycle changes (each one is unique by
    # construction) but breaks replay idempotency. Pre-check by
    # (contact_id, kind, ts, payload_signature) so a second migrate
    # run is a no-op.
    for row in _read_jsonl(events_path, limit=limit):
        contact_native = row.get("contact_id")
        ts = row.get("timestamp") or row.get("ts")
        if not contact_native or not ts:
            continue
        contact_id = contact_by_native.get(contact_native)
        if not contact_id:
            continue
        if dry_run:
            stats.lifecycle_events += 1
            continue
        legacy_type = row.get("type") or ""
        already = conn.execute(
            """
            SELECT id FROM events
            WHERE contact_id=? AND kind='lifecycle_change' AND ts=?
              AND payload_json LIKE ?
            LIMIT 1
            """,
            (contact_id, ts, f'%"legacyType":{json.dumps(legacy_type)}%'),
        ).fetchone()
        if already:
            continue
        try:
            record_lifecycle(
                conn,
                contact_id=contact_id,
                kind="lifecycle_change",
                actor=row.get("actor") or "legacy_backfill",
                ts=ts,
                payload={
                    "legacyType": legacy_type,
                    "title": row.get("title"),
                    "summary": row.get("summary"),
                },
            )
            stats.lifecycle_events += 1
        except sqlite3.IntegrityError:
            pass  # event_hash already present
        except Exception as exc:
            stats.errors.append(
                f"{source_id}/lead-events:{contact_native}@{ts}: {exc}"
            )


# ─── Outreach.db (templates) walker ────────────────────────────────────


def walk_outreach_db(
    outreach_db_path: Path,
    *,
    conn: sqlite3.Connection,
    stats: BackfillStats,
    actor: str = "human:legacy_backfill",
    dry_run: bool = False,
) -> None:
    """Replay the legacy ``templates`` table into the central
    templates table. Each legacy ``status='active'`` row maps to a
    proposed-then-approved live template; anything else stays
    proposed.

    Counters (uses/replies/wins) are NOT replayed — those are
    Sprint 4's territory. The backfill creates fresh, zero-counter
    rows; the legacy outreach.db keeps running until Sprint 2 cuts
    the live writes over."""
    if not outreach_db_path.exists():
        return

    src = sqlite3.connect(str(outreach_db_path))
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute(
            "SELECT id, lane, name, body, channel, status FROM templates"
        ).fetchall()
    except sqlite3.OperationalError:
        # Schema older than the columns we expect — treat as empty.
        rows = []
    finally:
        src.close()

    legacy_lane_map = {
        "new-outreach": "new-outreach",
        "new_outreach": "new-outreach",
        "hot-leads": "hot-leads-watcher",
        "hot-leads-watcher": "hot-leads-watcher",
        "hot_leads_watcher": "hot-leads-watcher",
        "follow-ups": "follow-ups",
        "follow_ups": "follow-ups",
    }

    for row in rows:
        lane = legacy_lane_map.get(
            (row["lane"] or "").strip().lower(), "follow-ups"
        )
        body = row["body"] or ""
        name = row["name"] or row["id"]
        legacy_status = (row["status"] or "active").strip().lower()
        try:
            existing = conn.execute(
                "SELECT id, status FROM templates WHERE lane=? AND name=?",
                (lane, name),
            ).fetchone()

            if dry_run:
                if existing:
                    stats.templates_skipped += 1
                else:
                    stats.templates += 1
                continue

            if existing:
                stats.templates_skipped += 1
                continue

            tpl = propose_template(
                conn,
                lane=lane,
                name=name,
                body=body,
                channel=row["channel"] or "any",
                origin="human",
                actor=actor,
                rationale="backfilled from outreach.db",
            )
            if legacy_status in ("active", "live"):
                approve_template(
                    conn,
                    template_id=tpl["id"],
                    actor=actor,
                )
            stats.templates += 1
        except Exception as exc:
            stats.errors.append(f"templates:{name}: {exc}")
            _LOG.exception("template replay failed: %s", name)


# ─── Top-level orchestrator ────────────────────────────────────────────


def run_backfill(
    *,
    sources_root: Path | None = None,
    outreach_db: Path | None = None,
    only_sources: list[str] | None = None,
    dry_run: bool = False,
    skip_backup: bool = False,
    limit: int | None = None,
) -> BackfillStats:
    """Walk every ``sources/<source_id>/`` subdirectory under
    ``sources_root`` plus the legacy ``outreach_db`` and replay rows
    through the data module. Returns the populated stats.

    ``--dry-run`` skips writes; the per-table counts still reflect
    what would have been written (existing rows roll into
    ``*_skipped`` so the operator can see "nothing to do" honestly).

    Raises ``RuntimeError`` if backup fails on a real run — we refuse
    to migrate without a restore point."""
    stats = BackfillStats(dry_run=dry_run)

    if not dry_run and not skip_backup:
        try:
            backup = backup_operational_db()
            stats.backup_path = str(backup) if backup.exists() else None
        except Exception as exc:
            raise RuntimeError(
                f"backup failed; refusing to migrate without one: {exc}"
            ) from exc

    with connect() as conn:
        if sources_root is not None and sources_root.exists():
            for child in sorted(sources_root.iterdir()):
                if not child.is_dir():
                    continue
                if only_sources and child.name not in only_sources:
                    continue
                walk_jsonl_source(
                    child,
                    conn=conn,
                    stats=stats,
                    limit=limit,
                    dry_run=dry_run,
                )

        if outreach_db is not None and (only_sources is None or "outreach" in only_sources):
            walk_outreach_db(
                outreach_db,
                conn=conn,
                stats=stats,
                dry_run=dry_run,
            )

    return stats
