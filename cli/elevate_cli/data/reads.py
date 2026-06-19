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


_FOLLOWUP_CHANNELS = {
    "email",
    "gmail",
    "sms",
    "imessage",
    "messenger",
    "facebook",
    "instagram",
    "instagram_dm",
    "whatsapp",
    "telegram",
}

_LEAD_SECTION_DEFS = {
    "hot": ("Hot leads", "contacts.heat_label or conversations.heat_label"),
    "warm": ("Warm leads", "contacts.heat_label"),
    "follow_up": (
        "Follow-ups",
        "contacts.needs_follow_up or open inbound conversation after outreach",
    ),
    "buyer_search": (
        "Buyer searches",
        "contacts.buyer_search_active or pcs_buyers.contact_id",
    ),
    "listing_active": ("Listing activity", "contacts.listing_active"),
    "messages": ("Messages", "open conversations"),
    "drafts": ("Drafts", "approval queue"),
    "skipped": ("Skipped", "recently skipped approval queue"),
    "favorites": ("Favorites", "lead_profile_flags.favorite"),
}

_SUPPRESSED_PIPELINE_STATUSES = {"dead", "closed_seller", "closed_buyer"}


def _new_lead_sections() -> dict[str, dict[str, Any]]:
    return {
        section_id: {
            "id": section_id,
            "label": label,
            "source": source,
            "count": 0,
            "contactIds": [],
            "threadIds": [],
            "profileIds": [],
            "draftIds": [],
            "buyerIds": [],
        }
        for section_id, (label, source) in _LEAD_SECTION_DEFS.items()
    }


def _append_unique(items: list[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text and text not in items:
        items.append(text)


def _add_section_item(
    sections: dict[str, dict[str, Any]],
    section_id: str,
    *,
    contact_id: Any = None,
    thread_id: Any = None,
    profile_id: Any = None,
    draft_id: Any = None,
    buyer_id: Any = None,
) -> None:
    section = sections.get(section_id)
    if section is None:
        return
    _append_unique(section["contactIds"], contact_id)
    _append_unique(section["threadIds"], thread_id)
    _append_unique(section["profileIds"], profile_id)
    _append_unique(section["draftIds"], draft_id)
    _append_unique(section["buyerIds"], buyer_id)


def _contact_section_ids(row: Any) -> set[str]:
    sections: set[str] = set()
    if row["heat_label"] == "hot":
        sections.add("hot")
    elif row["heat_label"] == "warm":
        sections.add("warm")
    if _safe_int(row["needs_follow_up"]) or row["pipeline_status"] == "follow_up":
        sections.add("follow_up")
    if _safe_int(row["buyer_search_active"]):
        sections.add("buyer_search")
    if _safe_int(row["listing_active"]):
        sections.add("listing_active")
    return sections


def _is_follow_up_thread(
    *,
    channel: Any,
    outbound_count: int,
    direction: str | None,
) -> bool:
    if str(channel or "").lower() not in _FOLLOWUP_CHANNELS:
        return False
    if outbound_count < 1:
        return False
    return direction == "inbound"


def _finalize_lead_sections(
    sections: dict[str, dict[str, Any]],
    *,
    totals: dict[str, int],
    buyer_search_count: int,
    drafts_count: int,
    skipped_count: int,
) -> dict[str, dict[str, Any]]:
    explicit_counts = {
        "hot": max(
            totals.get("hotContacts", 0),
            len(sections["hot"]["contactIds"]),
            len(sections["hot"]["threadIds"]),
        ),
        "warm": max(totals.get("warmContacts", 0), len(sections["warm"]["contactIds"])),
        "follow_up": max(
            totals.get("needsFollowUpContacts", 0),
            len(sections["follow_up"]["contactIds"]),
            len(sections["follow_up"]["threadIds"]),
        ),
        "buyer_search": max(
            buyer_search_count,
            len(sections["buyer_search"]["contactIds"]),
            len(sections["buyer_search"]["buyerIds"]),
        ),
        "listing_active": max(
            totals.get("listingActiveContacts", 0),
            len(sections["listing_active"]["contactIds"]),
        ),
        "messages": max(
            totals.get("threads", 0),
            len(sections["messages"]["threadIds"]),
        ),
        "drafts": drafts_count,
        "skipped": skipped_count,
        "favorites": len(sections["favorites"]["profileIds"]),
    }
    for section_id, section in sections.items():
        section["count"] = int(explicit_counts.get(section_id, 0))
    return sections


def _read_private_search_buyers_jsonl(
    source_root: Path,
) -> list[dict[str, Any]]:
    """Read the raw pipeline buyer entries from
    ``<source_root>/mls-private-search/buyers.jsonl``.

    Entries written by the PCS scraper aren't always tied to a CRM
    contact yet (manual pulls, brand-new buyers). The DB walk only
    surfaces buyers with a matching contact row, so we overlay the
    raw pipeline so nothing scored is hidden.
    """
    path = source_root / "mls-private-search" / "buyers.jsonl"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return []
    return entries


def db_private_search_buyers(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    source_root: Path | None = None,
) -> list[dict[str, Any]]:
    """DB-backed equivalent of ``_read_private_search_buyers``.

    Returns ``BuyerWatchlistEntry`` rows by joining ``contacts`` (the
    source of truth — ``buyer_search_active`` flag is set by review_contact)
    with ``pcs_buyers`` (per-contact MLS scoring detail). Matches the JSONL
    reader's sort order: score desc (CRM-native preferred over heat), then
    most-recent activity first.

    Pipeline entries written to ``mls-private-search/buyers.jsonl`` that
    don't yet match a CRM contact (by email/phone) are appended so the
    scraper's scored buyers stay visible.

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
        WHERE (c.buyer_search_active = 1 OR pb.contact_id IS NOT NULL)
          AND c.stage != 'closed'
          AND COALESCE(c.pipeline_status, '') NOT IN (
            'dead', 'closed_seller', 'closed_buyer'
          )
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
            "contactId": row["id"],
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
            "leadSectionIds": ["buyer_search"],
        })

    suppressed_identity_rows = conn.execute(
        """
        SELECT primary_email, primary_phone
        FROM contacts
        WHERE stage = 'closed'
           OR COALESCE(pipeline_status, '') IN (
             'dead', 'closed_seller', 'closed_buyer'
           )
        """
    ).fetchall()
    suppressed_emails = {
        (row["primary_email"] or "").strip().lower()
        for row in suppressed_identity_rows
        if row["primary_email"]
    }
    suppressed_phones = {
        "".join(ch for ch in (row["primary_phone"] or "") if ch.isdigit())
        for row in suppressed_identity_rows
        if row["primary_phone"]
    }

    # Overlay pipeline entries that don't already correspond to a
    # CRM contact in the DB walk. Matches the legacy JSONL reader: a
    # buyer is considered "already covered" if its email or phone
    # matches one of the DB rows.
    if source_root is None:
        try:
            from elevate_cli.source_connectors import get_source_root_info
            source_root = Path(get_source_root_info(None)["sourceRoot"])
        except Exception:
            source_root = None

    if source_root is not None:
        pipeline = _read_private_search_buyers_jsonl(source_root)
        if pipeline:
            covered_emails = {
                (e["email"] or "").strip().lower()
                for e in entries
                if e.get("email")
            }
            covered_phones = {
                "".join(ch for ch in (e["phone"] or "") if ch.isdigit())
                for e in entries
                if e.get("phone")
            }
            for raw in pipeline:
                email = (raw.get("email") or "").strip().lower()
                phone_digits = "".join(
                    ch for ch in str(raw.get("phone") or "") if ch.isdigit()
                )
                if email and email in suppressed_emails:
                    continue
                if phone_digits and phone_digits in suppressed_phones:
                    continue
                if email and email in covered_emails:
                    continue
                if phone_digits and phone_digits in covered_phones:
                    continue
                entry = dict(raw)
                entry["leadSectionIds"] = sorted({
                    *[str(x) for x in entry.get("leadSectionIds", []) if x],
                    "buyer_search",
                })
                entries.append(entry)

    def _sort_key(entry: dict[str, Any]) -> tuple[int, int, int]:
        score = entry.get("score")
        score_val = -int(score) if isinstance(score, (int, float)) else 0
        days = entry.get("days")
        days_val = int(days) if isinstance(days, (int, float)) else 9999
        has_score = 0 if isinstance(score, (int, float)) else 1
        return (has_score, score_val, days_val)

    entries.sort(key=_sort_key)
    return entries[: max(int(limit), 1)]


# ─── Source inbox ──────────────────────────────────────────────────────


def db_source_inbox_response(*, limit: int = 16) -> dict[str, Any]:
    """DB-derived equivalent of
    :func:`elevate_cli.source_connectors.build_source_inbox_response`.

    Returns the same top-level keys (``toolsRoot``, ``sourceRoot``,
    ``limit``, ``recordCounts``, ``hiddenCounts``, ``sources``,
    ``profiles``, ``threads``, ``drafts``, ``skippedDrafts``,
    ``privateSearchBuyers``) plus ``leadSections``. ``leadSections`` is
    the operational-db lane contract for /leads: every lead card gets
    section ids from stored contact/conversation cells instead of each
    UI lane re-deriving its own membership.
    """
    # Reuse the connector blueprint walker — connector metadata lives
    # outside operational.db (status files, blueprint definitions) and
    # always will. Importing inside the function keeps the data module
    # free of a top-level dep on source_connectors.
    from elevate_cli.source_connectors import (
        SOURCE_CONNECTION_BLUEPRINTS,
        _discover_composio_views,
        _profiles_from_threads,
        _read_json,
        _source_dir,
        connector_view,
        get_apple_messages_directions,
        get_source_root_info,
    )

    info = get_source_root_info(None)
    source_root = Path(info["sourceRoot"])
    safe_limit = max(1, min(int(limit or 16), 5000))
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]), include_prompt=False)) is not None
    ]
    existing_ids = {str(view.get("id") or "") for view in connectors}
    for extra in _discover_composio_views(source_root):
        if str(extra.get("id") or "") not in existing_ids:
            connectors.append(extra)
    source_by_id = {str(source.get("id") or ""): source for source in connectors}

    threads: list[dict[str, Any]] = []
    lead_sections = _new_lead_sections()
    contact_sections: dict[str, set[str]] = {}
    thread_sections_by_id: dict[str, set[str]] = {}
    buyer_search_count = 0
    suppressed_contact_ids: set[str] = set()
    profile_status_by_contact: dict[str, dict[str, Any]] = {}
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
        "favoriteProfiles": 0,
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
              SUM(CASE WHEN needs_follow_up = 1
                          OR pipeline_status = 'follow_up'
                                                        THEN 1 ELSE 0 END) AS nfu,
              SUM(CASE WHEN buyer_search_active = 1     THEN 1 ELSE 0 END) AS bsa,
              SUM(CASE WHEN listing_active = 1          THEN 1 ELSE 0 END) AS la
            FROM contacts
            WHERE stage != 'closed'
              AND COALESCE(pipeline_status, '') NOT IN (
                'dead', 'closed_seller', 'closed_buyer'
              )
            """,
        ).fetchone()
        totals["hotContacts"] = _safe_int(flag_row["hot"])
        totals["warmContacts"] = _safe_int(flag_row["warm"])
        totals["needsFollowUpContacts"] = _safe_int(flag_row["nfu"])
        totals["buyerSearchContacts"] = _safe_int(flag_row["bsa"])
        totals["listingActiveContacts"] = _safe_int(flag_row["la"])
        buyer_search_count = _safe_int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT c.id) AS c
                FROM contacts c
                LEFT JOIN pcs_buyers pb ON pb.contact_id = c.id
                WHERE c.stage != 'closed'
                  AND COALESCE(c.pipeline_status, '') NOT IN (
                    'dead', 'closed_seller', 'closed_buyer'
                  )
                  AND (c.buyer_search_active = 1 OR pb.contact_id IS NOT NULL)
                """,
            ).fetchone()["c"]
        )
        totals["buyerSearchContacts"] = buyer_search_count

        suppressed_contact_ids = {
            str(row["id"])
            for row in conn.execute(
                """
                SELECT id
                FROM contacts
                WHERE stage = 'closed'
                   OR COALESCE(pipeline_status, '') IN (
                     'dead', 'closed_seller', 'closed_buyer'
                   )
                """
            ).fetchall()
            if row["id"]
        }

        contact_rows = conn.execute(
            """
            SELECT
              id,
              heat_label,
              needs_follow_up,
              buyer_search_active,
              listing_active,
              pipeline_status
            FROM contacts
            WHERE stage != 'closed'
              AND COALESCE(pipeline_status, '') NOT IN (
                'dead', 'closed_seller', 'closed_buyer'
              )
            ORDER BY COALESCE(last_activity_at, updated_at) DESC
            LIMIT ?
            """,
            (max(safe_limit * 8, 5000),),
        ).fetchall()
        for contact_row in contact_rows:
            contact_id = str(contact_row["id"] or "")
            contact_sections[contact_id] = _contact_section_ids(contact_row)
            for section_id in contact_sections[contact_id]:
                _add_section_item(
                    lead_sections,
                    section_id,
                    contact_id=contact_id,
                )

        pcs_contact_rows = conn.execute(
            """
            SELECT DISTINCT pb.contact_id
            FROM pcs_buyers pb
            JOIN contacts c ON c.id = pb.contact_id
            WHERE pb.contact_id IS NOT NULL
              AND c.stage != 'closed'
              AND COALESCE(c.pipeline_status, '') NOT IN (
                'dead', 'closed_seller', 'closed_buyer'
              )
            LIMIT ?
            """,
            (max(safe_limit * 8, 500),),
        ).fetchall()
        for pcs_row in pcs_contact_rows:
            contact_id = str(pcs_row["contact_id"] or "")
            if not contact_id:
                continue
            contact_sections.setdefault(contact_id, set()).add("buyer_search")
            _add_section_item(
                lead_sections,
                "buyer_search",
                contact_id=contact_id,
            )

        # Fetch a slice of conversations large enough to mirror the
        # legacy "candidate_records_for_source" walk. Order by
        # heat_score desc, last_inbound_at desc to match the post-walk
        # sort the legacy code does.
        rows = conn.execute(
            """
            SELECT
              c.*,
              ct.display_name,
              ct.primary_email,
              ct.primary_phone,
              ct.stage AS contact_stage,
              ct.heat_label AS contact_heat_label,
              ct.needs_follow_up AS contact_needs_follow_up,
              ct.buyer_search_active AS contact_buyer_search_active,
              ct.listing_active AS contact_listing_active,
              ct.pipeline_status AS contact_pipeline_status,
              ct.pipeline_status_set_at AS contact_pipeline_status_set_at,
              latest_event.kind AS latest_event_kind,
              latest_event.payload_json AS latest_event_payload_json,
              latest_event.ts AS latest_event_ts
            FROM conversations c
            LEFT JOIN contacts ct ON ct.id = c.contact_id
            LEFT JOIN LATERAL (
              SELECT e.kind, e.payload_json, e.ts
              FROM events e
              WHERE e.conversation_id = c.id
                AND e.kind IN ('inbound','outbound')
              ORDER BY e.ts DESC
              LIMIT 1
            ) latest_event ON TRUE
            WHERE c.status = 'open'
              AND (
                ct.id IS NULL
                OR (
                  ct.stage != 'closed'
                  AND COALESCE(ct.pipeline_status, '') NOT IN (
                    'dead', 'closed_seller', 'closed_buyer'
                  )
                )
              )
            ORDER BY c.heat_score DESC,
                     COALESCE(c.last_inbound_at, c.last_outbound_at) DESC
            LIMIT ?
            """,
            (max(safe_limit * 4, 5000),),
        ).fetchall()

        for row in rows:
            conv_id = row["id"]
            source_id = row["source_id"]
            thread_key = row["thread_key"]
            heat_score = _safe_int(row["heat_score"])
            heat_label = row["heat_label"] or _heat_label_for(heat_score)
            inbound = _safe_int(row["inbound_count"])
            outbound = _safe_int(row["outbound_count"])

            latest_kind = row["latest_event_kind"]
            latest_text = _payload_body(row["latest_event_payload_json"]) if latest_kind else ""
            latest_at = row["latest_event_ts"] if latest_kind else (
                row["last_inbound_at"] or row["last_outbound_at"]
            )
            direction = (
                "inbound" if latest_kind == "inbound"
                else ("outbound" if latest_kind else None)
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

            contact_id = str(row["contact_id"] or "")
            lead_section_ids = set(contact_sections.get(contact_id, set()))
            lead_section_ids.add("messages")
            if heat_label == "hot" or row["contact_heat_label"] == "hot":
                lead_section_ids.add("hot")
            elif row["contact_heat_label"] == "warm":
                lead_section_ids.add("warm")
            if _safe_int(row["contact_needs_follow_up"]) or _is_follow_up_thread(
                channel=row["channel"],
                outbound_count=outbound,
                direction=direction,
            ):
                lead_section_ids.add("follow_up")
            if row["contact_pipeline_status"] == "follow_up":
                lead_section_ids.add("follow_up")
            if _safe_int(row["contact_buyer_search_active"]):
                lead_section_ids.add("buyer_search")
            if _safe_int(row["contact_listing_active"]):
                lead_section_ids.add("listing_active")

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
                "leadSectionIds": sorted(lead_section_ids),
                "record": record,
            }
            if heat_label == "hot":
                totals["hotThreads"] += 1
            threads.append(thread)
            thread_sections_by_id[thread["id"]] = lead_section_ids
            for section_id in lead_section_ids:
                _add_section_item(
                    lead_sections,
                    section_id,
                    contact_id=contact_id,
                    thread_id=thread["id"],
                )

    visible_threads = threads[:safe_limit]
    totals["threads"] = len(threads)
    # Drafts/skipped-drafts: operational.db has no draft table yet, so we
    # delegate to the same JSONL/outreach_db helpers the legacy builder
    # uses. Codex audit P0 (2026-05-05): DB-primary readers were dropping
    # the draft queue entirely, leaving /leads empty under
    # ELEVATE_DATA_PRIMARY=db.
    from elevate_cli.source_connectors import (  # noqa: E402
        SOURCE_INBOX_DRAFT_QUEUE_LIMIT,
        _collect_drafts_for_db_inbox,
    )
    from datetime import timedelta

    skipped_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    draft_limit = max(safe_limit, SOURCE_INBOX_DRAFT_QUEUE_LIMIT)
    drafts, skipped_drafts = _collect_drafts_for_db_inbox(
        source_root=source_root,
        connectors=connectors,
        threads=threads,
        skipped_cutoff=skipped_cutoff,
        max_drafts=draft_limit,
    )
    if suppressed_contact_ids:
        drafts = [
            draft for draft in drafts
            if str(draft.get("contactId") or "") not in suppressed_contact_ids
        ]
        skipped_drafts = [
            draft for draft in skipped_drafts
            if str(draft.get("contactId") or "") not in suppressed_contact_ids
        ]
    for draft in drafts:
        section_ids = sorted({
            *[str(x) for x in draft.get("leadSectionIds", []) if x],
            "drafts",
        })
        draft["leadSectionIds"] = section_ids
        thread_id = (
            f"{draft.get('sourceId')}:{draft.get('threadId')}"
            if draft.get("sourceId") and draft.get("threadId")
            else draft.get("threadId")
        )
        _add_section_item(
            lead_sections,
            "drafts",
            contact_id=draft.get("contactId"),
            thread_id=thread_id,
            draft_id=draft.get("id") or draft.get("taskId"),
        )
    for draft in skipped_drafts:
        section_ids = sorted({
            *[str(x) for x in draft.get("leadSectionIds", []) if x],
            "skipped",
        })
        draft["leadSectionIds"] = section_ids
        thread_id = (
            f"{draft.get('sourceId')}:{draft.get('threadId')}"
            if draft.get("sourceId") and draft.get("threadId")
            else draft.get("threadId")
        )
        _add_section_item(
            lead_sections,
            "skipped",
            contact_id=draft.get("contactId"),
            thread_id=thread_id,
            draft_id=draft.get("id") or draft.get("taskId"),
        )
    profiles = _profiles_from_threads(threads, source_by_id)
    profile_contact_ids = sorted({
        str(contact_id)
        for profile in profiles
        for contact_id in profile.get("contactIds", [])
        if str(contact_id or "").strip()
    })
    profile_ids = [
        str(profile.get("id") or "")
        for profile in profiles
        if str(profile.get("id") or "").strip()
    ]
    profile_flags_by_id: dict[str, Any] = {}
    for profile in profiles:
        profile_section_ids: set[str] = set()
        for contact_id in profile.get("contactIds", []):
            profile_section_ids.update(contact_sections.get(str(contact_id), set()))
        for thread_id in profile.get("threadIds", []):
            profile_section_ids.update(thread_sections_by_id.get(str(thread_id), set()))
        profile["leadSectionIds"] = sorted(profile_section_ids)
        for section_id in profile_section_ids:
            _add_section_item(
                lead_sections,
                section_id,
                profile_id=profile.get("id"),
            )
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
        if profile_contact_ids:
            placeholders = ",".join("?" for _ in profile_contact_ids)
            for row in conn.execute(
                f"""
                SELECT id, pipeline_status, pipeline_status_set_at
                FROM contacts
                WHERE id IN ({placeholders})
                """,
                profile_contact_ids,
            ).fetchall():
                profile_status_by_contact[str(row["id"])] = {
                    "status": row["pipeline_status"],
                    "updated_at": row["pipeline_status_set_at"],
                }
        if profile_ids:
            placeholders = ",".join("?" for _ in profile_ids)
            for row in conn.execute(
                f"""
                SELECT profile_id, contact_id, favorite, favorited_at, favorited_by
                FROM lead_profile_flags
                WHERE profile_id IN ({placeholders})
                """,
                profile_ids,
            ).fetchall():
                profile_flags_by_id[str(row["profile_id"])] = row
        private_search_buyers = db_private_search_buyers(
            conn,
            limit=max(safe_limit, 50),
            source_root=source_root,
        )
    for profile in profiles:
        db_status = None
        for contact_id in profile.get("contactIds", []):
            candidate = profile_status_by_contact.get(str(contact_id))
            if candidate and candidate.get("status"):
                db_status = candidate
                break
        profile["status"] = db_status.get("status") if db_status else None
        profile["statusUpdatedAt"] = db_status.get("updated_at") if db_status else None
        flag = profile_flags_by_id.get(str(profile.get("id") or ""))
        is_favorite = bool(flag and flag["favorite"])
        profile["favorite"] = is_favorite
        profile["favoritedAt"] = flag["favorited_at"] if flag else None
        profile["favoritedBy"] = flag["favorited_by"] if flag else None
        if is_favorite:
            profile["leadSectionIds"] = sorted({
                *[str(x) for x in profile.get("leadSectionIds", []) if x],
                "favorites",
            })
            _add_section_item(
                lead_sections,
                "favorites",
                profile_id=profile.get("id"),
            )
            for contact_id in profile.get("contactIds", []):
                _add_section_item(lead_sections, "favorites", contact_id=contact_id)
            for thread_id in profile.get("threadIds", []):
                _add_section_item(lead_sections, "favorites", thread_id=thread_id)
    totals["favoriteProfiles"] = len(lead_sections["favorites"]["profileIds"])
    for buyer in private_search_buyers:
        section_ids = sorted({
            *[str(x) for x in buyer.get("leadSectionIds", []) if x],
            "buyer_search",
        })
        buyer["leadSectionIds"] = section_ids
        _add_section_item(
            lead_sections,
            "buyer_search",
            contact_id=buyer.get("contactId"),
            buyer_id=buyer.get("id"),
        )
    lead_sections = _finalize_lead_sections(
        lead_sections,
        totals=totals,
        buyer_search_count=buyer_search_count,
        drafts_count=len(drafts),
        skipped_count=len(skipped_drafts),
    )

    am_dirs = get_apple_messages_directions(None)
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
        "leadSections": lead_sections,
        "sources": connectors,
        "appleMessages": apple_messages,
        "profiles": profiles[:safe_limit],
        "threads": visible_threads,
        "drafts": drafts[:draft_limit],
        "skippedDrafts": skipped_drafts[: max(draft_limit, 50)],
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

    # The dashboard builds profile.threadIds as ``<source_id>:<thread_key>``
    # (see ``_thread_from_record`` in source_connectors.py, line 715), then
    # the buyer-search row passes ``profile.threadIds[0]`` straight into
    # ``openThread(sourceId, threadId)``. The route splits source_id off the
    # URL path but leaves the rest as-is, so we receive
    # ``thread_id="crm:lofty-lead:1138..."`` even though contacts.id and
    # conversations.thread_key are stored as ``lofty-lead:1138...``.
    # Defensively strip a leading ``<source_id>:`` so both URL shapes work.
    if thread_id.startswith(f"{source_id}:"):
        thread_id = thread_id[len(source_id) + 1 :]

    messages: list[dict[str, Any]] = []
    person_name = ""
    lead_payload: dict[str, Any] | None = None
    activity_records: list[dict[str, Any]] = []
    notes_records: list[dict[str, Any]] = []
    tasks_records: list[dict[str, Any]] = []
    last_inbound_at: str | None = None
    last_outbound_at: str | None = None

    with connect() as conn:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE source_id=? AND thread_key=?",
            (source_id, thread_id),
        ).fetchone()

        # Lofty leads (and any CRM lead created without an inbound message)
        # have a contacts row but NO conversations row. Without this fallback
        # the drawer's contact lookup never runs, so every card (Lead Score,
        # Notes, Property Activity, Send History) renders empty even though
        # the contact row in the DB is fully populated. For CRM sources the
        # thread_id == contacts.id (e.g. "lofty-lead:1138815640363819"), so
        # try the contact directly if no conversation matches.
        contact: Any = None
        if conv is not None:
            contact = conn.execute(
                "SELECT * FROM contacts WHERE id=?",
                (conv["contact_id"],),
            ).fetchone()
        else:
            contact = conn.execute(
                "SELECT * FROM contacts WHERE id=?",
                (thread_id,),
            ).fetchone()

        if contact is not None:
            person_name = contact["display_name"] or ""

        # Messages only exist when there's a conversations row. Lofty
        # leads typically have no inbound message yet, so this block
        # is a no-op for them — the lead/activity/notes blocks below
        # still populate from the contacts + events tables.
        if conv is not None:
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
            if True:
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
                    ORDER BY ts DESC LIMIT 500
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
                    legacy_type = payload.get("legacyType") or payload.get("legacy_type")
                    summary = (
                        payload.get("note")
                        or payload.get("summary")
                        or payload.get("text")
                        or payload.get("title")
                        or payload.get("reason")
                        or payload.get("type")
                        or legacy_type
                        or None
                    )
                    title = (
                        payload.get("title")
                        or payload.get("subject")
                        or legacy_type
                        or summary
                    )
                    if legacy_type == "crm_task":
                        tasks_records.append(
                            {
                                "id": ev["id"],
                                "title": title or "Task",
                                "summary": summary or "",
                                "status": payload.get("status") or "open",
                                "dueAt": payload.get("dueAt") or payload.get("due_at"),
                                "timestamp": ev["ts"],
                            }
                        )
                        continue
                    if legacy_type == "crm_note":
                        notes_records.append(
                            {
                                "id": ev["id"],
                                "title": title or "Note",
                                "summary": summary or "",
                                "author": payload.get("author"),
                                "timestamp": ev["ts"],
                            }
                        )
                        continue
                    activity_records.append(
                        {
                            "id": ev["id"],
                            "type": legacy_type or ev["kind"],
                            "subtype": payload.get("subtype"),
                            "title": title,
                            "summary": summary,
                            "address": payload.get("address"),
                            "timestamp": ev["ts"],
                        }
                    )

                # Lead detail block — pulled straight from contacts row.
                # Convert the row to a dict so we can use .get() — the
                # Lofty enrichment columns (migration 0012) are optional
                # in older DBs and KeyError'ing here would 500 the drawer.
                try:
                    contact_dict = dict(contact)
                except (TypeError, ValueError):
                    contact_dict = {
                        k: contact[k] for k in contact.keys()  # type: ignore[attr-defined]
                    }

                emails = (
                    [contact["primary_email"]] if contact["primary_email"] else []
                )
                phones = (
                    [contact["primary_phone"]] if contact["primary_phone"] else []
                )

                # Tags: stored as JSON text; decode for the UI.
                tags_raw = contact_dict.get("tags_json")
                tags_list: list[Any] = []
                if isinstance(tags_raw, str) and tags_raw.strip():
                    try:
                        parsed = json.loads(tags_raw)
                        if isinstance(parsed, list):
                            tags_list = [str(t) for t in parsed if t]
                    except (TypeError, json.JSONDecodeError):
                        tags_list = []

                # Same trick for segments / leadTypes — drawer surfaces both.
                def _decode_json_list(key: str) -> list[Any]:
                    raw = contact_dict.get(key)
                    if not isinstance(raw, str) or not raw.strip():
                        return []
                    try:
                        parsed = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        return []
                    return parsed if isinstance(parsed, list) else []

                segments_list = _decode_json_list("segments_json")
                lead_types_list = _decode_json_list("lead_types_json")

                # Lofty's lead_score (0-100, behavioral) takes priority for
                # display; fall back to our heat_score so older rows still
                # show a number.
                lofty_score = contact_dict.get("lead_score")
                fallback_score = contact_dict.get("heat_score")
                display_score = (
                    lofty_score if lofty_score is not None else fallback_score
                )

                lead_payload = {
                    "leadId": contact["id"],
                    "displayName": contact["display_name"] or person_name,
                    "stage": contact["stage"],
                    "crmStage": contact_dict.get("crm_stage"),
                    "leadSource": contact_dict.get("lead_source"),
                    "assignedUser": contact_dict.get("assigned_agent"),
                    "score": display_score,
                    "tags": tags_list,
                    "segments": segments_list,
                    "leadTypes": lead_types_list,
                    "summary": contact["owner_notes"],
                    "emails": emails,
                    "phones": phones,
                    "channel": conv["channel"] if conv is not None else None,
                    "timestamp": contact["last_activity_at"],
                    "lastSeenAt": contact["last_activity_at"],
                    # Qualification / buyer-seller profile from Lofty.
                    "buyingTimeFrame": contact_dict.get("buying_time_frame"),
                    "sellingTimeFrame": contact_dict.get("selling_time_frame"),
                    "preQualStatus": contact_dict.get("pre_qual_status"),
                    "mortgageStatus": contact_dict.get("mortgage_status"),
                    "firstTimeHomeBuyer": contact_dict.get("first_time_home_buyer"),
                    "hasHouseToSell": contact_dict.get("has_house_to_sell"),
                    "withBuyerAgent": contact_dict.get("with_buyer_agent"),
                    "withListingAgent": contact_dict.get("with_listing_agent"),
                    "buyHouseIntent": contact_dict.get("buy_house_intent"),
                    "opportunity": contact_dict.get("opportunity"),
                    "referredBy": contact_dict.get("referred_by"),
                    "pondId": contact_dict.get("pond_id"),
                    "pondName": contact_dict.get("pond_name"),
                    # Consent flags — drive the contact toolbar in the drawer.
                    "cannotText": bool(contact_dict.get("cannot_text") or 0),
                    "cannotCall": bool(contact_dict.get("cannot_call") or 0),
                    "cannotEmail": bool(contact_dict.get("cannot_email") or 0),
                    "unsubscribed": bool(contact_dict.get("unsubscribed") or 0),
                    "hidden": bool(contact_dict.get("hidden") or 0),
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
