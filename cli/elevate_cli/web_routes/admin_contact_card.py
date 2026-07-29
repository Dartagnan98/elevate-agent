"""CRM contact-card routes.

Backs the redesigned single-contact card on /leads: full contact read,
tag/segment editing, pipeline + consent toggles, threaded notes with a
single-pin rule, a Top-25 flag kept in a side table (so the big contacts
row is never touched), and an inline edit-details PATCH.

Follows the ``create_*_router(log)`` factory pattern of the sibling routers
in this package. Every mutation is guarded so a bad payload returns a clean
4xx instead of a 500.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _TagsBody(BaseModel):
    tags: List[str] = []


class _SegmentsBody(BaseModel):
    segments: List[str] = []


class _PipelineBody(BaseModel):
    status: Optional[str] = None


class _ConsentBody(BaseModel):
    call: bool = True
    text: bool = True
    email: bool = True


class _NoteBody(BaseModel):
    body: str
    pinned: bool = False


class _PinBody(BaseModel):
    pinned: bool = True


class _Top25Body(BaseModel):
    on: bool = True


# Valid lead-temperature overrides. Empty string clears the override so the
# contact falls back to the derived (recency/tag-based) temperature.
_TEMPERATURES = {"hot", "warm", "lukewarm", "cool", "soi", "nurture"}


class _TemperatureBody(BaseModel):
    temperature: Optional[str] = None


class _BulkBody(BaseModel):
    # Bulk update across many contacts. action picks the dimension; mode picks
    # the set operation for tags/segments (ignored for pipeline).
    contactIds: List[str] = []
    action: str = ""  # "tags" | "segments" | "pipeline"
    mode: Optional[str] = "add"  # "add" | "replace" | "remove"
    value: Any = None


class _EditDetailsBody(BaseModel):
    # All optional — only provided keys are written.
    displayName: Optional[str] = None
    primaryEmail: Optional[str] = None
    primaryPhone: Optional[str] = None
    buyingTimeFrame: Optional[str] = None
    preQualStatus: Optional[str] = None
    address: Optional[str] = None
    birthday: Optional[str] = None


# camelCase field -> contacts column, for the PATCH builder.
_EDIT_COLUMNS: Dict[str, str] = {
    "displayName": "display_name",
    "primaryEmail": "primary_email",
    "primaryPhone": "primary_phone",
    "buyingTimeFrame": "buying_time_frame",
    "preQualStatus": "pre_qual_status",
    "address": "address",
    "birthday": "birthday",
}


def _ensure_top25_table(conn: Any) -> None:
    """Idempotently create the Top-25 side table. Works on pg + sqlite."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS contact_top25 (contact_id TEXT PRIMARY KEY)"
    )


# Contact items (Tasks / Appointments / Family) backing the card's add feature.
_ITEM_KINDS = {"task", "appointment", "family"}


class _ItemCreateBody(BaseModel):
    kind: str = ""
    title: str = ""
    subtitle: Optional[str] = None
    whenAt: Optional[str] = None


class _ItemPatchBody(BaseModel):
    # All optional — only provided keys are written.
    title: Optional[str] = None
    subtitle: Optional[str] = None
    whenAt: Optional[str] = None
    done: Optional[bool] = None


def _ensure_contact_items_table(conn: Any) -> None:
    """Idempotently create the contact_items side table + index. pg + sqlite.

    Mirrors migration 0037 so the endpoints work even before it runs, exactly
    like the Top-25 helper above. TEXT/INTEGER only for pg+sqlite parity.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS contact_items ("
        "id TEXT PRIMARY KEY, contact_id TEXT NOT NULL, kind TEXT NOT NULL, "
        "title TEXT, subtitle TEXT, when_at TEXT, done INTEGER DEFAULT 0, "
        "created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contact_items_contact_kind "
        "ON contact_items (contact_id, kind)"
    )


def _row_to_item(row: Any) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "subtitle": row["subtitle"],
        "whenAt": row["when_at"],
        "done": bool(row["done"]),
        "createdAt": row["created_at"],
    }


def _is_top25(conn: Any, contact_id: str) -> bool:
    _ensure_top25_table(conn)
    row = conn.execute(
        "SELECT 1 FROM contact_top25 WHERE contact_id=?", (contact_id,)
    ).fetchone()
    return row is not None


def _ensure_temperature_table(conn: Any) -> None:
    """Idempotently create the temperature-override side table. pg + sqlite."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS contact_temperature "
        "(contact_id TEXT PRIMARY KEY, temperature TEXT NOT NULL)"
    )


def _get_temperature(conn: Any, contact_id: str) -> Optional[str]:
    _ensure_temperature_table(conn)
    row = conn.execute(
        "SELECT temperature FROM contact_temperature WHERE contact_id=?",
        (contact_id,),
    ).fetchone()
    if row is None:
        return None
    # Row may be a tuple or a mapping depending on the driver.
    try:
        return row["temperature"]
    except (TypeError, KeyError, IndexError):
        return row[0]


def create_admin_contact_card_router(
    *,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/contacts/{contact_id}")
    def get_contact_card(contact_id: str):
        try:
            from elevate_cli.data import connect, get_contact

            with connect() as conn:
                contact = get_contact(conn, contact_id)
                if contact is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                contact["top25"] = _is_top25(conn, contact_id)
                contact["temperature"] = _get_temperature(conn, contact_id)
                return contact
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/contacts/%s failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Contact card read failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/tags")
    def post_contact_tags(contact_id: str, body: _TagsBody):
        try:
            from elevate_cli.data import connect, get_contact, set_contact_tags

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                # The helper does the strip/dedupe/sort the route used to do.
                set_contact_tags(conn, contact_id, body.tags)
                return get_contact(conn, contact_id)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/tags failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Tag update failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/segments")
    def post_contact_segments(contact_id: str, body: _SegmentsBody):
        try:
            from elevate_cli.data import connect, get_contact
            from elevate_cli.data.contacts import set_contact_segments

            segments = sorted({s.strip() for s in body.segments if s and s.strip()})
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                set_contact_segments(conn, contact_id, segments)
                return get_contact(conn, contact_id)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/segments failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Segment update failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/pipeline")
    def post_contact_pipeline(contact_id: str, body: _PipelineBody):
        try:
            from elevate_cli.data import connect, get_contact, set_pipeline_status

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                return set_pipeline_status(
                    conn,
                    contact_id,
                    status=body.status,
                    actor=web_actor,
                    set_by="operator",
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/pipeline failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Pipeline update failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/consent")
    def post_contact_consent(contact_id: str, body: _ConsentBody):
        try:
            from elevate_cli.data import connect, get_contact, update_contact_details

            # consent=true means the channel is allowed => cannot_* is False.
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                update_contact_details(
                    conn,
                    contact_id,
                    cannot_call=not body.call,
                    cannot_text=not body.text,
                    cannot_email=not body.email,
                )
                return get_contact(conn, contact_id)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/consent failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Consent update failed: {exc}")

    @router.get("/api/admin/contacts/{contact_id}/notes")
    def get_contact_notes(contact_id: str, limit: int = 50):
        try:
            from elevate_cli.data import connect, get_contact, list_notes_for_contact

            safe_limit = max(1, min(200, int(limit)))
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                rows = list_notes_for_contact(conn, contact_id, limit=safe_limit)
            return {"items": rows, "count": len(rows)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/contacts/%s/notes failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Notes read failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/notes")
    def post_contact_note(contact_id: str, body: _NoteBody):
        if not body.body or not body.body.strip():
            raise HTTPException(status_code=400, detail="note body is required")
        try:
            from elevate_cli.data import connect, get_contact, write_note

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                if body.pinned:
                    # Enforce single-pin: clear existing pins first.
                    conn.execute(
                        "UPDATE notes SET pinned=0 WHERE contact_id=? AND pinned=1",
                        (contact_id,),
                    )
                note = write_note(
                    conn,
                    contact_id=contact_id,
                    body=body.body.strip(),
                    author_kind="operator",
                    author_name=web_actor,
                    pinned=body.pinned,
                )
            return note
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/notes failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Note create failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/notes/{note_id}/pin")
    def post_contact_note_pin(contact_id: str, note_id: str, body: _PinBody):
        try:
            from elevate_cli.data import connect, get_contact
            from elevate_cli.data._util import now_iso

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                row = conn.execute(
                    "SELECT id FROM notes WHERE id=? AND contact_id=?",
                    (note_id, contact_id),
                ).fetchone()
                if row is None:
                    raise HTTPException(
                        status_code=404, detail=f"note {note_id!r} not found"
                    )
                now = now_iso()
                if body.pinned:
                    # Single-pin: clear other pins on this contact first.
                    conn.execute(
                        "UPDATE notes SET pinned=0, updated_at=? "
                        "WHERE contact_id=? AND id != ? AND pinned=1",
                        (now, contact_id, note_id),
                    )
                    conn.execute(
                        "UPDATE notes SET pinned=1, updated_at=? WHERE id=?",
                        (now, note_id),
                    )
                else:
                    conn.execute(
                        "UPDATE notes SET pinned=0, updated_at=? WHERE id=?",
                        (now, note_id),
                    )
                out = conn.execute(
                    "SELECT id, pinned FROM notes WHERE id=?", (note_id,)
                ).fetchone()
            return {"id": out["id"], "pinned": bool(out["pinned"])}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception(
                "POST /api/admin/contacts/%s/notes/%s/pin failed", contact_id, note_id
            )
            raise HTTPException(status_code=500, detail=f"Note pin failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/top25")
    def post_contact_top25(contact_id: str, body: _Top25Body):
        try:
            from elevate_cli.data import connect, get_contact

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                _ensure_top25_table(conn)
                if body.on:
                    conn.execute(
                        "INSERT INTO contact_top25(contact_id) VALUES (?) "
                        "ON CONFLICT (contact_id) DO NOTHING",
                        (contact_id,),
                    )
                else:
                    conn.execute(
                        "DELETE FROM contact_top25 WHERE contact_id=?", (contact_id,)
                    )
            return {"contactId": contact_id, "top25": bool(body.on)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/top25 failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Top 25 update failed: {exc}")

    # Bulk read of every manual temperature override, keyed by contact id, so the
    # leads list can reflect overrides on its badges. Distinct path (not under
    # /contacts/{id}) to avoid colliding with the {contact_id} GET route.
    @router.get("/api/admin/contact-temperatures")
    def get_contact_temperatures():
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                _ensure_temperature_table(conn)
                rows = conn.execute(
                    "SELECT contact_id, temperature FROM contact_temperature"
                ).fetchall()
            overrides: Dict[str, str] = {}
            for row in rows:
                try:
                    overrides[row["contact_id"]] = row["temperature"]
                except (TypeError, KeyError, IndexError):
                    overrides[row[0]] = row[1]
            return {"overrides": overrides}
        except Exception as exc:
            _log.exception("GET /api/admin/contact-temperatures failed")
            raise HTTPException(
                status_code=500, detail=f"Temperature overrides read failed: {exc}"
            )

    @router.post("/api/admin/contacts/{contact_id}/temperature")
    def post_contact_temperature(contact_id: str, body: _TemperatureBody):
        try:
            from elevate_cli.data import connect, get_contact

            value = (body.temperature or "").strip().lower()
            if value and value not in _TEMPERATURES:
                raise HTTPException(
                    status_code=400,
                    detail=f"temperature must be one of {sorted(_TEMPERATURES)} or empty",
                )
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                _ensure_temperature_table(conn)
                if value:
                    conn.execute(
                        "INSERT INTO contact_temperature(contact_id, temperature) "
                        "VALUES (?, ?) ON CONFLICT (contact_id) "
                        "DO UPDATE SET temperature=excluded.temperature",
                        (contact_id, value),
                    )
                else:
                    conn.execute(
                        "DELETE FROM contact_temperature WHERE contact_id=?",
                        (contact_id,),
                    )
            return {"contactId": contact_id, "temperature": value or None}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/temperature failed", contact_id)
            raise HTTPException(
                status_code=500, detail=f"Temperature update failed: {exc}"
            )

    @router.post("/api/admin/contacts/bulk")
    def post_contacts_bulk(body: _BulkBody):
        action = (body.action or "").strip().lower()
        if action not in {"tags", "segments", "pipeline"}:
            raise HTTPException(
                status_code=400,
                detail="action must be one of 'tags', 'segments', 'pipeline'",
            )
        contact_ids = [c for c in (body.contactIds or []) if c and str(c).strip()]
        if not contact_ids:
            raise HTTPException(status_code=400, detail="contactIds is required")

        # Normalize the incoming value to a clean list of strings for the
        # tags/segments set-ops; keep the raw value for pipeline.
        def _value_list() -> List[str]:
            v = body.value
            if v is None:
                return []
            raw = v if isinstance(v, list) else [v]
            return [str(x).strip() for x in raw if x is not None and str(x).strip()]

        mode = (body.mode or "add").strip().lower()
        if action in {"tags", "segments"} and mode not in {"add", "replace", "remove"}:
            raise HTTPException(
                status_code=400, detail="mode must be 'add', 'remove', or 'replace'"
            )

        column = "tags_json" if action == "tags" else "segments_json"
        updated = 0
        failed: List[Dict[str, str]] = []

        try:
            from elevate_cli.data import (
                connect,
                get_contact,
                set_contact_tags,
                set_pipeline_status,
            )
            from elevate_cli.data.contacts import set_contact_segments

            # Same pairing as ``column`` above: tags → tags_json writer,
            # anything else (segments) → segments_json writer.
            setter = set_contact_tags if action == "tags" else set_contact_segments
            values = _value_list()
            with connect() as conn:
                for cid in contact_ids:
                    try:
                        if get_contact(conn, cid) is None:
                            failed.append({"contactId": cid, "error": "not found"})
                            continue
                        if action == "pipeline":
                            set_pipeline_status(
                                conn,
                                cid,
                                status=(body.value if body.value else None),
                                actor=web_actor,
                                set_by="operator",
                            )
                        else:
                            row = conn.execute(
                                f"SELECT {column} AS j FROM contacts WHERE id=?", (cid,)
                            ).fetchone()
                            existing: List[str] = []
                            if row is not None and row["j"]:
                                try:
                                    parsed = json.loads(row["j"])
                                    if isinstance(parsed, list):
                                        existing = [str(x) for x in parsed]
                                except (ValueError, TypeError):
                                    existing = []
                            if mode == "replace":
                                merged = set(values)
                            elif mode == "remove":
                                merged = {t for t in existing if t not in set(values)}
                            else:  # add
                                merged = set(existing) | set(values)
                            setter(conn, cid, sorted(t for t in merged if t))
                        updated += 1
                    except Exception as exc:  # per-contact guard, never abort the batch
                        _log.warning("bulk update failed for contact %s: %s", cid, exc)
                        failed.append({"contactId": cid, "error": str(exc)})
            return {"updated": updated, "failed": failed}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/bulk failed")
            raise HTTPException(status_code=500, detail=f"Bulk update failed: {exc}")

    @router.patch("/api/admin/contacts/{contact_id}")
    def patch_contact_card(contact_id: str, body: _EditDetailsBody):
        try:
            from elevate_cli.data import connect, get_contact
            from elevate_cli.data.contacts import update_contact_card_details

            provided = body.model_dump(exclude_unset=True)
            fields: Dict[str, Any] = {
                column: provided[key]
                for key, column in _EDIT_COLUMNS.items()
                if key in provided
            }
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                contact = update_contact_card_details(conn, contact_id, fields)
                contact["top25"] = _is_top25(conn, contact_id)
                contact["temperature"] = _get_temperature(conn, contact_id)
                return contact
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("PATCH /api/admin/contacts/%s failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Contact update failed: {exc}")

    # ── contact items: Tasks / Appointments / Family ─────────────────────
    @router.get("/api/admin/contacts/{contact_id}/items")
    def get_contact_items(contact_id: str, kind: Optional[str] = None):
        try:
            from elevate_cli.data import connect, get_contact

            k = (kind or "").strip().lower() or None
            if k is not None and k not in _ITEM_KINDS:
                raise HTTPException(
                    status_code=400,
                    detail="kind must be one of 'task', 'appointment', 'family'",
                )
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                _ensure_contact_items_table(conn)
                # Ordering: tasks by done then when_at; appointments by when_at;
                # family by created_at. When no kind filter, use a combined order
                # that still keeps each kind sensible (done, when_at, created_at).
                if k == "task":
                    order = "done ASC, when_at IS NULL, when_at ASC, created_at ASC"
                elif k == "appointment":
                    order = "when_at IS NULL, when_at ASC, created_at ASC"
                elif k == "family":
                    order = "created_at ASC"
                else:
                    order = "kind ASC, done ASC, when_at IS NULL, when_at ASC, created_at ASC"
                if k is not None:
                    rows = conn.execute(
                        "SELECT id, contact_id, kind, title, subtitle, when_at, "
                        f"done, created_at, updated_at FROM contact_items "
                        f"WHERE contact_id=? AND kind=? ORDER BY {order}",
                        (contact_id, k),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, contact_id, kind, title, subtitle, when_at, "
                        f"done, created_at, updated_at FROM contact_items "
                        f"WHERE contact_id=? ORDER BY {order}",
                        (contact_id,),
                    ).fetchall()
            return {"items": [_row_to_item(r) for r in rows]}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/contacts/%s/items failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Items read failed: {exc}")

    @router.post("/api/admin/contacts/{contact_id}/items")
    def post_contact_item(contact_id: str, body: _ItemCreateBody):
        kind = (body.kind or "").strip().lower()
        if kind not in _ITEM_KINDS:
            raise HTTPException(
                status_code=400,
                detail="kind must be one of 'task', 'appointment', 'family'",
            )
        title = (body.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        subtitle = (body.subtitle or "").strip() or None
        when_at = (body.whenAt or "").strip() or None
        try:
            from elevate_cli.data import connect, get_contact
            from elevate_cli.data._util import now_iso

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                _ensure_contact_items_table(conn)
                now = now_iso()
                item_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO contact_items "
                    "(id, contact_id, kind, title, subtitle, when_at, done, "
                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (item_id, contact_id, kind, title, subtitle, when_at, 0, now, now),
                )
                row = conn.execute(
                    "SELECT id, contact_id, kind, title, subtitle, when_at, "
                    "done, created_at, updated_at FROM contact_items WHERE id=?",
                    (item_id,),
                ).fetchone()
            return _row_to_item(row)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/contacts/%s/items failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Item create failed: {exc}")

    @router.patch("/api/admin/contacts/{contact_id}/items/{item_id}")
    def patch_contact_item(contact_id: str, item_id: str, body: _ItemPatchBody):
        try:
            from elevate_cli.data import connect, get_contact
            from elevate_cli.data._util import now_iso

            provided = body.model_dump(exclude_unset=True)
            sets: List[str] = []
            params: List[Any] = []
            if "title" in provided:
                sets.append("title=?")
                params.append((provided["title"] or "").strip() or None)
            if "subtitle" in provided:
                sets.append("subtitle=?")
                params.append((provided["subtitle"] or "").strip() or None)
            if "whenAt" in provided:
                sets.append("when_at=?")
                params.append((provided["whenAt"] or "").strip() or None)
            if "done" in provided:
                sets.append("done=?")
                params.append(1 if provided["done"] else 0)
            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                _ensure_contact_items_table(conn)
                exists = conn.execute(
                    "SELECT id FROM contact_items WHERE id=? AND contact_id=?",
                    (item_id, contact_id),
                ).fetchone()
                if exists is None:
                    raise HTTPException(
                        status_code=404, detail=f"item {item_id!r} not found"
                    )
                if sets:
                    sets.append("updated_at=?")
                    params.append(now_iso())
                    params.append(item_id)
                    params.append(contact_id)
                    conn.execute(
                        f"UPDATE contact_items SET {', '.join(sets)} "
                        "WHERE id=? AND contact_id=?",
                        tuple(params),
                    )
                row = conn.execute(
                    "SELECT id, contact_id, kind, title, subtitle, when_at, "
                    "done, created_at, updated_at FROM contact_items WHERE id=?",
                    (item_id,),
                ).fetchone()
            return _row_to_item(row)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception(
                "PATCH /api/admin/contacts/%s/items/%s failed", contact_id, item_id
            )
            raise HTTPException(status_code=500, detail=f"Item update failed: {exc}")

    @router.delete("/api/admin/contacts/{contact_id}/items/{item_id}")
    def delete_contact_item(contact_id: str, item_id: str):
        try:
            from elevate_cli.data import connect, get_contact

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(
                        status_code=404, detail=f"contact {contact_id!r} not found"
                    )
                _ensure_contact_items_table(conn)
                conn.execute(
                    "DELETE FROM contact_items WHERE id=? AND contact_id=?",
                    (item_id, contact_id),
                )
            return {"deleted": True, "id": item_id}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception(
                "DELETE /api/admin/contacts/%s/items/%s failed", contact_id, item_id
            )
            raise HTTPException(status_code=500, detail=f"Item delete failed: {exc}")

    return router
