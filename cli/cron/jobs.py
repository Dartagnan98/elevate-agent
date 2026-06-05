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
        "schedule": "0 8,15 * * *",
        "goal": (
            "Each run: check new/changed leads since the last run; surface the hot ones "
            "with a one-line why; list overdue follow-ups and today's showings; draft "
            "(never send) the next-touch for anyone gone quiet. End with one tight summary; "
            "say 'all quiet' if nothing changed."
        ),
        "experiment": {
            "every_n_runs": 7, "metric": "next_touch_reply_rate", "metric_type": "qualitative",
            "direction": "higher", "window": "7d",
            "measurement": "Self-score 1-10 the quality/likely-conversion of the next-touch drafts vs the prior cycle, with justification, until a real reply-rate metric is wired.",
            "approval_required": False,
        },
    },
    "admin": {
        "name": "Admin Heartbeat",
        "schedule": "30 7 * * *",
        "goal": (
            "Each run: scan the calendar and tasks; flag deadlines, conflicts, and anything "
            "needing the realtor's decision; reconcile today's agenda. End with one tight "
            "summary; say 'all quiet' if nothing needs attention."
        ),
        "experiment": {
            "every_n_runs": 7, "metric": "tasks_slipped", "metric_type": "qualitative",
            "direction": "lower", "window": "7d",
            "measurement": "Self-score 1-10 how well the agenda/flagging kept anything from slipping vs the prior cycle, with justification, until a real slipped-task metric is wired.",
            "approval_required": False,
        },
    },
}


def _seed_surface_heartbeat_workspace(
    surface: str, spec: Dict[str, Any], *, enabled: bool = True
) -> Path:
    """Create accounts/<key>/heartbeats/<surface>/{config.json, learnings.md, history/,
    experiments/history/} from defaults if absent. Returns the workspace Path.

    ``enabled`` only governs a BRAND-NEW config.json — an existing config.json is
    never rewritten, so a surface the realtor has already turned on stays on.
    """
    from elevate_constants import get_account_data_dir
    ws = get_account_data_dir() / "heartbeats" / surface
    (ws / "history").mkdir(parents=True, exist_ok=True)
    (ws / "experiments" / "history").mkdir(parents=True, exist_ok=True)
    cfg = ws / "config.json"
    if not cfg.exists():
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
        cfg.write_text(json.dumps({
            "surface": surface, "goal": spec["goal"], "cadence": spec["schedule"],
            "enabled": bool(enabled), "experiment": spec["experiment"],
            "cycles": [_seed_cycle],
            "created_by": "system", "created_at": _hermes_now().date().isoformat(),
        }, indent=2))
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
# at runtime via create_surface() and persisted to the account registry
# accounts/<key>/heartbeats/surfaces.json — Elevate's analog of cortextOS
# enabled-agents.json. ensure_surface() seeds ANY surface (built-in or custom) the
# same way: workspace scaffold + opt-in cron job. SURFACE_TEMPLATE is the default
# spec a new surface is filled from (cortextOS copyTemplateFiles equivalent).
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


def _surfaces_registry_path() -> Path:
    from elevate_constants import get_account_data_dir
    return get_account_data_dir() / "heartbeats" / "surfaces.json"


def _write_surface_registry(reg: Dict[str, Dict[str, Any]]) -> None:
    path = _surfaces_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"surfaces": reg}, indent=2))
    tmp.replace(path)


def load_surface_registry() -> Dict[str, Dict[str, Any]]:
    """Return {surface: spec} for every registered surface — built-ins always present,
    custom surfaces preserved. Seeds/repairs the on-disk registry with the built-ins so
    a fresh account still gets Leads + Admin while custom surfaces persist across runs.
    """
    path = _surfaces_registry_path()
    reg: Dict[str, Any] = {}
    if path.exists():
        try:
            reg = (json.loads(path.read_text()) or {}).get("surfaces") or {}
        except Exception:
            reg = {}
    changed = not path.exists()
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
                    reg[surface] = {**spec, "builtin": True, "created_by": "system"}
                    changed = True
        else:
            for surface in missing:  # offline fallback → bundled built-ins
                reg[surface] = {
                    **SURFACE_HEARTBEAT_DEFAULTS[surface],
                    "builtin": True,
                    "created_by": "system",
                }
                changed = True
    if changed:
        _write_surface_registry(reg)
    return reg


def register_surface(surface: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a surface spec to the account registry (add or replace)."""
    reg = load_surface_registry()
    reg[surface] = spec
    _write_surface_registry(reg)
    return spec


def ensure_surface(surface: str, spec: Dict[str, Any], *, enabled: bool = False) -> Dict[str, Any]:
    """Seed ONE surface (built-in or custom): workspace scaffold + opt-in cron job.

    Idempotent — a job already present (matched by name) is left EXACTLY as-is (its
    enabled/paused state, schedule, history untouched); only the workspace dirs are
    repaired. Brand-new seeds default OFF (opt-in) unless ``enabled`` is set. Returns
    the job dict.
    """
    name = spec.get("name") or f"{surface.capitalize()} Heartbeat"
    existing = next(
        (j for j in load_jobs() if (j.get("name") or "").strip().lower() == name.lower()),
        None,
    )
    if existing:
        _seed_surface_heartbeat_workspace(
            surface, spec, enabled=bool(existing.get("enabled", False))
        )
        return existing
    ws = _seed_surface_heartbeat_workspace(surface, spec, enabled=enabled)
    prompt = (
        f"You are the {surface.upper()} surface-heartbeat. Surface: {surface}. "
        f"Workspace: {ws}. Run your loop per the surface-heartbeat skill: read config.json "
        f"+ learnings.md, do the {surface} work, log to history/, distill learnings, and run "
        f"the experiment loop when due. Drafts only — never act on the realtor's behalf."
    )
    source = "system" if spec.get("created_by", "system") == "system" else "user"
    job = create_job(
        prompt=prompt, schedule=spec["schedule"], name=name,
        skill=SURFACE_HEARTBEAT_SKILL, deliver="local",
        origin={"type": "surface-heartbeat", "surface": surface, "source": source},
        workdir=str(ws),
    )
    if not enabled:
        # create_job() returns an enabled+scheduled job; flip it off through the
        # canonical disable path (enabled=False / state="paused" / cleared next_run).
        paused = pause_job(job["id"], reason="surface heartbeat is opt-in (seeded off)")
        return paused or job
    return job


def create_surface(
    surface: str, spec: Optional[Dict[str, Any]] = None, *, created_by: str = "user"
) -> Dict[str, Any]:
    """Create a NEW custom surface from SURFACE_TEMPLATE + caller overrides, persist it
    to the registry, and seed it (opt-in/off). Mirrors cortextOS add-agent +
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
        "builtin": False,
        "created_by": created_by,
    }
    register_surface(key, merged)
    job = ensure_surface(key, merged, enabled=False)
    return {"surface": key, "spec": merged, "job": job}


def ensure_surface_heartbeats() -> List[Dict[str, Any]]:
    """Idempotently seed every REGISTERED surface heartbeat (workspace + cron job) for
    the active account — OFF by default (opt-in). Built-ins (Leads, Admin) come from
    the registry seed; custom surfaces created via create_surface() are seeded here too.

    Surface heartbeats run agent passes on the realtor's box, so a fresh install must
    not auto-fire them: new seeds are DISABLED (config.json ``enabled: false`` + cron
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


# ─── Day / night mode (port of cortextOS detectDayNightMode) ──────────────────
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
    honors config.timezone when zoneinfo resolves it. Faithful port of cortextOS
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
# only proposes, for dashboard approval). Faithful port of cortextOS theta-wave.
THETA_WAVE_SKILL = "real-estate/theta-wave"
THETA_WAVE_NAME = "Theta Wave"
THETA_WAVE_SCHEDULE = "0 2 * * *"


def _seed_theta_wave_workspace(*, enabled: bool = False) -> Path:
    """Scaffold accounts/<key>/system-review/{config.json, learnings.md, history/,
    experiments/history/, reviews/}. Never rewrites an existing config.json."""
    from elevate_constants import get_account_data_dir
    ws = get_account_data_dir() / "system-review"
    (ws / "history").mkdir(parents=True, exist_ok=True)
    (ws / "experiments" / "history").mkdir(parents=True, exist_ok=True)
    (ws / "reviews").mkdir(parents=True, exist_ok=True)
    cfg = ws / "config.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({
            "metric": "system_effectiveness",
            "metric_type": "qualitative_compound",
            "direction": "higher",
            "schedule": THETA_WAVE_SCHEDULE,
            "enabled": bool(enabled),
            "auto_create_agent_cycles": False,
            "auto_modify_agent_cycles": False,
            "approval_required": True,
            "created_by": "system",
            "created_at": _hermes_now().date().isoformat(),
        }, indent=2))
    learn = ws / "learnings.md"
    if not learn.exists():
        learn.write_text(
            "# Theta Wave — Fleet Learnings\n\n_Durable insight about which surfaces improve "
            "vs stall and why. Read every review; keep it tight._\n\n(none yet)\n"
        )
    return ws


def ensure_theta_wave() -> Dict[str, Any]:
    """Idempotently seed the Theta Wave system-review cron (workspace + job) for the
    active account — OFF by default (opt-in), like the surfaces it reviews. An existing
    job (matched by name) is left exactly as-is."""
    existing = next(
        (j for j in load_jobs() if (j.get("name") or "").strip().lower() == THETA_WAVE_NAME.lower()),
        None,
    )
    if existing:
        _seed_theta_wave_workspace(enabled=bool(existing.get("enabled", False)))
        return existing
    ws = _seed_theta_wave_workspace(enabled=False)
    prompt = (
        f"You are Theta Wave, the fleet self-improvement reviewer. Workspace: {ws}. The surface "
        f"fleet is in the sibling dir ../heartbeats/. Run your loop per the theta-wave skill: scan "
        f"every surface, classify each (Stale/Converged/Successful/Underperforming), and create/"
        f"modify/remove cycles via the cycle endpoints — gated by auto_create_agent_cycles / "
        f"auto_modify_agent_cycles (else propose for dashboard approval). You are the only actor "
        f"that authors cycles. Change cycles, never realtor data."
    )
    job = create_job(
        prompt=prompt, schedule=THETA_WAVE_SCHEDULE, name=THETA_WAVE_NAME,
        skill=THETA_WAVE_SKILL, deliver="local",
        origin={"type": "system-review", "source": "system"},
        workdir=str(ws),
    )
    paused = pause_job(job["id"], reason="theta-wave is opt-in (seeded off)")
    return paused or job


def ensure_system_jobs() -> List[Dict[str, Any]]:
    """Ensure repo-backed system cron jobs exist for the active Elevate home."""
    return [
        ensure_admin_calendar_sync_job(),
        ensure_operational_maintenance_job(),
        ensure_operational_freshness_job(),
        *ensure_surface_heartbeats(),
        *ensure_surface_automations(),
        ensure_theta_wave(),
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

    # Elevate /leads metadata normalization (agent picker, tier resolver
    # fallback, readiness gate, backfill iterator).
    normalized_agent = str(agent).strip() if isinstance(agent, str) else None
    normalized_agent = normalized_agent or None
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
        "profile": normalized_profile,
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
) -> Optional[Dict[str, Any]]:
    """Lane skill reports per-run backfill progress."""
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
    state["day"] = int(state.get("day") or 0) + 1
    if queued_today is not None:
        state["queued_today"] = int(queued_today)
    if eligible_remaining is not None:
        state["eligible_remaining"] = int(eligible_remaining)
    if total_estimate is not None:
        state["total_estimate"] = int(total_estimate)
    state["updated_at"] = _elevate_now().isoformat()
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
                 session_id: Optional[str] = None):
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
