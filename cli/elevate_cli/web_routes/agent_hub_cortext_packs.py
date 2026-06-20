"""Cortext agent-pack conversion helpers for Agent Hub routes."""

import os
from pathlib import Path
from typing import Any, Optional

from elevate_cli.web_routes.agent_hub_cortext_catalog import (
    _CORTEXT_AGENT_PACKS,
    _CORTEXT_NATIVE_REPLACEMENTS,
)
from elevate_cli.web_routes.agent_hub_cortext_config import (
    automation_seeds_from_rules,
    clean_cortext_time,
    cortext_cron_schedule,
    cortext_ecosystem_from_config,
    cortext_lifecycle_from_config,
    cortext_runtime_from_config,
    interval_to_schedule,
    load_json,
    merge_cortext_config,
    read_text,
    template_config_name,
)
from elevate_cli.web_routes.agent_hub_cortext_text import (
    extract_skill_refs,
    extract_toolsets,
    first_markdown_paragraph,
    goals_from_json,
    goals_from_markdown,
    markdown_bullets,
    markdown_section,
    merge_goal_seed,
    merge_unique,
)


def agent_presets_root() -> Optional[Path]:
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


def build_cortext_pack(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
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
        files = {"HEARTBEAT.md": read_text(source_path / "SKILL.md")}
        config: dict[str, Any] = {}
        source_exists = bool(files["HEARTBEAT.md"])
    else:
        files = {name: read_text(source_path / name) for name in file_names}
        config = load_json(source_path / "config.json")
        template_name = template_config_name(spec)
        template_config_path = root / "templates" / template_name / "config.json" if template_name else None
        template_config = load_json(template_config_path) if template_config_path else {}
        if template_config:
            config = merge_cortext_config(template_config, config)
        source_exists = source_path.exists()
    goals_json = read_text(source_path / "goals.json")

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
            "native_schedule": cortext_cron_schedule(cron),
        }
        for cron in crons
        if isinstance(cron, dict)
    ]
    first_heartbeat = next((cron for cron in crons if isinstance(cron, dict) and str(cron.get("name") or "").strip() == "heartbeat"), None)
    first_schedule = ""
    if isinstance(first_heartbeat, dict):
        first_schedule = str(first_heartbeat.get("cron") or "").strip() or interval_to_schedule(str(first_heartbeat.get("interval") or ""))

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
    skills = merge_unique(
        config.get("skills"),
        extract_skill_refs(agents, tools, guardrails, onboarding, heartbeat, system, user),
        ["theta-wave"] if spec.get("id") == "theta-wave" else [],
    )
    goals_seed = merge_goal_seed(
        goals_from_json(goals_json),
        goals_from_markdown(goals_md),
        goals_from_markdown(heartbeat),
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
    runtime_config = cortext_runtime_from_config(config)
    lifecycle_config = cortext_lifecycle_from_config(config)
    ecosystem_config = cortext_ecosystem_from_config(config, spec)
    agent_id = str(spec["id"])
    agent_name = str(spec["name"])
    payload = {
        "id": spec["id"],
        "name": spec["name"],
        "role": spec.get("role") or "support",
        "description": spec.get("description") or first_markdown_paragraph(identity) or f"{spec['name']} agent preset.",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "cron", "heartbeat", "api_server"],
        "skills": skills,
        "toolsets": extract_toolsets(tools + "\n" + heartbeat + "\n" + onboarding, config),
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
            "always_ask": merge_unique(
                ["external_send", "data_deletion", "deployment", "financial", "legal"],
                ["credential_change", "security_incident"] if spec.get("id") == "security" else [],
                ["experiment_cycle_change"] if spec.get("id") in {"analyst", "theta-wave"} else [],
            ),
            "never_ask": ["read_status", "summarize", "draft_only"],
            "dangerously_skip_permissions": False,
        },
        "identity": {
            "emoji": spec.get("emoji") or "A",
            "vibe": first_markdown_paragraph(identity) or spec.get("description", ""),
            "work_style": markdown_section(identity, "Work Style") or spec.get("day_mode", ""),
        },
        "soul": {
            "autonomy_rules": markdown_section(soul, "Autonomy Rules") or markdown_section(guardrails, "Autonomy Rules") or "\n".join(markdown_bullets(guardrails)[:20]),
            "communication_style": markdown_section(soul, "Communication Style") or markdown_section(identity, "Communication Style") or "Concise, evidence-led, and approval-aware.",
            "day_mode": markdown_section(soul, "Day Mode") or spec.get("day_mode", ""),
            "night_mode": markdown_section(soul, "Night Mode") or spec.get("night_mode", ""),
            "day_mode_start": clean_cortext_time(config.get("day_mode_start"), spec.get("day_start")),
            "day_mode_end": clean_cortext_time(config.get("day_mode_end"), spec.get("day_end")),
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
                "day_mode_start": clean_cortext_time(config.get("day_mode_start"), spec.get("day_start")),
                "day_mode_end": clean_cortext_time(config.get("day_mode_end"), spec.get("day_end")),
                "communication_style": str(config.get("communication_style") or ""),
                "approval_rules": config.get("approval_rules") if isinstance(config.get("approval_rules"), dict) else {},
                "startup_delay": lifecycle_config.get("startup_delay"),
                "max_session_seconds": lifecycle_config.get("max_session_seconds"),
                "max_crashes_per_day": lifecycle_config.get("max_crashes_per_day"),
                "telegram_polling": lifecycle_config.get("telegram_polling"),
                "agent_id": agent_id,
            },
        },
        "cronSeeds": automation_seeds_from_rules(
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


def bundled_presets_root() -> Path:
    return Path(__file__).resolve().parent.parent / "agent_presets"


def build_cortext_agent_packs() -> dict[str, Any]:
    root = agent_presets_root()
    if root is None:
        return {"root": None, "packs": []}
    # Per-pack root: the Elevate-native packs live in the bundled agent_presets/.
    # Fall back to the bundled copy whenever the resolved root doesn't carry a
    # pack's source dir, so an env override can't hide bundled packs.
    bundled = bundled_presets_root()
    packs = []
    for spec in _CORTEXT_AGENT_PACKS:
        pack_root = root
        source = str(spec.get("source") or "").strip().strip("/")
        if source and not (root / source).exists() and (bundled / source).exists():
            pack_root = bundled
        packs.append(build_cortext_pack(pack_root, spec))
    return {"root": str(root), "packs": packs}
