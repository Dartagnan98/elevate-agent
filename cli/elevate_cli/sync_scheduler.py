"""Portable recurring-sync scheduler for Elevate connectors.

Installs one launchd plist per connector (apple-messages / crm / social) that
calls ``elevate sync <source>`` on a fixed interval. The plists are generated
at install time using the real user's HOME, the detected venv, and the active
``ELEVATE_HOME`` so any fresh install gets correct paths without hard-coding.

Mac-only today. On non-Darwin platforms, ``install_all`` reports unsupported
and exits cleanly so ``elevate db init`` still succeeds.

Why launchd (not the AI cron in ``cron/jobs.json``):
- These are deterministic shell calls, not LLM prompts. AI cron would burn
  tokens for every fire. Memory rule ``feedback_scheduling_layer_choice``:
  launchd for dumb scripts, mcp__scheduled-tasks for AI work.
- launchd survives reboots, runs even when no terminal is open, and matches
  the existing pattern at ``~/Library/LaunchAgents/ai.elevate.*.plist``.
"""

from __future__ import annotations

import os
import platform
import pwd
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ─── Job registry ──────────────────────────────────────────────────────
#
# (label_stem, source_id, interval_seconds, description)
#
# Same on every install. Source ids match ``data_cli._KNOWN_SOURCE_IDS``;
# the "gmail" source is intentionally NOT a separate cron — it flows through
# ``elevate sync social`` (composio_inbound.pull_all_supported pulls every
# connected toolkit in one pass).

_JOBS: tuple[tuple[str, str, int, str], ...] = (
    ("sync-apple-messages", "apple-messages", 600, "iMessage / SMS pull"),
    ("sync-crm",            "crm",            3600, "CRM adapter pull (provider-agnostic)"),
    ("sync-social",         "social",         600, "Composio inbound (gmail, ig, wa, fb, slack, ...)"),
    # MLS private-search scraper. 48h cadence — Xposure scrapes are
    # browser sessions that take ~3-5 min each, and the underlying
    # buyer-search criteria don't change minute-to-minute. The buyer-
    # brief enrichment runs immediately after and is a cheap local
    # compute, so we chain them in one plist via the same source-id
    # dispatch (see source_connectors.scaffold_source). 172800s = 2d.
    ("sync-xposure-pcs",    "xposure-pcs",    172800, "MLS private-search scrape"),
    ("sync-buyer-brief",    "buyer-brief",    172800, "Buyer-brief enrichment (post-scrape)"),
    # Per-listing engagement (Client View one-way mirror). Same 48h
    # cadence as the criteria scrape but staggered: this one cares
    # about view counts / favorites / last_client_access and is the
    # primary signal source for the activity + outreach flagger.
    ("sync-xposure-pcs-views", "xposure-pcs-views", 172800, "MLS per-listing engagement scrape"),
)


@dataclass(frozen=True)
class SchedulerJob:
    label: str
    source_id: str
    interval_seconds: int
    description: str
    plist_path: Path


@dataclass(frozen=True)
class SchedulerResult:
    job: SchedulerJob
    ok: bool
    action: str  # "installed", "refreshed", "skipped", "uninstalled", "failed", "unsupported"
    message: str


# ─── Profile + path helpers ────────────────────────────────────────────

def _user_home() -> Path:
    """Real account home (not ELEVATE_HOME).

    launchd user agents live in ``~/Library/LaunchAgents``, which must be
    the OS-level home even when ``HOME`` has been pointed at a profile dir.
    """
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _profile_suffix() -> str:
    """Mirror of ``gateway._profile_suffix`` for service-label scoping.

    Imported lazily to avoid circulars during ``elevate db init``.
    """
    try:
        from elevate_cli.gateway import _profile_suffix as _g
        return _g()
    except Exception:
        return ""


def _label_for(stem: str) -> str:
    suffix = _profile_suffix()
    return f"ai.elevate.{stem}-{suffix}" if suffix else f"ai.elevate.{stem}"


def _plist_dir() -> Path:
    return _user_home() / "Library" / "LaunchAgents"


def _plist_path_for(label: str) -> Path:
    return _plist_dir() / f"{label}.plist"


def _python_path() -> str:
    """venv python if we can find one, else sys.executable."""
    try:
        from elevate_cli.gateway import get_python_path
        return get_python_path()
    except Exception:
        return sys.executable


def _elevate_home_str() -> str:
    try:
        from elevate_constants import get_elevate_home
        return str(get_elevate_home().resolve())
    except Exception:
        return str(Path("~/.elevate").expanduser().resolve())


def _log_dir() -> Path:
    p = Path(_elevate_home_str()) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def jobs() -> list[SchedulerJob]:
    return [
        SchedulerJob(
            label=_label_for(stem),
            source_id=source_id,
            interval_seconds=interval,
            description=desc,
            plist_path=_plist_path_for(_label_for(stem)),
        )
        for (stem, source_id, interval, desc) in _JOBS
    ]


# ─── Plist generation ──────────────────────────────────────────────────

def _sane_path() -> str:
    """PATH that includes the venv bin first, then the user's full shell PATH."""
    venv = Path(_python_path()).parent
    parts = [str(venv)]
    for p in os.environ.get("PATH", "").split(":"):
        if p and p not in parts:
            parts.append(p)
    # Hardcoded fallbacks so launchd's bare PATH still finds homebrew, etc.
    for fb in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"):
        if fb not in parts:
            parts.append(fb)
    return ":".join(parts)


def _job_timeout_seconds(job: SchedulerJob) -> int:
    """Hard runtime cap for one sync invocation.

    Without a cap, a hung connector (Apple chat.db slow query, Composio
    stalled fetch) holds a write lock on operational.db indefinitely and
    every dashboard surface (Admin, Leads, sessions) starts returning
    ``database is locked`` 500s. The cap kills the runaway child so the
    next scheduled tick can recover. Half the interval (capped at 10min)
    leaves headroom for the next tick to not pile up while still
    interrupting an obvious hang.

    The xposure-pcs* connectors drive an LLM agent against the AOIR MLS
    portal — login + email MFA + ~1000-row DataTables render + per-row
    extraction. 10 min isn't enough for the first MFA-bearing run, so
    those two get a 25-minute ceiling instead.
    """
    if job.source_id in ("xposure-pcs", "xposure-pcs-views"):
        return max(60, min(1500, job.interval_seconds // 2))
    return max(60, min(600, job.interval_seconds // 2))


def generate_plist(job: SchedulerJob) -> str:
    """Render an XML plist for one sync job.

    The job runs ``python -m elevate_cli.main sync <source>`` under a
    bash watchdog that SIGKILLs the child if it exceeds the per-job
    timeout. macOS launchd has no native runtime cap, and a hung sync
    holds operational.db locks that break the dashboard, so the
    watchdog is essential. ``ELEVATE_HOME`` is baked in so the launchd
    process points at the same store as the install that registered it.
    """
    python = _python_path()
    home = _elevate_home_str()
    path = _sane_path()
    log_dir = _log_dir()
    stdout = log_dir / f"{job.label}.log"
    stderr = log_dir / f"{job.label}.error.log"
    cwd = str(Path(__file__).parent.parent.resolve())
    timeout = _job_timeout_seconds(job)

    # Inline bash watchdog: background the python child, sleep for the cap,
    # then SIGKILL if still alive. Single file, no extra shipping artifact.
    bash_cmd = (
        f'set -uo pipefail; '
        f'"{python}" -m elevate_cli.main sync {job.source_id} & '
        f'child=$!; '
        f'( sleep {timeout}; '
        f'kill -0 "$child" 2>/dev/null && '
        f'kill -9 "$child" 2>/dev/null && '
        f'echo "[watchdog] sync {job.source_id} TIMEOUT after {timeout}s — killed pid $child" >&2 '
        f') & '
        f'watchdog=$!; '
        f'wait "$child"; rc=$?; '
        f'kill -0 "$watchdog" 2>/dev/null && kill "$watchdog" 2>/dev/null; '
        f'exit $rc'
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{job.label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>{bash_cmd}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{cwd}</string>

    <key>StartInterval</key>
    <integer>{job.interval_seconds}</integer>

    <!--
      RunAtLoad fires the job once when launchctl bootstraps the plist
      (i.e. at install time and at each login). That doubles as the
      "setup cron" — `elevate db init` installs the plist, launchd fires
      the sync immediately, the DB is hot before the first scheduled tick.
    -->
    <key>RunAtLoad</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{_user_home()}</string>
        <key>PATH</key>
        <string>{path}</string>
        <key>ELEVATE_HOME</key>
        <string>{home}</string>
    </dict>

    <key>StandardOutPath</key>
    <string>{stdout}</string>

    <key>StandardErrorPath</key>
    <string>{stderr}</string>
</dict>
</plist>
"""


# ─── Install / uninstall ───────────────────────────────────────────────

def _is_mac() -> bool:
    return platform.system() == "Darwin"


def _is_loaded(label: str) -> bool:
    """Return True if launchd has this label in the user domain."""
    if not _is_mac():
        return False
    r = subprocess.run(
        ["launchctl", "print", f"{_launchd_domain()}/{label}"],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0


def _bootstrap_only(plist_path: Path) -> None:
    """Bootstrap without a prior bootout. Use when not already loaded."""
    subprocess.run(
        ["launchctl", "bootstrap", _launchd_domain(), str(plist_path)],
        check=True, timeout=30, capture_output=True,
    )


def _bootout_then_bootstrap(plist_path: Path, label: str) -> None:
    """Reload — used only when the plist content actually changed.

    Bootout signals the running process to exit; we then re-bootstrap with
    the new plist content. Skipped when content is byte-identical, so an
    in-flight sync isn't killed by a no-op re-install.
    """
    subprocess.run(
        ["launchctl", "bootout", f"{_launchd_domain()}/{label}"],
        check=False, timeout=30, capture_output=True,
    )
    _bootstrap_only(plist_path)


def install_one(job: SchedulerJob, *, force: bool = False) -> SchedulerResult:
    if not _is_mac():
        return SchedulerResult(job, ok=True, action="unsupported",
                               message=f"{platform.system()} — launchd only runs on macOS")
    try:
        existing = job.plist_path.read_text(encoding="utf-8") if job.plist_path.exists() else None
        expected = generate_plist(job)
        plist_unchanged = (existing == expected) and not force

        if plist_unchanged:
            # Content matches what's on disk. Only bootstrap if launchd
            # doesn't already have it — don't reload an in-flight job.
            if _is_loaded(job.label):
                return SchedulerResult(job, ok=True, action="skipped",
                                       message="plist current; already loaded")
            _bootstrap_only(job.plist_path)
            return SchedulerResult(job, ok=True, action="skipped",
                                   message="plist current; bootstrapped")

        job.plist_path.parent.mkdir(parents=True, exist_ok=True)
        job.plist_path.write_text(expected, encoding="utf-8")
        if _is_loaded(job.label):
            _bootout_then_bootstrap(job.plist_path, job.label)
        else:
            _bootstrap_only(job.plist_path)
        action = "refreshed" if existing else "installed"
        return SchedulerResult(job, ok=True, action=action,
                               message=f"every {job.interval_seconds}s — {job.description}")
    except Exception as exc:
        return SchedulerResult(job, ok=False, action="failed", message=str(exc))


def install_all(*, force: bool = False) -> list[SchedulerResult]:
    return [install_one(j, force=force) for j in jobs()]


def uninstall_one(job: SchedulerJob) -> SchedulerResult:
    if not _is_mac():
        return SchedulerResult(job, ok=True, action="unsupported",
                               message=f"{platform.system()} — launchd only runs on macOS")
    try:
        subprocess.run(
            ["launchctl", "bootout", f"{_launchd_domain()}/{job.label}"],
            check=False, timeout=30,
            capture_output=True,
        )
        removed = False
        if job.plist_path.exists():
            job.plist_path.unlink()
            removed = True
        return SchedulerResult(job, ok=True, action="uninstalled",
                               message=f"plist {'removed' if removed else 'absent'}")
    except Exception as exc:
        return SchedulerResult(job, ok=False, action="failed", message=str(exc))


def uninstall_all() -> list[SchedulerResult]:
    return [uninstall_one(j) for j in jobs()]


# ─── Status ────────────────────────────────────────────────────────────

def status() -> list[dict]:
    """Return a snapshot for each job: installed/loaded state + next interval."""
    out: list[dict] = []
    for job in jobs():
        installed = job.plist_path.exists()
        loaded = False
        last_exit: int | None = None
        if _is_mac() and installed:
            try:
                r = subprocess.run(
                    ["launchctl", "print", f"{_launchd_domain()}/{job.label}"],
                    capture_output=True, text=True, timeout=10,
                )
                loaded = r.returncode == 0
                if loaded:
                    for line in (r.stdout or "").splitlines():
                        if "last exit code" in line:
                            try:
                                last_exit = int(line.split("=")[-1].strip().rstrip(","))
                            except ValueError:
                                pass
                            break
            except Exception:
                pass
        out.append({
            "label": job.label,
            "source_id": job.source_id,
            "interval_seconds": job.interval_seconds,
            "plist_path": str(job.plist_path),
            "installed": installed,
            "loaded": loaded,
            "last_exit": last_exit,
            "description": job.description,
        })
    return out


def print_status(rows: Iterable[dict] | None = None) -> None:
    rows = list(rows) if rows is not None else status()
    print("Elevate sync scheduler")
    if not _is_mac():
        print(f"  unsupported platform: {platform.system()} (launchd is mac-only)")
        return
    for r in rows:
        flag = "loaded" if r["loaded"] else ("installed" if r["installed"] else "absent")
        exit_part = f" last_exit={r['last_exit']}" if r["last_exit"] is not None else ""
        print(f"- {r['source_id']:<14} {flag:<10} every {r['interval_seconds']}s{exit_part}")
        print(f"  {r['plist_path']}")


def print_results(results: Iterable[SchedulerResult]) -> int:
    failures = 0
    for r in results:
        marker = "ok" if r.ok else "FAIL"
        if not r.ok:
            failures += 1
        print(f"- {r.job.source_id:<14} {marker:<4} {r.action:<11} {r.message}")
    return 1 if failures else 0
