"""Agent handoff route registration for Agent Hub."""

import logging
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.agent_hub_models import (
    AgentHandoffApproveCreate,
    AgentHandoffCreate,
    AgentHandoffDrain,
    AgentHandoffMessageCreate,
    AgentHandoffResultCreate,
)


def register_agent_handoff_routes(
    router: APIRouter,
    *,
    require_admin_setup_ready_for_launch: Callable[[], None],
    log: Optional[logging.Logger] = None,
    web_actor: str = "human:web",
) -> None:
    _log = log or logging.getLogger(__name__)

    @router.get("/api/agent-handoffs")
    def get_agent_handoffs(
        to_agent_id: Optional[str] = None,
        from_agent_id: Optional[str] = None,
        status: Optional[str] = None,
        deal_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, list_agent_handoffs

            with connect() as conn:
                items = list_agent_handoffs(
                    conn,
                    to_agent_id=to_agent_id,
                    from_agent_id=from_agent_id,
                    status=status,
                    deal_id=deal_id,
                    profile_id=profile_id,
                    limit=limit,
                    offset=offset,
                )
            return {"items": items, "count": len(items)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/agent-handoffs failed")
            raise HTTPException(status_code=500, detail=f"Agent handoffs failed: {exc}")

    @router.get("/api/agent-handoffs/{handoff_id}")
    def get_agent_handoff_detail(handoff_id: str):
        try:
            from elevate_cli.data import connect, get_agent_handoff

            with connect() as conn:
                handoff = get_agent_handoff(conn, handoff_id, include_messages=True)
            if not handoff:
                raise HTTPException(status_code=404, detail="Handoff not found")
            return handoff
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/agent-handoffs/%s failed", handoff_id)
            raise HTTPException(status_code=500, detail=f"Agent handoff failed: {exc}")

    @router.post("/api/agent-handoffs")
    def create_agent_handoff_endpoint(body: AgentHandoffCreate):
        try:
            if body.toAgentId.strip().lower().replace("_", "-") == "admin":
                require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, create_agent_handoff

            with connect() as conn:
                return create_agent_handoff(
                    conn,
                    from_agent_id=body.fromAgentId,
                    to_agent_id=body.toAgentId,
                    title=body.title,
                    task=body.task,
                    priority=body.priority,
                    deal_id=body.dealId,
                    profile_id=body.profileId,
                    contact_id=body.contactId,
                    conversation_id=body.conversationId,
                    source_run_id=body.sourceRunId,
                    parent_handoff_id=body.parentHandoffId,
                    payload=body.payload,
                    idempotency_key=body.idempotencyKey,
                    create_cron_job=body.runNow,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-handoffs failed")
            raise HTTPException(status_code=500, detail=f"Agent handoff failed: {exc}")

    @router.post("/api/agent-handoffs/drain")
    def drain_agent_handoffs_endpoint(body: AgentHandoffDrain):
        try:
            from elevate_cli.data import connect, drain_queued_agent_handoffs

            with connect() as conn:
                items = drain_queued_agent_handoffs(
                    conn,
                    to_agent_id=body.toAgentId,
                    limit=body.limit,
                    actor=web_actor,
                )
            return {"items": items, "count": len(items)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-handoffs/drain failed")
            raise HTTPException(status_code=500, detail=f"Agent handoff drain failed: {exc}")

    @router.post("/api/agent-handoffs/{handoff_id}/messages")
    def create_agent_handoff_message_endpoint(handoff_id: str, body: AgentHandoffMessageCreate):
        try:
            from elevate_cli.data import connect, record_agent_handoff_message

            with connect() as conn:
                return record_agent_handoff_message(
                    conn,
                    handoff_id,
                    from_agent_id=body.fromAgentId,
                    to_agent_id=body.toAgentId,
                    kind=body.kind,
                    content=body.content,
                    payload=body.payload,
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-handoffs/%s/messages failed", handoff_id)
            raise HTTPException(status_code=500, detail=f"Agent handoff message failed: {exc}")

    @router.post("/api/agent-handoffs/{handoff_id}/result")
    def record_agent_handoff_result_endpoint(handoff_id: str, body: AgentHandoffResultCreate):
        try:
            from elevate_cli.data import connect, record_agent_handoff_result

            with connect() as conn:
                return record_agent_handoff_result(
                    conn,
                    handoff_id,
                    status=body.status,
                    result=body.result,
                    error_message=body.errorMessage,
                    human_prompt=body.humanPrompt,
                    idempotency_key=body.idempotencyKey,
                    actor=body.actor,
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-handoffs/%s/result failed", handoff_id)
            raise HTTPException(status_code=500, detail=f"Agent handoff result failed: {exc}")

    @router.post("/api/agent-handoffs/{handoff_id}/approve")
    def approve_agent_handoff_endpoint(handoff_id: str, body: AgentHandoffApproveCreate):
        try:
            from elevate_cli.data import approve_agent_handoff, connect

            with connect() as conn:
                return approve_agent_handoff(
                    conn,
                    handoff_id,
                    approved=body.approved,
                    run_now=body.runNow,
                    actor=body.actor,
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-handoffs/%s/approve failed", handoff_id)
            raise HTTPException(status_code=500, detail=f"Agent handoff approval failed: {exc}")
