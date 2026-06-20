"""Admin template library routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _TemplateRejectBody(BaseModel):
    reason: str


class _TemplateEditBody(BaseModel):
    body: str


_ADMIN_TEMPLATES_TABS = {"live", "proposed", "retired"}


def create_admin_templates_router(
    *,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/templates")
    def get_admin_templates(
        tab: str = "live",
        lane: Optional[str] = None,
        channel: Optional[str] = None,
    ):
        tab_norm = tab.lower()
        if tab_norm not in _ADMIN_TEMPLATES_TABS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown tab {tab!r} (expected one of {sorted(_ADMIN_TEMPLATES_TABS)})",
            )
        try:
            from elevate_cli.data import (
                connect,
                list_proposed_templates,
                list_templates,
                template_leaderboard,
            )

            with connect() as conn:
                if tab_norm == "live":
                    board = template_leaderboard(conn, lane=lane, channel=channel)
                    return {
                        "tab": "live",
                        "authoritative": board["authoritative"],
                        "trial": board["trial"],
                        "count": len(board["authoritative"]) + len(board["trial"]),
                    }
                if tab_norm == "proposed":
                    rows = list_proposed_templates(conn)
                    return {"tab": "proposed", "items": rows, "count": len(rows)}
                rows = list_templates(conn, status="retired", lane=lane)
                return {"tab": "retired", "items": rows, "count": len(rows)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/templates failed")
            raise HTTPException(status_code=500, detail=f"Admin templates failed: {exc}")

    @router.post("/api/admin/templates/{template_id}/approve")
    def post_admin_template_approve(template_id: str):
        try:
            from elevate_cli.data import approve_template, connect, get_template

            with connect() as conn:
                if get_template(conn, template_id) is None:
                    raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
                return approve_template(conn, template_id, actor=web_actor)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/templates/%s/approve failed", template_id)
            raise HTTPException(status_code=500, detail=f"Approve template failed: {exc}")

    @router.post("/api/admin/templates/{template_id}/reject")
    def post_admin_template_reject(template_id: str, body: _TemplateRejectBody):
        if not body.reason or not body.reason.strip():
            raise HTTPException(status_code=400, detail="reason is required")
        try:
            from elevate_cli.data import connect, get_template, reject_template

            with connect() as conn:
                if get_template(conn, template_id) is None:
                    raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
                return reject_template(
                    conn, template_id, body.reason.strip(), actor=web_actor
                )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/templates/%s/reject failed", template_id)
            raise HTTPException(status_code=500, detail=f"Reject template failed: {exc}")

    @router.post("/api/admin/templates/{template_id}/edit")
    def post_admin_template_edit(template_id: str, body: _TemplateEditBody):
        if not body.body or not body.body.strip():
            raise HTTPException(status_code=400, detail="body is required")
        try:
            from elevate_cli.data import connect, edit_template, get_template

            with connect() as conn:
                if get_template(conn, template_id) is None:
                    raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
                return edit_template(
                    conn, template_id, new_body=body.body, actor=web_actor
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/templates/%s/edit failed", template_id)
            raise HTTPException(status_code=500, detail=f"Edit template failed: {exc}")

    @router.post("/api/admin/templates/{template_id}/retire")
    def post_admin_template_retire(template_id: str):
        try:
            from elevate_cli.data import connect, get_template, retire_template

            with connect() as conn:
                if get_template(conn, template_id) is None:
                    raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")
                return retire_template(conn, template_id, actor=web_actor)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/templates/%s/retire failed", template_id)
            raise HTTPException(status_code=500, detail=f"Retire template failed: {exc}")

    return router
