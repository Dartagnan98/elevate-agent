"""Elevate harness status and benchmark helpers.

The harness view is a compact, local-first health model inspired by mature
agent harnesses: one gateway/server, visible agent lifecycle state, skill/tool
manifest posture, memory readiness, safety posture, and payload measurements.
It intentionally does not start agents or execute tools.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from elevate_cli.config import get_elevate_home, load_config
from gateway.status import get_running_pid


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _model_name(config: dict[str, Any]) -> str:
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        return str(model_cfg.get("default") or model_cfg.get("model") or "gpt-5").strip() or "gpt-5"
    return str(model_cfg or "gpt-5").strip() or "gpt-5"


def _safe_count(value: Any, key: str, default: int = 0) -> int:
    if isinstance(value, dict):
        try:
            return int(value.get(key) or default)
        except (TypeError, ValueError):
            return default
    return default


def _safe_list_count(value: Any, key: str) -> int:
    if not isinstance(value, dict):
        return 0
    items = value.get(key)
    return len(items) if isinstance(items, list) else 0


def _memory_pipeline_summary(memory: dict[str, Any], embedding: dict[str, Any]) -> dict[str, Any]:
    """Summarize the observable memory pipeline from local journal state.

    Prefer the live holographic activity stream when present. Fall back to a
    journal-derived summary so fresh installs still show useful posture.
    """
    activity = memory.get("activity") if isinstance(memory.get("activity"), dict) else {}
    activity_pipeline = (
        activity.get("pipeline")
        if isinstance(activity.get("pipeline"), dict)
        else {}
    )
    if activity_pipeline and activity_pipeline.get("derived_from_journal") is False:
        journal_for_activity = memory.get("journal") if isinstance(memory.get("journal"), dict) else {}
        return {
            "derived_from_journal": False,
            "state": str(activity.get("state") or "idle"),
            "search": str(activity_pipeline.get("search") or "skipped"),
            "verify": str(activity_pipeline.get("verify") or "skipped"),
            "inject": str(activity_pipeline.get("inject") or "skipped"),
            "maintain": str(activity_pipeline.get("maintain") or "skipped"),
            "active": bool(activity_pipeline.get("active")),
            "backlog": _safe_count(journal_for_activity, "pending"),
            "failure_count": _safe_count(journal_for_activity, "failed"),
            "indexed_facts": _safe_count(memory, "indexed_facts"),
            "facts": _safe_count(memory, "facts"),
            "last_step": str(activity_pipeline.get("last_step") or ""),
            "updated_at": str(activity.get("updated_at") or ""),
            "recent_events": (
                activity.get("recent_events")
                if isinstance(activity.get("recent_events"), list)
                else []
            )[:10],
        }

    journal = memory.get("journal") if isinstance(memory.get("journal"), dict) else {}
    pending = _safe_count(journal, "pending")
    processed = _safe_count(journal, "processed")
    failed = _safe_count(journal, "failed")
    embeddings_enabled = _truthy(embedding.get("enabled"))
    indexed_facts = _safe_count(memory, "indexed_facts")
    facts = _safe_count(memory, "facts")

    if failed:
        state = "error"
    elif pending:
        state = "backlog"
    elif processed or indexed_facts:
        state = "idle"
    else:
        state = "not_started"

    return {
        "derived_from_journal": True,
        "state": state,
        "search": "done" if embeddings_enabled else "skipped",
        "verify": "pending" if pending else ("done" if processed else "skipped"),
        "inject": "done" if indexed_facts or processed else "skipped",
        "maintain": "error" if failed else ("pending" if pending else "done"),
        "active": bool(pending or failed),
        "backlog": pending,
        "failure_count": failed,
        "indexed_facts": indexed_facts,
        "facts": facts,
        "last_step": "",
        "updated_at": "",
        "recent_events": [],
    }


def _performance_profiles(config: dict[str, Any]) -> dict[str, Any]:
    """Measure static prompt/tool payload profiles without live model calls."""
    old_skip_mcp = os.environ.get("ELEVATE_SKIP_MCP_DISCOVERY")
    os.environ["ELEVATE_SKIP_MCP_DISCOVERY"] = "1"
    try:
        from scripts.elevate_context_efficiency import _scenario_rows
    except Exception as exc:
        if old_skip_mcp is None:
            os.environ.pop("ELEVATE_SKIP_MCP_DISCOVERY", None)
        else:
            os.environ["ELEVATE_SKIP_MCP_DISCOVERY"] = old_skip_mcp
        return {
            "available": False,
            "error": f"context efficiency harness unavailable: {exc}",
            "profiles": [],
        }

    try:
        rows = _scenario_rows(
            model=_model_name(config),
            baseline_toolsets=["elevate-cli"],
            include_local_context=False,
            include_memory=False,
            min_savings_override=None,
            no_assert=True,
        )
    except Exception as exc:
        if old_skip_mcp is None:
            os.environ.pop("ELEVATE_SKIP_MCP_DISCOVERY", None)
        else:
            os.environ["ELEVATE_SKIP_MCP_DISCOVERY"] = old_skip_mcp
        return {
            "available": False,
            "error": f"context efficiency measurement failed: {exc}",
            "profiles": [],
        }
    finally:
        if old_skip_mcp is None:
            os.environ.pop("ELEVATE_SKIP_MCP_DISCOVERY", None)
        else:
            os.environ["ELEVATE_SKIP_MCP_DISCOVERY"] = old_skip_mcp

    profiles = []
    for row in rows:
        profiles.append(
            {
                "name": row.name,
                "toolsets": row.toolsets,
                "loaded_tools": row.loaded_tools,
                "requested_tools": row.requested_tools,
                "system_prompt_tokens": row.system_prompt_tokens,
                "tool_schema_tokens": row.tool_schema_tokens,
                "request_tokens": row.request_tokens,
                "savings_pct": row.savings_pct,
                "issues": len(row.prompt_issues) + len(row.schema_issues),
            }
        )

    baseline = profiles[0] if profiles else {}
    focused = [profile for profile in profiles[1:] if isinstance(profile.get("savings_pct"), (int, float))]
    best = max(focused, key=lambda item: item.get("savings_pct") or 0.0, default=None)
    worst = min(focused, key=lambda item: item.get("savings_pct") or 0.0, default=None)
    return {
        "available": True,
        "error": "",
        "model": _model_name(config),
        "baseline_request_tokens": baseline.get("request_tokens", 0),
        "best_profile": best,
        "worst_profile": worst,
        "profiles": profiles,
    }


def build_harness_snapshot(
    *,
    config: dict[str, Any] | None = None,
    sessions: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    skills: dict[str, Any] | None = None,
    toolsets: dict[str, Any] | None = None,
    orchestration: dict[str, Any] | None = None,
    include_profiles: bool = True,
) -> dict[str, Any]:
    """Return a redacted snapshot of the Elevate harness posture."""
    config = config if isinstance(config, dict) else load_config()
    if not isinstance(sessions, dict):
        try:
            from elevate_cli.agent_hub import _session_summary

            sessions = _session_summary()
        except Exception:
            sessions = {}
    if not isinstance(memory, dict):
        try:
            from elevate_cli.agent_hub import _memory_summary

            memory = _memory_summary(config)
        except Exception:
            memory = {}
    if not isinstance(skills, dict):
        try:
            from elevate_cli.agent_hub import _skills_summary

            skills = _skills_summary(config)
        except Exception:
            skills = {}
    if not isinstance(toolsets, dict):
        try:
            from elevate_cli.agent_hub import _toolsets_summary

            toolsets = _toolsets_summary(config)
        except Exception:
            toolsets = {}
    if not isinstance(orchestration, dict):
        try:
            from elevate_cli.agent_hub import _orchestration_summary

            orchestration = _orchestration_summary()
        except Exception:
            orchestration = {}

    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    configured_platforms = []
    try:
        from gateway.config import load_gateway_config

        gw_config = load_gateway_config()
        configured_platforms = [platform.value for platform in gw_config.get_connected_platforms()]
    except Exception:
        configured_platforms = []

    agents = orchestration.get("agents") if isinstance(orchestration.get("agents"), list) else []
    runs = orchestration.get("runs") if isinstance(orchestration.get("runs"), list) else []
    recent_events = (
        orchestration.get("recent_events")
        if isinstance(orchestration.get("recent_events"), list)
        else []
    )
    active_runs = [
        run
        for run in runs
        if str(run.get("status") or "").lower() in {"queued", "running", "blocked", "waiting_for_approval"}
    ]
    coordinator = next(
        (
            agent
            for agent in agents
            if agent.get("agent_id") == "executive-assistant" or agent.get("tier") == "primary"
        ),
        None,
    )
    route_labeled_runs = [run for run in runs if run.get("route_label") or run.get("routing_label")]

    memory_journal = memory.get("journal") if isinstance(memory.get("journal"), dict) else {}
    embedding = memory.get("embedding") if isinstance(memory.get("embedding"), dict) else {}
    graph = memory.get("graph") if isinstance(memory.get("graph"), dict) else {}
    graph_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    graph_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    memory_pipeline = _memory_pipeline_summary(memory, embedding)
    plan_graph = orchestration.get("plan_graph") if isinstance(orchestration.get("plan_graph"), dict) else {}

    approvals_cfg = config.get("approvals") if isinstance(config.get("approvals"), dict) else {}
    safety_cfg = config.get("safety") if isinstance(config.get("safety"), dict) else {}
    external_policy = str(
        safety_cfg.get("external_actions")
        or safety_cfg.get("human_communication")
        or "advisory"
    ).strip().lower()
    enabled_toolsets = toolsets.get("enabled") if isinstance(toolsets.get("enabled"), list) else []
    messaging_enabled = "messaging" in enabled_toolsets or any(
        str(item).startswith("elevate-") for item in enabled_toolsets
    )

    recommendations: list[str] = []
    if not gateway_running:
        recommendations.append("Start the gateway so Telegram, API server, and Agent Hub share one live runtime.")
    if not coordinator:
        recommendations.append("Seed the Executive Assistant orchestration agent as the visible coordinator.")
    if messaging_enabled and external_policy in {"off", "none", "disabled"}:
        recommendations.append("Enable human-review policy for outbound messages before production sends.")
    if not _truthy(embedding.get("enabled")):
        recommendations.append("Enable embeddings for semantic memory retrieval when memory 2.0 is ready.")
    if _safe_count(memory_journal, "pending") > 50:
        recommendations.append("Run memory organization; pending turn journal entries are building up.")
    if plan_graph.get("cycle_run_ids"):
        recommendations.append("Review orchestration plan graph; one or more task dependencies form a cycle.")
    if plan_graph.get("unresolved_dependency_ids"):
        recommendations.append("Review orchestration plan graph; some runs reference missing dependency IDs.")

    performance = _performance_profiles(config) if include_profiles else {
        "available": False,
        "error": "profile measurement skipped",
        "profiles": [],
    }
    if performance.get("available") and performance.get("worst_profile"):
        worst = performance["worst_profile"]
        if (worst.get("savings_pct") or 0) < 35:
            recommendations.append("Review focused tool profiles; the weakest measured savings is below 35%.")

    return {
        "generated_at": _utc_now(),
        "elevate_home": str(get_elevate_home()),
        "server": {
            "pattern": "single-local-gateway",
            "gateway_running": gateway_running,
            "gateway_pid": gateway_pid,
            "clients": [
                {"id": "cli", "label": "CLI", "connected": True},
                {"id": "dashboard", "label": "Agent Hub", "connected": True},
                {
                    "id": "telegram",
                    "label": "Telegram",
                    "connected": "telegram" in configured_platforms,
                },
                {
                    "id": "api_server",
                    "label": "Local API Server",
                    "connected": "api_server" in configured_platforms,
                },
            ],
        },
        "orchestration": {
            "visible": bool(agents),
            "coordinator": coordinator.get("agent_id") if coordinator else "",
            "agent_states": sorted({str(agent.get("status") or "unknown") for agent in agents}),
            "total_agents": len(agents),
            "active_runs": len(active_runs),
            "recent_runs": len(runs),
            "route_labeled_runs": len(route_labeled_runs),
            "recent_events": len(recent_events),
            "event_tail": [
                {
                    "run_id": event.get("run_id"),
                    "type": event.get("type"),
                    "message": event.get("message"),
                    "timestamp": event.get("timestamp"),
                }
                for event in recent_events[:10]
                if isinstance(event, dict)
            ],
            "plan_graph": {
                "ready_runs": _safe_list_count(plan_graph, "ready_run_ids"),
                "blocked_runs": _safe_list_count(plan_graph, "blocked_run_ids"),
                "active_runs": _safe_list_count(plan_graph, "active_run_ids"),
                "completed_runs": _safe_list_count(plan_graph, "completed_run_ids"),
                "cycle_runs": _safe_list_count(plan_graph, "cycle_run_ids"),
                "unresolved_dependencies": _safe_list_count(plan_graph, "unresolved_dependency_ids"),
                "next_ready_run_ids": (
                    plan_graph.get("next_ready_run_ids")
                    if isinstance(plan_graph.get("next_ready_run_ids"), list)
                    else []
                ),
            },
            "lifecycle_states": [
                "ready",
                "running",
                "blocked",
                "waiting_for_approval",
                "completed",
                "failed",
                "crashed",
            ],
        },
        "skills": {
            "mode": "manifest-visible-detail-lazy",
            "index_visible": _safe_count(skills, "enabled") > 0,
            "enabled": _safe_count(skills, "enabled"),
            "total": _safe_count(skills, "total"),
            "details_loaded_on_demand": True,
            "tool_index_visible": bool(enabled_toolsets),
            "enabled_toolsets": enabled_toolsets,
        },
        "memory": {
            "mode": "async-local-hybrid",
            "provider": memory.get("provider") or "builtin",
            "embeddings_enabled": _truthy(embedding.get("enabled")),
            "embedding_provider": embedding.get("provider") or "",
            "embedding_model": embedding.get("model") or "",
            "pending_turns": _safe_count(memory_journal, "pending"),
            "processed_turns": _safe_count(memory_journal, "processed"),
            "session_segments": _safe_count(memory_journal, "session_segment_count"),
            "graph_nodes": len(graph_nodes),
            "graph_edges": len(graph_edges),
            "pipeline": memory_pipeline,
        },
        "safety": {
            "dangerous_command_mode": approvals_cfg.get("mode") or "manual",
            "external_actions_policy": external_policy,
            "human_communication_requires_review": external_policy not in {"off", "none", "disabled"},
            "send_message_available": messaging_enabled,
            "approval_surfaces": ["terminal", "gateway command approvals", "dashboard review posture"],
        },
        "performance": performance,
        "recommendations": recommendations,
    }


def format_harness_snapshot(snapshot: dict[str, Any]) -> str:
    """Format a harness snapshot for terminal output."""
    server = snapshot.get("server", {})
    orchestration = snapshot.get("orchestration", {})
    skills = snapshot.get("skills", {})
    memory = snapshot.get("memory", {})
    safety = snapshot.get("safety", {})
    performance = snapshot.get("performance", {})
    lines = [
        "Elevate Harness",
        f"  Gateway: {'online' if server.get('gateway_running') else 'offline'}"
        + (f" (PID {server.get('gateway_pid')})" if server.get("gateway_pid") else ""),
        f"  Clients: "
        + ", ".join(
            f"{client.get('label')}={'on' if client.get('connected') else 'off'}"
            for client in server.get("clients", [])
        ),
        f"  Coordinator: {orchestration.get('coordinator') or 'missing'}",
        (
            "  Orchestration: "
            f"{orchestration.get('total_agents', 0)} agents, "
            f"{orchestration.get('active_runs', 0)} active runs, "
            f"{orchestration.get('route_labeled_runs', 0)} routed runs, "
            f"{orchestration.get('recent_events', 0)} recent events"
        ),
        (
            "  Plan Graph: "
            f"ready={orchestration.get('plan_graph', {}).get('ready_runs', 0)}, "
            f"blocked={orchestration.get('plan_graph', {}).get('blocked_runs', 0)}, "
            f"cycles={orchestration.get('plan_graph', {}).get('cycle_runs', 0)}"
        ),
        (
            "  Skills: "
            f"{skills.get('enabled', 0)}/{skills.get('total', 0)} enabled, "
            f"mode={skills.get('mode')}"
        ),
        (
            "  Memory: "
            f"{memory.get('provider')} provider, "
            f"embeddings={'on' if memory.get('embeddings_enabled') else 'off'}, "
            f"pending_turns={memory.get('pending_turns', 0)}, "
            f"graph={memory.get('graph_nodes', 0)} nodes, "
            f"pipeline={memory.get('pipeline', {}).get('state', 'unknown')}"
        ),
        (
            "  Safety: "
            f"commands={safety.get('dangerous_command_mode')}, "
            f"external={safety.get('external_actions_policy')}, "
            f"send_message={'on' if safety.get('send_message_available') else 'off'}"
        ),
    ]
    if performance.get("available"):
        best = performance.get("best_profile") or {}
        worst = performance.get("worst_profile") or {}
        lines.append(
            "  Performance: "
            f"baseline={performance.get('baseline_request_tokens', 0)} rough tokens, "
            f"best={best.get('name', '-')} ({(best.get('savings_pct') or 0):.1f}% saved), "
            f"worst={worst.get('name', '-')} ({(worst.get('savings_pct') or 0):.1f}% saved)"
        )
    elif performance.get("error"):
        lines.append(f"  Performance: {performance.get('error')}")

    recommendations = snapshot.get("recommendations") or []
    if recommendations:
        lines.append("")
        lines.append("Next fixes:")
        lines.extend(f"  - {item}" for item in recommendations)
    return "\n".join(lines)


def run_context_efficiency(argv: list[str]) -> int:
    """Run the static context-efficiency harness in a subprocess-like path."""
    old_skip_mcp = os.environ.get("ELEVATE_SKIP_MCP_DISCOVERY")
    os.environ["ELEVATE_SKIP_MCP_DISCOVERY"] = "1"
    try:
        from scripts.elevate_context_efficiency import main as efficiency_main

        return int(efficiency_main(argv))
    finally:
        if old_skip_mcp is None:
            os.environ.pop("ELEVATE_SKIP_MCP_DISCOVERY", None)
        else:
            os.environ["ELEVATE_SKIP_MCP_DISCOVERY"] = old_skip_mcp


def cmd_harness(args: Any) -> int:
    action = getattr(args, "harness_action", None) or "status"
    if action == "status":
        snapshot = build_harness_snapshot(include_profiles=not getattr(args, "no_profiles", False))
        if getattr(args, "json", False):
            print(json.dumps(snapshot, indent=2, sort_keys=True))
        else:
            print(format_harness_snapshot(snapshot))
        return 0

    if action in {"benchmark", "adversarial"}:
        argv: list[str] = [
            "--baseline-toolsets",
            getattr(args, "baseline_toolsets", "elevate-cli"),
        ]
        if getattr(args, "model", None):
            argv.extend(["--model", args.model])
        if getattr(args, "include_local_context", False):
            argv.append("--include-local-context")
        if getattr(args, "include_memory", False):
            argv.append("--include-memory")
        if getattr(args, "json", False):
            argv.append("--json")
        if getattr(args, "no_assert", False):
            argv.append("--no-assert")
        if action == "benchmark" and getattr(args, "stress", False):
            argv.append("--stress")
            argv.extend(["--models", getattr(args, "models", "")])
            argv.extend(["--repetitions", str(getattr(args, "repetitions", 2))])
        if action == "adversarial":
            argv.append("--adversarial")
            argv.extend(["--models", getattr(args, "models", "")])
            argv.extend(
                [
                    "--max-adversarial-request-tokens",
                    str(getattr(args, "max_adversarial_request_tokens", 60_000)),
                ]
            )
        return run_context_efficiency(argv)

    print(f"Unknown harness action: {action}", file=sys.stderr)
    return 2


def run_harness_subprocess(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Small helper used by tests and external wrappers."""
    return subprocess.run(
        [sys.executable, "-m", "elevate_cli.main", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
    )
