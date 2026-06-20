"""Admin deal workflow routes."""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from elevate_cli.data.deals import DealPhaseGateBlocked


RequireReady = Callable[[], None]
AdminJurisdictionConfig = Callable[[], Dict[str, str]]


class _DealCreateBody(BaseModel):
    title: str
    side: str
    province: Optional[str] = None
    board: Optional[str] = None
    market: Optional[str] = None
    currentStage: int = 0
    primaryContactId: Optional[str] = None
    loftyContactId: Optional[str] = None
    listingAddress: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    dispatchInitialStage: bool = True
    suppressInitialDispatch: bool = False


class _ProfilePromotionBody(BaseModel):
    profileId: str
    side: str
    displayName: Optional[str] = None
    primaryContactId: Optional[str] = None
    listingAddress: Optional[str] = None
    workflow: Optional[str] = None
    province: Optional[str] = None
    board: Optional[str] = None
    market: Optional[str] = None
    currentStage: int = 0
    profileContext: Dict[str, Any] = Field(default_factory=dict)
    verifiers: List[Dict[str, Any]] = Field(default_factory=list)
    fields: Dict[str, Any] = Field(default_factory=dict)
    dispatchInitialStage: bool = True


class _DealMoveBody(BaseModel):
    toStage: int
    force: bool = False


class _DealToggleBody(BaseModel):
    field: str
    value: Any


class _DealContactBody(BaseModel):
    role: str
    contactId: str
    notes: Optional[str] = None


class _DealAttachmentBody(BaseModel):
    kind: str
    filePath: str
    summary: Optional[str] = None
    sourceRunId: Optional[str] = None
    sourceSnapshotId: Optional[str] = None


class _DealFieldsBody(BaseModel):
    fields: Dict[str, Any]


class _RunResultArtifact(BaseModel):
    kind: str
    file_path: Optional[str] = None
    filePath: Optional[str] = None
    summary: Optional[str] = None
    source_snapshot_id: Optional[str] = None
    sourceSnapshotId: Optional[str] = None


class _RunResultBody(BaseModel):
    status: str
    idempotency_key: Optional[str] = None
    idempotencyKey: Optional[str] = None
    artifacts: List[_RunResultArtifact] = []
    next_tasks: List[Dict[str, Any]] = []
    nextTasks: List[Dict[str, Any]] = []
    checklist_updates: List[Dict[str, Any]] = []
    checklistUpdates: List[Dict[str, Any]] = []
    human_prompt: Optional[Dict[str, Any]] = None
    humanPrompt: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class _DealAdvanceBody(BaseModel):
    force: bool = False


def _model_dump(model: BaseModel) -> dict:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return model.dict(exclude_none=True)


def create_admin_deals_router(
    *,
    require_admin_setup_ready_for_launch: RequireReady,
    admin_jurisdiction_config: AdminJurisdictionConfig,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/deals")
    def get_admin_deals(
        side: Optional[str] = None,
        current_stage: Optional[int] = None,
        status: Optional[str] = "active",
        province: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, list_deals
            from elevate_cli.data.deals import deal_card_gate

            with connect() as conn:
                rows = list_deals(
                    conn,
                    side=side or None,
                    current_stage=current_stage,
                    status=status or None,
                    province=province.strip().upper() if province and province.strip() else None,
                    limit=limit,
                    offset=offset,
                )
                for row in rows:
                    try:
                        scorecard = deal_card_gate(conn, row)
                        row["scorecard"] = scorecard
                        if scorecard.get("progress"):
                            row["progress"] = scorecard["progress"]
                    except Exception:
                        _log.debug("deal_card_gate failed for deal %s", row.get("id"), exc_info=True)
                return {"items": rows, "count": len(rows), "jurisdiction": admin_jurisdiction_config()}
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/deals failed")
            raise HTTPException(status_code=500, detail=f"Admin deals failed: {exc}")

    @router.get("/api/admin/upcoming-events")
    def get_admin_upcoming_events(days: int = 21):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data.admin_calendar import list_upcoming_admin_events

            safe_days = max(1, min(int(days or 21), 90))
            with connect() as conn:
                return list_upcoming_admin_events(conn, days=safe_days)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/upcoming-events failed")
            raise HTTPException(status_code=500, detail=f"Admin upcoming events failed: {exc}")

    @router.post("/api/admin/deals")
    def post_admin_deal(body: _DealCreateBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, create_deal, get_admin_setup

            jurisdiction = admin_jurisdiction_config()
            with connect() as conn:
                setup_profile = (get_admin_setup(conn).get("profile") or {})
                province = body.province if body.province is not None else (jurisdiction["province"] or setup_profile.get("province"))
                market = body.market if body.market is not None else (jurisdiction["market"] or setup_profile.get("market"))
                return create_deal(
                    conn,
                    title=body.title,
                    side=body.side,
                    actor=web_actor,
                    province=(province or "").strip().upper(),
                    board=(body.board or "").strip() or None,
                    market=(market or "").strip() or None,
                    current_stage=body.currentStage,
                    primary_contact_id=body.primaryContactId,
                    lofty_contact_id=body.loftyContactId,
                    listing_address=body.listingAddress,
                    fields=body.fields,
                    dispatch_initial_stage=body.dispatchInitialStage and not body.suppressInitialDispatch,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals failed")
            raise HTTPException(status_code=500, detail=f"Create deal failed: {exc}")

    @router.post("/api/admin/profile-promotions")
    def post_admin_profile_promotion(body: _ProfilePromotionBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, get_admin_setup, promote_profile_to_admin_deal

            jurisdiction = admin_jurisdiction_config()
            with connect() as conn:
                setup_profile = (get_admin_setup(conn).get("profile") or {})
                province = body.province if body.province is not None else (jurisdiction["province"] or setup_profile.get("province"))
                market = body.market if body.market is not None else (jurisdiction["market"] or setup_profile.get("market"))
                return promote_profile_to_admin_deal(
                    conn,
                    profile_id=body.profileId,
                    side=body.side,
                    actor=web_actor,
                    province=(province or "").strip().upper(),
                    board=(body.board or "").strip() or None,
                    market=(market or "").strip() or None,
                    current_stage=body.currentStage,
                    display_name=body.displayName,
                    primary_contact_id=body.primaryContactId,
                    listing_address=body.listingAddress,
                    workflow=body.workflow,
                    profile_context=body.profileContext,
                    verifiers=body.verifiers,
                    fields=body.fields,
                    dispatch_initial_stage=body.dispatchInitialStage,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/profile-promotions failed")
            raise HTTPException(status_code=500, detail=f"Promote profile failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/move")
    def post_admin_deal_move(deal_id: str, body: _DealMoveBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, move_deal_stage

            with connect() as conn:
                return move_deal_stage(
                    conn,
                    deal_id,
                    to_stage=body.toStage,
                    actor=web_actor,
                    force=body.force,
                )
        except HTTPException:
            raise
        except DealPhaseGateBlocked as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "gate": exc.gate,
                },
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/move failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Move deal failed: {exc}")

    @router.get("/api/admin/deals/deadlines")
    def get_admin_deal_deadlines(near_subject_days: int = 21, near_close_days: int = 30):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, deals_overview

            with connect() as conn:
                ov = deals_overview(
                    conn,
                    near_subject_days=near_subject_days,
                    near_close_days=near_close_days,
                )
            return {
                "subjectsSoon": ov.get("subjectsSoon", []),
                "closingsSoon": ov.get("closingsSoon", []),
                "staleStages": ov.get("staleStages", []),
            }
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/deadlines failed")
            raise HTTPException(status_code=500, detail=f"Deadlines failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/toggle")
    def post_admin_deal_toggle(deal_id: str, body: _DealToggleBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, set_deal_toggle

            with connect() as conn:
                return set_deal_toggle(
                    conn,
                    deal_id,
                    field=body.field,
                    value=body.value,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/toggle failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Toggle deal failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/cma-pdf")
    def get_admin_deal_cma_pdf(deal_id: str):
        # Auth is enforced by the dashboard middleware (Bearer header or, for
        # window.open() new-tab loads, the ?token= query param — see web_auth).
        try:
            from elevate_cli.data import connect, list_deal_attachments

            with connect() as conn:
                rows = list_deal_attachments(conn, deal_id, kind="cma_report", limit=1)
            if not rows:
                raise HTTPException(status_code=404, detail="no final CMA on file")
            file_path = rows[0].get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="CMA file missing")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
            )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/cma-pdf failed", deal_id)
            raise HTTPException(status_code=500, detail=f"CMA PDF failed: {exc}")

    @router.get("/api/deals/{deal_id}/context")
    def get_deal_source_context(deal_id: str):
        try:
            from elevate_cli.data import connect, get_deal_context

            with connect() as conn:
                return get_deal_context(conn, deal_id)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/deals/%s/context failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal context failed: {exc}")

    @router.post("/api/deals/{deal_id}/fields")
    def post_deal_fields(deal_id: str, body: _DealFieldsBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, set_deal_fields

            with connect() as conn:
                return set_deal_fields(conn, deal_id, actor=web_actor, fields=body.fields)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/fields failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal field update failed: {exc}")

    @router.post("/api/deals/{deal_id}/advance")
    def post_deal_advance(deal_id: str, body: _DealAdvanceBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, get_deal_context, move_deal_stage

            with connect() as conn:
                context = get_deal_context(conn, deal_id)
                gate = ((context.get("dealFlow") or {}).get("gate") or {})
                next_stage = gate.get("nextStage")
                if next_stage is None:
                    raise HTTPException(status_code=400, detail="deal is already at the final stage")
                if not body.force and not gate.get("canAdvance"):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "deal phase gate is blocked",
                            "gate": gate,
                        },
                    )
                move_deal_stage(
                    conn,
                    deal_id,
                    to_stage=int(next_stage),
                    actor=web_actor,
                    force=body.force,
                    gate_checked=not body.force,
                )
                return get_deal_context(conn, deal_id)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/advance failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal advance failed: {exc}")

    @router.post("/api/deals/{deal_id}/contacts")
    def post_deal_contact(deal_id: str, body: _DealContactBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import add_deal_contact, connect

            with connect() as conn:
                return add_deal_contact(
                    conn,
                    deal_id,
                    role=body.role,
                    contact_id=body.contactId,
                    notes=body.notes,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/contacts failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal contact link failed: {exc}")

    @router.post("/api/deals/{deal_id}/attachments")
    def post_deal_attachment(deal_id: str, body: _DealAttachmentBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import add_deal_attachment, connect

            with connect() as conn:
                return add_deal_attachment(
                    conn,
                    deal_id,
                    kind=body.kind,
                    file_path=body.filePath,
                    summary=body.summary,
                    source_run_id=body.sourceRunId,
                    source_snapshot_id=body.sourceSnapshotId,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/attachments failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal attachment failed: {exc}")

    @router.post("/api/deals/{deal_id}/runs/{run_id}/result")
    def post_deal_run_result(deal_id: str, run_id: str, body: _RunResultBody):
        try:
            from elevate_cli.data import connect, record_run_result

            artifacts = [_model_dump(item) for item in body.artifacts]
            next_tasks = body.next_tasks or body.nextTasks
            checklist_updates = body.checklist_updates or body.checklistUpdates
            human_prompt = body.human_prompt or body.humanPrompt
            idempotency_key = body.idempotency_key or body.idempotencyKey
            with connect() as conn:
                return record_run_result(
                    conn,
                    deal_id,
                    run_id,
                    status=body.status,
                    idempotency_key=idempotency_key,
                    artifacts=artifacts,
                    next_tasks=next_tasks,
                    checklist_updates=checklist_updates,
                    human_prompt=human_prompt,
                    error=body.error,
                    actor="skill:web-callback",
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/runs/%s/result failed", deal_id, run_id)
            raise HTTPException(status_code=500, detail=f"Deal run result failed: {exc}")

    return router
