"""Agent Hub and handoff routes for the Elevate dashboard."""

import inspect
import logging
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

WEB_ACTOR = "human:web"


def create_agent_hub_router(
    *,
    require_admin_setup_ready_for_launch: Callable[[], None],
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build routes for Agent Hub, agent handoffs, workers, and harness status."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    class AgentHandoffCreate(BaseModel):
        fromAgentId: str
        toAgentId: str
        task: str
        title: Optional[str] = None
        priority: str = "normal"
        dealId: Optional[str] = None
        profileId: Optional[str] = None
        contactId: Optional[str] = None
        conversationId: Optional[str] = None
        sourceRunId: Optional[str] = None
        parentHandoffId: Optional[str] = None
        payload: Optional[Dict[str, Any]] = None
        idempotencyKey: Optional[str] = None
        runNow: bool = False


    class AgentHandoffDrain(BaseModel):
        toAgentId: Optional[str] = None
        limit: int = 50


    class AgentHandoffMessageCreate(BaseModel):
        fromAgentId: str
        toAgentId: Optional[str] = None
        kind: str = "note"
        content: str = ""
        payload: Optional[Dict[str, Any]] = None


    class AgentHandoffResultCreate(BaseModel):
        status: str = "completed"
        result: Optional[Dict[str, Any]] = None
        errorMessage: Optional[str] = None
        humanPrompt: Optional[Dict[str, Any]] = None
        idempotencyKey: Optional[str] = None
        actor: str = "human:web"


    class AgentHandoffApproveCreate(BaseModel):
        approved: bool = True
        runNow: bool = True
        actor: str = "human:web"


    @router.get("/api/agent-hub")
    async def get_agent_hub():
        """Return the local Agent Hub snapshot for the dashboard."""
        try:
            from elevate_cli.agent_hub import build_agent_hub_snapshot
            import inspect

            kwargs = (
                {"include_profiles": False}
                if "include_profiles" in inspect.signature(build_agent_hub_snapshot).parameters
                else {}
            )
            return build_agent_hub_snapshot(**kwargs)
        except Exception as exc:
            _log.exception("GET /api/agent-hub failed")
            raise HTTPException(status_code=500, detail=f"Agent Hub failed: {exc}")


    @router.get("/api/agent-handoffs")
    async def get_agent_handoffs(
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
    async def get_agent_handoff_detail(handoff_id: str):
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
    async def create_agent_handoff_endpoint(body: AgentHandoffCreate):
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
                    actor="human:web",
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
    async def drain_agent_handoffs_endpoint(body: AgentHandoffDrain):
        try:
            from elevate_cli.data import connect, drain_queued_agent_handoffs

            with connect() as conn:
                items = drain_queued_agent_handoffs(
                    conn,
                    to_agent_id=body.toAgentId,
                    limit=body.limit,
                    actor="human:web",
                )
            return {"items": items, "count": len(items)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-handoffs/drain failed")
            raise HTTPException(status_code=500, detail=f"Agent handoff drain failed: {exc}")


    @router.post("/api/agent-handoffs/{handoff_id}/messages")
    async def create_agent_handoff_message_endpoint(handoff_id: str, body: AgentHandoffMessageCreate):
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
    async def record_agent_handoff_result_endpoint(handoff_id: str, body: AgentHandoffResultCreate):
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
    async def approve_agent_handoff_endpoint(handoff_id: str, body: AgentHandoffApproveCreate):
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


    @router.get("/api/agent-worker")
    async def get_agent_worker_status():
        try:
            from elevate_cli.agent_worker import snapshot

            return snapshot()
        except Exception as exc:
            _log.exception("GET /api/agent-worker failed")
            raise HTTPException(status_code=500, detail=f"Agent worker failed: {exc}")


    @router.post("/api/agent-worker/tick")
    async def post_agent_worker_tick():
        try:
            from elevate_cli.agent_worker import tick

            return tick(actor=WEB_ACTOR)
        except Exception as exc:
            _log.exception("POST /api/agent-worker/tick failed")
            raise HTTPException(status_code=500, detail=f"Agent worker tick failed: {exc}")


    @router.post("/api/agent-worker/wake")
    async def post_agent_worker_wake():
        try:
            from elevate_cli.agent_worker import request_wake

            return request_wake(reason="agent-hub", actor=WEB_ACTOR)
        except Exception as exc:
            _log.exception("POST /api/agent-worker/wake failed")
            raise HTTPException(status_code=500, detail=f"Agent worker wake failed: {exc}")


    @router.get("/api/harness")
    async def get_harness(include_profiles: bool = False):
        """Return the compact local harness health snapshot."""
        try:
            from elevate_cli.harness import build_harness_snapshot

            return build_harness_snapshot(include_profiles=include_profiles)
        except Exception as exc:
            _log.exception("GET /api/harness failed")
            raise HTTPException(status_code=500, detail=f"Harness snapshot failed: {exc}")



    return router
