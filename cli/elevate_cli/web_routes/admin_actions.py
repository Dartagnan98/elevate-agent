"""Admin action registry, run, and task routes."""

import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


RequireReady = Callable[[], None]


class _AdminTaskRunBody(BaseModel):
    dealId: str
    skill: str
    title: Optional[str] = None
    sourceTaskId: Optional[str] = None
    runNow: bool = True


class _ActionRunApproveBody(BaseModel):
    approved: bool = True
    runNow: bool = True


class _AdminActionCreateBody(BaseModel):
    name: str
    trigger: str
    skill: str
    side: Optional[str] = None
    fromStage: Optional[int] = None
    toStage: Optional[int] = None
    fieldKey: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    skillArgs: Optional[Dict[str, Any]] = None
    provinceFilter: Optional[List[str]] = None
    enabled: bool = True
    priority: int = 0
    approvalRequired: bool = False


class _AdminActionUpdateBody(BaseModel):
    name: Optional[str] = None
    trigger: Optional[str] = None
    skill: Optional[str] = None
    side: Optional[str] = None
    fromStage: Optional[int] = None
    toStage: Optional[int] = None
    fieldKey: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    skillArgs: Optional[Dict[str, Any]] = None
    provinceFilter: Optional[List[str]] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    approvalRequired: Optional[bool] = None


def create_admin_actions_router(
    *,
    require_admin_setup_ready_for_launch: RequireReady,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/actions")
    def get_admin_actions(
        trigger: Optional[str] = None,
        side: Optional[str] = None,
        enabled: Optional[bool] = None,
        skill: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, list_actions

            with connect() as conn:
                rows = list_actions(
                    conn,
                    trigger=trigger or None,
                    side=side or None,
                    enabled=enabled,
                    skill=skill or None,
                    limit=limit,
                    offset=offset,
                )
                return {"items": rows, "count": len(rows)}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/actions failed")
            raise HTTPException(status_code=500, detail=f"Admin actions failed: {exc}")

    @router.post("/api/admin/actions")
    def post_admin_action(body: _AdminActionCreateBody):
        try:
            from elevate_cli.data import connect, create_action

            with connect() as conn:
                return create_action(
                    conn,
                    name=body.name,
                    trigger=body.trigger,
                    skill=body.skill,
                    side=body.side,
                    from_stage=body.fromStage,
                    to_stage=body.toStage,
                    field_key=body.fieldKey,
                    condition=body.condition,
                    skill_args=body.skillArgs,
                    province_filter=body.provinceFilter,
                    enabled=body.enabled,
                    priority=body.priority,
                    approval_required=body.approvalRequired,
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/actions failed")
            raise HTTPException(status_code=500, detail=f"Create action failed: {exc}")

    @router.post("/api/admin/actions/defaults")
    def post_admin_actions_defaults():
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, ensure_default_admin_actions

            with connect() as conn:
                return ensure_default_admin_actions(conn)
        except Exception as exc:
            _log.exception("POST /api/admin/actions/defaults failed")
            raise HTTPException(status_code=500, detail=f"Seed default admin actions failed: {exc}")

    @router.patch("/api/admin/actions/{action_id}")
    def patch_admin_action(action_id: str, body: _AdminActionUpdateBody):
        try:
            from elevate_cli.data import connect, update_action

            with connect() as conn:
                return update_action(
                    conn,
                    action_id,
                    name=body.name,
                    trigger=body.trigger,
                    skill=body.skill,
                    side=body.side,
                    from_stage=body.fromStage,
                    to_stage=body.toStage,
                    field_key=body.fieldKey,
                    condition=body.condition,
                    skill_args=body.skillArgs,
                    province_filter=body.provinceFilter,
                    enabled=body.enabled,
                    priority=body.priority,
                    approval_required=body.approvalRequired,
                )
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PATCH /api/admin/actions/%s failed", action_id)
            raise HTTPException(status_code=500, detail=f"Update action failed: {exc}")

    @router.delete("/api/admin/actions/{action_id}")
    def delete_admin_action(action_id: str):
        try:
            from elevate_cli.data import connect, delete_action

            with connect() as conn:
                delete_action(conn, action_id)
            return {"ok": True, "id": action_id}
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("DELETE /api/admin/actions/%s failed", action_id)
            raise HTTPException(status_code=500, detail=f"Delete action failed: {exc}")

    @router.get("/api/admin/action-runs")
    def get_admin_action_runs(
        deal_id: Optional[str] = None,
        registry_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, list_action_runs

            with connect() as conn:
                rows = list_action_runs(
                    conn,
                    deal_id=deal_id or None,
                    registry_id=registry_id or None,
                    status=status or None,
                    limit=limit,
                    offset=offset,
                )
                return {"items": rows, "count": len(rows)}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/action-runs failed")
            raise HTTPException(status_code=500, detail=f"Admin runs failed: {exc}")

    @router.post("/api/admin/action-runs/drain")
    def post_admin_action_runs_drain(limit: int = 50):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, drain_queued_action_runs

            with connect() as conn:
                rows = drain_queued_action_runs(
                    conn,
                    limit=max(1, min(200, int(limit))),
                    actor=web_actor,
                )
            return {"items": rows, "count": len(rows)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/action-runs/drain failed")
            raise HTTPException(status_code=500, detail=f"Drain action runs failed: {exc}")

    @router.post("/api/admin/action-runs/{run_id}/approve")
    def post_admin_action_run_approve(run_id: str, body: _ActionRunApproveBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import approve_action_run, connect

            with connect() as conn:
                return approve_action_run(
                    conn,
                    run_id,
                    approved=body.approved,
                    actor=web_actor,
                    create_cron_job=body.runNow,
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/action-runs/%s/approve failed", run_id)
            raise HTTPException(status_code=500, detail=f"Approve action run failed: {exc}")

    @router.get("/api/admin/tasks")
    def get_admin_tasks(
        status: Optional[str] = "open",
        limit: int = 100,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, list_deal_tasks

            with connect() as conn:
                rows = list_deal_tasks(
                    conn,
                    status=status or "open",
                    limit=limit,
                    offset=offset,
                )
                return {"items": rows, "count": len(rows)}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/tasks failed")
            raise HTTPException(status_code=500, detail=f"Admin tasks failed: {exc}")

    @router.post("/api/admin/tasks/run")
    def post_admin_task_run(body: _AdminTaskRunBody):
        if not body.dealId or not body.dealId.strip():
            raise HTTPException(status_code=400, detail="dealId is required")
        if not body.skill or not body.skill.strip():
            raise HTTPException(status_code=400, detail="skill is required")
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, queue_action_run

            with connect() as conn:
                return queue_action_run(
                    conn,
                    deal_id=body.dealId,
                    skill=body.skill,
                    name=body.title or f"Task board: {body.skill}",
                    payload={
                        "trigger": "task_board",
                        "sourceTaskId": body.sourceTaskId,
                        "taskTitle": body.title,
                    },
                    create_cron_job=body.runNow,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/tasks/run failed")
            raise HTTPException(status_code=500, detail=f"Run admin task failed: {exc}")

    return router
