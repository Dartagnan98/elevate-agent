"""Agent config route registration for Agent Hub."""

import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.agent_hub_models import AgentConfigCreate, AgentConfigPatch


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-")


def register_agent_config_routes(
    router: APIRouter,
    *,
    log: Optional[logging.Logger] = None,
    web_actor: str = "human:web",
) -> None:
    _log = log or logging.getLogger(__name__)

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
                        actor=web_actor,
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
    def cleanup_agent_install_artifacts(
        agent_id: str,
        delete_agent: bool = True,
        force: bool = False,
    ):
        """Remove the native artifacts created by the Agent Hub pack installer.

        This is intentionally narrower than a data wipe: it removes the custom
        Agent Hub config, same-named heartbeat surface, agent-onboarding tasks,
        and cortext-import memory facts. Other user-created tasks/memory remain.
        """
        target_id = slug(str(agent_id or ""))
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
