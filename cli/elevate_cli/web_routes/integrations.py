"""Integration settings routes."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class IntegrationSettingsUpdate(BaseModel):
    provider: str = "custom"
    label: str = "CRM"
    apiKeyEnv: str = "CRM_API_KEY"
    apiKey: str = ""
    baseUrl: str = ""
    authType: str = "header"
    authHeader: str = "Authorization"
    authPrefix: str = "Bearer "
    authQueryParam: str = "api_key"
    dbColumns: dict = Field(default_factory=dict)
    endpoints: dict = Field(default_factory=dict)
    action: str = ""


def create_integrations_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build integration settings routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/integrations")
    async def get_integrations():
        try:
            from elevate_cli.source_connectors import get_integration_settings

            return get_integration_settings()
        except Exception as exc:
            _log.exception("GET /api/integrations failed")
            raise HTTPException(status_code=500, detail=f"Integration settings failed: {exc}")

    @router.put("/api/integrations")
    async def update_integrations(body: IntegrationSettingsUpdate):
        try:
            from elevate_cli.source_connectors import save_integration_settings

            return save_integration_settings(body.dict())
        except Exception as exc:
            _log.exception("PUT /api/integrations failed")
            raise HTTPException(status_code=500, detail=f"Integration settings save failed: {exc}")

    @router.post("/api/integrations")
    async def test_integrations(body: IntegrationSettingsUpdate):
        if body.action != "test":
            raise HTTPException(status_code=400, detail="Unsupported integration action")
        try:
            from elevate_cli.source_connectors import test_crm_connection

            return test_crm_connection(body.dict())
        except Exception as exc:
            _log.exception("POST /api/integrations failed")
            raise HTTPException(status_code=500, detail=f"Integration test failed: {exc}")

    return router
