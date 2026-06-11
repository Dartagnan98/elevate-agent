"""agent_recent_activity_digest — interactive continuity for heartbeat/cron work."""
import os
import pytest
from elevate_cli import agent_hub


@pytest.fixture()
def _acct(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    # fresh account dir; no activity yet
    return tmp_path


def test_digest_empty_when_no_activity(_acct):
    assert agent_hub.agent_recent_activity_digest("admin") == ""


def test_digest_surfaces_agent_activity(_acct):
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state
    with connect() as conn:
        surface_state.append_activity(conn, "admin", "agent_heartbeat", "Drafted 2 follow-ups")
        surface_state.set_heartbeat(conn, "admin", {"agent": "admin", "status": "active", "current_task": "lead follow-ups", "at": "2026-06-11T18:00:00Z"})
    d = agent_hub.agent_recent_activity_digest("admin")
    assert "RECENT AUTONOMOUS ACTIVITY" in d
    assert "Drafted 2 follow-ups" in d
    assert "lead follow-ups" in d  # its own last heartbeat


def test_orchestrator_sees_fleet(_acct):
    from elevate_cli.data import connect
    from elevate_cli.data import surface_state
    with connect() as conn:
        surface_state.append_activity(conn, "outreach", "agent_heartbeat", "Scraped 12 new buyers")
        surface_state.set_heartbeat(conn, "outreach", {"agent": "outreach", "status": "active", "current_task": "buyer search", "at": "2026-06-11T18:00:00Z"})
    ea = agent_hub.agent_recent_activity_digest("executive-assistant")
    assert "outreach" in ea
    assert "Scraped 12 new buyers" in ea
