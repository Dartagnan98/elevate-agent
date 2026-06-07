"""Cron job management routes for the Elevate dashboard."""

import logging
import threading
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"
    # Provenance tag (e.g. {"type": "heartbeat"}) so a feature surface can
    # filter its own jobs out of the general cron list. create_job already
    # accepts ``origin``; this just lets the HTTP layer forward it.
    origin: Optional[dict] = None
    # Phase 3 (/leads): universal cron form fields. All optional so existing
    # callers keep working. Skill-bound mode = pass `skill`. Per-job model is
    # the explicit override; tier is the harness-resolved fallback.
    skill: Optional[str] = None
    skills: Optional[List[str]] = None
    agent: Optional[str] = None
    tier: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    enabled_toolsets: Optional[List[str]] = None
    workdir: Optional[str] = None
    expected_readiness_version: Optional[str] = None
    backfill_pending: bool = False
    metadata: Optional[dict] = None


class CronJobUpdate(BaseModel):
    updates: dict




def create_cron_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build routes for cron job CRUD, lane seeding, and backfill progress."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    def _compact_job(job: dict) -> dict:
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

    @router.get("/api/cron/jobs")
    async def list_cron_jobs(compact: bool = False):
        from cron.jobs import list_jobs
        jobs = list_jobs(include_disabled=True)
        return [_compact_job(job) for job in jobs] if compact else jobs


    @router.get("/api/cron/jobs/{job_id}")
    async def get_cron_job(job_id: str):
        from cron.jobs import get_job
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


    @router.post("/api/cron/jobs")
    async def create_cron_job(body: CronJobCreate):
        from cron.jobs import create_job
        from elevate_cli.onboarding import compute_onboarding_status

        # Readiness gate: a job that pins ``expected_readiness_version`` is
        # declaring "I only make sense once the system is configured to this
        # snapshot." Reject if the snapshot has drifted (or system isn't ready)
        # so the wizard surfaces the mismatch instead of silently scheduling a
        # job that will skip itself at fire-time.
        if body.expected_readiness_version:
            try:
                snap = compute_onboarding_status()
            except Exception as exc:
                _log.exception("readiness probe failed during POST /api/cron/jobs")
                raise HTTPException(status_code=503, detail=f"readiness probe failed: {exc}")
            if not snap.get("ready"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "system_not_ready",
                        "message": "Onboarding readiness checks not all passing — finish setup before pinning a readiness version.",
                        "current_version": snap.get("version"),
                        "checks": snap.get("checks"),
                    },
                )
            if str(snap.get("version")) != str(body.expected_readiness_version):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "readiness_version_mismatch",
                        "message": "Onboarding state changed since the wizard read it — refresh and resubmit.",
                        "current_version": snap.get("version"),
                        "expected_version": body.expected_readiness_version,
                    },
                )

        try:
            job = create_job(
                prompt=body.prompt,
                schedule=body.schedule,
                name=body.name,
                deliver=body.deliver,
                origin=body.origin,
                skill=body.skill,
                skills=body.skills,
                agent=body.agent,
                tier=body.tier,
                model=body.model,
                provider=body.provider,
                base_url=body.base_url,
                enabled_toolsets=body.enabled_toolsets,
                workdir=body.workdir,
                expected_readiness_version=body.expected_readiness_version,
                backfill_pending=body.backfill_pending,
                metadata=body.metadata,
            )
            return job
        except ValueError as e:
            # Tier validation, workdir validation — surface to UI as 400.
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            _log.exception("POST /api/cron/jobs failed")
            raise HTTPException(status_code=400, detail=str(e))


    class _EnsureLanesBody(BaseModel):
        """Bulk seed for the default /leads lanes. Each entry is a minimal
        cron job spec; the server creates one only if no existing job has the
        same case-insensitive name. Lets the UI declare its default lane set
        in one place and have the backend converge to it on /leads load."""

        lanes: List[CronJobCreate]


    @router.post("/api/cron/jobs/ensure-lanes")
    async def ensure_lanes(body: _EnsureLanesBody):
        """Idempotently install/converge the default outreach/admin lanes.

        Returns ``{created: [...], updated: [...], skipped: [...]}`` so the UI can decide
        whether to refresh the cron list. Safe to call on every /leads
        mount. Existing lanes are updated when the default prompt, delivery,
        schedule, skills, or workdir changes.
        """
        from cron.jobs import create_job, list_jobs, update_job

        existing = list_jobs(include_disabled=True)
        existing_by_name = {str(j.get("name") or "").strip().lower(): j for j in existing}

        created: list[dict] = []
        updated: list[dict] = []
        skipped: list[str] = []
        for lane in body.lanes:
            target = str(lane.name or "").strip()
            if not target:
                continue
            existing_job = existing_by_name.get(target.lower())
            if existing_job:
                desired_skills = lane.skills if lane.skills is not None else ([lane.skill] if lane.skill else None)
                updates: dict[str, object] = {}
                if lane.prompt and existing_job.get("prompt") != lane.prompt:
                    updates["prompt"] = lane.prompt
                if lane.deliver and existing_job.get("deliver", "local") != lane.deliver:
                    updates["deliver"] = lane.deliver
                if lane.schedule and existing_job.get("schedule_display") != lane.schedule:
                    updates["schedule"] = lane.schedule
                if desired_skills is not None and existing_job.get("skills") != desired_skills:
                    updates["skills"] = desired_skills
                if lane.workdir is not None and existing_job.get("workdir") != lane.workdir:
                    updates["workdir"] = lane.workdir
                if updates:
                    try:
                        changed = update_job(existing_job["id"], updates)
                        if changed:
                            updated.append(changed)
                            existing_by_name[target.lower()] = changed
                            continue
                    except Exception as exc:
                        _log.exception("ensure-lanes: failed to update %s", target)
                        skipped.append(f"{target} (error: {exc})")
                        continue
                skipped.append(target)
                continue
            try:
                job = create_job(
                    prompt=lane.prompt,
                    schedule=lane.schedule,
                    name=target,
                    deliver=lane.deliver or "local",
                    skill=lane.skill,
                    skills=lane.skills,
                    agent=lane.agent,
                    tier=lane.tier,
                    model=lane.model,
                    provider=lane.provider,
                    base_url=lane.base_url,
                    enabled_toolsets=lane.enabled_toolsets,
                    workdir=lane.workdir,
                )
                created.append(job)
                existing_by_name[target.lower()] = job
            except Exception as exc:
                _log.exception("ensure-lanes: failed to create %s", target)
                skipped.append(f"{target} (error: {exc})")
        return {"created": created, "updated": updated, "skipped": skipped}


    @router.put("/api/cron/jobs/{job_id}")
    async def update_cron_job(job_id: str, body: CronJobUpdate):
        from cron.jobs import update_job
        job = update_job(job_id, body.updates)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


    class _BackfillProgressBody(BaseModel):
        queued_today: Optional[int] = None
        eligible_remaining: Optional[int] = None
        total_estimate: Optional[int] = None


    @router.get("/api/cron/jobs/{job_id}/backfill")
    async def get_cron_job_backfill(job_id: str):
        """Return the lane's backfill progress: pending flag + day/eligible counters."""
        from cron.jobs import get_job
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": job_id,
            "backfill_pending": bool(job.get("backfill_pending")),
            "backfill_state": job.get("backfill_state"),
        }


    @router.post("/api/cron/jobs/{job_id}/backfill/progress")
    async def post_cron_job_backfill_progress(job_id: str, body: _BackfillProgressBody):
        """Lane skill calls this at end of each backfill run to record progress.

        Increments day, records queued_today + eligible_remaining + total_estimate.
        When eligible_remaining hits 0, the job's ``backfill_pending`` is cleared
        and subsequent runs use the incremental window.
        """
        from cron.jobs import update_backfill_state
        job = update_backfill_state(
            job_id,
            queued_today=body.queued_today,
            eligible_remaining=body.eligible_remaining,
            total_estimate=body.total_estimate,
        )
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": job_id,
            "backfill_pending": bool(job.get("backfill_pending")),
            "backfill_state": job.get("backfill_state"),
        }


    @router.post("/api/cron/jobs/{job_id}/pause")
    async def pause_cron_job(job_id: str):
        from cron.jobs import pause_job
        job = pause_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


    @router.post("/api/cron/jobs/{job_id}/resume")
    async def resume_cron_job(job_id: str):
        from cron.jobs import resume_job
        job = resume_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


    @router.post("/api/cron/jobs/{job_id}/trigger")
    async def trigger_cron_job(job_id: str):
        from cron.jobs import trigger_job
        job = trigger_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        def _run_due_tick() -> None:
            # Manual runs should feel immediate in the dashboard. trigger_job()
            # only marks the row due; this starts the scheduler now instead of
            # waiting for the gateway's next 60s poll.
            try:
                from cron.scheduler import tick
            except Exception:
                _log.exception("cron trigger: scheduler import failed for %s", job_id)
                return
            for attempt in range(6):
                try:
                    ran = tick(verbose=False)
                    if ran:
                        return
                except Exception:
                    _log.exception("cron trigger: manual tick failed for %s", job_id)
                    return
                if attempt < 5:
                    time.sleep(0.75)

        threading.Thread(
            target=_run_due_tick,
            name=f"cron-trigger-{job['id']}",
            daemon=True,
        ).start()
        return job


    @router.delete("/api/cron/jobs/{job_id}")
    async def delete_cron_job(job_id: str):
        from cron.jobs import remove_job
        if not remove_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        return {"ok": True}


    @router.get("/api/cron/attention")
    async def cron_attention():
        """Aggregate what's waiting on the operator.

        Returns counts the dashboard can surface as a "needs attention" banner:
        - ``pending_drafts``: outreach drafts in `drafted` status waiting on review
        - ``errored_jobs``: cron jobs whose last run failed
        - ``stale_jobs``: enabled jobs that haven't fired in >36h (likely auth/runtime break)
        - ``jobs``: light per-job rollup (id, name, last_status, last_error_short, last_run_at)
        """
        from cron.jobs import list_jobs
        import datetime as _dt

        pending_drafts = 0
        try:
            from elevate_cli.outreach_db import connect as _outreach_connect
            with _outreach_connect() as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute(
                        "SELECT COUNT(*) FROM outreach_draft_attempts WHERE status = %s",
                        ("drafted",),
                    )
                    row = _cur.fetchone()
                    pending_drafts = int(row[0]) if row else 0
        except Exception as exc:
            _log.debug("attention: outreach draft count failed: %s", exc)

        errored: list[dict] = []
        stale: list[dict] = []
        now = _dt.datetime.now(_dt.timezone.utc)
        try:
            jobs = list_jobs(include_disabled=True)
        except Exception as exc:
            _log.exception("attention: list_jobs failed: %s", exc)
            jobs = []

        for job in jobs:
            if not job.get("enabled"):
                continue
            last_status = (job.get("last_status") or "").lower()
            last_error = job.get("last_error") or ""
            short_err = (last_error[:140] + "...") if len(last_error) > 140 else last_error
            if last_status == "error":
                errored.append({
                    "id": job.get("id"),
                    "name": job.get("name"),
                    "last_error": short_err,
                    "last_run_at": job.get("last_run_at"),
                })
            last_run = job.get("last_run_at")
            if last_run:
                try:
                    parsed = _dt.datetime.fromisoformat(str(last_run).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
                    age_h = (now - parsed).total_seconds() / 3600.0
                    if age_h > 36 and last_status != "error":
                        stale.append({
                            "id": job.get("id"),
                            "name": job.get("name"),
                            "last_run_at": last_run,
                            "hours_since": round(age_h, 1),
                        })
                except Exception:
                    pass

        return {
            "pending_drafts": pending_drafts,
            "errored_jobs": errored,
            "stale_jobs": stale,
            "total": pending_drafts + len(errored) + len(stale),
        }


    return router
