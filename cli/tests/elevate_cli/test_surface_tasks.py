from __future__ import annotations

import pytest

from elevate_cli.data import connect
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data import surface_tasks


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_surface_task_dependencies_block_and_unblock():
    with connect() as conn:
        blocker = surface_tasks.create_task(conn, title="Collect MLS docs", assignee="admin")
        child = surface_tasks.create_task(
            conn,
            title="Review listing packet",
            assignee="reviewer",
            blocked_by=[blocker["id"]],
        )

        assert child["status"] == "blocked"
        assert child["blockedBy"] == [blocker["id"]]
        assert child["unresolvedDependencyIds"] == [blocker["id"]]
        assert surface_tasks.get_task(conn, blocker["id"])["blocks"] == [child["id"]]

        surface_tasks.update_task(conn, blocker["id"], {"status": "completed"})
        unblocked = surface_tasks.get_task(conn, child["id"])

    assert unblocked["status"] == "pending"
    assert unblocked["unresolvedDependencyIds"] == []


def test_surface_tasks_accept_cortext_statuses_and_approval_categories():
    with connect() as conn:
        task = surface_tasks.create_task(
            conn,
            title="Cancelled parity task",
            status="cancelled",
            assignee="admin",
        )
        external = surface_tasks.create_approval(
            conn,
            title="External update",
            category="external-comms",
            surface="admin",
        )
        deletion = surface_tasks.create_approval(
            conn,
            title="Delete stale data",
            category="data_deletion",
            surface="admin",
        )
        financial = surface_tasks.create_approval(
            conn,
            title="Budget change",
            category="cost",
            surface="admin",
        )

    assert task["status"] == "cancelled"
    assert external["category"] == "external-comms"
    assert deletion["category"] == "data-deletion"
    assert financial["category"] == "financial"


def test_surface_task_cortext_metadata_claim_audit_and_completion():
    with connect() as conn:
        task = surface_tasks.create_task(
            conn,
            title="Prepare owner brief",
            description="Use the agent task bus shape.",
            assignee="research-agent",
            created_by="orchestrator",
            org="ctrl",
            kpi_key="brief_quality",
            due_date="2030-01-02T03:04:05+00:00",
            actor="human:web",
        )
        claimed = surface_tasks.claim_task(
            conn,
            task["id"],
            agent="research-agent",
            actor="agent:research-agent",
        )
        completed = surface_tasks.complete_task(
            conn,
            task["id"],
            result="Brief ready.",
            actor="human:web",
        )
        audit = surface_tasks.read_task_audit(conn, task["id"])

    assert task["createdBy"] == "orchestrator"
    assert task["created_by"] == "orchestrator"
    assert task["org"] == "ctrl"
    assert task["kpiKey"] == "brief_quality"
    assert task["dueDate"] == "2030-01-02T03:04:05+00:00"
    assert claimed["status"] == "in_progress"
    assert claimed["claimOwner"] == "research-agent"
    assert completed["status"] == "completed"
    assert completed["result"] == "Brief ready."
    assert completed["outputs"][0]["summary"] == "Brief ready."
    assert [event["event"] for event in audit] == ["create", "claim", "complete"]


def test_surface_task_claim_rejects_double_claim_and_dependencies():
    with connect() as conn:
        blocker = surface_tasks.create_task(conn, title="Collect context", assignee="admin")
        task = surface_tasks.create_task(conn, title="Wait for context", assignee="worker", blocked_by=[blocker["id"]])

        with pytest.raises(ValueError, match="unresolved dependencies"):
            surface_tasks.claim_task(conn, task["id"], agent="worker")

        surface_tasks.update_task(conn, blocker["id"], {"status": "completed"})
        claimed = surface_tasks.claim_task(conn, task["id"], agent="worker")
        with pytest.raises(ValueError, match="already claimed|not pending"):
            surface_tasks.claim_task(conn, task["id"], agent="other-worker")

    assert claimed["status"] == "in_progress"


def test_surface_task_stale_archive_and_compact_reports():
    with connect() as conn:
        old_pending = surface_tasks.create_task(conn, title="Old pending", assignee="admin")
        old_human = surface_tasks.create_task(conn, title="Old human", assignee="human", project="human-tasks")
        old_running = surface_tasks.create_task(conn, title="Old running", assignee="admin")
        old_done = surface_tasks.create_task(conn, title="Old done", assignee="admin")
        surface_tasks.update_task(conn, old_running["id"], {"status": "in_progress"})
        surface_tasks.complete_task(conn, old_done["id"], result="Done")
        conn.execute(
            "UPDATE surface_tasks SET created_at = ?, updated_at = ? WHERE id IN (?, ?)",
            (
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
                old_pending["id"],
                old_human["id"],
            ),
        )
        conn.execute(
            "UPDATE surface_tasks SET updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", old_running["id"]),
        )
        conn.execute(
            "UPDATE surface_tasks SET completed_at = ?, updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00", old_done["id"]),
        )

        stale = surface_tasks.check_stale_tasks(conn)
        archive = surface_tasks.archive_tasks(conn, older_than_days=7)
        compact = surface_tasks.compact_tasks(conn, older_than_days=30)
        archived_done = surface_tasks.get_task(conn, old_done["id"])

    assert old_pending["id"] in {task["id"] for task in stale["stale_pending"]}
    assert old_human["id"] in {task["id"] for task in stale["stale_human"]}
    assert old_running["id"] in {task["id"] for task in stale["stale_in_progress"]}
    assert archive["archived"] == 1
    assert archived_done["archived"] is True
    assert compact["archived"] == []


def test_surface_approval_resolution_unblocks_policy_blocked_task():
    import elevate_cli.agent_hub as agent_hub

    agent_hub.create_agent_config(
        {
            "id": "approval-resume-agent",
            "name": "Approval Resume Agent",
            "safety": {"always_ask": ["create_task"]},
        }
    )

    with connect() as conn:
        task = surface_tasks.create_task(
            conn,
            title="Approval-gated task",
            assignee="admin",
            actor="agent:approval-resume-agent",
            actor_agent_id="approval-resume-agent",
        )
        approval = surface_tasks.list_approvals(conn, status="pending", surface="approval-resume-agent")[0]
        resolved = surface_tasks.resolve_approval(conn, approval["id"], decision="approve", resolved_by="operator")
        unblocked = surface_tasks.get_task(conn, task["id"])
        audit = surface_tasks.read_task_audit(conn, task["id"])

    assert resolved["status"] == "approved"
    assert unblocked["status"] == "pending"
    assert unblocked["needsApproval"] is False
    assert audit[-1]["event"] == "approval_approved"


def test_surface_task_blocks_patch_updates_inverse_edge():
    with connect() as conn:
        blocker = surface_tasks.create_task(conn, title="Prep CMA", assignee="research")
        child = surface_tasks.create_task(conn, title="Write client brief", assignee="admin")

        updated = surface_tasks.update_task(conn, blocker["id"], {"blocks": [child["id"]]})
        child_after = surface_tasks.get_task(conn, child["id"])

    assert updated["blocks"] == [child["id"]]
    assert child_after["blockedBy"] == [blocker["id"]]
    assert child_after["status"] == "blocked"


def test_surface_task_dependency_cycle_is_rejected():
    with connect() as conn:
        first = surface_tasks.create_task(conn, title="First", assignee="admin")
        second = surface_tasks.create_task(
            conn,
            title="Second",
            assignee="reviewer",
            blocked_by=[first["id"]],
        )

        with pytest.raises(ValueError, match="dependency cycle"):
            surface_tasks.update_task(conn, first["id"], {"blocked_by": [second["id"]]})

        first_after = surface_tasks.get_task(conn, first["id"])
        second_after = surface_tasks.get_task(conn, second["id"])

    assert first_after["blockedBy"] == []
    assert first_after["blocks"] == [second["id"]]
    assert second_after["blockedBy"] == [first["id"]]


def test_agent_created_surface_task_policy_creates_native_approval():
    import elevate_cli.agent_hub as agent_hub

    agent_hub.create_agent_config(
        {
            "id": "task-policy-agent",
            "name": "Task Policy Agent",
            "safety": {"always_ask": ["create_task"]},
        }
    )

    with connect() as conn:
        task = surface_tasks.create_task(
            conn,
            title="Draft seller update",
            assignee="marketing",
            actor="task-policy-agent",
            actor_agent_id="task-policy-agent",
        )
        approvals = surface_tasks.list_approvals(conn, status="pending", surface="task-policy-agent")

    assert task["status"] == "blocked"
    assert task["needsApproval"] is True
    assert task["policyDecision"]["decision"] == "approval_required"
    assert "Agent safety policy requires dashboard approval" in task["notes"]
    assert len(approvals) == 1
    assert "create task" in approvals[0]["description"]


def test_agent_surface_task_update_and_delete_policy_block_without_mutation():
    import elevate_cli.agent_hub as agent_hub

    agent_hub.create_agent_config(
        {
            "id": "task-delete-agent",
            "name": "Task Delete Agent",
            "safety": {"always_ask": ["complete_task"]},
        }
    )

    with connect() as conn:
        task = surface_tasks.create_task(conn, title="Sensitive cleanup", assignee="admin")
        completed = surface_tasks.update_task(
            conn,
            task["id"],
            {"status": "completed"},
            actor="task-delete-agent",
            actor_agent_id="task-delete-agent",
        )
        delete_result = surface_tasks.request_delete_task(
            conn,
            task["id"],
            actor="task-delete-agent",
            actor_agent_id="task-delete-agent",
        )
        still_there = surface_tasks.get_task(conn, task["id"])
        approvals = surface_tasks.list_approvals(conn, status="pending", surface="task-delete-agent")

    assert completed["status"] == "blocked"
    assert completed["needsApproval"] is True
    assert completed["completedAt"] is None
    assert delete_result["approvalRequired"] is True
    assert delete_result["ok"] is False
    assert still_there is not None
    assert still_there["status"] == "blocked"
    assert len(approvals) == 2
