"""Snapshot source, cron, and operational DB freshness without waking an agent."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_constants import get_elevate_home


STATE_DIR = get_elevate_home() / "state" / "cron-health"
STATE_PATH = STATE_DIR / "operational-freshness-latest.json"
ALERT_KEY_PATH = STATE_DIR / "operational-freshness-alert-key.txt"

SYNC_LABELS = [
    "ai.elevate.gateway",
    "ai.elevate.sync-crm",
    "ai.elevate.sync-apple-messages",
    "ai.elevate.sync-xposure-pcs",
    "ai.elevate.sync-xposure-pcs-views",
    "ai.elevate.sync-social",
    "ai.elevate.review-contacts",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(conn: Any, table: str) -> set[str]:
    try:
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=?
            """,
            (table,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}
    except Exception:
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {str(row["name"]) for row in rows}
        except Exception:
            return set()


def _table_exists(conn: Any, table: str) -> bool:
    return bool(_table_columns(conn, table))


def _count(conn: Any, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    if not _table_exists(conn, table):
        return 0
    sql = f"SELECT COUNT(*) AS count FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql, params).fetchone()
    return int(row["count"] or 0) if row else 0


def _group_count(conn: Any, table: str, column: str) -> dict[str, int]:
    if column not in _table_columns(conn, table):
        return {}
    rows = conn.execute(
        f"SELECT {column}, COUNT(*) AS count FROM {table} GROUP BY {column} ORDER BY {column}"
    ).fetchall()
    return {str(row[column] or "blank"): int(row["count"] or 0) for row in rows}


def _cron_failures() -> list[dict[str, str]]:
    from cron.jobs import list_jobs

    failures: list[dict[str, str]] = []
    for job in list_jobs(include_disabled=True):
        if job.get("last_status") != "error":
            continue
        failures.append(
            {
                "id": str(job.get("id") or ""),
                "name": str(job.get("name") or ""),
                "state": str(job.get("state") or ""),
                "error": str(job.get("last_error") or "")[:240],
            }
        )
    return failures


def _launchd_snapshot() -> dict[str, Any]:
    try:
        output = subprocess.run(
            ["launchctl", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # pragma: no cover - macOS guardrail
        return {"error": str(exc), "labels": {}}

    labels: dict[str, Any] = {}
    for line in output.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        pid, status, label = parts
        if label not in SYNC_LABELS:
            continue
        labels[label] = {
            "loaded": True,
            "running": pid != "-",
            "pid": None if pid == "-" else pid,
            "lastExitStatus": status,
        }
    for label in SYNC_LABELS:
        labels.setdefault(label, {"loaded": False, "running": False, "pid": None, "lastExitStatus": None})
    return {"labels": labels, "error": "" if output.returncode == 0 else output.stderr.strip()[:240]}


def _source_snapshot() -> dict[str, Any]:
    from elevate_cli.source_connectors import build_source_connectors_response

    response = build_source_connectors_response(include_prompts=False)
    connectors = response.get("connectors") or []
    connected = [c for c in connectors if c.get("connected")]
    blocked = [c for c in connectors if c.get("blocked")]
    errors = [c for c in connectors if c.get("lastError")]
    counts: dict[str, int] = {}
    for connector in connectors:
        for key, value in (connector.get("recordCounts") or {}).items():
            try:
                counts[key] = counts.get(key, 0) + int(value or 0)
            except (TypeError, ValueError):
                continue
    return {
        "sourceRoot": response.get("sourceRoot"),
        "connectors": len(connectors),
        "connected": len(connected),
        "blocked": [
            {"id": c.get("id"), "label": c.get("label"), "step": c.get("nextOperatorStep")}
            for c in blocked
        ],
        "errors": [
            {"id": c.get("id"), "label": c.get("label"), "error": c.get("lastError")}
            for c in errors
        ],
        "recordCounts": counts,
    }


def _db_snapshot() -> dict[str, Any]:
    from elevate_cli.data.agent_handoffs import agent_handoff_summary
    from elevate_cli.data.connection import connect
    from elevate_cli.data.deals import deals_overview
    from elevate_cli.data.notes import list_pending_lofty_notes

    with connect() as conn:
        now = datetime.now(timezone.utc)
        stale_review_cutoff = (now - timedelta(days=7)).isoformat()
        upcoming_end = (now + timedelta(days=21)).isoformat()
        deals = deals_overview(conn, status="active", stale_days=10)
        totals = deals.get("totals") or {}
        snapshot: dict[str, Any] = {
            "contacts": {
                "total": _count(conn, "contacts"),
                "needsFollowUp": _count(conn, "contacts", "needs_follow_up=1"),
                "hot": _count(conn, "contacts", "heat_label='hot'"),
                "staleAiReview": _count(
                    conn,
                    "contacts",
                    "(ai_last_reviewed_at IS NULL OR ai_last_reviewed_at < ?)",
                    (stale_review_cutoff,),
                ),
            },
            "conversations": {
                "total": _count(conn, "conversations"),
                "open": _count(conn, "conversations", "COALESCE(status, 'open') <> 'closed'"),
                "hot": _count(conn, "conversations", "heat_label='hot'"),
            },
            "deals": {
                "active": int(totals.get("activeAfterFilter") or len(deals.get("deals") or [])),
                "byStage": deals.get("byStage") or {},
                "closingsSoon": len(deals.get("closingsSoon") or []),
                "subjectsSoon": len(deals.get("subjectsSoon") or []),
                "staleStages": len(deals.get("staleStages") or []),
            },
            "adminActionRuns": _group_count(conn, "admin_action_runs", "status"),
            "agentHandoffs": agent_handoff_summary(conn, limit=3),
            "notes": {
                "pendingCrmPush": len(list_pending_lofty_notes(conn, limit=250, max_attempts=5)),
                "bySyncState": _group_count(conn, "notes", "crm_sync_state"),
            },
            "calendar": {
                "upcoming21d": _count(
                    conn,
                    "admin_calendar_events",
                    "start_at IS NOT NULL AND start_at >= ? AND start_at <= ?",
                    (now.isoformat(), upcoming_end),
                ),
                "byKind": _group_count(conn, "admin_calendar_events", "kind"),
            },
        }
        return snapshot


def _warnings(report: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    db = report.get("db") or {}
    cron_failures = report.get("cronFailures") or []
    if cron_failures:
        warnings.append(
            "Cron jobs with errors: "
            + ", ".join(f"{item['name']} ({item['error']})" for item in cron_failures[:4])
        )
    admin = db.get("adminActionRuns") or {}
    if int(admin.get("failed") or 0) > 0:
        warnings.append(f"Admin action runs have {admin.get('failed')} failed rows.")
    handoffs = db.get("agentHandoffs") or {}
    if int(handoffs.get("failed") or 0) > 0:
        warnings.append(f"Agent handoffs have {handoffs.get('failed')} failed rows.")
    notes = db.get("notes") or {}
    if int(notes.get("pendingCrmPush") or 0) >= 25:
        warnings.append(f"CRM note push queue has {notes.get('pendingCrmPush')} pending notes.")
    sources = report.get("sources") or {}
    if sources.get("blocked"):
        warnings.append(
            "Blocked source connectors: "
            + ", ".join(str(item.get("id") or item.get("label")) for item in sources["blocked"][:6])
        )
    if sources.get("errors"):
        warnings.append(
            "Source connector errors: "
            + ", ".join(f"{item.get('id')}: {item.get('error')}" for item in sources["errors"][:4])
        )
    launchd = ((report.get("launchd") or {}).get("labels") or {})
    missing = [label for label, item in launchd.items() if not item.get("loaded")]
    if missing:
        warnings.append("Missing launchd sync services: " + ", ".join(missing))
    bad_exit = [
        label
        for label, item in launchd.items()
        if item.get("loaded") and str(item.get("lastExitStatus")) not in {"0", "None", ""}
        and not item.get("running")
    ]
    if bad_exit:
        warnings.append("Launchd sync services with non-zero last exit: " + ", ".join(bad_exit))
    return warnings


def _alert_key(warnings: list[str]) -> str:
    blob = json.dumps(warnings, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _write_state(report: dict[str, Any], alert_key: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(STATE_PATH)
    ALERT_KEY_PATH.write_text(alert_key, encoding="utf-8")


def main() -> int:
    report: dict[str, Any] = {
        "ok": True,
        "script": "operational-freshness-snapshot",
        "ts": _utc_now(),
        "db": {},
        "sources": {},
        "launchd": {},
        "cronFailures": [],
        "warnings": [],
        "errors": [],
    }
    try:
        report["db"] = _db_snapshot()
    except Exception as exc:
        report["errors"].append({"step": "db_snapshot", "error": str(exc), "trace": traceback.format_exc(limit=6)})
    try:
        report["sources"] = _source_snapshot()
    except Exception as exc:
        report["errors"].append({"step": "source_snapshot", "error": str(exc), "trace": traceback.format_exc(limit=6)})
    try:
        report["cronFailures"] = _cron_failures()
    except Exception as exc:
        report["errors"].append({"step": "cron_failures", "error": str(exc), "trace": traceback.format_exc(limit=6)})
    report["launchd"] = _launchd_snapshot()
    report["warnings"] = _warnings(report)
    report["ok"] = not report["errors"]

    alert_key = _alert_key(report["warnings"] + [item["error"] for item in report["errors"]])
    prior_key = ALERT_KEY_PATH.read_text(encoding="utf-8").strip() if ALERT_KEY_PATH.exists() else ""
    _write_state(report, alert_key)

    if os.environ.get("ELEVATE_CRON_VERBOSE"):
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 1 if report["errors"] else 0
    if not report["warnings"] and not report["errors"]:
        print("wakeAgent: false")
        return 0
    if prior_key == alert_key:
        print("wakeAgent: false")
        return 0

    lines = ["Operational freshness warning"]
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    if report["errors"]:
        lines.append("")
        lines.append("Snapshot errors:")
        lines.extend(f"- {item['step']}: {item['error']}" for item in report["errors"])
    lines.append("")
    lines.append(f"Snapshot: {STATE_PATH}")
    print("\n".join(lines))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
