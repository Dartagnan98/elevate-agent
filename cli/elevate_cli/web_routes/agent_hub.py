"""Agent Hub and handoff routes for the Elevate dashboard."""

import logging
import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.agent_hub_cortext_packs import (
    agent_presets_root as _agent_presets_root,
    build_cortext_agent_packs as _build_cortext_agent_packs,
    build_cortext_pack as _build_cortext_pack,
    bundled_presets_root as _bundled_presets_root,
)
from elevate_cli.web_routes.agent_hub_models import (
    AgentConfigCreate,
    AgentConfigPatch,
    AgentWorkerAction,
)
from elevate_cli.web_routes.agent_hub_handoffs import register_agent_handoff_routes
from elevate_cli.web_routes.agent_hub_peers import build_agent_peers

WEB_ACTOR = "human:web"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-")


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


    @router.post("/api/agent-hub/agents")
    async def create_agent_hub_agent(body: AgentConfigCreate):
        """Create a custom Agent Hub agent config entry."""
        payload = body.model_dump(exclude_unset=True, exclude_none=False)
        memory_seed = payload.pop("memorySeed", None) or payload.pop("memory_seed", None)
        try:
            from elevate_cli.agent_hub import create_agent_config, seed_agent_memory

            created = create_agent_config(payload)
            if isinstance(memory_seed, dict) and str(memory_seed.get("content") or "").strip():
                try:
                    created["memorySeedSummary"] = seed_agent_memory(
                        str(created.get("id") or payload.get("id") or payload.get("name") or ""),
                        memory_seed.get("content"),
                        source=str(memory_seed.get("source") or "cortext-import"),
                        actor=WEB_ACTOR,
                        scopes=memory_seed.get("scopes"),
                    )
                except Exception as exc:
                    _log.exception("Agent memory seed failed")
                    created["memorySeedError"] = str(exc)
            return created
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent-hub/agents failed")
            raise HTTPException(status_code=500, detail=f"Agent create failed: {exc}")


    @router.patch("/api/agent-hub/agents/{agent_id}")
    async def patch_agent_hub_agent(agent_id: str, body: AgentConfigPatch):
        """Update an Agent Hub agent's config (skills, toolsets, prompt, enabled, etc)."""
        patch = body.model_dump(exclude_unset=True, exclude_none=False)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")
        try:
            from elevate_cli.agent_hub import update_agent_config

            result = update_agent_config(agent_id, patch)
            # Installing/activating a worker agent gives it its own heartbeat
            # surface (own theta-wave cycle + learnings), seeded opt-in/off.
            if patch.get("enabled") is True:
                try:
                    from cron.jobs import ensure_agent_heartbeat

                    ensure_agent_heartbeat(agent_id, enabled=False)
                except Exception:
                    _log.exception("ensure_agent_heartbeat failed for %s", agent_id)
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PATCH /api/agent-hub/agents/%s failed", agent_id)
            raise HTTPException(status_code=500, detail=f"Agent update failed: {exc}")


    @router.delete("/api/agent-hub/agents/{agent_id}/install-artifacts")
    async def cleanup_agent_install_artifacts(
        agent_id: str,
        delete_agent: bool = True,
        force: bool = False,
    ):
        """Remove the native artifacts created by the Agent Hub pack installer.

        This is intentionally narrower than a data wipe: it removes the custom
        Agent Hub config, same-named heartbeat surface, agent-onboarding tasks,
        and cortext-import memory facts. Other user-created tasks/memory remain.
        """
        target_id = _slug(str(agent_id or ""))
        if not target_id:
            raise HTTPException(status_code=400, detail="agent id is required")
        try:
            from cron.jobs import delete_surface
            from elevate_cli.agent_hub import (
                _is_builtin_agent_id,
                delete_agent_config,
                delete_agent_memory_seed,
                get_agent_def,
            )
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            if _is_builtin_agent_id(target_id) and not force:
                raise HTTPException(status_code=400, detail="built-in agents cannot be cleanup-deleted")

            agent = get_agent_def(target_id)
            report: dict[str, Any] = {
                "ok": True,
                "id": target_id,
                "removed": {
                    "agent": False,
                    "heartbeatSurface": None,
                    "onboardingTasks": [],
                    "memory": None,
                },
            }

            try:
                report["removed"]["heartbeatSurface"] = delete_surface(target_id, force=bool(force))
            except LookupError:
                report["removed"]["heartbeatSurface"] = {"ok": False, "surface": target_id, "missing": True}

            with connect() as conn:
                for task in st.list_tasks(conn, assignee=target_id):
                    if str(task.get("project") or "") != "agent-onboarding":
                        continue
                    task_id = str(task.get("id") or "")
                    if task_id and st.delete_task(conn, task_id):
                        report["removed"]["onboardingTasks"].append(task_id)

            report["removed"]["memory"] = delete_agent_memory_seed(target_id, source="cortext-import")

            if delete_agent:
                if agent is None:
                    report["removed"]["agent"] = False
                else:
                    delete_agent_config(target_id)
                    report["removed"]["agent"] = True
            return report
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("DELETE /api/agent-hub/agents/%s/install-artifacts failed", agent_id)
            raise HTTPException(status_code=500, detail=f"Agent cleanup failed: {exc}")


    @router.delete("/api/agent-hub/agents/{agent_id}")
    async def delete_agent_hub_agent(agent_id: str):
        """Delete a custom Agent Hub agent config entry."""
        try:
            from elevate_cli.agent_hub import delete_agent_config

            return delete_agent_config(agent_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("DELETE /api/agent-hub/agents/%s failed", agent_id)
            raise HTTPException(status_code=500, detail=f"Agent delete failed: {exc}")


    register_agent_handoff_routes(
        router,
        require_admin_setup_ready_for_launch=require_admin_setup_ready_for_launch,
        log=_log,
        web_actor=WEB_ACTOR,
    )


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

            return tick(actor=WEB_ACTOR, agent_id=body.agentId if body else None)
        except Exception as exc:
            _log.exception("POST /api/agent-worker/tick failed")
            raise HTTPException(status_code=500, detail=f"Agent worker tick failed: {exc}")


    @router.post("/api/agent-worker/wake")
    async def post_agent_worker_wake(body: Optional[AgentWorkerAction] = None):
        try:
            from elevate_cli.agent_worker import request_wake

            return request_wake(
                reason="agent-hub",
                actor=WEB_ACTOR,
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



    return router
