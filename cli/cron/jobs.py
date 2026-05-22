"""
Cron job storage and management.

Jobs are stored in ~/.elevate/cron/jobs.json
Output is saved to ~/.elevate/cron/output/{job_id}/{timestamp}.md
"""

import copy
import json
import logging
import tempfile
import threading
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from elevate_constants import get_elevate_home
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

from elevate_time import now as _elevate_now

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False

# =============================================================================
# Configuration
# =============================================================================

_INITIAL_ELEVATE_DIR = get_elevate_home().resolve()
ELEVATE_DIR = _INITIAL_ELEVATE_DIR
CRON_DIR = ELEVATE_DIR / "cron"
JOBS_FILE = CRON_DIR / "jobs.json"

# In-process lock protecting load_jobs→modify→save_jobs cycles.
# Required when tick() runs jobs in parallel threads — without this,
# concurrent mark_job_run / advance_next_run calls can clobber each other.
_jobs_file_lock = threading.Lock()
OUTPUT_DIR = CRON_DIR / "output"
ONESHOT_GRACE_SECONDS = 120

WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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


def _current_elevate_dir() -> Path:
    """Resolve Elevate home at call time while preserving test monkeypatches."""
    configured = Path(ELEVATE_DIR).expanduser().resolve()
    if configured != _INITIAL_ELEVATE_DIR:
        return configured
    return get_elevate_home().resolve()


def _cron_dir() -> Path:
    configured = Path(CRON_DIR).expanduser()
    default = _INITIAL_ELEVATE_DIR / "cron"
    if configured.resolve() != default:
        return configured.resolve()
    return _current_elevate_dir() / "cron"


def _jobs_file() -> Path:
    configured = Path(JOBS_FILE).expanduser()
    default = _INITIAL_ELEVATE_DIR / "cron" / "jobs.json"
    if configured.resolve() != default:
        return configured.resolve()
    return _cron_dir() / "jobs.json"


def _output_dir() -> Path:
    configured = Path(OUTPUT_DIR).expanduser()
    default = _INITIAL_ELEVATE_DIR / "cron" / "output"
    if configured.resolve() != default:
        return configured.resolve()
    return _cron_dir() / "output"


def ensure_dirs():
    """Ensure cron directories exist with secure permissions."""
    cron_dir = _cron_dir()
    output_dir = _output_dir()
    jobs_dir = _jobs_file().parent
    cron_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    _secure_dir(cron_dir)
    _secure_dir(jobs_dir)
    _secure_dir(output_dir)


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
        "2w" → 20160
    """
    s = s.strip().lower()
    match = re.match(
        r'^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks)$',
        s,
    )
    if not match:
        raise ValueError(f"Invalid duration: '{s}'. Use format like '30m', '2h', '1d', or '2w'")
    
    value = int(match.group(1))
    unit = match.group(2)[0]  # First char: m, h, d, or w
    
    multipliers = {'m': 1, 'h': 60, 'd': 1440, 'w': 10080}
    return value * multipliers[unit]


def _format_interval_display(minutes: int) -> str:
    for unit_minutes, suffix in ((10080, "w"), (1440, "d"), (60, "h")):
        if minutes % unit_minutes == 0:
            return f"{minutes // unit_minutes}{suffix}"
    return f"{minutes}m"


def _normalize_anchor_time(value: str) -> str:
    match = re.match(r'^(\d{1,2}):(\d{2})$', value.strip())
    if not match:
        raise ValueError(f"Invalid interval time '{value}'. Use HH:MM, for example 09:00")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid interval time '{value}'. Use HH:MM, for example 09:00")
    return f"{hour:02d}:{minute:02d}"


def _next_anchor_start(weekday: Optional[int], time_label: str) -> str:
    now = _elevate_now()
    hour, minute = [int(part) for part in time_label.split(":", 1)]
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        candidate += timedelta(days=(weekday - now.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7 if weekday is not None else 1)
    return candidate.isoformat()


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
        "every 2w on Tuesday at 09:00" → every two weeks, anchored
        "0 9 * * *"        → cron expression
        "2026-02-03T14:00" → once at timestamp
    """
    schedule = schedule.strip()
    original = schedule
    schedule_lower = schedule.lower()
    
    # "every X" pattern → recurring interval
    if schedule_lower.startswith("every "):
        interval_text = schedule[6:].strip()
        match = re.match(
            r'^(?P<duration>\d+\s*(?:m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks))'
            r'(?:\s+on\s+(?P<weekday>mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:r|rs|rsday|rday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?))?'
            r'(?:\s+at\s+(?P<time>\d{1,2}:\d{2}))?$',
            interval_text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError(
                f"Invalid interval schedule '{original}'. Use 'every 30m', "
                f"'every 2h', or 'every 2w on Monday at 09:00'"
            )
        duration_str = match.group("duration")
        minutes = parse_duration(duration_str)
        parsed: Dict[str, Any] = {
            "kind": "interval",
            "minutes": minutes,
            "display": f"every {minutes}m"
        }
        weekday_text = match.group("weekday")
        time_text = match.group("time")
        if weekday_text or time_text:
            anchor_time = _normalize_anchor_time(time_text or "09:00")
            anchor_weekday = WEEKDAY_ALIASES[weekday_text.lower()] if weekday_text else None
            parsed["anchor_time"] = anchor_time
            parsed["start_at"] = _next_anchor_start(anchor_weekday, anchor_time)
            parsed["display"] = f"every {_format_interval_display(minutes)}"
            if anchor_weekday is not None:
                parsed["anchor_weekday"] = anchor_weekday
                parsed["display"] += f" on {WEEKDAY_LABELS[anchor_weekday]}"
            parsed["display"] += f" at {anchor_time}"
        return parsed
    
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
        run_at = _elevate_now() + timedelta(minutes=minutes)
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
    """Return a timezone-aware datetime in Elevate configured timezone.

    Backward compatibility:
    - Older stored timestamps may be naive.
    - Naive values are interpreted as *system-local wall time* (the timezone
      `datetime.now()` used when they were created), then converted to the
      configured Elevate timezone.

    This preserves relative ordering for legacy naive timestamps across
    timezone changes and avoids false not-due results.
    """
    target_tz = _elevate_now().tzinfo
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
            now = _elevate_now()
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
    now = _elevate_now()

    if schedule["kind"] == "once":
        return _recoverable_oneshot_run_at(schedule, now, last_run_at=last_run_at)

    elif schedule["kind"] == "interval":
        minutes = schedule["minutes"]
        if last_run_at:
            # Next run is last_run + interval
            last = _ensure_aware(datetime.fromisoformat(last_run_at))
            next_run = last + timedelta(minutes=minutes)
        elif schedule.get("start_at"):
            next_run = _ensure_aware(datetime.fromisoformat(schedule["start_at"]))
            while next_run <= now:
                next_run += timedelta(minutes=minutes)
        else:
            # First run is now + interval
            next_run = now + timedelta(minutes=minutes)
        return next_run.isoformat()

    elif schedule["kind"] == "cron":
        if not HAS_CRONITER:
            return None
        cron = croniter(schedule["expr"], now)
        next_run = cron.get_next(datetime)
        return next_run.isoformat()

    return None


# =============================================================================
# Job CRUD Operations
# =============================================================================

def load_jobs() -> List[Dict[str, Any]]:
    """Load all jobs from storage."""
    ensure_dirs()
    jobs_file = _jobs_file()
    if not jobs_file.exists():
        return []
    
    try:
        with open(jobs_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("jobs", [])
    except json.JSONDecodeError:
        # Retry with strict=False to handle bare control chars in string values
        try:
            with open(jobs_file, 'r', encoding='utf-8') as f:
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
    jobs_file = _jobs_file()
    fd, tmp_path = tempfile.mkstemp(dir=str(jobs_file.parent), suffix='.tmp', prefix='.jobs_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({"jobs": jobs, "updated_at": _elevate_now().isoformat()}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, jobs_file)
        _secure_file(jobs_file)
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


def create_job(
    prompt: str,
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
    enabled_toolsets: Optional[List[str]] = None,
    workdir: Optional[str] = None,
    agent: Optional[str] = None,
    tier: Optional[str] = None,
    expected_readiness_version: Optional[str] = None,
    backfill_pending: bool = False,
) -> Dict[str, Any]:
    """
    Create a new cron job.

    Args:
        prompt: The prompt to run (must be self-contained, or a task instruction when skill is set)
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
        script: Optional path to a Python script whose stdout is injected into the
                prompt each run.  The script runs before the agent turn, and its output
                is prepended as context.  Useful for data collection / change detection.
        enabled_toolsets: Optional list of toolset names to restrict the agent to.
                          When set, only tools from these toolsets are loaded, reducing
                          token overhead. When omitted, all default tools are loaded.
        workdir: Optional absolute path.  When set, the job runs as if launched
                from that directory: AGENTS.md / CLAUDE.md / .cursorrules from
                that directory are injected into the system prompt, and the
                terminal/file/code_exec tools use it as their working directory
                (via TERMINAL_CWD).  When unset, the old behaviour is preserved
                (no context files injected, tools use the scheduler's cwd).

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
    now = _elevate_now().isoformat()

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

    label_source = (prompt or (normalized_skills[0] if normalized_skills else None)) or "cron job"
    job = {
        "id": job_id,
        "name": name or label_source[:50].strip(),
        "prompt": prompt,
        "skills": normalized_skills,
        "skill": normalized_skills[0] if normalized_skills else None,
        "model": normalized_model,
        "provider": normalized_provider,
        "base_url": normalized_base_url,
        "script": normalized_script,
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
        # /leads cron metadata: agent picker, tier resolver fallback, readiness gate, backfill iterator
        "agent": normalized_agent,
        "tier": normalized_tier,
        "expected_readiness_version": normalized_readiness,
        "backfill_pending": bool(backfill_pending),
        # Backfill iterator state (Phase 4). Stays None until the lane's first
        # backfill run reports progress via update_backfill_state().
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
            return _apply_skill_fields(job)
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


def list_jobs(include_disabled: bool = False) -> List[Dict[str, Any]]:
    """List all jobs, optionally including disabled ones."""
    jobs = [_apply_skill_fields(j) for j in load_jobs()]
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
            if _wd in (None, "", False):
                updates["workdir"] = None
            else:
                updates["workdir"] = _normalize_workdir(_wd)

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
        return _apply_skill_fields(jobs[i])
    return None


def update_backfill_state(
    job_id: str,
    *,
    queued_today: Optional[int] = None,
    eligible_remaining: Optional[int] = None,
    total_estimate: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Lane skill reports per-run backfill progress.

    Increments ``day`` by 1, records the count it queued this run, and the
    remaining eligible profile count it observed. When ``eligible_remaining``
    hits 0, the job is marked ``backfill_pending=False`` and subsequent runs
    use the incremental window instead of the backfill iterator.

    Returns the refreshed job dict, or None if the job no longer exists.
    """
    job = get_job(job_id)
    if not job:
        return None
    if not job.get("backfill_pending"):
        # Iterator is done — accept the report but don't mutate pending state.
        return job

    state = dict(job.get("backfill_state") or {
        "day": 0, "total_estimate": 0, "queued_today": 0,
        "eligible_remaining": None, "updated_at": None,
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
    """Pause a job without deleting it."""
    return update_job(
        job_id,
        {
            "enabled": False,
            "state": "paused",
            "paused_at": _elevate_now().isoformat(),
            "paused_reason": reason,
        },
    )


def resume_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Resume a paused job and compute the next future run from now."""
    job = get_job(job_id)
    if not job:
        return None

    next_run_at = compute_next_run(job["schedule"])
    return update_job(
        job_id,
        {
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "paused_reason": None,
            "next_run_at": next_run_at,
        },
    )


def trigger_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Schedule a job to run on the next scheduler tick."""
    job = get_job(job_id)
    if not job:
        return None
    return update_job(
        job_id,
        {
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "paused_reason": None,
            "next_run_at": _elevate_now().isoformat(),
        },
    )


def remove_job(job_id: str) -> bool:
    """Remove a job by ID."""
    jobs = load_jobs()
    original_len = len(jobs)
    jobs = [j for j in jobs if j["id"] != job_id]
    if len(jobs) < original_len:
        save_jobs(jobs)
        return True
    return False


def mark_job_run(job_id: str, success: bool, error: Optional[str] = None,
                 delivery_error: Optional[str] = None):
    """
    Mark a job as having been run.
    
    Updates last_run_at, last_status, increments completed count,
    computes next_run_at, and auto-deletes if repeat limit reached.

    ``delivery_error`` is tracked separately from the agent error — a job
    can succeed (agent produced output) but fail delivery (platform down).
    """
    with _jobs_file_lock:
        jobs = load_jobs()
        for i, job in enumerate(jobs):
            if job["id"] == job_id:
                now = _elevate_now().isoformat()
                job["last_run_at"] = now
                job["last_status"] = "ok" if success else "error"
                job["last_error"] = error if not success else None
                # Track delivery failures separately — cleared on successful delivery
                job["last_delivery_error"] = delivery_error
                
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

                # If no next run (one-shot completed), disable
                if job["next_run_at"] is None:
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
                if kind not in ("cron", "interval"):
                    return False
                now = _elevate_now().isoformat()
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
    now = _elevate_now()
    raw_jobs = load_jobs()
    jobs = [_apply_skill_fields(j) for j in copy.deepcopy(raw_jobs)]
    due = []
    needs_save = False

    for job in jobs:
        if not job.get("enabled", True):
            continue

        next_run = job.get("next_run_at")
        if not next_run:
            recovered_next = _recoverable_oneshot_run_at(
                job.get("schedule", {}),
                now,
                last_run_at=job.get("last_run_at"),
            )
            if not recovered_next:
                continue

            job["next_run_at"] = recovered_next
            next_run = recovered_next
            logger.info(
                "Job '%s' had no next_run_at; recovering one-shot run at %s",
                job.get("name", job["id"]),
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
            if kind in ("cron", "interval") and (now - next_run_dt).total_seconds() > grace:
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
    job_output_dir = _output_dir() / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)
    _secure_dir(job_output_dir)
    
    timestamp = _elevate_now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = job_output_dir / f"{timestamp}.md"
    
    fd, tmp_path = tempfile.mkstemp(dir=str(job_output_dir), suffix='.tmp', prefix='.output_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_file)
        _secure_file(output_file)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    
    return output_file
