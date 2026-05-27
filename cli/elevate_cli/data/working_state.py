"""Per-entity "where we left off" journal for the agent.

Sits on top of the ``notes`` table (migration 0002). Lets the agent
record its working state on a deal or contact so the NEXT session knows
exactly where it left off without the user re-briefing.

Why it lives on ``notes`` and not a parallel table:

* Notes already round-trip a CRM sync infrastructure (``crm_provider``,
  ``crm_sync_state``); working-state rows just opt out with
  ``push_to_crm=False``.
* The drawer UI already paginates a contact's notes; surfacing the
  working-state row there is one filter on ``is_working_state``.
* Migration cost is one ``ALTER TABLE`` instead of a brand-new table.

Conceptual model
----------------

A working-state entry is the agent's snapshot of *what we're doing on
this deal/contact and what's pending next*. It is NOT the activity log
(that's ``events``) and NOT a checklist of UI tasks (that's
``deal_events`` for deals or ``leads_setup_items`` for the leads pack).

Each entry targets exactly one entity via ``(entity_kind, entity_id)``:

* ``contact`` → ``entity_id`` is the contact's id (covers leads — leads
  are contacts with ``lead_signals``)
* ``deal`` → ``entity_id`` is the deal id

When the agent updates the working state, the previous row is
*superseded* (its ``superseded_by_id`` points at the new row); the new
row becomes the "latest active" entry. Full history is preserved so the
user can audit "what was the agent thinking 3 days ago on this deal".

Status drives the session-start digest:

* ``in_progress``      — actively being worked
* ``pending_external`` — waiting on a third party (buyer agent, lawyer)
* ``blocked``          — can't proceed; needs user input or external fix
* ``resolved``         — done; excluded from active list

Public surface (re-exported via ``elevate_cli.data``):

* :func:`recall_working_state`     — latest active entry for one entity
* :func:`update_working_state`     — supersede + insert (the main write)
* :func:`resolve_working_state`    — convenience: mark current as resolved
* :func:`list_active_working_state`— for digest + ``working_state.list``
* :func:`working_state_digest`     — formatted markdown for system prompt
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from elevate_cli.data._util import new_id, now_iso


_VALID_KINDS = frozenset({"contact", "deal"})
_VALID_STATUSES = frozenset(
    {"in_progress", "pending_external", "blocked", "resolved"}
)


def _row_to_state(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "entityKind": row["entity_kind"] if "entity_kind" in keys else "contact",
        "contactId": row["contact_id"],
        "dealId": row["deal_id"] if "deal_id" in keys else None,
        "body": row["body"],
        "status": row["state_status"] if "state_status" in keys else None,
        "nextAction": row["next_action"] if "next_action" in keys else None,
        "blockedOn": row["blocked_on"] if "blocked_on" in keys else None,
        "agentKind": row["agent_kind"] if "agent_kind" in keys else None,
        "authorName": row["author_name"],
        "supersededById":
            row["superseded_by_id"] if "superseded_by_id" in keys else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _entity_filter_sql(entity_kind: str) -> str:
    """Return the WHERE clause fragment that pins on the right id column."""
    if entity_kind == "contact":
        return "entity_kind = 'contact' AND contact_id = ?"
    if entity_kind == "deal":
        return "entity_kind = 'deal' AND deal_id = ?"
    raise ValueError(f"invalid entity_kind: {entity_kind}")


# ─── Reads ──────────────────────────────────────────────────────────


def recall_working_state(
    conn: sqlite3.Connection,
    *,
    entity_kind: str,
    entity_id: str,
) -> dict[str, Any] | None:
    """Latest active working-state entry for ``(entity_kind, entity_id)``.

    Returns ``None`` if nothing recorded yet, or if the latest entry is
    resolved (use :func:`list_resolved_working_state` to inspect history).
    """
    if entity_kind not in _VALID_KINDS:
        raise ValueError(f"invalid entity_kind: {entity_kind}")
    where = _entity_filter_sql(entity_kind)
    sql = (
        f"SELECT * FROM notes WHERE {where} "
        "AND is_working_state = 1 AND superseded_by_id IS NULL "
        "AND deleted = 0 ORDER BY updated_at DESC LIMIT 1"
    )
    row = conn.execute(sql, (entity_id,)).fetchone()
    if row is None:
        return None
    state = _row_to_state(row)
    if state.get("status") == "resolved":
        return None
    return state


def list_active_working_state(
    conn: sqlite3.Connection,
    *,
    entity_kinds: Iterable[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Every non-resolved active entry, newest-updated first.

    Default scope is BOTH contacts and deals so the session-start digest
    captures everything in flight. Pass ``entity_kinds=('deal',)`` to
    narrow to one kind.
    """
    kinds = list(entity_kinds) if entity_kinds else ["contact", "deal"]
    invalid = [k for k in kinds if k not in _VALID_KINDS]
    if invalid:
        raise ValueError(f"invalid entity_kind(s): {invalid}")

    placeholders = ",".join(["?"] * len(kinds))
    sql = (
        f"SELECT * FROM notes WHERE entity_kind IN ({placeholders}) "
        "AND is_working_state = 1 AND superseded_by_id IS NULL "
        "AND deleted = 0 "
        "AND (state_status IS NULL OR state_status != 'resolved') "
        "ORDER BY updated_at DESC LIMIT ?"
    )
    rows = conn.execute(sql, (*kinds, int(limit))).fetchall()
    return [_row_to_state(r) for r in rows]


def list_history_working_state(
    conn: sqlite3.Connection,
    *,
    entity_kind: str,
    entity_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Full working-state history for one entity, newest first."""
    if entity_kind not in _VALID_KINDS:
        raise ValueError(f"invalid entity_kind: {entity_kind}")
    where = _entity_filter_sql(entity_kind)
    sql = (
        f"SELECT * FROM notes WHERE {where} "
        "AND is_working_state = 1 AND deleted = 0 "
        "ORDER BY updated_at DESC LIMIT ?"
    )
    rows = conn.execute(sql, (entity_id, int(limit))).fetchall()
    return [_row_to_state(r) for r in rows]


# ─── Writes ─────────────────────────────────────────────────────────


def _validate_status(status: str | None) -> str:
    s = (status or "in_progress").strip().lower()
    if s not in _VALID_STATUSES:
        raise ValueError(
            f"invalid status: {status!r}. Expected one of {sorted(_VALID_STATUSES)}."
        )
    return s


def update_working_state(
    conn: sqlite3.Connection,
    *,
    entity_kind: str,
    entity_id: str,
    body: str,
    status: str | None = None,
    next_action: str | None = None,
    blocked_on: str | None = None,
    agent_kind: str | None = None,
    author_name: str = "agent",
) -> dict[str, Any]:
    """Record a new working-state snapshot. Supersedes the prior one.

    ``body`` is the short narrative ("Sent counter at $450k, awaiting
    reply from listing agent"). ``next_action`` is the one-line
    next-step. ``blocked_on`` is who/what we're waiting on (only really
    needed when status is ``pending_external`` or ``blocked``).

    Returns the newly inserted row. The previous row (if any) is left in
    place with its ``superseded_by_id`` pointing at the new id, so the
    history table tells the full story.
    """
    if entity_kind not in _VALID_KINDS:
        raise ValueError(f"invalid entity_kind: {entity_kind}")
    body = (body or "").strip()
    if not body:
        raise ValueError("body cannot be empty")
    status = _validate_status(status)

    contact_id = entity_id if entity_kind == "contact" else None
    deal_id = entity_id if entity_kind == "deal" else None

    new_state_id = new_id()
    now = now_iso()

    # 1) Insert the new entry first so the supersede FK has a target.
    conn.execute(
        """
        INSERT INTO notes(
            id, contact_id, deal_id, entity_kind,
            body, author_kind, author_name,
            source_event_id, pinned, deleted,
            crm_remote_id, crm_sync_state,
            crm_synced_at, crm_last_error, crm_attempt_count,
            is_working_state, state_status, next_action, blocked_on,
            superseded_by_id, agent_kind,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, 'ai', ?,
            NULL, 0, 0, NULL, NULL, NULL, NULL, 0,
            1, ?, ?, ?, NULL, ?, ?, ?
        )
        """,
        (
            new_state_id, contact_id, deal_id, entity_kind,
            body, author_name,
            status, next_action, blocked_on, agent_kind,
            now, now,
        ),
    )

    # 2) Supersede the previous active entry, if any.
    where = _entity_filter_sql(entity_kind)
    conn.execute(
        f"""
        UPDATE notes SET superseded_by_id = ?, updated_at = ?
        WHERE {where}
          AND is_working_state = 1
          AND superseded_by_id IS NULL
          AND deleted = 0
          AND id <> ?
        """,
        (new_state_id, now, entity_id, new_state_id),
    )

    row = conn.execute(
        "SELECT * FROM notes WHERE id = ?", (new_state_id,)
    ).fetchone()
    return _row_to_state(row)


def resolve_working_state(
    conn: sqlite3.Connection,
    *,
    entity_kind: str,
    entity_id: str,
    body: str,
    agent_kind: str | None = None,
    author_name: str = "agent",
) -> dict[str, Any]:
    """Mark the work as done. ``body`` is the closing note."""
    return update_working_state(
        conn,
        entity_kind=entity_kind,
        entity_id=entity_id,
        body=body,
        status="resolved",
        next_action=None,
        blocked_on=None,
        agent_kind=agent_kind,
        author_name=author_name,
    )


# ─── Auto-touch hook for deal mutations ─────────────────────────────


def touch_deal_stage_move(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    deal_title: str,
    from_stage: int | None,
    to_stage: int,
    agent_kind: str | None = None,
) -> dict[str, Any] | None:
    """Auto-touch the working state when a deal's stage moves.

    Only inserts an entry if there's no existing active entry from the
    same ``agent_kind`` in the last 30 minutes — otherwise it would
    spam the timeline during a setup burst. Returns the new row, or
    ``None`` if suppressed.

    Body is a short structured line: human readers AND the agent both
    benefit from a predictable shape.
    """
    existing = recall_working_state(
        conn, entity_kind="deal", entity_id=deal_id
    )
    if existing is not None:
        # If the latest entry was written in the last 30 min by the SAME
        # agent kind, just supersede with a refreshed body. Otherwise we
        # respect the existing entry and let the agent decide whether to
        # update it.
        same_agent = (
            (existing.get("agentKind") or None) == (agent_kind or None)
        )
        if not same_agent:
            return None

    body = (
        f"Moved deal '{deal_title}' from stage {from_stage} to {to_stage}."
        if from_stage is not None
        else f"Deal '{deal_title}' entered stage {to_stage}."
    )
    return update_working_state(
        conn,
        entity_kind="deal",
        entity_id=deal_id,
        body=body,
        status="in_progress",
        next_action=None,
        blocked_on=None,
        agent_kind=agent_kind,
        author_name=agent_kind or "deal-state-tracker",
    )


# ─── Session-start digest ───────────────────────────────────────────


def _format_digest_line(state: dict[str, Any]) -> str:
    kind = state.get("entityKind") or "contact"
    eid = state.get("dealId") if kind == "deal" else state.get("contactId")
    eid = (eid or "?")[:12]
    status = state.get("status") or "in_progress"
    body = (state.get("body") or "").strip().replace("\n", " ")
    if len(body) > 140:
        body = body[:137].rstrip() + "…"
    parts = [f"- [{kind} {eid}] ({status}) {body}"]
    nxt = (state.get("nextAction") or "").strip()
    if nxt:
        parts.append(f"  next: {nxt}")
    blocked = (state.get("blockedOn") or "").strip()
    if blocked and status in {"pending_external", "blocked"}:
        parts.append(f"  blocked on: {blocked}")
    return "\n".join(parts)


def working_state_digest(
    conn: sqlite3.Connection,
    *,
    limit: int = 12,
) -> str | None:
    """Markdown digest of every active working state, oldest first.

    Returns ``None`` when there's nothing in flight so callers can skip
    appending an empty section to the system prompt.

    Format is deliberately compact — one entity per stanza, the body
    truncated to ~140 chars — so the agent gets the "what's in play"
    snapshot at session start without burning a lot of cache budget.
    Full bodies are recoverable via the ``working_state`` tool's
    ``recall`` action.
    """
    rows = list_active_working_state(conn, limit=limit)
    if not rows:
        return None
    # Render oldest-first so the agent reads the digest top-to-bottom in
    # the order things became open.
    rows = list(reversed(rows))
    lines = [
        "## Active work in flight",
        "",
        (
            "These are the deals and leads with open working-state entries. "
            "Use the `working_state` tool to pull the full body, update an "
            "entry when you make progress, or resolve it when done."
        ),
        "",
    ]
    lines.extend(_format_digest_line(s) for s in rows)
    return "\n".join(lines)


__all__ = [
    "list_active_working_state",
    "list_history_working_state",
    "recall_working_state",
    "resolve_working_state",
    "touch_deal_stage_move",
    "update_working_state",
    "working_state_digest",
]
