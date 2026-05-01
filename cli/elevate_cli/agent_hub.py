"""Local Agent Hub snapshot helpers for the Elevate dashboard.

The hub is intentionally read-only and local-first. It reflects what the
installed Elevate runtime can already see: gateway state, configured platform
connections, sessions, cron jobs, access profile, skills/toolsets, and the
holographic memory store. It never returns raw secrets.
"""

from __future__ import annotations

import copy
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from elevate_cli.access import PROFILE_LABELS, load_access_config
from elevate_cli.config import get_config_path, get_elevate_home, load_config, redact_key
from gateway.status import get_running_pid, read_runtime_status


DEFAULT_AGENT_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "executive-assistant",
        "name": "Executive Assistant",
        "role": "main",
        "description": "Primary Elevate assistant.",
        "enabled": True,
        "platforms": ["local", "telegram"],
        "session_sources": ["cli", "telegram", "api_server", "webhook", "cron"],
    },
    {
        "id": "admin",
        "name": "Admin",
        "role": "support",
        "description": "Operations, scheduling, and admin support.",
        "enabled": True,
        "platforms": ["local"],
        "session_sources": ["cli", "cron"],
    },
    {
        "id": "outreach",
        "name": "Outreach",
        "role": "support",
        "description": "Lead follow-up and relationship workflows.",
        "enabled": True,
        "platforms": ["local"],
        "session_sources": ["cli", "webhook"],
    },
    {
        "id": "marketing",
        "name": "Marketing",
        "role": "support",
        "description": "Listing, campaign, and brand workflows.",
        "enabled": True,
        "platforms": ["local"],
        "session_sources": ["cli", "cron"],
    },
    {
        "id": "social-media",
        "name": "Social Media",
        "role": "support",
        "description": "Social posts and content repurposing.",
        "enabled": True,
        "platforms": ["local"],
        "session_sources": ["cli"],
    },
)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _slug(text: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "agent"


def _model_summary(config: dict[str, Any]) -> dict[str, Any]:
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
        provider = str(model_cfg.get("provider") or "").strip()
        base_url = str(model_cfg.get("base_url") or "").strip()
        return {
            "model": model,
            "provider": provider,
            "base_url_configured": bool(base_url),
            "api_key_configured": bool(model_cfg.get("api_key")),
            "configured": bool(model or provider or base_url or model_cfg.get("api_key")),
        }
    model = str(model_cfg or "").strip()
    return {
        "model": model,
        "provider": "",
        "base_url_configured": False,
        "api_key_configured": False,
        "configured": bool(model),
    }


def _load_agent_defs(config: dict[str, Any]) -> list[dict[str, Any]]:
    hub_cfg = config.get("agent_hub")
    if not isinstance(hub_cfg, dict):
        hub_cfg = {}

    raw_agents = hub_cfg.get("agents")
    if raw_agents is None:
        raw_agents = config.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        raw_agents = [copy.deepcopy(agent) for agent in DEFAULT_AGENT_DEFS]

    agents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_agents):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("label") or "").strip()
        agent_id = str(raw.get("id") or raw.get("slug") or _slug(name)).strip()
        if not agent_id:
            agent_id = f"agent-{index + 1}"
        agent_id = _slug(agent_id)
        if agent_id in seen:
            suffix = 2
            base = agent_id
            while f"{base}-{suffix}" in seen:
                suffix += 1
            agent_id = f"{base}-{suffix}"
        seen.add(agent_id)
        if not name:
            name = agent_id.replace("-", " ").title()
        agents.append(
            {
                "id": agent_id,
                "name": name,
                "role": str(raw.get("role") or "support").strip().lower(),
                "description": str(raw.get("description") or "").strip(),
                "enabled": bool(raw.get("enabled", True)),
                "platforms": _as_list(raw.get("platforms")),
                "session_sources": _as_list(raw.get("session_sources")),
                "skills": _as_list(raw.get("skills")),
                "toolsets": _as_list(raw.get("toolsets")),
                "prompt": str(raw.get("prompt") or raw.get("system_prompt") or "").strip(),
                "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            }
        )
    return agents


def _session_summary(limit: int = 100) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": 0,
        "active": 0,
        "recent": [],
        "by_source": {},
        "by_day": {},
        "error": "",
    }
    try:
        from elevate_state import SessionDB

        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=limit, include_children=False)
            summary["total"] = db.session_count()
        finally:
            db.close()
    except Exception as exc:
        summary["error"] = str(exc)
        return summary

    now = time.time()
    recent: list[dict[str, Any]] = []
    by_source: dict[str, int] = {}
    by_day: dict[str, int] = {}
    active = 0
    for row in sessions:
        source = str(row.get("source") or "unknown")
        started = float(row.get("started_at") or 0)
        last_active = float(row.get("last_active") or started or 0)
        is_active = row.get("ended_at") is None and now - last_active < 300
        if is_active:
            active += 1
        day = datetime.fromtimestamp(started).date().isoformat() if started else "unknown"
        by_source[source] = by_source.get(source, 0) + 1
        by_day[day] = by_day.get(day, 0) + 1
        recent.append(
            {
                "id": row.get("id"),
                "title": row.get("title") or row.get("preview") or row.get("id"),
                "source": source,
                "started_at": started,
                "last_active": last_active,
                "is_active": is_active,
                "message_count": int(row.get("message_count") or 0),
                "tool_call_count": int(row.get("tool_call_count") or 0),
                "model": row.get("model") or "",
            }
        )

    summary["active"] = active
    summary["recent"] = recent[:20]
    summary["by_source"] = dict(sorted(by_source.items()))
    summary["by_day"] = dict(sorted(by_day.items(), reverse=True)[:14])
    return summary


def _platform_summary(runtime: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        from gateway.config import load_gateway_config
        from gateway.pairing import PairingStore

        gw_config = load_gateway_config()
        connected = {platform.value for platform in gw_config.get_connected_platforms()}
        pairing_store = PairingStore()
    except Exception as exc:
        return [{"name": "gateway", "error": str(exc)}]

    runtime_platforms = (runtime or {}).get("platforms") or {}
    platforms: list[dict[str, Any]] = []
    for platform, platform_cfg in sorted(
        gw_config.platforms.items(),
        key=lambda item: item[0].value,
    ):
        name = platform.value
        approved = []
        pending = []
        try:
            approved = pairing_store.list_approved(name)
            pending = pairing_store.list_pending(name)
        except Exception:
            approved = []
            pending = []
        runtime_state = runtime_platforms.get(name) if isinstance(runtime_platforms, dict) else {}
        home = platform_cfg.home_channel.to_dict() if platform_cfg.home_channel else None
        extra = platform_cfg.extra if isinstance(platform_cfg.extra, dict) else {}
        platforms.append(
            {
                "name": name,
                "enabled": bool(platform_cfg.enabled),
                "configured": name in connected,
                "token_configured": bool(platform_cfg.token or extra.get("token")),
                "api_key_configured": bool(platform_cfg.api_key),
                "home_channel": home,
                "reply_to_mode": platform_cfg.reply_to_mode,
                "runtime": runtime_state,
                "approved_users": len(approved),
                "pending_pairings": [
                    {
                        "code": item.get("code"),
                        "user_id": item.get("user_id"),
                        "user_name": item.get("user_name") or "",
                        "age_minutes": item.get("age_minutes"),
                    }
                    for item in pending
                ],
            }
        )
    return platforms


def _cron_summary() -> dict[str, Any]:
    try:
        from cron.jobs import list_jobs

        jobs = list_jobs(include_disabled=True)
    except Exception as exc:
        return {"total": 0, "enabled": 0, "paused": 0, "recent": [], "error": str(exc)}

    recent = []
    enabled = 0
    paused = 0
    for job in jobs:
        if bool(job.get("enabled", True)):
            enabled += 1
        else:
            paused += 1
        recent.append(
            {
                "id": job.get("id"),
                "name": job.get("name") or job.get("prompt", "")[:40],
                "schedule": job.get("schedule"),
                "enabled": bool(job.get("enabled", True)),
                "deliver": job.get("deliver") or "",
            }
        )
    return {
        "total": len(jobs),
        "enabled": enabled,
        "paused": paused,
        "recent": recent[:10],
        "error": "",
    }


def _skills_summary(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from elevate_cli.skills_config import get_disabled_skills
        from tools.skills_tool import _find_all_skills

        disabled = get_disabled_skills(config)
        skills = _find_all_skills(skip_disabled=True)
    except Exception as exc:
        return {"total": 0, "enabled": 0, "disabled": 0, "categories": {}, "error": str(exc)}

    categories: dict[str, int] = {}
    enabled = 0
    for skill in skills:
        if skill.get("name") not in disabled:
            enabled += 1
        category = str(skill.get("category") or "general")
        categories[category] = categories.get(category, 0) + 1
    return {
        "total": len(skills),
        "enabled": enabled,
        "disabled": len(skills) - enabled,
        "categories": dict(sorted(categories.items())),
        "error": "",
    }


def _toolsets_summary(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from elevate_cli.tools_config import (
            _get_effective_configurable_toolsets,
            _get_platform_tools,
        )

        enabled = set(
            _get_platform_tools(
                config,
                "cli",
                include_default_mcp_servers=False,
            )
        )
        known = [
            {"name": name, "label": label, "description": desc, "enabled": name in enabled}
            for name, label, desc in _get_effective_configurable_toolsets()
        ]
    except Exception as exc:
        return {"total": 0, "enabled": [], "known": [], "error": str(exc)}
    return {
        "total": len(known),
        "enabled": sorted(enabled),
        "known": known,
        "error": "",
    }


def _resolve_memory_db_path(config: dict[str, Any]) -> Path:
    plugin_cfg = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    memory_cfg = plugin_cfg.get("elevate-memory-store") if isinstance(plugin_cfg, dict) else {}
    if not isinstance(memory_cfg, dict):
        memory_cfg = {}
    default = get_elevate_home() / "memory_store.db"
    db_path = str(memory_cfg.get("db_path") or default)
    db_path = db_path.replace("$ELEVATE_HOME", str(get_elevate_home()))
    db_path = db_path.replace("${ELEVATE_HOME}", str(get_elevate_home()))
    return Path(db_path).expanduser()


def _sqlite_connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _memory_summary(config: dict[str, Any]) -> dict[str, Any]:
    memory_cfg = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    provider = str(memory_cfg.get("provider") or "builtin").strip()
    plugin_cfg = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    plugin_cfg = plugin_cfg.get("elevate-memory-store") if isinstance(plugin_cfg, dict) else {}
    plugin_cfg = plugin_cfg if isinstance(plugin_cfg, dict) else {}
    db_path = _resolve_memory_db_path(config)
    summary: dict[str, Any] = {
        "provider": provider,
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "facts": 0,
        "entities": 0,
        "embeddings": 0,
        "indexed_facts": 0,
        "journal": {
            "total": 0,
            "pending": 0,
            "processed": 0,
            "failed": 0,
            "active_session_count": 0,
            "session_segment_count": 0,
            "sessions": [],
        },
        "embedding": {
            "enabled": str(plugin_cfg.get("embedding_enabled", "false")).lower() in {"1", "true", "yes", "on"},
            "provider": str(plugin_cfg.get("embedding_provider") or "openai"),
            "model": str(plugin_cfg.get("embedding_model") or "text-embedding-3-small"),
            "api_key_env": str(plugin_cfg.get("embedding_api_key_env") or "OPENAI_API_KEY"),
        },
        "graph": {"nodes": [], "edges": []},
        "error": "",
    }
    if not db_path.exists():
        return summary

    try:
        conn = _sqlite_connect_readonly(db_path)
    except Exception as exc:
        summary["error"] = str(exc)
        return summary

    try:
        summary["facts"] = int(conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0])
        summary["entities"] = int(conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
        summary["embeddings"] = int(
            conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )
        summary["indexed_facts"] = int(
            conn.execute(
                "SELECT COUNT(DISTINCT target_id) FROM memory_embeddings WHERE target_type = 'fact'"
            ).fetchone()[0]
        )
        journal_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM memory_turn_journal
            GROUP BY status
            """
        ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in journal_rows}
        session_rows = conn.execute(
            """
            SELECT session_id,
                   session_day,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   MAX(created_at) AS latest_created_at
            FROM memory_turn_journal
            GROUP BY session_id, session_day
            ORDER BY latest_created_at DESC, session_id ASC, session_day DESC
            LIMIT 20
            """
        ).fetchall()
        sessions = [
            {
                "session_id": row["session_id"],
                "session_day": row["session_day"],
                "total": int(row["total"] or 0),
                "pending": int(row["pending"] or 0),
                "processed": int(row["processed"] or 0),
                "failed": int(row["failed"] or 0),
                "latest_created_at": row["latest_created_at"],
            }
            for row in session_rows
        ]
        summary["journal"] = {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "processed": counts.get("processed", 0),
            "failed": counts.get("failed", 0),
            "active_session_count": len({row["session_id"] for row in sessions}),
            "session_segment_count": len(sessions),
            "sessions": sessions,
        }
        summary["graph"] = _memory_graph(conn)
    except Exception as exc:
        summary["error"] = str(exc)
    finally:
        conn.close()
    return summary


def _memory_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    entity_rows = conn.execute(
        """
        SELECT e.entity_id, e.name, COUNT(fe.fact_id) AS fact_count
        FROM entities e
        LEFT JOIN fact_entities fe ON fe.entity_id = e.entity_id
        GROUP BY e.entity_id, e.name
        ORDER BY fact_count DESC, e.name ASC
        LIMIT 12
        """
    ).fetchall()
    fact_rows = conn.execute(
        """
        SELECT fact_id, content, category, trust_score
        FROM facts
        ORDER BY updated_at DESC, fact_id DESC
        LIMIT 10
        """
    ).fetchall()
    entity_ids = {int(row["entity_id"]) for row in entity_rows}
    fact_ids = {int(row["fact_id"]) for row in fact_rows}

    for row in entity_rows:
        nodes.append(
            {
                "id": f"entity:{row['entity_id']}",
                "label": row["name"],
                "type": "entity",
                "weight": int(row["fact_count"] or 0),
            }
        )
    for row in fact_rows:
        label = str(row["content"] or "").strip()
        nodes.append(
            {
                "id": f"fact:{row['fact_id']}",
                "label": label[:80],
                "type": "fact",
                "weight": float(row["trust_score"] or 0),
                "category": row["category"] or "general",
            }
        )

    if entity_ids and fact_ids:
        placeholders_entities = ",".join("?" for _ in entity_ids)
        placeholders_facts = ",".join("?" for _ in fact_ids)
        rows = conn.execute(
            f"""
            SELECT entity_id, fact_id
            FROM fact_entities
            WHERE entity_id IN ({placeholders_entities})
              AND fact_id IN ({placeholders_facts})
            LIMIT 40
            """,
            [*entity_ids, *fact_ids],
        ).fetchall()
        for row in rows:
            edges.append(
                {
                    "source": f"entity:{row['entity_id']}",
                    "target": f"fact:{row['fact_id']}",
                    "type": "mentions",
                }
            )
    return {"nodes": nodes, "edges": edges}


def _agent_summaries(
    config: dict[str, Any],
    *,
    gateway_running: bool,
    sessions: dict[str, Any],
    model: dict[str, Any],
) -> list[dict[str, Any]]:
    agents = _load_agent_defs(config)
    by_source = sessions.get("by_source") if isinstance(sessions.get("by_source"), dict) else {}
    recent_sessions = sessions.get("recent") if isinstance(sessions.get("recent"), list) else []
    global_toolsets = _as_list(config.get("toolsets"))

    result: list[dict[str, Any]] = []
    for agent in agents:
        sources = agent["session_sources"] or agent["platforms"] or ["cli"]
        source_set = set(sources)
        session_count = sum(int(by_source.get(source, 0) or 0) for source in source_set)
        active_count = sum(
            1
            for item in recent_sessions
            if item.get("source") in source_set and item.get("is_active")
        )
        if not agent["enabled"]:
            status = "disabled"
        elif not model.get("configured"):
            status = "needs_model"
        elif gateway_running and any(platform != "local" for platform in agent["platforms"]):
            status = "online"
        elif gateway_running:
            status = "ready"
        else:
            status = "offline"
        result.append(
            {
                **agent,
                "status": status,
                "session_count": session_count,
                "active_session_count": active_count,
                "toolsets": agent["toolsets"] or global_toolsets,
                "has_prompt": bool(agent.get("prompt")),
            }
        )
    return result


def _orchestration_summary() -> dict[str, Any]:
    try:
        from gateway.orchestration import get_orchestration_store

        return get_orchestration_store().snapshot(run_limit=20)
    except Exception as exc:
        return {
            "agents": [],
            "runs": [],
            "active_runs": 0,
            "error": str(exc),
        }


def build_agent_hub_snapshot() -> dict[str, Any]:
    """Return a redacted local snapshot for the dashboard Agent Hub."""
    config = load_config()
    runtime = read_runtime_status()
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    model = _model_summary(config)
    sessions = _session_summary()
    access = load_access_config(config)
    orchestration = _orchestration_summary()

    return {
        "generated_at": time.time(),
        "config_path": str(get_config_path()),
        "elevate_home": str(get_elevate_home()),
        "gateway": {
            "running": gateway_running,
            "pid": gateway_pid,
            "state": runtime.get("gateway_state") if runtime else None,
            "updated_at": runtime.get("updated_at") if runtime else None,
            "active_agents": runtime.get("active_agents") if runtime else 0,
            "exit_reason": runtime.get("exit_reason") if runtime else None,
        },
        "model": model,
        "access": {
            "profile": access.get("profile"),
            "label": PROFILE_LABELS.get(access.get("profile"), access.get("profile")),
            "affiliation": access.get("affiliation") or {},
            "entitlements": access.get("entitlements") or {},
        },
        "agents": _agent_summaries(
            config,
            gateway_running=gateway_running,
            sessions=sessions,
            model=model,
        ),
        "orchestration": orchestration,
        "platforms": _platform_summary(runtime),
        "sessions": sessions,
        "memory": _memory_summary(config),
        "cron": _cron_summary(),
        "skills": _skills_summary(config),
        "toolsets": _toolsets_summary(config),
        "redaction": {
            "example": redact_key("sk-example-secret"),
            "raw_secrets_returned": False,
        },
    }
