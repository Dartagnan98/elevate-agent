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


# Per-source handle kind for non-CRM sources. When a connector emits a
# ``handle`` field on its contacts.jsonl row, this map tells the migrator
# which kind-specific identity to write alongside the generic phone/email
# one (so reverse lookup from chat.db handle → contact_id is O(log n)).
#
# This is the ONE place that knows source-specific identity kinds. The
# walker logic is identical across sources — it just iterates whatever
# (kind, value) pairs ``_gather_identity_candidates`` produces. To add a
# new source: drop one line here. No new code paths.
_SOURCE_TO_HANDLE_KIND: dict[str, str] = {
    "apple-messages": "apple_handle",
    "imessage": "apple_handle",
    "instagram": "instagram_id",
    "composio-instagram": "instagram_id",
    "facebook": "facebook_id",
    "composio-facebook": "facebook_id",
    "whatsapp": "wa_id",
    "telegram": "telegram_id",
}


def _looks_like_email(value: str) -> bool:
    """Cheap shape check — no regex, no validation, just '@' presence."""
    return "@" in value


def _gather_identity_candidates(
    row: dict[str, Any],
    *,
    source_id: str,
    crm_identity_kind: str | None,
    native: str | None,
) -> list[tuple[str, str]]:
    """Extract every (kind, raw_value) pair from a contact row, shape-
    agnostic. Connectors can emit any of:

    * ``email`` / ``emails`` — string or list, comma/semicolon-delimited
    * ``phone`` / ``phones`` — same
    * ``handle`` — single auto-detected phone-or-email (apple-messages,
      Instagram, etc.)
    * ``identities`` — explicit ``[{"kind": "...", "value": "..."}, ...]``
      for connectors that want full control

    Plus the migrator adds:

    * The CRM-native id as ``(crm_identity_kind, native)`` when the source
      is a CRM (read from ``source.json``).
    * For non-CRM sources that emit a ``handle``, an extra
      ``(<source-specific kind>, normalized_value)`` pair — e.g. an
      apple-messages handle becomes BOTH ``('phone', '+1…')`` AND
      ``('apple_handle', '+1…')`` so the chat.db reverse lookup works.

    Returns raw values — canonicalization happens later in
    :func:`add_identity`. Duplicates are deduped by (kind, value).
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []

    def _push(kind: str, value: Any) -> None:
        v = str(value or "").strip()
        if not v:
            return
        key = (kind, v)
        if key in seen:
            return
        seen.add(key)
        out.append(key)

    # Generic email/phone lists
    for v in _normalize_split(row.get("emails") or row.get("email")):
        _push("email", v)
    for v in _normalize_split(row.get("phones") or row.get("phone")):
        _push("phone", v)

    # Source-native handle field (apple-messages, social, etc.)
    handle_kind = _SOURCE_TO_HANDLE_KIND.get(source_id)
    for raw_handle in _normalize_split(row.get("handle") or row.get("handles")):
        if _looks_like_email(raw_handle):
            _push("email", raw_handle)
        else:
            _push("phone", raw_handle)
        if handle_kind:
            _push(handle_kind, raw_handle)

    # CRM-native id (lofty_id / fub_id / …)
    if crm_identity_kind and native:
        _push(crm_identity_kind, str(native))

    # Explicit identities array — lets future connectors carry kinds the
    # migrator doesn't auto-derive (apple_chat_id, instagram_handle, …).
    for entry in row.get("identities") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").strip()
        value = entry.get("value")
        if kind and value:
            _push(kind, value)

    return out


_PHONE_NAME_RE = None  # lazy-built


def _looks_like_phone_name(value: str | None) -> bool:
    """A display_name that's really just a phone number — what Apple
    Messages and unknown-sender SMS feeds give us. We never let one of
    these clobber an existing human-readable name during merge."""
    if not value:
        return True
    s = value.strip()
    if not s:
        return True
    # Phone-shape: 80%+ digits, optional + - ( ) spaces. Cheap check.
    digits = sum(1 for c in s if c.isdigit())
    return digits >= 7 and digits / max(len(s), 1) >= 0.6


def _better_display_name(existing: str | None, candidate: str | None) -> str | None:
    """Return the name to actually persist. Preference order:

    1. Existing human-readable name (Lofty 'Sarah Martinez') NEVER gets
       overwritten by a phone-shaped one (apple-messages '+1…').
    2. A populated existing name beats an empty candidate.
    3. Candidate wins when existing is empty or phone-shaped and
       candidate isn't.

    Returns ``None`` when the existing value should be kept (caller
    passes ``None`` to upsert_contact, skipping the update)."""
    cand = (candidate or "").strip() or None
    exist = (existing or "").strip() or None
    if cand is None:
        return None  # don't overwrite with nothing
    if exist is None:
        return cand  # nothing to lose
    if _looks_like_phone_name(exist) and not _looks_like_phone_name(cand):
        return cand  # upgrade phone-shape → human name
    if not _looks_like_phone_name(exist) and _looks_like_phone_name(cand):
        return None  # don't downgrade human name → phone-shape
    return None  # both human or both phone; first-write wins


def _resolve_via_identities(
    conn: sqlite3.Connection,
    candidates: list[tuple[str, str]],
) -> tuple[str | None, list[str]]:
    """Walk candidate (kind, value) pairs and return the first contact_id
    any of them resolves to, plus the full list of distinct contact_ids
    seen across all candidates (for conflict logging).

    Identity-first contact resolution — the canonical pattern from
    ``docs/database-contract.md`` step 2: every connector's sync must
    join to an existing contact via identity match BEFORE creating a new
    contact row. Without this, the same human ends up split across one
    row per source.
    """
    from elevate_cli.data.identities import _canonicalize  # local import — avoids cycle

    matches: list[str] = []
    for kind, raw in candidates:
        canon = _canonicalize(kind, raw)
        if canon is None:
            continue
        row = conn.execute(
            "SELECT contact_id FROM identities WHERE kind=? AND value=?",
            (kind, canon),
        ).fetchone()
        if row and row["contact_id"] not in matches:
            matches.append(row["contact_id"])
    return (matches[0] if matches else None), matches


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
    #
    # Canonical contract (docs/database-contract.md, step 2):
    #
    #   1. Gather every identity the row carries (handle/phone/email/CRM
    #      native id/explicit identities[]) — source-shape agnostic.
    #   2. Resolve those identities against ``identities`` table. If any
    #      match an existing contact, reuse that contact_id.
    #   3. Upsert contact via the resolved id (or via source_key for a
    #      brand-new contact).
    #   4. Write every identity. (kind, value) UNIQUE handles dedup.
    #
    # No per-source branching. New connectors don't add code here —
    # they declare their handle kind in ``_SOURCE_TO_HANDLE_KIND`` or
    # emit ``identities[]`` rows directly.
    for row in _read_jsonl(contacts_path, limit=limit):
        native = row.get("contact_id") or row.get("source_record_id")
        if not native:
            stats.contacts_skipped += 1
            continue
        source_key = _build_source_key(source_id, native)
        try:
            # Step 1+2: gather candidates, resolve via identities.
            candidates = _gather_identity_candidates(
                row,
                source_id=source_id,
                crm_identity_kind=crm_identity_kind,
                native=str(native),
            )
            resolved_id, matched_ids = _resolve_via_identities(conn, candidates)

            existing_by_sk = conn.execute(
                "SELECT id FROM contacts WHERE source_key=?", (source_key,)
            ).fetchone()
            existing_id = (
                resolved_id
                or (existing_by_sk["id"] if existing_by_sk else None)
            )

            if dry_run:
                if existing_id:
                    stats.contacts_skipped += 1
                    contact_by_native[native] = existing_id
                else:
                    stats.contacts += 1
                    contact_by_native[native] = f"<dryrun>:{source_key}"
                continue

            # Step 3: upsert. Reuse resolved_id when an identity already
            # ties this person to an existing contact (e.g. Lofty pulled
            # them first, now apple-messages finds the same phone). Only
            # set source_key when creating a brand-new contact, so the
            # first-source's source_key remains canonical.
            #
            # Display-name preservation rule (database-contract.md, write
            # contract step 3): a phone-shaped name from a fresh source
            # never overwrites an existing human name. _better_display_name
            # returns None when we should skip the update — upsert_contact
            # treats None as "don't touch".
            candidate_name = row.get("display_name") or row.get("name")
            if resolved_id:
                existing_row = conn.execute(
                    "SELECT display_name FROM contacts WHERE id=?",
                    (resolved_id,),
                ).fetchone()
                existing_name = existing_row["display_name"] if existing_row else None
                name_to_write = _better_display_name(existing_name, candidate_name)
            else:
                name_to_write = candidate_name
            contact = upsert_contact(
                conn,
                contact_id=resolved_id,
                source_key=None if resolved_id else source_key,
                display_name=name_to_write,
            )
            contact_by_native[native] = contact["id"]
            if existing_id:
                stats.contacts_skipped += 1
            else:
                stats.contacts += 1

            # Step 4: write every identity. add_identity is idempotent on
            # (kind, value) and records identity_conflicts automatically
            # when the same (kind, value) maps to a different contact.
            for kind, raw in candidates:
                try:
                    out = add_identity(
                        conn,
                        contact_id=contact["id"],
                        kind=kind,
                        value=raw,
                        source_id=source_id,
                        # CRM-native ids are the workspace's source of
                        # truth; everything else stays unverified until a
                        # human confirms.
                        verified=(kind == crm_identity_kind),
                    )
                    if out is not None:
                        stats.identities += 1
                    else:
                        stats.identities_skipped += 1
                except Exception as exc:
                    stats.identities_skipped += 1
                    _LOG.debug("identity skip (%s %s): %s", kind, raw, exc)

            # If resolution saw multiple existing contacts via different
            # identities, log the straddle so an operator can merge.
            # ``add_identity`` only catches the (kind, value) collision —
            # this catches the (different kinds → different contacts)
            # case that's invisible to the per-row insert.
            if len(matched_ids) > 1:
                from elevate_cli.data.identities import record_identity_conflict
                record_identity_conflict(
                    conn,
                    kind="contact",
                    value=contact["id"],
                    candidate_contact_ids=matched_ids,
                    reason="cross_kind_mismatch",
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
    # Per-row dispatch: notes land as kind='note' so the UI's per-contact
    # notes panel can read them; other lead-events (activities, tasks,
    # sync placeholders, lifecycle changes) collapse to 'lifecycle_change'
    # for the audit-log surface. source_id is the actual connector id so
    # downstream readers can filter `WHERE source_id='crm'` etc.
    _NOTE_TYPES = {"crm_note", "note"}
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
        record_kind = "note" if legacy_type in _NOTE_TYPES else "lifecycle_change"
        already = conn.execute(
            """
            SELECT id FROM events
            WHERE contact_id=? AND kind=? AND ts=? AND source_id=?
              AND payload_json LIKE ?
            LIMIT 1
            """,
            (
                contact_id,
                record_kind,
                ts,
                source_id,
                f'%"legacyType":{json.dumps(legacy_type)}%',
            ),
        ).fetchone()
        if already:
            continue
        try:
            record_lifecycle(
                conn,
                contact_id=contact_id,
                kind=record_kind,
                actor=row.get("actor") or "legacy_backfill",
                ts=ts,
                payload={
                    "legacyType": legacy_type,
                    "title": row.get("title"),
                    "summary": row.get("summary"),
                    "body": row.get("body") or row.get("note") or row.get("text"),
                },
                source_id=source_id,
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
