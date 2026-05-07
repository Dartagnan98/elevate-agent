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
from typing import Any, Mapping, Sequence

from elevate_cli.data._util import new_id, now_iso


_VALID_SIDES = {"listing", "buyer"}
_VALID_STATUSES = {"active", "closed", "archived"}
_VALID_EVENT_KINDS = {"created", "stage_transition", "toggle_change", "run_result", "attachment_added", "contact_linked"}

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
        "board": row["board"],
        "market": row["market"],
        "primaryContactId": row["primary_contact_id"],
        "loftyContactId": row["lofty_contact_id"],
        "listingAddress": row["listing_address"],
        "extraToggles": _decode_json(row["extra_toggles_json"]) or {},
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "stageEnteredAt": row["stage_entered_at"],
        "closedAt": row["closed_at"],
        "listingDate": row["listing_date"],
        "offerDate": row["offer_date"],
        "subjectRemovalDate": row["subject_removal_date"],
        "depositDueDate": row["deposit_due_date"],
        "completionDate": row["completion_date"],
        "possessionDate": row["possession_date"],
        "anniversaryDate": row["anniversary_date"],
        "listPrice": row["list_price"],
        "offerPrice": row["offer_price"],
        "depositAmount": row["deposit_amount"],
        "commissionPct": row["commission_pct"],
        "mlsNumber": row["mls_number"],
        "legalDescription": row["legal_description"],
        "lotSizeSqft": row["lot_size_sqft"],
        "yearBuilt": row["year_built"],
        "depositInTrustAt": row["deposit_in_trust_at"],
        "listingPublishedAt": row["listing_published_at"],
        "offerAcceptedAt": row["offer_accepted_at"],
        "subjectsRemovedAt": row["subjects_removed_at"],
        "completedAt": row["completed_at"],
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
    province: str | None = None,
    board: str | None = None,
    market: str | None = None,
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
    if province is not None:
        sql += " AND province = ?"
        params.append(province)
    if board is not None:
        sql += " AND board = ?"
        params.append(board)
    if market is not None:
        sql += " AND market = ?"
        params.append(market)
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
    province: str = "",
    board: str | None = None,
    market: str | None = None,
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
        "board",
        "market",
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
        board,
        market,
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
                create_cron_jobs=True,
                **kwargs,
            )
        except Exception:
            continue


_DATE_FIELDS = {
    "listing_date", "offer_date", "subject_removal_date", "deposit_due_date",
    "completion_date", "possession_date", "anniversary_date",
}
_MONEY_FIELDS = {"list_price", "offer_price", "deposit_amount", "commission_pct"}
_PROPERTY_FIELDS = {"mls_number", "legal_description", "lot_size_sqft", "year_built"}
_STATUS_TS_FIELDS = {
    "deposit_in_trust_at", "listing_published_at", "offer_accepted_at",
    "subjects_removed_at", "completed_at",
}
_DEAL_DETAIL_FIELDS = _DATE_FIELDS | _MONEY_FIELDS | _PROPERTY_FIELDS | _STATUS_TS_FIELDS
_API_TO_DB_DETAIL_FIELDS = {
    "listingDate": "listing_date",
    "offerDate": "offer_date",
    "subjectRemovalDate": "subject_removal_date",
    "depositDueDate": "deposit_due_date",
    "completionDate": "completion_date",
    "possessionDate": "possession_date",
    "anniversaryDate": "anniversary_date",
    "listPrice": "list_price",
    "offerPrice": "offer_price",
    "depositAmount": "deposit_amount",
    "commissionPct": "commission_pct",
    "mlsNumber": "mls_number",
    "legalDescription": "legal_description",
    "lotSizeSqft": "lot_size_sqft",
    "yearBuilt": "year_built",
    "depositInTrustAt": "deposit_in_trust_at",
    "listingPublishedAt": "listing_published_at",
    "offerAcceptedAt": "offer_accepted_at",
    "subjectsRemovedAt": "subjects_removed_at",
    "completedAt": "completed_at",
}


def _contact_row_to_api(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        from elevate_cli.data.contacts import _row_to_contact
        return _row_to_contact(row)
    except Exception:
        return dict(row)


def _row_to_deal_contact(row: sqlite3.Row) -> dict[str, Any]:
    contact = _contact_row_to_api(row) if "display_name" in row.keys() else None
    return {
        "id": row["id"],
        "dealId": row["deal_id"],
        "role": row["role"],
        "contactId": row["contact_id"],
        "notes": row["notes"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "contact": contact,
    }


def _row_to_deal_attachment(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "dealId": row["deal_id"],
        "kind": row["kind"],
        "filePath": row["file_path"],
        "summary": row["summary"],
        "sourceRunId": row["source_run_id"],
        "sourceSnapshotId": row["source_snapshot_id"],
        "createdAt": row["created_at"],
    }


def _normalize_detail_field(field: str) -> str:
    field = _API_TO_DB_DETAIL_FIELDS.get(field, field)
    if field not in _DEAL_DETAIL_FIELDS:
        raise ValueError(f"unsupported deal detail field {field!r}")
    return field


def set_deal_fields(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    actor: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Set source-of-truth deal detail fields (dates, money, property, timestamps)."""
    if not fields:
        existing = get_deal(conn, deal_id)
        if existing is None:
            raise LookupError(f"deal {deal_id!r} not found")
        return existing
    row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if row is None:
        raise LookupError(f"deal {deal_id!r} not found")
    updates: dict[str, Any] = {}
    old_values: dict[str, Any] = {}
    for raw_field, value in fields.items():
        field = _normalize_detail_field(raw_field)
        old_values[field] = row[field]
        if field in _MONEY_FIELDS or field == "lot_size_sqft":
            updates[field] = None if value is None or value == "" else float(value)
        elif field == "year_built":
            updates[field] = None if value is None or value == "" else int(value)
        else:
            updates[field] = None if value is None else str(value)
    now = now_iso()
    sets = ", ".join([f"{field}=?" for field in updates] + ["updated_at=?"])
    conn.execute(
        f"UPDATE deals SET {sets} WHERE id=?",
        [*updates.values(), now, deal_id],
    )
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="toggle_change",
        actor=actor,
        field_name="deal_fields",
        old_value=old_values,
        new_value=updates,
        payload={"fields": updates},
        created_at=now,
    )
    return get_deal(conn, deal_id)  # type: ignore[return-value]


def set_deal_dates(conn: sqlite3.Connection, deal_id: str, *, actor: str, **dates: Any) -> dict[str, Any]:
    return set_deal_fields(conn, deal_id, actor=actor, fields=dates)


def set_deal_money(conn: sqlite3.Connection, deal_id: str, *, actor: str, **fields: Any) -> dict[str, Any]:
    return set_deal_fields(conn, deal_id, actor=actor, fields=fields)


def add_deal_contact(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    role: str,
    contact_id: str,
    notes: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    if get_deal(conn, deal_id) is None:
        raise LookupError(f"deal {deal_id!r} not found")
    if not role or not role.strip():
        raise ValueError("role is required")
    if conn.execute("SELECT id FROM contacts WHERE id=?", (contact_id,)).fetchone() is None:
        raise LookupError(f"contact {contact_id!r} not found")
    now = now_iso()
    cid = new_id()
    conn.execute(
        """
        INSERT INTO deal_contacts(id, deal_id, role, contact_id, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(deal_id, role, contact_id) DO UPDATE SET
            notes=excluded.notes,
            updated_at=excluded.updated_at
        """,
        (cid, deal_id, role.strip(), contact_id, notes, now, now),
    )
    row = conn.execute(
        "SELECT * FROM deal_contacts WHERE deal_id=? AND role=? AND contact_id=?",
        (deal_id, role.strip(), contact_id),
    ).fetchone()
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="contact_linked",
        actor=actor,
        payload={"role": role.strip(), "contactId": contact_id, "notes": notes},
        created_at=now,
    )
    return _row_to_deal_contact(row)


def list_deal_contacts(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    role: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT dc.*, c.*
        FROM deal_contacts dc
        JOIN contacts c ON c.id = dc.contact_id
        WHERE dc.deal_id=?
    """
    params: list[Any] = [deal_id]
    if role is not None:
        sql += " AND dc.role=?"
        params.append(role)
    sql += " ORDER BY dc.role ASC, dc.updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "id": row["id"],
            "dealId": row["deal_id"],
            "role": row["role"],
            "contactId": row["contact_id"],
            "notes": row["notes"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        contact_row = conn.execute("SELECT * FROM contacts WHERE id=?", (row["contact_id"],)).fetchone()
        item["contact"] = _contact_row_to_api(contact_row)
        out.append(item)
    return out


def add_deal_attachment(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    kind: str,
    file_path: str,
    summary: str | None = None,
    source_run_id: str | None = None,
    source_snapshot_id: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    if get_deal(conn, deal_id) is None:
        raise LookupError(f"deal {deal_id!r} not found")
    if not kind or not kind.strip():
        raise ValueError("attachment kind is required")
    if not file_path or not file_path.strip():
        raise ValueError("file_path is required")
    aid = new_id()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO deal_attachments(
            id, deal_id, kind, file_path, summary,
            source_run_id, source_snapshot_id, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (aid, deal_id, kind.strip(), file_path.strip(), summary, source_run_id, source_snapshot_id, now),
    )
    row = conn.execute("SELECT * FROM deal_attachments WHERE id=?", (aid,)).fetchone()
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="attachment_added",
        actor=actor,
        payload={"kind": kind.strip(), "filePath": file_path.strip(), "sourceRunId": source_run_id},
        created_at=now,
    )
    return _row_to_deal_attachment(row)


def list_deal_attachments(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    kind: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    sql = "SELECT * FROM deal_attachments WHERE deal_id=?"
    params: list[Any] = [deal_id]
    if kind is not None:
        sql += " AND kind=?"
        params.append(kind)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_deal_attachment(row) for row in conn.execute(sql, params).fetchall()]


def _row_to_action_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "registryId": row["registry_id"],
        "dealId": row["deal_id"],
        "dealEventId": row["deal_event_id"],
        "cronJobId": row["cron_job_id"],
        "harnessRunId": row["harness_run_id"],
        "status": row["status"],
        "outputPath": row["output_path"],
        "errorMessage": row["error_message"],
        "payload": _decode_json(row["payload_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
        "skill": row["skill"] if "skill" in row.keys() else None,
        "registryName": row["name"] if "name" in row.keys() else None,
    }


def list_deal_action_runs(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.*, a.skill, a.name
        FROM admin_action_runs r
        LEFT JOIN admin_action_registry a ON a.id = r.registry_id
        WHERE r.deal_id=?
        ORDER BY r.created_at DESC
        LIMIT ?
        """,
        (deal_id, limit),
    ).fetchall()
    return [_row_to_action_run(row) for row in rows]


def get_deal_context(conn: sqlite3.Connection, deal_id: str) -> dict[str, Any]:
    deal = get_deal(conn, deal_id)
    if deal is None:
        raise LookupError(f"deal {deal_id!r} not found")
    primary = None
    if deal.get("primaryContactId"):
        primary = _contact_row_to_api(
            conn.execute("SELECT * FROM contacts WHERE id=?", (deal["primaryContactId"],)).fetchone()
        )
    conditions = {field: deal.get(_field_api_name(field)) for field in sorted(_NAMED_FIELDS)}
    checklist = deal.get("extraToggles") or {}
    attachments = list_deal_attachments(conn, deal_id)
    prior_runs = list_deal_action_runs(conn, deal_id)
    from elevate_cli.admin_deal_flow import resolve_deal_phase

    deal_flow = resolve_deal_phase(
        deal=deal,
        checklist=checklist,
        attachments=attachments,
        prior_runs=prior_runs,
        conditions=conditions,
    )
    return {
        "deal": deal,
        "primaryContact": primary,
        "coContacts": list_deal_contacts(conn, deal_id),
        "conditions": conditions,
        "checklist": checklist,
        "attachments": attachments,
        "priorRuns": prior_runs,
        "dealFlow": deal_flow,
        "events": list_deal_events(conn, deal_id, limit=50),
    }


_OPEN_TASK_RUN_STATUSES = {"queued", "running", "waiting_human", "waiting_external", "failed"}
_DONE_TASK_RUN_STATUSES = {"succeeded", "completed", "cancelled", "skipped"}


def _deal_task_common(
    deal: Mapping[str, Any],
    flow: Mapping[str, Any],
    *,
    task_id: str,
    task_type: str,
    source: str,
    title: str,
    status: str,
    description: str | None = None,
    skill: str | None = None,
    can_run_with_ai: bool = False,
    run_id: str | None = None,
    field: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "type": task_type,
        "source": source,
        "title": title,
        "description": description,
        "status": status,
        "dealId": deal.get("id"),
        "dealTitle": deal.get("title"),
        "side": deal.get("side"),
        "currentStage": deal.get("currentStage"),
        "stageName": flow.get("stageName"),
        "packageKey": flow.get("packageKey"),
        "skill": skill,
        "canRunWithAi": bool(can_run_with_ai),
        "runId": run_id,
        "field": field,
        "kind": kind,
        "createdAt": deal.get("createdAt"),
        "updatedAt": deal.get("updatedAt"),
    }


def list_deal_tasks(
    conn: sqlite3.Connection,
    *,
    status: str = "open",
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return task-board rows derived from active Admin deal phase gates.

    The deal file remains the source of truth.  This function projects current
    phase work, missing docs/fields, and AI-capable action triggers into a
    task-list shape for the `/tasks` page.
    """
    if status not in {"open", "done", "all"}:
        raise ValueError("status must be one of: open, done, all")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    tasks: list[dict[str, Any]] = []
    for deal in list_deals(conn, status="active", limit=max(200, limit + offset), offset=0):
        context = get_deal_context(conn, str(deal["id"]))
        flow = context.get("dealFlow") or {}
        gate = flow.get("gate") or {}
        active_run_skills: set[str] = set()

        for run in context.get("priorRuns") or []:
            run_status = str(run.get("status") or "queued")
            if status == "open" and run_status in _DONE_TASK_RUN_STATUSES:
                continue
            if status == "done" and run_status not in _DONE_TASK_RUN_STATUSES:
                continue
            payload = run.get("payload") if isinstance(run.get("payload"), Mapping) else {}
            title = (
                run.get("registryName")
                or payload.get("registryName")
                or run.get("skill")
                or "Admin action"
            )
            skill = run.get("skill")
            if run_status in _OPEN_TASK_RUN_STATUSES and skill:
                active_run_skills.add(str(skill))
            tasks.append(
                _deal_task_common(
                    deal,
                    flow,
                    task_id=f"run:{run.get('id')}",
                    task_type="action_run",
                    source="admin_action_run",
                    title=str(title),
                    description=str(payload.get("trigger") or "Skill run") if payload else "Skill run",
                    status=run_status,
                    skill=str(skill) if skill else None,
                    can_run_with_ai=bool(skill),
                    run_id=str(run.get("id")),
                )
            )

        if status == "done":
            continue

        for trigger in flow.get("automationTriggers") or []:
            skill = str(trigger.get("skill") or "").strip()
            if skill and skill in active_run_skills:
                continue
            trigger_id = str(trigger.get("id") or skill or trigger.get("label") or "ai-action")
            tasks.append(
                _deal_task_common(
                    deal,
                    flow,
                    task_id=f"ai:{deal['id']}:{gate.get('stage')}:{trigger_id}",
                    task_type="ai_action",
                    source="phase_trigger",
                    title=str(trigger.get("label") or "Run AI action"),
                    description="Available from this deal phase",
                    status="available",
                    skill=skill or None,
                    can_run_with_ai=True,
                )
            )

        for item in gate.get("missingChecklist") or []:
            item_id = str(item.get("id") or item.get("label") or "checklist")
            tasks.append(
                _deal_task_common(
                    deal,
                    flow,
                    task_id=f"checklist:{deal['id']}:{gate.get('stage')}:{item_id}",
                    task_type="checklist",
                    source="phase_gate",
                    title=str(item.get("label") or item_id),
                    description="Required before this deal can advance",
                    status="open",
                )
            )

        for item in gate.get("missingFields") or []:
            field = str(item.get("field") or "")
            tasks.append(
                _deal_task_common(
                    deal,
                    flow,
                    task_id=f"field:{deal['id']}:{field}",
                    task_type="field",
                    source="phase_gate",
                    title=f"Update {item.get('label') or field}",
                    description="Missing source-of-truth field",
                    status="open",
                    field=field or None,
                )
            )

        for item in gate.get("missingDocs") or []:
            kind = str(item.get("kind") or "")
            tasks.append(
                _deal_task_common(
                    deal,
                    flow,
                    task_id=f"doc:{deal['id']}:{kind}",
                    task_type="document",
                    source="phase_gate",
                    title=f"Attach {item.get('label') or kind}",
                    description="Missing source-of-truth document",
                    status="open",
                    kind=kind or None,
                )
            )

    status_rank = {
        "waiting_human": 0,
        "failed": 1,
        "running": 2,
        "queued": 3,
        "available": 4,
        "open": 5,
        "waiting_external": 6,
        "succeeded": 8,
        "completed": 8,
        "cancelled": 9,
        "skipped": 9,
    }
    tasks.sort(
        key=lambda item: (
            status_rank.get(str(item.get("status")), 7),
            str(item.get("side") or ""),
            int(item.get("currentStage") or 0),
            str(item.get("dealTitle") or ""),
            str(item.get("title") or ""),
        )
    )
    return tasks[offset: offset + limit]


_ARTIFACT_CHECKLIST_HINTS = {
    "cma_report": "draft-cma-followup",
    "title_search": "pull-title",
    "title_pdf": "pull-title",
    "mlc_pdf": "fill-mlc",
    "mlc_form": "fill-mlc",
    "listing_agreement_pdf": "fill-listing-forms",
    "listing_forms": "fill-listing-forms",
    "signed_envelope": "track-signatures",
    "signed_docs": "track-signatures",
    "listing_photos": "organize-photos",
    "feature_sheet": "feature-sheet",
    "showing_digest": "showing-digest",
    "showingtime_digest": "showingtime-digest",
    "offer_pdf": "offer-summary",
    "offer_summary": "offer-summary",
    "deposit_receipt": "deposit-confirmed",
    "inspection_report": "inspection-timing",
    "strata_docs": "strata-docs-review",
}


def _explicit_checklist_updates(items: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None) -> dict[str, bool]:
    if not items:
        return {}
    if isinstance(items, Mapping):
        return {str(k): bool(v) for k, v in items.items()}
    updates: dict[str, bool] = {}
    for item in items:
        key = item.get("id") or item.get("itemId") or item.get("field")
        if key:
            updates[str(key)] = bool(item.get("completed", True))
    return updates


def record_run_result(
    conn: sqlite3.Connection,
    deal_id: str,
    run_id: str,
    *,
    status: str,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
    next_tasks: Sequence[Mapping[str, Any]] | None = None,
    checklist_updates: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    human_prompt: Mapping[str, Any] | None = None,
    error: str | None = None,
    actor: str = "skill",
) -> dict[str, Any]:
    if get_deal(conn, deal_id) is None:
        raise LookupError(f"deal {deal_id!r} not found")
    row = conn.execute(
        "SELECT * FROM admin_action_runs WHERE id=? AND deal_id=?",
        (run_id, deal_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"action run {run_id!r} not found for deal {deal_id!r}")
    normalized_status = "succeeded" if status == "completed" else status
    allowed = {"queued", "running", "succeeded", "completed", "failed", "skipped", "cancelled", "waiting_human", "waiting_external"}
    if normalized_status not in allowed:
        raise ValueError(f"invalid run status {status!r}")
    now = now_iso()
    completed_at = now if normalized_status in {"succeeded", "completed", "failed", "skipped", "cancelled"} else None
    payload = _decode_json(row["payload_json"]) or {}
    if not isinstance(payload, dict):
        payload = {"prior": payload}
    payload["result"] = {
        "status": status,
        "artifacts": [dict(item) for item in (artifacts or [])],
        "nextTasks": [dict(item) for item in (next_tasks or [])],
        "checklistUpdates": checklist_updates,
        "humanPrompt": dict(human_prompt) if human_prompt else None,
        "error": error,
        "recordedAt": now,
    }
    output_path = row["output_path"]
    for artifact in artifacts or []:
        attachment = add_deal_attachment(
            conn,
            deal_id,
            kind=str(artifact.get("kind") or "artifact"),
            file_path=str(artifact.get("file_path") or artifact.get("filePath") or ""),
            summary=artifact.get("summary"),
            source_run_id=run_id,
            source_snapshot_id=artifact.get("source_snapshot_id") or artifact.get("sourceSnapshotId"),
            actor=actor,
        )
        if output_path is None:
            output_path = attachment["filePath"]
    if normalized_status in {"succeeded", "completed"}:
        updates = _explicit_checklist_updates(checklist_updates)
        for artifact in artifacts or []:
            hinted = _ARTIFACT_CHECKLIST_HINTS.get(str(artifact.get("kind") or ""))
            if hinted:
                updates.setdefault(hinted, True)
        for field, value in updates.items():
            set_deal_toggle(conn, deal_id, field=field, value=value, actor=actor)
        if next_tasks:
            from elevate_cli.data.dispatch import queue_action_run

            for task in next_tasks:
                skill = task.get("skill")
                if not skill:
                    continue
                task_payload = {
                    "sourceRunId": run_id,
                    "nextTask": dict(task),
                }
                queue_action_run(
                    conn,
                    deal_id=deal_id,
                    skill=str(skill),
                    name=str(task.get("name") or f"Next task: {skill}"),
                    payload=task_payload,
                    create_cron_job=bool(task.get("runNow") or task.get("run_now")),
                    actor=actor,
                )
    conn.execute(
        """
        UPDATE admin_action_runs
        SET status=?, output_path=?, error_message=?, payload_json=?, updated_at=?, completed_at=?
        WHERE id=?
        """,
        (normalized_status, output_path, error, _encode_json(payload), now, completed_at, run_id),
    )
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="run_result",
        actor=actor,
        payload={"runId": run_id, "status": normalized_status, "humanPrompt": human_prompt, "error": error},
        created_at=now,
    )
    updated = conn.execute("SELECT * FROM admin_action_runs WHERE id=?", (run_id,)).fetchone()
    return _row_to_action_run(updated)
