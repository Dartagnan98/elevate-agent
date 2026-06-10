"""Tests for the weekly Memory Benchmark system-job seed (cron/jobs.py)."""

import pytest

from cron.jobs import (
    MEMORY_BENCHMARK_JOB_NAME,
    MEMORY_BENCHMARK_SCHEDULE,
    create_job,
    ensure_memory_benchmark_job,
    load_jobs,
    pause_job,
    update_job,
)


@pytest.fixture()
def tmp_cron_dir(tmp_path, monkeypatch):
    """Redirect cron storage to a temp directory (same as tests/cron/test_jobs.py)."""
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


class TestMemoryBenchmarkSeed:
    def test_seed_creates_enabled_weekly_job(self, tmp_cron_dir):
        job = ensure_memory_benchmark_job()

        assert job["name"] == MEMORY_BENCHMARK_JOB_NAME
        assert job["enabled"] is True
        assert job["state"] == "scheduled"
        assert MEMORY_BENCHMARK_SCHEDULE == "0 3 * * 0"
        assert job["schedule"]["kind"] == "cron"
        assert job["schedule"]["expr"] == "0 3 * * 0"
        assert job["origin"] == {"type": "system-maintenance", "source": "memory-benchmark"}
        assert "elevate memory benchmark" in job["prompt"]
        assert "benchmark_history.jsonl" in job["prompt"]
        assert "20%" in job["prompt"]

    def test_seed_is_idempotent(self, tmp_cron_dir):
        first = ensure_memory_benchmark_job()
        second = ensure_memory_benchmark_job()

        assert second["id"] == first["id"]
        names = [j["name"] for j in load_jobs() if j["name"] == MEMORY_BENCHMARK_JOB_NAME]
        assert len(names) == 1

    def test_existing_job_left_exactly_as_is(self, tmp_cron_dir):
        """Operator pause + edits are respected — the seeder never repairs."""
        seeded = ensure_memory_benchmark_job()
        update_job(seeded["id"], {"prompt": "operator-edited prompt"})
        paused = pause_job(seeded["id"], reason="operator pause")
        assert paused["enabled"] is False

        job = ensure_memory_benchmark_job()

        assert job["id"] == seeded["id"]
        assert job["enabled"] is False
        assert job["paused_reason"] == "operator pause"
        assert job["prompt"] == "operator-edited prompt"

    def test_name_match_is_case_insensitive(self, tmp_cron_dir):
        existing = create_job(
            prompt="legacy benchmark job",
            schedule="0 4 * * 0",
            name="memory benchmark",
            deliver="local",
        )

        job = ensure_memory_benchmark_job()

        assert job["id"] == existing["id"]
        assert len(load_jobs()) == 1
