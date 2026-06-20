"""Agent Hub and handoff routes for the Elevate dashboard."""

import logging
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.agent_hub_agents import register_agent_config_routes
from elevate_cli.web_routes.agent_hub_cortext_packs import (
    build_cortext_agent_packs as _build_cortext_agent_packs,
    build_cortext_pack as _build_cortext_pack,
)
from elevate_cli.web_routes.agent_hub_handoffs import register_agent_handoff_routes
from elevate_cli.web_routes.agent_hub_peers import build_agent_peers
from elevate_cli.web_routes.agent_hub_runtime import register_agent_runtime_routes

WEB_ACTOR = "human:web"


def create_agent_hub_router(
    *,
    require_admin_setup_ready_for_launch: Callable[[], None],
    log: Optional[logging.Logger] = None,
) -> APIRouter:
    """Build routes for Agent Hub, agent handoffs, workers, and harness status."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/agents/peers")
    def get_agent_peers():
        return build_agent_peers(_log)


    @router.get("/api/agent-hub")
    async def get_agent_hub(
        lite: bool = False,
        include_memory_graph: Optional[bool] = None,
        include_session_total: Optional[bool] = None,
        include_orchestration: Optional[bool] = None,
        include_skills: Optional[bool] = None,
        include_toolsets: Optional[bool] = None,
        include_harness: Optional[bool] = None,
    ):
        """Return the local Agent Hub snapshot for the dashboard."""
        try:
            from elevate_cli.agent_hub import build_agent_hub_snapshot

            return build_agent_hub_snapshot(
                include_profiles=False,
                include_memory_graph=not lite if include_memory_graph is None else include_memory_graph,
                include_session_total=not lite if include_session_total is None else include_session_total,
                include_orchestration=not lite if include_orchestration is None else include_orchestration,
                include_skills=not lite if include_skills is None else include_skills,
                include_toolsets=not lite if include_toolsets is None else include_toolsets,
                include_harness=not lite if include_harness is None else include_harness,
                compact_orchestration=lite,
            )
        except Exception as exc:
            _log.exception("GET /api/agent-hub failed")
            raise HTTPException(status_code=500, detail=f"Agent Hub failed: {exc}")


    @router.get("/api/agent-hub/agent-packs")
    @router.get("/api/agent-hub/cortext-packs")  # legacy alias
    async def get_cortext_agent_packs():
        """Return installable agent-pack presets converted to native Agent Hub payloads."""
        try:
            return _build_cortext_agent_packs()
        except Exception as exc:
            _log.exception("GET /api/agent-hub/agent-packs failed")
            raise HTTPException(status_code=500, detail=f"Agent packs failed: {exc}")


    register_agent_config_routes(router, log=_log, web_actor=WEB_ACTOR)


    register_agent_handoff_routes(
        router,
        require_admin_setup_ready_for_launch=require_admin_setup_ready_for_launch,
        log=_log,
        web_actor=WEB_ACTOR,
    )


    register_agent_runtime_routes(router, log=_log, web_actor=WEB_ACTOR)


    return router
