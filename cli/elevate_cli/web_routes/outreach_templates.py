"""Outreach template routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class OutreachTemplateCreate(BaseModel):
    lane: str
    name: str
    body: str
    channel: str = "any"


class OutreachTemplateUpdate(BaseModel):
    name: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[str] = None
    active: Optional[bool] = None


class OutreachSuggestBody(BaseModel):
    lane: str
    channel: str = "any"
    extraBrief: Optional[str] = None


def create_outreach_templates_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build outreach template CRUD and suggestion routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/outreach/templates")
    async def list_outreach_templates(lane: Optional[str] = None):
        try:
            from elevate_cli import outreach_db

            return {"templates": outreach_db.list_templates(lane=lane)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/outreach/templates failed")
            raise HTTPException(status_code=500, detail=f"List templates failed: {exc}")

    @router.post("/api/outreach/templates")
    async def create_outreach_template(body: OutreachTemplateCreate):
        try:
            from elevate_cli import outreach_db

            return {"template": outreach_db.create_template(
                lane=body.lane, name=body.name, body=body.body, channel=body.channel
            )}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/outreach/templates failed")
            raise HTTPException(status_code=500, detail=f"Create template failed: {exc}")

    @router.put("/api/outreach/templates/{template_id}")
    async def update_outreach_template(template_id: str, body: OutreachTemplateUpdate):
        try:
            from elevate_cli import outreach_db

            return {"template": outreach_db.update_template(
                template_id,
                name=body.name,
                body=body.body,
                channel=body.channel,
                active=body.active,
            )}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/outreach/templates failed")
            raise HTTPException(status_code=500, detail=f"Update template failed: {exc}")

    @router.delete("/api/outreach/templates/{template_id}")
    async def delete_outreach_template(template_id: str):
        try:
            from elevate_cli import outreach_db

            ok = outreach_db.delete_template(template_id)
            return {"ok": ok}
        except Exception as exc:
            _log.exception("DELETE /api/outreach/templates failed")
            raise HTTPException(status_code=500, detail=f"Delete template failed: {exc}")

    @router.get("/api/outreach/templates/overview")
    async def get_outreach_overview():
        try:
            from elevate_cli import outreach_db

            return outreach_db.overview()
        except Exception as exc:
            _log.exception("GET /api/outreach/templates/overview failed")
            raise HTTPException(status_code=500, detail=f"Overview failed: {exc}")

    @router.post("/api/outreach/templates/suggest")
    async def suggest_outreach_template(body: OutreachSuggestBody):
        try:
            from elevate_cli import template_suggester

            saved = template_suggester.suggest_and_save(
                body.lane,
                channel=body.channel,
                extra_brief=body.extraBrief,
            )
            return {"template": saved}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/outreach/templates/suggest failed")
            raise HTTPException(status_code=500, detail=f"Suggest failed: {exc}")

    @router.post("/api/outreach/templates/{template_id}/approve")
    async def approve_outreach_template(template_id: str):
        try:
            from elevate_cli import outreach_db

            return {"template": outreach_db.approve_template(template_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/outreach/templates/approve failed")
            raise HTTPException(status_code=500, detail=f"Approve failed: {exc}")

    @router.post("/api/outreach/templates/{template_id}/reject")
    async def reject_outreach_template(template_id: str):
        try:
            from elevate_cli import outreach_db

            ok = outreach_db.reject_template(template_id)
            return {"ok": ok}
        except Exception as exc:
            _log.exception("POST /api/outreach/templates/reject failed")
            raise HTTPException(status_code=500, detail=f"Reject failed: {exc}")

    return router
