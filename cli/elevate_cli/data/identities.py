"""Identity resolution + conflict quarantine.

Public surface:

* :func:`add_identity`
* :func:`resolve_identity`
* :func:`merge_contacts`             — actor must be ``human`` or ``human:<who>``
* :func:`record_identity_conflict`
* :func:`resolve_identity_conflict`
* :func:`list_open_conflicts`
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from elevate_cli.data import contacts as _contacts
from elevate_cli.data import events as _events
from elevate_cli.data._util import (
    new_id,
    normalize_email,
    normalize_handle,
    normalize_phone,
    now_iso,
)


# ─── Normalization dispatch ────────────────────────────────────────────


def _canonicalize(kind: str, value: str) -> str | None:
    if kind == "email":
        return normalize_email(value)
    if kind == "phone":
        return normalize_phone(value)
    if kind in {"instagram_handle"}:
        return normalize_handle(value)
    if kind in {
        "instagram_id", "facebook_id", "telegram_id",
        "lofty_id", "fub_id", "sierra_id", "brivity_id", "boldtrail_id",
        "xposure_pcs_id",
        "apple_handle", "apple_addressbook_id", "apple_chat_id",
        "wa_id",
    }:
        v = (value or "").strip()
        return v or None
    return None


def _row_to_identity(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "contactId": row["contact_id"],
        "kind": row["kind"],
        "value": row["value"],
        "sourceId": row["source_id"],
        "verified": bool(row["verified"]),
        "createdAt": row["created_at"],
    }


def _row_to_conflict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "value": row["value"],
        "candidateContactIds": json.loads(row["candidate_contact_ids"]),
        "reason": row["reason"],
        "createdAt": row["created_at"],
        "resolvedAt": row["resolved_at"],
        "resolvedBy": row["resolved_by"],
        "resolution": row["resolution"],
    }


# ─── Identity inserts ──────────────────────────────────────────────────


def add_identity(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    kind: str,
    value: str,
    source_id: str,
    verified: bool = False,
) -> dict[str, Any] | None:
    """Insert one (kind, value) row tied to ``contact_id``.

    * Returns the inserted/updated row.
    * If the canonical value is empty/un-parseable → no-op, returns None.
    * If (kind, value) already maps to ``contact_id``, this is a no-op
      idempotent call — verified flag is upgraded if already true elsewhere.
    * If (kind, value) maps to a DIFFERENT contact, this writes an
      identity_conflicts row instead of merging silently. The CLI/UI
      surfaces it on ``/admin/conflicts``.
    """
    canon = _canonicalize(kind, value)
    if canon is None:
        return None

    existing = conn.execute(
        "SELECT * FROM identities WHERE kind = ? AND value = ?", (kind, canon)
    ).fetchone()

    if existing is None:
        iid = new_id()
        conn.execute(
            """
            INSERT INTO identities(
                id, contact_id, kind, value, source_id, verified, created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (iid, contact_id, kind, canon, source_id, 1 if verified else 0, now_iso()),
        )
        # Denormalize phone/email onto contacts.primary_* so single-table
        # reads (and the verification spot-check) work without joining
        # identities. Only fill a blank — never overwrite a value the
        # operator may have curated.
        if kind == "phone":
            conn.execute(
                "UPDATE contacts SET primary_phone=? "
                "WHERE id=? AND (primary_phone IS NULL OR primary_phone='')",
                (canon, contact_id),
            )
        elif kind == "email":
            conn.execute(
                "UPDATE contacts SET primary_email=? "
                "WHERE id=? AND (primary_email IS NULL OR primary_email='')",
                (canon, contact_id),
            )
        return _row_to_identity(
            conn.execute(
                "SELECT * FROM identities WHERE id = ?", (iid,)
            ).fetchone()
        )

    if existing["contact_id"] == contact_id:
        # Idempotent: same identity already attached. Upgrade verified flag.
        if verified and not existing["verified"]:
            conn.execute(
                "UPDATE identities SET verified = 1 WHERE id = ?",
                (existing["id"],),
            )
        return _row_to_identity(
            conn.execute(
                "SELECT * FROM identities WHERE id = ?", (existing["id"],)
            ).fetchone()
        )

    # Conflict: identity already maps to a different contact.
    record_identity_conflict(
        conn,
        kind=kind,
        value=canon,
        candidate_contact_ids=[existing["contact_id"], contact_id],
        reason="multiple_matches",
    )
    return _row_to_identity(existing)


def resolve_identity(
    conn: sqlite3.Connection, kind: str, value: str
) -> dict[str, Any] | None:
    """Return the contact attached to ``(kind, value)``, or None.

    Caller is responsible for canonicalizing the value or letting the
    helper do it. Empty / un-parseable values return None.
    """
    canon = _canonicalize(kind, value)
    if canon is None:
        return None
    row = conn.execute(
        """
        SELECT c.*
        FROM identities i
        JOIN contacts c ON c.id = i.contact_id
        WHERE i.kind = ? AND i.value = ?
        """,
        (kind, canon),
    ).fetchone()
    return _contacts._row_to_contact(row) if row else None


# ─── Conflict tracking ─────────────────────────────────────────────────


def record_identity_conflict(
    conn: sqlite3.Connection,
    *,
    kind: str,
    value: str,
    candidate_contact_ids: Iterable[str],
    reason: str,
) -> dict[str, Any]:
    """Record a quarantine row for a (kind,value) that maps to multiple
    contacts. Idempotent across re-runs of ``elevate migrate-data`` — if an
    open conflict already exists for the same (kind,value,reason) tuple,
    fold the new candidates into the existing row instead of inserting a
    duplicate (Codex audit P1, 2026-05-05).
    """
    cids = list(dict.fromkeys(candidate_contact_ids))  # dedup + preserve order

    existing = conn.execute(
        """
        SELECT * FROM identity_conflicts
        WHERE kind=? AND value=? AND reason=? AND resolved_at IS NULL
        """,
        (kind, value, reason),
    ).fetchone()
    if existing is not None:
        try:
            prior = json.loads(existing["candidate_contact_ids"]) or []
        except (TypeError, ValueError, json.JSONDecodeError):
            prior = []
        merged = list(dict.fromkeys([*prior, *cids]))
        if merged != prior:
            conn.execute(
                "UPDATE identity_conflicts SET candidate_contact_ids=? WHERE id=?",
                (json.dumps(merged), existing["id"]),
            )
            _contacts.set_open_conflict_flag(conn, merged, True)
        return _row_to_conflict(
            conn.execute(
                "SELECT * FROM identity_conflicts WHERE id=?", (existing["id"],)
            ).fetchone()
        )

    conflict_id = new_id()
    conn.execute(
        """
        INSERT INTO identity_conflicts(
            id, kind, value, candidate_contact_ids, reason, created_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (conflict_id, kind, value, json.dumps(cids), reason, now_iso()),
    )
    _contacts.set_open_conflict_flag(conn, cids, True)
    return _row_to_conflict(
        conn.execute(
            "SELECT * FROM identity_conflicts WHERE id=?", (conflict_id,)
        ).fetchone()
    )


def resolve_identity_conflict(
    conn: sqlite3.Connection,
    conflict_id: str,
    *,
    resolution: str,            # 'merged_into:<contact_id>' | 'kept_separate' | 'discarded'
    actor: str,
) -> dict[str, Any]:
    if not (
        resolution == "kept_separate"
        or resolution == "discarded"
        or resolution.startswith("merged_into:")
    ):
        raise ValueError(f"invalid resolution {resolution!r}")
    if not actor.startswith("human"):
        raise PermissionError(
            "resolve_identity_conflict requires a human actor (starts with 'human')"
        )
    now = now_iso()
    conn.execute(
        """
        UPDATE identity_conflicts
        SET resolved_at=?, resolved_by=?, resolution=?
        WHERE id=?
        """,
        (now, actor, resolution, conflict_id),
    )
    row = conn.execute(
        "SELECT * FROM identity_conflicts WHERE id=?", (conflict_id,)
    ).fetchone()
    cids = json.loads(row["candidate_contact_ids"])

    if resolution.startswith("merged_into:"):
        primary_id = resolution.split(":", 1)[1]
        for cid in cids:
            if cid != primary_id:
                merge_contacts(conn, primary_id=primary_id, duplicate_id=cid, actor=actor)
        # After merge the old contacts are gone, so flagging them is moot.
        _contacts.set_open_conflict_flag(conn, [primary_id], False)
    else:
        _contacts.set_open_conflict_flag(conn, cids, False)
    return _row_to_conflict(row)


def list_open_conflicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM identity_conflicts
        WHERE resolved_at IS NULL
        ORDER BY created_at ASC
        """
    ).fetchall()
    return [_row_to_conflict(r) for r in rows]


def open_conflicts_blocking_active_leads(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Return open identity conflicts that touch contacts with hot/warm
    activity. Used as a DB-primary cutover gate — flipping
    ``ELEVATE_DATA_PRIMARY=db`` is unsafe while live leads have an
    unresolved merge candidate (heat, drafts, send state would split
    across both contact rows).

    Codex audit P1 (2026-05-05): "block production cutover on open
    identity conflicts for active leads."
    """
    open_rows = list_open_conflicts(conn)
    blocking: list[dict[str, Any]] = []
    for row in open_rows:
        cids = row.get("candidate_contact_ids") or []
        if not cids:
            continue
        placeholders = ",".join("?" * len(cids))
        active = conn.execute(
            f"""
            SELECT id FROM contacts
            WHERE id IN ({placeholders})
              AND (stage IN ('hot','warm') OR last_activity_at IS NOT NULL)
            LIMIT 1
            """,
            cids,
        ).fetchone()
        if active is not None:
            blocking.append(row)
    return blocking


# ─── Merge ─────────────────────────────────────────────────────────────


def merge_contacts(
    conn: sqlite3.Connection,
    *,
    primary_id: str,
    duplicate_id: str,
    actor: str,
) -> dict[str, Any]:
    """Reassign every dependent row from ``duplicate_id`` to ``primary_id``,
    then delete the duplicate. Emits a ``merge`` event on the primary.

    Constraint: actor must start with ``human`` (string match, mirrors
    how :func:`resolve_identity_conflict` enforces it). Agents propose
    merges via ``identity_conflicts`` only — they cannot execute the
    final merge directly.
    """
    if not actor.startswith("human"):
        raise PermissionError(
            "merge_contacts requires a human actor (starts with 'human')"
        )
    if primary_id == duplicate_id:
        raise ValueError("primary_id and duplicate_id are the same contact")
    if not _contacts.get_contact(conn, primary_id):
        raise LookupError(f"primary contact {primary_id!r} not found")
    if not _contacts.get_contact(conn, duplicate_id):
        raise LookupError(f"duplicate contact {duplicate_id!r} not found")

    # Reassign all FK rows. Anything not listed here stays untouched —
    # add tables to this list as the schema grows.
    #
    # CASCADE-on-delete tables (conversations, events, identities,
    # pcs_buyers, notes, lead_inquiries, lead_properties, deal_contacts)
    # would technically cascade, but we re-point them explicitly so the
    # primary contact ends up owning the rows instead of losing them.
    #
    # RESTRICT tables (lead_signals.graduated_to_contact_id,
    # events_summary, deals, agent_handoffs) MUST be reassigned before
    # the DELETE or the transaction aborts on FK violation.
    for sql in (
        "UPDATE identities      SET contact_id=? WHERE contact_id=?",
        "UPDATE conversations   SET contact_id=? WHERE contact_id=?",
        "UPDATE events          SET contact_id=? WHERE contact_id=?",
        "UPDATE lead_signals    SET graduated_to_contact_id=? WHERE graduated_to_contact_id=?",
        "UPDATE events_summary  SET contact_id=? WHERE contact_id=?",
    ):
        conn.execute(sql, (primary_id, duplicate_id))
    # pcs_buyers' contact_id is a PK — if both have rows, the duplicate
    # row needs to be deleted before we'd hit a constraint. If only the
    # duplicate has one, reassign it.
    pcs_dup = conn.execute(
        "SELECT * FROM pcs_buyers WHERE contact_id=?", (duplicate_id,)
    ).fetchone()
    if pcs_dup is not None:
        pcs_primary = conn.execute(
            "SELECT 1 FROM pcs_buyers WHERE contact_id=?", (primary_id,)
        ).fetchone()
        if pcs_primary is None:
            conn.execute(
                "UPDATE pcs_buyers SET contact_id=? WHERE contact_id=?",
                (primary_id, duplicate_id),
            )
        else:
            conn.execute(
                "DELETE FROM pcs_buyers WHERE contact_id=?", (duplicate_id,)
            )

    conn.execute("DELETE FROM contacts WHERE id=?", (duplicate_id,))
    _events.record_lifecycle(
        conn,
        contact_id=primary_id,
        kind="merge",
        actor=actor,
        payload={"mergedFrom": duplicate_id},
    )
    return _contacts.get_contact(conn, primary_id)  # type: ignore[return-value]
