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
    create_agent_handoff,
    create_deal,
    get_admin_setup,
    list_agent_handoffs,
    list_deal_events,
    list_deal_tasks,
    list_deal_action_runs,
    mark_stale_agent_handoffs,
    queue_action_run,
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


def test_agent_handoff_dispatch_blocks_without_agent_telegram_lane(monkeypatch):
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
            title="Needs lane",
            task="This should wait until Admin has its own Telegram lane.",
            create_cron_job=True,
            actor="executive-assistant",
        )

    assert handoff["status"] == "waiting_human"
    assert handoff["cronJobId"] is None
    assert handoff["result"]["blockedBy"][0]["type"] == "telegram_lane"
    assert created_jobs == []


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
    assert {"executive-assistant", "admin", "outreach", "ads", "marketing", "social-media"}.issubset(agent_ids)


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
