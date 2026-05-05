"""Instagram metric fetcher (Composio-backed).

Pulls the last N days of posts from a connected Instagram account and writes
the full insight payload (per-post + account-level) to social-metrics.jsonl.

Composio slugs used:
- INSTAGRAM_GET_IG_USER_MEDIA       — list posts (paginated)
- INSTAGRAM_GET_IG_MEDIA_INSIGHTS   — per-post deep insights
- INSTAGRAM_GET_USER_INSIGHTS       — account-level (followers, reach, demographics)

Per-post metrics requested (varies by media_product_type):
  REELS:    plays, reach, likes, comments, saves, shares, total_interactions,
            ig_reels_video_view_total_time, ig_reels_avg_watch_time
  FEED:     impressions, reach, likes, comments, saves, shares, profile_visits, follows
  STORY:    impressions, reach, exits, replies, taps_forward, taps_back

If the platform isn't connected via Composio, exits 0 with a `not_configured`
log line — callers (the skill orchestrator) should treat that as "skip, not
fail."
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

# Make the shared I/O importable regardless of cwd
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _metrics_io import (
    append_metric,
    find_composio_account,
    has_post_been_seen,
)


TOOLKIT_SLUG = "instagram"
SLUG_LIST_MEDIA = "INSTAGRAM_GET_USER_MEDIA"
SLUG_MEDIA_INSIGHTS = "INSTAGRAM_GET_POST_INSIGHTS"
SLUG_USER_INSIGHTS = "INSTAGRAM_GET_USER_INSIGHTS"

# Metric whitelists per media_product_type. Composio passes these through to
# the Graph API's `metric=` query param. Asking for unsupported metrics on a
# given media type returns 400, so we tier them.
#
# Valid metric names (per Meta v22+ Media Insights API, May 2026):
#   impressions (deprecated for posts after 2024-04-21 — Reels never had it)
#   shares, comments, plays, likes, saved, replies, total_interactions,
#   navigation, follows, profile_visits, profile_activity, reach, views,
#   ig_reels_video_view_total_time, ig_reels_avg_watch_time,
#   clips_replays_count, ig_reels_aggregated_all_plays_count,
#   total_views, total_likes, total_comments
METRICS_REEL = [
    "reach",
    "likes",
    "comments",
    "saved",
    "shares",
    "total_interactions",
    "views",
    "ig_reels_video_view_total_time",
    "ig_reels_avg_watch_time",
]
METRICS_FEED = [
    "reach",
    "likes",
    "comments",
    "saved",
    "shares",
    "total_interactions",
    "views",
    "profile_visits",
    "profile_activity",
    "follows",
]
METRICS_STORY = [
    "reach",
    "views",
    "replies",
    "navigation",
    "total_interactions",
    "profile_visits",
    "follows",
]
METRICS_VIDEO = METRICS_REEL  # IG VIDEO == Reel under the hood post-2022


def _metrics_for(media_type: str, product_type: str) -> list[str]:
    pt = (product_type or "").upper()
    mt = (media_type or "").upper()
    if pt == "REELS":
        return METRICS_REEL
    if pt == "STORY":
        return METRICS_STORY
    if mt == "VIDEO":
        return METRICS_VIDEO
    return METRICS_FEED


def _within_lookback(posted_at: str | None, cutoff: datetime) -> bool:
    if not posted_at:
        return False
    try:
        # IG returns ISO with timezone, e.g. "2026-04-15T18:32:00+0000"
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True  # don't drop if we can't parse — let aggregator decide
    return dt >= cutoff


def fetch(*, lookback_days: int = 30, max_posts: int = 200) -> dict[str, Any]:
    """Returns a small summary dict for the run log."""
    summary: dict[str, Any] = {
        "platform": "instagram",
        "lookback_days": lookback_days,
        "posts_seen": 0,
        "posts_with_insights": 0,
        "errors": [],
        "status": "ok",
    }

    account = find_composio_account(TOOLKIT_SLUG)
    if not account:
        summary["status"] = "not_configured"
        return summary

    try:
        from elevate_cli import composio_client
    except Exception as exc:
        summary["status"] = "import_failed"
        summary["errors"].append(f"composio_client import failed: {exc}")
        return summary

    account_id = account.get("id") or account.get("connected_account_id")
    if not account_id:
        summary["status"] = "no_account_id"
        return summary

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    def _unwrap(resp: dict[str, Any]) -> dict[str, Any]:
        # Composio: {ok, data: {data|response_data: <graph>}}
        body = resp.get("data") or {}
        if not isinstance(body, dict):
            return {}
        inner = body.get("data") if isinstance(body.get("data"), dict) else body
        if isinstance(inner, dict) and isinstance(inner.get("response_data"), dict):
            inner = inner["response_data"]
        return inner if isinstance(inner, dict) else {}

    # 1) List recent media. Composio paginates via `after` cursor in the response.
    cursor: str | None = None
    pulled = 0
    posts: list[dict[str, Any]] = []
    page = 0
    while pulled < max_posts and page < 10:
        args: dict[str, Any] = {
            "fields": (
                "id,caption,media_type,media_product_type,permalink,timestamp,"
                "thumbnail_url,media_url,like_count,comments_count,"
                # duration is required for hold-rate (avg_watch_time / duration).
                # IG returns it in seconds for VIDEO/REELS media types.
                "duration"
            ),
            "limit": 50,
        }
        if cursor:
            args["after"] = cursor
        resp = composio_client.execute_tool(SLUG_LIST_MEDIA, account_id, args)
        if not resp.get("ok"):
            summary["errors"].append(f"list_media page {page}: {resp.get('error')}")
            break
        graph = _unwrap(resp)
        items = graph.get("data") or []
        if not isinstance(items, list):
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            posted_at = item.get("timestamp")
            if not _within_lookback(posted_at, cutoff):
                pulled = max_posts
                break
            posts.append(item)
            pulled += 1
            if pulled >= max_posts:
                break
        cursor = ((graph.get("paging") or {}).get("cursors") or {}).get("after")
        if not cursor:
            break
        page += 1

    summary["posts_seen"] = len(posts)

    # 2) Per-post insights
    for item in posts:
        media_id = item.get("id")
        if not media_id:
            continue
        product_type = item.get("media_product_type") or ""
        media_type = item.get("media_type") or ""
        metric_list = _metrics_for(media_type, product_type)
        ins_resp = composio_client.execute_tool(
            SLUG_MEDIA_INSIGHTS,
            account_id,
            {"ig_post_id": str(media_id), "metric": metric_list},
        )
        metrics_payload: dict[str, Any] = {}
        # Composio wraps tool calls; transport-level ok=True can still hide
        # an upstream Graph API failure in `data.successful=false`.
        inner = ins_resp.get("data") if isinstance(ins_resp, dict) else None
        tool_successful = bool(inner.get("successful")) if isinstance(inner, dict) else False
        tool_error = (
            inner.get("error") if isinstance(inner, dict) else None
        ) or ins_resp.get("error")
        if ins_resp.get("ok") and tool_successful:
            data_list = _unwrap(ins_resp).get("data") or []
            if isinstance(data_list, dict) and isinstance(data_list.get("data"), list):
                data_list = data_list["data"]
            if not isinstance(data_list, list):
                data_list = []
            for entry in data_list:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                values = entry.get("values") or []
                value = values[0].get("value") if values and isinstance(values[0], dict) else None
                if name:
                    metrics_payload[name] = value
            summary["posts_with_insights"] += 1
        else:
            summary["errors"].append(f"insights {media_id}: {tool_error}")
            metrics_payload["_error"] = tool_error

        # Hoist engagement counts from the post fields when /insights returns
        # nothing — covers personal accounts where Graph denies insights API.
        # Keep the platform's native metric names (likes, comments, shares,
        # views, saved) — no aliasing, no duplicates.
        post_likes = item.get("like_count")
        post_comments = item.get("comments_count")
        if isinstance(post_likes, int) and "likes" not in metrics_payload:
            metrics_payload["likes"] = post_likes
        if isinstance(post_comments, int) and "comments" not in metrics_payload:
            metrics_payload["comments"] = post_comments

        # Hoist duration (seconds) so the frontend can derive hold rate.
        duration = item.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            metrics_payload["duration_sec"] = float(duration)

        first_seen = not has_post_been_seen("instagram", media_id)
        append_metric(
            platform="instagram",
            post_id=media_id,
            posted_at=item.get("timestamp"),
            media_type=(product_type or media_type or "UNKNOWN").upper(),
            permalink=item.get("permalink"),
            caption=item.get("caption"),
            metrics=metrics_payload,
            raw=item,
            include_raw=True,
        )

    # 3) Account-level insights (one shot, lifetime + 30d window)
    acc_resp = composio_client.execute_tool(
        SLUG_USER_INSIGHTS,
        account_id,
        {
            "metric": "reach,follower_count,profile_views,website_clicks",
            "period": "day",
            "since": int(cutoff.timestamp()),
            "until": int(datetime.now(timezone.utc).timestamp()),
        },
    )
    if acc_resp.get("ok"):
        acc_metrics = {}
        for entry in _unwrap(acc_resp).get("data") or []:
            if isinstance(entry, dict) and entry.get("name"):
                acc_metrics[entry["name"]] = entry.get("values")
        append_metric(
            platform="instagram",
            post_id=f"_account_{account_id}",
            posted_at=None,
            media_type="ACCOUNT",
            permalink=None,
            caption=None,
            metrics=acc_metrics,
        )
    else:
        summary["errors"].append(f"user_insights: {acc_resp.get('error')}")

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Instagram metrics into social-metrics.jsonl")
    parser.add_argument("--lookback", type=int, default=30, help="days of post history to pull")
    parser.add_argument("--max-posts", type=int, default=200, help="hard cap on posts per run")
    args = parser.parse_args(argv)
    summary = fetch(lookback_days=args.lookback, max_posts=args.max_posts)
    import json
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "ok" else 0  # not_configured is OK


if __name__ == "__main__":
    sys.exit(main())
