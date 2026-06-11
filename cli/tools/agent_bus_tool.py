"""Native agent bus tool.

This is the in-app agent state bus. It deliberately writes to Elevate's
existing stores only.

Surface STATE (heartbeat records, surface config, goals, experiment records,
activity events, the run index) lives in the account database via
``elevate_cli.data.surface_state`` — the same tables the dashboard cards
read, one source of truth. The legacy ``agent_activity.jsonl`` feed is
lazily bulk-imported once (sentinel: ``agent_activity.jsonl.imported``) and
never deleted; likewise each surface's legacy ``history/*.json`` run records
(sentinel: ``history/.runs_imported``). Markdown artifacts
stay on disk by design: ``learnings.md``, ``history/*.md`` run transcripts,
playbooks, and ``experiments/results.tsv``.
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
    """Legacy JSONL feed location — only used by the one-shot importer
    (and still read by web_server until it's repointed)."""
    from elevate_cli.data.paths import data_root

    return data_root() / "agent_activity.jsonl"


def _activity_record(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the original jsonl record shape from a surface_activity row.
    category/severity/kind ride inside the metadata JSON payload."""
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    inner = meta.get("metadata")
    return {
        "kind": str(meta.get("kind") or "agent_activity"),
        "agent": str(row.get("agent") or ""),
        "category": str(meta.get("category") or "action"),
        "event": str(row.get("event") or "event"),
        "severity": str(meta.get("severity") or "info"),
        "message": str(row.get("message") or ""),
        "metadata": inner if isinstance(inner, dict) else {},
        "ts": str(row.get("at") or ""),
    }


def _import_legacy_activity() -> None:
    """One-shot lazy import of the legacy agent_activity.jsonl into
    surface_activity. Gated by a sentinel marker file written only after
    the insert transaction commits, so a crash mid-import just re-runs.
    The jsonl itself is never deleted (web_server still reads it)."""
    path = _activity_log_path()
    marker = path.parent / (path.name + ".imported")
    if marker.exists() or not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict) or not str(rec.get("agent") or "").strip():
                continue
            surface_state.append_activity(
                conn,
                str(rec.get("agent")),
                str(rec.get("event") or "event"),
                message=str(rec.get("message") or ""),
                metadata={
                    "kind": str(rec.get("kind") or "agent_activity"),
                    "category": str(rec.get("category") or "action"),
                    "severity": str(rec.get("severity") or "info"),
                    "metadata": rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {},
                },
                at=str(rec.get("ts") or "") or None,
            )
    # connect() commits on clean exit — only now is the import durable.
    marker.write_text(_now_iso() + "\n", encoding="utf-8")


def _append_activity(
    *,
    agent_id: str,
    category: str,
    event: str,
    severity: str = "info",
    message: str = "",
    metadata: Any = None,
) -> dict[str, Any]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    _import_legacy_activity()
    with connect() as conn:
        row = surface_state.append_activity(
            conn,
            agent_id,
            str(event or "event"),
            message=str(message or ""),
            metadata={
                "kind": "agent_activity",
                "category": str(category or "action"),
                "severity": str(severity or "info"),
                "metadata": metadata if isinstance(metadata, dict) else {},
            },
        )
    return _activity_record(row)


def _read_activity(agent_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    _import_legacy_activity()
    clean_agent = _slug(agent_id) if agent_id else ""
    with connect() as conn:
        rows = surface_state.list_activity(
            conn, agent=clean_agent or None, limit=max(1, min(limit, 100))
        )
    return [_activity_record(row) for row in rows]


def _heartbeat_dir(agent_id: str) -> Path:
    """Workspace dir for a surface's FILE artifacts (learnings.md,
    history/*.md transcripts, experiments/results.tsv). JSON state lives in
    the account database (surface_state), not here."""
    from elevate_constants import get_account_data_dir

    return get_account_data_dir() / "heartbeats" / agent_id


def _import_legacy_runs(surface: str) -> None:
    """One-shot lazy import of a surface's legacy ``history/*.json`` run
    records into surface_runs (migration 0027). Same pattern as
    ``_import_legacy_activity``: gated by a ``history/.runs_imported``
    sentinel marker written only after the insert transaction commits, so a
    crash mid-import just re-runs. The json files are never deleted (the
    markdown transcripts + json run records stay on disk by design)."""
    hist_dir = _heartbeat_dir(surface) / "history"
    marker = hist_dir / ".runs_imported"
    if marker.exists() or not hist_dir.is_dir():
        return
    files = sorted(p for p in hist_dir.glob("*.json") if p.is_file())
    if not files:
        return
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        for path in files:
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                rec = None
            if not isinstance(rec, dict):
                # Corrupt records still index (count parity with the old
                # `ls history | wc -l` cadence check) as empty payloads.
                rec = {}
            surface_state.append_run(
                conn,
                surface,
                kind="work",
                status="ok",
                summary=str(rec.get("summary") or rec.get("did") or "") or None,
                record=rec,
                ran_at=str(rec.get("ran_at") or "").strip() or path.stem,
            )
    # connect() commits on clean exit — only now is the import durable.
    marker.write_text(_now_iso() + "\n", encoding="utf-8")


def _log_run(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    surface = _surface_for_experiment(args, parent_agent)
    _import_legacy_runs(surface)
    summary = str(args.get("summary") or args.get("message") or "").strip()
    with connect() as conn:
        run = surface_state.append_run(
            conn,
            surface,
            kind=str(args.get("kind") or "work"),
            status=str(args.get("status") or "ok"),
            summary=summary or None,
            record=args.get("record") if isinstance(args.get("record"), dict) else None,
        )
        count = surface_state.count_runs(conn, surface)
    return {"run": run, "run_count": count}


def _count_runs(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    surface = _surface_for_experiment(args, parent_agent)
    _import_legacy_runs(surface)
    with connect() as conn:
        total = surface_state.count_runs(conn, surface)
        work = surface_state.count_runs(conn, surface, kind="work")
        experiment = surface_state.count_runs(conn, surface, kind="experiment")
    return {
        "surface": surface,
        "count": total,
        "count_by_kind": {"work": work, "experiment": experiment},
    }


def _update_heartbeat(agent_id: str, message: str, status: str = "active", metadata: Any = None) -> dict[str, Any]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    ts = _now_iso()
    rec = {
        "at": ts,
        "surface": agent_id,
        "agent": agent_id,
        "status": str(status or "active"),
        "summary": str(message or "heartbeat"),
        "did": str(message or "heartbeat"),
        "ran_at": ts,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "source": "agent_bus",
    }
    with connect() as conn:
        surface_state.set_heartbeat(conn, agent_id, rec)
        if not surface_state.get_config(conn, agent_id):
            surface_state.set_config(
                conn,
                agent_id,
                {
                    "surface": agent_id,
                    "title": agent_id.replace("-", " ").title(),
                    "enabled": False,
                    "source": "agent_bus",
                },
            )
    return rec


def _read_heartbeats(agent_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    limit = max(1, min(limit, 100))
    target = _slug(agent_id) if agent_id else ""
    with connect() as conn:
        if target:
            rec = surface_state.get_heartbeat(conn, target)
            if rec:
                rec.setdefault("agent", target)
            items = [rec] if rec else []
        else:
            items = surface_state.list_heartbeats(conn, limit=limit)
    for rec in items:
        rec.setdefault("status", "unknown")
    return items[:limit]


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
    """File-artifact dir for a surface's experiments (results.tsv only —
    experiment RECORDS live in the account database)."""
    return _heartbeat_dir(surface) / "experiments"


def _cycle_key(value: Any) -> str:
    return _slug(value) or "default"


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
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        history = surface_state.list_experiments(conn, surface, limit=100)
        active_records = surface_state.list_experiments(conn, surface, status="active")
    active_by_cycle: dict[str, Any] = {}
    for rec in active_records:  # newest first — keep the freshest per cycle
        active_by_cycle.setdefault(_cycle_key(rec.get("cycle") or rec.get("metric")), rec)
    active = active_records[0] if active_records else None
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
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        surface_state.upsert_experiment(conn, surface, rec)
    _append_activity(
        agent_id=rec["createdBy"],
        category="experiment",
        event="experiment_created",
        message=rec["title"],
        metadata={"surface": surface, "experiment_id": exp_id},
    )
    return rec


def _run_experiment(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    surface = _surface_for_experiment(args, parent_agent)
    with connect() as conn:
        rec = surface_state.get_experiment(
            conn, surface, str(args.get("experiment_id") or args.get("id") or "").strip() or None
        )
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
        surface_state.upsert_experiment(conn, surface, rec)
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
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    surface = _surface_for_experiment(args, parent_agent)
    with connect() as conn:
        active = surface_state.get_experiment(
            conn, surface, str(args.get("experiment_id") or args.get("id") or "").strip() or None
        )
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
    with connect() as conn:
        surface_state.upsert_experiment(conn, surface, rec)
    _append_experiment_result(surface, rec, measured)
    _append_learning(surface, rec)
    _append_activity(
        agent_id=rec["evaluatedBy"],
        category="experiment",
        event="experiment_evaluated",
        message=f"{rec.get('title')}: {decision}",
        metadata={"surface": surface, "experiment_id": rec.get("id"), "decision": decision},
    )
    return rec


def _gather_experiment_context(args: dict[str, Any], parent_agent: Any = None) -> dict[str, Any]:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

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
    with connect() as conn:
        config = surface_state.get_config(conn, surface)
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

        if action in {"log_run", "run_log"}:
            logged = _log_run(args, parent_agent)
            return tool_result(success=True, run=logged["run"], run_count=logged["run_count"])

        if action in {"run_count", "count_runs"}:
            counted = _count_runs(args, parent_agent)
            return tool_result(
                success=True,
                surface=counted["surface"],
                count=counted["count"],
                count_by_kind=counted["count_by_kind"],
            )

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

        if action in {"get_surface_config", "surface_config"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            surface = _surface_for_experiment(args, parent_agent)
            with connect() as conn:
                config = surface_state.get_config(conn, surface)
            return tool_result(success=True, surface=surface, config=config)

        if action in {"update_surface_config", "surface_config_update"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            surface = _surface_for_experiment(args, parent_agent)
            patch = args.get("patch")
            if not isinstance(patch, dict) or not patch:
                return tool_error("patch (object) is required")
            with connect() as conn:
                config = surface_state.patch_config(conn, surface, patch)
            return tool_result(success=True, surface=surface, config=config)

        if action in {"get_goals", "surface_goals"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            surface = _surface_for_experiment(args, parent_agent)
            with connect() as conn:
                goals = surface_state.get_goals(conn, surface)
            return tool_result(success=True, surface=surface, goals=goals)

        if action in {"update_goals", "goals_update", "surface_goals_update"}:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            surface = _surface_for_experiment(args, parent_agent)
            goals = args.get("goals")
            if not isinstance(goals, dict):
                return tool_error("goals (object) is required")
            goals = dict(goals)
            goals["updated_at"] = _now_iso()
            with connect() as conn:
                saved = surface_state.set_goals(conn, surface, goals)
            return tool_result(success=True, surface=surface, goals=saved)

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
            "Native Elevate agent bus. Use it for "
            "agent-visible tasks, approvals, activity events, heartbeat status, "
            "run records (log_run after every heartbeat run / run_count for the "
            "experiment cadence — the database-backed run index the dashboard "
            "also reads), memory, worker wake/tick, experiments, surface config "
            "+ goals (get_surface_config / update_surface_config / get_goals / "
            "update_goals — the database-backed surface state the dashboard also "
            "reads), catalog browse, and installed skills."
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
                        "log_run",
                        "run_count",
                        "write_memory",
                        "list_memory",
                        "wake_agent",
                        "run_queued_work",
                        "create_experiment",
                        "run_experiment",
                        "list_experiments",
                        "evaluate_experiment",
                        "gather_experiment_context",
                        "get_surface_config",
                        "update_surface_config",
                        "get_goals",
                        "update_goals",
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
                "kind": {
                    "type": "string",
                    "enum": ["work", "experiment"],
                    "description": "Run kind for log_run (default 'work')",
                },
                "record": {
                    "type": "object",
                    "description": "Full run-record JSON payload for log_run",
                },
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
                "patch": {
                    "type": "object",
                    "description": "Shallow-merge patch for update_surface_config",
                },
                "goals": {
                    "type": "object",
                    "description": "Full goals object for update_goals (replaces the stored goals)",
                },
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
    description="Native Elevate agent bus for tasks, approvals, heartbeat, activity, run records, experiments, surface config/goals, and catalog",
    emoji="",
)
