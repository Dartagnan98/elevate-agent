"""Fail-closed scheduled execution policy for the exact Realtor Beta."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import cron.scheduler as scheduler
import elevate_cli.agent_worker as agent_worker
import elevate_cli.data as elevate_data
import run_agent


_DISABLED_CODE = "beta_scheduled_execution_disabled"


def _job(*, no_agent: bool = False) -> dict:
    job = {
        "id": "policy-job",
        "name": "Policy job",
        "prompt": "Do scheduled work.",
        "schedule_display": "Every hour",
        "deliver": "local",
    }
    if no_agent:
        job.update({"no_agent": True, "script": "watchdog.py"})
    return job


def test_exact_beta_run_job_blocks_agent_and_script_before_any_runtime_side_effect(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    @contextmanager
    def forbidden_profile_context(*_args, **_kwargs):
        raise AssertionError("profile context must not start in Realtor Beta")
        yield  # pragma: no cover

    monkeypatch.setattr(scheduler, "_job_profile_context", forbidden_profile_context)
    script = MagicMock(side_effect=AssertionError("scheduled script must not run"))
    monkeypatch.setattr(scheduler, "_run_job_script", script)
    agent = MagicMock(side_effect=AssertionError("scheduled agent must not be created"))
    monkeypatch.setattr(run_agent, "AIAgent", agent)

    for job in (_job(), _job(no_agent=True)):
        success, output, final_response, error = scheduler.run_job(job)
        assert success is False
        assert final_response == ""
        assert error is not None and _DISABLED_CODE in error
        assert "**Status:** disabled" in output
        assert "No agent, script, provider, tool, session, or delivery was started." in output

    script.assert_not_called()
    agent.assert_not_called()


def test_exact_beta_tick_stops_before_lock_due_job_and_audit_mutations(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    forbidden = MagicMock(side_effect=AssertionError("scheduler side effect must not start"))
    for name in (
        "_get_lock_paths",
        "ensure_system_jobs",
        "_maybe_reap_idle_sessions",
        "get_due_jobs",
        "advance_next_run",
        "_precreate_cron_session",
        "run_job",
        "save_job_output",
        "mark_job_run",
        "_deliver_result",
    ):
        monkeypatch.setattr(scheduler, name, forbidden)

    assert scheduler.tick(verbose=False) == 0
    forbidden.assert_not_called()


def test_exact_beta_worker_records_disabled_without_draining_or_recovering_queues(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    written: list[dict] = []
    monkeypatch.setattr(agent_worker, "_write_status", lambda status: written.append(status))
    monkeypatch.setattr(
        agent_worker,
        "_lock_path",
        MagicMock(side_effect=AssertionError("worker lock must not be opened")),
    )

    status = agent_worker.tick(
        actor="test",
        reason="heartbeat",
        config={"agent_worker": {"enabled": True}},
    )

    assert status["state"] == "disabled"
    assert status["enabled"] is False
    assert status["configuredEnabled"] is True
    assert _DISABLED_CODE in status["disabledReason"]
    assert _DISABLED_CODE in status["lastError"]
    assert status["drained"] == {"handoffs": 0, "adminRuns": 0}
    assert status["recovered"] == {"staleHandoffs": 0, "staleAdminRuns": 0}
    assert written == [status]


def test_exact_beta_wake_and_background_loop_are_refused_without_thread_or_wake_file(
    monkeypatch,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    written: list[dict] = []
    monkeypatch.setattr(agent_worker, "_write_status", lambda status: written.append(status))
    monkeypatch.setattr(
        agent_worker,
        "_wake_path",
        MagicMock(side_effect=AssertionError("wake request must not be persisted")),
    )
    thread = MagicMock(side_effect=AssertionError("worker thread must not be created"))
    monkeypatch.setattr(agent_worker.threading, "Thread", thread)

    wake = agent_worker.request_wake(reason="test-wake", actor="test")
    loop = agent_worker.start_background_loop(
        config={"agent_worker": {"enabled": True}}
    )

    assert wake["state"] == "disabled"
    assert wake["wake"]["enabled"] is False
    assert wake["wake"]["pending"] is False
    assert _DISABLED_CODE in wake["lastError"]
    assert loop["state"] == "disabled"
    assert loop["loop"]["running"] is False
    assert _DISABLED_CODE in loop["lastError"]
    thread.assert_not_called()
    assert written == [wake, loop]


def test_stable_run_job_keeps_no_agent_script_execution(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    script = MagicMock(return_value=(True, "stable watchdog output"))
    monkeypatch.setattr(scheduler, "_run_job_script", script)

    success, output, final_response, error = scheduler.run_job(_job(no_agent=True))

    assert (success, final_response, error) == (True, "stable watchdog output", None)
    assert "stable watchdog output" in output
    script.assert_called_once_with("watchdog.py")


def test_stable_tick_and_worker_config_remain_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    lock_dir = tmp_path / "cron"
    lock_dir.mkdir()
    monkeypatch.setattr(
        scheduler,
        "_get_lock_paths",
        lambda: (lock_dir, lock_dir / ".tick.lock"),
    )
    job = _job()
    monkeypatch.setattr(scheduler, "get_due_jobs", lambda: [job])
    advance = MagicMock()
    run = MagicMock(return_value=(True, "stable output", "stable response", None))
    mark = MagicMock()
    monkeypatch.setattr(scheduler, "advance_next_run", advance)
    monkeypatch.setattr(scheduler, "run_job", run)
    monkeypatch.setattr(scheduler, "save_job_output", lambda *_args: tmp_path / "run.md")
    monkeypatch.setattr(scheduler, "mark_job_run", mark)
    monkeypatch.setattr(scheduler, "_deliver_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_record_agent_handoff_delivery", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_precreate_cron_session", lambda *_args: False)
    monkeypatch.setattr(scheduler, "_should_ensure_system_jobs", lambda: False)
    monkeypatch.setattr(scheduler, "_maybe_reap_idle_sessions", lambda: None)

    assert scheduler.tick(verbose=False) == 1
    advance.assert_called_once_with("policy-job")
    run.assert_called_once()
    mark.assert_called_once()
    assert agent_worker._config({"agent_worker": {"enabled": True}})["enabled"] is True


def test_stable_worker_still_drains_scheduled_queues(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")

    @contextmanager
    def connect():
        yield object()

    monkeypatch.setattr(agent_worker, "_lock_path", lambda: tmp_path / ".worker.lock")
    monkeypatch.setattr(agent_worker, "_write_status", lambda _status: None)
    monkeypatch.setattr(elevate_data, "connect", connect)
    monkeypatch.setattr(elevate_data, "mark_stale_agent_handoffs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(elevate_data, "mark_stale_action_runs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        elevate_data,
        "drain_queued_agent_handoffs",
        lambda *_args, **_kwargs: [{"id": "handoff-one"}],
    )
    monkeypatch.setattr(
        elevate_data,
        "drain_queued_action_runs",
        lambda *_args, **_kwargs: [{"id": "admin-one"}],
    )

    status = agent_worker.tick(
        actor="test",
        reason="manual",
        config={"agent_worker": {"enabled": True}},
    )

    assert status["state"] == "ok"
    assert status["enabled"] is True
    assert status["disabledReason"] == ""
    assert status["drained"] == {"handoffs": 1, "adminRuns": 1}
