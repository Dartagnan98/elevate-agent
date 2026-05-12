"""Tool for durable visible-agent handoffs."""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result


def _session_agent_id() -> str:
    try:
        from gateway.session_context import get_session_env

        return get_session_env("ELEVATE_SESSION_AGENT_ID", "")
    except Exception:
        return ""


def _parent_agent_id(parent_agent: Any) -> str:
    if parent_agent is None:
        return ""
    for attr in ("agent_id", "_agent_id", "name"):
        value = str(getattr(parent_agent, attr, "") or "").strip()
        if value:
            return value
    return ""


def _current_agent_id(parent_agent: Any = None) -> str:
    return _session_agent_id() or _parent_agent_id(parent_agent)


def _handoff_tool(args: dict[str, Any], **kw: Any) -> str:
    action = str(args.get("action") or "create").strip().lower()
    try:
        from elevate_cli.data import (
            approve_agent_handoff,
            connect,
            create_agent_handoff,
            drain_queued_agent_handoffs,
            get_agent_handoff,
            list_agent_handoffs,
            record_agent_handoff_message,
            record_agent_handoff_result,
        )

        with connect() as conn:
            current_agent_id = _current_agent_id(kw.get("parent_agent"))
            if action == "create":
                from_agent_id = (
                    current_agent_id
                    or str(args.get("from_agent_id") or args.get("fromAgentId") or "").strip()
                    or "executive-assistant"
                )
                handoff = create_agent_handoff(
                    conn,
                    from_agent_id=from_agent_id,
                    to_agent_id=str(args.get("to_agent_id") or args.get("toAgentId") or "").strip(),
                    title=args.get("title"),
                    task=str(args.get("task") or "").strip(),
                    priority=str(args.get("priority") or "normal"),
                    deal_id=args.get("deal_id") or args.get("dealId"),
                    profile_id=args.get("profile_id") or args.get("profileId"),
                    contact_id=args.get("contact_id") or args.get("contactId"),
                    conversation_id=args.get("conversation_id") or args.get("conversationId"),
                    source_run_id=args.get("source_run_id") or args.get("sourceRunId"),
                    parent_handoff_id=args.get("parent_handoff_id") or args.get("parentHandoffId"),
                    payload=args.get("payload"),
                    idempotency_key=args.get("idempotency_key") or args.get("idempotencyKey"),
                    create_cron_job=bool(args.get("run_now", args.get("runNow", True))),
                    actor=from_agent_id,
                )
                return tool_result(success=True, handoff=handoff)

            if action == "list":
                items = list_agent_handoffs(
                    conn,
                    to_agent_id=args.get("to_agent_id") or args.get("toAgentId"),
                    from_agent_id=args.get("from_agent_id") or args.get("fromAgentId"),
                    status=args.get("status"),
                    deal_id=args.get("deal_id") or args.get("dealId"),
                    profile_id=args.get("profile_id") or args.get("profileId"),
                    limit=int(args.get("limit") or 20),
                )
                return tool_result(success=True, items=items, count=len(items))

            if action == "get":
                handoff = get_agent_handoff(
                    conn,
                    str(args.get("handoff_id") or args.get("handoffId") or ""),
                    include_messages=True,
                )
                if not handoff:
                    return tool_error("handoff not found")
                return tool_result(success=True, handoff=handoff)

            if action == "message":
                from_agent_id = (
                    current_agent_id
                    or str(args.get("from_agent_id") or args.get("fromAgentId") or "").strip()
                    or "executive-assistant"
                )
                message = record_agent_handoff_message(
                    conn,
                    str(args.get("handoff_id") or args.get("handoffId") or ""),
                    from_agent_id=from_agent_id,
                    to_agent_id=args.get("to_agent_id") or args.get("toAgentId"),
                    kind=str(args.get("kind") or "note"),
                    content=str(args.get("content") or ""),
                    payload=args.get("payload"),
                )
                return tool_result(success=True, message=message)

            if action == "complete":
                handoff_id = str(args.get("handoff_id") or args.get("handoffId") or "")
                handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
                if not handoff:
                    return tool_error("handoff not found")
                if current_agent_id and current_agent_id != handoff.get("toAgentId"):
                    return tool_error("only the receiving agent can complete this handoff")
                handoff = record_agent_handoff_result(
                    conn,
                    handoff_id,
                    status=str(args.get("status") or "completed"),
                    result=args.get("result"),
                    error_message=args.get("error_message") or args.get("errorMessage"),
                    human_prompt=args.get("human_prompt") or args.get("humanPrompt"),
                    idempotency_key=args.get("idempotency_key") or args.get("idempotencyKey"),
                    actor=current_agent_id or str(args.get("actor") or "").strip() or "executive-assistant",
                )
                return tool_result(success=True, handoff=handoff)

            if action == "approve":
                handoff_id = str(args.get("handoff_id") or args.get("handoffId") or "")
                handoff = get_agent_handoff(conn, handoff_id, include_messages=False)
                if not handoff:
                    return tool_error("handoff not found")
                if current_agent_id and current_agent_id not in {
                    "executive-assistant",
                    handoff.get("fromAgentId"),
                }:
                    return tool_error("only the requesting agent or executive assistant can approve this handoff")
                handoff = approve_agent_handoff(
                    conn,
                    handoff_id,
                    approved=bool(args.get("approved", True)),
                    run_now=bool(args.get("run_now", args.get("runNow", True))),
                    actor=current_agent_id or str(args.get("actor") or "").strip() or "executive-assistant",
                )
                return tool_result(success=True, handoff=handoff)

            if action == "drain":
                requested_to_agent = str(args.get("to_agent_id") or args.get("toAgentId") or "").strip()
                if current_agent_id and current_agent_id != "executive-assistant":
                    if requested_to_agent and requested_to_agent != current_agent_id:
                        return tool_error("agents can only drain their own handoffs")
                    requested_to_agent = current_agent_id
                items = drain_queued_agent_handoffs(
                    conn,
                    to_agent_id=requested_to_agent or None,
                    limit=int(args.get("limit") or 20),
                    actor=current_agent_id or str(args.get("actor") or "").strip() or "executive-assistant",
                )
                return tool_result(success=True, items=items, count=len(items))

            return tool_error(f"unknown agent_handoff action {action!r}")
    except Exception as exc:
        return tool_error(str(exc))


AGENT_HANDOFF_SCHEMA = {
    "type": "function",
    "function": {
        "name": "agent_handoff",
        "description": (
            "Create, inspect, drain, message, or complete durable handoffs "
            "between visible Elevate agents. Use this when specialist agents "
            "need to pass a task to another agent or write back a handoff result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "message", "complete", "approve", "drain"],
                    "description": "Operation to perform. Defaults to create.",
                },
                "from_agent_id": {"type": "string"},
                "to_agent_id": {"type": "string"},
                "handoff_id": {"type": "string"},
                "title": {"type": "string"},
                "task": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "waiting_human", "completed", "failed", "cancelled"],
                    "description": "Result status for action=complete, or filter for action=list.",
                },
                "deal_id": {"type": "string"},
                "profile_id": {"type": "string"},
                "contact_id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "source_run_id": {"type": "string"},
                "parent_handoff_id": {"type": "string"},
                "payload": {"type": "object"},
                "result": {"type": "object"},
                "human_prompt": {"type": "object"},
                "error_message": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "content": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["request", "note", "status", "result", "human_prompt", "error"],
                },
                "run_now": {
                    "type": "boolean",
                    "description": "For action=create/approve, immediately launch the receiving agent via cron. Defaults true.",
                },
                "approved": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["action"],
        },
    },
}


registry.register(
    name="agent_handoff",
    toolset="agent_handoff",
    schema=AGENT_HANDOFF_SCHEMA,
    handler=lambda args, **kw: _handoff_tool(args, **kw),
    description="Durable agent-to-agent handoff bus",
    emoji="",
)
