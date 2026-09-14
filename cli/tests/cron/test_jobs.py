"""Tests for cron/jobs.py — schedule parsing, job CRUD, and due-job detection."""

import threading
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cron.jobs import (
    parse_duration,
    parse_schedule,
    compute_next_run,
    create_job,
    load_jobs,
    save_jobs,
    get_job,
    list_jobs,
    update_job,
    pause_job,
    resume_job,
    remove_job,
    mark_job_run,
    advance_next_run,
    get_due_jobs,
    save_job_output,
    ensure_theta_wave,
    THETA_WAVE_SKILL,
)


# =========================================================================
# parse_duration
# =========================================================================

class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("30m") == 30
        assert parse_duration("1min") == 1
        assert parse_duration("5mins") == 5
        assert parse_duration("10minute") == 10
        assert parse_duration("120minutes") == 120

    def test_hours(self):
        assert parse_duration("2h") == 120
        assert parse_duration("1hr") == 60
        assert parse_duration("3hrs") == 180
        assert parse_duration("1hour") == 60
        assert parse_duration("24hours") == 1440

    def test_days(self):
        assert parse_duration("1d") == 1440
        assert parse_duration("7day") == 7 * 1440
        assert parse_duration("2days") == 2 * 1440

    def test_whitespace_tolerance(self):
        assert parse_duration("  30m  ") == 30
        assert parse_duration("2 h") == 120

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_duration("abc")
        with pytest.raises(ValueError):
            parse_duration("30x")
        with pytest.raises(ValueError):
            parse_duration("")
        with pytest.raises(ValueError):
            parse_duration("m30")


# =========================================================================
# parse_schedule
# =========================================================================

class TestParseSchedule:
    def test_duration_becomes_once(self):
        result = parse_schedule("30m")
        assert result["kind"] == "once"
        assert "run_at" in result
        # run_at should be a valid ISO timestamp string ~30 minutes from now
        run_at_str = result["run_at"]
        assert isinstance(run_at_str, str)
        run_at = datetime.fromisoformat(run_at_str)
        now = datetime.now().astimezone()
        assert run_at > now
        assert run_at < now + timedelta(minutes=31)

    def test_every_becomes_interval(self):
        result = parse_schedule("every 2h")
        assert result["kind"] == "interval"
        assert result["minutes"] == 120

    def test_every_case_insensitive(self):
        result = parse_schedule("Every 30m")
        assert result["kind"] == "interval"
        assert result["minutes"] == 30

    def test_cron_expression(self):
        pytest.importorskip("croniter")
        result = parse_schedule("0 9 * * *")
        assert result["kind"] == "cron"
        assert result["expr"] == "0 9 * * *"

    def test_iso_timestamp(self):
        result = parse_schedule("2030-01-15T14:00:00")
        assert result["kind"] == "once"
        assert "2030-01-15" in result["run_at"]

    def test_invalid_schedule_raises(self):
        with pytest.raises(ValueError):
            parse_schedule("not_a_schedule")

    def test_invalid_cron_raises(self):
        pytest.importorskip("croniter")
        with pytest.raises(ValueError):
            parse_schedule("99 99 99 99 99")


class TestAgentValidation:
    def test_create_job_canonicalizes_agent_id(self, tmp_cron_dir):
        job = create_job(prompt="Admin lane", schedule="every 1h", agent="Admin")

        assert job["agent"] == "admin"

    def test_create_job_rejects_unknown_agent(self, tmp_cron_dir):
        with pytest.raises(ValueError, match="unknown agent"):
            create_job(prompt="Bad lane", schedule="every 1h", agent="admn")

    def test_update_job_canonicalizes_agent_id(self, tmp_cron_dir):
        job = create_job(prompt="Admin lane", schedule="every 1h")

        updated = update_job(job["id"], {"agent": "Admin"})

        assert updated["agent"] == "admin"


# =========================================================================
# compute_next_run
# =========================================================================

class TestComputeNextRun:
    def test_once_future_returns_time(self):
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        schedule = {"kind": "once", "run_at": future}
        assert compute_next_run(schedule) == future

    def test_once_recent_past_within_grace_returns_time(self, monkeypatch):
        now = datetime(2026, 3, 18, 4, 22, 3, tzinfo=timezone.utc)
        run_at = "2026-03-18T04:22:00+00:00"
        monkeypatch.setattr("cron.jobs._hermes_now", lambda: now)

        schedule = {"kind": "once", "run_at": run_at}

        assert compute_next_run(schedule) == run_at

    def test_once_past_returns_none(self):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        schedule = {"kind": "once", "run_at": past}
        assert compute_next_run(schedule) is None

    def test_once_with_last_run_returns_none_even_within_grace(self, monkeypatch):
        now = datetime(2026, 3, 18, 4, 22, 3, tzinfo=timezone.utc)
        run_at = "2026-03-18T04:22:00+00:00"
        monkeypatch.setattr("cron.jobs._hermes_now", lambda: now)

        schedule = {"kind": "once", "run_at": run_at}

        assert compute_next_run(schedule, last_run_at=now.isoformat()) is None

    def test_interval_first_run(self):
        schedule = {"kind": "interval", "minutes": 60}
        result = compute_next_run(schedule)
        next_dt = datetime.fromisoformat(result)
        # Should be ~60 minutes from now
        assert next_dt > datetime.now().astimezone() + timedelta(minutes=59)

    def test_interval_subsequent_run(self):
        schedule = {"kind": "interval", "minutes": 30}
        last = datetime.now().astimezone().isoformat()
        result = compute_next_run(schedule, last_run_at=last)
        next_dt = datetime.fromisoformat(result)
        # Should be ~30 minutes from last run
        assert next_dt > datetime.now().astimezone() + timedelta(minutes=29)

    def test_interval_anchored_weekly_resnaps_after_drift(self):
        # Regression: Memory maintenance benchmark drifted off Sunday after a
        # delayed fire. Anchored intervals must re-snap to (weekday, time),
        # not just add `minutes` to last_run_at.
        schedule = {
            "kind": "interval",
            "minutes": 10080,
            "anchor_weekday": 6,  # Sunday (Python: Mon=0..Sun=6)
            "anchor_time": "03:00",
        }
        # last_run on a Wednesday at 22:09 PT (simulating a delayed fire)
        last_run = "2026-05-20T22:09:44-07:00"
        result = compute_next_run(schedule, last_run_at=last_run)
        next_dt = datetime.fromisoformat(result)
        assert next_dt.weekday() == 6, f"expected Sunday, got weekday {next_dt.weekday()}"
        assert (next_dt.hour, next_dt.minute) == (3, 0)
        # Must be strictly after last_run (no infinite re-fire of same moment)
        assert next_dt > datetime.fromisoformat(last_run)

    def test_interval_anchored_daily_resnaps_to_time(self):
        schedule = {
            "kind": "interval",
            "minutes": 1440,
            "anchor_time": "03:00",
        }
        last_run = "2026-05-20T22:09:44-07:00"
        result = compute_next_run(schedule, last_run_at=last_run)
        next_dt = datetime.fromisoformat(result)
        assert (next_dt.hour, next_dt.minute) == (3, 0)
        assert next_dt > datetime.fromisoformat(last_run)

    def test_interval_unanchored_uses_pure_arithmetic(self):
        # No anchor fields → preserve existing behaviour: last + period.
        schedule = {"kind": "interval", "minutes": 60}
        last_run = "2026-05-20T22:09:44-07:00"
        result = compute_next_run(schedule, last_run_at=last_run)
        next_dt = datetime.fromisoformat(result)
        expected = datetime.fromisoformat(last_run) + timedelta(minutes=60)
        assert next_dt == expected

    def test_cron_returns_future(self):
        pytest.importorskip("croniter")
        schedule = {"kind": "cron", "expr": "* * * * *"}  # every minute
        result = compute_next_run(schedule)
        assert isinstance(result, str), f"Expected ISO timestamp string, got {type(result)}"
        assert len(result) > 0
        next_dt = datetime.fromisoformat(result)
        assert isinstance(next_dt, datetime)
        assert next_dt > datetime.now().astimezone()

    def test_unknown_kind_returns_none(self):
        assert compute_next_run({"kind": "unknown"}) is None


# =========================================================================
# Job CRUD (with tmp file storage)
# =========================================================================

@pytest.fixture()
def tmp_cron_dir(tmp_path, monkeypatch):
    """Redirect cron storage to a temp directory."""
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


@pytest.fixture()
def pg_state():
    """Fresh per-test account database (surface state lives in PG since 0024).

    Same pattern as tests/elevate_cli/test_surface_state.py: drop the cached
    pool + embedded server so connect() boots against THIS test's isolated
    ELEVATE_HOME instead of reusing a pool from a previous test's tempdir.
    """
    from elevate_cli.data.connection import _reset_schema_cache

    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _pg_config(surface: str) -> dict:
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state

    with connect() as conn:
        return surface_state.get_config(conn, surface)


class TestThetaWaveSeed:
    def test_ensure_theta_wave_creates_active_agent_job(self, tmp_cron_dir, pg_state):
        from elevate_constants import get_account_data_dir

        job = ensure_theta_wave()

        assert job["name"] == "Theta Wave"
        assert job["enabled"] is True
        assert job["state"] == "scheduled"
        assert job["agent"] == "theta-wave"
        assert job["skill"] == THETA_WAVE_SKILL
        assert job["workdir"] == str(get_account_data_dir() / "system-review")
        # Config is STATE → database, not a workspace config.json.
        assert not (get_account_data_dir() / "system-review" / "config.json").exists()

        config = _pg_config("system-review")
        assert config["enabled"] is True
        assert config["auto_create_agent_cycles"] is True
        assert config["auto_modify_agent_cycles"] is True
        assert config["approval_required"] is False

    def test_ensure_theta_wave_repairs_existing_paused_seed(self, tmp_cron_dir, pg_state):
        """Repair fills in agent/workdir but RESPECTS the operator's pause.

        ensure_theta_wave used to force-resume a paused seed on every hourly
        ensure_system_jobs pass, so "pause all crons" could never keep Theta
        Wave down. Now the enabled/paused state is left exactly as-is — same
        contract as ensure_surface().
        """
        from elevate_constants import get_account_data_dir

        old = create_job(
            prompt="old theta prompt",
            schedule="0 2 * * *",
            name="Theta Wave",
            skill=THETA_WAVE_SKILL,
            deliver="local",
        )
        paused = pause_job(old["id"], reason="old opt-in seed")
        assert paused["enabled"] is False

        job = ensure_theta_wave()

        assert job["id"] == old["id"]
        # Pause respected — no silent resume within the hour.
        assert job["enabled"] is False
        assert job["paused_reason"] == "old opt-in seed"
        # Repair fields still applied.
        assert job["agent"] == "theta-wave"
        assert job["workdir"] == str(get_account_data_dir() / "system-review")

        config = _pg_config("system-review")
        assert config["auto_create_agent_cycles"] is True
        assert config["auto_modify_agent_cycles"] is True

    def test_ensure_theta_wave_never_rewrites_existing_config(self, tmp_cron_dir, pg_state):
        """An existing stored config is never overwritten by the seeder."""
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state

        with connect() as conn:
            surface_state.set_config(
                conn, "system-review",
                {"enabled": False, "auto_create_agent_cycles": False, "custom": "kept"},
            )

        ensure_theta_wave()

        config = _pg_config("system-review")
        assert config["enabled"] is False
        assert config["auto_create_agent_cycles"] is False
        assert config["custom"] == "kept"


class TestSurfaceRegistryPG:
    """Registry + workspace seeding now persist to the account database."""

    def test_load_surface_registry_seeds_builtins_idempotently(self, tmp_cron_dir, pg_state):
        from cron.jobs import SURFACE_HEARTBEAT_DEFAULTS, load_surface_registry
        from elevate_cli.data import connect
        from elevate_cli.data import surface_state
        from elevate_constants import get_account_data_dir

        reg = load_surface_registry()
        for surface in SURFACE_HEARTBEAT_DEFAULTS:
            assert surface in reg
            assert reg[surface]["builtin"] is True
            assert reg[surface]["created_by"] == "system"
            assert reg[surface]["schedule"] == SURFACE_HEARTBEAT_DEFAULTS[surface]["schedule"]
        # No surfaces.json written — registry lives in PG now.
        assert not (get_account_data_dir() / "heartbeats" / "surfaces.json").exists()

        # Idempotent: a second load returns the same registry, still one row each.
        again = load_surface_registry()
        assert set(again) == set(reg)
        with connect() as conn:
            rows = surface_state.list_registry(conn)
        assert set(rows) == set(reg)

    def test_register_surface_persists_custom_surface(self, tmp_cron_dir, pg_state):
        from cron.jobs import load_surface_registry, register_surface

        spec = {"name": "Custom Heartbeat", "schedule": "0 7 * * *",
                "builtin": False, "created_by": "user"}
        returned = register_surface("custom-x", spec)
        assert returned is spec  # public contract: echoes the caller's spec

        reg = load_surface_registry()
        assert reg["custom-x"]["name"] == "Custom Heartbeat"
        assert reg["custom-x"]["builtin"] is False
        assert reg["custom-x"]["created_by"] == "user"

    def test_seed_surface_workspace_config_in_pg_never_rewritten(self, tmp_cron_dir, pg_state):
        from cron.jobs import SURFACE_HEARTBEAT_DEFAULTS, _seed_surface_heartbeat_workspace

        spec = SURFACE_HEARTBEAT_DEFAULTS["leads"]
        ws = _seed_surface_heartbeat_workspace("leads", spec, enabled=False)

        # Markdown artifacts stay on disk…
        assert (ws / "history").is_dir()
        assert (ws / "experiments" / "history").is_dir()
        assert (ws / "learnings.md").exists()
        # …but the config is STATE → PG only, no config.json anymore.
        assert not (ws / "config.json").exists()

        config = _pg_config("leads")
        assert config["surface"] == "leads"
        assert config["enabled"] is False
        assert config["goal"] == spec["goal"]
        assert config["cadence"] == spec["schedule"]
        # Legacy experiment block kept + exactly one cycle seeded from it.
        assert config["experiment"] == spec["experiment"]
        assert len(config["cycles"]) == 1
        assert config["cycles"][0]["metric"] == spec["experiment"]["metric"]

        # Re-seeding with a different enabled flag must NOT rewrite the config.
        _seed_surface_heartbeat_workspace("leads", spec, enabled=True)
        assert _pg_config("leads")["enabled"] is False


class TestJobCRUD:
    def test_create_and_get(self, tmp_cron_dir):
        job = create_job(prompt="Check server status", schedule="30m")
        assert job["id"]
        assert job["prompt"] == "Check server status"
        assert job["enabled"] is True
        assert job["schedule"]["kind"] == "once"

        fetched = get_job(job["id"])
        assert fetched is not None
        assert fetched["prompt"] == "Check server status"

    def test_list_jobs(self, tmp_cron_dir):
        create_job(prompt="Job 1", schedule="every 1h")
        create_job(prompt="Job 2", schedule="every 2h")
        jobs = list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_normalizes_partial_legacy_records(self, tmp_cron_dir):
        save_jobs([
            {
                "id": "abc123deadbe",
                "name": None,
                "prompt": None,
                "schedule_display": None,
                "schedule": {"kind": "interval", "minutes": 60, "display": "every 60m"},
                "enabled": True,
            }
        ])

        jobs = list_jobs()

        assert jobs[0]["id"] == "abc123deadbe"
        assert jobs[0]["name"] == "abc123deadbe"
        assert jobs[0]["prompt"] == ""
        assert jobs[0]["schedule_display"] == "every 60m"
        assert jobs[0]["state"] == "scheduled"

    def test_remove_job(self, tmp_cron_dir):
        job = create_job(prompt="Temp job", schedule="30m")
        assert remove_job(job["id"]) is True
        assert get_job(job["id"]) is None

    def test_remove_nonexistent_returns_false(self, tmp_cron_dir):
        assert remove_job("nonexistent") is False

    def test_auto_repeat_for_once(self, tmp_cron_dir):
        job = create_job(prompt="One-shot", schedule="1h")
        assert job["repeat"]["times"] == 1

    def test_interval_no_auto_repeat(self, tmp_cron_dir):
        job = create_job(prompt="Recurring", schedule="every 1h")
        assert job["repeat"]["times"] is None

    def test_default_delivery_origin(self, tmp_cron_dir):
        job = create_job(
            prompt="Test", schedule="30m",
            origin={"platform": "telegram", "chat_id": "123"},
        )
        assert job["deliver"] == "origin"

    def test_default_delivery_local_no_origin(self, tmp_cron_dir):
        job = create_job(prompt="Test", schedule="30m")
        assert job["deliver"] == "local"


class TestUpdateJob:
    def test_update_name(self, tmp_cron_dir):
        job = create_job(prompt="Check server status", schedule="every 1h", name="Old Name")
        assert job["name"] == "Old Name"
        updated = update_job(job["id"], {"name": "New Name"})
        assert updated is not None
        assert isinstance(updated, dict)
        assert updated["name"] == "New Name"
        # Verify other fields are preserved
        assert updated["prompt"] == "Check server status"
        assert updated["id"] == job["id"]
        assert updated["schedule"] == job["schedule"]
        # Verify persisted to disk
        fetched = get_job(job["id"])
        assert fetched["name"] == "New Name"

    def test_update_schedule(self, tmp_cron_dir):
        job = create_job(prompt="Daily report", schedule="every 1h")
        assert job["schedule"]["kind"] == "interval"
        assert job["schedule"]["minutes"] == 60
        old_next_run = job["next_run_at"]
        new_schedule = parse_schedule("every 2h")
        updated = update_job(job["id"], {"schedule": new_schedule, "schedule_display": new_schedule["display"]})
        assert updated is not None
        assert updated["schedule"]["kind"] == "interval"
        assert updated["schedule"]["minutes"] == 120
        assert updated["schedule_display"] == "every 120m"
        assert updated["next_run_at"] != old_next_run
        # Verify persisted to disk
        fetched = get_job(job["id"])
        assert fetched["schedule"]["minutes"] == 120
        assert fetched["schedule_display"] == "every 120m"

    def test_update_enable_disable(self, tmp_cron_dir):
        job = create_job(prompt="Toggle me", schedule="every 1h")
        assert job["enabled"] is True
        updated = update_job(job["id"], {"enabled": False})
        assert updated["enabled"] is False
        fetched = get_job(job["id"])
        assert fetched["enabled"] is False

    def test_update_nonexistent_returns_none(self, tmp_cron_dir):
        result = update_job("nonexistent_id", {"name": "X"})
        assert result is None


class TestPauseResumeJob:
    def test_pause_sets_state(self, tmp_cron_dir):
        job = create_job(prompt="Pause me", schedule="every 1h")
        paused = pause_job(job["id"], reason="user paused")
        assert paused is not None
        assert paused["enabled"] is False
        assert paused["state"] == "paused"
        assert paused["paused_reason"] == "user paused"

    def test_resume_reenables_job(self, tmp_cron_dir):
        job = create_job(prompt="Resume me", schedule="every 1h")
        pause_job(job["id"], reason="user paused")
        resumed = resume_job(job["id"])
        assert resumed is not None
        assert resumed["enabled"] is True
        assert resumed["state"] == "scheduled"
        assert resumed["paused_at"] is None
        assert resumed["paused_reason"] is None


class TestResolveJobRef:
    """Name-based job lookup for CLI/tool callers (PR #2627, @buntingszn)."""

    def test_resolve_by_exact_id(self, tmp_cron_dir):
        from cron.jobs import resolve_job_ref

        job = create_job(prompt="A", schedule="1h", name="alpha")
        assert resolve_job_ref(job["id"])["id"] == job["id"]

    def test_resolve_by_name(self, tmp_cron_dir):
        from cron.jobs import resolve_job_ref

        job = create_job(prompt="A", schedule="1h", name="alpha")
        assert resolve_job_ref("alpha")["id"] == job["id"]

    def test_resolve_by_name_case_insensitive(self, tmp_cron_dir):
        from cron.jobs import resolve_job_ref

        job = create_job(prompt="A", schedule="1h", name="MyJob")
        assert resolve_job_ref("myjob")["id"] == job["id"]
        assert resolve_job_ref("MYJOB")["id"] == job["id"]

    def test_resolve_returns_none_when_not_found(self, tmp_cron_dir):
        from cron.jobs import resolve_job_ref

        create_job(prompt="A", schedule="1h", name="alpha")
        assert resolve_job_ref("does-not-exist") is None
        assert resolve_job_ref("") is None

    def test_resolve_id_wins_over_name(self, tmp_cron_dir):
        """If a job's name happens to equal another job's ID, ID match wins."""
        from cron.jobs import resolve_job_ref

        j1 = create_job(prompt="A", schedule="1h")
        # Create a second job whose name is j1's ID
        j2 = create_job(prompt="B", schedule="1h", name=j1["id"])
        # Looking up j1["id"] must return j1, not the colliding-name job j2
        assert resolve_job_ref(j1["id"])["id"] == j1["id"]
        assert resolve_job_ref(j1["id"])["id"] != j2["id"]

    def test_resolve_ambiguous_name_raises(self, tmp_cron_dir):
        """Two jobs sharing a name → refuse to pick, surface both IDs."""
        from cron.jobs import AmbiguousJobReference, resolve_job_ref

        j1 = create_job(prompt="A", schedule="1h", name="dup")
        j2 = create_job(prompt="B", schedule="1h", name="dup")
        with pytest.raises(AmbiguousJobReference) as exc_info:
            resolve_job_ref("dup")
        ids = {m["id"] for m in exc_info.value.matches}
        assert ids == {j1["id"], j2["id"]}
        # Error message mentions both IDs so the user can pick one
        assert j1["id"] in str(exc_info.value)
        assert j2["id"] in str(exc_info.value)

    def test_trigger_by_name(self, tmp_cron_dir):
        from cron.jobs import trigger_job

        job = create_job(prompt="A", schedule="1h", name="alpha")
        result = trigger_job("alpha")
        assert result is not None
        assert result["id"] == job["id"]

    def test_pause_by_name(self, tmp_cron_dir):
        job = create_job(prompt="A", schedule="1h", name="alpha")
        result = pause_job("alpha", reason="manual")
        assert result is not None
        assert result["id"] == job["id"]
        assert result["state"] == "paused"

    def test_remove_by_name(self, tmp_cron_dir):
        job = create_job(prompt="A", schedule="1h", name="alpha")
        assert remove_job("alpha") is True
        assert get_job(job["id"]) is None

    def test_mutations_refuse_ambiguous_name(self, tmp_cron_dir):
        """pause/resume/trigger/remove must refuse to act on an ambiguous name."""
        from cron.jobs import AmbiguousJobReference, trigger_job

        create_job(prompt="A", schedule="1h", name="dup")
        create_job(prompt="B", schedule="1h", name="dup")
        for fn in (pause_job, resume_job, trigger_job):
            with pytest.raises(AmbiguousJobReference):
                fn("dup")
        with pytest.raises(AmbiguousJobReference):
            remove_job("dup")


class TestMarkJobRun:
    def test_increments_completed(self, tmp_cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        mark_job_run(job["id"], success=True)
        updated = get_job(job["id"])
        assert updated["repeat"]["completed"] == 1
        assert updated["last_status"] == "ok"

    def test_repeat_limit_removes_job(self, tmp_cron_dir):
        job = create_job(prompt="Once", schedule="30m", repeat=1)
        mark_job_run(job["id"], success=True)
        # Job should be removed after hitting repeat limit
        assert get_job(job["id"]) is None

    def test_repeat_negative_one_is_infinite(self, tmp_cron_dir):
        # LLMs often pass repeat=-1 to mean "infinite/forever".
        # The job must NOT be deleted after runs when repeat <= 0.
        job = create_job(prompt="Forever", schedule="every 1h", repeat=-1)
        # -1 should be normalised to None (infinite) at create time
        assert job["repeat"]["times"] is None
        # Running it multiple times should never delete it
        for _ in range(3):
            mark_job_run(job["id"], success=True)
            assert get_job(job["id"]) is not None, "job was deleted after run despite infinite repeat"

    def test_repeat_zero_is_infinite(self, tmp_cron_dir):
        # repeat=0 should also be treated as None (infinite), not "run zero times".
        job = create_job(prompt="ZeroRepeat", schedule="every 1h", repeat=0)
        assert job["repeat"]["times"] is None
        mark_job_run(job["id"], success=True)
        assert get_job(job["id"]) is not None

    def test_error_status(self, tmp_cron_dir):
        job = create_job(prompt="Fail", schedule="every 1h")
        mark_job_run(job["id"], success=False, error="timeout")
        updated = get_job(job["id"])
        assert updated["last_status"] == "error"
        assert updated["last_error"] == "timeout"

    def test_delivery_error_tracked_separately(self, tmp_cron_dir):
        """Agent succeeds but delivery fails — both tracked independently."""
        job = create_job(prompt="Report", schedule="every 1h")
        mark_job_run(job["id"], success=True, delivery_error="platform 'telegram' not configured")
        updated = get_job(job["id"])
        assert updated["last_status"] == "ok"
        assert updated["last_error"] is None
        assert updated["last_delivery_error"] == "platform 'telegram' not configured"

    def test_delivery_error_cleared_on_success(self, tmp_cron_dir):
        """Successful delivery clears the previous delivery error."""
        job = create_job(prompt="Report", schedule="every 1h")
        mark_job_run(job["id"], success=True, delivery_error="network timeout")
        updated = get_job(job["id"])
        assert updated["last_delivery_error"] == "network timeout"
        # Next run delivers successfully
        mark_job_run(job["id"], success=True, delivery_error=None)
        updated = get_job(job["id"])
        assert updated["last_delivery_error"] is None

    def test_both_agent_and_delivery_error(self, tmp_cron_dir):
        """Agent fails AND delivery fails — both errors recorded."""
        job = create_job(prompt="Report", schedule="every 1h")
        mark_job_run(job["id"], success=False, error="model timeout",
                     delivery_error="platform 'discord' not enabled")
        updated = get_job(job["id"])
        assert updated["last_status"] == "error"
        assert updated["last_error"] == "model timeout"
        assert updated["last_delivery_error"] == "platform 'discord' not enabled"

    def test_recurring_cron_not_disabled_when_croniter_missing(self, tmp_cron_dir, monkeypatch):
        """Regression test for issue #16265.

        If the gateway runs in an env where `croniter` went missing after a
        recurring cron job was persisted, `compute_next_run()` returns None.
        `mark_job_run()` must NOT treat that as terminal completion — the job
        has to stay enabled with state=error so the user notices, rather than
        silently flipping to enabled=false, state=completed.
        """
        pytest.importorskip("croniter")  # need it to create the job
        job = create_job(prompt="Recurring", schedule="0 7,15,23 * * *")
        assert job["schedule"]["kind"] == "cron"

        # Simulate the runtime env having lost croniter between job creation
        # and this run.
        monkeypatch.setattr("cron.jobs.HAS_CRONITER", False)

        mark_job_run(job["id"], success=True)

        updated = get_job(job["id"])
        assert updated is not None, "recurring cron job was deleted"
        assert updated["enabled"] is True, (
            "recurring cron job was disabled despite croniter-missing being "
            "a runtime dep issue, not a terminal completion"
        )
        assert updated["state"] == "error"
        assert updated["state"] != "completed"
        assert updated["next_run_at"] is None
        assert updated["last_error"]
        assert "croniter" in updated["last_error"].lower()

    def test_recurring_interval_not_disabled_when_next_run_is_none(self, tmp_cron_dir, monkeypatch):
        """Defensive sibling of the cron test — any recurring schedule that
        somehow yields next_run_at=None must stay enabled with state=error.
        """
        job = create_job(prompt="Recurring", schedule="every 1h")
        assert job["schedule"]["kind"] == "interval"

        # Force compute_next_run to return None for this call — simulates
        # any future regression where a recurring schedule loses its
        # next-run computation (missing dep, corrupt schedule, etc.).
        monkeypatch.setattr("cron.jobs.compute_next_run", lambda *a, **kw: None)

        mark_job_run(job["id"], success=True)

        updated = get_job(job["id"])
        assert updated is not None
        assert updated["enabled"] is True
        assert updated["state"] == "error"
        assert updated["state"] != "completed"

    def test_oneshot_still_completes_when_next_run_is_none(self, tmp_cron_dir):
        """One-shot jobs must still flip to enabled=false, state=completed
        when next_run_at cannot be computed — the #16265 fix must not
        regress this path. We bypass create_job and craft a minimal
        one-shot record directly so that the repeat-limit branch doesn't
        pop the job before we observe the terminal-completion branch.
        """
        jobs = [{
            "id": "oneshot-test",
            "prompt": "Once",
            "schedule": {"kind": "once", "run_at": "2020-01-01T00:00:00+00:00", "display": "once"},
            "repeat": {"times": None, "completed": 0},
            "enabled": True,
            "state": "scheduled",
            "next_run_at": "2020-01-01T00:00:00+00:00",
            "last_run_at": None,
            "last_status": None,
            "last_error": None,
            "last_delivery_error": None,
            "created_at": "2020-01-01T00:00:00+00:00",
        }]
        save_jobs(jobs)

        mark_job_run("oneshot-test", success=True)

        updated = get_job("oneshot-test")
        assert updated is not None
        assert updated["next_run_at"] is None
        assert updated["enabled"] is False
        assert updated["state"] == "completed"


class TestAdvanceNextRun:
    """Tests for advance_next_run() — crash-safety for recurring jobs."""

    def test_advances_interval_job(self, tmp_cron_dir):
        """Interval jobs should have next_run_at bumped to the next future occurrence."""
        job = create_job(prompt="Recurring check", schedule="every 1h")
        # Force next_run_at to 5 minutes ago (i.e. the job is due)
        jobs = load_jobs()
        old_next = (datetime.now() - timedelta(minutes=5)).isoformat()
        jobs[0]["next_run_at"] = old_next
        save_jobs(jobs)

        result = advance_next_run(job["id"])
        assert result is True

        updated = get_job(job["id"])
        from cron.jobs import _ensure_aware, _hermes_now
        new_next_dt = _ensure_aware(datetime.fromisoformat(updated["next_run_at"]))
        assert new_next_dt > _hermes_now(), "next_run_at should be in the future after advance"

    def test_advances_cron_job(self, tmp_cron_dir):
        """Cron-expression jobs should have next_run_at bumped to the next occurrence."""
        pytest.importorskip("croniter")
        job = create_job(prompt="Daily wakeup", schedule="15 6 * * *")
        # Force next_run_at to 30 minutes ago
        jobs = load_jobs()
        old_next = (datetime.now() - timedelta(minutes=30)).isoformat()
        jobs[0]["next_run_at"] = old_next
        save_jobs(jobs)

        result = advance_next_run(job["id"])
        assert result is True

        updated = get_job(job["id"])
        from cron.jobs import _ensure_aware, _hermes_now
        new_next_dt = _ensure_aware(datetime.fromisoformat(updated["next_run_at"]))
        assert new_next_dt > _hermes_now(), "next_run_at should be in the future after advance"

    def test_skips_oneshot_job(self, tmp_cron_dir):
        """One-shot jobs should NOT be advanced — they need to retry on restart."""
        job = create_job(prompt="Run once", schedule="30m")
        original_next = get_job(job["id"])["next_run_at"]

        result = advance_next_run(job["id"])
        assert result is False

        updated = get_job(job["id"])
        assert updated["next_run_at"] == original_next, "one-shot next_run_at should be unchanged"

    def test_nonexistent_job_returns_false(self, tmp_cron_dir):
        result = advance_next_run("nonexistent-id")
        assert result is False

    def test_already_future_stays_future(self, tmp_cron_dir):
        """If next_run_at is already in the future, advance keeps it in the future (no harm)."""
        job = create_job(prompt="Future job", schedule="every 1h")
        # next_run_at is already set to ~1h from now by create_job
        advance_next_run(job["id"])
        # Regardless of return value, the job should still be in the future
        updated = get_job(job["id"])
        from cron.jobs import _ensure_aware, _hermes_now
        new_next_dt = _ensure_aware(datetime.fromisoformat(updated["next_run_at"]))
        assert new_next_dt > _hermes_now(), "next_run_at should remain in the future"

    def test_crash_safety_scenario(self, tmp_cron_dir):
        """Simulate the crash-loop scenario: after advance, the job should NOT be due."""
        job = create_job(prompt="Crash test", schedule="every 1h")
        # Force next_run_at to 5 minutes ago (job is due)
        jobs = load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=5)).isoformat()
        save_jobs(jobs)

        # Job should be due before advance
        due_before = get_due_jobs()
        assert len(due_before) == 1

        # Advance (simulating what tick() does before run_job)
        advance_next_run(job["id"])

        # Now the job should NOT be due (simulates restart after crash)
        due_after = get_due_jobs()
        assert len(due_after) == 0, "Job should not be due after advance_next_run"


class TestGetDueJobs:
    def test_past_due_within_window_returned(self, tmp_cron_dir):
        """Jobs within the dynamic grace window are still considered due (not stale).

        For an hourly job, grace = 30 min (half the period, clamped to [120s, 2h]).
        """
        job = create_job(prompt="Due now", schedule="every 1h")
        # Force next_run_at to 10 minutes ago (within the 30-min grace for hourly)
        jobs = load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=10)).isoformat()
        save_jobs(jobs)

        due = get_due_jobs()
        assert len(due) == 1
        assert due[0]["id"] == job["id"]

    def test_stale_past_due_skipped(self, tmp_cron_dir):
        """Recurring jobs past their dynamic grace window are fast-forwarded, not fired.

        For an hourly job, grace = 30 min. Setting 35 min late exceeds the window.
        """
        job = create_job(prompt="Stale", schedule="every 1h")
        # Force next_run_at to 35 minutes ago (beyond the 30-min grace for hourly)
        jobs = load_jobs()
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=35)).isoformat()
        save_jobs(jobs)

        due = get_due_jobs()
        assert len(due) == 0
        # next_run_at should be fast-forwarded to the future
        updated = get_job(job["id"])
        from cron.jobs import _ensure_aware, _hermes_now
        next_dt = _ensure_aware(datetime.fromisoformat(updated["next_run_at"]))
        assert next_dt > _hermes_now()

    def test_future_not_returned(self, tmp_cron_dir):
        create_job(prompt="Not yet", schedule="every 1h")
        due = get_due_jobs()
        assert len(due) == 0

    def test_disabled_not_returned(self, tmp_cron_dir):
        job = create_job(prompt="Disabled", schedule="every 1h")
        jobs = load_jobs()
        jobs[0]["enabled"] = False
        jobs[0]["next_run_at"] = (datetime.now() - timedelta(minutes=5)).isoformat()
        save_jobs(jobs)

        due = get_due_jobs()
        assert len(due) == 0

    def test_broken_recent_one_shot_without_next_run_is_recovered(self, tmp_cron_dir, monkeypatch):
        now = datetime(2026, 3, 18, 4, 22, 30, tzinfo=timezone.utc)
        monkeypatch.setattr("cron.jobs._hermes_now", lambda: now)

        run_at = "2026-03-18T04:22:00+00:00"
        save_jobs(
            [{
                "id": "oneshot-recover",
                "name": "Recover me",
                "prompt": "Word of the day",
                "schedule": {"kind": "once", "run_at": run_at, "display": "once at 2026-03-18 04:22"},
                "schedule_display": "once at 2026-03-18 04:22",
                "repeat": {"times": 1, "completed": 0},
                "enabled": True,
                "state": "scheduled",
                "paused_at": None,
                "paused_reason": None,
                "created_at": "2026-03-18T04:21:00+00:00",
                "next_run_at": None,
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
                "deliver": "local",
                "origin": None,
            }]
        )

        due = get_due_jobs()

        assert [job["id"] for job in due] == ["oneshot-recover"]
        assert get_job("oneshot-recover")["next_run_at"] == run_at

    def test_broken_stale_one_shot_without_next_run_is_not_recovered(self, tmp_cron_dir, monkeypatch):
        now = datetime(2026, 3, 18, 4, 30, 0, tzinfo=timezone.utc)
        monkeypatch.setattr("cron.jobs._hermes_now", lambda: now)

        save_jobs(
            [{
                "id": "oneshot-stale",
                "name": "Too old",
                "prompt": "Word of the day",
                "schedule": {"kind": "once", "run_at": "2026-03-18T04:22:00+00:00", "display": "once at 2026-03-18 04:22"},
                "schedule_display": "once at 2026-03-18 04:22",
                "repeat": {"times": 1, "completed": 0},
                "enabled": True,
                "state": "scheduled",
                "paused_at": None,
                "paused_reason": None,
                "created_at": "2026-03-18T04:21:00+00:00",
                "next_run_at": None,
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
                "deliver": "local",
                "origin": None,
            }]
        )

        assert get_due_jobs() == []
        assert get_job("oneshot-stale")["next_run_at"] is None

    def test_broken_cron_without_next_run_is_recovered(self, tmp_cron_dir, monkeypatch):
        now = datetime(2026, 3, 18, 10, 0, 0, tzinfo=timezone.utc)
        monkeypatch.setattr("cron.jobs._hermes_now", lambda: now)

        save_jobs(
            [{
                "id": "cron-recover",
                "name": "AI Daily Digest",
                "prompt": "...",
                "schedule": {"kind": "cron", "expr": "0 12 * * *", "display": "0 12 * * *"},
                "schedule_display": "0 12 * * *",
                "repeat": {"times": None, "completed": 0},
                "enabled": True,
                "state": "scheduled",
                "paused_at": None,
                "paused_reason": None,
                "created_at": "2026-03-18T09:00:00+00:00",
                "next_run_at": None,
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
                "deliver": "local",
                "origin": None,
            }]
        )

        assert get_due_jobs() == []
        recovered = get_job("cron-recover")["next_run_at"]
        assert recovered is not None
        recovered_dt = datetime.fromisoformat(recovered)
        if recovered_dt.tzinfo is None:
            recovered_dt = recovered_dt.replace(tzinfo=timezone.utc)
        assert recovered_dt > now

    def test_broken_interval_without_next_run_is_recovered(self, tmp_cron_dir, monkeypatch):
        now = datetime(2026, 3, 18, 10, 0, 0, tzinfo=timezone.utc)
        monkeypatch.setattr("cron.jobs._hermes_now", lambda: now)

        save_jobs(
            [{
                "id": "interval-recover",
                "name": "Hourly heartbeat",
                "prompt": "...",
                "schedule": {"kind": "interval", "minutes": 60, "display": "every 60m"},
                "schedule_display": "every 1h",
                "repeat": {"times": None, "completed": 0},
                "enabled": True,
                "state": "scheduled",
                "paused_at": None,
                "paused_reason": None,
                "created_at": "2026-03-18T09:00:00+00:00",
                "next_run_at": None,
                "last_run_at": None,
                "last_status": None,
                "last_error": None,
                "deliver": "local",
                "origin": None,
            }]
        )

        assert get_due_jobs() == []
        recovered = get_job("interval-recover")["next_run_at"]
        assert recovered is not None
        recovered_dt = datetime.fromisoformat(recovered)
        if recovered_dt.tzinfo is None:
            recovered_dt = recovered_dt.replace(tzinfo=timezone.utc)
        assert recovered_dt > now


class TestEnabledToolsets:
    def test_enabled_toolsets_stored(self, tmp_cron_dir):
        job = create_job(prompt="monitor", schedule="every 1h", enabled_toolsets=["web", "terminal"])
        assert job["enabled_toolsets"] == ["web", "terminal"]

    def test_enabled_toolsets_persisted(self, tmp_cron_dir):
        job = create_job(prompt="monitor", schedule="every 1h", enabled_toolsets=["web", "file"])
        fetched = get_job(job["id"])
        assert fetched["enabled_toolsets"] == ["web", "file"]

    def test_enabled_toolsets_none_when_omitted(self, tmp_cron_dir):
        job = create_job(prompt="monitor", schedule="every 1h")
        assert job["enabled_toolsets"] is None

    def test_enabled_toolsets_empty_list_normalizes_to_none(self, tmp_cron_dir):
        job = create_job(prompt="monitor", schedule="every 1h", enabled_toolsets=[])
        assert job["enabled_toolsets"] is None

    def test_enabled_toolsets_whitespace_entries_stripped(self, tmp_cron_dir):
        job = create_job(prompt="monitor", schedule="every 1h", enabled_toolsets=["web", " ", "file"])
        assert job["enabled_toolsets"] == ["web", "file"]

    def test_enabled_toolsets_updated_via_update_job(self, tmp_cron_dir):
        job = create_job(prompt="monitor", schedule="every 1h")
        update_job(job["id"], {"enabled_toolsets": ["web", "delegation"]})
        fetched = get_job(job["id"])
        assert fetched["enabled_toolsets"] == ["web", "delegation"]


class TestStallBackoff:
    """A recurring job stuck on `waiting_human`/errors must back off its tick
    instead of re-firing on schedule forever (burning a model session each
    time for zero progress). A run that makes progress resets the cadence.
    """

    WH = '{"status": "waiting_human", "blocker": "expired SkySlope login"}'
    OK = '{"status": "ok", "uploaded": 1}'

    def _mins_out(self, job):
        from cron.jobs import _ensure_aware, _hermes_now
        nr = job.get("next_run_at")
        return (_ensure_aware(datetime.fromisoformat(nr)) - _hermes_now()).total_seconds() / 60

    def test_grace_then_exponential_backoff(self, tmp_cron_dir):
        job = create_job(prompt="MLC watcher", schedule="every 10m")
        jid = job["id"]
        # First two stalls stay on the normal tick (give the human a chance).
        for _ in range(2):
            mark_job_run(jid, success=True, summary=self.WH)
        j = get_job(jid)
        assert j["stall_count"] == 2
        assert j.get("backoff_minutes") is None
        assert self._mins_out(j) <= 15  # still ~10-min cadence
        # Third stall trips backoff: 30 -> 60 -> 120 minutes.
        expected = [30, 60, 120]
        for exp in expected:
            mark_job_run(jid, success=True, summary=self.WH)
            j = get_job(jid)
            assert j["backoff_minutes"] == exp
            assert self._mins_out(j) > 20

    def test_backoff_is_capped(self, tmp_cron_dir):
        job = create_job(prompt="watcher", schedule="every 10m")
        jid = job["id"]
        for _ in range(12):
            mark_job_run(jid, success=True, summary=self.WH)
        assert get_job(jid)["backoff_minutes"] == 360  # _STALL_BACKOFF_MAX_MIN

    def test_progress_resets_cadence(self, tmp_cron_dir):
        job = create_job(prompt="watcher", schedule="every 10m")
        jid = job["id"]
        for _ in range(5):
            mark_job_run(jid, success=True, summary=self.WH)
        assert get_job(jid)["stall_count"] == 5
        # A run that makes progress clears the backoff and restores the tick.
        mark_job_run(jid, success=True, summary=self.OK)
        j = get_job(jid)
        assert j["stall_count"] == 0
        assert j.get("backoff_minutes") is None
        assert self._mins_out(j) <= 15

    def test_repeated_errors_also_back_off(self, tmp_cron_dir):
        job = create_job(prompt="watcher", schedule="every 10m")
        jid = job["id"]
        for _ in range(3):
            mark_job_run(jid, success=False, error="boom", summary="boom")
        assert get_job(jid)["backoff_minutes"] == 30

    def test_normal_runs_never_back_off(self, tmp_cron_dir):
        job = create_job(prompt="watcher", schedule="every 10m")
        jid = job["id"]
        for _ in range(5):
            mark_job_run(jid, success=True, summary=self.OK)
        j = get_job(jid)
        assert j["stall_count"] == 0
        assert j.get("backoff_minutes") is None

    def test_outcome_marker_drives_backoff_on_prose(self, tmp_cron_dir):
        # Cron now delivers human-friendly prose (no `waiting_human` token), so
        # the explicit outcome marker must drive backoff instead of the summary.
        job = create_job(prompt="watcher", schedule="every 10m")
        jid = job["id"]
        prose = "Just ran the watcher — still waiting on you to add the seller's phone number."
        for _ in range(3):
            mark_job_run(jid, success=True, summary=prose, outcome="waiting_human")
        assert get_job(jid)["backoff_minutes"] == 30

    def test_ok_marker_overrides_stray_token_in_summary(self, tmp_cron_dir):
        # An explicit ok outcome must NOT be treated as a stall even if the
        # literal token happens to appear in the prose summary.
        job = create_job(prompt="watcher", schedule="every 10m")
        jid = job["id"]
        for _ in range(4):
            mark_job_run(jid, success=True,
                         summary="done; note: this is not a waiting_human situation",
                         outcome="ok")
        j = get_job(jid)
        assert j["stall_count"] == 0
        assert j.get("backoff_minutes") is None


class TestMarkJobRunConcurrency:
    """Regression tests for concurrent parallel job state writes.

    tick() dispatches multiple jobs to separate threads simultaneously.
    Without _jobs_file_lock protecting the load→modify→save cycle in
    mark_job_run(), concurrent writes can clobber each other's updates
    (last-writer-wins), leaving some jobs with stale last_status / last_run_at.
    """

    def test_three_concurrent_mark_job_run_no_overwrites(self, tmp_cron_dir):
        """Run mark_job_run() for 3 jobs in parallel threads; all must land correctly."""
        # Create 3 distinct recurring jobs
        job_a = create_job(prompt="Job A", schedule="every 1h")
        job_b = create_job(prompt="Job B", schedule="every 1h")
        job_c = create_job(prompt="Job C", schedule="every 1h")

        errors: list = []

        def run_mark(job_id: str, success: bool, error_msg=None):
            try:
                mark_job_run(job_id, success=success, error=error_msg)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        # Fire all three concurrently
        threads = [
            threading.Thread(target=run_mark, args=(job_a["id"], True)),
            threading.Thread(target=run_mark, args=(job_b["id"], False, "timeout")),
            threading.Thread(target=run_mark, args=(job_c["id"], True)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected exceptions in worker threads: {errors}"

        # Verify each job has the correct state — no overwrites
        a = get_job(job_a["id"])
        b = get_job(job_b["id"])
        c = get_job(job_c["id"])

        assert a is not None, "Job A was unexpectedly deleted"
        assert b is not None, "Job B was unexpectedly deleted"
        assert c is not None, "Job C was unexpectedly deleted"

        assert a["last_status"] == "ok", f"Job A last_status wrong: {a['last_status']}"
        assert a["last_run_at"] is not None, "Job A last_run_at not set"
        assert a["repeat"]["completed"] == 1, f"Job A completed count wrong: {a['repeat']['completed']}"

        assert b["last_status"] == "error", f"Job B last_status wrong: {b['last_status']}"
        assert b["last_error"] == "timeout", f"Job B last_error wrong: {b['last_error']}"
        assert b["last_run_at"] is not None, "Job B last_run_at not set"
        assert b["repeat"]["completed"] == 1, f"Job B completed count wrong: {b['repeat']['completed']}"

        assert c["last_status"] == "ok", f"Job C last_status wrong: {c['last_status']}"
        assert c["last_run_at"] is not None, "Job C last_run_at not set"
        assert c["repeat"]["completed"] == 1, f"Job C completed count wrong: {c['repeat']['completed']}"

    def test_repeated_concurrent_runs_accumulate_completed_count(self, tmp_cron_dir):
        """Stress test: 10 threads each call mark_job_run on a different job once.

        The completed count for every job must be exactly 1 after all threads finish,
        confirming no thread's write was silently dropped.
        """
        n = 10
        jobs = [create_job(prompt=f"Stress job {i}", schedule="every 1h") for i in range(n)]
        errors: list = []

        def run_mark(job_id: str):
            try:
                mark_job_run(job_id, success=True)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=run_mark, args=(j["id"],)) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected exceptions: {errors}"

        for job in jobs:
            updated = get_job(job["id"])
            assert updated is not None, f"Job {job['id']} was deleted"
            assert updated["last_status"] == "ok", (
                f"Job {job['id']} has wrong last_status: {updated['last_status']}"
            )
            assert updated["repeat"]["completed"] == 1, (
                f"Job {job['id']} completed count is {updated['repeat']['completed']}, expected 1"
            )


class TestSaveJobOutput:
    def test_creates_output_file(self, tmp_cron_dir):
        output_file = save_job_output("test123", "# Results\nEverything ok.")
        assert output_file.exists()
        assert output_file.read_text() == "# Results\nEverything ok."
        assert "test123" in str(output_file)
