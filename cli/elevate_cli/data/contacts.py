"""Read/write helpers for the ``contacts`` table.

Public surface (re-exported via ``elevate_cli.data``):

* :func:`get_contact`
* :func:`find_contacts`
* :func:`upsert_contact`
* :func:`classify_contact`
* :func:`park_contact`, :func:`unpark_contact`
* :func:`update_contact_stage`
* :func:`add_contact_note`

Every mutation writes a paired row into the ``events`` audit log via
:mod:`elevate_cli.data.events`. Callers don't need to know.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from elevate_cli.data import events as _events
from elevate_cli.data._util import new_id, now_iso


def _row_to_contact(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys() if hasattr(row, "keys") else []
    def _get(name: str, default: Any = None) -> Any:
        return row[name] if name in keys else default
    return {
        "id": row["id"],
        "displayName": row["display_name"],
        "primaryEmail": row["primary_email"],
        "primaryPhone": row["primary_phone"],
        "type": row["type"],
        "stage": row["stage"],
        "ownerNotes": row["owner_notes"],
        "parkedReason": row["parked_reason"],
        "hasOpenConflict": bool(row["has_open_conflict"]),
        "lastActivityAt": row["last_activity_at"],
        "classifiedAt": row["classified_at"],
        "sourceKey": row["source_key"],
        "ingestRunId": row["ingest_run_id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        # Lane flags (migration 0013_contact_flags). Read-default if older row
        # made it through before the migration applied.
        "heatLabel": _get("heat_label", "normal"),
        "heatScore": int(_get("heat_score", 0) or 0),
        "heatReason": _get("heat_reason"),
        "needsFollowUp": bool(_get("needs_follow_up", 0)),
        "nextFollowUpAt": _get("next_follow_up_at"),
        "buyerSearchActive": bool(_get("buyer_search_active", 0)),
        "listingActive": bool(_get("listing_active", 0)),
        "aiLastReviewedAt": _get("ai_last_reviewed_at"),
        "aiReviewRunId": _get("ai_review_run_id"),
        # Pipeline status (migration 0014_pipeline_status). Set by either the
        # operator clicking the /leads dropdown or the AI in review_contact.
        "pipelineStatus": _get("pipeline_status"),
        "pipelineStatusSetAt": _get("pipeline_status_set_at"),
        "pipelineStatusSetBy": _get("pipeline_status_set_by"),
        # Lofty/CRM enrichment (migrations 0017_contacts_lofty_fields +
        # 0012_lofty_lead_metadata). Default to None on rows that
        # predate the migration so callers don't KeyError.
        "leadSource": _get("lead_source"),
        "assignedAgent": _get("assigned_agent"),
        "crmStage": _get("crm_stage"),
        "leadScore": _get("lead_score"),
        "tagsJson": _get("tags_json"),
        "segmentsJson": _get("segments_json"),
        "leadTypesJson": _get("lead_types_json"),
        "crmUserId": _get("crm_user_id"),
        "loftyLeadUserId": _get("lofty_lead_user_id"),
        "pondId": _get("pond_id"),
        "pondName": _get("pond_name"),
        "referredBy": _get("referred_by"),
        "opportunity": _get("opportunity"),
        "buyingTimeFrame": _get("buying_time_frame"),
        "sellingTimeFrame": _get("selling_time_frame"),
        "preQualStatus": _get("pre_qual_status"),
        "hasHouseToSell": _get("has_house_to_sell"),
        "firstTimeHomeBuyer": _get("first_time_home_buyer"),
        "withBuyerAgent": _get("with_buyer_agent"),
        "withListingAgent": _get("with_listing_agent"),
        "mortgageStatus": _get("mortgage_status"),
        "buyHouseIntent": _get("buy_house_intent"),
        "cannotText": bool(_get("cannot_text", 0)),
        "cannotCall": bool(_get("cannot_call", 0)),
        "cannotEmail": bool(_get("cannot_email", 0)),
        "unsubscribed": bool(_get("unsubscribed", 0)),
        "hidden": bool(_get("hidden", 0)),
    }


_FLAG_COLUMNS: dict[str, str] = {
    "heatLabel": "heat_label",
    "heatScore": "heat_score",
    "heatReason": "heat_reason",
    "needsFollowUp": "needs_follow_up",
    "nextFollowUpAt": "next_follow_up_at",
    "buyerSearchActive": "buyer_search_active",
    "listingActive": "listing_active",
    "aiLastReviewedAt": "ai_last_reviewed_at",
    "aiReviewRunId": "ai_review_run_id",
}

_HEAT_LABELS = {"hot", "warm", "watch", "normal"}
_VALID_SIDES_FOR_ADMIN = {"buyer", "listing"}
_PIPELINE_STATUS_VALUES = {
    "new_lead", "follow_up", "ghosting", "dead",
    "closed_seller", "closed_buyer",
}
_PIPELINE_STATUS_SET_BY = {"operator", "ai"}


# ─── Reads ─────────────────────────────────────────────────────────────


def get_contact(conn: sqlite3.Connection, contact_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    return _row_to_contact(row) if row else None


def find_contacts(
    conn: sqlite3.Connection,
    *,
    type: str | None = None,
    stage: str | None = None,
    stage_in: Iterable[str] | None = None,
    has_open_conflict: bool | None = None,
    last_activity_after: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Filterable list. All filters are AND-ed; pass ``None`` to skip a filter.

    ``last_activity_after`` is an ISO timestamp string — the SQL compares
    lexically, which works for ISO-8601 with a stable timezone offset
    (we always emit ``+00:00``).

    ``stage`` and ``stage_in`` are mutually exclusive — pass one or the
    other (or neither). ``stage_in`` accepts a list/tuple/set and emits
    ``stage IN (?, ?, …)``. Empty iterable returns no rows.
    """
    if stage is not None and stage_in is not None:
        raise ValueError("pass either stage or stage_in, not both")
    sql = "SELECT * FROM contacts WHERE 1=1"
    params: list[Any] = []
    if type is not None:
        sql += " AND type = ?"
        params.append(type)
    if stage is not None:
        sql += " AND stage = ?"
        params.append(stage)
    if stage_in is not None:
        stages = [s for s in stage_in]
        if not stages:
            return []
        placeholders = ",".join(["?"] * len(stages))
        sql += f" AND stage IN ({placeholders})"
        params.extend(stages)
    if has_open_conflict is not None:
        sql += " AND has_open_conflict = ?"
        params.append(1 if has_open_conflict else 0)
    if last_activity_after is not None:
        sql += " AND last_activity_at >= ?"
        params.append(last_activity_after)
    sql += " ORDER BY last_activity_at DESC NULLS LAST LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_contact(r) for r in rows]


# ─── Writes ────────────────────────────────────────────────────────────


# Lofty enrichment columns the connector writes through. Kept as a
# module-level whitelist so the INSERT and the UPDATE branches stay in
# lockstep and a new column only needs to be added in one place.
#
# Order matters for the INSERT: it must match the column list in the
# VALUES clause. Update branch keys off the same list via setattr-style
# dynamic SET.
_ENRICHMENT_COLUMNS: tuple[str, ...] = (
    # Lofty linkage
    "lofty_lead_user_id",
    "crm_user_id",
    "lead_source",
    "assigned_agent",
    "crm_stage",
    "lead_score",
    "tags_json",
    "segments_json",
    "lead_types_json",
    "pond_id",
    "pond_name",
    "referred_by",
    "opportunity",
    # Buyer/seller qualification (free-form strings from Lofty)
    "buying_time_frame",
    "selling_time_frame",
    "pre_qual_status",
    "has_house_to_sell",
    "first_time_home_buyer",
    "with_buyer_agent",
    "with_listing_agent",
    "mortgage_status",
    "buy_house_intent",
    # Consent + visibility flags (0/1 ints)
    "cannot_text",
    "cannot_call",
    "cannot_email",
    "unsubscribed",
    "hidden",
    # Activity timestamp from the source system
    "last_activity_at",
)


def upsert_contact(
    conn: sqlite3.Connection,
    *,
    contact_id: str | None = None,
    display_name: str | None = None,
    primary_email: str | None = None,
    primary_phone: str | None = None,
    type: str = "unclassified",
    stage: str = "cold",
    source_key: str | None = None,
    ingest_run_id: str | None = None,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new contact or update an existing one by id or source_key.

    Resolution order: explicit ``contact_id`` > ``source_key`` lookup >
    new contact. Returns the resulting row in dict form.

    ``enrichment`` is an optional dict of {column_name: value} pairs
    drawn from :data:`_ENRICHMENT_COLUMNS`. Keys outside that whitelist
    are dropped — keeps the writer immune to schema drift and stops
    JSONL noise from poisoning the contacts row. None values inside the
    dict are skipped (treated as "don't touch") so successive sync runs
    don't blank out enrichment fields that vanished from a later API
    response.

    Does NOT write an event — contact creation is an indirect side
    effect of identity resolution and ingest, so the connector code is
    responsible for emitting ``ingest_run_started`` etc. The lifecycle
    helpers below (``classify_contact``, ``park_contact``, ...) DO write
    events because each one is a direct user/agent action.
    """
    now = now_iso()

    # Pre-filter enrichment payload: keep only whitelisted columns whose
    # values are not None / empty-string. Empty strings explicitly count
    # as "no value" so Lofty's "" placeholders don't overwrite real data
    # on the next sync.
    enrichment = enrichment or {}
    clean_enrich: dict[str, Any] = {}
    for col in _ENRICHMENT_COLUMNS:
        if col not in enrichment:
            continue
        value = enrichment[col]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        clean_enrich[col] = value

    existing: sqlite3.Row | None = None
    if contact_id:
        existing = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
    elif source_key:
        existing = conn.execute(
            "SELECT * FROM contacts WHERE source_key = ?", (source_key,)
        ).fetchone()

    if existing is None:
        cid = contact_id or new_id()
        base_cols = (
            "id", "display_name", "primary_email", "primary_phone",
            "type", "stage", "source_key", "ingest_run_id",
            "created_at", "updated_at",
        )
        base_vals: list[Any] = [
            cid,
            display_name,
            primary_email,
            primary_phone,
            type,
            stage,
            source_key,
            ingest_run_id,
            now,
            now,
        ]
        # Append enrichment columns in deterministic order.
        all_cols = list(base_cols)
        for col in _ENRICHMENT_COLUMNS:
            if col in clean_enrich:
                all_cols.append(col)
                base_vals.append(clean_enrich[col])
        placeholders = ",".join("?" * len(all_cols))
        column_list = ", ".join(all_cols)
        conn.execute(
            f"INSERT INTO contacts({column_list}) VALUES ({placeholders})",
            base_vals,
        )
        return get_contact(conn, cid)  # type: ignore[return-value]

    cid = existing["id"]
    # Patch only fields that the caller actually provided.
    sets: list[str] = []
    params: list[Any] = []
    if display_name is not None and display_name != existing["display_name"]:
        sets.append("display_name=?")
        params.append(display_name)
    if primary_email is not None and primary_email != existing["primary_email"]:
        sets.append("primary_email=?")
        params.append(primary_email)
    if primary_phone is not None and primary_phone != existing["primary_phone"]:
        sets.append("primary_phone=?")
        params.append(primary_phone)
    if ingest_run_id is not None and ingest_run_id != existing["ingest_run_id"]:
        sets.append("ingest_run_id=?")
        params.append(ingest_run_id)
    # Enrichment columns — only patch when the new value differs from
    # what's already on the row. _row_to_contact aside, this keeps
    # updated_at honest (no UPDATE = no timestamp bump).
    existing_keys = set(existing.keys()) if hasattr(existing, "keys") else set()
    for col, value in clean_enrich.items():
        if col not in existing_keys:
            # Migration hasn't applied for this column on this DB yet —
            # skip silently rather than 500 the whole sync.
            continue
        if value != existing[col]:
            sets.append(f"{col}=?")
            params.append(value)
    if sets:
        sets.append("updated_at=?")
        params.extend([now, cid])
        conn.execute(f"UPDATE contacts SET {', '.join(sets)} WHERE id = ?", params)
    return get_contact(conn, cid)  # type: ignore[return-value]


def classify_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    type: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Set ``contacts.type`` and stamp ``classified_at``. Emits ``classified``."""
    if type not in {"buyer", "listing", "other"}:
        raise ValueError(f"invalid type {type!r}")
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET type=?, classified_at=?, updated_at=? WHERE id=?",
        (type, now, now, contact_id),
    )
    _events.record_classification(
        conn, contact_id=contact_id, type=type, actor=actor, ts=now
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def park_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    reason: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Mark a contact ``stage='parked'`` with a reason. Emits ``parked``."""
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET stage='parked', parked_reason=?, updated_at=? WHERE id=?",
        (reason, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="parked",
        actor=actor,
        ts=now,
        payload={"reason": reason},
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def unpark_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Clear the parked state, returning the contact to ``stage='active'``.
    Emits ``unparked``."""
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET stage='active', parked_reason=NULL, updated_at=? WHERE id=?",
        (now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="unparked",
        actor=actor,
        ts=now,
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def update_contact_stage(
    conn: sqlite3.Connection,
    contact_id: str,
    stage: str,
    *,
    actor: str,
) -> dict[str, Any]:
    now = now_iso()
    conn.execute(
        "UPDATE contacts SET stage=?, updated_at=? WHERE id=?",
        (stage, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="lifecycle_change",
        actor=actor,
        ts=now,
        payload={"stage": stage},
    )
    return get_contact(conn, contact_id)  # type: ignore[return-value]


def add_contact_note(
    conn: sqlite3.Connection,
    contact_id: str,
    note: str,
    *,
    actor: str,
) -> None:
    """Append a note to ``contacts.owner_notes`` (newline-delimited).
    Emits ``note``. Notes are append-only; we never overwrite history."""
    now = now_iso()
    row = conn.execute(
        "SELECT owner_notes FROM contacts WHERE id=?", (contact_id,)
    ).fetchone()
    existing = row["owner_notes"] if row and row["owner_notes"] else ""
    new_notes = (existing + ("\n" if existing else "") + note).strip()
    conn.execute(
        "UPDATE contacts SET owner_notes=?, updated_at=? WHERE id=?",
        (new_notes, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="note",
        actor=actor,
        ts=now,
        payload={"note": note},
    )


def leads_worked_recently(
    conn: sqlite3.Connection, *, since_hours: int = 18, limit: int = 100
) -> list[dict[str, Any]]:
    """Leads the agent already worked in the last ``since_hours`` (an
    ``agent_activity`` event), with the status it left them in.

    The Leads heartbeat reads this to avoid re-processing a lead it already
    handled today — and to see what status was assigned — instead of acting
    blind. Newest-worked first.
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=max(1, since_hours))).isoformat()
    rows = conn.execute(
        """
        SELECT e.contact_id            AS contact_id,
               MAX(e.ts)               AS last_worked_at,
               c.display_name          AS display_name,
               c.pipeline_status       AS pipeline_status,
               c.pipeline_status_set_by AS set_by,
               c.heat_label            AS heat_label,
               c.needs_follow_up       AS needs_follow_up
        FROM events e
        JOIN contacts c ON c.id = e.contact_id
        WHERE e.kind = 'agent_activity' AND e.ts >= ?
        GROUP BY e.contact_id, c.display_name, c.pipeline_status,
                 c.pipeline_status_set_by, c.heat_label, c.needs_follow_up
        ORDER BY last_worked_at DESC
        LIMIT ?
        """,
        (since, int(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "contactId": r["contact_id"],
            "name": r["display_name"],
            "lastWorkedAt": r["last_worked_at"],
            "pipelineStatus": r["pipeline_status"],
            "pipelineStatusSetBy": r["set_by"],
            "heatLabel": r["heat_label"],
            "needsFollowUp": bool(r["needs_follow_up"]),
        })
    return out


def touch_last_activity(
    conn: sqlite3.Connection, contact_id: str, ts: str
) -> None:
    """Bump ``last_activity_at`` if the new ts is newer. Internal helper
    used by inbound/outbound recorders."""
    row = conn.execute(
        "SELECT last_activity_at FROM contacts WHERE id=?", (contact_id,)
    ).fetchone()
    if row is None:
        return
    current = row["last_activity_at"] or ""
    if ts > current:
        conn.execute(
            "UPDATE contacts SET last_activity_at=?, updated_at=? WHERE id=?",
            (ts, now_iso(), contact_id),
        )


def set_open_conflict_flag(
    conn: sqlite3.Connection, contact_ids: Iterable[str], value: bool
) -> None:
    """Toggle ``has_open_conflict`` across a set of contacts. Used by
    ``identities.record_identity_conflict`` and the resolver."""
    flag = 1 if value else 0
    for cid in contact_ids:
        conn.execute(
            "UPDATE contacts SET has_open_conflict=?, updated_at=? WHERE id=?",
            (flag, now_iso(), cid),
        )


# ─── Lane flags (heat / follow-up / buyer-search / listing) ────────────


def update_flags(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    actor: str,
    record_event: bool = True,
    **flags: Any,
) -> dict[str, Any] | None:
    """Partial update of the AI-maintained lane flags on ``contacts``.

    Accepts camelCase keys matching ``_FLAG_COLUMNS`` (heatLabel, heatScore,
    heatReason, needsFollowUp, nextFollowUpAt, buyerSearchActive,
    listingActive, aiLastReviewedAt, aiReviewRunId). Unknown keys raise.

    Bools coerce to 0/1. Heat label is validated against the enum.

    Writes one ``lifecycle_change`` event with the diff so the audit log
    can replay how a contact moved between lanes. Pass ``record_event=False``
    for high-volume bulk reviews where event noise isn't useful.
    """
    if not flags:
        return get_contact(conn, contact_id)

    sets: list[str] = []
    values: list[Any] = []
    payload: dict[str, Any] = {}
    for key, value in flags.items():
        col = _FLAG_COLUMNS.get(key)
        if col is None:
            raise ValueError(f"unknown flag {key!r}; expected one of {sorted(_FLAG_COLUMNS)}")
        if key == "heatLabel" and value is not None and value not in _HEAT_LABELS:
            raise ValueError(f"invalid heat label {value!r}; expected one of {sorted(_HEAT_LABELS)}")
        if key == "heatScore" and value is not None:
            ivalue = int(value)
            if not 0 <= ivalue <= 100:
                raise ValueError(f"heat score out of range: {value!r}")
            value = ivalue
        if key in ("needsFollowUp", "buyerSearchActive", "listingActive"):
            value = 1 if value else 0
        sets.append(f"{col}=?")
        values.append(value)
        payload[key] = value

    now = now_iso()
    sets.append("updated_at=?")
    values.append(now)
    values.append(contact_id)
    cursor = conn.execute(
        f"UPDATE contacts SET {', '.join(sets)} WHERE id=?",
        tuple(values),
    )
    if cursor.rowcount == 0:
        return None

    if record_event:
        _events.record_lifecycle(
            conn,
            contact_id=contact_id,
            kind="lifecycle_change",
            actor=actor,
            ts=now,
            payload={"flags": payload},
        )
    return get_contact(conn, contact_id)


def close_to_admin(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    side: str,
    actor: str,
    province: str = "BC",
    listing_address: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Convert a /leads contact into an /admin deal.

    Workflow:
      1. Validate the contact exists and has a verifier (email or phone) so
         ``promote_profile_to_admin_deal`` will accept it.
      2. Flip ``contacts.stage`` → ``'closed'`` and clear the active-lane
         flags so the contact disappears from /leads widgets.
      3. Call ``promote_profile_to_admin_deal(side=...)`` to create or
         match an Admin deal under the buyer or listing side.

    Raises ``ValueError`` on missing contact, invalid side, or missing
    verifier (which Admin promotion needs).
    """
    if side not in _VALID_SIDES_FOR_ADMIN:
        raise ValueError(f"invalid side {side!r}; expected 'buyer' or 'listing'")
    contact = get_contact(conn, contact_id)
    if contact is None:
        raise ValueError(f"contact {contact_id!r} not found")

    email = (contact.get("primaryEmail") or "").strip()
    phone = (contact.get("primaryPhone") or "").strip()
    if not email and not phone:
        raise ValueError(
            f"contact {contact_id!r} has no email or phone — add a verifier "
            "before closing to admin"
        )

    now = now_iso()
    conn.execute(
        """
        UPDATE contacts
        SET stage='closed',
            type=COALESCE(NULLIF(type,'unclassified'), ?),
            buyer_search_active=0,
            listing_active=0,
            needs_follow_up=0,
            heat_label='normal',
            heat_score=0,
            updated_at=?
        WHERE id=?
        """,
        (side, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="lifecycle_change",
        actor=actor,
        ts=now,
        payload={"stage": "closed", "promotedTo": "admin", "side": side},
    )

    from elevate_cli.data import deals as _deals  # local to avoid cycle
    profile_context = {
        "displayName": contact.get("displayName"),
        "contactIds": [contact_id],
        "phones": [phone] if phone else [],
        "emails": [email] if email else [],
    }
    promotion = _deals.promote_profile_to_admin_deal(
        conn,
        profile_id=contact_id,
        side=side,
        actor=actor,
        province=province,
        display_name=contact.get("displayName"),
        primary_contact_id=contact_id,
        listing_address=listing_address,
        workflow=workflow,
        profile_context=profile_context,
    )
    return {
        "contact": get_contact(conn, contact_id),
        "deal": promotion.get("deal"),
        "action": promotion.get("action"),
        "matchReason": promotion.get("matchReason"),
    }


def set_lead_profile_favorite(
    conn: sqlite3.Connection,
    profile_id: str,
    *,
    favorite: bool,
    contact_id: str | None = None,
    actor: str = "operator:leads-ui",
) -> dict[str, Any]:
    """Set or clear the /leads favorite flag for a source-inbox profile.

    This is intentionally UI-scoped. It does not change heat, follow-up,
    pipeline status, outreach approval, or CRM/source state.
    """
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profile_id is required")

    cid = str(contact_id or "").strip() or None
    now = now_iso()
    if favorite:
        conn.execute(
            """
            INSERT INTO lead_profile_flags (
                profile_id, contact_id, favorite, favorited_at, favorited_by, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT (profile_id) DO UPDATE SET
                contact_id = COALESCE(EXCLUDED.contact_id, lead_profile_flags.contact_id),
                favorite = 1,
                favorited_at = COALESCE(lead_profile_flags.favorited_at, EXCLUDED.favorited_at),
                favorited_by = EXCLUDED.favorited_by,
                updated_at = EXCLUDED.updated_at
            """,
            (pid, cid, now, actor, now),
        )
    else:
        conn.execute(
            """
            INSERT INTO lead_profile_flags (
                profile_id, contact_id, favorite, favorited_at, favorited_by, updated_at
            ) VALUES (?, ?, 0, NULL, ?, ?)
            ON CONFLICT (profile_id) DO UPDATE SET
                contact_id = COALESCE(EXCLUDED.contact_id, lead_profile_flags.contact_id),
                favorite = 0,
                favorited_at = NULL,
                favorited_by = EXCLUDED.favorited_by,
                updated_at = EXCLUDED.updated_at
            """,
            (pid, cid, actor, now),
        )

    row = conn.execute(
        """
        SELECT profile_id, contact_id, favorite, favorited_at, favorited_by, updated_at
        FROM lead_profile_flags
        WHERE profile_id = ?
        """,
        (pid,),
    ).fetchone()
    return {
        "profileId": row["profile_id"],
        "contactId": row["contact_id"],
        "favorite": bool(row["favorite"]),
        "favoritedAt": row["favorited_at"],
        "favoritedBy": row["favorited_by"],
        "updatedAt": row["updated_at"],
    }


def set_pipeline_status(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    status: str | None,
    actor: str,
    set_by: str = "operator",
    province: str = "BC",
) -> dict[str, Any]:
    """Set or clear the operator/AI-marked pipeline status for a contact.

    Validates the status against the migration 0014 CHECK constraint, writes
    the contacts row, and emits a lifecycle_change event. When the operator
    picks ``closed_seller`` or ``closed_buyer`` from the dropdown, this routes
    through :func:`close_to_admin` so the contact lands on the /admin kanban
    in the same transaction — UI clicks should never leave the contact in a
    half-promoted state.

    Pass ``status=None`` (or any falsy string) to clear the field. AI callers
    must pass ``set_by="ai"``; the operator dropdown passes the default.

    Returns the refreshed contact dict.
    """
    contact = get_contact(conn, contact_id)
    if contact is None:
        raise ValueError(f"contact {contact_id!r} not found")
    if set_by not in _PIPELINE_STATUS_SET_BY:
        raise ValueError(f"invalid set_by {set_by!r}")

    norm = (status or "").strip().lower() or None
    if norm is not None and norm not in _PIPELINE_STATUS_VALUES:
        raise ValueError(f"invalid pipeline_status {status!r}")

    # AI must not overwrite explicit operator marks. The check is here, not
    # in review_contact, so any AI caller respects the precedence rule.
    if set_by == "ai" and contact.get("pipelineStatusSetBy") == "operator":
        if contact.get("pipelineStatus") not in (None, norm):
            return contact  # operator owns this contact's status; no-op

    if norm in ("closed_seller", "closed_buyer"):
        side = "listing" if norm == "closed_seller" else "buyer"
        result = close_to_admin(
            conn,
            contact_id,
            side=side,
            actor=actor,
            province=province,
        )
        # close_to_admin already flips stage='closed'; record the status too
        # so the dropdown shows the right pill on next read.
        now = now_iso()
        conn.execute(
            """
            UPDATE contacts
            SET pipeline_status=?,
                pipeline_status_set_at=?,
                pipeline_status_set_by=?,
                updated_at=?
            WHERE id=?
            """,
            (norm, now, set_by, now, contact_id),
        )
        refreshed = get_contact(conn, contact_id)
        return {**(refreshed or {}), "closedTo": result}

    now = now_iso()
    conn.execute(
        """
        UPDATE contacts
        SET pipeline_status=?,
            pipeline_status_set_at=?,
            pipeline_status_set_by=?,
            updated_at=?
        WHERE id=?
        """,
        (norm, now if norm else None, set_by if norm else None, now, contact_id),
    )
    _events.record_lifecycle(
        conn,
        contact_id=contact_id,
        kind="lifecycle_change",
        actor=actor,
        ts=now,
        payload={"pipelineStatus": norm, "setBy": set_by},
    )
    return get_contact(conn, contact_id) or contact
