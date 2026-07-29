"""Contact lifecycle, conflict, and signal routes."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _ContactClassifyBody(BaseModel):
    type: str  # 'buyer' | 'listing' | 'other'


class _ContactParkBody(BaseModel):
    reason: str


class _ConflictResolveBody(BaseModel):
    resolution: str  # 'merged_into:<contact_id>' | 'kept_separate' | 'discarded'


class _SignalGraduateBody(BaseModel):
    contactId: str


_ADMIN_CONTACTS_TAB_FILTERS = {
    "all": {},
    "buyers": {"type": "buyer"},
    "listings": {"type": "listing"},
    "parked": {"stage": "parked"},
    "dormant": {"stage": "dormant"},
    "dead": {"stage": "dead"},
}


def create_admin_contacts_router(
    *,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.post("/api/contacts/{contact_id}/classify")
    def post_contact_classify(contact_id: str, body: _ContactClassifyBody):
        try:
            from elevate_cli.data import classify_contact, connect, get_contact

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
                return classify_contact(conn, contact_id, body.type, actor=web_actor)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/contacts/%s/classify failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Classify failed: {exc}")

    @router.post("/api/contacts/{contact_id}/park")
    def post_contact_park(contact_id: str, body: _ContactParkBody):
        if not body.reason or not body.reason.strip():
            raise HTTPException(status_code=400, detail="reason is required")
        try:
            from elevate_cli.data import connect, get_contact, park_contact

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
                return park_contact(conn, contact_id, body.reason.strip(), actor=web_actor)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/contacts/%s/park failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Park failed: {exc}")

    @router.post("/api/contacts/{contact_id}/unpark")
    def post_contact_unpark(contact_id: str):
        try:
            from elevate_cli.data import connect, get_contact, unpark_contact

            with connect() as conn:
                if get_contact(conn, contact_id) is None:
                    raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
                return unpark_contact(conn, contact_id, actor=web_actor)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/contacts/%s/unpark failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Unpark failed: {exc}")

    @router.delete("/api/admin/contacts/{contact_id}")
    def delete_admin_contact(contact_id: str):
        """Permanently delete a lead/contact and all their data (Skyleigh 2026-07-17:
        hard delete, not archive). Most child tables are ON DELETE CASCADE; a few
        (events_summary, lead_signals) and the FK-less contact_items/contact_top25
        plus send_queue rows (matched by payload contact_id) are cleared first."""
        import json as _json

        try:
            from elevate_cli.data import connect, get_contact

            with connect() as conn:
                existing = get_contact(conn, contact_id)
                if existing is None:
                    raise HTTPException(status_code=404, detail=f"contact {contact_id!r} not found")
                name = existing.get("display_name") or contact_id
                deleted: dict[str, int] = {}

                def _sp(label: str, sql: str, params: tuple) -> None:
                    # Run one cleanup statement inside a savepoint so a single
                    # failure (missing table/column on some install) rolls back
                    # just that statement instead of aborting the whole delete.
                    conn.execute("SAVEPOINT sp_del")
                    try:
                        cur = conn.execute(sql, params)
                        deleted[label] = getattr(cur, "rowcount", 0) or 0
                        conn.execute("RELEASE SAVEPOINT sp_del")
                    except Exception:
                        conn.execute("ROLLBACK TO SAVEPOINT sp_del")
                        _log.debug("delete_contact: %s cleanup skipped", label, exc_info=True)

                # Blockers (FK NO ACTION) + FK-less tables -> clear first.
                # events_summary/contact_items/contact_top25 key on contact_id;
                # lead_signals references via graduated_to_contact_id (null it so
                # the lead-gen signal row survives, just unlinked).
                _sp("events_summary", "DELETE FROM events_summary WHERE contact_id=?", (contact_id,))
                _sp("contact_items", "DELETE FROM contact_items WHERE contact_id=?", (contact_id,))
                _sp("contact_top25", "DELETE FROM contact_top25 WHERE contact_id=?", (contact_id,))
                _sp("lead_signals", "UPDATE lead_signals SET graduated_to_contact_id=NULL WHERE graduated_to_contact_id=?", (contact_id,))
                # events.conversation_id -> conversations is a NO-ACTION FK
                # (fk_events_2), so cascading the contact delete into its
                # conversations is blocked while any event still points at them.
                # Clear those events first. (The contact's own events cascade via
                # fk_events_1 anyway; this also catches any cross-referenced ones.)
                _sp(
                    "events_by_conversation",
                    "DELETE FROM events WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE contact_id=?)",
                    (contact_id,),
                )

                # send_queue has no contact_id column: match on payload's contact_id.
                try:
                    sq = conn.execute(
                        "SELECT id, payload_json FROM send_queue WHERE payload_json LIKE ?",
                        (f'%{contact_id}%',),
                    ).fetchall()
                    sq_ids = []
                    for r in sq:
                        try:
                            p = _json.loads(r["payload_json"] or "{}")
                        except Exception:
                            p = {}
                        rec = p.get("recipient") if isinstance(p.get("recipient"), dict) else {}
                        if p.get("contact_id") == contact_id or rec.get("contact_id") == contact_id:
                            sq_ids.append(r["id"])
                    for sid in sq_ids:
                        conn.execute("DELETE FROM send_queue WHERE id=?", (sid,))
                    deleted["send_queue"] = len(sq_ids)
                except Exception:
                    _log.debug("delete_contact: send_queue cleanup skipped", exc_info=True)

                # The contact row itself. FK CASCADE removes conversations, notes,
                # identities, events, lead_inquiries/properties, deal_contacts,
                # pcs_*; deals.primary_contact_id / agent_handoffs are SET NULL.
                cur = conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
                deleted["contacts"] = getattr(cur, "rowcount", 0) or 0
                conn.commit()

                _log.info("delete_admin_contact %s (%s) -> %s by %s", contact_id, name, deleted, web_actor)
                return {"ok": True, "deletedContactId": contact_id, "name": name, "deleted": deleted}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("DELETE /api/admin/contacts/%s failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    @router.get("/api/contacts/active")
    def get_contacts_active(limit: int = 100):
        try:
            from elevate_cli.data import connect, find_contacts

            safe_limit = max(1, min(500, int(limit)))
            with connect() as conn:
                rows = find_contacts(
                    conn,
                    stage_in=("first_touched", "active"),
                    limit=safe_limit,
                )
            return {"items": rows, "count": len(rows)}
        except Exception as exc:
            _log.exception("GET /api/contacts/active failed")
            raise HTTPException(status_code=500, detail=f"Active contacts failed: {exc}")

    @router.get("/api/admin/contacts")
    def get_admin_contacts(
        type: Optional[str] = None,
        stage: Optional[str] = None,
        tab: Optional[str] = None,
        lastActivityAfter: Optional[str] = None,
        hasOpenConflict: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, find_contacts

            kwargs: Dict[str, Any] = {}
            if tab:
                tab_filter = _ADMIN_CONTACTS_TAB_FILTERS.get(tab.lower())
                if tab_filter is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"unknown tab {tab!r} (expected one of {sorted(_ADMIN_CONTACTS_TAB_FILTERS)})",
                    )
                kwargs.update(tab_filter)
            if type is not None:
                kwargs["type"] = type
            if stage is not None:
                kwargs["stage"] = stage
            if hasOpenConflict is not None:
                kwargs["has_open_conflict"] = hasOpenConflict
            if lastActivityAfter is not None:
                kwargs["last_activity_after"] = lastActivityAfter
            kwargs["limit"] = max(1, min(500, int(limit)))
            kwargs["offset"] = max(0, int(offset))

            with connect() as conn:
                rows = find_contacts(conn, **kwargs)
            return {"items": rows, "count": len(rows), "tab": tab, "limit": kwargs["limit"], "offset": kwargs["offset"]}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/contacts failed")
            raise HTTPException(status_code=500, detail=f"Admin contacts failed: {exc}")

    @router.get("/api/admin/conflicts")
    def get_admin_conflicts():
        try:
            from elevate_cli.data import connect, list_open_conflicts

            with connect() as conn:
                rows = list_open_conflicts(conn)
            return {"items": rows, "count": len(rows)}
        except Exception as exc:
            _log.exception("GET /api/admin/conflicts failed")
            raise HTTPException(status_code=500, detail=f"Admin conflicts failed: {exc}")

    @router.post("/api/admin/conflicts/{conflict_id}/resolve")
    def post_admin_conflict_resolve(conflict_id: str, body: _ConflictResolveBody):
        try:
            from elevate_cli.data import connect, resolve_identity_conflict

            with connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM identity_conflicts WHERE id=?", (conflict_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail=f"conflict {conflict_id!r} not found")
                return resolve_identity_conflict(
                    conn, conflict_id, resolution=body.resolution, actor=web_actor
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/conflicts/%s/resolve failed", conflict_id)
            raise HTTPException(status_code=500, detail=f"Resolve conflict failed: {exc}")

    @router.get("/api/admin/signals")
    def get_admin_signals(sourceId: Optional[str] = None, limit: int = 200):
        try:
            from elevate_cli.data import connect, list_open_signals

            safe_limit = max(1, min(500, int(limit)))
            with connect() as conn:
                rows = list_open_signals(conn, source_id=sourceId, limit=safe_limit)
            return {"items": rows, "count": len(rows)}
        except Exception as exc:
            _log.exception("GET /api/admin/signals failed")
            raise HTTPException(status_code=500, detail=f"Admin signals failed: {exc}")

    @router.post("/api/admin/signals/{signal_id}/graduate")
    def post_admin_signal_graduate(signal_id: str, body: _SignalGraduateBody):
        if not body.contactId or not body.contactId.strip():
            raise HTTPException(status_code=400, detail="contactId is required")
        try:
            from elevate_cli.data import (
                connect,
                get_contact,
                get_lead_signal,
                graduate_lead_signal,
            )

            with connect() as conn:
                if get_lead_signal(conn, signal_id) is None:
                    raise HTTPException(status_code=404, detail=f"signal {signal_id!r} not found")
                if get_contact(conn, body.contactId) is None:
                    raise HTTPException(status_code=404, detail=f"contact {body.contactId!r} not found")
                return graduate_lead_signal(
                    conn, signal_id, contact_id=body.contactId, actor=web_actor
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/signals/%s/graduate failed", signal_id)
            raise HTTPException(status_code=500, detail=f"Graduate signal failed: {exc}")

    return router
