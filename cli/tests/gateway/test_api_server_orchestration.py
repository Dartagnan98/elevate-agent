import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.orchestration import OrchestrationStore
from gateway.platforms.api_server import APIServerAdapter, cors_middleware


def _make_adapter(tmp_path, api_key: str = "") -> APIServerAdapter:
    extra = {"key": api_key} if api_key else {}
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra=extra))
    adapter._orchestration_store = OrchestrationStore(tmp_path / "orchestration.db")
    return adapter


def _create_app(adapter: APIServerAdapter) -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app["api_server_adapter"] = adapter
    app.router.add_get("/health/detailed", adapter._handle_health_detailed)
    app.router.add_get("/api/tools", adapter._handle_tools_snapshot)
    app.router.add_get("/api/orchestration", adapter._handle_orchestration_snapshot)
    app.router.add_get("/api/agents", adapter._handle_list_agents)
    app.router.add_post("/api/agents", adapter._handle_create_agent)
    app.router.add_get("/api/agents/{agent_id}", adapter._handle_get_agent)
    app.router.add_patch("/api/agents/{agent_id}", adapter._handle_update_agent)
    app.router.add_get("/api/agent-runs", adapter._handle_list_agent_runs)
    app.router.add_post("/api/agent-runs", adapter._handle_create_agent_run)
    app.router.add_get("/api/agent-runs/{run_id}/events", adapter._handle_list_agent_run_events)
    app.router.add_post("/api/agent-runs/{run_id}/events", adapter._handle_create_agent_run_event)
    app.router.add_get("/api/agent-runs/{run_id}", adapter._handle_get_agent_run)
    app.router.add_patch("/api/agent-runs/{run_id}", adapter._handle_update_agent_run)
    return app


@pytest.mark.asyncio
async def test_orchestration_snapshot_and_health(tmp_path):
    adapter = _make_adapter(tmp_path)
    app = _create_app(adapter)

    async with TestClient(TestServer(app)) as cli:
        snapshot_resp = await cli.get("/api/orchestration")
        assert snapshot_resp.status == 200
        snapshot = await snapshot_resp.json()
        assert any(agent["agent_id"] == "executive-assistant" for agent in snapshot["agents"])

        health_resp = await cli.get("/health/detailed")
        assert health_resp.status == 200
        health = await health_resp.json()
        assert health["orchestration"]["agents"] >= 5
        assert "db_path" not in health["orchestration"]


@pytest.mark.asyncio
async def test_tools_snapshot_exposes_code_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_GATEWAY_TOOL_PROFILE", "auto")
    adapter = _make_adapter(tmp_path)
    app = _create_app(adapter)

    async with TestClient(TestServer(app)) as cli:
        resp = await cli.get(
            "/api/tools",
            params={
                "platform": "telegram",
                "message": "Patch the CMA photo QA code in the local repo",
            },
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["focused_auto"]["selected_profile"] == "coding-edit"
        selected = set(body["focused_auto"]["selected_toolsets"])
        assert {"terminal", "file", "delegation", "code_execution"} <= selected
        assert body["focused_auto"]["decision"]["reason"] == "matched coding-edit intent"
        assert "patch" in body["focused_auto"]["decision"]["matched_keywords"]
        assert (
            body["focused_auto"]["router_probes"]["followup"]["selected_profile"]
            == "gateway-followup"
        )
        assert (
            body["focused_auto"]["router_probes"]["code_patch"]["selected_profile"]
            == "coding-edit"
        )


@pytest.mark.asyncio
async def test_agent_run_crud_and_events(tmp_path):
    adapter = _make_adapter(tmp_path)
    app = _create_app(adapter)

    async with TestClient(TestServer(app)) as cli:
        create_resp = await cli.post(
            "/api/agent-runs",
            json={"agent_id": "outreach", "task": "Follow up with buyer lead", "status": "running"},
        )
        assert create_resp.status == 201
        run = (await create_resp.json())["run"]

        event_resp = await cli.post(
            f"/api/agent-runs/{run['run_id']}/events",
            json={"type": "note", "message": "Lead researched"},
        )
        assert event_resp.status == 201

        patch_resp = await cli.patch(
            f"/api/agent-runs/{run['run_id']}",
            json={"status": "completed", "summary": "Follow-up drafted."},
        )
        assert patch_resp.status == 200
        assert (await patch_resp.json())["run"]["status"] == "completed"

        events_resp = await cli.get(f"/api/agent-runs/{run['run_id']}/events")
        assert events_resp.status == 200
        event_types = [event["type"] for event in (await events_resp.json())["events"]]
        assert event_types == ["run.running", "note", "run.completed"]


@pytest.mark.asyncio
async def test_orchestration_api_requires_gateway_auth_when_configured(tmp_path):
    adapter = _make_adapter(tmp_path, api_key="sk-test")
    app = _create_app(adapter)

    async with TestClient(TestServer(app)) as cli:
        denied = await cli.get("/api/orchestration")
        assert denied.status == 401

        allowed = await cli.get("/api/orchestration", headers={"Authorization": "Bearer sk-test"})
        assert allowed.status == 200
