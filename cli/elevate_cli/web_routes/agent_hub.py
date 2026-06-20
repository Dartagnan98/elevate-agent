"""Agent Hub and handoff routes for the Elevate dashboard."""

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.agent_hub_cortext_catalog import (
    _CORTEXT_AGENT_PACKS,
    _CORTEXT_NATIVE_REPLACEMENTS,
)
from elevate_cli.web_routes.agent_hub_cortext_config import (
    automation_seeds_from_rules as _automation_seeds_from_rules,
    clean_cortext_time as _clean_cortext_time,
    cortext_cron_schedule as _cortext_cron_schedule,
    cortext_ecosystem_from_config as _cortext_ecosystem_from_config,
    cortext_lifecycle_from_config as _cortext_lifecycle_from_config,
    cortext_runtime_from_config as _cortext_runtime_from_config,
    interval_to_schedule as _interval_to_schedule,
    load_json as _load_json,
    merge_cortext_config as _merge_cortext_config,
    read_text as _read_text,
    template_config_name as _template_config_name,
)
from elevate_cli.web_routes.agent_hub_cortext_text import (
    extract_skill_refs as _extract_skill_refs,
    extract_toolsets as _extract_toolsets,
    first_markdown_paragraph as _first_markdown_paragraph,
    goals_from_json as _goals_from_json,
    goals_from_markdown as _goals_from_markdown,
    markdown_bullets as _markdown_bullets,
    markdown_section as _markdown_section,
    merge_goal_seed as _merge_goal_seed,
    merge_unique as _merge_unique,
)
from elevate_cli.web_routes.agent_hub_models import (
    AgentConfigCreate,
    AgentConfigPatch,
    AgentHandoffApproveCreate,
    AgentHandoffCreate,
    AgentHandoffDrain,
    AgentHandoffMessageCreate,
    AgentHandoffResultCreate,
    AgentWorkerAction,
)
from elevate_cli.web_routes.agent_hub_peers import build_agent_peers

WEB_ACTOR = "human:web"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-")


def _agent_presets_root() -> Optional[Path]:
    # Installable-pack content is bundled inside the app (cli/elevate_cli/
    # agent_presets) so packs resolve on every box. Resolution order: explicit
    # env override, then the bundled copy.
    bundled = Path(__file__).resolve().parent.parent / "agent_presets"
    candidates = [
        os.environ.get("ELEVATE_AGENT_PRESETS_ROOT"),
        str(bundled),
    ]
    for item in candidates:
        if not item:
            continue
        root = Path(item).expanduser()
        if (root / "community").exists() or (root / "templates").exists():
            return root
    return None


def _build_cortext_pack(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    source = str(spec["source"])
    source_path = root / source
    file_names = [
        "AGENTS.md",
        "IDENTITY.md",
        "SOUL.md",
        "SYSTEM.md",
        "USER.md",
        "TOOLS.md",
        "GUARDRAILS.md",
        "ONBOARDING.md",
        "HEARTBEAT.md",
        "GOALS.md",
        "MEMORY.md",
    ]
    if spec.get("skill_source"):
        files = {"HEARTBEAT.md": _read_text(source_path / "SKILL.md")}
        config: dict[str, Any] = {}
        source_exists = bool(files["HEARTBEAT.md"])
    else:
        files = {name: _read_text(source_path / name) for name in file_names}
        config = _load_json(source_path / "config.json")
        template_name = _template_config_name(spec)
        template_config_path = root / "templates" / template_name / "config.json" if template_name else None
        template_config = _load_json(template_config_path) if template_config_path else {}
        if template_config:
            config = _merge_cortext_config(template_config, config)
        source_exists = source_path.exists()
    goals_json = _read_text(source_path / "goals.json")

    agents = files.get("AGENTS.md", "")
    identity = files.get("IDENTITY.md", "")
    soul = files.get("SOUL.md", "")
    system = files.get("SYSTEM.md", "")
    user = files.get("USER.md", "")
    tools = files.get("TOOLS.md", "")
    guardrails = files.get("GUARDRAILS.md", "")
    onboarding = files.get("ONBOARDING.md", "")
    heartbeat = files.get("HEARTBEAT.md", "")
    goals_md = files.get("GOALS.md", "")
    memory = files.get("MEMORY.md", "")
    crons = config.get("crons") if isinstance(config.get("crons"), list) else []
    automation_rules = [
        {
            "name": str(cron.get("name") or "").strip(),
            "type": str(cron.get("type") or "recurring").strip(),
            "interval": str(cron.get("interval") or "").strip(),
            "cron": str(cron.get("cron") or "").strip(),
            "prompt": str(cron.get("prompt") or "").strip(),
            "native_store": "heartbeat" if str(cron.get("name") or "").strip() == "heartbeat" else "cron",
            "native_schedule": _cortext_cron_schedule(cron),
        }
        for cron in crons
        if isinstance(cron, dict)
    ]
    first_heartbeat = next((cron for cron in crons if isinstance(cron, dict) and str(cron.get("name") or "").strip() == "heartbeat"), None)
    first_schedule = ""
    if isinstance(first_heartbeat, dict):
        first_schedule = str(first_heartbeat.get("cron") or "").strip() or _interval_to_schedule(str(first_heartbeat.get("interval") or ""))

    prompt_parts = [
        f"# Agent Preset: {spec['name']}",
        spec.get("description", ""),
        system and f"# Imported SYSTEM\n{system}",
        user and f"# Imported USER\n{user}",
        agents and f"# Imported AGENTS\n{agents}",
        identity and f"# Imported IDENTITY\n{identity}",
        soul and f"# Imported SOUL\n{soul}",
        tools and f"# Imported TOOLS\n{tools}",
        guardrails and f"# Imported GUARDRAILS\n{guardrails}",
        onboarding and f"# Imported ONBOARDING\n{onboarding}",
        heartbeat and f"# Imported HEARTBEAT\n{heartbeat}",
        goals_md and f"# Imported GOALS\n{goals_md}",
        automation_rules and "# Imported AUTOMATION RULES\n" + "\n\n".join(
            f"## {rule['name']}\nSchedule: {rule.get('cron') or rule.get('interval') or 'manual'}\n{rule.get('prompt') or ''}"
            for rule in automation_rules
        ),
    ]
    skills = _merge_unique(
        config.get("skills"),
        _extract_skill_refs(agents, tools, guardrails, onboarding, heartbeat, system, user),
        ["theta-wave"] if spec.get("id") == "theta-wave" else [],
    )
    goals_seed = _merge_goal_seed(
        _goals_from_json(goals_json),
        _goals_from_markdown(goals_md),
        _goals_from_markdown(heartbeat),
        {
            "daily_focus": spec.get("day_mode", ""),
            "goals": [
                {"title": item, "progress": 0, "order": index}
                for index, item in enumerate(spec.get("owns") or [])
            ],
        },
    )
    memory_content = memory.strip() or "\n".join(
        [
            f"{spec['name']} installed from agent preset.",
            f"Owns: {', '.join(spec.get('owns') or [])}.",
            f"Escalates to: {spec.get('escalation_target') or 'executive-assistant'}.",
        ]
    )
    runtime_config = _cortext_runtime_from_config(config)
    lifecycle_config = _cortext_lifecycle_from_config(config)
    ecosystem_config = _cortext_ecosystem_from_config(config, spec)
    agent_id = str(spec["id"])
    agent_name = str(spec["name"])
    payload = {
        "id": spec["id"],
        "name": spec["name"],
        "role": spec.get("role") or "support",
        "description": spec.get("description") or _first_markdown_paragraph(identity) or f"{spec['name']} agent preset.",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "cron", "heartbeat", "api_server"],
        "skills": skills,
        "toolsets": _extract_toolsets(tools + "\n" + heartbeat + "\n" + onboarding, config),
        "prompt": "\n\n".join(str(part).strip() for part in prompt_parts if str(part or "").strip()),
        "runtime": runtime_config,
        "routing": {
            "owns": spec.get("owns") or [],
            "handoff_targets": spec.get("handoff_targets") or ["executive-assistant"],
            "escalation_target": spec.get("escalation_target") or "executive-assistant",
            "default_priority": "high" if spec.get("id") in {"security", "theta-wave"} else "normal",
        },
        "safety": {
            "approval_mode": "always_confirm" if spec.get("id") in {"security", "agentic-crm-assistant", "compliance-reviewer"} else "confirm_external_send",
            "always_ask": _merge_unique(
                ["external_send", "data_deletion", "deployment", "financial", "legal"],
                ["credential_change", "security_incident"] if spec.get("id") == "security" else [],
                ["experiment_cycle_change"] if spec.get("id") in {"analyst", "theta-wave"} else [],
            ),
            "never_ask": ["read_status", "summarize", "draft_only"],
            "dangerously_skip_permissions": False,
        },
        "identity": {
            "emoji": spec.get("emoji") or "A",
            "vibe": _first_markdown_paragraph(identity) or spec.get("description", ""),
            "work_style": _markdown_section(identity, "Work Style") or spec.get("day_mode", ""),
        },
        "soul": {
            "autonomy_rules": _markdown_section(soul, "Autonomy Rules") or _markdown_section(guardrails, "Autonomy Rules") or "\n".join(_markdown_bullets(guardrails)[:20]),
            "communication_style": _markdown_section(soul, "Communication Style") or _markdown_section(identity, "Communication Style") or "Concise, evidence-led, and approval-aware.",
            "day_mode": _markdown_section(soul, "Day Mode") or spec.get("day_mode", ""),
            "night_mode": _markdown_section(soul, "Night Mode") or spec.get("night_mode", ""),
            "day_mode_start": _clean_cortext_time(config.get("day_mode_start"), spec.get("day_start")),
            "day_mode_end": _clean_cortext_time(config.get("day_mode_end"), spec.get("day_end")),
            "core_truths": soul or guardrails or spec.get("description", ""),
        },
        "lifecycle": lifecycle_config,
        "ecosystem": ecosystem_config,
        "memory": {
            "mode": "shared_scoped",
            "scopes": spec.get("memory_scopes") or [spec["id"]],
            "sources": ["cortext-preset", spec["id"]],
            "recall_policy": "agent_scoped_recent",
            "write_policy": "append_events",
            "handoff_policy": "summary_only",
        },
        "metadata": {
            "cortext_preset": {
                "id": spec["id"],
                "source_path": str(source_path),
                "source_exists": source_exists,
                "template_config": str(template_config_path) if not spec.get("skill_source") and template_config_path and template_config_path.is_file() else "",
                "source_files": [name for name, text in files.items() if text.strip()] + (["config.json"] if config else []) + (["goals.json"] if goals_json.strip() else []),
                "ignored_files": ["CLAUDE.md", ".env", ".env.example", "PM2", "daemon", "IPC", "PTY"],
                "native_replacements": _CORTEXT_NATIVE_REPLACEMENTS,
                "automation_rules": automation_rules,
                "automation_store": "Elevate heartbeat/crons/tasks; no per-agent cron config store",
                "theta_wave_native_cron": spec.get("id") == "theta-wave",
            }
        },
        "heartbeatSurfaceSeed": {
            "schedule": first_schedule or "0 */4 * * *",
            "goal": (
                str(first_heartbeat.get("prompt") or "").strip()
                if isinstance(first_heartbeat, dict)
                else ""
            ) or spec.get("day_mode") or spec.get("description") or f"{spec['name']} work loop",
            "experiment": {
                "every_n_runs": 7,
                "metric": f"{spec['id']}_quality",
                "metric_type": "qualitative",
                "direction": "higher",
                "window": "7d",
                "measurement": "Self-score 1-10 against the preset's stated goals and cite evidence from Tasks, Activity, Comms, and handoffs.",
                "approval_required": spec.get("id") in {"security", "theta-wave", "analyst"},
            },
            "config": {
                "runtime": runtime_config.get("runtime_type"),
                "model": runtime_config.get("model"),
                "provider": runtime_config.get("provider"),
                "base_url": runtime_config.get("base_url"),
                "workdir": runtime_config.get("workdir"),
                "timezone": runtime_config.get("timezone"),
                "day_mode_start": _clean_cortext_time(config.get("day_mode_start"), spec.get("day_start")),
                "day_mode_end": _clean_cortext_time(config.get("day_mode_end"), spec.get("day_end")),
                "communication_style": str(config.get("communication_style") or ""),
                "approval_rules": config.get("approval_rules") if isinstance(config.get("approval_rules"), dict) else {},
                "startup_delay": lifecycle_config.get("startup_delay"),
                "max_session_seconds": lifecycle_config.get("max_session_seconds"),
                "max_crashes_per_day": lifecycle_config.get("max_crashes_per_day"),
                "telegram_polling": lifecycle_config.get("telegram_polling"),
                "agent_id": agent_id,
            },
        },
        "cronSeeds": _automation_seeds_from_rules(
            automation_rules,
            agent_id=agent_id,
            agent_name=agent_name,
            runtime=runtime_config,
        ),
        "heartbeatGoalsSeed": goals_seed,
        "onboardingTaskSeed": {
            "title": f"Finish {spec['name']} setup",
            "description": "\n\n".join(
                part
                for part in [
                    f"Installed from agent preset {source}.",
                    "Review runtime/model inheritance, Telegram lane, routing targets, safety rules, day/night soul, memory scopes, and heartbeat cadence.",
                    automation_rules and "Automation rules imported as native Elevate metadata. Use Heartbeat/Cron pages with this agent selected for any active schedule changes.",
                    onboarding[:4000],
                ]
                if part
            ),
        },
        "memorySeed": {
            "content": memory_content[:40000],
            "source": f"cortext-preset:{spec['id']}",
            "scopes": spec.get("memory_scopes") or [spec["id"]],
        },
    }
    return {
        "id": spec["id"],
        "name": spec["name"],
        "role": spec.get("role") or "support",
        "description": payload["description"],
        "sourcePath": str(source_path),
        "sourceExists": source_exists,
        "includes": spec.get("includes") or [],
        "automationCount": len(automation_rules),
        "payload": payload,
    }


def _bundled_presets_root() -> Path:
    return Path(__file__).resolve().parent.parent / "agent_presets"


def _build_cortext_agent_packs() -> dict[str, Any]:
    root = _agent_presets_root()
    if root is None:
        return {"root": None, "packs": []}
    # Per-pack root: the Elevate-native packs live in the bundled agent_presets/.
    # Fall back to the bundled copy whenever the resolved root doesn't carry a
    # pack's source dir, so an env override can't hide bundled packs.
    bundled = _bundled_presets_root()
    packs = []
    for spec in _CORTEXT_AGENT_PACKS:
        pack_root = root
        source = str(spec.get("source") or "").strip().strip("/")
        if source and not (root / source).exists() and (bundled / source).exists():
            pack_root = bundled
        packs.append(_build_cortext_pack(pack_root, spec))
    return {"root": str(root), "packs": packs}


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
