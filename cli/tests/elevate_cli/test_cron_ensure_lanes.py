from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


def test_ensure_lanes_repairs_agent_on_existing_job(client):
    from cron.jobs import create_job, get_job

    job = create_job(
        prompt="Check the admin lane.",
        schedule="every 1h",
        name="Admin lane",
        skills=["tasks"],
    )

    response = client.post(
        "/api/cron/jobs/ensure-lanes",
        json={
            "lanes": [
                {
                    "name": "Admin lane",
                    "prompt": "Check the admin lane.",
                    "schedule": "every 1h",
                    "deliver": "local",
                    "skills": ["tasks"],
                    "agent": "admin",
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updated"][0]["agent"] == "admin"
    assert get_job(job["id"])["agent"] == "admin"
