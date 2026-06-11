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


def _agent_def(agent_id: str) -> Mapping[str, Any]:
    try:
        from elevate_cli.agent_hub import get_agent_def

        agent = get_agent_def(_normalize_agent_id(agent_id))
        return agent if isinstance(agent, Mapping) else {}
    except Exception:
        return {}


def _agent_routing(agent_id: str) -> Mapping[str, Any]:
    agent = _agent_def(agent_id)
    routing = agent.get("routing") if isinstance(agent.get("routing"), Mapping) else {}
    return routing if isinstance(routing, Mapping) else {}


def _agent_safety(agent_id: str) -> Mapping[str, Any]:
    agent = _agent_def(agent_id)
    safety = agent.get("safety") if isinstance(agent.get("safety"), Mapping) else {}
    return safety if isinstance(safety, Mapping) else {}


def _agent_runtime(agent_id: str) -> Mapping[str, Any]:
    agent = _agent_def(agent_id)
    runtime = agent.get("runtime") if isinstance(agent.get("runtime"), Mapping) else {}
    return runtime if isinstance(runtime, Mapping) else {}


def _agent_memory(agent_id: str) -> Mapping[str, Any]:
    agent = _agent_def(agent_id)
    memory = agent.get("memory") if isinstance(agent.get("memory"), Mapping) else {}
    return memory if isinstance(memory, Mapping) else {}


def _agent_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


_TOOLSET_LIKE_SKILL_NAMES = {
    "agent-bus",
    "agent_bus",
    "agent-handoff",
    "agent_handoff",
    "approvals",
    "comms",
    "memory",
    "tasks",
}

_SKILL_TO_TOOLSET_ALIASES = {
    "agent-bus": "agent_bus",
    "agent_bus": "agent_bus",
    "agent-handoff": "agent_handoff",
    "agent_handoff": "agent_handoff",
    "memory": "memory",
    "tasks": "todo",
}

_ADMIN_NATIVE_TOOLSETS = [
    "agent_bus",
    "agent_handoff",
    "memory",
    "deals_overview",
    "elevate_db",
    "admin_deal",
]


def _append_unique(items: list[str], names: list[str]) -> list[str]:
    seen = {item for item in items}
    for name in names:
        clean = str(name or "").strip()
        if clean and clean not in seen:
            items.append(clean)
            seen.add(clean)
    return items


def _agent_handoff_targets(agent_id: str) -> list[str]:
    return [_normalize_agent_id(item) for item in _agent_list(_agent_routing(agent_id).get("handoff_targets"))]


def _agent_default_priority(agent_id: str) -> str:
    priority = str(_agent_routing(agent_id).get("default_priority") or "normal").strip().lower()
    return priority if priority in _VALID_PRIORITIES else "normal"


def _agent_can_handoff(from_agent_id: str, to_agent_id: str) -> bool:
    targets = _agent_handoff_targets(from_agent_id)
    return not targets or _normalize_agent_id(to_agent_id) in targets


def _agent_policy_payload(agent_id: str) -> dict[str, Any]:
    agent = _agent_def(agent_id)
    routing = _agent_routing(agent_id)
    safety = _agent_safety(agent_id)
    runtime = _agent_runtime(agent_id)
    return {
        "id": _normalize_agent_id(agent_id),
        "name": agent.get("name") or _normalize_agent_id(agent_id),
        "role": agent.get("role") or "support",
        "description": agent.get("description") or "",
        "enabled": bool(agent.get("enabled", True)),
        "prompt": agent.get("prompt") or "",
        "runtime": {
            "model": runtime.get("model") or "",
            "provider": runtime.get("provider") or "",
            "runtime_type": runtime.get("runtime_type") or "",
            "workdir": runtime.get("workdir") or "",
            "timezone": runtime.get("timezone") or "",
            "context_warning_threshold": runtime.get("context_warning_threshold"),
            "context_handoff_threshold": runtime.get("context_handoff_threshold"),
            "codex_context_cap": runtime.get("codex_context_cap"),
        },
        "routing": {
            "owns": _agent_list(routing.get("owns")),
            "handoff_targets": _agent_handoff_targets(agent_id),
            "escalation_target": routing.get("escalation_target") or "",
            "default_priority": _agent_default_priority(agent_id),
        },
        "safety": {
            "approval_mode": safety.get("approval_mode") or "confirm_external_send",
            "always_ask": _agent_list(safety.get("always_ask")),
            "never_ask": _agent_list(safety.get("never_ask")),
            "dangerously_skip_permissions": bool(safety.get("dangerously_skip_permissions")),
        },
        "identity": agent.get("identity") if isinstance(agent.get("identity"), Mapping) else {},
        "soul": agent.get("soul") if isinstance(agent.get("soul"), Mapping) else {},
        "lifecycle": agent.get("lifecycle") if isinstance(agent.get("lifecycle"), Mapping) else {},
        "ecosystem": agent.get("ecosystem") if isinstance(agent.get("ecosystem"), Mapping) else {},
        "memory": agent.get("memory") if isinstance(agent.get("memory"), Mapping) else {},
        "compat": agent.get("compat") if isinstance(agent.get("compat"), Mapping) else {},
    }


def _clip_text(value: Any, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _memory_policy_payload(agent_id: str) -> dict[str, Any]:
    memory = _agent_memory(agent_id)
    return {
        "agentId": _normalize_agent_id(agent_id),
        "mode": memory.get("mode") or "shared_scoped",
        "scopes": _agent_list(memory.get("scopes")),
        "sources": _agent_list(memory.get("sources")),
        "recall_policy": memory.get("recall_policy") or "agent_scoped_recent",
        "write_policy": memory.get("write_policy") or "append_events",
        "handoff_policy": memory.get("handoff_policy") or "summary_only",
    }


def _apply_memory_handoff_policy(agent_id: str, result: Any) -> Any:
    if not isinstance(result, Mapping):
        return result
    policy = str(_agent_memory(agent_id).get("handoff_policy") or "summary_only").strip().lower()
    if policy in {"full", "full_text", "verbatim"}:
        return result
    if policy in {"facts_only", "facts"}:
        facts = result.get("facts") or result.get("memoryFacts") or result.get("memory_facts") or []
        return {
            "summary": _clip_text(result.get("summary") or result.get("message") or result.get("content")),
            "facts": facts if isinstance(facts, list) else [],
            "source": result.get("source"),
            "nextHandoffs": result.get("nextHandoffs") or result.get("next_handoffs") or [],
        }
    keep = {
        "summary",
        "message",
        "status",
        "source",
        "cronJobId",
        "outcome",
        "silent",
        "facts",
        "nextHandoffs",
        "next_handoffs",
    }
    compact = {key: value for key, value in result.items() if key in keep}
    if "summary" not in compact:
        compact["summary"] = _clip_text(
            result.get("summary")
            or result.get("message")
            or result.get("content")
            or result.get("fullText")
            or result.get("full_text")
            or result.get("raw")
        )
    return compact


def _assert_agent_handoff_allowed(from_agent_id: str, to_agent_id: str, *, actor: str) -> None:
    from_id = _normalize_agent_id(from_agent_id)
    to_id = _normalize_agent_id(to_agent_id)
    if from_id in {"executive-assistant", "system", "human", "human-web"}:
        return
    # Dashboard/API-created tasks use actor=human:web and can route deliberately.
    if _normalize_agent_id(actor) != from_id:
        return
    if not _agent_can_handoff(from_id, to_id):
        targets = ", ".join(_agent_handoff_targets(from_id)) or "none"
        raise ValueError(f"{from_id} is not configured to hand work to {to_id}; allowed targets: {targets}")


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


def _pause_for_policy_decision(
    conn: sqlite3.Connection,
    handoff: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
    actor: str,
) -> dict[str, Any] | None:
    if decision.get("decision") != "approval_required":
        return None
    now = now_iso()
    prompt = {
        "title": f"Approve handoff: {handoff.get('title')}",
        "message": (
            f"{decision.get('agentId') or handoff.get('fromAgentId')} needs human approval "
            f"before {decision.get('action') or 'continuing this handoff'}."
        ),
        "handoffId": handoff.get("id"),
        "policy": dict(decision),
    }
    result = {
        "blockedBy": [{"type": "agent_policy", "decision": dict(decision)}],
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
            "Agent safety policy requires human approval",
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
            event="policy_blocked",
            payload={"decision": dict(decision)},
        )
    return updated


def _pause_for_lifecycle_status(
    conn: sqlite3.Connection,
    handoff: Mapping[str, Any],
    *,
    lifecycle_status: Mapping[str, Any],
    actor: str,
) -> dict[str, Any] | None:
    if not lifecycle_status.get("suspended"):
        return None
    now = now_iso()
    reason = str(lifecycle_status.get("reason") or "lifecycle_limit")
    to_agent_id = _normalize_agent_id(handoff.get("toAgentId"))
    prompt = {
        "title": f"Review {to_agent_id} lifecycle",
        "message": f"This handoff is paused because {to_agent_id} hit lifecycle limit: {reason}.",
        "handoffId": handoff.get("id"),
        "lifecycle": dict(lifecycle_status),
    }
    result = {
        "blockedBy": [{"type": "lifecycle", "reason": reason, "status": dict(lifecycle_status)}],
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
            f"Lifecycle policy paused agent run: {reason}",
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
            event="lifecycle_blocked",
            payload={"lifecycle": dict(lifecycle_status)},
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
    handoff = get_agent_handoff(conn, handoff_id, include_messages=True)
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


def _comms_pair_key(left: Any, right: Any) -> str:
    a = _normalize_agent_id(left)
    b = _normalize_agent_id(right)
    ordered = sorted([a, b])
    return f"{ordered[0]}--{ordered[1]}"


def _split_comms_pair(pair: str) -> tuple[str, str]:
    parts = str(pair or "").split("--", 1)
    if len(parts) != 2:
        raise ValueError("channel pair must use agent-a--agent-b")
    a = _normalize_agent_id(parts[0])
    b = _normalize_agent_id(parts[1])
    if not a or not b or a == b:
        raise ValueError("channel pair requires two different participants")
    return a, b


def _handoff_row_to_comms_message(row: sqlite3.Row) -> dict[str, Any]:
    from_id = row["from_agent_id"]
    to_id = row["to_agent_id"]
    created_at = row["created_at"]
    return {
        "id": f"handoff:{row['id']}",
        "source": "handoff",
        "handoffId": row["id"],
        "messageId": None,
        "pair": _comms_pair_key(from_id, to_id),
        "from": from_id,
        "to": to_id,
        "priority": row["priority"],
        "timestamp": created_at,
        "createdAt": created_at,
        "text": row["task"] or row["title"] or "",
        "replyTo": row["parent_handoff_id"],
        "reply_to": row["parent_handoff_id"],
        "kind": "request",
        "title": row["title"],
        "handoffStatus": row["status"],
        "archived": row["status"] in _TERMINAL_STATUSES,
        "payload": _json_loads(row["payload_json"]),
    }


def _message_row_to_comms_message(row: sqlite3.Row) -> dict[str, Any]:
    from_id = row["message_from_agent_id"]
    to_id = row["message_to_agent_id"] or row["handoff_to_agent_id"]
    created_at = row["message_created_at"]
    return {
        "id": f"handoff-message:{row['message_id']}",
        "source": "handoff_message",
        "handoffId": row["handoff_id"],
        "messageId": row["message_id"],
        "pair": _comms_pair_key(from_id, to_id),
        "from": from_id,
        "to": to_id,
        "priority": row["priority"],
        "timestamp": created_at,
        "createdAt": created_at,
        "text": row["content"] or "",
        "replyTo": row["handoff_id"],
        "reply_to": row["handoff_id"],
        "kind": row["kind"],
        "title": row["title"],
        "handoffStatus": row["status"],
        "archived": row["status"] in _TERMINAL_STATUSES,
        "payload": _json_loads(row["message_payload_json"]),
    }


def _message_text_matches(message: Mapping[str, Any], search: str | None) -> bool:
    if not search:
        return True
    q = search.casefold()
    haystack = " ".join(
        str(message.get(key) or "")
        for key in ("from", "to", "title", "text", "kind", "priority", "handoffStatus")
    ).casefold()
    return q in haystack


def list_agent_comms_messages(
    conn: sqlite3.Connection,
    *,
    agent_id: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return native meeting-room messages from native handoffs."""
    clean_agent = _normalize_agent_id(agent_id) if agent_id else None
    cap = max(1, min(int(limit or 200), 1000))
    params: list[Any] = []
    agent_filter = ""
    if clean_agent:
        agent_filter = " AND (from_agent_id = ? OR to_agent_id = ?)"
        params.extend([clean_agent, clean_agent])

    handoff_rows = conn.execute(
        f"""
        SELECT * FROM agent_handoffs
        WHERE 1=1 {agent_filter}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (*params, cap * 3),
    ).fetchall()

    msg_params: list[Any] = []
    msg_filter = ""
    if clean_agent:
        msg_filter = (
            " AND (m.from_agent_id = ? OR m.to_agent_id = ? "
            "OR h.from_agent_id = ? OR h.to_agent_id = ?)"
        )
        msg_params.extend([clean_agent, clean_agent, clean_agent, clean_agent])
    message_rows = conn.execute(
        f"""
        SELECT
            m.id AS message_id,
            m.handoff_id AS handoff_id,
            m.from_agent_id AS message_from_agent_id,
            m.to_agent_id AS message_to_agent_id,
            m.kind AS kind,
            m.content AS content,
            m.payload_json AS message_payload_json,
            m.created_at AS message_created_at,
            h.from_agent_id AS handoff_from_agent_id,
            h.to_agent_id AS handoff_to_agent_id,
            h.title AS title,
            h.status AS status,
            h.priority AS priority
        FROM agent_handoff_messages m
        JOIN agent_handoffs h ON h.id = m.handoff_id
        WHERE 1=1 {msg_filter}
        ORDER BY m.created_at DESC
        LIMIT ?
        """,
        (*msg_params, cap * 4),
    ).fetchall()

    messages = [_handoff_row_to_comms_message(row) for row in handoff_rows]
    messages.extend(_message_row_to_comms_message(row) for row in message_rows)
    filtered = [msg for msg in messages if _message_text_matches(msg, search)]
    filtered.sort(key=lambda msg: str(msg.get("timestamp") or ""), reverse=True)
    return filtered[:cap]


def list_agent_comms_channels(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Group native handoff messages into native pair channels."""
    messages = list_agent_comms_messages(conn, limit=max(limit * 5, 500))
    channels: dict[str, dict[str, Any]] = {}
    for msg in messages:
        pair = str(msg.get("pair") or "")
        if not pair:
            continue
        archived = bool(msg.get("archived"))
        if archived and not include_archived:
            # Keep terminal conversations if a newer non-terminal message already
            # opened the channel; otherwise hide old completed-only pairs.
            if pair not in channels:
                continue
        channel = channels.get(pair)
        participants = pair.split("--", 1)
        if channel is None:
            channel = {
                "pair": pair,
                "agents": participants,
                "message_count": 0,
                "messageCount": 0,
                "last_message": None,
                "lastMessage": None,
                "last_activity": None,
                "lastActivity": None,
                "archived": archived,
            }
            channels[pair] = channel
        channel["message_count"] += 1
        channel["messageCount"] = channel["message_count"]
        if not channel["last_activity"] or str(msg.get("timestamp") or "") > str(channel["last_activity"]):
            preview = {
                "id": msg.get("id"),
                "from": msg.get("from"),
                "to": msg.get("to"),
                "text": msg.get("text"),
                "timestamp": msg.get("timestamp"),
                "kind": msg.get("kind"),
                "priority": msg.get("priority"),
            }
            channel["last_message"] = preview
            channel["lastMessage"] = preview
            channel["last_activity"] = msg.get("timestamp")
            channel["lastActivity"] = msg.get("timestamp")
    out = list(channels.values())
    out.sort(key=lambda ch: str(ch.get("last_activity") or ""), reverse=True)
    return out[: max(1, min(int(limit or 200), 1000))]


def get_agent_comms_channel(
    conn: sqlite3.Connection,
    pair: str,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    a, b = _split_comms_pair(pair)
    cap = max(1, min(int(limit or 200), 1000))
    rows = conn.execute(
        """
        SELECT * FROM agent_handoffs
        WHERE (from_agent_id = ? AND to_agent_id = ?)
           OR (from_agent_id = ? AND to_agent_id = ?)
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (a, b, b, a, cap),
    ).fetchall()
    handoff_ids = [row["id"] for row in rows]
    messages = [_handoff_row_to_comms_message(row) for row in rows]
    if handoff_ids:
        placeholders = ",".join("?" for _ in handoff_ids)
        msg_rows = conn.execute(
            f"""
            SELECT
                m.id AS message_id,
                m.handoff_id AS handoff_id,
                m.from_agent_id AS message_from_agent_id,
                m.to_agent_id AS message_to_agent_id,
                m.kind AS kind,
                m.content AS content,
                m.payload_json AS message_payload_json,
                m.created_at AS message_created_at,
                h.from_agent_id AS handoff_from_agent_id,
                h.to_agent_id AS handoff_to_agent_id,
                h.title AS title,
                h.status AS status,
                h.priority AS priority
            FROM agent_handoff_messages m
            JOIN agent_handoffs h ON h.id = m.handoff_id
            WHERE m.handoff_id IN ({placeholders})
            ORDER BY m.created_at ASC
            """,
            handoff_ids,
        ).fetchall()
        messages.extend(_message_row_to_comms_message(row) for row in msg_rows)
    messages.sort(key=lambda msg: str(msg.get("timestamp") or ""))
    if len(messages) > cap:
        messages = messages[-cap:]
    canonical = _comms_pair_key(a, b)
    return {
        "pair": canonical,
        "agents": canonical.split("--", 1),
        "messages": messages,
        "count": len(messages),
    }


def create_agent_comms_message(
    conn: sqlite3.Connection,
    *,
    from_agent_id: str,
    to_agent_id: str,
    text: str,
    priority: str = "normal",
    reply_to: str | None = None,
    run_now: bool = False,
    actor: str = "human:web",
) -> dict[str, Any]:
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("message text is required")
    handoff = create_agent_handoff(
        conn,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        title=clean_text.splitlines()[0][:90],
        task=clean_text,
        priority=priority,
        parent_handoff_id=reply_to if reply_to and not str(reply_to).startswith("handoff-message:") else None,
        payload={"source": "comms", "replyTo": reply_to},
        create_cron_job=run_now,
        actor=actor,
    )
    messages = handoff.get("messages") if isinstance(handoff, Mapping) else None
    message = messages[-1] if isinstance(messages, list) and messages else None
    return {
        "handoff": handoff,
        "message": {
            "id": f"handoff-message:{message.get('id')}" if isinstance(message, Mapping) else f"handoff:{handoff.get('id')}",
            "source": "handoff_message" if isinstance(message, Mapping) else "handoff",
            "handoffId": handoff.get("id"),
            "messageId": message.get("id") if isinstance(message, Mapping) else None,
            "pair": _comms_pair_key(handoff.get("fromAgentId"), handoff.get("toAgentId")),
            "from": handoff.get("fromAgentId"),
            "to": handoff.get("toAgentId"),
            "priority": handoff.get("priority"),
            "timestamp": message.get("createdAt") if isinstance(message, Mapping) else handoff.get("createdAt"),
            "createdAt": message.get("createdAt") if isinstance(message, Mapping) else handoff.get("createdAt"),
            "text": message.get("content") if isinstance(message, Mapping) else handoff.get("task"),
            "replyTo": reply_to,
            "reply_to": reply_to,
            "kind": message.get("kind") if isinstance(message, Mapping) else "request",
            "title": handoff.get("title"),
            "handoffStatus": handoff.get("status"),
            "archived": handoff.get("status") in _TERMINAL_STATUSES,
            "payload": message.get("payload") if isinstance(message, Mapping) else handoff.get("payload"),
        },
    }


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
    _assert_agent_handoff_allowed(from_id, to_id, actor=actor)
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
    handoff = get_agent_handoff(conn, handoff_id, include_messages=True)
    if handoff:
        _record_deal_handoff_event(
            conn,
            handoff,
            actor=actor,
            event="created",
            payload={"priority": clean_priority},
        )
        if from_id not in {"executive-assistant", "system", "human", "human-web"} and _normalize_agent_id(actor) == from_id:
            try:
                from elevate_cli.agent_policy import evaluate_agent_policy

                decision = evaluate_agent_policy(
                    from_id,
                    action="follow_up_handoff" if parent_handoff_id else "handoff",
                    category="follow_up_handoff" if parent_handoff_id else "handoff",
                    conn=conn,
                    create_approval=False,
                    surface="agent-handoffs",
                    description=f"{from_id} wants to hand work to {to_id}: {clean_title}",
                    actor=actor,
                    resource=to_id,
                )
            except Exception:
                decision = {"decision": "allow"}
            policy_blocked = _pause_for_policy_decision(conn, handoff, decision=decision, actor=actor)
            if policy_blocked:
                return policy_blocked
        blocked = _pause_for_dependency_blocks(conn, handoff, actor=actor)
        if blocked:
            return blocked
    if create_cron_job:
        return dispatch_agent_handoff_to_cron(conn, handoff_id, actor=actor)
    return handoff  # type: ignore[return-value]


def _agent_skill_names(agent_id: str) -> list[str]:
    try:
        agent = _agent_def(agent_id)
        skills = agent.get("skills") if isinstance(agent, Mapping) else []
        if isinstance(skills, str):
            skills = [skills]
        if isinstance(skills, (list, tuple, set)):
            clean: list[str] = []
            for skill in skills:
                name = str(skill or "").strip()
                if not name:
                    continue
                if name.lower() in _TOOLSET_LIKE_SKILL_NAMES:
                    continue
                clean.append(name)
            return clean
    except Exception:
        return []
    return []


def _agent_toolset_names(agent_id: str) -> list[str]:
    try:
        agent = _agent_def(agent_id)
        toolsets = agent.get("toolsets") if isinstance(agent, Mapping) else []
        if isinstance(toolsets, str):
            toolsets = [toolsets]
        if not isinstance(toolsets, (list, tuple, set)):
            toolsets = []
        names = [str(toolset).strip() for toolset in toolsets if str(toolset or "").strip()]
        skills = agent.get("skills") if isinstance(agent, Mapping) else []
        for skill in _agent_list(skills):
            alias = _SKILL_TO_TOOLSET_ALIASES.get(skill.lower())
            if alias:
                _append_unique(names, [alias])
        role = str(agent.get("role") or "").strip().lower() if isinstance(agent, Mapping) else ""
        owns = {_normalize_agent_id(item) for item in _agent_list(_agent_routing(agent_id).get("owns"))}
        if role == "admin" or owns.intersection({"admin-operations", "deal-files", "compliance", "deadline-review"}):
            _append_unique(names, _ADMIN_NATIVE_TOOLSETS)
        if names and "agent_handoff" not in names:
            names.append("agent_handoff")
        return names
    except Exception:
        return []


def _handoff_prompt(handoff: Mapping[str, Any]) -> str:
    payload = handoff.get("payload")
    to_agent_id = _normalize_agent_id(handoff.get("toAgentId"))
    agent_policy = _agent_policy_payload(to_agent_id)
    messages = handoff.get("messages") if isinstance(handoff.get("messages"), list) else []
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
        "- Follow the receiving agent identity, routing, runtime, and safety policy below as hard run policy.",
        "- Work only the requested task, then write back to the handoff bus with the agent_handoff tool.",
        "- If the task needs human confirmation, mark the handoff waiting_human and include a concise human prompt.",
        "- If your safety policy says to ask, mark the handoff waiting_human before taking that action.",
        "- Only create follow-up handoffs to configured handoff_targets unless the target list is empty.",
        "- Escalate ambiguous, blocked, or out-of-scope work to the configured escalation_target.",
        "- Follow persona, soul, lifecycle, ecosystem, and memory policy fields when present.",
        "- Recall/write durable memory only according to the memory policy; do not dump long-running memory into the result.",
        "- If you attach, draft, or modify deal work, use the deal-specific result writer or data helper the workflow requires.",
        "- Do not message the human directly with send_message unless this handoff explicitly asks for external delivery.",
        "- Prefer agent_handoff action='complete'. If you do not call the tool, your final response is recorded back into this Comms handoff thread.",
        "- If there is nothing useful to report, still update the handoff bus and respond exactly [SILENT].",
        "",
        "Completion contract:",
        "Use agent_handoff with action='complete' and this handoff_id.",
        "Use action='message' for intermediate notes or action='create' only when handing work to another agent.",
    ]
    prompt_lines.extend(["", "Receiving agent policy:", json.dumps(agent_policy, indent=2, default=str)])
    if messages:
        prompt_lines.extend(
            [
                "",
                "Handoff message thread:",
                json.dumps(messages[-12:], indent=2, default=str),
            ]
        )
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
    handoff = get_agent_handoff(conn, handoff_id, include_messages=True)
    if not handoff:
        raise LookupError(f"handoff {handoff_id!r} not found")
    if handoff["status"] != "queued":
        return handoff
    blocked = _pause_for_dependency_blocks(conn, handoff, actor=actor)
    if blocked:
        return blocked

    to_agent_id = _normalize_agent_id(handoff["toAgentId"])
    agent_policy = _agent_policy_payload(to_agent_id)
    if not agent_policy.get("enabled", True):
        now = now_iso()
        prompt = {
            "title": f"Enable {to_agent_id}",
            "message": "This handoff is waiting because the receiving agent is suspended.",
            "handoffId": handoff["id"],
            "missing": [
                {
                    "type": "agent_enabled",
                    "agentId": to_agent_id,
                    "label": "Receiving agent must be enabled",
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
                "Receiving agent is suspended",
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
        return get_agent_handoff(conn, handoff_id, include_messages=False)  # type: ignore[return-value]
    try:
        from elevate_cli.agent_policy import agent_lifecycle_status

        lifecycle_status = agent_lifecycle_status(to_agent_id, conn=conn)
    except Exception:
        lifecycle_status = {"startupDelay": 0, "suspended": False}
    lifecycle_blocked = _pause_for_lifecycle_status(
        conn,
        handoff,
        lifecycle_status=lifecycle_status,
        actor=actor,
    )
    if lifecycle_blocked:
        return lifecycle_blocked
    try:
        from cron import jobs as cron_jobs

        delivery_target = ""
        telegram_lane = ""
        try:
            from gateway.agent_lanes import (
                agent_telegram_delivery_target,
                agent_telegram_lane_ready,
            )

            candidate = agent_telegram_delivery_target(to_agent_id, default="")
            if agent_telegram_lane_ready(to_agent_id) and candidate:
                delivery_target = candidate
                telegram_lane = f"{to_agent_id}-agent"
        except Exception:
            delivery_target = ""

        startup_delay = int(lifecycle_status.get("startupDelay") or 0)
        schedule_at = (
            (datetime.now(timezone.utc) + timedelta(seconds=startup_delay)).isoformat()
            if startup_delay > 0
            else now_iso()
        )
        # Handoff step jobs NEVER deliver their own output to the chat:
        # each chain step used to message the user's Telegram on completion,
        # so a decomposed workflow produced a wall of internal micro-step
        # spam. Steps run deliver="local" (output still lands in
        # cron/output/ + last_summary + the Comms handoff thread); the
        # scheduler delivers ONE rollup to the origin chat when the whole
        # handoff chain reaches a terminal state (see
        # claim_agent_handoff_chain_rollup + cron.scheduler).
        job = cron_jobs.create_job(
            prompt=_handoff_prompt(handoff),
            schedule=schedule_at,
            name=f"handoff:{to_agent_id}:{handoff['id'][:8]}",
            repeat=1,
            deliver="local",
            skills=_agent_skill_names(to_agent_id),
            enabled_toolsets=_agent_toolset_names(to_agent_id) or None,
            agent=to_agent_id,
            metadata={"source": "handoff"},
            origin={
                "source": "agent_handoff",
                "actor": actor,
                "agent": to_agent_id,
                "from_agent_id": handoff["fromAgentId"],
                "to_agent_id": to_agent_id,
                "handoff_id": handoff["id"],
                "deal_id": handoff.get("dealId"),
                "profile_id": handoff.get("profileId"),
                "delivery": "in_app_handoff",
                "telegram_lane": telegram_lane,
                "optional_delivery_target": delivery_target,
                "lifecycle": lifecycle_status,
                "startup_delay_seconds": startup_delay,
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
        content=(
            f"Dispatched to {to_agent_id} cron job {cron_job_id or 'unknown'}; "
            "final output will return to this Comms handoff thread."
        ),
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
    run_actor = _normalize_agent_id(actor)
    receiving_agent = _normalize_agent_id(handoff.get("toAgentId"))
    policy_agent = receiving_agent if receiving_agent not in {"system", "human", "human-web"} else run_actor
    compact_result = _apply_memory_handoff_policy(policy_agent, result)
    memory_policy = _memory_policy_payload(policy_agent)
    payload = compact_result
    if human_prompt is not None:
        payload = {"result": compact_result, "humanPrompt": human_prompt}
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
    if not content and isinstance(compact_result, Mapping):
        content = str(compact_result.get("summary") or compact_result.get("message") or "")
    if not content:
        content = f"Handoff marked {status}."
    record_agent_handoff_message(
        conn,
        handoff_id,
        from_agent_id=actor,
        to_agent_id=handoff.get("fromAgentId"),
        kind=kind,
        content=content,
        payload={
            "result": compact_result,
            "humanPrompt": human_prompt,
            "status": status,
            "memoryPolicy": memory_policy,
        },
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
                    "result": compact_result,
                    "humanPrompt": human_prompt,
                    "memoryPolicy": memory_policy,
                },
            )
        next_handoffs = []
        if isinstance(compact_result, Mapping):
            raw_next = compact_result.get("nextHandoffs") or compact_result.get("next_handoffs") or []
            if isinstance(raw_next, (list, tuple)):
                next_handoffs = [item for item in raw_next if isinstance(item, Mapping)]
        for item in next_handoffs:
            from_agent = str(updated.get("toAgentId") or actor)
            to_agent = str(item.get("toAgentId") or item.get("to_agent_id") or "").strip()
            task = str(item.get("task") or "").strip()
            if not to_agent or not task:
                continue
            if not _agent_can_handoff(from_agent, to_agent):
                record_agent_handoff_message(
                    conn,
                    handoff_id,
                    from_agent_id="system",
                    to_agent_id=from_agent,
                    kind="error",
                    content=(
                        f"Skipped follow-up handoff to {to_agent}: "
                        f"{from_agent} is not configured to hand work to that agent."
                    ),
                    payload={
                        "toAgentId": to_agent,
                        "allowedTargets": _agent_handoff_targets(from_agent),
                        "source": "routing_policy",
                    },
                )
                continue
            create_agent_handoff(
                conn,
                from_agent_id=from_agent,
                to_agent_id=to_agent,
                title=item.get("title"),
                task=task,
                priority=str(item.get("priority") or _agent_default_priority(from_agent)),
                deal_id=item.get("dealId") or item.get("deal_id") or updated.get("dealId"),
                profile_id=item.get("profileId") or item.get("profile_id") or updated.get("profileId"),
                contact_id=item.get("contactId") or item.get("contact_id") or updated.get("contactId"),
                conversation_id=item.get("conversationId") or item.get("conversation_id") or updated.get("conversationId"),
                source_run_id=item.get("sourceRunId") or item.get("source_run_id") or updated.get("sourceRunId"),
                parent_handoff_id=handoff_id,
                payload=item.get("payload"),
                idempotency_key=item.get("idempotencyKey") or item.get("idempotency_key"),
                create_cron_job=bool(item.get("runNow") or item.get("run_now")),
                actor=from_agent,
            )
        if next_handoffs:
            updated = get_agent_handoff(conn, handoff_id, include_messages=True)
    return updated  # type: ignore[return-value]


def record_agent_handoff_cron_delivery(
    conn: sqlite3.Connection,
    handoff_id: str,
    *,
    success: bool,
    final_response: str | None = "",
    error_message: str | None = None,
    cron_outcome: str | None = None,
    actor: str | None = None,
    cron_job_id: str | None = None,
) -> dict[str, Any]:
    """Mirror an agent-owned cron run back into the visible handoff thread.

    The agent_handoff tool remains the preferred completion path. This helper
    is the native in-app fallback for cron runs that finish with only a final
    response, so agent-to-agent work does not require a Telegram lane.
    """
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if not handoff:
        raise LookupError(f"handoff {handoff_id!r} not found")
    if handoff.get("status") in _TERMINAL_STATUSES:
        return get_agent_handoff(conn, handoff_id, include_messages=True) or handoff

    text = str(final_response or "").strip()
    clean_error = str(error_message or "").strip() or None
    outcome = str(cron_outcome or "").strip().lower() or None
    run_actor = _normalize_agent_id(actor or handoff.get("toAgentId"))
    result_key = f"cron-final:{cron_job_id or 'unknown'}:{handoff_id}"

    def _record(**kwargs: Any) -> dict[str, Any]:
        try:
            return record_agent_handoff_result(
                conn,
                handoff_id,
                idempotency_key=result_key,
                actor=run_actor,
                **kwargs,
            )
        except ValueError as exc:
            if "already been recorded" in str(exc):
                return get_agent_handoff(conn, handoff_id, include_messages=True) or handoff
            raise

    base_result = {
        "source": "cron_final_response",
        "cronJobId": cron_job_id,
        "outcome": outcome,
    }
    if not success or outcome == "error":
        summary = clean_error or text or "Cron handoff run failed."
        return _record(
            status="failed",
            result={**base_result, "summary": summary},
            error_message=summary,
        )

    if outcome in {"waiting_human", "needs_operator"}:
        message = text or "Agent run requested human review."
        prompt = {
            "title": f"Review handoff: {handoff.get('title')}",
            "message": message,
            "handoffId": handoff_id,
            "source": "cron_final_response",
            "cronJobId": cron_job_id,
            "outcome": outcome,
        }
        return _record(
            status="waiting_human",
            result={**base_result, "summary": message},
            human_prompt=prompt,
        )

    silent = not text or "[SILENT]" in text.upper()
    summary = "Agent run completed silently." if silent else text
    return _record(
        status="completed",
        result={**base_result, "summary": summary, "silent": silent},
    )


_ROLLUP_CLAIM_KEY = "rollupDeliveredAt"


def _agent_handoff_chain_root_id(conn: sqlite3.Connection, handoff_id: str) -> str:
    """Walk parent_handoff_id links up to the chain root."""
    current = str(handoff_id)
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        row = conn.execute(
            "SELECT parent_handoff_id FROM agent_handoffs WHERE id = ?",
            (current,),
        ).fetchone()
        if not row:
            break
        parent = row["parent_handoff_id"]
        if not parent or str(parent) in seen:
            break
        current = str(parent)
    return current


def _agent_handoff_chain_members(conn: sqlite3.Connection, root_id: str) -> list[dict[str, Any]]:
    """Return the root handoff plus every (recursive) follow-up handoff."""
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    frontier = [str(root_id)]
    while frontier:
        placeholders = ",".join("?" for _ in frontier)
        rows = conn.execute(
            f"SELECT * FROM agent_handoffs WHERE id IN ({placeholders})",
            frontier,
        ).fetchall()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            members.append(_row_to_handoff(row))
        child_rows = conn.execute(
            f"SELECT id FROM agent_handoffs WHERE parent_handoff_id IN ({placeholders})",
            frontier,
        ).fetchall()
        frontier = [r["id"] for r in child_rows if r["id"] not in seen]
    members.sort(key=lambda item: str(item.get("createdAt") or ""))
    return members


def claim_agent_handoff_chain_rollup(
    conn: sqlite3.Connection,
    handoff_id: str,
) -> dict[str, Any] | None:
    """Detect chain end and claim the single rollup delivery.

    A handoff chain is the root handoff (no parent) plus every recursive
    follow-up linked via ``parent_handoff_id``. Called after a handoff
    reaches a terminal status: returns the rollup payload exactly ONCE —
    when every chain member is terminal and this caller wins the atomic
    claim (a ``rollupDeliveredAt`` marker on the root's result_json,
    guarded by the UPDATE's WHERE clause so concurrent step completions
    cannot double-deliver). Returns None while the chain is still open or
    when another caller already claimed the rollup.
    """
    handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
    if not handoff or handoff.get("status") not in _TERMINAL_STATUSES:
        return None

    root_id = _agent_handoff_chain_root_id(conn, handoff_id)
    members = _agent_handoff_chain_members(conn, root_id)
    if not members:
        return None
    if any(member.get("status") in _OPEN_STATUSES for member in members):
        return None

    # Atomic claim on the root row: only the first writer's UPDATE matches.
    root = next((m for m in members if m["id"] == root_id), members[0])
    prior_result = root.get("result")
    if isinstance(prior_result, Mapping):
        claimed_result = {**dict(prior_result), _ROLLUP_CLAIM_KEY: now_iso()}
    elif prior_result is None:
        claimed_result = {_ROLLUP_CLAIM_KEY: now_iso()}
    else:
        claimed_result = {"result": prior_result, _ROLLUP_CLAIM_KEY: now_iso()}
    cursor = conn.execute(
        """
        UPDATE agent_handoffs
        SET result_json = ?, updated_at = ?
        WHERE id = ?
          AND (result_json IS NULL OR result_json NOT LIKE ?)
        """,
        (
            _json_dumps(claimed_result),
            now_iso(),
            root["id"],
            f'%"{_ROLLUP_CLAIM_KEY}"%',
        ),
    )
    if cursor.rowcount != 1:
        return None

    def _summary_of(item: Mapping[str, Any]) -> str:
        result = item.get("result")
        if isinstance(result, Mapping):
            text = str(result.get("summary") or result.get("message") or "").strip()
            if text:
                return text
        return str(item.get("errorMessage") or "").strip()

    trigger = next((m for m in members if m["id"] == handoff_id), None)
    final_summary = ""
    if trigger is not None:
        final_summary = _summary_of(trigger)
    if not final_summary:
        for member in reversed(members):
            final_summary = _summary_of(member)
            if final_summary:
                break

    status_counts: dict[str, int] = {}
    for member in members:
        key = str(member.get("status") or "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1

    return {
        "rootId": root["id"],
        "rootTitle": str(root.get("title") or root.get("task") or "agent handoff").strip(),
        "total": len(members),
        "statusCounts": status_counts,
        "steps": [
            {
                "id": member["id"],
                "title": str(member.get("title") or member.get("task") or member["id"]).strip(),
                "status": member.get("status"),
                "toAgentId": member.get("toAgentId"),
            }
            for member in members
        ],
        "finalSummary": final_summary,
    }


def mark_stale_agent_handoffs(
    conn: sqlite3.Connection,
    *,
    to_agent_id: str | None = None,
    max_running_minutes: int = _DEFAULT_STALE_RUNNING_MINUTES,
    actor: str = "agent-worker",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fail running handoffs that have not written back in time."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, int(max_running_minutes)))).isoformat()
    clauses = [
        "status = 'running'",
        "claimed_at IS NOT NULL",
        "claimed_at < ?",
    ]
    params: list[Any] = [cutoff]
    if to_agent_id:
        clauses.append("to_agent_id = ?")
        params.append(str(to_agent_id))
    params.append(max(1, min(int(limit or 100), 500)))
    rows = conn.execute(
        f"""
        SELECT id FROM agent_handoffs
        WHERE {' AND '.join(clauses)}
        ORDER BY claimed_at ASC
        LIMIT ?
        """,
        params,
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
        SELECT *
        FROM (
            SELECT to_agent_id,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued,
                   SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
                   SUM(CASE WHEN status = 'waiting_human' THEN 1 ELSE 0 END) AS waiting_human,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM agent_handoffs
            GROUP BY to_agent_id
        ) counts
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
