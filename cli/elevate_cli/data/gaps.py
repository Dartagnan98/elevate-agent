"""Sprint 5.2 — weekly template-gap analysis.

Returns a structured list of "gaps" the realtor (or AI worker) should
address. Two kinds:

* **low_reply_rate** — a lane/channel where every live template that
  has cleared the min-sample window (uses ≥ 50 OR age > 30 days, the
  same threshold the leaderboard uses) is replying under 5%. Signal:
  the templates you wrote aren't landing — write better ones.
* **no_template_fit** — inbound threads in the last N days that never
  got a same-channel templated outbound reply. Signal: there are
  conversations the picker isn't matching, either because no eligible
  template existed or the realtor sent freehand instead.

The function is read-only — it produces a report. The AI drafting hook
(plan §5.2) is upstream: a worker reads the gap list, asks Claude/Codex
to write a candidate body for each, then calls
:func:`elevate_cli.data.templates.propose_template` with
``origin='ai_pattern'`` (low reply rate) or ``'ai_failure_analysis'``
(no fit). Until Codex auth is back the gap list still ships and the
realtor can write candidates by hand.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.data import templates as _templates


_LOW_REPLY_RATE_THRESHOLD = 0.05
_NO_FIT_RESPONSE_WINDOW_HOURS = 24
_DEFAULT_LOOKBACK_DAYS = 30
# Cap how many sample inbound ids we attach to each no_template_fit
# gap. The realtor uses these to drill in; the full set lives in the
# events table.
_MAX_EXAMPLES_PER_GAP = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "+00:00"
    )


def _low_reply_rate_gaps(
    conn: sqlite3.Connection, *, now: datetime
) -> list[dict[str, Any]]:
    """For each (lane, channel) combination, flag if the best template
    that has cleared the min-sample window is replying < 5%."""
    rows = _templates.list_templates(
        conn, status="live", active_only=True
    )
    cutoff = now - timedelta(days=_templates._LEADERBOARD_MIN_AGE_DAYS)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for tpl in rows:
        key = (tpl["lane"], tpl["channel"])
        grouped.setdefault(key, []).append(tpl)

    out: list[dict[str, Any]] = []
    for (lane, channel), members in grouped.items():
        cleared = []
        for tpl in members:
            if int(tpl["uses"] or 0) >= _templates._LEADERBOARD_MIN_USES:
                cleared.append(tpl)
                continue
            try:
                created = datetime.fromisoformat(
                    tpl["createdAt"].replace("Z", "+00:00")
                )
                if created < cutoff:
                    cleared.append(tpl)
            except (AttributeError, ValueError):
                continue

        if not cleared:
            continue
        max_rate = max(float(tpl["replyRate"] or 0.0) for tpl in cleared)
        if max_rate >= _LOW_REPLY_RATE_THRESHOLD:
            continue
        out.append({
            "kind": "low_reply_rate",
            "lane": lane,
            "channel": channel,
            "templateIds": [tpl["id"] for tpl in cleared],
            "maxReplyRate": round(max_rate, 4),
            "templateCount": len(cleared),
            "suggestedOrigin": "ai_failure_analysis",
        })
    return out


def _no_template_fit_gaps(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    days_back: int,
) -> list[dict[str, Any]]:
    """Find inbound events that didn't receive a templated outbound
    reply within :data:`_NO_FIT_RESPONSE_WINDOW_HOURS` hours.

    Groups by (channel, source_id) so the realtor can see the bucket
    that's leaking — e.g. "23 SMS inbounds in last 30 days had no
    templated reply" → write more SMS templates.
    """
    cutoff = now - timedelta(days=days_back)
    response_window_hours = _NO_FIT_RESPONSE_WINDOW_HOURS

    sql = """
        SELECT inb.id          AS inbound_id,
               inb.channel     AS channel,
               inb.source_id   AS source_id,
               inb.conversation_id AS conversation_id,
               inb.ts          AS ts
        FROM events inb
        WHERE inb.kind = 'inbound'
          AND inb.ts >= ?
          AND NOT EXISTS (
              SELECT 1 FROM events outb
              WHERE outb.conversation_id = inb.conversation_id
                AND outb.kind = 'outbound'
                AND outb.template_id IS NOT NULL
                AND outb.ts > inb.ts
                AND outb.ts <= datetime(inb.ts, ?)
          )
        ORDER BY inb.ts DESC
    """
    inbound_offset = f"+{response_window_hours} hours"
    rows = conn.execute(sql, (_iso(cutoff), inbound_offset)).fetchall()

    grouped: dict[tuple[str | None, str | None], list[sqlite3.Row]] = {}
    for r in rows:
        grouped.setdefault((r["channel"], r["source_id"]), []).append(r)

    out: list[dict[str, Any]] = []
    for (channel, source_id), inbounds in grouped.items():
        out.append({
            "kind": "no_template_fit",
            "channel": channel,
            "sourceId": source_id,
            "inboundCount": len(inbounds),
            "exampleInboundIds": [
                r["inbound_id"] for r in inbounds[:_MAX_EXAMPLES_PER_GAP]
            ],
            "windowHours": response_window_hours,
            "lookbackDays": days_back,
            "suggestedOrigin": "ai_pattern",
        })
    out.sort(key=lambda g: g["inboundCount"], reverse=True)
    return out


def analyze_template_gaps(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    days_back: int = _DEFAULT_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Produce a gap report for the AI template-generation worker.

    ``now`` and ``days_back`` are exposed for testability — the weekly
    cron passes nothing.
    """
    now = now or _utc_now()
    return _low_reply_rate_gaps(conn, now=now) + _no_template_fit_gaps(
        conn, now=now, days_back=days_back
    )


__all__ = ["analyze_template_gaps"]
