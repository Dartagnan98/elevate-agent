"""Conversation lookup + counter maintenance.

A "conversation" is one ``(contact_id, source_id, channel, thread_key)``
tuple. The unique index on ``(source_id, thread_key)`` is what makes
re-imports collide cleanly instead of duplicating threads.

Public surface:

* :func:`get_or_create_conversation`
* :func:`update_conversation_status`
* :func:`get_conversations_for_contact`
* :func:`bump_conversation_counters`
* :func:`set_heat`
"""

from __future__ import annotations

import sqlite3
from typing import Any

from elevate_cli.data._util import new_id, now_iso


def _row_to_conv(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "contactId": row["contact_id"],
        "sourceId": row["source_id"],
        "channel": row["channel"],
        "threadKey": row["thread_key"],
        "status": row["status"],
        "inboundCount": row["inbound_count"],
        "outboundCount": row["outbound_count"],
        "lastInboundAt": row["last_inbound_at"],
        "lastOutboundAt": row["last_outbound_at"],
        "heatScore": row["heat_score"],
        "heatLabel": row["heat_label"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_or_create_conversation(
    conn: sqlite3.Connection,
    *,
    contact_id: str,
    source_id: str,
    channel: str,
    thread_key: str,
) -> dict[str, Any]:
    """Idempotent lookup-or-insert keyed on ``(source_id, thread_key)``.

    If a row with the same ``(source_id, thread_key)`` already exists
    against a DIFFERENT contact, we trust the existing assignment and
    return that row — the caller (typically identity resolution) is the
    layer responsible for figuring out whether the two contacts should
    merge. We never silently re-parent a conversation here.
    """
    row = conn.execute(
        "SELECT * FROM conversations WHERE source_id=? AND thread_key=?",
        (source_id, thread_key),
    ).fetchone()
    if row is not None:
        return _row_to_conv(row)
    cid = new_id()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO conversations(
            id, contact_id, source_id, channel, thread_key,
            status, inbound_count, outbound_count,
            heat_score, heat_label, created_at, updated_at
        ) VALUES (?,?,?,?,?, 'open', 0, 0, 0, 'normal', ?, ?)
        """,
        (cid, contact_id, source_id, channel, thread_key, now, now),
    )
    return _row_to_conv(
        conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    )


def get_conversation(
    conn: sqlite3.Connection, conversation_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    return _row_to_conv(row) if row else None


def update_conversation_status(
    conn: sqlite3.Connection, conversation_id: str, status: str
) -> None:
    if status not in {"open", "done", "archived"}:
        raise ValueError(f"invalid conversation status {status!r}")
    conn.execute(
        "UPDATE conversations SET status=?, updated_at=? WHERE id=?",
        (status, now_iso(), conversation_id),
    )


def get_conversations_for_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    channel: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM conversations WHERE contact_id = ?"
    params: list[Any] = [contact_id]
    if channel is not None:
        sql += " AND channel = ?"
        params.append(channel)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY last_inbound_at DESC NULLS LAST, updated_at DESC"
    return [_row_to_conv(r) for r in conn.execute(sql, params).fetchall()]


def bump_conversation_counters(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    direction: str,        # 'inbound' | 'outbound'
    ts: str,
) -> None:
    """Atomically increment the matching counter and stamp the timestamp."""
    if direction == "inbound":
        conn.execute(
            """
            UPDATE conversations
            SET inbound_count = inbound_count + 1,
                last_inbound_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (ts, now_iso(), conversation_id),
        )
    elif direction == "outbound":
        conn.execute(
            """
            UPDATE conversations
            SET outbound_count = outbound_count + 1,
                last_outbound_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (ts, now_iso(), conversation_id),
        )
    else:
        raise ValueError(f"invalid direction {direction!r}")


def set_heat(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    score: int,
    label: str,
) -> None:
    if label not in {"hot", "warm", "watch", "normal"}:
        raise ValueError(f"invalid heat label {label!r}")
    conn.execute(
        """
        UPDATE conversations
        SET heat_score=?, heat_label=?, updated_at=?
        WHERE id=?
        """,
        (score, label, now_iso(), conversation_id),
    )
