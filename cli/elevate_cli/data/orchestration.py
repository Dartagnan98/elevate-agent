"""Postgres-backed wrapper around the orchestration registry.

Replaces ``~/.elevate/orchestration.db`` (SQLite, single-writer-lock prone)
with the embedded Postgres instance owned by ``elevate_cli.data.connection``.

The public surface mirrors ``gateway.orchestration.OrchestrationStore`` so
callers swap one import line and keep working. The SQL is nearly identical
to the SQLite version — ``?`` placeholders and ``INSERT OR IGNORE`` are
translated by the connection shim; ``COLLATE NOCASE`` is replaced with
``LOWER(...)`` ordering (the only SQLite-ism the shim does not handle).

Backfill of the legacy file is done by ``_aux_data_migrate``.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from elevate_cli.data.connection import connect

# ─── Re-exports + helpers cribbed from gateway.orchestration ─────────────
# We pull the validation helpers, status sets, and row-shaping functions
# from gateway.orchestration so behavior stays identical bit-for-bit.

from gateway.orchestration import (  # noqa: F401 — public re-exports
    DEFAULT_ORCHESTRATION_AGENTS,
    OrchestrationValidationError,
    _ACTIVE_RUN_STATUSES,
    _AGENT_STATUSES,
    _RUN_METADATA_FIELDS,
    _RUN_STATUSES,
    _TERMINAL_STATUSES,
    _UNSET,
    _clean_id,
    _clean_run_id,
    _clean_status,
    _clean_string,
    _json_dumps,
    _row_to_agent,
    _row_to_event,
    _row_to_run,
    _slug_id,
    _utc_now,
    normalize_run_metadata,
    summarize_run_plan_graph,
)


class OrchestrationStorePg:
    """Postgres-backed orchestration registry.

    Drop-in for ``OrchestrationStore``. No db_path argument — there's
    exactly one operational DB per install.
    """

    def __init__(self) -> None:
        self._defaults_seeded = False

    # ─── default-agent seed (idempotent) ─────────────────────────────────

    def ensure_default_agents(self) -> None:
        if self._defaults_seeded:
            return
        now = _utc_now()
        with connect() as conn:
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
        self._defaults_seeded = True

    # ─── agents ───────────────────────────────────────────────────────────

    def list_agents(
        self, *, org: Optional[str] = None, include_disabled: bool = True
    ) -> List[Dict[str, Any]]:
        self.ensure_default_agents()
        clauses: list[str] = []
        params: list[Any] = []
        if org:
            clauses.append("org = ?")
            params.append(str(org))
        if not include_disabled:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM orchestration_agents
                {where}
                ORDER BY
                  CASE tier WHEN 'primary' THEN 0 ELSE 1 END,
                  LOWER(display_name)
                """,
                params,
            ).fetchall()
        return [_row_to_agent(row) for row in rows]

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agent_id = _clean_id(agent_id)
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return _row_to_agent(row) if row else None

    def upsert_agent(self, data: Dict[str, Any]) -> Dict[str, Any]:
        raw_agent_id = data.get("agent_id") or data.get("id")
        agent_id = _clean_id(
            raw_agent_id or _slug_id(data.get("name") or data.get("display_name"))
        )
        display_name = _clean_string(
            data.get("display_name")
            or data.get("name")
            or agent_id.replace("-", " ").title(),
            field="display_name",
            max_length=160,
            required=True,
        )
        role = _clean_string(data.get("role") or "", field="role", max_length=600) or ""
        tier = (
            _clean_string(data.get("tier") or "specialist", field="tier", max_length=40)
            or "specialist"
        )
        reports_to_raw = data.get("reports_to")
        reports_to = _clean_id(reports_to_raw, field="reports_to") if reports_to_raw else None
        lane = (
            _clean_string(data.get("lane") or display_name, field="lane", max_length=120)
            or display_name
        )
        org = (
            _clean_string(data.get("org") or "standalone", field="org", max_length=120)
            or "standalone"
        )
        enabled = bool(data.get("enabled", True))
        status = _clean_status(
            data.get("status"), _AGENT_STATUSES, default="ready", field="status"
        )
        current_task = _clean_string(
            data.get("current_task"), field="current_task", max_length=1000
        )
        metadata_json = _json_dumps(
            data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        )
        now = _utc_now()

        with connect() as conn:
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

    def update_agent(
        self, agent_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        current = self.get_agent(agent_id)
        if not current:
            return None
        metadata_update = updates.get("metadata", _UNSET)
        current_metadata = (
            current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        )
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
            self.upsert_agent(
                {"agent_id": agent_id, "display_name": agent_id.replace("-", " ").title()}
            )
        values: list[Any] = []
        sets = ["last_seen_at = ?", "updated_at = ?"]
        now = _utc_now()
        values.extend([now, now])
        if status is not None:
            sets.append("status = ?")
            values.append(
                _clean_status(status, _AGENT_STATUSES, default="ready", field="status")
            )
        if current_task is not _UNSET:
            sets.append("current_task = ?")
            values.append(
                _clean_string(current_task, field="current_task", max_length=1000)
            )
        values.append(agent_id)
        with connect() as conn:
            conn.execute(
                f"UPDATE orchestration_agents SET {', '.join(sets)} WHERE agent_id = ?",
                values,
            )
            conn.commit()

    # ─── runs ─────────────────────────────────────────────────────────────

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
            self.upsert_agent(
                {"agent_id": agent_id, "display_name": agent_id.replace("-", " ").title()}
            )
        run_id = _clean_run_id(run_id or f"run_{uuid.uuid4().hex}")
        task = _clean_string(task, field="task", max_length=8000, required=True) or ""
        status = _clean_status(status, _RUN_STATUSES, default="queued", field="status")
        mode = (
            _clean_string(mode or "manual", field="mode", max_length=80) or "manual"
        )
        parent_run_id = _clean_string(
            parent_run_id, field="parent_run_id", max_length=128
        )
        parent_session_key = _clean_string(
            parent_session_key, field="parent_session_key", max_length=256
        )
        session_key = _clean_string(session_key, field="session_key", max_length=256)
        normalized_metadata = normalize_run_metadata(metadata or {})
        metadata_json = _json_dumps(normalized_metadata)
        now = _utc_now()
        started_at = now if status == "running" else None
        completed_at = now if status in _TERMINAL_STATUSES else None

        with connect() as conn:
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
        self.append_event(
            run_id, f"run.{status}", f"{status}: {task[:160]}", {"agent_id": agent_id}
        )
        return self.get_run(run_id) or {}

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        run_id = _clean_run_id(run_id)
        with connect() as conn:
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
            params.append(
                _clean_status(status, _RUN_STATUSES, default="queued", field="status")
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit or 50), 200))
        with connect() as conn:
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

    def update_run(
        self, run_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        current = self.get_run(run_id)
        if not current:
            return None

        allowed = {
            "status",
            "summary",
            "error",
            "session_key",
            "metadata",
            *_RUN_METADATA_FIELDS,
        }
        cleaned: dict[str, Any] = {}
        current_metadata = (
            current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        )
        metadata_patch: dict[str, Any] = {}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "status":
                cleaned[key] = _clean_status(
                    value, _RUN_STATUSES, default=current["status"], field="status"
                )
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

        with connect() as conn:
            conn.execute(
                f"UPDATE orchestration_runs SET {', '.join(set_parts)} WHERE run_id = ?",
                params,
            )
            conn.commit()

        status_for_event = new_status or current["status"]
        self.append_event(
            run_id,
            f"run.{status_for_event}",
            updates.get("summary") or updates.get("error") or status_for_event,
        )
        updated = self.get_run(run_id)
        if updated:
            agent_status = "ready" if updated["status"] in _TERMINAL_STATUSES else "running"
            self.touch_agent(
                updated["agent_id"],
                status=agent_status,
                current_task=None if agent_status == "ready" else updated["task"],
            )
        return updated

    # ─── events ───────────────────────────────────────────────────────────

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
        event_type = (
            _clean_string(event_type, field="type", max_length=120, required=True)
            or "event"
        )
        message = _clean_string(message, field="message", max_length=4000)
        data_json = _json_dumps(data or {})
        event_id = f"evt_{uuid.uuid4().hex}"
        ts = _utc_now()
        with connect() as conn:
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
        with connect() as conn:
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
        with connect() as conn:
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

    def snapshot(
        self, *, org: Optional[str] = None, run_limit: int = 50
    ) -> Dict[str, Any]:
        agents = self.list_agents(org=org)
        runs = self.list_runs(limit=run_limit)
        active = [run for run in runs if run["status"] in _ACTIVE_RUN_STATUSES]
        by_agent = {
            agent["agent_id"]: {"active_runs": 0, "recent_runs": 0} for agent in agents
        }
        for run in runs:
            entry = by_agent.setdefault(
                run["agent_id"], {"active_runs": 0, "recent_runs": 0}
            )
            entry["recent_runs"] += 1
            if run["status"] in _ACTIVE_RUN_STATUSES:
                entry["active_runs"] += 1
        for agent in agents:
            agent["run_counts"] = by_agent.get(
                agent["agent_id"], {"active_runs": 0, "recent_runs": 0}
            )
        return {
            "generated_at": _utc_now(),
            "db_path": "postgres://elevate_operational",
            "agents": agents,
            "runs": runs,
            "active_runs": len(active),
            "run_counts": by_agent,
            "plan_graph": summarize_run_plan_graph(runs),
            "recent_events": self.list_recent_events(limit=25),
        }

    def stats(self) -> Dict[str, Any]:
        with connect() as conn:
            agent_count = int(
                conn.execute("SELECT COUNT(*) FROM orchestration_agents")
                .fetchone()[0]
            )
            active_runs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM orchestration_runs WHERE status IN ('queued', 'running')"
                ).fetchone()[0]
            )
            total_runs = int(
                conn.execute("SELECT COUNT(*) FROM orchestration_runs").fetchone()[0]
            )
        return {
            "db_path": "postgres://elevate_operational",
            "agents": agent_count,
            "active_runs": active_runs,
            "total_runs": total_runs,
        }


# Singleton — there's exactly one operational DB per install.
_singleton: Optional[OrchestrationStorePg] = None
_singleton_lock = threading.Lock()


def get_orchestration_store_pg() -> OrchestrationStorePg:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = OrchestrationStorePg()
            _singleton.ensure_default_agents()
        return _singleton


__all__ = [
    "OrchestrationStorePg",
    "OrchestrationValidationError",
    "get_orchestration_store_pg",
    "normalize_run_metadata",
    "summarize_run_plan_graph",
]
