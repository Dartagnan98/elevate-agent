"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.config import (
    get_config_path,
    get_elevate_home,
    get_env_path,
    load_config,
    load_env,
    save_config,
    save_env_value,
)
from elevate_cli.source_connector_modules.prompts import (
    _local_counts_command,
    _local_python_prefix,
    _local_sync_command,
    _render_apple_messages_agent_prompt,
    _render_buyer_brief_agent_prompt,
    _render_crm_prompt,
    _render_social_agent_prompt,
    _render_xposure_pcs_agent_prompt,
    _render_xposure_pcs_views_agent_prompt,
    _source_file_count_commands,
    source_prompt_for,
)


JsonRecord = dict[str, Any]

from elevate_cli.source_connector_modules.source_catalog import (
    AGENT_SESSION_SOURCE_IDS,
    COMPOSIO_SOCIAL_CONTRACT,
    CONNECTION_CONTRACT,
    JSONL_FILES,
    OWNER_BY_SOURCE,
    SERVER_INLINE_SOURCE_IDS,
    SOURCE_CATEGORIES,
    SOURCE_CONNECTION_BLUEPRINTS,
    SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
    SOURCE_PROMPT_CATEGORIES,
    UI_BY_SOURCE,
    WIRED_SOURCE_IDS,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


from elevate_cli.source_connector_modules.source_io import (
    PROFILE_STATUS_VALUES,
    _JSONL_COUNT_CACHE,
    _JSONL_RECORD_CACHE,
    _count_jsonl,
    _find_jsonl_record_by_id,
    _profile_state_path,
    _read_json,
    _read_jsonl_records,
    _read_profile_state,
    _read_source_ui_state,
    _record_timestamp,
    _replace_jsonl,
    _parse_record_dt,
    _safe_int,
    _snapshot_reader_lock,
    _snapshot_writer_lock,
    _source_dir,
    _source_ui_state_path,
    _stream_jsonl_records_by_id,
    _tag_text,
    _write_json,
    _write_profile_state,
    _write_source_ui_state,
)


from elevate_cli.source_connector_modules.thread_helpers import (
    _AUTOMATED_DOMAIN_HINTS,
    _AUTOMATED_LOCALPARTS,
    _channel_label,
    _extract_email,
    _heat_score_for_record,
    _is_automated_email,
    _is_automated_sender_record,
    _latest_text,
    _record_person_name,
    _thread_from_record,
    _thread_key,
)

from elevate_cli.source_connector_modules.record_snapshots import (
    _LIST_RECORD_FIELDS,
    _compact_list_text,
    _list_record_snapshot,
)

from elevate_cli.source_connector_modules.draft_helpers import (
    _TEMPLATE_TOKEN_RE,
    _draft_from_task,
    _draft_from_thread,
    _draft_recipient,
    _draft_text_for_task,
    _fallback_draft_for_thread,
    _first_name_from_person,
    _is_message_draft_task,
    _outreach_lane_for_thread,
    _record_field,
    _render_outreach_template,
    _select_thread_template,
    _task_key,
    _template_channel_for_thread,
    _template_values_for_thread,
    _templated_draft_for_thread,
)

from elevate_cli.source_connector_modules.profile_helpers import (
    SOCIAL_INTENT_WORDS,
    SOCIAL_SOURCE_IDS,
    _email_key,
    _is_social_intent,
    _merge_profile,
    _merge_profile_verifiers,
    _name_key,
    _phone_key,
    _profile_contact_values,
    _profile_label,
    _profile_match_keys,
    _profile_verifiers,
    _profiles_from_threads,
    _source_has_inbox_records,
    _source_record_counts,
    _string_values,
)


from elevate_cli.source_connector_modules.apple_messages import (
    APPLE_EPOCH,
    _apple_dt,
    _apple_messages_chat_db_path,
    _apple_messages_source_dir,
    _init_apple_index_db,
    _load_chat_participants,
    _looks_like_fda_denied,
    _sqlite_uri,
    _update_span,
    _write_blocked_apple_messages_source,
    _write_paused_apple_messages_source,
    get_apple_messages_directions,
    initialize_apple_messages_source,
    set_apple_messages_directions,
)


from elevate_cli.source_connector_modules.connector_state import (
    _blueprint,
    _connector_recovery,
    _mutable_source_exists,
    _state_from_status,
)




from elevate_cli.source_connector_modules.connector_views import (
    _candidate_records_for_source,
    _composio_connector_view,
    _discover_composio_views,
    _initialize_behavior,
    build_source_connectors_response,
    build_source_records_response,
    connector_view,
)


from elevate_cli.source_connector_modules.source_inbox import (
    _collect_drafts_for_db_inbox,
    build_source_inbox_response,
)


from elevate_cli.source_connector_modules.private_search import (
    _PCS_BUYER_TAGS,
    _is_pcs_tag,
    _norm_email,
    _norm_phone,
    _pcs_tagged_crm_buyers,
    _read_private_search_buyers,
)


from elevate_cli.source_connector_modules.thread_context import (
    _message_for_thread,
    _resolve_source_view,
    build_thread_context_response,
)


from elevate_cli.source_connector_modules.source_actions import (
    update_profile_favorite,
    update_profile_state,
)


def update_source_thread_state(
    source_id: str,
    thread_id: str,
    action: str,
    config: dict[str, Any] | None = None,
    *,
    return_inbox: bool = True,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
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
            "updated_at": _now(),
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
                (db_status, _now(), source_id, db_thread_id),
            )
    except Exception:
        # Keep the legacy UI-state write available for rows that have not
        # been merged into operational DB yet. DB-primary routes will still
        # show the row until it has a matching conversation to update.
        pass
    return build_source_inbox_response(config) if return_inbox else {"ok": True}


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


def _fire_approve_tick(task_id: str) -> None:
    """Drain the sender ONCE, in the current process, right after an approve.

    Runs in a daemon thread so the HTTP response isn't blocked on the send
    (10-90s). CRITICAL: this must run inside the Elevate app (dashboard)
    process, where macOS Automation→Messages can be granted — the launchd
    gateway daemon cannot send via Messages (no GUI prompt for Automation), so
    the app must own the actual delivery. Disable with ELEVATE_APPROVE_AUTO_TICK=0.
    """
    if os.getenv("ELEVATE_APPROVE_AUTO_TICK", "1") in ("0", "false", "no"):
        return
    import threading

    def _tick() -> None:
        try:
            from elevate_cli import sender as _sender

            _sender.tick(batch=int(os.getenv("ELEVATE_APPROVE_TICK_BATCH", "1")))
        except Exception:
            import traceback

            traceback.print_exc()

    threading.Thread(target=_tick, name=f"approve-tick-{str(task_id)[:24]}", daemon=True).start()


def update_source_task_state(
    source_id: str,
    task_id: str,
    action: str,
    *,
    draft_text: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    if not _mutable_source_exists(source_root, source_id):
        raise ValueError(f"Unknown source connector: {source_id}")
    normalized = str(action or "").strip().lower()
    if normalized not in {"approve", "edit", "skip", "restore", "open"}:
        raise ValueError("Unsupported draft action")

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
        return build_source_inbox_response(config) if return_inbox else {"ok": True}

    status = "approved" if normalized == "approve" else "skipped" if normalized == "skip" else "pending"
    existing = _as_dict(tasks.get(task_id))
    existing.update({"status": status, "updated_at": _now()})
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
        # Outbound pause: if this is a native Mac Messages send (channel "sms")
        # and the Apple Messages outbound toggle is OFF, hold the approval —
        # don't release to the sender, don't fire. The card stays in the queue
        # (status kept pending) so nothing leaves until outbound is turned back
        # on. Inbound/banner are unaffected (different toggle).
        if _channel_for_source(source_id) == "sms" and not get_apple_messages_directions(
            config
        ).get("outbound", True):
            existing["status"] = "pending"
            tasks[task_id] = existing
            state["tasks"] = tasks
            _write_source_ui_state(source_dir, state)
            return build_source_inbox_response(config) if return_inbox else {
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

            flipped = outreach_db.approve_pending_send(source_id, task_id, draft_text=draft_text or None)
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
            _fire_approve_tick(task_id)
        else:
            _approve_atomic(source_id, task_id, existing, source_dir, state)
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

    return build_source_inbox_response(config) if return_inbox else {"ok": True}


def _approve_atomic(
    source_id: str,
    task_id: str,
    task_record: dict[str, Any],
    source_dir: Path,
    state: dict[str, Any],
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

    channel = _channel_for_source(source_id)
    if not channel:
        _write_source_ui_state(source_dir, state)
        return

    # ui-state's task entry only carries {status, updated_at, draft_text}.
    # The recipient (phone/email/handle) lives in the original tasks.jsonl
    # record. Merge it in so the queue payload has what the dispatcher needs;
    # ui-state values win when present (user-edited draft_text).
    merged: dict[str, Any] = {}
    for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
        if _task_key(record) == task_id:
            merged.update(record)
            break
    for k, v in (task_record or {}).items():
        if v not in (None, ""):
            merged[k] = v

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
            outreach_db.enqueue_send(
                conn,
                source_id=source_id,
                thread_id=thread_id,
                task_id=task_id,
                channel=channel,
                payload=payload,
                attempt_id=attempt_id,
            )
            _write_source_ui_state(source_dir, state)

    # Fire the sender immediately so the UI experience is "click → sent."
    _fire_approve_tick(task_id)


from elevate_cli.source_connector_modules.crm_helpers import (
    _LOFTY_LIST_KEYS,
    _basic_auth_header,
    _build_crm_auth,
    _extract_lead_records,
    _generic_crm_get,
    _generic_crm_write,
    _list_text,
    _lofty_epoch_ms_to_iso,
    _lofty_extract_list,
    _lofty_get,
    _lofty_get_activities,
    _lofty_get_first_ok,
    _lofty_get_notes,
    _lofty_get_tasks,
    _lofty_headers,
    _lofty_lead_name,
    _lofty_listing_address,
    _lofty_normalize_activity,
    _lofty_normalize_note,
    _lofty_normalize_task,
    _lofty_timestamp,
    _lofty_write,
    _provider_label,
    _stable_hash_id,
    _tag_names,
)


def sync_generic_crm_source(
    config: dict[str, Any] | None = None, *, limit: int = 5000
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = _combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    provider = str(crm.get("provider") or "custom")
    label = str(crm.get("label") or _provider_label(provider))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")

    if not api_key or not str(crm.get("base_url") or "").strip():
        _write_json(
            source_dir / "source.json",
            {
                "source_id": "crm",
                "provider": label,
                "account_label": label,
                "connection_type": f"{provider}_api",
                "auth_status": "missing_secret",
                "sync_mode": "crm_lead_snapshot",
                "owner_agent": owner,
                "enabled_ui_surfaces": surfaces,
                "setup_status": "needs_operator",
                "last_sync_at": None,
                "setup_notes": f"Add {env_key} to ~/.elevate/.env and confirm the {label} base URL.",
            },
        )
        _write_json(
            source_dir / "status.json",
            {
                "connected": False,
                "import_only": False,
                "blocked": False,
                "last_error": None,
                "next_operator_step": f"Add the {label} API key, then sync CRM again.",
                "last_checked_at": now,
            },
        )
        for file_name in JSONL_FILES:
            _replace_jsonl(source_dir / file_name, [])
        view = connector_view(source_root, "crm")
        if view is None:
            raise RuntimeError(f"{label} source could not be read")
        return view

    leads: list[JsonRecord] = []
    attempted: list[str] = [leads_path]
    errors: list[str] = []
    pagination_params: dict[str, Any] = {"limit": min(limit, 100)}
    if provider == "followupboss":
        pagination_params = {"limit": min(limit, 100), "sort": "-updated"}
    elif provider == "sierra":
        pagination_params = {"page": 1, "pageSize": min(limit, 100)}
    elif provider == "boldtrail":
        pagination_params = {"limit": min(limit, 100), "sort": "-updated_at"}
    elif provider == "brivity":
        pagination_params = {"page": 1, "per_page": min(limit, 100)}
    try:
        payload = _generic_crm_get(crm, api_key, leads_path, pagination_params)
        leads = _extract_lead_records(payload)
    except Exception as exc:
        errors.append(f"{leads_path}: {exc}")

    deduped: list[JsonRecord] = []
    seen_ids: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("id") or lead.get("leadId") or lead.get("lead_id") or "").strip()
        if not lead_id:
            lead_id = f"unknown-{len(seen_ids) + 1}"
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        deduped.append(lead)

    contact_records: list[JsonRecord] = []
    conversation_records: list[JsonRecord] = []
    lead_events: list[JsonRecord] = []
    task_records: list[JsonRecord] = []
    for lead in deduped:
        lead_id = str(lead.get("id") or lead.get("leadId") or lead.get("lead_id") or "").strip()
        record_id = f"{provider}-lead:{lead_id or len(contact_records) + 1}"
        name = _lofty_lead_name(lead)
        timestamp = _lofty_timestamp(lead)
        stage = str(
            lead.get("stage") or lead.get("status") or lead.get("leadType") or lead.get("aiStage") or ""
        ).strip()
        source = str(
            lead.get("source") or lead.get("leadSource") or lead.get("origin") or ""
        ).strip()
        tags = _tag_names(lead.get("tags"))
        score = _safe_int(lead.get("score") or lead.get("leadScore"), 45)
        summary = (
            f"{name} from {label}"
            + (f" is in {stage}" if stage else "")
            + (f" via {source}" if source else "")
            + "."
        )
        base_record = {
            "source_id": "crm",
            "source_record_id": record_id,
            "conversation_id": record_id,
            "contact_id": record_id,
            "display_name": name,
            "channel": label,
            "timestamp": timestamp,
            "last_seen_at": timestamp,
            "last_message_at": timestamp,
            "text": summary,
            "summary": summary,
            "lead_id": lead_id or None,
            "stage": stage or None,
            "lead_source": source or None,
            "assigned_user": lead.get("assignedUser") or lead.get("assignedAgent") or lead.get("assigned_to"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, f"{provider}-crm", "crm-lead"],
            "confidence": 0.82,
            "target_ui_surfaces": surfaces,
        }
        contact_records.append(base_record)
        conversation_records.append(
            {
                **base_record,
                "total_messages": _safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
                "inbound_count": 0,
                "outbound_count": 0,
                "last_text": summary,
            }
        )
        lead_events.append(
            {
                **base_record,
                "type": "crm_lead_synced",
                "title": f"{label} lead synced",
            }
        )
        heat_score, heat_label = _heat_score_for_record(base_record)
        if heat_label in {"hot", "warm"}:
            task_records.append(
                {
                    **base_record,
                    "source_record_id": f"{record_id}:follow-up",
                    "title": f"Review {name}",
                    "status": "open",
                    "task_type": "lead_follow_up",
                    "approval_required": False,
                    "owner_agent": owner,
                    "summary": f"{name} looks {heat_label} in {label}. Review source, stage, notes, and next outreach step.",
                    "heat_score": heat_score,
                    "target_ui_surfaces": ["Leads", "Today", "Outreach"],
                }
            )

    # Atomic multi-file rewrite (Codex audit P1, 2026-05-05).
    with _snapshot_writer_lock(source_dir):
        preserved_tasks = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": label,
            "account_label": label,
            "connection_type": f"{provider}_api",
            "auth_status": f"{str(crm.get('auth_type') or 'header')}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": f"Read-only {label} lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                if deduped
                else f"{label} auth was found, but no lead rows were returned. Check the API key scope, then sync again."
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
            },
        },
    )
    # Continuous DB writethrough — Codex audit P0 (2026-05-05).
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough: {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": now, "error": str(exc)},
        )

    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError(f"{label} source could not be read")
    return view


# ── CRM write layer (create, note, stage update) ──────────────────────────────


def _sierra_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Sierra-ApiKey": api_key,
        "Sierra-OriginatingSystemName": "elevate",
    }


def _sierra_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_sierra_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _sierra_get(path: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    request = urllib.request.Request(url, headers=_sierra_headers(api_key), method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _brivity_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token token={api_key}",
    }


def _brivity_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://www.brivity.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_brivity_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _resolve_crm_context(
    config: dict[str, Any],
) -> tuple[str, str, JsonRecord, dict[str, str]]:
    """Return (provider, api_key, crm_config, env_values)."""
    env_values = _combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    # Honor whatever CRM was picked at onboarding/config — never assume Lofty.
    provider = _canonical_crm_provider(crm.get("provider"))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    if not api_key and provider == "lofty":
        api_key = str(env_values.get("LOFTY_API_KEY") or env_values.get("LOFTY_ACCESS_TOKEN") or "").strip()
    return provider, api_key, crm, env_values


def crm_find_lead(
    email: str = "",
    config: dict[str, Any] | None = None,
    *,
    phone: str = "",
) -> JsonRecord | None:
    """Find a CRM lead by email (or phone fallback). Returns normalized {id, stage, tags} or None."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    def _normalize_lofty(lead: JsonRecord) -> JsonRecord:
        return {
            "id": str(lead.get("leadId") or ""),
            "stage": str(lead.get("stage") or ""),
            "tags": [t.get("tagName") for t in (lead.get("tags") or []) if t.get("tagName")],
            "raw": lead,
        }

    if provider == "lofty":
        if email:
            payload = _lofty_get(f"v1.0/leads?email={urllib.parse.quote(email)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        if phone:
            payload = _lofty_get(f"v1.0/leads?phone={urllib.parse.quote(phone)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        return None

    if provider == "followupboss":
        if email:
            payload = _generic_crm_get(crm, api_key, "v1/people", {"email": email, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        if phone:
            payload = _generic_crm_get(crm, api_key, "v1/people", {"phone": phone, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        return None

    if provider == "sierra":
        if email:
            payload = _sierra_get("leads", api_key, {"email": email, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        if phone:
            payload = _sierra_get("leads", api_key, {"phone": phone, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        return None

    if provider == "brivity":
        # Brivity has no public search endpoint -- caller must track ids externally
        return None

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_find_lead not yet implemented for provider: {provider}")


def crm_create_lead(
    contact: JsonRecord,
    config: dict[str, Any] | None = None,
) -> str:
    """Create a lead in the CRM. contact = {firstName, lastName, email, phone, source, stage, tags}.
    Returns the new lead's CRM id."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)
    first = str(contact.get("firstName") or "")
    last = str(contact.get("lastName") or "")
    email = str(contact.get("email") or "")
    phone = str(contact.get("phone") or "")
    source = str(contact.get("source") or "elevate")
    stage = str(contact.get("stage") or "New Leads")
    tags = list(contact.get("tags") or [])

    if provider == "lofty":
        body: JsonRecord = {"firstName": first, "lastName": last, "source": source, "stage": stage, "tags": tags}
        if email:
            body["emails"] = [email]
        if phone:
            body["phones"] = [phone]
        result = _lofty_write("v1.0/leads", env_values, body, method="POST")
        return str(result.get("leadId") or result.get("id") or "")

    if provider == "followupboss":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["emails"] = [{"value": email, "type": "work"}]
        if phone:
            body["phones"] = [{"value": phone, "type": "mobile"}]
        result = _generic_crm_write(crm, api_key, "v1/people", body, method="POST")
        lead_id = str(result.get("id") or result.get("person", {}).get("id") or "")
        if lead_id and stage and stage != "New Leads":
            _generic_crm_write(crm, api_key, f"v1/people/{lead_id}", {"stage": stage}, method="PUT")
        return lead_id

    if provider == "sierra":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if tags:
            body["tags"] = tags
        if stage:
            body["leadType"] = stage  # Sierra uses leadType on create, status on update
        note_text = str(contact.get("note") or "")
        if note_text:
            body["note"] = note_text
        result = _sierra_write("leads", api_key, body, method="POST")
        return str((result.get("data") or {}).get("id") or "")

    if provider == "brivity":
        # Brivity uses snake_case and encodes notes in description
        body = {"source": source}
        if first:
            body["first_name"] = first
        if last:
            body["last_name"] = last
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if stage:
            # Brivity status enum: new, unqualified, watch, nurture, hot, archived
            body["status"] = stage.lower()
        note_text = str(contact.get("note") or "")
        if note_text:
            body["description"] = note_text
        result = _brivity_write("api/v2/leads", api_key, body, method="POST")
        return str((result.get("lead") or result).get("id") or "")

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_create_lead not yet implemented for provider: {provider}")


def crm_add_note(
    lead_id: str,
    note: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """Add a note to an existing CRM lead. Returns True on success."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        try:
            _lofty_write(f"v1.0/leads/{lead_id}/notes", env_values, {"content": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        try:
            _generic_crm_write(crm, api_key, "v1/notes", {"personId": int(lead_id), "body": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "sierra":
        try:
            _sierra_write(f"leads/{lead_id}/note", api_key, {"message": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no notes endpoint -- notes must go into description at create time
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_add_note not yet implemented for provider: {provider}")


def sync_pending_notes_to_lofty(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 25,
    max_attempts: int = 5,
) -> JsonRecord:
    """Push every ``notes`` row with ``crm_sync_state='pending'`` to
    Lofty. Returns a summary ``{pushed, skipped, failed, errors[]}``.

    Skip rules (counted in ``skipped``, not retried):
      * non-Lofty CRM provider — caller picked the wrong source.
      * Contact has no ``lofty_id`` identity — we have nowhere to POST.

    Failure rules:
      * 4xx → ``mark_lofty_failed(permanent=True)`` — payload bad, retry
        won't fix it. Operator can re-trigger by editing the body.
      * 5xx / timeout / unknown → ``mark_lofty_failed(permanent=False)`` —
        attempt counter bumps; row stays ``pending`` until ``max_attempts``.

    Content prefix: ``[AI/{author_name}] {body}`` — so the operator can
    skim Lofty's note feed and know what wrote each line.
    """
    config = config or load_config()
    provider, _api_key, _crm, env_values = _resolve_crm_context(config)

    summary: JsonRecord = {
        "provider": provider,
        "pushed": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    if provider != "lofty":
        # Future: dispatch to followupboss / sierra / etc. For now only
        # Lofty is wired — others fall through silently to keep the cron
        # safe to run regardless of which CRM the operator connected.
        return summary

    headers, _auth_type = _lofty_headers(env_values)
    if not headers.get("Authorization"):
        summary["errors"].append("LOFTY_API_KEY / LOFTY_ACCESS_TOKEN not set")
        return summary

    from elevate_cli.data import (
        connect as _db_connect,
        list_pending_lofty_notes,
        mark_lofty_synced,
        mark_lofty_failed,
    )

    with _db_connect() as conn:
        pending = list_pending_lofty_notes(conn, limit=limit, max_attempts=max_attempts)
        for note in pending:
            note_id = note["id"]
            contact_id = note["contactId"]
            # Resolve the contact's Lofty lead id via the identities table.
            lofty_row = conn.execute(
                "SELECT value FROM identities "
                "WHERE contact_id=? AND kind='lofty_id' LIMIT 1",
                (contact_id,),
            ).fetchone()
            if lofty_row is None or not lofty_row["value"]:
                # No Lofty linkage — permanently fail. If a Lofty identity
                # gets added later, the operator can re-trigger by editing
                # the note body (which moves it back to pending).
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error="contact has no lofty_id identity",
                    permanent=True,
                )
                summary["skipped"] += 1
                continue
            lead_id = str(lofty_row["value"])
            content = f"[AI/{note['authorName']}] {note['body']}"

            try:
                resp = _lofty_write(
                    f"v1.0/leads/{lead_id}/notes",
                    env_values,
                    {"content": content},
                    method="POST",
                )
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=True,
                    )
                    summary["failed"] += 1
                else:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=False,
                    )
                    summary["errors"].append(f"{note_id}: HTTP {exc.code}")
                continue
            except Exception as exc:
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error=str(exc)[:500],
                    permanent=False,
                )
                summary["errors"].append(f"{note_id}: {exc}")
                continue

            lofty_note_id = None
            if isinstance(resp, dict):
                # Lofty returns either {"noteId": …} or wraps the row under
                # "data". Probe both shapes.
                raw = resp.get("noteId") or resp.get("id")
                if raw is None and isinstance(resp.get("data"), dict):
                    raw = resp["data"].get("noteId") or resp["data"].get("id")
                if raw is not None:
                    lofty_note_id = str(raw)

            if lofty_note_id:
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=lofty_note_id)
                summary["pushed"] += 1
            else:
                # POST succeeded (no exception) but we couldn't parse the
                # id. Mark synced with a placeholder so we don't double-post,
                # but flag in errors so the operator can investigate.
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=f"unknown:{note_id}")
                summary["pushed"] += 1
                summary["errors"].append(
                    f"{note_id}: posted but noteId missing from response"
                )

    return summary


def crm_update_stage(
    lead_id: str,
    stage: str,
    tags: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    """Update a CRM lead's stage and optionally merge tags. Returns True on success."""
    config = config or load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        body: JsonRecord = {"stage": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _lofty_write(f"v1.0/leads/{lead_id}", env_values, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        body = {"stage": stage}
        try:
            _generic_crm_write(crm, api_key, f"v1/people/{lead_id}", body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "sierra":
        # Sierra status enum: New, Qualify, Active, Prime, Pending, Closed, Archived, Junk, DoNotContact, Watch, Blocked
        body = {"status": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _sierra_write(f"leads/{lead_id}", api_key, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no status-update endpoint -- re-POST with status to upsert by email
        # Caller should use crm_create_lead with status set instead
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_update_stage not yet implemented for provider: {provider}")


# Lofty enrichment is the dominant cost of `elevate sync crm`: 3 HTTP calls
# per lead (activities + notes + tasks). To prevent a slow tenant from hanging
# the whole sync, enrichment runs in parallel with a per-call ceiling and
# checkpoints to disk every N leads so a killed run resumes instead of restarting.
_LOFTY_ENRICHMENT_WORKERS = 8
_LOFTY_ENRICHMENT_TIMEOUT_S = 10
_LOFTY_ENRICHMENT_CHECKPOINT_EVERY = 5


def _lofty_load_enrichment_progress(
    artifacts_dir: Path,
) -> tuple[set[str], list[JsonRecord], dict[str, int]]:
    """Load the prior enrichment checkpoint so a resumed sync skips already-
    enriched lead_ids. Missing/corrupt file = clean start, never raises."""
    path = artifacts_dir / "enrichment_progress.json"
    if not path.exists():
        return set(), [], {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        return set(), [], {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    completed = {str(x) for x in (payload.get("completed_lead_ids") or []) if x}
    events = [e for e in (payload.get("events") or []) if isinstance(e, dict)]
    summary = payload.get("summary") or {}
    base_summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    for key in base_summary:
        base_summary[key] = int(summary.get(key, 0) or 0)
    return completed, events, base_summary


def _lofty_save_enrichment_progress(
    artifacts_dir: Path,
    *,
    completed_lead_ids: set[str],
    events: list[JsonRecord],
    summary: dict[str, int],
    total_leads: int,
    status: str,
) -> None:
    """Atomic checkpoint write — same readers/writers can see partial
    enrichment without a torn file."""
    payload = {
        "checkpointed_at": _now(),
        "status": status,
        "completed_lead_ids": sorted(completed_lead_ids),
        "completed_count": len(completed_lead_ids),
        "total_leads": total_leads,
        "summary": summary,
        "events": events,
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tmp = artifacts_dir / "enrichment_progress.json.tmp"
    final = artifacts_dir / "enrichment_progress.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)


def _lofty_enrich_one_lead(
    *,
    lead_id: str,
    record_id: str,
    base_record: JsonRecord,
    fallback_timestamp: str,
    env_values: dict[str, str],
    timeout: int,
) -> tuple[str, list[JsonRecord], dict[str, int]]:
    """Worker called from a thread pool. Pulls activities + notes + tasks
    for one lead and returns the typed lead_events + a per-lead summary
    delta. Never raises — endpoint errors increment the error counter so
    one slow lead can't block the whole pool."""
    events: list[JsonRecord] = []
    summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}

    try:
        activity_payload = _lofty_get_activities(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        activity_payload = []
        summary["errors"] += 1
    for raw_act in activity_payload:
        norm = _lofty_normalize_activity(raw_act, lead_id)
        act_id = norm["id"] or _stable_hash_id(
            norm["subtype"], norm["title"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:activity:{act_id}",
                "type": "crm_activity",
                "provider": "lofty",
                "subtype": norm["subtype"],
                "title": norm["title"],
                "summary": norm["summary"],
                "address": norm["address"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["activities"] = len(activity_payload)

    try:
        notes_payload = _lofty_get_notes(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        notes_payload = []
        summary["errors"] += 1
    for raw_note in notes_payload:
        norm = _lofty_normalize_note(raw_note, lead_id)
        note_id = norm["id"] or _stable_hash_id(
            norm["title"], norm["summary"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:note:{note_id}",
                "type": "crm_note",
                "provider": "lofty",
                "title": norm["title"] or "Note",
                "summary": norm["summary"],
                "author": norm["author"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["notes"] = len(notes_payload)

    try:
        tasks_payload = _lofty_get_tasks(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        tasks_payload = []
        summary["errors"] += 1
    tasks_payload = [t for t in tasks_payload if not t.get("deleteFlag")]
    for raw_task in tasks_payload:
        norm = _lofty_normalize_task(raw_task, lead_id)
        task_id = norm["id"] or _stable_hash_id(
            norm["title"], norm["summary"], norm["dueAt"], norm["timestamp"]
        )
        events.append(
            {
                **base_record,
                "source_record_id": f"{record_id}:task:{task_id}",
                "type": "crm_task",
                "provider": "lofty",
                "title": norm["title"],
                "summary": norm["summary"],
                "status": norm["status"],
                "task_subtype": norm["type"],
                "assignedUser": norm["assignedUser"],
                "dueAt": norm["dueAt"],
                "timestamp": norm["timestamp"] or fallback_timestamp,
            }
        )
    summary["tasks"] = len(tasks_payload)

    return lead_id, events, summary


def sync_lofty_crm_source(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 5000,
    enrichment_limit: int = 5000,
) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = _combined_env(config)
    headers, auth_type = _lofty_headers(env_values)

    if not headers.get("Authorization"):
        _write_json(
            source_dir / "source.json",
            {
                "source_id": "crm",
                "provider": "Lofty CRM",
                "account_label": "Lofty CRM",
                "connection_type": "lofty_api",
                "auth_status": "missing_secret",
                "sync_mode": "crm_lead_snapshot",
                "owner_agent": owner,
                "enabled_ui_surfaces": surfaces,
                "setup_status": "needs_operator",
                "last_sync_at": None,
                "setup_notes": "Add LOFTY_API_KEY or LOFTY_ACCESS_TOKEN to ~/.elevate/.env or the tools root .env.",
            },
        )
        _write_json(
            source_dir / "status.json",
            {
                "connected": False,
                "import_only": False,
                "blocked": False,
                "last_error": None,
                "next_operator_step": "Add the Lofty API key, then initialize/sync CRM again.",
                "last_checked_at": now,
            },
        )
        for file_name in JSONL_FILES:
            _replace_jsonl(source_dir / file_name, [])
        view = connector_view(source_root, "crm")
        if view is None:
            raise RuntimeError("Lofty CRM source could not be read")
        return view

    # Lofty caps page size at 100. For limit>100 we paginate via offset.
    # The two endpoints are tried in fall-through order: v2.0/working-leads
    # returns the high-priority slice, v1.0/leads returns everything.
    leads: list[JsonRecord] = []
    attempted: list[str] = []
    errors: list[str] = []
    page_size = 100
    for path, base_params in (
        ("/v2.0/working-leads", {"aiStage": "HIGH_PRIORITY", "sort": "UpdateTime", "desc": "true"}),
        ("/v1.0/leads", {}),
    ):
        attempted.append(path)
        offset = 0
        endpoint_pulled = 0
        while endpoint_pulled < limit:
            params = {
                **base_params,
                "limit": min(page_size, limit - endpoint_pulled),
                "offset": offset,
            }
            try:
                payload = _lofty_get(path, env_values, params)
            except Exception as exc:
                errors.append(f"{path}@offset={offset}: {exc}")
                break
            extracted = _extract_lead_records(payload)
            if not extracted:
                break  # exhausted this endpoint
            leads.extend(extracted)
            endpoint_pulled += len(extracted)
            offset += len(extracted)
            if len(extracted) < page_size:
                break  # short page = last page

    deduped: list[JsonRecord] = []
    seen_ids: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("leadId") or lead.get("id") or lead.get("lead_id") or "").strip()
        if not lead_id:
            lead_id = f"unknown-{len(seen_ids) + 1}"
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        deduped.append(lead)

    contact_records: list[JsonRecord] = []
    conversation_records: list[JsonRecord] = []
    lead_events: list[JsonRecord] = []
    task_records: list[JsonRecord] = []
    pending_enrichments: list[JsonRecord] = []
    enrichment_summary: dict[str, int] = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}
    max_enriched = max(0, int(enrichment_limit or 0))
    for index, lead in enumerate(deduped):
        lead_id = str(lead.get("leadId") or lead.get("id") or lead.get("lead_id") or "").strip()
        record_id = f"lofty-lead:{lead_id or len(contact_records) + 1}"
        name = _lofty_lead_name(lead)
        timestamp = _lofty_timestamp(lead)
        stage = str(lead.get("stage") or lead.get("aiStage") or lead.get("status") or "").strip()
        source = str(lead.get("source") or lead.get("leadSource") or "").strip()
        tags = _tag_names(lead.get("tags"))
        score = _safe_int(lead.get("score") or lead.get("leadScore"), 45)
        summary = (
            f"{name} from Lofty"
            + (f" is in {stage}" if stage else "")
            + (f" via {source}" if source else "")
            + "."
        )
        # Carry the full Lofty lead profile through to JSONL so the
        # migrate.py writethrough can enrich the contacts row. Pre-0012
        # this only carried name/email/phone/stage and the drawer rendered
        # blank cards. See migration 0012_lofty_lead_metadata.sql for the
        # column list and _CONTACT_ENRICHMENT_KEY_MAP in migrate.py for
        # accepted aliases.
        def _lead_get(*keys: str) -> Any:
            for key in keys:
                if key in lead:
                    value = lead.get(key)
                    if value not in (None, ""):
                        return value
            return None

        base_record = {
            "source_id": "crm",
            "source_record_id": record_id,
            "conversation_id": record_id,
            "contact_id": record_id,
            "display_name": name,
            "channel": "Lofty CRM",
            "timestamp": timestamp,
            "last_seen_at": timestamp,
            "last_message_at": timestamp,
            "text": summary,
            "summary": summary,
            "lead_id": lead_id or None,
            "stage": stage or None,
            "lead_source": source or None,
            "assigned_user": _lead_get("assignedUser", "assignedAgent"),
            "assignedUser": _lead_get("assignedUser", "assignedAgent"),
            "assignedUserId": _lead_get("assignedUserId", "assigned_user_id"),
            "leadUserId": _lead_get("leadUserId", "lofty_lead_user_id"),
            "emails": lead.get("emails") or lead.get("email"),
            "phones": lead.get("phones") or lead.get("phone"),
            "score": score,
            "tags": [*tags, "lofty-crm", "crm-lead"],
            "confidence": 0.86,
            "target_ui_surfaces": surfaces,
            # --- Lofty enrichment (migration 0012) ---
            "pondId": _lead_get("pondId", "pond_id"),
            "pondName": _lead_get("pondName", "pond_name"),
            "referredBy": _lead_get("referredBy", "referred_by"),
            "opportunity": _lead_get("opportunity"),
            "buyingTimeFrame": _lead_get("buyingTimeFrame", "buying_time_frame"),
            "sellingTimeFrame": _lead_get("sellingTimeFrame", "selling_time_frame"),
            "preQual": _lead_get("preQual", "preQualStatus", "pre_qual_status"),
            "mortgage": _lead_get("mortgage", "mortgageStatus", "mortgage_status"),
            "fthb": _lead_get("fthb", "firstTimeHomeBuyer", "first_time_home_buyer"),
            "hasHouseToSell": _lead_get("hasHouseToSell", "has_house_to_sell", "houseToSell"),
            "withBuyerAgent": _lead_get("withBuyerAgent", "with_buyer_agent"),
            "withListingAgent": _lead_get("withListingAgent", "with_listing_agent"),
            "buyHouseIntent": _lead_get("buyHouseIntent", "buy_house_intent", "buyHouse"),
            "leadTypes": lead.get("leadTypes") or lead.get("lead_types") or [],
            "segments": lead.get("segments") or [],
            "cannotText": _lead_get("cannotText", "cannot_text"),
            "cannotCall": _lead_get("cannotCall", "cannot_call"),
            "cannotEmail": _lead_get("cannotEmail", "cannot_email"),
            "unsubscribed": _lead_get("unsubscribed", "unsubscription"),
            "hidden": _lead_get("hidden", "hiddenFlag"),
        }
        contact_records.append(base_record)
        conversation_records.append(
            {
                **base_record,
                "total_messages": _safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
                "inbound_count": 0,
                "outbound_count": 0,
                "last_text": summary,
            }
        )
        lead_events.append(
            {
                **base_record,
                "type": "crm_lead_synced",
                "title": "Lofty lead synced",
            }
        )

        # Phase 2 enrichment runs in parallel after Phase 1 writes the
        # lead snapshot to disk. Stash everything we need to enrich this
        # lead later so the thread pool has self-contained job inputs.
        if lead_id and index < max_enriched:
            pending_enrichments.append(
                {
                    "lead_id": lead_id,
                    "record_id": record_id,
                    "base_record": base_record,
                    "fallback_timestamp": timestamp,
                }
            )

        heat_score, heat_label = _heat_score_for_record(base_record)
        if heat_label in {"hot", "warm"}:
            task_records.append(
                {
                    **base_record,
                    "source_record_id": f"{record_id}:follow-up",
                    "title": f"Review {name}",
                    "status": "open",
                    "task_type": "lead_follow_up",
                    "approval_required": False,
                    "owner_agent": owner,
                    "summary": f"{name} looks {heat_label} in Lofty. Review source, stage, notes, and next outreach step.",
                    "heat_score": heat_score,
                    "target_ui_surfaces": ["Leads", "Today", "Outreach"],
                }
            )

    # === PHASE 1 — Lead snapshot to disk + writethrough to operational Postgres ===
    # Write the lead snapshot before enrichment so even if Phase 2 hangs or
    # gets killed, downstream readers (operational Postgres, /leads UI, thread
    # drawer) already see the 21 leads with stage/score/source. Enrichment
    # in Phase 2 only adds the activity/note/task lead_events.
    base_lead_events = list(lead_events)
    with _snapshot_writer_lock(source_dir):
        preserved_tasks_phase1 = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", base_lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks_phase1 + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": "Lofty CRM",
            "account_label": "Lofty CRM",
            "connection_type": "lofty_api",
            "auth_status": f"{auth_type}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": "Read-only Lofty lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "enrichment_status": "pending" if pending_enrichments else "skipped",
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(base_lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Lead snapshot written. Enrichment running in background — refresh in a minute for activities/notes."
                if pending_enrichments
                else (
                    "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                    if deduped
                    else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
                )
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(base_lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough (phase 1): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": _now(), "phase": 1, "error": str(exc)},
        )

    # === PHASE 2 — Parallel enrichment with checkpointing ===
    # Each lead needs 3 HTTP calls (activities + notes + tasks). Running
    # them serially × 21 leads × 18s timeout = 19 min worst case. Running
    # in parallel (8 workers, 10s timeout each) brings this to 1-3 min for
    # 21 leads. Checkpoints every N completed leads so a killed run
    # resumes from where it left off.
    enrichment_status = "skipped"
    if pending_enrichments:
        prior_completed, prior_events, prior_summary = _lofty_load_enrichment_progress(artifacts_dir)
        # Keep prior summary so resumed runs surface cumulative counts.
        for key in enrichment_summary:
            enrichment_summary[key] = prior_summary.get(key, 0)
        completed_lead_ids: set[str] = set(prior_completed)
        enrichment_events: list[JsonRecord] = [
            e for e in prior_events
            if str((e.get("lead_id") or "")).strip() in completed_lead_ids
        ]
        to_enrich = [
            job for job in pending_enrichments
            if job["lead_id"] not in completed_lead_ids
        ]
        total = len(pending_enrichments)
        done = len(completed_lead_ids)
        if to_enrich:
            print(
                f"[crm] enrichment phase: {done}/{total} already done, "
                f"enriching {len(to_enrich)} leads with {_LOFTY_ENRICHMENT_WORKERS} workers"
                f" (timeout={_LOFTY_ENRICHMENT_TIMEOUT_S}s/call)",
                file=sys.stderr,
                flush=True,
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=_LOFTY_ENRICHMENT_WORKERS,
                thread_name_prefix="lofty-enrich",
            ) as executor:
                futures = {
                    executor.submit(
                        _lofty_enrich_one_lead,
                        lead_id=job["lead_id"],
                        record_id=job["record_id"],
                        base_record=job["base_record"],
                        fallback_timestamp=job["fallback_timestamp"],
                        env_values=env_values,
                        timeout=_LOFTY_ENRICHMENT_TIMEOUT_S,
                    ): job["lead_id"]
                    for job in to_enrich
                }
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        lead_id, events, delta = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        enrichment_summary["errors"] += 1
                        errors.append(f"enrichment worker crashed: {exc}")
                        continue
                    completed_lead_ids.add(lead_id)
                    enrichment_events.extend(events)
                    for key, val in delta.items():
                        enrichment_summary[key] = enrichment_summary.get(key, 0) + int(val or 0)
                    done = len(completed_lead_ids)
                    if done % _LOFTY_ENRICHMENT_CHECKPOINT_EVERY == 0 or done == total:
                        # Atomic checkpoint: lead-events.jsonl + progress file
                        # both reflect the same partial state. Resume picks
                        # up from the union of base + checkpoint events.
                        with _snapshot_writer_lock(source_dir):
                            _replace_jsonl(
                                source_dir / "lead-events.jsonl",
                                base_lead_events + enrichment_events,
                            )
                        _lofty_save_enrichment_progress(
                            artifacts_dir,
                            completed_lead_ids=completed_lead_ids,
                            events=enrichment_events,
                            summary=enrichment_summary,
                            total_leads=total,
                            status="in_progress" if done < total else "complete",
                        )
                        print(
                            f"[crm] enriched {done}/{total} leads "
                            f"(activities={enrichment_summary['activities']}, "
                            f"notes={enrichment_summary['notes']}, "
                            f"tasks={enrichment_summary['tasks']}, "
                            f"errors={enrichment_summary['errors']})",
                            file=sys.stderr,
                            flush=True,
                        )
        # Always include prior + new events in the final lead_events list
        lead_events = base_lead_events + enrichment_events
        enrichment_status = "complete" if done >= total else "partial"

    # === PHASE 3 — Final atomic rewrite + writethrough ===
    # Atomic multi-file rewrite — readers holding _snapshot_reader_lock
    # see either the pre-sync snapshot or the post-sync snapshot, never
    # a torn one. Codex audit P1 (2026-05-05).
    with _snapshot_writer_lock(source_dir):
        preserved_tasks = [
            r for r in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000)
            if str(r.get("task_type") or "").lower() != "lead_follow_up"
        ]
        _replace_jsonl(source_dir / "contacts.jsonl", contact_records)
        _replace_jsonl(source_dir / "conversations.jsonl", conversation_records)
        _replace_jsonl(source_dir / "messages.jsonl", [])
        _replace_jsonl(source_dir / "message-days.jsonl", [])
        _replace_jsonl(source_dir / "lead-events.jsonl", lead_events)
        _replace_jsonl(source_dir / "tasks.jsonl", preserved_tasks + task_records)
    _write_json(
        source_dir / "source.json",
        {
            "source_id": "crm",
            "provider": "Lofty CRM",
            "account_label": "Lofty CRM",
            "connection_type": "lofty_api",
            "auth_status": f"{auth_type}_configured",
            "sync_mode": "crm_lead_snapshot",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "connected" if deduped else "needs_operator",
            "last_sync_at": now,
            "setup_notes": "Read-only Lofty lead snapshot normalized into the local Elevate source inbox.",
            "attempted_endpoints": attempted,
            "enrichment_status": enrichment_status,
            "record_counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": bool(deduped),
            "import_only": True,
            "blocked": False,
            "last_error": "; ".join(errors) if errors and not deduped else None,
            "next_operator_step": (
                "Review the hot/warm lead cards and decide which conversations should become outreach tasks."
                if deduped
                else "Lofty auth was found, but no lead rows were returned. Check the key scope/OAuth permissions, then sync again."
            ),
            "last_checked_at": now,
            "last_imported_at": now if deduped else None,
            "counts": {
                "contacts": len(contact_records),
                "conversations": len(conversation_records),
                "lead_events": len(lead_events),
                "tasks": len(task_records),
                "enrichment": dict(enrichment_summary),
                "enrichment_lead_limit": max_enriched,
            },
        },
    )
    if errors:
        _write_json(artifacts_dir / "last-sync-errors.json", {"checked_at": now, "errors": errors})

    # Continuous ingest into operational Postgres so DB-primary readers see
    # tonight's Lofty data without a manual ``elevate migrate-data`` rerun.
    # Codex audit P0 (2026-05-05): JSONL-only sync left the DB stale.
    # Phase 1 already ran a writethrough for the bare snapshot; this Phase 3
    # writethrough lands the enrichment lead_events.
    try:
        _walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        # Never let the DB writethrough fail the sync; legacy JSONL is
        # still the canonical store under DB shadow-read mode.
        if errors is not None:
            errors.append(f"db writethrough (phase 3): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": now, "phase": 3, "error": str(exc)},
        )
    # Mark enrichment checkpoint complete so a subsequent run doesn't
    # re-enrich leads already finalized.
    if enrichment_status in {"complete", "partial"}:
        try:
            _lofty_save_enrichment_progress(
                artifacts_dir,
                completed_lead_ids=set(completed_lead_ids) if pending_enrichments else set(),
                events=[e for e in lead_events if e.get("type") != "crm_lead_synced"],
                summary=enrichment_summary,
                total_leads=len(pending_enrichments),
                status=enrichment_status,
            )
        except Exception:  # noqa: BLE001
            pass

    view = connector_view(source_root, "crm")
    if view is None:
        raise RuntimeError("Lofty CRM sync finished but could not be read")
    return view


def _walk_jsonl_into_pg(source_dir: Path) -> dict[str, Any]:
    """Replay the just-written JSONL snapshot through the operational
    Postgres walker so DB-primary readers see fresh data without a
    manual ``elevate migrate-data`` rerun. Idempotent — every helper
    underneath ``walk_jsonl_source`` is keyed on source_key /
    event_hash / etc."""
    from elevate_cli.data import connect as _data_connect
    from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source

    stats = BackfillStats()
    with _data_connect() as conn:
        walk_jsonl_source(source_dir, conn=conn, stats=stats, dry_run=False)
    return stats.to_dict()


def scaffold_composio_social_source(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    blueprint = _blueprint("social")
    if not blueprint:
        raise RuntimeError("Composio social connector blueprint is missing")

    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "social")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = _now()
    surfaces = UI_BY_SOURCE["social"]
    owner = OWNER_BY_SOURCE["social"]
    prompt = source_prompt_for("social")
    prompt_path = artifacts_dir / "composio-social-setup-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    composio_server = _configured_composio_server(config)
    has_server = composio_server is not None
    next_step = (
        "Add Instagram, Facebook, LinkedIn, YouTube, TikTok, or other social apps inside Composio, "
        "then run the social sync/import agent prompt so Elevate can write local metrics, messages, lead events, and tasks."
        if has_server
        else (
            "Connect Composio MCP in Settings/config first, add the social apps inside Composio, "
            "then refresh this setup and run the social sync/import agent prompt."
        )
    )

    _write_json(
        source_dir / "source.json",
        {
            "source_id": "social",
            "provider": "Composio Social Accounts",
            "account_label": "Composio Social Hub",
            "connection_type": "composio_mcp" if has_server else "composio_mcp_setup",
            "auth_status": "composio_mcp_configured" if has_server else "needs_composio_account",
            "sync_mode": "composio_social_setup",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "needs_social_accounts" if has_server else "needs_composio_mcp",
            "last_sync_at": now,
            "setup_notes": (
                "Composio is the social account hub. Elevate reads through the local MCP/tool connection "
                "and writes normalized local source records; outbound replies remain approval-gated."
            ),
            "agent_setup_prompt_path": str(prompt_path),
            "composio_server": composio_server,
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": None,
            "next_operator_step": next_step,
            "last_checked_at": now,
        },
    )

    for file_name in JSONL_FILES:
        _replace_jsonl(source_dir / file_name, [])

    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": "social",
                "source_record_id": f"social-composio-setup:{now}",
                "display_name": "Composio Social Accounts",
                "timestamp": now,
                "title": "Connect social accounts in Composio",
                "status": "open",
                "task_type": "connector_setup",
                "approval_required": False,
                "owner_agent": owner,
                "summary": next_step,
                "agent_prompt_path": str(prompt_path),
                "agent_prompt": prompt,
                "confidence": 0.9,
                "tags": ["connector-setup", "composio", "social-media"],
                "target_ui_surfaces": ["Settings", "Social Media", "Leads", "Tasks"],
            }
        ],
    )
    _write_json(
        artifacts_dir / "setup-checklist.json",
        {
            "source_id": "social",
            "owner_agent": owner,
            "created_at": now,
            "steps": [
                "Connect the operator's Composio account in Elevate Settings/config.",
                "Add approved social apps inside Composio.",
                "Confirm read scopes for metrics, posts, comments, and DMs.",
                "Run the social sync/import agent prompt to write local records.",
                "Keep outbound replies and posts approval-gated.",
            ],
        },
    )
    view = connector_view(source_root, "social")
    if view is None:
        raise RuntimeError("Composio social scaffold was written but could not be read")
    return view


def scaffold_source(source_id: str, config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    blueprint = _blueprint(source_id)
    if not blueprint:
        raise ValueError(f"Unknown source connector: {source_id}")

    if source_id == "apple-messages":
        return initialize_apple_messages_source(config)
    if source_id == "social":
        return scaffold_composio_social_source(config)
    if source_id == "crm":
        integrations = _as_dict(config.get("integrations"))
        crm = _merge_crm(integrations.get("crm"))
        provider = str(crm.get("provider") or "").lower()
        env_values = _combined_env(config)
        if provider == "lofty" or (not provider and env_values.get("LOFTY_API_KEY")):
            return sync_lofty_crm_source(config)
        if provider in {"followupboss", "sierra", "boldtrail", "brivity", "custom"}:
            return sync_generic_crm_source(config)
        return sync_lofty_crm_source(config)
    if source_id == "xposure-pcs":
        # Real scraper + canonical writethrough lives in its own module
        # (the source_connectors file is already 5,800 lines and the
        # scraper is replaceable — keep it isolated).
        from elevate_cli.xposure_pcs_connector import sync_xposure_pcs_source

        # skip_scraper honored via env so cron + manual /api/source-
        # connectors/{id}/run can choose to reuse the latest snapshot
        # without burning a Lofty session.
        skip = bool(os.getenv("ELEVATE_XPOSURE_SKIP_SCRAPER"))
        return sync_xposure_pcs_source(config, skip_scraper=skip)
    if source_id == "buyer-brief":
        from elevate_cli.xposure_pcs_enrichment import run_enrichment

        return run_enrichment(config)
    if source_id == "xposure-pcs-views":
        # Per-listing engagement scrape (one-way mirror Client View).
        # Reuses the same Lofty/Xposure session as xposure-pcs but runs
        # on its own 48h cadence so we can re-fetch view counts without
        # re-running the criteria scrape every time.
        from elevate_cli.xposure_pcs_views import run_views_sync

        skip = bool(os.getenv("ELEVATE_XPOSURE_VIEWS_SKIP_SCRAPER"))
        views_cfg = _as_dict(config.get("xposure_pcs_views")) or config
        return run_views_sync(views_cfg, skip_scraper=skip)

    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, source_id)
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = _now()
    surfaces = UI_BY_SOURCE.get(source_id, ["Settings"])
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    prompt = source_prompt_for(source_id)
    prompt_path = artifacts_dir / "agent-setup-prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    _write_json(
        source_dir / "source.json",
        {
            "source_id": source_id,
            "provider": blueprint["source"],
            "account_label": f"{blueprint['source']} setup",
            "connection_type": "agent_setup_task",
            "auth_status": "needs_agent_or_operator",
            "sync_mode": "agent_build_required",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "needs_agent_setup",
            "last_sync_at": now,
            "setup_notes": (
                "No live account is connected yet. Elevate created a local setup prompt and task "
                "for the agent/operator to build the real webhook, poller, import command, or local bridge."
            ),
            "agent_setup_prompt_path": str(prompt_path),
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": False,
            "blocked": False,
            "last_error": None,
            "next_operator_step": (
                f"Run the agent setup prompt at {prompt_path} to build the {blueprint['source']} "
                "connector. No records are imported until that connector exists."
            ),
            "last_checked_at": now,
        },
    )

    _replace_jsonl(source_dir / "contacts.jsonl", [])
    _replace_jsonl(source_dir / "conversations.jsonl", [])
    _replace_jsonl(source_dir / "messages.jsonl", [])
    _replace_jsonl(source_dir / "message-days.jsonl", [])
    _replace_jsonl(source_dir / "lead-events.jsonl", [])
    _replace_jsonl(
        source_dir / "tasks.jsonl",
        [
            {
                "source_id": source_id,
                "source_record_id": f"{source_id}-agent-setup:{now}",
                "display_name": blueprint["source"],
                "timestamp": now,
                "title": f"Build {blueprint['source']} connector",
                "status": "open",
                "task_type": "connector_setup",
                "approval_required": False,
                "owner_agent": owner,
                "summary": (
                    "Use the generated setup prompt to create the real read-only connector, "
                    "then write normalized source records for the Hub."
                ),
                "agent_prompt_path": str(prompt_path),
                "agent_prompt": prompt,
                "confidence": 0.86,
                "tags": ["connector-setup", "agent-build-required"],
                "target_ui_surfaces": ["Settings", "Tasks"],
            }
        ],
    )
    _write_json(
        artifacts_dir / "setup-checklist.json",
        {
            "source_id": source_id,
            "owner_agent": owner,
            "created_at": now,
            "steps": [
                "Confirm provider/account and allowed data scope.",
                "Choose webhook, poller, import command, or local bridge.",
                "Create read-only credentials or export path.",
                "Normalize contacts, conversations, messages, lead events, and tasks.",
                "Mark status.json as connected, import_only, blocked, or needs_operator with exact next step.",
            ],
        },
    )
    view = connector_view(source_root, source_id)
    if view is None:
        raise RuntimeError("Connector scaffold was written but could not be read")
    return view


from elevate_cli.source_connector_modules.integration_settings import (
    DEFAULT_CRM,
    _CRM_PROVIDER_ALIASES,
    _CRM_PROVIDER_ENV_DEFAULTS,
    _as_dict,
    _candidate_tools_root,
    _canonical_crm_provider,
    _combined_env,
    _configured_composio_server,
    _crm_to_ui,
    _expand_path,
    _merge_crm,
    _provider_from_admin_profile,
    _ui_crm_to_config,
    get_integration_settings,
    get_source_root_info,
    save_integration_settings,
    test_crm_connection,
)
