"""Tests for crash-safe backfill progress persistence (cron/jobs.py).

Covers the 2026-06-09 audit fix: backfill_state historically only got written
by a single end-of-run report, so a crash/timeout mid-run lost the whole
run's progress.  update_backfill_state now supports per-chunk checkpoints
(``checkpoint=True`` + a stable ``run_id``) that persist immediately and are
idempotent on the day counter, so a failed run resumes from the last
persisted checkpoint instead of from zero.
"""

import pytest

from cron.jobs import (
    create_job,
    get_job,
    update_backfill_state,
)


@pytest.fixture()
def tmp_cron_dir(tmp_path, monkeypatch):
    """Redirect cron storage to a temp directory (test seam: scoping off)."""
    monkeypatch.setattr("cron.jobs._account_scoping_enabled", False)
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


def _make_backfill_job():
    return create_job(
        prompt="backfill lane",
        schedule="every 1d",
        name="backfill-test",
        backfill_pending=True,
    )


class TestLegacyBackfillBehaviour:
    """Calls without run_id keep the original contract (backward compat)."""

    def test_each_call_bumps_day(self, tmp_cron_dir):
        job = _make_backfill_job()
        update_backfill_state(job["id"], queued_today=20, eligible_remaining=80)
        updated = update_backfill_state(job["id"], queued_today=20, eligible_remaining=60)
        assert updated["backfill_state"]["day"] == 2
        assert updated["backfill_state"]["queued_today"] == 20
        assert updated["backfill_state"]["eligible_remaining"] == 60

    def test_legacy_state_dict_loads(self, tmp_cron_dir):
        """A state dict written by the old code (no last_run_id/checkpoint
        keys) must keep working."""
        from cron.jobs import load_jobs, save_jobs

        job = _make_backfill_job()
        jobs = load_jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["backfill_state"] = {
                    "day": 3,
                    "total_estimate": 100,
                    "queued_today": 20,
                    "eligible_remaining": 40,
                    "updated_at": "2026-06-01T00:00:00",
                }
        save_jobs(jobs)

        updated = update_backfill_state(job["id"], queued_today=15, eligible_remaining=25)
        state = updated["backfill_state"]
        assert state["day"] == 4
        assert state["queued_today"] == 15
        assert state["eligible_remaining"] == 25

    def test_eligible_zero_clears_pending(self, tmp_cron_dir):
        job = _make_backfill_job()
        updated = update_backfill_state(job["id"], queued_today=5, eligible_remaining=0)
        assert updated["backfill_pending"] is False

    def test_missing_job_returns_none(self, tmp_cron_dir):
        assert update_backfill_state("nonexistent") is None

    def test_non_backfill_job_is_untouched(self, tmp_cron_dir):
        job = create_job(prompt="plain", schedule="every 1d", name="plain")
        result = update_backfill_state(job["id"], queued_today=5)
        assert result["backfill_state"] is None


class TestCheckpointPersistence:
    """The crash-safety contract: progress persists per chunk, day counts once."""

    def test_checkpoint_persists_immediately(self, tmp_cron_dir):
        job = _make_backfill_job()
        update_backfill_state(
            job["id"],
            queued_today=5,
            eligible_remaining=95,
            total_estimate=100,
            run_id="run-1",
            checkpoint=True,
        )
        # Re-read from disk — the checkpoint must already be durable.
        state = get_job(job["id"])["backfill_state"]
        assert state["day"] == 1
        assert state["queued_today"] == 5
        assert state["eligible_remaining"] == 95
        assert state["checkpoint"] is True
        assert state["last_run_id"] == "run-1"

    def test_same_run_checkpoints_bump_day_once(self, tmp_cron_dir):
        job = _make_backfill_job()
        for queued, remaining in ((5, 95), (10, 90), (15, 85)):
            update_backfill_state(
                job["id"],
                queued_today=queued,
                eligible_remaining=remaining,
                run_id="run-1",
                checkpoint=True,
            )
        state = get_job(job["id"])["backfill_state"]
        assert state["day"] == 1  # not 3
        assert state["queued_today"] == 15
        assert state["eligible_remaining"] == 85

    def test_final_report_does_not_double_count_day(self, tmp_cron_dir):
        job = _make_backfill_job()
        update_backfill_state(
            job["id"], queued_today=10, eligible_remaining=90,
            run_id="run-1", checkpoint=True,
        )
        updated = update_backfill_state(
            job["id"], queued_today=20, eligible_remaining=80, run_id="run-1",
        )
        state = updated["backfill_state"]
        assert state["day"] == 1
        assert state["checkpoint"] is False  # final report clears the flag

    def test_crash_mid_run_resumes_from_last_checkpoint(self, tmp_cron_dir):
        """Simulate: run-1 checkpoints twice then dies (no final report).
        run-2 must see the checkpointed counters and get its own day bump."""
        job = _make_backfill_job()
        update_backfill_state(
            job["id"], queued_today=5, eligible_remaining=95,
            total_estimate=100, run_id="run-1", checkpoint=True,
        )
        update_backfill_state(
            job["id"], queued_today=12, eligible_remaining=88,
            run_id="run-1", checkpoint=True,
        )
        # ── crash: no final report for run-1 ──

        # Next run reads the durable state: progress was NOT lost.
        state = get_job(job["id"])["backfill_state"]
        assert state["queued_today"] == 12
        assert state["eligible_remaining"] == 88
        assert state["checkpoint"] is True  # tells run-2 the last run died mid-flight
        assert state["day"] == 1

        # run-2 reports — new run_id bumps the day exactly once.
        updated = update_backfill_state(
            job["id"], queued_today=20, eligible_remaining=68, run_id="run-2",
        )
        state = updated["backfill_state"]
        assert state["day"] == 2
        assert state["eligible_remaining"] == 68
        assert state["last_run_id"] == "run-2"
        assert state["checkpoint"] is False

    def test_checkpoint_can_finish_backfill(self, tmp_cron_dir):
        job = _make_backfill_job()
        updated = update_backfill_state(
            job["id"], queued_today=3, eligible_remaining=0,
            run_id="run-1", checkpoint=True,
        )
        assert updated["backfill_pending"] is False
