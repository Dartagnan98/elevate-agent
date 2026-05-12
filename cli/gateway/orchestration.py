"""Durable local orchestration registry for Elevate gateway agents.

This module is intentionally small and local-first. It gives the gateway and
dashboards one shared source of truth for the visible agent team, delegated
runs, and lifecycle events without starting hidden worker processes by itself.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from elevate_constants import get_elevate_home


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted", "timeout"}
_ACTIVE_RUN_STATUSES = {"queued", "running", "blocked", "waiting_for_approval"}
_RUN_STATUSES = {*_ACTIVE_RUN_STATUSES, *_TERMINAL_STATUSES}
_AGENT_STATUSES = {"ready", "online", "offline", "disabled", "running", "error"}
_RUN_METADATA_FIELDS = {"blocked_by", "depends_on", "assigned_to", "file_scope", "priority", "subsystem", "handoff"}
_UNSET = object()


DEFAULT_ORCHESTRATION_AGENTS: tuple[dict[str, Any], ...] = (
    {
        "agent_id": "executive-assistant",
        "display_name": "Executive Assistant",
        "role": "Primary operator and orchestration agent for the Elevate team.",
        "tier": "primary",
        "reports_to": None,
        "lane": "Executive Assistant",
        "org": "standalone",
        "enabled": True,
        "status": "ready",
        "metadata": {
            "job_profile": {
                "job": "Main talking agent, daily-update owner, supervisor, router, and final-response owner for cross-domain work.",
                "owns": ["main chat", "daily updates", "request triage", "task decomposition", "agent routing", "final synthesis", "user-facing decisions"],
                "not_for": ["deep specialist production when a narrower agent owns the work"],
                "default_expected_return": "Return a concise update, routed plan, decision, or synthesized final answer.",
            }
        },
    },
    {
        "agent_id": "admin",
        "display_name": "Admin",
        "role": "Operations, scheduling, paperwork, and transaction support agent.",
        "tier": "specialist",
        "reports_to": "executive-assistant",
        "lane": "Admin",
        "org": "standalone",
        "enabled": True,
        "status": "ready",
        "metadata": {
            "job_profile": {
                "job": "Operations support for paperwork, scheduling, checklists, listing status, transaction steps, and follow-through.",
                "owns": ["calendar/admin ops", "paperwork/checklists", "listing status tracking", "transaction coordination", "CRM hygiene", "ops follow-through"],
                "not_for": ["sales copy", "brand strategy", "social captions unless asked for ops support"],
                "default_expected_return": "Return current status, checklist items, blockers, next steps, and any required owner/date.",
            }
        },
    },
    {
        "agent_id": "outreach",
        "display_name": "Outreach",
        "role": "Lead follow-up, relationship management, and client touchpoint agent.",
        "tier": "specialist",
        "reports_to": "executive-assistant",
        "lane": "Outreach",
        "org": "standalone",
        "enabled": True,
        "status": "ready",
        "metadata": {
            "job_profile": {
                "job": "Dedicated outreach lane for lead follow-up, client communication, relationship touchpoints, and nurture sequencing.",
                "owns": ["lead follow-up", "client follow-ups", "client touchpoints", "relationship notes", "nurture messaging", "conversation strategy"],
                "not_for": ["transaction paperwork", "long-form campaign strategy", "platform-specific social formatting"],
                "default_expected_return": "Return the recommended outreach message, timing, and next follow-up action.",
            }
        },
    },
    {
        "agent_id": "marketing",
        "display_name": "Marketing",
        "role": "Listing marketing, seller updates, email campaigns, and creative direction agent.",
        "tier": "specialist",
        "reports_to": "executive-assistant",
        "lane": "Marketing",
        "org": "standalone",
        "enabled": True,
        "status": "ready",
        "metadata": {
            "job_profile": {
                "job": "Listing marketing lane for seller updates, marketing emails, graphics/creative direction, listing launch packages, and campaign handoffs.",
                "owns": ["seller updates", "marketing emails", "listing launch copy", "graphics/creative direction", "campaign handoff briefs", "market update framing"],
                "not_for": ["routine scheduling", "CRM cleanup", "transaction checklist ownership", "paid media optimization unless paired with Ads"],
                "default_expected_return": "Return the marketing asset plan, draft copy, approval needs, and next production step.",
            }
        },
    },
    {
        "agent_id": "ads",
        "display_name": "Ads",
        "role": "Paid ads, listing campaigns, email campaign, and offer positioning agent.",
        "tier": "specialist",
        "reports_to": "executive-assistant",
        "lane": "Ads",
        "org": "standalone",
        "enabled": True,
        "status": "ready",
        "metadata": {
            "job_profile": {
                "job": "Paid acquisition and campaign lane for listing ads, paid social/search strategy, email campaigns, offer framing, and creative briefs.",
                "owns": ["paid ads", "listing ad strategy", "campaign planning", "email campaign strategy", "ad copy", "ad creative direction", "offer/message strategy", "market update framing"],
                "not_for": ["routine scheduling", "CRM cleanup", "transaction checklist ownership", "organic social captions unless paired with Social Media"],
                "default_expected_return": "Return the ad/campaign angle, audience, offer, channel plan, draft copy, and next production step.",
            }
        },
    },
    {
        "agent_id": "social-media",
        "display_name": "Social Media",
        "role": "Short-form content, caption, hook, posting plan, and platform adaptation agent.",
        "tier": "specialist",
        "reports_to": "marketing",
        "lane": "Social Media",
        "org": "standalone",
        "enabled": True,
        "status": "ready",
        "metadata": {
            "job_profile": {
                "job": "Organic social production lane for short-form content, hooks, captions, posting plans, and platform-specific adaptation.",
                "owns": ["short-form posts", "caption variants", "hooks", "platform adaptation", "posting schedule ideas", "content repurposing", "organic social calendar"],
                "not_for": ["paperwork", "transaction operations", "paid ad strategy unless Ads asks"],
                "default_expected_return": "Return platform-ready captions/hooks, format notes, and posting recommendation.",
            }
        },
    },
)


class OrchestrationValidationError(ValueError):
    """Raised when a caller supplies invalid orchestration data."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_db_path() -> Path:
    return get_elevate_home() / "orchestration.db"


def _json_dumps(value: Any) -> str:
    if value is None:
        value = {}
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except TypeError as exc:
        raise OrchestrationValidationError(f"metadata must be JSON serializable: {exc}") from exc


def _json_loads(value: Any) -> Any:
    if not value:
        return {}
    try:
        return json.loads(str(value))
    except Exception:
        return {}


def _clean_id(value: Any, *, field: str = "agent_id") -> str:
    text = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(text):
        raise OrchestrationValidationError(f"{field} must match {_ID_RE.pattern}")
    return text


def _slug_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug or "agent"


def _clean_run_id(value: Any) -> str:
    text = str(value or "").strip()
    if not _RUN_ID_RE.fullmatch(text):
        raise OrchestrationValidationError("run_id contains unsupported characters")
    return text


def _clean_string(value: Any, *, field: str, max_length: int, required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise OrchestrationValidationError(f"{field} is required")
        return None
    text = str(value).strip()
    if required and not text:
        raise OrchestrationValidationError(f"{field} is required")
    if len(text) > max_length:
        raise OrchestrationValidationError(f"{field} must be <= {max_length} characters")
    return text or None


def _clean_status(value: Any, allowed: set[str], *, default: str, field: str) -> str:
    text = str(value or default).strip().lower()
    if text not in allowed:
        raise OrchestrationValidationError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return text


def _clean_string_list(value: Any, *, field: str, max_items: int = 50, max_length: int = 500) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, dict):
        raise OrchestrationValidationError(f"{field} must be a string or list")
    elif isinstance(value, Iterable):
        raw_items = list(value)
    else:
        raise OrchestrationValidationError(f"{field} must be a string or list")
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_items[:max_items]:
        text = str(raw or "").strip()
        if not text:
            continue
        if len(text) > max_length:
            raise OrchestrationValidationError(f"{field} entries must be <= {max_length} characters")
        if text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned


def normalize_run_metadata(metadata: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize visible run planning metadata.

    API callers may send dependency/owner fields either inside ``metadata`` or
    as top-level request fields. The store persists them in metadata so older
    DB schemas remain compatible.
    """

    merged: Dict[str, Any] = {}
    if isinstance(metadata, dict):
        merged.update(metadata)
    if isinstance(payload, dict):
        for field in _RUN_METADATA_FIELDS:
            if field in payload:
                merged[field] = payload[field]

    for dep_field in ("blocked_by", "depends_on"):
        if dep_field in merged:
            cleaned = []
            for value in _clean_string_list(merged.get(dep_field), field=dep_field, max_length=128):
                try:
                    cleaned.append(_clean_run_id(value))
                except OrchestrationValidationError:
                    raise OrchestrationValidationError(f"{dep_field} contains an invalid run id: {value}") from None
            merged[dep_field] = cleaned

    if "file_scope" in merged:
        merged["file_scope"] = _clean_string_list(merged.get("file_scope"), field="file_scope", max_length=1000)
    if "assigned_to" in merged and merged.get("assigned_to") not in (None, ""):
        merged["assigned_to"] = _clean_id(merged.get("assigned_to"), field="assigned_to")
    if "priority" in merged and merged.get("priority") not in (None, ""):
        merged["priority"] = _clean_string(merged.get("priority"), field="priority", max_length=40) or "normal"
    if "subsystem" in merged and merged.get("subsystem") not in (None, ""):
        merged["subsystem"] = _clean_string(merged.get("subsystem"), field="subsystem", max_length=120)
    if "handoff" in merged and merged.get("handoff") is not None and not isinstance(merged.get("handoff"), dict):
        raise OrchestrationValidationError("handoff must be an object")
    return merged


def _row_to_agent(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "agent_id": row["agent_id"],
        "id": row["agent_id"],
        "display_name": row["display_name"],
        "name": row["display_name"],
        "role": row["role"],
        "tier": row["tier"],
        "reports_to": row["reports_to"],
        "lane": row["lane"],
        "org": row["org"],
        "enabled": bool(row["enabled"]),
        "status": row["status"],
        "current_task": row["current_task"],
        "last_seen_at": row["last_seen_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": _json_loads(row["metadata_json"]),
    }


def _run_route_label(metadata: Dict[str, Any]) -> Optional[str]:
    handoff = metadata.get("handoff") if isinstance(metadata, dict) else None
    if not isinstance(handoff, dict):
        return None
    if handoff.get("visible_handoff") is False:
        return None
    raw_label = handoff.get("routing_label") or handoff.get("route_label")
    if isinstance(raw_label, str) and raw_label.strip():
        return raw_label.strip()[:160]
    to_agent = handoff.get("to_agent")
    if isinstance(to_agent, str) and to_agent.strip():
        label = to_agent.strip().replace("_", "-").replace("-", " ").title()
        return f"Agent Routing ({label})"
    return None


def _row_to_run(row: sqlite3.Row) -> Dict[str, Any]:
    metadata = _json_loads(row["metadata_json"])
    route_label = _run_route_label(metadata)
    return {
        "run_id": row["run_id"],
        "id": row["run_id"],
        "agent_id": row["agent_id"],
        "route_label": route_label,
        "routing_label": route_label,
        "parent_run_id": row["parent_run_id"],
        "parent_session_key": row["parent_session_key"],
        "session_key": row["session_key"],
        "task": row["task"],
        "status": row["status"],
        "mode": row["mode"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "summary": row["summary"],
        "error": row["error"],
        "metadata": metadata,
        "blocked_by": _run_blockers({"metadata": metadata}),
        "depends_on": _run_blockers({"metadata": metadata}),
        "assigned_to": metadata.get("assigned_to"),
        "file_scope": metadata.get("file_scope") if isinstance(metadata.get("file_scope"), list) else [],
        "priority": metadata.get("priority") or "normal",
        "subsystem": metadata.get("subsystem"),
    }


def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "id": row["event_id"],
        "run_id": row["run_id"],
        "timestamp": row["ts"],
        "type": row["type"],
        "message": row["message"],
        "data": _json_loads(row["data_json"]),
    }


def _run_blockers(run: Dict[str, Any]) -> list[str]:
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    values = metadata.get("blocked_by") or metadata.get("depends_on") or []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    blockers = []
    for value in values:
        try:
            blockers.append(_clean_run_id(value))
        except OrchestrationValidationError:
            continue
    return blockers


def _priority_rank(run: Dict[str, Any]) -> int:
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    priority = str(metadata.get("priority") or "normal").strip().lower()
    return {
        "urgent": 0,
        "p0": 0,
        "high": 1,
        "p1": 1,
        "normal": 2,
        "medium": 2,
        "p2": 2,
        "low": 3,
        "p3": 3,
    }.get(priority, 2)


def _cycle_run_ids(items: list[dict[str, Any]]) -> list[str]:
    run_ids = {item["run_id"] for item in items}
    indegree = {run_id: 0 for run_id in run_ids}
    dependents: dict[str, list[str]] = {}
    for item in items:
        run_id = item["run_id"]
        for dependency in item["blocked_by"]:
            if dependency not in run_ids:
                continue
            indegree[run_id] += 1
            dependents.setdefault(dependency, []).append(run_id)

    queue = [run_id for run_id, degree in indegree.items() if degree == 0]
    visited: set[str] = set()
    while queue:
        run_id = queue.pop()
        if run_id in visited:
            continue
        visited.add(run_id)
        for child in dependents.get(run_id, []):
            indegree[child] = max(0, indegree[child] - 1)
            if indegree[child] == 0:
                queue.append(child)

    return sorted(run_id for run_id, degree in indegree.items() if degree > 0 and run_id not in visited)


def summarize_run_plan_graph(runs: list[Dict[str, Any]], *, next_limit: int = 8) -> Dict[str, Any]:
    """Return a dependency summary for visible orchestration runs.

    Summarizes the local run registry without requiring an external planner.
    Dependencies live in run metadata as
    ``blocked_by``/``depends_on`` run-id arrays.
    """
    items = [
        {
            "run_id": run["run_id"],
            "agent_id": run.get("agent_id"),
            "status": str(run.get("status") or "queued").lower(),
            "blocked_by": _run_blockers(run),
            "priority_rank": _priority_rank(run),
            "priority": (run.get("metadata") or {}).get("priority", "normal") if isinstance(run.get("metadata"), dict) else "normal",
            "assigned_to": (run.get("metadata") or {}).get("assigned_to") if isinstance(run.get("metadata"), dict) else None,
            "file_scope": (run.get("metadata") or {}).get("file_scope", []) if isinstance(run.get("metadata"), dict) else [],
            "subsystem": (run.get("metadata") or {}).get("subsystem") if isinstance(run.get("metadata"), dict) else None,
        }
        for run in runs
        if run.get("run_id")
    ]
    known_ids = {item["run_id"] for item in items}
    completed_ids = {
        item["run_id"]
        for item in items
        if item["status"] == "completed"
    }
    cycle_ids = _cycle_run_ids(items)
    cycle_set = set(cycle_ids)

    ready_ids: list[str] = []
    blocked_ids: list[str] = []
    active_ids: list[str] = []
    terminal_ids: list[str] = []
    unresolved_dependency_ids: set[str] = set()
    dependency_blocked_ids: set[str] = set()

    for item in items:
        run_id = item["run_id"]
        status = item["status"]
        missing = [dependency for dependency in item["blocked_by"] if dependency not in known_ids]
        incomplete = [
            dependency
            for dependency in item["blocked_by"]
            if dependency in known_ids and dependency not in completed_ids
        ]
        unresolved_dependency_ids.update(missing)
        dependency_blocked_ids.update(incomplete)

        if status == "running":
            active_ids.append(run_id)
        if status in _TERMINAL_STATUSES:
            terminal_ids.append(run_id)

        has_blocker = bool(missing or incomplete or run_id in cycle_set)
        if status == "queued" and not has_blocker:
            ready_ids.append(run_id)
        elif status == "blocked" or (
            status not in _TERMINAL_STATUSES
            and status != "running"
            and has_blocker
        ):
            blocked_ids.append(run_id)

    ready_ids.sort()
    blocked_ids.sort()
    active_ids.sort()
    completed = sorted(completed_ids)
    terminal_ids.sort()
    unresolved = sorted(unresolved_dependency_ids)
    dependency_blocked = sorted(dependency_blocked_ids)
    next_ready_ids = [
        item["run_id"]
        for item in sorted(
            (item for item in items if item["run_id"] in ready_ids),
            key=lambda item: (item["priority_rank"], item["run_id"]),
        )[: max(1, int(next_limit or 8))]
    ]

    return {
        "item_count": len(items),
        "items": [
            {
                "run_id": item["run_id"],
                "agent_id": item.get("agent_id"),
                "status": item["status"],
                "blocked_by": item["blocked_by"],
                "assigned_to": item.get("assigned_to"),
                "file_scope": item.get("file_scope") if isinstance(item.get("file_scope"), list) else [],
                "subsystem": item.get("subsystem"),
                "priority": item.get("priority") or "normal",
            }
            for item in items
        ],
        "ready_run_ids": ready_ids,
        "blocked_run_ids": blocked_ids,
        "active_run_ids": active_ids,
        "completed_run_ids": completed,
        "terminal_run_ids": terminal_ids,
        "cycle_run_ids": cycle_ids,
        "unresolved_dependency_ids": unresolved,
        "dependency_blocked_run_ids": dependency_blocked,
        "next_ready_run_ids": next_ready_ids,
    }


class OrchestrationStore:
    """SQLite-backed registry for visible Elevate agent orchestration."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self._lock = threading.RLock()
        self._init_schema()
        self.ensure_default_agents()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orchestration_agents (
                    agent_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    tier TEXT NOT NULL DEFAULT 'specialist',
                    reports_to TEXT,
                    lane TEXT NOT NULL DEFAULT '',
                    org TEXT NOT NULL DEFAULT 'standalone',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'ready',
                    current_task TEXT,
                    last_seen_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_orchestration_agents_org
                    ON orchestration_agents(org);

                CREATE TABLE IF NOT EXISTS orchestration_runs (
                    run_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    parent_session_key TEXT,
                    session_key TEXT,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    summary TEXT,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_orchestration_runs_agent
                    ON orchestration_runs(agent_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_orchestration_runs_status
                    ON orchestration_runs(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS orchestration_events (
                    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT,
                    data_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_orchestration_events_run
                    ON orchestration_events(run_id, event_seq ASC);
                """
            )
            conn.commit()

    def ensure_default_agents(self) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            for item in DEFAULT_ORCHESTRATION_AGENTS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO orchestration_agents (
                        agent_id, display_name, role, tier, reports_to, lane,
                        org, enabled, status, created_at, updated_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["agent_id"],
                        item["display_name"],
                        item["role"],
                        item["tier"],
                        item["reports_to"],
                        item["lane"],
                        item["org"],
                        1 if item.get("enabled", True) else 0,
                        item.get("status", "ready"),
                        now,
                        now,
                        _json_dumps(item.get("metadata") or {}),
                    ),
                )
            conn.commit()

    def list_agents(self, *, org: Optional[str] = None, include_disabled: bool = True) -> List[Dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if org:
            clauses.append("org = ?")
            params.append(str(org))
        if not include_disabled:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM orchestration_agents
                {where}
                ORDER BY
                  CASE tier WHEN 'primary' THEN 0 ELSE 1 END,
                  display_name COLLATE NOCASE
                """,
                params,
            ).fetchall()
        return [_row_to_agent(row) for row in rows]

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agent_id = _clean_id(agent_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return _row_to_agent(row) if row else None

    def upsert_agent(self, data: Dict[str, Any]) -> Dict[str, Any]:
        raw_agent_id = data.get("agent_id") or data.get("id")
        agent_id = _clean_id(raw_agent_id or _slug_id(data.get("name") or data.get("display_name")))
        display_name = _clean_string(
            data.get("display_name") or data.get("name") or agent_id.replace("-", " ").title(),
            field="display_name",
            max_length=160,
            required=True,
        )
        role = _clean_string(data.get("role") or "", field="role", max_length=600) or ""
        tier = _clean_string(data.get("tier") or "specialist", field="tier", max_length=40) or "specialist"
        reports_to_raw = data.get("reports_to")
        reports_to = _clean_id(reports_to_raw, field="reports_to") if reports_to_raw else None
        lane = _clean_string(data.get("lane") or display_name, field="lane", max_length=120) or display_name
        org = _clean_string(data.get("org") or "standalone", field="org", max_length=120) or "standalone"
        enabled = bool(data.get("enabled", True))
        status = _clean_status(data.get("status"), _AGENT_STATUSES, default="ready", field="status")
        current_task = _clean_string(data.get("current_task"), field="current_task", max_length=1000)
        metadata_json = _json_dumps(data.get("metadata") if isinstance(data.get("metadata"), dict) else {})
        now = _utc_now()

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_agents (
                    agent_id, display_name, role, tier, reports_to, lane, org,
                    enabled, status, current_task, last_seen_at, created_at,
                    updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    role=excluded.role,
                    tier=excluded.tier,
                    reports_to=excluded.reports_to,
                    lane=excluded.lane,
                    org=excluded.org,
                    enabled=excluded.enabled,
                    status=excluded.status,
                    current_task=excluded.current_task,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    agent_id,
                    display_name,
                    role,
                    tier,
                    reports_to,
                    lane,
                    org,
                    1 if enabled else 0,
                    status,
                    current_task,
                    now,
                    now,
                    now,
                    metadata_json,
                ),
            )
            conn.commit()
        return self.get_agent(agent_id) or {}

    def update_agent(self, agent_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = self.get_agent(agent_id)
        if not current:
            return None
        metadata_update = updates.get("metadata", _UNSET)
        current_metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        if metadata_update is _UNSET:
            metadata = current_metadata
        elif isinstance(metadata_update, dict):
            metadata = {**current_metadata, **metadata_update}
        else:
            metadata = {}
        merged = {
            **current,
            **updates,
            "agent_id": current["agent_id"],
            "metadata": metadata,
        }
        return self.upsert_agent(merged)

    def touch_agent(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        current_task: Any = _UNSET,
    ) -> None:
        agent_id = _clean_id(agent_id)
        if self.get_agent(agent_id) is None:
            self.upsert_agent({"agent_id": agent_id, "display_name": agent_id.replace("-", " ").title()})
        values: list[Any] = []
        sets = ["last_seen_at = ?", "updated_at = ?"]
        now = _utc_now()
        values.extend([now, now])
        if status is not None:
            sets.append("status = ?")
            values.append(_clean_status(status, _AGENT_STATUSES, default="ready", field="status"))
        if current_task is not _UNSET:
            sets.append("current_task = ?")
            values.append(_clean_string(current_task, field="current_task", max_length=1000))
        values.append(agent_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE orchestration_agents SET {', '.join(sets)} WHERE agent_id = ?",
                values,
            )
            conn.commit()

    def create_run(
        self,
        *,
        agent_id: str,
        task: str,
        run_id: Optional[str] = None,
        status: str = "queued",
        mode: str = "manual",
        parent_run_id: Optional[str] = None,
        parent_session_key: Optional[str] = None,
        session_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        agent_id = _clean_id(agent_id)
        if self.get_agent(agent_id) is None:
            self.upsert_agent({"agent_id": agent_id, "display_name": agent_id.replace("-", " ").title()})
        run_id = _clean_run_id(run_id or f"run_{uuid.uuid4().hex}")
        task = _clean_string(task, field="task", max_length=8000, required=True) or ""
        status = _clean_status(status, _RUN_STATUSES, default="queued", field="status")
        mode = _clean_string(mode or "manual", field="mode", max_length=80) or "manual"
        parent_run_id = _clean_string(parent_run_id, field="parent_run_id", max_length=128)
        parent_session_key = _clean_string(parent_session_key, field="parent_session_key", max_length=256)
        session_key = _clean_string(session_key, field="session_key", max_length=256)
        normalized_metadata = normalize_run_metadata(metadata or {})
        metadata_json = _json_dumps(normalized_metadata)
        now = _utc_now()
        started_at = now if status == "running" else None
        completed_at = now if status in _TERMINAL_STATUSES else None

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_runs (
                    run_id, agent_id, parent_run_id, parent_session_key,
                    session_key, task, status, mode, created_at, updated_at,
                    started_at, completed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    agent_id,
                    parent_run_id,
                    parent_session_key,
                    session_key,
                    task,
                    status,
                    mode,
                    now,
                    now,
                    started_at,
                    completed_at,
                    metadata_json,
                ),
            )
            conn.commit()
        self.touch_agent(
            agent_id,
            status="running" if status == "running" else "ready",
            current_task=task if status in {"queued", "running"} else None,
        )
        self.append_event(run_id, f"run.{status}", f"{status}: {task[:160]}", {"agent_id": agent_id})
        return self.get_run(run_id) or {}

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        run_id = _clean_run_id(run_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(
        self,
        *,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(_clean_id(agent_id))
        if status:
            clauses.append("status = ?")
            params.append(_clean_status(status, _RUN_STATUSES, default="queued", field="status"))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit or 50), 200))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM orchestration_runs
                {where}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def update_run(self, run_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = self.get_run(run_id)
        if not current:
            return None

        allowed = {"status", "summary", "error", "session_key", "metadata", *_RUN_METADATA_FIELDS}
        cleaned: dict[str, Any] = {}
        current_metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        metadata_patch: dict[str, Any] = {}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "status":
                cleaned[key] = _clean_status(value, _RUN_STATUSES, default=current["status"], field="status")
            elif key == "summary":
                cleaned[key] = _clean_string(value, field="summary", max_length=20000)
            elif key == "error":
                cleaned[key] = _clean_string(value, field="error", max_length=4000)
            elif key == "session_key":
                cleaned[key] = _clean_string(value, field="session_key", max_length=256)
            elif key == "metadata":
                if not isinstance(value, dict):
                    raise OrchestrationValidationError("metadata must be an object")
                metadata_patch.update(value)
            elif key in _RUN_METADATA_FIELDS:
                metadata_patch[key] = value

        if metadata_patch:
            cleaned["metadata"] = _json_dumps(
                normalize_run_metadata({**current_metadata, **metadata_patch})
            )

        if not cleaned:
            return current

        now = _utc_now()
        set_parts = ["updated_at = ?"]
        params: list[Any] = [now]
        new_status = cleaned.get("status")
        if new_status == "running" and not current.get("started_at"):
            set_parts.append("started_at = ?")
            params.append(now)
        if new_status in _TERMINAL_STATUSES and not current.get("completed_at"):
            set_parts.append("completed_at = ?")
            params.append(now)
        for key, value in cleaned.items():
            column = "metadata_json" if key == "metadata" else key
            set_parts.append(f"{column} = ?")
            params.append(value)
        params.append(run_id)

        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE orchestration_runs SET {', '.join(set_parts)} WHERE run_id = ?",
                params,
            )
            conn.commit()

        status_for_event = new_status or current["status"]
        self.append_event(run_id, f"run.{status_for_event}", updates.get("summary") or updates.get("error") or status_for_event)
        updated = self.get_run(run_id)
        if updated:
            agent_status = "ready" if updated["status"] in _TERMINAL_STATUSES else "running"
            self.touch_agent(updated["agent_id"], status=agent_status, current_task=None if agent_status == "ready" else updated["task"])
        return updated

    def append_event(
        self,
        run_id: str,
        event_type: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        run_id = _clean_run_id(run_id)
        if self.get_run(run_id) is None:
            raise OrchestrationValidationError("Run not found")
        event_type = _clean_string(event_type, field="type", max_length=120, required=True) or "event"
        message = _clean_string(message, field="message", max_length=4000)
        data_json = _json_dumps(data or {})
        event_id = f"evt_{uuid.uuid4().hex}"
        ts = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_events (event_id, run_id, ts, type, message, data_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, run_id, ts, event_type, message, data_json),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM orchestration_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _row_to_event(row)

    def list_events(self, run_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        run_id = _clean_run_id(run_id)
        limit = max(1, min(int(limit or 100), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM orchestration_events
                WHERE run_id = ?
                ORDER BY event_seq ASC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_recent_events(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM orchestration_events
                ORDER BY event_seq DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def snapshot(self, *, org: Optional[str] = None, run_limit: int = 50) -> Dict[str, Any]:
        agents = self.list_agents(org=org)
        runs = self.list_runs(limit=run_limit)
        active = [run for run in runs if run["status"] in _ACTIVE_RUN_STATUSES]
        by_agent = {agent["agent_id"]: {"active_runs": 0, "recent_runs": 0} for agent in agents}
        for run in runs:
            entry = by_agent.setdefault(run["agent_id"], {"active_runs": 0, "recent_runs": 0})
            entry["recent_runs"] += 1
            if run["status"] in _ACTIVE_RUN_STATUSES:
                entry["active_runs"] += 1
        for agent in agents:
            agent["run_counts"] = by_agent.get(agent["agent_id"], {"active_runs": 0, "recent_runs": 0})
        return {
            "generated_at": _utc_now(),
            "db_path": str(self.db_path),
            "agents": agents,
            "runs": runs,
            "active_runs": len(active),
            "run_counts": by_agent,
            "plan_graph": summarize_run_plan_graph(runs),
            "recent_events": self.list_recent_events(limit=25),
        }

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            agent_count = int(conn.execute("SELECT COUNT(*) FROM orchestration_agents").fetchone()[0])
            active_runs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM orchestration_runs WHERE status IN ('queued', 'running')"
                ).fetchone()[0]
            )
            total_runs = int(conn.execute("SELECT COUNT(*) FROM orchestration_runs").fetchone()[0])
        return {
            "db_path": str(self.db_path),
            "agents": agent_count,
            "active_runs": active_runs,
            "total_runs": total_runs,
        }


_store_cache: dict[str, OrchestrationStore] = {}
_store_cache_lock = threading.Lock()


def get_orchestration_store(db_path: Optional[Path | str] = None) -> OrchestrationStore:
    path = Path(db_path) if db_path else _default_db_path()
    key = str(path.resolve()) if path != Path(":memory:") else f":memory:{time.time_ns()}"
    with _store_cache_lock:
        store = _store_cache.get(key)
        if store is None:
            store = OrchestrationStore(path)
            _store_cache[key] = store
        return store
