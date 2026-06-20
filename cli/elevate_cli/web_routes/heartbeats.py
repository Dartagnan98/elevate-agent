"""Heartbeat surface and experiment routes."""

import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from elevate_cli.web_routes.heartbeats_models import (
    AgentHeartbeatMdBody as _AgentHeartbeatMdBody,
    HeartbeatAutomationEnabledBody as _HeartbeatAutomationEnabledBody,
    HeartbeatConfigPatchBody as _HeartbeatConfigPatchBody,
    HeartbeatCycleCreateBody as _HeartbeatCycleCreateBody,
    HeartbeatCyclePatchBody as _HeartbeatCyclePatchBody,
    HeartbeatGoalsPatchBody as _HeartbeatGoalsPatchBody,
    HeartbeatRouteBody as _HeartbeatRouteBody,
    HeartbeatSurfaceCreateBody as _HeartbeatSurfaceCreateBody,
    HeartbeatSurfaceEnabledBody as _HeartbeatSurfaceEnabledBody,
)


FsCacheGet = Callable[[str], Any]
FsCachePut = Callable[[str, Any, float], None]
FsCacheInvalidate = Callable[[str], None]


def create_heartbeats_router(
    *,
    fs_cache_get: FsCacheGet,
    fs_cache_put: FsCachePut,
    fs_cache_invalidate: FsCacheInvalidate,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)
    _fs_cache_get = fs_cache_get
    _fs_cache_put = fs_cache_put
    _fs_cache_invalidate = fs_cache_invalidate

    @router.get("/api/heartbeats/surfaces")
    def get_heartbeat_surfaces():
        """Per-surface heartbeat state, cached per account for a few seconds. The
        scan walks every surface dir + reads its config/history/learnings, so rapid
        polling is collapsed to one scan. Surface mutations invalidate the cache
        (see _fs_cache_invalidate('surfaces')); the short TTL is a backstop for any
        mutation path that doesn't."""
        cached = _fs_cache_get("surfaces")
        if cached is not None:
            return cached
        result = _compute_heartbeat_surfaces()
        _fs_cache_put("surfaces", result, 3.0)
        return result


    def _compute_heartbeat_surfaces():
        """Per-surface heartbeat state for the CURRENT account.

        Surface STATE (config, heartbeat record, experiments) lives in the account
        database (migration 0024); markdown artifacts (learnings.md, history/ run
        records) stay in ``<account_data_dir>/heartbeats/<surface>/``. Surfaces
        enumerate from the DB, unioned with any workspace dirs that exist
        (back-compat). Mirrors the experiments scan but Elevate-native
        and per-account-scoped. Missing rows/files degrade to empty so a surface
        that has never fired still renders.
        """
        try:
            from elevate_constants import get_account_data_dir
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            heartbeats_dir = get_account_data_dir() / "heartbeats"
            surfaces: List[Dict[str, Any]] = []

            # Authoritative enabled state lives on the cron job, not the config — a
            # paused/resumed toggle updates the job first. Map surface -> job.enabled
            # so a card reflects whether the heartbeat will actually fire, even if a
            # stale config copy disagrees.
            job_by_surface: Dict[str, Dict[str, Any]] = {}
            job_enabled_by_surface: Dict[str, bool] = {}
            # A surface's heartbeat is split into several FOCUSED crons (origin.focus) —
            # collect them per surface like automations so each card lists them; the
            # surface counts as enabled if ANY focused heartbeat is enabled.
            heartbeats_by_surface: Dict[str, List[Dict[str, Any]]] = {}
            # Surface automations are the per-surface "kit" cron jobs that pair with
            # each heartbeat (origin.type=="surface-automation"). Group them by
            # surface here from the SAME job scan so each card can list its own.
            automations_by_surface: Dict[str, List[Dict[str, Any]]] = {}
            try:
                from cron.jobs import list_jobs as _list_jobs

                for _job in _list_jobs(include_disabled=True):
                    _origin = _job.get("origin") or {}
                    _otype = _origin.get("type")
                    _surf = _origin.get("surface")
                    if not (isinstance(_surf, str) and _surf):
                        continue
                    if _otype == "surface-heartbeat":
                        _is_owner = bool(_origin.get("experiment_owner"))
                        # Representative job for the surface = the experiment owner when
                        # present (it carries the surface-level cadence/settings).
                        if _surf not in job_by_surface or _is_owner:
                            job_by_surface[_surf] = _job
                        _hb_enabled = bool(_job.get("enabled", True))
                        job_enabled_by_surface[_surf] = (
                            job_enabled_by_surface.get(_surf, False) or _hb_enabled
                        )
                        _hb_sched_obj = _job.get("schedule") or {}
                        _hb_sched = (
                            str(_job.get("schedule_display") or "").strip()
                            or str(_hb_sched_obj.get("display") or "").strip()
                            or str(_hb_sched_obj.get("expr") or "").strip()
                        )
                        heartbeats_by_surface.setdefault(_surf, []).append(
                            {
                                "id": _job.get("id"),
                                "name": _job.get("name") or _job.get("id") or "heartbeat",
                                "focus": str(_origin.get("focus") or ""),
                                "schedule": _hb_sched,
                                "enabled": _hb_enabled,
                                "experiment_owner": _is_owner,
                                "last_run_at": _job.get("last_run_at"),
                            }
                        )
                    elif _otype == "surface-automation":
                        _sched_obj = _job.get("schedule") or {}
                        _sched = (
                            str(_job.get("schedule_display") or "").strip()
                            or str(_sched_obj.get("display") or "").strip()
                            or str(_sched_obj.get("expr") or "").strip()
                        )
                        automations_by_surface.setdefault(_surf, []).append(
                            {
                                "id": _job.get("id"),
                                "name": _job.get("name") or _job.get("id") or "automation",
                                "schedule": _sched,
                                "enabled": bool(_job.get("enabled", True)),
                                "last_run_at": _job.get("last_run_at"),
                            }
                        )
            except Exception:
                # No cron access -> fall back to the config's own enabled below.
                job_enabled_by_surface = {}
                automations_by_surface = {}

            # Stable order: sort each surface's automations by name (case-insensitive).
            for _list in automations_by_surface.values():
                _list.sort(key=lambda a: str(a.get("name") or "").lower())
            # Stable order: experiment owner first, then by name.
            for _list in heartbeats_by_surface.values():
                _list.sort(
                    key=lambda h: (not h.get("experiment_owner"), str(h.get("name") or "").lower())
                )

            def _read_json(path: Path) -> Optional[Any]:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    return None

            with connect() as conn:
                # Surfaces enumerate from the account DB (state + registry rows),
                # unioned with any workspace dirs that exist (back-compat / markdown).
                surface_names = set(surface_state.list_state_surfaces(conn))
                if heartbeats_dir.is_dir():
                    surface_names.update(
                        p.name for p in heartbeats_dir.iterdir() if p.is_dir()
                    )

                for surface_name in sorted(surface_names):
                    surface_dir = heartbeats_dir / surface_name

                    # Config (account DB; missing row degrades to None like the old
                    # missing config.json read).
                    config: Optional[Dict[str, Any]] = (
                        surface_state.get_config(conn, surface_name) or None
                    )
                    # Overlay the AUTHORITATIVE enabled from the cron job so the card
                    # never shows a stale config value (the toggle writes the job
                    # first). Falls back to the config's own enabled when no job exists.
                    if surface_name in job_enabled_by_surface:
                        if not isinstance(config, dict):
                            config = {}
                        config["enabled"] = job_enabled_by_surface[surface_name]
                    job = job_by_surface.get(surface_name)
                    if job:
                        if not isinstance(config, dict):
                            config = {}
                        if job.get("agent"):
                            config["agent"] = job.get("agent")
                        if job.get("deliver"):
                            config["deliver"] = job.get("deliver")
                        if job.get("model"):
                            config["model"] = job.get("model")
                        if not config.get("cadence"):
                            schedule = job.get("schedule") or {}
                            config["cadence"] = (
                                job.get("schedule_display")
                                or (schedule.get("display") if isinstance(schedule, dict) else None)
                                or (schedule.get("expr") if isinstance(schedule, dict) else None)
                            )
                    if isinstance(config, dict) and not str(config.get("agent") or "").strip():
                        try:
                            from cron.jobs import resolve_surface_agent

                            inferred_agent = resolve_surface_agent(surface_name, {"config": config})
                            if inferred_agent:
                                config["agent"] = inferred_agent
                        except Exception:
                            pass

                    # Work-run history: prefer the DB run index (surface_runs,
                    # migration 0027) — newest row wins. Surfaces that never
                    # logged/imported runs to the DB fall back to the legacy
                    # history/*.json file scan (markdown transcripts and old
                    # json run records stay on disk).
                    db_runs = surface_state.list_runs(conn, surface_name, limit=1)
                    if db_runs:
                        newest_run = db_runs[0]
                        run_count = surface_state.count_runs(conn, surface_name)
                        last_run = newest_run.get("record") or {
                            "ran_at": newest_run.get("ran_at"),
                            "summary": newest_run.get("summary"),
                            "status": newest_run.get("status"),
                        }
                    else:
                        history_files: List[Path] = []
                        hist_dir = surface_dir / "history"
                        if hist_dir.is_dir():
                            history_files = sorted(
                                (p for p in hist_dir.glob("*.json") if p.is_file()),
                                key=lambda p: p.name,
                                reverse=True,
                            )
                        run_count = len(history_files)
                        last_run = _read_json(history_files[0]) if history_files else None
                    if last_run is None:
                        # Fall back to the agent_bus heartbeat record (account DB).
                        last_run = surface_state.get_heartbeat(conn, surface_name)

                    # Learnings (raw markdown, stays on disk)
                    learnings = ""
                    learnings_path = surface_dir / "learnings.md"
                    if learnings_path.is_file():
                        try:
                            learnings = learnings_path.read_text(encoding="utf-8")
                        except Exception:
                            learnings = ""

                    # Experiments (account DB): most recent active record + the
                    # completed keep/discard history.
                    active_exp = surface_state.get_experiment(conn, surface_name)
                    exp_history: List[Any] = surface_state.list_experiments(
                        conn, surface_name, status="completed"
                    )

                    # Newest first by timestamp when present (updated_at order is
                    # the fallback, matching the old filename sort).
                    def _exp_ts(e: Any) -> str:
                        return str(e.get("ts") or "") if isinstance(e, dict) else ""

                    exp_history.sort(key=_exp_ts, reverse=True)

                    kept = sum(
                        1
                        for e in exp_history
                        if isinstance(e, dict) and e.get("decision") == "keep"
                    )
                    discarded = sum(
                        1
                        for e in exp_history
                        if isinstance(e, dict) and e.get("decision") == "discard"
                    )
                    decided = kept + discarded
                    keep_rate = round((kept / decided) * 100) if decided else 0

                    # Job health: stall backoff + last status, so a backed-off
                    # heartbeat is visible on its card instead of silently sleeping
                    # for up to 6h (the stall cap) with no explanation.
                    job_health: Optional[Dict[str, Any]] = None
                    if job:
                        job_health = {
                            "lastStatus": job.get("last_status"),
                            "lastRunAt": job.get("last_run_at"),
                            "nextRunAt": job.get("next_run_at"),
                            "stallCount": job.get("stall_count") or 0,
                            "backoffUntil": job.get("backoff_until"),
                            "backoffMinutes": job.get("backoff_minutes"),
                            "lastError": job.get("last_error"),
                        }

                    surfaces.append(
                        {
                            "surface": surface_name,
                            "config": config,
                            "runCount": run_count,
                            "lastRun": last_run,
                            "jobHealth": job_health,
                            "learnings": learnings,
                            "heartbeats": heartbeats_by_surface.get(surface_name, []),
                            "automations": automations_by_surface.get(surface_name, []),
                            "experiments": {
                                "active": active_exp,
                                "history": exp_history,
                                "stats": {
                                    "total": len(exp_history),
                                    "kept": kept,
                                    "discarded": discarded,
                                    "keepRate": keep_rate,
                                },
                            },
                        }
                    )

            return {"surfaces": surfaces}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/heartbeats/surfaces failed")
            raise HTTPException(status_code=500, detail=f"Heartbeat surfaces failed: {exc}")


    @router.post("/api/heartbeats/surfaces")
    def create_heartbeat_surface(body: _HeartbeatSurfaceCreateBody):
        """Create a NEW custom surface from the template + overrides (add-agent
        equivalent). Registers it in the account surface registry, scaffolds its workspace,
        and seeds an opt-in (off) cron job. The realtor turns it on from the Heartbeat page.
        """
        try:
            from cron.jobs import create_surface

            spec = {
                k: v
                for k, v in {
                    "title": body.title,
                    "name": body.name,
                    "schedule": body.schedule,
                    "goal": body.goal,
                    "experiment": body.experiment,
                    "config": body.config,
                }.items()
                if v is not None
            }
            result = create_surface(body.surface, spec, created_by="user")
            # Mirror the registry write into the account DB (migration 0024) so
            # PG-backed reads see the new surface immediately, whichever storage
            # cron.jobs.register_surface targets.
            try:
                from elevate_cli.data import connect
                from elevate_cli.data import surface_state

                with connect() as conn:
                    surface_state.upsert_registry(
                        conn,
                        result["surface"],
                        dict(result.get("spec") or {}),
                        created_by="user",
                    )
            except Exception:
                _log.warning("surface registry DB mirror failed", exc_info=True)
            _fs_cache_invalidate("surfaces")
            return {"ok": True, **result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/heartbeats/surfaces failed")
            raise HTTPException(status_code=500, detail=f"Create surface failed: {exc}")


    @router.delete("/api/heartbeats/surfaces/{surface}")
    def delete_heartbeat_surface(surface: str, force: bool = False):
        """Delete a custom heartbeat surface, its generated jobs, and its workspace.

        Built-in surfaces are protected unless ``force=true`` is passed. This is
        primarily the inverse of the add-agent/import flow: the surface registry,
        surface heartbeat cron, surface-automation crons, and
        ``accounts/<key>/heartbeats/<surface>/`` are removed together.
        """
        try:
            from cron.jobs import delete_surface
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            key = (surface or "").strip().lower()
            try:
                result: Optional[Dict[str, Any]] = delete_surface(surface, force=bool(force))
            except LookupError:
                result = None  # may still exist only in the account DB — checked below

            # Purge the account-DB state (migration 0024): registry row, state row,
            # experiments, and goals history all go with the surface.
            with connect() as conn:
                spec = surface_state.list_registry(conn).get(key)
                if result is None:
                    known = key in surface_state.list_state_surfaces(conn)
                    if spec is None and not known:
                        raise LookupError(f"surface '{key}' not found")
                    if spec and spec.get("builtin") and not force:
                        raise ValueError("built-in heartbeat surfaces cannot be deleted")
                removed_registry = surface_state.remove_registry(conn, key)
                conn.execute("DELETE FROM surface_state WHERE surface = ?", (key,))
                conn.execute("DELETE FROM surface_experiments WHERE surface = ?", (key,))
                conn.execute("DELETE FROM surface_goals_history WHERE surface = ?", (key,))

            if result is None:
                result = {
                    "ok": True,
                    "surface": key,
                    "removed": {"registry": removed_registry, "files": False, "jobs": []},
                }
            elif removed_registry and isinstance(result.get("removed"), dict):
                result["removed"]["registry"] = True
            _fs_cache_invalidate("surfaces")
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("DELETE /api/heartbeats/surfaces/%s failed", surface)
            raise HTTPException(status_code=500, detail=f"Delete surface failed: {exc}")


    def _experiment_stats(experiments: List[Dict[str, Any]]) -> Dict[str, int]:
        """Per-surface experiment stats, computed at read time (never persisted)."""
        running = sum(1 for e in experiments if e.get("status") == "running")
        proposed = sum(1 for e in experiments if e.get("status") == "proposed")
        completed = sum(1 for e in experiments if e.get("status") == "completed")
        kept = sum(1 for e in experiments if e.get("decision") == "keep")
        discarded = sum(1 for e in experiments if e.get("decision") == "discard")
        decided = kept + discarded
        return {
            "total": len(experiments),
            "running": running,
            "proposed": proposed,
            "completed": completed,
            "kept": kept,
            "discarded": discarded,
            "keepRate": round((kept / decided) * 100) if decided else 0,
        }


    def _experiment_summary(surfaces: List[Dict[str, Any]]) -> Dict[str, int]:
        """Fleet-wide rollup across all surfaces."""
        kept = sum(s["stats"]["kept"] for s in surfaces)
        discarded = sum(s["stats"]["discarded"] for s in surfaces)
        decided = kept + discarded
        return {
            "surfaces": len(surfaces),
            "cycles": sum(len(s["cycles"]) for s in surfaces),
            "total": sum(s["stats"]["total"] for s in surfaces),
            "running": sum(s["stats"]["running"] for s in surfaces),
            "completed": sum(s["stats"]["completed"] for s in surfaces),
            "kept": kept,
            "discarded": discarded,
            "keepRate": round((kept / decided) * 100) if decided else 0,
        }


    @router.get("/api/heartbeats/experiments")
    def get_heartbeat_experiments():
        """Dedicated experiments view for the CURRENT account — the data behind the
        Experiments page. For every surface, reads the cycle definition (the config's
        ``experiment`` block / ``cycles[]``), the active (proposed+running) experiments,
        and the completed ones — all from the account DB (migration 0024) — normalizes
        each to one shape, folds in learnings.md (still on disk), and computes
        per-surface + fleet stats. Read-only; the surface-heartbeat EXPERIMENT loop owns
        all writes. Elevate-native port of scanExperiments().
        """
        try:
            from elevate_constants import get_account_data_dir
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            heartbeats_dir = get_account_data_dir() / "heartbeats"
            out_surfaces: List[Dict[str, Any]] = []

            with connect() as conn:
                # Surfaces enumerate from the account DB (state + registry rows),
                # unioned with any workspace dirs that exist (markdown back-compat).
                surface_names = set(surface_state.list_state_surfaces(conn))
                if heartbeats_dir.is_dir():
                    surface_names.update(
                        p.name for p in heartbeats_dir.iterdir() if p.is_dir()
                    )
                if not surface_names:
                    return {"surfaces": out_surfaces, "summary": _experiment_summary([])}

                for surface_name in sorted(surface_names):
                    surface_dir = heartbeats_dir / surface_name
                    config = surface_state.get_config(conn, surface_name)
                    try:
                        from cron.jobs import resolve_surface_agent

                        agent_name = resolve_surface_agent(
                            surface_name,
                            {"config": config if isinstance(config, dict) else {}},
                        )
                    except Exception:
                        agent_name = (
                            str(config.get("agent") or "").strip()
                            if isinstance(config, dict)
                            else ""
                        )
                    agent_name = agent_name or surface_name
                    exp_cfg = config.get("experiment") if isinstance(config, dict) else None
                    exp_cfg = exp_cfg if isinstance(exp_cfg, dict) else {}

                    # Cycles are agent-creatable DATA: the real config.cycles[] array,
                    # falling back (read-only) to the migrated legacy ``experiment`` block.
                    try:
                        from cron.cycles import list_cycles as _list_cycles
                        cycles: List[Dict[str, Any]] = _list_cycles(surface_name)
                    except Exception:
                        cycles = []
                    cycles = [
                        {**c, "agent": c.get("agent") or agent_name}
                        for c in cycles
                        if isinstance(c, dict)
                    ]

                    # Metric/direction/window context for normalizing experiments below.
                    cycle_by_metric = {
                        str(c.get("metric") or ""): c
                        for c in cycles
                        if isinstance(c, dict) and c.get("metric")
                    }
                    _ctx = cycles[0] if cycles else exp_cfg
                    c_metric = _ctx.get("metric")
                    c_direction = _ctx.get("direction")
                    c_window = _ctx.get("window")

                    def _normalize_experiment(r: Dict[str, Any], *, active: bool = False) -> Dict[str, Any]:
                        metric = r.get("metric") or c_metric
                        cycle_ctx = cycle_by_metric.get(str(metric or "")) or _ctx
                        status = str(r.get("status") or ("running" if active else "completed")).lower()
                        result_value = (
                            r.get("result_value")
                            if r.get("result_value") is not None
                            else r.get("result")
                        )
                        baseline_value = (
                            r.get("baseline_value")
                            if r.get("baseline_value") is not None
                            else r.get("baseline")
                        )
                        return {
                            "id": r.get("id") or r.get("ts"),
                            "surface": surface_name,
                            "agent": agent_name,
                            "status": status,
                            "decision": r.get("decision"),
                            "hypothesis": r.get("hypothesis"),
                            "changes_description": r.get("surface_change") or r.get("changes_description"),
                            "baseline": baseline_value,
                            "result": None if active and status == "running" else result_value,
                            "learning": r.get("learning"),
                            "metric": metric,
                            "direction": r.get("direction") or cycle_ctx.get("direction") or c_direction,
                            "window": r.get("window") or cycle_ctx.get("window") or c_window,
                            "created_at": r.get("created_at") or r.get("createdAt") or r.get("started_at") or r.get("ts"),
                            "started_at": r.get("started_at"),
                            "completed_at": r.get("completed_at") or r.get("ts"),
                        }

                    experiments: List[Dict[str, Any]] = []
                    seen_exp_ids: set[str] = set()

                    # Active (proposed + running) experiments from the account DB.
                    for r in surface_state.list_experiments(conn, surface_name, status="active"):
                        if not isinstance(r, dict):
                            continue
                        rid = str(r.get("id") or "")
                        if rid and rid in seen_exp_ids:
                            continue
                        experiments.append(_normalize_experiment(r, active=True))
                        if rid:
                            seen_exp_ids.add(rid)

                    # Completed (keep/discard) experiments from the account DB.
                    hist_records: List[Dict[str, Any]] = [
                        r
                        for r in surface_state.list_experiments(
                            conn, surface_name, status="completed"
                        )
                        if isinstance(r, dict)
                    ]
                    hist_records.sort(
                        key=lambda e: str(
                            e.get("completed_at")
                            or e.get("started_at")
                            or e.get("created_at")
                            or e.get("createdAt")
                            or e.get("ts")
                            or ""
                        ),
                        reverse=True,
                    )
                    for r in hist_records:
                        rid = str(r.get("id") or r.get("ts") or "")
                        if rid and rid in seen_exp_ids:
                            continue
                        experiments.append(_normalize_experiment(r))
                        if rid:
                            seen_exp_ids.add(rid)

                    experiments.sort(
                        key=lambda e: str(e.get("completed_at") or e.get("started_at") or e.get("created_at") or ""),
                        reverse=True,
                    )

                    learnings = ""
                    lp = surface_dir / "learnings.md"
                    if lp.is_file():
                        try:
                            learnings = lp.read_text(encoding="utf-8")
                        except Exception:
                            learnings = ""

                    out_surfaces.append({
                        "surface": surface_name,
                        "agent": agent_name,
                        "cycles": cycles,
                        "experiments": experiments,
                        "learnings": learnings,
                        "stats": _experiment_stats(experiments),
                    })

            return {"surfaces": out_surfaces, "summary": _experiment_summary(out_surfaces)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/heartbeats/experiments failed")
            raise HTTPException(status_code=500, detail=f"Heartbeat experiments failed: {exc}")


    @router.get("/api/experiments")
    def list_experiments_alias(surface: Optional[str] = None):
        """native experiment list backed by native heartbeat experiments."""
        try:
            if surface:
                from tools.agent_bus_tool import _list_experiments

                return {"experiments": _list_experiments(surface)}
            return get_heartbeat_experiments()
        except Exception as exc:
            _log.exception("GET /api/experiments failed")
            raise HTTPException(status_code=500, detail=f"List experiments failed: {exc}")


    @router.post("/api/experiments")
    def create_experiment_alias(body: Dict[str, Any]):
        """Create a native heartbeat experiment through the Cortext-style HTTP path."""
        try:
            from tools.agent_bus_tool import _create_experiment

            return {"ok": True, "experiment": _create_experiment(dict(body or {}))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/experiments failed")
            raise HTTPException(status_code=500, detail=f"Create experiment failed: {exc}")


    @router.post("/api/experiments/{experiment_id}/run")
    def run_experiment_alias(experiment_id: str, body: Optional[Dict[str, Any]] = None):
        """Start a native heartbeat experiment through the Cortext-style HTTP path."""
        try:
            from tools.agent_bus_tool import _run_experiment

            payload = dict(body or {})
            payload.setdefault("experiment_id", experiment_id)
            return {"ok": True, "experiment": _run_experiment(payload)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/experiments/%s/run failed", experiment_id)
            raise HTTPException(status_code=500, detail=f"Run experiment failed: {exc}")


    @router.post("/api/experiments/{experiment_id}/evaluate")
    def evaluate_experiment_alias(experiment_id: str, body: Dict[str, Any]):
        """Evaluate a native heartbeat experiment through the Cortext-style HTTP path."""
        try:
            from tools.agent_bus_tool import _evaluate_experiment

            payload = dict(body or {})
            payload.setdefault("experiment_id", experiment_id)
            return {"ok": True, "experiment": _evaluate_experiment(payload)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/experiments/%s/evaluate failed", experiment_id)
            raise HTTPException(status_code=500, detail=f"Evaluate experiment failed: {exc}")


    def _validate_heartbeat_surface(surface: str) -> str:
        """Return the trimmed surface name if it's a known surface for the current
        account — present in the account DB (state/registry rows, migration 0024)
        OR with a heartbeat workspace dir (back-compat) — else raise 400/404.
        Cycle endpoints are scoped to real surfaces only.
        """
        from elevate_constants import get_account_data_dir

        surface_key = (surface or "").strip()
        if not surface_key:
            raise HTTPException(status_code=400, detail="surface is required")
        surface_dir = get_account_data_dir() / "heartbeats" / surface_key
        if surface_dir.is_dir():
            return surface_key
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                if surface_key in surface_state.list_state_surfaces(conn):
                    return surface_key
        except Exception:
            _log.warning("surface validation DB lookup failed", exc_info=True)
        raise HTTPException(status_code=404, detail=f"No heartbeat surface '{surface_key}'")


    def _validate_heartbeat_agent(agent_id: str) -> str:
        """Resolve + validate an agent id for the per-agent heartbeat endpoints."""
        from cron.jobs import _slug_agent, _HEARTBEAT_CRON_EXCLUDED_AGENTS

        aid = _slug_agent(agent_id)
        if not aid:
            raise HTTPException(status_code=400, detail="invalid agent id")
        if aid in _HEARTBEAT_CRON_EXCLUDED_AGENTS:
            raise HTTPException(status_code=404, detail=f"agent '{aid}' has no heartbeat")
        return aid


    def _agent_heartbeat_job(aid: str) -> Optional[Dict[str, Any]]:
        """The agent-bound 'heartbeat' cron job, if seeded."""
        from cron.jobs import load_jobs, _slug_agent

        for j in load_jobs():
            if (j.get("name") or "").strip().lower() == "heartbeat" and _slug_agent(
                str(j.get("agent") or "")
            ) == aid:
                return j
        return None


    @router.get("/api/agents/{agent_id}/heartbeat-md")
    def get_agent_heartbeat_md(agent_id: str):
        """Read an agent's HEARTBEAT.md (the 10-step beat it runs each cycle) plus its
        heartbeat cron state. Seeds the file from the role-aware template if missing."""
        try:
            aid = _validate_heartbeat_agent(agent_id)
            from cron.jobs import ensure_agent_heartbeat_md, agent_heartbeat_md_path

            ensure_agent_heartbeat_md(aid)
            path = agent_heartbeat_md_path(aid)
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            job = _agent_heartbeat_job(aid)
            enabled = bool(job and job.get("enabled", True) and job.get("state") != "paused")
            return {
                "agent": aid,
                "path": str(path),
                "content": content,
                "job_id": (job or {}).get("id"),
                "enabled": enabled,
            }
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/agents/%s/heartbeat-md failed", agent_id)
            raise HTTPException(status_code=500, detail=f"read heartbeat-md failed: {exc}")


    @router.put("/api/agents/{agent_id}/heartbeat-md")
    def put_agent_heartbeat_md(agent_id: str, body: _AgentHeartbeatMdBody):
        """Overwrite an agent's HEARTBEAT.md (manual edit from the Agent Hub)."""
        try:
            aid = _validate_heartbeat_agent(agent_id)
            from cron.jobs import agent_heartbeat_md_path

            path = agent_heartbeat_md_path(aid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.content or "", encoding="utf-8")
            return {"ok": True, "agent": aid, "path": str(path)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PUT /api/agents/%s/heartbeat-md failed", agent_id)
            raise HTTPException(status_code=500, detail=f"write heartbeat-md failed: {exc}")


    @router.get("/api/heartbeats/surfaces/{surface}/cycles")
    def list_heartbeat_cycles(surface: str):
        """List a surface's experiment cycles (the real ``cycles[]`` array, falling
        back to the migrated legacy ``experiment`` block). Read-only."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.cycles import list_cycles
            return {"cycles": list_cycles(surface_key)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/heartbeats/surfaces/%s/cycles failed", surface)
            raise HTTPException(status_code=500, detail=f"List cycles failed: {exc}")


    @router.post("/api/heartbeats/surfaces/{surface}/cycles")
    def create_heartbeat_cycle(surface: str, body: _HeartbeatCycleCreateBody):
        """Create a new agent-creatable experiment cycle on a surface."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.cycles import manage_cycle

            opts = {k: v for k, v in body.model_dump().items() if v is not None}
            result = manage_cycle(surface_key, "create", **opts)
            if not result.get("ok"):
                raise HTTPException(status_code=400, detail=result.get("error") or "create failed")
            return result
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/heartbeats/surfaces/%s/cycles failed", surface)
            raise HTTPException(status_code=500, detail=f"Create cycle failed: {exc}")


    @router.patch("/api/heartbeats/surfaces/{surface}/cycles/{name}")
    def modify_heartbeat_cycle(surface: str, name: str, body: _HeartbeatCyclePatchBody):
        """Patch supplied fields of a surface cycle (matched by name, case-insensitive)."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.cycles import manage_cycle

            opts = {k: v for k, v in body.model_dump().items() if v is not None}
            result = manage_cycle(surface_key, "modify", name=name, **opts)
            if not result.get("ok"):
                err = result.get("error") or "modify failed"
                status = 404 if "not found" in err.lower() else 400
                raise HTTPException(status_code=status, detail=err)
            return result
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PATCH /api/heartbeats/surfaces/%s/cycles/%s failed", surface, name)
            raise HTTPException(status_code=500, detail=f"Modify cycle failed: {exc}")


    @router.delete("/api/heartbeats/surfaces/{surface}/cycles/{name}")
    def remove_heartbeat_cycle(surface: str, name: str):
        """Remove a surface cycle by name (case-insensitive)."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.cycles import manage_cycle

            result = manage_cycle(surface_key, "remove", name=name)
            if not result.get("ok"):
                err = result.get("error") or "remove failed"
                status = 404 if "not found" in err.lower() else 400
                raise HTTPException(status_code=status, detail=err)
            return result
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("DELETE /api/heartbeats/surfaces/%s/cycles/%s failed", surface, name)
            raise HTTPException(status_code=500, detail=f"Remove cycle failed: {exc}")


    # ─── Surface delivery routing (each agent routes to its own channel/bot) ───────
    def _surface_heartbeat_jobs(surface_key: str) -> List[Dict[str, Any]]:
        """ALL account-scoped focused heartbeat crons for a surface (enabled or not)."""
        from cron.jobs import list_jobs

        return [
            job
            for job in list_jobs(include_disabled=True)
            if (job.get("origin") or {}).get("type") == "surface-heartbeat"
            and (job.get("origin") or {}).get("surface") == surface_key
        ]


    def _surface_heartbeat_job(surface_key: str) -> Optional[Dict[str, Any]]:
        """The representative heartbeat cron for a surface — the experiment owner when
        present (it carries the surface-level cadence/settings), else any."""
        jobs = _surface_heartbeat_jobs(surface_key)
        if not jobs:
            return None
        for job in jobs:
            if (job.get("origin") or {}).get("experiment_owner"):
                return job
        return jobs[-1]


    def _delivery_routes() -> List[Dict[str, str]]:
        """Available delivery routes for the picker: in-app (local) + every channel the
        account has connected (the channel directory — Telegram/Discord/Slack/…). Each
        agent/surface can route to its own channel, faithful to CTRL Flow's per-agent
        bot/channel routing."""
        routes: List[Dict[str, str]] = [
            {"value": "local", "label": "In-app (default)", "platform": "local"}
        ]
        try:
            from gateway.channel_directory import load_directory

            directory = load_directory()
            for platform, channels in (directory.get("platforms") or {}).items():
                channels = [c for c in (channels or []) if c.get("id")]
                if not channels:
                    continue  # platform not actually connected — skip the noise
                routes.append(
                    {"value": platform, "label": f"{platform.title()} (home)", "platform": platform}
                )
                for ch in channels:
                    cid = ch["id"]
                    name = ch.get("name") or cid
                    routes.append(
                        {"value": f"{platform}:{cid}", "label": f"{name} ({platform})", "platform": platform}
                    )
        except Exception:
            _log.warning("delivery routes: channel directory unavailable", exc_info=True)
        return routes


    @router.get("/api/heartbeats/surfaces/{surface}/route")
    def get_heartbeat_surface_route(surface: str):
        """Current delivery route for a surface + the routes available to pick from."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            job = _surface_heartbeat_job(surface_key)
            deliver = (job or {}).get("deliver") or "local"
            return {"surface": surface_key, "deliver": deliver, "routes": _delivery_routes()}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/heartbeats/surfaces/%s/route failed", surface)
            raise HTTPException(status_code=500, detail=f"Get route failed: {exc}")


    @router.post("/api/heartbeats/surfaces/{surface}/route")
    def set_heartbeat_surface_route(surface: str, body: _HeartbeatRouteBody):
        """Route a surface's heartbeat output to a channel/bot (or 'local' = in-app).
        Updates the authoritative cron job's ``deliver`` + mirrors to the surface
        config in the account DB."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.jobs import update_job

            deliver = (body.deliver or "local").strip() or "local"
            valid = {r["value"] for r in _delivery_routes()}
            platform0 = deliver.split(":")[0]
            if deliver not in valid and platform0 != "local":
                # Accept explicit ``platform:chat`` forms whose platform is known even
                # if the directory cache is stale.
                from cron.scheduler import _is_known_delivery_platform

                if not _is_known_delivery_platform(platform0):
                    raise HTTPException(status_code=400, detail=f"unknown delivery route: {deliver}")
            # Route ALL of the surface's focused heartbeats to the same channel.
            surface_jobs = _surface_heartbeat_jobs(surface_key)
            if not surface_jobs:
                raise HTTPException(
                    status_code=404, detail=f"No heartbeat job for surface '{surface_key}'"
                )
            updated = None
            for job in surface_jobs:
                updated = update_job(job["id"], {"deliver": deliver}) or updated
            try:
                from elevate_cli.data import connect
                from elevate_cli.data import surface_state

                with connect() as conn:
                    surface_state.patch_config(conn, surface_key, {"deliver": deliver})
            except Exception:
                _log.warning("route config mirror failed for %s", surface_key, exc_info=True)
            return {"surface": surface_key, "deliver": (updated or {}).get("deliver", deliver)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/heartbeats/surfaces/%s/route failed", surface)
            raise HTTPException(status_code=500, detail=f"Set route failed: {exc}")



    @router.post("/api/heartbeats/surfaces/{surface}/enabled")
    def set_heartbeat_surface_enabled(surface: str, body: _HeartbeatSurfaceEnabledBody):
        """Turn a surface heartbeat ON or OFF (opt-in) for the CURRENT account.

        Surface heartbeats are seeded OFF (they run agent passes on the realtor's
        box). The realtor opts in here. This flips the AUTHORITATIVE cron job via the
        canonical resume/pause paths — ``resume_job`` recomputes a fresh future
        ``next_run_at`` so an enabled heartbeat actually schedules and never gets
        stuck — then mirrors ``enabled`` into the surface config (account DB).
        """
        try:
            from cron.jobs import list_jobs, pause_job, resume_job

            want = bool(body.enabled)
            surface_key = (surface or "").strip()
            if not surface_key:
                raise HTTPException(status_code=400, detail="surface is required")

            # A surface's heartbeat is split into several FOCUSED crons — flip ALL of
            # them so the card toggle controls the whole surface (account-scoped).
            surface_jobs = [
                j
                for j in list_jobs(include_disabled=True)
                if (j.get("origin") or {}).get("type") == "surface-heartbeat"
                and (j.get("origin") or {}).get("surface") == surface_key
            ]
            if not surface_jobs:
                raise HTTPException(
                    status_code=404,
                    detail=f"No heartbeat job for surface '{surface_key}'",
                )

            # Flip each via the canonical cron paths (resume recomputes next_run_at).
            updated = None
            for job in surface_jobs:
                if want:
                    updated = resume_job(job["id"]) or updated
                else:
                    updated = (
                        pause_job(job["id"], reason="surface heartbeat disabled by realtor")
                        or updated
                    )
            if not updated:
                raise HTTPException(status_code=404, detail="Job not found")

            # Keep the surface config (account DB) in sync so it never drifts from the job.
            try:
                from elevate_cli.data import connect
                from elevate_cli.data import surface_state

                with connect() as conn:
                    surface_state.patch_config(conn, surface_key, {"enabled": want})
            except Exception:
                # Job state is authoritative; a config write hiccup is non-fatal.
                _log.warning("heartbeat %s: config enabled sync failed", surface_key, exc_info=True)

            _fs_cache_invalidate("surfaces")  # reflect the toggle immediately
            return {"surface": surface_key, "enabled": bool(updated.get("enabled", want))}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/heartbeats/surfaces/%s/enabled failed", surface)
            raise HTTPException(status_code=500, detail=f"Heartbeat toggle failed: {exc}")


    _HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    # Allowlist of per-surface heartbeat settings the dashboard may edit. The
    # backend still stores these under ``surface`` workspaces, but the UI presents
    # them as ordinary heartbeats.
    _SURFACE_CONFIG_EDITABLE = {
        "goal",
        "cadence",
        "agent",
        "model",
        "timezone",
        "day_mode_start",
        "day_mode_end",
        "communication_style",
        "approval_rules",
        "max_session_seconds",
        "heartbeat_report_mode",
    }


    def _normalize_heartbeat_report_mode(value: Any) -> str:
        raw = str(value or "").strip().lower().replace("_", "-")
        if raw in {"notify", "notifying", "always", "always-notify", "every-run", "report"}:
            return "notify"
        if raw in {"quiet", "silent", "changes", "change-only", "important", "important-only"}:
            return "quiet"
        raise HTTPException(
            status_code=400,
            detail="heartbeat_report_mode must be quiet or notify",
        )


    @router.get("/api/heartbeats/surfaces/{surface}/config")
    def get_heartbeat_surface_config(surface: str):
        """Return a surface's config (account DB) plus its current day/night mode. Read-only."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.jobs import day_night_mode
            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                cfg: Dict[str, Any] = surface_state.get_config(conn, surface_key)
            if not str(cfg.get("agent") or "").strip():
                try:
                    from cron.jobs import resolve_surface_agent

                    inferred_agent = resolve_surface_agent(surface_key, {"config": cfg})
                    if inferred_agent:
                        cfg["agent"] = inferred_agent
                except Exception:
                    pass
            return {"surface": surface_key, "config": cfg, "mode": day_night_mode(cfg)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/heartbeats/surfaces/%s/config failed", surface)
            raise HTTPException(status_code=500, detail=f"Get surface config failed: {exc}")


    @router.patch("/api/heartbeats/surfaces/{surface}/config")
    def patch_heartbeat_surface_config(surface: str, body: _HeartbeatConfigPatchBody):
        """Allowlist-merge editable settings into a surface's config (account DB).

        Mirrors job-owned fields (cadence, agent, model) onto the surface heartbeat
        cron job so the settings are functional, not just prompt-visible.
        """
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from cron.jobs import day_night_mode

            patch = {k: v for k, v in body.model_dump().items() if v is not None}
            mode_value = None
            for alias in ("heartbeat_report_mode", "report_mode", "notification_mode"):
                if alias in patch:
                    mode_value = patch.pop(alias)
                    break
            if mode_value is not None:
                patch["heartbeat_report_mode"] = _normalize_heartbeat_report_mode(mode_value)
            if "goal" in patch and not str(patch["goal"]).strip():
                raise HTTPException(status_code=400, detail="goal is required")
            if "cadence" in patch:
                cadence = str(patch["cadence"]).strip()
                if not cadence:
                    raise HTTPException(status_code=400, detail="cadence is required")
                try:
                    from cron.jobs import parse_schedule

                    parse_schedule(cadence)
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"invalid cadence: {exc}")
                patch["cadence"] = cadence
            # Validate time windows.
            for k in ("day_mode_start", "day_mode_end"):
                if k in patch and not _HHMM_RE.match(str(patch[k])):
                    raise HTTPException(status_code=400, detail=f"{k} must be HH:MM (00:00–23:59)")
            # Validate approval_rules shape: {always_ask:[...], never_ask:[...]}.
            if "approval_rules" in patch:
                ar = patch["approval_rules"]
                if not isinstance(ar, dict):
                    raise HTTPException(status_code=400, detail="approval_rules must be an object")
                for bucket in ("always_ask", "never_ask"):
                    if bucket in ar and not isinstance(ar[bucket], list):
                        raise HTTPException(
                            status_code=400, detail=f"approval_rules.{bucket} must be a list"
                        )
            # Only allowlisted keys survive (belt-and-suspenders over the typed body).
            patch = {k: v for k, v in patch.items() if k in _SURFACE_CONFIG_EDITABLE}

            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                # Shallow merge: preserves goal/cadence/experiment/cycles/playbook
                # and every other non-allowlisted key already in the config.
                cfg: Dict[str, Any] = surface_state.patch_config(conn, surface_key, patch)
            job_updates: Dict[str, Any] = {}
            if "model" in patch:
                job_updates["model"] = patch.get("model") or None
            if "agent" in patch:
                job_updates["agent"] = patch.get("agent") or None
            if "cadence" in patch:
                job_updates["schedule"] = patch["cadence"]
            if "heartbeat_report_mode" in patch:
                job = _surface_heartbeat_job(surface_key)
                metadata = job.get("metadata") if isinstance((job or {}).get("metadata"), dict) else {}
                job_updates["metadata"] = {
                    **metadata,
                    "heartbeat_report_mode": patch["heartbeat_report_mode"],
                }
            if job_updates:
                from cron.jobs import update_job

                job = _surface_heartbeat_job(surface_key)
                if job:
                    update_job(job["id"], job_updates)
            _fs_cache_invalidate("surfaces")  # reflect edited settings immediately
            return {"surface": surface_key, "config": cfg, "mode": day_night_mode(cfg)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PATCH /api/heartbeats/surfaces/%s/config failed", surface)
            raise HTTPException(status_code=500, detail=f"Update surface config failed: {exc}")


    def _read_surface_goals(surface_key: str) -> Dict[str, Any]:
        """Read + normalize a surface's goals (account DB). Tolerant: coerces legacy
        string goal entries into the rich {id,title,progress,order} shape."""
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            data: Dict[str, Any] = surface_state.get_goals(conn, surface_key)
        raw_goals = data.get("goals") if isinstance(data.get("goals"), list) else []
        goals: List[Dict[str, Any]] = []
        for i, g in enumerate(raw_goals):
            if isinstance(g, str):
                goals.append({"id": f"g{i}", "title": g, "progress": 0, "order": i})
            elif isinstance(g, dict) and g.get("title"):
                goals.append({
                    "id": str(g.get("id") or f"g{i}"),
                    "title": str(g["title"])[:200],
                    "progress": max(0, min(100, int(g.get("progress") or 0))),
                    "order": int(g.get("order") if g.get("order") is not None else i),
                })
        goals.sort(key=lambda x: x["order"])
        return {
            "bottleneck": str(data.get("bottleneck") or ""),
            "daily_focus": str(data.get("daily_focus") or ""),
            "daily_focus_set_at": data.get("daily_focus_set_at"),
            "goals": goals,
            "updated_at": data.get("updated_at"),
        }


    @router.get("/api/heartbeats/surfaces/{surface}/goals")
    def get_heartbeat_surface_goals(surface: str):
        """Return a surface's goals (north-star focus + bottleneck + rich goal list)."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            return {"surface": surface_key, **_read_surface_goals(surface_key)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/heartbeats/surfaces/%s/goals failed", surface)
            raise HTTPException(status_code=500, detail=f"Get goals failed: {exc}")


    @router.patch("/api/heartbeats/surfaces/{surface}/goals")
    def patch_heartbeat_surface_goals(surface: str, body: _HeartbeatGoalsPatchBody):
        """Replace goals[] / set bottleneck / set daily_focus. Validates title length,
        clamps progress 0-100, mints ids + order, stamps updated_at. Appends a history row."""
        try:
            surface_key = _validate_heartbeat_surface(surface)
            from datetime import datetime, timezone

            current = _read_surface_goals(surface_key)
            now_iso = datetime.now(timezone.utc).isoformat()
            if body.bottleneck is not None:
                current["bottleneck"] = body.bottleneck.strip()
            if body.daily_focus is not None:
                new_focus = body.daily_focus.strip()
                if new_focus != current.get("daily_focus"):
                    current["daily_focus_set_at"] = now_iso
                current["daily_focus"] = new_focus
            if body.goals is not None:
                cleaned: List[Dict[str, Any]] = []
                for i, g in enumerate(body.goals):
                    title = (g.title or "").strip()
                    if not title:
                        continue
                    if len(title) > 200:
                        raise HTTPException(status_code=400, detail="goal title max 200 chars")
                    cleaned.append({
                        "id": str(g.id or f"g{int(time.time())}_{secrets.token_hex(2)}"),
                        "title": title,
                        "progress": max(0, min(100, int(g.progress or 0))),
                        "order": int(g.order if g.order is not None else i),
                    })
                cleaned.sort(key=lambda x: x["order"])
                for i, g in enumerate(cleaned):
                    g["order"] = i
                current["goals"] = cleaned
            current["updated_at"] = now_iso

            from elevate_cli.data import connect
            from elevate_cli.data import surface_state

            with connect() as conn:
                # set_goals appends the history row itself (the old goals_history.jsonl).
                surface_state.set_goals(conn, surface_key, current)
            return {"surface": surface_key, **current}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PATCH /api/heartbeats/surfaces/%s/goals failed", surface)
            raise HTTPException(status_code=500, detail=f"Update goals failed: {exc}")



    @router.post("/api/heartbeats/automations/{job_id}/enabled")
    def set_heartbeat_automation_enabled(job_id: str, body: _HeartbeatAutomationEnabledBody):
        """Turn a single surface AUTOMATION on or off for the CURRENT account.

        Surface automations are the per-surface "kit" cron jobs that pair with each
        surface heartbeat (``origin.type == "surface-automation"``). They ship OFF
        (opt-in) and the realtor flips one here. This reuses the EXACT same cron
        enable/disable path as ``set_heartbeat_surface_enabled`` — ``resume_job``
        (recomputes a fresh ``next_run_at`` so it actually schedules) / ``pause_job``.

        Safety: refuses to toggle any job that is NOT a ``surface-automation`` job, so
        this endpoint can never be used to flip arbitrary cron jobs.
        """
        try:
            from cron.jobs import get_job, pause_job, resume_job

            want = bool(body.enabled)
            job_ref = (job_id or "").strip()
            if not job_ref:
                raise HTTPException(status_code=400, detail="job_id is required")

            # Look up by ID and verify it's a surface-automation job before touching it.
            job = get_job(job_ref)
            if not job:
                raise HTTPException(status_code=404, detail=f"No job '{job_ref}'")
            origin = job.get("origin") or {}
            if origin.get("type") != "surface-automation":
                raise HTTPException(
                    status_code=400,
                    detail="Job is not a surface automation",
                )

            # Flip via the canonical cron paths (resume recomputes next_run_at) — the
            # same path the surface-heartbeat toggle uses.
            if want:
                updated = resume_job(job["id"])
            else:
                updated = pause_job(job["id"], reason="surface automation disabled by realtor")
            if not updated:
                raise HTTPException(status_code=404, detail="Job not found")

            return {"id": job["id"], "enabled": bool(updated.get("enabled", want))}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/heartbeats/automations/%s/enabled failed", job_id)
            raise HTTPException(status_code=500, detail=f"Automation toggle failed: {exc}")




    return router
