"""TikTok metric fetcher (Composio + direct fallback).

Composio currently exposes only:
- TIKTOK_LIST_VIDEOS     — list videos for the authenticated user
- TIKTOK_GET_USER_STATS  — account-level (follower count, etc.)

There is no Composio slug for per-video deep insights (avg_watch_time,
total_time_watched, full_video_watched_rate). The Display API gives basic
counts (views, likes, comments, shares); the Marketing API gives the deep
metrics but requires a separate business account dance.

v1: pull what Composio gives us — view_count, like_count, comment_count,
share_count per video — and account-level stats. Mark hold-rate fields as
`null` so the aggregator can show "not available" rather than fake a number.
v2: layer in TikTok Marketing API for per-video retention.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _metrics_io import append_metric, find_composio_account, has_post_been_seen


TOOLKIT_SLUG = "tiktok"
SLUG_LIST = "TIKTOK_LIST_VIDEOS"
SLUG_USER_STATS = "TIKTOK_GET_USER_STATS"

VIDEO_FIELDS = [
    "id",
    "create_time",
    "video_description",
    "duration",
    "cover_image_url",
    "share_url",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
]


def fetch(*, lookback_days: int = 30, max_posts: int = 200) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "platform": "tiktok",
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
        summary["errors"].append(str(exc))
        return summary

    account_id = account.get("id")
    if not account_id:
        summary["status"] = "no_account_id"
        return summary

    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp()

    # 1) List videos. TikTok Display API returns up to 20 per page; paginate via cursor.
    cursor: int | None = None
    pulled = 0
    page = 0
    while pulled < max_posts and page < 10:
        args: dict[str, Any] = {"fields": ",".join(VIDEO_FIELDS), "max_count": 20}
        if cursor:
            args["cursor"] = cursor
        resp = composio_client.execute_tool(SLUG_LIST, account_id, args)
        if not resp.get("ok"):
            summary["errors"].append(f"list page {page}: {resp.get('error')}")
            break
        body = resp.get("data") or {}
        rd = body.get("response_data") if isinstance(body, dict) else None
        videos = (rd or {}).get("videos") or body.get("videos") or []
        for v in videos:
            if not isinstance(v, dict):
                continue
            create_time = v.get("create_time")
            if create_time and float(create_time) < cutoff_ts:
                pulled = max_posts
                break
            metrics = {
                "view_count": v.get("view_count"),
                "like_count": v.get("like_count"),
                "comment_count": v.get("comment_count"),
                "share_count": v.get("share_count"),
                "duration_sec": v.get("duration"),
                # Deep retention metrics not available via Composio
                "avg_watch_time_sec": None,
                "total_time_watched_sec": None,
                "full_video_watched_rate": None,
            }
            posted_at = (
                datetime.fromtimestamp(int(create_time), tz=timezone.utc).isoformat()
                if create_time
                else None
            )
            first_seen = not has_post_been_seen("tiktok", str(v.get("id")))
            append_metric(
                platform="tiktok",
                post_id=str(v.get("id")),
                posted_at=posted_at,
                media_type="VIDEO",
                permalink=v.get("share_url"),
                caption=v.get("video_description"),
                metrics=metrics,
                raw=v if first_seen else None,
                include_raw=first_seen,
            )
            pulled += 1
            summary["posts_with_insights"] += 1
            if pulled >= max_posts:
                break
        cursor = (rd or {}).get("cursor") or body.get("cursor")
        if not cursor:
            break
        page += 1

    summary["posts_seen"] = pulled

    # 2) Account-level stats
    stats_resp = composio_client.execute_tool(SLUG_USER_STATS, account_id, {})
    if stats_resp.get("ok"):
        sb = stats_resp.get("data") or {}
        srd = sb.get("response_data") if isinstance(sb, dict) else None
        user = (srd or {}).get("user") or sb.get("user") or {}
        append_metric(
            platform="tiktok",
            post_id=f"_account_{account_id}",
            posted_at=None,
            media_type="ACCOUNT",
            permalink=None,
            caption=None,
            metrics={
                "follower_count": user.get("follower_count"),
                "following_count": user.get("following_count"),
                "likes_count": user.get("likes_count"),
                "video_count": user.get("video_count"),
            },
        )
    else:
        summary["errors"].append(f"user_stats: {stats_resp.get('error')}")

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull TikTok metrics")
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--max-posts", type=int, default=200)
    args = parser.parse_args(argv)
    import json
    print(json.dumps(fetch(lookback_days=args.lookback, max_posts=args.max_posts), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
