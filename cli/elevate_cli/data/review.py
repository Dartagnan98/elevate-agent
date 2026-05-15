"""AI contact review — heat scoring + lane flags.

Maintains the four `contacts` flag columns introduced in migration 0013:

* ``heat_label``       hot|warm|watch|normal
* ``heat_score``       0-100
* ``heat_reason``      one-line audit string
* ``needs_follow_up``  0|1
* ``next_follow_up_at`` ISO ts (when needs_follow_up=1)
* ``buyer_search_active`` 0|1
* ``listing_active``    0|1

These flags back the /leads widgets directly — see ``data.reads`` and the
``source-inbox`` API. The dashboard reads contacts, never JSONL.

Scoring formula (v1):

  crm_floor      = max(pcs_buyers.score or 0, latest lead_signal score)
  event_score    = inbound velocity + reply timing + pcs intent + keywords
  final          = max(crm_floor, min(crm_floor + event_score, 100))

The CRM-native score acts as a floor — if Lofty already says someone is 80,
we don't drop them below 80 just because the event log is thin. We can
only push them higher.

Buckets: hot ≥76, warm 54-75, watch 35-53, normal <35.

Public surface:

* :func:`score_contact`         — score one contact, optionally write flags
* :func:`review_all_contacts`   — bulk run across all open contacts
* :data:`SCORING_VERSION`       — bump when formula changes

Closed contacts (``stage='closed'``) are skipped — they live on /admin and
their flags are forced to defaults by ``close_to_admin``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.data._util import new_id, now_iso
from elevate_cli.data.contacts import update_flags
from elevate_cli.data.notes import write_note


SCORING_VERSION = "v1.0"

# Bucket thresholds.
_HOT_THRESHOLD = 76
_WARM_THRESHOLD = 54
_WATCH_THRESHOLD = 35

# Keyword triggers in latest inbound text. Anything here adds the
# READY_KEYWORD_BOOST — these are explicit "I'm ready to act" signals.
_READY_KEYWORDS = re.compile(
    r"\b("
    r"ready|let'?s\s+(go|do|set)|let\s+me\s+know|"
    r"schedule|book|appointment|meeting|"
    r"want\s+to\s+see|show\s+me|interested\s+in|"
    r"buy|buying|sell|selling|list(?:ing)?\s+(?:my|the)|"
    r"offer|make\s+an\s+offer|cash\s+offer|"
    r"call\s+me|text\s+me|email\s+me"
    r")\b",
    re.IGNORECASE,
)


# ─── Helpers ────────────────────────────────────────────────────────────


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _crm_floor_for_contact(conn: sqlite3.Connection, contact_id: str) -> int:
    """CRM-native lead score from pcs_buyers (latest) or lead_signals payload.

    Returns 0 if no CRM-native score is present. This is the floor — the
    final heat_score will never be lower than this.
    """
    pcs = conn.execute(
        "SELECT score FROM pcs_buyers WHERE contact_id=?", (contact_id,)
    ).fetchone()
    if pcs and pcs["score"] is not None:
        try:
            return max(0, min(int(pcs["score"]), 100))
        except (TypeError, ValueError):
            pass

    # Fall back to graduated lead_signals payload — some CRMs stash a
    # `lead_score` or `heat_score` field in the raw payload.
    sig_row = conn.execute(
        "SELECT payload_json FROM lead_signals WHERE graduated_to_contact_id=? "
        "ORDER BY updated_at DESC LIMIT 1",
        (contact_id,),
    ).fetchone()
    if sig_row and sig_row["payload_json"]:
        try:
            payload = json.loads(sig_row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0
        for key in ("lead_score", "heat_score", "score"):
            val = payload.get(key) if isinstance(payload, dict) else None
            if val is None:
                continue
            try:
                return max(0, min(int(val), 100))
            except (TypeError, ValueError):
                continue
    return 0


def _latest_inbound_text(conn: sqlite3.Connection, contact_id: str) -> str:
    """Pull body text from the most recent inbound event payload."""
    row = conn.execute(
        "SELECT payload_json FROM events "
        "WHERE contact_id=? AND kind='inbound' "
        "ORDER BY ts DESC LIMIT 1",
        (contact_id,),
    ).fetchone()
    if not row or not row["payload_json"]:
        return ""
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("text", "body", "snippet", "message", "content"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _event_signal_payload(
    conn: sqlite3.Connection, contact_id: str, *, now: datetime
) -> dict[str, Any]:
    """Pull all event-derived facts for the contact in one pass.

    Returns inbound/outbound counts, latest timestamps, pcs activity, and
    saved-search recency. Keeps the heavy lifting in SQL so 1k+ contacts
    can be scored in seconds.
    """
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    cutoff_48h = (now - timedelta(hours=48)).isoformat()

    rows = conn.execute(
        """
        SELECT
          SUM(CASE WHEN kind='inbound'      AND ts >= ? THEN 1 ELSE 0 END) AS inbound_24h,
          SUM(CASE WHEN kind='inbound'      AND ts >= ? THEN 1 ELSE 0 END) AS inbound_7d,
          SUM(CASE WHEN kind='outbound'     AND ts >= ? THEN 1 ELSE 0 END) AS outbound_7d,
          SUM(CASE WHEN kind='pcs_activity' AND ts >= ? THEN 1 ELSE 0 END) AS pcs_7d,
          SUM(CASE WHEN kind='pcs_activity' AND ts >= ? THEN 1 ELSE 0 END) AS pcs_30d,
          SUM(CASE WHEN kind='inbound'                       THEN 1 ELSE 0 END) AS inbound_total,
          SUM(CASE WHEN kind='outbound'                      THEN 1 ELSE 0 END) AS outbound_total,
          MAX(CASE WHEN kind='inbound'      THEN ts END)                   AS latest_inbound,
          MAX(CASE WHEN kind='outbound'     THEN ts END)                   AS latest_outbound,
          MAX(CASE WHEN kind='inbound'      AND ts >= ? THEN ts END)       AS recent_inbound_48h
        FROM events
        WHERE contact_id=?
        """,
        (
            cutoff_24h,
            cutoff_7d,
            cutoff_7d,
            cutoff_7d,
            cutoff_30d,
            cutoff_48h,
            contact_id,
        ),
    ).fetchone()

    # pcs_buyers saved-search recency — CRM-native intent
    saved_search_row = conn.execute(
        "SELECT last_activity_at FROM pcs_buyers WHERE contact_id=?",
        (contact_id,),
    ).fetchone()
    saved_search_recent = False
    if saved_search_row and saved_search_row["last_activity_at"]:
        sa_dt = _parse_iso(saved_search_row["last_activity_at"])
        if sa_dt and sa_dt >= (now - timedelta(days=7)):
            saved_search_recent = True

    return {
        "inbound_24h": rows["inbound_24h"] or 0,
        "inbound_7d": rows["inbound_7d"] or 0,
        "outbound_7d": rows["outbound_7d"] or 0,
        "pcs_7d": rows["pcs_7d"] or 0,
        "pcs_30d": rows["pcs_30d"] or 0,
        "inbound_total": rows["inbound_total"] or 0,
        "outbound_total": rows["outbound_total"] or 0,
        "latest_inbound": rows["latest_inbound"],
        "latest_outbound": rows["latest_outbound"],
        "recent_inbound_48h": rows["recent_inbound_48h"],
        "saved_search_recent": saved_search_recent,
    }


# ─── Scoring ────────────────────────────────────────────────────────────


def _compute_score(
    *,
    crm_floor: int,
    signals: dict[str, Any],
    latest_inbound_text: str,
) -> tuple[int, str, list[str]]:
    """Pure scoring function — easy to unit test without a DB."""
    reasons: list[str] = []
    event_score = 0

    if signals["inbound_24h"] >= 1:
        event_score += 25
        reasons.append(f"inbound_24h={signals['inbound_24h']} (+25)")
    if signals["inbound_7d"] >= 3:
        event_score += 20
        reasons.append(f"inbound_7d={signals['inbound_7d']} (+20)")

    # Reply velocity: outbound within 1h of latest inbound.
    li = _parse_iso(signals["latest_inbound"])
    lo = _parse_iso(signals["latest_outbound"])
    if li and lo and lo >= li and (lo - li) <= timedelta(hours=1):
        event_score += 15
        reasons.append("reply_within_1h (+15)")

    # PCS listing-view intent (capped at +30).
    if signals["pcs_7d"] > 0:
        pcs_boost = min(signals["pcs_7d"] * 15, 30)
        event_score += pcs_boost
        reasons.append(f"pcs_views_7d={signals['pcs_7d']} (+{pcs_boost})")

    if signals["saved_search_recent"]:
        event_score += 10
        reasons.append("saved_search_recent (+10)")

    if latest_inbound_text and _READY_KEYWORDS.search(latest_inbound_text):
        event_score += 15
        reasons.append("ready_keyword (+15)")

    raw = crm_floor + event_score
    # Floor: never go below the CRM-native score. Cap: 100.
    final = max(crm_floor, min(raw, 100))

    if final >= _HOT_THRESHOLD:
        label = "hot"
    elif final >= _WARM_THRESHOLD:
        label = "warm"
    elif final >= _WATCH_THRESHOLD:
        label = "watch"
    else:
        label = "normal"

    if crm_floor:
        reasons.insert(0, f"crm_floor={crm_floor}")
    if not reasons:
        reasons.append("no_signal")

    return final, label, reasons


def _compute_flags(
    *,
    contact_type: str,
    contact_stage: str,
    signals: dict[str, Any],
    pcs_buyer_present: bool,
    now: datetime,
) -> dict[str, Any]:
    """Decide buyer_search_active, listing_active, needs_follow_up flags."""
    li = _parse_iso(signals["latest_inbound"])
    lo = _parse_iso(signals["latest_outbound"])
    recent_inbound_48h = bool(signals["recent_inbound_48h"])

    # needs_follow_up: had an inbound within 48h AND haven't replied since.
    needs_follow_up = 0
    next_follow_up_at: str | None = None
    if recent_inbound_48h and li and (lo is None or lo < li):
        needs_follow_up = 1
        next_follow_up_at = (li + timedelta(hours=24)).isoformat()

    # buyer_search_active: any signal that this contact is shopping for property.
    buyer_search_active = 0
    if contact_type == "buyer":
        buyer_search_active = 1
    elif pcs_buyer_present:
        buyer_search_active = 1
    elif signals["pcs_30d"] > 0:
        buyer_search_active = 1

    # listing_active: typed listing and not closed. listing_active is also
    # forced to 1 when promote_profile_to_admin_deal lands them on the
    # listing kanban; we won't clobber that here for closed contacts.
    listing_active = 1 if (contact_type == "listing" and contact_stage != "closed") else 0

    return {
        "needs_follow_up": needs_follow_up,
        "next_follow_up_at": next_follow_up_at,
        "buyer_search_active": buyer_search_active,
        "listing_active": listing_active,
    }


def _compute_ai_pipeline_status(
    *,
    signals: dict[str, Any],
    now: datetime,
) -> str | None:
    """Return the AI-recommended pipeline_status, or ``None`` if the contact
    doesn't match any auto-status rule.

    Rules (operator marks always win — caller enforces precedence):

    * ``new_lead`` — inbound in the last 24h AND no outbound has ever been
      sent. Cleared once we reply (outbound_total > 0).
    * ``ghosting`` — 3+ outbound lifetime AND no inbound in 30d.
    * ``dead``     — 5+ outbound lifetime AND no inbound in 60d.
    """
    inbound_24h = int(signals.get("inbound_24h") or 0)
    inbound_total = int(signals.get("inbound_total") or 0)
    outbound_total = int(signals.get("outbound_total") or 0)
    latest_inbound = _parse_iso(signals.get("latest_inbound"))

    # Dead wins over ghosting; check it first.
    if outbound_total >= 5:
        if latest_inbound is None or latest_inbound < (now - timedelta(days=60)):
            return "dead"
    if outbound_total >= 3:
        if latest_inbound is None or latest_inbound < (now - timedelta(days=30)):
            return "ghosting"
    if inbound_24h >= 1 and outbound_total == 0 and inbound_total == inbound_24h:
        return "new_lead"
    return None


# AI may only set/clear these statuses. closed_seller/closed_buyer are
# operator-only (they trigger /admin promotion).
_AI_PIPELINE_STATUSES: frozenset[str] = frozenset({"new_lead", "ghosting", "dead"})


def _compose_status_change_note(
    *,
    previous: str | None,
    new: str | None,
    signals: dict[str, Any],
) -> str:
    """Build the body for the note that goes alongside an AI status
    change. Lands locally and, once the push worker fires, on the Lofty
    note feed (with an ``[AI/review_contact]`` prefix).

    The body explains the WHY: which rule fired and what counts triggered
    it. Without this the operator just sees "ghosting" appear on a lead
    they remember from last week and has to dig through the timeline to
    figure out who's right."""
    inbound_24h = int(signals.get("inbound_24h") or 0)
    inbound_total = int(signals.get("inbound_total") or 0)
    outbound_total = int(signals.get("outbound_total") or 0)
    latest_inbound = signals.get("latest_inbound") or "never"
    prev_label = previous or "none"
    new_label = new or "none"

    header = f"AI status: {prev_label} → {new_label}."

    if new == "dead":
        return (
            f"{header} {outbound_total} outbounds, last inbound: {latest_inbound}. "
            f"No reply in 60+ days. Autopilot will skip until operator overrides."
        )
    if new == "ghosting":
        return (
            f"{header} {outbound_total} outbounds, last inbound: {latest_inbound}. "
            f"No reply in 30+ days. Worth a manual touch before retiring."
        )
    if new == "new_lead":
        return (
            f"{header} First inbound in last 24h, no outbound history yet. "
            f"Top of queue for draft + reply."
        )
    # Clearing (new is None) — the contact came back to life or rules no
    # longer match. Still worth a single line so the timeline shows it.
    if new is None:
        return (
            f"{header} Conditions no longer met "
            f"(outbound={outbound_total}, inbound24h={inbound_24h}, "
            f"inbound_total={inbound_total}). Re-eligible for outreach."
        )
    return header


def score_contact(
    conn: sqlite3.Connection,
    contact_id: str,
    *,
    actor: str = "review_contact",
    run_id: str | None = None,
    write: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score a single contact. Returns the computed flags and (when write=True)
    persists them via ``update_flags``.

    Returns ``None``-ish payload only for closed contacts (they're skipped).
    Set ``write=False`` for dry-run.
    """
    contact = conn.execute(
        "SELECT id, type, stage, heat_label, heat_score, "
        "needs_follow_up, next_follow_up_at, buyer_search_active, listing_active, "
        "pipeline_status, pipeline_status_set_by "
        "FROM contacts WHERE id=?",
        (contact_id,),
    ).fetchone()
    if contact is None:
        raise LookupError(f"contact {contact_id!r} not found")

    if contact["stage"] == "closed":
        return {
            "contact_id": contact_id,
            "skipped": "closed",
            "wrote": False,
        }

    now_dt = now or datetime.now(timezone.utc)
    signals = _event_signal_payload(conn, contact_id, now=now_dt)
    crm_floor = _crm_floor_for_contact(conn, contact_id)
    pcs_buyer_present = (
        conn.execute(
            "SELECT 1 FROM pcs_buyers WHERE contact_id=? LIMIT 1", (contact_id,)
        ).fetchone()
        is not None
    )
    latest_text = _latest_inbound_text(conn, contact_id)

    score, label, reasons = _compute_score(
        crm_floor=crm_floor,
        signals=signals,
        latest_inbound_text=latest_text,
    )
    flags = _compute_flags(
        contact_type=contact["type"],
        contact_stage=contact["stage"],
        signals=signals,
        pcs_buyer_present=pcs_buyer_present,
        now=now_dt,
    )
    reason_str = "; ".join(reasons)[:240]

    payload = {
        "contact_id": contact_id,
        "heat_label": label,
        "heat_score": score,
        "heat_reason": reason_str,
        "needs_follow_up": flags["needs_follow_up"],
        "next_follow_up_at": flags["next_follow_up_at"],
        "buyer_search_active": flags["buyer_search_active"],
        "listing_active": flags["listing_active"],
        "crm_floor": crm_floor,
        "signals": signals,
        "wrote": False,
    }

    if not write:
        return payload

    update_flags(
        conn,
        contact_id,
        actor=actor,
        record_event=False,
        heatLabel=label,
        heatScore=score,
        heatReason=reason_str,
        needsFollowUp=flags["needs_follow_up"],
        nextFollowUpAt=flags["next_follow_up_at"],
        buyerSearchActive=flags["buyer_search_active"],
        listingActive=flags["listing_active"],
        aiLastReviewedAt=now_dt.isoformat(),
        aiReviewRunId=run_id,
    )

    # AI pipeline_status — only touch AI-owned slots so operator marks win.
    # Skip closed contacts entirely (return earlier), and never touch
    # closed_seller/closed_buyer rows (those are operator-set).
    current_status = contact["pipeline_status"]
    current_set_by = contact["pipeline_status_set_by"]
    if current_set_by != "operator" and current_status not in {"closed_seller", "closed_buyer"}:
        desired_status = _compute_ai_pipeline_status(signals=signals, now=now_dt)
        if desired_status != current_status:
            # Write directly (no set_pipeline_status to avoid the close_to_admin
            # branch and keep the AI sweep stateless re: identity matching).
            conn.execute(
                "UPDATE contacts SET pipeline_status=?, pipeline_status_set_by=?, "
                "pipeline_status_set_at=?, updated_at=? WHERE id=?",
                (
                    desired_status,
                    "ai" if desired_status else None,
                    now_dt.isoformat() if desired_status else None,
                    now_dt.isoformat(),
                    contact_id,
                ),
            )
            # Annotate the contact so the operator (and Lofty) can see WHY
            # the AI changed the label. Daily cap on the helper suppresses
            # repeat notes if the cron flips status more than once per day.
            # NULL → NULL transitions never reach here (caught by the !=
            # check above), so we always have something worth saying.
            try:
                note_body = _compose_status_change_note(
                    previous=current_status,
                    new=desired_status,
                    signals=signals,
                )
                if note_body:
                    write_note(
                        conn,
                        contact_id=contact_id,
                        body=note_body,
                        author_kind="ai",
                        author_name=actor or "review_contact",
                        push_to_lofty=True,
                    )
            except Exception:
                # Note writes never block scoring — log via payload and move on.
                payload["note_write_failed"] = True
        payload["pipeline_status"] = desired_status
        payload["pipeline_status_set_by"] = "ai" if desired_status else None

    payload["wrote"] = True
    return payload


def review_all_contacts(
    conn: sqlite3.Connection,
    *,
    actor: str = "review_contact",
    limit: int | None = None,
    write: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score every non-closed contact. Returns counters + run_id.

    Idempotent — calling twice in quick succession with the same data
    yields the same flags. ``update_flags`` writes a ``lifecycle_change``
    event only when the flag values actually change.
    """
    run_id = new_id()
    rows = conn.execute(
        "SELECT id FROM contacts WHERE stage != 'closed' ORDER BY updated_at DESC"
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()

    counters = {
        "scanned": 0,
        "skipped": 0,
        "wrote": 0,
        "by_label": {"hot": 0, "warm": 0, "watch": 0, "normal": 0},
        "needs_follow_up": 0,
        "buyer_search_active": 0,
        "listing_active": 0,
    }

    for row in rows:
        counters["scanned"] += 1
        try:
            result = score_contact(
                conn,
                row["id"],
                actor=actor,
                run_id=run_id,
                write=write,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001
            counters.setdefault("errors", []).append(
                {"contact_id": row["id"], "error": str(exc)}
            )
            continue
        if result.get("skipped"):
            counters["skipped"] += 1
            continue
        if result.get("wrote"):
            counters["wrote"] += 1
        counters["by_label"][result["heat_label"]] += 1
        counters["needs_follow_up"] += int(bool(result["needs_follow_up"]))
        counters["buyer_search_active"] += int(bool(result["buyer_search_active"]))
        counters["listing_active"] += int(bool(result["listing_active"]))

    counters["run_id"] = run_id
    counters["completed_at"] = (now or datetime.now(timezone.utc)).isoformat()
    counters["scoring_version"] = SCORING_VERSION
    return counters
