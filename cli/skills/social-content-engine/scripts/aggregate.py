"""Metrics aggregator for the social-content-engine skill.

Reads ``social-metrics.jsonl`` (append-only, one row per fetch), normalizes
each platform's native metric vocabulary into a common shape, computes
per-post derived rates, and writes a weekly snapshot to:

    ~/.elevate/state/<workspace>/social-snapshot.json

The snapshot is the single source of truth for both the UI (``/social-media``)
and the idea generator. Re-running the aggregator overwrites the snapshot.

Derived per-post metrics:
- hook_rate          : (3-sec / 1-sec views) / impressions, when both exist
- hold_rate          : avg_watch_time_sec / duration_sec, when both exist
- engagement_rate    : (likes + comments + saves + shares) / reach (or impressions)
- save_rate          : saves / reach (or impressions) — IG signal of high intent
- completion_rate    : alias for hold_rate when available
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  re-exec under the bundled app Python if launched by a bare python3

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _metrics_io import metrics_path, write_snapshot, snapshot_path


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _to_num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list) and v:
        # IG sometimes returns metrics as [{"value": N}]
        first = v[0]
        if isinstance(first, dict) and "value" in first:
            return _to_num(first["value"])
        return _to_num(first)
    if isinstance(v, dict):
        if "value" in v:
            return _to_num(v["value"])
        # post_reactions_by_type_total → {"like": N, "love": M, ...}
        try:
            return float(sum(_to_num(x) or 0 for x in v.values()))
        except Exception:
            return None
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _iso_duration_to_sec(iso: str | None) -> float | None:
    """Parse ISO-8601 duration like 'PT1M30S' → 90.0. YouTube + others."""
    if not iso or not isinstance(iso, str):
        return None
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", iso)
    if not m:
        return None
    h, mi, s = m.groups()
    return (float(h or 0) * 3600) + (float(mi or 0) * 60) + float(s or 0)


# ---- Per-platform normalizers --------------------------------------------------

def _normalize_instagram(row: dict[str, Any]) -> dict[str, Any]:
    m = row.get("metrics") or {}
    media_type = (row.get("media_type") or "").upper()

    reach = _to_num(m.get("reach"))
    impressions = _to_num(m.get("impressions")) or _to_num(m.get("plays"))
    plays = _to_num(m.get("plays"))
    likes = _to_num(m.get("likes"))
    comments = _to_num(m.get("comments"))
    saves = _to_num(m.get("saves"))
    shares = _to_num(m.get("shares"))
    total_interactions = _to_num(m.get("total_interactions"))
    profile_visits = _to_num(m.get("profile_visits"))
    follows = _to_num(m.get("follows"))
    video_views = _to_num(m.get("video_views"))

    # IG Reels avg watch time is reported in milliseconds
    avg_watch_ms = _to_num(m.get("ig_reels_avg_watch_time"))
    avg_watch_sec = (avg_watch_ms / 1000.0) if avg_watch_ms is not None else None
    total_watch_ms = _to_num(m.get("ig_reels_video_view_total_time"))

    return {
        "reach": reach,
        "impressions": impressions,
        "plays": plays,
        "likes": likes,
        "comments": comments,
        "saves": saves,
        "shares": shares,
        "video_views": video_views,
        "engagement_total": total_interactions
            or sum(x for x in (likes, comments, saves, shares) if x is not None) or None,
        "profile_visits": profile_visits,
        "follows": follows,
        "avg_watch_time_sec": avg_watch_sec,
        "total_watch_time_sec": (total_watch_ms / 1000.0) if total_watch_ms else None,
        "duration_sec": None,  # IG Graph doesn't expose video length in insights
    }


def _normalize_tiktok(row: dict[str, Any]) -> dict[str, Any]:
    m = row.get("metrics") or {}
    return {
        "reach": None,  # TikTok doesn't expose unique reach via Display API
        "impressions": _to_num(m.get("view_count")),
        "plays": _to_num(m.get("view_count")),
        "likes": _to_num(m.get("like_count")),
        "comments": _to_num(m.get("comment_count")),
        "saves": None,
        "shares": _to_num(m.get("share_count")),
        "video_views": _to_num(m.get("view_count")),
        "engagement_total": sum(
            x for x in (
                _to_num(m.get("like_count")),
                _to_num(m.get("comment_count")),
                _to_num(m.get("share_count")),
            ) if x is not None
        ) or None,
        "avg_watch_time_sec": _to_num(m.get("avg_watch_time_sec")),
        "total_watch_time_sec": _to_num(m.get("total_time_watched_sec")),
        "duration_sec": _to_num(m.get("duration_sec")),
        "full_video_watched_rate": _to_num(m.get("full_video_watched_rate")),
    }


def _normalize_youtube(row: dict[str, Any]) -> dict[str, Any]:
    m = row.get("metrics") or {}
    duration_iso = m.get("duration_iso")
    return {
        "reach": None,
        "impressions": _to_num(m.get("view_count")),
        "plays": _to_num(m.get("view_count")),
        "likes": _to_num(m.get("like_count")),
        "comments": _to_num(m.get("comment_count")),
        "saves": _to_num(m.get("favorite_count")),
        "shares": None,
        "video_views": _to_num(m.get("view_count")),
        "engagement_total": sum(
            x for x in (_to_num(m.get("like_count")), _to_num(m.get("comment_count")))
            if x is not None
        ) or None,
        "avg_watch_time_sec": _to_num(m.get("avg_view_duration_sec")),
        "total_watch_time_sec": None,
        "duration_sec": _iso_duration_to_sec(duration_iso),
        "avg_view_percentage": _to_num(m.get("avg_view_percentage")),
    }


def _normalize_facebook(row: dict[str, Any]) -> dict[str, Any]:
    m = row.get("metrics") or {}
    impressions = _to_num(m.get("post_impressions"))
    reach = _to_num(m.get("post_impressions_unique"))
    engaged = _to_num(m.get("post_engaged_users"))
    clicks = _to_num(m.get("post_clicks"))
    reactions = _to_num(m.get("post_reactions_by_type_total"))
    video_views = _to_num(m.get("post_video_views"))
    avg_watch = _to_num(m.get("post_video_avg_time_watched"))  # ms

    return {
        "reach": reach,
        "impressions": impressions,
        "plays": video_views,
        "likes": reactions,
        "comments": None,
        "saves": None,
        "shares": None,
        "video_views": video_views,
        "engagement_total": engaged or sum(
            x for x in (reactions, clicks) if x is not None
        ) or None,
        "clicks": clicks,
        "avg_watch_time_sec": (avg_watch / 1000.0) if avg_watch else None,
        "total_watch_time_sec": (_to_num(m.get("post_video_view_time_organic")) or 0) / 1000.0
            if m.get("post_video_view_time_organic") else None,
        "duration_sec": None,
    }


def _normalize_linkedin(row: dict[str, Any]) -> dict[str, Any]:
    m = row.get("metrics") or {}
    impressions = _to_num(m.get("impression_count"))
    reach = _to_num(m.get("unique_impression_count"))
    likes = _to_num(m.get("like_count"))
    comments = _to_num(m.get("comment_count"))
    shares = _to_num(m.get("share_count"))
    clicks = _to_num(m.get("click_count"))
    engagement = _to_num(m.get("engagement"))
    return {
        "reach": reach,
        "impressions": impressions,
        "plays": None,
        "likes": likes,
        "comments": comments,
        "saves": None,
        "shares": shares,
        "video_views": None,
        "engagement_total": engagement
            or sum(x for x in (likes, comments, shares, clicks) if x is not None) or None,
        "clicks": clicks,
        "avg_watch_time_sec": None,
        "total_watch_time_sec": None,
        "duration_sec": None,
    }


NORMALIZERS = {
    "instagram": _normalize_instagram,
    "tiktok": _normalize_tiktok,
    "youtube": _normalize_youtube,
    "facebook": _normalize_facebook,
    "linkedin": _normalize_linkedin,
}


def _derive(stats: dict[str, Any]) -> dict[str, Any]:
    """Compute the rates that the idea generator + UI care about."""
    out = dict(stats)
    # Reach is the preferred denominator (unique users). Fall back to impressions
    # only if the platform doesn't expose unique reach (TikTok, YouTube).
    reach = stats.get("reach") or stats.get("impressions") or stats.get("plays")
    eng = stats.get("engagement_total")

    if reach and reach > 0 and eng is not None:
        out["engagement_rate"] = round(eng / reach, 4)
    else:
        out["engagement_rate"] = None

    saves = stats.get("saves")
    if reach and reach > 0 and saves is not None:
        out["save_rate"] = round(saves / reach, 4)
    else:
        out["save_rate"] = None

    # Hold rate: avg watch time / video duration
    awt = stats.get("avg_watch_time_sec")
    dur = stats.get("duration_sec")
    if awt is not None and dur and dur > 0:
        out["hold_rate"] = round(min(awt / dur, 1.0), 4)
    elif stats.get("avg_view_percentage") is not None:
        out["hold_rate"] = round(stats["avg_view_percentage"] / 100.0, 4)
    elif stats.get("full_video_watched_rate") is not None:
        out["hold_rate"] = round(stats["full_video_watched_rate"], 4)
    else:
        out["hold_rate"] = None

    # Hook rate: % of impressions that became plays. Only meaningful when the
    # platform exposes both impressions (feed renders) AND plays/views as
    # distinct values. Autoplay platforms (IG Reels, TikTok feed) collapse the
    # two — leave null there. Facebook video and YouTube long-form expose both.
    impressions_raw = stats.get("impressions")
    plays_raw = stats.get("plays") or stats.get("video_views")
    if (
        impressions_raw and plays_raw
        and impressions_raw > 0
        and plays_raw != impressions_raw
    ):
        out["hook_rate"] = round(min(plays_raw / impressions_raw, 1.0), 4)
    else:
        out["hook_rate"] = None

    return out


# ---- Aggregation ---------------------------------------------------------------

def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _latest_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the most recent row per (platform, post_id)."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        platform = r.get("platform")
        post_id = r.get("post_id")
        if not platform or not post_id:
            continue
        key = (platform, post_id)
        existing = by_key.get(key)
        if not existing:
            by_key[key] = r
            continue
        if (r.get("fetched_at") or "") > (existing.get("fetched_at") or ""):
            by_key[key] = r
    return list(by_key.values())


def _within(posted_at: str | None, cutoff: datetime) -> bool:
    dt = _parse_iso(posted_at)
    if not dt:
        return False
    return dt >= cutoff


def _safe_sort(items: list[dict[str, Any]], key: str, *, reverse: bool = True) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: (x.get("derived", {}).get(key) or x.get("derived", {}).get(key.replace("_rate", "_total")) or 0), reverse=reverse)


def aggregate(*, lookback_days: int = 30) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    prior_cutoff = cutoff - timedelta(days=lookback_days)  # for WoW comparison

    all_rows = list(_read_jsonl(metrics_path()))
    latest = _latest_rows(all_rows)

    snapshot: dict[str, Any] = {
        "lookback_days": lookback_days,
        "window_start": cutoff.isoformat(timespec="seconds"),
        "platforms": {},
        "totals": {
            "post_count": 0,
            "reach": 0,
            "impressions": 0,
            "engagement_total": 0,
        },
        "top_posts": [],
        "bottom_posts": [],
        "format_breakdown": {},
        "wow_delta": {},
    }

    enriched_posts: list[dict[str, Any]] = []
    enriched_account: list[dict[str, Any]] = []
    prior_posts: list[dict[str, Any]] = []

    for row in latest:
        platform = row.get("platform")
        if platform not in NORMALIZERS:
            continue
        normalizer = NORMALIZERS[platform]
        media_type = (row.get("media_type") or "").upper()

        if media_type == "ACCOUNT":
            enriched_account.append({
                "platform": platform,
                "post_id": row.get("post_id"),
                "metrics": row.get("metrics") or {},
                "fetched_at": row.get("fetched_at"),
            })
            continue

        derived = _derive(normalizer(row))
        enriched = {
            "platform": platform,
            "post_id": row.get("post_id"),
            "posted_at": row.get("posted_at"),
            "permalink": row.get("permalink"),
            "caption": row.get("caption"),
            "media_type": media_type,
            "fetched_at": row.get("fetched_at"),
            "derived": derived,
        }

        if _within(row.get("posted_at"), cutoff):
            enriched_posts.append(enriched)
        elif _within(row.get("posted_at"), prior_cutoff):
            prior_posts.append(enriched)

    # Per-platform breakdown
    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in enriched_posts:
        by_platform[p["platform"]].append(p)

    fmt_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for platform, posts in by_platform.items():
        reach_sum = sum(p["derived"].get("reach") or 0 for p in posts)
        impressions_sum = sum(p["derived"].get("impressions") or 0 for p in posts)
        eng_sum = sum(p["derived"].get("engagement_total") or 0 for p in posts)

        # Average rates only over posts where the rate exists
        eng_rates = [p["derived"]["engagement_rate"] for p in posts if p["derived"].get("engagement_rate") is not None]
        hold_rates = [p["derived"]["hold_rate"] for p in posts if p["derived"].get("hold_rate") is not None]
        hook_rates = [p["derived"]["hook_rate"] for p in posts if p["derived"].get("hook_rate") is not None]
        save_rates = [p["derived"]["save_rate"] for p in posts if p["derived"].get("save_rate") is not None]

        snapshot["platforms"][platform] = {
            "post_count": len(posts),
            "totals": {
                "reach": reach_sum,
                "impressions": impressions_sum,
                "engagement_total": eng_sum,
            },
            "averages": {
                "engagement_rate": round(sum(eng_rates) / len(eng_rates), 4) if eng_rates else None,
                "hook_rate": round(sum(hook_rates) / len(hook_rates), 4) if hook_rates else None,
                "hold_rate": round(sum(hold_rates) / len(hold_rates), 4) if hold_rates else None,
                "save_rate": round(sum(save_rates) / len(save_rates), 4) if save_rates else None,
            },
            "top_posts": [
                {
                    "post_id": p["post_id"],
                    "permalink": p.get("permalink"),
                    "caption": (p.get("caption") or "")[:140],
                    "media_type": p["media_type"],
                    "posted_at": p.get("posted_at"),
                    "derived": p["derived"],
                }
                for p in _safe_sort(posts, "engagement_rate", reverse=True)[:5]
            ],
            "bottom_posts": [
                {
                    "post_id": p["post_id"],
                    "permalink": p.get("permalink"),
                    "caption": (p.get("caption") or "")[:140],
                    "media_type": p["media_type"],
                    "posted_at": p.get("posted_at"),
                    "derived": p["derived"],
                }
                for p in _safe_sort(posts, "engagement_rate", reverse=False)[:5]
                if p["derived"].get("engagement_rate") is not None
            ],
            "account_metrics": next(
                (a["metrics"] for a in enriched_account if a["platform"] == platform),
                {},
            ),
        }

        for p in posts:
            fmt_counts[platform][p["media_type"] or "UNKNOWN"] += 1

    snapshot["format_breakdown"] = {p: dict(counts) for p, counts in fmt_counts.items()}

    # Cross-platform top + bottom (same engagement_rate sort)
    snapshot["top_posts"] = [
        {
            "platform": p["platform"],
            "post_id": p["post_id"],
            "permalink": p.get("permalink"),
            "caption": (p.get("caption") or "")[:140],
            "media_type": p["media_type"],
            "posted_at": p.get("posted_at"),
            "derived": p["derived"],
        }
        for p in _safe_sort(enriched_posts, "engagement_rate", reverse=True)[:10]
    ]
    snapshot["bottom_posts"] = [
        {
            "platform": p["platform"],
            "post_id": p["post_id"],
            "permalink": p.get("permalink"),
            "caption": (p.get("caption") or "")[:140],
            "media_type": p["media_type"],
            "posted_at": p.get("posted_at"),
            "derived": p["derived"],
        }
        for p in _safe_sort(enriched_posts, "engagement_rate", reverse=False)[:10]
        if p["derived"].get("engagement_rate") is not None
    ]

    snapshot["totals"] = {
        "post_count": len(enriched_posts),
        "reach": sum(p["derived"].get("reach") or 0 for p in enriched_posts),
        "impressions": sum(p["derived"].get("impressions") or 0 for p in enriched_posts),
        "engagement_total": sum(p["derived"].get("engagement_total") or 0 for p in enriched_posts),
    }

    # Week-over-week delta (current window vs equally-sized prior window)
    def _avg(items: list[dict[str, Any]], k: str) -> float | None:
        vals = [p["derived"].get(k) for p in items if p["derived"].get(k) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    def _delta(curr: float | None, prior: float | None) -> float | None:
        if curr is None or prior is None or prior == 0:
            return None
        return round((curr - prior) / prior, 4)

    snapshot["wow_delta"] = {
        "post_count_delta": len(enriched_posts) - len(prior_posts),
        "engagement_rate_delta": _delta(
            _avg(enriched_posts, "engagement_rate"),
            _avg(prior_posts, "engagement_rate"),
        ),
        "hook_rate_delta": _delta(
            _avg(enriched_posts, "hook_rate"),
            _avg(prior_posts, "hook_rate"),
        ),
        "hold_rate_delta": _delta(
            _avg(enriched_posts, "hold_rate"),
            _avg(prior_posts, "hold_rate"),
        ),
    }

    snapshot["account_metrics"] = {a["platform"]: a["metrics"] for a in enriched_account}

    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate social-metrics.jsonl into a snapshot")
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--print", action="store_true", help="print snapshot JSON to stdout")
    args = parser.parse_args(argv)

    snapshot = aggregate(lookback_days=args.lookback)
    out = write_snapshot(snapshot)
    if args.print:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({
            "snapshot_path": str(out),
            "lookback_days": snapshot["lookback_days"],
            "post_count": snapshot["totals"]["post_count"],
            "platforms": list(snapshot["platforms"].keys()),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
