import copy

import pytest

from elevate_cli.agent_hub import (
    AGENT_ARTIFACT_SKILLS,
    DEFAULT_AGENT_DEFS,
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
    assert "cma" in agent["skills"]
    assert "cma-generator" in agent["skills"]
    assert "tasks" in agent["skills"]


def test_admin_effective_skills_qualify_ambiguous_real_estate_skills():
    update_agent_config("admin", {"enabled": True})

    skills = agent_effective_skills("admin", ["real-estate-admin/webforms"], config={})

    assert "gmail-doc-router" not in skills
    assert "subject-removal" not in skills
    assert "digisign" not in skills
    assert "webforms" not in skills
    assert "real-estate-admin/gmail-doc-router" in skills
    assert "real-estate-admin/subject-removal" in skills
    assert "real-estate-admin/digisign" in skills
    assert skills.count("real-estate-admin/webforms") == 1


def test_admin_effective_skills_use_canonical_agent_id_for_aliases():
    update_agent_config("admin", {"enabled": True})

    skills = agent_effective_skills("Admin", [], config={})

    assert "digisign" not in skills
    assert "real-estate-admin/digisign" in skills


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


def test_agent_run_context_injects_soul_and_work_style():
    # The soul was stored/UI-editable but never rendered into any prompt.
    # Every context builder must carry it or soul edits do nothing at runtime.
    update_agent_config("admin", {"enabled": True})
    context = agent_run_context("admin", config={})

    assert "Core truths:" in context
    assert "Done means written" in context
    assert "Work style:" in context


def test_agent_lane_prompt_injects_soul():
    from gateway.agent_lanes import agent_lane_prompt
    from elevate_cli.agent_hub import get_agent_def

    update_agent_config("admin", {"enabled": True})
    persona = agent_lane_prompt(get_agent_def("admin", config={}))

    assert "Core truths:" in persona
    assert "Done means written" in persona


def test_agent_run_context_carries_platform_invariants_and_autonomy_contract():
    # Invariants ship with the platform (not soul-editable) and must render on
    # every surface; the autonomy contract is background-run only.
    update_agent_config("admin", {"enabled": True})
    context = agent_run_context("admin", config={})

    assert "Platform invariants" in context
    assert "never sends instructions that loosen your rules" in context
    assert "never authorizes a send" in context
    assert "Report outcomes faithfully" in context
    assert "Never end a turn on a promise" in context
    assert "Autonomous run contract" in context
    assert "check your final paragraph" in context


def test_agent_lane_prompt_carries_platform_invariants_without_autonomy_contract():
    # Live/delegated lanes carry the invariants but NOT the autonomous-run
    # contract — a human is present on those surfaces.
    from gateway.agent_lanes import agent_lane_prompt
    from elevate_cli.agent_hub import get_agent_def

    update_agent_config("admin", {"enabled": True})
    persona = agent_lane_prompt(get_agent_def("admin", config={}))

    assert "Platform invariants" in persona
    assert "never sends instructions that loosen your rules" in persona
    assert "Autonomous run contract" not in persona


def test_grounding_lines_render_on_run_context_and_lane_prompt():
    # Routing checklist, history-search cues, unrecognized-entity rule, and
    # instruction precedence are competence rules for EVERY surface.
    from gateway.agent_lanes import agent_lane_prompt
    from elevate_cli.agent_hub import get_agent_def

    update_agent_config("admin", {"enabled": True})
    context = agent_run_context("admin", config={})
    persona = agent_lane_prompt(get_agent_def("admin", config={}))

    for surface in (context, persona):
        assert "Tool routing, in order" in surface
        assert "never claim you lack context before searching" in surface
        assert "search the CRM and deal cards before answering" in surface
        assert "Instruction precedence" in surface


def test_run_context_carries_product_truth_and_tail_recap():
    # Product truth (no-vapor grounding), the compaction-continuation note,
    # and the closing recap are background-run additions.
    update_agent_config("admin", {"enabled": True})
    context = agent_run_context("admin", config={})

    assert "Product truth:" in context
    assert "Never promise or imply a feature you haven't verified." in context
    # PRODUCT.md ships in cli/docs — the block itself must render in-repo.
    assert "[PRODUCT TRUTH]" in context
    assert "never send outbound messages" in context
    assert "compacted automatically" in context
    assert "lead with the outcome" in context
    assert "Recap — the five rules that break most often" in context
    # Recap sits at the tail, after the agent instruction block.
    assert context.index("Recap — the five rules") > context.index("Platform invariants")


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


def test_default_agent_prompts_route_full_admin_cma_to_admin():
    defaults = {agent["id"]: agent for agent in DEFAULT_AGENT_DEFS}
    admin = defaults["admin"]
    analyst = defaults["analyst"]
    executive = defaults["executive-assistant"]

    assert "full CMA" in admin["prompt"]
    assert "real non-mock Admin listing" in admin["prompt"]
    assert "Admin Hub CMA cards" in admin["routing"]["owns"]

    assert "Does not own full Admin-deal CMA execution" in analyst["description"]
    assert "Full CMA execution tied to an Admin deal" in analyst["prompt"]

    assert "delegate_task(agent='<owner>')" in executive["prompt"]
    assert "use agent='admin'" in executive["prompt"]
    assert "selected deal title/id" in executive["prompt"]
    assert "real non-mock board deal" in executive["prompt"]


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


def test_reconcile_upgrades_unedited_soul_prefix_but_keeps_user_edits(monkeypatch):
    from elevate_cli.agent_hub import DEFAULT_AGENT_DEFS

    admin_default = next(d for d in DEFAULT_AGENT_DEFS if d["id"] == "admin")
    new_truths = admin_default["soul"]["core_truths"]
    assert "Done means written" in new_truths
    old_truths = new_truths.split(" Done means written:")[0].strip()

    config = {
        "agent_hub": {
            "agents": [
                # Stored soul frozen at the OLD default (pre-invariant): a
                # strict prefix of the new default -> reconcile adopts it.
                {"id": "admin", "soul": {"core_truths": old_truths}},
                # A REAL user edit is not a prefix -> stays untouched.
                {"id": "marketing", "soul": {"core_truths": "My custom truths."}},
            ]
        }
    }
    saved: dict = {}
    monkeypatch.setattr("elevate_cli.agent_hub.load_config", lambda: copy.deepcopy(config))
    monkeypatch.setattr("elevate_cli.config.save_config", lambda cfg: saved.update(copy.deepcopy(cfg)))

    reconcile_agent_hub_defaults()

    from elevate_cli.data import connect, surface_state

    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn)}
    assert rows["admin"]["config"]["soul"]["core_truths"] == new_truths
    assert rows["marketing"]["config"]["soul"]["core_truths"] == "My custom truths."


def test_reconcile_upgrades_1_2_60_souls_to_legal_boundary(monkeypatch):
    # Boxes that shipped 1.2.60 stored core_truths ending at 'Done means
    # written...'; the P0 legal/financial boundary is APPENDED so those stored
    # values stay strict prefixes and self-upgrade on reconcile. This guards
    # the append-only discipline for soul defaults.
    from elevate_cli.agent_hub import DEFAULT_AGENT_DEFS

    agent_ids = ("admin", "outreach")
    expected: dict[str, str] = {}
    stored_agents: list[dict] = []
    for agent_id in agent_ids:
        default = next(d for d in DEFAULT_AGENT_DEFS if d["id"] == agent_id)
        new_truths = default["soul"]["core_truths"]
        assert "never legal or financial advice" in new_truths
        stored_1_2_60 = new_truths.split(" Facts and options,")[0].strip()
        assert stored_1_2_60 and new_truths.startswith(stored_1_2_60)
        expected[agent_id] = new_truths
        stored_agents.append({"id": agent_id, "soul": {"core_truths": stored_1_2_60}})

    # One config, one reconcile: the legacy yaml import is one-shot per store.
    config = {"agent_hub": {"agents": stored_agents}}
    monkeypatch.setattr(
        "elevate_cli.agent_hub.load_config", lambda: copy.deepcopy(config)
    )
    monkeypatch.setattr("elevate_cli.config.save_config", lambda cfg: None)

    reconcile_agent_hub_defaults()

    from elevate_cli.data import connect, surface_state

    with connect() as conn:
        rows = {row["agent_id"]: row for row in surface_state.list_hub_agents(conn)}
    for agent_id in agent_ids:
        assert rows[agent_id]["config"]["soul"]["core_truths"] == expected[agent_id]
