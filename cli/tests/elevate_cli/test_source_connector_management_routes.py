import logging

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli import source_connectors
from elevate_cli.web_routes.source_connector_management import register_source_connector_management_routes


def make_client():
    app = FastAPI()
    router = APIRouter()
    register_source_connector_management_routes(router, log=logging.getLogger(__name__))
    app.include_router(router)
    return TestClient(app)


def test_get_source_connectors(monkeypatch):
    monkeypatch.setattr(
        source_connectors,
        "build_source_connectors_response",
        lambda include_prompts=False: {"sources": [], "includePrompts": include_prompts},
    )

    resp = make_client().get("/api/source-connectors?include_prompts=true")

    assert resp.status_code == 200
    assert resp.json() == {"sources": [], "includePrompts": True}


def test_source_connector_prompt_unknown_returns_404(monkeypatch):
    monkeypatch.setattr(source_connectors, "source_prompt_for", lambda _source_id: "")

    resp = make_client().get("/api/source-connectors/missing/prompt")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown source connector: missing"


def test_source_connector_update_rejects_unknown_action():
    resp = make_client().post(
        "/api/source-connectors",
        json={"action": "launch-the-moon", "sourceId": "crm"},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unsupported source connector action"
