"""Read/write helpers for Admin Hub deals.

Public surface:

* :func:`get_deal`
* :func:`list_deals`
* :func:`create_deal`
* :func:`move_deal_stage`
* :func:`set_deal_toggle`
* :func:`list_deal_events`
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from elevate_cli.data._util import new_id, now_iso


_VALID_SIDES = {"listing", "buyer"}
_VALID_STATUSES = {"active", "closed", "archived"}
_VALID_EVENT_KINDS = {"created", "stage_transition", "toggle_change"}

_ENUM_FIELDS = {
    "signing_authority",
    "fintrac_form_type",
    "listing_track",
    "property_subtype",
    "estate_status",
    "transaction_type",
    "listing_type",
}
_TOGGLE_FIELDS = {
    "pep",
    "tenanted",
    "poa_signing",
    "corporate",
    "has_suite",
    "multiple_offers",
    "family_member",
    "dual_rep",
    "unrepresented_other_side",
    "lockbox",
    "delayed_offer",
    "sale_of_buyers_property",
}
_NAMED_FIELDS = _ENUM_FIELDS | _TOGGLE_FIELDS
_FIELD_API_NAMES = {
    "signing_authority": "signingAuthority",
    "fintrac_form_type": "fintracFormType",
    "listing_track": "listingTrack",
    "property_subtype": "propertySubtype",
    "estate_status": "estateStatus",
    "transaction_type": "transactionType",
    "listing_type": "listingType",
    "poa_signing": "poaSigning",
    "has_suite": "hasSuite",
    "multiple_offers": "multipleOffers",
    "family_member": "familyMember",
    "dual_rep": "dualRep",
    "unrepresented_other_side": "unrepresentedOtherSide",
    "delayed_offer": "delayedOffer",
    "sale_of_buyers_property": "saleOfBuyersProperty",
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


def _validate_stage(stage: int) -> int:
    if isinstance(stage, bool):
        raise ValueError("stage must be an integer between 0 and 9")
    stage_int = int(stage)
    if stage_int < 0 or stage_int > 9:
        raise ValueError("stage must be an integer between 0 and 9")
    return stage_int


def _sql_toggle_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if value in (0, 1):
        return int(value)
    raise ValueError("toggle values must be true, false, 0, 1, or null")


def _api_toggle_value(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _field_api_name(field: str) -> str:
    return _FIELD_API_NAMES.get(field, field)


def _row_to_deal(row: sqlite3.Row) -> dict[str, Any]:
    """Normalize one deals row into the Admin Hub API shape."""
    deal = {
        "id": row["id"],
        "title": row["title"],
        "side": row["side"],
        "currentStage": row["current_stage"],
        "status": row["status"],
        "province": row["province"],
        "primaryContactId": row["primary_contact_id"],
        "loftyContactId": row["lofty_contact_id"],
        "listingAddress": row["listing_address"],
        "extraToggles": _decode_json(row["extra_toggles_json"]) or {},
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "stageEnteredAt": row["stage_entered_at"],
        "closedAt": row["closed_at"],
    }
    for field in sorted(_ENUM_FIELDS):
        deal[_field_api_name(field)] = row[field]
    for field in sorted(_TOGGLE_FIELDS):
        deal[_field_api_name(field)] = _api_toggle_value(row[field])
    return deal


def _row_to_deal_event(row: sqlite3.Row) -> dict[str, Any]:
    """Normalize one deal_events row and decode JSON value fields."""
    return {
        "id": row["id"],
        "dealId": row["deal_id"],
        "kind": row["kind"],
        "actor": row["actor"],
        "fromStage": row["from_stage"],
        "toStage": row["to_stage"],
        "fieldName": row["field_name"],
        "oldValue": _decode_json(row["old_value_json"]),
        "newValue": _decode_json(row["new_value_json"]),
        "payload": _decode_json(row["payload_json"]),
        "createdAt": row["created_at"],
    }


def _insert_deal_event(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    kind: str,
    actor: str,
    from_stage: int | None = None,
    to_stage: int | None = None,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    payload: Any = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if kind not in _VALID_EVENT_KINDS:
        raise ValueError(f"invalid deal event kind {kind!r}")
    eid = new_id()
    ts = created_at or now_iso()
    conn.execute(
        """
        INSERT INTO deal_events(
            id, deal_id, kind, actor, from_stage, to_stage, field_name,
            old_value_json, new_value_json, payload_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            eid,
            deal_id,
            kind,
            actor,
            from_stage,
            to_stage,
            field_name,
            _encode_json(old_value),
            _encode_json(new_value),
            _encode_json(payload),
            ts,
        ),
    )
    row = conn.execute("SELECT * FROM deal_events WHERE id=?", (eid,)).fetchone()
    return _row_to_deal_event(row)


def _split_fields(
    fields: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    named: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for field, value in (fields or {}).items():
        if not field or not isinstance(field, str):
            raise ValueError("field names must be non-empty strings")
        if field in _TOGGLE_FIELDS:
            named[field] = _sql_toggle_value(value)
        elif field in _ENUM_FIELDS:
            named[field] = None if value is None else str(value)
        else:
            extra[field] = value
    return named, extra


# --- Reads -------------------------------------------------------------


def get_deal(conn: sqlite3.Connection, deal_id: str) -> dict[str, Any] | None:
    """Return one deal by id, or None when it does not exist."""
    row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    return _row_to_deal(row) if row else None


def list_deals(
    conn: sqlite3.Connection,
    *,
    side: str | None = None,
    current_stage: int | None = None,
    status: str | None = "active",
    primary_contact_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List deals for kanban columns and admin filters."""
    if side is not None and side not in _VALID_SIDES:
        raise ValueError(f"invalid side {side!r}")
    if current_stage is not None:
        current_stage = _validate_stage(current_stage)
    if status is not None and status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    sql = "SELECT * FROM deals WHERE 1=1"
    params: list[Any] = []
    if side is not None:
        sql += " AND side = ?"
        params.append(side)
    if current_stage is not None:
        sql += " AND current_stage = ?"
        params.append(current_stage)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if primary_contact_id is not None:
        sql += " AND primary_contact_id = ?"
        params.append(primary_contact_id)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return [_row_to_deal(r) for r in conn.execute(sql, params).fetchall()]


def list_deal_events(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return the newest stage/toggle events for one deal."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    rows = conn.execute(
        """
        SELECT * FROM deal_events
        WHERE deal_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (deal_id, limit),
    ).fetchall()
    return [_row_to_deal_event(r) for r in rows]


# --- Lifecycle ---------------------------------------------------------


def create_deal(
    conn: sqlite3.Connection,
    *,
    title: str,
    side: str,
    actor: str,
    province: str = "BC",
    current_stage: int = 0,
    primary_contact_id: str | None = None,
    lofty_contact_id: str | None = None,
    listing_address: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a deal, apply initial field values, and append a created event."""
    if not title or not title.strip():
        raise ValueError("title is required")
    if side not in _VALID_SIDES:
        raise ValueError(f"invalid side {side!r}")
    current_stage = _validate_stage(current_stage)
    if primary_contact_id is not None:
        contact = conn.execute(
            "SELECT id FROM contacts WHERE id=?", (primary_contact_id,)
        ).fetchone()
        if contact is None:
            raise LookupError(f"contact {primary_contact_id!r} not found")

    named_fields, extra_fields = _split_fields(fields)
    now = now_iso()
    did = new_id()
    columns = [
        "id",
        "title",
        "side",
        "current_stage",
        "status",
        "province",
        "primary_contact_id",
        "lofty_contact_id",
        "listing_address",
        "extra_toggles_json",
        "created_at",
        "updated_at",
        "stage_entered_at",
    ]
    values: list[Any] = [
        did,
        title.strip(),
        side,
        current_stage,
        "active",
        province,
        primary_contact_id,
        lofty_contact_id,
        listing_address,
        _encode_json(extra_fields) if extra_fields else None,
        now,
        now,
        now,
    ]
    for field, value in named_fields.items():
        columns.append(field)
        values.append(value)
    placeholders = ",".join(["?"] * len(columns))
    conn.execute(
        f"INSERT INTO deals({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    _insert_deal_event(
        conn,
        deal_id=did,
        kind="created",
        actor=actor,
        payload={
            "title": title.strip(),
            "side": side,
            "currentStage": current_stage,
            "province": province,
            "fields": dict(fields or {}),
        },
        created_at=now,
    )
    return get_deal(conn, did)  # type: ignore[return-value]


def move_deal_stage(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    to_stage: int,
    actor: str,
) -> dict[str, Any]:
    """Move a deal to a 0-9 stage and append a stage_transition event."""
    to_stage = _validate_stage(to_stage)
    existing = get_deal(conn, deal_id)
    if existing is None:
        raise LookupError(f"deal {deal_id!r} not found")
    from_stage = existing["currentStage"]
    now = now_iso()
    conn.execute(
        """
        UPDATE deals
        SET current_stage=?, stage_entered_at=?, updated_at=?
        WHERE id=?
        """,
        (to_stage, now, now, deal_id),
    )
    event = _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="stage_transition",
        actor=actor,
        from_stage=from_stage,
        to_stage=to_stage,
        payload={"fromStage": from_stage, "toStage": to_stage},
        created_at=now,
    )
    _dispatch_safely(
        conn,
        deal_id=deal_id,
        deal_event_id=event["id"],
        actor=actor,
        triggers=(
            ("stage_exit", {"from_stage": from_stage}),
            ("stage_entry", {"to_stage": to_stage}),
        ),
    )
    return get_deal(conn, deal_id)  # type: ignore[return-value]


def set_deal_toggle(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    field: str,
    value: Any,
    actor: str,
) -> dict[str, Any]:
    """Update one named toggle or enum field and append a toggle_change event."""
    if not field or not isinstance(field, str):
        raise ValueError("field is required")
    row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if row is None:
        raise LookupError(f"deal {deal_id!r} not found")

    now = now_iso()
    if field in _TOGGLE_FIELDS:
        old_value = _api_toggle_value(row[field])
        stored = _sql_toggle_value(value)
        new_value = _api_toggle_value(stored)
        conn.execute(
            f"UPDATE deals SET {field}=?, updated_at=? WHERE id=?",
            (stored, now, deal_id),
        )
    elif field in _ENUM_FIELDS:
        old_value = row[field]
        new_value = None if value is None else str(value)
        conn.execute(
            f"UPDATE deals SET {field}=?, updated_at=? WHERE id=?",
            (new_value, now, deal_id),
        )
    else:
        extra = _decode_json(row["extra_toggles_json"]) or {}
        if not isinstance(extra, dict):
            extra = {}
        old_value = extra.get(field)
        extra[field] = value
        new_value = value
        conn.execute(
            """
            UPDATE deals
            SET extra_toggles_json=?, updated_at=?
            WHERE id=?
            """,
            (_encode_json(extra), now, deal_id),
        )

    event = _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="toggle_change",
        actor=actor,
        field_name=field,
        old_value=old_value,
        new_value=new_value,
        created_at=now,
    )
    _dispatch_safely(
        conn,
        deal_id=deal_id,
        deal_event_id=event["id"],
        actor=actor,
        triggers=(
            (
                "toggle_change",
                {"field_key": field, "field_old": old_value, "field_new": new_value},
            ),
        ),
    )
    return get_deal(conn, deal_id)  # type: ignore[return-value]


def _dispatch_safely(
    conn: sqlite3.Connection,
    *,
    deal_id: str,
    deal_event_id: str,
    actor: str,
    triggers: "tuple[tuple[str, dict[str, Any]], ...]",
) -> None:
    """Best-effort hook into the action dispatcher.

    A failure inside :func:`elevate_cli.data.dispatch.evaluate` must never
    fail the deal mutation that produced the event — the deal state is the
    source of truth, dispatch is downstream wiring. Errors are swallowed
    here so the caller commits the deal change cleanly. The dispatcher's
    own tests cover its happy path; a real failure shows up as a missing
    ``admin_action_runs`` row, which the worker can rebuild from the
    ``deal_events`` log if needed.
    """
    try:
        from elevate_cli.data.dispatch import evaluate as _evaluate
    except Exception:  # pragma: no cover — import errors should be loud, but never fatal
        return
    for trigger, kwargs in triggers:
        try:
            _evaluate(
                conn,
                deal_id=deal_id,
                deal_event_id=deal_event_id,
                trigger=trigger,
                actor=actor,
                **kwargs,
            )
        except Exception:
            continue
