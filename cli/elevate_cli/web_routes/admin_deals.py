"""Admin deal workflow routes."""

import logging
import os
import re
from datetime import datetime, timezone
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


class _DealCollapseBody(BaseModel):
    side: Optional[str] = None


class _DealToggleBody(BaseModel):
    field: str
    value: Any


class _GatherCpsBody(BaseModel):
    mls: str
    deal_id: Optional[str] = None
    dry_run: bool = False


class _GenerateCpsBody(BaseModel):
    umbrella: str
    clauses: List[str] = []
    customClauses: List[Dict[str, Any]] = []
    vars: Dict[str, Any] = {}
    address: Optional[str] = None
    deal_id: Optional[str] = None
    dry_run: bool = False
    forms: Optional[List[str]] = None  # which accessory forms to include in the package


class _GenerateFormBody(BaseModel):
    form: str            # pnc | dorts | disclosure-rem
    address: Optional[str] = None
    deal_id: Optional[str] = None
    dry_run: bool = False


class _OnboardingDocBody(BaseModel):
    form: str            # agency | dorts | pnc


class _CmaRunBody(BaseModel):
    phase: str           # collect | actives | normalize | finish | render | qa


class _CmaCompToggleBody(BaseModel):
    mls: str
    kind: str            # sold | active


class _CmaRegenBody(BaseModel):
    instructions: str = ""   # free text, e.g. "expand to Westsyde + Westmount, target $635k"


class _CmaRepriceBody(BaseModel):
    price: str = ""          # exact target list price, e.g. "$635,000"
    rationale: str = ""      # the operator's "why" (folded into the CMA narrative)


class _CmaCaptureProspectingBody(BaseModel):
    mls: str                 # the active comp the operator chose as the prospecting anchor


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


class _KitDocApproveBody(BaseModel):
    # Toggle an offer-kit document's status from the card (approved / draft).
    status: Optional[str] = "approved"


class _KitFieldBody(BaseModel):
    # Save one editable kit-document field (the in-app, phone-friendly form input).
    key: str
    value: Optional[str] = ""


class _PullListingBody(BaseModel):
    # Pull a listing's docs/title/facts from Xposure by MLS #.
    mls: str


class _KitAddBody(BaseModel):
    # Add a form to the offer kit: upload a PDF (base64) or pick a catalog template.
    templateId: Optional[str] = None
    name: Optional[str] = None
    filename: Optional[str] = None
    contentB64: Optional[str] = None


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


_COLLAPSE_ACTOR = "dashboard:deal-collapsed-button"
_LISTING_RESET_STAGE = 5
_BUYER_RESET_STAGE = 0
_LISTING_CLEAR_FIELDS: Dict[str, Any] = {
    "offerDate": None,
    "subjectRemovalDate": None,
    "depositDueDate": None,
    "completionDate": None,
    "possessionDate": None,
    "offerPrice": None,
    "depositAmount": None,
    "offerAcceptedAt": None,
    "subjectsRemovedAt": None,
    "completedAt": None,
    "depositInTrustAt": None,
}
_BUYER_CLEAR_FIELDS: Dict[str, Any] = {
    **_LISTING_CLEAR_FIELDS,
    "mlsNumber": None,
    "legalDescription": None,
    "lotSizeSqft": None,
    "yearBuilt": None,
    "listPrice": None,
    "listingDate": None,
    "listingPublishedAt": None,
}
_LISTING_EXTRA_RE = re.compile(
    r"(buyer|purchaser|offer|accepted|deposit|subject|completion|possession|adjustment)",
    re.I,
)
_BUYER_EXTRA_RE = re.compile(
    r"(property|listing|address|mls|legal|pid|strata|offer|accepted|deposit|subject|completion|possession|adjustment)",
    re.I,
)
_BUYER_ROLE_RE = re.compile(r"(buyer|purchaser|tenant)", re.I)


def _collapse_contact_name(item: Dict[str, Any]) -> str | None:
    contact = item.get("contact") or {}
    if not isinstance(contact, dict):
        return None
    for key in ("displayName", "display_name", "name", "fullName", "primaryEmail", "primary_email"):
        value = contact.get(key)
        if value:
            return str(value)
    return None


def _scrub_extra_toggles(conn: Any, deal_id: str, pattern: re.Pattern[str]) -> Dict[str, Any]:
    from elevate_cli.data.deals import _decode_json, _encode_json

    row = conn.execute("SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)).fetchone()
    extra = _decode_json(row["extra_toggles_json"]) if row and row["extra_toggles_json"] else {}
    if not isinstance(extra, dict):
        extra = {}
    removed = {key: extra[key] for key in list(extra.keys()) if pattern.search(str(key))}
    if removed:
        for key in removed:
            extra.pop(key, None)
        conn.execute(
            "UPDATE deals SET extra_toggles_json=?, updated_at=? WHERE id=?",
            (
                _encode_json(extra),
                datetime.now(timezone.utc).isoformat(),
                deal_id,
            ),
        )
    return removed


def _remove_listing_buyers(conn: Any, deal_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, role, contact_id, notes FROM deal_contacts WHERE deal_id=?",
        (deal_id,),
    ).fetchall()
    removed: List[Dict[str, Any]] = []
    for row in rows:
        role = str(row["role"] or "")
        if _BUYER_ROLE_RE.search(role):
            removed.append(
                {
                    "id": row["id"],
                    "role": role,
                    "contactId": row["contact_id"],
                    "notes": row["notes"],
                }
            )
            conn.execute("DELETE FROM deal_contacts WHERE id=?", (row["id"],))
    return removed


def _maybe_rename_buyer_card(conn: Any, deal_id: str) -> str | None:
    from elevate_cli.data import list_deal_contacts

    contacts = list_deal_contacts(conn, deal_id)
    buyer_names: List[str] = []
    for item in contacts:
        role = str(item.get("role") or "")
        if _BUYER_ROLE_RE.search(role) or role.lower() in {"client", "primary"}:
            name = _collapse_contact_name(item)
            if name and name not in buyer_names:
                buyer_names.append(name)
    if not buyer_names:
        return None
    new_title = "Buyer: " + " & ".join(buyer_names[:2])
    conn.execute(
        "UPDATE deals SET title=?, updated_at=? WHERE id=?",
        (
            new_title,
            datetime.now(timezone.utc).isoformat(),
            deal_id,
        ),
    )
    return new_title


def _collapse_admin_deal(conn: Any, deal_id: str, requested_side: str | None) -> Dict[str, Any]:
    from elevate_cli.data import get_deal, move_deal_stage, set_deal_fields, set_deal_toggle
    from elevate_cli.data.deals import _insert_deal_event

    deal = get_deal(conn, deal_id)
    if deal is None:
        raise LookupError(f"deal {deal_id!r} not found")
    side = requested_side or deal.get("side")
    if side not in {"listing", "buyer"}:
        raise ValueError(f"unsupported deal side {side!r}")
    current_stage = int(deal.get("currentStage") or 0)
    if side == "listing" and current_stage not in {6, 7}:
        raise ValueError("listing deal collapse is only available from Accepted Offer or Condition Removal")
    if side == "buyer" and current_stage not in {1, 2, 3}:
        raise ValueError("buyer deal collapse is only available from accepted-offer buyer stages")

    target_stage = _LISTING_RESET_STAGE if side == "listing" else _BUYER_RESET_STAGE
    clear_fields = _LISTING_CLEAR_FIELDS if side == "listing" else _BUYER_CLEAR_FIELDS
    removed_contacts = _remove_listing_buyers(conn, deal_id) if side == "listing" else []
    removed_extra = _scrub_extra_toggles(conn, deal_id, _LISTING_EXTRA_RE if side == "listing" else _BUYER_EXTRA_RE)
    new_title = None

    set_deal_fields(conn, deal_id, actor=_COLLAPSE_ACTOR, fields=clear_fields)
    if side == "buyer":
        conn.execute(
            "UPDATE deals SET listing_address=NULL, source_row_id=NULL, updated_at=? WHERE id=?",
            (
                datetime.now(timezone.utc).isoformat(),
                deal_id,
            ),
        )
        new_title = _maybe_rename_buyer_card(conn, deal_id)
    set_deal_toggle(conn, deal_id, field="deal_collapsed", value=True, actor=_COLLAPSE_ACTOR)
    set_deal_toggle(conn, deal_id, field="collapsed_reset_target_stage", value=target_stage, actor=_COLLAPSE_ACTOR)
    set_deal_toggle(conn, deal_id, field="collapsed_reset_side", value=side, actor=_COLLAPSE_ACTOR)
    moved = move_deal_stage(conn, deal_id, to_stage=target_stage, actor=_COLLAPSE_ACTOR, force=True)
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="toggle_change",
        actor=_COLLAPSE_ACTOR,
        field_name="deal_collapsed_reset",
        old_value={"stage": current_stage, "side": side},
        new_value={"stage": target_stage, "side": side},
        payload={
            "reason": "deal_collapsed_button",
            "listingBehavior": "move_to_listing_live_and_clear_previous_buyers",
            "buyerBehavior": "move_to_top_25_and_clear_property_information",
            "clearedFields": sorted(clear_fields.keys()),
            "removedBuyerContacts": removed_contacts,
            "removedExtraKeys": sorted(removed_extra.keys()),
            "newTitle": new_title,
        },
    )
    return {
        "success": True,
        "deal": moved,
        "targetStage": target_stage,
        "removedBuyerContacts": len(removed_contacts),
        "removedExtraKeys": sorted(removed_extra.keys()),
        "newTitle": new_title,
    }


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

    @router.post("/api/admin/deals/{deal_id}/collapse")
    def post_admin_deal_collapse(deal_id: str, body: _DealCollapseBody):
        try:
            require_admin_setup_ready_for_launch()
            requested_side = body.side if body.side in {"listing", "buyer", None} else None
            from elevate_cli.data import connect

            with connect() as conn:
                result = _collapse_admin_deal(conn, deal_id, requested_side)
                conn.commit()
                return result
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/collapse failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Collapse deal failed: {exc}")

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
                content_disposition_type="inline",
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

    @router.get("/api/admin/deals/{deal_id}/kit-doc/{doc_id}")
    def get_admin_deal_kit_doc(deal_id: str, doc_id: str, download: int = 0):
        # Serve one offer-kit document PDF. download=0 → inline (quick read-only
        # view in a browser tab). download=1 → attachment, so it saves and opens
        # in Preview/Acrobat where the AcroForm fields are actually editable
        # (browser tabs render forms read-only). Auth: Bearer header or ?token=.
        try:
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="deal not found")
            raw = row["extra_toggles_json"]
            toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            docs = ((toggles.get("offerKit") or {}).get("documents") or [])
            doc = next((d for d in docs if d.get("id") == doc_id), None)
            if not doc:
                raise HTTPException(status_code=404, detail="kit document not found")
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="kit document not generated yet")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="attachment" if download else "inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/kit-doc/%s failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit doc failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/approve")
    def post_admin_deal_kit_doc_approve(deal_id: str, doc_id: str, body: _KitDocApproveBody):
        # Toggle a kit document's status (approved / draft) from the card.
        try:
            import json as _json
            from elevate_cli.data import connect

            new_status = (body.status or "approved").strip() or "approved"
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                docs = kit.get("documents") or []
                found = False
                for d in docs:
                    if d.get("id") == doc_id:
                        d["status"] = new_status
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="kit document not found")
                kit["documents"] = docs
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "status": new_status}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/%s/approve failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit doc approve failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/field")
    def post_admin_deal_kit_doc_field(deal_id: str, doc_id: str, body: _KitFieldBody):
        # Save one editable form field for a kit document (the in-app inputs the
        # operator edits on the card / on their phone).
        try:
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                found = False
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        flds = d.get("fields") or {}
                        flds[body.key] = body.value or ""
                        d["fields"] = flds
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="kit document not found")
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "key": body.key, "value": body.value}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/%s/field failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit field save failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/generate")
    def post_admin_deal_kit_doc_generate(deal_id: str, doc_id: str):
        # Fill the official fillable form template from the document's card fields
        # and write the per-deal editable PDF. This is the "Generate" button: the
        # operator edits fields on the card, then generates the compliant PDF.
        try:
            import json as _json
            import subprocess
            import tempfile
            from elevate_cli.data import connect

            FORMS = "/Users/admin/skyleigh-tools/knowledge/deals/forms"
            ENGINE = f"{FORMS}/fill-form-generic.py"
            TEMPLATES = {
                "cps-residential": f"{FORMS}/cps-residential-fillable-template.pdf",
                "cps-addendum": f"{FORMS}/cps-addendum-template.pdf",
                "disclosure-remuneration": f"{FORMS}/disclosure-remuneration-template.pdf",
                "privacy-notice": f"{FORMS}/privacy-notice-template.pdf",
                "bcfsa-disclosure": f"{FORMS}/bcfsa-disclosure-template.pdf",
                "condition-waiver": f"{FORMS}/condition-waiver-template.pdf",
                "subject-removal": f"{FORMS}/subject-removal-template.pdf",
            }
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                docs = kit.get("documents") or []
                doc = next((d for d in docs if d.get("id") == doc_id), None)
                if not doc:
                    raise HTTPException(status_code=404, detail="kit document not found")
            if doc_id not in TEMPLATES:
                raise HTTPException(status_code=400, detail="no template wired for this document yet")
            template = TEMPLATES[doc_id]
            # Canonical data lives on the CPS doc's fields; every form fills from it.
            cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
            cf = cps.get("fields") or {}
            pp = [x.strip() for x in str(cf.get("property", "")).split(",")]
            pnum = pstreet = pcity = pstate = pzip = ""
            if pp and pp[0]:
                sp = pp[0].split(" ", 1)
                if sp and sp[0].isdigit():
                    pnum, pstreet = sp[0], (sp[1] if len(sp) > 1 else "")
                else:
                    pstreet = pp[0]
            if len(pp) >= 2:
                pcity = pp[1]
            if len(pp) >= 3:
                ps = pp[2].split(" ", 1)
                pstate, pzip = ps[0], (ps[1] if len(ps) > 1 else "")
            sellers = [x.strip() for x in str(toggles.get("sellerNames") or "").split(",") if x.strip()]
            import datetime as _dt
            today = _dt.date.today().isoformat()
            context = {
                "buyer1": cf.get("buyer1", ""), "buyer2": cf.get("buyer2", ""), "buyer3": cf.get("buyer3", ""),
                "seller1": sellers[0] if len(sellers) > 0 else "",
                "seller2": sellers[1] if len(sellers) > 1 else "",
                "p_streetnum": pnum, "p_street": pstreet, "p_city": pcity, "p_state": pstate, "p_zip": pzip,
                "mls": str(toggles.get("mlsNumber") or toggles.get("mls") or ""),
                "agentName": "Skyleigh McCallum", "officeName": "Forever Real Estate Group",
                "price": cf.get("price", ""), "priceWords": cf.get("priceWords", ""),
                "deposit": cf.get("deposit", ""), "depositHolder": cf.get("depositHolder", ""),
                "completionDate": cf.get("completionDate", ""), "possessionDate": cf.get("possessionDate", ""),
                "adjustmentDate": cf.get("adjustmentDate", ""),
                "included": cf.get("included", ""), "excluded": cf.get("excluded", ""), "conditions": cf.get("conditions", ""),
                "today": today, "contractDate": cf.get("contractDate", "") or today,
            }
            # Assemble the wizard's selected subjects/clauses into the CPS Section-3
            # terms text (numbered, sole-benefit line). Overrides the free-text
            # conditions so the contract reflects the Subjects step.
            cps_clauses = toggles.get("cpsClauses") or []
            if cps_clauses:
                asm_input = {
                    "umbrella": toggles.get("cpsUmbrella") or "residential",
                    "selections": cps_clauses,
                    "vars": {**(toggles.get("cpsVars") or {}), "subject_removal_date": toggles.get("subjectRemovalDate") or ""},
                    "custom": toggles.get("cpsCustomClauses") or [],
                }
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as af:
                    _json.dump(asm_input, af)
                    asm_path = af.name
                asm = subprocess.run(
                    ["/usr/bin/python3", f"{FORMS}/assemble-cps-terms.py", asm_path],
                    capture_output=True, text=True, timeout=30,
                    env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"},
                )
                try:
                    os.unlink(asm_path)
                except Exception:
                    pass
                if asm.returncode == 0 and asm.stdout.strip():
                    context["conditions"] = asm.stdout.strip()
            out_path = doc.get("filePath") or (
                f"/Users/admin/.elevate/cache/documents/admin_artifacts/offer-kits/{deal_id}-{doc_id}.pdf"
            )
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                _json.dump(context, tf)
                ctx_path = tf.name
            # Clean env: the app sets PYTHON* vars that point /usr/bin/python3 at the
            # app runtime (no pypdf). HOME must be set so it finds user-site pypdf.
            proc = subprocess.run(
                ["/usr/bin/python3", ENGINE, ctx_path, template, out_path],
                capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"},
            )
            try:
                os.unlink(ctx_path)
            except Exception:
                pass
            if proc.returncode != 0:
                raise HTTPException(status_code=500, detail=f"fill failed: {(proc.stderr or '')[:300]}")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        d["filePath"] = out_path
                        d["ready"] = True
                        d["status"] = "draft"
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "generated": True}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/%s/generate failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Generate failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/offer-kit/build")
    def post_admin_deal_build_offer_kit(deal_id: str):
        # Build / refresh the offer kit for a buyer deal, seeding each document's
        # fields from the deal's data so most of the form is pre-filled. Preserves
        # operator edits on an existing kit (the deal only fills blanks).
        try:
            import json as _json
            from elevate_cli.data import connect

            KITDIR = "/Users/admin/.elevate/cache/documents/admin_artifacts/offer-kits"
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json, listing_address FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                listing = row["listing_address"] or ""

                def ao(k):
                    return str(toggles.get("acceptedOffer." + k) or "")

                bn = toggles.get("buyerNames") or ", ".join(toggles.get("skyslopeBuyerNames") or [])
                parts = [p.strip() for p in str(bn).split(",") if p.strip()]
                seeded = {
                    "buyer1": parts[0] if len(parts) > 0 else "",
                    "buyer2": parts[1] if len(parts) > 1 else "",
                    "property": listing,
                    "price": ao("purchasePrice"),
                    "priceWords": "",
                    "deposit": ao("depositAmount"),
                    "depositHolder": ao("depositHolder") or "Listing Brokerage in trust",
                    "completionDate": ao("completionDate"),
                    "possessionDate": ao("possessionDate"),
                    "adjustmentDate": ao("adjustmentDate"),
                    "included": ao("includedItems"),
                    "excluded": ao("excludedItems"),
                    "conditions": str(toggles.get("subjectConditions") or ""),
                }
                existing = toggles.get("offerKit") or {}
                ex_cps = next((d for d in (existing.get("documents") or []) if d.get("id") == "cps-residential"), None)
                cps_path = (ex_cps or {}).get("filePath") or f"{KITDIR}/{deal_id}-cps-residential.pdf"
                fields = dict(seeded)
                for k, v in ((ex_cps or {}).get("fields") or {}).items():
                    if v:
                        fields[k] = v  # keep existing operator edits
                kit = {
                    "createdAt": existing.get("createdAt") or "",
                    "documents": [
                        {"id": "cps-residential", "name": "CPS - Residential", "status": (ex_cps or {}).get("status", "draft"), "fillable": True, "ready": True, "filePath": cps_path, "fields": fields},
                        {"id": "cps-addendum", "name": "CPS - Addendum / Amendment", "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-cps-addendum.pdf"},
                        {"id": "disclosure-remuneration", "name": "Disclosure of Remuneration (RECBC 5-11)", "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-disclosure-remuneration.pdf"},
                        {"id": "privacy-notice", "name": "Privacy Notice and Consent", "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-privacy-notice.pdf"},
                        {"id": "bcfsa-disclosure", "name": "BCFSA - Disclosure of Representation", "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-bcfsa-disclosure.pdf"},
                        {"id": "condition-waiver", "name": "Notice of Condition Waiver / Declaration of Fulfillment", "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-condition-waiver.pdf"},
                    ],
                }
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"built": True, "documents": len(kit["documents"])}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/offer-kit/build failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Build offer kit failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/add")
    def post_admin_deal_kit_doc_add(deal_id: str, body: _KitAddBody):
        # Add a form to the offer kit: upload a PDF (base64 in contentB64) or pick
        # a wired catalog template (templateId). Appends to offerKit.documents.
        try:
            import json as _json
            import base64 as _b64
            import re as _re
            from elevate_cli.data import connect

            KITDIR = "/Users/admin/.elevate/cache/documents/admin_artifacts/offer-kits"
            os.makedirs(KITDIR, exist_ok=True)
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {"createdAt": "", "documents": []}
                docs = kit.get("documents") or []
                if body.contentB64:
                    fname = (body.filename or "form.pdf").strip()
                    if not fname.lower().endswith(".pdf"):
                        fname += ".pdf"
                    slug = _re.sub(r"[^a-z0-9]+", "-", fname.lower().rsplit(".", 1)[0]).strip("-") or "form"
                    doc_id = "custom-" + slug
                    n = 2
                    while any(d.get("id") == doc_id for d in docs):
                        doc_id = f"custom-{slug}-{n}"
                        n += 1
                    try:
                        data = _b64.b64decode(body.contentB64)
                    except Exception:
                        raise HTTPException(status_code=400, detail="bad file content")
                    out_path = f"{KITDIR}/{deal_id}-{doc_id}.pdf"
                    with open(out_path, "wb") as fh:
                        fh.write(data)
                    docs.append({"id": doc_id, "name": fname, "status": "draft", "fillable": False, "ready": True, "filePath": out_path})
                elif body.templateId:
                    tid = body.templateId.strip()
                    if any(d.get("id") == tid for d in docs):
                        raise HTTPException(status_code=400, detail="already in kit")
                    cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
                    docs.append({"id": tid, "name": (body.name or tid), "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-{tid}.pdf", "fields": dict(cps.get("fields") or {})})
                else:
                    raise HTTPException(status_code=400, detail="need a file or templateId")
                kit["documents"] = docs
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"ok": True, "documents": len(docs)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/add failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Add form failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/pull-listing")
    def post_admin_deal_pull_listing(deal_id: str, body: _PullListingBody):
        # Kick off the Xposure listing pull (docs + title + facts incl. postal
        # code) in the background and mark the deal as pulling. The scraper writes
        # results back via the dashboard API and flips listingPullStatus when done.
        try:
            import json as _json
            import subprocess
            from elevate_cli.data import connect

            mls = (body.mls or "").strip()
            if not mls:
                raise HTTPException(status_code=400, detail="mls required")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                toggles["mlsNumber"] = mls
                toggles["listingPullStatus"] = "pulling"
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            script = "/Users/admin/skyleigh-tools/scripts/pull-listing-by-mls.js"
            if os.path.exists(script):
                log = open("/Users/admin/.elevate/cache/pull-listing.log", "a")
                subprocess.Popen(
                    ["/usr/local/bin/node", script, deal_id, mls],
                    stdout=log, stderr=subprocess.STDOUT,
                    env={"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin", "HOME": "/Users/admin"},
                )
            return {"started": True, "mls": mls}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/pull-listing failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Pull listing failed: {exc}")

    @router.get("/api/admin/clause-library")
    def get_admin_clause_library():
        # Serve the scraped WEBForms clause library (Personal/Office/System) for
        # the Insert Clauses popup. Refreshes whenever pull-clauses-from-webforms.js
        # rewrites the file — no rebuild needed.
        try:
            import json as _json
            path = "/Users/admin/skyleigh-tools/knowledge/deals/forms/webforms-clauses.json"
            if not os.path.exists(path):
                return {"folders": {"system": [], "office": [], "personal": []}, "counts": {}}
            return _json.loads(open(path).read())
        except Exception as exc:
            _log.exception("GET /api/admin/clause-library failed")
            raise HTTPException(status_code=500, detail=f"Clause library failed: {exc}")

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

    # --- CPS Offer Prep (buyer side) -------------------------------------

    def _cps_deal_facts(deal_id: Optional[str]) -> Dict[str, Any]:
        """Build the CPS / accessory-form fill facts from a deal: party names
        (resolved the same way the score card displays them — extra first,
        contacts as fallback), money (card override -> deal columns), mailing
        addresses, dates, and the cooperating commission for the remuneration
        form. Returns {} on any failure (forms then fill blank lines)."""
        if not deal_id:
            return {}
        try:
            from elevate_cli.data import connect
            from elevate_cli.data.deals import get_deal_context

            with connect() as conn:
                ctx = get_deal_context(conn, deal_id)
            d = ctx.get("deal") or {}
            chk = ctx.get("checklist") or {}
            primary = ctx.get("primaryContact") or {}
            cos = ctx.get("coContacts") or []
            buyers: List[str] = []
            sellers: List[str] = []
            if primary.get("displayName"):
                buyers.append(primary["displayName"])
            for c in cos:
                role = str(c.get("role") or "").lower()
                nm = ((c.get("contact") or {}).get("displayName")) or ""
                if not nm:
                    continue
                (sellers if "seller" in role else buyers).append(nm)
            buyers = list(dict.fromkeys(buyers))
            sellers = list(dict.fromkeys(sellers))

            def _card_names(keys, fallback):
                for k in keys:
                    v = chk.get(k)
                    if isinstance(v, list):
                        vals = [str(x).strip() for x in v if str(x).strip()]
                        if vals:
                            return vals
                    elif isinstance(v, str) and v.strip():
                        return [p.strip() for p in v.split(",") if p.strip()]
                return fallback
            buyers = _card_names(["buyerClientNames", "skyslopeBuyerNames", "buyerNames"], buyers)
            sellers = _card_names(["sellerLegalNames", "skyslopeSellerNames", "sellerNames"], sellers)

            card_price = str(chk.get("cpsPurchasePrice") or "").strip()
            card_deposit = str(chk.get("cpsDeposit") or "").strip()
            card_deposit_terms = str(chk.get("cpsDepositTerms") or "").strip()
            commission = ""
            bse = chk.get("buyerSideEarn")
            if isinstance(bse, dict):
                commission = str(bse.get("cooperatingCommission") or "").strip()
            commission = commission or str(chk.get("cooperatingCommission") or "").strip()
            return {
                "listingAddress": d.get("listingAddress"),
                "buyers": buyers, "sellers": sellers,
                "buyerAddress": chk.get("mailingAddress"),
                "sellerAddress": chk.get("sellerMailingAddress") or chk.get("seller_mailing_address"),
                "price": card_price or d.get("offerPrice") or d.get("listPrice"),
                "depositAmount": card_deposit or d.get("depositAmount"),
                "depositTerms": card_deposit_terms or None,
                "mlsNumber": d.get("mlsNumber"),
                "targetMls": chk.get("targetMls"),  # MLS used at gather; locates the title for legal/PID extraction
                "legalDescription": chk.get("cpsLegalDescription") or d.get("legalDescription"),
                "pid": chk.get("cpsPid") or d.get("pid"),
                "completionDate": chk.get("completionDate") or d.get("completionDate"),
                "possessionDate": chk.get("possessionDate") or d.get("possessionDate"),
                "adjustmentDate": chk.get("adjustmentDate") or chk.get("completionDate") or d.get("completionDate"),
                "possessionTime": chk.get("possessionTime"),
                "offerDate": d.get("offerDate"),
                "commission": commission,
            }
        except Exception:
            _log.warning("CPS deal facts load failed for %s", deal_id, exc_info=True)
            return {}
    # Gather the listing's MLS sheet + Docs-tab documents from Xposure into the
    # buyer deal's Drive folder, then assemble a CPS draft on the actual BCREA
    # form + Schedule A. Both call scripts in ~/skyleigh-tools (separate repo),
    # spawned with /usr/bin/python3 because the PDF deps (reportlab/pypdf/fitz)
    # are --user installs the dashboard's default python can't see.

    @router.post("/api/admin/offer-prep/gather")
    def post_offer_prep_gather(body: _GatherCpsBody):
        """Kick off the Xposure gather (login -> MLS search -> docs + MLS sheet
        -> file into the deal folder). Detached + slow (~1-2 min), so this
        returns immediately after starting it."""
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            mls = (body.mls or "").strip()
            if not mls.isdigit() or not (6 <= len(mls) <= 9):
                raise HTTPException(status_code=400, detail="Enter a valid MLS number")
            script = os.path.expanduser("~/skyleigh-tools/scripts/cps-prep-package.sh")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="CPS gather script not found")
            args = ["/bin/bash", script, mls]
            if body.dry_run:
                args.append("--dry-run")
            # DEAL_ID lets the gather write the extracted legal/PID back onto the
            # deal once the title finishes downloading, so Generate has them no
            # matter the timing.
            gather_env = {**os.environ, "DEAL_ID": (body.deal_id or "")}
            _sp.Popen(
                args,
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
                start_new_session=True,
                env=gather_env,
            )
            _log.info("offer-prep CPS gather started for MLS %s (dry_run=%s)", mls, body.dry_run)
            return {"ok": True, "started": True, "mls": mls, "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep CPS gather failed")
            raise HTTPException(status_code=500, detail=f"CPS gather failed: {exc}")

    @router.post("/api/admin/offer-prep/generate")
    def post_offer_prep_generate(body: _GenerateCpsBody):
        """Fill the real BCREA Contract of Purchase and Sale from the deal's
        facts (parties, price, legal, dates) and append Schedule A (selected
        subjects + clauses), then file the draft into the deal folder.
        Synchronous (no browser), returns the result + Drive URL."""
        import json as _json
        import re as _re
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            if not body.umbrella:
                raise HTTPException(status_code=400, detail="Pick a form first")
            # Pull the deal's real facts so the base CPS form fills itself.
            deal_facts = _cps_deal_facts(body.deal_id)
            payload = {
                "umbrella": body.umbrella, "clauses": body.clauses,
                "customClauses": body.customClauses, "vars": body.vars,
                "address": (body.address or "Property"), "dealId": (body.deal_id or "deal"),
                "dryRun": body.dry_run, "deal": deal_facts,
            }
            pf = f"/tmp/cps-gen-payload-{body.deal_id or 'x'}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            script = os.path.expanduser("~/skyleigh-tools/scripts/cps-generate.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="CPS generate script not found")
            # /usr/bin/python3 has reportlab/pypdf/fitz as --user installs; the
            # dashboard hides them with PYTHONNOUSERSITE + a bundle PYTHONPATH/
            # PYTHONHOME. Strip those and point at the user site-packages.
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                                      "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
            child_env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=120, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("CPS generate produced no PDF: %s | %s", (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Generation failed to produce a PDF")
            _log.info("CPS draft generated for %s (dry_run=%s, saved=%s)", result.get("address"), body.dry_run, "save" in result)
            return {"ok": True, "address": result.get("address"), "saved": ("save" in result),
                    "url": result.get("url"), "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep CPS generate failed")
            raise HTTPException(status_code=500, detail=f"CPS generate failed: {exc}")

    @router.post("/api/admin/offer-prep/form")
    def post_offer_prep_form(body: _GenerateFormBody):
        """Fill one buyer-side accessory form (PNC / DORTS representation /
        Disclosure of Remuneration) from the deal facts and file it into the
        deal folder. Synchronous; returns the result + Drive URL."""
        import json as _json
        import re as _re
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            form = (body.form or "").strip().lower()
            if form not in ("pnc", "dorts", "disclosure-rem"):
                raise HTTPException(status_code=400, detail="Unknown form")
            deal_facts = _cps_deal_facts(body.deal_id)
            payload = {
                "form": form, "address": (body.address or "Property"),
                "dealId": (body.deal_id or "deal"), "dryRun": body.dry_run,
                "deal": deal_facts,
            }
            pf = f"/tmp/offer-form-payload-{body.deal_id or 'x'}-{form}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="Offer-prep forms script not found")
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                                      "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
            child_env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=120, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("offer form %s produced no PDF: %s | %s", form, (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Form generation failed")
            _log.info("offer-prep form %s generated for %s (dry_run=%s)", form, result.get("address"), body.dry_run)
            return {"ok": True, "form": form, "address": result.get("address"),
                    "saved": ("save" in result), "url": result.get("url"), "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep form generate failed")
            raise HTTPException(status_code=500, detail=f"Form generate failed: {exc}")

    @router.post("/api/admin/offer-prep/package")
    def post_offer_prep_package(body: _GenerateCpsBody):
        """Build the full offer package — CPS draft + DORTS + PNC + Disclosure of
        Remuneration merged into one PDF — and file it to the deal folder for
        preview. Returns the Drive URL."""
        import json as _json
        import re as _re
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            if not body.umbrella:
                raise HTTPException(status_code=400, detail="Pick a form first")
            deal_facts = _cps_deal_facts(body.deal_id)
            payload = {
                "umbrella": body.umbrella, "clauses": body.clauses,
                "customClauses": body.customClauses, "vars": body.vars,
                "address": (body.address or "Property"), "dealId": (body.deal_id or "deal"),
                "dryRun": body.dry_run, "deal": deal_facts, "forms": body.forms,
            }
            pf = f"/tmp/offer-package-payload-{body.deal_id or 'x'}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-package.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="Offer-prep package script not found")
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                                      "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
            child_env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=180, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("offer package produced no PDF: %s | %s", (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Package build failed")
            _log.info("offer package built for %s (%s docs, dry_run=%s)", result.get("address"), result.get("count"), body.dry_run)
            return {"ok": True, "address": result.get("address"), "count": result.get("count"),
                    "url": result.get("url"), "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep package build failed")
            raise HTTPException(status_code=500, detail=f"Package build failed: {exc}")

    def _user_site_env():
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
        env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
        return env

    @router.get("/api/admin/deals/{deal_id}/documents")
    def get_deal_documents(deal_id: str):
        """List the deal's Drive-folder files (classified/grouped) for the card's
        Documents panel. Read-only — runs deal-docs-list.py against the deal's
        property address."""
        import json as _json
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            facts = _cps_deal_facts(deal_id)
            # Deal folders are named by the street address only (no city/postal),
            # so match on the portion before the first comma.
            address = str(facts.get("listingAddress") or "").split(",")[0].strip()
            empty = {"ok": True, "folderId": None, "folderUrl": None, "files": []}
            if not address:
                return empty
            script = os.path.expanduser("~/skyleigh-tools/scripts/deal-docs-list.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="docs-list script not found")
            r = _sp.run(["/usr/bin/python3", script, "--address", address],
                        capture_output=True, text=True, timeout=60, env=_user_site_env())
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    return _json.loads(line)
                except Exception:
                    continue
            _log.warning("deal documents: no JSON from docs-list: %s | %s", (r.stdout or "")[-200:], (r.stderr or "")[-200:])
            return empty
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("list deal documents failed")
            raise HTTPException(status_code=500, detail=f"List documents failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/onboarding-doc")
    def post_onboarding_doc(deal_id: str, body: _OnboardingDocBody):
        """Generate one Client-Onboarding document (agency / dorts / pnc) filled
        from the deal + client, filed to the deal folder. Returns the Drive URL."""
        import json as _json
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            form = (body.form or "").strip().lower()
            if form not in ("agency", "dorts", "pnc"):
                raise HTTPException(status_code=400, detail="Unknown onboarding form")
            facts = _cps_deal_facts(deal_id)
            address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"
            payload: Dict[str, Any] = {"address": address, "dealId": deal_id, "dryRun": False, "deal": facts}
            if form == "agency":
                script = os.path.expanduser("~/skyleigh-tools/scripts/buyer-agency-fill.py")
            else:
                payload["form"] = form
                script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="onboarding form script not found")
            pf = f"/tmp/onboarding-{deal_id}-{form}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=120, env=_user_site_env())
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("onboarding %s produced no PDF: %s | %s", form, (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Onboarding doc generation failed")
            return {"ok": True, "form": form, "url": result.get("url")}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("onboarding doc generate failed")
            raise HTTPException(status_code=500, detail=f"Onboarding doc failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/onboarding-sign")
    def post_onboarding_sign(deal_id: str):
        """Draft-first onboarding signatures. Deterministically fills Agency +
        DORTS + PNC, merges one preview PDF, and parks a review card carrying that
        preview (previewPdf) so the user reviews the actual drafts BEFORE approving.
        After approval, the signing-package skill uploads the already-filled PDFs
        and sends via the configured provider — the agent never has to fill or
        decide, which keeps that run small. Falls back to direct agent dispatch if
        the deterministic prep fails (never worse than the prior behavior)."""
        try:
            require_admin_setup_ready_for_launch()
            import json as _json
            import subprocess as _sp
            from elevate_cli.data import connect
            from elevate_cli.data.dispatch import queue_action_run

            facts = _cps_deal_facts(deal_id)
            address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"

            # --- Deterministic draft prep: fill the 3 docs + merge one preview ---
            prefilled: List[Dict[str, str]] = []
            preview_pdf = None
            try:
                forms_seq = [
                    ("agency", os.path.expanduser("~/skyleigh-tools/scripts/buyer-agency-fill.py"), None),
                    ("dorts", os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py"), "dorts"),
                    ("pnc", os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py"), "pnc"),
                ]
                for key, script, formarg in forms_seq:
                    if not os.path.exists(script):
                        continue
                    pl: Dict[str, Any] = {"address": address, "dealId": deal_id, "dryRun": True, "deal": facts}
                    if formarg:
                        pl["form"] = formarg
                    pf = f"/tmp/onboarding-sign-{deal_id}-{key}.json"
                    with open(pf, "w") as f:
                        _json.dump(pl, f)
                    r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                                text=True, timeout=120, env=_user_site_env())
                    res: Dict[str, Any] = {}
                    for line in reversed((r.stdout or "").strip().splitlines()):
                        try:
                            res = _json.loads(line); break
                        except Exception:
                            continue
                    if res.get("ok") and res.get("pdf") and os.path.exists(res["pdf"]):
                        prefilled.append({"form": key, "pdf": res["pdf"]})
                if len(prefilled) == 3:
                    pv_dir = os.path.expanduser("~/.elevate/uploads/onboarding-previews")
                    os.makedirs(pv_dir, exist_ok=True)
                    preview_path = f"{pv_dir}/{deal_id}-onboarding-preview.pdf"
                    merge_src = (
                        "import sys\n"
                        "from pypdf import PdfReader, PdfWriter\n"
                        "w = PdfWriter()\n"
                        "for f in sys.argv[2:]:\n"
                        "    for p in PdfReader(f).pages:\n"
                        "        w.add_page(p)\n"
                        "with open(sys.argv[1], 'wb') as fh:\n"
                        "    w.write(fh)\n"
                    )
                    mr = _sp.run(["/usr/bin/python3", "-c", merge_src, preview_path] + [d["pdf"] for d in prefilled],
                                 capture_output=True, text=True, timeout=60,
                                 env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"})
                    if mr.returncode == 0 and os.path.exists(preview_path):
                        preview_pdf = preview_path
            except Exception:
                _log.exception("onboarding draft prep failed; falling back to agent dispatch")
                prefilled = []
                preview_pdf = None

            buyers = [b for b in (facts.get("buyers") or []) if b]
            who = ", ".join(buyers) or "the buyer(s)"
            payload = {
                "purpose": "buyer-onboarding-signatures",
                "documents": [
                    "Buyer's Agency Agreement",
                    "Disclosure of Representation in Trading Services (DORTS)",
                    "Privacy Notice & Consent (PNC)",
                ],
                "prefilledDocs": prefilled,
                "previewPdf": preview_pdf or "",
                "note": (
                    "The 3 onboarding documents are ALREADY filled (local paths in prefilledDocs). "
                    "After the user approves, upload exactly those PDFs to the configured signing "
                    "provider and send them for signature to the buyer(s). Do not re-fill or regenerate them."
                ),
            }

            with connect() as conn:
                if preview_pdf:
                    run = queue_action_run(
                        conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                        name="Send onboarding package for signatures", payload=payload,
                        create_cron_job=False, actor="dashboard:onboarding")
                    rid = run.get("id") if isinstance(run, dict) else None
                    prompt = {
                        "title": "Review & approve: onboarding signatures",
                        "message": (
                            f"Buyer's Agency, DORTS, and PNC are drafted and filled for {who}. "
                            "Open the Preview to review, then approve to send them for signature by DigiSign."
                        ),
                        "requiredFields": [
                            f"Approve sending the filled Agency, DORTS & PNC to {who} for signature by DigiSign? yes/no"
                        ],
                        "previewPdf": preview_pdf,
                    }
                    conn.execute(
                        "UPDATE admin_action_runs SET status='waiting_human', human_prompt_json=? WHERE id=?",
                        (_json.dumps(prompt), rid),
                    )
                    return {"ok": True, "runId": rid, "previewPdf": preview_pdf, "draftFirst": True}
                # Fallback: prior behavior — let the agent fill, park, and send.
                run = queue_action_run(
                    conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                    name="Send onboarding package for signatures", payload=payload,
                    create_cron_job=True, actor="dashboard:onboarding")
                return {"ok": True, "runId": run.get("id") if isinstance(run, dict) else None, "draftFirst": False}
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("onboarding sign dispatch failed")
            raise HTTPException(status_code=500, detail=f"Send for signatures failed: {exc}")

    # --- CMA wizard (listing side): checkpointed phase runner + comp review ---
    _CMA_RUNNER = os.path.expanduser("~/skyleigh-tools/scripts/cma-phase-runner.py")

    def _cma_addr(deal_id):
        facts = _cps_deal_facts(deal_id)
        return str(facts.get("listingAddress") or "").split(",")[0].strip()

    def _cma_call(addr, args, timeout=60):
        import json as _json
        import subprocess as _sp
        r = _sp.run(["/usr/bin/python3", _CMA_RUNNER, "--address", addr] + args,
                    capture_output=True, text=True, timeout=timeout, env=_user_site_env())
        for line in reversed((r.stdout or "").strip().splitlines()):
            try:
                return _json.loads(line)
            except Exception:
                continue
        _log.warning("cma-runner no JSON (%s): %s | %s", args, (r.stdout or "")[-200:], (r.stderr or "")[-200:])
        return {}

    @router.get("/api/admin/deals/{deal_id}/cma/phases")
    def get_cma_phases(deal_id: str):
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                return {"ok": True, "done": 0, "total": 0, "phases": [], "pdfUrl": None}
            return _cma_call(addr, ["--status"], timeout=30)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma phases failed")
            raise HTTPException(status_code=500, detail=f"CMA phases failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/run")
    def post_cma_run(deal_id: str, body: _CmaRunBody):
        """Kick a single CMA phase. Detached — browser phases run for minutes;
        the wizard polls /cma/phases for status."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            import subprocess as _sp
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--phase", body.phase],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      start_new_session=True)
            return {"ok": True, "started": True, "phase": body.phase}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma run failed")
            raise HTTPException(status_code=500, detail=f"CMA run failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/skip-photos")
    def post_cma_skip_photos(deal_id: str):
        """Skip the photo/finish step when there are no usable photos: writes
        neutral analysis so normalize/render still run (price-based, no finish
        adjustment) and marks photos done so the wizard advances. Synchronous."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            return _cma_call(addr, ["--skip-photos"], timeout=60)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma skip-photos failed")
            raise HTTPException(status_code=500, detail=f"CMA skip-photos failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/regenerate-comps")
    def post_cma_regenerate(deal_id: str, body: _CmaRegenBody):
        """Re-pull comps with adjustments parsed from free text (e.g. 'expand to
        Westsyde + Westmount, target $635k'): sets CMA_AREAS / CMA_VALUE_ANCHOR,
        resets the comp-derived phases, and re-runs collect (detached)."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            import re as _re, subprocess as _sp
            text = body.instructions or ""
            env = _user_site_env()
            anchor = ""
            m = _re.search(r"([0-9]{3})[, ]?([0-9]{3})\b", text)
            if m:
                anchor = m.group(1) + m.group(2)
            else:
                mk = _re.search(r"([0-9]{3})\s*k\b", text, _re.I)
                if mk:
                    anchor = mk.group(1) + "000"
            if anchor:
                env["CMA_VALUE_ANCHOR"] = anchor
            AREAS = ["Brocklehurst", "Westsyde", "Westmount", "Batchelor", "North Kamloops",
                     "South Kamloops", "Sahali", "Aberdeen", "Dallas", "Valleyview", "Juniper",
                     "Barnhartvale", "Rayleigh", "Pineview", "Sun Rivers", "Dufferin"]
            picked = [a for a in AREAS if a.lower() in text.lower()]
            if picked:
                env["CMA_AREAS"] = ",".join(picked)
            env["CMA_MAX_COMPS"] = "10"
            _sp.run(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--reset-downstream"],
                    env=env, capture_output=True, timeout=30)
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--phase", "collect"],
                      env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
            return {"ok": True, "started": True, "areas": env.get("CMA_AREAS"),
                    "anchor": env.get("CMA_VALUE_ANCHOR"), "instructions": text}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma regenerate failed")
            raise HTTPException(status_code=500, detail=f"CMA regenerate failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/cma/comp-photo/{comp_num}")
    def get_cma_comp_photo(deal_id: str, comp_num: int):
        """Serve a comp's first captured photo (comp-N-photo-00.jpg) for the
        Comparables-step thumbnail. 404 if that comp has no photo (placeholder)."""
        import glob as _glob
        base = os.path.join(os.path.dirname(_CMA_RUNNER), "screenshots", "comp-photos")
        cand = os.path.join(base, f"comp-{comp_num}-photo-00.jpg")
        if not os.path.exists(cand):
            hits = sorted(_glob.glob(os.path.join(base, f"comp-{comp_num}-photo-*.jpg")))
            cand = hits[0] if hits else ""
        if not cand or not os.path.exists(cand):
            raise HTTPException(status_code=404, detail="no photo for this comp")
        return FileResponse(cand, media_type="image/jpeg")

    @router.get("/api/admin/deals/{deal_id}/cma/pricing")
    def get_cma_pricing(deal_id: str):
        """Pricing breakdown for the wizard's Pricing step: recommended price,
        range, the better/comparable/worse sandwich, and the strategy reasoning."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            return _cma_call(addr, ["--pricing"], timeout=30)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma pricing failed")
            raise HTTPException(status_code=500, detail=f"CMA pricing failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/reprice")
    def post_cma_reprice(deal_id: str, body: _CmaRepriceBody):
        """The 'Your take' override: force the recommended price to exactly
        body.price, fold body.rationale into the narrative, and re-derive the
        sandwich + comp descriptions + PDF. Detached; the wizard polls pricing."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            import subprocess as _sp
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--reprice",
                       "--price", body.price or "", "--rationale", body.rationale or ""],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
            return {"ok": True, "started": True, "price": body.price}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma reprice failed")
            raise HTTPException(status_code=500, detail=f"CMA reprice failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/capture-prospecting")
    def post_cma_capture_prospecting(deal_id: str, body: _CmaCaptureProspectingBody):
        """The Pricing step's 'Capture buyer demand': one last Xposure pull for the
        active listing the operator chose as the prospecting anchor (persistent
        profile, no MFA). Detached; reshapes to prospecting-brackets.json and marks
        the prospecting phase done. The wizard polls /cma/phases for completion."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            if not (body.mls or "").strip():
                raise HTTPException(status_code=400, detail="Pick an active listing first")
            import os as _os, subprocess as _sp
            script = _os.path.join(_os.path.dirname(_CMA_RUNNER), "capture-prospecting.sh")
            _sp.Popen(["/bin/bash", script, body.mls, addr],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
            return {"ok": True, "started": True, "mls": body.mls}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma capture-prospecting failed")
            raise HTTPException(status_code=500, detail=f"CMA capture-prospecting failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/cma/comps")
    def get_cma_comps(deal_id: str):
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                return {"ok": True, "sold": [], "active": []}
            return _cma_call(addr, ["--comps"], timeout=30)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma comps failed")
            raise HTTPException(status_code=500, detail=f"CMA comps failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/comp-toggle")
    def post_cma_comp_toggle(deal_id: str, body: _CmaCompToggleBody):
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            return _cma_call(addr, ["--toggle-comp", body.mls, "--kind", body.kind], timeout=20)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma comp-toggle failed")
            raise HTTPException(status_code=500, detail=f"CMA comp-toggle failed: {exc}")

    return router
