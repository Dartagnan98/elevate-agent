import copy

import pytest

from elevate_cli.agent_hub import (
    AGENT_ARTIFACT_SKILLS,
    SHARED_AGENT_SKILLS,
    agent_effective_skills,
    agent_run_context,
    create_agent_config,
    get_agent_def,
    reconcile_agent_hub_defaults,
    update_agent_config,
)
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    """Agent defs are PG-backed (hub_agents) — bind the pool to this test's
    ELEVATE_HOME instead of a previous test's torn-down embedded server."""
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_builtin_agents_include_shared_artifact_capabilities():
    # Admin is an installable default — patching it installs a fresh copy.
    update_agent_config("admin", {"enabled": True})
    agent = get_agent_def("admin", config={})

    assert agent is not None
    for skill in AGENT_ARTIFACT_SKILLS:
        assert skill in agent["skills"]
    assert "admin-agent" in agent["skills"]
    assert "tasks" in agent["skills"]


def test_effective_skills_merge_shared_agent_and_run_specific_without_duplicates():
    # Agent definitions persist in the account DB now (hub_agents), not in a
    # caller-supplied config dict.
    create_agent_config({"id": "custom", "name": "Custom", "skills": ["custom-skill", "nano-pdf"]})

    skills = agent_effective_skills("custom", ["job-skill", "custom-skill"], config={})

    assert skills[: len(SHARED_AGENT_SKILLS)] == list(SHARED_AGENT_SKILLS)
    assert skills.count("nano-pdf") == 1
    assert skills.count("custom-skill") == 1
    assert skills[-1] == "job-skill"


def test_unknown_agent_effective_skills_keep_only_explicit_run_skills():
    assert agent_effective_skills("missing-agent", ["job-skill"], config={}) == ["job-skill"]


def test_agent_run_context_names_specialization_handoff_and_artifacts():
    update_agent_config("admin", {"enabled": True})
    context = agent_run_context("admin", config={})

    assert "AGENT HUB CONTEXT" in context
    assert "Admin" in context
    assert "outside this agent's specialization" in context
    assert "handoff/task" in context
    assert "PDFs, presentations, diagrams, and graphics" in context


def test_analyst_and_theta_wave_are_backend_defaults():
    update_agent_config("analyst", {"enabled": True})
    update_agent_config("theta-wave", {"enabled": True})
    analyst = get_agent_def("analyst", config={})
    theta_wave = get_agent_def("theta-wave", config={})

    assert analyst is not None
    assert theta_wave is not None
    assert "catalog-browse" in analyst["skills"]
    assert "theta-wave" in theta_wave["skills"]
    assert theta_wave["routing"]["escalation_target"] == "executive-assistant"


def test_reconcile_agent_hub_defaults_repairs_persisted_rows_without_overwriting_user_state(monkeypatch):
    config = {
        "agent_hub": {
            "agents": [
                {
                    "id": "admin",
                    "name": "My Admin",
                    "enabled": False,
                    "skills": ["custom-admin-skill"],
                    "routing": {"owns": ["custom admin lane"]},
                }
            ]
        }
    }
    saved: dict = {}

    # The legacy config.yaml shape is consumed once by the one-shot import;
    # reconcile then repairs the persisted hub_agents rows, never the yaml.
    monkeypatch.setattr("elevate_cli.agent_hub.load_config", lambda: copy.deepcopy(config))
    monkeypatch.setattr("elevate_cli.config.save_config", lambda cfg: saved.update(copy.deepcopy(cfg)))

    report = reconcile_agent_hub_defaults()

    assert report["changed"] is True
    # Only the always-on agent (EA) is auto-seeded; analyst/theta-wave are now
    # installable defaults, not auto-created.
    assert "executive-assistant" in report["created"]
    assert "analyst" not in report["created"]
    assert "theta-wave" not in report["created"]
    # Only the default_agent housekeeping key goes back to config.yaml.
    assert saved["agent_hub"]["default_agent"] == "executive-assistant"
    assert saved["agent_hub"]["agents"] == config["agent_hub"]["agents"]  # frozen archive

    from elevate_cli.data import connect, surface_state

    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn)}
    admin = rows["admin"]["config"]
    assert rows["admin"]["builtin"] is True
    assert admin["name"] == "My Admin"
    assert admin["enabled"] is False
    assert "custom-admin-skill" in admin["skills"]
    assert "admin-agent" in admin["skills"]
    assert "surface-heartbeat" in admin["skills"]
    assert "custom admin lane" in admin["routing"]["owns"]
    assert "deal files" in admin["routing"]["owns"]
