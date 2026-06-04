"""Read/write helpers for ``surface_tasks`` + ``surface_approvals`` (migration 0020).

Faithful port of CTRL Flow's `/ai` tasks + approvals, adapted to Elevate's
drafts-only surface model:

* **Tasks** — the realtor (or theta-wave) dispatches a unit of work to a surface.
  ``assignee`` is a surface name (``leads``/``admin``/…) or ``'human'``. Dispatch =
  ENQUEUE: a pending task assigned to a surface is drained by that surface's next
  heartbeat WORK run (drafts-only). No daemon, no IPC.
* **Approvals** — created INTERNALLY by a heartbeat/experiment run when it produces
  something needing sign-off. Resolved on the dashboard ONLY (never Telegram — see
  feedback_no_telegram_approvals).

Every function takes an open ``conn`` (``with connect() as conn:``), matching the
other table modules. TEXT/INTEGER columns keep the SQLite + Postgres paths identical.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from elevate_cli.data._util import new_id, now_iso

TASK_STATUSES = {"pending", "in_progress", "blocked", "completed"}
TASK_PRIORITIES = {"urgent", "high", "normal", "low"}
APPROVAL_CATEGORIES = {"deployment", "cost", "access", "other"}
APPROVAL_STATUSES = {"pending", "approved", "rejected"}

_TASK_EDITABLE = {
    "title",
    "description",
    "status",
    "priority",
    "assignee",
    "project",
    "needs_approval",
    "notes",
    "outputs",
}


# ─── tasks ─────────────────────────────────────────────────────────────


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    outputs = row["outputs"]
    try:
        outputs = json.loads(outputs) if outputs else []
    except Exception:
        outputs = []
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "assignee": row["assignee"],
        "project": row["project"],
        "needsApproval": bool(row["needs_approval"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
        "notes": row["notes"],
        "outputs": outputs,
    }


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str | None = None,
    status: str = "pending",
    priority: str = "normal",
    assignee: str | None = None,
    project: str | None = None,
    needs_approval: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ValueError("task title cannot be empty")
    if status not in TASK_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    if priority not in TASK_PRIORITIES:
        raise ValueError(f"invalid priority: {priority!r}")
    tid = new_id()
    ts = now_iso()
    conn.execute(
        "INSERT INTO surface_tasks(id, title, description, status, priority, assignee, "
        "project, needs_approval, created_at, updated_at, completed_at, notes, outputs) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tid, title, description, status, priority, assignee, project,
            1 if needs_approval else 0, ts, ts, None, notes, json.dumps([]),
        ),
    )
    return get_task(conn, tid)  # type: ignore[return-value]


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    assignee: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM surface_tasks"
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if assignee:
        where.append("assignee = ?")
        params.append(assignee)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"
    return [_row_to_task(r) for r in conn.execute(sql, tuple(params))]


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM surface_tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def update_task(
    conn: sqlite3.Connection, task_id: str, patch: dict[str, Any]
) -> Optional[dict[str, Any]]:
    if not get_task(conn, task_id):
        return None
    sets: list[str] = []
    params: list[Any] = []
    for key, val in patch.items():
        if key not in _TASK_EDITABLE or val is None:
            continue
        if key == "status" and val not in TASK_STATUSES:
            raise ValueError(f"invalid status: {val!r}")
        if key == "priority" and val not in TASK_PRIORITIES:
            raise ValueError(f"invalid priority: {val!r}")
        if key == "needs_approval":
            val = 1 if val else 0
        if key == "outputs":
            val = json.dumps(val)
        sets.append(f"{key} = ?")
        params.append(val)
    ts = now_iso()
    sets.append("updated_at = ?")
    params.append(ts)
    # Stamp completed_at when transitioning to completed.
    if patch.get("status") == "completed":
        sets.append("completed_at = ?")
        params.append(ts)
    params.append(task_id)
    conn.execute(f"UPDATE surface_tasks SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return get_task(conn, task_id)


def delete_task(conn: sqlite3.Connection, task_id: str) -> bool:
    cur = conn.execute("DELETE FROM surface_tasks WHERE id = ?", (task_id,))
    return bool(getattr(cur, "rowcount", 0))


# ─── approvals ─────────────────────────────────────────────────────────


def _row_to_approval(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "description": row["description"],
        "status": row["status"],
        "surface": row["surface"],
        "createdAt": row["created_at"],
        "resolvedAt": row["resolved_at"],
        "resolvedBy": row["resolved_by"],
        "resolutionNote": row["resolution_note"],
    }


def create_approval(
    conn: sqlite3.Connection,
    *,
    title: str,
    category: str = "other",
    description: str | None = None,
    surface: str | None = None,
) -> dict[str, Any]:
    """Create a pending approval. INTERNAL — called by a heartbeat/experiment run,
    not a public endpoint."""
    title = (title or "").strip()
    if not title:
        raise ValueError("approval title cannot be empty")
    if category not in APPROVAL_CATEGORIES:
        category = "other"
    aid = new_id()
    conn.execute(
        "INSERT INTO surface_approvals(id, title, category, description, status, surface, "
        "created_at, resolved_at, resolved_by, resolution_note) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (aid, title, category, description, "pending", surface, now_iso(), None, None, None),
    )
    return get_approval(conn, aid)  # type: ignore[return-value]


def list_approvals(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    surface: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM surface_approvals"
    where: list[str] = []
    params: list[Any] = []
    if status == "resolved":
        where.append("status IN ('approved','rejected')")
    elif status:
        where.append("status = ?")
        params.append(status)
    if surface:
        where.append("surface = ?")
        params.append(surface)
    if category:
        where.append("category = ?")
        params.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"
    return [_row_to_approval(r) for r in conn.execute(sql, tuple(params))]


def get_approval(conn: sqlite3.Connection, approval_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM surface_approvals WHERE id = ?", (approval_id,)
    ).fetchone()
    return _row_to_approval(row) if row else None


def resolve_approval(
    conn: sqlite3.Connection,
    approval_id: str,
    *,
    decision: str,
    note: str | None = None,
    resolved_by: str = "operator",
) -> Optional[dict[str, Any]]:
    """Resolve an approval. ``decision`` is ``approve`` or ``reject``. Dashboard-only."""
    status = {"approve": "approved", "reject": "rejected"}.get(decision)
    if status is None:
        raise ValueError("decision must be 'approve' or 'reject'")
    if not get_approval(conn, approval_id):
        return None
    conn.execute(
        "UPDATE surface_approvals SET status = ?, resolved_at = ?, resolved_by = ?, "
        "resolution_note = ? WHERE id = ?",
        (status, now_iso(), resolved_by, note, approval_id),
    )
    return get_approval(conn, approval_id)
