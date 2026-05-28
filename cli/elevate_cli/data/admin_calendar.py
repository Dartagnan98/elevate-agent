"""Admin board calendar-event helpers.

External calendar rows are stored in ``admin_calendar_events``. Deal milestone
dates stay on ``deals`` and are projected into the same API shape at read time.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from elevate_cli.data._util import new_id, now_iso


_DAY_SECONDS = 86_400
_MATCH_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DATE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("subject_removal_date", "Subject removal", "subject_removal"),
    ("deposit_due_date", "Deposit due", "deposit_due"),
    ("completion_date", "Completion", "completion"),
    ("possession_date", "Possession", "possession"),
    ("offer_date", "Offer", "offer"),
    ("listing_date", "Listing live", "listing"),
    ("appointment_date", "Appointment", "appointment"),
    ("agreement_signed_date", "Agreement signed", "agreement_signed"),
    ("contract_date", "Contract", "contract"),
    ("appraisal_date", "Appraisal", "appraisal"),
    ("home_inspection_date", "Home inspection", "inspection"),
    ("escrow_date", "Escrow", "escrow"),
    ("expiration_date", "Expiration", "expiration"),
    ("expected_close_date", "Expected close", "expected_close"),
)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            return datetime.fromisoformat(f"{raw}T12:00:00")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compare_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_local_tz())
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _json(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, separators=(",", ":"), default=str)
    except TypeError:
        return json.dumps(str(value))


def _tokens(value: str | None) -> list[str]:
    return _MATCH_TOKEN_RE.findall((value or "").lower())


def _norm(value: str | None) -> str:
    return " ".join(_tokens(value))


def _short_location(location: str | None, fallback: str) -> str:
    text = (location or "").strip() or fallback
    return text[:80]


def _score_deal_match(row: Mapping[str, Any], haystack: str) -> int:
    address = _norm(row.get("listing_address"))
    if not address:
        return 0
    hay = _norm(haystack)
    if not hay:
        return 0
    if address in hay or hay in address:
        return 100

    address_tokens = _tokens(address)
    hay_tokens = set(_tokens(hay))
    if not address_tokens or not hay_tokens:
        return 0

    score = 0
    first = address_tokens[0]
    if first.isdigit() and first in hay_tokens:
        score += 35
    overlap = len(set(address_tokens).intersection(hay_tokens))
    score += int((overlap / max(len(set(address_tokens)), 1)) * 70)
    return score


def match_deal_by_address(conn: Any, *, title: str | None = None, location: str | None = None) -> str | None:
    """Best-effort link from a calendar title/location to an active deal."""
    haystack = " ".join(part for part in (title or "", location or "") if part).strip()
    if not haystack:
        return None
    rows = conn.execute(
        """
        SELECT id, title, listing_address
        FROM deals
        WHERE status = 'active'
          AND listing_address IS NOT NULL
          AND TRIM(listing_address) <> ''
        LIMIT 500
        """
    ).fetchall()
    best_id: str | None = None
    best_score = 0
    for row in rows:
        score = _score_deal_match(row, haystack)
        if score > best_score:
            best_id = row["id"]
            best_score = score
    return best_id if best_score >= 55 else None


def classify_calendar_kind(title: str | None) -> str:
    text = (title or "").lower()
    checks = (
        ("open house", "open_house"),
        ("showing", "showing"),
        ("tour", "showing"),
        ("inspection", "inspection"),
        ("subject", "subject_removal"),
        ("condition", "subject_removal"),
        ("deposit", "deposit_due"),
        ("completion", "completion"),
        ("closing", "completion"),
        ("possession", "possession"),
        ("appointment", "appointment"),
        ("sign", "signing"),
        ("photos", "marketing"),
        ("photo", "marketing"),
    )
    for needle, kind in checks:
        if needle in text:
            return kind
    return "calendar"


def upsert_calendar_event(
    conn: Any,
    *,
    source: str,
    source_event_id: str,
    title: str,
    start_at: datetime | str,
    end_at: datetime | str | None = None,
    location: str | None = None,
    kind: str | None = None,
    deal_id: str | None = None,
    raw: Any = None,
    synced_at: str | None = None,
) -> dict[str, Any]:
    start = _parse_dt(start_at)
    if start is None:
        raise ValueError("start_at is required")
    end = _parse_dt(end_at)
    event_id = new_id()
    synced = synced_at or now_iso()
    conn.execute(
        """
        INSERT INTO admin_calendar_events(
            id, source, source_event_id, deal_id, title, location,
            start_at, end_at, kind, synced_at, raw_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (source, source_event_id) DO UPDATE SET
            deal_id = EXCLUDED.deal_id,
            title = EXCLUDED.title,
            location = EXCLUDED.location,
            start_at = EXCLUDED.start_at,
            end_at = EXCLUDED.end_at,
            kind = EXCLUDED.kind,
            synced_at = EXCLUDED.synced_at,
            raw_json = EXCLUDED.raw_json
        """,
        (
            event_id,
            source,
            source_event_id,
            deal_id,
            title.strip() or "Calendar event",
            location,
            start,
            end,
            kind or classify_calendar_kind(title),
            synced,
            _json(raw),
        ),
    )
    row = conn.execute(
        "SELECT * FROM admin_calendar_events WHERE source=? AND source_event_id=?",
        (source, source_event_id),
    ).fetchone()
    return _row_to_event(row)


def list_calendar_events(conn: Any, *, days: int = 21) -> list[dict[str, Any]]:
    safe_days = max(1, min(int(days or 21), 90))
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=safe_days)
    rows = conn.execute(
        """
        SELECT *
        FROM admin_calendar_events
        WHERE start_at >= ?
          AND start_at <= ?
        ORDER BY start_at ASC
        LIMIT 250
        """,
        (now, horizon),
    ).fetchall()
    return [_row_to_event(row) for row in rows]


def list_deal_date_events(conn: Any, *, days: int = 21) -> list[dict[str, Any]]:
    safe_days = max(1, min(int(days or 21), 90))
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=safe_days)
    rows = conn.execute(
        """
        SELECT
            id, title, listing_address,
            subject_removal_date, deposit_due_date, completion_date,
            possession_date, offer_date, listing_date, appointment_date,
            agreement_signed_date, contract_date, appraisal_date,
            home_inspection_date, escrow_date, expiration_date,
            expected_close_date
        FROM deals
        WHERE status = 'active'
        LIMIT 500
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        fallback = row["title"] or "Untitled deal"
        address = _short_location(row["listing_address"], fallback)
        for field, label, kind in _DATE_FIELDS:
            raw = row.get(field)
            when = _parse_dt(raw)
            if when is None:
                continue
            cmp_when = _compare_dt(when)
            if cmp_when < now or cmp_when > horizon:
                continue
            out.append(
                {
                    "id": f"deal-date:{row['id']}:{field}",
                    "source": "deal_date",
                    "sourceEventId": f"{row['id']}:{field}",
                    "dealId": row["id"],
                    "title": label,
                    "location": row["listing_address"],
                    "address": address,
                    "startAt": _iso(when),
                    "endAt": None,
                    "kind": kind,
                    "syncedAt": None,
                }
            )
    out.sort(key=lambda item: _sort_key(item["startAt"]))
    return out


def list_upcoming_admin_events(conn: Any, *, days: int = 21) -> dict[str, Any]:
    safe_days = max(1, min(int(days or 21), 90))
    items = [*list_calendar_events(conn, days=safe_days), *list_deal_date_events(conn, days=safe_days)]
    items.sort(key=lambda item: _sort_key(item.get("startAt")))
    items = items[:50]
    return {
        "items": items,
        "count": len(items),
        "days": safe_days,
        "generatedAt": now_iso(),
    }


def prune_old_calendar_events(conn: Any, *, keep_days: int = 120) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, keep_days))
    cur = conn.execute(
        "DELETE FROM admin_calendar_events WHERE source='gcal' AND start_at < ?",
        (cutoff,),
    )
    return int(getattr(cur, "rowcount", 0) or 0)


def _row_to_event(row: Mapping[str, Any]) -> dict[str, Any]:
    start = _parse_dt(row.get("start_at"))
    end = _parse_dt(row.get("end_at"))
    title = str(row.get("title") or "Calendar event")
    location = row.get("location")
    return {
        "id": row["id"],
        "source": row["source"],
        "sourceEventId": row["source_event_id"],
        "dealId": row.get("deal_id"),
        "title": title,
        "location": location,
        "address": _short_location(location, title),
        "startAt": _iso(start),
        "endAt": _iso(end),
        "kind": row.get("kind") or "calendar",
        "syncedAt": _iso(_parse_dt(row.get("synced_at"))),
    }


def _sort_key(value: Any) -> float:
    dt = _parse_dt(value)
    if dt is None:
        return float("inf")
    return _compare_dt(dt).timestamp()


def event_rows_from_payload(payload: Any) -> Iterable[Mapping[str, Any]]:
    """Extract event-like dicts from common Composio/Google response shapes."""
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                yield item
        return
    if not isinstance(payload, Mapping):
        return
    for key in ("items", "events", "value", "data", "results"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, Mapping):
                    yield item
            return
        if isinstance(candidate, Mapping):
            yielded = list(event_rows_from_payload(candidate))
            if yielded:
                for item in yielded:
                    yield item
                return
