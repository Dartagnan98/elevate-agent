from concurrent.futures import ThreadPoolExecutor

import pytest

from gateway.orchestration import OrchestrationStore, OrchestrationValidationError


def test_orchestration_store_seeds_visible_agent_team(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    agents = store.list_agents()
    ids = {agent["agent_id"] for agent in agents}

    assert {
        "executive-assistant",
        "admin",
        "outreach",
        "marketing",
        "social-media",
    }.issubset(ids)
    executive = store.get_agent("executive-assistant")
    assert executive["tier"] == "primary"
    assert executive["reports_to"] is None
    admin = store.get_agent("admin")
    assert admin["metadata"]["job_profile"]["owns"]
    assert "checklist" in admin["metadata"]["job_profile"]["job"].lower()
    marketing = store.get_agent("marketing")
    assert "marketing emails" in marketing["metadata"]["job_profile"]["owns"]
    assert "graphics/creative direction" in marketing["metadata"]["job_profile"]["owns"]
    social = store.get_agent("social-media")
    assert social["reports_to"] == "marketing"


def test_orchestration_run_lifecycle_and_events(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    run = store.create_run(
        agent_id="marketing",
        task="Draft the new listing campaign.",
        status="running",
        mode="delegated",
        metadata={"source": "test"},
    )
    store.append_event(run["run_id"], "tool.started", "research", {"tool": "search"})
    updated = store.update_run(
        run["run_id"],
        {"status": "completed", "summary": "Campaign drafted."},
    )
    events = store.list_events(run["run_id"])
    recent_events = store.list_recent_events()
    snapshot = store.snapshot()

    assert updated["status"] == "completed"
    assert updated["completed_at"]
    assert events[0]["type"] == "run.running"
    assert events[-1]["type"] == "run.completed"
    assert recent_events[0]["type"] == "run.completed"
    assert snapshot["active_runs"] == 0
    assert snapshot["run_counts"]["marketing"]["recent_runs"] == 1
    assert snapshot["recent_events"][0]["type"] == "run.completed"


def test_orchestration_run_surfaces_handoff_routing_label(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    run = store.create_run(
        agent_id="marketing",
        task="Build the listing launch campaign.",
        status="running",
        mode="delegated",
        metadata={"handoff": {"to_agent": "marketing", "routing_label": "Agent Routing (Marketing)"}},
    )

    assert run["route_label"] == "Agent Routing (Marketing)"
    assert run["routing_label"] == "Agent Routing (Marketing)"
    assert store.get_run(run["run_id"])["route_label"] == "Agent Routing (Marketing)"


def test_orchestration_snapshot_summarizes_run_plan_graph(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    setup = store.create_run(
        run_id="setup",
        agent_id="admin",
        task="Collect listing inputs.",
        status="completed",
        metadata={"priority": "high"},
    )
    ready = store.create_run(
        run_id="ready",
        agent_id="marketing",
        task="Draft campaign.",
        status="queued",
        metadata={"blocked_by": [setup["run_id"]], "priority": "urgent"},
    )
    blocked = store.create_run(
        run_id="blocked",
        agent_id="outreach",
        task="Send nurture follow-up.",
        status="queued",
        metadata={"blocked_by": [ready["run_id"]]},
    )
    missing = store.create_run(
        run_id="missing",
        agent_id="social-media",
        task="Create social cutdowns.",
        status="queued",
        metadata={"blocked_by": ["does-not-exist"]},
    )

    graph = store.snapshot()["plan_graph"]

    assert graph["ready_run_ids"] == [ready["run_id"]]
    assert graph["blocked_run_ids"] == [blocked["run_id"], missing["run_id"]]
    assert graph["completed_run_ids"] == [setup["run_id"]]
    assert graph["unresolved_dependency_ids"] == ["does-not-exist"]
    assert graph["next_ready_run_ids"] == [ready["run_id"]]
    ready_item = next(item for item in graph["items"] if item["run_id"] == ready["run_id"])
    assert ready_item["priority"] == "urgent"


def test_orchestration_snapshot_reports_dependency_cycles(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    store.create_run(
        run_id="a",
        agent_id="admin",
        task="A",
        status="queued",
        metadata={"blocked_by": ["c"]},
    )
    store.create_run(
        run_id="b",
        agent_id="marketing",
        task="B",
        status="queued",
        metadata={"blocked_by": ["a"]},
    )
    store.create_run(
        run_id="c",
        agent_id="outreach",
        task="C",
        status="queued",
        metadata={"blocked_by": ["b"]},
    )

    graph = store.snapshot()["plan_graph"]

    assert graph["ready_run_ids"] == []
    assert graph["blocked_run_ids"] == ["a", "b", "c"]
    assert graph["cycle_run_ids"] == ["a", "b", "c"]


def test_orchestration_run_hides_route_label_for_generic_delegates(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    run = store.create_run(
        agent_id="executive-assistant",
        task="Do focused research.",
        status="running",
        mode="delegated",
        metadata={"handoff": {"to_agent": "executive-assistant", "visible_handoff": False}},
    )

    assert run["route_label"] is None
    assert run["routing_label"] is None


def test_orchestration_store_rejects_bad_ids(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    with pytest.raises(OrchestrationValidationError):
        store.create_run(agent_id="../bad", task="nope")


def test_orchestration_store_slugs_display_name_when_agent_id_missing(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    agent = store.upsert_agent({"name": "Client Care"})

    assert agent["agent_id"] == "client-care"
    assert agent["display_name"] == "Client Care"


def test_orchestration_agent_update_merges_metadata(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")
    store.upsert_agent({
        "agent_id": "client-care",
        "display_name": "Client Care",
        "metadata": {
            "job_profile": {"owns": ["follow-up"]},
            "identity": {"emoji": "spark"},
        },
    })

    agent = store.update_agent(
        "client-care",
        {"metadata": {"config": {"timezone": "America/Vancouver"}}},
    )

    assert agent["metadata"]["job_profile"] == {"owns": ["follow-up"]}
    assert agent["metadata"]["identity"] == {"emoji": "spark"}
    assert agent["metadata"]["config"] == {"timezone": "America/Vancouver"}


def test_orchestration_run_metadata_fields_are_normalized(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")
    setup = store.create_run(
        run_id="setup",
        agent_id="admin",
        task="Collect paperwork.",
        status="completed",
    )

    run = store.create_run(
        run_id="campaign",
        agent_id="marketing",
        task="Draft campaign.",
        status="queued",
        metadata={
            "depends_on": setup["run_id"],
            "assigned_to": "marketing",
            "file_scope": "knowledge/listings/123.md",
            "subsystem": "listing-launch",
            "priority": "high",
        },
    )

    assert run["blocked_by"] == [setup["run_id"]]
    assert run["assigned_to"] == "marketing"
    assert run["file_scope"] == ["knowledge/listings/123.md"]
    graph_item = next(item for item in store.snapshot()["plan_graph"]["items"] if item["run_id"] == "campaign")
    assert graph_item["assigned_to"] == "marketing"
    assert graph_item["subsystem"] == "listing-launch"

    updated = store.update_run(
        "campaign",
        {
            "blocked_by": ["setup"],
            "file_scope": ["knowledge/listings/123.md", "scripts/render.js"],
            "priority": "urgent",
        },
    )

    assert updated["metadata"]["blocked_by"] == ["setup"]
    assert updated["metadata"]["file_scope"] == ["knowledge/listings/123.md", "scripts/render.js"]
    assert updated["priority"] == "urgent"


def test_orchestration_store_rejects_orphan_events(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    with pytest.raises(OrchestrationValidationError):
        store.append_event("run_missing", "note", "orphan")


def test_orchestration_store_handles_concurrent_run_writes(tmp_path):
    store = OrchestrationStore(tmp_path / "orchestration.db")

    def worker(index: int) -> str:
        run = store.create_run(
            agent_id="outreach",
            task=f"Follow up with lead {index}",
            status="running",
            mode="stress",
        )
        store.update_run(run["run_id"], {"status": "completed", "summary": f"done {index}"})
        return run["run_id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        run_ids = list(pool.map(worker, range(32)))

    assert len(set(run_ids)) == 32
    assert store.stats()["total_runs"] == 32
    assert store.stats()["active_runs"] == 0
