"""Post-update runtime reconciliation for ``elevate update``.

This module intentionally runs as a separate Python process from the updater.
That lets the updater execute reconciliation with the runtime interpreter after
dependencies have been refreshed, instead of relying on modules already loaded
by the old process.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from typing import Any


_REQUIRED_IMPORTS = (
    "croniter",
    "fastapi",
    "multipart",
    "openai",
    "psycopg",
    "psycopg_pool",
    "uvicorn",
)


def _record_error(report: dict[str, Any], step: str, exc: BaseException) -> None:
    report["ok"] = False
    report.setdefault("errors", []).append(
        {
            "step": step,
            "error": str(exc),
            "trace": traceback.format_exc(limit=6),
        }
    )


def _check_required_imports(report: dict[str, Any]) -> None:
    imports: dict[str, dict[str, Any]] = {}
    for module_name in _REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
            imports[module_name] = {"ok": True}
        except Exception as exc:
            imports[module_name] = {"ok": False, "error": str(exc)}
            report["ok"] = False
    report["imports"] = imports


def _sync_bundled_skills(report: dict[str, Any]) -> None:
    from tools.skills_sync import sync_skills

    result = sync_skills(quiet=True)
    report["bundledSkills"] = {
        "copied": len(result.get("copied") or []),
        "updated": len(result.get("updated") or []),
        "skipped": int(result.get("skipped") or 0),
        "userModified": len(result.get("user_modified") or []),
        "cleaned": len(result.get("cleaned") or []),
        "totalBundled": int(result.get("total_bundled") or 0),
    }


def _seed_agent_hub_defaults(report: dict[str, Any]) -> None:
    from elevate_cli.agent_hub import reconcile_agent_hub_defaults

    result = reconcile_agent_hub_defaults()
    report["agentHub"] = {
        "changed": bool(result.get("changed")),
        "created": list(result.get("created") or []),
        "updated": len(result.get("updated") or []),
        "count": int(result.get("count") or 0),
        "defaultAgent": result.get("defaultAgent") or "executive-assistant",
    }


def _seed_operational_defaults(report: dict[str, Any]) -> None:
    from elevate_cli.data import connect
    from elevate_cli.data.dispatch import ensure_default_admin_actions

    with connect() as conn:
        result = ensure_default_admin_actions(conn)

    report["adminActions"] = {
        "created": len(result.get("created") or []),
        "updated": len(result.get("updated") or []),
        "skipped": len(result.get("skipped") or []),
        "count": int(result.get("count") or 0),
    }


def _seed_system_crons(report: dict[str, Any]) -> None:
    from cron.jobs import compute_next_run, ensure_system_jobs, list_jobs

    jobs = ensure_system_jobs()
    cron_items: list[dict[str, Any]] = []
    for job in jobs:
        item = {
            "id": job.get("id"),
            "name": job.get("name"),
            "prompt": bool(str(job.get("prompt") or "").strip()),
            "nextRunOk": True,
            "nextRunAt": None,
            "error": None,
        }
        try:
            schedule = job.get("schedule")
            if isinstance(schedule, dict):
                item["nextRunAt"] = compute_next_run(schedule, job.get("last_run_at"))
                item["nextRunOk"] = bool(item["nextRunAt"])
        except Exception as exc:
            item["nextRunOk"] = False
            item["error"] = str(exc)
            report["ok"] = False
        cron_items.append(item)

    enabled_checks: list[dict[str, Any]] = []
    for job in list_jobs(include_disabled=True):
        if not job.get("enabled", True) or job.get("state") == "paused":
            continue
        schedule = job.get("schedule")
        if not isinstance(schedule, dict):
            continue
        if schedule.get("kind") not in {"cron", "interval"}:
            continue
        item = {
            "id": job.get("id"),
            "name": job.get("name"),
            "ok": True,
            "nextRunAt": None,
            "error": None,
        }
        try:
            item["nextRunAt"] = compute_next_run(schedule, job.get("last_run_at"))
            item["ok"] = bool(item["nextRunAt"])
        except Exception as exc:
            item["ok"] = False
            item["error"] = str(exc)
        if not item["ok"]:
            report["ok"] = False
        enabled_checks.append(item)

    report["systemJobs"] = {
        "count": len(cron_items),
        "withPrompts": sum(1 for item in cron_items if item["prompt"]),
        "nextRunOk": sum(1 for item in cron_items if item["nextRunOk"]),
        "jobs": cron_items,
        "enabledRecurringChecked": len(enabled_checks),
        "enabledRecurringOk": sum(1 for item in enabled_checks if item["ok"]),
        "enabledRecurringFailures": [
            item for item in enabled_checks if not item["ok"]
        ][:10],
    }


def reconcile() -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "python": sys.executable,
        "imports": {},
        "bundledSkills": None,
        "agentHub": None,
        "adminActions": None,
        "systemJobs": None,
        "errors": [],
    }

    _check_required_imports(report)

    try:
        _sync_bundled_skills(report)
    except Exception as exc:  # pragma: no cover - update guardrail
        _record_error(report, "bundled skills", exc)

    try:
        _seed_agent_hub_defaults(report)
    except Exception as exc:  # pragma: no cover - update guardrail
        _record_error(report, "agent hub defaults", exc)

    try:
        _seed_operational_defaults(report)
    except Exception as exc:  # pragma: no cover - update guardrail
        _record_error(report, "admin defaults", exc)

    try:
        _seed_system_crons(report)
    except Exception as exc:  # pragma: no cover - update guardrail
        _record_error(report, "system cron jobs", exc)

    return report


def _print_human(report: dict[str, Any]) -> None:
    print(f"  Python: {report.get('python')}")

    imports = report.get("imports") or {}
    missing = [name for name, item in imports.items() if not item.get("ok")]
    if missing:
        print(f"  ! Missing runtime imports: {', '.join(missing)}")
    else:
        print("  OK Runtime imports available")

    skills = report.get("bundledSkills")
    if isinstance(skills, dict):
        print(
            "  OK Bundled skills: "
            f"{skills.get('totalBundled', 0)} bundled "
            f"(+{skills.get('copied', 0)}, "
            f"updated {skills.get('updated', 0)}, "
            f"{skills.get('userModified', 0)} user-modified kept)"
        )

    hub = report.get("agentHub")
    if isinstance(hub, dict):
        created = hub.get("created") or []
        created_text = f", created {', '.join(created)}" if created else ""
        print(
            "  OK Agent Hub: "
            f"{hub.get('count', 0)} agents, "
            f"{hub.get('updated', 0)} repaired, "
            f"default {hub.get('defaultAgent') or 'executive-assistant'}"
            f"{created_text}"
        )

    actions = report.get("adminActions")
    if isinstance(actions, dict):
        print(
            "  OK Admin actions: "
            f"{actions.get('count', 0)} total "
            f"(+{actions.get('created', 0)}, "
            f"updated {actions.get('updated', 0)}, "
            f"{actions.get('skipped', 0)} unchanged)"
        )

    jobs = report.get("systemJobs")
    if isinstance(jobs, dict):
        print(
            "  OK System cron jobs: "
            f"{jobs.get('count', 0)} present, "
            f"{jobs.get('withPrompts', 0)} with prompts, "
            f"{jobs.get('nextRunOk', 0)} next-run checks ok"
        )
        checked = int(jobs.get("enabledRecurringChecked") or 0)
        ok = int(jobs.get("enabledRecurringOk") or 0)
        if checked:
            print(f"  OK Enabled recurring crons: {ok}/{checked} next-run checks ok")
        failures = jobs.get("enabledRecurringFailures") or []
        for failure in failures[:3]:
            print(
                "  ! Cron next-run failed: "
                f"{failure.get('name') or failure.get('id')}: {failure.get('error') or 'no next run'}"
            )

    for error in report.get("errors") or []:
        print(f"  ! {error.get('step')}: {error.get('error')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile Elevate runtime state after update.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = reconcile()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _print_human(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
