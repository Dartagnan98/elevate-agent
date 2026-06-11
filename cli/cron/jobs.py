"""
Cron job storage and management.

Jobs are stored in ~/.elevate/cron/jobs.json
Output is saved to ~/.elevate/cron/output/{job_id}/{timestamp}.md
"""

import copy
import json
import logging
import shutil
import tempfile
import threading
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from elevate_constants import get_elevate_home, get_account_data_dir
from typing import Optional, Dict, List, Any, Union

logger = logging.getLogger(__name__)

from elevate_time import now as _hermes_now
from utils import atomic_replace

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False

# =============================================================================
# Configuration
# =============================================================================

ELEVATE_DIR = get_elevate_home().resolve()
CRON_DIR = ELEVATE_DIR / "cron"
JOBS_FILE = CRON_DIR / "jobs.json"
ADMIN_CALENDAR_SYNC_JOB_NAME = "Admin Calendar Sync"
ADMIN_CALENDAR_SYNC_SCRIPT = "admin-calendar-sync.py"
OPERATIONAL_MAINTENANCE_JOB_NAME = "Operational DB Maintenance"
OPERATIONAL_MAINTENANCE_SCRIPT = "operational-maintenance.py"
OPERATIONAL_FRESHNESS_JOB_NAME = "Account + DB Freshness Snapshot"
OPERATIONAL_FRESHNESS_SCRIPT = "operational-freshness-snapshot.py"

# In-process lock protecting load_jobs→modify→save_jobs cycles.
# Required when tick() runs jobs in parallel threads — without this,
# concurrent mark_job_run / advance_next_run calls can clobber each other.
_jobs_file_lock = threading.Lock()
OUTPUT_DIR = CRON_DIR / "output"
ONESHOT_GRACE_SECONDS = 120

# Test seam: when False, ``_sync_account_cron_paths()`` is a no-op so tests can
# pin CRON_DIR/JOBS_FILE/OUTPUT_DIR directly. Always True in production.
_account_scoping_enabled = True


def _sync_account_cron_paths() -> None:
    """Re-point CRON_DIR/JOBS_FILE/OUTPUT_DIR at the logged-in account's dir.

    Cron jobs (automations + heartbeats) are scoped per account: switching
    accounts (which rewrites ``license.json`` → new ``get_account_key()``) moves
    the cron store to ``accounts/<key>/cron`` on the next op, no restart needed.
    Called from ``ensure_dirs()`` — which every read/write path runs first — so
    the module-level path constants always reflect the active account.
    """
    if not _account_scoping_enabled:
        return
    global CRON_DIR, JOBS_FILE, OUTPUT_DIR
    base = get_account_data_dir() / "cron"
    CRON_DIR = base
    JOBS_FILE = base / "jobs.json"
    OUTPUT_DIR = base / "output"


def _normalize_skill_list(skill: Optional[str] = None, skills: Optional[Any] = None) -> List[str]:
    """Normalize legacy/single-skill and multi-skill inputs into a unique ordered list."""
    if skills is None:
        raw_items = [skill] if skill else []
    elif isinstance(skills, str):
        raw_items = [skills]
    else:
        raw_items = list(skills)

    normalized: List[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _apply_skill_fields(job: Dict[str, Any]) -> Dict[str, Any]:
    """Return a job dict with canonical `skills` and legacy `skill` fields aligned."""
    normalized = dict(job)
    skills = _normalize_skill_list(normalized.get("skill"), normalized.get("skills"))
    normalized["skills"] = skills
    normalized["skill"] = skills[0] if skills else None
    return normalized


def _coerce_job_text(value: Any, fallback: str = "") -> str:
    """Coerce legacy/hand-edited nullable cron fields to strings for readers."""
    if value is None:
        return fallback
    return str(value)


def _schedule_display_for_job(job: Dict[str, Any]) -> str:
    display = _coerce_job_text(job.get("schedule_display")).strip()
    if display:
        return display

    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        for key in ("display", "value", "expr", "run_at"):
            text = _coerce_job_text(schedule.get(key)).strip()
            if text:
                return text
    elif schedule is not None:
        return str(schedule)

    return "?"


def _normalize_job_record(job: Dict[str, Any]) -> Dict[str, Any]:
    """Return a read-safe cron job shape for UI/API/tool/scheduler consumers.

    Older or hand-edited jobs can have nullable fields like ``prompt``,
    ``name``, or ``schedule_display``.  Keep storage untouched on read, but
    ensure consumers never crash while formatting or running those records.
    """
    normalized = _apply_skill_fields(job)
    job_id = _coerce_job_text(normalized.get("id"), "unknown")
    prompt = _coerce_job_text(normalized.get("prompt"))
    normalized["id"] = job_id
    normalized["prompt"] = prompt

    name = _coerce_job_text(normalized.get("name")).strip()
    if not name:
        script = _coerce_job_text(normalized.get("script")).strip()
        label_source = (
            prompt
            or (normalized["skills"][0] if normalized.get("skills") else "")
            or script
            or job_id
            or "cron job"
        )
        name = label_source[:50].strip() or "cron job"
    normalized["name"] = name
    normalized["schedule_display"] = _schedule_display_for_job(normalized)

    state = _coerce_job_text(normalized.get("state")).strip()
    if not state:
        state = "scheduled" if normalized.get("enabled", True) else "paused"
    normalized["state"] = state

    profile = _coerce_job_text(normalized.get("profile")).strip()
    normalized["profile"] = profile or None

    return normalized


def _secure_dir(path: Path):
    """Set directory to owner-only access (0700). No-op on Windows."""
    try:
        os.chmod(path, 0o700)
    except (OSError, NotImplementedError):
        pass  # Windows or other platforms where chmod is not supported


def _secure_file(path: Path):
    """Set file to owner-only read/write (0600). No-op on Windows."""
    try:
        if path.exists():
            os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


def ensure_dirs():
    """Ensure the active account's cron directories exist with secure perms."""
    _sync_account_cron_paths()
    CRON_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _secure_dir(CRON_DIR)
    _secure_dir(OUTPUT_DIR)


_SYSTEM_SCRIPT_BODIES = {
    ADMIN_CALENDAR_SYNC_SCRIPT: """from elevate_cli.events_sync import main

if __name__ == "__main__":
    raise SystemExit(main())
""",
    OPERATIONAL_MAINTENANCE_SCRIPT: """from elevate_cli.operational_maintenance import main

if __name__ == "__main__":
    raise SystemExit(main())
""",
    OPERATIONAL_FRESHNESS_SCRIPT: """from elevate_cli.operational_freshness import main

if __name__ == "__main__":
    raise SystemExit(main())
""",
}


def _ensure_system_script(script_name: str) -> Path:
    scripts_dir = ELEVATE_DIR / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    _secure_dir(scripts_dir)
    script_path = scripts_dir / script_name
    body = _SYSTEM_SCRIPT_BODIES[script_name]
    if not script_path.exists() or script_path.read_text(encoding="utf-8") != body:
        script_path.write_text(body, encoding="utf-8")
        _secure_file(script_path)
    return script_path


def _ensure_system_job(
    *,
    name: str,
    script: str,
    schedule: str,
    source: str,
    prompt: str,
) -> Dict[str, Any]:
    """Idempotently register a repo-backed no-agent system cron job."""
    _ensure_system_script(script)
    desired_updates: Dict[str, Any] = {
        "name": name,
        "prompt": prompt,
        "schedule": schedule,
        "script": script,
        "no_agent": True,
        "deliver": "local",
        "origin": {"type": "system", "source": source},
    }
    jobs = load_jobs()
    for job in jobs:
        if (job.get("name") or "").strip().lower() == name.lower():
            updates = dict(desired_updates)
            if job.get("state") == "paused":
                updates.pop("schedule", None)
            return update_job(job["id"], updates) or _normalize_job_record(job)

    return create_job(
        prompt=prompt,
        schedule=schedule,
        name=name,
        deliver="local",
        origin={"type": "system", "source": source},
        script=script,
        no_agent=True,
    )


def ensure_admin_calendar_sync_job() -> Dict[str, Any]:
    """Idempotently register the Admin Google Calendar sync cron job."""
    return _ensure_system_job(
        name=ADMIN_CALENDAR_SYNC_JOB_NAME,
        script=ADMIN_CALENDAR_SYNC_SCRIPT,
        schedule="every 15m",
        source="admin-calendar-sync",
        prompt=(
            "Run the Admin calendar sync. Pull upcoming Google Calendar events through "
            "the connected calendar integration, match events to active deals when possible, "
            "and upsert them into the Admin calendar event store. This is a no-agent system "
            "job; report only sync changes, warnings, or failures."
        ),
    )


def ensure_operational_maintenance_job() -> Dict[str, Any]:
    """Idempotently register the operational DB queue maintenance job."""
    return _ensure_system_job(
        name=OPERATIONAL_MAINTENANCE_JOB_NAME,
        script=OPERATIONAL_MAINTENANCE_SCRIPT,
        schedule="every 15m",
        source="operational-maintenance",
        prompt=(
            "Run operational DB maintenance. Seed default admin actions, fail stale admin "
            "runs and agent handoffs, dispatch queued admin actions and handoffs, summarize "
            "active deal health, and push pending CRM notes. This is a no-agent system job; "
            "stay silent when nothing needs attention."
        ),
    )


def ensure_operational_freshness_job() -> Dict[str, Any]:
    """Idempotently register the account and DB freshness snapshot job."""
    return _ensure_system_job(
        name=OPERATIONAL_FRESHNESS_JOB_NAME,
        script=OPERATIONAL_FRESHNESS_SCRIPT,
        schedule="every 30m",
        source="operational-freshness",
        prompt=(
            "Run the account and DB freshness snapshot. Check source connectors, launchd "
            "sync services, cron failures, contacts, conversations, deals, admin queues, "
            "CRM note queues, and calendar freshness. Save the snapshot and surface only "
            "new or changed warnings. This is a no-agent system job."
        ),
    )


# ─── Surface heartbeats ───────────────────────────────────────────────────────
# Per-surface work+experiment loops (Admin, Leads). Each runs the surface-heartbeat
# skill on a cadence: do the surface's work, log history, distill learnings, and
# every Nth run experiment on its own playbook. See docs/surface-heartbeats.md.
SURFACE_HEARTBEAT_SKILL = "real-estate/surface-heartbeat"
SURFACE_HEARTBEAT_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "leads": {
        "name": "Leads Heartbeat",
        "title": "Leads",
        # Primary cadence/goal = the general surface config (used by the workspace
        # seeder + surface settings). The actual runs are the FOCUSED heartbeats
        # below — each a small, context-first cron on its own cadence instead of
        # one huge run that does every lane at once.
        "schedule": "0 9 * * *",
        "config": {"agent": "outreach"},
        "goal": (
            "Work the leads board CONTEXT-FIRST: reconcile each lead's real state (latest thread "
            "message + any existing draft/approval) before acting, and never touch anyone already "
            "answered or already drafted. Split across focused heartbeats: new-lead response, "
            "follow-up cadence, hot-lead watch, and cold re-engagement."
        ),
        "heartbeats": [
            {
                "key": "new-lead-response",
                "name": "Leads · New-Lead Response",
                "schedule": "0 8,11,14,17 * * *",
                "goal": (
                    "ONLY new leads since the last run. For each, check the real thread (CRM/SMS/"
                    "email) and whether a draft/approval already exists; SKIP any already answered "
                    "or already drafted. Draft (never send) a personalized first response that "
                    "answers what they actually asked — speed-to-lead. 'all quiet' if no new leads."
                ),
            },
            {
                "key": "follow-up-sweep",
                "name": "Leads · Follow-up Sweep",
                "schedule": "0 9 * * *",
                "experiment_owner": True,
                "goal": (
                    "ONLY follow-up cadence. Reconcile each active lead's last touch + next-touch "
                    "date; list overdue follow-ups and today's showings. Draft (never send) the next "
                    "touch ONLY for cadence touches actually due and not yet drafted. Skip anyone "
                    "already answered or with a pending draft. 'all quiet' if nothing is due."
                ),
            },
            {
                "key": "hot-lead-watch",
                "name": "Leads · Hot-Lead Watch",
                "schedule": "0 12,16 * * *",
                "goal": (
                    "ONLY hot signals since the last run (inbound replies, viewing requests, repeat "
                    "opens, stage moves). Surface the hottest with a one-line why. For any with a new "
                    "inbound not already answered or drafted, draft the advancing touch. Skip "
                    "already-handled. 'all quiet' if no hot movement."
                ),
            },
            {
                "key": "appointment-confirmation",
                "name": "Leads · Appointment & Showing Confirmation",
                "schedule": "0 8,15 * * *",
                "goal": (
                    "ONLY booked appointments and showings in the next ~48h. Read the realtor's "
                    "calendar and each attendee's thread; for any not already confirmed, draft (never "
                    "send) a confirmation/reminder and flag reschedule requests or conflicts. Skip "
                    "anything already confirmed. 'all quiet' if every upcoming appointment is locked."
                ),
            },
            {
                "key": "re-engagement",
                "name": "Leads · Re-engagement",
                "schedule": "0 8 * * 1",
                "goal": (
                    "ONLY leads gone quiet 30+ days with no pending draft. Batch-draft (never send) a "
                    "revival touch anchored to something current (new listing, market shift). Skip "
                    "anyone recently re-touched or with a pending draft. 'all quiet' if none."
                ),
            },
        ],
        "experiment": {
            "every_n_runs": 7, "metric": "next_touch_reply_rate", "metric_type": "qualitative",
            "direction": "higher", "window": "7d",
            "measurement": "Self-score 1-10 the quality/likely-conversion of the next-touch drafts vs the prior cycle, with justification, until a real reply-rate metric is wired.",
            "approval_required": False,
        },
    },
    "admin": {
        "name": "Admin Heartbeat",
        "title": "Admin",
        "schedule": "30 7 * * *",
        "config": {"agent": "admin"},
        "goal": (
            "Run the admin board CONTEXT-FIRST: read where things actually stand (the realtor's "
            "connected transaction-management board, Gmail, Google Calendar, Google Drive, deal "
            "message threads, and the dashboard tasks/deals/approvals) before acting, and surface "
            "only genuine changes and questions. Split across focused heartbeats: morning transaction-"
            "board review, inbox & message triage, document routing, stage & deadline watch, and "
            "agenda & conflicts."
        ),
        "heartbeats": [
            {
                "key": "transaction-board-review",
                "name": "Admin · Transaction Board Review",
                "schedule": "0 7 * * *",
                "goal": (
                    "Every morning, look over the realtor's connected transaction-management board — "
                    "their configured compliance/admin platform (e.g. SkySlope, Lone Wolf, dotloop — "
                    "whichever they set at onboarding; use the sync skill if one exists, otherwise "
                    "sign in to the portal) — plus each active deal's message threads. Reconcile "
                    "against the Elevate deal record and what you flagged last run. Surface ONLY what "
                    "CHANGED since the last review (status moves, new or outstanding broker/compliance "
                    "items, new documents, party replies) and ONLY questions you genuinely need the "
                    "realtor to answer — draft, never send. 'all quiet' if nothing changed and nothing "
                    "needs them."
                ),
            },
            {
                "key": "inbox-triage",
                "name": "Admin · Inbox & Message Triage",
                "schedule": "0 8,11,14,17 * * *",
                "goal": (
                    "ONLY unaddressed inbound since the last run. Scan the connected Gmail and deal "
                    "message threads (sellers, buyers, the other agent, lawyer/notary, lender, "
                    "vendors) for anything not yet handled. Reconcile against what's already answered, "
                    "drafted, or filed — SKIP those. For each genuine unaddressed item: classify it, "
                    "draft (never send) the reply or create the review task on the right deal, and "
                    "flag anything that needs the realtor. 'all quiet' if the inbox is clear."
                ),
            },
            {
                "key": "doc-routing",
                "name": "Admin · Document Routing",
                "schedule": "0 9,15 * * *",
                "goal": (
                    "ONLY inbound documents since the last run (Gmail attachments, Drive drops). For "
                    "each: match it to the right deal and stage, route/file it where that deal's "
                    "documents live, attach it to the deal record, and tick or create the matching "
                    "checklist item — never send anything. Skip documents already filed. 'all quiet' "
                    "if nothing new arrived."
                ),
            },
            {
                "key": "deadline-watch",
                "name": "Admin · Stage, Deadline & Condition Watch",
                "schedule": "30 7,13 * * *",
                "experiment_owner": True,
                "goal": (
                    "ONLY active deals' stage progress and deadline risk. For each active deal: "
                    "reconcile its CURRENT board stage and read that stage's province-guide checklist "
                    "(province_checklists / admin_deal show) alongside Gmail, Calendar, and Drive to "
                    "see exactly what is done. Flag ONLY genuine gaps not already handled, on the "
                    "calendar, or flagged — an unchecked item that's now due, a condition/deadline at "
                    "risk, or a deal whose stage checklist is clear and ready to advance. Draft (never "
                    "send) what's needed and note advance-ready deals for the realtor. 'all quiet' if "
                    "every deal is on track."
                ),
            },
            {
                "key": "agenda-conflicts",
                "name": "Admin · Agenda & Conflicts",
                "schedule": "30 7 * * *",
                "goal": (
                    "ONLY today's agenda. Read Gmail, Calendar, and dashboard tasks; reconcile the "
                    "day, flag calendar conflicts and decisions the realtor owes that aren't already "
                    "resolved. 'all quiet' if the day is clear."
                ),
            },
        ],
        "experiment": {
            "every_n_runs": 7, "metric": "tasks_slipped", "metric_type": "qualitative",
            "direction": "lower", "window": "7d",
            "measurement": "Self-score 1-10 how well the agenda/flagging kept anything from slipping vs the prior cycle, with justification, until a real slipped-task metric is wired.",
            "approval_required": False,
        },
    },
    # Orchestrator (Executive Assistant) heartbeat — modeled on the
    # orchestrator HEARTBEAT cadence (fleet health 4h, approval/human-task escalation
    # 2h, morning + evening review), translated to Elevate-native (agent_bus, native
    # Tasks/Comms/Approvals; approvals escalate on the DASHBOARD, never Telegram).
    "executive-assistant": {
        "name": "Executive Assistant Heartbeat",
        "title": "Executive Assistant",
        "schedule": "0 8 * * *",
        "config": {"agent": "executive-assistant"},
        "goal": (
            "Coordinate the fleet Elevate-native: keep every agent alive and unblocked, escalate "
            "aging approvals and [HUMAN] tasks to the realtor on the dashboard, and run the daily "
            "goal cascade. Split across focused heartbeats: fleet health, approval escalation, and "
            "morning/evening rhythm."
        ),
        "heartbeats": [
            {
                "key": "fleet-health",
                "name": "EA · Fleet Health",
                "schedule": "0 */4 * * *",
                "goal": (
                    "ONLY fleet health. Read every agent's heartbeat via agent_bus; flag any agent "
                    "silent > 5h, nudge it, and note it in memory. Clear any of your own stale "
                    "in-progress tasks and keep every agent unblocked. 'all quiet' if the fleet is "
                    "healthy."
                ),
            },
            {
                "key": "approval-escalation",
                "name": "EA · Approval & Human-Task Escalation",
                "schedule": "0 */2 * * *",
                "goal": (
                    "ONLY approvals and [HUMAN] tasks. Surface every pending approval older than ~1h "
                    "and every [HUMAN] task older than ~4h to the realtor ON THE DASHBOARD (never "
                    "Telegram), and ACK related inbox messages. 'all quiet' if nothing is waiting."
                ),
            },
            {
                "key": "morning-rhythm",
                "name": "EA · Morning Review & Goal Cascade",
                "schedule": "0 8 * * *",
                "experiment_owner": True,
                "goal": (
                    "Morning rhythm: run the morning review, cascade the day's goals to each agent, "
                    "and prepare a tight briefing of the day's priorities plus the realtor's short "
                    "decision list. Draft only."
                ),
            },
            {
                "key": "evening-rhythm",
                "name": "EA · Evening Summary",
                "schedule": "0 18 * * *",
                "goal": (
                    "Evening rhythm: summarize what shipped today and what's pending, queue safe "
                    "overnight work, and surface anything aging. Draft only. 'all quiet' if the day "
                    "closed clean."
                ),
            },
        ],
        "experiment": {
            "every_n_runs": 7, "metric": "fleet_unblocked", "metric_type": "qualitative",
            "direction": "higher", "window": "7d",
            "measurement": "Self-score 1-10 how well the fleet stayed alive, unblocked, and on-goal vs the prior cycle, with justification, until a real fleet-health metric is wired.",
            "approval_required": False,
        },
    },
    # Analyst heartbeat — ported from the analyst HEARTBEAT cadence (system
    # health + agent-liveness 4h, usage/liveness pulse 2h, nightly metrics), Elevate-
    # native (agent_bus + native signals).
    "analyst": {
        "name": "Analyst Heartbeat",
        "title": "Analyst",
        "schedule": "0 1 * * *",
        "config": {"agent": "analyst"},
        "goal": (
            "Keep the system honest: monitor agent liveness, watch native signals for anomalies, and "
            "collect pipeline metrics — reporting deltas to the Executive Assistant. Split across "
            "focused heartbeats: system health, a liveness/usage pulse, and nightly metrics."
        ),
        "heartbeats": [
            {
                "key": "system-health",
                "name": "Analyst · System Health & Liveness",
                "schedule": "0 */4 * * *",
                "experiment_owner": True,
                "goal": (
                    "ONLY system health. Read every agent's heartbeat via agent_bus; flag any silent "
                    "> 5h (nudge) or > 8h (notify the Executive Assistant + log). Scan native signals "
                    "— stalled deals, aging leads, leaking stages, failed runs — and surface genuine "
                    "anomalies. 'all quiet' if the system is healthy."
                ),
            },
            {
                "key": "liveness-pulse",
                "name": "Analyst · Liveness & Usage Pulse",
                "schedule": "0 */2 * * *",
                "goal": (
                    "ONLY a fast liveness + usage pulse. Confirm agents are alive and check "
                    "session-cost / usage signals; if anything is regressing or crosses a threshold, "
                    "report it to the Executive Assistant and log it. 'all quiet' if steady."
                ),
            },
            {
                "key": "nightly-metrics",
                "name": "Analyst · Nightly Metrics",
                "schedule": "0 1 * * *",
                "goal": (
                    "Nightly metrics: collect pipeline / velocity / lead-source attribution metrics, "
                    "log them to memory, and report anomalies or notable deltas to the Executive "
                    "Assistant. Draft only."
                ),
            },
        ],
        "experiment": {
            "every_n_runs": 7, "metric": "anomalies_caught", "metric_type": "qualitative",
            "direction": "higher", "window": "7d",
            "measurement": "Self-score 1-10 how well real issues were caught early and reported vs the prior cycle, with justification, until a real anomaly metric is wired.",
            "approval_required": False,
        },
    },
}


HEARTBEAT_AGENT_ALIASES: Dict[str, List[str]] = {
    "admin": ["admin"],
    "analyst": ["analyst"],
    "theta-wave": ["theta-wave"],
    "executive-assistant": ["executive-assistant"],
    "leads": ["leads", "outreach"],
}


def _agent_exists(agent_id: str) -> bool:
    try:
        from elevate_cli.agent_hub import get_agent_def

        return get_agent_def(agent_id) is not None
    except Exception:
        return False


def resolve_surface_agent(surface: str, spec: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Resolve the Agent Hub owner for a heartbeat storage key.

    ``surface`` remains the on-disk compatibility key, but heartbeat runs should
    be owned by a real Agent Hub agent whenever one can be resolved.
    """
    spec = spec if isinstance(spec, dict) else {}
    config = spec.get("config") if isinstance(spec.get("config"), dict) else {}
    explicit = str(config.get("agent") or spec.get("agent") or "").strip()
    if explicit and _agent_exists(explicit):
        return explicit
    key = (surface or "").strip().lower()
    candidates = [key, *HEARTBEAT_AGENT_ALIASES.get(key, [])]
    seen: set[str] = set()
    for candidate in candidates:
        clean = str(candidate or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        if _agent_exists(clean):
            return clean
    return explicit or None


def _seed_surface_heartbeat_workspace(
    surface: str, spec: Dict[str, Any], *, enabled: bool = True
) -> Path:
    """Create accounts/<key>/heartbeats/<surface>/{learnings.md, history/,
    experiments/history/} on disk and seed the surface's config in the account
    database (``surface_state``, migration 0024) from defaults if absent.
    Returns the workspace Path.

    Markdown artifacts (learnings.md, history/) are documents and stay on disk;
    the config is STATE and lives in the database. ``enabled`` only governs a
    BRAND-NEW config — an existing stored config is never rewritten, so a
    surface the realtor has already turned on stays on.
    """
    from elevate_constants import get_account_data_dir
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    ws = get_account_data_dir() / "heartbeats" / surface
    (ws / "history").mkdir(parents=True, exist_ok=True)
    (ws / "experiments" / "history").mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        if not surface_state.get_config(conn, surface):
            # Build the new agent-creatable cycles[] from the spec's experiment block
            # ADDITIVELY: keep the legacy single ``experiment`` key for back-compat
            # (every reader tolerates both), and seed exactly one cycle from it so a
            # brand-new surface already carries a real cycle.
            exp = spec["experiment"]
            _every_n = exp.get("every_n_runs", 7)
            _seed_cycle = {
                "name": exp.get("metric") or f"{surface} self-improvement",
                "metric": exp.get("metric"),
                "metric_type": exp.get("metric_type", "qualitative"),
                "surface": "playbook",
                "direction": exp.get("direction", "higher"),
                "window": exp.get("window"),
                "measurement": exp.get("measurement"),
                "every_n_runs": _every_n,
                "loop_interval": f"every {_every_n} runs",
                "approval_required": bool(exp.get("approval_required", False)),
                "enabled": True,
                "created_by": "system",
                "created_at": _hermes_now().isoformat(),
            }
            extra_config = spec.get("config") if isinstance(spec.get("config"), dict) else {}
            resolved_agent = str(extra_config.get("agent") or resolve_surface_agent(surface, spec) or "").strip()
            if resolved_agent and not extra_config.get("agent"):
                extra_config = {**extra_config, "agent": resolved_agent}
            surface_state.set_config(conn, surface, {
                "surface": surface, "goal": spec["goal"], "cadence": spec["schedule"],
                "enabled": bool(enabled), "experiment": spec["experiment"],
                "cycles": [_seed_cycle],
                "created_by": "system", "created_at": _hermes_now().date().isoformat(),
                **extra_config,
            })
    learn = ws / "learnings.md"
    if not learn.exists():
        learn.write_text(
            f"# {surface.capitalize()} Heartbeat — Learnings\n\n"
            "_Accumulated work + experiment learnings. Read every run; write back durable "
            "insight. Keep it tight._\n\n(none yet — first runs populate this)\n"
        )
    return ws


# ─── Surface registry (surfaces are creatable, not hardcoded) ──────────────────
# Built-in surfaces (leads, admin) are seed specs above; custom surfaces are added
# at runtime via create_surface() and persisted to the account registry — the
# ``surface_registry`` table (migration 0024; formerly heartbeats/surfaces.json) —
# Elevate's analog of enabled-agents.json. ensure_surface() seeds ANY
# surface (built-in or custom) the same way: workspace scaffold + opt-in cron job.
# SURFACE_TEMPLATE is the default spec a new surface is filled from (
# copyTemplateFiles equivalent).
SURFACE_TEMPLATE: Dict[str, Any] = {
    "name": "{Title} Heartbeat",
    "schedule": "0 9 * * *",
    "goal": (
        "Each run: do this surface's recurring work, surface what changed, and draft "
        "(never send) anything that needs the realtor. End with one tight summary; say "
        "'all quiet' if nothing changed."
    ),
    "experiment": {
        "every_n_runs": 7, "metric": "surface_effectiveness", "metric_type": "qualitative",
        "direction": "higher", "window": "7d",
        "measurement": "Self-score 1-10 how well this surface did its job vs the prior cycle, with justification.",
        "approval_required": False,
    },
}


def load_surface_registry() -> Dict[str, Dict[str, Any]]:
    """Return {surface: spec} for every registered surface — built-ins always present,
    custom surfaces preserved. Seeds/repairs the database registry with the built-ins
    so a fresh account still gets Leads + Admin while custom surfaces persist across
    runs.
    """
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        reg = surface_state.list_registry(conn)
        # Built-in surface KEYS are stable (leads, admin); only pay the backend fetch
        # when one is actually missing (first seed). Backend mode honours the gate: seed
        # ONLY the surfaces the entitled kit returned. Offline mode (kit is None) falls
        # back to the full bundled SURFACE_HEARTBEAT_DEFAULTS.
        missing = [s for s in SURFACE_HEARTBEAT_DEFAULTS if s not in reg]
        if missing:
            kit = _backend_kit()
            if kit is not None:
                hb = kit.get("heartbeats") or {}
                for surface in missing:
                    spec = hb.get(surface)
                    if spec:  # entitled → seed; unentitled surface is skipped (gate)
                        reg[surface] = surface_state.upsert_registry(
                            conn, surface, {**spec, "created_by": "system"},
                            builtin=True, created_by="system",
                        )
            else:
                for surface in missing:  # offline fallback → bundled built-ins
                    reg[surface] = surface_state.upsert_registry(
                        conn, surface,
                        {**SURFACE_HEARTBEAT_DEFAULTS[surface], "created_by": "system"},
                        builtin=True, created_by="system",
                    )
        # Refresh stale built-ins: a row registered BEFORE the focused-heartbeat
        # split stored a spec without ``heartbeats[]``, so ensure_surface() kept
        # seeding the legacy monolithic cron forever on existing installs. Adopt
        # the split onto those rows (custom surfaces and any other realtor edits
        # to the spec are untouched — only the missing key is added).
        for surface, default_spec in SURFACE_HEARTBEAT_DEFAULTS.items():
            current = reg.get(surface)
            if not isinstance(current, dict) or current.get("heartbeats"):
                continue
            split = default_spec.get("heartbeats")
            if not split:
                continue
            reg[surface] = surface_state.upsert_registry(
                conn, surface, {**current, "heartbeats": split},
                builtin=True, created_by="system",
            )
    return reg


def register_surface(surface: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a surface spec to the account registry (add or replace)."""
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        surface_state.upsert_registry(conn, surface, dict(spec))
    return spec


def _heartbeat_units(surface: str, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The focused heartbeat units to seed for a surface.

    A surface with a ``heartbeats`` list (built-in Leads/Admin) becomes several
    small, focused crons — each its own concern on its own cadence — instead of
    one huge run. Surfaces without one (custom + per-agent) stay a single cron.
    Exactly one unit owns the experiment/cycle loop (default: the first).
    """
    title = spec.get("title") or (spec.get("name") or surface.capitalize()).replace(" Heartbeat", "")
    hbs = spec.get("heartbeats")
    if isinstance(hbs, list) and hbs:
        units: List[Dict[str, Any]] = []
        for i, hb in enumerate(hbs):
            if not isinstance(hb, dict):
                continue
            uname = str(hb.get("name") or f"{title} · Heartbeat {i + 1}").strip()
            units.append({
                "key": str(hb.get("key") or _slug_agent(uname) or f"hb{i}"),
                "name": uname,
                "schedule": hb.get("schedule") or spec.get("schedule"),
                "goal": hb.get("goal") or spec.get("goal"),
                "experiment_owner": bool(hb.get("experiment_owner", False)),
            })
        if units and not any(u["experiment_owner"] for u in units):
            units[0]["experiment_owner"] = True
        return units
    # Legacy / custom / per-agent: one cron that does the whole surface.
    return [{
        "key": "main",
        "name": spec.get("name") or f"{title} Heartbeat",
        "schedule": spec.get("schedule"),
        "goal": spec.get("goal"),
        "experiment_owner": True,
    }]


def _focused_heartbeat_prompt(surface: str, ws: Any, unit: Dict[str, Any]) -> str:
    scope = str(unit.get("goal") or "").strip()
    if unit.get("experiment_owner"):
        exp_clause = (
            "You OWN this surface's experiment/cycle loop — run it when due (per the skill's "
            "autoresearch section)."
        )
    else:
        exp_clause = (
            "You do NOT run experiments — another focused heartbeat owns this surface's experiment "
            "loop, so skip the autoresearch loop entirely."
        )
    return (
        f"You are the {surface.upper()} surface-heartbeat — a FOCUSED heartbeat. Focus: "
        f"{unit.get('name')}. Surface: {surface}. Workspace: {ws}. Run the surface-heartbeat skill "
        f"scoped to THIS focus ONLY (the surface's other focused heartbeats cover the rest): "
        f"read your surface config via the agent_bus tool (action get_surface_config) + the "
        f"workspace learnings.md, RECONCILE current state FIRST (context-first — skip anything "
        f"already handled or already drafted), then do only this focus — {scope} — log to history/, "
        f"and distill learnings. {exp_clause} Drafts only — never act on the realtor's behalf."
    )


def ensure_surface(surface: str, spec: Dict[str, Any], *, enabled: bool = False) -> Dict[str, Any]:
    """Seed ONE surface (built-in or custom): workspace scaffold + opt-in cron jobs.

    A built-in surface (Leads/Admin) seeds SEVERAL focused heartbeat crons — each a
    small, context-first concern on its own cadence — sharing the surface workspace.
    Custom/per-agent surfaces seed a single cron. Idempotent: a job already present
    (matched by name) keeps its enabled/paused state, schedule, and history; only the
    workspace + agent/prompt are repaired. New seeds default OFF (opt-in) unless
    ``enabled``. Returns the PRIMARY (experiment-owner) job.
    """
    ws = _seed_surface_heartbeat_workspace(surface, spec, enabled=enabled)
    units = _heartbeat_units(surface, spec)
    unit_names = {u["name"].strip().lower() for u in units}
    source = "system" if spec.get("created_by", "system") == "system" else "user"
    resolved_agent = resolve_surface_agent(surface, spec)
    jobs = load_jobs()

    # Retire any superseded heartbeat cron for this surface — e.g. the legacy
    # monolithic "Leads Heartbeat" once the focused units replace it — so a prior
    # install doesn't keep firing the old one-huge-run job alongside the new ones.
    # If the realtor had a retired legacy job ON, the replacement units inherit
    # that, so an upgrade never silently turns a running surface off.
    for j in jobs:
        origin = j.get("origin") or {}
        if origin.get("type") != "surface-heartbeat" or origin.get("surface") != surface:
            continue
        if (j.get("name") or "").strip().lower() not in unit_names:
            if j.get("enabled", True) and j.get("state") != "paused":
                enabled = True
            remove_job(j["id"])

    seeded: List[Dict[str, Any]] = []
    for unit in units:
        name = unit["name"]
        existing = next(
            (j for j in load_jobs() if (j.get("name") or "").strip().lower() == name.lower()),
            None,
        )
        if existing:
            patch: Dict[str, Any] = {}
            if not str(existing.get("agent") or "").strip() and resolved_agent:
                patch["agent"] = resolved_agent
            old_prompt = str(existing.get("prompt") or "")
            if "read config.json" in old_prompt:
                patch["prompt"] = old_prompt.replace(
                    "read config.json",
                    "read your surface config via the agent_bus tool (action get_surface_config)",
                    1,
                )
            if patch:
                existing = update_job(existing["id"], patch) or existing
            seeded.append((unit, existing))
            continue
        job = create_job(
            prompt=_focused_heartbeat_prompt(surface, ws, unit),
            schedule=unit["schedule"], name=name,
            skill=SURFACE_HEARTBEAT_SKILL, deliver="local",
            origin={"type": "surface-heartbeat", "surface": surface,
                    "focus": unit["key"], "experiment_owner": bool(unit.get("experiment_owner")),
                    "source": source},
            workdir=str(ws),
            agent=resolved_agent,
        )
        if not enabled:
            job = pause_job(job["id"], reason="surface heartbeat is opt-in (seeded off)") or job
        seeded.append((unit, job))

    # Primary = the experiment owner (for callers that want one representative job).
    primary = next((j for u, j in seeded if u.get("experiment_owner")), None)
    if primary is None and seeded:
        primary = seeded[0][1]
    return primary or {}


def create_surface(
    surface: str, spec: Optional[Dict[str, Any]] = None, *, created_by: str = "user"
) -> Dict[str, Any]:
    """Create a NEW custom surface from SURFACE_TEMPLATE + caller overrides, persist it
    to the registry, and seed it (opt-in/off). Mirrors add-agent +
    copyTemplateFiles. Returns {surface, spec, job}. Raises ValueError on a bad key or
    a name that already exists.
    """
    key = (surface or "").strip().lower()
    if not re.match(r"^[a-z][a-z0-9_-]{1,31}$", key):
        raise ValueError(
            "surface key must be 2-32 chars: a lowercase letter then letters/digits/-/_"
        )
    reg = load_surface_registry()
    if key in reg:
        raise ValueError(f"surface '{key}' already exists")
    spec = spec or {}
    title = spec.get("title") or key.replace("-", " ").replace("_", " ").title()
    merged = {
        "name": spec.get("name") or SURFACE_TEMPLATE["name"].format(Title=title),
        "schedule": spec.get("schedule") or SURFACE_TEMPLATE["schedule"],
        "goal": spec.get("goal") or SURFACE_TEMPLATE["goal"],
        "experiment": {**SURFACE_TEMPLATE["experiment"], **(spec.get("experiment") or {})},
        "config": spec.get("config") if isinstance(spec.get("config"), dict) else {},
        "builtin": False,
        "created_by": created_by,
    }
    register_surface(key, merged)
    job = ensure_surface(key, merged, enabled=False)
    return {"surface": key, "spec": merged, "job": job}


def delete_surface(
    surface: str,
    *,
    force: bool = False,
    remove_files: bool = True,
) -> Dict[str, Any]:
    """Remove a custom surface heartbeat and its generated cron jobs.

    Built-in surfaces are protected unless ``force`` is explicitly set. This is
    the inverse of ``create_surface``: remove the registry entry, delete the
    surface heartbeat job and any surface-automation jobs tagged to the same
    surface, then remove the heartbeat workspace folder.
    """
    key = (surface or "").strip().lower()
    if not re.match(r"^[a-z][a-z0-9_-]{1,31}$", key):
        raise ValueError(
            "surface key must be 2-32 chars: a lowercase letter then letters/digits/-/_"
        )

    reg = load_surface_registry()
    spec = reg.get(key)
    from elevate_constants import get_account_data_dir

    surface_dir = get_account_data_dir() / "heartbeats" / key
    jobs = [
        job
        for job in load_jobs()
        if (job.get("origin") or {}).get("surface") == key
        and (job.get("origin") or {}).get("type") in {"surface-heartbeat", "surface-automation"}
    ]
    if not spec and not surface_dir.exists() and not jobs:
        raise LookupError(f"surface '{key}' not found")
    if spec and spec.get("builtin") and not force:
        raise ValueError("built-in heartbeat surfaces cannot be deleted")

    removed_jobs: List[str] = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        if job_id and remove_job(job_id):
            removed_jobs.append(job_id)

    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    removed_registry = False
    with connect() as conn:
        if key in reg:
            removed_registry = bool(surface_state.remove_registry(conn, key))
        if remove_files:
            # State rows are part of the surface's data now (the old workspace
            # config.json/goals.json/heartbeat.json/experiments lived in the
            # folder being removed). surface_state has no bulk-delete helper, so
            # clear the rows directly to keep delete_surface a true inverse of
            # create_surface (a recreated surface seeds a fresh config).
            conn.execute("DELETE FROM surface_state WHERE surface = ?", (key,))
            conn.execute("DELETE FROM surface_experiments WHERE surface = ?", (key,))
            conn.execute("DELETE FROM surface_goals_history WHERE surface = ?", (key,))

    removed_files = False
    if remove_files and surface_dir.exists():
        shutil.rmtree(surface_dir)
        removed_files = True

    return {
        "ok": True,
        "surface": key,
        "removed": {
            "registry": removed_registry,
            "files": removed_files,
            "jobs": removed_jobs,
        },
    }


# ─── Per-agent heartbeats ─────────────────────────────────────────────────────
# Every installed WORKER agent gets its own heartbeat surface — its own WORK loop,
# its own experiment/theta-wave cycle, and its own learnings.md. An agent that
# owns a built-in surface (outreach→leads, admin→admin) reuses it; everyone else
# gets a per-agent surface keyed by the agent id. The orchestrator (executive-
# assistant) and the system reviewer (theta-wave) are not workers and are excluded.
_HEARTBEAT_EXCLUDED_AGENTS = {"executive-assistant", "theta-wave"}


def _slug_agent(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _agent_owns_builtin_surface(agent_id: str) -> Optional[str]:
    """The built-in surface an agent already owns (so we don't double-seed)."""
    for surface, spec in SURFACE_HEARTBEAT_DEFAULTS.items():
        owner = str((spec.get("config") or {}).get("agent") or "").strip().lower()
        if owner == agent_id:
            return surface
    return None


def _agent_surface_spec(agent_id: str) -> Dict[str, Any]:
    """A per-agent surface spec from SURFACE_TEMPLATE, personalized with the agent's
    name/role and a per-agent experiment metric (its own theta-wave cycle)."""
    name = agent_id.replace("-", " ").title()
    role = ""
    try:
        from elevate_cli.agent_hub import get_agent_def

        agent = get_agent_def(agent_id) or {}
        name = str(agent.get("name") or name)
        role = str(agent.get("role") or "")
    except Exception:
        pass
    spec = copy.deepcopy(SURFACE_TEMPLATE)
    spec["name"] = f"{name} Heartbeat"
    spec["goal"] = (
        f"Each run: do {name}'s recurring work" + (f" ({role})" if role else "") + ", surface what "
        "changed, and draft (never send) anything that needs the realtor. End with one tight "
        "summary; say 'all quiet' if nothing changed."
    )
    spec["config"] = {"agent": agent_id}
    exp = dict(spec.get("experiment") or {})
    exp["metric"] = f"{agent_id.replace('-', '_')}_effectiveness"
    spec["experiment"] = exp
    spec["created_by"] = "system"
    spec["builtin"] = False
    return spec


def _resolve_agent_surface(agent_id: str, reg: Dict[str, Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    """Return (surface, spec) for an agent — its built-in surface if it owns one,
    a registered surface if present, else a fresh per-agent spec."""
    surface = _agent_owns_builtin_surface(agent_id) or agent_id
    if surface in reg:
        return surface, reg[surface]
    if surface in SURFACE_HEARTBEAT_DEFAULTS:
        return surface, {**SURFACE_HEARTBEAT_DEFAULTS[surface], "builtin": True, "created_by": "system"}
    return surface, _agent_surface_spec(agent_id)


def _installed_agent_ids() -> List[str]:
    try:
        from elevate_cli.agent_hub import _load_agent_defs
        from elevate_cli.config import load_config

        return [
            _slug_agent(str(a.get("id") or ""))
            for a in _load_agent_defs(load_config())
            if isinstance(a, dict)
        ]
    except Exception:
        return []


def ensure_agent_heartbeat(agent_id: str, *, enabled: bool = False) -> Optional[Dict[str, Any]]:
    """Ensure ONE worker agent has its own heartbeat surface (own theta-wave cycle +
    learnings). Idempotent — reuses a built-in/registered surface, else creates one.
    Returns the seeded job, or None if the agent is excluded. Called on install."""
    aid = _slug_agent(agent_id)
    if not aid or aid in _HEARTBEAT_EXCLUDED_AGENTS:
        return None
    reg = load_surface_registry()
    surface, spec = _resolve_agent_surface(aid, reg)
    if surface not in reg:
        register_surface(surface, spec)
    return ensure_surface(surface, spec, enabled=enabled)


def register_agent_surfaces() -> None:
    """Register one heartbeat surface per installed worker agent so the next
    ensure_surface_heartbeats() seeds them. Register-only (no job seeding here)."""
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    reg = load_surface_registry()
    missing: Dict[str, Dict[str, Any]] = {}
    for aid in _installed_agent_ids():
        if not aid or aid in _HEARTBEAT_EXCLUDED_AGENTS:
            continue
        surface, spec = _resolve_agent_surface(aid, reg)
        if surface not in reg and surface not in missing:
            missing[surface] = spec
    if missing:
        with connect() as conn:
            for surface, spec in missing.items():
                surface_state.upsert_registry(conn, surface, dict(spec))


# ─── Per-agent heartbeat (model: a HEARTBEAT.md the agent reads each beat
#     + an agent-bound cron that fires it) ──────────────────────────────────────────
# Distinct from the theta-wave "surface" above (an experiment loop). This is the
# operational beat: update status, sweep inbox, (orchestrator) check fleet health,
# work tasks, surface blockers. Native Elevate only (agent_bus + Tasks/Comms/
# Approvals) — never external daemons/PM2/PTY. theta-wave (system-review) is excluded;
# the executive-assistant IS included (it's the orchestrator and beats like one).
_HEARTBEAT_CRON_EXCLUDED_AGENTS = {"theta-wave"}

_AGENT_HEARTBEAT_CRON_PROMPT = (
    "Read HEARTBEAT.md (in your working directory) and follow its instructions "
    "exactly: update your heartbeat, sweep and ACK your inbox, review agent/fleet "
    "health, work your assigned tasks (drafts only), and surface any blockers. End "
    "with one tight summary, or 'all quiet' if nothing changed."
)


def agent_heartbeat_dir(agent_id: str) -> Path:
    """Per-account, per-agent working directory: <account>/agents/<agent_id>/."""
    return get_account_data_dir() / "agents" / _slug_agent(agent_id)


def agent_heartbeat_md_path(agent_id: str) -> Path:
    """Absolute path to an agent's HEARTBEAT.md."""
    return agent_heartbeat_dir(agent_id) / "HEARTBEAT.md"


def _agent_heartbeat_md_template(agent_id: str) -> str:
    """Role-aware, Elevate-native HEARTBEAT.md — the full 10-step beat.

    Faithful port of the 10-step heartbeat, translated to Elevate tools:
    shared state via the agent_bus tool actions (update_heartbeat, read_heartbeats,
    log_event, list_tasks, update_task/complete_task, create_approval, get_goals,
    write_memory); inbox via agent_handoff/Comms; the agent's private docs
    (GOALS.md / MEMORY.md / GUARDRAILS.md / memory/<day>.md) live in its workdir.
    No external daemons / PM2 / PTY — this is the Elevate app. There is no manual
    KB-ingest in Elevate (memory is indexed automatically).
    """
    name = agent_id.replace("-", " ").title()
    role = ""
    try:
        from elevate_cli.agent_hub import get_agent_def

        agent = get_agent_def(agent_id) or {}
        name = str(agent.get("name") or name)
        role = str(agent.get("role") or "")
    except Exception:
        pass
    is_orchestrator = _slug_agent(agent_id) == "executive-assistant" or role == "main"
    lane = f"{name}" + (f" ({role})" if role else "")

    orchestrator_block = (
        "\n## Orchestrator duties (Executive Assistant only)\n"
        "You run two extra steps the workers don't — do them as part of your beat:\n\n"
        "STEP 3 — FLEET HEALTH (do this BEFORE your own tasks):\n"
        "- agent_bus `read_heartbeats` — for each agent whose heartbeat is older than "
        "5h, send it a nudge and note it; if it stays dark, escalate to the realtor.\n"
        "- agent_bus `list_approvals` — for any pending approval older than 4h, ping "
        "the realtor (Comms) with the title and what it blocks.\n"
        "- Check [HUMAN] tasks (`check_human_tasks`) — for any pending longer than 4h, "
        "ping the realtor with the title and which agent/parent task it blocks.\n\n"
        "STEP 6 — ORG GOALS (instead of the worker goal check):\n"
        "- Read the org goals (agent_bus `get_goals` / your `GOALS.md`). If today's "
        "daily focus isn't set yet AND it's before 10 AM, run your morning review now "
        "(morning-review skill). If the north-star is empty, ping the realtor to set it.\n"
        "- If any agent has empty goals, write their goals and regenerate their GOALS.md "
        "so their Step 6 finds fresh objectives.\n\n"
        "Your other rhythm (approvals watch, morning/evening/weekly review, morning "
        "brief) runs as its own separate crons — keep them enabled.\n"
        if is_orchestrator
        else ""
    )

    return (
        f"# Heartbeat — {name}\n\n"
        "Your heartbeat cron fires ~every 4 hours. Run ALL 10 steps below, in order, "
        "every cycle. This is how the dashboard and the fleet know you are alive and "
        "working.\n\n"
        "NATIVE ELEVATE ONLY — use your tools: the agent_bus tool (actions named below), "
        "Tasks, agent_handoff/Comms, Approvals, memory, and your own files. NEVER call "
        "external daemons, PM2, or PTY; this is the Elevate app.\n\n"
        "## The 10 steps\n"
        "1. UPDATE HEARTBEAT (first, always) — agent_bus `update_heartbeat` with a "
        "one-sentence summary of what you're doing. Refreshes your \"alive\" status; skip "
        "it and you show DEAD. (Distinct from the Step 4 event.)\n"
        "2. SWEEP YOUR INBOX — check incoming handoffs/messages addressed to you "
        "(agent_handoff / Comms) and act on each. Nothing should sit unanswered. Target: "
        "inbox clear.\n"
        "3. CHECK YOUR TASK QUEUE + STALE — agent_bus `list_tasks` (pending, then "
        "in_progress) for yourself; `check_stale_tasks`. Pick the highest priority. Any "
        "task in_progress > 2h: finish it or add a status note (`update_task`). No tasks "
        "→ go to Step 6.\n"
        "4. LOG A HEARTBEAT EVENT — agent_bus `log_event` (event_type heartbeat / "
        "agent_heartbeat / info). Appends to the activity feed — the audit log, separate "
        "from the Step 1 status string.\n"
        "5. WRITE DAILY MEMORY — append a block to `memory/<today>.md` in your workdir: "
        "what you're working on, status (healthy/working/blocked), inbox count, next "
        "action. (Or agent_bus `write_memory`.)\n"
        "6. CHECK YOUR GOALS — read `GOALS.md` (the orchestrator refreshes goals each "
        "morning) or agent_bus `get_goals`. Goals stale > 24h → message the Executive "
        "Assistant for fresh goals. No goals → message it now; don't idle.\n"
        "7. RESUME WORK — take the highest-priority task, `update_task` → in_progress, "
        "work it, `complete_task` with a result. Blocked → raise an Approval / [HUMAN] "
        "task instead of stalling. Drafts only for anything client-facing.\n"
        "8. GUARDRAIL SELF-CHECK — ask: \"did I skip a step or rationalize not doing "
        "something?\" If yes, `log_event` a guardrail_triggered event. A new failure "
        "pattern → append it to `GUARDRAILS.md`.\n"
        "9. UPDATE LONG-TERM MEMORY — anything that should persist across sessions "
        "(patterns that work/don't, user prefs, system behaviors) → append to `MEMORY.md`.\n"
        "10. RE-INGEST MEMORY — Elevate indexes your memory into the knowledge base "
        "automatically; there is NO manual ingest call here. Just confirm Steps 5/9 "
        "actually wrote something this cycle.\n"
        f"{orchestrator_block}"
        "\n## Target\n"
        "A heartbeat with 0 events logged and 0 memory updates means you did nothing "
        "visible. Target: ≥ 2 events and ≥ 1 memory update per cycle. Invisible work is "
        "wasted work.\n\n"
        f"## Your lane\n{lane}. Do only your own work; hand anything that belongs to "
        "another specialist up via agent_handoff rather than doing it yourself.\n\n"
        "## Rules\n"
        "- Never claim a status you haven't verified.\n"
        "- Native Elevate only: agent_bus + Tasks + Comms + Approvals + memory + your "
        "files. No external daemons / PM2 / PTY / shell agent CLIs.\n"
        "- Drafts-only for anything client-facing.\n"
    )


# Companion docs the 10-step beat reads/writes, seeded alongside HEARTBEAT.md in the
# agent's workdir. Per-agent files; seeded only if absent so the
# agent's edits/accumulated history are never clobbered.
def _agent_companion_files(agent_id: str) -> Dict[str, str]:
    name = _slug_agent(agent_id).replace("-", " ").title()
    return {
        "GOALS.md": (
            f"# Goals — {name}\n\n"
            "The orchestrator (Executive Assistant) refreshes these each morning. If "
            "this is empty or stale > 24h, message the Executive Assistant for fresh "
            "goals on your next beat (Step 6) — don't idle.\n\n"
            "## Current focus\n_(none yet)_\n\n## Goals\n_(none yet)_\n"
        ),
        "MEMORY.md": (
            f"# Long-term memory — {name}\n\n"
            "Append things that should persist across sessions: patterns that work / "
            "don't, user preferences, system behaviors (Step 9). Indexed into the "
            "knowledge base automatically.\n"
        ),
        "GUARDRAILS.md": (
            f"# Guardrails — {name}\n\n"
            "Append a line whenever you catch yourself skipping a step or rationalizing "
            "not doing something (Step 8), so the pattern doesn't repeat.\n"
        ),
    }


def ensure_agent_heartbeat_md(agent_id: str) -> Optional[Path]:
    """Idempotently seed an agent's HEARTBEAT.md from the role-aware template.

    Never overwrites an edited file — if HEARTBEAT.md already exists it is left
    exactly as-is (the realtor/agent may have customized it). Returns the path,
    or None if the agent is excluded/invalid.
    """
    aid = _slug_agent(agent_id)
    if not aid or aid in _HEARTBEAT_CRON_EXCLUDED_AGENTS:
        return None
    path = agent_heartbeat_md_path(aid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_agent_heartbeat_md_template(aid), encoding="utf-8")
        # Companion docs the 10-step beat reads/writes — seed only if absent so we
        # never clobber the agent's accumulated goals/memory/guardrails.
        for fname, body in _agent_companion_files(aid).items():
            fp = path.parent / fname
            if not fp.exists():
                fp.write_text(body, encoding="utf-8")
        (path.parent / "memory").mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.debug("ensure_agent_heartbeat_md: could not write %s", path, exc_info=True)
        return None
    return path


def ensure_agent_heartbeat_cron(
    agent_id: str, *, enabled: bool = False
) -> Optional[Dict[str, Any]]:
    """Idempotently seed an agent-bound 'heartbeat' cron (4h interval) that fires the
    agent to read its HEARTBEAT.md and run its beat. Seeded OFF/paused (opt-in) —
    the realtor enables it per agent from the Agent Hub. An existing heartbeat job
    for this agent keeps its enabled/paused state; only workdir/prompt are repaired.
    Returns the job, or None if the agent is excluded.
    """
    aid = _slug_agent(agent_id)
    if not aid or aid in _HEARTBEAT_CRON_EXCLUDED_AGENTS:
        return None
    md = ensure_agent_heartbeat_md(aid)
    workdir = str(md.parent) if md else str(agent_heartbeat_dir(aid))

    existing = next(
        (
            j
            for j in load_jobs()
            if (j.get("name") or "").strip().lower() == "heartbeat"
            and _slug_agent(str(j.get("agent") or "")) == aid
        ),
        None,
    )
    if existing:
        patch: Dict[str, Any] = {}
        if str(existing.get("workdir") or "") != workdir:
            patch["workdir"] = workdir
        if str(existing.get("prompt") or "") != _AGENT_HEARTBEAT_CRON_PROMPT:
            patch["prompt"] = _AGENT_HEARTBEAT_CRON_PROMPT
        if patch:
            existing = update_job(existing["id"], patch) or existing
        return existing

    job = create_job(
        prompt=_AGENT_HEARTBEAT_CRON_PROMPT,
        schedule="every 4h",
        name="heartbeat",
        skill="heartbeat",
        deliver="local",
        origin={"type": "system", "source": "agent-heartbeat", "agent": aid},
        workdir=workdir,
        agent=aid,
    )
    if not enabled:
        job = pause_job(job["id"], reason="per-agent heartbeat is opt-in (seeded off)") or job
    return job


def ensure_agent_heartbeats(*, enabled: bool = False) -> List[Dict[str, Any]]:
    """Seed a HEARTBEAT.md + a paused agent-bound heartbeat cron for every installed
    agent (theta-wave excluded; executive-assistant included). Idempotent."""
    out: List[Dict[str, Any]] = []
    for aid in _installed_agent_ids():
        if not aid or aid in _HEARTBEAT_CRON_EXCLUDED_AGENTS:
            continue
        # Per-agent guard: a single bad agent must never break the rest of
        # ensure_system_jobs() (this runs on every connect/install).
        try:
            job = ensure_agent_heartbeat_cron(aid, enabled=enabled)
        except Exception:
            logger.debug("ensure_agent_heartbeats: %s failed", aid, exc_info=True)
            continue
        if job:
            out.append(job)
    return out


# The Executive Assistant's coordination crons beyond its heartbeat — the
# orchestrator companion set (approvals watch + daily/weekly reviews + morning brief),
# translated to Elevate-native (agent_bus + native Tasks/Comms/Approvals + the EA's
# review skills; no the agent bus). EA-bound, seeded paused/opt-in.
_ORCHESTRATOR_AGENT = "executive-assistant"
_ORCHESTRATOR_CRONS: List[Dict[str, Any]] = [
    {
        "name": "check-approvals",
        "schedule": "every 2h",
        "skill": None,
        "prompt": (
            "Check pending approvals and human tasks. (1) agent_bus `list_approvals` — "
            "for any pending approval older than 1h, ping the realtor via Comms with the "
            "title and what it blocks. (2) `check_human_tasks` — for any [HUMAN] task "
            "pending > 4h, ping the realtor with the title and what's blocked. ACK any "
            "approval/human-task messages addressed to you. Native Elevate tools only."
        ),
    },
    {
        "name": "morning-review",
        "schedule": "0 8 * * *",
        "skill": "morning-review",
        "prompt": (
            "Run your full morning review (morning-review skill), including the goal "
            "cascade (goal-management): set the day's focus, cascade goals to each agent, "
            "then send the realtor a briefing."
        ),
    },
    {
        "name": "evening-review",
        "schedule": "0 18 * * *",
        "skill": "evening-review",
        "prompt": (
            "Run your full evening review (evening-review skill): summarize the day, "
            "propose overnight tasks, and queue nighttime work."
        ),
    },
    {
        "name": "weekly-review",
        "schedule": "0 8 * * 1",
        "skill": "weekly-review",
        "prompt": (
            "Run your full weekly review (weekly-review skill): review all agent outputs, "
            "evaluate performance, and plan next week."
        ),
    },
    {
        "name": "morning-brief",
        "schedule": "every 24h",
        "skill": None,
        "prompt": (
            "Build the morning brief: summarize the top 3-5 actions across the fleet from "
            "the overnight agent activity and surface-heartbeat outputs, and DM the realtor "
            "a punchy summary via Comms — keep it under 8 lines."
        ),
    },
]


def ensure_orchestrator_crons(*, enabled: bool = False) -> List[Dict[str, Any]]:
    """Seed the Executive Assistant's coordination crons (approvals watch + daily/weekly
    reviews + morning brief), mirroring the orchestrator. EA-bound, seeded
    paused/opt-in, idempotent (find by name+agent). No-op if the EA isn't installed."""
    aid = _ORCHESTRATOR_AGENT
    if aid not in _installed_agent_ids():
        return []
    md = ensure_agent_heartbeat_md(aid)  # ensure the EA workdir exists
    workdir = str(md.parent) if md else str(agent_heartbeat_dir(aid))
    out: List[Dict[str, Any]] = []
    for spec in _ORCHESTRATOR_CRONS:
        try:
            existing = next(
                (
                    j
                    for j in load_jobs()
                    if (j.get("name") or "").strip().lower() == spec["name"]
                    and _slug_agent(str(j.get("agent") or "")) == aid
                ),
                None,
            )
            if existing:
                out.append(existing)
                continue
            job = create_job(
                prompt=spec["prompt"],
                schedule=spec["schedule"],
                name=spec["name"],
                skill=spec.get("skill"),
                deliver="local",
                origin={"type": "system", "source": "orchestrator-cron", "agent": aid},
                workdir=workdir,
                agent=aid,
            )
            if not enabled:
                job = pause_job(
                    job["id"], reason="orchestrator cron is opt-in (seeded off)"
                ) or job
            out.append(job)
        except Exception:
            logger.debug(
                "ensure_orchestrator_crons: %s failed", spec.get("name"), exc_info=True
            )
    return out


def ensure_surface_heartbeats() -> List[Dict[str, Any]]:
    """Idempotently seed every REGISTERED surface heartbeat (workspace + cron job) for
    the active account — OFF by default (opt-in). Built-ins (Leads, Admin) come from
    the registry seed; custom surfaces created via create_surface() are seeded here too.

    Surface heartbeats run agent passes on the realtor's box, so a fresh install must
    not auto-fire them: new seeds are DISABLED (stored config ``enabled: false`` + cron
    paused). The realtor turns a surface on from the Heartbeat page. A surface whose
    cron job already exists is left exactly as-is. Mirrors the system-job seeders.
    """
    out: List[Dict[str, Any]] = []
    for surface, spec in load_surface_registry().items():
        out.append(ensure_surface(surface, spec, enabled=False))
    return out


# ─── Surface automations ──────────────────────────────────────────────────────
# The lead/admin "kit" that pairs with each surface heartbeat: the recurring
# automations a realtor can turn on per surface. Seeded OFF (opt-in), same as the
# heartbeats. Prompts are generic — each realtor's OWN connected sources, no
# hardcoded identity/data; skills are bundled (cli/skills/...). Region-specific jobs
# (Xposure/AOIR MLS, market-stats) are intentionally NOT here — not universal defaults.
SURFACE_AUTOMATION_DEFAULTS: List[Dict[str, Any]] = [
    {
        "name": "New Outreach", "surface": "leads", "schedule": "0 8 * * *",
        "skill": "local/outreach-lanes",
        "prompt": (
            "Run the outreach skill. Pull fresh leads from every connected source "
            "(CRM, SMS, email, social via Composio) that have not yet received a "
            "first-touch in the last 14 days. For each one: enrich from CRM + "
            "property-lookup, draft a personalized first message on the channel they "
            "came in from, and write the draft to the source inbox for approval. Do "
            "not send. Mark each lead as touched only after the human approves."
        ),
    },
    {
        "name": "Hot Leads Watcher", "surface": "leads", "schedule": "15 8 * * *",
        "skill": "local/outreach-lanes",
        "prompt": (
            "Run the outreach skill in monitor mode. Scan every connected source "
            "(CRM, Messages, email, SMS, social via Composio) for hot signals since "
            "the last run: inbound replies, viewing requests, repeat opens, CRM stage "
            "moves, listing alerts. Re-score heat across the inbox and surface the top "
            "10 hottest leads. For any lead with a brand-new inbound message that needs "
            "a reply, draft a same-channel response and queue it for approval. Do not send."
        ),
    },
    {
        "name": "Follow-ups", "surface": "leads", "schedule": "0 10,15 * * *",
        "skill": "local/outreach-lanes",
        "prompt": (
            "Run the outreach skill in nurture mode. For every lead with an open thread "
            "whose last outbound was 3+ days ago without a reply (or whose CRM stage is "
            "in nurture), draft a context-aware follow-up on the same channel they were "
            "last contacted. Use the relationship history, last touch, and CRM stage to "
            "pick the angle. Queue every draft for approval. Do not send."
        ),
    },
    {
        "name": "Gmail Doc Router", "surface": "admin", "schedule": "0 9 * * 1",
        "skill": "real-estate-admin/gmail-doc-router",
        "prompt": (
            "Run the gmail-doc-router skill. Check the last 7 days of Gmail attachments, "
            "match listing documents to active Elevate deals with deal-matcher, file "
            "documents to the correct Drive folder, and write artifacts/checklist "
            "evidence back to the deal with admin-result-writer. Do not send messages."
        ),
    },
    {
        "name": "Seller Update", "surface": "admin", "schedule": "0 16 * * 1-5",
        "skill": "real-estate-admin/seller-update",
        "prompt": (
            "Run the seller-update skill. Pull ShowingTime feedback/activity for active "
            "listings, match each listing to an Elevate deal, write the digest back to "
            "the operational deal store, and create Gmail seller-update drafts. Never "
            "send directly."
        ),
    },
    {
        "name": "Social Content Engine", "surface": "marketing", "schedule": "20 7 * * 1",
        "skill": "local/social-content-engine",
        "prompt": (
            "Run the social-content-engine skill (weekly content engine for the connected "
            "real estate agent).\n\n"
            "Steps:\n"
            "1. Pull last-30-day post metrics from every connected social platform "
            "(Instagram, TikTok, YouTube, Facebook, LinkedIn) using the bundled native fetchers.\n"
            "2. Aggregate + rank with scripts/aggregate.py.\n"
            "3. Research current real-estate content trends in the agent's market via the last30days skill.\n"
            "4. Read inbox + CRM signals with scripts/read_signals.py to ground ideas in real client questions.\n"
            "5. Generate 5-10 content ideas. Each one MUST cite at least one of metric / trend / signal.\n"
            "6. Queue each idea with scripts/queue_idea.py — ideas land in /social-media for human approval.\n"
            "7. Append a run summary to social-runs.jsonl.\n\n"
            "Never publish. Never invent metrics. Real-estate scope only. The human approves on /social-media."
        ),
    },
    {
        "name": "Market Stats Watcher", "surface": "marketing", "schedule": "0 7 * * 1",
        "skill": "real-estate/market-stats-watcher",
        "prompt": (
            "Run the market-stats-watcher skill. Pull fresh market-stat emails and route "
            "useful market context into the real estate knowledge/admin workflow. Do not send messages."
        ),
    },
]


# ─── Backend-distributed kit resolvers ───────────────────────────────────────
# The lead/admin kit (heartbeats + automations) is a premium, entitlement-gated
# download served by the backend (parallel to skills). At seed time we prefer the
# backend kit; if the backend is unreachable / there's no license, we fall back to
# the bundled SURFACE_*_DEFAULTS so offline + already-entitled accounts still seed.
# A reachable-but-empty reply (unentitled) returns empty collections — NOT None —
# so the entitlement gate is honoured (seed nothing rather than fall back).
def _backend_kit() -> Optional[Dict[str, Any]]:
    try:
        from elevate_cli import cloud_automations

        return cloud_automations.fetch_kit()
    except Exception:
        return None


def _effective_automation_specs() -> List[Dict[str, Any]]:
    kit = _backend_kit()
    if kit is not None:
        return kit.get("automations") or []
    return SURFACE_AUTOMATION_DEFAULTS


def ensure_surface_automations() -> List[Dict[str, Any]]:
    """Idempotently seed the per-surface lead/admin automations (the 'kit' that pairs
    with each surface heartbeat) for the active account — OFF by default (opt-in),
    exactly like ensure_surface_heartbeats().

    New seeds are created then paused (enabled=False / state="paused"). A job that
    already exists (matched by name) is ADOPTED into its surface — tagged with
    origin.type="surface-automation"/origin.surface so it shows on the surface UI —
    but its enabled state, schedule, skill, and run history are NEVER touched. So a
    realtor's own already-on automations keep running and simply appear under their
    surface (this is the "connect the lead/admin ones" half). Re-running is a no-op
    once tagged.
    """
    out: List[Dict[str, Any]] = []
    for spec in _effective_automation_specs():
        name = spec["name"]
        existing = next(
            (j for j in load_jobs() if (j.get("name") or "").strip().lower() == name.lower()),
            None,
        )
        if existing:
            # Adopt into the surface: tag origin ONLY (no enabled/schedule change).
            o = existing.get("origin") or {}
            if o.get("type") != "surface-automation":
                existing = update_job(existing["id"], {"origin": {
                    "type": "surface-automation", "surface": spec["surface"],
                    "source": "adopted",
                }}) or existing
            out.append(existing)
            continue
        job = create_job(
            prompt=spec["prompt"], schedule=spec["schedule"], name=name,
            skill=spec["skill"], deliver="local",
            origin={"type": "surface-automation", "surface": spec["surface"], "source": "system"},
        )
        paused = pause_job(job["id"], reason="surface automation is opt-in (seeded off)")
        out.append(paused or job)
    return out


# ─── Day / night mode (port of detectDayNightMode) ──────────────────
def _parse_hhmm(val: Any, default: tuple) -> tuple:
    """Parse 'HH:MM' → (h, m); fall back to default on anything malformed."""
    try:
        h, m = str(val).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except Exception:
        pass
    return default


def day_night_mode(config: Dict[str, Any], *, now=None) -> str:
    """Return 'day' or 'night' for a surface config's day window. Defaults 08:00–22:00,
    honors config.timezone when zoneinfo resolves it. Faithful port of the
    detectDayNightMode, incl. windows that wrap past midnight."""
    start = _parse_hhmm(config.get("day_mode_start"), (8, 0))
    end = _parse_hhmm(config.get("day_mode_end"), (22, 0))
    n = now or _hermes_now()
    tz = config.get("timezone")
    if tz:
        try:
            from zoneinfo import ZoneInfo
            n = n.astimezone(ZoneInfo(str(tz)))
        except Exception:
            pass
    cur = n.hour * 60 + n.minute
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]
    if s <= e:
        return "day" if s <= cur < e else "night"
    return "day" if (cur >= s or cur < e) else "night"  # wraps midnight


def is_day_mode(config: Dict[str, Any], *, now=None) -> bool:
    return day_night_mode(config, now=now) == "day"


# ─── Theta Wave — fleet self-improvement reviewer ─────────────────────────────
# The system-level analyst: the ONLY actor that creates/modifies/removes surface
# experiment cycles. Runs nightly (quiet window), scans every surface, classifies
# each (Stale/Converged/Successful/Underperforming), and shapes cycles via the cycle
# endpoints — gated by auto_create_agent_cycles / auto_modify_agent_cycles (else it
# only proposes, for dashboard approval). Faithful port of theta-wave.
THETA_WAVE_SKILL = "real-estate/theta-wave"
THETA_WAVE_NAME = "Theta Wave"
THETA_WAVE_SCHEDULE = "0 2 * * *"


def _seed_theta_wave_workspace(*, enabled: bool = True) -> Path:
    """Scaffold accounts/<key>/system-review/{learnings.md, history/,
    experiments/history/, reviews/} on disk and seed the ``system-review``
    config in the account database (``surface_state``) when absent, so the
    native fleet loop can author heartbeat experiment cycles without a daemon
    or dashboard session. Markdown artifacts stay on disk; an existing stored
    config is never rewritten (same contract as the surface seeds)."""
    from elevate_constants import get_account_data_dir
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    ws = get_account_data_dir() / "system-review"
    (ws / "history").mkdir(parents=True, exist_ok=True)
    (ws / "experiments" / "history").mkdir(parents=True, exist_ok=True)
    (ws / "reviews").mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        if not surface_state.get_config(conn, "system-review"):
            surface_state.set_config(conn, "system-review", {
                "metric": "system_effectiveness",
                "metric_type": "qualitative_compound",
                "direction": "higher",
                "schedule": THETA_WAVE_SCHEDULE,
                "created_by": "system",
                "created_at": _hermes_now().date().isoformat(),
                "enabled": bool(enabled),
                "auto_create_agent_cycles": True,
                "auto_modify_agent_cycles": True,
                "approval_required": False,
            })
    learn = ws / "learnings.md"
    if not learn.exists():
        learn.write_text(
            "# Theta Wave — Fleet Learnings\n\n_Durable insight about which surfaces improve "
            "vs stall and why. Read every review; keep it tight._\n\n(none yet)\n"
        )
    return ws


def ensure_theta_wave() -> Dict[str, Any]:
    """Idempotently seed the Theta Wave system-review cron (workspace + job) for the
    active account. Existing older paused seeds are repaired into an active native
    theta-wave agent job."""
    existing = next(
        (j for j in load_jobs() if (j.get("name") or "").strip().lower() == THETA_WAVE_NAME.lower()),
        None,
    )
    if existing:
        ws = _seed_theta_wave_workspace(enabled=True)
        updates: Dict[str, Any] = {}
        if (existing.get("agent") or "") != "theta-wave":
            updates["agent"] = "theta-wave"
        if existing.get("workdir") != str(ws):
            updates["workdir"] = str(ws)
        if (existing.get("skill") or "") != THETA_WAVE_SKILL:
            updates["skill"] = THETA_WAVE_SKILL
            updates["skills"] = [THETA_WAVE_SKILL]
        if existing.get("deliver") != "local":
            updates["deliver"] = "local"
        if existing.get("origin") != {"type": "system-review", "source": "system"}:
            updates["origin"] = {"type": "system-review", "source": "system"}
        job = update_job(existing["id"], updates) if updates else existing
        if not job:
            job = existing
        # Respect the operator's pause. An existing Theta Wave job is repaired
        # (agent/workdir/skill/origin) but its enabled/paused state is left
        # exactly as-is — same contract as ensure_surface() and the system-job
        # helper. Force-resuming here meant a paused Theta Wave silently came
        # back on within the hour (the hourly ensure_system_jobs pass), so
        # "pause all crons" could never keep it down. Fresh installs still seed
        # it enabled via create_job() in the branch below.
        return job
    ws = _seed_theta_wave_workspace(enabled=True)
    prompt = (
        f"You are Theta Wave, the fleet self-improvement reviewer. Workspace: {ws}. The surface "
        f"fleet is in the sibling dir ../heartbeats/. Run your loop per the theta-wave skill: scan "
        f"every surface, classify each (Stale/Converged/Successful/Underperforming), and create/"
        f"modify/remove cycles through the native agent_bus cycle actions — gated by "
        f"auto_create_agent_cycles / auto_modify_agent_cycles. You are the only actor "
        f"that authors cycles. Change cycles, never realtor data."
    )
    return create_job(
        prompt=prompt, schedule=THETA_WAVE_SCHEDULE, name=THETA_WAVE_NAME,
        skill=THETA_WAVE_SKILL, deliver="local",
        origin={"type": "system-review", "source": "system"},
        workdir=str(ws),
        agent="theta-wave",
    )


# ─── Memory benchmark (weekly, read-only telemetry) ──────────────────────────
MEMORY_BENCHMARK_JOB_NAME = "Memory Benchmark"
MEMORY_BENCHMARK_SCHEDULE = "0 3 * * 0"  # weekly, Sunday 03:00


def ensure_memory_benchmark_job() -> Dict[str, Any]:
    """Idempotently seed the weekly Memory Benchmark system job.

    Enabled by default — the benchmark is cheap and strictly read-only against
    the memory store (it only appends telemetry to the account's
    ``memory/benchmark_history.jsonl`` and posts one activity event). An
    existing job is left exactly as-is (pause/edits respected, no repair).
    """
    existing = next(
        (
            j for j in load_jobs()
            if (j.get("name") or "").strip().lower() == MEMORY_BENCHMARK_JOB_NAME.lower()
        ),
        None,
    )
    if existing:
        return existing
    prompt = (
        "Run the weekly holographic memory benchmark. Execute `elevate memory benchmark --json` "
        "in the terminal — it is read-only against the memory store, prints the score, appends it "
        "to the account's memory/benchmark_history.jsonl, and posts a memory_benchmark activity "
        "event. Then compare this run to the PREVIOUS line of benchmark_history.jsonl: if any "
        "metric regressed more than 20% (recall_hit_rate down, duplicate_injection_rate up, "
        "latency_ms.p95 up, or injected_token_estimate.mean_per_query up), post a one-line "
        "agent_bus activity note (event 'memory_benchmark_regression') naming the metric and its "
        "before/after values. If nothing regressed, stay silent. Never write to the memory store."
    )
    return create_job(
        prompt=prompt,
        schedule=MEMORY_BENCHMARK_SCHEDULE,
        name=MEMORY_BENCHMARK_JOB_NAME,
        deliver="local",
        origin={"type": "system-maintenance", "source": "memory-benchmark"},
    )


# ─── One-time fleet-rebuild hard replace (beta) ───────────────────────────────
# The agent-rebuild release ships a completely new fleet (7 super-agents) and a
# new focused-heartbeat layout. Existing installs carry the OLD stored agents and
# OLD heartbeat/automation crons, which would shadow the rebuild and fire next to
# the new units. This reset runs ONCE per account: purge the stored agents, every
# surface heartbeat/automation/system-review cron, and the surface registry, then
# let ensure_system_jobs() reseed the new fleet clean. Sentinel-gated so it never
# wipes a customization made AFTER the upgrade.
_FLEET_REBUILD_SENTINEL = ".fleet_rebuild_v1_applied"


def _reset_fleet_for_rebuild() -> bool:
    """Hard-replace the fleet + its heartbeats once per account. Returns True if
    it ran this call, False if already applied (sentinel present)."""
    sentinel = get_account_data_dir() / _FLEET_REBUILD_SENTINEL
    if sentinel.exists():
        return False

    # 1) Remove every old fleet cron (heartbeats, automations, theta-wave).
    fleet_origin_types = {"surface-heartbeat", "surface-automation", "system-review"}
    for job in load_jobs():
        if ((job.get("origin") or {}).get("type")) in fleet_origin_types:
            try:
                remove_job(job.get("id"))
            except Exception:
                pass

    # 2) Clear the surface registry so built-ins reseed from the new defaults.
    try:
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state as ss
        with connect() as conn:
            for surface in list(ss.list_registry(conn).keys()):
                ss.remove_registry(conn, surface)
    except Exception:
        pass

    # 3) Hard-replace the stored agent roster with the new DEFAULT_AGENT_DEFS.
    try:
        from elevate_cli.agent_hub import reset_hub_agents_to_defaults
        reset_hub_agents_to_defaults()
    except Exception:
        pass

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("applied\n", encoding="utf-8")
    return True


def ensure_system_jobs() -> List[Dict[str, Any]]:
    """Ensure repo-backed system cron jobs exist for the active Elevate home."""
    # One-time hard replace of the pre-rebuild fleet + heartbeats (beta). Runs
    # before any seeding so the reseed below starts from a clean slate.
    _reset_fleet_for_rebuild()
    # Give every installed worker agent its own heartbeat surface before seeding,
    # so each gets its own theta-wave cycle + learnings.
    register_agent_surfaces()
    return [
        ensure_admin_calendar_sync_job(),
        ensure_operational_maintenance_job(),
        ensure_operational_freshness_job(),
        *ensure_surface_heartbeats(),
        *ensure_surface_automations(),
        *ensure_agent_heartbeats(),
        *ensure_orchestrator_crons(),
        ensure_theta_wave(),
        ensure_memory_benchmark_job(),
    ]


# =============================================================================
# Schedule Parsing
# =============================================================================

def parse_duration(s: str) -> int:
    """
    Parse duration string into minutes.
    
    Examples:
        "30m" → 30
        "2h" → 120
        "1d" → 1440
    """
    s = s.strip().lower()
    match = re.match(r'^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$', s)
    if not match:
        raise ValueError(f"Invalid duration: '{s}'. Use format like '30m', '2h', or '1d'")
    
    value = int(match.group(1))
    unit = match.group(2)[0]  # First char: m, h, or d
    
    multipliers = {'m': 1, 'h': 60, 'd': 1440}
    return value * multipliers[unit]


def parse_schedule(schedule: str) -> Dict[str, Any]:
    """
    Parse schedule string into structured format.
    
    Returns dict with:
        - kind: "once" | "interval" | "cron"
        - For "once": "run_at" (ISO timestamp)
        - For "interval": "minutes" (int)
        - For "cron": "expr" (cron expression)
    
    Examples:
        "30m"              → once in 30 minutes
        "2h"               → once in 2 hours
        "every 30m"        → recurring every 30 minutes
        "every 2h"         → recurring every 2 hours
        "0 9 * * *"        → cron expression
        "2026-02-03T14:00" → once at timestamp
    """
    schedule = schedule.strip()
    original = schedule
    schedule_lower = schedule.lower()
    
    # "every X" pattern → recurring interval
    if schedule_lower.startswith("every "):
        duration_str = schedule[6:].strip()
        minutes = parse_duration(duration_str)
        return {
            "kind": "interval",
            "minutes": minutes,
            "display": f"every {minutes}m"
        }
    
    # Check for cron expression (5 or 6 space-separated fields)
    # Cron fields: minute hour day month weekday [year]
    parts = schedule.split()
    if len(parts) >= 5 and all(
        re.match(r'^[\d\*\-,/]+$', p) for p in parts[:5]
    ):
        if not HAS_CRONITER:
            raise ValueError("Cron expressions require 'croniter' package. Install with: pip install croniter")
        # Validate cron expression
        try:
            croniter(schedule)
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{schedule}': {e}")
        return {
            "kind": "cron",
            "expr": schedule,
            "display": schedule
        }
    
    # ISO timestamp (contains T or looks like date)
    if 'T' in schedule or re.match(r'^\d{4}-\d{2}-\d{2}', schedule):
        try:
            # Parse and validate
            dt = datetime.fromisoformat(schedule.replace('Z', '+00:00'))
            # Make naive timestamps timezone-aware at parse time so the stored
            # value doesn't depend on the system timezone matching at check time.
            if dt.tzinfo is None:
                dt = dt.astimezone()  # Interpret as local timezone
            return {
                "kind": "once",
                "run_at": dt.isoformat(),
                "display": f"once at {dt.strftime('%Y-%m-%d %H:%M')}"
            }
        except ValueError as e:
            raise ValueError(f"Invalid timestamp '{schedule}': {e}")
    
    # Duration like "30m", "2h", "1d" → one-shot from now
    try:
        minutes = parse_duration(schedule)
        run_at = _hermes_now() + timedelta(minutes=minutes)
        return {
            "kind": "once",
            "run_at": run_at.isoformat(),
            "display": f"once in {original}"
        }
    except ValueError:
        pass
    
    raise ValueError(
        f"Invalid schedule '{original}'. Use:\n"
        f"  - Duration: '30m', '2h', '1d' (one-shot)\n"
        f"  - Interval: 'every 30m', 'every 2h' (recurring)\n"
        f"  - Cron: '0 9 * * *' (cron expression)\n"
        f"  - Timestamp: '2026-02-03T14:00:00' (one-shot at time)"
    )


def _ensure_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime in Hermes configured timezone.

    Backward compatibility:
    - Older stored timestamps may be naive.
    - Naive values are interpreted as *system-local wall time* (the timezone
      `datetime.now()` used when they were created), then converted to the
      configured Hermes timezone.

    This preserves relative ordering for legacy naive timestamps across
    timezone changes and avoids false not-due results.
    """
    target_tz = _hermes_now().tzinfo
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        return dt.replace(tzinfo=local_tz).astimezone(target_tz)
    return dt.astimezone(target_tz)


def _recoverable_oneshot_run_at(
    schedule: Dict[str, Any],
    now: datetime,
    *,
    last_run_at: Optional[str] = None,
) -> Optional[str]:
    """Return a one-shot run time if it is still eligible to fire.

    One-shot jobs get a small grace window so jobs created a few seconds after
    their requested minute still run on the next tick. Once a one-shot has
    already run, it is never eligible again.
    """
    if schedule.get("kind") != "once":
        return None
    if last_run_at:
        return None

    run_at = schedule.get("run_at")
    if not run_at:
        return None

    run_at_dt = _ensure_aware(datetime.fromisoformat(run_at))
    if run_at_dt >= now - timedelta(seconds=ONESHOT_GRACE_SECONDS):
        return run_at
    return None


def _compute_grace_seconds(schedule: dict) -> int:
    """Compute how late a job can be and still catch up instead of fast-forwarding.

    Uses half the schedule period, clamped between 120 seconds and 2 hours.
    This ensures daily jobs can catch up if missed by up to 2 hours,
    while frequent jobs (every 5-10 min) still fast-forward quickly.
    """
    MIN_GRACE = 120
    MAX_GRACE = 7200  # 2 hours

    kind = schedule.get("kind")

    if kind == "interval":
        period_seconds = schedule.get("minutes", 1) * 60
        grace = period_seconds // 2
        return max(MIN_GRACE, min(grace, MAX_GRACE))

    if kind == "cron" and HAS_CRONITER:
        try:
            now = _hermes_now()
            cron = croniter(schedule["expr"], now)
            first = cron.get_next(datetime)
            second = cron.get_next(datetime)
            period_seconds = int((second - first).total_seconds())
            grace = period_seconds // 2
            return max(MIN_GRACE, min(grace, MAX_GRACE))
        except Exception:
            pass

    return MIN_GRACE


def compute_next_run(schedule: Dict[str, Any], last_run_at: Optional[str] = None) -> Optional[str]:
    """
    Compute the next run time for a schedule.

    Returns ISO timestamp string, or None if no more runs.
    """
    now = _hermes_now()

    if schedule["kind"] == "once":
        return _recoverable_oneshot_run_at(schedule, now, last_run_at=last_run_at)

    elif schedule["kind"] == "interval":
        minutes = schedule["minutes"]
        anchor_weekday = schedule.get("anchor_weekday")
        anchor_time = schedule.get("anchor_time")
        if last_run_at:
            base = _ensure_aware(datetime.fromisoformat(last_run_at))
        else:
            base = now

        # Anchored intervals (e.g. "every Sunday at 03:00") must re-snap to the
        # configured weekday + wall-clock time on every advance. Pure interval
        # arithmetic from last_run_at drifts permanently after the first delayed
        # fire (see Memory benchmark Sunday-slot drift, 2026-05-20).
        if minutes >= 1440 and (anchor_weekday is not None or anchor_time):
            hh, mm = 0, 0
            if anchor_time:
                try:
                    hh, mm = (int(x) for x in str(anchor_time).split(":", 1))
                except (ValueError, AttributeError):
                    hh, mm = 0, 0
            candidate = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if anchor_weekday is not None:
                days_ahead = (int(anchor_weekday) - candidate.weekday()) % 7
                candidate = candidate + timedelta(days=days_ahead)
                # Must be strictly after base; if not, jump one full week.
                while candidate <= base:
                    candidate = candidate + timedelta(days=7)
            else:
                # Daily anchor (anchor_time only): if today's anchor moment has
                # already passed, roll to tomorrow.
                while candidate <= base:
                    candidate = candidate + timedelta(days=1)
            return candidate.isoformat()

        # Plain interval — last (or now) + period.
        next_run = base + timedelta(minutes=minutes)
        return next_run.isoformat()

    elif schedule["kind"] == "cron":
        if not HAS_CRONITER:
            logger.warning(
                "Cannot compute next run for cron schedule %r: 'croniter' is "
                "not installed. croniter is a core dependency as of v0.9.x; "
                "reinstall hermes-agent or run 'pip install croniter' in your "
                "runtime env.",
                schedule.get("expr"),
            )
            return None
        # Use last_run_at as the croniter base when available, consistent
        # with interval jobs.  This ensures that after a crash/restart,
        # the next run is anchored to the actual last execution time
        # rather than to an arbitrary restart time.
        base_time = now
        if last_run_at:
            base_time = _ensure_aware(datetime.fromisoformat(last_run_at))
        cron = croniter(schedule["expr"], base_time)
        next_run = cron.get_next(datetime)
        return next_run.isoformat()

    return None


# =============================================================================
# Job CRUD Operations
# =============================================================================

def load_jobs() -> List[Dict[str, Any]]:
    """Load all jobs from storage."""
    ensure_dirs()
    if not JOBS_FILE.exists():
        return []
    
    try:
        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("jobs", [])
    except json.JSONDecodeError:
        # Retry with strict=False to handle bare control chars in string values
        try:
            with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                data = json.loads(f.read(), strict=False)
                jobs = data.get("jobs", [])
                if jobs:
                    # Auto-repair: rewrite with proper escaping
                    save_jobs(jobs)
                    logger.warning("Auto-repaired jobs.json (had invalid control characters)")
                return jobs
        except Exception as e:
            logger.error("Failed to auto-repair jobs.json: %s", e)
            raise RuntimeError(f"Cron database corrupted and unrepairable: {e}") from e
    except IOError as e:
        logger.error("IOError reading jobs.json: %s", e)
        raise RuntimeError(f"Failed to read cron database: {e}") from e


def save_jobs(jobs: List[Dict[str, Any]]):
    """Save all jobs to storage."""
    ensure_dirs()
    fd, tmp_path = tempfile.mkstemp(dir=str(JOBS_FILE.parent), suffix='.tmp', prefix='.jobs_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({"jobs": jobs, "updated_at": _hermes_now().isoformat()}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        atomic_replace(tmp_path, JOBS_FILE)
        _secure_file(JOBS_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _normalize_workdir(workdir: Optional[str]) -> Optional[str]:
    """Normalize and validate a cron job workdir.

    Rules:
      - Empty / None → None (feature off, preserves old behaviour).
      - ``~`` is expanded.  Relative paths are rejected — cron jobs run detached
        from any shell cwd, so relative paths have no stable meaning.
      - The path must exist and be a directory at create/update time.  We do
        NOT re-check at run time (a user might briefly unmount the dir; the
        scheduler will just fall back to old behaviour with a logged warning).

    Returns the absolute path string, or None when disabled.
    Raises ValueError on invalid input.
    """
    if workdir is None:
        return None
    raw = str(workdir).strip()
    if not raw:
        return None
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        raise ValueError(
            f"Cron workdir must be an absolute path (got {raw!r}). "
            f"Cron jobs run detached from any shell cwd, so relative paths are ambiguous."
        )
    resolved = expanded.resolve()
    if not resolved.exists():
        raise ValueError(f"Cron workdir does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Cron workdir is not a directory: {resolved}")
    return str(resolved)


def _normalize_profile(profile: Optional[str]) -> Optional[str]:
    """Normalize and validate an optional cron job profile name.

    Empty / None disables per-job profile selection. Otherwise the profile name
    is canonicalized with the same rules as ``hermes -p`` and must refer to an
    existing profile at create/update time. ``default`` is the built-in root
    profile and is always valid.
    """
    if profile is None:
        return None
    raw = str(profile).strip()
    if not raw:
        return None

    from elevate_cli.profiles import normalize_profile_name, resolve_profile_env

    normalized = normalize_profile_name(raw)
    # resolve_profile_env validates the canonical name and checks that named
    # profiles exist. Store only the stable profile id, not the filesystem path,
    # so profile directories can move with the Hermes root.
    resolve_profile_env(normalized)
    return normalized


def create_job(
    prompt: Optional[str],
    schedule: str,
    name: Optional[str] = None,
    repeat: Optional[int] = None,
    deliver: Optional[str] = None,
    origin: Optional[Dict[str, Any]] = None,
    skill: Optional[str] = None,
    skills: Optional[List[str]] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    script: Optional[str] = None,
    context_from: Optional[Union[str, List[str]]] = None,
    enabled_toolsets: Optional[List[str]] = None,
    workdir: Optional[str] = None,
    profile: Optional[str] = None,
    no_agent: bool = False,
    # Elevate-specific extensions for the /leads admin agent pipeline.
    # Must remain on the public signature so elevate_cli.data.dispatch and
    # admin endpoints can keep passing them. Restored after B5b-phase3
    # cron/jobs.py port from Hermes (which doesn't carry these fields).
    agent: Optional[str] = None,
    tier: Optional[str] = None,
    expected_readiness_version: Optional[str] = None,
    backfill_pending: bool = False,
    max_session_seconds: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a new cron job.

    Args:
        prompt: The prompt to run (must be self-contained, or a task instruction when skill is set).
                Ignored when ``no_agent=True`` except as an optional name hint.
        schedule: Schedule string (see parse_schedule)
        name: Optional friendly name
        repeat: How many times to run (None = forever, 1 = once)
        deliver: Where to deliver output ("origin", "local", "telegram", etc.)
        origin: Source info where job was created (for "origin" delivery)
        skill: Optional legacy single skill name to load before running the prompt
        skills: Optional ordered list of skills to load before running the prompt
        model: Optional per-job model override
        provider: Optional per-job provider override
        base_url: Optional per-job base URL override
        script: Optional path to a script whose stdout feeds the job. With
                ``no_agent=True`` the script IS the job — its stdout is
                delivered verbatim. Without ``no_agent``, its stdout is
                injected into the agent's prompt as context (data-collection /
                change-detection pattern). Paths resolve under
                ~/.elevate/scripts/; ``.sh`` / ``.bash`` files run via bash,
                anything else via Python.
        context_from: Optional job ID (or list of job IDs) whose most recent output
                      is injected into the prompt as context before each run.
                      Useful for chaining cron jobs: job A finds data, job B processes it.
        enabled_toolsets: Optional list of toolset names to restrict the agent to.
                          When set, only tools from these toolsets are loaded, reducing
                          token overhead. When omitted, all default tools are loaded.
                          Ignored when ``no_agent=True``.
        workdir: Optional absolute path.  When set, the job runs as if launched
                from that directory: AGENTS.md / CLAUDE.md / .cursorrules from
                that directory are injected into the system prompt, and the
                terminal/file/code_exec tools use it as their working directory
                (via TERMINAL_CWD).  When unset, the old behaviour is preserved
                (no context files injected, tools use the scheduler's cwd).
                With ``no_agent=True``, ``workdir`` is still applied as the
                script's cwd so relative paths inside the script behave
                predictably.
        profile: Optional Hermes profile name. When set, the job runs with
                that profile's ELEVATE_HOME so profile-specific config,
                credentials, scripts, skills, and memory paths resolve
                consistently. ``default`` selects the root profile; empty /
                None preserves the scheduler's existing behaviour.
        no_agent: When True, skip the agent entirely — run ``script`` on schedule
                and deliver its stdout directly. Empty stdout = silent (no
                delivery). Requires ``script`` to be set. Ideal for classic
                watchdogs and periodic alerts that don't need LLM reasoning.

    Returns:
        The created job dict
    """
    parsed_schedule = parse_schedule(schedule)

    # Normalize repeat: treat 0 or negative values as None (infinite)
    if repeat is not None and repeat <= 0:
        repeat = None

    # Auto-set repeat=1 for one-shot schedules if not specified
    if parsed_schedule["kind"] == "once" and repeat is None:
        repeat = 1

    # Default delivery to origin if available, otherwise local
    if deliver is None:
        deliver = "origin" if origin else "local"

    job_id = uuid.uuid4().hex[:12]
    now = _hermes_now().isoformat()

    normalized_skills = _normalize_skill_list(skill, skills)
    normalized_model = str(model).strip() if isinstance(model, str) else None
    normalized_provider = str(provider).strip() if isinstance(provider, str) else None
    normalized_base_url = str(base_url).strip().rstrip("/") if isinstance(base_url, str) else None
    normalized_model = normalized_model or None
    normalized_provider = normalized_provider or None
    normalized_base_url = normalized_base_url or None
    normalized_script = str(script).strip() if isinstance(script, str) else None
    normalized_script = normalized_script or None
    normalized_toolsets = [str(t).strip() for t in enabled_toolsets if str(t).strip()] if enabled_toolsets else None
    normalized_toolsets = normalized_toolsets or None
    normalized_workdir = _normalize_workdir(workdir)
    normalized_profile = _normalize_profile(profile)
    normalized_no_agent = bool(no_agent)
    normalized_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    try:
        normalized_max_session_seconds = int(max_session_seconds) if max_session_seconds not in (None, "") else None
    except (TypeError, ValueError):
        normalized_max_session_seconds = None
    if normalized_max_session_seconds is not None and normalized_max_session_seconds <= 0:
        normalized_max_session_seconds = None

    # Elevate /leads metadata normalization (agent picker, tier resolver
    # fallback, readiness gate, backfill iterator).
    normalized_agent = str(agent).strip() if isinstance(agent, str) else None
    normalized_agent = normalized_agent or None
    if normalized_agent:
        try:
            from elevate_cli.agent_hub import agent_lifecycle_defaults, agent_runtime_defaults

            runtime_defaults = agent_runtime_defaults(normalized_agent)
            lifecycle_defaults = agent_lifecycle_defaults(normalized_agent)
        except Exception:
            runtime_defaults = {}
            lifecycle_defaults = {}
        normalized_model = normalized_model or str(runtime_defaults.get("model") or "").strip() or None
        normalized_provider = normalized_provider or str(runtime_defaults.get("provider") or "").strip() or None
        normalized_base_url = (
            normalized_base_url
            or str(runtime_defaults.get("base_url") or "").strip().rstrip("/")
            or None
        )
        if normalized_workdir is None:
            normalized_workdir = _normalize_workdir(runtime_defaults.get("workdir"))
        if normalized_max_session_seconds is None:
            try:
                runtime_max_session = int(
                    lifecycle_defaults.get("max_session_seconds")
                    or runtime_defaults.get("max_session_seconds")
                    or 0
                )
            except (TypeError, ValueError):
                runtime_max_session = 0
            if runtime_max_session > 0:
                normalized_max_session_seconds = runtime_max_session
    normalized_tier = str(tier).strip().lower() if isinstance(tier, str) else None
    if normalized_tier:
        try:
            from elevate_cli.tier_resolver import VALID_TIERS as _VALID_TIERS
        except Exception:
            _VALID_TIERS = ("orchestrator", "draft", "utility", "send")
        if normalized_tier not in _VALID_TIERS:
            raise ValueError(f"unknown tier: {normalized_tier!r}")
    normalized_readiness = str(expected_readiness_version).strip() if isinstance(expected_readiness_version, str) else None
    normalized_readiness = normalized_readiness or None

    # no_agent jobs are meaningless without a script — the script IS the job.
    # Surface this as a clear ValueError at create time so bad configs never
    # reach the scheduler.
    if normalized_no_agent and not normalized_script:
        raise ValueError(
            "no_agent=True requires a script — with no agent and no script "
            "there is nothing for the job to run."
        )

    # Normalize context_from: accept str or list of str, store as list or None
    if isinstance(context_from, str):
        context_from = [context_from.strip()] if context_from.strip() else None
    elif isinstance(context_from, list):
        context_from = [str(j).strip() for j in context_from if str(j).strip()] or None
    else:
        context_from = None

    prompt_text = _coerce_job_text(prompt)
    label_source = (prompt_text or (normalized_skills[0] if normalized_skills else None) or (normalized_script if normalized_no_agent else None)) or "cron job"
    job = {
        "id": job_id,
        "name": name or label_source[:50].strip(),
        "prompt": prompt_text,
        "skills": normalized_skills,
        "skill": normalized_skills[0] if normalized_skills else None,
        "model": normalized_model,
        "provider": normalized_provider,
        "base_url": normalized_base_url,
        "script": normalized_script,
        "no_agent": normalized_no_agent,
        "context_from": context_from,
        "schedule": parsed_schedule,
        "schedule_display": parsed_schedule.get("display", schedule),
        "repeat": {
            "times": repeat,  # None = forever
            "completed": 0
        },
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": now,
        "next_run_at": compute_next_run(parsed_schedule),
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        # Delivery configuration
        "deliver": deliver,
        "origin": origin,  # Tracks where job was created for "origin" delivery
        "enabled_toolsets": normalized_toolsets,
        "workdir": normalized_workdir,
        "max_session_seconds": normalized_max_session_seconds,
        "profile": normalized_profile,
        "metadata": normalized_metadata,
        # /leads cron metadata
        "agent": normalized_agent,
        "tier": normalized_tier,
        "expected_readiness_version": normalized_readiness,
        "backfill_pending": bool(backfill_pending),
        # Backfill iterator state (Phase 4). Stays None until the lane's
        # first backfill run reports progress via update_backfill_state().
        # Shape: {day, total_estimate, queued_today, eligible_remaining, updated_at}
        "backfill_state": None if not backfill_pending else {
            "day": 0,
            "total_estimate": 0,
            "queued_today": 0,
            "eligible_remaining": None,
            "updated_at": None,
        },
    }

    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)

    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a job by ID."""
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id:
            return _normalize_job_record(job)
    return None


class AmbiguousJobReference(LookupError):
    """Raised when a job name matches more than one job."""

    def __init__(self, ref: str, matches: List[Dict[str, Any]]):
        self.ref = ref
        self.matches = matches
        ids = ", ".join(m["id"] for m in matches)
        super().__init__(
            f"Job name '{ref}' is ambiguous — matches {len(matches)} jobs: {ids}. "
            f"Use the job ID instead."
        )


def resolve_job_ref(ref: str) -> Optional[Dict[str, Any]]:
    """Resolve a job reference (ID or name) to a job record.

    - Exact ID match wins (works even if a different job's name equals this ID).
    - Otherwise, case-insensitive name match.
    - If a name matches more than one job, raises AmbiguousJobReference so the
      caller can surface the matching IDs rather than silently picking one.
    """
    if not ref:
        return None
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == ref:
            return _normalize_job_record(job)
    ref_lower = ref.lower()
    name_matches = [j for j in jobs if (j.get("name") or "").lower() == ref_lower]
    if not name_matches:
        return None
    if len(name_matches) > 1:
        raise AmbiguousJobReference(
            ref, [_normalize_job_record(j) for j in name_matches]
        )
    return _normalize_job_record(name_matches[0])


def list_jobs(include_disabled: bool = False) -> List[Dict[str, Any]]:
    """List all jobs, optionally including disabled ones."""
    jobs = [_normalize_job_record(j) for j in load_jobs()]
    if not include_disabled:
        jobs = [j for j in jobs if j.get("enabled", True)]
    return jobs


def update_job(job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a job by ID, refreshing derived schedule fields when needed."""
    jobs = load_jobs()
    for i, job in enumerate(jobs):
        if job["id"] != job_id:
            continue

        # Validate / normalize workdir if present in updates.  Empty string or
        # None both mean "clear the field" (restore old behaviour).
        if "workdir" in updates:
            _wd = updates["workdir"]
            if _wd in {None, "", False}:
                updates["workdir"] = None
            else:
                updates["workdir"] = _normalize_workdir(_wd)

        # Validate / normalize profile if present in updates.  Empty string or
        # None both mean "clear the field" (restore old behaviour).
        if "profile" in updates:
            _profile = updates["profile"]
            if _profile is None or _profile == "" or _profile is False:
                updates["profile"] = None
            else:
                updates["profile"] = _normalize_profile(_profile)

        updated = _apply_skill_fields({**job, **updates})
        schedule_changed = "schedule" in updates

        if "skills" in updates or "skill" in updates:
            normalized_skills = _normalize_skill_list(updated.get("skill"), updated.get("skills"))
            updated["skills"] = normalized_skills
            updated["skill"] = normalized_skills[0] if normalized_skills else None

        if schedule_changed:
            updated_schedule = updated["schedule"]
            # The API may pass schedule as a raw string (e.g. "every 10m")
            # instead of a pre-parsed dict.  Normalize it the same way
            # create_job() does so downstream code can call .get() safely.
            if isinstance(updated_schedule, str):
                updated_schedule = parse_schedule(updated_schedule)
                updated["schedule"] = updated_schedule
            updated["schedule_display"] = updates.get(
                "schedule_display",
                updated_schedule.get("display", updated.get("schedule_display")),
            )
            if updated.get("state") != "paused":
                updated["next_run_at"] = compute_next_run(updated_schedule)

        if updated.get("enabled", True) and updated.get("state") != "paused" and not updated.get("next_run_at"):
            updated["next_run_at"] = compute_next_run(updated["schedule"])

        jobs[i] = updated
        save_jobs(jobs)
        return _normalize_job_record(jobs[i])
    return None


def update_backfill_state(
    job_id: str,
    *,
    queued_today: Optional[int] = None,
    eligible_remaining: Optional[int] = None,
    total_estimate: Optional[int] = None,
    run_id: Optional[str] = None,
    checkpoint: bool = False,
) -> Optional[Dict[str, Any]]:
    """Lane skill reports per-run backfill progress.

    Every call persists IMMEDIATELY, so callers can (and should) report
    after each unit of work instead of only once at successful end-of-run.
    Historically the lane skill reported once after a run completed — a
    crash/timeout mid-run lost the whole run's progress and the iterator
    resumed from the previous run's counters.

    Crash-safe protocol: pass a stable ``run_id`` (e.g. the cron session id)
    and call with ``checkpoint=True`` after each chunk.  ``day`` bumps once
    per distinct run_id (first report wins; later reports from the same run
    only refresh the counters), so mid-run checkpoints never inflate the day
    counter and a final end-of-run report doesn't double-count.  If the run
    dies between checkpoints, the last persisted checkpoint is the resume
    point for the next run.

    Backward compatible: calls without ``run_id`` keep the legacy behavior
    (every call bumps ``day``), and state dicts written by older versions
    load unchanged — the new ``last_run_id`` / ``checkpoint`` keys are
    simply absent.
    """
    # Hold the jobs-file lock across the read-modify-write so concurrent
    # checkpoint posts / mark_job_run calls can't clobber each other.
    # (get_job/update_job do not themselves acquire the lock.)
    with _jobs_file_lock:
        job = get_job(job_id)
        if not job:
            return None
        if not job.get("backfill_pending"):
            return job
        state = dict(job.get("backfill_state") or {
            "day": 0,
            "total_estimate": 0,
            "queued_today": 0,
            "eligible_remaining": None,
            "updated_at": None,
        })
        same_run = bool(run_id) and state.get("last_run_id") == run_id
        if not same_run:
            state["day"] = int(state.get("day") or 0) + 1
        if run_id:
            state["last_run_id"] = str(run_id)
        # Flag mid-run snapshots so observers (dashboard, next run) can tell
        # "in-flight checkpoint" from "run finished cleanly".  A final
        # (non-checkpoint) report clears it.
        state["checkpoint"] = bool(checkpoint)
        if queued_today is not None:
            state["queued_today"] = int(queued_today)
        if eligible_remaining is not None:
            state["eligible_remaining"] = int(eligible_remaining)
        if total_estimate is not None:
            state["total_estimate"] = int(total_estimate)
        # NOTE: was `_elevate_now()` — an undefined name, so EVERY progress
        # report raised NameError and no backfill state ever persisted (the
        # root of the "progress only survives a clean run" audit finding).
        state["updated_at"] = _hermes_now().isoformat()
        updates: Dict[str, Any] = {"backfill_state": state}
        if state.get("eligible_remaining") == 0:
            updates["backfill_pending"] = False
        return update_job(job_id, updates)


def pause_job(job_id: str, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Pause a job without deleting it. Accepts a job ID or name."""
    job = resolve_job_ref(job_id)
    if not job:
        return None
    return update_job(
        job["id"],
        {
            "enabled": False,
            "state": "paused",
            "paused_at": _hermes_now().isoformat(),
            "paused_reason": reason,
        },
    )


def resume_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Resume a paused job and compute the next future run from now. Accepts a job ID or name."""
    job = resolve_job_ref(job_id)
    if not job:
        return None

    next_run_at = compute_next_run(job["schedule"])
    return update_job(
        job["id"],
        {
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "paused_reason": None,
            "next_run_at": next_run_at,
        },
    )


def trigger_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Schedule a job to run on the next scheduler tick. Accepts a job ID or name."""
    job = resolve_job_ref(job_id)
    if not job:
        return None
    return update_job(
        job["id"],
        {
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "paused_reason": None,
            "next_run_at": _hermes_now().isoformat(),
        },
    )


def remove_job(job_id: str) -> bool:
    """Remove a job by ID or name."""
    job = resolve_job_ref(job_id)
    if not job:
        return False
    canonical_id = job["id"]
    jobs = load_jobs()
    original_len = len(jobs)
    jobs = [j for j in jobs if j["id"] != canonical_id]
    if len(jobs) < original_len:
        save_jobs(jobs)
        # Clean up output directory to prevent orphaned dirs accumulating
        job_output_dir = OUTPUT_DIR / canonical_id
        if job_output_dir.exists():
            shutil.rmtree(job_output_dir)
        return True
    return False


# ── Backoff for recurring jobs stuck with no progress ────────────────────
# A run that ends in `waiting_human` (blocked on the realtor) or errors out is
# otherwise recorded as a normal run and re-fires on the next scheduled tick.
# So a watcher blocked on a single unresolved item (expired portal login,
# missing field) can reprocess it every 10 min, 24/7, spending a full model
# session each time for zero progress. We count consecutive stalled runs and,
# past a small grace, push the next run out exponentially (capped). The first
# run that makes progress resets the counter and restores normal cadence.
_STALL_BACKOFF_AFTER = 3        # allow this many quick retries before backing off
_STALL_BACKOFF_BASE_MIN = 30    # first backoff delay (minutes)
_STALL_BACKOFF_MAX_MIN = 360    # cap (6h)


def _looks_waiting_human(summary: Optional[str]) -> bool:
    """True if a cron run reported it is blocked on a human.

    Workers return a structured result whose ``status`` is ``waiting_human``
    (or ``needs_operator``) when they cannot proceed without the realtor. That
    text rides along in the run summary, so a substring check drives backoff
    without threading a new status field through the executor.
    """
    if not summary:
        return False
    s = summary.lower()
    return "waiting_human" in s or "needs_operator" in s


def mark_job_run(job_id: str, success: bool, error: Optional[str] = None,
                 delivery_error: Optional[str] = None,
                 summary: Optional[str] = None,
                 session_id: Optional[str] = None,
                 outcome: Optional[str] = None):
    """
    Mark a job as having been run.

    Updates last_run_at, last_status, increments completed count,
    computes next_run_at, and auto-deletes if repeat limit reached.

    ``delivery_error`` is tracked separately from the agent error — a job
    can succeed (agent produced output) but fail delivery (platform down).

    ``summary`` is the agent's final assistant message (truncated). Surfaced
    on the Cron page so the user can see WHAT happened, not just "ok".
    ``session_id`` is the cron_<jobid>_<ts> id the run executed under, so
    the UI can deep-link from job card → session transcript.
    """
    with _jobs_file_lock:
        jobs = load_jobs()
        for i, job in enumerate(jobs):
            if job["id"] == job_id:
                now = _hermes_now().isoformat()
                job["last_run_at"] = now
                job["last_status"] = "ok" if success else "error"
                job["last_error"] = error if not success else None
                # Track delivery failures separately — cleared on successful delivery
                job["last_delivery_error"] = delivery_error
                if summary is not None:
                    # Cap at 600 chars — anything longer belongs in the
                    # session transcript, not the job card. Strip control
                    # chars so the dashboard doesn't choke on stray ANSI.
                    _s = str(summary).strip()
                    if len(_s) > 600:
                        _s = _s[:597].rstrip() + "..."
                    job["last_summary"] = _s
                if session_id is not None:
                    job["last_session_id"] = str(session_id)
                
                # Increment completed count
                if job.get("repeat"):
                    job["repeat"]["completed"] = job["repeat"].get("completed", 0) + 1
                    
                    # Check if we've hit the repeat limit
                    times = job["repeat"].get("times")
                    completed = job["repeat"]["completed"]
                    if times is not None and times > 0 and completed >= times:
                        # Remove the job (limit reached)
                        jobs.pop(i)
                        save_jobs(jobs)
                        return
                
                # Compute next run
                job["next_run_at"] = compute_next_run(job["schedule"], now)

                # Track consecutive stalled runs (blocked on a human / errored)
                # and back the schedule off so a stuck watcher stops hammering
                # its tick. A progressing run resets the counter and cadence.
                # Prefer the explicit cron `outcome` marker (survives the
                # human-friendly prose delivery); fall back to the summary
                # heuristic when no marker was emitted (older/non-cron callers).
                cron_outcome = (outcome or "").strip().lower()
                if cron_outcome in ("waiting_human", "needs_operator", "error"):
                    stalled = True
                elif cron_outcome == "ok":
                    stalled = not success
                else:
                    stalled = (not success) or _looks_waiting_human(summary)
                if stalled:
                    job["stall_count"] = int(job.get("stall_count") or 0) + 1
                else:
                    job["stall_count"] = 0
                stall_count = int(job.get("stall_count") or 0)
                kind = job.get("schedule", {}).get("kind")
                if (
                    stalled
                    and stall_count >= _STALL_BACKOFF_AFTER
                    and kind in {"cron", "interval"}
                    and job.get("next_run_at")
                ):
                    delay_min = min(
                        _STALL_BACKOFF_MAX_MIN,
                        _STALL_BACKOFF_BASE_MIN * (2 ** (stall_count - _STALL_BACKOFF_AFTER)),
                    )
                    backoff_at = (_hermes_now() + timedelta(minutes=delay_min)).isoformat()
                    # Only ever push the next run further out, never pull it in.
                    if backoff_at > job["next_run_at"]:
                        job["next_run_at"] = backoff_at
                        job["backoff_until"] = backoff_at
                        job["backoff_minutes"] = delay_min
                        logger.info(
                            "Job '%s' stalled %d× (waiting_human/error) — backing "
                            "off %d min to %s instead of re-firing on schedule.",
                            job.get("name", job["id"]), stall_count, delay_min, backoff_at,
                        )
                else:
                    job.pop("backoff_until", None)
                    job.pop("backoff_minutes", None)

                # If no next run, decide whether this is terminal completion
                # (one-shot) or a transient failure (recurring schedule couldn't
                # compute — e.g. 'croniter' missing from the runtime env).
                # Recurring jobs must NEVER be silently disabled: that turns a
                # missing runtime dep into "job completed" and the user's
                # schedule quietly goes off. See issue #16265.
                if job["next_run_at"] is None:
                    kind = job.get("schedule", {}).get("kind")
                    if kind in {"cron", "interval"}:
                        job["state"] = "error"
                        if not job.get("last_error"):
                            job["last_error"] = (
                                "Failed to compute next run for recurring "
                                "schedule (is the 'croniter' package "
                                "installed in the gateway's Python env?)"
                            )
                        logger.error(
                            "Job '%s' (%s) could not compute next_run_at; "
                            "leaving enabled and marking state=error so the "
                            "job is not silently disabled.",
                            job.get("name", job["id"]),
                            kind,
                        )
                    else:
                        job["enabled"] = False
                        job["state"] = "completed"
                elif job.get("state") != "paused":
                    job["state"] = "scheduled"

                save_jobs(jobs)
                return

        logger.warning("mark_job_run: job_id %s not found, skipping save", job_id)


def advance_next_run(job_id: str) -> bool:
    """Preemptively advance next_run_at for a recurring job before execution.

    Call this BEFORE run_job() so that if the process crashes mid-execution,
    the job won't re-fire on the next gateway restart.  This converts the
    scheduler from at-least-once to at-most-once for recurring jobs — missing
    one run is far better than firing dozens of times in a crash loop.

    One-shot jobs are left unchanged so they can still retry on restart.

    Returns True if next_run_at was advanced, False otherwise.
    """
    with _jobs_file_lock:
        jobs = load_jobs()
        for job in jobs:
            if job["id"] == job_id:
                kind = job.get("schedule", {}).get("kind")
                if kind not in {"cron", "interval"}:
                    return False
                now = _hermes_now().isoformat()
                new_next = compute_next_run(job["schedule"], now)
                if new_next and new_next != job.get("next_run_at"):
                    job["next_run_at"] = new_next
                    save_jobs(jobs)
                    return True
                return False
        return False


def get_due_jobs() -> List[Dict[str, Any]]:
    """Get all jobs that are due to run now.

    For recurring jobs (cron/interval), if the scheduled time is stale
    (more than one period in the past, e.g. because the gateway was down),
    the job is fast-forwarded to the next future run instead of firing
    immediately.  This prevents a burst of missed jobs on gateway restart.
    """
    with _jobs_file_lock:
        return _get_due_jobs_locked()


def _get_due_jobs_locked() -> List[Dict[str, Any]]:
    """Inner implementation of get_due_jobs(); must be called with _jobs_file_lock held."""
    now = _hermes_now()
    raw_jobs = load_jobs()
    jobs = [_apply_skill_fields(j) for j in copy.deepcopy(raw_jobs)]
    due = []
    needs_save = False

    for job in jobs:
        if not job.get("enabled", True):
            continue

        next_run = job.get("next_run_at")
        if not next_run:
            schedule = job.get("schedule", {})
            kind = schedule.get("kind")

            # One-shot jobs use a small grace window via the dedicated helper.
            recovered_next = _recoverable_oneshot_run_at(
                schedule,
                now,
                last_run_at=job.get("last_run_at"),
            )
            recovery_kind = "one-shot" if recovered_next else None

            # Recurring jobs reach here only when something — typically a
            # direct jobs.json edit that bypassed add_job() — left
            # next_run_at unset.  Without this branch, such jobs are
            # silently skipped forever; recompute next_run_at from the
            # schedule so they pick up at their next scheduled tick.
            if not recovered_next and kind in {"cron", "interval"}:
                recovered_next = compute_next_run(schedule, now.isoformat())
                if recovered_next:
                    recovery_kind = kind

            if not recovered_next:
                continue

            job["next_run_at"] = recovered_next
            next_run = recovered_next
            logger.info(
                "Job '%s' had no next_run_at; recovering %s run at %s",
                job.get("name", job["id"]),
                recovery_kind,
                recovered_next,
            )
            for rj in raw_jobs:
                if rj["id"] == job["id"]:
                    rj["next_run_at"] = recovered_next
                    needs_save = True
                    break

        next_run_dt = _ensure_aware(datetime.fromisoformat(next_run))
        if next_run_dt <= now:
            schedule = job.get("schedule", {})
            kind = schedule.get("kind")

            # For recurring jobs, check if the scheduled time is stale
            # (gateway was down and missed the window). Fast-forward to
            # the next future occurrence instead of firing a stale run.
            grace = _compute_grace_seconds(schedule)
            if kind in {"cron", "interval"} and (now - next_run_dt).total_seconds() > grace:
                # Job is past its catch-up grace window — this is a stale missed run.
                # Grace scales with schedule period: daily=2h, hourly=30m, 10min=5m.
                new_next = compute_next_run(schedule, now.isoformat())
                if new_next:
                    logger.info(
                        "Job '%s' missed its scheduled time (%s, grace=%ds). "
                        "Fast-forwarding to next run: %s",
                        job.get("name", job["id"]),
                        next_run,
                        grace,
                        new_next,
                    )
                    # Update the job in storage
                    for rj in raw_jobs:
                        if rj["id"] == job["id"]:
                            rj["next_run_at"] = new_next
                            needs_save = True
                            break
                    continue  # Skip this run

            due.append(job)

    if needs_save:
        save_jobs(raw_jobs)

    return due


def save_job_output(job_id: str, output: str):
    """Save job output to file."""
    ensure_dirs()
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)
    _secure_dir(job_output_dir)
    
    timestamp = _hermes_now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = job_output_dir / f"{timestamp}.md"
    
    fd, tmp_path = tempfile.mkstemp(dir=str(job_output_dir), suffix='.tmp', prefix='.output_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno())
        atomic_replace(tmp_path, output_file)
        _secure_file(output_file)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    
    return output_file


# =============================================================================
# Skill reference rewriting (curator integration)
# =============================================================================

def rewrite_skill_refs(
    consolidated: Optional[Dict[str, str]] = None,
    pruned: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Rewrite cron job skill references after a curator consolidation pass.

    When the curator consolidates a skill X into umbrella Y (or archives X
    as pruned), any cron job that lists ``X`` in its ``skills`` field will
    fail to load ``X`` at run time — the scheduler logs a warning and
    skips the skill, so the job runs without the instructions it was
    scheduled to follow. See cron/scheduler.py where ``skill_view`` is
    called per skill name.

    This function repairs cron jobs in-place:

    - A skill listed in ``consolidated`` is replaced with its umbrella
      target (the ``into`` value). If the umbrella is already in the
      job's skill list, the stale name is dropped without duplication.
    - A skill listed in ``pruned`` is dropped outright — there is no
      forwarding target.
    - Ordering and other skills in the list are preserved.
    - The legacy ``skill`` field is realigned via ``_apply_skill_fields``.

    Args:
        consolidated: mapping of ``old_skill_name -> umbrella_skill_name``.
        pruned: list of skill names that were archived with no forwarding
            target.

    Returns a report dict::

        {
            "rewrites": [
                {
                    "job_id": ...,
                    "job_name": ...,
                    "before": [...],
                    "after": [...],
                    "mapped": {"old": "new", ...},
                    "dropped": ["old", ...],
                },
                ...
            ],
            "jobs_updated": N,
            "jobs_scanned": M,
        }

    Best-effort: exceptions from loading/saving propagate to the caller so
    tests can assert behaviour; the curator invocation site wraps this
    call in a try/except so a failure here never breaks the curator.
    """
    consolidated = dict(consolidated or {})
    pruned_set = set(pruned or [])
    # A skill listed in both wins as "consolidated" — it has a target,
    # which is the more useful of the two outcomes.
    pruned_set -= set(consolidated.keys())

    if not consolidated and not pruned_set:
        return {"rewrites": [], "jobs_updated": 0, "jobs_scanned": 0}

    with _jobs_file_lock:
        jobs = load_jobs()
        rewrites: List[Dict[str, Any]] = []
        changed = False

        for job in jobs:
            skills_before = _normalize_skill_list(job.get("skill"), job.get("skills"))
            if not skills_before:
                continue

            mapped: Dict[str, str] = {}
            dropped: List[str] = []
            new_skills: List[str] = []

            for name in skills_before:
                if name in consolidated:
                    target = consolidated[name]
                    mapped[name] = target
                    if target and target not in new_skills:
                        new_skills.append(target)
                elif name in pruned_set:
                    dropped.append(name)
                elif name not in new_skills:
                    new_skills.append(name)

            if not mapped and not dropped:
                continue

            job["skills"] = new_skills
            job["skill"] = new_skills[0] if new_skills else None
            changed = True

            rewrites.append({
                "job_id": job.get("id"),
                "job_name": job.get("name") or job.get("id"),
                "before": list(skills_before),
                "after": list(new_skills),
                "mapped": mapped,
                "dropped": dropped,
            })

        if changed:
            save_jobs(jobs)
            logger.info(
                "Curator rewrote skill references in %d cron job(s)", len(rewrites)
            )

        return {
            "rewrites": rewrites,
            "jobs_updated": len(rewrites),
            "jobs_scanned": len(jobs),
        }
