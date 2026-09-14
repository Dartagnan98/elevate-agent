"""Slow synchronous history/status reads must not stall the ASGI event loop."""
import asyncio
import logging
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from elevate_cli.web_routes import session_details, sessions, status


@pytest.mark.parametrize("route_kind", ["session", "status", "list"])
def test_slow_database_does_not_block_other_requests(tmp_path, route_kind):
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    class SlowDb:
        def get_session(self, sid):
            time.sleep(0.3)
            return {"id": sid}

        def close(self):
            pass

        def list_sessions_rich(self, **kwargs):
            time.sleep(0.3)
            return [{"id": "example"}]

    if route_kind == "session":
        app.include_router(session_details.create_session_detail_router(
            get_session_db=SlowDb,
            session_reveal_target=lambda sid: tmp_path,
            open_in_file_manager=lambda path: None,
            live_subagent_child_session_ids=set,
            log=logging.getLogger(__name__),
        ))
        path = "/api/sessions/example"
    elif route_kind == "list":
        app.include_router(sessions.create_sessions_router(
            get_session_db=SlowDb, platform_chat_sources=lambda: [],
            mark_session_activity=lambda rows, now: None,
            session_list_payload=lambda row: row,
        ))
        path = "/api/sessions?include_details=true&include_total=false"
    else:
        def slow_config():
            time.sleep(0.3)
            return 1, 1

        app.include_router(status.create_status_router(
            workspace_root=tmp_path, get_session_db=SlowDb,
            session_active_window_sec=60,
            check_config_version_func=slow_config,
            get_running_pid_func=lambda: None,
            read_runtime_status_func=lambda: None,
            gateway_health_url_func=lambda: None,
        ))
        path = "/api/status"

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            started = time.monotonic()
            slow = asyncio.create_task(client.get(path))
            try:
                await asyncio.sleep(0.02)
                response = await client.get("/ping")
                elapsed = time.monotonic() - started
                assert response.status_code == 200
                assert elapsed < 0.2, f"Unrelated request blocked for {elapsed:.3f}s"
                assert (await slow).status_code == 200
            finally:
                await slow

    with patch.object(session_details, "_resolve_active_session_or_404", return_value=("example", "example", {})), \
         patch("elevate_cli.data.chat_sessions.active_session_count", return_value=0):
        asyncio.run(scenario())
