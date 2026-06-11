"""Experiment-cycle management for surface heartbeats.

Elevate-native ``manageCycle`` / ``findCycleDefaults``
(``src/bus/experiment.ts``). A *cycle* is an agent-creatable, recurring
self-improvement experiment definition that lives as DATA in a surface's
stored config (``surface_state`` table, migration 0024 — formerly the
workspace ``config.json``) under a ``cycles[]`` array — replacing the single
hardcoded ``experiment`` block.

This module is ADDITIVE and TOLERANT:
  * Reads accept BOTH the new ``cycles[]`` array AND the legacy single
    ``experiment`` dict. A surface that only has the legacy block is migrated
    (in-memory on a plain ``list_cycles``; persisted on the first mutating
    ``manage_cycle``) into one synthesized cycle.
  * The legacy ``experiment`` key is NEVER deleted, so the running
    surface-heartbeats keep working unchanged.

A Cycle shape (Elevate flavor — carries ``every_n_runs`` + ``approval_required``
in addition to the Elevate fields)::

    {
      "name": str,
      "metric": str,
      "metric_type": "quantitative" | "qualitative",
      "surface": str,               # the experiment's TARGET surface (e.g. "playbook")
      "direction": "higher" | "lower",
      "window": str,
      "measurement": str,
      "every_n_runs": int,
      "loop_interval": str,         # e.g. "every 7 runs"
      "approval_required": bool,
      "enabled": bool,
      "created_by": str,
      "created_at": str,
    }

Tolerant reads; writes persist through the account database.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from elevate_time import now as _hermes_now
except Exception:  # pragma: no cover - elevate_time should always import
    from datetime import datetime as _dt

    def _hermes_now():  # type: ignore
        return _dt.utcnow()


_VALID_DIRECTIONS = {"higher", "lower"}
_VALID_METRIC_TYPES = {"quantitative", "qualitative"}
_DEFAULT_EVERY_N_RUNS = 7


def _now_iso() -> str:
    return _hermes_now().isoformat()


def _read_config(surface: str) -> Dict[str, Any]:
    """Tolerant read of a surface's stored config. Returns ``{}`` on any failure
    (the old tolerant ``config.json`` read contract)."""
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            return surface_state.get_config(conn, surface)
    except Exception:
        return {}


def _write_config(surface: str, config: Dict[str, Any]) -> None:
    """Persist a surface's config to the account database (replaces the old
    atomic ``config.json`` write)."""
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        surface_state.set_config(conn, surface, config)


def _migrate_legacy(config: Dict[str, Any], surface: str) -> List[Dict[str, Any]]:
    """Return the cycles list for ``config``.

    If ``config`` already has a non-empty ``cycles[]``, return it untouched.
    Otherwise, if it has a legacy ``experiment`` dict, synthesize ONE cycle
    from it. The legacy ``experiment`` key is NOT removed (tolerant).
    Returns ``[]`` when there is neither.
    """
    cycles = config.get("cycles")
    if isinstance(cycles, list) and cycles:
        return cycles

    exp = config.get("experiment")
    if not isinstance(exp, dict) or not exp:
        return []

    every_n = exp.get("every_n_runs", _DEFAULT_EVERY_N_RUNS)
    metric = exp.get("metric")
    synthesized = {
        "name": metric or f"{surface} self-improvement",
        "metric": metric,
        "metric_type": exp.get("metric_type", "qualitative"),
        "surface": "playbook",
        "direction": exp.get("direction", "higher"),
        "window": exp.get("window"),
        "measurement": exp.get("measurement"),
        "every_n_runs": every_n,
        "loop_interval": f"every {every_n} runs",
        "approval_required": bool(exp.get("approval_required", False)),
        "enabled": True,
        "created_by": "system",
        "created_at": _now_iso(),
    }
    return [synthesized]


def list_cycles(surface: str) -> List[Dict[str, Any]]:
    """Return the surface's cycles.

    Returns ``cycles[]`` if present and non-empty; otherwise the migrated
    single cycle synthesized from the legacy ``experiment`` block. Read-only —
    does NOT write the migration to disk (mutating ``manage_cycle`` persists it).
    """
    config = _read_config(surface)
    return _migrate_legacy(config, surface)


def manage_cycle(surface: str, action: str, **opts: Any) -> Dict[str, Any]:
    """Create / modify / remove / list a surface's experiment cycles.

    Returns ``{"ok": True, "cycles": [...]}`` on success, or
    ``{"ok": False, "error": "..."}`` on a validation/lookup failure.

    On any MUTATING action, the surface's legacy ``experiment`` block is first
    migrated into ``config.cycles[]`` (via ``_migrate_legacy``) so an existing
    single-experiment surface keeps its cycle, then the action is applied and
    the config is written atomically. The legacy ``experiment`` key is left in
    place for back-compat.
    """
    action = (action or "").strip().lower()
    if action not in {"create", "modify", "remove", "list"}:
        return {"ok": False, "error": f"Unknown cycle action: {action}"}

    config = _read_config(surface)
    # Seed cycles[] from the legacy block so a single-experiment surface keeps
    # its cycle once we start mutating.
    config["cycles"] = list(_migrate_legacy(config, surface))
    cycles: List[Dict[str, Any]] = config["cycles"]

    if action == "list":
        return {"ok": True, "cycles": cycles}

    if action == "create":
        name = opts.get("name")
        metric = opts.get("metric")
        if not name or not metric:
            return {"ok": False, "error": "Cycle create requires name and metric"}

        direction = opts.get("direction", "higher")
        if direction not in _VALID_DIRECTIONS:
            return {"ok": False, "error": "direction must be 'higher' or 'lower'"}

        metric_type = opts.get("metric_type", "qualitative")
        if metric_type not in _VALID_METRIC_TYPES:
            return {"ok": False, "error": "metric_type must be 'quantitative' or 'qualitative'"}

        if any((c.get("name") or "").strip().lower() == str(name).strip().lower() for c in cycles):
            return {"ok": False, "error": f"Cycle '{name}' already exists"}

        every_n = opts.get("every_n_runs", _DEFAULT_EVERY_N_RUNS)
        loop_interval = opts.get("loop_interval") or f"every {every_n} runs"
        cycle = {
            "name": name,
            "metric": metric,
            "metric_type": metric_type,
            "surface": opts.get("surface") or "playbook",
            "direction": direction,
            "window": opts.get("window"),
            "measurement": opts.get("measurement", ""),
            "every_n_runs": every_n,
            "loop_interval": loop_interval,
            "approval_required": bool(opts.get("approval_required", False)),
            "enabled": bool(opts.get("enabled", True)),
            "created_by": opts.get("created_by") or "agent",
            "created_at": _now_iso(),
        }
        cycles.append(cycle)
        _write_config(surface, config)
        return {"ok": True, "cycles": cycles}

    # modify / remove both need a name to locate the cycle (case-insensitive).
    name = opts.get("name")
    if not name:
        return {"ok": False, "error": f"Cycle {action} requires name"}
    target = str(name).strip().lower()
    idx = next(
        (i for i, c in enumerate(cycles) if (c.get("name") or "").strip().lower() == target),
        None,
    )
    if idx is None:
        return {"ok": False, "error": f"Cycle '{name}' not found"}

    if action == "remove":
        cycles.pop(idx)
        _write_config(surface, config)
        return {"ok": True, "cycles": cycles}

    # modify: validate then patch only supplied keys.
    if "direction" in opts and opts["direction"] not in _VALID_DIRECTIONS:
        return {"ok": False, "error": "direction must be 'higher' or 'lower'"}
    if "metric_type" in opts and opts["metric_type"] not in _VALID_METRIC_TYPES:
        return {"ok": False, "error": "metric_type must be 'quantitative' or 'qualitative'"}

    patchable = (
        "window", "loop_interval", "every_n_runs", "surface",
        "measurement", "metric_type", "direction", "enabled",
    )
    for key in patchable:
        if key in opts and opts[key] is not None:
            cycles[idx][key] = opts[key]
    _write_config(surface, config)
    return {"ok": True, "cycles": cycles}


def find_cycle_defaults(surface: str, metric: str) -> Optional[Dict[str, Any]]:
    """Match a cycle by ``metric`` and return its measurement method + framing so
    repeat experiments inherit it. Returns ``None`` when no cycle matches.
    """
    try:
        for cycle in list_cycles(surface):
            if cycle.get("metric") == metric:
                return {
                    "surface": cycle.get("surface"),
                    "direction": cycle.get("direction"),
                    "window": cycle.get("window"),
                    "measurement": cycle.get("measurement"),
                    "metric_type": cycle.get("metric_type"),
                    "every_n_runs": cycle.get("every_n_runs"),
                }
    except Exception:
        return None
    return None
