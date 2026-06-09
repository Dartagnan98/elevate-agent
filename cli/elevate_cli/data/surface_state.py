"""Read/write helpers for surface heartbeat STATE (migration 0024).

Surface state used to live as per-account JSON files under
``accounts/<key>/heartbeats/`` (``surfaces.json``, ``<surface>/config.json``,
``goals.json`` + ``goals_history.jsonl``, ``heartbeat.json``,
``experiments/active|history/*.json``). That made the dashboard cards a file
scan while tasks/approvals/deals/leads lived in the account database. This
module moves the STATE into the same database so the cards and the agent's
``agent_bus`` tool share one source of truth everywhere.

Markdown artifacts are NOT state and stay on disk: ``learnings.md``,
``history/*.md`` run transcripts, and playbooks are documents (git-committed
by the experiment loop).

Every function takes an open ``conn`` (``with connect() as conn:``), matching
the other table modules. JSON payloads are stored as TEXT; reads are tolerant
(corrupt/missing rows degrade to empty shapes, mirroring the old tolerant
file reads). TEXT/INTEGER columns keep the SQLite + Postgres paths identical.

One-shot import of the legacy files: ``_pg_surface_state_migrate.py``
(sentinel 9010), invoked from ``data.connection.connect()`` alongside the
kanban/outreach importers.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from elevate_cli.data._util import new_id, now_iso

EXPERIMENT_STATUSES = {"proposed", "running", "completed", "abandoned"}
# Statuses that count as "the active experiment" for a surface/cycle.
ACTIVE_EXPERIMENT_STATUSES = ("proposed", "running")

DEFAULT_GOALS: dict[str, Any] = {
    "bottleneck": "",
    "daily_focus": "",
    "daily_focus_set_at": None,
    "goals": [],
    "updated_at": None,
}


def _json_dict(value: Any) -> dict[str, Any]:
    """Tolerant JSON-dict read: TEXT column → dict, anything else → {}."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str)


# ─── registry (surfaces are creatable, not hardcoded) ──────────────────


def list_registry(conn: Any) -> dict[str, dict[str, Any]]:
    """Return {surface: spec} for every registered surface. The spec dict
    carries ``builtin``/``created_by`` merged in, matching the old
    surfaces.json shape."""
    rows = conn.execute(
        "SELECT surface, spec, builtin, created_by FROM surface_registry "
        "ORDER BY surface"
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        spec = _json_dict(row["spec"])
        spec["builtin"] = bool(row["builtin"])
        if row["created_by"] and not spec.get("created_by"):
            spec["created_by"] = row["created_by"]
        out[row["surface"]] = spec
    return out


def upsert_registry(
    conn: Any,
    surface: str,
    spec: dict[str, Any],
    *,
    builtin: Optional[bool] = None,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    """Add or replace a surface spec. ``builtin`` defaults to the spec's own
    flag (or the existing row's) so callers can pass the merged shape back."""
    surface = str(surface or "").strip()
    if not surface:
        raise ValueError("surface is required")
    spec = dict(spec or {})
    is_builtin = spec.pop("builtin", None) if builtin is None else builtin
    creator = created_by or spec.get("created_by")
    now = now_iso()
    existing = conn.execute(
        "SELECT builtin, created_at FROM surface_registry WHERE surface = ?",
        (surface,),
    ).fetchone()
    if is_builtin is None:
        is_builtin = bool(existing["builtin"]) if existing else False
    if existing:
        conn.execute(
            "UPDATE surface_registry SET spec=?, builtin=?, created_by=?, updated_at=? "
            "WHERE surface=?",
            (_dump(spec), 1 if is_builtin else 0, creator, now, surface),
        )
    else:
        conn.execute(
            "INSERT INTO surface_registry(surface, spec, builtin, created_by, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (surface, _dump(spec), 1 if is_builtin else 0, creator, now, now),
        )
    return {**spec, "builtin": bool(is_builtin)}


def remove_registry(conn: Any, surface: str) -> bool:
    cur = conn.execute(
        "DELETE FROM surface_registry WHERE surface = ?", (str(surface or "").strip(),)
    )
    return bool(getattr(cur, "rowcount", 0))


# ─── per-surface state row (config / goals / heartbeat) ────────────────


def _ensure_state_row(conn: Any, surface: str) -> None:
    conn.execute(
        "INSERT INTO surface_state(surface, config, goals, updated_at) "
        "VALUES(?,?,?,?) ON CONFLICT(surface) DO NOTHING",
        (surface, "{}", "{}", now_iso()),
    )


def list_state_surfaces(conn: Any) -> list[str]:
    """Every surface that has a state row OR a registry row (sorted)."""
    rows = conn.execute(
        "SELECT surface FROM surface_state UNION SELECT surface FROM surface_registry "
        "ORDER BY surface"
    ).fetchall()
    return [row["surface"] for row in rows]


def get_config(conn: Any, surface: str) -> dict[str, Any]:
    """Tolerant config read — {} when the surface has no row yet (the old
    ``_read_config`` file contract)."""
    row = conn.execute(
        "SELECT config FROM surface_state WHERE surface = ?", (str(surface or "").strip(),)
    ).fetchone()
    return _json_dict(row["config"]) if row else {}


def set_config(conn: Any, surface: str, config: dict[str, Any]) -> dict[str, Any]:
    """Replace a surface's config (the old atomic config.json write)."""
    surface = str(surface or "").strip()
    if not surface:
        raise ValueError("surface is required")
    _ensure_state_row(conn, surface)
    config = dict(config or {})
    conn.execute(
        "UPDATE surface_state SET config=?, updated_at=? WHERE surface=?",
        (_dump(config), now_iso(), surface),
    )
    return config


def patch_config(conn: Any, surface: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge ``patch`` into the surface config and persist."""
    config = get_config(conn, surface)
    config.update(patch or {})
    return set_config(conn, surface, config)


def get_goals(conn: Any, surface: str) -> dict[str, Any]:
    """Tolerant goals read with the dashboard's default shape filled in."""
    row = conn.execute(
        "SELECT goals FROM surface_state WHERE surface = ?", (str(surface or "").strip(),)
    ).fetchone()
    goals = _json_dict(row["goals"]) if row else {}
    out = dict(DEFAULT_GOALS)
    out.update({k: v for k, v in goals.items() if v is not None or k in goals})
    if not isinstance(out.get("goals"), list):
        out["goals"] = []
    return out


def set_goals(
    conn: Any, surface: str, goals: dict[str, Any], *, history: bool = True
) -> dict[str, Any]:
    """Replace a surface's goals; appends a history row (the old
    goals_history.jsonl append) unless ``history=False``."""
    surface = str(surface or "").strip()
    if not surface:
        raise ValueError("surface is required")
    _ensure_state_row(conn, surface)
    goals = dict(goals or {})
    now = now_iso()
    conn.execute(
        "UPDATE surface_state SET goals=?, updated_at=? WHERE surface=?",
        (_dump(goals), now, surface),
    )
    if history:
        conn.execute(
            "INSERT INTO surface_goals_history(id, surface, at, payload) VALUES(?,?,?,?)",
            (
                new_id(),
                surface,
                now,
                _dump(
                    {
                        "at": now,
                        "goals": goals.get("goals", []),
                        "bottleneck": goals.get("bottleneck", ""),
                        "daily_focus": goals.get("daily_focus", ""),
                    }
                ),
            ),
        )
    return goals


def list_goals_history(conn: Any, surface: str, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT at, payload FROM surface_goals_history WHERE surface = ? "
        "ORDER BY at DESC LIMIT ?",
        (str(surface or "").strip(), int(limit)),
    ).fetchall()
    out = []
    for row in rows:
        payload = _json_dict(row["payload"])
        payload.setdefault("at", row["at"])
        out.append(payload)
    return out


def get_heartbeat(conn: Any, surface: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT heartbeat FROM surface_state WHERE surface = ?",
        (str(surface or "").strip(),),
    ).fetchone()
    if not row or row["heartbeat"] is None:
        return None
    rec = _json_dict(row["heartbeat"])
    return rec or None


def set_heartbeat(conn: Any, surface: str, record: dict[str, Any]) -> dict[str, Any]:
    """Store the latest heartbeat record for a surface (the old
    heartbeat.json overwrite — last-write-wins, one record per surface)."""
    surface = str(surface or "").strip()
    if not surface:
        raise ValueError("surface is required")
    _ensure_state_row(conn, surface)
    record = dict(record or {})
    conn.execute(
        "UPDATE surface_state SET heartbeat=?, updated_at=? WHERE surface=?",
        (_dump(record), now_iso(), surface),
    )
    return record


def list_heartbeats(conn: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    """Latest heartbeat per surface, most recent first (old dir scan)."""
    rows = conn.execute(
        "SELECT surface, heartbeat FROM surface_state WHERE heartbeat IS NOT NULL"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        rec = _json_dict(row["heartbeat"])
        if not rec:
            continue
        rec.setdefault("agent", row["surface"])
        out.append(rec)
    out.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return out[: int(limit)]


# ─── activity feed ──────────────────────────────────────────────────────


def append_activity(
    conn: Any,
    agent: str,
    event: str,
    message: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    *,
    at: Optional[str] = None,
) -> dict[str, Any]:
    """Append one activity event (the old ``agent_activity.jsonl`` append)
    and return the stored row. ``at`` defaults to now; the legacy-file
    importer passes the original ``ts`` so ordering survives the import."""
    agent = str(agent or "").strip()
    if not agent:
        raise ValueError("agent is required")
    row = {
        "id": new_id(),
        "agent": agent,
        "event": str(event or "").strip() or "event",
        "message": str(message) if message is not None else None,
        "metadata": dict(metadata) if isinstance(metadata, dict) else {},
        "at": str(at or "").strip() or now_iso(),
    }
    conn.execute(
        "INSERT INTO surface_activity(id, agent, event, message, metadata, at) "
        "VALUES(?,?,?,?,?,?)",
        (
            row["id"],
            row["agent"],
            row["event"],
            row["message"],
            _dump(row["metadata"]) if row["metadata"] else None,
            row["at"],
        ),
    )
    return row


def list_activity(
    conn: Any, agent: Optional[str] = None, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Activity events, newest first. ``agent`` filters; ``metadata`` is a
    tolerant JSON read (NULL/corrupt rows degrade to {})."""
    where = ""
    params: list[Any] = []
    if agent:
        where = " WHERE agent = ?"
        params.append(str(agent).strip())
    rows = conn.execute(
        "SELECT id, agent, event, message, metadata, at FROM surface_activity"
        + where
        + " ORDER BY at DESC LIMIT ?",
        (*params, int(limit)),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "agent": row["agent"],
            "event": row["event"],
            "message": row["message"],
            "metadata": _json_dict(row["metadata"]),
            "at": row["at"],
        }
        for row in rows
    ]


# ─── experiments ────────────────────────────────────────────────────────


def upsert_experiment(conn: Any, surface: str, record: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace one experiment record owned by ``surface`` (the
    heartbeat surface — NOT the record's own ``surface`` field, which is the
    experiment's TARGET, e.g. "playbook"). The full record is the JSON payload
    (same shape the files held); ``id``/``cycle``/``status`` are mirrored into
    columns for querying."""
    record = dict(record or {})
    exp_id = str(record.get("id") or "").strip() or new_id()
    record["id"] = exp_id
    owner = str(surface or "").strip()
    if not owner:
        raise ValueError("experiment record needs an owning surface")
    status = str(record.get("status") or "proposed").strip().lower()
    if status not in EXPERIMENT_STATUSES:
        status = "proposed"
    cycle = str(record.get("cycle") or record.get("cycle_name") or "").strip() or None
    now = now_iso()
    completed_at = record.get("completed_at") if status in {"completed", "abandoned"} else None
    existing = conn.execute(
        "SELECT created_at FROM surface_experiments WHERE id = ?", (exp_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE surface_experiments SET surface=?, cycle=?, status=?, record=?, "
            "updated_at=?, completed_at=? WHERE id=?",
            (owner, cycle, status, _dump(record), now, completed_at, exp_id),
        )
    else:
        conn.execute(
            "INSERT INTO surface_experiments(id, surface, cycle, status, record, "
            "created_at, updated_at, completed_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                exp_id,
                owner,
                cycle,
                status,
                _dump(record),
                record.get("created_at") or now,
                now,
                completed_at,
            ),
        )
    return record


def get_experiment(
    conn: Any, surface: str, experiment_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Fetch one experiment. Without an id, returns the most recent ACTIVE
    (proposed/running) experiment for the surface — the old
    ``experiments/active/*.json`` lookup."""
    surface = str(surface or "").strip()
    wanted = str(experiment_id or "").strip()
    if wanted:
        row = conn.execute(
            "SELECT record FROM surface_experiments WHERE id = ? AND surface = ?",
            (wanted, surface),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT record FROM surface_experiments WHERE surface = ? "
            "AND status IN (?,?) ORDER BY updated_at DESC LIMIT 1",
            (surface, *ACTIVE_EXPERIMENT_STATUSES),
        ).fetchone()
    return _json_dict(row["record"]) if row else None


def get_active_experiment_for_cycle(
    conn: Any, surface: str, cycle: str
) -> Optional[dict[str, Any]]:
    """The active experiment for one cycle — the old per-cycle
    ``experiments/active/<cycle>.json`` file."""
    row = conn.execute(
        "SELECT record FROM surface_experiments WHERE surface = ? AND cycle = ? "
        "AND status IN (?,?) ORDER BY updated_at DESC LIMIT 1",
        (str(surface or "").strip(), str(cycle or "").strip(), *ACTIVE_EXPERIMENT_STATUSES),
    ).fetchone()
    return _json_dict(row["record"]) if row else None


def list_experiments(
    conn: Any,
    surface: Optional[str] = None,
    *,
    status: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Experiment records, newest first. ``status`` filters; ``status='active'``
    means proposed+running."""
    clauses: list[str] = []
    params: list[Any] = []
    if surface:
        clauses.append("surface = ?")
        params.append(str(surface).strip())
    if status == "active":
        clauses.append("status IN (?,?)")
        params.extend(ACTIVE_EXPERIMENT_STATUSES)
    elif status:
        clauses.append("status = ?")
        params.append(str(status).strip().lower())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        "SELECT record FROM surface_experiments" + where + " ORDER BY updated_at DESC LIMIT ?",
        (*params, int(limit)),
    ).fetchall()
    return [_json_dict(row["record"]) for row in rows]


# ─── runs (heartbeat run index — markdown transcripts stay on disk) ─────

RUN_KINDS = ("work", "experiment")


def append_run(
    conn: Any,
    surface: str,
    *,
    kind: str = "work",
    status: str = "ok",
    summary: Optional[str] = None,
    record: Optional[dict[str, Any]] = None,
    ran_at: Optional[str] = None,
) -> dict[str, Any]:
    """Index one heartbeat run (the old ``history/<iso>.json`` file write,
    migration 0027). ``record`` carries the full run-record JSON; ``ran_at``
    defaults to now — the legacy-file importer passes the original timestamp
    so ordering survives the import."""
    surface = str(surface or "").strip()
    if not surface:
        raise ValueError("surface is required")
    kind = str(kind or "work").strip().lower()
    if kind not in RUN_KINDS:
        kind = "work"
    row = {
        "id": new_id(),
        "surface": surface,
        "ran_at": str(ran_at or "").strip() or now_iso(),
        "kind": kind,
        "status": str(status or "ok").strip() or "ok",
        "summary": str(summary) if summary is not None else None,
        "record": dict(record) if isinstance(record, dict) else {},
    }
    conn.execute(
        "INSERT INTO surface_runs(id, surface, ran_at, kind, status, summary, record) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            row["id"],
            row["surface"],
            row["ran_at"],
            row["kind"],
            row["status"],
            row["summary"],
            _dump(row["record"]) if row["record"] else None,
        ),
    )
    return row


def list_runs(
    conn: Any, surface: Optional[str] = None, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Run records, newest first. ``surface`` filters; ``record`` is a
    tolerant JSON read (NULL/corrupt rows degrade to {})."""
    where = ""
    params: list[Any] = []
    if surface:
        where = " WHERE surface = ?"
        params.append(str(surface).strip())
    rows = conn.execute(
        "SELECT id, surface, ran_at, kind, status, summary, record FROM surface_runs"
        + where
        + " ORDER BY ran_at DESC LIMIT ?",
        (*params, int(limit)),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "surface": row["surface"],
            "ran_at": row["ran_at"],
            "kind": row["kind"],
            "status": row["status"],
            "summary": row["summary"],
            "record": _json_dict(row["record"]),
        }
        for row in rows
    ]


def count_runs(conn: Any, surface: str, *, kind: Optional[str] = None) -> int:
    """How many runs a surface has indexed (the old ``ls history | wc -l``
    cadence check). ``kind`` filters to 'work' or 'experiment'."""
    where = "surface = ?"
    params: list[Any] = [str(surface or "").strip()]
    if kind:
        where += " AND kind = ?"
        params.append(str(kind).strip().lower())
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM surface_runs WHERE " + where,
        tuple(params),
    ).fetchone()
    return int(row["n"]) if row else 0


# ─── hub agents (Agent Hub roster, migration 0026) ──────────────────────


def list_hub_agents(conn: Any, include_removed: bool = False) -> list[dict[str, Any]]:
    """Agent Hub rows in stable (creation, then id) order. ``config`` is a
    tolerant JSON-dict read; ``removed=1`` tombstone rows (parked defaults +
    the one-shot import marker) only appear with ``include_removed=True``."""
    rows = conn.execute(
        "SELECT agent_id, config, builtin, removed FROM hub_agents"
        + ("" if include_removed else " WHERE removed = 0")
        + " ORDER BY created_at, agent_id"
    ).fetchall()
    return [
        {
            "agent_id": row["agent_id"],
            "config": _json_dict(row["config"]),
            "builtin": bool(row["builtin"]),
            "removed": bool(row["removed"]),
        }
        for row in rows
    ]


def upsert_hub_agent(
    conn: Any,
    agent_id: str,
    config: dict[str, Any],
    *,
    builtin: Optional[bool] = None,
    removed: Optional[bool] = None,
) -> dict[str, Any]:
    """Insert or replace one Agent Hub agent config. ``builtin``/``removed``
    preserve the existing row's flags when None (same pattern as
    ``upsert_registry``); a fresh row defaults both to False."""
    agent_id = str(agent_id or "").strip()
    if not agent_id:
        raise ValueError("agent_id is required")
    config = dict(config or {})
    now = now_iso()
    existing = conn.execute(
        "SELECT builtin, removed FROM hub_agents WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if builtin is None:
        builtin = bool(existing["builtin"]) if existing else False
    if removed is None:
        removed = bool(existing["removed"]) if existing else False
    if existing:
        conn.execute(
            "UPDATE hub_agents SET config=?, builtin=?, removed=?, updated_at=? "
            "WHERE agent_id=?",
            (_dump(config), 1 if builtin else 0, 1 if removed else 0, now, agent_id),
        )
    else:
        conn.execute(
            "INSERT INTO hub_agents(agent_id, config, builtin, removed, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (agent_id, _dump(config), 1 if builtin else 0, 1 if removed else 0, now, now),
        )
    return {
        "agent_id": agent_id,
        "config": config,
        "builtin": bool(builtin),
        "removed": bool(removed),
    }


def remove_hub_agent(conn: Any, agent_id: str, *, tombstone: bool = False) -> bool:
    """Remove one Agent Hub agent. ``tombstone=True`` keeps (or creates) the
    row with ``removed=1`` — a parked default that reconcile must not re-seed.
    ``tombstone=False`` deletes the row outright (custom agents); returns
    whether a row existed."""
    agent_id = str(agent_id or "").strip()
    if not agent_id:
        raise ValueError("agent_id is required")
    if tombstone:
        existing = conn.execute(
            "SELECT 1 FROM hub_agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        now = now_iso()
        if existing:
            conn.execute(
                "UPDATE hub_agents SET removed=1, updated_at=? WHERE agent_id=?",
                (now, agent_id),
            )
        else:
            # Parking an absent default is an idempotent no-op that still
            # records the tombstone (mirrors the old removed-ids list).
            conn.execute(
                "INSERT INTO hub_agents(agent_id, config, builtin, removed, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (agent_id, "{}", 0, 1, now, now),
            )
        return True
    cur = conn.execute("DELETE FROM hub_agents WHERE agent_id = ?", (agent_id,))
    return bool(getattr(cur, "rowcount", 0))
