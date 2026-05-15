"""One-shot enrichment for apple-messages contacts.

Per ``docs/database-contract.md``: identities table is the universal
join key, and every apple contact needs the apple_handle / phone /
email / apple_addressbook_id / apple_chat_id rows populated so chat.db
and AddressBook are reachable from operational.db via SQL JOIN.

This module does ENRICHMENT ONLY — it never merges, never deletes,
never overwrites human-readable names with raw handles. Duplicate-
detection (an apple contact's phone matches a Lofty contact's phone)
is logged to ``identity_conflicts`` so the operator can review and
merge manually if appropriate.

Entry point: :func:`run` — invoked from the CLI as
``elevate apple-contacts resolve [--apply]``. Default is dry-run.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elevate_cli.apple_contacts import (
    AddressBookAccessError,
    AddressBookIndex,
    build_index,
    normalize_email,
    normalize_phone,
)
from elevate_cli.data import connect
from elevate_cli.data._util import new_id, now_iso

_log = logging.getLogger(__name__)


CHAT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


# ─── Stats ────────────────────────────────────────────────────────────


@dataclass
class BackfillStats:
    """Counters for the report. Mutated during the walk; rendered at
    end so the operator sees exactly what changed (or would change in
    dry-run)."""

    contacts_walked: int = 0
    contacts_with_handle_name: int = 0
    apple_handle_written: int = 0
    phone_identity_written: int = 0
    email_identity_written: int = 0
    apple_addressbook_matched: int = 0
    apple_addressbook_written: int = 0
    display_name_upgraded: int = 0
    primary_phone_populated: int = 0
    primary_email_populated: int = 0
    apple_chat_id_written: int = 0
    duplicate_with_existing_contact: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "errors"}
        d["errors"] = list(self.errors)
        return d


# ─── chat.db join helpers ─────────────────────────────────────────────


def _open_chat_db_readonly() -> sqlite3.Connection:
    if not CHAT_DB_PATH.exists():
        raise FileNotFoundError(
            f"chat.db not found at {CHAT_DB_PATH}. Grant Full Disk "
            "Access in System Settings → Privacy & Security."
        )
    uri = f"file:{CHAT_DB_PATH.as_posix()}?mode=ro&immutable=1"
    try:
        return sqlite3.connect(uri, uri=True, isolation_level=None)
    except sqlite3.OperationalError as exc:
        raise PermissionError(
            f"Cannot open chat.db: {exc}. Grant Full Disk Access."
        ) from exc


def _chat_ids_for_handle(chat_conn: sqlite3.Connection, handle_id: str) -> list[str]:
    """Return chat.db chat ROWIDs that include this handle.

    A single person can be in many threads (1:1 with you, group chats,
    legacy threads after they changed numbers). We write one
    ``apple_chat_id`` identity row per thread so the UI can show "this
    person across 3 conversations" without re-querying chat.db.
    """
    rows = chat_conn.execute(
        """
        SELECT DISTINCT chj.chat_id
        FROM chat_handle_join chj
        JOIN handle h ON h.ROWID = chj.handle_id
        WHERE h.id = ?
        """,
        (handle_id,),
    ).fetchall()
    return [str(r[0]) for r in rows]


# ─── Identity write helpers ───────────────────────────────────────────


def _identity_exists(
    conn: sqlite3.Connection, *, kind: str, value: str
) -> str | None:
    """Return the contact_id that already owns (kind, value), or None."""
    row = conn.execute(
        "SELECT contact_id FROM identities WHERE kind=? AND value=?",
        (kind, value),
    ).fetchone()
    return row["contact_id"] if row else None


def _add_identity(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    kind: str,
    value: str,
    source_id: str,
) -> bool:
    """Insert an identity row. Returns True if it was new, False if it
    already existed (any contact_id). Caller decides what to do on a
    pre-existing row.

    This is a thin wrapper over INSERT — the cross-contact dedup logic
    (i.e., "this phone is already on a different contact") happens in
    the caller, because the right action depends on context (enrich
    quietly vs. record a conflict)."""
    existing_contact = _identity_exists(conn, kind=kind, value=value)
    if existing_contact is not None:
        return False
    conn.execute(
        """
        INSERT INTO identities(
            id, contact_id, kind, value, source_id, verified, created_at
        ) VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (new_id(), contact_id, kind, value, source_id, now_iso()),
    )
    return True


def _record_phone_collision(
    conn: sqlite3.Connection,
    *,
    apple_contact_id: str,
    existing_contact_id: str,
    handle: str,
    actor: str,
) -> None:
    """Log a duplicate (apple contact's phone already belongs to a
    different existing contact, e.g. a Lofty lead) into
    identity_conflicts. We DO NOT merge — that's an operator decision.

    The table's open-row uniqueness index prevents duplicate conflicts
    for the same (kind, value, reason). ``INSERT OR IGNORE`` so re-runs
    don't fail."""
    import json
    conn.execute(
        """
        INSERT OR IGNORE INTO identity_conflicts(
            id, kind, value, candidate_contact_ids, reason, created_at
        ) VALUES (?, 'phone', ?, ?, 'multiple_matches', ?)
        """,
        (
            new_id(),
            handle,
            json.dumps([existing_contact_id, apple_contact_id]),
            now_iso(),
        ),
    )


# ─── Backfill walk ────────────────────────────────────────────────────


def _extract_handle_from_display_name(display_name: str | None) -> tuple[str | None, str | None]:
    """If display_name is a phone/email handle, return ``(kind, value)``
    where kind is 'phone' or 'email'. Otherwise (None, None).

    Apple-messages backfill landed phone numbers / emails directly into
    the display_name field (see source_connectors.py heuristics that
    fall through to ``Client conversation``). We detect those shapes and
    extract; anything else (real names, organizations) we leave alone."""
    if not display_name:
        return None, None
    s = display_name.strip()
    if "@" in s and " " not in s:
        normalized = normalize_email(s)
        if normalized:
            return "email", normalized
    if s.startswith("+") or (s.replace("-", "").replace(" ", "").replace("(", "").replace(")", "").isdigit() and len(s) >= 7):
        normalized = normalize_phone(s)
        if normalized:
            return "phone", normalized
    return None, None


def _safe_check_identity_conflicts_table(conn: sqlite3.Connection) -> bool:
    """identity_conflicts was added in an early migration; guard against
    older DBs missing it."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='identity_conflicts'"
    ).fetchone()
    return row is not None


def run(*, apply: bool = False, actor: str = "human:cli-backfill") -> BackfillStats:
    """Walk every apple-messages contact, enrich identities + AddressBook
    linkage, write chat thread ids.

    Default ``apply=False`` is a dry-run: walk + count + render report,
    but every DB write is rolled back. Pass ``apply=True`` to commit.
    """
    stats = BackfillStats()

    try:
        index: AddressBookIndex = build_index()
    except AddressBookAccessError as exc:
        stats.errors.append(str(exc))
        return stats

    try:
        chat_conn = _open_chat_db_readonly()
    except (FileNotFoundError, PermissionError) as exc:
        stats.errors.append(str(exc))
        return stats

    with connect() as conn:
        conflicts_table_ok = _safe_check_identity_conflicts_table(conn)
        if not conflicts_table_ok:
            stats.errors.append(
                "identity_conflicts table missing — phone collisions will be "
                "counted but not logged."
            )

        rows = conn.execute(
            """
            SELECT id, display_name, primary_phone, primary_email
            FROM contacts
            WHERE source_key LIKE 'apple-messages:%'
            """
        ).fetchall()

        for row in rows:
            contact_id = row["id"]
            display_name = row["display_name"]
            primary_phone = row["primary_phone"]
            primary_email = row["primary_email"]
            stats.contacts_walked += 1

            kind, value = _extract_handle_from_display_name(display_name)
            if kind is None:
                # Display name is already human-readable — nothing to extract.
                # We still try AddressBook matching by existing primary_phone
                # / primary_email so we can write apple_addressbook_id.
                kind, value = (
                    ("phone", normalize_phone(primary_phone)) if primary_phone
                    else (("email", normalize_email(primary_email)) if primary_email else (None, None))
                )
                if kind is None or value is None:
                    continue
            else:
                stats.contacts_with_handle_name += 1

            # 1. Write generic phone/email identity for cross-source
            #    matching (Lofty<->Apple uses these as the join key).
            existing_owner = _identity_exists(conn, kind=kind, value=value)
            if existing_owner is None:
                if _add_identity(
                    conn,
                    contact_id=contact_id,
                    kind=kind,
                    value=value,
                    source_id="apple-messages",
                ):
                    if kind == "phone":
                        stats.phone_identity_written += 1
                    else:
                        stats.email_identity_written += 1
            elif existing_owner != contact_id:
                # Different contact already owns this handle (e.g. Lofty
                # contact had the phone). Log as conflict, don't merge.
                stats.duplicate_with_existing_contact += 1
                if conflicts_table_ok:
                    _record_phone_collision(
                        conn,
                        apple_contact_id=contact_id,
                        existing_contact_id=existing_owner,
                        handle=value,
                        actor=actor,
                    )

            # 2. Write apple_handle (always, even if generic phone/email
            #    already exists — apple_handle is the chat.db-specific
            #    join key and lives in its own namespace).
            if _add_identity(
                conn,
                contact_id=contact_id,
                kind="apple_handle",
                value=value,
                source_id="apple-messages",
            ):
                stats.apple_handle_written += 1

            # 3. Populate primary_phone / primary_email if missing.
            update_cols: list[str] = []
            update_vals: list[Any] = []
            if kind == "phone" and not primary_phone:
                update_cols.append("primary_phone = ?")
                update_vals.append(value)
                stats.primary_phone_populated += 1
            elif kind == "email" and not primary_email:
                update_cols.append("primary_email = ?")
                update_vals.append(value)
                stats.primary_email_populated += 1

            # 4. AddressBook lookup.
            ab_record = index.lookup(value)
            if ab_record is not None:
                stats.apple_addressbook_matched += 1
                if _add_identity(
                    conn,
                    contact_id=contact_id,
                    kind="apple_addressbook_id",
                    value=ab_record.unique_id,
                    source_id="apple-messages",
                ):
                    stats.apple_addressbook_written += 1
                # Upgrade display_name ONLY if current name is the raw
                # handle. Never overwrite a name a human already curated.
                handle_kind, _ = _extract_handle_from_display_name(display_name)
                if handle_kind is not None:
                    update_cols.append("display_name = ?")
                    update_vals.append(ab_record.display_name)
                    stats.display_name_upgraded += 1
                # Also write every OTHER handle the AddressBook knows
                # for this person. If Sarah is in chat.db as
                # +17787163070 but Contacts also has her email
                # sarah@example.com, write that as an apple_handle too.
                for other in ab_record.handles:
                    if other == value:
                        continue
                    other_kind = "email" if "@" in other else "phone"
                    if _add_identity(
                        conn,
                        contact_id=contact_id,
                        kind=other_kind,
                        value=other,
                        source_id="apple-messages",
                    ):
                        if other_kind == "phone":
                            stats.phone_identity_written += 1
                        else:
                            stats.email_identity_written += 1
                    _add_identity(
                        conn,
                        contact_id=contact_id,
                        kind="apple_handle",
                        value=other,
                        source_id="apple-messages",
                    )

            # 5. Apply contact column updates.
            if update_cols:
                update_cols.append("updated_at = ?")
                update_vals.append(now_iso())
                update_vals.append(contact_id)
                conn.execute(
                    f"UPDATE contacts SET {', '.join(update_cols)} WHERE id = ?",
                    update_vals,
                )

            # 6. Write apple_chat_id per chat.db thread.
            for chat_id in _chat_ids_for_handle(chat_conn, value):
                if _add_identity(
                    conn,
                    contact_id=contact_id,
                    kind="apple_chat_id",
                    value=chat_id,
                    source_id="apple-messages",
                ):
                    stats.apple_chat_id_written += 1

        if not apply:
            conn.rollback()
        else:
            conn.commit()

    chat_conn.close()
    return stats


def render(stats: BackfillStats, *, applied: bool) -> str:
    """Format a one-screen report for the CLI."""
    header = "APPLIED" if applied else "DRY-RUN"
    lines = [
        f"[{header}] apple-contacts backfill",
        f"  contacts walked              : {stats.contacts_walked}",
        f"  with handle-shaped name      : {stats.contacts_with_handle_name}",
        f"  apple_handle rows written    : {stats.apple_handle_written}",
        f"  phone identity rows written  : {stats.phone_identity_written}",
        f"  email identity rows written  : {stats.email_identity_written}",
        f"  AddressBook matches found    : {stats.apple_addressbook_matched}",
        f"  apple_addressbook_id rows    : {stats.apple_addressbook_written}",
        f"  display_name upgraded        : {stats.display_name_upgraded}",
        f"  primary_phone populated      : {stats.primary_phone_populated}",
        f"  primary_email populated      : {stats.primary_email_populated}",
        f"  apple_chat_id rows written   : {stats.apple_chat_id_written}",
        f"  phone collisions w/ existing : {stats.duplicate_with_existing_contact}",
    ]
    if stats.errors:
        lines.append("  errors:")
        for err in stats.errors:
            lines.append(f"    - {err}")
    return "\n".join(lines)


__all__ = ["BackfillStats", "render", "run"]
