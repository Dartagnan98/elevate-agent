"""Core source-inbox routes."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from elevate_cli.web_routes.source_inbox_debug import with_source_inbox_debug


class SourceInboxThreadAction(BaseModel):
    action: str
    returnInbox: bool = True
    sourceId: str
    threadId: str


class SourceInboxDraftAction(BaseModel):
    action: str
    returnInbox: bool = True
    sourceId: str
    taskId: str
    draftText: str = ""
    scheduledAt: str | None = None


class SourceInboxProfileAction(BaseModel):
    profileId: str
    returnInbox: bool = True
    status: str | None = None


class SourceInboxFavoriteAction(BaseModel):
    profileId: str
    favorite: bool
    contactId: str | None = None
    returnInbox: bool = True


class SourceInboxTop25Action(BaseModel):
    profileId: str
    top25: bool
    contactId: str | None = None
    returnInbox: bool = True


class SourceInboxTagsAction(BaseModel):
    profileId: str
    tags: list[str]
    contactId: str | None = None
    returnInbox: bool = True


class SourceInboxNoteCreate(BaseModel):
    contactId: str
    body: str


class SourceInboxNotePin(BaseModel):
    noteId: str
    pinned: bool


class SearchCriteriaUpdate(BaseModel):
    contactId: str
    criteria: dict | None = None


class AccountGoalsUpdate(BaseModel):
    leadsGoal: int | None = None
    apptsGoal: int | None = None
    closingsGoal: int | None = None
    gciGoal: int | None = None


class LeadCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    type: str | None = None


class ContactDetailsUpdate(BaseModel):
    contactId: str
    displayName: str | None = None
    primaryEmail: str | None = None
    primaryPhone: str | None = None
    type: str | None = None
    cannotText: bool | None = None
    cannotCall: bool | None = None
    cannotEmail: bool | None = None
    customFields: dict[str, str] | None = None


class ContactTaskCreate(BaseModel):
    contactId: str
    title: str
    dueLabel: str | None = None


class ContactTaskStatus(BaseModel):
    taskId: str
    status: str


class CrmColumnsUpdate(BaseModel):
    columns: list[dict]


_SOURCE_INBOX_ACTION_LIMIT = 500


def register_source_inbox_routes(router: APIRouter, *, log: logging.Logger) -> None:
    def _source_inbox_response(limit: int = _SOURCE_INBOX_ACTION_LIMIT, *, debug: bool = False):
        from elevate_cli.source_connectors import build_source_inbox_response
        from elevate_cli.data import db_source_inbox_response

        try:
            payload = db_source_inbox_response(limit=limit)
            return with_source_inbox_debug(payload, read_path="db") if debug else payload
        except Exception as exc:
            log.exception(
                "db_source_inbox_response failed, falling back to JSONL source inbox"
            )
            payload = build_source_inbox_response(limit=limit)
            return (
                with_source_inbox_debug(payload, read_path="jsonl", fallback_error=exc)
                if debug
                else payload
            )

    @router.get("/api/source-inbox")
    async def get_source_inbox(limit: int = 16, debug: bool = False):
        try:
            return _source_inbox_response(limit=limit, debug=debug)
        except Exception:
            log.exception("GET /api/source-inbox failed")
            raise HTTPException(status_code=500, detail="source_inbox_unavailable")

    @router.get("/api/source-inbox/thread/{source_id}/{thread_id}")
    async def get_source_inbox_thread(source_id: str, thread_id: str, limit: int = 200):
        try:
            from elevate_cli.source_connectors import build_thread_context_response
            from elevate_cli.data import db_thread_context_response

            # DB is the source of truth for lead cards (Lead Score, Notes,
            # Property Activity, Send History all key off contacts.id +
            # events.contact_id). The legacy JSONL reader pulls a thin
            # slice — last 4000 lead-events globally, contacts.jsonl rows
            # only — and silently returns empty cards for any Lofty lead
            # whose enrichment didn't make it into the tail window. Prefer
            # the DB path; fall back to JSONL only on real DB errors so
            # the drawer never blanks out.
            try:
                return db_thread_context_response(
                    source_id, thread_id, limit=limit
                )
            except ValueError:
                # Unknown source connector — propagate as 404.
                raise
            except Exception:
                log.exception(
                    "db_thread_context_response failed, falling back to JSONL for %s/%s",
                    source_id,
                    thread_id,
                )
                return build_thread_context_response(
                    source_id, thread_id, limit=limit
                )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            log.exception("GET /api/source-inbox/thread/%s/%s failed", source_id, thread_id)
            raise HTTPException(status_code=500, detail=f"Thread context failed: {exc}")

    @router.post("/api/source-inbox/thread")
    async def update_source_inbox_thread(body: SourceInboxThreadAction):
        try:
            from elevate_cli.source_connectors import update_source_thread_state

            update_source_thread_state(
                body.sourceId,
                body.threadId,
                body.action,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/thread failed")
            raise HTTPException(status_code=500, detail=f"Source inbox update failed: {exc}")

    @router.post("/api/source-inbox/profile")
    async def update_source_inbox_profile(body: SourceInboxProfileAction):
        try:
            from elevate_cli.source_connectors import update_profile_state

            update_profile_state(
                body.profileId,
                body.status,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/profile failed")
            raise HTTPException(status_code=500, detail=f"Profile update failed: {exc}")

    @router.post("/api/source-inbox/profile/favorite")
    async def update_source_inbox_profile_favorite(body: SourceInboxFavoriteAction):
        try:
            from elevate_cli.source_connectors import update_profile_favorite

            update_profile_favorite(
                body.profileId,
                favorite=body.favorite,
                contact_id=body.contactId,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/profile/favorite failed")
            raise HTTPException(status_code=500, detail=f"Favorite update failed: {exc}")

    @router.post("/api/source-inbox/draft")
    async def update_source_inbox_draft(body: SourceInboxDraftAction):
        try:
            from elevate_cli.source_connectors import update_source_task_state

            update_source_task_state(
                body.sourceId,
                body.taskId,
                body.action,
                draft_text=body.draftText,
                scheduled_at=body.scheduledAt,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/draft failed")
            raise HTTPException(status_code=500, detail=f"Source draft update failed: {exc}")

    @router.post("/api/source-inbox/profile/top25")
    async def update_source_inbox_profile_top25(body: SourceInboxTop25Action):
        try:
            from elevate_cli.source_connectors import update_profile_top25

            update_profile_top25(
                body.profileId,
                top25=body.top25,
                contact_id=body.contactId,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/profile/top25 failed")
            raise HTTPException(status_code=500, detail=f"Top 25 update failed: {exc}")

    @router.post("/api/source-inbox/profile/tags")
    async def update_source_inbox_profile_tags(body: SourceInboxTagsAction):
        try:
            from elevate_cli.source_connectors import update_profile_tags

            update_profile_tags(
                body.profileId,
                body.tags,
                contact_id=body.contactId,
                return_inbox=False,
            )
            if not body.returnInbox:
                return {"ok": True}
            return _source_inbox_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/profile/tags failed")
            raise HTTPException(status_code=500, detail=f"Tags update failed: {exc}")

    @router.get("/api/source-inbox/notes/{contact_id}")
    async def get_source_inbox_notes(contact_id: str, limit: int = 100):
        try:
            from elevate_cli.data import connect, list_notes_for_contact

            with connect() as conn:
                notes = list_notes_for_contact(conn, contact_id, limit=limit)
            return {"notes": notes}
        except Exception as exc:
            log.exception("GET /api/source-inbox/notes/%s failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Notes read failed: {exc}")

    @router.post("/api/source-inbox/note")
    async def create_source_inbox_note(body: SourceInboxNoteCreate):
        try:
            text = str(body.body or "").strip()
            if not text:
                raise ValueError("note body is required")
            from elevate_cli.data import connect, write_note

            with connect() as conn:
                note = write_note(
                    conn,
                    contact_id=body.contactId,
                    body=text,
                    author_kind="operator",
                    author_name="operator:leads-ui",
                    daily_cap=False,
                )
            return {"ok": True, "note": note}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/note failed")
            raise HTTPException(status_code=500, detail=f"Note create failed: {exc}")

    @router.post("/api/source-inbox/note/pin")
    async def pin_source_inbox_note(body: SourceInboxNotePin):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data._util import now_iso

            with connect() as conn:
                row = conn.execute(
                    "SELECT id, contact_id FROM notes WHERE id = ? AND deleted = 0",
                    (body.noteId,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"note {body.noteId!r} not found")
                if body.pinned:
                    # Single pin per contact: pinning one unpins the rest.
                    conn.execute(
                        "UPDATE notes SET pinned = 0, updated_at = ? "
                        "WHERE contact_id = ? AND pinned = 1",
                        (now_iso(), row["contact_id"]),
                    )
                conn.execute(
                    "UPDATE notes SET pinned = ?, updated_at = ? WHERE id = ?",
                    (1 if body.pinned else 0, now_iso(), body.noteId),
                )
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/note/pin failed")
            raise HTTPException(status_code=500, detail=f"Note pin failed: {exc}")

    @router.post("/api/source-inbox/search-criteria")
    async def update_search_criteria(body: SearchCriteriaUpdate):
        try:
            from elevate_cli.data import connect, set_contact_search_criteria

            with connect() as conn:
                set_contact_search_criteria(conn, body.contactId, body.criteria)
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/search-criteria failed")
            raise HTTPException(status_code=500, detail=f"Search criteria update failed: {exc}")

    @router.post("/api/source-inbox/lead")
    async def create_source_inbox_lead(body: LeadCreate):
        try:
            name = str(body.name or "").strip()
            email = str(body.email or "").strip()
            phone = str(body.phone or "").strip()
            if not name and not email and not phone:
                raise ValueError("A name, email, or phone is required")
            contact_type = str(body.type or "unclassified").strip().lower()
            if contact_type not in {"unclassified", "buyer", "listing", "other"}:
                raise ValueError(f"invalid lead type {body.type!r}")
            import uuid as _uuid

            from elevate_cli.data import connect, upsert_contact

            with connect() as conn:
                contact = upsert_contact(
                    conn,
                    display_name=name or None,
                    primary_email=email or None,
                    primary_phone=phone or None,
                    type=contact_type,
                    source_key=f"manual:{_uuid.uuid4().hex}",
                )
            return {"ok": True, "contact": contact}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/lead failed")
            raise HTTPException(status_code=500, detail=f"Lead create failed: {exc}")

    @router.post("/api/source-inbox/contact")
    async def update_source_inbox_contact(body: ContactDetailsUpdate):
        try:
            from elevate_cli.data import connect, update_contact_details

            with connect() as conn:
                contact = update_contact_details(
                    conn,
                    body.contactId,
                    display_name=body.displayName,
                    primary_email=body.primaryEmail,
                    primary_phone=body.primaryPhone,
                    type=body.type,
                    cannot_text=body.cannotText,
                    cannot_call=body.cannotCall,
                    cannot_email=body.cannotEmail,
                    custom_fields=body.customFields,
                )
            return {"ok": True, "contact": contact}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/contact failed")
            raise HTTPException(status_code=500, detail=f"Contact update failed: {exc}")

    @router.post("/api/source-inbox/task")
    async def create_source_inbox_task(body: ContactTaskCreate):
        try:
            title = str(body.title or "").strip()
            if not title:
                raise ValueError("task title is required")
            import hashlib as _hashlib
            import json as _json
            import uuid as _uuid

            from elevate_cli.data import connect, get_contact
            from elevate_cli.data._util import now_iso

            with connect() as conn:
                if get_contact(conn, body.contactId) is None:
                    raise ValueError(f"contact {body.contactId!r} not found")
                event_id = _uuid.uuid4().hex
                payload = {
                    "legacy_type": "crm_task",
                    "title": title,
                    "summary": str(body.dueLabel or "").strip(),
                    "status": "open",
                }
                conn.execute(
                    """
                    INSERT INTO events
                        (id, contact_id, kind, source_id, actor, payload_json,
                         ts, event_hash)
                    VALUES (?, ?, 'pcs_activity', 'crm', 'operator:leads-ui', ?, ?, ?)
                    """,
                    (
                        event_id,
                        body.contactId,
                        _json.dumps(payload, ensure_ascii=False),
                        now_iso(),
                        _hashlib.sha256(event_id.encode()).hexdigest(),
                    ),
                )
            return {"ok": True, "taskId": event_id}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/task failed")
            raise HTTPException(status_code=500, detail=f"Task create failed: {exc}")

    @router.get("/api/source-inbox/tasks/{contact_id}")
    async def get_source_inbox_tasks(contact_id: str, limit: int = 200):
        try:
            import json as _json

            from elevate_cli.data import connect

            with connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, payload_json, ts
                    FROM events
                    WHERE contact_id = ? AND kind = 'pcs_activity'
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (contact_id, max(1, min(int(limit or 200), 500))),
                ).fetchall()
            tasks = []
            for row in rows:
                try:
                    payload = _json.loads(row["payload_json"] or "{}")
                except (ValueError, TypeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if (payload.get("legacy_type") or payload.get("legacyType")) != "crm_task":
                    continue
                tasks.append({
                    "id": row["id"],
                    "title": payload.get("title") or "Task",
                    "summary": payload.get("summary") or "",
                    "status": payload.get("status") or "open",
                    "dueAt": payload.get("dueAt") or payload.get("due_at"),
                    "timestamp": row["ts"],
                })
            return {"tasks": tasks}
        except Exception as exc:
            log.exception("GET /api/source-inbox/tasks/%s failed", contact_id)
            raise HTTPException(status_code=500, detail=f"Tasks read failed: {exc}")

    @router.post("/api/source-inbox/task/status")
    async def update_source_inbox_task_status(body: ContactTaskStatus):
        try:
            status = str(body.status or "").strip().lower()
            if status not in {"open", "done"}:
                raise ValueError(f"invalid task status {body.status!r}")
            import json as _json

            from elevate_cli.data import connect
            from elevate_cli.data._util import now_iso

            with connect() as conn:
                row = conn.execute(
                    "SELECT id, payload_json FROM events WHERE id = ?",
                    (body.taskId,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"task {body.taskId!r} not found")
                try:
                    payload = _json.loads(row["payload_json"] or "{}")
                except (ValueError, TypeError):
                    payload = {}
                if not isinstance(payload, dict) or (
                    (payload.get("legacy_type") or payload.get("legacyType"))
                    != "crm_task"
                ):
                    raise ValueError("event is not a CRM task")
                payload["status"] = status
                payload["status_updated_at"] = now_iso()
                conn.execute(
                    "UPDATE events SET payload_json = ? WHERE id = ?",
                    (_json.dumps(payload, ensure_ascii=False), body.taskId),
                )
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("POST /api/source-inbox/task/status failed")
            raise HTTPException(status_code=500, detail=f"Task status update failed: {exc}")

    @router.get("/api/crm/columns")
    async def get_crm_columns():
        try:
            import json as _json

            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT custom_columns_json FROM crm_settings WHERE id = 'default'",
                ).fetchone()
            columns: list[dict] = []
            if row is not None and row["custom_columns_json"]:
                try:
                    parsed = _json.loads(row["custom_columns_json"])
                    if isinstance(parsed, list):
                        columns = [c for c in parsed if isinstance(c, dict) and c.get("key")]
                except (ValueError, TypeError):
                    columns = []
            return {"columns": columns}
        except Exception as exc:
            log.exception("GET /api/crm/columns failed")
            raise HTTPException(status_code=500, detail=f"Columns read failed: {exc}")

    @router.put("/api/crm/columns")
    async def put_crm_columns(body: CrmColumnsUpdate):
        try:
            import json as _json
            import re as _re

            from elevate_cli.data import connect
            from elevate_cli.data._util import now_iso

            cleaned: list[dict] = []
            seen: set[str] = set()
            for column in body.columns:
                label = str(column.get("label") or "").strip()
                if not label:
                    continue
                key = str(column.get("key") or "").strip() or _re.sub(
                    r"[^a-z0-9]+", "_", label.lower()
                ).strip("_")
                if not key or key in seen:
                    continue
                seen.add(key)
                cleaned.append({"key": key, "label": label})
            if len(cleaned) > 12:
                raise ValueError("A maximum of 12 custom columns is supported")
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO crm_settings (id, custom_columns_json, updated_at)
                    VALUES ('default', ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        custom_columns_json = EXCLUDED.custom_columns_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (_json.dumps(cleaned, ensure_ascii=False), now_iso()),
                )
            return {"ok": True, "columns": cleaned}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("PUT /api/crm/columns failed")
            raise HTTPException(status_code=500, detail=f"Columns update failed: {exc}")

    @router.get("/api/crm/goals")
    async def get_account_goals():
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT leads_goal, appts_goal, closings_goal, gci_goal, updated_at "
                    "FROM account_goals WHERE id = 'default'",
                ).fetchone()
            if row is None:
                return {
                    "leadsGoal": None,
                    "apptsGoal": None,
                    "closingsGoal": None,
                    "gciGoal": None,
                    "updatedAt": None,
                }
            return {
                "leadsGoal": row["leads_goal"],
                "apptsGoal": row["appts_goal"],
                "closingsGoal": row["closings_goal"],
                "gciGoal": row["gci_goal"],
                "updatedAt": row["updated_at"],
            }
        except Exception as exc:
            log.exception("GET /api/crm/goals failed")
            raise HTTPException(status_code=500, detail=f"Goals read failed: {exc}")

    @router.put("/api/crm/goals")
    async def put_account_goals(body: AccountGoalsUpdate):
        try:
            for label, value in (
                ("leadsGoal", body.leadsGoal),
                ("apptsGoal", body.apptsGoal),
                ("closingsGoal", body.closingsGoal),
                ("gciGoal", body.gciGoal),
            ):
                if value is not None and value < 0:
                    raise ValueError(f"{label} must be >= 0")
            from elevate_cli.data import connect
            from elevate_cli.data._util import now_iso

            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO account_goals
                        (id, leads_goal, appts_goal, closings_goal, gci_goal, updated_at)
                    VALUES ('default', ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        leads_goal = EXCLUDED.leads_goal,
                        appts_goal = EXCLUDED.appts_goal,
                        closings_goal = EXCLUDED.closings_goal,
                        gci_goal = EXCLUDED.gci_goal,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        body.leadsGoal,
                        body.apptsGoal,
                        body.closingsGoal,
                        body.gciGoal,
                        now_iso(),
                    ),
                )
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("PUT /api/crm/goals failed")
            raise HTTPException(status_code=500, detail=f"Goals update failed: {exc}")
