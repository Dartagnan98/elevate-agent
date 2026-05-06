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
existing scheduler. By default :func:`evaluate` only persists a queued run
row; a separate worker drains those rows and creates cron jobs. Callers that
need an immediate, blocking run (e.g. a manual button click) can pass
``create_cron_jobs=True``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from elevate_cli.data._util import new_id, now_iso


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
    "failed",
    "skipped",
    "cancelled",
}


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
        "status": row["status"],
        "outputPath": row["output_path"],
        "errorMessage": row["error_message"],
        "payload": _decode_json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
    }


def _row_to_doc(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "province": row["province"],
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

    sql = "SELECT * FROM admin_action_runs WHERE 1=1"
    params: list[Any] = []
    if deal_id is not None:
        sql += " AND deal_id = ?"
        params.append(deal_id)
    if registry_id is not None:
        sql += " AND registry_id = ?"
        params.append(registry_id)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return [_row_to_run(r) for r in conn.execute(sql, params).fetchall()]


def _insert_run(
    conn: sqlite3.Connection,
    *,
    registry_id: str,
    deal_id: str,
    deal_event_id: str | None,
    payload: Mapping[str, Any] | None,
    cron_job_id: str | None = None,
) -> dict[str, Any]:
    rid = new_id()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO admin_action_runs(
            id, registry_id, deal_id, deal_event_id, cron_job_id,
            status, payload_json, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            rid,
            registry_id,
            deal_id,
            deal_event_id,
            cron_job_id,
            "queued",
            _encode_json(dict(payload)) if payload else None,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM admin_action_runs WHERE id=?", (rid,)
    ).fetchone()
    return _row_to_run(row)


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
    new run and stamps the resulting cron_job_id on the row. The hook in
    ``data.deals`` keeps that flag False — a separate worker drains queued
    runs and creates cron jobs so deal mutations never block on cron I/O.
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

        cron_job_id: str | None = None
        if create_cron_jobs and not action.get("approvalRequired"):
            cron_job_id = _spawn_cron_job(
                action=action,
                deal=deal,
                actor=actor,
                payload=base_payload,
            )

        run = _insert_run(
            conn,
            registry_id=action["id"],
            deal_id=deal_id,
            deal_event_id=deal_event_id,
            payload={**base_payload, "registryName": action["name"]},
            cron_job_id=cron_job_id,
        )
        runs.append(run)

    return runs


def _spawn_cron_job(
    *,
    action: Mapping[str, Any],
    deal: Mapping[str, Any],
    actor: str,
    payload: Mapping[str, Any],
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
        prompt_lines = [
            f"Admin Hub action: {action.get('name')}",
            f"Deal: {deal.get('id')} ({deal.get('side')}, stage {deal.get('currentStage')})",
            f"Trigger: {payload.get('trigger')}",
        ]
        if skill_args:
            prompt_lines.append(f"Skill args: {json.dumps(skill_args, default=str)}")
        prompt = "\n".join(prompt_lines)
        job = cron_jobs.create_job(
            prompt=prompt,
            schedule=now_iso(),
            name=f"admin:{action.get('name')}:{deal.get('id')[:8]}",
            repeat=1,
            deliver="local",
            skills=[action["skill"]],
            origin={"source": "admin_hub", "actor": actor, "deal_id": deal.get("id")},
        )
        return job.get("id") if isinstance(job, dict) else None
    except Exception:
        return None


# --- Conditional docs --------------------------------------------------


def list_conditional_docs(
    conn: sqlite3.Connection,
    *,
    province: str | None = None,
    field_key: str | None = None,
    field_value: Any = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM conditional_docs WHERE 1=1"
    params: list[Any] = []
    if province is not None:
        sql += " AND province = ?"
        params.append(province)
    if field_key is not None:
        sql += " AND field_key = ?"
        params.append(field_key)
    if field_value is not None:
        sql += " AND field_value = ?"
        params.append(str(field_value))
    sql += " ORDER BY province, field_key, field_value"
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
            "UPDATE conditional_docs SET doc_name=?, notes=? WHERE id=?",
            (doc_name, notes, existing["id"]),
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
                doc_code, doc_name, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (did, province, field_key, field_value_str, doc_code, doc_name, notes, now),
        )
        row = conn.execute(
            "SELECT * FROM conditional_docs WHERE id=?", (did,)
        ).fetchone()
    return _row_to_doc(row)
