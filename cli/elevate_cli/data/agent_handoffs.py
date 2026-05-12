"""Durable visible-agent handoff bus.

This is the product-level counterpart to in-process delegation metadata:
rows live in ``operational.db``, can be shown in Agent Hub, and can be
drained into one-shot cron jobs that speak as the receiving agent.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.data._util import new_id, now_iso


_VALID_STATUSES = {
    "queued",
    "running",
    "waiting_human",
    "completed",
    "failed",
    "cancelled",
}
_OPEN_STATUSES = {"queued", "running", "waiting_human"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
_VALID_MESSAGE_KINDS = {"request", "note", "status", "result", "human_prompt", "error"}
_DEFAULT_STALE_RUNNING_MINUTES = 120


def _normalize_agent_id(value: Any) -> str:
    try:
        from gateway.agent_lanes import normalize_agent_id

        return normalize_agent_id(value)
    except Exception:
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
        return "".join(cleaned).strip("-") or "executive-assistant"


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _json_loads(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "handoffId": row["handoff_id"],
        "fromAgentId": row["from_agent_id"],
        "toAgentId": row["to_agent_id"],
        "kind": row["kind"],
        "content": row["content"],
        "payload": _json_loads(row["payload_json"]),
        "createdAt": row["created_at"],
    }


def _row_to_handoff(row: sqlite3.Row, *, messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "fromAgentId": row["from_agent_id"],
        "toAgentId": row["to_agent_id"],
        "title": row["title"],
        "task": row["task"],
        "status": row["status"],
        "priority": row["priority"],
        "dealId": row["deal_id"],
        "profileId": row["profile_id"],
        "contactId": row["contact_id"],
        "conversationId": row["conversation_id"],
        "sourceRunId": row["source_run_id"],
        "parentHandoffId": row["parent_handoff_id"],
        "cronJobId": row["cron_job_id"],
        "idempotencyKey": row["idempotency_key"],
        "resultIdempotencyKey": row["result_idempotency_key"],
        "payload": _json_loads(row["payload_json"]),
        "result": _json_loads(row["result_json"]),
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "claimedAt": row["claimed_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
        "messages": messages,
    }


def _priority_order_sql() -> str:
    return "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END"


def _present(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _result_has_human_approval(handoff: Mapping[str, Any]) -> bool:
    result = handoff.get("result")
    if not isinstance(result, Mapping):
        return False
    decision = result.get("decision")
    return isinstance(decision, Mapping) and decision.get("approved") is True


def _dependency_specs(handoff: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payload = handoff.get("payload")
    if not isinstance(payload, Mapping):
        return []
    raw = (
        payload.get("requires")
        or payload.get("dependencies")
        or payload.get("requiredDependencies")
        or []
    )
    if isinstance(raw, Mapping):
        raw = raw.get("items") or [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _dependency_blocks(conn: sqlite3.Connection, handoff: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return unmet dependency descriptors for a queued handoff.

    The payload contract intentionally stays small and provider-neutral:
    ``requires`` can include deal fields, checklist cells, attachments, or
    Admin setup items. Missing requirements pause the handoff before cron so
    specialist agents do not launch without the context they need.
    """
    if _result_has_human_approval(handoff):
        return []
    specs = _dependency_specs(handoff)
    if not specs:
        return []
    blocks: list[dict[str, Any]] = []
    deal = None
    deal_id = handoff.get("dealId")
    if deal_id:
        try:
            from elevate_cli.data.deals import get_deal

            deal = get_deal(conn, str(deal_id))
        except Exception:
            deal = None
    for spec in specs:
        dep_type = str(spec.get("type") or spec.get("kind") or "").strip().lower()
        label = str(spec.get("label") or spec.get("title") or dep_type or "Dependency").strip()
        if dep_type in {"deal_field", "field"}:
            field = str(spec.get("field") or spec.get("key") or "").strip()
            if not field:
                continue
            aliases = [field, _snake_to_camel(field)]
            if deal is None or not any(_present(deal.get(alias)) for alias in aliases):
                blocks.append({"type": "deal_field", "field": field, "label": label})
        elif dep_type in {"checklist", "checklist_item"}:
            key = str(spec.get("id") or spec.get("key") or spec.get("field") or "").strip()
            checklist = (deal or {}).get("extraToggles") if isinstance(deal, Mapping) else {}
            if not key or not isinstance(checklist, Mapping) or checklist.get(key) is not True:
                blocks.append({"type": "checklist", "id": key, "label": label})
        elif dep_type in {"attachment", "document", "artifact"}:
            kind = str(spec.get("kind") or spec.get("attachmentKind") or spec.get("docKind") or "").strip()
            if not deal_id:
                blocks.append({"type": "attachment", "kind": kind, "label": label})
                continue
            try:
                from elevate_cli.data.deals import list_deal_attachments

                attachments = list_deal_attachments(conn, str(deal_id), kind=kind or None, limit=1)
            except Exception:
                attachments = []
            if not attachments:
                blocks.append({"type": "attachment", "kind": kind, "label": label})
        elif dep_type in {"admin_setup", "setup_item", "provider"}:
            key = str(spec.get("key") or spec.get("provider") or "").strip()
            if not key:
                continue
            row = conn.execute(
                "SELECT status, provider FROM admin_setup_items WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None or row["status"] not in {"configured", "connected", "manual"}:
                blocks.append({"type": "admin_setup", "key": key, "label": label})
    return blocks


def _record_deal_handoff_event(
    conn: sqlite3.Connection,
    handoff: Mapping[str, Any],
    *,
    actor: str,
    event: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    deal_id = handoff.get("dealId")
    if not deal_id:
        return
    try:
        from elevate_cli.data.deals import _insert_deal_event

        _insert_deal_event(
            conn,
            deal_id=str(deal_id),
            kind="run_result",
            actor=actor,
            payload={
                "source": "agent_handoff",
                "event": event,
                "handoffId": handoff.get("id"),
                "fromAgentId": handoff.get("fromAgentId"),
                "toAgentId": handoff.get("toAgentId"),
                "status": handoff.get("status"),
                **(dict(payload) if payload else {}),
            },
        )
    except Exception:
        # Deal timeline fan-out should never make the handoff bus unusable.
        return


def _pause_for_dependency_blocks(
    conn: sqlite3.Connection,
    handoff: Mapping[str, Any],
    *,
    actor: str,
) -> dict[str, Any] | None:
    blocks = _dependency_blocks(conn, handoff)
    if not blocks:
        return None
    now = now_iso()
    prompt = {
        "title": f"Resolve blocked handoff: {handoff.get('title')}",
        "message": "This handoff is waiting for required context before the receiving agent can run.",
        "handoffId": handoff.get("id"),
        "missing": blocks,
    }
    result = {
        "blockedBy": blocks,
        "humanPrompt": prompt,
        "blockedAt": now,
    }
    conn.execute(
        """
        UPDATE agent_handoffs
        SET status = 'waiting_human', result_json = ?, error_message = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            _json_dumps(result),
            "Dependency gate blocked handoff",
            now,
            handoff["id"],
        ),
    )
    record_agent_handoff_message(
        conn,
        str(handoff["id"]),
        from_agent_id="system",
        to_agent_id=handoff.get("fromAgentId"),
        kind="human_prompt",
        content=prompt["message"],
        payload=prompt,
    )
    updated = get_agent_handoff(conn, str(handoff["id"]), include_messages=False)
    if updated:
        _record_deal_handoff_event(
            conn,
            updated,
            actor=actor,
            event="dependency_blocked",
            payload={"missing": blocks},
        )
    return updated


def get_agent_handoff(
    conn: sqlite3.Connection,
    handoff_id: str,
    *,
    include_messages: bool = True,
) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM agent_handoffs WHERE id = ?", (handoff_id,)).fetchone()
    if not row:
        return None
    messages = None
    if include_messages:
        messages = [
            _row_to_message(msg)
            for msg in conn.execute(
                """
                SELECT * FROM agent_handoff_messages
                WHERE handoff_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (handoff_id,),
            ).fetchall()
        ]
    return _row_to_handoff(row, messages=messages)


def list_agent_handoffs(
    conn: sqlite3.Connection,
    *,
    to_agent_id: str | None = None,
    from_agent_id: str | None = None,
    status: str | None = None,
    deal_id: str | None = None,
    profile_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM agent_handoffs WHERE 1=1"
    params: list[Any] = []
    if to_agent_id:
        sql += " AND to_agent_id = ?"
        params.append(_normalize_agent_id(to_agent_id))
    if from_agent_id:
        sql += " AND from_agent_id = ?"
        params.append(_normalize_agent_id(from_agent_id))
    if status:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid handoff status {status!r}")
        sql += " AND status = ?"
        params.append(status)
    if deal_id:
        sql += " AND deal_id = ?"
        params.append(deal_id)
    if profile_id:
        sql += " AND profile_id = ?"
        params.append(profile_id)
    sql += f" ORDER BY {_priority_order_sql()} ASC, created_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit or 100), 500)), max(0, int(offset or 0))])
    return [_row_to_handoff(row) for row in conn.execute(sql, params).fetchall()]


def record_agent_handoff_message(
    conn: sqlite3.Connection,
    handoff_id: str,
    *,
    from_agent_id: str,
    to_agent_id: str | None = None,
    kind: str = "note",
    content: str = "",
    payload: Any = None,
) -> dict[str, Any]:
    if kind not in _VALID_MESSAGE_KINDS:
        raise ValueError(f"invalid handoff message kind {kind!r}")
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if not handoff:
        raise LookupError(f"handoff {handoff_id!r} not found")
    now = now_iso()
    mid = new_id()
    conn.execute(
        """
        INSERT INTO agent_handoff_messages(
            id, handoff_id, from_agent_id, to_agent_id, kind, content,
            payload_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            mid,
            handoff_id,
            _normalize_agent_id(from_agent_id),
            _normalize_agent_id(to_agent_id) if to_agent_id else None,
            kind,
            str(content or ""),
            _json_dumps(payload),
            now,
        ),
    )
    conn.execute(
        "UPDATE agent_handoffs SET updated_at = ? WHERE id = ?",
        (now, handoff_id),
    )
    row = conn.execute(
        "SELECT * FROM agent_handoff_messages WHERE id = ?",
        (mid,),
    ).fetchone()
    return _row_to_message(row)


def create_agent_handoff(
    conn: sqlite3.Connection,
    *,
    from_agent_id: str,
    to_agent_id: str,
    task: str,
    title: str | None = None,
    priority: str = "normal",
    deal_id: str | None = None,
    profile_id: str | None = None,
    contact_id: str | None = None,
    conversation_id: str | None = None,
    source_run_id: str | None = None,
    parent_handoff_id: str | None = None,
    payload: Any = None,
    idempotency_key: str | None = None,
    create_cron_job: bool = False,
    actor: str = "system",
) -> dict[str, Any]:
    from_id = _normalize_agent_id(from_agent_id)
    to_id = _normalize_agent_id(to_agent_id)
    if from_id == to_id:
        raise ValueError("agent handoff requires two different agents")
    clean_task = str(task or "").strip()
    if not clean_task:
        raise ValueError("agent handoff task is required")
    clean_priority = str(priority or "normal").strip().lower()
    if clean_priority not in _VALID_PRIORITIES:
        raise ValueError(f"invalid handoff priority {priority!r}")
    clean_key = str(idempotency_key or "").strip() or None
    if clean_key:
        existing = conn.execute(
            """
            SELECT * FROM agent_handoffs
            WHERE from_agent_id = ? AND to_agent_id = ? AND idempotency_key = ?
            """,
            (from_id, to_id, clean_key),
        ).fetchone()
        if existing:
            existing_handoff = _row_to_handoff(existing)
            if create_cron_job and existing_handoff["status"] == "queued":
                return dispatch_agent_handoff_to_cron(conn, existing_handoff["id"], actor=actor)
            return existing_handoff

    now = now_iso()
    handoff_id = new_id()
    clean_title = str(title or "").strip() or clean_task.splitlines()[0][:90]
    conn.execute(
        """
        INSERT INTO agent_handoffs(
            id, from_agent_id, to_agent_id, title, task, status, priority,
            deal_id, profile_id, contact_id, conversation_id, source_run_id,
            parent_handoff_id, idempotency_key, payload_json,
            created_at, updated_at
        ) VALUES (?,?,?,?,?, 'queued', ?, ?,?,?,?,?,?,?,?,?,?)
        """,
        (
            handoff_id,
            from_id,
            to_id,
            clean_title,
            clean_task,
            clean_priority,
            deal_id,
            profile_id,
            contact_id,
            conversation_id,
            source_run_id,
            parent_handoff_id,
            clean_key,
            _json_dumps(payload),
            now,
            now,
        ),
    )
    record_agent_handoff_message(
        conn,
        handoff_id,
        from_agent_id=from_id,
        to_agent_id=to_id,
        kind="request",
        content=clean_task,
        payload={"actor": actor, "title": clean_title, "priority": clean_priority, "payload": payload},
    )
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if handoff:
        _record_deal_handoff_event(
            conn,
            handoff,
            actor=actor,
            event="created",
            payload={"priority": clean_priority},
        )
        blocked = _pause_for_dependency_blocks(conn, handoff, actor=actor)
        if blocked:
            return blocked
    if create_cron_job:
        return dispatch_agent_handoff_to_cron(conn, handoff_id, actor=actor)
    return handoff  # type: ignore[return-value]


def _agent_skill_names(agent_id: str) -> list[str]:
    try:
        from elevate_cli.agent_hub import _load_agent_defs
        from elevate_cli.config import load_config

        config = load_config()
        normalized = _normalize_agent_id(agent_id)
        for agent in _load_agent_defs(config):
            if _normalize_agent_id(agent.get("id")) == normalized:
                skills = agent.get("skills") if isinstance(agent, Mapping) else []
                if isinstance(skills, str):
                    return [skills]
                if isinstance(skills, (list, tuple, set)):
                    return [str(skill).strip() for skill in skills if str(skill or "").strip()]
    except Exception:
        return []
    return []


def _handoff_prompt(handoff: Mapping[str, Any]) -> str:
    payload = handoff.get("payload")
    prompt_lines = [
        f"Visible agent handoff: {handoff.get('title')}",
        f"Handoff ID: {handoff.get('id')}",
        f"From agent: {handoff.get('fromAgentId')}",
        f"To agent: {handoff.get('toAgentId')}",
        f"Priority: {handoff.get('priority')}",
        "",
        "Task:",
        str(handoff.get("task") or ""),
        "",
        "Handoff rules:",
        "- You are the receiving specialist agent for this handoff.",
        "- Work only the requested task, then write back to the handoff bus with the agent_handoff tool.",
        "- If the task needs human confirmation, mark the handoff waiting_human and include a concise human prompt.",
        "- If you attach, draft, or modify deal work, use the deal-specific result writer or data helper the workflow requires.",
        "- Do not message the human directly with send_message. Cron delivery sends your final summary to your agent Telegram lane.",
        "- If there is nothing useful to report, still update the handoff bus and respond exactly [SILENT].",
        "",
        "Completion contract:",
        "Use agent_handoff with action='complete' and this handoff_id.",
        "Use action='message' for intermediate notes or action='create' only when handing work to another agent.",
    ]
    context = {
        "dealId": handoff.get("dealId"),
        "profileId": handoff.get("profileId"),
        "contactId": handoff.get("contactId"),
        "conversationId": handoff.get("conversationId"),
        "sourceRunId": handoff.get("sourceRunId"),
        "payload": payload,
    }
    prompt_lines.extend(["", "Source-of-truth context:", json.dumps(context, indent=2, default=str)])
    return "\n".join(prompt_lines)


def dispatch_agent_handoff_to_cron(
    conn: sqlite3.Connection,
    handoff_id: str,
    *,
    actor: str = "system",
) -> dict[str, Any]:
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if not handoff:
        raise LookupError(f"handoff {handoff_id!r} not found")
    if handoff["status"] != "queued":
        return handoff
    blocked = _pause_for_dependency_blocks(conn, handoff, actor=actor)
    if blocked:
        return blocked

    to_agent_id = _normalize_agent_id(handoff["toAgentId"])
    try:
        from cron import jobs as cron_jobs
        from gateway.agent_lanes import (
            agent_telegram_delivery_target,
            agent_telegram_lane_ready,
        )

        delivery_target = agent_telegram_delivery_target(to_agent_id, default="")
        if not agent_telegram_lane_ready(to_agent_id) or not delivery_target:
            now = now_iso()
            prompt = {
                "title": f"Configure Telegram lane for {to_agent_id}",
                "message": "This handoff is waiting because the receiving agent does not have its own Telegram bot token and lane configured.",
                "handoffId": handoff["id"],
                "missing": [
                    {
                        "type": "telegram_lane",
                        "agentId": to_agent_id,
                        "label": "Agent Telegram bot token and chat/topic target",
                    }
                ],
            }
            result = {
                "blockedBy": prompt["missing"],
                "humanPrompt": prompt,
                "blockedAt": now,
            }
            conn.execute(
                """
                UPDATE agent_handoffs
                SET status = 'waiting_human', result_json = ?, error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _json_dumps(result),
                    "Agent Telegram lane is not configured",
                    now,
                    handoff_id,
                ),
            )
            record_agent_handoff_message(
                conn,
                handoff_id,
                from_agent_id="system",
                to_agent_id=handoff.get("fromAgentId"),
                kind="human_prompt",
                content=prompt["message"],
                payload=prompt,
            )
            updated = get_agent_handoff(conn, handoff_id, include_messages=False)
            if updated:
                _record_deal_handoff_event(
                    conn,
                    updated,
                    actor=actor,
                    event="telegram_lane_blocked",
                    payload={"missing": prompt["missing"]},
                )
            return updated  # type: ignore[return-value]

        job = cron_jobs.create_job(
            prompt=_handoff_prompt(handoff),
            schedule=now_iso(),
            name=f"handoff:{to_agent_id}:{handoff['id'][:8]}",
            repeat=1,
            deliver=delivery_target,
            skills=_agent_skill_names(to_agent_id),
            agent=to_agent_id,
            origin={
                "source": "agent_handoff",
                "actor": actor,
                "agent": to_agent_id,
                "from_agent_id": handoff["fromAgentId"],
                "to_agent_id": to_agent_id,
                "handoff_id": handoff["id"],
                "deal_id": handoff.get("dealId"),
                "profile_id": handoff.get("profileId"),
                "telegram_lane": f"{to_agent_id}-agent",
            },
        )
        cron_job_id = job.get("id") if isinstance(job, dict) else None
    except Exception as exc:
        now = now_iso()
        conn.execute(
            """
            UPDATE agent_handoffs
            SET status = 'failed', error_message = ?, updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (str(exc), now, now, handoff_id),
        )
        record_agent_handoff_message(
            conn,
            handoff_id,
            from_agent_id="system",
            to_agent_id=to_agent_id,
            kind="error",
            content=f"Failed to launch handoff cron job: {exc}",
        )
        return get_agent_handoff(conn, handoff_id, include_messages=False)  # type: ignore[return-value]

    now = now_iso()
    conn.execute(
        """
        UPDATE agent_handoffs
        SET status = 'running', cron_job_id = ?, claimed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (cron_job_id, now, now, handoff_id),
    )
    record_agent_handoff_message(
        conn,
        handoff_id,
        from_agent_id="system",
        to_agent_id=to_agent_id,
        kind="status",
        content=f"Dispatched to {to_agent_id} cron job {cron_job_id or 'unknown'}.",
    )
    return get_agent_handoff(conn, handoff_id, include_messages=False)  # type: ignore[return-value]


def drain_queued_agent_handoffs(
    conn: sqlite3.Connection,
    *,
    to_agent_id: str | None = None,
    limit: int = 50,
    actor: str = "system",
) -> list[dict[str, Any]]:
    items = list_agent_handoffs(
        conn,
        to_agent_id=to_agent_id,
        status="queued",
        limit=limit,
    )
    return [dispatch_agent_handoff_to_cron(conn, item["id"], actor=actor) for item in items]


def approve_agent_handoff(
    conn: sqlite3.Connection,
    handoff_id: str,
    *,
    approved: bool = True,
    run_now: bool = True,
    actor: str = "human",
) -> dict[str, Any]:
    """Approve or cancel a handoff that is waiting on a human decision."""
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if not handoff:
        raise LookupError(f"handoff {handoff_id!r} not found")
    if handoff["status"] != "waiting_human":
        raise ValueError("only waiting_human handoffs can be approved")
    now = now_iso()
    prior_result = handoff.get("result") if isinstance(handoff.get("result"), Mapping) else {}
    decision = {
        "approved": bool(approved),
        "actor": actor,
        "decidedAt": now,
    }
    result = {**dict(prior_result or {}), "decision": decision}
    if not approved:
        conn.execute(
            """
            UPDATE agent_handoffs
            SET status = 'cancelled', result_json = ?, updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (_json_dumps(result), now, now, handoff_id),
        )
        record_agent_handoff_message(
            conn,
            handoff_id,
            from_agent_id=actor,
            to_agent_id=handoff.get("toAgentId"),
            kind="result",
            content="Handoff was not approved and has been cancelled.",
            payload={"decision": decision},
        )
        updated = get_agent_handoff(conn, handoff_id, include_messages=True)
        if updated:
            _record_deal_handoff_event(
                conn,
                updated,
                actor=actor,
                event="approval_cancelled",
                payload={"decision": decision},
            )
        return updated  # type: ignore[return-value]

    conn.execute(
        """
        UPDATE agent_handoffs
        SET status = 'queued', result_json = ?, error_message = NULL,
            updated_at = ?, completed_at = NULL
        WHERE id = ?
        """,
        (_json_dumps(result), now, handoff_id),
    )
    record_agent_handoff_message(
        conn,
        handoff_id,
        from_agent_id=actor,
        to_agent_id=handoff.get("toAgentId"),
        kind="status",
        content="Handoff approved and queued to resume.",
        payload={"decision": decision, "runNow": bool(run_now)},
    )
    queued = get_agent_handoff(conn, handoff_id, include_messages=False)
    if queued:
        _record_deal_handoff_event(
            conn,
            queued,
            actor=actor,
            event="approval_granted",
            payload={"decision": decision},
        )
    if run_now:
        return dispatch_agent_handoff_to_cron(conn, handoff_id, actor=actor)
    return get_agent_handoff(conn, handoff_id, include_messages=True)  # type: ignore[return-value]


def record_agent_handoff_result(
    conn: sqlite3.Connection,
    handoff_id: str,
    *,
    status: str = "completed",
    result: Any = None,
    error_message: str | None = None,
    human_prompt: Any = None,
    idempotency_key: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    if status not in _VALID_STATUSES - {"queued"}:
        raise ValueError(f"invalid result handoff status {status!r}")
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if not handoff:
        raise LookupError(f"handoff {handoff_id!r} not found")
    clean_key = str(idempotency_key or "").strip() or None
    prior_key = handoff.get("resultIdempotencyKey")
    if prior_key:
        if clean_key and prior_key == clean_key:
            return handoff
        raise ValueError("agent handoff result has already been recorded")
    if handoff.get("status") in _TERMINAL_STATUSES:
        raise ValueError("agent handoff result has already been recorded")

    now = now_iso()
    completed_at = now if status in _TERMINAL_STATUSES else None
    payload = result
    if human_prompt is not None:
        payload = {"result": result, "humanPrompt": human_prompt}
    conn.execute(
        """
        UPDATE agent_handoffs
        SET status = ?, result_json = ?, result_idempotency_key = ?,
            error_message = ?, updated_at = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            status,
            _json_dumps(payload),
            clean_key,
            error_message,
            now,
            completed_at,
            handoff_id,
        ),
    )
    kind = "error" if status == "failed" else "human_prompt" if status == "waiting_human" else "result"
    content = error_message or ""
    if not content and isinstance(result, Mapping):
        content = str(result.get("summary") or result.get("message") or "")
    if not content:
        content = f"Handoff marked {status}."
    record_agent_handoff_message(
        conn,
        handoff_id,
        from_agent_id=actor,
        to_agent_id=handoff.get("fromAgentId"),
        kind=kind,
        content=content,
        payload={"result": result, "humanPrompt": human_prompt, "status": status},
    )
    updated = get_agent_handoff(conn, handoff_id, include_messages=True)
    if updated:
        _record_deal_handoff_event(
            conn,
            updated,
            actor=actor,
            event="result",
            payload={
                "resultStatus": status,
                "humanPrompt": human_prompt,
                "error": error_message,
            },
        )
        if (
            updated.get("toAgentId") != "executive-assistant"
            and updated.get("fromAgentId") != "executive-assistant"
        ):
            record_agent_handoff_message(
                conn,
                handoff_id,
                from_agent_id=actor,
                to_agent_id="executive-assistant",
                kind="status",
                content=f"{updated.get('toAgentId')} finished handoff for {updated.get('fromAgentId')} with status {status}.",
                payload={
                    "handoffId": handoff_id,
                    "status": status,
                    "result": result,
                    "humanPrompt": human_prompt,
                },
            )
        next_handoffs = []
        if isinstance(result, Mapping):
            raw_next = result.get("nextHandoffs") or result.get("next_handoffs") or []
            if isinstance(raw_next, (list, tuple)):
                next_handoffs = [item for item in raw_next if isinstance(item, Mapping)]
        for item in next_handoffs:
            to_agent = str(item.get("toAgentId") or item.get("to_agent_id") or "").strip()
            task = str(item.get("task") or "").strip()
            if not to_agent or not task:
                continue
            create_agent_handoff(
                conn,
                from_agent_id=str(updated.get("toAgentId") or actor),
                to_agent_id=to_agent,
                title=item.get("title"),
                task=task,
                priority=str(item.get("priority") or "normal"),
                deal_id=item.get("dealId") or item.get("deal_id") or updated.get("dealId"),
                profile_id=item.get("profileId") or item.get("profile_id") or updated.get("profileId"),
                contact_id=item.get("contactId") or item.get("contact_id") or updated.get("contactId"),
                conversation_id=item.get("conversationId") or item.get("conversation_id") or updated.get("conversationId"),
                source_run_id=item.get("sourceRunId") or item.get("source_run_id") or updated.get("sourceRunId"),
                parent_handoff_id=handoff_id,
                payload=item.get("payload"),
                idempotency_key=item.get("idempotencyKey") or item.get("idempotency_key"),
                create_cron_job=bool(item.get("runNow") or item.get("run_now")),
                actor=actor,
            )
        if next_handoffs:
            updated = get_agent_handoff(conn, handoff_id, include_messages=True)
    return updated  # type: ignore[return-value]


def mark_stale_agent_handoffs(
    conn: sqlite3.Connection,
    *,
    max_running_minutes: int = _DEFAULT_STALE_RUNNING_MINUTES,
    actor: str = "agent-worker",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fail running handoffs that have not written back in time."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, int(max_running_minutes)))).isoformat()
    rows = conn.execute(
        """
        SELECT id FROM agent_handoffs
        WHERE status = 'running'
          AND claimed_at IS NOT NULL
          AND claimed_at < ?
        ORDER BY claimed_at ASC
        LIMIT ?
        """,
        (cutoff, max(1, min(int(limit or 100), 500))),
    ).fetchall()
    recovered: list[dict[str, Any]] = []
    for row in rows:
        recovered.append(
            record_agent_handoff_result(
                conn,
                row["id"],
                status="failed",
                error_message=f"Handoff exceeded {max_running_minutes} minute running timeout.",
                result={"reason": "stale_running_timeout", "cutoff": cutoff},
                actor=actor,
            )
        )
    return recovered


def agent_handoff_summary(conn: sqlite3.Connection, *, limit: int = 8) -> dict[str, Any]:
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM agent_handoffs GROUP BY status"
    ).fetchall()
    counts = {row["status"]: int(row["count"] or 0) for row in status_rows}
    by_agent_rows = conn.execute(
        """
        SELECT to_agent_id,
               COUNT(*) AS total,
               SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued,
               SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
               SUM(CASE WHEN status = 'waiting_human' THEN 1 ELSE 0 END) AS waiting_human,
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
        FROM agent_handoffs
        GROUP BY to_agent_id
        ORDER BY (queued + running + waiting_human) DESC, total DESC, to_agent_id ASC
        """
    ).fetchall()
    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "waitingHuman": counts.get("waiting_human", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
        "open": sum(counts.get(status, 0) for status in _OPEN_STATUSES),
        "byAgent": [
            {
                "agentId": row["to_agent_id"],
                "total": int(row["total"] or 0),
                "queued": int(row["queued"] or 0),
                "running": int(row["running"] or 0),
                "waitingHuman": int(row["waiting_human"] or 0),
                "completed": int(row["completed"] or 0),
                "failed": int(row["failed"] or 0),
            }
            for row in by_agent_rows
        ],
        "recent": list_agent_handoffs(conn, limit=limit),
        "error": "",
    }
