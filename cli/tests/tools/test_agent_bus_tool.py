import json

from tools.agent_bus_tool import _agent_bus_tool


def _call(body):
    return json.loads(_agent_bus_tool(body))


def test_agent_bus_task_lifecycle_uses_surface_tasks():
    created = _call(
        {
            "action": "create_task",
            "agent_id": "executive-assistant",
            "title": "Review Cortext parity",
            "description": "Check the native bus mapping.",
            "priority": "high",
        }
    )
    assert created["success"] is True
    task = created["task"]
    assert task["title"] == "Review Cortext parity"
    assert task["assignee"] == "executive-assistant"
    assert task["priority"] == "high"

    completed = _call(
        {
            "action": "complete_task",
            "agent_id": "executive-assistant",
            "task_id": task["id"],
            "result": "Mapped into native Elevate stores.",
        }
    )
    assert completed["success"] is True
    assert completed["task"]["status"] == "completed"
    assert completed["task"]["outputs"][0]["summary"] == "Mapped into native Elevate stores."


def test_agent_bus_approval_activity_and_heartbeat_are_native():
    approval = _call(
        {
            "action": "create_approval",
            "agent_id": "executive-assistant",
            "title": "Send external update",
            "category": "external-comms",
            "context": "Draft is ready for review.",
        }
    )
    assert approval["success"] is True
    assert approval["approval"]["status"] == "pending"
    assert approval["approval"]["surface"] == "executive-assistant"
    assert approval["approval"]["category"] == "external-comms"

    activity = _call(
        {
            "action": "post_activity",
            "agent_id": "executive-assistant",
            "event": "parity_check",
            "message": "Native bus parity checked.",
            "metadata": {"source": "test"},
        }
    )
    assert activity["success"] is True
    assert activity["event"]["event"] == "parity_check"

    heartbeat = _call(
        {
            "action": "update_heartbeat",
            "agent_id": "executive-assistant",
            "message": "WORKING ON: parity checks",
        }
    )
    assert heartbeat["success"] is True
    assert heartbeat["heartbeat"]["agent"] == "executive-assistant"

    listed = _call(
        {
            "action": "read_heartbeats",
            "agent_id": "executive-assistant",
        }
    )
    assert listed["success"] is True
    assert listed["items"][0]["summary"] == "WORKING ON: parity checks"


def test_agent_bus_experiment_create_run_evaluate_and_context():
    created = _call(
        {
            "action": "create_experiment",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
            "title": "Try native heartbeat summary",
            "hypothesis": "Visible heartbeat summaries reduce stale work.",
            "metric": "stale_items",
            "direction": "lower",
            "baseline_value": 5,
        }
    )
    assert created["success"] is True
    assert created["experiment"]["surface"] == "executive-assistant"
    assert created["experiment"]["status"] == "proposed"

    started = _call(
        {
            "action": "run_experiment",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
            "experiment_id": created["experiment"]["id"],
            "changes_description": "Show summaries on heartbeat cards.",
        }
    )
    assert started["success"] is True
    assert started["experiment"]["status"] == "running"
    assert started["experiment"]["changes_description"] == "Show summaries on heartbeat cards."

    evaluated = _call(
        {
            "action": "evaluate_experiment",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
            "experiment_id": created["experiment"]["id"],
            "measured_value": 3,
            "learning": "Useful enough to keep.",
        }
    )
    assert evaluated["success"] is True
    assert evaluated["experiment"]["decision"] == "keep"
    assert evaluated["experiment"]["status"] == "completed"
    assert evaluated["experiment"]["result_value"] == 3

    listed = _call(
        {
            "action": "list_experiments",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
        }
    )
    assert listed["success"] is True
    assert listed["experiments"]["active"] is None
    assert listed["experiments"]["history"][0]["decision"] == "keep"

    context = _call(
        {
            "action": "gather_experiment_context",
            "agent_id": "executive-assistant",
            "surface": "executive-assistant",
        }
    )
    assert context["success"] is True
    assert context["context"]["keeps"] == 1
    assert "Useful enough to keep." in context["context"]["learnings"]


def test_agent_bus_cycle_management_is_native():
    created = _call(
        {
            "action": "create_cycle",
            "agent_id": "theta-wave",
            "surface": "admin",
            "name": "Admin stale blocker reduction",
            "metric": "stale_blockers",
            "metric_type": "quantitative",
            "direction": "lower",
            "window": "24h",
            "every_n_runs": 2,
            "measurement": "Count unresolved blockers after the heartbeat.",
            "approval_required": True,
        }
    )
    assert created["success"] is True
    assert created["surface"] == "admin"
    cycle = created["cycles"][0]
    assert cycle["name"] == "Admin stale blocker reduction"
    assert cycle["metric"] == "stale_blockers"
    assert cycle["approval_required"] is True

    modified = _call(
        {
            "action": "modify_cycle",
            "agent_id": "theta-wave",
            "surface": "admin",
            "name": "Admin stale blocker reduction",
            "enabled": False,
            "every_n_runs": 5,
        }
    )
    assert modified["success"] is True
    assert modified["cycles"][0]["enabled"] is False
    assert modified["cycles"][0]["every_n_runs"] == 5

    listed = _call(
        {
            "action": "list_cycles",
            "agent_id": "theta-wave",
            "surface": "admin",
        }
    )
    assert listed["success"] is True
    assert listed["cycles"][0]["name"] == "Admin stale blocker reduction"

    removed = _call(
        {
            "action": "remove_cycle",
            "agent_id": "theta-wave",
            "surface": "admin",
            "name": "Admin stale blocker reduction",
        }
    )
    assert removed["success"] is True
    assert removed["cycles"] == []


def test_agent_bus_memory_write_and_list_are_native():
    agent_id = "memory-bus-agent"
    written = _call(
        {
            "action": "write_memory",
            "agent_id": agent_id,
            "content": "Client prefers Friday updates. api_key=super-secret-value",
            "source": "test",
            "scopes": ["client-notes"],
        }
    )
    assert written["success"] is True
    assert written["memory"]["agent"] == agent_id
    assert written["memory"]["seeded"] == 1

    listed = _call(
        {
            "action": "list_memory",
            "agent_id": agent_id,
        }
    )
    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["items"][0]["fact"] == "Client prefers Friday updates. api_key=[redacted]"
    assert "super-secret-value" not in json.dumps(listed)


def test_agent_bus_claim_audit_stale_and_archive_task_actions():
    created = _call(
        {
            "action": "create_task",
            "agent_id": "executive-assistant",
            "title": "Claimable native task",
            "assignee": "executive-assistant",
            "created_by": "orchestrator",
            "org": "ctrl",
            "due_date": "2030-01-01T00:00:00+00:00",
        }
    )
    assert created["success"] is True
    task_id = created["task"]["id"]
    assert created["task"]["createdBy"] == "orchestrator"
    assert created["task"]["dueDate"] == "2030-01-01T00:00:00+00:00"

    claimed = _call(
        {
            "action": "claim_task",
            "agent_id": "executive-assistant",
            "task_id": task_id,
        }
    )
    assert claimed["success"] is True
    assert claimed["task"]["status"] == "in_progress"
    assert claimed["task"]["claimOwner"] == "executive-assistant"

    completed = _call(
        {
            "action": "complete_task",
            "agent_id": "executive-assistant",
            "task_id": task_id,
            "result": "Task finished.",
        }
    )
    assert completed["success"] is True
    assert completed["task"]["result"] == "Task finished."

    audit = _call(
        {
            "action": "read_task_audit",
            "agent_id": "executive-assistant",
            "task_id": task_id,
        }
    )
    assert audit["success"] is True
    assert [event["event"] for event in audit["items"]] == ["create", "claim", "complete"]

    stale = _call({"action": "check_stale_tasks", "agent_id": "executive-assistant"})
    assert stale["success"] is True
    assert "stale_pending" in stale["report"]

    archive = _call({"action": "archive_tasks", "agent_id": "executive-assistant", "dry_run": True})
    assert archive["success"] is True
    assert archive["report"]["dry_run"] is True
