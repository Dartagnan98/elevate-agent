"""Ayrshare publisher routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class AyrshareKeyBody(BaseModel):
    apiKey: str


def create_ayrshare_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build Ayrshare publisher routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/ayrshare/status")
    async def ayrshare_status():
        try:
            from elevate_cli import ayrshare_client

            return ayrshare_client.get_status()
        except Exception as exc:
            _log.exception("GET /api/ayrshare/status failed")
            raise HTTPException(status_code=500, detail=f"Ayrshare status failed: {exc}")

    @router.post("/api/ayrshare/key")
    async def ayrshare_set_key(body: AyrshareKeyBody):
        try:
            from elevate_cli import ayrshare_client

            result = ayrshare_client.set_api_key(body.apiKey)
            if not result.get("ok"):
                raise HTTPException(status_code=400, detail=result.get("error", "Invalid key"))
            return ayrshare_client.get_status()
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/ayrshare/key failed")
            raise HTTPException(status_code=500, detail=f"Set Ayrshare key failed: {exc}")

    @router.delete("/api/ayrshare/key")
    async def ayrshare_clear_key():
        try:
            from elevate_cli import ayrshare_client

            ayrshare_client.clear_api_key()
            return ayrshare_client.get_status()
        except Exception as exc:
            _log.exception("DELETE /api/ayrshare/key failed")
            raise HTTPException(status_code=500, detail=f"Clear Ayrshare key failed: {exc}")

    @router.get("/api/ayrshare/profiles")
    async def ayrshare_profiles():
        try:
            from elevate_cli import ayrshare_client

            return ayrshare_client.profiles()
        except Exception as exc:
            _log.exception("GET /api/ayrshare/profiles failed")
            raise HTTPException(status_code=500, detail=f"Ayrshare profiles failed: {exc}")

    @router.get("/api/ayrshare/scheduled")
    async def ayrshare_scheduled():
        try:
            from elevate_cli import ayrshare_client

            return ayrshare_client.list_scheduled()
        except Exception as exc:
            _log.exception("GET /api/ayrshare/scheduled failed")
            raise HTTPException(status_code=500, detail=f"Ayrshare scheduled failed: {exc}")

    @router.get("/api/ayrshare/history")
    async def ayrshare_history(last_records: int = 100, last_days: Optional[int] = None):
        try:
            from elevate_cli import ayrshare_client

            return ayrshare_client.history(last_records=last_records, last_days=last_days)
        except Exception as exc:
            _log.exception("GET /api/ayrshare/history failed")
            raise HTTPException(status_code=500, detail=f"Ayrshare history failed: {exc}")

    return router
