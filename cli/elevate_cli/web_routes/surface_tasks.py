"""Surface task and approval routes."""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _SurfaceTaskCreateBody(BaseModel):
    title: str
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    assigned_to: Optional[str] = None
    project: Optional[str] = None
    needs_approval: Optional[bool] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None
    createdBy: Optional[str] = None
    org: Optional[str] = None
    kpi_key: Optional[str] = None
    kpiKey: Optional[str] = None
    due_date: Optional[str] = None
    dueDate: Optional[str] = None
    blocked_by: Optional[List[str]] = None
    blockedBy: Optional[List[str]] = None
    blocks: Optional[List[str]] = None
    actor: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    policyCategory: Optional[str] = None
    policy_category: Optional[str] = None


class _SurfaceTaskPatchBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    assigned_to: Optional[str] = None
    project: Optional[str] = None
    needs_approval: Optional[bool] = None
    notes: Optional[str] = None
    outputs: Optional[List[Any]] = None
    created_by: Optional[str] = None
    createdBy: Optional[str] = None
    org: Optional[str] = None
    kpi_key: Optional[str] = None
    kpiKey: Optional[str] = None
    due_date: Optional[str] = None
    dueDate: Optional[str] = None
    result: Optional[str] = None
    archived: Optional[bool] = None
    blocked_by: Optional[List[str]] = None
    blockedBy: Optional[List[str]] = None
    blocks: Optional[List[str]] = None
    actor: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    policyAction: Optional[str] = None
    policy_action: Optional[str] = None
    policyCategory: Optional[str] = None
    policy_category: Optional[str] = None


class _SurfaceTaskClaimBody(BaseModel):
    agent: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    actor: Optional[str] = None


class _SurfaceTaskArchiveBody(BaseModel):
    dry_run: Optional[bool] = None
    dryRun: Optional[bool] = None
    older_than_days: Optional[int] = None
    olderThanDays: Optional[int] = None


class _SurfaceApprovalResolveBody(BaseModel):
    decision: str
    note: Optional[str] = None


def _body_dump(body: BaseModel) -> dict:
    dump = getattr(body, "model_dump", None)
    if callable(dump):
        return dump()
    return body.dict()


def create_surface_tasks_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/tasks")
    @router.get("/api/surface-tasks")
    def list_surface_tasks(
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        project: Optional[str] = None,
        include_archived: bool = False,
        limit: Optional[int] = None,
    ):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                reaped: list = []
                if status == "pending":
                    try:
                        reaped = st.reap_stale_in_progress(conn)
                        if reaped:
                            _log.warning(
                                "surface-tasks: reaped %d stale in_progress task(s) back to pending",
                                len(reaped),
                            )
                    except Exception:
                        _log.exception("surface-tasks reaper failed (non-fatal)")
                payload = {
                    "tasks": st.list_tasks(
                        conn,
                        status=status,
                        assignee=assignee,
                        priority=priority,
                        project=project,
                        include_archived=include_archived,
                        limit=limit,
                    )
                }
                if reaped:
                    payload["reaped"] = [t.get("id") for t in reaped]
                return payload
        except Exception as exc:
            _log.exception("GET /api/surface-tasks failed")
            raise HTTPException(status_code=500, detail=f"List tasks failed: {exc}")

    @router.post("/api/tasks")
    @router.post("/api/surface-tasks")
    def create_surface_task(body: _SurfaceTaskCreateBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                task = st.create_task(
                    conn,
                    title=body.title,
                    description=body.description,
                    type=body.type or "agent",
                    status=body.status or "pending",
                    priority=body.priority or "normal",
                    assignee=body.assignee or body.assigned_to,
                    project=body.project,
                    needs_approval=bool(body.needs_approval),
                    notes=body.notes,
                    created_by=body.created_by or body.createdBy,
                    org=body.org,
                    kpi_key=body.kpi_key or body.kpiKey,
                    due_date=body.due_date or body.dueDate,
                    blocked_by=body.blocked_by if body.blocked_by is not None else body.blockedBy,
                    blocks=body.blocks,
                    actor=body.actor or "human:web",
                    actor_agent_id=body.agentId or body.agent_id,
                    policy_category=body.policyCategory or body.policy_category or "task",
                )
            return {"ok": True, "task": task}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/surface-tasks failed")
            raise HTTPException(status_code=500, detail=f"Create task failed: {exc}")

    @router.get("/api/tasks/stale")
    @router.get("/api/surface-tasks/stale")
    def check_surface_task_stale():
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                return st.check_stale_tasks(conn)
        except Exception as exc:
            _log.exception("GET /api/surface-tasks/stale failed")
            raise HTTPException(status_code=500, detail=f"Check stale tasks failed: {exc}")

    @router.get("/api/tasks/human")
    @router.get("/api/surface-tasks/human")
    def check_surface_human_tasks():
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                items = st.check_human_tasks(conn)
                return {"tasks": items, "count": len(items)}
        except Exception as exc:
            _log.exception("GET /api/surface-tasks/human failed")
            raise HTTPException(status_code=500, detail=f"Check human tasks failed: {exc}")

    @router.post("/api/tasks/archive")
    @router.post("/api/surface-tasks/archive")
    def archive_surface_tasks(body: _SurfaceTaskArchiveBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                return st.archive_tasks(
                    conn,
                    dry_run=bool(body.dry_run or body.dryRun),
                    older_than_days=body.older_than_days or body.olderThanDays or 7,
                    actor="human:web",
                )
        except Exception as exc:
            _log.exception("POST /api/surface-tasks/archive failed")
            raise HTTPException(status_code=500, detail=f"Archive tasks failed: {exc}")

    @router.post("/api/tasks/compact")
    @router.post("/api/surface-tasks/compact")
    def compact_surface_tasks(body: _SurfaceTaskArchiveBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                return st.compact_tasks(
                    conn,
                    dry_run=bool(body.dry_run or body.dryRun),
                    older_than_days=body.older_than_days or body.olderThanDays or 30,
                    actor="human:web",
                )
        except Exception as exc:
            _log.exception("POST /api/surface-tasks/compact failed")
            raise HTTPException(status_code=500, detail=f"Compact tasks failed: {exc}")

    @router.get("/api/tasks/{task_id}")
    @router.get("/api/surface-tasks/{task_id}")
    def get_surface_task(task_id: str):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                task = st.get_task(conn, task_id)
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            return {"task": task}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/surface-tasks/%s failed", task_id)
            raise HTTPException(status_code=500, detail=f"Get task failed: {exc}")

    @router.get("/api/tasks/{task_id}/audit")
    @router.get("/api/surface-tasks/{task_id}/audit")
    def get_surface_task_audit(task_id: str, limit: int = 200):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                return {"events": st.read_task_audit(conn, task_id, limit=limit)}
        except Exception as exc:
            _log.exception("GET /api/surface-tasks/%s/audit failed", task_id)
            raise HTTPException(status_code=500, detail=f"Read task audit failed: {exc}")

    @router.post("/api/tasks/{task_id}/claim")
    @router.post("/api/surface-tasks/{task_id}/claim")
    def claim_surface_task(task_id: str, body: _SurfaceTaskClaimBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            agent = body.agent or body.agentId or body.agent_id
            if not agent:
                raise HTTPException(status_code=400, detail="agent is required")
            with connect() as conn:
                task = st.claim_task(
                    conn,
                    task_id,
                    agent=agent,
                    actor=body.actor or f"agent:{agent}",
                )
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            return {"ok": True, "task": task}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/surface-tasks/%s/claim failed", task_id)
            raise HTTPException(status_code=500, detail=f"Claim task failed: {exc}")

    @router.patch("/api/tasks/{task_id}")
    @router.patch("/api/surface-tasks/{task_id}")
    def patch_surface_task(task_id: str, body: _SurfaceTaskPatchBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            patch = {k: v for k, v in _body_dump(body).items() if v is not None}
            actor = str(patch.pop("actor", "human:web") or "human:web")
            actor_agent_id = patch.pop("agentId", None) or patch.pop("agent_id", None)
            policy_action = patch.pop("policyAction", None) or patch.pop("policy_action", None)
            policy_category = patch.pop("policyCategory", None) or patch.pop("policy_category", None)
            with connect() as conn:
                task = st.update_task(
                    conn,
                    task_id,
                    patch,
                    actor=actor,
                    actor_agent_id=actor_agent_id,
                    policy_action=policy_action,
                    policy_category=policy_category,
                )
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            return {"ok": True, "task": task}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PATCH /api/surface-tasks/%s failed", task_id)
            raise HTTPException(status_code=500, detail=f"Update task failed: {exc}")

    @router.delete("/api/tasks/{task_id}")
    @router.delete("/api/surface-tasks/{task_id}")
    def delete_surface_task(
        task_id: str,
        actor: Optional[str] = None,
        agentId: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                result = st.request_delete_task(
                    conn,
                    task_id,
                    actor=actor or "human:web",
                    actor_agent_id=agentId or agent_id,
                )
            if result.get("approvalRequired"):
                return result
            if not result.get("ok"):
                raise HTTPException(status_code=404, detail="task not found")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("DELETE /api/surface-tasks/%s failed", task_id)
            raise HTTPException(status_code=500, detail=f"Delete task failed: {exc}")

    @router.get("/api/approvals")
    @router.get("/api/surface-approvals")
    def list_surface_approvals(
        status: Optional[str] = None,
        surface: Optional[str] = None,
        category: Optional[str] = None,
    ):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                return {
                    "approvals": st.list_approvals(
                        conn, status=status, surface=surface, category=category
                    )
                }
        except Exception as exc:
            _log.exception("GET /api/surface-approvals failed")
            raise HTTPException(status_code=500, detail=f"List approvals failed: {exc}")

    @router.patch("/api/approvals/{approval_id}")
    @router.patch("/api/surface-approvals/{approval_id}")
    def resolve_surface_approval(approval_id: str, body: _SurfaceApprovalResolveBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data import surface_tasks as st

            with connect() as conn:
                approval = st.resolve_approval(
                    conn, approval_id, decision=body.decision, note=body.note
                )
            if not approval:
                raise HTTPException(status_code=404, detail="approval not found")
            return {"ok": True, "approval": approval}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PATCH /api/surface-approvals/%s failed", approval_id)
            raise HTTPException(status_code=500, detail=f"Resolve approval failed: {exc}")

    return router
