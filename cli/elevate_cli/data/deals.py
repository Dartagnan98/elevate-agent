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
import re
import sqlite3
from typing import Any, Mapping, Sequence

from elevate_cli.data._util import new_id, now_iso


_VALID_SIDES = {"listing", "buyer"}
_VALID_STATUSES = {"active", "closed", "archived"}
_VALID_EVENT_KINDS = {"created", "stage_transition", "toggle_change", "run_result", "attachment_added", "contact_linked", "agent_activity"}

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
_WORKFLOW_STAGE_COMPLETE_RE = re.compile(r"^workflow_stage_(\d+)_complete$")
# Checklist-driven auto-advance, keyed by the completed stage. Stage 5 (Listing
# Live) is intentionally absent: a live listing only moves to Accepted Offer (6)
# on the accepted-offer signal, never just because its marketing tasks are done.
# Stage 8 (Closed) is terminal.
_WORKFLOW_STAGE_COMPLETE_ADVANCES_TO = {
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    6: 7,
    7: 8,
}
_WORKFLOW_ACCEPTED_OFFER_FIELDS = {"workflow_accepted_offer_date"}
# Stages whose resolved phase gate may auto-advance the deal when clear. 5 is
# excluded (offer-driven, handled by _advance_on_accepted_offer); 8 is terminal.
_AUTO_ADVANCE_GATE_STAGES = {0, 1, 2, 3, 4, 6, 7}
_CHECKLIST_TRUE_VALUES = {"1", "true", "yes", "y", "checked", "done", "complete", "completed"}
_CHECKLIST_FALSE_VALUES = {"0", "false", "no", "n", "unchecked", "todo", "incomplete", "not done", ""}


class DealPhaseGateBlocked(ValueError):
    """Raised when a stage move would bypass the source-of-truth phase gate."""

    def __init__(self, message: str, *, gate: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.gate = dict(gate or {})


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
        raise ValueError("stage must be an integer between 0 and 10")
    stage_int = int(stage)
    if stage_int < 0 or stage_int > 10:
        raise ValueError("stage must be an integer between 0 and 10")
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
    row_keys = set(row.keys())

    def row_value(key: str) -> Any:
        return row[key] if key in row_keys else None

    deal = {
        "id": row["id"],
        "title": row["title"],
        "side": row["side"],
        "currentStage": row["current_stage"],
        "status": row["status"],
        "province": row["province"],
        "board": row["board"],
        "market": row["market"],
        "sourceKey": row["source_key"],
        "sourceRowId": row["source_row_id"],
        "sourceLabel": row["source_label"],
        "sourceSyncedAt": row["source_synced_at"],
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
        # Deal-sheet / CRM revenue fields.  These are especially important for
        # referral files where there may be no MLS sale package, but Admin still
        # needs to show what was paid out.
        "homePrice": row_value("home_price"),
        "gci": row_value("gci"),
        "teamRevenue": row_value("team_revenue"),
        "agentRevenue": row_value("agent_revenue"),
        "expectedCloseDate": row_value("expected_close_date"),
        "crmTransactionStatus": row_value("crm_transaction_status"),
        "crmTransactionType": row_value("crm_transaction_type"),
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
        normalized_field = _API_TO_DB_DETAIL_FIELDS.get(field, field)
        if normalized_field in _TOGGLE_FIELDS:
            named[normalized_field] = _sql_toggle_value(value)
        elif normalized_field in _ENUM_FIELDS:
            named[normalized_field] = None if value is None else str(value)
        elif normalized_field in _DEAL_DETAIL_FIELDS:
            named[normalized_field] = _coerce_detail_value(normalized_field, value)
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


# --- Pipeline snapshot ------------------------------------------------
#
# One-call answer to "what's currently active in my pipeline and what
# needs my attention." Saves the agent from chaining list_deals → N×
# get_deal → elevate_db count queries when the user just wants a
# briefing. Aggregates in Python because the active deal count is
# always small (~10-50); a SQL GROUP BY would be premature optimization
# and would force separate queries for each grouping anyway.

_MOCK_SOURCE_TOKENS = ("mock", "beta", "dry-run", "dry_run", "dryrun", "test_")


def _looks_like_mock_source(label: str | None, key: str | None) -> bool:
    blob = f"{label or ''} {key or ''}".lower()
    return any(tok in blob for tok in _MOCK_SOURCE_TOKENS)


def _iso_to_date_naive(value: str | None) -> str | None:
    """Slice an ISO timestamp to YYYY-MM-DD without touching tz logic."""
    if not value:
        return None
    s = str(value).strip()
    return s[:10] if len(s) >= 10 else None


def _days_between(today_iso: str, target_iso: str | None) -> int | None:
    """Whole days from today to target (positive = future). None if unparseable."""
    if not target_iso:
        return None
    from datetime import date
    try:
        t = date.fromisoformat(today_iso[:10])
        tgt = date.fromisoformat(str(target_iso)[:10])
    except ValueError:
        return None
    return (tgt - t).days


def deals_overview(
    conn: sqlite3.Connection,
    *,
    status: str | None = "active",
    side: str | None = None,
    exclude_mock: bool = True,
    near_close_days: int = 30,
    near_subject_days: int = 21,
    stale_days: int = 14,
    today: str | None = None,
) -> dict[str, Any]:
    """Whole-pipeline snapshot in one call.

    Returns a structured dict the agent can read once to answer
    "where are my deals and what needs attention" without N round-trips.

    Aggregates and lists:
      * ``totals``: counts by status, side, source-mock filtering applied
      * ``byStage``: dict of stage→count (0-10)
      * ``bySource``: dict of source_label → count
      * ``mockDeals``: thin list of any source-tagged mock/beta entries
        (always returned so the agent knows what was filtered out)
      * ``closingsSoon``: deals with completion_date inside ``near_close_days``
      * ``subjectsSoon``: deals with subject_removal_date inside ``near_subject_days``
      * ``staleStages``: deals whose stage_entered_at is older than
        ``stale_days`` and aren't in a terminal stage
      * ``deals``: thin scan-friendly list of every active deal
        (id, title, side, currentStage, stageEnteredAt, completionDate,
        subjectRemovalDate, listingDate, listPrice, sourceLabel,
        primaryContactId) — sorted by stage then completion date

    Pass ``status=None`` to include all statuses. Pass ``exclude_mock=False``
    to keep mock/beta source entries in the aggregates.
    """
    if status is not None and status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    if side is not None and side not in _VALID_SIDES:
        raise ValueError(f"invalid side {side!r}")

    sql = "SELECT * FROM deals WHERE 1=1"
    params: list[Any] = []
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if side is not None:
        sql += " AND side = ?"
        params.append(side)
    sql += " ORDER BY current_stage ASC, completion_date ASC NULLS LAST, updated_at DESC"

    rows = conn.execute(sql, params).fetchall()
    all_deals = [_row_to_deal(r) for r in rows]

    today_iso = today or now_iso()[:10]

    mock_deals: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for d in all_deals:
        if exclude_mock and _looks_like_mock_source(
            d.get("sourceLabel"), d.get("sourceKey")
        ):
            mock_deals.append({
                "id": d["id"],
                "title": d.get("title"),
                "sourceLabel": d.get("sourceLabel"),
                "sourceKey": d.get("sourceKey"),
            })
        else:
            kept.append(d)

    by_stage: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_side: dict[str, int] = {}

    closings_soon: list[dict[str, Any]] = []
    subjects_soon: list[dict[str, Any]] = []
    stale_stages: list[dict[str, Any]] = []
    thin_list: list[dict[str, Any]] = []

    _TERMINAL_STAGES = {10}

    for d in kept:
        stage = d.get("currentStage")
        if stage is not None:
            by_stage[str(stage)] = by_stage.get(str(stage), 0) + 1
        src = d.get("sourceLabel") or d.get("sourceKey") or "unknown"
        by_source[str(src)] = by_source.get(str(src), 0) + 1
        st = str(d.get("status") or "")
        by_status[st] = by_status.get(st, 0) + 1
        sd = str(d.get("side") or "")
        by_side[sd] = by_side.get(sd, 0) + 1

        completion = _iso_to_date_naive(d.get("completionDate"))
        subject = _iso_to_date_naive(d.get("subjectRemovalDate"))
        stage_at = _iso_to_date_naive(d.get("stageEnteredAt"))

        days_to_close = _days_between(today_iso, completion)
        if days_to_close is not None and -7 <= days_to_close <= near_close_days:
            closings_soon.append({
                "id": d["id"],
                "title": d.get("title"),
                "currentStage": stage,
                "completionDate": completion,
                "daysToClose": days_to_close,
                "listPrice": d.get("listPrice"),
                "offerPrice": d.get("offerPrice"),
            })

        days_to_subject = _days_between(today_iso, subject)
        if days_to_subject is not None and -3 <= days_to_subject <= near_subject_days:
            subjects_soon.append({
                "id": d["id"],
                "title": d.get("title"),
                "currentStage": stage,
                "subjectRemovalDate": subject,
                "daysToSubject": days_to_subject,
            })

        days_in_stage = _days_between(stage_at, today_iso) if stage_at else None
        if (
            days_in_stage is not None
            and days_in_stage >= stale_days
            and stage not in _TERMINAL_STAGES
        ):
            stale_stages.append({
                "id": d["id"],
                "title": d.get("title"),
                "currentStage": stage,
                "stageEnteredAt": stage_at,
                "daysInStage": days_in_stage,
            })

        thin_list.append({
            "id": d["id"],
            "title": d.get("title"),
            "side": d.get("side"),
            "currentStage": stage,
            "stageEnteredAt": stage_at,
            "completionDate": completion,
            "subjectRemovalDate": subject,
            "listingDate": _iso_to_date_naive(d.get("listingDate")),
            "listPrice": d.get("listPrice"),
            "offerPrice": d.get("offerPrice"),
            "sourceLabel": d.get("sourceLabel"),
            "sourceKey": d.get("sourceKey"),
            "primaryContactId": d.get("primaryContactId"),
            "mlsNumber": d.get("mlsNumber"),
        })

    closings_soon.sort(key=lambda x: (x.get("daysToClose") is None, x.get("daysToClose")))
    subjects_soon.sort(key=lambda x: (x.get("daysToSubject") is None, x.get("daysToSubject")))
    stale_stages.sort(key=lambda x: -(x.get("daysInStage") or 0))

    return {
        "generatedAt": now_iso(),
        "today": today_iso,
        "filters": {
            "status": status,
            "side": side,
            "excludeMock": exclude_mock,
            "nearCloseDays": near_close_days,
            "nearSubjectDays": near_subject_days,
            "staleDays": stale_days,
        },
        "totals": {
            "activeAfterFilter": len(kept),
            "mockExcluded": len(mock_deals),
            "rawMatched": len(all_deals),
            "byStatus": by_status,
            "bySide": by_side,
        },
        "byStage": by_stage,
        "bySource": by_source,
        "mockDeals": mock_deals,
        "closingsSoon": closings_soon,
        "subjectsSoon": subjects_soon,
        "staleStages": stale_stages,
        "deals": thin_list,
    }


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
    source_key: str | None = None,
    source_row_id: str | None = None,
    source_label: str | None = None,
    source_synced_at: str | None = None,
    fields: Mapping[str, Any] | None = None,
    dispatch_initial_stage: bool = True,
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
        "source_key",
        "source_row_id",
        "source_label",
        "source_synced_at",
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
        source_key,
        source_row_id,
        source_label,
        source_synced_at,
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
    event = _insert_deal_event(
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
    if dispatch_initial_stage:
        _dispatch_safely(
            conn,
            deal_id=did,
            deal_event_id=event["id"],
            actor=actor,
            triggers=(("stage_entry", {"to_stage": current_stage}),),
        )
    return get_deal(conn, did)  # type: ignore[return-value]


def _compact_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_strings(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = _compact_string(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _profile_context_list(context: Mapping[str, Any], key: str) -> list[str]:
    value = context.get(key)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _unique_strings(value)
    return []


def _sequence_or_empty(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []


def _canonical_phone_key(value: Any) -> str | None:
    text = _compact_string(value)
    if not text:
        return None
    digits = re.sub(r"\D+", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) < 7:
        return None
    return f"phone:{digits}"


def _canonical_email_key(value: Any) -> str | None:
    text = _compact_string(value)
    if not text or "@" not in text:
        return None
    return f"email:{text.lower()}"


def _canonical_profile_verifier_keys(
    *,
    verifiers: Sequence[Mapping[str, Any]] | None = None,
    phones: Sequence[Any] | None = None,
    emails: Sequence[Any] | None = None,
) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: str | None) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    for verifier in verifiers or []:
        if not isinstance(verifier, Mapping):
            continue
        kind = str(verifier.get("kind") or verifier.get("type") or "").strip().lower()
        value = verifier.get("value")
        raw_key = _compact_string(verifier.get("key"))
        if kind == "email" or (raw_key or "").startswith("email:"):
            add(_canonical_email_key(value) or (raw_key.lower() if raw_key else None))
        elif kind in {"phone", "tel", "telephone", "sms"} or (raw_key or "").startswith("phone:"):
            add(_canonical_phone_key(value) or (raw_key.lower() if raw_key else None))
    for phone in phones or []:
        add(_canonical_phone_key(phone))
    for email in emails or []:
        add(_canonical_email_key(email))
    return keys


def _sanitize_profile_verifiers(verifiers: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for verifier in verifiers or []:
        if not isinstance(verifier, Mapping):
            continue
        kind = _compact_string(verifier.get("kind") or verifier.get("type"))
        value = _compact_string(verifier.get("value"))
        key = _compact_string(verifier.get("key"))
        if not kind or not value:
            continue
        out.append({"kind": kind, "value": value, "key": key or f"{kind}:{value}"})
    return out


def _existing_contact_id(conn: sqlite3.Connection, contact_id: str | None) -> str | None:
    contact_id = _compact_string(contact_id)
    if not contact_id:
        return None
    row = conn.execute("SELECT id FROM contacts WHERE id=?", (contact_id,)).fetchone()
    return contact_id if row else None


def _profile_deal_match_keys(deal: Mapping[str, Any]) -> set[str]:
    extra = deal.get("extraToggles") if isinstance(deal.get("extraToggles"), Mapping) else {}
    keys: set[str] = set()
    for key in _unique_strings(extra.get("profileVerifierKeys") if isinstance(extra, Mapping) else []):
        keys.add(key.lower())
    if isinstance(extra, Mapping):
        keys.update(
            _canonical_profile_verifier_keys(
                verifiers=_sequence_or_empty(extra.get("profileVerifiers")),
                phones=_sequence_or_empty(extra.get("profilePhones")),
                emails=_sequence_or_empty(extra.get("profileEmails")),
            )
        )
    return keys


def _find_profile_admin_deal(
    conn: sqlite3.Connection,
    *,
    profile_id: str,
    side: str,
    primary_contact_id: str | None,
    verifier_keys: Sequence[str],
) -> tuple[dict[str, Any] | None, str | None]:
    candidates = list_deals(conn, side=side, status="active", limit=500)
    for deal in candidates:
        extra = deal.get("extraToggles") if isinstance(deal.get("extraToggles"), Mapping) else {}
        source_profile_ids = set(_unique_strings(extra.get("sourceProfileIds") if isinstance(extra, Mapping) else []))
        source_profile_id = _compact_string(extra.get("sourceProfileId") if isinstance(extra, Mapping) else None)
        if source_profile_id:
            source_profile_ids.add(source_profile_id)
        if profile_id in source_profile_ids:
            return deal, "source_profile"

    if primary_contact_id:
        for deal in candidates:
            if deal.get("primaryContactId") == primary_contact_id:
                return deal, "primary_contact"

    wanted = {key.lower() for key in verifier_keys}
    if wanted:
        for deal in candidates:
            if wanted.intersection(_profile_deal_match_keys(deal)):
                return deal, "verifier"

    return None, None


def _profile_promotion_extra_fields(
    *,
    profile_id: str,
    side: str,
    workflow: str | None,
    display_name: str | None,
    profile_context: Mapping[str, Any],
    verifiers: Sequence[Mapping[str, Any]],
    verifier_keys: Sequence[str],
    phones: Sequence[str],
    emails: Sequence[str],
    existing_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contact_ids = _profile_context_list(profile_context, "contactIds")
    conversation_ids = _profile_context_list(profile_context, "conversationIds")
    thread_ids = _profile_context_list(profile_context, "threadIds")
    source_ids = _profile_context_list(profile_context, "sourceIds")
    prior_profile_ids: list[Any] = []
    existing_source_profile_ids = (existing_extra or {}).get("sourceProfileIds")
    if isinstance(existing_source_profile_ids, Sequence) and not isinstance(
        existing_source_profile_ids,
        (str, bytes, bytearray),
    ):
        prior_profile_ids.extend(existing_source_profile_ids)
    prior_profile_ids.extend([(existing_extra or {}).get("sourceProfileId"), profile_id])
    source_profile_ids = _unique_strings(prior_profile_ids)
    promoted_at = now_iso()
    fields: dict[str, Any] = {
        "sourceProfileId": profile_id,
        "sourceProfileIds": source_profile_ids,
        "sourceAdminSide": side,
        "workflow": workflow,
        "profileDisplayName": display_name,
        "profileContactIds": contact_ids,
        "profileConversationIds": conversation_ids,
        "profileThreadIds": thread_ids,
        "profileSourceIds": source_ids,
        "profileSources": _profile_context_list(profile_context, "sources"),
        "profileChannels": _profile_context_list(profile_context, "channels"),
        "profilePhones": list(phones),
        "profileEmails": list(emails),
        "profileVerifiers": _sanitize_profile_verifiers(verifiers),
        "profileVerifierKeys": list(verifier_keys),
        "profileLatestText": _compact_string(profile_context.get("latestText")),
        "profileLatestAt": _compact_string(profile_context.get("latestAt")),
        "profileHeatScore": profile_context.get("heatScore"),
        "profileHeatLabel": _compact_string(profile_context.get("heatLabel")),
        "profileTags": _profile_context_list(profile_context, "tags"),
        "profilePromotedAt": promoted_at,
        "profileLastSyncedAt": promoted_at,
    }
    return {key: value for key, value in fields.items() if value not in (None, "", [])}


def promote_profile_to_admin_deal(
    conn: sqlite3.Connection,
    *,
    profile_id: str,
    side: str,
    actor: str,
    province: str = "",
    board: str | None = None,
    market: str | None = None,
    current_stage: int = 0,
    display_name: str | None = None,
    primary_contact_id: str | None = None,
    listing_address: str | None = None,
    workflow: str | None = None,
    profile_context: Mapping[str, Any] | None = None,
    verifiers: Sequence[Mapping[str, Any]] | None = None,
    fields: Mapping[str, Any] | None = None,
    dispatch_initial_stage: bool = True,
) -> dict[str, Any]:
    """Create or update an Admin deal from a verified lead profile.

    Matching is intentionally verifier-first: source profile id, existing
    contact id, then normalized phone/email keys. That gives the Admin agent a
    stable path from conversations to deal files without guessing identities.
    """
    profile_id = _compact_string(profile_id) or _compact_string((profile_context or {}).get("id")) or ""
    if not profile_id:
        raise ValueError("profile_id is required")
    if side not in _VALID_SIDES:
        raise ValueError(f"invalid side {side!r}")
    current_stage = _validate_stage(current_stage)
    context = dict(profile_context or {})
    display_name = _compact_string(display_name) or _compact_string(context.get("displayName"))
    context_contact_ids = _profile_context_list(context, "contactIds")
    primary_contact_id = _compact_string(primary_contact_id) or (context_contact_ids[0] if context_contact_ids else None)
    if primary_contact_id and not context_contact_ids:
        context["contactIds"] = [primary_contact_id]
    valid_primary_contact_id = _existing_contact_id(conn, primary_contact_id)
    phones = _unique_strings(_sequence_or_empty(context.get("phones")))
    emails = _unique_strings(_sequence_or_empty(context.get("emails")))
    sanitized_verifiers = _sanitize_profile_verifiers(verifiers or _sequence_or_empty(context.get("verifiers")))
    verifier_keys = _canonical_profile_verifier_keys(
        verifiers=sanitized_verifiers,
        phones=phones,
        emails=emails,
    )
    if not verifier_keys:
        raise ValueError("at least one phone or email verifier is required before promoting a profile to Admin")

    existing, match_reason = _find_profile_admin_deal(
        conn,
        profile_id=profile_id,
        side=side,
        primary_contact_id=valid_primary_contact_id,
        verifier_keys=verifier_keys,
    )
    existing_extra = existing.get("extraToggles") if isinstance((existing or {}).get("extraToggles"), Mapping) else {}
    promotion_fields = _profile_promotion_extra_fields(
        profile_id=profile_id,
        side=side,
        workflow=_compact_string(workflow) or _compact_string(context.get("workflow")),
        display_name=display_name,
        profile_context=context,
        verifiers=sanitized_verifiers,
        verifier_keys=verifier_keys,
        phones=phones,
        emails=emails,
        existing_extra=existing_extra,
    )
    combined_fields = {**dict(fields or {}), **promotion_fields}

    if existing is None:
        title_name = display_name or _compact_string(listing_address) or "Lead profile"
        title = f"{'Seller' if side == 'listing' else 'Buyer'}: {title_name}"
        deal = create_deal(
            conn,
            title=title,
            side=side,
            actor=actor,
            province=province,
            board=board,
            market=market,
            current_stage=current_stage,
            primary_contact_id=valid_primary_contact_id,
            listing_address=listing_address,
            fields=combined_fields,
            dispatch_initial_stage=dispatch_initial_stage,
        )
        return {"action": "created", "matchReason": None, "deal": deal}

    row = conn.execute("SELECT * FROM deals WHERE id=?", (existing["id"],)).fetchone()
    if row is None:
        raise LookupError(f"deal {existing['id']!r} not found")
    named_fields, extra_fields = _split_fields(combined_fields)
    extra = _decode_json(row["extra_toggles_json"]) or {}
    if not isinstance(extra, dict):
        extra = {}
    old_extra = dict(extra)
    for key, value in extra_fields.items():
        extra[key] = _normalize_extra_field_value(value)

    updates: dict[str, Any] = dict(named_fields)
    if valid_primary_contact_id and not row["primary_contact_id"]:
        updates["primary_contact_id"] = valid_primary_contact_id
    listing_address = _compact_string(listing_address)
    if listing_address and not row["listing_address"]:
        updates["listing_address"] = listing_address
    if extra != old_extra:
        updates["extra_toggles_json"] = _encode_json(extra)
    if updates:
        now = now_iso()
        updates["updated_at"] = now
        sets = ", ".join(f"{field}=?" for field in updates)
        conn.execute(
            f"UPDATE deals SET {sets} WHERE id=?",
            [*updates.values(), existing["id"]],
        )
        _insert_deal_event(
            conn,
            deal_id=existing["id"],
            kind="contact_linked",
            actor=actor,
            old_value={"extra": old_extra},
            new_value={"extra": extra, **{k: v for k, v in updates.items() if k != "updated_at"}},
            payload={
                "profileId": profile_id,
                "side": side,
                "workflow": promotion_fields.get("workflow"),
                "matchReason": match_reason,
                "verifierKeys": verifier_keys,
            },
            created_at=now,
        )
    return {"action": "updated", "matchReason": match_reason, "deal": get_deal(conn, existing["id"])}


def record_deal_activity(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    actor: str,
    summary: str,
    tools: Sequence[str] | None = None,
    session_id: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any] | None:
    """Mark that the agent worked AROUND a deal this turn without a formal
    stage/checklist change (drafted a counter, read a contract, prepped docs).

    Appends an ``agent_activity`` event and bumps ``deals.updated_at`` so the
    board's freshness/ordering reflects the work. Returns the event, or None if
    the deal no longer exists (best-effort: never raises for a stale id).
    """
    if get_deal(conn, deal_id) is None:
        return None
    now = now_iso()
    event = _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="agent_activity",
        actor=actor,
        payload={
            "summary": summary[:500],
            "tools": list(tools or [])[:20],
            "sessionId": session_id,
            "confidence": confidence,
        },
        created_at=now,
    )
    conn.execute("UPDATE deals SET updated_at=? WHERE id=?", (now, deal_id))
    return event


def move_deal_stage(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    to_stage: int,
    actor: str,
    force: bool = False,
    gate_checked: bool = False,
) -> dict[str, Any]:
    """Move a deal to a 0-10 stage and append a stage_transition event."""
    to_stage = _validate_stage(to_stage)
    existing = get_deal(conn, deal_id)
    if existing is None:
        raise LookupError(f"deal {deal_id!r} not found")
    from_stage = existing["currentStage"]
    if from_stage == to_stage:
        return existing
    gate_snapshot: dict[str, Any] | None = None
    if to_stage > from_stage and not force and not gate_checked:
        gate_snapshot = _resolved_phase_gate(conn, deal_id, expected_stage=int(from_stage or 0))
        if not gate_snapshot.get("canAdvance") or gate_snapshot.get("nextStage") != to_stage:
            raise DealPhaseGateBlocked("deal phase gate is blocked", gate=gate_snapshot)
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
        payload={
            "fromStage": from_stage,
            "toStage": to_stage,
            **({"force": True, "gate": gate_snapshot} if force else {}),
        },
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
    # Auto-touch the working-state journal so the next session knows where
    # this deal sits without re-reading deal_events. Best-effort: a failure
    # here must not block the stage transition itself.
    try:
        from elevate_cli.data.working_state import touch_deal_stage_move
        touch_deal_stage_move(
            conn,
            deal_id=deal_id,
            deal_title=str(existing.get("title") or existing.get("address") or ""),
            from_stage=from_stage,
            to_stage=to_stage,
            agent_kind=actor,
        )
    except Exception:
        pass
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
        extra[field] = _normalize_extra_field_value(value)
        new_value = extra[field]
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
    moved = _maybe_advance_from_workflow_signal(conn, deal_id, field=field, value=new_value, actor=actor)
    if moved is None:
        _maybe_auto_advance_from_gate(conn, deal_id, actor=actor, expected_stage=int(row["current_stage"] or 0))
    return get_deal(conn, deal_id)  # type: ignore[return-value]


def _workflow_stage_complete_stage(field: str) -> int | None:
    match = _WORKFLOW_STAGE_COMPLETE_RE.match(field)
    if not match:
        return None
    try:
        return _validate_stage(int(match.group(1)))
    except ValueError:
        return None


def _is_completion_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _CHECKLIST_TRUE_VALUES
    return False


def _maybe_advance_from_workflow_signal(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    field: str,
    value: Any,
    actor: str,
) -> dict[str, Any] | None:
    try:
        if field in _WORKFLOW_ACCEPTED_OFFER_FIELDS and _present_signal(value):
            return _advance_on_accepted_offer(conn, deal_id, actor=actor)
    except DealPhaseGateBlocked:
        return None
    completed_stage = _workflow_stage_complete_stage(field)
    if completed_stage is None or not _is_completion_value(value):
        return None
    next_stage = _WORKFLOW_STAGE_COMPLETE_ADVANCES_TO.get(completed_stage)
    if next_stage is None:
        return None
    try:
        return _move_if_current_stage(conn, deal_id, current_stage=completed_stage, to_stage=next_stage, actor=actor)
    except DealPhaseGateBlocked:
        return None


def _advance_on_accepted_offer(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    actor: str,
) -> dict[str, Any] | None:
    """Move a live listing (stage 5) into Accepted Offer (6) on an accepted-offer
    signal, but only once the listing-live phase gate is otherwise clear."""
    try:
        context = get_deal_context(conn, deal_id)
    except Exception:
        return None
    deal = context.get("deal") or {}
    if int(deal.get("currentStage") or 0) != 5:
        return None
    gate = ((context.get("dealFlow") or {}).get("gate") or {})
    next_stage = gate.get("nextStage")
    if not gate.get("canAdvance") or next_stage is None:
        return None
    try:
        return move_deal_stage(conn, deal_id, to_stage=int(next_stage), actor=actor, gate_checked=True)
    except Exception:
        return None


def _move_if_current_stage(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    current_stage: int,
    to_stage: int,
    actor: str,
) -> dict[str, Any] | None:
    deal = get_deal(conn, deal_id)
    if deal is None:
        raise LookupError(f"deal {deal_id!r} not found")
    if int(deal.get("currentStage") or 0) != current_stage:
        return None
    return move_deal_stage(conn, deal_id, to_stage=to_stage, actor=actor)


def _resolved_phase_gate(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    expected_stage: int | None = None,
) -> dict[str, Any]:
    try:
        context = get_deal_context(conn, deal_id)
    except Exception as exc:
        return {
            "stage": expected_stage,
            "canAdvance": False,
            "reason": f"phase gate could not be resolved: {exc}",
        }
    deal = context.get("deal") or {}
    current_stage = int(deal.get("currentStage") or 0)
    gate = dict(((context.get("dealFlow") or {}).get("gate") or {}))
    if expected_stage is not None and current_stage != expected_stage:
        gate["canAdvance"] = False
        gate["reason"] = "deal stage changed before gate evaluation completed"
    return gate


def _maybe_auto_advance_from_gate(
    conn: sqlite3.Connection,
    deal_id: str,
    *,
    actor: str,
    expected_stage: int | None = None,
) -> dict[str, Any] | None:
    """Advance once when the resolved source-of-truth phase gate is clear."""
    try:
        context = get_deal_context(conn, deal_id)
    except Exception:
        return None
    deal = context.get("deal") or {}
    current_stage = int(deal.get("currentStage") or 0)
    if expected_stage is not None and current_stage != expected_stage:
        return None
    if current_stage not in _AUTO_ADVANCE_GATE_STAGES:
        return None
    gate = ((context.get("dealFlow") or {}).get("gate") or {})
    if not gate.get("canAdvance"):
        return None
    next_stage = gate.get("nextStage")
    if next_stage is None:
        return None
    try:
        return move_deal_stage(conn, deal_id, to_stage=int(next_stage), actor=actor, gate_checked=True)
    except Exception:
        return None


def _present_signal(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _normalize_extra_field_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _CHECKLIST_TRUE_VALUES:
            return True
        if lowered in _CHECKLIST_FALSE_VALUES:
            return False
    return value


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
    "completion_date", "possession_date", "anniversary_date", "expected_close_date",
}
_MONEY_FIELDS = {
    "list_price",
    "offer_price",
    "deposit_amount",
    "commission_pct",
    "home_price",
    "gci",
    "team_revenue",
    "agent_revenue",
}
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
    "homePrice": "home_price",
    "gci": "gci",
    "teamRevenue": "team_revenue",
    "agentRevenue": "agent_revenue",
    "expectedCloseDate": "expected_close_date",
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


def _coerce_detail_value(field: str, value: Any) -> Any:
    if field in _MONEY_FIELDS or field == "lot_size_sqft":
        return None if value is None or value == "" else float(value)
    if field == "year_built":
        return None if value is None or value == "" else int(value)
    return None if value is None else str(value)


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
        updates[field] = _coerce_detail_value(field, value)
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
    stage_before = int(row["current_stage"] or 0)
    moved = None
    if _present_signal(updates.get("offer_accepted_at")):
        try:
            moved = _advance_on_accepted_offer(conn, deal_id, actor=actor)
        except DealPhaseGateBlocked:
            moved = None
    if moved is None:
        _maybe_auto_advance_from_gate(conn, deal_id, actor=actor, expected_stage=stage_before)
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
    deal = get_deal(conn, deal_id)
    if deal is None:
        raise LookupError(f"deal {deal_id!r} not found")
    if not kind or not kind.strip():
        raise ValueError("attachment kind is required")
    if not file_path or not file_path.strip():
        raise ValueError("file_path is required")
    kind_clean = kind.strip()
    file_path_clean = file_path.strip()
    if source_run_id:
        existing = conn.execute(
            """
            SELECT * FROM deal_attachments
            WHERE deal_id=? AND source_run_id=? AND kind=? AND file_path=?
            """,
            (deal_id, source_run_id, kind_clean, file_path_clean),
        ).fetchone()
        if existing is not None:
            return _row_to_deal_attachment(existing)
    aid = new_id()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO deal_attachments(
            id, deal_id, kind, file_path, summary,
            source_run_id, source_snapshot_id, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (aid, deal_id, kind_clean, file_path_clean, summary, source_run_id, source_snapshot_id, now),
    )
    row = conn.execute("SELECT * FROM deal_attachments WHERE id=?", (aid,)).fetchone()
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="attachment_added",
        actor=actor,
        payload={"kind": kind_clean, "filePath": file_path_clean, "sourceRunId": source_run_id},
        created_at=now,
    )
    _maybe_auto_advance_from_gate(conn, deal_id, actor=actor, expected_stage=int(deal.get("currentStage") or 0))
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
    keys = row.keys()
    return {
        "id": row["id"],
        "registryId": row["registry_id"],
        "dealId": row["deal_id"],
        "dealEventId": row["deal_event_id"],
        "cronJobId": row["cron_job_id"],
        "harnessRunId": row["harness_run_id"] if "harness_run_id" in keys else None,
        "status": row["status"],
        "outputPath": row["output_path"],
        "errorMessage": row["error_message"],
        "payload": _decode_json(row["payload_json"]),
        "humanPrompt": _decode_json(row["human_prompt_json"]) if "human_prompt_json" in keys else None,
        "result": _decode_json(row["result_json"]) if "result_json" in keys else None,
        "resultIdempotencyKey": row["result_idempotency_key"] if "result_idempotency_key" in keys else None,
        "createdAt": row["created_at"],
        "startedAt": row["started_at"] if "started_at" in keys else None,
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
        "skill": row["skill"] if "skill" in keys else None,
        "registryName": row["name"] if "name" in keys else None,
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
    from elevate_cli.data.province_guides import (
        condition_docs_for_conditions,
        normalize_province_code,
        province_agent_memory,
        province_guide_summary,
        province_stage_documents,
    )
    # Province on the deal row may be stored as either a clean code ("BC") or
    # a legacy country-prefixed tuple ("ca.bc"). Normalize once so every
    # downstream call uses the canonical short code.
    raw_province = str(deal.get("province") or "").strip()
    try:
        deal_province = normalize_province_code(raw_province.split(".", 1)[-1]) or ""
    except ValueError:
        deal_province = ""
    condition_docs = condition_docs_for_conditions(
        conn,
        province=deal_province,
        conditions=conditions,
        side=str(deal.get("side") or ""),
        stage=int(deal.get("currentStage") or 0),
    )
    province_guide = province_guide_summary(conn, deal_province)
    agent_guide_memory = province_agent_memory(conn, deal_province)
    # Conditions for stage-document mapping combine the named-field conditions
    # (signing_authority, fintrac_form_type, etc.) with any boolean toggles
    # carried on the checklist (tenanted, multiple_offers, strata, lockbox...).
    # The conditional_docs overlay matches on field_key + field_value pairs.
    stage_doc_conditions: dict[str, Any] = dict(conditions)
    if isinstance(checklist, Mapping):
        for key, value in checklist.items():
            if value is None:
                continue
            if isinstance(value, bool):
                stage_doc_conditions[str(key)] = "true" if value else "false"
            else:
                stage_doc_conditions[str(key)] = value
    if deal.get("propertySubtype"):
        stage_doc_conditions["property_subtype"] = deal.get("propertySubtype")
    stage_documents = province_stage_documents(
        conn,
        province=deal_province,
        side=str(deal.get("side") or "listing"),
        conditions=stage_doc_conditions,
    )
    from elevate_cli.admin_deal_flow import resolve_deal_phase

    deal_flow = resolve_deal_phase(
        deal=deal,
        checklist=checklist,
        attachments=attachments,
        prior_runs=prior_runs,
        conditions=conditions,
        condition_docs=condition_docs,
    )
    return {
        "deal": deal,
        "primaryContact": primary,
        "coContacts": list_deal_contacts(conn, deal_id),
        "conditions": conditions,
        "conditionalDocs": condition_docs,
        "checklist": checklist,
        "attachments": attachments,
        "priorRuns": prior_runs,
        "dealFlow": deal_flow,
        "provinceGuide": province_guide,
        "agentGuideMemory": agent_guide_memory,
        "stageDocuments": stage_documents,
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
    handoff_id: str | None = None,
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
        "handoffId": handoff_id,
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

        try:
            from elevate_cli.data.agent_handoffs import list_agent_handoffs

            handoffs = list_agent_handoffs(conn, deal_id=str(deal["id"]), limit=50)
        except Exception:
            handoffs = []
        for handoff in handoffs:
            handoff_status = str(handoff.get("status") or "queued")
            if status == "open" and handoff_status in {"completed", "cancelled"}:
                continue
            if status == "done" and handoff_status not in {"completed", "cancelled"}:
                continue
            tasks.append(
                _deal_task_common(
                    deal,
                    flow,
                    task_id=f"handoff:{handoff.get('id')}",
                    task_type="agent_handoff",
                    source="agent_handoff",
                    title=str(handoff.get("title") or "Agent handoff"),
                    description=str(handoff.get("task") or ""),
                    status=handoff_status,
                    skill=None,
                    can_run_with_ai=False,
                    handoff_id=str(handoff.get("id")),
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
    "title_search": "workflow_title_ordered",
    "title_pdf": "workflow_title_ordered",
    "mlc_pdf": "workflow_stage_2_complete",
    "mlc_form": "workflow_stage_2_complete",
    "listing_agreement_pdf": "workflow_stage_2_complete",
    "listing_forms": "workflow_stage_2_complete",
    "signed_envelope": "workflow_stage_2_complete",
    "signed_docs": "workflow_stage_2_complete",
    "listing_photos": "workflow_photos_in_drive",
    "feature_sheet": "workflow_feature_sheet_uploaded",
    "showing_digest": "workflow_stage_5_complete",
    "showingtime_digest": "workflow_stage_5_complete",
    "offer_pdf": "workflow_within_24hrs_contract_reviewed",
    "offer_summary": "workflow_within_24hrs_contract_reviewed",
    "deposit_receipt": "workflow_deposit_rof_received_date",
    "inspection_report": "workflow_calendar_dates_added",
    "strata_docs": "strata-docs-review",
}
_PROTECTED_SKILL_CHECKLIST_KEYS = {
    "workflow_listing_description_approved",
    "workflow_jeff_photo_review",
}


def _is_skill_actor(actor: str) -> bool:
    return str(actor or "").startswith("skill")


def _is_protected_skill_checklist_key(key: str) -> bool:
    return bool(_workflow_stage_complete_stage(key) is not None or key in _PROTECTED_SKILL_CHECKLIST_KEYS)


def _filter_protected_skill_checklist_updates(
    updates: Mapping[str, bool],
    *,
    actor: str,
) -> tuple[dict[str, bool], list[str]]:
    if not _is_skill_actor(actor):
        return dict(updates), []
    allowed: dict[str, bool] = {}
    skipped: list[str] = []
    for key, value in updates.items():
        if value is True and _is_protected_skill_checklist_key(str(key)):
            skipped.append(str(key))
            continue
        allowed[str(key)] = bool(value)
    return allowed, skipped


def _coerce_checklist_bool(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _CHECKLIST_TRUE_VALUES:
            return True
        if lowered in _CHECKLIST_FALSE_VALUES:
            return False
    return bool(value)


def _explicit_checklist_updates(items: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None) -> dict[str, bool]:
    if not items:
        return {}
    if isinstance(items, Mapping):
        return {str(k): _coerce_checklist_bool(v) for k, v in items.items()}
    updates: dict[str, bool] = {}
    for item in items:
        key = item.get("id") or item.get("itemId") or item.get("field")
        if key:
            updates[str(key)] = _coerce_checklist_bool(item.get("completed"), default=True)
    return updates


def _run_payload_stage(payload: Mapping[str, Any]) -> int | None:
    for key in ("toStage", "currentStage"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return _validate_stage(int(value))
        except (TypeError, ValueError):
            continue
    return None


def record_run_result(
    conn: sqlite3.Connection,
    deal_id: str,
    run_id: str,
    *,
    status: str,
    idempotency_key: str | None = None,
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
    prior_key = row["result_idempotency_key"] if "result_idempotency_key" in row.keys() else None
    prior_result = row["result_json"] if "result_json" in row.keys() else None
    if prior_key:
        if idempotency_key and prior_key == idempotency_key:
            return _row_to_action_run(row)
        raise ValueError("action run result has already been recorded")
    if prior_result and row["status"] in {"succeeded", "completed", "failed", "skipped", "cancelled"}:
        raise ValueError("action run result has already been recorded")
    payload = _decode_json(row["payload_json"]) or {}
    if not isinstance(payload, dict):
        payload = {"prior": payload}
    result_payload = {
        "status": status,
        "artifacts": [dict(item) for item in (artifacts or [])],
        "nextTasks": [dict(item) for item in (next_tasks or [])],
        "checklistUpdates": checklist_updates,
        "protectedChecklistSkipped": [],
        "humanPrompt": dict(human_prompt) if human_prompt else None,
        "error": error,
        "idempotencyKey": idempotency_key,
        "recordedAt": now,
    }
    payload["result"] = result_payload
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
        updates, protected_skipped = _filter_protected_skill_checklist_updates(updates, actor=actor)
        result_payload["protectedChecklistSkipped"] = protected_skipped
        payload["result"] = result_payload
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
        SET status=?, output_path=?, error_message=?, payload_json=?,
            result_idempotency_key=?, result_json=?, human_prompt_json=?,
            updated_at=?, completed_at=?
        WHERE id=?
        """,
        (
            normalized_status,
            output_path,
            error,
            _encode_json(payload),
            idempotency_key,
            _encode_json(result_payload),
            _encode_json(dict(human_prompt)) if human_prompt else None,
            now,
            completed_at,
            run_id,
        ),
    )
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="run_result",
        actor=actor,
        payload={"runId": run_id, "status": normalized_status, "humanPrompt": human_prompt, "error": error},
        created_at=now,
    )
    if normalized_status in {"succeeded", "completed"}:
        _maybe_auto_advance_from_gate(conn, deal_id, actor=actor, expected_stage=_run_payload_stage(payload))
    updated = conn.execute("SELECT * FROM admin_action_runs WHERE id=?", (run_id,)).fetchone()
    return _row_to_action_run(updated)
