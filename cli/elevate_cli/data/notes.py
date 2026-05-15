"""Read/write helpers for the ``notes`` table (migrations 0019 + 0020).

Notes are annotations attached to a contact: operator-typed in the
Elevate UI, or AI-written by cron jobs (review_contact, draft monitors,
theta-wave, close-to-admin). Distinct from ``events`` — events are the
immutable activity log; notes are mutable annotations that round-trip
through the CRM's note CRUD endpoints.

Migration 0020 renamed the sync-state columns to be CRM-agnostic:
``crm_remote_id``, ``crm_sync_state``, ``crm_synced_at``,
``crm_last_error``, ``crm_attempt_count`` (+ ``crm_provider``
discriminator). The push worker reads ``crm_provider`` to pick the API.

Public surface (re-exported via ``elevate_cli.data``):

* :func:`write_note` — insert a note. Returns the new row.
* :func:`list_notes_for_contact` — drawer read path.
* :func:`recent_ai_note` — daily-cap probe.
* :func:`list_pending_lofty_notes` — push worker queue (name kept for
  back-compat; reads ``crm_sync_state='pending'``).
* :func:`mark_lofty_synced` / :func:`mark_lofty_failed` /
  :func:`mark_lofty_deleted` — push/pull worker state transitions.

Volume guard: ``write_note`` enforces a per-(contact, author_kind,
author_name) daily cap when ``daily_cap=True`` (default for AI authors).
The first AI cron pass auto-labeled 217 contacts; without the cap that
would have been 217 CRM POSTs in a single sweep.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.data._util import new_id, now_iso


def _row_to_note(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "contactId": row["contact_id"],
        "body": row["body"],
        "authorKind": row["author_kind"],
        "authorName": row["author_name"],
        "sourceEventId": row["source_event_id"],
        "pinned": bool(row["pinned"]),
        "deleted": bool(row["deleted"]),
        "crmProvider": row["crm_provider"] if "crm_provider" in keys else None,
        "crmRemoteId": row["crm_remote_id"],
        "crmSyncState": row["crm_sync_state"],
        "crmSyncedAt": row["crm_synced_at"],
        "crmLastError": row["crm_last_error"],
        "crmAttemptCount": int(row["crm_attempt_count"] or 0),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def recent_ai_note(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    author_name: str,
    within_hours: int = 24,
) -> dict[str, Any] | None:
    """Return the most recent AI note from ``author_name`` on this contact
    if one was written in the last ``within_hours``. ``None`` otherwise.

    Used by ``write_note`` for the daily cap. Also useful for cron jobs
    that want to dedupe "I already said this" before composing a body.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    row = conn.execute(
        """
        SELECT * FROM notes
        WHERE contact_id = ?
          AND author_kind = 'ai'
          AND author_name = ?
          AND created_at >= ?
          AND deleted = 0
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (contact_id, author_name, cutoff),
    ).fetchone()
    return _row_to_note(row) if row is not None else None


def write_note(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    body: str,
    author_kind: str,
    author_name: str,
    source_event_id: str | None = None,
    pinned: bool = False,
    push_to_crm: bool = True,
    daily_cap: bool | None = None,
) -> dict[str, Any] | None:
    """Insert a note for ``contact_id``. Returns the new row.

    ``author_kind`` is one of ``ai`` / ``operator`` / ``system``.
    ``author_name`` is the cron identifier or human name.

    ``push_to_crm`` sets ``crm_sync_state='pending'`` so the push worker
    picks the note up on its next pass. Setting False keeps the note
    local-only (useful for system bookkeeping the operator doesn't need
    to see in their CRM).

    ``daily_cap`` defaults to True for ``ai`` authors, False otherwise.
    When True and the same (contact, author_kind, author_name) already
    has a note in the last 24h, returns ``None`` without inserting.
    Caller treats ``None`` as "duplicate suppressed, that's fine."
    """
    body = (body or "").strip()
    if not body:
        raise ValueError("note body cannot be empty")
    if author_kind not in {"ai", "operator", "system"}:
        raise ValueError(f"invalid author_kind: {author_kind}")
    if not author_name:
        raise ValueError("author_name is required")

    if daily_cap is None:
        daily_cap = author_kind == "ai"

    if daily_cap:
        existing = recent_ai_note(
            conn,
            contact_id=contact_id,
            author_name=author_name,
            within_hours=24,
        )
        if existing is not None:
            return None

    note_id = new_id()
    now = now_iso()
    sync_state = "pending" if push_to_crm else None

    conn.execute(
        """
        INSERT INTO notes(
            id, contact_id, body,
            author_kind, author_name,
            source_event_id, pinned, deleted,
            crm_remote_id, crm_sync_state,
            crm_synced_at, crm_last_error,
            crm_attempt_count,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL, NULL, 0, ?, ?)
        """,
        (
            note_id, contact_id, body,
            author_kind, author_name,
            source_event_id, 1 if pinned else 0,
            sync_state,
            now, now,
        ),
    )
    row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    return _row_to_note(row)


def list_notes_for_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    include_deleted: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Drawer read path. Most recent first."""
    if include_deleted:
        sql = (
            "SELECT * FROM notes WHERE contact_id=? "
            "ORDER BY pinned DESC, created_at DESC LIMIT ?"
        )
    else:
        sql = (
            "SELECT * FROM notes WHERE contact_id=? AND deleted=0 "
            "ORDER BY pinned DESC, created_at DESC LIMIT ?"
        )
    rows = conn.execute(sql, (contact_id, limit)).fetchall()
    return [_row_to_note(r) for r in rows]


def list_pending_lofty_notes(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    max_attempts: int = 5,
) -> list[dict[str, Any]]:
    """Push-worker queue: pending notes oldest-first, with attempt cap.

    Notes whose contact lacks a CRM identity stay in the queue until
    either an identity gets added or the worker marks them failed after
    ``max_attempts``.
    """
    rows = conn.execute(
        """
        SELECT * FROM notes
        WHERE crm_sync_state = 'pending'
          AND crm_attempt_count < ?
          AND deleted = 0
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (max_attempts, limit),
    ).fetchall()
    return [_row_to_note(r) for r in rows]


def mark_lofty_synced(
    conn: sqlite3.Connection,
    *,
    note_id: str,
    lofty_note_id: str,
    crm_provider: str = "lofty",
) -> None:
    """Push worker success path."""
    now = now_iso()
    conn.execute(
        """
        UPDATE notes
        SET crm_remote_id = ?,
            crm_provider = COALESCE(crm_provider, ?),
            crm_sync_state = 'synced',
            crm_synced_at = ?,
            crm_last_error = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (lofty_note_id, crm_provider, now, now, note_id),
    )


def mark_lofty_failed(
    conn: sqlite3.Connection,
    *,
    note_id: str,
    error: str,
    permanent: bool = False,
) -> None:
    """Push worker failure path. ``permanent=True`` moves the row to
    ``failed`` immediately (4xx). ``permanent=False`` increments the
    attempt counter and leaves it ``pending`` for the next worker pass
    (5xx, timeout)."""
    now = now_iso()
    if permanent:
        conn.execute(
            """
            UPDATE notes
            SET crm_sync_state = 'failed',
                crm_last_error = ?,
                crm_attempt_count = crm_attempt_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (error[:2000], now, note_id),
        )
    else:
        conn.execute(
            """
            UPDATE notes
            SET crm_last_error = ?,
                crm_attempt_count = crm_attempt_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (error[:2000], now, note_id),
        )


def mark_lofty_deleted(
    conn: sqlite3.Connection,
    *,
    lofty_note_id: str,
    crm_provider: str | None = None,
) -> None:
    """Pull-side mirror. When the CRM sync sees a note with
    ``deleteFlag=true`` we mark our row deleted so it stops appearing in
    the drawer and the push worker doesn't try to re-create it.

    If ``crm_provider`` is given, only matches notes for that provider —
    relevant once multiple CRMs can hand us the same remote id.
    """
    now = now_iso()
    if crm_provider is None:
        conn.execute(
            """
            UPDATE notes
            SET deleted = 1,
                crm_sync_state = 'deleted',
                updated_at = ?
            WHERE crm_remote_id = ?
            """,
            (now, lofty_note_id),
        )
    else:
        conn.execute(
            """
            UPDATE notes
            SET deleted = 1,
                crm_sync_state = 'deleted',
                updated_at = ?
            WHERE crm_remote_id = ? AND crm_provider = ?
            """,
            (now, lofty_note_id, crm_provider),
        )


__all__ = [
    "list_notes_for_contact",
    "list_pending_lofty_notes",
    "mark_lofty_deleted",
    "mark_lofty_failed",
    "mark_lofty_synced",
    "recent_ai_note",
    "write_note",
]
