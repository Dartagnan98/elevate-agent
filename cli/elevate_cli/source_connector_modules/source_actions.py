"""Source inbox state actions."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.connector_state import (
    _blueprint,
    _mutable_source_exists,
)
from elevate_cli.source_connector_modules.connector_views import _candidate_records_for_source
from elevate_cli.source_connector_modules.draft_helpers import (
    _draft_text_for_task,
    _task_key,
    _templated_draft_for_thread,
)
from elevate_cli.source_connector_modules.integration_settings import _as_dict
from elevate_cli.source_connector_modules.source_io import (
    PROFILE_STATUS_VALUES,
    _read_json,
    _read_jsonl_records,
    _read_profile_state,
    _read_source_ui_state,
    _source_dir,
    _write_source_ui_state,
    _write_profile_state,
)
from elevate_cli.source_connector_modules.thread_helpers import (
    _thread_from_record,
    _thread_key,
)


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def update_profile_state(
    profile_id: str,
    status: str | None,
    config: dict[str, Any] | None = None,
    *,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set pipeline status for a profile.

    Writes ``contacts.pipeline_status`` in the operational DB via
    :func:`set_pipeline_status` (migration 0014). Picking
    ``closed_seller`` / ``closed_buyer`` from the dropdown also calls
    :func:`close_to_admin` so the contact lands on /admin in the same
    transaction. By default returns the refreshed /leads response so legacy
    callers can rerender without a second fetch; HTTP routes pass
    ``return_inbox=False`` and build the DB-primary response once.

    Falls back to the legacy ``profile-state.json`` writer when the
    profile is not a contact UUID (e.g. composio thread-derived profiles
    that don't have a contacts row yet); the AI sweep eventually merges
    them, at which point the SQLite path takes over.
    """
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")
    normalized = str(status or "").strip().lower()
    if normalized == "none":
        normalized = ""
    if normalized and normalized not in PROFILE_STATUS_VALUES:
        raise ValueError(f"Unsupported profile status: {status}")

    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()

    # Primary path: write to contacts.pipeline_status in SQLite. The UI
    # passes the source-inbox profile id (e.g. "email:foo@bar.com" or
    # "phone:+15551234567") so we resolve to a contacts row by either UUID
    # or verifier match.
    try:
        from elevate_cli.data import connect, get_contact, set_pipeline_status
        with connect() as conn:
            contact_id: str | None = None
            if get_contact(conn, pid) is not None:
                contact_id = pid
            elif ":" in pid:
                kind, _, value = pid.partition(":")
                kind = kind.strip().lower()
                value = value.strip()
                if value:
                    if kind == "email":
                        row = conn.execute(
                            "SELECT id FROM contacts WHERE LOWER(primary_email) = LOWER(?) LIMIT 1",
                            (value,),
                        ).fetchone()
                    elif kind == "phone":
                        row = conn.execute(
                            "SELECT id FROM contacts WHERE primary_phone = ? LIMIT 1",
                            (value,),
                        ).fetchone()
                    else:
                        row = None
                    if row is not None:
                        contact_id = row["id"]
            if contact_id:
                set_pipeline_status(
                    conn,
                    contact_id,
                    status=normalized or None,
                    actor="operator:leads-ui",
                    set_by="operator",
                )
                return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}
    except ValueError:
        raise
    except Exception:
        # Fall through to the legacy JSON writer if the data module can't
        # accept this profile_id (e.g. composio thread profile without a
        # contacts row yet).
        pass

    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    state = _read_profile_state(source_root)
    profiles = _as_dict(state.get("profiles"))
    if not normalized:
        profiles.pop(pid, None)
    else:
        profiles[pid] = {"status": normalized, "updated_at": source_connectors._now()}
    state["profiles"] = profiles
    _write_profile_state(source_root, state)
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


def update_profile_favorite(
    profile_id: str,
    *,
    favorite: bool,
    contact_id: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set /leads favorite flag for a profile."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")

    from elevate_cli.data import connect, set_lead_profile_favorite

    with connect() as conn:
        set_lead_profile_favorite(
            conn,
            pid,
            favorite=bool(favorite),
            contact_id=contact_id,
            actor="operator:leads-ui",
        )
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


def update_profile_top25(
    profile_id: str,
    *,
    top25: bool,
    contact_id: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set /leads Top 25 flag for a profile (migration 0035)."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")

    from elevate_cli.data import connect, set_lead_profile_top25

    with connect() as conn:
        set_lead_profile_top25(
            conn,
            pid,
            top25=bool(top25),
            contact_id=contact_id,
            actor="operator:leads-ui",
        )
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


def _resolve_profile_contact_id(conn, profile_id: str) -> str | None:
    """Resolve a source-inbox profile id to a contacts row id.

    Same resolution the pipeline-status path uses: a contact UUID passes
    through; ``email:<addr>`` / ``phone:<number>`` match on the verifier.
    """
    from elevate_cli.data import get_contact

    pid = str(profile_id or "").strip()
    if not pid:
        return None
    if get_contact(conn, pid) is not None:
        return pid
    if ":" in pid:
        kind, _, value = pid.partition(":")
        kind = kind.strip().lower()
        value = value.strip()
        if value:
            if kind == "email":
                row = conn.execute(
                    "SELECT id FROM contacts WHERE LOWER(primary_email) = LOWER(?) LIMIT 1",
                    (value,),
                ).fetchone()
            elif kind == "phone":
                row = conn.execute(
                    "SELECT id FROM contacts WHERE primary_phone = ? LIMIT 1",
                    (value,),
                ).fetchone()
            else:
                row = None
            if row is not None:
                return row["id"]
    return None


def update_profile_tags(
    profile_id: str,
    tags: list[str],
    *,
    contact_id: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    """Replace the tag set on the contact behind a /leads profile (migration 0035)."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")

    from elevate_cli.data import connect, set_contact_tags

    with connect() as conn:
        cid = str(contact_id or "").strip() or _resolve_profile_contact_id(conn, pid)
        if not cid:
            raise ValueError(
                "This profile has no contact record yet — tags need a merged contact"
            )
        set_contact_tags(conn, cid, tags)
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


def update_source_thread_state(
    source_id: str,
    thread_id: str,
    action: str,
    config: dict[str, Any] | None = None,
    *,
    return_inbox: bool = True,
) -> JsonRecord:
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    if not _mutable_source_exists(source_root, source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"done", "archive", "restore", "open"}:
        raise ValueError("Unsupported thread action")

    source_dir = _source_dir(source_root, source_id)
    state = _read_source_ui_state(source_dir)
    threads = _as_dict(state.get("threads"))
    if normalized in {"restore", "open"}:
        threads.pop(thread_id, None)
    else:
        threads[thread_id] = {
            "status": "archived" if normalized == "archive" else "done",
            "updated_at": source_connectors._now(),
        }
    state["threads"] = threads
    _write_source_ui_state(source_dir, state)
    try:
        from elevate_cli.data import connect

        db_thread_id = thread_id
        if db_thread_id.startswith(f"{source_id}:"):
            db_thread_id = db_thread_id[len(source_id) + 1:]
        db_status = "open" if normalized in {"restore", "open"} else (
            "archived" if normalized == "archive" else "done"
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET status = ?, updated_at = ?
                WHERE source_id = ? AND thread_key = ?
                """,
                (db_status, source_connectors._now(), source_id, db_thread_id),
            )
    except Exception:
        # Keep the legacy UI-state write available for rows that have not
        # been merged into operational DB yet. DB-primary routes will still
        # show the row until it has a matching conversation to update.
        pass
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


_SOURCE_TO_CHANNEL = {
    "apple-messages": "sms",
    "sms-provider": "sms",
    "android-device": "sms",
    "rcs": "sms",
    "email": "email",
    "social": "social_dm",
    "crm": "crm_note",
}


def _channel_for_source(source_id: str) -> str | None:
    """Return the outbound channel for a source_id, or None if the source has
    no outbound (skills/market-stats/etc are read-only inputs, not channels).
    """
    return _SOURCE_TO_CHANNEL.get(source_id)


def _channel_for_task(source_id: str, task: JsonRecord) -> str | None:
    """Resolve an outbound transport from task evidence without guessing.

    CRM can contain both internal notes and real text/email follow-ups. Route a
    CRM task to an external sender only when its saved channel metadata and
    recipient field agree; otherwise keep it as ``crm_note``, which the sender
    deliberately fails closed until a real CRM-note adapter exists.
    """
    default = _channel_for_source(source_id)
    if source_id != "crm":
        return default
    evidence = " ".join(
        str(task.get(key) or "").strip().lower()
        for key in (
            "channel",
            "template_channel",
            "templateChannel",
            "transport",
            "source",
        )
    )
    phone = task.get("phone") or task.get("recipient_phone") or (task.get("phones") or [None])[0]
    email = task.get("email") or task.get("recipient_email") or (task.get("emails") or [None])[0]
    handle = task.get("social_handle") or task.get("recipient_handle")
    if phone and any(token in evidence for token in ("sms", "text", "imessage", "messages")):
        return "sms"
    if email and any(token in evidence for token in ("email", "gmail", "outlook")):
        return "email"
    if handle and any(token in evidence for token in ("social", "instagram", "facebook", "linkedin", "dm")):
        return "social_dm"
    return default


def _source_view_for_state(source_id: str, source_dir: Path) -> JsonRecord:
    source = _read_json(source_dir / "source.json") or {}
    blueprint = _blueprint(source_id) or {}
    source.setdefault("id", source_id)
    source.setdefault("label", blueprint.get("source") or source_id)
    source.setdefault("source", blueprint.get("source") or source.get("label") or source_id)
    source.setdefault("category", blueprint.get("category") or "messages")
    return source


def _thread_draft_template_state(source_id: str, task_id: str, source_dir: Path) -> JsonRecord:
    prefix = "thread-draft:"
    if not task_id.startswith(prefix):
        return {}
    thread_id = task_id[len(prefix):].strip()
    if not thread_id:
        return {}
    source = _source_view_for_state(source_id, source_dir)
    for record in _candidate_records_for_source(source_dir, source, 5000):
        if _thread_key(record) != thread_id:
            continue
        thread = _thread_from_record(source, record, status="open")
        template_draft = _templated_draft_for_thread(source, thread)
        if not template_draft:
            return {}
        return {
            "draft_text": template_draft.get("draftText"),
            "template_id": template_draft.get("templateId"),
            "template_name": template_draft.get("templateName"),
            "template_channel": template_draft.get("templateChannel"),
            "outreach_lane": template_draft.get("outreachLane"),
        }
    return {}


def _merged_task_record(
    source_dir: Path,
    task_id: str,
    task_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge persisted task evidence with the operator's current UI state."""
    merged: dict[str, Any] = {}
    for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
        if _task_key(record) == task_id:
            merged.update(record)
            break
    for key, value in (task_record or {}).items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def _fire_approve_tick(task_id: str, queue_id: str | None = None) -> None:
    """Dispatch exactly the approved row in the current app process.

    Runs in a daemon thread so the HTTP response isn't blocked on the send
    (10-90s). CRITICAL: this must run inside the Elevate app (dashboard)
    process, where macOS Automation→Messages can be granted — the launchd
    gateway daemon cannot send via Messages (no GUI prompt for Automation), so
    the app must own the actual delivery. Disable with ELEVATE_APPROVE_AUTO_TICK=0.
    """
    if os.getenv("ELEVATE_APPROVE_AUTO_TICK", "1") in ("0", "false", "no"):
        return
    if not queue_id:
        logging.getLogger(__name__).error(
            "approve dispatch skipped for %s: queue id is unavailable",
            task_id,
        )
        return
    import threading

    def _tick() -> None:
        try:
            from elevate_cli import outreach_db as _outreach_db
            from elevate_cli import sender as _sender

            queued = _outreach_db.get_send_by_id(queue_id)
            if (
                queued is not None
                and not _sender.sandbox_enabled()
                and _sender.is_apple_messages_channel(queued.get("channel"))
                and not _sender.apple_messages_outbound_enabled()
            ):
                logging.getLogger(__name__).info(
                    "approve dispatch held for %s: Apple Messages outbound is disabled",
                    task_id,
                )
                return
            claimed = _outreach_db.claim_send_by_id(queue_id)
            if claimed is not None:
                _sender.dispatch_one(claimed)
        except Exception:
            import traceback

            traceback.print_exc()

    threading.Thread(target=_tick, name=f"approve-tick-{str(task_id)[:24]}", daemon=True).start()


def _validate_scheduled_at(scheduled_at: str | None) -> str | None:
    """Normalize a /leads "Send later" timestamp to UTC ISO, or None.

    Rejects unparseable values and moments not in the future — a stale picker
    value must fail loudly, not silently send now.
    """
    raw = str(scheduled_at or "").strip()
    if not raw:
        return None
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid scheduledAt: {scheduled_at!r}")
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    parsed = parsed.astimezone(timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        raise ValueError("scheduledAt must be in the future")
    return parsed.isoformat().replace("+00:00", "Z")


def update_source_task_state(
    source_id: str,
    task_id: str,
    action: str,
    *,
    draft_text: str | None = None,
    scheduled_at: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    if not _mutable_source_exists(source_root, source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"approve", "edit", "skip", "restore", "open"}:
        raise ValueError("Unsupported draft action")
    schedule_for = _validate_scheduled_at(scheduled_at) if normalized == "approve" else None

    source_dir = _source_dir(source_root, source_id)
    state = _read_source_ui_state(source_dir)
    tasks = _as_dict(state.get("tasks"))

    if normalized in {"restore", "open"}:
        tasks.pop(task_id, None)
        state["tasks"] = tasks
        _write_source_ui_state(source_dir, state)
        try:
            from elevate_cli import outreach_db

            outreach_db.restore_skipped_send(source_id, task_id)
        except Exception:
            logging.getLogger(__name__).warning(
                "restore: pending-send restore failed for %s/%s", source_id, task_id,
                exc_info=True,
            )
        return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}

    status = "approved" if normalized == "approve" else "skipped" if normalized == "skip" else "pending"
    existing = _as_dict(tasks.get(task_id))
    existing.update({"status": status, "updated_at": source_connectors._now()})
    # Only overwrite the stored draft when a NON-EMPTY draft is supplied. The
    # /leads Approve button calls this with draftText="" (the api default), and a
    # blanking overwrite here strips the real draft — the send then fails with
    # "messages-native: payload missing draft_text". An explicit empty edit can't
    # be sent anyway, so guarding on truthiness is safe.
    if draft_text:
        existing["draft_text"] = str(draft_text)
    if task_id.startswith("thread-draft:"):
        template_state = _thread_draft_template_state(source_id, task_id, source_dir)
        for key in ("template_id", "template_name", "template_channel", "outreach_lane"):
            if template_state.get(key) and not existing.get(key):
                existing[key] = template_state[key]
        if template_state.get("draft_text") and not existing.get("draft_text"):
            existing["draft_text"] = template_state["draft_text"]
    tasks[task_id] = existing
    state["tasks"] = tasks

    if normalized == "approve":
        # Resolve the real transport before applying the outbound pause. A CRM
        # source may contain an SMS task, and a DB-backed approval row is more
        # authoritative than the source label or sparse ui-state record.
        from elevate_cli import outreach_db
        from elevate_cli import sender

        pending_send = None
        try:
            pending_send = outreach_db.get_pending_send(source_id, task_id)
        except Exception:
            logging.getLogger(__name__).warning(
                "approve: pending-send channel lookup failed for %s/%s",
                source_id,
                task_id,
                exc_info=True,
            )
        approval_channel = (
            str(pending_send.get("channel") or "") if pending_send is not None else ""
        )
        if not approval_channel:
            approval_channel = str(
                _channel_for_task(
                    source_id,
                    _merged_task_record(source_dir, task_id, existing),
                )
                or ""
            )

        # Hold rather than release: no DB mutation, no dispatch thread. The
        # card remains pending until the current profile's outbound setting is
        # enabled again. Inbound import has an independent direction flag.
        if (
            not sender.sandbox_enabled()
            and sender.is_apple_messages_channel(approval_channel)
            and not sender.apple_messages_outbound_enabled(config)
        ):
            existing["status"] = "pending"
            tasks[task_id] = existing
            state["tasks"] = tasks
            _write_source_ui_state(source_dir, state)
            return source_connectors.build_source_inbox_response(config) if return_inbox else {
                "ok": False,
                "held": True,
                "reason": "apple_messages_outbound_disabled",
            }
        # Most /leads drafts are send_queue rows in pending_approval (a cron wrote
        # them straight to the DB), surfaced with id "<source>:send-queue:<id>".
        # For those, approval means RELEASE the existing row to 'queued' so the
        # sender delivers it — NOT insert a fresh source-dir send. Try that first;
        # fall back to the source-dir task path only if there's no pending row.
        flipped = None
        try:
            from elevate_cli import outreach_db

            flipped = outreach_db.approve_pending_send(
                source_id,
                task_id,
                draft_text=draft_text or None,
                scheduled_at=schedule_for,
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "approve: pending-send release failed for %s/%s", source_id, task_id,
                exc_info=True,
            )
        if flipped is not None:
            _write_source_ui_state(source_dir, state)
            # Send NOW, in THIS process. The approve API runs inside the Elevate
            # app (dashboard), which can hold macOS Automation→Messages — the
            # launchd gateway daemon CANNOT (no GUI prompt), so leaving the send
            # to the gateway's periodic tick fails the permission check. Firing
            # here keeps the send in the app context. Best-effort + threaded so
            # the HTTP response isn't blocked.
            #
            # A scheduled send must NOT tick now — the row's next_retry_at holds
            # it and the app's cron-driven /api/sender/tick delivers it later.
            if schedule_for is None:
                _fire_approve_tick(task_id, str(flipped.get("id") or ""))
        else:
            _approve_atomic(
                source_id, task_id, existing, source_dir, state,
                scheduled_at=schedule_for,
            )
    else:
        # An edit (Save) must also land on the underlying send_queue row — where
        # the real outbound payload lives — not just the source-dir UI state, or
        # a later Approve would still send the original template.
        if normalized == "edit" and draft_text:
            try:
                from elevate_cli import outreach_db

                outreach_db.update_pending_send_draft(source_id, task_id, draft_text)
            except Exception:
                logging.getLogger(__name__).warning(
                    "edit: pending-send draft update failed for %s/%s", source_id, task_id,
                    exc_info=True,
                )
        # Skip must ALSO flip the underlying send_queue row out of
        # pending_approval. The Approve queue is built from pending_approval
        # send_queue rows (build_source_inbox_response), NOT from ui-state — so
        # writing only status=skipped here leaves the DB row pending and it
        # reappears on the next refresh (the "Skip does nothing" bug).
        if normalized == "skip":
            try:
                from elevate_cli import outreach_db

                outreach_db.skip_pending_send(source_id, task_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "skip: pending-send skip failed for %s/%s", source_id, task_id,
                    exc_info=True,
                )
        _write_source_ui_state(source_dir, state)

    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


def _approve_atomic(
    source_id: str,
    task_id: str,
    task_record: dict[str, Any],
    source_dir: Path,
    state: dict[str, Any],
    *,
    scheduled_at: str | None = None,
) -> None:
    """Atomically pair: insert send_queue row + flip task status to approved.

    Order: open SQLite IMMEDIATE txn, insert queue row, write UI JSON,
    commit SQLite. If the JSON write fails, the SQLite insert is rolled back.
    Idempotent on (source_id, thread_id, task_id) so repeat clicks don't
    create duplicate sends.

    Sources with no outbound channel (skills, market-stats, etc.) just write
    the JSON state — they can't be sent, only acknowledged.
    """
    from elevate_cli import outreach_db

    # ui-state's task entry is sparse. Merge recipient/channel evidence from
    # tasks.jsonl so the queue payload and the pre-approval kill-switch guard
    # resolve the same transport; current UI values win.
    merged = _merged_task_record(source_dir, task_id, task_record)

    channel = _channel_for_task(source_id, merged)
    if not channel:
        _write_source_ui_state(source_dir, state)
        return

    thread_id = str(merged.get("thread_id") or merged.get("threadId") or task_id)
    if thread_id == task_id and task_id.startswith("thread-draft:"):
        thread_id = task_id.removeprefix("thread-draft:")
    draft_text = str(merged.get("draft_text") or _draft_text_for_task(merged) or "").strip()
    payload = {
        "draft_text": draft_text,
        "recipient": {
            "person_name": merged.get("person_name") or merged.get("personName") or merged.get("display_name"),
            "contact_id": merged.get("contact_id"),
            "conversation_id": merged.get("conversation_id") or merged.get("source_record_id"),
            "phone": merged.get("phone") or merged.get("recipient_phone") or (merged.get("phones") or [None])[0],
            "email": merged.get("email") or merged.get("recipient_email") or (merged.get("emails") or [None])[0],
            "social_handle": merged.get("social_handle") or merged.get("recipient_handle"),
        },
        "channel_meta": {
            "toolkit": merged.get("toolkit"),
            "account_id": merged.get("composio_account_id"),
        },
        "source_id": source_id,
        "thread_id": thread_id,
        "task_id": task_id,
    }
    attempt_id = merged.get("attempt_id") or merged.get("attemptId")
    template_id = merged.get("template_id") or merged.get("templateId")
    outreach_lane = merged.get("outreach_lane") or merged.get("outreachLane") or merged.get("lane")
    if template_id:
        payload["template_id"] = template_id
        payload["templateId"] = template_id
    if outreach_lane:
        payload["outreach_lane"] = outreach_lane
        payload["outreachLane"] = outreach_lane

    with outreach_db.connect() as conn:
        with outreach_db.transaction(conn):
            if template_id and not attempt_id:
                try:
                    attempt_id = outreach_db.record_use_in_transaction(
                        conn,
                        str(template_id),
                        lane=str(outreach_lane or "new-outreach"),
                        source_id=source_id,
                        thread_id=thread_id,
                        task_id=task_id,
                    )
                    task_record["attempt_id"] = attempt_id
                except Exception:
                    attempt_id = None
            if attempt_id:
                payload["attempt_id"] = attempt_id
                payload["attemptId"] = attempt_id
            queued_send = outreach_db.enqueue_send(
                conn,
                source_id=source_id,
                thread_id=thread_id,
                task_id=task_id,
                channel=channel,
                payload=payload,
                attempt_id=attempt_id,
                next_retry_at=scheduled_at,
            )
            _write_source_ui_state(source_dir, state)

    # Dispatch only the row created/reused by this explicit approval. A global
    # tick could claim an older unrelated lead. A scheduled send is held by its
    # next_retry_at and delivered by the app's cron-driven sender tick instead.
    if scheduled_at is None:
        _fire_approve_tick(task_id, str((queued_send or {}).get("id") or ""))
