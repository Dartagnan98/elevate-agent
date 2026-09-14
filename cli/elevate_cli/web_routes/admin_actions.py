"""Admin action registry, run, and task routes."""

import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


RequireReady = Callable[[], None]


class _ReviewBody(BaseModel):
    dealId: str
    manifestPath: str
    sessionId: str
    runId: Optional[str] = None


class _RecordedReviewAuthorizationBody(BaseModel):
    manifestPath: str
    approvedActions: list[str]
    sourceText: str


class _ReviewClaimBody(BaseModel):
    action: str
    runDir: str


class _AdminTaskRunBody(BaseModel):
    dealId: str
    skill: str
    title: Optional[str] = None
    sourceTaskId: Optional[str] = None
    runNow: bool = True


class _ActionRunApproveBody(BaseModel):
    approved: bool = True
    runNow: bool = True
    expectedTitleOrderHash: Optional[str] = None


class _TitleOrderBody(BaseModel):
    pid: str
    titleNumber: str
    totalCad: str
    quotedAt: str
    runId: Optional[str] = None


class _ActionRunAnswerBody(BaseModel):
    # Fillable "Waiting on you" cards submit the operator's typed field answers
    # here (keyed by field label) plus runNow. Restored 2026-06-26 — the route
    # was wiped by the 1.2.59 update and was missing from the source clone, so
    # every fillable card 405'd on submit. Re-applied/protected by
    # ~/skyleigh-tools/scripts/elevate-reapply-after-update.sh.
    answers: Dict[str, str] = {}
    runNow: bool = True
    expectedTitleOrderHash: Optional[str] = None


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

    @router.post('/api/admin/deals/{deal_id}/title-order-review')
    def prepare_listing_title_review(deal_id: str, body: _TitleOrderBody):
        from elevate_cli.data import connect
        from elevate_cli.listing_title import prepare_title_order
        try:
            with connect() as conn:
                return prepare_title_order(conn, deal_id, body.model_dump(), body.runId)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.post('/api/admin/action-runs/{run_id}/claim-title-order')
    def claim_listing_title_order(run_id: str, body: _TitleOrderBody):
        from elevate_cli.data import connect
        from elevate_cli.listing_title import claim_title_order
        try:
            with connect() as conn:
                return claim_title_order(conn, run_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

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

    @router.post("/api/admin/reviews")
    def prepare_review(body: _ReviewBody):
        import json
        from elevate_cli.data import connect
        from elevate_cli.data.dispatch import queue_action_run, _run_lookup, _row_to_run
        from elevate_cli.review_packages import freeze_review, register_artifacts
        from elevate_cli.web_routes.session_details import _resolve_active_session_or_404
        from elevate_state import SessionDB
        try:
            review = freeze_review(body.manifestPath)
            manifest = json.loads(open(review["manifestPath"]).read())
            db = SessionDB()
            try:
                _sid, _active, identity = _resolve_active_session_or_404(db, body.sessionId)
                register_artifacts(db, identity, review["artifacts"])
            finally:
                db.close()
            prompt = {"title": manifest.get("title", "Review marketing launch"),
                      "message": manifest.get("message", "Review these assets and the exact launch plan before approving."),
                      "requiredFields": manifest.get("requiredFields", []),
                      "reviewPackage": review, "sessionId": body.sessionId}
            with connect() as conn:
                # Serialize prepare retries for a deal and reuse the same pending package.
                conn.execute("SELECT id FROM deals WHERE id=? FOR UPDATE", (body.dealId,)).fetchone()
                existing_id = body.runId
                if not existing_id:
                    candidates = conn.execute("SELECT id, human_prompt_json FROM admin_action_runs WHERE deal_id=? AND status IN ('waiting_human','running','queued')", (body.dealId,)).fetchall()
                    for candidate in candidates:
                        raw = candidate["human_prompt_json"]
                        prior = json.loads(raw) if isinstance(raw, str) and raw else raw or {}
                        if (prior.get("reviewPackage") or {}).get("manifestPath") == review["manifestPath"]:
                            existing_id = candidate["id"]
                            break
                if existing_id:
                    conn.execute("SELECT id FROM admin_action_runs WHERE id=? FOR UPDATE", (existing_id,)).fetchone()
                    row = _run_lookup(conn, existing_id)
                    if row["deal_id"] != body.dealId or row["status"] not in ("running", "queued", "waiting_human"):
                        raise ValueError("Review must belong to an active run on this deal")
                    previous = json.loads(row["human_prompt_json"] or "{}")
                    if previous.get("actionClaims"):
                        raise ValueError("A launch action already started. Reconcile provider results before preparing a new review.")
                    conn.execute("UPDATE admin_action_runs SET status='waiting_human', human_prompt_json=? WHERE id=?", (json.dumps(prompt), existing_id))
                    run_id = existing_id
                else:
                    run = queue_action_run(conn, deal_id=body.dealId, skill="marketing",
                        name=prompt["title"], payload={"reviewSessionId": body.sessionId}, human_prompt=prompt)
                    run_id = run["id"]
            return {"runId": run_id, "reviewPackage": review, "status": "waiting_human"}
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/api/admin/action-runs/{run_id}/review-authorization")
    def record_existing_review_authorization(run_id: str, body: _RecordedReviewAuthorizationBody):
        from elevate_cli.data import connect
        from elevate_cli.review_packages import apply_recorded_review_authorization
        try:
            with connect() as conn:
                return apply_recorded_review_authorization(conn, run_id, body.manifestPath,
                    body.approvedActions, body.sourceText)
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.post("/api/admin/action-runs/{run_id}/claim-review-action")
    def claim_review_action(run_id: str, body: _ReviewClaimBody):
        import json
        from pathlib import Path
        from elevate_cli.data import connect
        from elevate_cli.data.dispatch import _run_lookup, _decode_json, now_iso
        from elevate_cli.review_packages import validate_review
        try:
            with connect() as conn:
                conn.execute("SELECT id FROM admin_action_runs WHERE id=? FOR UPDATE", (run_id,)).fetchone()
                row = _run_lookup(conn, run_id)
                prompt = _decode_json(row["human_prompt_json"]) or {}
                review, decision = prompt.get("reviewPackage"), prompt.get("decision", {})
                if (row["status"] not in ("queued", "running") or not review or
                    decision.get("approved") is not True or decision.get("versionHash") != review["versionHash"] or
                    body.action not in decision.get("actions", [])):
                    raise ValueError("This action has no current publishing approval")
                if str(Path(body.runDir).resolve()) != review["runDir"]:
                    raise ValueError("Approval belongs to a different marketing package")
                validate_review(review, publishing=True)
                claims = prompt.setdefault("actionClaims", {})
                if body.action in claims:
                    raise ValueError("Action was already started. Reconcile provider results before retrying; do not create duplicates.")
                claims[body.action] = {"claimedAt": now_iso(), "versionHash": review["versionHash"]}
                conn.execute("UPDATE admin_action_runs SET human_prompt_json=? WHERE id=?", (json.dumps(prompt), run_id))
                return {"claimed": True, "action": body.action, "versionHash": review["versionHash"]}
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

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
                    expected_title_order_hash=body.expectedTitleOrderHash,
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/action-runs/%s/approve failed", run_id)
            raise HTTPException(status_code=500, detail=f"Approve action run failed: {exc}")

    @router.post("/api/admin/action-runs/{run_id}/answer")
    def post_admin_action_run_answer(run_id: str, body: _ActionRunAnswerBody):
        """Submit a fillable card's typed field answers, then resume the run.

        The frontend posts {answers: {<field label>: <value>}, runNow} for any
        "Waiting on you" card that has requiredFields. We record the answers onto
        the run's human_prompt_json.providedAnswers (where the re-dispatched skill
        reads them) and then take the normal approval/re-dispatch path. Without
        this route fillable cards 405 on submit and stay stuck forever.
        """
        try:
            require_admin_setup_ready_for_launch()
            import json as _json
            from elevate_cli.data import approve_action_run, connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT human_prompt_json FROM admin_action_runs WHERE id=?",
                    (run_id,),
                ).fetchone()
                if row is None:
                    raise LookupError(f"action run {run_id!r} not found")
                raw = row["human_prompt_json"]
                if isinstance(raw, dict):
                    prompt = dict(raw)
                elif isinstance(raw, str) and raw.strip():
                    try:
                        prompt = _json.loads(raw)
                    except Exception:
                        prompt = {}
                else:
                    prompt = {}
                if not isinstance(prompt, dict):
                    prompt = {}
                prompt["providedAnswers"] = dict(body.answers or {})
                conn.execute(
                    "UPDATE admin_action_runs SET human_prompt_json=? WHERE id=?",
                    (_json.dumps(prompt), run_id),
                )
                # Re-use the approval path: stamps the decision + re-dispatches a
                # fresh worker, which reads providedAnswers off the prompt.
                return approve_action_run(
                    conn,
                    run_id,
                    approved=True,
                    actor=web_actor,
                    create_cron_job=body.runNow,
                    # Fillable title-reconciliation cards retain the approved
                    # title order in their prompt. Reuse that hash so submitting
                    # answers does not require a second approval click.
                    expected_title_order_hash=(
                        body.expectedTitleOrderHash
                        or ((prompt.get("titleOrder") or {}).get("versionHash"))
                    ),
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/action-runs/%s/answer failed", run_id)
            raise HTTPException(status_code=500, detail=f"Answer action run failed: {exc}")

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
