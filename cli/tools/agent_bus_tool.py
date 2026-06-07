"""Native agent bus tool.

This is the in-app replacement for CortextOS' shell-based ``cortextos bus``
commands. It deliberately writes to Elevate's existing stores only.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.registry import registry, tool_error, tool_result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: Any) -> str:
    try:
        from gateway.agent_lanes import normalize_agent_id

        return normalize_agent_id(value)
    except Exception:
        text = str(value or "").strip().lower().replace("_", "-")
        cleaned: list[str] = []
        last_dash = False
        for ch in text:
            if ch.isalnum():
                cleaned.append(ch)
                last_dash = False
            elif not last_dash:
                cleaned.append("-")
                last_dash = True
        return "".join(cleaned).strip("-")


def _session_agent_id(parent_agent: Any = None) -> str:
    try:
        from gateway.session_context import get_session_env

        value = get_session_env("ELEVATE_SESSION_AGENT_ID", "")
        if value:
            return _slug(value)
    except Exception:
        pass
    if parent_agent is not None:
        for attr in ("agent_id", "_agent_id", "name"):
            value = getattr(parent_agent, attr, "")
            if value:
                return _slug(value)
    return _slug(os.environ.get("ELEVATE_AGENT_ID", ""))


def _actor_agent(args: dict[str, Any], parent_agent: Any = None) -> str:
    return (
        _slug(args.get("agent_id") or args.get("agentId"))
        or _session_agent_id(parent_agent)
        or "executive-assistant"
    )


def _approval_category(value: Any) -> str:
    raw = str(value or "other").strip().lower().replace("_", "-")
    return {
        "external-comms": "external-comms",
        "external-send": "external-comms",
        "external-communications": "external-comms",
        "data-deletion": "data-deletion",
        "data-delete": "data-deletion",
        "delete": "data-deletion",
        "financial": "financial",
        "finance": "financial",
        "cost": "financial",
        "deployment": "deployment",
        "deploy": "deployment",
        "access": "other",
    }.get(raw, raw if raw in {"external-comms", "financial", "deployment", "data-deletion", "other"} else "other")


def _priority(value: Any) -> str:
    raw = str(value or "normal").strip().lower()
    return raw if raw in {"urgent", "high", "normal", "low"} else "normal"


def _status(value: Any, default: str = "pending") -> str:
    raw = str(value or default).strip().lower().replace("-", "_")
    return raw if raw in {"pending", "in_progress", "blocked", "completed", "cancelled"} else default


def _activity_log_path() -> Path:
    from elevate_cli.data.paths import data_root

    return data_root() / "agent_activity.jsonl"


def _append_activity(
    *,
    agent_id: str,
    category: str,
    event: str,
    severity: str = "info",
    message: str = "",
    metadata: Any = None,
) -> dict[str, Any]:
    rec = {
        "kind": "agent_activity",
        "agent": agent_id,
        "category": str(category or "action"),
        "event": str(event or "event"),
        "severity": str(severity or "info"),
        "message": str(message or ""),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "ts": _now_iso(),
    }
    path = _activity_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
    return rec


def _read_activity(agent_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    path = _activity_log_path()
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit * 3, 300)):]
    except Exception:
        return []
    clean_agent = _slug(agent_id) if agent_id else ""
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        if clean_agent and _slug(rec.get("agent")) != clean_agent:
            continue
        items.append(rec)
    items.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return items[: max(1, min(limit, 100))]


def _heartbeat_dir(agent_id: str) -> Path:
    from elevate_constants import get_account_data_dir

    return get_account_data_dir() / "heartbeats" / agent_id


def _update_heartbeat(agent_id: str, message: str, status: str = "active", metadata: Any = None) -> dict[str, Any]:
    hb_dir = _heartbeat_dir(agent_id)
    hist_dir = hb_dir / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = _now_iso()
    rec = {
        "surface": agent_id,
        "agent": agent_id,
        "status": str(status or "active"),
        "summary": str(message or "heartbeat"),
        "did": str(message or "heartbeat"),
        "ran_at": ts,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "source": "agent_bus",
    }
    (hb_dir / "heartbeat.json").write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    (hist_dir / f"{ts.replace(':', '-')}.json").write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    cfg_path = hb_dir / "config.json"
    if not cfg_path.exists():
        cfg_path.write_text(
            json.dumps(
                {
                    "surface": agent_id,
                    "title": agent_id.replace("-", " ").title(),
                    "enabled": False,
                    "source": "agent_bus",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return rec


def _read_heartbeats(agent_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    from elevate_constants import get_account_data_dir

    root = get_account_data_dir() / "heartbeats"
    if not root.exists():
        return []
    target = _slug(agent_id) if agent_id else ""
    out: list[dict[str, Any]] = []
    for hb_dir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        if target and hb_dir.name != target:
            continue
        rec: dict[str, Any] = {"agent": hb_dir.name, "status": "unknown"}
        try:
            parsed = json.loads((hb_dir / "heartbeat.json").read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                rec.update(parsed)
        except Exception:
            hist = hb_dir / "history"
            files = sorted(hist.glob("*.json"), reverse=True) if hist.exists() else []
            if files:
                try:
                    parsed = json.loads(files[0].read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        rec.update(parsed)
                except Exception:
                    pass
        out.append(rec)
    out.sort(key=lambda item: str(item.get("ran_at") or item.get("ts") or ""), reverse=True)
    return out[: max(1, min(limit, 100))]


def _agent_memory_policy(agent_id: str) -> dict[str, Any]:
    try:
        from agent.memory_manager import normalize_agent_memory_policy
        from elevate_cli.agent_hub import get_agent_def

        agent = get_agent_def(agent_id)
        memory = agent.get("memory") if isinstance(agent, dict) else {}
        return normalize_agent_memory_policy(agent_id, memory if isinstance(memory, dict) else {})
    except Exception:
        return {"agentId": _slug(agent_id)}


def _surface_for_experiment(args: dict[str, Any], parent_agent: Any = None) -> str:
    return _slug(args.get("surface") or args.get("agent_id") or args.get("agentId")) or _session_agent_id(parent_agent) or "executive-assistant"


def _experiments_dir(surface: str) -> Path:
    return _heartbeat_dir(surface) / "experiments"


def _experiment_history_dir(surface: str) -> Path:
    return _experiments_dir(surface) / "history"


def _experiment_active_dir(surface: str) -> Path:
    return _experiments_dir(surface) / "active"


def _cycle_key(value: Any) -> str:
    return _slug(value) or "default"


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _experiment_id() -> str:
    return f"exp_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:5]}"


def _float_arg(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_arg(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_arg(value: Any, default: bool | None = None) -> bool | None:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return True
    if raw in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _cycle_defaults(surface: str, metric: str) -> dict[str, Any]:
    try:
        from cron.cycles import find_cycle_defaults

        defaults = find_cycle_defaults(surface, metric)
        return defaults if isinstance(defaults, dict) else {}
    except Exception:
        return {}


def _load_experiment(surface: str, experiment_id: str | None = None) -> dict[str, Any] | None:
    exp_dir = _experiments_dir(surface)
    wanted = str(experiment_id or "").strip()
    if wanted:
        hist = _read_json_file(_experiment_history_dir(surface) / f"{wanted}.json")
        if hist:
            return hist
        for path in _experiment_active_dir(surface).glob("*.json"):
            rec = _read_json_file(path)
            if rec and str(rec.get("id") or "") == wanted:
                return rec
        legacy = _read_json_file(exp_dir / "active.json")
        if legacy and str(legacy.get("id") or "") == wanted:
            return legacy
        return None

    legacy = _read_json_file(exp_dir / "active.json")
    if legacy:
        return legacy
    active_files = sorted(_experiment_active_dir(surface).glob("*.json"), reverse=True)
    for path in active_files:
        rec = _read_json_file(path)
        if rec:
            return rec
    return None


def _save_experiment_history(surface: str, rec: dict[str, Any]) -> None:
    exp_id = str(rec.get("id") or _experiment_id())
    rec["id"] = exp_id
    _write_json_file(_experiment_history_dir(surface) / f"{exp_id}.json", rec)


def _save_active_experiment(surface: str, rec: dict[str, Any]) -> None:
    cycle = _cycle_key(rec.get("cycle") or rec.get("metric") or "default")
    _write_json_file(_experiment_active_dir(surface) / f"{cycle}.json", rec)
    _write_json_file(_experiments_dir(surface) / "active.json", rec)


def _remove_active_experiment(surface: str, rec: dict[str, Any]) -> None:
    exp_id = str(rec.get("id") or "")
    cycle = _cycle_key(rec.get("cycle") or rec.get("metric") or "default")
    for path in (
        _experiment_active_dir(surface) / f"{cycle}.json",
        _experiments_dir(surface) / "active.json",
    ):
        current = _read_json_file(path)
        if current and exp_id and str(current.get("id") or "") != exp_id:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _append_experiment_result(surface: str, rec: dict[str, Any], measured: float | None) -> None:
    exp_dir = _experiments_dir(surface)
    exp_dir.mkdir(parents=True, exist_ok=True)
    tsv = exp_dir / "results.tsv"
    if not tsv.exists():
        tsv.write_text(
            "ts\tcycle\tmetric\tbaseline\tresult\tdecision\thypothesis\n",
            encoding="utf-8",
        )
    with tsv.open("a", encoding="utf-8") as fh:
        fh.write(
            "\t".join(
                [
                    str(rec.get("completed_at") or _now_iso()),
                    str(rec.get("cycle") or rec.get("metric") or ""),
                    str(rec.get("metric") or ""),
                    str(rec.get("baseline_value") if rec.get("baseline_value") is not None else ""),
                    str(measured if measured is not None else rec.get("result_value") or ""),
                    str(rec.get("decision") or ""),
                    str(rec.get("hypothesis") or "").replace("\t", " "),
                ]
            )
            + "\n"
        )


def _append_learning(surface: str, rec: dict[str, Any]) -> None:
    learning = str(rec.get("learning") or "").strip()
    if not learning:
        return
    learn_path = _heartbeat_dir(surface) / "learnings.md"
    learn_path.parent.mkdir(parents=True, exist_ok=True)
    if not learn_path.exists():
        learn_path.write_text(f"# {surface.replace('-', ' ').title()} Heartbeat - Learnings\n\n", encoding="utf-8")
    with learn_path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {rec.get('id')}: {learning}\n")


def _list_experiments(surface: str) -> dict[str, Any]:
    exp_dir = _experiments_dir(surface)
    active = None
    active_by_cycle: dict[str, Any] = {}
    history: list[dict[str, Any]] = []
    legacy_active = _read_json_file(exp_dir / "active.json")
    if legacy_active:
        active = legacy_active
        active_by_cycle[_cycle_key(legacy_active.get("cycle") or legacy_active.get("metric"))] = legacy_active
    active_dir = _experiment_active_dir(surface)
    if active_dir.exists():
        for path in sorted(active_dir.glob("*.json"), reverse=True):
            rec = _read_json_file(path)
            if rec:
                active_by_cycle[path.stem] = rec
                active = active or rec
    hist_dir = exp_dir / "history"
    if hist_dir.exists():
        for path in sorted(hist_dir.glob("*.json"), reverse=True)[:100]:
            rec = _read_json_file(path)
            if rec:
                history.append(rec)
    history.sort(
        key=lambda item: str(
            item.get("completed_at")
            or item.get("started_at")
            or item.get("created_at")
            or item.get("ts")
            or ""
        ),
        reverse=True,
    )
    return {
        "surface": surface,
        "active": active,
        "activeByCycle": active_by_cycle,
        "history": history,
        "count": len(history) + len(active_by_cycle),
    }


def _cycle_opts(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "name": str(args.get("name") or args.get("cycle") or args.get("cycle_name") or args.get("title") or "").strip(),
        "metric": str(args.get("metric") or "").strip(),
        "created_by": _actor_agent(args, parent_agent),
    }
    aliases = {
        "metric_type": args.get("metric_type") or args.get("metricType"),
        "direction": args.get("direction"),
        "window": args.get("window"),
        "measurement": args.get("measurement"),
        "loop_interval": args.get("loop_interval") or args.get("loopInterval"),
        "surface": args.get("target_surface") or args.get("targetSurface") or args.get("experiment_surface"),
    }
    opts.update({key: value for key, value in aliases.items() if value not in (None, "")})
    every_n = _int_arg(args.get("every_n_runs") if args.get("every_n_runs") is not None else args.get("everyNRuns"))
    if every_n is not None:
        opts["every_n_runs"] = every_n
    approval_required = _bool_arg(
        args.get("approval_required") if args.get("approval_required") is not None else args.get("approvalRequired")
    )
    if approval_required is not None:
        opts["approval_required"] = approval_required
    enabled = _bool_arg(args.get("enabled"))
    if enabled is not None:
        opts["enabled"] = enabled
    return opts


def _list_cycles(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    surface = _surface_for_experiment(args, parent_agent)
    from cron.cycles import list_cycles

    return {"surface": surface, "cycles": list_cycles(surface)}


def _manage_cycle(action: str, args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    surface = _surface_for_experiment(args, parent_agent)
    from cron.cycles import manage_cycle

    result = manage_cycle(surface, action, **_cycle_opts(args, parent_agent))
    if not result.get("ok"):
        raise ValueError(str(result.get("error") or f"cycle {action} failed"))
    actor = _actor_agent(args, parent_agent)
    _append_activity(
        agent_id=actor,
        category="experiment",
        event=f"cycle_{action}d" if action != "modify" else "cycle_modified",
        message=str(args.get("name") or args.get("cycle") or args.get("cycle_name") or "cycle"),
        metadata={"surface": surface, "action": action},
    )
    return {"surface": surface, "action": action, "cycles": result.get("cycles") or []}


def _create_experiment(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    surface = _surface_for_experiment(args, parent_agent)
    metric = str(args.get("metric") or "").strip()
    defaults = _cycle_defaults(surface, metric) if metric else {}
    now = _now_iso()
    exp_id = str(args.get("experiment_id") or args.get("id") or _experiment_id())
    status = str(args.get("status") or "proposed").strip().lower()
    if status not in {"proposed", "running"}:
        status = "proposed"
    baseline = _float_arg(args.get("baseline_value") or args.get("baseline"), 0.0)
    rec = {
        "id": exp_id,
        "agent": str(args.get("agent") or surface),
        "cycle": str(args.get("cycle") or args.get("cycle_name") or metric or "default"),
        "metric": metric,
        "metric_type": str(args.get("metric_type") or defaults.get("metric_type") or "qualitative"),
        "hypothesis": str(args.get("hypothesis") or args.get("description") or ""),
        "surface": surface,
        "title": str(args.get("title") or exp_id),
        "direction": str(args.get("direction") or defaults.get("direction") or "higher"),
        "window": str(args.get("window") or defaults.get("window") or "24h"),
        "measurement": str(args.get("measurement") or defaults.get("measurement") or ""),
        "status": status,
        "baseline_value": baseline,
        "result_value": None,
        "decision": None,
        "learning": "",
        "changes_description": None,
        "experiment_commit": None,
        "tracking_commit": str(args.get("tracking_commit") or ""),
        "created_at": now,
        "started_at": now if status == "running" else None,
        "completed_at": None,
        "createdAt": now,
        "createdBy": _actor_agent(args, parent_agent),
        "payload": args.get("payload") if isinstance(args.get("payload"), dict) else {},
    }
    _save_experiment_history(surface, rec)
    if status == "running":
        _save_active_experiment(surface, rec)
    _append_activity(
        agent_id=rec["createdBy"],
        category="experiment",
        event="experiment_created",
        message=rec["title"],
        metadata={"surface": surface, "experiment_id": exp_id},
    )
    return rec


def _run_experiment(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    surface = _surface_for_experiment(args, parent_agent)
    rec = _load_experiment(surface, str(args.get("experiment_id") or args.get("id") or "").strip() or None)
    if not rec:
        raise ValueError("experiment not found")
    if str(rec.get("status") or "").lower() == "completed":
        raise ValueError("completed experiments cannot be run")
    now = _now_iso()
    rec["status"] = "running"
    rec["started_at"] = rec.get("started_at") or now
    if args.get("changes_description") or args.get("change") or args.get("summary"):
        rec["changes_description"] = str(args.get("changes_description") or args.get("change") or args.get("summary"))
    if args.get("experiment_commit") or args.get("commit"):
        rec["experiment_commit"] = str(args.get("experiment_commit") or args.get("commit"))
    _save_experiment_history(surface, rec)
    _save_active_experiment(surface, rec)
    actor = _actor_agent(args, parent_agent)
    _append_activity(
        agent_id=actor,
        category="experiment",
        event="experiment_started",
        message=str(rec.get("title") or rec.get("id") or "experiment"),
        metadata={"surface": surface, "experiment_id": rec.get("id")},
    )
    return rec


def _evaluate_experiment(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    surface = _surface_for_experiment(args, parent_agent)
    active = _load_experiment(surface, str(args.get("experiment_id") or args.get("id") or "").strip() or None)
    if not active:
        raise ValueError("experiment not found")
    measured = _float_arg(
        args.get("measured_value")
        if args.get("measured_value") is not None
        else args.get("score")
        if args.get("score") is not None
        else args.get("result_value")
        if args.get("result_value") is not None
        else args.get("result")
    )
    decision = str(args.get("decision") or "").strip().lower()
    if not decision:
        if measured is None:
            raise ValueError("measured_value, score, result_value, result, or decision is required")
        baseline = _float_arg(active.get("baseline_value") or active.get("baseline"), 0.0) or 0.0
        direction = str(active.get("direction") or "higher").lower()
        decision = "keep" if (measured > baseline if direction == "higher" else measured < baseline) else "discard"
    if decision not in {"keep", "discard", "defer"}:
        raise ValueError("decision must be keep, discard, or defer")
    learning_parts = []
    if args.get("learning"):
        learning_parts.append(str(args.get("learning")))
    if args.get("justification"):
        learning_parts.append(str(args.get("justification")))
    if args.get("outcome") or args.get("notes"):
        learning_parts.append(str(args.get("outcome") or args.get("notes")))
    now = _now_iso()
    rec = {
        **active,
        "status": "completed",
        "decision": decision,
        "result_value": measured,
        "learning": " - ".join(part for part in learning_parts if part).strip(),
        "outcome": str(args.get("outcome") or args.get("result") or args.get("notes") or ""),
        "completed_at": now,
        "evaluatedAt": now,
        "evaluatedBy": _actor_agent(args, parent_agent),
    }
    if decision == "keep" and measured is not None:
        rec["baseline_value"] = measured
    _save_experiment_history(surface, rec)
    _append_experiment_result(surface, rec, measured)
    _append_learning(surface, rec)
    _remove_active_experiment(surface, rec)
    _append_activity(
        agent_id=rec["evaluatedBy"],
        category="experiment",
        event="experiment_evaluated",
        message=f"{rec.get('title')}: {decision}",
        metadata={"surface": surface, "experiment_id": rec.get("id"), "decision": decision},
    )
    return rec


def _gather_experiment_context(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    surface = _surface_for_experiment(args, parent_agent)
    listed = _list_experiments(surface)
    history = [item for item in listed["history"] if isinstance(item, dict)]
    completed = [item for item in history if str(item.get("status") or "").lower() == "completed"]
    keeps = sum(1 for item in completed if item.get("decision") == "keep")
    discards = sum(1 for item in completed if item.get("decision") == "discard")
    exp_dir = _experiments_dir(surface)
    learnings = ""
    results_tsv = ""
    for path, key in ((exp_dir.parent / "learnings.md", "learnings"), (exp_dir / "results.tsv", "results")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        if key == "learnings":
            learnings = text
        else:
            results_tsv = text
    config = _read_json_file(_heartbeat_dir(surface) / "config.json") or {}
    return {
        "agent": surface,
        "surface": surface,
        "total_experiments": len(history),
        "running": len(listed.get("activeByCycle") or {}),
        "keeps": keeps,
        "discards": discards,
        "keep_rate": (keeps / len(completed)) if completed else 0,
        "learnings": learnings,
        "results_tsv": results_tsv,
        "identity": json.dumps(config, indent=2, default=str),
        "goals": str(config.get("goal") or ""),
    }


def _browse_catalog(args: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(args.get("query") or args.get("search") or "").strip()
    source = str(args.get("source") or "all").strip() or "all"
    limit = max(1, min(int(args.get("limit") or 10), 25))
    from tools.skills_hub import GitHubAuth, create_source_router, unified_search

    metas = unified_search(query, create_source_router(auth=GitHubAuth()), source_filter=source, limit=limit)
    return [
        {
            "name": meta.name,
            "description": meta.description,
            "source": meta.source,
            "identifier": meta.identifier,
            "trustLevel": meta.trust_level,
            "repo": meta.repo,
            "path": meta.path,
            "tags": meta.tags,
        }
        for meta in metas
    ]


def _list_skills(args: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(args.get("query") or args.get("search") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 50), 200))
    from tools.skills_tool import _find_all_skills
    from elevate_cli.config import load_config
    from elevate_cli.skills_config import get_disabled_skills

    disabled = get_disabled_skills(load_config())
    skills = _find_all_skills(skip_disabled=False)
    out: list[dict[str, Any]] = []
    for skill in skills:
        name = str(skill.get("name") or "")
        haystack = f"{name} {skill.get('description') or ''}".lower()
        if query and query not in haystack:
            continue
        item = dict(skill)
        item["enabled"] = name not in disabled
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _agent_bus_tool(args: dict[str, Any], **kw: Any) -> str:
    action = str(args.get("action") or "").strip().lower().replace("-", "_")
    parent_agent = kw.get("parent_agent")
    agent_id = _actor_agent(args, parent_agent)
    try:
        if action in {"create_task", "task_create"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                task = surface_tasks.create_task(
                    conn,
                    title=str(args.get("title") or ""),
                    description=args.get("description") or args.get("desc"),
                    type=str(args.get("type") or "agent"),
                    status=_status(args.get("status"), "pending"),
                    priority=_priority(args.get("priority")),
                    assignee=args.get("assignee") or args.get("assigned_to") or agent_id,
                    project=args.get("project"),
                    needs_approval=bool(args.get("needs_approval") or args.get("needsApproval")),
                    notes=args.get("notes"),
                    created_by=args.get("created_by") or args.get("createdBy") or agent_id,
                    org=args.get("org"),
                    kpi_key=args.get("kpi_key") or args.get("kpiKey"),
                    due_date=args.get("due_date") or args.get("dueDate"),
                    blocked_by=args.get("blocked_by") or args.get("blockedBy"),
                    blocks=args.get("blocks"),
                    actor=f"agent:{agent_id}",
                    actor_agent_id=agent_id,
                    policy_action=str(args.get("policy_action") or "create_task"),
                    policy_category=str(args.get("policy_category") or "task"),
                )
                return tool_result(success=True, task=task)

        if action in {"list_tasks", "tasks"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                items = surface_tasks.list_tasks(
                    conn,
                    status=args.get("status"),
                    assignee=args.get("assignee") or args.get("agent_id") or args.get("agentId"),
                    priority=args.get("priority"),
                    project=args.get("project"),
                    include_archived=bool(args.get("include_archived") or args.get("includeArchived")),
                )
                return tool_result(success=True, items=items, count=len(items))

        if action in {"update_task", "complete_task", "block_task"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            task_id = str(args.get("task_id") or args.get("taskId") or "").strip()
            if not task_id:
                return tool_error("task_id is required")
            patch: dict[str, Any] = {}
            if action == "complete_task":
                result = args.get("result") or args.get("summary")
                with connect() as conn:
                    task = surface_tasks.complete_task(
                        conn,
                        task_id,
                        result=str(result) if result else None,
                        outputs=args.get("outputs"),
                        actor=f"agent:{agent_id}",
                        actor_agent_id=agent_id,
                        policy_category=str(args.get("policy_category") or "task"),
                    )
                    if not task:
                        return tool_error("task not found")
                    return tool_result(success=True, task=task)
            elif action == "block_task":
                patch["status"] = "blocked"
                if args.get("reason"):
                    patch["notes"] = str(args.get("reason"))
            else:
                for key in (
                    "title",
                    "description",
                    "type",
                    "status",
                    "priority",
                    "assignee",
                    "assigned_to",
                    "project",
                    "notes",
                    "created_by",
                    "createdBy",
                    "org",
                    "kpi_key",
                    "kpiKey",
                    "due_date",
                    "dueDate",
                    "result",
                ):
                    if args.get(key) is not None:
                        patch[key] = args.get(key)
                if args.get("outputs") is not None:
                    patch["outputs"] = args.get("outputs")
                if args.get("blocked_by") is not None or args.get("blockedBy") is not None:
                    patch["blocked_by"] = args.get("blocked_by") or args.get("blockedBy")
                if args.get("blocks") is not None:
                    patch["blocks"] = args.get("blocks")
            with connect() as conn:
                task = surface_tasks.update_task(
                    conn,
                    task_id,
                    patch,
                    actor=f"agent:{agent_id}",
                    actor_agent_id=agent_id,
                    policy_action=str(args.get("policy_action") or action),
                    policy_category=str(args.get("policy_category") or "task"),
                )
                if not task:
                    return tool_error("task not found")
                return tool_result(success=True, task=task)

        if action in {"claim_task", "task_claim"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            task_id = str(args.get("task_id") or args.get("taskId") or "").strip()
            if not task_id:
                return tool_error("task_id is required")
            with connect() as conn:
                task = surface_tasks.claim_task(
                    conn,
                    task_id,
                    agent=str(args.get("assignee") or args.get("assigned_to") or agent_id),
                    actor=f"agent:{agent_id}",
                )
                if not task:
                    return tool_error("task not found")
                return tool_result(success=True, task=task)

        if action in {"read_task_audit", "task_audit"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            task_id = str(args.get("task_id") or args.get("taskId") or "").strip()
            if not task_id:
                return tool_error("task_id is required")
            with connect() as conn:
                items = surface_tasks.read_task_audit(conn, task_id, limit=int(args.get("limit") or 200))
                return tool_result(success=True, items=items, count=len(items))

        if action in {"check_stale_tasks", "stale_tasks"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                report = surface_tasks.check_stale_tasks(conn)
                return tool_result(success=True, report=report)

        if action in {"check_human_tasks", "human_tasks"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                items = surface_tasks.check_human_tasks(conn)
                return tool_result(success=True, items=items, count=len(items))

        if action in {"archive_tasks", "task_archive"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                report = surface_tasks.archive_tasks(
                    conn,
                    dry_run=bool(args.get("dry_run") or args.get("dryRun")),
                    older_than_days=int(args.get("older_than_days") or args.get("olderThanDays") or 7),
                    actor=f"agent:{agent_id}",
                )
                return tool_result(success=True, report=report)

        if action in {"compact_tasks", "task_compact"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                report = surface_tasks.compact_tasks(
                    conn,
                    dry_run=bool(args.get("dry_run") or args.get("dryRun")),
                    older_than_days=int(args.get("older_than_days") or args.get("olderThanDays") or 30),
                    actor=f"agent:{agent_id}",
                )
                return tool_result(success=True, report=report)

        if action in {"create_approval", "approval_create"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                approval = surface_tasks.create_approval(
                    conn,
                    title=str(args.get("title") or ""),
                    category=_approval_category(args.get("category")),
                    description=args.get("description") or args.get("context"),
                    surface=agent_id,
                )
                return tool_result(success=True, approval=approval)

        if action in {"list_approvals", "approvals"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks

            with connect() as conn:
                items = surface_tasks.list_approvals(
                    conn,
                    status=args.get("status"),
                    surface=args.get("surface") or args.get("agent_id") or args.get("agentId"),
                    category=_approval_category(args.get("category")) if args.get("category") else None,
                )
                return tool_result(success=True, items=items, count=len(items))

        if action in {"post_activity", "log_event", "activity"}:
            rec = _append_activity(
                agent_id=agent_id,
                category=str(args.get("category") or "action"),
                event=str(args.get("event") or args.get("title") or "activity"),
                severity=str(args.get("severity") or "info"),
                message=str(args.get("message") or args.get("content") or ""),
                metadata=args.get("metadata") or args.get("meta"),
            )
            return tool_result(success=True, event=rec)

        if action in {"list_activity", "read_activity"}:
            items = _read_activity(args.get("agent_id") or args.get("agentId"), limit=int(args.get("limit") or 50))
            return tool_result(success=True, items=items, count=len(items))

        if action in {"update_heartbeat", "heartbeat"}:
            rec = _update_heartbeat(
                agent_id,
                str(args.get("message") or args.get("status_text") or args.get("current_task") or "active"),
                status=str(args.get("status") or "active"),
                metadata=args.get("metadata") or args.get("meta"),
            )
            return tool_result(success=True, heartbeat=rec)

        if action in {"read_heartbeats", "list_heartbeats"}:
            items = _read_heartbeats(args.get("agent_id") or args.get("agentId"), limit=int(args.get("limit") or 50))
            return tool_result(success=True, items=items, count=len(items))

        if action in {"write_memory", "memory_write"}:
            from agent.memory_manager import memory_policy_allows_write
            from elevate_cli.agent_hub import seed_agent_memory

            policy = _agent_memory_policy(agent_id)
            if not memory_policy_allows_write(policy):
                return tool_error("agent memory write is disabled by policy")
            content = str(args.get("content") or args.get("fact") or args.get("message") or "").strip()
            if not content:
                return tool_error("content is required")
            summary = seed_agent_memory(
                agent_id,
                content,
                source=str(args.get("source") or "agent_bus"),
                actor=f"agent:{agent_id}",
                scopes=args.get("scopes"),
            )
            _append_activity(
                agent_id=agent_id,
                category="memory",
                event="memory_written",
                message=f"{summary.get('seeded', 0)} memory fact(s) written",
                metadata={"source": summary.get("source"), "duplicates": summary.get("duplicates", 0)},
            )
            return tool_result(success=True, memory=summary)

        if action in {"list_memory", "memory"}:
            from agent.memory_manager import memory_policy_allows_recall
            from elevate_cli.agent_hub import agent_memory_facts

            policy = _agent_memory_policy(agent_id)
            if not memory_policy_allows_recall(policy):
                return tool_error("agent memory recall is disabled by policy")
            items = agent_memory_facts(agent_id, limit=int(args.get("limit") or 40))
            return tool_result(success=True, items=items, count=len(items))

        if action in {"wake_agent", "wake"}:
            from elevate_cli.agent_worker import request_wake

            status = request_wake(
                reason=str(args.get("reason") or "agent_bus"),
                actor=f"agent:{agent_id}",
                agent_id=args.get("target_agent_id") or args.get("to_agent_id") or args.get("agent_id") or agent_id,
            )
            return tool_result(success=True, worker=status)

        if action in {"run_queued_work", "tick", "drain"}:
            from elevate_cli.agent_worker import tick

            status = tick(
                actor=f"agent:{agent_id}",
                reason=str(args.get("reason") or "agent_bus"),
                agent_id=args.get("target_agent_id") or args.get("to_agent_id") or args.get("agent_id") or agent_id,
            )
            return tool_result(success=True, worker=status)

        if action in {"create_experiment", "experiment_create"}:
            return tool_result(success=True, experiment=_create_experiment(args, parent_agent))

        if action in {"run_experiment", "experiment_run", "start_experiment", "experiment_start"}:
            return tool_result(success=True, experiment=_run_experiment(args, parent_agent))

        if action in {"list_experiments", "experiments"}:
            surface = _surface_for_experiment(args, parent_agent)
            return tool_result(success=True, experiments=_list_experiments(surface))

        if action in {"evaluate_experiment", "experiment_evaluate"}:
            return tool_result(success=True, experiment=_evaluate_experiment(args, parent_agent))

        if action in {"gather_experiment_context", "experiment_context", "context_experiments"}:
            return tool_result(success=True, context=_gather_experiment_context(args, parent_agent))

        if action in {"list_cycles", "cycles", "cycle_list"}:
            return tool_result(success=True, **_list_cycles(args, parent_agent))

        if action in {"create_cycle", "cycle_create"}:
            return tool_result(success=True, **_manage_cycle("create", args, parent_agent))

        if action in {"modify_cycle", "update_cycle", "cycle_modify", "cycle_update"}:
            return tool_result(success=True, **_manage_cycle("modify", args, parent_agent))

        if action in {"remove_cycle", "delete_cycle", "cycle_remove", "cycle_delete"}:
            return tool_result(success=True, **_manage_cycle("remove", args, parent_agent))

        if action in {"browse_catalog", "catalog"}:
            items = _browse_catalog(args)
            return tool_result(success=True, items=items, count=len(items))

        if action in {"list_skills", "skills"}:
            items = _list_skills(args)
            return tool_result(success=True, items=items, count=len(items))

        return tool_error(f"unknown agent_bus action {action!r}")
    except Exception as exc:
        return tool_error(str(exc))


AGENT_BUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "agent_bus",
        "description": (
            "Native Elevate replacement for CortextOS bus commands. Use it for "
            "agent-visible tasks, approvals, activity events, heartbeat status, "
            "memory, worker wake/tick, experiments, catalog browse, and installed skills."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_task",
                        "list_tasks",
                        "update_task",
                        "claim_task",
                        "complete_task",
                        "block_task",
                        "read_task_audit",
                        "check_stale_tasks",
                        "check_human_tasks",
                        "archive_tasks",
                        "compact_tasks",
                        "create_approval",
                        "list_approvals",
                        "post_activity",
                        "log_event",
                        "list_activity",
                        "update_heartbeat",
                        "read_heartbeats",
                        "write_memory",
                        "list_memory",
                        "wake_agent",
                        "run_queued_work",
                        "create_experiment",
                        "run_experiment",
                        "list_experiments",
                        "evaluate_experiment",
                        "gather_experiment_context",
                        "list_cycles",
                        "create_cycle",
                        "modify_cycle",
                        "remove_cycle",
                        "browse_catalog",
                        "list_skills",
                    ],
                },
                "agent_id": {"type": "string"},
                "target_agent_id": {"type": "string"},
                "to_agent_id": {"type": "string"},
                "surface": {"type": "string"},
                "target_surface": {"type": "string"},
                "targetSurface": {"type": "string"},
                "task_id": {"type": "string"},
                "name": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "desc": {"type": "string"},
                "type": {"type": "string"},
                "status": {"type": "string"},
                "enabled": {"type": "boolean"},
                "priority": {"type": "string", "enum": ["urgent", "high", "normal", "low"]},
                "assignee": {"type": "string"},
                "assigned_to": {"type": "string"},
                "project": {"type": "string"},
                "needs_approval": {"type": "boolean"},
                "notes": {"type": "string"},
                "reason": {"type": "string"},
                "result": {"type": "string"},
                "summary": {"type": "string"},
                "created_by": {"type": "string"},
                "createdBy": {"type": "string"},
                "org": {"type": "string"},
                "kpi_key": {"type": "string"},
                "kpiKey": {"type": "string"},
                "due_date": {"type": "string"},
                "dueDate": {"type": "string"},
                "category": {"type": "string"},
                "context": {"type": "string"},
                "event": {"type": "string"},
                "severity": {"type": "string"},
                "message": {"type": "string"},
                "content": {"type": "string"},
                "fact": {"type": "string"},
                "metadata": {"type": "object"},
                "meta": {"type": "object"},
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "blockedBy": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "blocks": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "outputs": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "include_archived": {"type": "boolean"},
                "includeArchived": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "dryRun": {"type": "boolean"},
                "older_than_days": {"type": "integer", "minimum": 0},
                "olderThanDays": {"type": "integer", "minimum": 0},
                "experiment_id": {"type": "string"},
                "cycle": {"type": "string"},
                "cycle_name": {"type": "string"},
                "hypothesis": {"type": "string"},
                "metric": {"type": "string"},
                "metric_type": {"type": "string"},
                "direction": {"type": "string", "enum": ["higher", "lower"]},
                "window": {"type": "string"},
                "measurement": {"type": "string"},
                "every_n_runs": {"type": "integer", "minimum": 1},
                "everyNRuns": {"type": "integer", "minimum": 1},
                "loop_interval": {"type": "string"},
                "loopInterval": {"type": "string"},
                "approval_required": {"type": "boolean"},
                "approvalRequired": {"type": "boolean"},
                "baseline_value": {"type": "number"},
                "measured_value": {"type": "number"},
                "result_value": {"type": "number"},
                "score": {"type": "number"},
                "decision": {"type": "string", "enum": ["keep", "discard", "defer"]},
                "outcome": {"type": "string"},
                "learning": {"type": "string"},
                "justification": {"type": "string"},
                "changes_description": {"type": "string"},
                "experiment_commit": {"type": "string"},
                "tracking_commit": {"type": "string"},
                "query": {"type": "string"},
                "search": {"type": "string"},
                "source": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "payload": {"type": "object"},
                "policy_action": {"type": "string"},
                "policy_category": {"type": "string"},
            },
            "required": ["action"],
        },
    },
}


registry.register(
    name="agent_bus",
    toolset="agent_bus",
    schema=AGENT_BUS_SCHEMA,
    handler=lambda args, **kw: _agent_bus_tool(args, **kw),
    description="Native Elevate agent bus for tasks, approvals, heartbeat, activity, experiments, and catalog",
    emoji="",
)
