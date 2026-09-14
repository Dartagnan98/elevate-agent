"""Keep Elevate's operational queues and Admin registry healthy.

This module is intentionally no-agent safe: it uses the repo data layer, touches
only operational state, and prints ``wakeAgent: false`` when there is nothing
new to report.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from elevate_constants import get_elevate_home


STATE_DIR = get_elevate_home() / "state" / "cron-health"
STATE_PATH = STATE_DIR / "operational-maintenance-latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count(conn: Any, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    sql = f"SELECT COUNT(*) AS count FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql, params).fetchone()
    return int(row["count"] or 0) if row else 0


def _run_step(report: dict[str, Any], key: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - cron guardrail
        report["errors"].append(
            {
                "step": key,
                "error": str(exc),
                "trace": traceback.format_exc(limit=6),
            }
        )
        return None


def _write_state(report: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _emit(report: dict[str, Any], changed: bool) -> int:
    _write_state(report)
    if os.environ.get("ELEVATE_CRON_VERBOSE"):
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 1 if report["errors"] else 0
    if not changed and not report["errors"] and not report["warnings"]:
        print("wakeAgent: false")
        return 0

    actions = report.get("actions", {})
    deals = report.get("deals", {})
    handoffs = report.get("handoffs", {})
    crm = report.get("crm", {})
    lines = [
        "Operational DB maintenance",
        f"- admin dispatched: {actions.get('queuedAdminDispatched', 0)}",
        f"- stale admin re-queued (self-heal): {actions.get('staleAdminRequeued', 0)}",
        f"- stale admin failed (retries exhausted): {actions.get('staleAdminFailed', 0)}",
        f"- handoffs dispatched: {handoffs.get('queuedDispatched', 0)}",
        f"- stale handoffs failed: {handoffs.get('staleFailed', 0)}",
        f"- active deals: {deals.get('active', 0)}",
        f"- stale deal stages: {deals.get('staleStages', 0)}",
        f"- pending CRM note pushes: {crm.get('pendingNotePushes', 0)}",
    ]
    if report["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report["warnings"])
    if report["errors"]:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {item['step']}: {item['error']}" for item in report["errors"])
    print("\n".join(lines))
    return 1 if report["errors"] else 0


def main() -> int:
    from elevate_cli.data.agent_handoffs import (
        agent_handoff_summary,
        drain_queued_agent_handoffs,
        mark_stale_agent_handoffs,
    )
    from elevate_cli.data.connection import connect
    from elevate_cli.data.deals import deals_overview
    from elevate_cli.data.dispatch import (
        drain_queued_action_runs,
        ensure_default_admin_actions,
        mark_stale_action_runs,
    )
    from elevate_cli.data.notes import list_pending_lofty_notes

    report: dict[str, Any] = {
        "ok": True,
        "script": "operational-maintenance",
        "ts": _utc_now(),
        "actions": {},
        "handoffs": {},
        "deals": {},
        "crm": {},
        "warnings": [],
        "errors": [],
    }
    changed = False

    with connect() as conn:
        seed = _run_step(report, "ensure_default_admin_actions", lambda: ensure_default_admin_actions(conn))
        if isinstance(seed, dict):
            created = len(seed.get("created") or [])
            updated = len(seed.get("updated") or [])
            report["actions"]["defaultActionsCreated"] = created
            report["actions"]["defaultActionsUpdated"] = updated
            changed = changed or created > 0 or updated > 0

        stale_admin = _run_step(
            report,
            "mark_stale_action_runs",
            # 15 min (was 180): a run 'running' that long with no result callback
            # means its worker session died. mark_stale_action_runs re-queues it
            # (up to its retry cap) so drain_queued below re-dispatches a fresh
            # session — the run self-heals instead of sitting dead for hours.
            lambda: mark_stale_action_runs(conn, max_running_minutes=15, actor="operational-maintenance"),
        )
        if isinstance(stale_admin, list):
            requeued = sum(1 for r in stale_admin if isinstance(r, dict) and r.get("status") == "queued")
            failed = sum(1 for r in stale_admin if isinstance(r, dict) and r.get("status") == "failed")
            report["actions"]["staleAdminRequeued"] = requeued
            report["actions"]["staleAdminFailed"] = failed
            changed = changed or bool(stale_admin)

        queued_admin_count = _run_step(
            report,
            "count_queued_admin_runs",
            lambda: _count(conn, "admin_action_runs", "status='queued' AND cron_job_id IS NULL"),
        )
        if isinstance(queued_admin_count, int):
            report["actions"]["queuedAdminOpen"] = queued_admin_count

        dispatched_admin = _run_step(
            report,
            "drain_queued_action_runs",
            lambda: drain_queued_action_runs(conn, limit=25, actor="operational-maintenance"),
        )
        if isinstance(dispatched_admin, list):
            report["actions"]["queuedAdminDispatched"] = len(dispatched_admin)
            changed = changed or bool(dispatched_admin)
            if queued_admin_count and not dispatched_admin:
                report["warnings"].append(
                    "Admin action runs are queued but were not dispatched; admin setup may still need required fields."
                )

        stale_handoffs = _run_step(
            report,
            "mark_stale_agent_handoffs",
            lambda: mark_stale_agent_handoffs(
                conn,
                max_running_minutes=180,
                actor="operational-maintenance",
                limit=100,
            ),
        )
        if isinstance(stale_handoffs, list):
            report["handoffs"]["staleFailed"] = len(stale_handoffs)
            changed = changed or bool(stale_handoffs)

        dispatched_handoffs = _run_step(
            report,
            "drain_queued_agent_handoffs",
            lambda: drain_queued_agent_handoffs(conn, limit=25, actor="operational-maintenance"),
        )
        if isinstance(dispatched_handoffs, list):
            report["handoffs"]["queuedDispatched"] = len(dispatched_handoffs)
            changed = changed or bool(dispatched_handoffs)

        handoff_summary = _run_step(report, "agent_handoff_summary", lambda: agent_handoff_summary(conn, limit=5))
        if isinstance(handoff_summary, dict):
            report["handoffs"]["open"] = int(handoff_summary.get("open") or 0)
            report["handoffs"]["queued"] = int(handoff_summary.get("queued") or 0)
            report["handoffs"]["running"] = int(handoff_summary.get("running") or 0)
            report["handoffs"]["waitingHuman"] = int(handoff_summary.get("waitingHuman") or 0)
            report["handoffs"]["failed"] = int(handoff_summary.get("failed") or 0)

        overview = _run_step(report, "deals_overview", lambda: deals_overview(conn, status="active", stale_days=10))
        if isinstance(overview, dict):
            totals = overview.get("totals") or {}
            report["deals"] = {
                "active": int(totals.get("activeAfterFilter") or len(overview.get("deals") or [])),
                "staleStages": len(overview.get("staleStages") or []),
                "closingsSoon": len(overview.get("closingsSoon") or []),
                "subjectsSoon": len(overview.get("subjectsSoon") or []),
            }

        pending_notes = _run_step(
            report,
            "list_pending_lofty_notes",
            lambda: list_pending_lofty_notes(conn, limit=100, max_attempts=5),
        )
        if isinstance(pending_notes, list):
            report["crm"]["pendingNotePushes"] = len(pending_notes)

    pending_note_pushes = int(report["crm"].get("pendingNotePushes") or 0)
    if pending_note_pushes > 0:
        from elevate_cli.source_connectors import sync_pending_notes_to_lofty

        pushed = _run_step(
            report,
            "sync_pending_notes_to_lofty",
            lambda: sync_pending_notes_to_lofty(limit=25, max_attempts=5),
        )
        if isinstance(pushed, dict):
            report["crm"]["notePushSummary"] = pushed
            changed = changed or any(int(pushed.get(key) or 0) for key in ("pushed", "skipped", "failed"))
            if pushed.get("errors"):
                report["warnings"].append(
                    "CRM note push reported errors: " + "; ".join(str(item) for item in pushed["errors"][:3])
                )
        with connect() as conn:
            pending_after = _run_step(
                report,
                "list_pending_lofty_notes_after_push",
                lambda: list_pending_lofty_notes(conn, limit=100, max_attempts=5),
            )
            if isinstance(pending_after, list):
                report["crm"]["pendingNotePushes"] = len(pending_after)

    report["ok"] = not report["errors"]
    return _emit(report, changed)


if __name__ == "__main__":
    raise SystemExit(main())
