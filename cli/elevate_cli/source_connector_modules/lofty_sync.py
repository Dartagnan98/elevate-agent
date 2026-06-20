"""Lofty CRM source sync and enrichment."""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.connector_views import connector_view
from elevate_cli.source_connector_modules.source_catalog import JSONL_FILES, OWNER_BY_SOURCE, UI_BY_SOURCE
from elevate_cli.source_connector_modules.source_io import (
    _read_jsonl_records,
    _replace_jsonl,
    _snapshot_writer_lock,
    _source_dir,
    _write_json,
)


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


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
        "checkpointed_at": _source_connectors()._now(),
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
    source_connectors = _source_connectors()
    events: list[JsonRecord] = []
    summary = {"activities": 0, "notes": 0, "tasks": 0, "errors": 0}

    try:
        activity_payload = source_connectors._lofty_get_activities(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        activity_payload = []
        summary["errors"] += 1
    for raw_act in activity_payload:
        norm = source_connectors._lofty_normalize_activity(raw_act, lead_id)
        act_id = norm["id"] or source_connectors._stable_hash_id(
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
        notes_payload = source_connectors._lofty_get_notes(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        notes_payload = []
        summary["errors"] += 1
    for raw_note in notes_payload:
        norm = source_connectors._lofty_normalize_note(raw_note, lead_id)
        note_id = norm["id"] or source_connectors._stable_hash_id(
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
        tasks_payload = source_connectors._lofty_get_tasks(lead_id, env_values, timeout=timeout)
    except Exception:  # noqa: BLE001
        tasks_payload = []
        summary["errors"] += 1
    tasks_payload = [t for t in tasks_payload if not t.get("deleteFlag")]
    for raw_task in tasks_payload:
        norm = source_connectors._lofty_normalize_task(raw_task, lead_id)
        task_id = norm["id"] or source_connectors._stable_hash_id(
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
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, "crm")
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = source_connectors._now()
    surfaces = UI_BY_SOURCE["crm"]
    owner = OWNER_BY_SOURCE["crm"]
    env_values = source_connectors._combined_env(config)
    headers, auth_type = source_connectors._lofty_headers(env_values)

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
                payload = source_connectors._lofty_get(path, env_values, params)
            except Exception as exc:
                errors.append(f"{path}@offset={offset}: {exc}")
                break
            extracted = source_connectors._extract_lead_records(payload)
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
        name = source_connectors._lofty_lead_name(lead)
        timestamp = source_connectors._lofty_timestamp(lead)
        stage = str(lead.get("stage") or lead.get("aiStage") or lead.get("status") or "").strip()
        source = str(lead.get("source") or lead.get("leadSource") or "").strip()
        tags = source_connectors._tag_names(lead.get("tags"))
        score = source_connectors._safe_int(lead.get("score") or lead.get("leadScore"), 45)
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
                "total_messages": source_connectors._safe_int(lead.get("activityCount") or lead.get("taskCount"), 1),
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

        heat_score, heat_label = source_connectors._heat_score_for_record(base_record)
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
        source_connectors._walk_jsonl_into_pg(source_dir)
    except Exception as exc:  # noqa: BLE001
        if errors is not None:
            errors.append(f"db writethrough (phase 1): {exc}")
        _write_json(
            artifacts_dir / "last-db-writethrough-error.json",
            {"checked_at": source_connectors._now(), "phase": 1, "error": str(exc)},
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
        source_connectors._walk_jsonl_into_pg(source_dir)
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
