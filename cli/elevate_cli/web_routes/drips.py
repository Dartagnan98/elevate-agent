"""Drip campaign routes (``/api/drips/*``).

Thin HTTP layer over :mod:`elevate_cli.drips_db`. Every handler opens a
pooled connection through ``drips_db.connect()`` so the Elevation seed is
applied on first use, maps ``ValueError`` to 400 and logs everything else
as a 500.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class SegmentCreate(BaseModel):
    label: str
    key: Optional[str] = None
    description: Optional[str] = None
    windowLabel: Optional[str] = None
    color: Optional[str] = None


class SegmentUpdate(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    windowLabel: Optional[str] = None
    color: Optional[str] = None
    enabled: Optional[bool] = None


class SegmentReorder(BaseModel):
    keys: list[str]


class StepBody(BaseModel):
    day: int
    channel: str
    title: str
    subject: Optional[str] = None
    body: Optional[str] = None
    video: Optional[str] = None
    notes: Optional[str] = None
    routeTo: Optional[str] = None


class StepUpdate(BaseModel):
    day: Optional[int] = None
    channel: Optional[str] = None
    title: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    video: Optional[str] = None
    notes: Optional[str] = None
    routeTo: Optional[str] = None
    sortOrder: Optional[int] = None


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    kind: str = "custom"
    role: str = "primary"
    triggerSegment: Optional[str] = None
    layerFlag: Optional[str] = None
    deferLayers: bool = False
    runOnce: bool = False
    enabled: bool = True
    exitDay: Optional[int] = None
    exitRule: Optional[str] = None
    notes: Optional[str] = None
    sourceUrl: Optional[str] = None
    steps: list[StepBody] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None
    role: Optional[str] = None
    triggerSegment: Optional[str] = None
    layerFlag: Optional[str] = None
    deferLayers: Optional[bool] = None
    runOnce: Optional[bool] = None
    enabled: Optional[bool] = None
    exitDay: Optional[int] = None
    exitRule: Optional[str] = None
    notes: Optional[str] = None
    sourceUrl: Optional[str] = None


class EnabledBody(BaseModel):
    enabled: bool


class DuplicateBody(BaseModel):
    name: Optional[str] = None


class InstallBody(BaseModel):
    asCopy: bool = False


class ContactSegmentBody(BaseModel):
    segment: Optional[str] = None
    note: Optional[str] = None
    buying: Optional[bool] = None
    selling: Optional[bool] = None
    startDate: Optional[str] = None


class EnrollBody(BaseModel):
    campaignId: str
    contactId: str
    startDate: Optional[str] = None


class StopBody(BaseModel):
    reason: Optional[str] = None


class TouchBody(BaseModel):
    note: Optional[str] = None


class RunBody(BaseModel):
    date: Optional[str] = None


class VideoCreate(BaseModel):
    name: str
    script: Optional[str] = None
    lengthLabel: Optional[str] = None
    usedIn: Optional[str] = None


class VideoUpdate(BaseModel):
    name: Optional[str] = None
    script: Optional[str] = None
    lengthLabel: Optional[str] = None
    usedIn: Optional[str] = None
    link: Optional[str] = None
    recordedAt: Optional[str] = None


class SettingsUpdate(BaseModel):
    autoEnrollNewLeads: Optional[bool] = None
    autoTagMoves: Optional[bool] = None
    sendWindowStart: Optional[str] = None
    sendWindowEnd: Optional[str] = None
    callsAsTasks: Optional[bool] = None
    pauseAiDraftsInCampaigns: Optional[bool] = None
    newsletterTool: Optional[str] = None


def _clean(model: BaseModel) -> dict[str, Any]:
    """Only the fields the caller actually sent (so PUT bodies stay partial)."""
    return {k: v for k, v in model.model_dump().items() if k in model.model_fields_set}


def create_drips_router(*, web_actor: str = "human:web", log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    def _guard(label: str):
        """Decorator-free error mapping shared by every handler."""

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                if exc is None:
                    return False
                if isinstance(exc, HTTPException):
                    return False
                if isinstance(exc, ValueError):
                    raise HTTPException(status_code=400, detail=str(exc))
                _log.exception("%s failed", label)
                raise HTTPException(status_code=500, detail=f"{label} failed: {exc}")

        return _Ctx()

    # ── Overview ───────────────────────────────────────────────────────

    @router.get("/api/drips/overview")
    def get_overview(date: Optional[str] = None):
        with _guard("GET /api/drips/overview"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return drips_db.overview(conn, today=date)

    # ── Segments ───────────────────────────────────────────────────────

    @router.get("/api/drips/segments")
    def get_segments():
        with _guard("GET /api/drips/segments"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"segments": drips_db.list_segments(conn)}

    @router.post("/api/drips/segments")
    def post_segment(body: SegmentCreate):
        with _guard("POST /api/drips/segments"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"segment": drips_db.create_segment(
                    conn, label=body.label, key=body.key, description=body.description,
                    window_label=body.windowLabel, color=body.color,
                )}

    @router.post("/api/drips/segments/reorder")
    def post_segments_reorder(body: SegmentReorder):
        with _guard("POST /api/drips/segments/reorder"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"segments": drips_db.reorder_segments(conn, body.keys)}

    @router.put("/api/drips/segments/{key}")
    def put_segment(key: str, body: SegmentUpdate):
        with _guard("PUT /api/drips/segments"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"segment": drips_db.update_segment(conn, key, **_clean(body))}

    @router.delete("/api/drips/segments/{key}")
    def delete_segment(key: str):
        with _guard("DELETE /api/drips/segments"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                ok = drips_db.delete_segment(conn, key)
            if not ok:
                raise HTTPException(status_code=404, detail=f"segment {key!r} not found")
            return {"ok": True}

    # ── Campaigns ──────────────────────────────────────────────────────

    @router.get("/api/drips/campaigns")
    def get_campaigns():
        with _guard("GET /api/drips/campaigns"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"campaigns": drips_db.list_campaigns(conn)}

    @router.post("/api/drips/campaigns")
    def post_campaign(body: CampaignCreate):
        with _guard("POST /api/drips/campaigns"):
            from elevate_cli import drips_db

            steps = [
                {
                    "day": s.day, "channel": s.channel, "title": s.title, "subject": s.subject, "body": s.body,
                    "video": s.video, "notes": s.notes, "route_to": s.routeTo,
                }
                for s in body.steps
            ]
            with drips_db.connect() as conn:
                return {"campaign": drips_db.create_campaign(
                    conn, name=body.name, description=body.description, kind=body.kind, role=body.role,
                    trigger_segment=body.triggerSegment, layer_flag=body.layerFlag, defer_layers=body.deferLayers,
                    run_once=body.runOnce, enabled=body.enabled, exit_day=body.exitDay, exit_rule=body.exitRule,
                    notes=body.notes, source_url=body.sourceUrl, steps=steps,
                )}

    @router.get("/api/drips/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str):
        with _guard("GET /api/drips/campaigns/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                campaign = drips_db.get_campaign(conn, campaign_id)
            if campaign is None:
                raise HTTPException(status_code=404, detail=f"campaign {campaign_id!r} not found")
            return {"campaign": campaign}

    @router.put("/api/drips/campaigns/{campaign_id}")
    def put_campaign(campaign_id: str, body: CampaignUpdate):
        with _guard("PUT /api/drips/campaigns/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"campaign": drips_db.update_campaign(conn, campaign_id, **_clean(body))}

    @router.post("/api/drips/campaigns/{campaign_id}/enabled")
    def post_campaign_enabled(campaign_id: str, body: EnabledBody):
        with _guard("POST /api/drips/campaigns/{id}/enabled"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"campaign": drips_db.set_campaign_enabled(conn, campaign_id, body.enabled)}

    @router.post("/api/drips/campaigns/{campaign_id}/duplicate")
    def post_campaign_duplicate(campaign_id: str, body: DuplicateBody | None = None):
        with _guard("POST /api/drips/campaigns/{id}/duplicate"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"campaign": drips_db.duplicate_campaign(conn, campaign_id, name=body.name if body else None)}

    @router.post("/api/drips/campaigns/{campaign_id}/reset")
    def post_campaign_reset(campaign_id: str):
        with _guard("POST /api/drips/campaigns/{id}/reset"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"campaign": drips_db.reset_campaign_to_template(conn, campaign_id)}

    @router.delete("/api/drips/campaigns/{campaign_id}")
    def delete_campaign(campaign_id: str, force: bool = False):
        with _guard("DELETE /api/drips/campaigns/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                ok = drips_db.delete_campaign(conn, campaign_id, force=force)
            if not ok:
                raise HTTPException(status_code=404, detail=f"campaign {campaign_id!r} not found")
            return {"ok": True}

    @router.post("/api/drips/campaigns/{campaign_id}/steps")
    def post_step(campaign_id: str, body: StepBody):
        with _guard("POST /api/drips/campaigns/{id}/steps"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"step": drips_db.add_step(
                    conn, campaign_id, day=body.day, channel=body.channel, title=body.title, subject=body.subject,
                    body=body.body, video=body.video, notes=body.notes, route_to=body.routeTo,
                )}

    @router.put("/api/drips/steps/{step_id}")
    def put_step(step_id: str, body: StepUpdate):
        with _guard("PUT /api/drips/steps/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"step": drips_db.update_step(conn, step_id, **_clean(body))}

    @router.delete("/api/drips/steps/{step_id}")
    def delete_step(step_id: str):
        with _guard("DELETE /api/drips/steps/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                ok = drips_db.delete_step(conn, step_id)
            if not ok:
                raise HTTPException(status_code=404, detail=f"step {step_id!r} not found")
            return {"ok": True}

    # ── Template library ───────────────────────────────────────────────

    @router.get("/api/drips/templates")
    def get_templates():
        with _guard("GET /api/drips/templates"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"templates": drips_db.list_templates(conn)}

    @router.post("/api/drips/templates/{slug}/install")
    def post_template_install(slug: str, body: InstallBody | None = None):
        with _guard("POST /api/drips/templates/{slug}/install"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"campaign": drips_db.install_template(conn, slug, as_copy=bool(body and body.asCopy))}

    # ── Contacts ───────────────────────────────────────────────────────

    @router.get("/api/drips/contacts")
    def get_contacts(q: Optional[str] = None, segment: Optional[str] = None, limit: int = 25):
        with _guard("GET /api/drips/contacts"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"contacts": drips_db.search_contacts(conn, q, limit=limit, segment=segment)}

    @router.get("/api/drips/contacts/{contact_id}")
    def get_contact(contact_id: str):
        with _guard("GET /api/drips/contacts/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                state = drips_db.contact_drip_state(conn, contact_id)
            if state is None:
                raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
            return {"contact": state}

    @router.post("/api/drips/contacts/{contact_id}/segment")
    def post_contact_segment(contact_id: str, body: ContactSegmentBody):
        with _guard("POST /api/drips/contacts/{id}/segment"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"contact": drips_db.set_contact_segment(
                    conn, contact_id, body.segment, actor=web_actor, note=body.note,
                    buying=body.buying, selling=body.selling, start_date=body.startDate,
                )}

    # ── Enrollments ────────────────────────────────────────────────────

    @router.post("/api/drips/enroll")
    def post_enroll(body: EnrollBody):
        with _guard("POST /api/drips/enroll"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"enrollment": drips_db.enroll_contact(
                    conn, body.campaignId, body.contactId, actor=web_actor, start_date=body.startDate,
                )}

    @router.get("/api/drips/enrollments/{enrollment_id}")
    def get_enrollment(enrollment_id: str):
        with _guard("GET /api/drips/enrollments/{id}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                enrollment = drips_db.get_enrollment(conn, enrollment_id)
            if enrollment is None:
                raise HTTPException(status_code=404, detail=f"enrollment {enrollment_id!r} not found")
            return {"enrollment": enrollment}

    @router.post("/api/drips/enrollments/{enrollment_id}/pause")
    def post_enrollment_pause(enrollment_id: str):
        with _guard("POST /api/drips/enrollments/{id}/pause"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"enrollment": drips_db.pause_enrollment(conn, enrollment_id)}

    @router.post("/api/drips/enrollments/{enrollment_id}/resume")
    def post_enrollment_resume(enrollment_id: str):
        with _guard("POST /api/drips/enrollments/{id}/resume"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"enrollment": drips_db.resume_enrollment(conn, enrollment_id)}

    @router.post("/api/drips/enrollments/{enrollment_id}/stop")
    def post_enrollment_stop(enrollment_id: str, body: StopBody | None = None):
        with _guard("POST /api/drips/enrollments/{id}/stop"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"enrollment": drips_db.stop_enrollment(conn, enrollment_id, reason=body.reason if body else None)}

    # ── Board + engine ─────────────────────────────────────────────────

    @router.get("/api/drips/board")
    def get_board(date: Optional[str] = None, horizon: int = 7):
        with _guard("GET /api/drips/board"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return drips_db.due_board(conn, today=date, horizon_days=horizon)

    @router.post("/api/drips/touches/{touch_id}/done")
    def post_touch_done(touch_id: str, body: TouchBody | None = None):
        with _guard("POST /api/drips/touches/{id}/done"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"touch": drips_db.complete_touch(conn, touch_id, status="done", note=body.note if body else None)}

    @router.post("/api/drips/touches/{touch_id}/skip")
    def post_touch_skip(touch_id: str, body: TouchBody | None = None):
        with _guard("POST /api/drips/touches/{id}/skip"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"touch": drips_db.complete_touch(conn, touch_id, status="skipped", note=body.note if body else None)}

    @router.post("/api/drips/run")
    def post_run(body: RunBody | None = None):
        with _guard("POST /api/drips/run"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"run": drips_db.run_engine(conn, today=body.date if body else None)}

    # ── Videos ─────────────────────────────────────────────────────────

    @router.get("/api/drips/videos")
    def get_videos():
        with _guard("GET /api/drips/videos"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"videos": drips_db.list_videos(conn)}

    @router.post("/api/drips/videos")
    def post_video(body: VideoCreate):
        with _guard("POST /api/drips/videos"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"video": drips_db.create_video(
                    conn, name=body.name, script=body.script, length_label=body.lengthLabel, used_in=body.usedIn,
                )}

    @router.put("/api/drips/videos/{slug}")
    def put_video(slug: str, body: VideoUpdate):
        with _guard("PUT /api/drips/videos/{slug}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"video": drips_db.update_video(conn, slug, **_clean(body))}

    @router.delete("/api/drips/videos/{slug}")
    def delete_video(slug: str):
        with _guard("DELETE /api/drips/videos/{slug}"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                ok = drips_db.delete_video(conn, slug)
            if not ok:
                raise HTTPException(status_code=404, detail=f"video {slug!r} not found")
            return {"ok": True}

    # ── Settings ───────────────────────────────────────────────────────

    @router.get("/api/drips/settings")
    def get_settings():
        with _guard("GET /api/drips/settings"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"settings": drips_db.get_settings(conn)}

    @router.put("/api/drips/settings")
    def put_settings(body: SettingsUpdate):
        with _guard("PUT /api/drips/settings"):
            from elevate_cli import drips_db

            with drips_db.connect() as conn:
                return {"settings": drips_db.update_settings(conn, _clean(body))}

    return router
