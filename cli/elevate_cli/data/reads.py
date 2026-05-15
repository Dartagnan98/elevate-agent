"""Sprint 2: DB-derived response builders.

These mirror the legacy ``build_source_inbox_response`` and
``build_thread_context_response`` in ``elevate_cli.source_connectors``,
but read from the central operational store instead of JSONL files.
The shadow-read wrapper executes both during Sprint 2 and writes a
parity snapshot for every difference; once the 3-day window is clean
``ELEVATE_DATA_PRIMARY=db`` flips reads onto this module.

Scope notes (the legacy builders pull from several places that don't
live in operational.db yet — Sprint 3+ closes those gaps):

* ``drafts`` / ``skippedDrafts`` / ``pendingDraft`` come from
  ``tasks.jsonl`` + per-source ``ui-state.json``. The DB has no draft
  table today (the draft event_kind exists but the connector still
  writes the JSONL). Returned empty here so parity diffs surface the
  gap explicitly rather than masking it.
* ``sources`` (the connector blueprint view) and ``source.{label,
  category, ownerAgent, connected}`` are read from blueprint files /
  status.json — operational.db doesn't model connector state. We reuse
  the existing ``connector_view`` helper rather than re-implementing it,
  so this module is the only one that needs to track the V1 schema; the
  cosmetic source metadata stays where it lives.
* ``leadLabel`` / ``score`` come from the legacy ``thread_meta`` table
  in outreach.db. Until lead-scoring writes through the data module
  (Sprint 4 attribution chain) we surface the operational ``heat_label``
  / ``heat_score`` instead — that's the closest equivalent and what the
  UI already keys on.

Anything we can't represent yet returns the same shape with empty/None
values, NOT a missing key. The shadow-read parity diff comparison
handles missing-key vs None-value differently, so empty placeholders
keep the diff readable.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elevate_cli.data import connect


# ─── Helpers ───────────────────────────────────────────────────────────


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _payload_body(payload_json: str | None) -> str:
    """Pull ``body`` out of an event payload JSON blob. Inbound and
    outbound events both store ``{"body": "..."}``; older outbound
    events also nest ``draftAttemptId`` next to it."""
    if not payload_json:
        return ""
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return ""
    if isinstance(payload, dict):
        body = payload.get("body")
        if isinstance(body, str):
            return body
    return ""


def _heat_label_for(score: int) -> str:
    """Mirror legacy thresholds so the wrapper can compare apples to
    apples. Source-of-truth lives in source_connectors._heat_score_for_record;
    we only need the bucketing here, not the scorer."""
    if score >= 80:
        return "hot"
    if score >= 50:
        return "warm"
    if score >= 20:
        return "watch"
    return "normal"


def db_private_search_buyers(
    conn: sqlite3.Connection, *, limit: int = 50
) -> list[dict[str, Any]]:
    """DB-backed equivalent of ``_read_private_search_buyers``.

    Returns ``BuyerWatchlistEntry`` rows by joining ``contacts`` (the
    source of truth — ``buyer_search_active`` flag is set by review_contact)
    with ``pcs_buyers`` (per-contact MLS scoring detail). Matches the JSONL
    reader's sort order: score desc (CRM-native preferred over heat), then
    most-recent activity first.

    Surfaced fields match ``web/src/lib/api-types.ts::BuyerWatchlistEntry``.
    """
    rows = conn.execute(
        """
        SELECT
          c.id,
          c.display_name,
          c.primary_email,
          c.primary_phone,
          c.heat_score,
          c.heat_label,
          c.updated_at,
          pb.score                  AS pcs_score,
          pb.tier                   AS pcs_tier,
          pb.days                   AS pcs_days,
          pb.last_activity_at       AS pcs_last_activity,
          pb.last_scraped_at        AS pcs_last_scraped,
          pb.profile_url            AS pcs_profile_url,
          pb.searches_json,
          pb.matching_listings_json
        FROM contacts c
        LEFT JOIN pcs_buyers pb ON pb.contact_id = c.id
        WHERE c.buyer_search_active = 1
           OR pb.contact_id IS NOT NULL
        ORDER BY COALESCE(pb.score, c.heat_score, 0) DESC,
                 COALESCE(pb.last_activity_at, c.updated_at) DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()

    entries: list[dict[str, Any]] = []
    for row in rows:
        def _list_from_json(blob: str | None) -> list[str]:
            if not blob:
                return []
            try:
                parsed = json.loads(blob)
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
            if not isinstance(parsed, list):
                return []
            return [str(x) for x in parsed if x]

        score_val: int | None = None
        if row["pcs_score"] is not None:
            score_val = _safe_int(row["pcs_score"], default=0)
        elif row["heat_score"] is not None:
            score_val = _safe_int(row["heat_score"], default=0)

        entries.append({
            "id": row["id"],
            "name": row["display_name"] or "Unnamed buyer",
            "email": row["primary_email"],
            "phone": row["primary_phone"],
            "score": score_val,
            "tier": row["pcs_tier"],
            "days": row["pcs_days"],
            "lastActivity": row["pcs_last_activity"],
            "dateEntered": None,
            "searches": _list_from_json(row["searches_json"]),
            "matchingListings": _list_from_json(row["matching_listings_json"]),
            "profileUrl": row["pcs_profile_url"],
            "source": "mls-private-search",
            "sourceLabel": "MLS private search",
            "tags": [],
            "scrapedAt": row["pcs_last_scraped"],
        })
    return entries


# ─── Source inbox ──────────────────────────────────────────────────────


def db_source_inbox_response(*, limit: int = 16) -> dict[str, Any]:
    """DB-derived equivalent of
    :func:`elevate_cli.source_connectors.build_source_inbox_response`.

    Returns the same top-level keys (``toolsRoot``, ``sourceRoot``,
    ``limit``, ``recordCounts``, ``hiddenCounts``, ``sources``,
    ``profiles``, ``threads``, ``drafts``, ``skippedDrafts``,
    ``privateSearchBuyers``) so the shadow-read diff is field-by-field
    rather than reshape-vs-reshape.
    """
    # Reuse the connector blueprint walker — connector metadata lives
    # outside operational.db (status files, blueprint definitions) and
    # always will. Importing inside the function keeps the data module
    # free of a top-level dep on source_connectors.
    from elevate_cli.source_connectors import (
        SOURCE_CONNECTION_BLUEPRINTS,
        _discover_composio_views,
        _profiles_from_threads,
        connector_view,
        get_source_root_info,
    )

    info = get_source_root_info(None)
    source_root = Path(info["sourceRoot"])
    safe_limit = max(1, min(int(limit or 16), 5000))
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]))) is not None
    ]
    existing_ids = {str(view.get("id") or "") for view in connectors}
    for extra in _discover_composio_views(source_root):
        if str(extra.get("id") or "") not in existing_ids:
            connectors.append(extra)
    source_by_id = {str(source.get("id") or ""): source for source in connectors}

    threads: list[dict[str, Any]] = []
    totals = {
        "sources": 0,
        "threads": 0,
        "messages": 0,
        "conversations": 0,
        "contacts": 0,
        "hotThreads": 0,
        "drafts": 0,
        # Contact-level (AI-maintained) flag counts — these back the
        # /leads dashboard widgets directly. After review_contact runs,
        # these reflect the actual source of truth.
        "hotContacts": 0,
        "warmContacts": 0,
        "needsFollowUpContacts": 0,
        "buyerSearchContacts": 0,
        "listingActiveContacts": 0,
    }

    with connect() as conn:
        # Total counts come straight from SQL — no per-source walking.
        totals["contacts"] = _safe_int(
            conn.execute("SELECT COUNT(*) AS c FROM contacts").fetchone()["c"]
        )
        totals["conversations"] = _safe_int(
            conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()["c"]
        )
        totals["messages"] = _safe_int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE kind IN ('inbound','outbound')"
            ).fetchone()["c"]
        )
        # "sources" totals = how many connectors actually have rows.
        active_sources = {
            row["source_id"]
            for row in conn.execute(
                "SELECT DISTINCT source_id FROM conversations"
            ).fetchall()
        }
        totals["sources"] = len(active_sources)

        # Contact-flag counts — these are what /leads widgets show.
        # `hotContacts` answers "how many people are hot leads" rather
        # than "how many threads have a hot heat", which is what the
        # legacy threads-array filter measured. Closed contacts are
        # excluded because they live on /admin.
        flag_row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN heat_label='hot'            THEN 1 ELSE 0 END) AS hot,
              SUM(CASE WHEN heat_label='warm'           THEN 1 ELSE 0 END) AS warm,
              SUM(CASE WHEN needs_follow_up = 1         THEN 1 ELSE 0 END) AS nfu,
              SUM(CASE WHEN buyer_search_active = 1     THEN 1 ELSE 0 END) AS bsa,
              SUM(CASE WHEN listing_active = 1          THEN 1 ELSE 0 END) AS la
            FROM contacts
            WHERE stage != 'closed'
            """,
        ).fetchone()
        totals["hotContacts"] = _safe_int(flag_row["hot"])
        totals["warmContacts"] = _safe_int(flag_row["warm"])
        totals["needsFollowUpContacts"] = _safe_int(flag_row["nfu"])
        totals["buyerSearchContacts"] = _safe_int(flag_row["bsa"])
        totals["listingActiveContacts"] = _safe_int(flag_row["la"])

        # Fetch a slice of conversations large enough to mirror the
        # legacy "candidate_records_for_source" walk. Order by
        # heat_score desc, last_inbound_at desc to match the post-walk
        # sort the legacy code does.
        rows = conn.execute(
            """
            SELECT c.*, ct.display_name, ct.primary_email, ct.primary_phone
            FROM conversations c
            LEFT JOIN contacts ct ON ct.id = c.contact_id
            WHERE c.status = 'open'
            ORDER BY c.heat_score DESC,
                     COALESCE(c.last_inbound_at, c.last_outbound_at) DESC
            LIMIT ?
            """,
            (safe_limit * 4,),
        ).fetchall()

        for row in rows:
            conv_id = row["id"]
            source_id = row["source_id"]
            thread_key = row["thread_key"]
            heat_score = _safe_int(row["heat_score"])
            heat_label = row["heat_label"] or _heat_label_for(heat_score)
            inbound = _safe_int(row["inbound_count"])
            outbound = _safe_int(row["outbound_count"])

            latest_event = conn.execute(
                """
                SELECT kind, payload_json, ts
                FROM events
                WHERE conversation_id = ?
                  AND kind IN ('inbound','outbound')
                ORDER BY ts DESC LIMIT 1
                """,
                (conv_id,),
            ).fetchone()
            latest_text = _payload_body(latest_event["payload_json"]) if latest_event else ""
            latest_at = latest_event["ts"] if latest_event else (
                row["last_inbound_at"] or row["last_outbound_at"]
            )
            direction = (
                "inbound" if latest_event and latest_event["kind"] == "inbound"
                else ("outbound" if latest_event else None)
            )

            person_name = row["display_name"] or ""
            source_view = source_by_id.get(source_id, {})
            record = {
                "display_name": person_name,
                "email": row["primary_email"],
                "emails": [row["primary_email"]] if row["primary_email"] else [],
                "phone": row["primary_phone"],
                "phones": [row["primary_phone"]] if row["primary_phone"] else [],
                "source_id": source_id,
                "conversation_id": thread_key,
                "contact_id": row["contact_id"],
            }

            # Match the legacy id format so existing UI keys stay valid.
            thread = {
                "id": f"{source_id}:{thread_key}",
                "sourceId": source_id,
                "sourceLabel": str(source_view.get("label") or source_id),
                "sourceState": source_view.get("state"),
                "threadId": thread_key,
                "conversationId": conv_id,
                "contactId": row["contact_id"],
                "personName": person_name,
                "channel": row["channel"],
                "latestText": latest_text,
                "latestAt": latest_at,
                "direction": direction,
                "messageCount": inbound + outbound,
                "inboundCount": inbound,
                "outboundCount": outbound,
                "heatScore": heat_score,
                "heatLabel": heat_label,
                "status": row["status"],
                # operational.db doesn't carry the lead_score meta yet —
                # surface heat as the placeholder.
                "score": None,
                "leadLabel": None,
                "scoreReason": None,
                "scoredAt": None,
                "record": record,
            }
            if heat_label == "hot":
                totals["hotThreads"] += 1
            threads.append(thread)

    visible_threads = threads[:safe_limit]
    totals["threads"] = len(threads)
    # Drafts/skipped-drafts: operational.db has no draft table yet, so we
    # delegate to the same JSONL/outreach_db helpers the legacy builder
    # uses. Codex audit P0 (2026-05-05): DB-primary readers were dropping
    # the draft queue entirely, leaving /leads empty under
    # ELEVATE_DATA_PRIMARY=db.
    from elevate_cli.source_connectors import (  # noqa: E402
        _collect_drafts_for_db_inbox,
    )
    from datetime import timedelta

    skipped_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    drafts, skipped_drafts = _collect_drafts_for_db_inbox(
        source_root=source_root,
        connectors=connectors,
        threads=threads,
        skipped_cutoff=skipped_cutoff,
        max_drafts=24,
    )
    profiles = _profiles_from_threads(threads, source_by_id)
    totals["drafts"] = len(drafts)
    totals["people"] = len(profiles)
    totals["crmPeople"] = sum(1 for profile in profiles if profile.get("hasCrm"))
    totals["conversationPeople"] = sum(1 for profile in profiles if profile.get("hasConversation"))
    totals["potentialLeads"] = sum(
        1
        for profile in profiles
        if profile.get("isPotentialLead") and not profile.get("hasCrm")
    )
    hidden_counts = {"done": 0, "archived": 0}
    with connect() as conn:
        for status in hidden_counts:
            hidden_counts[status] = _safe_int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM conversations WHERE status = ?",
                    (status,),
                ).fetchone()["c"]
            )
        private_search_buyers = db_private_search_buyers(
            conn,
            limit=max(safe_limit, 50),
        )

    return {
        **info,
        "limit": safe_limit,
        "recordCounts": totals,
        "hiddenCounts": hidden_counts,
        "sources": connectors,
        "profiles": profiles[:safe_limit],
        "threads": visible_threads,
        "drafts": drafts[:safe_limit],
        "skippedDrafts": skipped_drafts[: max(safe_limit, 50)],
        "privateSearchBuyers": private_search_buyers,
    }


# ─── Thread context ────────────────────────────────────────────────────


def db_thread_context_response(
    source_id: str,
    thread_id: str,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """DB-derived equivalent of
    :func:`elevate_cli.source_connectors.build_thread_context_response`.

    Looks up the conversation by ``(source_id, thread_key)`` and aggregates
    messages from the events log, contact details, tasks, notes, and
    lifecycle activity.
    """
    from elevate_cli.source_connectors import (
        _resolve_source_view,
        get_source_root_info,
    )

    info = get_source_root_info(None)
    source_root = Path(info["sourceRoot"])
    source = _resolve_source_view(source_root, source_id)
    safe_limit = max(20, min(int(limit or 200), 500))

    messages: list[dict[str, Any]] = []
    person_name = ""
    lead_payload: dict[str, Any] | None = None
    activity_records: list[dict[str, Any]] = []
    last_inbound_at: str | None = None
    last_outbound_at: str | None = None

    with connect() as conn:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE source_id=? AND thread_key=?",
            (source_id, thread_id),
        ).fetchone()

        if conv is not None:
            contact = conn.execute(
                "SELECT * FROM contacts WHERE id=?",
                (conv["contact_id"],),
            ).fetchone()
            if contact is not None:
                person_name = contact["display_name"] or ""

            # Codex audit P2 (2026-05-05): bound the messages fetch by
            # safe_limit at the SQL layer instead of loading every event
            # for the conversation and slicing in Python. Threads with
            # thousands of inbound/outbound events were churning memory
            # for no benefit. idx_events_conv_ts(conversation_id, ts) makes
            # this an indexed reverse range scan. Final list is reversed
            # to ASC for the UI shape.
            event_rows = conn.execute(
                """
                SELECT id, kind, payload_json, ts, actor
                FROM events
                WHERE conversation_id = ?
                  AND kind IN ('inbound','outbound')
                ORDER BY ts DESC
                LIMIT ?
                """,
                (conv["id"], safe_limit),
            ).fetchall()
            for ev in reversed(event_rows):  # restore ASC for UI
                body = _payload_body(ev["payload_json"])
                if not body:
                    continue
                direction = ev["kind"]
                sender = (
                    person_name if direction == "inbound" else None
                )
                messages.append(
                    {
                        "id": ev["id"],
                        "direction": direction,
                        "sender": sender,
                        "text": body,
                        "timestamp": ev["ts"],
                    }
                )
            last_inbound_at = conv["last_inbound_at"]
            last_outbound_at = conv["last_outbound_at"]

            if contact is not None:
                # Activity: lifecycle events for this contact, newest first.
                activity_rows = conn.execute(
                    """
                    SELECT id, kind, payload_json, ts
                    FROM events
                    WHERE contact_id = ?
                      AND kind IN (
                        'classified','parked','unparked','lifecycle_change',
                        'note','merge','merge_conflict','pcs_activity',
                        'reply_attributed'
                      )
                    ORDER BY ts DESC LIMIT 20
                    """,
                    (contact["id"],),
                ).fetchall()
                for ev in activity_rows:
                    payload: dict[str, Any] = {}
                    if ev["payload_json"]:
                        try:
                            payload = json.loads(ev["payload_json"])
                        except (TypeError, json.JSONDecodeError):
                            payload = {}
                    summary = (
                        payload.get("note")
                        or payload.get("reason")
                        or payload.get("type")
                        or None
                    )
                    activity_records.append(
                        {
                            "id": ev["id"],
                            "type": ev["kind"],
                            "title": summary,
                            "summary": summary,
                            "timestamp": ev["ts"],
                        }
                    )

                # Lead detail block — pulled straight from contacts row.
                emails = (
                    [contact["primary_email"]] if contact["primary_email"] else []
                )
                phones = (
                    [contact["primary_phone"]] if contact["primary_phone"] else []
                )
                lead_payload = {
                    "leadId": contact["id"],
                    "displayName": contact["display_name"] or person_name,
                    "stage": contact["stage"],
                    "leadSource": None,
                    "assignedUser": None,
                    "score": None,
                    "tags": [],
                    "summary": contact["owner_notes"],
                    "emails": emails,
                    "phones": phones,
                    "channel": conv["channel"],
                    "timestamp": contact["last_activity_at"],
                    "lastSeenAt": contact["last_activity_at"],
                }

    source_block: dict[str, Any]
    if source is not None:
        source_block = {
            "id": source.get("id"),
            "label": source.get("label"),
            "category": source.get("category"),
            "ownerAgent": source.get("ownerAgent"),
            "connected": source.get("connected"),
        }
    else:
        # Match the legacy 404 behavior: callers wrap this in a try/except
        # and translate ValueError into HTTP 404. Keeping the contract
        # the same so the wrapper doesn't have to special-case.
        raise ValueError(f"Unknown source connector: {source_id}")

    # pendingDraft / sends / meta / notes still live outside operational.db
    # (tasks.jsonl + outreach.db + lead-events.jsonl). Codex audit P0
    # (2026-05-05): the DB-primary builder was returning None/[] for all
    # of these, which silently emptied the lead drawer. Delegate to the
    # same helpers the legacy builder uses.
    from elevate_cli.source_connectors import (  # noqa: E402
        _as_dict,
        _draft_from_task,
        _is_message_draft_task,
        _read_jsonl_records,
        _read_source_ui_state,
        _source_dir,
        _thread_key,
    )

    source_dir = _source_dir(source_root, source_id)
    ui_state = _read_source_ui_state(source_dir)
    task_states = _as_dict(ui_state.get("tasks"))
    pending_draft: dict[str, Any] | None = None
    for record in _read_jsonl_records(source_dir / "tasks.jsonl", limit=200):
        if not _is_message_draft_task(record):
            continue
        if _thread_key(record) != thread_id:
            continue
        task_id = str(record.get("id") or record.get("task_id") or "")
        state = _as_dict(task_states.get(task_id))
        status = str(state.get("status") or record.get("status") or "pending").lower()
        if status in {"approved", "done", "archived", "cancelled", "skipped"}:
            continue
        if source is not None:
            pending_draft = _draft_from_task(source, record, state)
        break

    notes_records: list[dict[str, Any]] = []
    tasks_records: list[dict[str, Any]] = []
    # tail=True so the most-recent notes are surfaced even when the file
    # has >4000 lifetime events (Codex audit P2, 2026-05-05).
    for record in _read_jsonl_records(source_dir / "lead-events.jsonl", limit=4000, tail=True):
        if str(record.get("contact_id") or record.get("conversation_id") or "").strip() != thread_id:
            continue
        event_type = str(record.get("type") or record.get("event_type") or "event").strip()
        timestamp = record.get("timestamp") or record.get("created_at") or record.get("last_seen_at")
        rec_id = str(record.get("source_record_id") or record.get("id") or "")
        if event_type != "lofty_note":
            if event_type == "lofty_task":
                tasks_records.append(
                    {
                        "id": rec_id,
                        "title": record.get("title") or "Task",
                        "summary": record.get("summary") or record.get("text") or "",
                        "status": record.get("status") or "open",
                        "dueAt": record.get("dueAt") or record.get("due_at"),
                        "timestamp": timestamp,
                    }
                )
                continue
            activity_records.append(
                {
                    "id": rec_id,
                    "type": event_type,
                    "subtype": record.get("subtype"),
                    "title": record.get("title") or record.get("summary") or record.get("text"),
                    "summary": record.get("summary") or record.get("text"),
                    "address": record.get("address"),
                    "timestamp": timestamp,
                }
            )
            continue
        notes_records.append(
            {
                "id": rec_id,
                "title": record.get("title") or "Note",
                "summary": record.get("summary") or record.get("text") or "",
                "author": record.get("author"),
                "timestamp": timestamp,
            }
        )

    sends: list[dict[str, Any]] = []
    meta: dict[str, Any] | None = None
    try:
        from elevate_cli import outreach_db as _odb
        sends = _odb.list_sends_by_thread(source_id, thread_id, limit=50)
        meta = _odb.get_thread_meta(source_id, thread_id)
    except Exception:
        sends = []
        meta = None

    return {
        "sourceId": source_id,
        "threadId": thread_id,
        "source": source_block,
        "personName": person_name or "Client",
        "messageCount": len(messages),
        "messages": messages,
        "lastInboundAt": last_inbound_at,
        "lastOutboundAt": last_outbound_at,
        "pendingDraft": pending_draft,
        "sends": sends,
        "meta": meta,
        "lead": lead_payload,
        "notes": notes_records,
        "tasks": tasks_records,
        "activity": activity_records,
    }
