"""Read/write helpers for the ``contacts`` table.

Public surface (re-exported via ``elevate_cli.data``):

* :func:`get_contact`
* :func:`find_contacts`
* :func:`upsert_contact`
* :func:`classify_contact`
* :func:`park_contact`, :func:`unpark_contact`
* :func:`update_contact_stage`
* :func:`add_contact_note`

Every mutation writes a paired row into the ``events`` audit log via
:mod:`elevate_cli.data.events`. Callers don't need to know.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from elevate_cli.data import events as _events
from elevate_cli.data._util import new_id, now_iso


def _row_to_contact(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "displayName": row["display_name"],
        "primaryEmail": row["primary_email"],
        "primaryPhone": row["primary_phone"],
        "type": row["type"],
        "stage": row["stage"],
        "ownerNotes": row["owner_notes"],
        "parkedReason": row["parked_reason"],
        "hasOpenConflict": bool(row["has_open_conflict"]),
        "lastActivityAt": row["last_activity_at"],
        "classifiedAt": row["classified_at"],
        "sourceKey": row["source_key"],
        "ingestRunId": row["ingest_run_id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# ─── Reads ─────────────────────────────────────────────────────────────


def get_contact(conn: sqlite3.Connection, contact_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    return _row_to_contact(row) if row else None


def find_contacts(
    conn: sqlite3.Connection,
    *,
    type: str | None = None,
    stage: str | None = None,
    stage_in: Iterable[str] | None = None,
    has_open_conflict: bool | None = None,
    last_activity_after: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Filterable list. All filters are AND-ed; pass ``None`` to skip a filter.

    ``last_activity_after`` is an ISO timestamp string — the SQL compares
    lexically, which works for ISO-8601 with a stable timezone offset
    (we always emit ``+00:00``).

    ``stage`` and ``stage_in`` are mutually exclusive — pass one or the
    other (or neither). ``stage_in`` accepts a list/tuple/set and emits
    ``stage IN (?, ?, …)``. Empty iterable returns no rows.
    """
    if stage is not None and stage_in is not None:
        raise ValueError("pass either stage or stage_in, not both")
    sql = "SELECT * FROM contacts WHERE 1=1"
    params: list[Any] = []
    if type is not None:
        sql += " AND type = ?"
        params.append(type)
    if stage is not None:
        sql += " AND stage = ?"
        params.append(stage)
    if stage_in is not None:
        stages = [s for s in stage_in]
        if not stages:
            return []
        placeholders = ",".join(["?"] * len(stages))
        sql += f" AND stage IN ({placeholders})"
        params.extend(stages)
    if has_open_conflict is not None:
        sql += " AND has_open_conflict = ?"
        params.append(1 if has_open_conflict else 0)
    if last_activity_after is not None:
        sql += " AND last_activity_at >= ?"
        params.append(last_activity_after)
    sql += " ORDER BY last_activity_at DESC NULLS LAST LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_contact(r) for r in rows]


# ─── Writes ────────────────────────────────────────────────────────────


def upsert_contact(
    conn: sqlite3.Connection,
    *,
    contact_id: str | None = None,
    display_name: str | None = None,
    primary_email: str | None = None,
    primary_phone: str | None = None,
    type: str = "unclassified",
    stage: str = "cold",
    source_key: str | None = None,
    ingest_run_id: str | None = None,
) -> dict[str, Any]:
    """Insert a new contact or update an existing one by id or source_key.

    Resolution order: explicit ``contact_id`` > ``source_key`` lookup >
    new contact. Returns the resulting row in dict form.

    Does NOT write an event — contact creation is an indirect side
    effect of identity resolution and ingest, so the connector code is
    responsible for emitting ``ingest_run_started`` etc. The lifecycle
    helpers below (``classify_contact``, ``park_contact``, ...) DO write
    events because each one is a direct user/agent action.
    """
    now = now_iso()

    existing: sqlite3.Row | None = None
    if contact_id:
        existing = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
    elif source_key:
        existing = conn.execute(
            "SELECT * FROM contacts WHERE source_key = ?", (source_key,)
        ).fetchone()

    if existing is None:
        cid = contact_id or new_id()
        conn.execute(
            """
            INSERT INTO contacts(
                id, display_name, primary_email, primary_phone,
                type, stage, source_key, ingest_run_id,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                display_name,
                primary_email,
                primary_phone,
                type,
                stage,
                source_key,
                ingest_run_id,
                now,
                now,
            ),
        )
        return get_contact(conn, cid)  # type: ignore[return-value]

    cid = existing["id"]
    # Patch only fields that the caller actually provided.
    sets: list[str] = []
    params: list[Any] = []
    if display_name is not None and display_name != existing["display_name"]:
        sets.append("display_name=?")
        params.append(display_name)
    if primary_email is not None and primary_email != existing["primary_email"]:
        sets.append("primary_email=?")
        params.append(primary_email)
    if primary_phone is not None and primary_phone != existing["primary_phone"]:
        sets.append("primary_phone=?")
        params.append(primary_phone)
    if ingest_run_id is not None and ingest_run_id != existing["ingest_run_id"]:
        sets.append("ingest_run_id=?")
        params.append(ingest_run_id)
    if sets:
        sets.append("updated_at=?")
        params.extend([now, cid])
        conn.execute(f"UPDATE contacts SET {', '.join(sets)} WHERE id = ?", params)
    return get_contact(conn, cid)  # type: ignore[return-value]


def classify_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    type: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Set ``contacts.type`` and stamp ``classified_at``. Emits ``classified``."""
    if type not in {"buyer", "listing", "other"}:
        raise ValueError(f"invalid type {type!r}")
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET type=?, classified_at=?, updated_at=? WHERE id=?",
        (type, now, now, contact_id),
    )
    _events.record_classification(
        conn, contact_id=contact_id, type=type, actor=actor, ts=now
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def park_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    reason: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Mark a contact ``stage='parked'`` with a reason. Emits ``parked``."""
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET stage='parked', parked_reason=?, updated_at=? WHERE id=?",
        (reason, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="parked",
        actor=actor,
        ts=now,
        payload={"reason": reason},
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def unpark_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Clear the parked state, returning the contact to ``stage='active'``.
    Emits ``unparked``."""
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET stage='active', parked_reason=NULL, updated_at=? WHERE id=?",
        (now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="unparked",
        actor=actor,
        ts=now,
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def update_contact_stage(
    conn: sqlite3.Connection,
    contact_id: str,
    stage: str,
    *,
    actor: str,
) -> dict[str, Any]:
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET stage=?, updated_at=? WHERE id=?",
        (stage, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="lifecycle_change",
        actor=actor,
        ts=now,
        payload={"stage": stage},
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def add_contact_note(
    conn: sqlite3.Connection,
    contact_id: str,
    note: str,
    *,
    actor: str,
) -> None:
    """Append a note to ``contacts.owner_notes`` (newline-delimited).
    Emits ``note``. Notes are append-only; we never overwrite history."""
    now = now_iso()
    row = conn.execute(
        "SELECT owner_notes FROM contacts WHERE id=?", (contact_id,)
    ).fetchone()
    existing = row["owner_notes"] if row and row["owner_notes"] else ""
    new_notes = (existing + ("\n" if existing else "") + note).strip()
    conn.execute(
        "UPDATE contacts SET owner_notes=?, updated_at=? WHERE id=?",
        (new_notes, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="note",
        actor=actor,
        ts=now,
        payload={"note": note},
    )


def touch_last_activity(
    conn: sqlite3.Connection, contact_id: str, ts: str
) -> None:
    """Bump ``last_activity_at`` if the new ts is newer. Internal helper
    used by inbound/outbound recorders."""
    row = conn.execute(
        "SELECT last_activity_at FROM contacts WHERE id=?", (contact_id,)
    ).fetchone()
    if row is None:
        return
    current = row["last_activity_at"] or ""
    if ts > current:
        conn.execute(
            "UPDATE contacts SET last_activity_at=?, updated_at=? WHERE id=?",
            (ts, now_iso(), contact_id),
        )


def set_open_conflict_flag(
    conn: sqlite3.Connection, contact_ids: Iterable[str], value: bool
) -> None:
    """Toggle ``has_open_conflict`` across a set of contacts. Used by
    ``identities.record_identity_conflict`` and the resolver."""
    flag = 1 if value else 0
    for cid in contact_ids:
        conn.execute(
            "UPDATE contacts SET has_open_conflict=?, updated_at=? WHERE id=?",
            (flag, now_iso(), cid),
        )
