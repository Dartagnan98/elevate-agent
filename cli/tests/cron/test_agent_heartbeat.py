"""Tests for the per-agent heartbeat (cortextOS model ported to Elevate).

Covers cron/jobs.py:
  - ensure_agent_heartbeat_md: seeds HEARTBEAT.md (10-step, native) + companion
    files (GOALS/MEMORY/GUARDRAILS + memory/ dir); idempotent; never clobbers
    edits; role-aware (orchestrator gets the fleet-health block).
  - ensure_agent_heartbeat_cron: agent-bound 'heartbeat' job, recurring 4h
    interval, seeded paused (opt-in), idempotent; theta-wave excluded.
"""

from __future__ import annotations

import pytest

from cron import jobs


@pytest.fixture()
def iso_cron(tmp_path, monkeypatch):
    """Isolate cron job + account storage into the test tempdir."""
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "out")
    monkeypatch.setattr(
        "elevate_constants.get_account_data_dir", lambda: tmp_path / "acct"
    )
    return tmp_path


def test_heartbeat_md_seeded_with_companions(iso_cron):
    path = jobs.ensure_agent_heartbeat_md("admin")
    assert path is not None and path.exists()
    body = path.read_text()
    # All 10 numbered steps present.
    for n in range(1, 11):
        assert f"{n}." in body, f"missing step {n}"
    # Native: references real agent_bus actions, and is fully cortextOS-free
    # (the whole product was scrubbed of cortextOS naming).
    assert "update_heartbeat" in body and "get_goals" in body and "log_event" in body
    low = body.lower()
    assert "cortextos" not in low
    assert "pm2" not in low or "no external daemons / pm2" in low  # only the prohibition may mention pm2
    # Companion docs + memory dir.
    d = path.parent
    for fname in ("GOALS.md", "MEMORY.md", "GUARDRAILS.md"):
        assert (d / fname).exists()
    assert (d / "memory").is_dir()


def test_orchestrator_gets_fleet_health_block(iso_cron):
    ea = jobs.ensure_agent_heartbeat_md("executive-assistant").read_text()
    admin = jobs.ensure_agent_heartbeat_md("admin").read_text()
    assert "FLEET HEALTH" in ea
    assert "FLEET HEALTH" not in admin


def test_heartbeat_md_never_clobbers_edits(iso_cron):
    path = jobs.ensure_agent_heartbeat_md("admin")
    path.write_text("MY CUSTOM BEAT")
    again = jobs.ensure_agent_heartbeat_md("admin")
    assert again.read_text() == "MY CUSTOM BEAT"


def test_theta_wave_excluded(iso_cron):
    assert jobs.ensure_agent_heartbeat_md("theta-wave") is None
    assert jobs.ensure_agent_heartbeat_cron("theta-wave") is None


def test_heartbeat_cron_is_agent_bound_recurring_and_paused(iso_cron):
    job = jobs.ensure_agent_heartbeat_cron("admin")
    assert job is not None
    assert job.get("name") == "heartbeat"
    assert jobs._slug_agent(str(job.get("agent"))) == "admin"
    assert job.get("schedule", {}).get("kind") == "interval"
    # Opt-in: seeded paused.
    assert job.get("state") == "paused"
    # Workdir points at the agent's heartbeat dir (where HEARTBEAT.md lives).
    assert job.get("workdir") and "admin" in job["workdir"]
    # The scheduler resolves the run-as agent from this job.
    from cron.scheduler import _job_agent_id

    assert jobs._slug_agent(_job_agent_id(job)) == "admin"


def test_heartbeat_cron_idempotent(iso_cron):
    j1 = jobs.ensure_agent_heartbeat_cron("outreach")
    j2 = jobs.ensure_agent_heartbeat_cron("outreach")
    assert j1["id"] == j2["id"]
    # Exactly one heartbeat job for this agent.
    hb = [
        j
        for j in jobs.load_jobs()
        if (j.get("name") or "").lower() == "heartbeat"
        and jobs._slug_agent(str(j.get("agent") or "")) == "outreach"
    ]
    assert len(hb) == 1


def test_enabled_flag_seeds_active(iso_cron):
    job = jobs.ensure_agent_heartbeat_cron("marketing", enabled=True)
    assert job.get("state") != "paused"


def test_orchestrator_heartbeat_has_step3_and_step6(iso_cron):
    ea = jobs.ensure_agent_heartbeat_md("executive-assistant").read_text()
    # Step 3 fleet health (orchestrator only): heartbeats, approvals >4h, human tasks.
    assert "FLEET HEALTH" in ea
    assert "older than 4h" in ea
    # Step 6 org goals: morning-review trigger + write missing agents' goals.
    assert "before 10" in ea.lower()
    assert "north-star" in ea.lower() or "north star" in ea.lower()


def test_orchestrator_crons_seeded_paused_and_ea_bound(iso_cron):
    # Full system seed installs the default fleet (incl. EA) then seeds these.
    jobs.ensure_system_jobs()
    orch = [
        j
        for j in jobs.load_jobs()
        if (j.get("origin") or {}).get("source") == "orchestrator-cron"
    ]
    names = {j.get("name") for j in orch}
    assert names == {
        "check-approvals",
        "morning-review",
        "evening-review",
        "weekly-review",
        "morning-brief",
    }
    assert all(j.get("state") == "paused" for j in orch)
    assert all(jobs._slug_agent(str(j.get("agent"))) == "executive-assistant" for j in orch)
    # Idempotent.
    jobs.ensure_orchestrator_crons()
    orch2 = [
        j
        for j in jobs.load_jobs()
        if (j.get("origin") or {}).get("source") == "orchestrator-cron"
    ]
    assert len(orch2) == 5
