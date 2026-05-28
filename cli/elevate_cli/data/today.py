"""Today dashboard read model.

The Today page needs counters that are about actual activity windows, not just
the latest visible thread row.  This module computes those counters from the
operational event log so the UI can render one page-specific snapshot.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any


DAY = timedelta(days=1)
WEEK_WINDOW = 7


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _day_start(dt: datetime) -> datetime:
    return dt.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def _hour_label(hour: int) -> str:
    if hour == 0:
        return "12a"
    if hour == 12:
        return "12p"
    if hour < 12:
        return f"{hour}a"
    return f"{hour - 12}p"


def _empty_hour_buckets() -> list[dict[str, Any]]:
    return [
        {
            "hour": hour,
            "label": _hour_label(hour),
            "leadsIn": 0,
            "repliesOut": 0,
        }
        for hour in range(24)
    ]


def _empty_day_buckets(today_start: datetime) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    for idx in range(WEEK_WINDOW - 1, -1, -1):
        day = today_start - idx * DAY
        buckets.append(
            {
                "iso": day.date().isoformat(),
                "label": day.strftime("%a"),
                "leadsIn": 0,
                "repliesOut": 0,
                "dealsAdvanced": 0,
            }
        )
    return buckets


def _fmt_delta(today: int, yesterday: int) -> dict[str, Any]:
    if today == 0 and yesterday == 0:
        return {"delta": None, "label": None}
    if yesterday == 0:
        return {"delta": today, "label": f"+{today}"}
    diff = today - yesterday
    if diff == 0:
        return {"delta": 0, "label": "flat"}
    return {"delta": diff, "label": f"+{diff}" if diff > 0 else str(diff)}


def _fmt_minutes_delta(today: int | None, yesterday: int | None) -> dict[str, Any]:
    if today is None or yesterday is None:
        return {"delta": None, "label": None}
    diff = today - yesterday
    if diff == 0:
        return {"delta": 0, "label": "flat"}
    return {"delta": diff, "label": f"+{diff}m" if diff > 0 else f"{diff}m"}


def _tone_for_waiting(count: int) -> str:
    if count >= 5:
        return "danger"
    if count > 0:
        return "warn"
    return "good"


def _tone_for_response(minutes: int | None) -> str:
    if minutes is None:
        return "good"
    if minutes >= 30:
        return "danger"
    if minutes >= 10:
        return "warn"
    return "good"


def _waiting_threads_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM conversations c
        LEFT JOIN contacts ct ON ct.id = c.contact_id
        WHERE c.status = 'open'
          AND c.last_inbound_at IS NOT NULL
          AND (c.last_outbound_at IS NULL OR c.last_inbound_at > c.last_outbound_at)
          AND (
            ct.id IS NULL
            OR (
              ct.stage != 'closed'
              AND COALESCE(ct.pipeline_status, '') NOT IN (
                'dead', 'closed_seller', 'closed_buyer'
              )
            )
          )
        """
    ).fetchone()
    return int(row["c"] if row and row["c"] is not None else 0)


def _event_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          e.kind,
          e.ts,
          e.conversation_id
        FROM events e
        WHERE e.kind IN ('inbound', 'outbound')
        ORDER BY e.ts DESC
        LIMIT 20000
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _completed_run_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT status, completed_at
        FROM admin_action_runs
        WHERE completed_at IS NOT NULL
        ORDER BY completed_at DESC
        LIMIT 5000
        """
    ).fetchall()
    return [dict(row) for row in rows]


def build_today_activity(
    conn: sqlite3.Connection,
    *,
    pending_drafts_count: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the activity portion of the Today page from canonical DB rows."""
    local_now = (now or datetime.now(timezone.utc)).astimezone()
    today_start = _day_start(local_now)
    tomorrow_start = today_start + DAY
    yesterday_start = today_start - DAY
    week_start = today_start - (WEEK_WINDOW - 1) * DAY

    hour_buckets = _empty_hour_buckets()
    day_buckets = _empty_day_buckets(today_start)
    day_by_iso = {bucket["iso"]: bucket for bucket in day_buckets}

    today_counts = {"inbound": 0, "outbound": 0}
    yesterday_counts = {"inbound": 0, "outbound": 0}
    response_samples_today: list[int] = []
    response_samples_yesterday: list[int] = []
    latest_activity: datetime | None = None
    parsed_events: list[tuple[datetime, str, str | None]] = []

    for row in _event_rows(conn):
        ts = _parse_ts(row.get("ts"))
        kind = str(row.get("kind") or "")
        if ts is None or kind not in {"inbound", "outbound"}:
            continue
        if ts < week_start or ts >= tomorrow_start:
            continue
        latest_activity = max(latest_activity, ts) if latest_activity else ts
        conversation_id = row.get("conversation_id")
        parsed_events.append((ts, kind, str(conversation_id) if conversation_id else None))

        day_iso = ts.date().isoformat()
        day_bucket = day_by_iso.get(day_iso)
        if day_bucket:
            if kind == "inbound":
                day_bucket["leadsIn"] += 1
            else:
                day_bucket["repliesOut"] += 1

        if today_start <= ts < tomorrow_start:
            if kind == "inbound":
                today_counts["inbound"] += 1
                hour_buckets[ts.hour]["leadsIn"] += 1
            else:
                today_counts["outbound"] += 1
                hour_buckets[ts.hour]["repliesOut"] += 1
        elif yesterday_start <= ts < today_start:
            if kind == "inbound":
                yesterday_counts["inbound"] += 1
            else:
                yesterday_counts["outbound"] += 1

    parsed_events.sort(key=lambda item: item[0])
    last_inbound_by_conversation: dict[str, datetime] = {}
    for ts, kind, conversation_id in parsed_events:
        if not conversation_id:
            continue
        if kind == "inbound":
            last_inbound_by_conversation[conversation_id] = ts
            continue
        inbound_at = last_inbound_by_conversation.get(conversation_id)
        if inbound_at is None or inbound_at > ts:
            continue
        minutes = max(1, round((ts - inbound_at).total_seconds() / 60))
        if today_start <= ts < tomorrow_start:
            response_samples_today.append(minutes)
        elif yesterday_start <= ts < today_start:
            response_samples_yesterday.append(minutes)

    for row in _completed_run_rows(conn):
        if str(row.get("status") or "") not in {"succeeded", "completed", "success", "approved"}:
            continue
        completed = _parse_ts(row.get("completed_at"))
        if completed is None or completed < week_start or completed >= tomorrow_start:
            continue
        bucket = day_by_iso.get(completed.date().isoformat())
        if bucket:
            bucket["dealsAdvanced"] += 1

    waiting_threads = _waiting_threads_count(conn)
    median_response_today = (
        int(round(median(response_samples_today))) if response_samples_today else None
    )
    median_response_yesterday = (
        int(round(median(response_samples_yesterday))) if response_samples_yesterday else None
    )

    in_delta = _fmt_delta(today_counts["inbound"], yesterday_counts["inbound"])
    out_delta = _fmt_delta(today_counts["outbound"], yesterday_counts["outbound"])
    response_delta = _fmt_minutes_delta(median_response_today, median_response_yesterday)
    day_leads = [int(bucket["leadsIn"]) for bucket in day_buckets]
    day_replies = [int(bucket["repliesOut"]) for bucket in day_buckets]
    today_hourly = [
        int(bucket["leadsIn"]) + int(bucket["repliesOut"])
        for bucket in hour_buckets
    ]
    drafts_spark = [pending_drafts_count for _ in range(WEEK_WINDOW)]

    pulse = [
        {
            "label": "Leads in today",
            "value": str(today_counts["inbound"]),
            "rawValue": today_counts["inbound"],
            "delta": in_delta["delta"],
            "deltaLabel": in_delta["label"],
            "spark": day_leads,
            "tone": "neutral",
        },
        {
            "label": "Replies out today",
            "value": str(today_counts["outbound"]),
            "rawValue": today_counts["outbound"],
            "delta": out_delta["delta"],
            "deltaLabel": out_delta["label"],
            "spark": day_replies,
            "tone": "warn" if today_counts["outbound"] == 0 and today_counts["inbound"] > 0 else "neutral",
        },
        {
            "label": "Drafts waiting",
            "value": str(pending_drafts_count),
            "rawValue": pending_drafts_count,
            "delta": None,
            "deltaLabel": None,
            "spark": drafts_spark,
            "tone": "warn" if pending_drafts_count >= 5 else ("neutral" if pending_drafts_count > 0 else "good"),
        },
        {
            "label": "Threads waiting on you",
            "value": str(waiting_threads),
            "rawValue": waiting_threads,
            "delta": None,
            "deltaLabel": None,
            "spark": day_leads,
            "tone": _tone_for_waiting(waiting_threads),
        },
        {
            "label": "Median response",
            "value": f"{median_response_today}m" if median_response_today is not None else "-",
            "rawValue": median_response_today or 0,
            "delta": response_delta["delta"],
            "deltaLabel": response_delta["label"],
            "spark": today_hourly,
            "tone": _tone_for_response(median_response_today),
        },
    ]

    return {
        "pulse": pulse,
        "hourBuckets": hour_buckets,
        "dayBuckets": day_buckets,
        "activityUpdatedAt": latest_activity.isoformat() if latest_activity else None,
        "todayWindow": {
            "start": today_start.isoformat(),
            "end": tomorrow_start.isoformat(),
            "timezone": local_now.tzname(),
        },
    }
