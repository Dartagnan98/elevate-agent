from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import (
    agent_handoff_summary,
    approve_agent_handoff,
    complete_admin_setup,
    connect,
    create_agent_comms_message,
    create_agent_handoff,
    create_deal,
    dispatch_agent_handoff_to_cron,
    get_agent_comms_channel,
    get_admin_setup,
    get_agent_handoff,
    list_agent_comms_channels,
    list_agent_comms_messages,
    list_agent_handoffs,
    list_deal_events,
    list_deal_tasks,
    list_deal_action_runs,
    mark_stale_agent_handoffs,
    queue_action_run,
    record_agent_handoff_cron_delivery,
    record_agent_handoff_message,
    record_agent_handoff_result,
    update_admin_setup,
)
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def client():
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    yield c
    if hasattr(app.state, "bound_host"):
        del app.state.bound_host


def _complete_admin_setup():
    def item_payload(item):
        value = None
        if item["key"] in {"approval_channel", "email", "calendar", "drive", "crm"}:
            value = {
                "verification": {
                    "checkedAt": "2026-05-07T00:00:00+00:00",
                    "signals": ["test connector verified"],
                }
            }
        elif item["key"] == "browser_workflows":
            value = {
                "mode": "browser-use",
                "notes": "Use saved browser profile for portal tests.",
                "playbooks": {
                    "mls": {"provider": "Matrix", "loginUrl": "https://mls.example", "credentialRef": "test"},
                    "compliance": {"provider": "SkySlope", "loginUrl": "https://skyslope.example", "credentialRef": "test"},
                    "showing": {"provider": "ShowingTime", "loginUrl": "https://showing.example", "credentialRef": "test"},
                },
            }
        elif item["key"] == "photo_processing":
            value = {"provider": "Drive + Nano Banana", "source": "google-drive"}
        return {
            "key": item["key"],
            "status": "manual" if item["key"] == "fintrac_workflow" else "configured",
            "provider": "test",
            "value": value,
        }

    with connect() as conn:
        setup = get_admin_setup(conn)
        update_admin_setup(
            conn,
            profile={
                "realtorLegalName": "Test Realtor",
                "brokerageName": "Test Brokerage",
                "province": "BC",
                "approvalChannel": "telegram:test",
            },
            items=[item_payload(item) for item in setup["items"] if item["required"]],
        )
        complete_admin_setup(conn)


def _configure_agent_telegram(monkeypatch, agent_id: str = "admin", channel: str = "admin-chat-123"):
    key = agent_id.upper().replace("-", "_")
    monkeypatch.setenv(f"ELEVATE_AGENT_{key}_TELEGRAM_BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv(f"ELEVATE_AGENT_{key}_TELEGRAM_CHANNEL", channel)


def test_agent_handoff_create_dispatch_and_idempotency(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch)

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Review listing docs",
            task="Check the MLC package and ask for approval if anything is missing.",
            priority="high",
            payload={"expectedReturn": "missing docs and next task"},
            idempotency_key="handoff-1",
            create_cron_job=True,
            actor="executive-assistant",
        )
        same = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            task="Duplicate retry",
            idempotency_key="handoff-1",
            create_cron_job=True,
        )

    assert handoff["status"] == "running"
    assert handoff["cronJobId"] == "cron-1"
    assert same["id"] == handoff["id"]
    assert len(created_jobs) == 1
    assert created_jobs[0]["agent"] == "admin"
    assert created_jobs[0]["deliver"] == "telegram:admin-chat-123"
    assert created_jobs[0]["origin"]["source"] == "agent_handoff"
    assert "Use agent_handoff with action='complete'" in created_jobs[0]["prompt"]


def test_agent_comms_projection_and_routes(client):
    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Review docs",
            task="Please review the disclosure packet.",
            priority="high",
            actor="human:web",
        )
        record_agent_handoff_message(
            conn,
            handoff["id"],
            from_agent_id="admin",
            to_agent_id="executive-assistant",
            kind="note",
            content="Packet review is in progress.",
        )
        sent = create_agent_comms_message(
            conn,
            from_agent_id="human-web",
            to_agent_id="admin",
            text="Can you also check the addendum?",
            priority="urgent",
            actor="human:web",
        )
        feed = list_agent_comms_messages(conn, search="packet", limit=20)
        channels = list_agent_comms_channels(conn)
        thread = get_agent_comms_channel(conn, "admin--executive-assistant")

    assert sent["handoff"]["fromAgentId"] == "human-web"
    assert any(msg["text"] == "Please review the disclosure packet." for msg in feed)
    assert any(ch["pair"] == "admin--executive-assistant" for ch in channels)
    assert thread["pair"] == "admin--executive-assistant"
    assert [msg["kind"] for msg in thread["messages"]].count("request") >= 1
    assert any(msg["text"] == "Packet review is in progress." for msg in thread["messages"])

    feed_res = client.get("/api/comms/feed?search=addendum")
    assert feed_res.status_code == 200
    assert any(msg["to"] == "admin" for msg in feed_res.json())

    channels_res = client.get("/api/comms/channels")
    assert channels_res.status_code == 200
    assert any(ch["pair"] == "admin--human-web" for ch in channels_res.json())

    thread_res = client.get("/api/comms/channel/admin--human-web")
    assert thread_res.status_code == 200
    assert any(msg["text"] == "Can you also check the addendum?" for msg in thread_res.json()["messages"])

    send_res = client.post(
        "/api/comms/messages",
        json={"toAgentId": "admin", "text": "New dashboard message", "priority": "normal"},
    )
    assert send_res.status_code == 200
    assert send_res.json()["handoff"]["toAgentId"] == "admin"


def test_cortext_compat_api_aliases_route_to_native_stores(client):
    task_res = client.post(
        "/api/tasks",
        json={
            "title": "Cortext alias task",
            "description": "Created through /api/tasks.",
            "assignee": "admin",
            "priority": "high",
        },
    )
    assert task_res.status_code == 200
    task = task_res.json()["task"]

    listed = client.get("/api/tasks?assignee=admin")
    assert listed.status_code == 200
    assert any(item["id"] == task["id"] for item in listed.json()["tasks"])

    patched = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert patched.status_code == 200
    assert patched.json()["task"]["status"] == "completed"

    send_res = client.post(
        "/api/messages/send",
        json={"toAgentId": "admin", "text": "Cortext alias message", "priority": "normal"},
    )
    assert send_res.status_code == 200
    assert send_res.json()["handoff"]["toAgentId"] == "admin"

    from elevate_cli.data import surface_tasks as st

    with connect() as conn:
        approval = st.create_approval(
            conn,
            title="Cortext alias approval",
            category="external-comms",
            surface="admin",
        )

    approvals = client.get("/api/approvals?status=pending")
    assert approvals.status_code == 200
    assert any(item["id"] == approval["id"] for item in approvals.json()["approvals"])

    resolved = client.patch(f"/api/approvals/{approval['id']}", json={"decision": "approve"})
    assert resolved.status_code == 200
    assert resolved.json()["approval"]["status"] == "approved"

    created = client.post(
        "/api/experiments",
        json={
            "surface": "executive-assistant",
            "title": "Cortext alias experiment",
            "hypothesis": "Alias routes keep experiment writes native.",
            "metric": "alias_quality",
            "direction": "higher",
            "baseline_value": 1,
        },
    )
    assert created.status_code == 200
    experiment = created.json()["experiment"]

    running = client.post(
        f"/api/experiments/{experiment['id']}/run",
        json={"surface": "executive-assistant", "changes_description": "Run through alias."},
    )
    assert running.status_code == 200
    assert running.json()["experiment"]["status"] == "running"

    evaluated = client.post(
        f"/api/experiments/{experiment['id']}/evaluate",
        json={"surface": "executive-assistant", "decision": "keep", "result_value": 2},
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["experiment"]["decision"] == "keep"


def test_agent_handoff_dispatch_includes_agent_policy_thread_and_toolsets(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"policy-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch, "reviewer", "reviewer-chat-123")
    agent_hub.create_agent_config(
        {
            "id": "reviewer",
            "name": "Reviewer",
            "prompt": "Review listing packets and escalate missing context.",
            "toolsets": ["deal"],
            "runtime": {"model": "gpt-policy", "timezone": "America/Vancouver"},
            "routing": {
                "owns": ["listing-review"],
                "handoff_targets": ["admin"],
                "escalation_target": "executive-assistant",
                "default_priority": "high",
            },
            "safety": {
                "approval_mode": "always_confirm",
                "always_ask": ["external_send"],
                "never_ask": ["read_only"],
            },
            "identity": {"vibe": "precise packet reviewer"},
            "soul": {"core_truths": "Never hide missing listing context."},
            "lifecycle": {"max_session_seconds": 3600},
            "ecosystem": {"local_version_control": True},
            "memory": {"scopes": ["listings"], "write_policy": "facts_only"},
        }
    )

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="reviewer",
            title="Review packet",
            task="Review the listing packet and report missing context.",
            create_cron_job=False,
            actor="executive-assistant",
        )
        record_agent_handoff_message(
            conn,
            handoff["id"],
            from_agent_id="admin",
            to_agent_id="reviewer",
            kind="note",
            content="Use the updated amendment before writing the result.",
        )
        dispatched = dispatch_agent_handoff_to_cron(conn, handoff["id"], actor="executive-assistant")

    assert dispatched["status"] == "running"
    assert len(created_jobs) == 1
    assert created_jobs[0]["agent"] == "reviewer"
    # Shared agent baseline skills ("memory", "tasks") map onto the memory and
    # todo native toolsets for every agent.
    assert set(created_jobs[0]["enabled_toolsets"]) == {"deal", "agent_handoff", "memory", "todo"}
    prompt = created_jobs[0]["prompt"]
    assert "Receiving agent policy:" in prompt
    assert "Review listing packets and escalate missing context." in prompt
    assert '"handoff_targets": [\n      "admin"\n    ]' in prompt
    assert "precise packet reviewer" in prompt
    assert "Never hide missing listing context." in prompt
    assert '"scopes": [\n      "listings"\n    ]' in prompt
    assert "Use the updated amendment before writing the result." in prompt


def test_admin_handoff_dispatch_adds_native_toolsets_and_filters_tool_skills(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"admin-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    agent_hub.create_agent_config(
        {
            "id": "adminish",
            "name": "Adminish",
            "role": "admin",
            "skills": ["admin-agent", "agent_handoff", "approvals", "comms", "memory", "tasks"],
            "toolsets": ["agent_bus"],
            "routing": {"owns": ["admin-operations", "deal-files"]},
        }
    )

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="adminish",
            title="Admin data check",
            task="Summarize current admin blockers.",
            create_cron_job=False,
            actor="executive-assistant",
        )
        dispatch_agent_handoff_to_cron(conn, handoff["id"], actor="executive-assistant")

    assert len(created_jobs) == 1
    job_skills = created_jobs[0]["skills"]
    assert "admin-agent" in job_skills
    # Toolset-like skill names are filtered out of the cron job's skill
    # preload (they ride along as native toolsets instead).
    assert not {"agent_handoff", "agent-handoff", "approvals", "comms", "memory", "tasks"}.intersection(job_skills)
    assert set(created_jobs[0]["enabled_toolsets"]) >= {
        "agent_bus",
        "agent_handoff",
        "memory",
        "deals_overview",
        "elevate_db",
        "admin_deal",
        "todo",
    }


def test_agent_routing_policy_blocks_agent_created_wrong_target():
    import elevate_cli.agent_hub as agent_hub

    agent_hub.create_agent_config(
        {
            "id": "router",
            "name": "Router",
            "routing": {"handoff_targets": ["admin"]},
        }
    )

    with connect() as conn:
        allowed = create_agent_handoff(
            conn,
            from_agent_id="router",
            to_agent_id="admin",
            task="Allowed by router policy.",
            actor="router",
            create_cron_job=False,
        )
        with pytest.raises(ValueError, match="not configured to hand work"):
            create_agent_handoff(
                conn,
                from_agent_id="router",
                to_agent_id="marketing",
                task="Blocked by router policy.",
                actor="router",
                create_cron_job=False,
            )
        human_routed = create_agent_handoff(
            conn,
            from_agent_id="router",
            to_agent_id="marketing",
            task="Dashboard-created override stays possible.",
            actor="human:web",
            create_cron_job=False,
        )

    assert allowed["status"] == "queued"
    assert human_routed["status"] == "queued"


def test_agent_handoff_dispatch_without_agent_telegram_lane_uses_local_delivery(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Needs native loop",
            task="This should run through the in-app handoff bus without Telegram.",
            create_cron_job=True,
            actor="executive-assistant",
        )
        threaded = get_agent_handoff(conn, handoff["id"], include_messages=True)

    assert handoff["status"] == "running"
    assert handoff["cronJobId"] == "cron-1"
    assert len(created_jobs) == 1
    assert created_jobs[0]["deliver"] == "local"
    assert created_jobs[0]["origin"]["delivery"] == "in_app_handoff"
    assert created_jobs[0]["origin"]["telegram_lane"] == ""
    assert "final output will return to this Comms handoff thread" in threaded["messages"][-1]["content"]


def test_agent_handoff_result_and_summary():
    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="outreach",
            to_agent_id="admin",
            title="Attach docs",
            task="Attach inbound signed docs to the listing deal.",
            create_cron_job=False,
        )
        result = record_agent_handoff_result(
            conn,
            handoff["id"],
            status="waiting_human",
            result={"summary": "Drafted document review"},
            human_prompt={"title": "Approve docs"},
            idempotency_key="result-1",
            actor="admin",
        )
        summary = agent_handoff_summary(conn)

    assert result["status"] == "waiting_human"
    assert result["result"]["humanPrompt"]["title"] == "Approve docs"
    assert len(result["messages"]) == 2
    assert summary["waitingHuman"] == 1
    assert summary["open"] == 1
    assert summary["byAgent"][0]["agentId"] == "admin"


def test_agent_handoff_cron_delivery_records_final_response():
    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Finish listing checks",
            task="Check the package and report back.",
            create_cron_job=False,
        )
        conn.execute(
            """
            UPDATE agent_handoffs
            SET status = 'running', cron_job_id = ?, claimed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            ("cron-native-1", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), handoff["id"]),
        )
        result = record_agent_handoff_cron_delivery(
            conn,
            handoff["id"],
            success=True,
            final_response="Listing package is complete.",
            cron_outcome="ok",
            actor="admin",
            cron_job_id="cron-native-1",
        )

    assert result["status"] == "completed"
    assert result["result"]["summary"] == "Listing package is complete."
    assert result["messages"][-1]["kind"] == "result"
    assert result["messages"][-1]["content"] == "Listing package is complete."


def test_scheduler_agent_handoff_delivery_records_comms_result():
    from cron.scheduler import _record_agent_handoff_delivery

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Ask human",
            task="Prepare the approval question.",
            create_cron_job=False,
        )
        conn.execute(
            """
            UPDATE agent_handoffs
            SET status = 'running', cron_job_id = ?, claimed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            ("cron-native-2", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), handoff["id"]),
        )

    error = _record_agent_handoff_delivery(
        {
            "id": "cron-native-2",
            "agent": "admin",
            "origin": {
                "source": "agent_handoff",
                "handoff_id": handoff["id"],
                "to_agent_id": "admin",
            },
        },
        success=True,
        final_response="Please approve the launch.",
        error=None,
        cron_outcome="waiting_human",
    )

    with connect() as conn:
        updated = get_agent_handoff(conn, handoff["id"], include_messages=True)

    assert error is None
    assert updated["status"] == "waiting_human"
    assert updated["result"]["humanPrompt"]["message"] == "Please approve the launch."
    assert updated["messages"][-1]["kind"] == "human_prompt"


def test_agent_handoff_terminal_result_is_idempotent_not_overwritable():
    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Close once",
            task="Return one final answer.",
            create_cron_job=False,
        )
        first = record_agent_handoff_result(
            conn,
            handoff["id"],
            status="completed",
            result={"summary": "Done"},
            idempotency_key="handoff-result-1",
            actor="admin",
        )
        same = record_agent_handoff_result(
            conn,
            handoff["id"],
            status="completed",
            result={"summary": "Duplicate retry"},
            idempotency_key="handoff-result-1",
            actor="admin",
        )
        with pytest.raises(ValueError):
            record_agent_handoff_result(
                conn,
                handoff["id"],
                status="failed",
                error_message="Late overwrite",
                idempotency_key="handoff-result-2",
                actor="admin",
            )

    assert first["status"] == "completed"
    assert same["id"] == first["id"]
    assert same["result"]["summary"] == "Done"


def test_agent_handoff_tool_completion_is_receiver_scoped(monkeypatch):
    import tools.agent_handoff_tool as handoff_tool

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="admin",
            to_agent_id="social-media",
            title="Receiver only",
            task="Prepare listing launch post.",
            create_cron_job=False,
        )

    monkeypatch.setattr(handoff_tool, "_session_agent_id", lambda: "admin")
    blocked = json.loads(
        handoff_tool._handoff_tool(
            {
                "action": "complete",
                "handoff_id": handoff["id"],
                "status": "completed",
                "result": {"summary": "wrong actor"},
            }
        )
    )
    assert "success" not in blocked
    assert "receiving agent" in blocked["error"]

    monkeypatch.setattr(handoff_tool, "_session_agent_id", lambda: "social-media")
    completed = json.loads(
        handoff_tool._handoff_tool(
            {
                "action": "complete",
                "handoff_id": handoff["id"],
                "status": "completed",
                "result": {"summary": "done"},
                "idempotency_key": "receiver-complete",
            }
        )
    )
    assert completed["success"] is True
    assert completed["handoff"]["status"] == "completed"


def test_agent_handoff_tool_completion_accepts_summary_and_skipped(monkeypatch):
    import tools.agent_handoff_tool as handoff_tool

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Summary only",
            task="Acknowledge and report a blocker summary.",
            create_cron_job=False,
        )

    monkeypatch.setattr(handoff_tool, "_session_agent_id", lambda: "admin")
    completed = json.loads(
        handoff_tool._handoff_tool(
            {
                "action": "complete",
                "handoff_id": handoff["id"],
                "status": "skipped",
                "summary": "Admin acknowledged the handoff; live blocker data was unavailable.",
                "idempotency_key": "summary-only-complete",
            }
        )
    )

    assert completed["success"] is True
    assert completed["handoff"]["status"] == "completed"
    assert completed["handoff"]["result"]["summary"] == "Admin acknowledged the handoff; live blocker data was unavailable."
    assert completed["handoff"]["result"]["outcome"] == "skipped"
    assert completed["handoff"]["messages"][-1]["content"] == "Admin acknowledged the handoff; live blocker data was unavailable."


def test_agent_handoff_tool_completion_defaults_actor_to_receiver(monkeypatch):
    import tools.agent_handoff_tool as handoff_tool

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Receiver actor",
            task="Complete without an explicit session agent id.",
            create_cron_job=False,
        )

    monkeypatch.setattr(handoff_tool, "_session_agent_id", lambda: "")
    completed = json.loads(
        handoff_tool._handoff_tool(
            {
                "action": "complete",
                "handoff_id": handoff["id"],
                "summary": "Admin completed this handoff.",
                "idempotency_key": "receiver-default-actor",
            }
        )
    )

    assert completed["success"] is True
    assert completed["handoff"]["messages"][-1]["fromAgentId"] == "admin"
    assert completed["handoff"]["messages"][-1]["toAgentId"] == "executive-assistant"


def test_agent_handoff_api_create_list_and_drain(client, monkeypatch):
    _complete_admin_setup()

    def fake_create_job(**kwargs):
        return {"id": "cron-api"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch)

    created = client.post(
        "/api/agent-handoffs",
        json={
            "fromAgentId": "executive-assistant",
            "toAgentId": "admin",
            "title": "Run admin check",
            "task": "Check the listing stage and write back the next task.",
            "priority": "urgent",
            "runNow": False,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "queued"

    listed = client.get("/api/agent-handoffs?status=queued")
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1

    drained = client.post("/api/agent-handoffs/drain", json={"limit": 10})
    assert drained.status_code == 200, drained.text
    assert drained.json()["count"] == 1
    assert drained.json()["items"][0]["status"] == "running"
    assert drained.json()["items"][0]["cronJobId"] == "cron-api"


def test_admin_agent_handoff_api_requires_admin_setup(client):
    created = client.post(
        "/api/agent-handoffs",
        json={
            "fromAgentId": "executive-assistant",
            "toAgentId": "admin",
            "title": "Run admin check",
            "task": "Check the listing stage and write back the next task.",
        },
    )

    assert created.status_code == 409
    assert "Admin setup must be completed" in created.json()["detail"]["message"]


def test_agent_hub_snapshot_includes_handoff_summary(monkeypatch):
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: None)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: None)

    with connect() as conn:
        create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            task="Prepare admin context.",
            create_cron_job=False,
        )

    snapshot = agent_hub.build_agent_hub_snapshot(include_profiles=False)

    assert snapshot["handoffs"]["queued"] == 1
    assert snapshot["handoffs"]["open"] == 1
    assert snapshot["handoffs"]["recent"][0]["toAgentId"] == "admin"
    assert snapshot["agentWorker"]["enabled"] is True


def test_agent_hub_requires_specific_telegram_lane_before_online(monkeypatch):
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: 12345)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: {"platforms": {}})
    monkeypatch.setattr(
        agent_hub,
        "load_config",
        lambda: {"model": {"default": "gpt-test", "provider": "openai"}},
    )
    env_values: dict[str, str] = {}
    monkeypatch.setattr(agent_hub, "get_env_value", lambda key: env_values.get(key))

    missing = agent_hub.build_agent_hub_snapshot(include_profiles=False)
    admin = next(agent for agent in missing["agents"] if agent["id"] == "admin")
    assert admin["status"] == "needs_telegram"
    assert admin["telegramLane"]["configured"] is False

    env_values["ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN"] = "123456789:abcdefghijklmnopqrstuvwxyz"
    env_values["ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL"] = "12345"
    ready = agent_hub.build_agent_hub_snapshot(include_profiles=False)
    admin_ready = next(agent for agent in ready["agents"] if agent["id"] == "admin")
    assert admin_ready["status"] == "online"
    assert admin_ready["telegramLane"]["configured"] is True


def test_agent_hub_does_not_treat_shared_bot_as_agent_bot(monkeypatch):
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: 12345)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: {"platforms": {}})
    monkeypatch.setattr(
        agent_hub,
        "load_config",
        lambda: {"model": {"default": "gpt-test", "provider": "openai"}},
    )
    env_values = {
        "TELEGRAM_BOT_TOKEN": "123456789:sharedabcdefghijklmnopqrstuvwxyz",
        "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL": "12345",
    }
    monkeypatch.setattr(agent_hub, "get_env_value", lambda key: env_values.get(key))

    snapshot = agent_hub.build_agent_hub_snapshot(include_profiles=False)
    executive = next(agent for agent in snapshot["agents"] if agent["id"] == "executive-assistant")

    assert executive["status"] == "needs_telegram"
    assert executive["telegramLane"]["configured"] is False
    assert executive["telegramLane"]["tokenConfigured"] is False
    assert executive["telegramLane"]["tokenEnv"] == "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN"


def test_agent_hub_rejects_non_executive_duplicate_shared_bot(monkeypatch):
    import elevate_cli.agent_hub as agent_hub
    import elevate_cli.config as config_mod

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: 12345)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: {"platforms": {}})
    monkeypatch.setattr(
        agent_hub,
        "load_config",
        lambda: {"model": {"default": "gpt-test", "provider": "openai"}},
    )
    env_values = {
        "TELEGRAM_BOT_TOKEN": "123456789:sharedabcdefghijklmnopqrstuvwxyz",
        "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN": "123456789:sharedabcdefghijklmnopqrstuvwxyz",
        "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL": "12345",
    }
    monkeypatch.setattr(agent_hub, "get_env_value", lambda key: env_values.get(key))
    monkeypatch.setattr(config_mod, "get_env_value", lambda key: env_values.get(key))

    snapshot = agent_hub.build_agent_hub_snapshot(include_profiles=False)
    admin = next(agent for agent in snapshot["agents"] if agent["id"] == "admin")

    assert admin["status"] == "needs_telegram"
    assert admin["telegramLane"]["tokenConfigured"] is True
    assert admin["telegramLane"]["targetConfigured"] is True
    assert admin["telegramLane"]["configured"] is False
    assert admin["telegramLane"]["usesSharedBot"] is True


def test_agent_hub_upgrades_stale_local_only_agent_config(monkeypatch):
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: 12345)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: {"platforms": {}})
    monkeypatch.setattr(
        agent_hub,
        "load_config",
        lambda: {
            "model": {"default": "gpt-test", "provider": "openai"},
            "agent_hub": {
                "agents": [
                    {
                        "id": "admin",
                        "name": "Admin",
                        "enabled": True,
                        "platforms": ["local"],
                        "session_sources": ["cli", "cron"],
                        "skills": [],
                        "prompt": "",
                    }
                ]
            },
        },
    )
    monkeypatch.setattr(agent_hub, "get_env_value", lambda key: None)

    snapshot = agent_hub.build_agent_hub_snapshot(include_profiles=False)
    admin = next(agent for agent in snapshot["agents"] if agent["id"] == "admin")
    agent_ids = {agent["id"] for agent in snapshot["agents"]}

    assert "telegram" in admin["platforms"]
    assert "admin-agent" in admin["skills"]
    assert admin["telegramLane"]["tokenEnv"] == "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN"
    assert admin["telegramLane"]["targetEnv"] == "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL"
    assert admin["status"] == "needs_telegram"
    assert {"executive-assistant", "admin"}.issubset(agent_ids)
    # EA-only base seed: other native agents are installable from the Agent
    # Library, never auto-seeded into the roster.
    assert not {"outreach", "marketing", "social-media"}.intersection(agent_ids)


def test_agent_hub_custom_agent_config_lifecycle(monkeypatch):
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: None)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: None)

    created = agent_hub.create_agent_config(
        {
            "id": "listings",
            "name": "Listings",
            "description": "Owns listing launch work.",
            "runtime": {
                "model": "gpt-listings",
                "provider": "openai",
                "workdir": "/tmp/listings",
                "timezone": "America/Vancouver",
                "context_warning_threshold": 72,
                "context_handoff_threshold": 88,
            },
            "routing": {
                "owns": ["listing-launch"],
                "handoff_targets": ["admin"],
                "escalation_target": "executive-assistant",
                "default_priority": "high",
            },
            "safety": {
                "approval_mode": "always_confirm",
                "always_ask": ["external_send"],
                "never_ask": ["read_only"],
            },
            "identity": {
                "emoji": "L",
                "vibe": "precise listing coordinator",
                "work_style": "checklists first",
            },
            "soul": {
                "autonomy_rules": "Act independently on read-only listing review.",
                "communication_style": "brief and concrete",
                "day_mode": "fast triage",
                "night_mode": "quiet summaries",
                "core_truths": "Never hide missing context.",
            },
            "lifecycle": {
                "startup_delay": 5,
                "max_session_seconds": 3600,
                "max_crashes_per_day": 3,
                "crash_window_seconds": 900,
                "crash_window_max": 2,
                "telegram_polling": False,
            },
            "ecosystem": {
                "local_version_control": True,
                "upstream_sync": False,
                "catalog_browse": True,
                "community_publish": False,
            },
            "memory": {
                "mode": "shared_scoped",
                "scopes": ["listings", "admin"],
                "sources": ["deals", "handoffs"],
                "recall_policy": "agent_scoped_recent",
                "write_policy": "append_events",
                "handoff_policy": "summary_only",
            },
        }
    )
    assert created["id"] == "listings"
    assert created["canDelete"] is True
    assert created["runtime"]["model"] == "gpt-listings"
    assert created["identity"]["vibe"] == "precise listing coordinator"
    assert created["lifecycle"]["max_session_seconds"] == 3600
    assert created["ecosystem"]["local_version_control"] is True
    assert created["memory"]["scopes"] == ["listings", "admin"]

    updated = agent_hub.update_agent_config(
        "listings",
        {
            "enabled": False,
            "runtime": {"provider": "openrouter"},
            "routing": {"default_priority": "normal"},
            "safety": {"never_ask": ["local_note"]},
            "lifecycle": {"telegram_polling": True},
            "memory": {"write_policy": "facts_only"},
        },
    )
    assert updated["enabled"] is False
    assert updated["runtime"]["model"] == "gpt-listings"
    assert updated["runtime"]["provider"] == "openrouter"
    assert updated["lifecycle"]["telegram_polling"] is True
    assert updated["memory"]["write_policy"] == "facts_only"

    snapshot = agent_hub.build_agent_hub_snapshot(include_profiles=False)
    listings = next(agent for agent in snapshot["agents"] if agent["id"] == "listings")
    executive = next(agent for agent in snapshot["agents"] if agent["id"] == "executive-assistant")
    assert listings["canDelete"] is True
    assert executive["canDelete"] is False
    assert listings["queueSummary"]["queued"] == 0
    assert listings["automationSummary"]["total"] == 0
    assert listings["soul"]["core_truths"] == "Never hide missing context."
    assert snapshot["redaction"]["raw_secrets_returned"] is False

    with pytest.raises(ValueError):
        agent_hub.delete_agent_config("executive-assistant")

    assert agent_hub.delete_agent_config("listings") == {"ok": True, "id": "listings", "removable": False}
    with pytest.raises(LookupError):
        agent_hub.delete_agent_config("listings")


def test_agent_hub_accepts_cortext_alias_config_and_validates_values(monkeypatch):
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(agent_hub, "get_running_pid", lambda: None)
    monkeypatch.setattr(agent_hub, "read_runtime_status", lambda: None)

    created = agent_hub.create_agent_config(
        {
            "id": "cortext-listings",
            "name": "Cortext Listings",
            "runtime": "codex",
            "model": "gpt-cortext",
            "provider": "openai",
            "working_directory": "/tmp/cortext-listings",
            "timezone": "America/Vancouver",
            "ctx_warning_threshold": 70,
            "ctx_handoff_threshold": 92,
            "codex_context_cap": 200000,
            "dangerously_skip_permissions": True,
            "approval_rules": {
                "approval_mode": "confirm_external_send",
                "always_ask": ["external_send", "deployment"],
                "never_ask": ["read_only"],
            },
            "communication_style": "concise operator updates",
            "day_mode_start": "08:30",
            "day_mode_end": "18:15",
            "startup_delay": 12,
            "max_session_seconds": 3600,
            "max_crashes_per_day": 2,
            "crash_window": {"seconds": 600, "max_crashes": 1},
            "telegram_polling": False,
        }
    )

    assert created["runtime"]["runtime_type"] == "codex"
    assert created["runtime"]["model"] == "gpt-cortext"
    assert created["runtime"]["workdir"] == "/tmp/cortext-listings"
    assert created["runtime"]["context_warning_threshold"] == 70
    assert created["runtime"]["context_handoff_threshold"] == 92
    assert created["runtime"]["codex_context_cap"] == 200000
    assert created["safety"]["dangerously_skip_permissions"] is True
    assert created["safety"]["always_ask"] == ["external_send", "deployment"]
    assert created["soul"]["communication_style"] == "concise operator updates"
    assert created["soul"]["day_mode_start"] == "08:30"
    assert created["lifecycle"]["startup_delay"] == 12
    assert created["lifecycle"]["crash_window_seconds"] == 600
    assert created["lifecycle"]["crash_window_max"] == 1
    assert created["lifecycle"]["telegram_polling"] is False
    compat = created["compat"]["cortext"]
    assert compat["runtime"] == "codex"
    assert compat["working_directory"] == "/tmp/cortext-listings"
    assert compat["approval_rules"]["always_ask"] == ["external_send", "deployment"]
    assert compat["crash_window"] == {"seconds": 600, "max_crashes": 1}

    with pytest.raises(ValueError, match="lower than context_handoff"):
        agent_hub.create_agent_config(
            {
                "id": "bad-thresholds",
                "name": "Bad Thresholds",
                "ctx_warning_threshold": 95,
                "ctx_handoff_threshold": 80,
            }
        )
    with pytest.raises(ValueError, match="HH:MM"):
        agent_hub.create_agent_config(
            {"id": "bad-day-mode", "name": "Bad Day Mode", "day_mode_start": "25:00"}
        )
    with pytest.raises(ValueError, match="positive integer"):
        agent_hub.create_agent_config(
            {"id": "bad-context-cap", "name": "Bad Context Cap", "codex_context_cap": 0}
        )


def test_agent_policy_gates_external_send_with_native_approval():
    import elevate_cli.agent_hub as agent_hub
    from elevate_cli.data import surface_tasks
    from tools import send_message_tool

    agent_hub.create_agent_config(
        {
            "id": "sender",
            "name": "Sender",
            "safety": {
                "approval_mode": "confirm_external_send",
                "always_ask": ["external_send"],
            },
        }
    )

    blocked = json.loads(
        send_message_tool._agent_send_policy_block(
            {"agent_id": "sender"},
            platform_name="telegram",
            target="telegram:123",
            chat_id="123",
        )
    )

    assert blocked["approvalRequired"] is True
    assert blocked["policy"]["decision"] == "approval_required"
    with connect() as conn:
        approvals = surface_tasks.list_approvals(conn, status="pending", surface="telegram")
    assert len(approvals) == 1
    assert "sender" in approvals[0]["title"]
    assert approvals[0]["status"] == "pending"


def test_agent_handoff_lifecycle_startup_delay_and_crash_window(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"lifecycle-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch, "slow-agent", "slow-chat-123")
    agent_hub.create_agent_config(
        {
            "id": "slow-agent",
            "name": "Slow Agent",
            "lifecycle": {
                "startup_delay": 30,
                "max_crashes_per_day": 1,
                "crash_window": {"seconds": 3600, "max_crashes": 1},
            },
        }
    )

    with connect() as conn:
        delayed = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="slow-agent",
            title="Delayed run",
            task="Run after startup delay.",
            create_cron_job=True,
            actor="executive-assistant",
        )

    assert delayed["status"] == "running"
    assert created_jobs[0]["agent"] == "slow-agent"
    assert created_jobs[0]["origin"]["startup_delay_seconds"] == 30
    scheduled_at = datetime.fromisoformat(created_jobs[0]["schedule"])
    assert scheduled_at > datetime.now(timezone.utc) + timedelta(seconds=20)

    with connect() as conn:
        failed = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="slow-agent",
            task="This run failed.",
            create_cron_job=False,
        )
        record_agent_handoff_result(
            conn,
            failed["id"],
            status="failed",
            result={"summary": "crashed"},
            error_message="crashed",
            actor="slow-agent",
        )
        paused = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="slow-agent",
            task="Should pause after crash limit.",
            create_cron_job=True,
            actor="executive-assistant",
        )

    assert paused["status"] == "waiting_human"
    assert "Lifecycle policy paused" in paused["errorMessage"]
    assert paused["result"]["blockedBy"][0]["reason"] in {"max_crashes_per_day", "crash_window"}
    assert len(created_jobs) == 1


def test_context_pressure_records_activity_and_queues_native_handoff():
    import elevate_cli.agent_hub as agent_hub
    from elevate_cli.agent_policy import record_agent_context_pressure

    agent_hub.create_agent_config(
        {
            "id": "context-agent",
            "name": "Context Agent",
            "runtime": {
                "context_warning_threshold": 50,
                "context_handoff_threshold": 80,
            },
            "routing": {
                "escalation_target": "admin",
                "default_priority": "high",
            },
        }
    )

    with connect() as conn:
        warning = record_agent_context_pressure(
            "context-agent",
            session_id="sess-warning",
            current_tokens=60,
            context_limit=100,
            summary="Warning only.",
            conn=conn,
            actor="context-agent",
        )
        handoff = record_agent_context_pressure(
            "context-agent",
            session_id="sess-handoff",
            current_tokens=90,
            context_limit=100,
            summary="Continue this compressed context.",
            conn=conn,
            actor="context-agent",
        )
        queued = list_agent_handoffs(conn, to_agent_id="admin", limit=10)

    assert warning["recorded"] is True
    assert warning["event"]["kind"] == "context_warning"
    assert warning["handoff"] is None
    assert handoff["recorded"] is True
    assert handoff["event"]["kind"] == "context_handoff"
    assert handoff["handoff"]["toAgentId"] == "admin"
    assert handoff["event"]["handoffId"] == handoff["handoff"]["id"]
    assert any(item["sourceRunId"] == "sess-handoff" for item in queued)


def test_context_pressure_self_continuation_uses_native_handoff_bus():
    import elevate_cli.agent_hub as agent_hub
    from elevate_cli.agent_policy import record_agent_context_pressure

    agent_hub.create_agent_config(
        {
            "id": "self-context-agent",
            "name": "Self Context Agent",
            "runtime": {
                "context_warning_threshold": 50,
                "context_handoff_threshold": 80,
            },
        }
    )

    with connect() as conn:
        handoff = record_agent_context_pressure(
            "self-context-agent",
            session_id="sess-self-handoff",
            current_tokens=90,
            context_limit=100,
            summary="Continue my own compressed context.",
            conn=conn,
            actor="self-context-agent",
        )
        queued = list_agent_handoffs(conn, to_agent_id="self-context-agent", limit=10)

    assert handoff["recorded"] is True
    assert handoff["event"]["kind"] == "context_handoff"
    assert handoff["handoff"]["fromAgentId"] == "system"
    assert handoff["handoff"]["toAgentId"] == "self-context-agent"
    assert handoff["handoff"]["payload"]["sourceAgentId"] == "self-context-agent"
    assert any(item["sourceRunId"] == "sess-self-handoff" for item in queued)


def test_memory_handoff_policy_compacts_result_and_surfaces_summary():
    import elevate_cli.agent_hub as agent_hub

    agent_hub.create_agent_config(
        {
            "id": "memory-agent",
            "name": "Memory Agent",
            "memory": {
                "scopes": ["listings"],
                "sources": ["handoffs"],
                "recall_policy": "agent_scoped_recent",
                "write_policy": "append_events",
                "handoff_policy": "facts_only",
            },
        }
    )

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="memory-agent",
            task="Return only memory-safe facts.",
            create_cron_job=False,
        )
        result = record_agent_handoff_result(
            conn,
            handoff["id"],
            status="completed",
            result={
                "summary": "Facts captured.",
                "fullText": "This verbose body should not be stored under facts_only.",
                "facts": ["Listing docs missing strata form."],
            },
            idempotency_key="memory-facts-only",
            actor="memory-agent",
        )

    assert result["result"]["summary"] == "Facts captured."
    assert result["result"]["facts"] == ["Listing docs missing strata form."]
    assert "fullText" not in result["result"]
    assert result["messages"][-1]["payload"]["memoryPolicy"]["handoff_policy"] == "facts_only"


def test_agent_hub_api_create_patch_delete_custom_agent(client):
    created = client.post(
        "/api/agent-hub/agents",
        json={
            "id": "api-agent",
            "name": "API Agent",
            "description": "Created through the dashboard API.",
            "runtime": "codex",
            "model": "gpt-api",
            "provider": "openai",
            "working_directory": "/tmp/api-agent",
            "ctx_warning_threshold": 65,
            "ctx_handoff_threshold": 85,
            "codex_context_cap": 128000,
            "approval_rules": {"always_ask": ["external_send"]},
            "day_mode_start": "09:00",
            "day_mode_end": "17:00",
            "metadata": {
                "cortext_import": {
                    "source_files": ["AGENTS.md", "SYSTEM.md", "TOOLS.md"],
                    "native_replacements": ["daemon -> Elevate desktop backend"],
                },
                "telegram_bot_token_env": "ELEVATE_AGENT_API_AGENT_TELEGRAM_BOT_TOKEN",
                "raw_token": "should-not-survive",
                "daemon": {"pid": 123},
            },
            "memorySeed": {
                "content": "Remember launch checklist order. api_key=raw-secret-value",
                "source": "cortext-import",
            },
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["id"] == "api-agent"
    assert created.json()["canDelete"] is True
    assert created.json()["runtime"]["runtime_type"] == "codex"
    assert created.json()["runtime"]["workdir"] == "/tmp/api-agent"
    assert created.json()["compat"]["cortext"]["ctx_handoff_threshold"] == 85
    assert created.json()["metadata"]["cortext_import"]["source_files"] == ["AGENTS.md", "SYSTEM.md", "TOOLS.md"]
    assert created.json()["metadata"]["telegram_bot_token_env"] == "ELEVATE_AGENT_API_AGENT_TELEGRAM_BOT_TOKEN"
    assert "raw_token" not in created.json()["metadata"]
    assert "daemon" not in created.json()["metadata"]
    assert created.json()["memorySeedSummary"]["seeded"] == 1
    assert "raw-secret-value" not in created.text

    from elevate_cli.agent_hub import agent_memory_facts

    facts = agent_memory_facts("api-agent")
    assert facts[0]["fact"] == "Remember launch checklist order. api_key=[redacted]"

    snapshot = client.get("/api/agent-hub?lite=true")
    assert snapshot.status_code == 200, snapshot.text
    api_agent = next(agent for agent in snapshot.json()["agents"] if agent["id"] == "api-agent")
    assert api_agent["memorySummary"]["nativeFacts"] == 1
    assert api_agent["memorySummary"]["recentFacts"][0]["fact"] == "Remember launch checklist order. api_key=[redacted]"

    patched = client.patch(
        "/api/agent-hub/agents/api-agent",
        json={
            "enabled": False,
            "routing": {"owns": ["api-work"], "handoff_targets": ["admin"]},
            "safety": {"approval_mode": "always_confirm"},
            "identity": {"vibe": "API steady"},
            "lifecycle": {"max_crashes_per_day": 4},
            "memory": {"scopes": ["api-work"]},
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["enabled"] is False
    assert patched.json()["routing"]["owns"] == ["api-work"]
    assert patched.json()["identity"]["vibe"] == "API steady"
    assert patched.json()["lifecycle"]["max_crashes_per_day"] == 4
    assert patched.json()["memory"]["scopes"] == ["api-work"]

    # The Executive Assistant is the only permanent agent; every other
    # built-in is removable (delete tombstones it so it isn't re-seeded).
    permanent_delete = client.delete("/api/agent-hub/agents/executive-assistant")
    assert permanent_delete.status_code == 400
    assert "Executive Assistant cannot be deleted" in permanent_delete.json()["detail"]

    builtin_delete = client.delete("/api/agent-hub/agents/admin")
    assert builtin_delete.status_code == 200, builtin_delete.text
    assert builtin_delete.json() == {"ok": True, "id": "admin", "removable": True}

    deleted = client.delete("/api/agent-hub/agents/api-agent")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"ok": True, "id": "api-agent", "removable": False}


def test_cron_agent_jobs_inherit_runtime_defaults_when_job_fields_absent(tmp_path):
    from cron.jobs import create_job
    from elevate_cli.agent_hub import create_agent_config

    workdir = tmp_path / "agent-workdir"
    workdir.mkdir()
    create_agent_config(
        {
            "id": "runtime-agent",
            "name": "Runtime Agent",
            "max_session_seconds": 3600,
            "runtime": {
                "model": "gpt-agent-default",
                "provider": "openai",
                "base_url": "https://models.example/v1/",
                "workdir": str(workdir),
            },
        }
    )

    inherited = create_job(
        prompt="Use agent defaults.",
        schedule="every 1h",
        agent="runtime-agent",
    )
    overridden = create_job(
        prompt="Use job overrides.",
        schedule="every 1h",
        agent="runtime-agent",
        model="gpt-job",
        provider="anthropic",
        base_url="https://job.example/v1",
        workdir=str(tmp_path),
        max_session_seconds=120,
    )

    assert inherited["model"] == "gpt-agent-default"
    assert inherited["provider"] == "openai"
    assert inherited["base_url"] == "https://models.example/v1"
    assert inherited["workdir"] == str(workdir)
    assert inherited["max_session_seconds"] == 3600
    assert overridden["model"] == "gpt-job"
    assert overridden["provider"] == "anthropic"
    assert overridden["base_url"] == "https://job.example/v1"
    assert overridden["workdir"] == str(tmp_path)
    assert overridden["max_session_seconds"] == 120


def test_agent_worker_tick_drains_handoffs_and_admin_runs(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"worker-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch)

    _complete_admin_setup()
    with connect() as conn:
        create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            task="Handle the listing handoff.",
            create_cron_job=False,
        )
        deal = create_deal(
            conn,
            title="Worker listing",
            side="listing",
            current_stage=2,
            actor="human:test",
        )
        queue_action_run(
            conn,
            deal_id=deal["id"],
            skill="seller-update",
            name="Worker admin run",
            payload={"reason": "test"},
            create_cron_job=False,
            actor="human:test",
        )

    from elevate_cli.agent_worker import snapshot, tick

    status = tick(actor="test-worker")

    assert status["state"] == "ok"
    assert status["drained"] == {"handoffs": 1, "adminRuns": 1}
    assert snapshot()["lastSuccessAt"] == status["lastSuccessAt"]
    assert len(created_jobs) == 2
    assert {job["origin"]["source"] for job in created_jobs} == {
        "agent_handoff",
        "admin_hub",
    }

    with connect() as conn:
        assert list_agent_handoffs(conn)[0]["status"] == "running"
        assert list_deal_action_runs(conn, deal_id=deal["id"])[0]["status"] == "running"


def test_agent_worker_tick_with_agent_id_drains_only_that_agent(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"scoped-worker-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch, "admin")
    _configure_agent_telegram(monkeypatch, "marketing", "marketing-chat-123")
    # Admin is an installable native (not auto-seeded); install it so the
    # scoped worker treats it as an enabled agent.
    agent_hub.update_agent_config("admin", {"enabled": True})

    with connect() as conn:
        admin_handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            task="Admin-only scoped handoff.",
            create_cron_job=False,
        )
        ads_handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="marketing",
            task="Marketing handoff should stay queued.",
            create_cron_job=False,
        )

    from elevate_cli.agent_worker import tick

    status = tick(actor="test-worker", agent_id="admin")

    assert status["state"] == "ok"
    assert status["agentId"] == "admin"
    assert status["drained"] == {"handoffs": 1, "adminRuns": 0}
    assert len(created_jobs) == 1
    assert created_jobs[0]["agent"] == "admin"

    with connect() as conn:
        statuses = {item["id"]: item["status"] for item in list_agent_handoffs(conn, limit=10)}
    assert statuses[admin_handoff["id"]] == "running"
    assert statuses[ads_handoff["id"]] == "queued"


def test_agent_worker_scoped_tick_and_wake_refuse_disabled_agent(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"disabled-worker-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs
    import elevate_cli.agent_hub as agent_hub

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch, "admin")
    agent_hub.update_agent_config("admin", {"enabled": False})

    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            task="Disabled agent should not be drained.",
            create_cron_job=False,
        )

    from elevate_cli.agent_worker import request_wake, tick

    wake = request_wake(actor="test-worker", reason="test", agent_id="admin")
    status = tick(actor="test-worker", agent_id="admin")

    assert wake["state"] == "disabled"
    assert wake["wake"]["pending"] is False
    assert status["state"] == "disabled"
    assert status["agentId"] == "admin"
    assert status["drained"] == {"handoffs": 0, "adminRuns": 0}
    assert created_jobs == []

    with connect() as conn:
        assert get_agent_handoff(conn, handoff["id"])["status"] == "queued"


def test_agent_worker_api_tick(client, monkeypatch):
    def fake_create_job(**kwargs):
        return {"id": "worker-api-cron"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch)

    with connect() as conn:
        create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            task="API worker handoff.",
            create_cron_job=False,
        )

    resp = client.post("/api/agent-worker/tick")

    assert resp.status_code == 200, resp.text
    assert resp.json()["drained"]["handoffs"] == 1
    assert resp.json()["state"] == "ok"


def test_agent_worker_background_loop_consumes_wake_signal(monkeypatch):
    created_jobs: list[dict] = []
    after_ticks: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"wake-loop-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs
    from elevate_cli.agent_worker import start_background_loop, stop_background_loop

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch)
    _complete_admin_setup()

    start_background_loop(
        config={
            "agent_worker": {
                "enabled": True,
                "max_handoffs_per_tick": 25,
                "max_admin_runs_per_tick": 25,
                "heartbeat_interval_seconds": 5,
                "wake_poll_seconds": 1,
            }
        },
        after_tick=lambda status: after_ticks.append(status),
    )
    try:
        with connect() as conn:
            deal = create_deal(
                conn,
                title="Wake loop listing",
                side="listing",
                current_stage=2,
                actor="human:test",
            )
            queue_action_run(
                conn,
                deal_id=deal["id"],
                skill="seller-update",
                name="Wake loop admin run",
                payload={"reason": "wake-loop-test"},
                create_cron_job=False,
                actor="human:test",
            )

        deadline = time.time() + 4
        run = None
        while time.time() < deadline:
            with connect() as conn:
                rows = list_deal_action_runs(conn, deal_id=deal["id"])
            run = rows[0] if rows else None
            if run and run["status"] == "running":
                break
            time.sleep(0.1)

        assert run is not None
        assert run["status"] == "running"
        assert created_jobs
        assert any(status["drained"]["adminRuns"] for status in after_ticks)
    finally:
        stop_background_loop()


def test_agent_worker_tolerates_bad_numeric_config():
    from elevate_cli.agent_worker import tick

    status = tick(
        actor="test-worker",
        config={
            "agent_worker": {
                "enabled": "false",
                "max_handoffs_per_tick": "not-an-int",
                "max_admin_runs_per_tick": {},
                "stale_running_minutes": "eventually",
            }
        },
    )

    assert status["state"] == "disabled"
    assert status["limits"] == {
        "handoffs": 25,
        "adminRuns": 25,
        "staleRunningMinutes": 120,
    }


def test_handoff_dependencies_block_until_human_approval(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"approval-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch, "social-media", "social-chat-123")

    with connect() as conn:
        deal = create_deal(
            conn,
            title="Dependency listing",
            side="listing",
            current_stage=3,
            actor="human:test",
        )
        handoff = create_agent_handoff(
            conn,
            from_agent_id="admin",
            to_agent_id="social-media",
            title="Launch photo cleanup",
            task="Clean listing photos after approval.",
            deal_id=deal["id"],
            payload={
                "requires": [
                    {"type": "deal_field", "field": "mlsNumber", "label": "MLS number"},
                    {"type": "attachment", "kind": "listing_photo", "label": "Listing photos"},
                ]
            },
            create_cron_job=True,
            actor="admin",
        )
        tasks = list_deal_tasks(conn, status="open")
        events = list_deal_events(conn, deal["id"])
        assert handoff["status"] == "waiting_human"
        assert created_jobs == []

        approved = approve_agent_handoff(
            conn,
            handoff["id"],
            approved=True,
            run_now=True,
            actor="human:test",
        )

    assert handoff["result"]["blockedBy"][0]["field"] == "mlsNumber"
    assert any(task["type"] == "agent_handoff" and task["handoffId"] == handoff["id"] for task in tasks)
    assert any((event["payload"] or {}).get("event") == "dependency_blocked" for event in events)
    assert approved["status"] == "running"
    assert approved["cronJobId"] == "approval-cron-1"
    assert created_jobs[0]["agent"] == "social-media"
    assert created_jobs[0]["deliver"] == "telegram:social-chat-123"


def test_handoff_admin_setup_dependency_accepts_configured_status(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"configured-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch, "social-media", "social-chat-123")

    with connect() as conn:
        update_admin_setup(
            conn,
            items=[{"key": "forms_provider", "status": "configured", "provider": "WEBForms"}],
            actor="human:test",
        )
        handoff = create_agent_handoff(
            conn,
            from_agent_id="admin",
            to_agent_id="social-media",
            title="Configured dependency",
            task="Run only after forms are configured.",
            payload={"requires": [{"type": "admin_setup", "key": "forms_provider", "label": "Forms"}]},
            create_cron_job=True,
            actor="admin",
        )

    assert handoff["status"] == "running"
    assert handoff["cronJobId"] == "configured-cron-1"
    assert created_jobs[0]["agent"] == "social-media"


def test_handoff_result_fans_out_to_deal_and_next_handoff(monkeypatch):
    created_jobs: list[dict] = []

    def fake_create_job(**kwargs):
        created_jobs.append(kwargs)
        return {"id": f"next-cron-{len(created_jobs)}"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    _configure_agent_telegram(monkeypatch)

    with connect() as conn:
        deal = create_deal(
            conn,
            title="Fanout listing",
            side="listing",
            current_stage=4,
            actor="human:test",
        )
        handoff = create_agent_handoff(
            conn,
            from_agent_id="admin",
            to_agent_id="social-media",
            title="Prepare media",
            task="Prepare social launch assets.",
            deal_id=deal["id"],
            create_cron_job=False,
        )
        result = record_agent_handoff_result(
            conn,
            handoff["id"],
            status="completed",
            result={
                "summary": "Assets are ready.",
                "nextHandoffs": [
                    {
                        "toAgentId": "admin",
                        "title": "Approve launch",
                        "task": "Review prepared assets and ask for launch approval.",
                        "runNow": True,
                        "idempotencyKey": "approve-launch",
                    }
                ],
            },
            idempotency_key="media-result",
            actor="social-media",
        )
        events = list_deal_events(conn, deal["id"])
        handoffs = list_agent_handoffs(conn, deal_id=deal["id"], limit=10)

    assert result["status"] == "completed"
    assert any((event["payload"] or {}).get("event") == "result" for event in events)
    assert any(item["parentHandoffId"] == handoff["id"] for item in handoffs)
    assert created_jobs[0]["agent"] == "admin"


def test_stale_running_handoffs_fail_and_surface_to_summary():
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=180)).isoformat()
    with connect() as conn:
        handoff = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Stale handoff",
            task="This worker never wrote back.",
            create_cron_job=False,
        )
        conn.execute(
            """
            UPDATE agent_handoffs
            SET status = 'running', claimed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (stale_at, stale_at, handoff["id"]),
        )
        recovered = mark_stale_agent_handoffs(conn, max_running_minutes=120, actor="test-worker")
        summary = agent_handoff_summary(conn)

    assert len(recovered) == 1
    assert recovered[0]["status"] == "failed"
    assert "120 minute" in recovered[0]["errorMessage"]
    assert summary["failed"] == 1


def test_mark_stale_handoffs_can_filter_to_agent():
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=180)).isoformat()
    with connect() as conn:
        admin = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="admin",
            title="Stale admin handoff",
            task="Admin worker never wrote back.",
            create_cron_job=False,
        )
        ads = create_agent_handoff(
            conn,
            from_agent_id="executive-assistant",
            to_agent_id="marketing",
            title="Stale marketing handoff",
            task="Marketing worker never wrote back.",
            create_cron_job=False,
        )
        conn.execute(
            """
            UPDATE agent_handoffs
            SET status = 'running', claimed_at = ?, updated_at = ?
            WHERE id IN (?, ?)
            """,
            (stale_at, stale_at, admin["id"], ads["id"]),
        )
        recovered = mark_stale_agent_handoffs(
            conn,
            to_agent_id="admin",
            max_running_minutes=120,
            actor="test-worker",
        )
        statuses = {item["id"]: item["status"] for item in list_agent_handoffs(conn, limit=10)}

    assert [item["id"] for item in recovered] == [admin["id"]]
    assert statuses[admin["id"]] == "failed"
    assert statuses[ads["id"]] == "running"
