"""Today dashboard route."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException


_ACTIVE_SESSION_WINDOW_SEC = 300
_DAY = timedelta(days=1)
_DONE_RUN_STATUSES = {"succeeded", "completed", "success", "approved", "skipped", "cancelled"}
_ATTENTION_RUN_STATUSES = {"waiting_human", "waiting_external", "needs_input", "blocked", "error", "failed"}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _waited_minutes(value: Any, now: datetime) -> int | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return max(0, round((now - parsed).total_seconds() / 60))


def _compact_job(job: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "name",
        "prompt",
        "skills",
        "skill",
        "schedule",
        "schedule_display",
        "enabled",
        "state",
        "paused_at",
        "paused_reason",
        "next_run_at",
        "last_run_at",
        "last_status",
        "last_error",
        "last_summary",
        "last_session_id",
        "deliver",
        "origin",
        "workdir",
        "agent",
        "tier",
        "alignment_status",
        "alignment_reason",
    )
    compact = {key: job.get(key) for key in fields if key in job}
    prompt = str(compact.get("prompt") or "")
    if len(prompt) > 520:
        compact["prompt"] = prompt[:517].rstrip() + "..."
    return compact


def _scheduled_next_24h(jobs: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    horizon = now + _DAY
    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for job in jobs:
        if not bool(job.get("enabled")):
            continue
        next_run = _parse_ts(job.get("next_run_at"))
        if next_run is None or next_run < now or next_run > horizon:
            continue
        upcoming.append((next_run, _compact_job(job)))
    upcoming.sort(key=lambda item: item[0])
    return [job for _, job in upcoming[:6]]


def _live_sessions() -> list[dict[str, Any]]:
    now = time.time()
    try:
        from elevate_cli.data.chat_sessions import list_session_summaries

        sessions = list_session_summaries(limit=36, offset=0)
    except Exception:
        from elevate_state import SessionDB

        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=36, offset=0)
        finally:
            db.close()

    live: list[dict[str, Any]] = []
    for session in sessions:
        last_active = float(session.get("last_active") or session.get("started_at") or 0)
        is_active = session.get("ended_at") is None and (now - last_active) < _ACTIVE_SESSION_WINDOW_SEC
        session["is_active"] = is_active
        if is_active:
            live.append(session)
    return live[:5]


def _source_inbox_response(*, limit: int, log: logging.Logger) -> dict[str, Any]:
    from elevate_cli.data import db_source_inbox_response
    from elevate_cli.source_connectors import build_source_inbox_response

    try:
        return db_source_inbox_response(limit=limit)
    except Exception:
        log.exception("Today source inbox DB read failed, falling back to JSONL")
        return build_source_inbox_response(limit=limit)


def _pending_drafts(source_inbox: dict[str, Any]) -> list[dict[str, Any]]:
    drafts = source_inbox.get("drafts")
    if not isinstance(drafts, list):
        return []
    return [
        draft
        for draft in drafts
        if isinstance(draft, dict) and str(draft.get("status") or "pending") == "pending"
    ]


def _pending_draft_total(conn: Any, *, fallback: int) -> int:
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM outreach_send_queue
            WHERE status = 'pending_approval'
            """
        ).fetchone()
    except Exception:
        return fallback
    count = int(row["c"] if row and row["c"] is not None else 0)
    return max(count, fallback)


def _count_table(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
    except Exception:
        return 0
    return int(row["c"] if row and row["c"] is not None else 0)


def _latest_ingest_items(conn: Any) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT source_id, status, rows_seen, rows_written, rows_quarantined, error, completed_at
            FROM ingest_runs
            ORDER BY started_at DESC
            LIMIT 5
            """
        ).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _upcoming_deal_dates(conn: Any, now: datetime) -> int:
    today = now.date().isoformat()
    horizon = (now + timedelta(days=14)).date().isoformat()
    date_fields = (
        "subject_removal_date",
        "deposit_due_date",
        "completion_date",
        "possession_date",
        "expected_close_date",
    )
    clauses = " OR ".join(f"({field} IS NOT NULL AND {field} >= ? AND {field} <= ?)" for field in date_fields)
    params: list[str] = []
    for _field in date_fields:
        params.extend([today, horizon])
    return _count_table(
        conn,
        f"""
        SELECT COUNT(*) AS c
        FROM deals
        WHERE status = 'active'
          AND ({clauses})
        """,
        tuple(params),
    )


def _operational_intelligence(conn: Any, *, now: datetime) -> list[dict[str, Any]]:
    pending_approvals = _pending_draft_total(conn, fallback=0)
    pcs_buyers = _count_table(conn, "SELECT COUNT(*) AS c FROM pcs_buyers")
    viewed_listings = _count_table(
        conn,
        """
        SELECT COUNT(*) AS c
        FROM pcs_listing_views
        WHERE view_count > 0 OR view_state IN ('viewed', 'favorite')
        """,
    )
    identity_conflicts = _count_table(
        conn,
        """
        SELECT COUNT(*) AS c
        FROM identity_conflicts
        WHERE resolved_at IS NULL
        """,
    )
    memory_pending = _count_table(
        conn,
        """
        SELECT COUNT(*) AS c
        FROM memory_turn_journal
        WHERE status != 'processed'
        """,
    )
    upcoming_dates = _upcoming_deal_dates(conn, now)
    latest_ingests = _latest_ingest_items(conn)
    last_ingest = latest_ingests[0] if latest_ingests else None

    items: list[dict[str, Any]] = [
        {
            "id": "pending-approvals",
            "kind": "approvals",
            "title": "Outreach approvals",
            "value": pending_approvals,
            "meta": "drafts waiting for review",
            "tone": "danger" if pending_approvals >= 50 else ("warn" if pending_approvals else "good"),
            "to": "/leads",
            "updatedAt": None,
        },
        {
            "id": "pcs-engagement",
            "kind": "pcs",
            "title": "PCS buyer signal",
            "value": pcs_buyers,
            "meta": f"{viewed_listings} viewed listings tracked",
            "tone": "warn" if viewed_listings else "neutral",
            "to": "/leads",
            "updatedAt": None,
        },
        {
            "id": "deal-dates",
            "kind": "admin",
            "title": "Admin dates",
            "value": upcoming_dates,
            "meta": "deal dates inside 14 days",
            "tone": "warn" if upcoming_dates else "good",
            "to": "/admin",
            "updatedAt": None,
        },
        {
            "id": "identity-conflicts",
            "kind": "identity",
            "title": "Identity cleanup",
            "value": identity_conflicts,
            "meta": "open merge conflicts",
            "tone": "warn" if identity_conflicts else "good",
            "to": "/leads",
            "updatedAt": None,
        },
        {
            "id": "memory-backlog",
            "kind": "memory",
            "title": "Memory backlog",
            "value": memory_pending,
            "meta": "turns pending extraction",
            "tone": "warn" if memory_pending else "good",
            "to": "/memory",
            "updatedAt": None,
        },
    ]
    if last_ingest:
        source_id = str(last_ingest.get("source_id") or "source")
        status = str(last_ingest.get("status") or "unknown")
        rows_written = int(last_ingest.get("rows_written") or 0)
        rows_quarantined = int(last_ingest.get("rows_quarantined") or 0)
        items.append(
            {
                "id": "source-health",
                "kind": "source",
                "title": "Latest source sync",
                "value": rows_written,
                "meta": f"{source_id} · {status} · {rows_quarantined} quarantined",
                "tone": "danger" if status != "completed" or rows_quarantined else "neutral",
                "to": "/leads",
                "updatedAt": last_ingest.get("completed_at"),
            }
        )
    return items


def _hot_threads(source_inbox: dict[str, Any]) -> list[dict[str, Any]]:
    threads = source_inbox.get("threads")
    if not isinstance(threads, list):
        return []
    return [
        thread
        for thread in threads
        if isinstance(thread, dict)
        and str(thread.get("status") or "") == "open"
        and str(thread.get("direction") or "") == "inbound"
        and str(thread.get("heatLabel") or "") in {"hot", "warm"}
    ]


def _urgent_admin_items(
    *,
    deal_tasks: list[dict[str, Any]],
    action_runs: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for task in deal_tasks:
        status = str(task.get("status") or "")
        if status in {"done", "completed"}:
            continue
        waited = _waited_minutes(task.get("updatedAt") or task.get("createdAt"), now)
        tone = "danger" if waited is not None and waited > 60 * 24 else ("warn" if waited is not None and waited > 60 * 4 else "neutral")
        items.append(
            {
                "id": f"task-{task.get('id')}",
                "kind": "deal-task",
                "title": task.get("title") or "Deal task",
                "meta": f"{task.get('dealTitle') or 'Deal'} · {task.get('stageName') or 'Stage'}",
                "waitedMinutes": waited,
                "tone": tone,
                "to": "/admin",
                "taskId": task.get("id"),
            }
        )

    for run in action_runs:
        status = str(run.get("status") or "")
        if status in _DONE_RUN_STATUSES:
            continue
        if status not in _ATTENTION_RUN_STATUSES:
            continue
        waited = _waited_minutes(run.get("updatedAt") or run.get("createdAt"), now)
        items.append(
            {
                "id": f"run-{run.get('id')}",
                "kind": "action-run",
                "title": run.get("registryName") or run.get("skill") or "Action run",
                "meta": str(run.get("errorMessage") or status)[:80],
                "waitedMinutes": waited,
                "tone": "danger" if status in {"error", "failed"} else "warn",
                "to": "/admin",
                "runId": run.get("id"),
            }
        )

    items.sort(key=lambda item: item.get("waitedMinutes") or 0, reverse=True)
    return items[:6]


def _priority_items(
    *,
    source_inbox: dict[str, Any],
    deal_tasks: list[dict[str, Any]],
    action_runs: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for draft in _pending_drafts(source_inbox):
        waited = _waited_minutes(draft.get("latestAt"), now)
        tone = "danger" if waited is not None and waited > 60 * 6 else ("warn" if waited is not None and waited > 60 else "neutral")
        items.append(
            {
                "id": f"draft-{draft.get('id')}",
                "kind": "draft",
                "title": f"Approve reply to {draft.get('personName') or 'lead'}",
                "meta": str(draft.get("draftText") or draft.get("title") or "Draft ready")[:90],
                "waitedMinutes": waited,
                "tone": tone,
                "to": "/leads",
                "sourceId": draft.get("sourceId"),
                "threadId": draft.get("threadId"),
            }
        )

    for thread in _hot_threads(source_inbox):
        waited = _waited_minutes(thread.get("latestAt"), now)
        heat = str(thread.get("heatLabel") or "")
        items.append(
            {
                "id": f"thread-{thread.get('id')}",
                "kind": "hot-lead",
                "title": f"{'Hot' if heat == 'hot' else 'Warm'} lead: {thread.get('personName') or 'Lead'}",
                "meta": str(thread.get("latestText") or f"{thread.get('channel') or 'message'} thread")[:90],
                "waitedMinutes": waited,
                "tone": "danger" if heat == "hot" else "warn",
                "to": "/leads",
                "sourceId": thread.get("sourceId"),
                "threadId": thread.get("threadId"),
            }
        )

    items.extend(_urgent_admin_items(deal_tasks=deal_tasks, action_runs=action_runs, now=now))
    tone_order = {"danger": 0, "warn": 1, "neutral": 2}
    items.sort(key=lambda item: (tone_order.get(str(item.get("tone")), 3), -(item.get("waitedMinutes") or 0)))
    return items[:8]


def _running_runs(action_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    running_statuses = {"running", "in_progress", "pending", "queued"}
    runs = [run for run in action_runs if str(run.get("status") or "") in running_statuses]
    runs.sort(
        key=lambda run: _parse_ts(run.get("startedAt") or run.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return runs[:5]


def create_today_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/today")
    async def get_today(source_limit: int = 160):
        try:
            from elevate_cli.data import connect, list_action_runs, list_deal_tasks
            from elevate_cli.data.today import build_today_activity

            safe_source_limit = max(16, min(int(source_limit or 160), 500))
            now = datetime.now(timezone.utc).astimezone()
            source_inbox = _source_inbox_response(limit=safe_source_limit, log=_log)
            drafts = _pending_drafts(source_inbox)
            with connect() as conn:
                action_runs = list_action_runs(conn, limit=200)
                deal_tasks = list_deal_tasks(conn, status="open", limit=200)
                pending_drafts_count = _pending_draft_total(conn, fallback=len(drafts))
                activity = build_today_activity(
                    conn,
                    pending_drafts_count=pending_drafts_count,
                    now=now,
                )
                intelligence = _operational_intelligence(conn, now=now)
            try:
                from cron.jobs import list_jobs

                jobs = list_jobs(include_disabled=True)
            except Exception:
                _log.exception("Today scheduled-job read failed")
                jobs = []
            return {
                **activity,
                "generatedAt": now.isoformat(),
                "priority": _priority_items(
                    source_inbox=source_inbox,
                    deal_tasks=deal_tasks,
                    action_runs=action_runs,
                    now=now,
                ),
                "scheduled": _scheduled_next_24h(jobs, now),
                "live": _live_sessions(),
                "running": _running_runs(action_runs),
                "intelligence": intelligence,
            }
        except Exception as exc:
            _log.exception("GET /api/today failed")
            raise HTTPException(status_code=500, detail=f"Today summary failed: {exc}")

    return router
