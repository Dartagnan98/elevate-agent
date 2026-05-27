"""xposure-pcs buyer-brief enrichment.

Reads ``pcs_buyers`` rows and the ``events`` table for every contact
with an xposure-pcs identity / source_key, synthesizes a one-line
human-readable buyer brief, and writes it back to
``contacts.enrichment_brief`` along with the denormalized activity
fields (``activity_tier``, ``last_search_at``, ``search_count_90d``).

The connector card on the Source Connectors page maps to this module
via :func:`run_enrichment`. The downstream every-other-day cron also
calls it after the scraper finishes, so the dashboard never lags.

What goes in the brief:
- Price band   ($800k-$1.2M, derived from searches_json when present)
- Bed/bath     (3+ bed, 2+ bath)
- Areas        (Aberdeen + Westsyde)
- Recency      ("last search 6d ago" / "no search in 90d")
- 90-day volume ("14 searches in 90d")

The synthesizer is intentionally cheap (no LLM). Pure string assembly
over the raw search JSON. If a search row carries no structured price/
bed/area fields (the early Xposure scraper just dumped search NAMES),
we fall back to listing the search labels verbatim.

Activity tier rules (simple, tunable):
- ``active``         search in last 14d AND ≥3 searches in 90d
- ``warm``           search in last 30d
- ``dormant``        search 30-90d ago
- ``never-touched``  no searches in 90d (or no pcs_buyers row at all)

Idempotent: keyed on ``contact_id``. Re-running refreshes the brief in
place. Never touches display_name, notes, or tags.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

from elevate_cli.data import connect

_log = logging.getLogger(__name__)

SOURCE_ID = "buyer-brief"
_LOOKBACK_DAYS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # PG returns timestamptz as datetime when using psycopg, str
        # when serialized through the sqlite shim. Handle both.
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ─── Brief synthesis ──────────────────────────────────────────────────


def _format_price(value: Any) -> str | None:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    if n >= 1_000_000:
        m = n / 1_000_000
        return f"${m:.2f}M" if m % 1 else f"${int(m)}M"
    if n >= 1_000:
        return f"${n // 1_000}k"
    return f"${n}"


def _summarize_searches(searches: list[Any]) -> dict[str, Any]:
    """Walk the searches array. Each entry may be:
    - a bare label string ("Kamloops 3-bed under 800k")
    - a dict with structured fields (price_min, price_max, beds, area)

    We try structured first; fall back to label parsing only if a
    field is missing. Empty dict if no useful signal.
    """
    if not searches:
        return {}

    prices_min: list[int] = []
    prices_max: list[int] = []
    beds: list[int] = []
    areas: list[str] = []
    labels: list[str] = []

    for s in searches:
        if isinstance(s, dict):
            for key in ("price_min", "priceMin", "minPrice"):
                if s.get(key) is not None:
                    try:
                        prices_min.append(int(float(s[key])))
                    except (TypeError, ValueError):
                        pass
                    break
            for key in ("price_max", "priceMax", "maxPrice"):
                if s.get(key) is not None:
                    try:
                        prices_max.append(int(float(s[key])))
                    except (TypeError, ValueError):
                        pass
                    break
            for key in ("beds", "min_beds", "minBeds"):
                if s.get(key) is not None:
                    try:
                        beds.append(int(float(s[key])))
                    except (TypeError, ValueError):
                        pass
                    break
            label = str(s.get("label") or s.get("name") or "").strip()
            if label and label != "no title":
                labels.append(label)
            area = str(s.get("area") or s.get("neighborhood") or "").strip()
            if area:
                areas.append(area)
        elif isinstance(s, str):
            label = s.strip()
            if label and label != "no title":
                labels.append(label)

    out: dict[str, Any] = {}
    if prices_min and prices_max:
        out["price_range"] = f"{_format_price(min(prices_min))}-{_format_price(max(prices_max))}"
    elif prices_max:
        out["price_range"] = f"up to {_format_price(max(prices_max))}"
    elif prices_min:
        out["price_range"] = f"from {_format_price(min(prices_min))}"

    if beds:
        out["beds"] = f"{min(beds)}+ bed"

    if areas:
        # Dedup, preserve order.
        seen: dict[str, bool] = {}
        for a in areas:
            seen[a] = True
        out["areas"] = " + ".join(list(seen.keys())[:3])

    if labels and "price_range" not in out and "beds" not in out and "areas" not in out:
        # Fully-unstructured snapshot — fall back to listing labels.
        seen2: dict[str, bool] = {}
        for label in labels:
            seen2[label] = True
        out["labels"] = " / ".join(list(seen2.keys())[:3])

    return out


def _format_recency(last_search_at: datetime | None) -> str:
    if not last_search_at:
        return "no recorded search"
    delta = _now() - last_search_at
    days = delta.days
    if days <= 0:
        return "last search today"
    if days == 1:
        return "last search 1d ago"
    if days < 30:
        return f"last search {days}d ago"
    if days < 90:
        return f"last search {days // 7}w ago"
    return f"last search {days // 30}mo ago"


def _build_brief(
    *,
    searches: list[Any],
    last_search_at: datetime | None,
    search_count_90d: int,
    tier: str | None,
) -> str:
    summary = _summarize_searches(searches)
    parts: list[str] = []

    if summary.get("price_range"):
        parts.append(summary["price_range"])
    if summary.get("beds"):
        parts.append(summary["beds"])
    if summary.get("areas"):
        parts.append(summary["areas"])
    elif summary.get("labels"):
        parts.append(summary["labels"])

    if not parts:
        # No structured signal AND no labels. Lean on tier + recency
        # only so the brief still beats the generic "buyer interested".
        if tier:
            parts.append(f"MLS buyer ({tier.lower()})")
        else:
            parts.append("MLS buyer")

    parts.append(_format_recency(last_search_at))
    if search_count_90d:
        parts.append(f"{search_count_90d} searches in 90d")

    return ", ".join(parts)


def _tier_for(
    *, last_search_at: datetime | None, search_count_90d: int
) -> str:
    if not last_search_at:
        return "never-touched"
    days = (_now() - last_search_at).days
    if days <= 14 and search_count_90d >= 3:
        return "active"
    if days <= 30:
        return "warm"
    if days <= 90:
        return "dormant"
    return "never-touched"


# ─── Stats counters ────────────────────────────────────────────────────


class EnrichmentStats:
    """Mutable counters for the report. Shared across the walk."""

    def __init__(self) -> None:
        self.contacts_walked = 0
        self.briefs_written = 0
        self.briefs_unchanged = 0
        self.tier_active = 0
        self.tier_warm = 0
        self.tier_dormant = 0
        self.tier_never = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "contacts_walked": self.contacts_walked,
            "briefs_written": self.briefs_written,
            "briefs_unchanged": self.briefs_unchanged,
            "tier_active": self.tier_active,
            "tier_warm": self.tier_warm,
            "tier_dormant": self.tier_dormant,
            "tier_never_touched": self.tier_never,
            "errors": list(self.errors),
        }


def _bump_tier(stats: EnrichmentStats, tier: str) -> None:
    if tier == "active":
        stats.tier_active += 1
    elif tier == "warm":
        stats.tier_warm += 1
    elif tier == "dormant":
        stats.tier_dormant += 1
    else:
        stats.tier_never += 1


# ─── Entry point ──────────────────────────────────────────────────────


def run_enrichment(
    config: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Walk every pcs_buyers row, compute brief + tier, write to contacts.

    Connector-card-shaped return value so the Source Connectors page
    renders it the same way as the xposure-pcs scrape card.
    """
    stats = EnrichmentStats()
    cutoff = _now() - timedelta(days=_LOOKBACK_DAYS)

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT pb.contact_id,
                   pb.searches_json,
                   pb.tier,
                   pb.last_activity_at,
                   pb.last_scraped_at
            FROM pcs_buyers pb
            """
        ).fetchall()

        # Bulk-count xposure-pcs events per contact in one pass. ~1k
        # contacts × per-row COUNT(*) is wasteful and would mask any
        # transaction-abort failure mode behind 1k retries. One grouped
        # query keeps walk time flat.
        count_rows = conn.execute(
            """
            SELECT contact_id, COUNT(*) AS n
              FROM events
             WHERE source_id = 'xposure-pcs'
               AND ts >= ?
             GROUP BY contact_id
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        counts_90d_by_contact = {
            r["contact_id"]: int(r["n"]) for r in count_rows
        }

        for row in rows:
            stats.contacts_walked += 1
            contact_id = row["contact_id"]
            try:
                searches_raw = row["searches_json"] or "[]"
                searches = json.loads(searches_raw) if isinstance(searches_raw, str) else (searches_raw or [])
                last_search_at = (
                    _parse_ts(row["last_activity_at"])
                    or _parse_ts(row["last_scraped_at"])
                )

                count_90d = counts_90d_by_contact.get(contact_id, 0)

                brief = _build_brief(
                    searches=searches,
                    last_search_at=last_search_at,
                    search_count_90d=count_90d,
                    tier=row["tier"],
                )
                tier = _tier_for(
                    last_search_at=last_search_at,
                    search_count_90d=count_90d,
                )
                _bump_tier(stats, tier)

                # Idempotent update. Only write when something actually
                # changed — saves UPDATE traffic on contacts (which has
                # busy indexes) and keeps the audit trail thin.
                existing = conn.execute(
                    "SELECT enrichment_brief, activity_tier, last_search_at, search_count_90d "
                    "FROM contacts WHERE id=?",
                    (contact_id,),
                ).fetchone()
                if existing:
                    same = (
                        (existing["enrichment_brief"] or "") == brief
                        and (existing["activity_tier"] or "") == tier
                        and int(existing["search_count_90d"] or 0) == count_90d
                    )
                    if same:
                        stats.briefs_unchanged += 1
                        continue

                if not dry_run:
                    conn.execute(
                        """
                        UPDATE contacts
                           SET enrichment_brief = ?,
                               activity_tier    = ?,
                               last_search_at   = ?,
                               search_count_90d = ?
                         WHERE id = ?
                        """,
                        (
                            brief,
                            tier,
                            last_search_at.isoformat() if last_search_at else None,
                            count_90d,
                            contact_id,
                        ),
                    )
                stats.briefs_written += 1
            except Exception as exc:
                stats.errors.append(f"contact {contact_id}: {exc}")
                _log.exception("enrichment failed for %s", contact_id)

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    counts = stats.to_dict()
    state = "connected"
    return {
        "id": SOURCE_ID,
        "label": "Buyer Brief Enrichment",
        "state": state,
        "sourceExists": True,
        "connectionType": "local_enrichment",
        "syncMode": "compute",
        "authStatus": "n/a",
        "connected": True,
        "importOnly": False,
        "blocked": False,
        "lastError": counts["errors"][0] if counts["errors"] else None,
        "nextOperatorStep": None,
        "lastCheckedAt": _now().isoformat(),
        "recordCounts": {
            "contacts_walked": counts["contacts_walked"],
            "briefs_written": counts["briefs_written"],
            "briefs_unchanged": counts["briefs_unchanged"],
            "active": counts["tier_active"],
            "warm": counts["tier_warm"],
            "dormant": counts["tier_dormant"],
            "never_touched": counts["tier_never_touched"],
        },
        "dryRun": dry_run,
    }


def render(result: dict[str, Any]) -> str:
    """Pretty one-screen report for the CLI."""
    counts = result.get("recordCounts") or {}
    head = "DRY-RUN" if result.get("dryRun") else "APPLIED"
    lines = [
        f"[{head}] buyer-brief enrichment",
        f"  contacts walked    : {counts.get('contacts_walked', 0)}",
        f"  briefs written     : {counts.get('briefs_written', 0)}",
        f"  briefs unchanged   : {counts.get('briefs_unchanged', 0)}",
        f"  tier active        : {counts.get('active', 0)}",
        f"  tier warm          : {counts.get('warm', 0)}",
        f"  tier dormant       : {counts.get('dormant', 0)}",
        f"  tier never-touched : {counts.get('never_touched', 0)}",
    ]
    if result.get("lastError"):
        lines.append(f"  first error        : {result['lastError']}")
    return "\n".join(lines)


__all__ = ["SOURCE_ID", "EnrichmentStats", "render", "run_enrichment"]
