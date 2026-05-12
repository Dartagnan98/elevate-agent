"""Admin Hub stage-action dispatcher.

Public surface:

* :func:`list_actions`
* :func:`create_action`
* :func:`update_action`
* :func:`delete_action`
* :func:`list_action_runs`
* :func:`evaluate`               — main hook called from data.deals
* :func:`list_conditional_docs`
* :func:`upsert_conditional_doc`

Architecture (per ``docs/plans/skyleigh-admin-hub-codex-review-B-dispatch.md``):

The dispatcher is a **producer** of action-run rows + cron jobs. It is NOT a
second skill runner — skills run via ``cron.jobs.create_job(...)`` and the
existing scheduler. A run row is created first, then immediate callers may
drain it into cron with ``create_cron_jobs=True``. Deferred callers can use
``drain_queued_action_runs`` later.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from elevate_cli.data._util import new_id, now_iso


def _request_agent_worker_wake(*, reason: str, actor: str) -> None:
    """Best-effort nudge for the gateway worker after durable queue writes."""
    try:
        from elevate_cli.agent_worker import request_wake

        request_wake(reason=reason, actor=actor, delay_seconds=0.25)
    except Exception:
        return


_VALID_TRIGGERS = {
    "stage_entry",
    "stage_exit",
    "toggle_change",
    "recurring",
    "time_offset",
    "external_event",
    "manual",
}
_VALID_SIDES = {"listing", "buyer"}
_VALID_RUN_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "completed",
    "failed",
    "skipped",
    "cancelled",
    "waiting_human",
    "waiting_external",
}

_ADMIN_AGENT_ID = "admin"
_ADMIN_ORCHESTRATOR_SKILL = "admin-agent"
_ADMIN_RESULT_WRITER_SKILL = "admin-result-writer"
_ADMIN_DEAL_MATCHER_SKILL = "deal-matcher"


_DEFAULT_ADMIN_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "S1 Collect listing info for MLC",
        "trigger": "stage_entry",
        "skill": "mlc",
        "skill_args": {"mode": "intake"},
        "side": "listing",
        "to_stage": 1,
        "priority": 90,
    },
    {
        "name": "S2 Prepare MLC package",
        "trigger": "stage_entry",
        "skill": "mlc",
        "skill_args": {"mode": "documents"},
        "side": "listing",
        "to_stage": 2,
        "priority": 90,
    },
    {
        "name": "S2 Sync signing status",
        "trigger": "stage_entry",
        "skill": "signing-package",
        "skill_args": {
            "mode": "sync",
            "provider": "digisign",
            "packageKind": "listing_mlc",
            "sendPolicy": "approval_required",
        },
        "side": "listing",
        "to_stage": 2,
        "priority": 80,
    },
    {
        "name": "S2 Check SkySlope opening docs",
        "trigger": "stage_entry",
        "skill": "skyslope-sync",
        "side": "listing",
        "to_stage": 2,
        "priority": 70,
    },
    {
        "name": "S3 Prepare listing-ready photos",
        "trigger": "stage_entry",
        "skill": "photo-cleanup",
        "side": "listing",
        "to_stage": 3,
        "priority": 90,
    },
    {
        "name": "S4 Research prior listing context",
        "trigger": "stage_entry",
        "skill": "property-lookup",
        "side": "listing",
        "to_stage": 4,
        "priority": 85,
    },
    {
        "name": "S4 Build MLS launch package",
        "trigger": "stage_entry",
        "skill": "listing-build",
        "side": "listing",
        "to_stage": 4,
        "priority": 80,
    },
    {
        "name": "S5 Run listing-live marketing",
        "trigger": "stage_entry",
        "skill": "marketing",
        "side": "listing",
        "to_stage": 5,
        "priority": 80,
    },
    {
        "name": "S6 Review accepted-offer package",
        "trigger": "stage_entry",
        "skill": "offer-review",
        "side": "listing",
        "to_stage": 6,
        "priority": 90,
    },
    {
        "name": "S7 Run subject-removal admin check",
        "trigger": "stage_entry",
        "skill": "subject-removal",
        "side": "listing",
        "to_stage": 7,
        "priority": 90,
    },
    {
        "name": "S7 Sync subject-removal signing",
        "trigger": "stage_entry",
        "skill": "signing-package",
        "skill_args": {
            "mode": "sync",
            "provider": "digisign",
            "packageKind": "subject_removal",
            "sendPolicy": "approval_required",
        },
        "side": "listing",
        "to_stage": 7,
        "priority": 70,
    },
    {
        "name": "S8 Run closing admin check",
        "trigger": "stage_entry",
        "skill": "closing-admin",
        "side": "listing",
        "to_stage": 8,
        "priority": 90,
    },
    {
        "name": "S9 Verify SkySlope closeout",
        "trigger": "stage_entry",
        "skill": "skyslope-sync",
        "side": "listing",
        "to_stage": 9,
        "priority": 90,
    },
    {
        "name": "S9 Create sold update and nurture handoff",
        "trigger": "stage_entry",
        "skill": "marketing",
        "side": "listing",
        "to_stage": 9,
        "priority": 70,
    },
)


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


def _decode_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _encode_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _admin_action_skill_chain(worker_skill: str | None) -> list[str]:
    """Return the ordered skill stack for Admin cron orchestration."""
    ordered = [
        _ADMIN_ORCHESTRATOR_SKILL,
        _ADMIN_DEAL_MATCHER_SKILL,
        str(worker_skill or "").strip(),
        _ADMIN_RESULT_WRITER_SKILL,
    ]
    seen: set[str] = set()
    skills: list[str] = []
    for skill in ordered:
        if skill and skill not in seen:
            seen.add(skill)
            skills.append(skill)
    return skills


def _admin_agent_delivery_target() -> str:
    """Return the Admin agent Telegram delivery lane for cron jobs."""
    try:
        from gateway.agent_lanes import agent_telegram_delivery_target
    except Exception:
        return "telegram"
    return agent_telegram_delivery_target(_ADMIN_AGENT_ID)


def _dashboard_callback_base_url() -> str:
    value = (
        os.getenv("ELEVATE_DASHBOARD_URL")
        or os.getenv("ELEVATE_WEB_URL")
        or "http://127.0.0.1:9119"
    )
    return value.rstrip("/")


def _validate_stage(stage: int | None) -> int | None:
    if stage is None:
        return None
    if isinstance(stage, bool):
        raise ValueError("stage must be an integer between 0 and 9")
    stage_int = int(stage)
    if stage_int < 0 or stage_int > 9:
        raise ValueError("stage must be an integer between 0 and 9")
    return stage_int


def _row_to_action(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "side": row["side"],
        "fromStage": row["from_stage"],
        "toStage": row["to_stage"],
        "trigger": row["trigger"],
        "fieldKey": row["field_key"],
        "condition": _decode_json(row["condition_json"]),
        "skill": row["skill"],
        "skillArgs": _decode_json(row["skill_args_json"]) or {},
        "provinceFilter": _decode_json(row["province_filter_json"]),
        "enabled": bool(row["enabled"]),
        "priority": row["priority"],
        "approvalRequired": bool(row["approval_required"]),
        "version": row["version"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "registryId": row["registry_id"],
        "dealId": row["deal_id"],
        "dealEventId": row["deal_event_id"],
        "cronJobId": row["cron_job_id"],
        "harnessRunId": _row_value(row, "harness_run_id"),
        "status": row["status"],
        "outputPath": row["output_path"],
        "errorMessage": row["error_message"],
        "payload": _decode_json(row["payload_json"]),
        "humanPrompt": _decode_json(_row_value(row, "human_prompt_json")),
        "result": _decode_json(_row_value(row, "result_json")),
        "resultIdempotencyKey": _row_value(row, "result_idempotency_key"),
        "createdAt": row["created_at"],
        "startedAt": _row_value(row, "started_at"),
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
        "skill": _row_value(row, "skill"),
        "registryName": _row_value(row, "registry_name"),
    }


def _row_to_doc(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "province": row["province"],
        "side": _row_value(row, "side"),
        "stage": _row_value(row, "stage"),
        "fieldKey": row["field_key"],
        "fieldValue": row["field_value"],
        "docCode": row["doc_code"],
        "docName": row["doc_name"],
        "notes": row["notes"],
        "createdAt": row["created_at"],
    }


# --- Registry CRUD -----------------------------------------------------


def list_actions(
    conn: sqlite3.Connection,
    *,
    trigger: str | None = None,
    side: str | None = None,
    enabled: bool | None = None,
    skill: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List registry rows for the admin UI / dispatcher."""
    if trigger is not None and trigger not in _VALID_TRIGGERS:
        raise ValueError(f"invalid trigger {trigger!r}")
    if side is not None and side not in _VALID_SIDES:
        raise ValueError(f"invalid side {side!r}")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    sql = "SELECT * FROM admin_action_registry WHERE 1=1"
    params: list[Any] = []
    if trigger is not None:
        sql += " AND trigger = ?"
        params.append(trigger)
    if side is not None:
        sql += " AND (side IS NULL OR side = ?)"
        params.append(side)
    if enabled is not None:
        sql += " AND enabled = ?"
        params.append(1 if enabled else 0)
    if skill is not None:
        sql += " AND skill = ?"
        params.append(skill)
    sql += " ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return [_row_to_action(r) for r in conn.execute(sql, params).fetchall()]


def get_action(conn: sqlite3.Connection, action_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM admin_action_registry WHERE id=?", (action_id,)
    ).fetchone()
    return _row_to_action(row) if row else None


def create_action(
    conn: sqlite3.Connection,
    *,
    name: str,
    trigger: str,
    skill: str,
    side: str | None = None,
    from_stage: int | None = None,
    to_stage: int | None = None,
    field_key: str | None = None,
    condition: Mapping[str, Any] | None = None,
    skill_args: Mapping[str, Any] | None = None,
    province_filter: list[str] | None = None,
    enabled: bool = True,
    priority: int = 0,
    approval_required: bool = False,
) -> dict[str, Any]:
    """Insert a registry row."""
    if not name or not name.strip():
        raise ValueError("name is required")
    if trigger not in _VALID_TRIGGERS:
        raise ValueError(f"invalid trigger {trigger!r}")
    if side is not None and side not in _VALID_SIDES:
        raise ValueError(f"invalid side {side!r}")
    if not skill or not skill.strip():
        raise ValueError("skill is required")
    if trigger == "toggle_change" and not field_key:
        raise ValueError("toggle_change rules require field_key")
    from_stage = _validate_stage(from_stage)
    to_stage = _validate_stage(to_stage)

    aid = new_id()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO admin_action_registry(
            id, name, side, from_stage, to_stage, trigger, field_key,
            condition_json, skill, skill_args_json, province_filter_json,
            enabled, priority, approval_required, version,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            aid,
            name.strip(),
            side,
            from_stage,
            to_stage,
            trigger,
            field_key,
            _encode_json(dict(condition)) if condition else None,
            skill.strip(),
            _encode_json(dict(skill_args)) if skill_args else None,
            _encode_json(list(province_filter)) if province_filter else None,
            1 if enabled else 0,
            int(priority),
            1 if approval_required else 0,
            1,
            now,
            now,
        ),
    )
    return get_action(conn, aid)  # type: ignore[return-value]


def ensure_default_admin_actions(conn: sqlite3.Connection) -> dict[str, Any]:
    """Idempotently seed the production listing phase action registry."""
    existing_rows = conn.execute("SELECT * FROM admin_action_registry").fetchall()
    existing_by_name = {str(row["name"]).strip().lower(): _row_to_action(row) for row in existing_rows}
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for spec in _DEFAULT_ADMIN_ACTIONS:
        name = str(spec["name"])
        found = existing_by_name.get(name.strip().lower())
        if found:
            expected_approval = bool(spec.get("approval_required", False))
            expected_skill_args = dict(spec.get("skill_args") or {})
            needs_update = (
                found["trigger"] != spec["trigger"]
                or found["skill"] != spec["skill"]
                or found["skillArgs"] != expected_skill_args
                or found["side"] != spec.get("side")
                or found["toStage"] != spec.get("to_stage")
                or found["priority"] != int(spec.get("priority", 0))
                or found["approvalRequired"] != expected_approval
            )
            if needs_update:
                action = update_action(
                    conn,
                    found["id"],
                    trigger=spec["trigger"],
                    skill=spec["skill"],
                    side=spec.get("side"),
                    to_stage=spec.get("to_stage"),
                    skill_args=expected_skill_args,
                    priority=int(spec.get("priority", 0)),
                    approval_required=expected_approval,
                )
                updated.append(action)
                existing_by_name[name.strip().lower()] = action
            else:
                skipped.append(found)
            continue
        action = create_action(conn, **spec)
        created.append(action)
        existing_by_name[name.strip().lower()] = action
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "count": len(created) + len(updated) + len(skipped),
    }


def update_action(
    conn: sqlite3.Connection,
    action_id: str,
    *,
    name: str | None = None,
    trigger: str | None = None,
    skill: str | None = None,
    side: str | None = None,
    from_stage: int | None = None,
    to_stage: int | None = None,
    field_key: str | None = None,
    condition: Mapping[str, Any] | None = None,
    skill_args: Mapping[str, Any] | None = None,
    province_filter: list[str] | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
    approval_required: bool | None = None,
    clear_condition: bool = False,
    clear_skill_args: bool = False,
    clear_province_filter: bool = False,
    clear_field_key: bool = False,
) -> dict[str, Any]:
    """Update a registry row and bump its version. Only sets supplied fields."""
    existing = get_action(conn, action_id)
    if existing is None:
        raise LookupError(f"action {action_id!r} not found")

    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        if not name.strip():
            raise ValueError("name must be non-empty")
        sets.append("name=?")
        params.append(name.strip())
    if trigger is not None:
        if trigger not in _VALID_TRIGGERS:
            raise ValueError(f"invalid trigger {trigger!r}")
        sets.append("trigger=?")
        params.append(trigger)
    if skill is not None:
        if not skill.strip():
            raise ValueError("skill must be non-empty")
        sets.append("skill=?")
        params.append(skill.strip())
    if side is not None or "side" in {}:  # placeholder; explicit None means "set NULL"
        pass  # Side updates handled below for clarity
    if side is not None:
        if side not in _VALID_SIDES and side != "":
            raise ValueError(f"invalid side {side!r}")
        sets.append("side=?")
        params.append(side or None)
    if from_stage is not None:
        sets.append("from_stage=?")
        params.append(_validate_stage(from_stage))
    if to_stage is not None:
        sets.append("to_stage=?")
        params.append(_validate_stage(to_stage))
    if field_key is not None:
        sets.append("field_key=?")
        params.append(field_key or None)
    if clear_field_key:
        sets.append("field_key=?")
        params.append(None)
    if condition is not None:
        sets.append("condition_json=?")
        params.append(_encode_json(dict(condition)))
    if clear_condition:
        sets.append("condition_json=?")
        params.append(None)
    if skill_args is not None:
        sets.append("skill_args_json=?")
        params.append(_encode_json(dict(skill_args)))
    if clear_skill_args:
        sets.append("skill_args_json=?")
        params.append(None)
    if province_filter is not None:
        sets.append("province_filter_json=?")
        params.append(_encode_json(list(province_filter)))
    if clear_province_filter:
        sets.append("province_filter_json=?")
        params.append(None)
    if enabled is not None:
        sets.append("enabled=?")
        params.append(1 if enabled else 0)
    if priority is not None:
        sets.append("priority=?")
        params.append(int(priority))
    if approval_required is not None:
        sets.append("approval_required=?")
        params.append(1 if approval_required else 0)

    if not sets:
        return existing

    # Re-validate toggle_change/field_key invariant after the merge.
    final_trigger = trigger if trigger is not None else existing["trigger"]
    final_field_key = (
        None
        if clear_field_key
        else (field_key if field_key is not None else existing["fieldKey"])
    )
    if final_trigger == "toggle_change" and not final_field_key:
        raise ValueError("toggle_change rules require field_key")

    sets.append("version=version+1")
    sets.append("updated_at=?")
    params.append(now_iso())
    params.append(action_id)
    conn.execute(
        f"UPDATE admin_action_registry SET {', '.join(sets)} WHERE id=?",
        params,
    )
    return get_action(conn, action_id)  # type: ignore[return-value]


def delete_action(conn: sqlite3.Connection, action_id: str) -> None:
    """Delete a registry row. Cascades to any queued runs that reference it."""
    cur = conn.execute(
        "DELETE FROM admin_action_registry WHERE id=?", (action_id,)
    )
    if cur.rowcount == 0:
        raise LookupError(f"action {action_id!r} not found")


# --- Run log -----------------------------------------------------------


def list_action_runs(
    conn: sqlite3.Connection,
    *,
    deal_id: str | None = None,
    registry_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if status is not None and status not in _VALID_RUN_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    sql = """
        SELECT r.*, a.skill AS skill, a.name AS registry_name
        FROM admin_action_runs r
        LEFT JOIN admin_action_registry a ON a.id = r.registry_id
        WHERE 1=1
    """
    params: list[Any] = []
    if deal_id is not None:
        sql += " AND r.deal_id = ?"
        params.append(deal_id)
    if registry_id is not None:
        sql += " AND r.registry_id = ?"
        params.append(registry_id)
    if status is not None:
        sql += " AND r.status = ?"
        params.append(status)
    sql += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return [_row_to_run(r) for r in conn.execute(sql, params).fetchall()]


def _select_action_run_with_registry(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT r.*, a.skill AS skill, a.name AS registry_name
        FROM admin_action_runs r
        LEFT JOIN admin_action_registry a ON a.id = r.registry_id
        WHERE r.id=?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"action run {run_id!r} not found")
    return row


def _insert_run(
    conn: sqlite3.Connection,
    *,
    registry_id: str,
    deal_id: str,
    deal_event_id: str | None,
    payload: Mapping[str, Any] | None,
    status: str = "queued",
    human_prompt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in _VALID_RUN_STATUSES:
        raise ValueError(f"invalid run status {status!r}")
    if deal_event_id:
        existing = conn.execute(
            """
            SELECT id FROM admin_action_runs
            WHERE registry_id=? AND deal_event_id=?
            """,
            (registry_id, deal_event_id),
        ).fetchone()
        if existing is not None:
            return _row_to_run(_select_action_run_with_registry(conn, existing["id"]))
    rid = new_id()
    now = now_iso()
    try:
        conn.execute(
            """
            INSERT INTO admin_action_runs(
                id, registry_id, deal_id, deal_event_id,
                status, payload_json, human_prompt_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                registry_id,
                deal_id,
                deal_event_id,
                status,
                _encode_json(dict(payload)) if payload else None,
                _encode_json(dict(human_prompt)) if human_prompt else None,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        if deal_event_id:
            existing = conn.execute(
                """
                SELECT id FROM admin_action_runs
                WHERE registry_id=? AND deal_event_id=?
                """,
                (registry_id, deal_event_id),
            ).fetchone()
            if existing is not None:
                return _row_to_run(_select_action_run_with_registry(conn, existing["id"]))
        raise
    row = _select_action_run_with_registry(conn, rid)
    if status == "queued":
        _request_agent_worker_wake(reason=f"admin-run:{rid}", actor="admin-dispatch")
    return _row_to_run(row)


def _hash_callback_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_callback_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _hash_callback_token(token)


def verify_action_run_token(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    run_id: str,
    token: str,
) -> bool:
    """Return True when ``token`` is the callback token for one run."""
    if not token:
        return False
    row = conn.execute(
        "SELECT callback_token_hash FROM admin_action_runs WHERE id=? AND deal_id=?",
        (run_id, deal_id),
    ).fetchone()
    if row is None or not row["callback_token_hash"]:
        return False
    return hmac.compare_digest(_hash_callback_token(token), row["callback_token_hash"])


def _run_lookup(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT r.*, a.name, a.skill, a.skill_args_json, a.approval_required,
               d.side, d.current_stage, d.province
        FROM admin_action_runs r
        JOIN admin_action_registry a ON a.id = r.registry_id
        JOIN deals d ON d.id = r.deal_id
        WHERE r.id=?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"action run {run_id!r} not found")
    return row


def _row_to_spawn_action(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["registry_id"],
        "name": row["name"],
        "skill": row["skill"],
        "skillArgs": _decode_json(row["skill_args_json"]) or {},
    }


def _row_to_spawn_deal(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["deal_id"],
        "side": row["side"],
        "currentStage": row["current_stage"],
        "province": row["province"],
    }


def _non_empty_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in (value or {}).items()
        if item not in (None, "", [], {})
    }


def _agent_run_context_for_prompt(conn: sqlite3.Connection, deal_id: str) -> dict[str, Any]:
    """Build the compact SQLite context injected into Admin skill runs."""
    try:
        from elevate_cli.data.deals import get_deal_context
        from elevate_cli.data.admin_setup import get_admin_setup

        context = get_deal_context(conn, deal_id)
        setup = get_admin_setup(conn)
        setup_profile = setup.get("profile") or {}
        setup_items = {
            item.get("key"): {
                "status": item.get("status"),
                "provider": item.get("provider"),
                "value": item.get("value"),
                "notes": item.get("notes"),
            }
            for item in (setup.get("items") or [])
            if item.get("key") in {
                "browser_workflows",
                "photo_processing",
                "mls",
                "forms_provider",
                "signing_provider",
                "compliance_platform",
                "showing_platform",
                "fintrac_workflow",
            }
        }
        deal = context.get("deal") or {}
        primary = context.get("primaryContact") or {}
        flow = context.get("dealFlow") or {}
        gate = flow.get("gate") or {}
        province_guide = context.get("provinceGuide") or {}
        return {
            "source": "sqlite:deal_context",
            "deal": {
                "id": deal.get("id"),
                "title": deal.get("title"),
                "side": deal.get("side"),
                "currentStage": deal.get("currentStage"),
                "province": deal.get("province"),
                "market": deal.get("market"),
                "listingAddress": deal.get("listingAddress"),
                "status": deal.get("status"),
            },
            "primaryContact": _non_empty_mapping(
                {
                    "id": primary.get("id"),
                    "displayName": primary.get("displayName"),
                    "email": primary.get("primaryEmail"),
                    "phone": primary.get("primaryPhone"),
                    "type": primary.get("type"),
                    "stage": primary.get("stage"),
                }
            ),
            "conditions": _non_empty_mapping(context.get("conditions") or {}),
            "adminSetup": {
                "country": setup_profile.get("country"),
                "province": setup_profile.get("province"),
                "market": setup_profile.get("market"),
                "boardMemberships": setup_profile.get("boardMemberships") or [],
                "approvalPolicy": setup_profile.get("approvalPolicy") or {},
                "regionalMemory": setup_profile.get("regionalMemory") or {},
                "browserWorkflows": (setup_items.get("browser_workflows") or {}).get("value") or {},
                "photoProcessing": (setup_items.get("photo_processing") or {}).get("value") or {},
                "providers": {
                    key: value
                    for key, value in setup_items.items()
                    if key not in {"browser_workflows", "photo_processing"}
                },
            },
            "dealFlow": {
                "packageKey": flow.get("packageKey"),
                "stage": flow.get("stage"),
                "stageName": flow.get("stageName"),
                "stageSubtitle": flow.get("stageSubtitle"),
                "checklistItems": flow.get("checklistItems") or [],
                "requiredFields": flow.get("requiredFields") or [],
                "requiredDocs": flow.get("requiredDocs") or [],
                "requiredForms": flow.get("requiredForms") or [],
                "automationTriggers": flow.get("automationTriggers") or [],
                "gate": {
                    "canAdvance": gate.get("canAdvance"),
                    "missingChecklist": gate.get("missingChecklist") or [],
                    "missingFields": gate.get("missingFields") or [],
                    "missingDocs": gate.get("missingDocs") or [],
                    "blockingRuns": gate.get("blockingRuns") or [],
                },
            },
            "conditionalDocs": context.get("conditionalDocs") or [],
            "provinceGuide": {
                "province": province_guide.get("province"),
                "provinceLabel": province_guide.get("provinceLabel"),
                "coverage": province_guide.get("coverage") or {},
                "forms": province_guide.get("forms") or [],
            },
            "agentGuideMemory": context.get("agentGuideMemory") or {},
            "attachments": [
                _non_empty_mapping(
                    {
                        "id": item.get("id"),
                        "kind": item.get("kind"),
                        "filePath": item.get("filePath"),
                        "summary": item.get("summary"),
                    }
                )
                for item in (context.get("attachments") or [])
            ],
        }
    except Exception as exc:
        return {
            "source": "sqlite:deal_context",
            "deal": {"id": deal_id},
            "contextError": str(exc),
        }


def dispatch_action_run_to_cron(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    actor: str = "system",
) -> dict[str, Any]:
    """Move one queued run into cron and mark it running.

    This is the explicit queued-run drain primitive. It regenerates the
    per-run callback token immediately before cron creation so stale queued
    runs can be retried without storing a plaintext token in SQLite.
    """
    row = _run_lookup(conn, run_id)
    if row["status"] != "queued":
        return _row_to_run(_select_action_run_with_registry(conn, run_id))

    now = now_iso()
    payload = _decode_json(row["payload_json"]) or {}
    if not isinstance(payload, dict):
        payload = {"prior": payload}

    setup_block = _admin_setup_dispatch_block_reason(conn)
    if setup_block:
        payload["dispatchBlocked"] = {
            "message": setup_block,
            "actor": actor,
            "recordedAt": now,
        }
        conn.execute(
            """
            UPDATE admin_action_runs
            SET payload_json=?, updated_at=?
            WHERE id=?
            """,
            (_encode_json(payload), now, run_id),
        )
        return _row_to_run(_select_action_run_with_registry(conn, run_id))

    payload.pop("dispatchBlocked", None)
    token, token_hash = _new_callback_token()
    conn.execute(
        """
        UPDATE admin_action_runs
        SET callback_token_hash=?, payload_json=?, updated_at=?
        WHERE id=?
        """,
        (token_hash, _encode_json(payload), now, run_id),
    )
    agent_context = _agent_run_context_for_prompt(conn, str(row["deal_id"]))
    cron_job_id = _spawn_cron_job(
        action=_row_to_spawn_action(row),
        deal=_row_to_spawn_deal(row),
        run_id=run_id,
        callback_token=token,
        actor=actor,
        payload=payload,
        agent_context=agent_context,
    )
    if cron_job_id:
        conn.execute(
            """
            UPDATE admin_action_runs
            SET cron_job_id=?, status='running', started_at=?, updated_at=?
            WHERE id=?
            """,
            (cron_job_id, now, now, run_id),
        )
    else:
        payload["dispatchError"] = {
            "message": "cron job creation failed",
            "actor": actor,
            "recordedAt": now,
        }
        conn.execute(
            """
            UPDATE admin_action_runs
            SET status='failed', error_message=?, payload_json=?, updated_at=?, completed_at=?
            WHERE id=?
            """,
            (
                "cron job creation failed",
                _encode_json(payload),
                now,
                now,
                run_id,
            ),
        )
    return _row_to_run(_select_action_run_with_registry(conn, run_id))


def drain_queued_action_runs(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    actor: str = "system",
) -> list[dict[str, Any]]:
    """Dispatch queued Admin action runs into cron."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if _admin_setup_dispatch_block_reason(conn):
        return []
    rows = conn.execute(
        """
        SELECT r.id
        FROM admin_action_runs r
        JOIN admin_action_registry a ON a.id = r.registry_id
        WHERE r.status='queued'
          AND r.cron_job_id IS NULL
          AND a.approval_required=0
        ORDER BY r.created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dispatch_action_run_to_cron(conn, row["id"], actor=actor) for row in rows]


def _admin_setup_dispatch_block_reason(conn: sqlite3.Connection) -> str | None:
    """Return why Admin cron dispatch is blocked, or None when setup is ready."""
    try:
        from elevate_cli.data.admin_setup import get_admin_setup

        snapshot = get_admin_setup(conn)
    except Exception as exc:
        return f"admin setup readiness could not be verified: {exc}"
    if snapshot.get("complete"):
        return None
    missing = ", ".join(snapshot.get("missingRequiredKeys") or [])
    if missing:
        return f"admin setup is required before starting admin work: {missing}"
    return "admin setup is required before starting admin work"


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def mark_stale_action_runs(
    conn: sqlite3.Connection,
    *,
    max_running_minutes: int = 120,
    actor: str = "agent-worker",
) -> list[dict[str, Any]]:
    """Fail running Admin action runs that never wrote a result callback."""
    if max_running_minutes < 1:
        raise ValueError("max_running_minutes must be >= 1")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_running_minutes)
    rows = conn.execute(
        """
        SELECT * FROM admin_action_runs
        WHERE status='running'
        ORDER BY COALESCE(started_at, updated_at, created_at) ASC
        """
    ).fetchall()
    stale_rows: list[sqlite3.Row] = []
    for row in rows:
        started = (
            _parse_iso(_row_value(row, "started_at"))
            or _parse_iso(row["updated_at"])
            or _parse_iso(row["created_at"])
        )
        if started is not None and started <= cutoff:
            stale_rows.append(row)
    if not stale_rows:
        return []
    now = now_iso()
    recovered: list[dict[str, Any]] = []
    for row in stale_rows:
        payload = _decode_json(row["payload_json"]) or {}
        if not isinstance(payload, dict):
            payload = {"prior": payload}
        payload["recovery"] = {
            "event": "stale_running_failed",
            "actor": actor,
            "maxRunningMinutes": max_running_minutes,
            "recordedAt": now,
        }
        message = (
            "Admin action run exceeded "
            f"{max_running_minutes} minute runtime without result callback."
        )
        conn.execute(
            """
            UPDATE admin_action_runs
            SET status='failed', error_message=?, payload_json=?, updated_at=?, completed_at=?
            WHERE id=?
            """,
            (message, _encode_json(payload), now, now, row["id"]),
        )
        updated = conn.execute("SELECT * FROM admin_action_runs WHERE id=?", (row["id"],)).fetchone()
        recovered.append(_row_to_run(updated))
    return recovered


def approve_action_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    approved: bool = True,
    actor: str = "human",
    create_cron_job: bool = True,
) -> dict[str, Any]:
    """Approve or cancel a human-gated run."""
    row = _run_lookup(conn, run_id)
    if row["status"] != "waiting_human":
        raise ValueError("only waiting_human runs can be approved")
    now = now_iso()
    prompt = _decode_json(_row_value(row, "human_prompt_json")) or {}
    if not isinstance(prompt, dict):
        prompt = {"prompt": prompt}
    prompt["decision"] = {
        "approved": bool(approved),
        "actor": actor,
        "decidedAt": now,
    }
    if not approved:
        conn.execute(
            """
            UPDATE admin_action_runs
            SET status='cancelled', human_prompt_json=?, updated_at=?, completed_at=?
            WHERE id=?
            """,
            (_encode_json(prompt), now, now, run_id),
        )
        return _row_to_run(_select_action_run_with_registry(conn, run_id))
    conn.execute(
        """
        UPDATE admin_action_runs
        SET status='queued', human_prompt_json=?, updated_at=?
        WHERE id=?
        """,
        (_encode_json(prompt), now, run_id),
    )
    if create_cron_job:
        return dispatch_action_run_to_cron(conn, run_id, actor=actor)
    _request_agent_worker_wake(reason=f"admin-run-approved:{run_id}", actor=actor)
    return _row_to_run(_select_action_run_with_registry(conn, run_id))


def queue_action_run(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    skill: str,
    name: str | None = None,
    payload: Mapping[str, Any] | None = None,
    create_cron_job: bool = False,
    actor: str = "system",
) -> dict[str, Any]:
    """Queue one ad-hoc Admin action run.

    Skill callbacks use this for ``next_tasks``.  The row still references a
    registry entry so the existing schema remains intact, but the registry row
    is disabled and manual-only; it is not a durable automation rule.
    """
    if not skill or not skill.strip():
        raise ValueError("skill is required")
    deal_row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if deal_row is None:
        raise LookupError(f"deal {deal_id!r} not found")
    from elevate_cli.data.deals import _row_to_deal  # local import to avoid cycles

    deal = _row_to_deal(deal_row)
    action = create_action(
        conn,
        name=name or f"Next task: {skill.strip()}",
        trigger="manual",
        skill=skill.strip(),
        side=deal["side"],
        enabled=False,
    )
    run_payload = {
        "trigger": "next_task",
        "dealSide": deal["side"],
        "currentStage": deal["currentStage"],
        "province": deal["province"],
        "registryName": action["name"],
        **(dict(payload) if payload else {}),
    }
    if create_cron_job:
        run = _insert_run(
            conn,
            registry_id=action["id"],
            deal_id=deal_id,
            deal_event_id=None,
            payload=run_payload,
        )
        return dispatch_action_run_to_cron(conn, run["id"], actor=actor)
    return _insert_run(
        conn,
        registry_id=action["id"],
        deal_id=deal_id,
        deal_event_id=None,
        payload=run_payload,
    )


# --- Condition evaluator ----------------------------------------------


def _condition_matches(
    condition: Mapping[str, Any] | None,
    deal: Mapping[str, Any],
) -> bool:
    """Match a flat {field: value} condition against the deal.

    Composite predicates and edge-triggered ``predicate_matched`` semantics
    are deferred to a follow-up sprint; PR-2 only handles AND-of-equals.
    """
    if not condition:
        return True
    if not isinstance(condition, Mapping):
        return False
    for raw_key, expected in condition.items():
        actual = deal.get(raw_key)
        if actual is None and "_" in raw_key:
            # Match against the camelCase API names the deal row uses.
            parts = raw_key.split("_")
            camel = parts[0] + "".join(p.title() for p in parts[1:])
            actual = deal.get(camel)
        if actual != expected:
            return False
    return True


def _province_allowed(
    province_filter: list[str] | None, province: str | None
) -> bool:
    if not province_filter:
        return True
    if province is None:
        return False
    return province in province_filter


def _registry_query_for_trigger(
    trigger: str,
    *,
    side: str | None,
    to_stage: int | None,
    from_stage: int | None,
    field_key: str | None,
) -> tuple[str, list[Any]]:
    sql = (
        "SELECT * FROM admin_action_registry "
        "WHERE enabled=1 AND trigger=?"
    )
    params: list[Any] = [trigger]
    if trigger in ("stage_entry", "stage_exit", "toggle_change"):
        sql += " AND (side IS NULL OR side=?)"
        params.append(side)
    if trigger == "stage_entry":
        sql += " AND (to_stage IS NULL OR to_stage=?)"
        params.append(to_stage)
    elif trigger == "stage_exit":
        sql += " AND (from_stage IS NULL OR from_stage=?)"
        params.append(from_stage)
    elif trigger == "toggle_change":
        sql += " AND field_key=?"
        params.append(field_key)
    sql += " ORDER BY priority DESC, created_at ASC"
    return sql, params


def evaluate(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    trigger: str,
    actor: str,
    deal_event_id: str | None = None,
    field_key: str | None = None,
    field_old: Any = None,
    field_new: Any = None,
    from_stage: int | None = None,
    to_stage: int | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    create_cron_jobs: bool = False,
) -> list[dict[str, Any]]:
    """Match registry rules against this trigger and persist queued run rows.

    Returns the list of runs created (status=``queued``). When
    ``create_cron_jobs`` is True, also calls ``cron.jobs.create_job`` for each
    new run and stamps the resulting cron_job_id on the row. Human-gated
    actions stay ``waiting_human`` until explicitly approved.
    """
    if trigger not in _VALID_TRIGGERS:
        raise ValueError(f"invalid trigger {trigger!r}")
    if trigger == "toggle_change" and not field_key:
        raise ValueError("toggle_change evaluations require field_key")

    deal_row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if deal_row is None:
        raise LookupError(f"deal {deal_id!r} not found")

    # Build a Mapping-shaped snapshot of the deal for condition matching.
    # We use the same camelCase shape the API returns so registry conditions
    # written against the public field names work directly.
    from elevate_cli.data.deals import _row_to_deal  # local import to avoid cycles

    deal = _row_to_deal(deal_row)

    sql, params = _registry_query_for_trigger(
        trigger,
        side=deal["side"],
        to_stage=to_stage,
        from_stage=from_stage,
        field_key=field_key,
    )
    rows = conn.execute(sql, params).fetchall()

    base_payload: dict[str, Any] = {
        "trigger": trigger,
        "dealSide": deal["side"],
        "currentStage": deal["currentStage"],
        "province": deal["province"],
    }
    if from_stage is not None:
        base_payload["fromStage"] = from_stage
    if to_stage is not None:
        base_payload["toStage"] = to_stage
    if field_key is not None:
        base_payload["fieldKey"] = field_key
        base_payload["fieldOld"] = field_old
        base_payload["fieldNew"] = field_new
    if extra_payload:
        base_payload["extra"] = dict(extra_payload)

    runs: list[dict[str, Any]] = []
    for row in rows:
        action = _row_to_action(row)
        if not _province_allowed(action["provinceFilter"], deal["province"]):
            continue
        if not _condition_matches(action["condition"], deal):
            continue

        initial_status = "waiting_human" if action.get("approvalRequired") else "queued"
        human_prompt = None
        if initial_status == "waiting_human":
            human_prompt = {
                "title": f"Approve {action['name']}",
                "message": "This automation requires approval before the skill runs.",
                "actionId": action["id"],
                "actionName": action["name"],
                "skill": action["skill"],
                "dealId": deal_id,
                "trigger": trigger,
            }

        run = _insert_run(
            conn,
            registry_id=action["id"],
            deal_id=deal_id,
            deal_event_id=deal_event_id,
            payload={**base_payload, "registryName": action["name"]},
            status=initial_status,
            human_prompt=human_prompt,
        )
        if create_cron_jobs and initial_status == "queued":
            run = dispatch_action_run_to_cron(conn, run["id"], actor=actor)
        runs.append(run)

    return runs


def _spawn_cron_job(
    *,
    action: Mapping[str, Any],
    deal: Mapping[str, Any],
    run_id: str,
    callback_token: str,
    actor: str,
    payload: Mapping[str, Any],
    agent_context: Mapping[str, Any] | None = None,
) -> str | None:
    """Hand the action off to ``cron.jobs.create_job`` and return its id.

    Imports lazily so unit tests of :func:`evaluate` (with
    ``create_cron_jobs=False``) don't pull in cron's filesystem state.
    Failures here never propagate — the queued run row is the source of
    truth, and the worker can retry later.
    """
    try:
        from cron import jobs as cron_jobs

        skill_args = action.get("skillArgs") or {}
        worker_skill = str(action.get("skill") or "").strip()
        skills = _admin_action_skill_chain(worker_skill)
        deliver_target = _admin_agent_delivery_target()
        callback_url = f"{_dashboard_callback_base_url()}/api/deals/{deal.get('id')}/runs/{run_id}/result"
        prompt_lines = [
            f"Admin agent orchestration action: {action.get('name')}",
            f"Deal: {deal.get('id')} ({deal.get('side')}, stage {deal.get('currentStage')})",
            f"Action run ID: {run_id}",
            f"Trigger: {payload.get('trigger')}",
            f"Worker skill: {worker_skill}",
            "",
            "Admin agent orchestration:",
            "- You are the Admin agent for this deal run. Coordinate the worker skill as a capability; do not treat it as an independent messenger.",
            "- All human outreach goes through the Admin agent Telegram lane. Worker skills must write back through the result contract and never contact the human or client directly.",
            "- Prepare documents, drafts, review notes, artifacts, or task updates first; ask for human confirmation only when the next step needs approval.",
            "- Use deal-matcher before attaching external documents unless this injected run context already proves the exact deal ID.",
            "- Use admin-result-writer to close the run with checklist updates, artifacts, next tasks, human prompts, and a stable idempotency key.",
            "",
            "When the skill is done, write the result back to the deal file:",
            f"POST {callback_url}",
            f"Header: X-Elevate-Run-Token: {callback_token}",
            "Use a stable idempotencyKey when retrying the same result.",
            "",
            "Admin Telegram handoff:",
            "- If you processed documents, routed artifacts, created drafts, or need human approval, include human_prompt in the result callback and make your final response a concise confirmation summary for the Admin agent Telegram lane.",
            "- Report SQLite changes only after the result callback succeeds. If the callback fails, say no SQLite updates were written and explain the callback/database mismatch.",
            "- Include the deal, documents/artifacts processed, callback status, and the exact decision needed.",
            "- If there is no new document/artifact and no human confirmation needed, respond exactly [SILENT].",
            "- Do not use send_message yourself; cron delivery handles the Admin agent Telegram lane.",
        ]
        if skill_args:
            prompt_lines.append(f"Skill args: {json.dumps(skill_args, default=str)}")
        if agent_context:
            prompt_lines.extend(
                [
                    "",
                    "Injected source-of-truth context from SQLite. Treat this as the run's working memory.",
                    "Use agentGuideMemory for province guide/reference/checklist/form material.",
                    "Use sourcePath values when the full local guide file is needed.",
                    json.dumps(agent_context, indent=2, default=str),
                ]
            )
        prompt = "\n".join(prompt_lines)
        job = cron_jobs.create_job(
            prompt=prompt,
            schedule=now_iso(),
            name=f"admin:{action.get('name')}:{deal.get('id')[:8]}",
            repeat=1,
            deliver=deliver_target,
            skills=skills,
            agent=_ADMIN_AGENT_ID,
            origin={
                "source": "admin_hub",
                "actor": actor,
                "agent": _ADMIN_AGENT_ID,
                "deal_id": deal.get("id"),
                "run_id": run_id,
                "telegram_lane": "admin-agent",
            },
        )
        return job.get("id") if isinstance(job, dict) else None
    except Exception:
        return None


# --- Conditional docs --------------------------------------------------


def list_conditional_docs(
    conn: sqlite3.Connection,
    *,
    province: str | None = None,
    side: str | None = None,
    stage: int | None = None,
    field_key: str | None = None,
    field_value: Any = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM conditional_docs WHERE 1=1"
    params: list[Any] = []
    if province is not None:
        sql += " AND province = ?"
        params.append(province)
    if side is not None:
        sql += " AND (side IS NULL OR side = ?)"
        params.append(side)
    if stage is not None:
        sql += " AND (stage IS NULL OR stage = ?)"
        params.append(int(stage))
    if field_key is not None:
        sql += " AND field_key = ?"
        params.append(field_key)
    if field_value is not None:
        sql += " AND field_value = ?"
        params.append(str(field_value))
    sql += " ORDER BY province, side, stage, field_key, field_value"
    return [_row_to_doc(r) for r in conn.execute(sql, params).fetchall()]


def upsert_conditional_doc(
    conn: sqlite3.Connection,
    *,
    province: str,
    field_key: str,
    field_value: Any,
    doc_code: str,
    doc_name: str,
    notes: str | None = None,
    side: str | None = None,
    stage: int | None = None,
) -> dict[str, Any]:
    if not province or not field_key or not doc_code:
        raise ValueError("province, field_key, and doc_code are required")
    field_value_str = str(field_value)
    existing = conn.execute(
        """
        SELECT id FROM conditional_docs
        WHERE province=? AND field_key=? AND field_value=? AND doc_code=?
        """,
        (province, field_key, field_value_str, doc_code),
    ).fetchone()
    now = now_iso()
    if existing:
        conn.execute(
            "UPDATE conditional_docs SET doc_name=?, notes=?, side=?, stage=? WHERE id=?",
            (doc_name, notes, side, stage, existing["id"]),
        )
        row = conn.execute(
            "SELECT * FROM conditional_docs WHERE id=?", (existing["id"],)
        ).fetchone()
    else:
        did = new_id()
        conn.execute(
            """
            INSERT INTO conditional_docs(
                id, province, field_key, field_value,
                doc_code, doc_name, notes, created_at, side, stage
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (did, province, field_key, field_value_str, doc_code, doc_name, notes, now, side, stage),
        )
        row = conn.execute(
            "SELECT * FROM conditional_docs WHERE id=?", (did,)
        ).fetchone()
    return _row_to_doc(row)


# --- Date trigger ledger ----------------------------------------------


def record_date_trigger_firing(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    registry_id: str,
    field_key: str,
    target_date: str,
    offset_days: int = 0,
    run_id: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Record one date-relative firing and return whether it was new."""
    if not deal_id or not registry_id or not field_key or not target_date:
        raise ValueError("deal_id, registry_id, field_key, and target_date are required")
    existing = conn.execute(
        """
        SELECT * FROM admin_date_trigger_firings
        WHERE deal_id=? AND registry_id=? AND field_key=? AND offset_days=? AND target_date=?
        """,
        (deal_id, registry_id, field_key, int(offset_days), target_date),
    ).fetchone()
    if existing is not None:
        return {**dict(existing), "created": False}
    fid = new_id()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO admin_date_trigger_firings(
            id, deal_id, registry_id, run_id, field_key,
            offset_days, target_date, fired_at, actor
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (fid, deal_id, registry_id, run_id, field_key, int(offset_days), target_date, now, actor),
    )
    row = conn.execute(
        "SELECT * FROM admin_date_trigger_firings WHERE id=?", (fid,)
    ).fetchone()
    return {**dict(row), "created": True}
