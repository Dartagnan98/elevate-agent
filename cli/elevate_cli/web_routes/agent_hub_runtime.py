"""Agent Worker and harness route registration for Agent Hub."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.agent_hub_models import AgentWorkerAction


def register_agent_runtime_routes(
    router: APIRouter,
    *,
    log: Optional[logging.Logger] = None,
    web_actor: str = "human:web",
) -> None:
    _log = log or logging.getLogger(__name__)

    @router.get("/api/agent-worker")
    async def get_agent_worker_status():
        try:
            from elevate_cli.agent_worker import snapshot

            return snapshot()
        except Exception as exc:
            _log.exception("GET /api/agent-worker failed")
            raise HTTPException(status_code=500, detail=f"Agent worker failed: {exc}")

    @router.post("/api/agent-worker/tick")
    async def post_agent_worker_tick(body: Optional[AgentWorkerAction] = None):
        try:
            from elevate_cli.agent_worker import tick

            return tick(actor=web_actor, agent_id=body.agentId if body else None)
        except Exception as exc:
            _log.exception("POST /api/agent-worker/tick failed")
            raise HTTPException(status_code=500, detail=f"Agent worker tick failed: {exc}")

    @router.post("/api/agent-worker/wake")
    async def post_agent_worker_wake(body: Optional[AgentWorkerAction] = None):
        try:
            from elevate_cli.agent_worker import request_wake

            return request_wake(
                reason="agent-hub",
                actor=web_actor,
                agent_id=body.agentId if body else None,
            )
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
