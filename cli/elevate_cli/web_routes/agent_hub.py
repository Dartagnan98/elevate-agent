"""Agent Hub and handoff routes for the Elevate dashboard."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from elevate_cli.web_routes.agent_hub_cortext_catalog import (
    _CORTEXT_AGENT_PACKS,
    _CORTEXT_NATIVE_REPLACEMENTS,
)

WEB_ACTOR = "human:web"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _clean_cortext_time(raw: Any, fallback: Any) -> str:
    """Return a valid HH:MM time, falling back when the config value is an
    unfilled ``{{template}}`` placeholder or otherwise malformed."""
    value = str(raw or "").strip()
    if value and not value.startswith("{{") and _TIME_RE.match(value):
        return value
    fb = str(fallback or "").strip()
    return fb if _TIME_RE.match(fb) else ""


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


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, item in value.items():
        lower = str(key).lower().replace("-", "_")
        if (
            ("token" in lower and not lower.endswith("_env"))
            or "secret" in lower
            or "api_key" in lower
            or "apikey" in lower
            or "password" in lower
            or lower in {"pm2", "daemon", "ipc", "pty", "file_inbox", "fileinbox", "fast_checker"}
            or lower.startswith(("daemon_", "pm2_", "ipc_", "pty_"))
        ):
            continue
        out[key] = _strip_secrets(item)
    return out


def _load_json(path: Path) -> dict[str, Any]:
    raw = _read_text(path)
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return _strip_secrets(parsed) if isinstance(parsed, dict) else {}


def _template_config_name(spec: dict[str, Any]) -> str:
    explicit = str(spec.get("template") or "").strip()
    if explicit:
        return explicit
    source = str(spec.get("source") or "").strip().strip("/")
    parts = source.split("/")
    if len(parts) >= 3 and parts[0] == "community" and parts[1] == "agents":
        return parts[2]
    return ""


def _merge_cortext_config(template: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    merged = {**template, **config}
    for key in ("approval_rules", "ecosystem", "memory", "safety", "runtime", "lifecycle"):
        left = template.get(key)
        right = config.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            merged[key] = {**left, **right}
    return merged


def _first_markdown_paragraph(text: str) -> str:
    for part in re.split(r"\n{2,}", text or ""):
        clean = re.sub(r"^#+\s*", "", part, flags=re.MULTILINE).strip()
        if clean:
            return clean
    return ""


def _markdown_section(text: str, heading: str) -> str:
    lines = str(text or "").splitlines()
    target = heading.strip().lower()
    start = -1
    for index, line in enumerate(lines):
        if re.sub(r"^#+\s*", "", line).strip().lower() == target:
            start = index
            break
    if start < 0:
        return ""
    body: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"^#{1,6}\s+\S", line):
            break
        body.append(line)
    return "\n".join(body).strip()


def _markdown_bullets(text: str) -> list[str]:
    out: list[str] = []
    for line in str(text or "").splitlines():
        match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if not match:
            continue
        item = re.sub(r"^\[[ xX]\]\s*", "", match.group(1).strip())
        if item:
            out.append(item)
    return out


def _merge_unique(*groups: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        values = group if isinstance(group, list) else re.split(r"[,\n]", group) if isinstance(group, str) else []
        for value in values:
            clean = str(value or "").strip()
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)
            out.append(clean)
    return out


def _extract_skill_refs(*texts: str) -> list[str]:
    refs: list[str] = []
    for text in texts:
        refs.extend(re.findall(r"(?:^|[/\"\s])skills/([a-z0-9._-]+)/SKILL\.md", text or "", flags=re.I))
        refs.extend(re.findall(r"\.claude/skills/([a-z0-9._-]+)/SKILL\.md", text or "", flags=re.I))
    return _merge_unique(refs)


def _extract_toolsets(tools_text: str, config: dict[str, Any]) -> list[str]:
    configured = _merge_unique(config.get("toolsets"), config.get("tool_sets"), config.get("enabled_toolsets"))
    inferred: list[str] = []
    lower = str(tools_text or "").lower()
    if re.search(r"\b(agent_handoff|handoff|send-message|check-inbox)\b", lower):
        inferred.append("agent_handoff")
    if re.search(r"\b(create-task|update-task|complete-task|list-tasks|create-approval|list-approvals|post-activity|log-event|heartbeat|update-heartbeat|read-all-heartbeats|create-experiment|run-experiment|evaluate-experiment|list-experiments|browse-catalog|list-skills)\b", lower):
        inferred.append("agent_bus")
    if re.search(r"\b(kb-query|memory|knowledge-base|knowledge base)\b", lower):
        inferred.append("memory")
    return _merge_unique(configured, inferred, ["agent_bus", "agent_handoff", "memory"])


def _goals_from_json(raw: str) -> Optional[dict[str, Any]]:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    obj = {"goals": parsed} if isinstance(parsed, list) else parsed if isinstance(parsed, dict) else {}
    raw_goals = obj.get("goals") if isinstance(obj.get("goals"), list) else obj.get("items") if isinstance(obj.get("items"), list) else []
    goals: list[dict[str, Any]] = []
    for index, item in enumerate(raw_goals):
        if isinstance(item, str):
            title = item.strip()
            progress = 0
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or item.get("goal") or item.get("text") or "").strip()
            try:
                progress = max(0, min(100, int(item.get("progress") or item.get("percent") or item.get("completion") or 0)))
            except Exception:
                progress = 0
        else:
            continue
        if title:
            goals.append({"title": title, "progress": progress, "order": index})
    daily_focus = str(obj.get("daily_focus") or obj.get("dailyFocus") or obj.get("focus") or "").strip()
    bottleneck = str(obj.get("bottleneck") or obj.get("blocker") or "").strip()
    if not goals and not daily_focus and not bottleneck:
        return None
    return {"daily_focus": daily_focus, "bottleneck": bottleneck, "goals": goals}


def _goals_from_markdown(raw: str) -> Optional[dict[str, Any]]:
    if not raw.strip():
        return None
    goals: list[dict[str, Any]] = []
    daily_focus = ""
    bottleneck = ""
    for line in raw.splitlines():
        clean = line.strip()
        if not clean:
            continue
        daily = re.match(r"^daily[_\s-]*focus\s*:\s*(.+)$", clean, flags=re.I)
        if daily:
            daily_focus = daily.group(1).strip()
            continue
        blocker = re.match(r"^bottleneck\s*:\s*(.+)$", clean, flags=re.I)
        if blocker:
            bottleneck = blocker.group(1).strip()
            continue
        match = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)$", clean)
        if not match:
            continue
        title = re.sub(r"^\[[ xX]\]\s*", "", match.group(1).strip())
        progress = 0
        progress_match = re.search(r"(?:^|\s)(\d{1,3})%\s*$", title)
        if progress_match:
            progress = max(0, min(100, int(progress_match.group(1))))
            title = title[:progress_match.start()].strip()
        if title and not re.match(r"^(daily[_\s-]*focus|bottleneck)", title, flags=re.I):
            goals.append({"title": title, "progress": progress, "order": len(goals)})
    if not goals and not daily_focus and not bottleneck:
        return None
    return {"daily_focus": daily_focus, "bottleneck": bottleneck, "goals": goals}


def _merge_goal_seed(*seeds: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    merged_goals: list[dict[str, Any]] = []
    seen: set[str] = set()
    daily_focus = ""
    bottleneck = ""
    for seed in seeds:
        if not seed:
            continue
        daily_focus = daily_focus or str(seed.get("daily_focus") or "")
        bottleneck = bottleneck or str(seed.get("bottleneck") or "")
        for goal in seed.get("goals") or []:
            title = str(goal.get("title") or "").strip() if isinstance(goal, dict) else ""
            key = title.lower()
            if not title or key in seen:
                continue
            seen.add(key)
            merged_goals.append({"title": title, "progress": int(goal.get("progress") or 0), "order": len(merged_goals)})
    if not merged_goals and not daily_focus and not bottleneck:
        return None
    return {"daily_focus": daily_focus, "bottleneck": bottleneck, "goals": merged_goals}


def _interval_to_schedule(value: str) -> str:
    clean = str(value or "").strip().lower()
    match = re.match(r"^(\d+)\s*h$", clean)
    if match:
        hours = max(1, int(match.group(1)))
        if hours == 24:
            return "0 8 * * *"
        return f"0 */{hours} * * *"
    return clean


def _cortext_cron_schedule(cron: dict[str, Any]) -> str:
    raw_cron = str(cron.get("cron") or "").strip()
    if raw_cron:
        return raw_cron
    interval = str(cron.get("interval") or "").strip()
    if interval:
        return f"every {interval}"
    return ""


def _config_enabled(value: Any, default: bool = False) -> bool:
    if isinstance(value, dict):
        if "enabled" in value:
            return bool(value.get("enabled"))
        return default
    if value is None:
        return default
    return bool(value)


def _cortext_runtime_from_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "runtime_type": str(config.get("runtime") or config.get("runtime_type") or "native").strip() or "native",
        "timezone": str(config.get("timezone") or "America/Vancouver").strip() or "America/Vancouver",
    }
    for source, target in (
        ("model", "model"),
        ("provider", "provider"),
        ("base_url", "base_url"),
        ("working_directory", "workdir"),
        ("workdir", "workdir"),
        ("ctx_warning_threshold", "context_warning_threshold"),
        ("context_warning_threshold", "context_warning_threshold"),
        ("ctx_handoff_threshold", "context_handoff_threshold"),
        ("context_handoff_threshold", "context_handoff_threshold"),
        ("codex_context_cap", "codex_context_cap"),
    ):
        value = config.get(source)
        if value not in (None, ""):
            runtime[target] = value
    if "context_warning_threshold" not in runtime:
        runtime["context_warning_threshold"] = 72
    if "context_handoff_threshold" not in runtime:
        runtime["context_handoff_threshold"] = 88
    return runtime


def _cortext_lifecycle_from_config(config: dict[str, Any]) -> dict[str, Any]:
    lifecycle: dict[str, Any] = {
        "startup_delay": config.get("startup_delay", 0),
        "max_session_seconds": config.get("max_session_seconds", 7200),
        "max_crashes_per_day": config.get("max_crashes_per_day", 3),
        "crash_window_seconds": 86400,
        "crash_window_max": config.get("max_crashes_per_day", 3),
        "telegram_polling": config.get("telegram_polling", True),
    }
    crash_window = config.get("crash_window")
    if isinstance(crash_window, dict):
        seconds = crash_window.get("seconds") or crash_window.get("duration_seconds") or crash_window.get("window_seconds")
        max_crashes = crash_window.get("max_crashes") or crash_window.get("max") or crash_window.get("count")
        if seconds is not None:
            lifecycle["crash_window_seconds"] = seconds
        if max_crashes is not None:
            lifecycle["crash_window_max"] = max_crashes
    return lifecycle


def _cortext_ecosystem_from_config(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, bool]:
    ecosystem = config.get("ecosystem") if isinstance(config.get("ecosystem"), dict) else {}
    return {
        "local_version_control": _config_enabled(ecosystem.get("local_version_control"), spec.get("id") in {"analyst"}),
        "upstream_sync": _config_enabled(ecosystem.get("upstream_sync"), spec.get("id") == "analyst"),
        "catalog_browse": _config_enabled(ecosystem.get("catalog_browse"), spec.get("id") == "analyst"),
        "community_publish": _config_enabled(ecosystem.get("community_publish"), False),
    }


def _automation_seeds_from_rules(
    rules: list[dict[str, Any]],
    *,
    agent_id: str,
    agent_name: str,
    runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for rule in rules:
        name = str(rule.get("name") or "").strip()
        if not name or name.lower() == "heartbeat":
            continue
        schedule = str(rule.get("cron") or "").strip()
        if not schedule and rule.get("interval"):
            schedule = f"every {rule.get('interval')}"
        prompt = str(rule.get("prompt") or "").strip()
        if not schedule or not prompt:
            continue
        seeds.append(
            {
                "name": f"{agent_name} - {name}",
                "schedule": schedule,
                "prompt": prompt,
                "deliver": "local",
                "agent": agent_id,
                "workdir": runtime.get("workdir") or None,
                "model": runtime.get("model") or None,
                "provider": runtime.get("provider") or None,
                "base_url": runtime.get("base_url") or None,
                "enabled": False,
                "origin": {
                    "type": "cortext-cron",
                    "agent": agent_id,
                    "source": "cortext-preset",
                    "cortext_name": name,
                },
            }
        )
    return seeds


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


    class AgentConfigPatch(BaseModel):
        name: Optional[str] = None
        enabled: Optional[bool] = None
        role: Optional[str] = None
        description: Optional[str] = None
        prompt: Optional[str] = None
        skills: Optional[list[str]] = None
        toolsets: Optional[list[str]] = None
        platforms: Optional[list[str]] = None
        session_sources: Optional[list[str]] = None
        runtime: Optional[Any] = None
        routing: Optional[Dict[str, Any]] = None
        safety: Optional[Dict[str, Any]] = None
        identity: Optional[Dict[str, Any]] = None
        soul: Optional[Dict[str, Any]] = None
        lifecycle: Optional[Dict[str, Any]] = None
        ecosystem: Optional[Dict[str, Any]] = None
        memory: Optional[Dict[str, Any]] = None
        metadata: Optional[Dict[str, Any]] = None
        runtime_type: Optional[str] = None
        model: Optional[str] = None
        provider: Optional[str] = None
        base_url: Optional[str] = None
        working_directory: Optional[str] = None
        timezone: Optional[str] = None
        ctx_warning_threshold: Optional[int] = None
        ctx_handoff_threshold: Optional[int] = None
        codex_context_cap: Optional[int] = None
        dangerously_skip_permissions: Optional[bool] = None
        day_mode_start: Optional[str] = None
        day_mode_end: Optional[str] = None
        communication_style: Optional[str] = None
        startup_delay: Optional[int] = None
        max_session_seconds: Optional[int] = None
        max_crashes_per_day: Optional[int] = None
        crash_window: Optional[Dict[str, Any]] = None
        telegram_polling: Optional[bool] = None
        approval_rules: Optional[Dict[str, Any]] = None


    class AgentConfigCreate(AgentConfigPatch):
        id: Optional[str] = None
        name: str
        memorySeed: Optional[Dict[str, Any]] = None
        memory_seed: Optional[Dict[str, Any]] = None


    class AgentWorkerAction(BaseModel):
        agentId: Optional[str] = None


    @router.get("/api/agents/peers")
    def get_agent_peers():
        """Return the list of Cortex OS-style peer agents on this Mac."""
        roots: list[Path] = []
        primary = os.environ.get("ELEVATE_PEERS_ROOT", "").strip()
        if primary:
            roots.append(Path(primary).expanduser())
        extra = os.environ.get("ELEVATE_PEERS_ROOTS", "").strip()
        if extra:
            for chunk in extra.split(":"):
                chunk = chunk.strip()
                if chunk:
                    roots.append(Path(chunk).expanduser())
        if not roots:
            fallback = Path.home() / "claudeclaw" / "orgs"
            if fallback.exists():
                roots.append(fallback)

        peers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            try:
                for config_path in sorted(root.glob("*/agents/*/config.json")):
                    try:
                        payload = json.loads(config_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    org = config_path.parents[2].name
                    agent = str(payload.get("agent_name") or config_path.parent.name)
                    key = f"{org}/{agent}"
                    if key in seen:
                        continue
                    seen.add(key)

                    role_hint = ""
                    for fname in ("AGENTS.md", "CLAUDE.md", "IDENTITY.md"):
                        agent_doc = config_path.parent / fname
                        if not agent_doc.exists():
                            continue
                        try:
                            for line in agent_doc.read_text(encoding="utf-8").splitlines():
                                stripped = line.strip()
                                if not stripped or stripped.startswith("#"):
                                    continue
                                if stripped.startswith("@"):
                                    continue
                                if len(stripped) > 140:
                                    stripped = stripped[:137] + "…"
                                role_hint = stripped
                                break
                            if role_hint:
                                break
                        except Exception:
                            continue

                    telegram_chat_id = ""
                    telegram_bot_handle = ""
                    telegram_preview = ""
                    telegram_source = ""

                    def _capture_token(value: str, source: str) -> None:
                        nonlocal telegram_preview, telegram_source
                        value = (value or "").strip().strip("'\"")
                        if not value or telegram_preview:
                            return
                        telegram_preview = "•••" + value[-4:] if len(value) >= 4 else "•••"
                        telegram_source = source

                    channels_blob = payload.get("channels")
                    if isinstance(channels_blob, dict):
                        tg = channels_blob.get("telegram")
                        if isinstance(tg, dict):
                            chat = tg.get("chat_id") or tg.get("chatId")
                            if chat:
                                telegram_chat_id = str(chat)
                            handle = tg.get("bot_handle") or tg.get("botHandle") or tg.get("username")
                            if handle:
                                telegram_bot_handle = str(handle)
                            for k in ("bot_token", "botToken", "token"):
                                if tg.get(k):
                                    _capture_token(str(tg[k]), f"{config_path.name}#channels.telegram.{k}")
                                    break

                    env_path = config_path.parent / ".env"
                    if env_path.exists():
                        try:
                            for raw in env_path.read_text(encoding="utf-8").splitlines():
                                line = raw.strip()
                                if not line or line.startswith("#"):
                                    continue
                                if "=" not in line:
                                    continue
                                k, _, v = line.partition("=")
                                k = k.strip()
                                v = v.strip().strip("'\"")
                                if k in ("TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN"):
                                    _capture_token(v, ".env#" + k)
                                elif k in ("TELEGRAM_CHAT_ID", "TG_CHAT_ID") and not telegram_chat_id:
                                    telegram_chat_id = v
                                elif k in ("TELEGRAM_BOT_USERNAME", "TG_BOT_USERNAME") and not telegram_bot_handle:
                                    telegram_bot_handle = v
                        except Exception:
                            pass

                    peers.append({
                        "org": org,
                        "name": agent,
                        "enabled": bool(payload.get("enabled", True)),
                        "workingDirectory": str(payload.get("working_directory") or ""),
                        "timezone": str(payload.get("timezone") or ""),
                        "communicationStyle": str(payload.get("communication_style") or ""),
                        "cronCount": len(payload.get("crons") or []),
                        "roleHint": role_hint,
                        "configPath": str(config_path),
                        "telegram": {
                            "configured": bool(telegram_preview or telegram_chat_id),
                            "botHandle": telegram_bot_handle,
                            "chatId": telegram_chat_id,
                            "tokenPreview": telegram_preview,
                            "source": telegram_source,
                        },
                    })
            except Exception:
                _log.exception("GET /api/agents/peers failed walking root=%s", root)
                continue
        return {"peers": peers, "rootsSearched": [str(r) for r in roots]}


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
