"""Source inbox draft queue assembly helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.connector_views import (
    _candidate_records_for_source,
    _discover_composio_views,
    connector_view,
)
from elevate_cli.source_connector_modules.draft_helpers import (
    _draft_from_task,
    _draft_from_thread,
    _is_message_draft_task,
    _task_key,
)
from elevate_cli.source_connector_modules.integration_settings import _as_dict
from elevate_cli.source_connector_modules.private_search import _read_private_search_buyers
from elevate_cli.source_connector_modules.profile_helpers import (
    _is_social_intent,
    _profiles_from_threads,
    _source_has_inbox_records,
    _source_record_counts,
)
from elevate_cli.source_connector_modules.source_catalog import (
    SOURCE_CONNECTION_BLUEPRINTS,
    SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
)
from elevate_cli.source_connector_modules.source_io import (
    _parse_record_dt,
    _read_json,
    _read_jsonl_records,
    _read_profile_state,
    _read_source_ui_state,
    _safe_int,
    _source_dir,
)
from elevate_cli.source_connector_modules.thread_helpers import (
    _is_automated_sender_record,
    _thread_from_record,
    _thread_key,
)


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def build_source_inbox_response(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 16,
) -> JsonRecord:
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    safe_limit = max(1, min(int(limit or 16), 5000))
    draft_limit = max(safe_limit, SOURCE_INBOX_DRAFT_QUEUE_LIMIT)
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]), include_prompt=False)) is not None
    ]
    # Fold in the composio per-toolkit dirs so messages pulled by the
    # inbound puller surface in /leads alongside Apple Messages and CRM.
    existing_ids = {str(view.get("id") or "") for view in connectors}
    for extra in _discover_composio_views(source_root):
        if str(extra.get("id") or "") in existing_ids:
            continue
        connectors.append(extra)

    threads: list[JsonRecord] = []
    drafts: list[JsonRecord] = []
    skipped_drafts: list[JsonRecord] = []
    skipped_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    hidden_counts = {"done": 0, "archived": 0}
    totals = {
        "sources": 0,
        "threads": 0,
        "messages": 0,
        "conversations": 0,
        "contacts": 0,
        "hotThreads": 0,
        "drafts": 0,
    }
    seen: set[str] = set()
    seen_drafts: set[str] = set()
    # Canonical key: (source_id, thread_id) → "this thread already has a
    # real persisted draft, don't stack a fallback on top." Codex audit
    # P1 (2026-05-05): real AI drafts must supersede fallback drafts.
    seen_thread_drafts: set[tuple[str, str]] = set()
    task_state_by_source: dict[str, JsonRecord] = {}

    # Phase 6: enrich each thread with lead-scorer meta (score / label / reason)
    # so lane skills + dashboard see scorer state alongside heatLabel. Bulk-load
    # BEFORE we walk records — we need the dead label to short-circuit
    # enumeration so dead threads don't pollute the hotThreads counter or the
    # default leads view. Dashboard still shows them via /api/threads/meta?label=dead.
    try:
        from elevate_cli import outreach_db as _odb
        _meta_by_key: dict[tuple[str, str], dict[str, Any]] = {
            (m["sourceId"], m["threadId"]): m for m in _odb.list_thread_meta(limit=1000)
        }
    except Exception:
        _meta_by_key = {}

    for source in connectors:
        counts = _source_record_counts(source)
        totals["sources"] += 1 if _source_has_inbox_records(source) else 0
        totals["messages"] += _safe_int(counts.get("messages"))
        totals["conversations"] += _safe_int(counts.get("conversations"))
        totals["contacts"] += _safe_int(counts.get("contacts"))
        source_id = str(source.get("id") or "")
        source_dir = _source_dir(source_root, source_id)
        ui_state = _read_source_ui_state(source_dir)
        thread_states = _as_dict(ui_state.get("threads"))
        task_states = _as_dict(ui_state.get("tasks"))
        task_state_by_source[source_id] = task_states

        for record in _candidate_records_for_source(source_dir, source, safe_limit):
            thread_id = _thread_key(record)
            state = _as_dict(thread_states.get(thread_id))
            status = str(state.get("status") or "open")
            if status in ("done", "archived"):
                hidden_counts[status] = hidden_counts.get(status, 0) + 1
                continue
            thread = _thread_from_record(source, record, status=status)
            if thread["id"] in seen:
                continue

            # Attach scorer meta and short-circuit dead threads BEFORE the
            # hotThreads counter so the dashboard total reflects actionable leads.
            _meta = _meta_by_key.get((str(thread.get("sourceId") or ""), str(thread.get("threadId") or "")))
            if _meta:
                thread["score"] = _meta.get("score")
                thread["leadLabel"] = _meta.get("label")
                thread["scoreReason"] = _meta.get("reason")
                thread["scoredAt"] = _meta.get("scoredAt")
            else:
                thread["score"] = None
                thread["leadLabel"] = None
                thread["scoreReason"] = None
                thread["scoredAt"] = None

            if thread.get("leadLabel") == "dead":
                continue

            seen.add(thread["id"])
            if thread["heatLabel"] == "hot":
                totals["hotThreads"] += 1
            threads.append(thread)

        # 2026-05-26: drop tail=True. The CRM sync's tasks.jsonl rewrite
        # preserves drafts at the HEAD of the file (preserved_tasks +
        # task_records, source_connectors.py:3799) and then appends fresh
        # lead_follow_up rows. tail=True was the right pick before the
        # preserve change landed (c6ba97cae) — at that point drafts were
        # always at the bottom because the file was rewritten from scratch.
        # Now the opposite is true: tail=True reads only follow-up
        # tombstones and silently drops every message_draft. In a large Lofty
        # workspace this previously meant 182 pending drafts -> 0 in the inbox.
        # Bump the limit so a head-scan still picks them all up even after
        # several sync cycles.
        for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
            if not _is_message_draft_task(record):
                continue
            task_id = _task_key(record)
            state = _as_dict(task_states.get(task_id))
            status = str(state.get("status") or record.get("status") or "pending").lower()
            thread_meta = _meta_by_key.get((source_id, _thread_key(record)))
            if status == "skipped":
                updated_dt = _parse_record_dt(state.get("updated_at"))
                if updated_dt and updated_dt >= skipped_cutoff:
                    draft = _draft_from_task(source, record, state)
                    draft["skippedAt"] = state.get("updated_at")
                    if thread_meta:
                        draft["score"] = thread_meta.get("score")
                        draft["leadLabel"] = thread_meta.get("label")
                        draft["scoreReason"] = thread_meta.get("reason")
                    skipped_drafts.append(draft)
                continue
            if status in {"approved", "done", "archived", "cancelled"}:
                continue
            draft = _draft_from_task(source, record, state)
            if thread_meta:
                draft["score"] = thread_meta.get("score")
                draft["leadLabel"] = thread_meta.get("label")
                draft["scoreReason"] = thread_meta.get("reason")
            if draft["id"] in seen_drafts:
                continue
            seen_drafts.add(draft["id"])
            # Mark this thread as already having a real draft — fallback
            # generation below must skip it (Codex P1, 2026-05-05).
            persisted_thread_id = str(draft.get("threadId") or "").strip()
            if persisted_thread_id:
                seen_thread_drafts.add((source_id, persisted_thread_id))
            drafts.append(draft)

    threads.sort(
        key=lambda item: (
            _safe_int(item.get("heatScore")),
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    source_by_id = {str(source.get("id") or ""): source for source in connectors}
    for thread in threads:
        if len(drafts) >= draft_limit:
            break
        if str(thread.get("direction") or "") != "inbound":
            continue
        if str(thread.get("heatLabel") or "") not in {"hot", "warm"} and not _is_social_intent(
            source_by_id.get(str(thread.get("sourceId") or ""), {}),
            thread,
        ):
            continue
        if _is_automated_sender_record(_as_dict(thread.get("record")) or thread):
            continue
        source_id = str(thread.get("sourceId") or "")
        thread_id_str = str(thread.get("threadId") or "")
        # Canonical key: if a real persisted draft already covers this
        # (source_id, thread_id), skip the fallback regardless of how
        # Codex chose to name the task_id (Codex P1, 2026-05-05).
        if thread_id_str and (source_id, thread_id_str) in seen_thread_drafts:
            continue
        task_id = f"thread-draft:{thread_id_str}"
        state = _as_dict(task_state_by_source.get(source_id, {}).get(task_id))
        status = str(state.get("status") or "").lower()
        if status in {"approved", "skipped", "done", "archived", "cancelled"}:
            continue
        generated_id = f"{source_id}:{task_id}"
        if generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
        if thread_id_str:
            seen_thread_drafts.add((source_id, thread_id_str))
        generated_draft = _draft_from_thread(source_by_id.get(source_id, {}), thread)
        if state.get("draft_text"):
            generated_draft["draftText"] = str(state.get("draft_text"))
        generated_draft["score"] = thread.get("score")
        generated_draft["leadLabel"] = thread.get("leadLabel")
        generated_draft["scoreReason"] = thread.get("scoreReason")
        drafts.append(generated_draft)

    drafts.sort(
        key=lambda item: (
            1 if item.get("generated") is False else 0,
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    profiles = _profiles_from_threads(threads, source_by_id)
    profile_state_entries = _as_dict(_read_profile_state(source_root).get("profiles"))
    # SQLite contacts.pipeline_status is the source of truth when a profile
    # has a linked contactId; fall back to the legacy JSON state file
    # otherwise (e.g. composio inbox threads with no CRM contact yet).
    db_status_by_contact: dict[str, dict[str, Any]] = {}
    try:
        from elevate_cli.data import connect as _db_connect
        contact_ids: list[str] = []
        for p in profiles:
            for cid in p.get("contactIds") or []:
                cid_s = str(cid or "").strip()
                if cid_s:
                    contact_ids.append(cid_s)
        if contact_ids:
            with _db_connect() as _conn:
                placeholders = ",".join("?" for _ in contact_ids)
                cur = _conn.execute(
                    f"SELECT id, pipeline_status, pipeline_status_set_at "
                    f"FROM contacts WHERE id IN ({placeholders})",
                    contact_ids,
                )
                for row in cur.fetchall():
                    db_status_by_contact[row["id"]] = {
                        "status": row["pipeline_status"],
                        "updated_at": row["pipeline_status_set_at"],
                    }
    except Exception:
        db_status_by_contact = {}
    for profile in profiles:
        db_entry: dict[str, Any] | None = None
        for cid in profile.get("contactIds") or []:
            entry = db_status_by_contact.get(str(cid))
            if entry and entry.get("status"):
                db_entry = entry
                break
        if db_entry is not None:
            profile["status"] = db_entry.get("status")
            profile["statusUpdatedAt"] = db_entry.get("updated_at")
        else:
            entry = _as_dict(profile_state_entries.get(str(profile.get("id") or "")))
            profile["status"] = entry.get("status")
            profile["statusUpdatedAt"] = entry.get("updated_at")
    visible_threads = threads[:safe_limit]
    totals["threads"] = len(threads)
    totals["drafts"] = len(drafts)
    totals["people"] = len(profiles)
    totals["crmPeople"] = sum(1 for profile in profiles if profile.get("hasCrm"))
    totals["conversationPeople"] = sum(1 for profile in profiles if profile.get("hasConversation"))
    totals["potentialLeads"] = sum(1 for profile in profiles if profile.get("isPotentialLead") and not profile.get("hasCrm"))
    skipped_drafts.sort(
        key=lambda item: _parse_record_dt(item.get("skippedAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    private_search_buyers = _read_private_search_buyers(source_root, limit=max(safe_limit, 50))
    # Real Apple Messages direction state + health for the /leads toggles and
    # the source-access banner. The banner must reflect REAL status (not a
    # hardcoded mock) and only nag when inbound is actually enabled: FDA is
    # only needed to READ chat.db, never to SEND.
    am_dirs = source_connectors.get_apple_messages_directions(config)
    am_status = _read_json(_source_dir(source_root, "apple-messages") / "status.json") or {}
    apple_messages = {
        "inbound": bool(am_dirs.get("inbound", True)),
        "outbound": bool(am_dirs.get("outbound", True)),
        "blocked": bool(am_dirs.get("inbound", True)) and bool(am_status.get("blocked")),
        "note": str(am_status.get("next_operator_step") or ""),
    }
    return {
        **info,
        "limit": safe_limit,
        "recordCounts": totals,
        "hiddenCounts": hidden_counts,
        "sources": connectors,
        "appleMessages": apple_messages,
        "profiles": profiles[:safe_limit],
        "threads": visible_threads,
        "drafts": drafts[:draft_limit],
        "skippedDrafts": skipped_drafts[: max(draft_limit, 50)],
        "privateSearchBuyers": private_search_buyers,
    }

def _collect_drafts_for_db_inbox(
    *,
    source_root: Path,
    connectors: list[JsonRecord],
    threads: list[JsonRecord],
    skipped_cutoff: datetime,
    max_drafts: int = SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
) -> tuple[list[JsonRecord], list[JsonRecord]]:
    """Build the same drafts/skippedDrafts buckets as
    :func:`build_source_inbox_response`, but driven by externally-provided
    ``connectors`` and ``threads`` lists (so the DB-primary builder can
    reuse the legacy draft pipeline without re-walking source dirs for
    threads).

    Codex audit P0 (2026-05-05): the DB readers were returning empty
    ``drafts`` / ``skippedDrafts`` arrays, which broke the /leads queue
    under ``ELEVATE_DATA_PRIMARY=db``. This helper collapses the
    persisted-draft + fallback-draft logic into a single shared codepath.
    """
    drafts: list[JsonRecord] = []
    skipped_drafts: list[JsonRecord] = []
    max_drafts = max(1, int(max_drafts or SOURCE_INBOX_DRAFT_QUEUE_LIMIT))
    seen_drafts: set[str] = set()
    seen_skipped_drafts: set[str] = set()
    seen_thread_drafts: set[tuple[str, str]] = set()
    task_state_by_source: dict[str, JsonRecord] = {}

    try:
        from elevate_cli import outreach_db as _odb
        _meta_by_key: dict[tuple[str, str], dict[str, Any]] = {
            (m["sourceId"], m["threadId"]): m for m in _odb.list_thread_meta(limit=1000)
        }
    except Exception:
        _meta_by_key = {}

    source_by_id = {str(s.get("id") or ""): s for s in connectors}

    for source in connectors:
        source_id = str(source.get("id") or "")
        source_dir = _source_dir(source_root, source_id)
        ui_state = _read_source_ui_state(source_dir)
        task_states = _as_dict(ui_state.get("tasks"))
        task_state_by_source[source_id] = task_states

        # 2026-05-26: drop tail=True. The CRM sync's tasks.jsonl rewrite
        # preserves drafts at the HEAD of the file (preserved_tasks +
        # task_records, source_connectors.py:3799) and then appends fresh
        # lead_follow_up rows. tail=True was the right pick before the
        # preserve change landed (c6ba97cae) — at that point drafts were
        # always at the bottom because the file was rewritten from scratch.
        # Now the opposite is true: tail=True reads only follow-up
        # tombstones and silently drops every message_draft. In a large Lofty
        # workspace this previously meant 182 pending drafts -> 0 in the inbox.
        # Bump the limit so a head-scan still picks them all up even after
        # several sync cycles.
        for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=5000):
            if not _is_message_draft_task(record):
                continue
            task_id = _task_key(record)
            state = _as_dict(task_states.get(task_id))
            status = str(state.get("status") or record.get("status") or "pending").lower()
            thread_meta = _meta_by_key.get((source_id, _thread_key(record)))
            if status == "skipped":
                updated_dt = _parse_record_dt(state.get("updated_at"))
                if updated_dt and updated_dt >= skipped_cutoff:
                    draft = _draft_from_task(source, record, state)
                    draft["skippedAt"] = state.get("updated_at")
                    if thread_meta:
                        draft["score"] = thread_meta.get("score")
                        draft["leadLabel"] = thread_meta.get("label")
                        draft["scoreReason"] = thread_meta.get("reason")
                    seen_skipped_drafts.add(str(draft.get("id") or ""))
                    skipped_drafts.append(draft)
                continue
            if status in {"approved", "done", "archived", "cancelled"}:
                continue
            draft = _draft_from_task(source, record, state)
            if thread_meta:
                draft["score"] = thread_meta.get("score")
                draft["leadLabel"] = thread_meta.get("label")
                draft["scoreReason"] = thread_meta.get("reason")
            if draft["id"] in seen_drafts:
                continue
            seen_drafts.add(draft["id"])
            persisted_thread_id = str(draft.get("threadId") or "").strip()
            if persisted_thread_id:
                seen_thread_drafts.add((source_id, persisted_thread_id))
            drafts.append(draft)

    def send_queue_draft(send: JsonRecord, *, skipped: bool = False) -> JsonRecord | None:
        source_id = str(send.get("sourceId") or "")
        thread_id_str = str(send.get("threadId") or "")
        if not source_id or not thread_id_str:
            return None
        source = source_by_id.get(source_id) or {"id": source_id, "label": source_id}
        payload = _as_dict(send.get("payload"))
        recipient = _as_dict(payload.get("recipient"))
        person_name = (
            str(recipient.get("person_name") or "").strip()
            or str(payload.get("person_name") or "").strip()
            or "Client"
        )
        draft_text = str(payload.get("draft_text") or "").strip() or "Draft text has not been generated yet."
        queue_id = str(send.get("id") or "")
        task_id = str(send.get("taskId") or queue_id)
        channel = str(send.get("channel") or "")
        draft: JsonRecord = {
            "id": f"{source_id}:send-queue:{queue_id}",
            "sourceId": source_id,
            "sourceLabel": str(source.get("label") or source_id),
            "taskId": task_id,
            "threadId": thread_id_str,
            "contactId": recipient.get("contact_id") or payload.get("contact_id"),
            "conversationId": recipient.get("conversation_id"),
            "personName": person_name,
            "channel": channel,
            "title": f"Approve first-touch draft for {person_name}",
            "draftText": draft_text,
            "context": "",
            "latestAt": str(send.get("updatedAt") or send.get("createdAt") or ""),
            "status": "skipped" if skipped else "pending",
            "approvalRequired": True,
            "generated": False,
            "fallback": False,
            "record": {},
        }
        if skipped:
            draft["skippedAt"] = str(send.get("updatedAt") or send.get("createdAt") or "")
        thread_meta = _meta_by_key.get((source_id, thread_id_str))
        if thread_meta:
            draft["score"] = thread_meta.get("score")
            draft["leadLabel"] = thread_meta.get("label")
            draft["scoreReason"] = thread_meta.get("reason")
        return draft

    # Source of truth: any send_queue row in pending_approval that isn't
    # already represented by a tasks.jsonl entry. Crons that write directly
    # to send_queue (e.g. run_fresh_first_touch_cron.py) sometimes race with
    # the tasks.jsonl append, or the jsonl head-of-file gets shadowed by
    # thousands of older lead_follow_up rows. Reading the PG table here
    # makes the /leads inbox self-healing.
    try:
        pending_sends = _odb.list_recent_sends(
            statuses=("pending_approval",), limit=max_drafts * 4
        )
    except Exception:
        pending_sends = []

    for send in pending_sends:
        if len(drafts) >= max_drafts:
            break
        synthesized = send_queue_draft(send)
        if not synthesized:
            continue
        source_id = str(synthesized.get("sourceId") or "")
        thread_id_str = str(synthesized.get("threadId") or "")
        if (source_id, thread_id_str) in seen_thread_drafts:
            continue
        generated_id = str(synthesized.get("id") or "")
        if not generated_id or generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
        seen_thread_drafts.add((source_id, thread_id_str))
        drafts.append(synthesized)

    try:
        skipped_sends = _odb.list_recent_sends(
            statuses=("skipped",), limit=max_drafts * 4
        )
    except Exception:
        skipped_sends = []

    for send in skipped_sends:
        updated_dt = _parse_record_dt(send.get("updatedAt"))
        if updated_dt and updated_dt < skipped_cutoff:
            continue
        synthesized = send_queue_draft(send, skipped=True)
        if not synthesized:
            continue
        generated_id = str(synthesized.get("id") or "")
        if not generated_id or generated_id in seen_skipped_drafts:
            continue
        seen_skipped_drafts.add(generated_id)
        skipped_drafts.append(synthesized)

    for thread in threads:
        if len(drafts) >= max_drafts:
            break
        if str(thread.get("direction") or "") != "inbound":
            continue
        if str(thread.get("heatLabel") or "") not in {"hot", "warm"} and not _is_social_intent(
            source_by_id.get(str(thread.get("sourceId") or ""), {}),
            thread,
        ):
            continue
        if _is_automated_sender_record(_as_dict(thread.get("record")) or thread):
            continue
        source_id = str(thread.get("sourceId") or "")
        thread_id_str = str(thread.get("threadId") or "")
        if thread_id_str and (source_id, thread_id_str) in seen_thread_drafts:
            continue
        task_id = f"thread-draft:{thread_id_str}"
        state = _as_dict(task_state_by_source.get(source_id, {}).get(task_id))
        status = str(state.get("status") or "").lower()
        if status in {"approved", "skipped", "done", "archived", "cancelled"}:
            continue
        generated_id = f"{source_id}:{task_id}"
        if generated_id in seen_drafts:
            continue
        seen_drafts.add(generated_id)
        if thread_id_str:
            seen_thread_drafts.add((source_id, thread_id_str))
        generated_draft = _draft_from_thread(source_by_id.get(source_id, {}), thread)
        if state.get("draft_text"):
            generated_draft["draftText"] = str(state.get("draft_text"))
        generated_draft["score"] = thread.get("score")
        generated_draft["leadLabel"] = thread.get("leadLabel")
        generated_draft["scoreReason"] = thread.get("scoreReason")
        drafts.append(generated_draft)

    drafts.sort(
        key=lambda item: (
            1 if item.get("generated") is False else 0,
            _parse_record_dt(item.get("latestAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    skipped_drafts.sort(
        key=lambda item: _parse_record_dt(item.get("skippedAt")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    return drafts, skipped_drafts
