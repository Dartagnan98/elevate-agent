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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from elevate_cli.data._util import new_id, now_iso

TASK_STATUSES = {"pending", "in_progress", "blocked", "completed", "cancelled"}
TASK_PRIORITIES = {"urgent", "high", "normal", "low"}
APPROVAL_CATEGORIES = {
    "external-comms",
    "financial",
    "deployment",
    "data-deletion",
    "cost",
    "access",
    "other",
}
APPROVAL_STATUSES = {"pending", "approved", "rejected"}
_HUMAN_ACTORS = {"", "human", "human-web", "human:web", "operator", "dashboard", "system"}

_TASK_EDITABLE = {
    "title",
    "description",
    "type",
    "status",
    "priority",
    "assignee",
    "assigned_to",
    "project",
    "needs_approval",
    "needsApproval",
    "notes",
    "outputs",
    "created_by",
    "createdBy",
    "org",
    "kpi_key",
    "kpiKey",
    "due_date",
    "dueDate",
    "result",
    "archived",
}

_MISSING = object()
_DEPENDENCY_KEYS = {"blocked_by", "blockedBy", "blocks"}


# ─── tasks ─────────────────────────────────────────────────────────────



def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        return default


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            value = raw.split(",")
    if isinstance(value, dict):
        value = [value.get("id") or value.get("taskId") or value.get("task_id")]
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("id") or item.get("taskId") or item.get("task_id")
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _json_array(values: list[str]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _json_value(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return value
    return value


def _truthy_db(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, *, now: datetime) -> float | None:
    parsed = _parse_iso(value)
    if not parsed:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _normalize_agent_id(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    cleaned: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            cleaned.append(ch)
            last_dash = False
        elif not last_dash:
            cleaned.append("-")
            last_dash = True
    return "".join(cleaned).strip("-")


def _normalize_approval_category(value: Any) -> str:
    category = str(value or "other").strip().lower().replace("_", "-")
    aliases = {
        "external-send": "external-comms",
        "external-comms": "external-comms",
        "external-communications": "external-comms",
        "data-delete": "data-deletion",
        "data-deletion": "data-deletion",
        "delete": "data-deletion",
        "financial": "financial",
        "finance": "financial",
        "cost": "financial",
        "deployment": "deployment",
        "deploy": "deployment",
        "access": "other",
    }
    category = aliases.get(category, category)
    return category if category in APPROVAL_CATEGORIES else "other"


def _policy_agent_id(actor: str | None = None, agent_id: str | None = None) -> str:
    explicit = _normalize_agent_id(agent_id)
    if explicit:
        return explicit
    raw_actor = str(actor or "").strip()
    if raw_actor.startswith("agent:"):
        return _normalize_agent_id(raw_actor.split(":", 1)[1])
    normalized_actor = _normalize_agent_id(raw_actor)
    if normalized_actor in _HUMAN_ACTORS:
        return ""
    return normalized_actor


def _append_note(notes: str | None, addition: str) -> str:
    addition = addition.strip()
    if not addition:
        return notes or ""
    if not notes:
        return addition
    return f"{notes.rstrip()}\n\n{addition}"


def _task_policy_decision(
    conn: sqlite3.Connection,
    *,
    actor: str | None,
    actor_agent_id: str | None,
    action: str,
    category: str,
    title: str,
    assignee: str | None = None,
    resource: str | None = None,
) -> dict[str, Any] | None:
    agent_id = _policy_agent_id(actor=actor, agent_id=actor_agent_id)
    if not agent_id:
        return None
    from elevate_cli.agent_policy import evaluate_agent_policy

    decision = evaluate_agent_policy(
        agent_id,
        action=action,
        category=category,
        conn=conn,
        create_approval=True,
        surface=agent_id,
        description=(
            f"Agent {agent_id} requested {action.replace('_', ' ')} for "
            f"task '{title}'"
            + (f" assigned to {assignee}." if assignee else ".")
        ),
        actor=actor or agent_id,
        resource=resource or title,
    )
    if decision.get("decision") == "deny":
        raise ValueError(f"agent policy denied {action}: {decision.get('reason')}")
    return decision


def _policy_note(decision: dict[str, Any] | None) -> str:
    if not decision or decision.get("decision") != "approval_required":
        return ""
    approval = decision.get("approval") if isinstance(decision.get("approval"), dict) else {}
    approval_id = approval.get("id") or "pending approval"
    return (
        "Agent safety policy requires dashboard approval before this task action continues.\n"
        f"Approval: {approval_id}\n"
        f"Action: {decision.get('action')}\n"
        f"Agent: {decision.get('agentId')}"
    )


def record_task_event(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    event: str,
    actor: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
    payload: Any = None,
) -> dict[str, Any]:
    eid = new_id()
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO surface_task_events(
            id, task_id, event, actor, from_status, to_status, note,
            payload_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            eid,
            task_id,
            str(event or "event"),
            actor,
            from_status,
            to_status,
            note,
            json.dumps(payload, separators=(",", ":"), default=str) if payload is not None else None,
            ts,
        ),
    )
    return {
        "id": eid,
        "taskId": task_id,
        "event": str(event or "event"),
        "actor": actor,
        "from": from_status,
        "to": to_status,
        "note": note,
        "payload": payload,
        "createdAt": ts,
        "ts": ts,
    }


def read_task_audit(conn: sqlite3.Connection, task_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM surface_task_events
        WHERE task_id = ?
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (task_id, max(1, min(int(limit or 200), 500))),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_value(_row_get(row, "payload_json"), {})
        out.append(
            {
                "id": _row_get(row, "id"),
                "taskId": _row_get(row, "task_id"),
                "event": _row_get(row, "event"),
                "actor": _row_get(row, "actor"),
                "from": _row_get(row, "from_status"),
                "to": _row_get(row, "to_status"),
                "note": _row_get(row, "note"),
                "payload": payload if isinstance(payload, dict) else {},
                "createdAt": _row_get(row, "created_at"),
                "ts": _row_get(row, "created_at"),
            }
        )
    return out


def _mark_task_policy_blocked(
    conn: sqlite3.Connection,
    task_id: str,
    decision: dict[str, Any],
) -> dict[str, Any] | None:
    task = get_task(conn, task_id)
    if not task:
        return None
    next_status = "completed" if task.get("status") == "completed" else "blocked"
    conn.execute(
        """
        UPDATE surface_tasks
        SET status = ?, needs_approval = 1, notes = ?, updated_at = ?,
            completed_at = CASE WHEN ? = 'completed' THEN completed_at ELSE NULL END
        WHERE id = ?
        """,
        (
            next_status,
            _append_note(task.get("notes"), _policy_note(decision)),
            now_iso(),
            next_status,
            task_id,
        ),
    )
    blocked = get_task(conn, task_id)
    if blocked is not None:
        blocked["policyDecision"] = decision
    return blocked


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    outputs = _row_get(row, "outputs")
    try:
        outputs = json.loads(outputs) if outputs else []
    except Exception:
        outputs = []
    blocked_by = _json_list(_row_get(row, "blocked_by"))
    blocks = _json_list(_row_get(row, "blocks"))
    assignee = _row_get(row, "assignee")
    created_by = _row_get(row, "created_by")
    due_date = _row_get(row, "due_date")
    kpi_key = _row_get(row, "kpi_key")
    claimed_at = _row_get(row, "claimed_at")
    claim_owner = _row_get(row, "claim_owner")
    return {
        "id": _row_get(row, "id"),
        "title": _row_get(row, "title"),
        "description": _row_get(row, "description"),
        "type": _row_get(row, "type") or "agent",
        "status": _row_get(row, "status"),
        "priority": _row_get(row, "priority"),
        "assignee": assignee,
        "assigned_to": assignee,
        "project": _row_get(row, "project"),
        "needsApproval": bool(_row_get(row, "needs_approval")),
        "needs_approval": bool(_row_get(row, "needs_approval")),
        "createdBy": created_by,
        "created_by": created_by,
        "org": _row_get(row, "org"),
        "kpiKey": kpi_key,
        "kpi_key": kpi_key,
        "createdAt": _row_get(row, "created_at"),
        "created_at": _row_get(row, "created_at"),
        "updatedAt": _row_get(row, "updated_at"),
        "updated_at": _row_get(row, "updated_at"),
        "completedAt": _row_get(row, "completed_at"),
        "completed_at": _row_get(row, "completed_at"),
        "dueDate": due_date,
        "due_date": due_date,
        "archived": _truthy_db(_row_get(row, "archived")),
        "result": _row_get(row, "result"),
        "claimedAt": claimed_at,
        "claimed_at": claimed_at,
        "claimOwner": claim_owner,
        "claim_owner": claim_owner,
        "notes": _row_get(row, "notes"),
        "outputs": outputs,
        "blockedBy": blocked_by,
        "blocked_by": blocked_by,
        "blocks": blocks,
        "unresolvedDependencyIds": [],
    }


def _all_task_rows(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM surface_tasks ORDER BY created_at ASC").fetchall()
    return {str(_row_get(row, "id")): row for row in rows}


def _dependency_graph(rows: dict[str, sqlite3.Row]) -> dict[str, list[str]]:
    return {
        task_id: _json_list(_row_get(row, "blocked_by"))
        for task_id, row in rows.items()
    }


def _find_cycle(graph: dict[str, list[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str, path: list[str]) -> list[str]:
        if node in visiting:
            try:
                start = path.index(node)
            except ValueError:
                start = 0
            return path[start:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep not in graph:
                continue
            cycle = walk(dep, path + [dep])
            if cycle:
                return cycle
        visiting.remove(node)
        visited.add(node)
        return []

    for task_id in graph:
        cycle = walk(task_id, [task_id])
        if cycle:
            return cycle
    return []


def _unresolved_dependencies(
    graph: dict[str, list[str]],
    rows: dict[str, sqlite3.Row],
    task_id: str,
) -> list[str]:
    unresolved: list[str] = []
    for dep_id in graph.get(task_id, []):
        dep = rows.get(dep_id)
        if dep is None or _row_get(dep, "status") != "completed":
            unresolved.append(dep_id)
    return unresolved


def _apply_dependency_patch(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    blocked_by: Any = _MISSING,
    blocks: Any = _MISSING,
) -> None:
    rows = _all_task_rows(conn)
    if task_id not in rows:
        return
    old_graph = _dependency_graph(rows)
    graph = {key: list(values) for key, values in old_graph.items()}

    if blocked_by is not _MISSING:
        deps = _json_list(blocked_by)
        if task_id in deps:
            raise ValueError("a task cannot block itself")
        graph[task_id] = deps

    if blocks is not _MISSING:
        downstream = _json_list(blocks)
        if task_id in downstream:
            raise ValueError("a task cannot block itself")
        missing = [child_id for child_id in downstream if child_id not in rows]
        if missing:
            raise ValueError(f"blocked task does not exist: {', '.join(missing)}")
        downstream_set = set(downstream)
        for child_id, deps in list(graph.items()):
            if task_id in deps and child_id not in downstream_set:
                graph[child_id] = [dep for dep in deps if dep != task_id]
        for child_id in downstream:
            deps = graph.setdefault(child_id, [])
            if task_id not in deps:
                deps.append(task_id)

    cycle = _find_cycle(graph)
    if cycle:
        raise ValueError("dependency cycle: " + " -> ".join(cycle))

    reverse: dict[str, list[str]] = {key: [] for key in rows}
    for child_id, deps in graph.items():
        for dep_id in deps:
            if dep_id in reverse and child_id not in reverse[dep_id]:
                reverse[dep_id].append(child_id)

    ts = now_iso()
    for row_id, row in rows.items():
        old_deps = old_graph.get(row_id, [])
        next_deps = graph.get(row_id, [])
        old_blocks = _json_list(_row_get(row, "blocks"))
        next_blocks = reverse.get(row_id, [])
        current_status = str(_row_get(row, "status") or "pending")
        next_status = current_status
        next_unresolved = _unresolved_dependencies(graph, rows, row_id)
        if current_status != "completed" and next_unresolved:
            next_status = "blocked"
        elif current_status == "blocked" and graph.get(row_id) and not next_unresolved:
            next_status = "pending"

        sets: list[str] = []
        params: list[Any] = []
        if old_deps != next_deps:
            sets.append("blocked_by = ?")
            params.append(_json_array(next_deps))
        if old_blocks != next_blocks:
            sets.append("blocks = ?")
            params.append(_json_array(next_blocks))
        if next_status != current_status:
            sets.append("status = ?")
            params.append(next_status)
            if next_status != "completed":
                sets.append("completed_at = ?")
                params.append(None)
        if not sets:
            continue
        sets.append("updated_at = ?")
        params.append(ts)
        params.append(row_id)
        conn.execute(f"UPDATE surface_tasks SET {', '.join(sets)} WHERE id = ?", tuple(params))


def _enrich_task_dependencies(
    tasks: list[dict[str, Any]],
    rows: dict[str, sqlite3.Row] | None = None,
) -> list[dict[str, Any]]:
    if rows is None:
        return tasks
    graph = _dependency_graph(rows)
    for task in tasks:
        task_id = str(task.get("id") or "")
        unresolved = _unresolved_dependencies(graph, rows, task_id)
        task["unresolvedDependencyIds"] = unresolved
        task["unresolvedDependencies"] = [
            {
                "id": dep_id,
                "title": _row_get(rows[dep_id], "title") if dep_id in rows else None,
                "status": _row_get(rows[dep_id], "status") if dep_id in rows else "missing",
            }
            for dep_id in unresolved
        ]
    return tasks


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str | None = None,
    type: str = "agent",
    status: str = "pending",
    priority: str = "normal",
    assignee: str | None = None,
    project: str | None = None,
    needs_approval: bool = False,
    notes: str | None = None,
    created_by: str | None = None,
    org: str | None = None,
    kpi_key: str | None = None,
    due_date: str | None = None,
    result: str | None = None,
    blocked_by: Any = None,
    blocks: Any = None,
    actor: str = "human:web",
    actor_agent_id: str | None = None,
    policy_action: str = "create_task",
    policy_category: str = "task",
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ValueError("task title cannot be empty")
    if status not in TASK_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    if priority not in TASK_PRIORITIES:
        raise ValueError(f"invalid priority: {priority!r}")
    decision = _task_policy_decision(
        conn,
        actor=actor,
        actor_agent_id=actor_agent_id,
        action=policy_action,
        category=policy_category,
        title=title,
        assignee=assignee,
    )
    if decision and decision.get("decision") == "approval_required":
        status = "blocked" if status != "completed" else status
        needs_approval = True
        notes = _append_note(notes, _policy_note(decision))
    tid = new_id()
    ts = now_iso()
    creator = created_by or _policy_agent_id(actor=actor, agent_id=actor_agent_id) or actor
    conn.execute(
        "INSERT INTO surface_tasks(id, title, description, status, priority, assignee, "
        "project, needs_approval, created_at, updated_at, completed_at, notes, outputs, "
        "blocked_by, blocks, type, created_by, org, kpi_key, due_date, archived, result, "
        "claimed_at, claim_owner) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tid, title, description, status, priority, assignee, project,
            1 if needs_approval else 0, ts, ts, None, notes, json.dumps([]),
            _json_array([]), _json_array([]), str(type or "agent"), creator, org,
            kpi_key, due_date, 0, result, None, None,
        ),
    )
    if blocked_by is not None or blocks is not None:
        _apply_dependency_patch(
            conn,
            tid,
            blocked_by=blocked_by if blocked_by is not None else _MISSING,
            blocks=blocks if blocks is not None else _MISSING,
        )
    task = get_task(conn, tid)  # type: ignore[assignment]
    record_task_event(
        conn,
        tid,
        event="create",
        actor=actor,
        to_status=task.get("status") if isinstance(task, dict) else status,
        note=title,
        payload={"assignee": assignee, "priority": priority, "project": project},
    )
    if task is not None and decision:
        task["policyDecision"] = decision
    return task  # type: ignore[return-value]


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    project: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM surface_tasks"
    where: list[str] = []
    params: list[Any] = []
    if not include_archived:
        where.append("(archived IS NULL OR archived = 0)")
    if status:
        where.append("status = ?")
        params.append(status)
    if assignee:
        where.append("assignee = ?")
        params.append(assignee)
    if priority:
        where.append("priority = ?")
        params.append(priority)
    if project:
        where.append("project = ?")
        params.append(project)
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Oldest-first when a drain limit is set so a backed-up queue is worked
    # FIFO instead of newest-first starvation; newest-first otherwise (UI).
    if limit is not None and limit > 0:
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(int(limit))
    else:
        sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    all_rows = _all_task_rows(conn)
    return _enrich_task_dependencies([_row_to_task(r) for r in rows], all_rows)


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM surface_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    return _enrich_task_dependencies([_row_to_task(row)], _all_task_rows(conn))[0]


def reap_stale_in_progress(
    conn: sqlite3.Connection,
    *,
    max_age_seconds: int = 3600,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Reset crash-orphaned in_progress tasks back to pending.

    A surface heartbeat drains status=pending, PATCHes a task to
    in_progress, works it, then PATCHes to completed. If the agent dies
    in the middle, the task sits in_progress forever — the next run only
    queries pending, so nothing ever picks it up again. Any in_progress
    task that hasn't been touched in *max_age_seconds* is assumed
    orphaned and returned to the pending queue with an audit note.

    Returns the reaped tasks (post-reset). Safe to call on every list
    query — it's a no-op when nothing is stale.
    """
    current = now or datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT * FROM surface_tasks WHERE status = 'in_progress' "
        "AND (archived IS NULL OR archived = 0)"
    ).fetchall()
    reaped: list[dict[str, Any]] = []
    for row in rows:
        age = _age_seconds(_row_get(row, "updated_at"), now=current)
        if age is None or age <= max_age_seconds:
            continue
        task_id = _row_get(row, "id")
        note = _append_note(
            _row_get(row, "notes"),
            f"auto-reset to pending: in_progress untouched for {int(age // 60)}m "
            "(assignee likely crashed mid-task — verify partial work before redoing)",
        )
        ts = now_iso()
        conn.execute(
            "UPDATE surface_tasks SET status = 'pending', notes = ?, updated_at = ? WHERE id = ?",
            (note, ts, task_id),
        )
        record_task_event(
            conn,
            task_id,
            event="reaped",
            actor="system",
            from_status="in_progress",
            to_status="pending",
            note=f"stale in_progress ({int(age)}s old) auto-reset",
        )
        fresh = get_task(conn, task_id)
        if fresh:
            reaped.append(fresh)
    return reaped


def update_task(
    conn: sqlite3.Connection,
    task_id: str,
    patch: dict[str, Any],
    *,
    actor: str = "human:web",
    actor_agent_id: str | None = None,
    policy_action: str | None = None,
    policy_category: str | None = None,
) -> Optional[dict[str, Any]]:
    existing = get_task(conn, task_id)
    if not existing:
        return None
    action = policy_action or (
        "complete_task"
        if patch.get("status") == "completed"
        else "update_task"
    )
    category = policy_category or "task"
    decision = _task_policy_decision(
        conn,
        actor=actor,
        actor_agent_id=actor_agent_id,
        action=action,
        category=category,
        title=str(existing.get("title") or task_id),
        assignee=str(patch.get("assignee") or existing.get("assignee") or ""),
        resource=task_id,
    )
    if decision and decision.get("decision") == "approval_required":
        return _mark_task_policy_blocked(conn, task_id, decision)
    blocked_by = _MISSING
    blocks = _MISSING
    if "blockedBy" in patch:
        blocked_by = patch.get("blockedBy")
    if "blocked_by" in patch:
        blocked_by = patch.get("blocked_by")
    if "blocks" in patch:
        blocks = patch.get("blocks")
    sets: list[str] = []
    params: list[Any] = []
    for key, val in patch.items():
        if key in _DEPENDENCY_KEYS:
            continue
        if key not in _TASK_EDITABLE or val is None:
            continue
        db_key = {
            "assigned_to": "assignee",
            "needsApproval": "needs_approval",
            "createdBy": "created_by",
            "kpiKey": "kpi_key",
            "dueDate": "due_date",
        }.get(key, key)
        if key == "status" and val not in TASK_STATUSES:
            raise ValueError(f"invalid status: {val!r}")
        if key == "priority" and val not in TASK_PRIORITIES:
            raise ValueError(f"invalid priority: {val!r}")
        if db_key == "needs_approval":
            val = 1 if val else 0
        if db_key == "archived":
            val = 1 if val else 0
        if db_key == "outputs":
            val = json.dumps(val)
        sets.append(f"{db_key} = ?")
        params.append(val)
    if sets:
        ts = now_iso()
        sets.append("updated_at = ?")
        params.append(ts)
        # Stamp completed_at when transitioning to completed.
        if patch.get("status") == "completed":
            sets.append("completed_at = ?")
            params.append(ts)
        elif "status" in patch:
            sets.append("completed_at = ?")
            params.append(None)
        params.append(task_id)
        conn.execute(f"UPDATE surface_tasks SET {', '.join(sets)} WHERE id = ?", tuple(params))
        updated_status = str(patch.get("status") or existing.get("status") or "")
        record_task_event(
            conn,
            task_id,
            event="complete" if patch.get("status") == "completed" else "update",
            actor=actor,
            from_status=str(existing.get("status") or ""),
            to_status=updated_status,
            note=str(patch.get("notes") or patch.get("result") or ""),
            payload={k: v for k, v in patch.items() if k not in {"outputs"}},
        )
    if blocked_by is not _MISSING or blocks is not _MISSING or patch.get("status") is not None:
        _apply_dependency_patch(conn, task_id, blocked_by=blocked_by, blocks=blocks)
    task = get_task(conn, task_id)
    if task is not None and decision:
        task["policyDecision"] = decision
    return task


def claim_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    agent: str,
    actor: str | None = None,
) -> Optional[dict[str, Any]]:
    claimant = _normalize_agent_id(agent)
    if not claimant:
        raise ValueError("claim agent is required")
    existing = get_task(conn, task_id)
    if not existing:
        return None
    if existing.get("status") == "in_progress" and (
        _normalize_agent_id(existing.get("claimOwner")) == claimant
        or _normalize_agent_id(existing.get("assignee")) == claimant
    ):
        return existing
    unresolved = existing.get("unresolvedDependencyIds") or []
    if unresolved:
        raise ValueError(f"task {task_id} has unresolved dependencies: {', '.join(map(str, unresolved))}")
    if existing.get("status") != "pending":
        raise ValueError(f"task {task_id} is not pending (status={existing.get('status')}); cannot claim")
    now = now_iso()
    cur = conn.execute(
        """
        UPDATE surface_tasks
        SET status = 'in_progress', assignee = ?, claim_owner = ?,
            claimed_at = ?, updated_at = ?, completed_at = NULL
        WHERE id = ? AND status = 'pending' AND (claim_owner IS NULL OR claim_owner = '')
        """,
        (claimant, claimant, now, now, task_id),
    )
    if getattr(cur, "rowcount", 0) == 0:
        current = get_task(conn, task_id)
        if current and (
            _normalize_agent_id(current.get("claimOwner")) == claimant
            or (
                current.get("status") == "in_progress"
                and _normalize_agent_id(current.get("assignee")) == claimant
            )
        ):
            return current
        owner = current.get("claimOwner") or current.get("assignee") or "unknown" if current else "unknown"
        raise ValueError(f"task {task_id} already claimed by {owner}")
    record_task_event(
        conn,
        task_id,
        event="claim",
        actor=actor or f"agent:{claimant}",
        from_status=str(existing.get("status") or ""),
        to_status="in_progress",
        payload={"agent": claimant},
    )
    return get_task(conn, task_id)


def complete_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    result: str | None = None,
    outputs: Any = None,
    actor: str = "human:web",
    actor_agent_id: str | None = None,
    policy_category: str | None = None,
) -> Optional[dict[str, Any]]:
    patch: dict[str, Any] = {"status": "completed"}
    if result is not None:
        patch["result"] = result
    if outputs is not None:
        patch["outputs"] = outputs
    elif result:
        patch["outputs"] = [{"summary": result, "source": "surface_tasks"}]
    return update_task(
        conn,
        task_id,
        patch,
        actor=actor,
        actor_agent_id=actor_agent_id,
        policy_action="complete_task",
        policy_category=policy_category or "task",
    )


def delete_task(conn: sqlite3.Connection, task_id: str) -> bool:
    existing = get_task(conn, task_id)
    if existing:
        record_task_event(
            conn,
            task_id,
            event="delete",
            actor="human:web",
            from_status=str(existing.get("status") or ""),
            note=str(existing.get("title") or ""),
        )
        _apply_dependency_patch(conn, task_id, blocked_by=[], blocks=[])
    cur = conn.execute("DELETE FROM surface_tasks WHERE id = ?", (task_id,))
    return bool(getattr(cur, "rowcount", 0))


def request_delete_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    actor: str = "human:web",
    actor_agent_id: str | None = None,
) -> dict[str, Any]:
    existing = get_task(conn, task_id)
    if not existing:
        return {"ok": False, "task": None}
    decision = _task_policy_decision(
        conn,
        actor=actor,
        actor_agent_id=actor_agent_id,
        action="delete_task",
        category="data_deletion",
        title=str(existing.get("title") or task_id),
        assignee=str(existing.get("assignee") or ""),
        resource=task_id,
    )
    if decision and decision.get("decision") == "approval_required":
        task = _mark_task_policy_blocked(conn, task_id, decision)
        return {
            "ok": False,
            "approvalRequired": True,
            "approval": decision.get("approval"),
            "policyDecision": decision,
            "task": task,
        }
    return {"ok": delete_task(conn, task_id), "task": None}


def check_stale_tasks(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    stale_in_progress_seconds: int = 7200,
    stale_pending_seconds: int = 86400,
    stale_human_seconds: int = 86400,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    tasks = list_tasks(conn, include_archived=False)
    report: dict[str, Any] = {
        "stale_in_progress": [],
        "stale_pending": [],
        "stale_human": [],
        "overdue": [],
    }
    for task in tasks:
        status = str(task.get("status") or "")
        if status in {"completed", "cancelled"}:
            continue
        updated_age = _age_seconds(task.get("updatedAt"), now=current)
        created_age = _age_seconds(task.get("createdAt"), now=current)
        if status == "in_progress" and updated_age is not None and updated_age > stale_in_progress_seconds:
            report["stale_in_progress"].append(task)
        if status == "pending" and created_age is not None and created_age > stale_pending_seconds:
            report["stale_pending"].append(task)
        assignee = str(task.get("assignee") or "").strip().lower()
        project = str(task.get("project") or "").strip().lower()
        if (
            assignee in {"human", "user"}
            or project == "human-tasks"
        ) and created_age is not None and created_age > stale_human_seconds:
            report["stale_human"].append(task)
        due = _parse_iso(task.get("dueDate"))
        if due and due < current:
            report["overdue"].append(task)
    report["counts"] = {key: len(value) for key, value in report.items() if isinstance(value, list)}
    report["total"] = sum(report["counts"].values())
    return report


def check_human_tasks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return list(check_stale_tasks(conn).get("stale_human") or [])


def archive_tasks(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    older_than_days: int = 7,
    actor: str = "system",
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(older_than_days or 7)))
    archived: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for task in list_tasks(conn, status="completed", include_archived=True):
        if task.get("archived"):
            skipped.append({"id": task.get("id"), "reason": "already archived"})
            continue
        completed_at = _parse_iso(task.get("completedAt"))
        if not completed_at:
            skipped.append({"id": task.get("id"), "reason": "no completed_at timestamp"})
            continue
        if completed_at > cutoff:
            skipped.append({"id": task.get("id"), "reason": "completed_at within cutoff"})
            continue
        entry = {
            "id": task.get("id"),
            "title": task.get("title"),
            "assignee": task.get("assignee"),
            "completedAt": task.get("completedAt"),
        }
        if not dry_run:
            conn.execute(
                "UPDATE surface_tasks SET archived = 1, updated_at = ? WHERE id = ?",
                (now_iso(), task.get("id")),
            )
            record_task_event(
                conn,
                str(task.get("id")),
                event="archive",
                actor=actor,
                from_status="completed",
                to_status="completed",
                payload=entry,
            )
        archived.append(entry)
    return {"archived": len(archived), "items": archived, "skipped": skipped, "dry_run": dry_run}


def compact_tasks(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    older_than_days: int = 30,
    actor: str = "system",
) -> dict[str, Any]:
    tasks = list_tasks(conn, include_archived=True)
    by_id = {str(task.get("id")): task for task in tasks}
    still_needed: set[str] = set()
    stack: list[str] = []
    for task in tasks:
        if task.get("status") == "completed" or task.get("archived"):
            continue
        stack.extend([str(item) for item in task.get("blockedBy") or []])
    while stack:
        current = stack.pop()
        if current in still_needed:
            continue
        still_needed.add(current)
        parent = by_id.get(current)
        if parent:
            stack.extend([str(item) for item in parent.get("blockedBy") or []])

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(older_than_days or 30)))
    archived: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        if task.get("status") != "completed":
            continue
        if task.get("archived"):
            skipped.append({"id": task_id, "reason": "already archived"})
            continue
        completed_at = _parse_iso(task.get("completedAt"))
        if not completed_at:
            skipped.append({"id": task_id, "reason": "no completed_at timestamp"})
            continue
        if completed_at > cutoff:
            skipped.append({"id": task_id, "reason": "completed_at within cutoff"})
            continue
        if task_id in still_needed:
            skipped.append({"id": task_id, "reason": "still referenced by an open task's blocked_by chain"})
            continue
        archive_file = f"native-db:{completed_at.strftime('%Y-%m')}"
        entry = {
            "id": task_id,
            "archive_file": archive_file,
            "title": task.get("title"),
            "result": task.get("result") or "",
        }
        if not dry_run:
            conn.execute(
                "UPDATE surface_tasks SET archived = 1, updated_at = ? WHERE id = ?",
                (now_iso(), task_id),
            )
            record_task_event(
                conn,
                task_id,
                event="compact",
                actor=actor,
                from_status="completed",
                to_status="completed",
                payload=entry,
            )
        archived.append(entry)
    return {"archived": archived, "skipped": skipped, "dry_run": dry_run}


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
    category = _normalize_approval_category(category)
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
    approval_before = get_approval(conn, approval_id)
    if not approval_before:
        return None
    conn.execute(
        "UPDATE surface_approvals SET status = ?, resolved_at = ?, resolved_by = ?, "
        "resolution_note = ? WHERE id = ?",
        (status, now_iso(), resolved_by, note, approval_id),
    )
    try:
        task_rows = conn.execute(
            """
            SELECT * FROM surface_tasks
            WHERE needs_approval = 1
              AND (notes LIKE ? OR notes LIKE ?)
            """,
            (f"%Approval: {approval_id}%", f"%{approval_id}%"),
        ).fetchall()
    except Exception:
        task_rows = []
    for row in task_rows:
        task_id = str(_row_get(row, "id") or "")
        previous = str(_row_get(row, "status") or "")
        if not task_id:
            continue
        if status == "approved":
            next_status = "pending" if previous == "blocked" else previous
            conn.execute(
                """
                UPDATE surface_tasks
                SET status = ?, needs_approval = 0, updated_at = ?
                WHERE id = ?
                """,
                (next_status, now_iso(), task_id),
            )
            record_task_event(
                conn,
                task_id,
                event="approval_approved",
                actor=resolved_by,
                from_status=previous,
                to_status=next_status,
                note=note,
                payload={"approvalId": approval_id},
            )
        else:
            conn.execute(
                "UPDATE surface_tasks SET status = 'blocked', updated_at = ? WHERE id = ?",
                (now_iso(), task_id),
            )
            record_task_event(
                conn,
                task_id,
                event="approval_rejected",
                actor=resolved_by,
                from_status=previous,
                to_status="blocked",
                note=note,
                payload={"approvalId": approval_id},
            )
    return get_approval(conn, approval_id)
