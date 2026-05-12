"""Cold MLS / scrape data + PCS graduation.

Lead signals are the holding pen for scraped records that aren't yet
contacts — high-volume private-search buyers, future Realtor.ca
saved searches, etc. They graduate to ``contacts`` only when:

* a verified identity match links the signal to an existing contact, OR
* a human classify/respond action explicitly promotes the signal.

Public surface:

* :func:`upsert_lead_signal`
* :func:`get_lead_signal`
* :func:`graduate_lead_signal`
* :func:`detect_lead_signal_activity_change`
* :func:`upsert_pcs_buyer`
* :func:`list_open_signals`
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from elevate_cli.data import events as _events
from elevate_cli.data._util import (
    new_id,
    normalize_email,
    normalize_phone,
    now_iso,
)


def _row_to_signal(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceId": row["source_id"],
        "sourceNativeId": row["source_native_id"],
        "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "lastActivityAt": row["last_activity_at"],
        "graduatedAt": row["graduated_at"],
        "graduatedToContactId": row["graduated_to_contact_id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_pcs(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "contactId": row["contact_id"],
        "leadSignalId": row["lead_signal_id"],
        "score": row["score"],
        "tier": row["tier"],
        "days": row["days"],
        "searches": json.loads(row["searches_json"]) if row["searches_json"] else None,
        "matchingListings": (
            json.loads(row["matching_listings_json"])
            if row["matching_listings_json"] else None
        ),
        "lastActivityAt": row["last_activity_at"],
        "lastScrapedAt": row["last_scraped_at"],
        "profileUrl": row["profile_url"],
    }


# ─── Lead signal CRUD ──────────────────────────────────────────────────


def upsert_lead_signal(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    source_native_id: str,
    payload: dict[str, Any],
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    last_activity_at: str | None = None,
) -> dict[str, Any]:
    """Idempotent insert keyed on ``(source_id, source_native_id)``.

    ``last_activity_at`` updates only when the new value is newer than
    the stored one — that's how :func:`detect_lead_signal_activity_change`
    knows whether to emit a ``pcs_activity`` event later.
    """
    canon_email = normalize_email(email)
    canon_phone = normalize_phone(phone)
    now = now_iso()

    existing = conn.execute(
        "SELECT * FROM lead_signals WHERE source_id=? AND source_native_id=?",
        (source_id, source_native_id),
    ).fetchone()

    if existing is None:
        sid = new_id()
        conn.execute(
            """
            INSERT INTO lead_signals(
                id, source_id, source_native_id, payload_json,
                name, email, phone, last_activity_at,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sid, source_id, source_native_id, json.dumps(payload),
                name, canon_email, canon_phone, last_activity_at,
                now, now,
            ),
        )
        return _row_to_signal(
            conn.execute("SELECT * FROM lead_signals WHERE id=?", (sid,)).fetchone()
        )

    sid = existing["id"]
    new_last = last_activity_at if last_activity_at and (
        not existing["last_activity_at"] or last_activity_at > existing["last_activity_at"]
    ) else existing["last_activity_at"]
    conn.execute(
        """
        UPDATE lead_signals
        SET payload_json=?, name=?, email=?, phone=?,
            last_activity_at=?, updated_at=?
        WHERE id=?
        """,
        (
            json.dumps(payload),
            name if name is not None else existing["name"],
            canon_email if canon_email is not None else existing["email"],
            canon_phone if canon_phone is not None else existing["phone"],
            new_last,
            now,
            sid,
        ),
    )
    return _row_to_signal(
        conn.execute("SELECT * FROM lead_signals WHERE id=?", (sid,)).fetchone()
    )


def get_lead_signal(
    conn: sqlite3.Connection, signal_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM lead_signals WHERE id=?", (signal_id,)
    ).fetchone()
    return _row_to_signal(row) if row else None


def list_open_signals(
    conn: sqlite3.Connection,
    *,
    source_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM lead_signals WHERE graduated_at IS NULL"
    params: list[Any] = []
    if source_id:
        sql += " AND source_id = ?"
        params.append(source_id)
    sql += " ORDER BY last_activity_at DESC NULLS LAST, updated_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_signal(r) for r in conn.execute(sql, params).fetchall()]


def graduate_lead_signal(
    conn: sqlite3.Connection,
    signal_id: str,
    *,
    contact_id: str,
    actor: str,
) -> dict[str, Any]:
    """Promote a lead signal into a real contact link.

    Sets ``graduated_at`` + ``graduated_to_contact_id`` on the signal
    and emits a ``lifecycle_change`` event on the contact recording
    the source link. Caller is responsible for having created the
    contact + identity rows first."""
    now = now_iso()
    conn.execute(
        """
        UPDATE lead_signals
        SET graduated_at=?, graduated_to_contact_id=?, updated_at=?
        WHERE id=?
        """,
        (now, contact_id, now, signal_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="lifecycle_change",
        actor=actor,
        ts=now,
        payload={
            "leadSignalId": signal_id,
            "transition": "graduated_from_lead_signal",
        },
    )
    return get_lead_signal(conn, signal_id)  # type: ignore[return-value]


def detect_lead_signal_activity_change(
    conn: sqlite3.Connection,
    signal_id: str,
    *,
    new_last_activity_at: str,
) -> bool:
    """Return True if ``new_last_activity_at`` is strictly newer than
    the stored value. Caller emits a ``pcs_activity`` event on the
    graduated contact and updates the row.

    Returns False if the signal is unknown or the new ts is not newer."""
    row = conn.execute(
        "SELECT last_activity_at FROM lead_signals WHERE id=?", (signal_id,)
    ).fetchone()
    if row is None:
        return False
    current = row["last_activity_at"] or ""
    return new_last_activity_at > current


# ─── PCS buyer addendum ────────────────────────────────────────────────


def upsert_pcs_buyer(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    lead_signal_id: str,
    analyzer_record: dict[str, Any],
) -> dict[str, Any]:
    """Insert/refresh the PCS buyer addendum row for a graduated contact."""
    now = now_iso()
    score = analyzer_record.get("score")
    tier = analyzer_record.get("tier")
    days = analyzer_record.get("days")
    searches = analyzer_record.get("searches")
    listings = analyzer_record.get("matchingListings") or analyzer_record.get("matching_listings")
    profile_url = analyzer_record.get("profileUrl") or analyzer_record.get("profile_url")
    last_activity = (
        analyzer_record.get("lastActivity")
        or analyzer_record.get("last_activity")
        or analyzer_record.get("lastActivityAt")
    )

    row = conn.execute(
        "SELECT 1 FROM pcs_buyers WHERE contact_id=?", (contact_id,)
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO pcs_buyers(
                contact_id, lead_signal_id, score, tier, days,
                searches_json, matching_listings_json,
                last_activity_at, last_scraped_at, profile_url
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                contact_id, lead_signal_id, score, tier, days,
                json.dumps(searches) if searches is not None else None,
                json.dumps(listings) if listings is not None else None,
                last_activity, now, profile_url,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE pcs_buyers
            SET lead_signal_id=?, score=?, tier=?, days=?,
                searches_json=?, matching_listings_json=?,
                last_activity_at=?, last_scraped_at=?, profile_url=?
            WHERE contact_id=?
            """,
            (
                lead_signal_id, score, tier, days,
                json.dumps(searches) if searches is not None else None,
                json.dumps(listings) if listings is not None else None,
                last_activity, now, profile_url,
                contact_id,
            ),
        )
    return _row_to_pcs(
        conn.execute(
            "SELECT * FROM pcs_buyers WHERE contact_id=?", (contact_id,)
        ).fetchone()
    )
