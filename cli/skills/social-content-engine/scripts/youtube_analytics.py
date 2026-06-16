"""YouTube metric fetcher (Composio).

Composio slugs used:
- YOUTUBE_LIST_CHANNEL_VIDEOS    — list videos from authenticated channel
- YOUTUBE_VIDEO_DETAILS          — fetch statistics for a single video
- YOUTUBE_GET_CHANNEL_STATISTICS — channel-level

Per-video metrics surfaced from the `statistics` part:
  viewCount, likeCount, dislikeCount, commentCount, favoriteCount

YouTube's deep retention metrics (averageViewDuration,
averageViewPercentage, audienceRetentionData) require the YouTube Analytics
API which is a separate scope. Mark hold-rate fields null in v1.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  re-exec under the bundled app Python if launched by a bare python3

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _metrics_io import append_metric, find_composio_account, has_post_been_seen


TOOLKIT_SLUG = "youtube"
SLUG_LIST = "YOUTUBE_LIST_CHANNEL_VIDEOS"
SLUG_VIDEO = "YOUTUBE_VIDEO_DETAILS"
SLUG_CHANNEL_STATS = "YOUTUBE_GET_CHANNEL_STATISTICS"


def _within(published_at: str | None, cutoff: datetime) -> bool:
    if not published_at:
        return True
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return dt >= cutoff


def fetch(*, lookback_days: int = 30, max_posts: int = 200) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "platform": "youtube",
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

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    def _unwrap(resp: dict[str, Any]) -> dict[str, Any]:
        body = resp.get("data") or {}
        if not isinstance(body, dict):
            return {}
        inner = body.get("data") if isinstance(body.get("data"), dict) else body
        if isinstance(inner, dict) and isinstance(inner.get("response_data"), dict):
            inner = inner["response_data"]
        return inner if isinstance(inner, dict) else {}

    # 0) Discover channel ID via user playlists (the only YT endpoint that
    # returns the connected channel without already knowing its ID).
    pl_resp = composio_client.execute_tool(
        "YOUTUBE_LIST_USER_PLAYLISTS",
        account_id,
        {"part": "snippet", "maxResults": 1},
    )
    if not pl_resp.get("ok"):
        summary["errors"].append(f"discover_channel: {pl_resp.get('error')}")
        return summary
    pl_items = _unwrap(pl_resp).get("items") or []
    channel_id = None
    if pl_items and isinstance(pl_items[0], dict):
        channel_id = (pl_items[0].get("snippet") or {}).get("channelId")
    if not channel_id:
        summary["status"] = "no_channel_id"
        return summary

    # 0b) Channel stats (now that we have an id)
    ch_resp = composio_client.execute_tool(SLUG_CHANNEL_STATS, account_id, {"id": channel_id, "part": "statistics,snippet"})
    ch_items = _unwrap(ch_resp).get("items") or [] if ch_resp.get("ok") else []

    # 1) List uploads. YouTube Data API search.list caps maxResults at 50,
    # so clamp here regardless of caller intent (Composio forwards as-is).
    list_resp = composio_client.execute_tool(
        SLUG_LIST,
        account_id,
        {"channelId": channel_id, "max_results": min(max_posts, 50)},
    )
    if not list_resp.get("ok"):
        summary["errors"].append(f"list: {list_resp.get('error')}")
        return summary
    list_unwrapped = _unwrap(list_resp)
    # Composio sometimes wraps a Google API error inside {message, status_code}
    # instead of failing at the transport layer — surface it as an error.
    if "items" not in list_unwrapped and ("message" in list_unwrapped or "status_code" in list_unwrapped):
        summary["errors"].append(
            f"list: {list_unwrapped.get('message') or 'API error'} (status={list_unwrapped.get('status_code')})"
        )
        return summary
    items = list_unwrapped.get("items") or []
    if not isinstance(items, list):
        items = []
    video_ids: list[str] = []
    snippet_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") or {}
        published_at = snippet.get("publishedAt")
        if not _within(published_at, cutoff):
            continue
        # Composio normalizes either {id: "..."} or {id: {videoId: "..."}}
        vid = item.get("id")
        if isinstance(vid, dict):
            vid = vid.get("videoId")
        if not vid:
            continue
        video_ids.append(str(vid))
        snippet_by_id[str(vid)] = {
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "publishedAt": published_at,
            "thumbnail": (snippet.get("thumbnails") or {}).get("high", {}).get("url"),
        }

    summary["posts_seen"] = len(video_ids)
    if not video_ids:
        return summary

    # 2) Per-video stats (no batch endpoint — iterate)
    for vid in video_ids:
        v_resp = composio_client.execute_tool(
            SLUG_VIDEO,
            account_id,
            {"id": vid, "part": "snippet,contentDetails,statistics"},
        )
        if not v_resp.get("ok"):
            summary["errors"].append(f"video {vid}: {v_resp.get('error')}")
            continue
        vitems = _unwrap(v_resp).get("items") or []
        if not vitems or not isinstance(vitems[0], dict):
            continue
        it = vitems[0]
        stats = it.get("statistics") or {}
        content = it.get("contentDetails") or {}
        snip = snippet_by_id.get(str(vid), {})
        duration_iso = content.get("duration")  # ISO 8601 e.g. "PT1M30S"
        permalink = (
            f"https://www.youtube.com/watch?v={vid}"
            if not (duration_iso and "S" in duration_iso and "M" not in duration_iso)
            else f"https://www.youtube.com/shorts/{vid}"
        )
        metrics = {
            "view_count": _to_int(stats.get("viewCount")),
            "like_count": _to_int(stats.get("likeCount")),
            "dislike_count": _to_int(stats.get("dislikeCount")),
            "comment_count": _to_int(stats.get("commentCount")),
            "favorite_count": _to_int(stats.get("favoriteCount")),
            "duration_iso": duration_iso,
            # Deep retention metrics need YouTube Analytics API scope
            "avg_view_duration_sec": None,
            "avg_view_percentage": None,
        }
        append_metric(
            platform="youtube",
            post_id=str(vid),
            posted_at=snip.get("publishedAt"),
            media_type="SHORT" if (duration_iso or "").startswith("PT") and "M" not in (duration_iso or "") else "VIDEO",
            permalink=permalink,
            caption=snip.get("title"),
            metrics=metrics,
            raw={"snippet": snip, "stats": stats, "contentDetails": content, "thumbnail": snip.get("thumbnail")},
            include_raw=True,
        )
        summary["posts_with_insights"] += 1

    # 3) Channel stats (already pulled in step 0; reuse)
    if ch_items and isinstance(ch_items[0], dict):
        stats = ch_items[0].get("statistics") or {}
        append_metric(
            platform="youtube",
            post_id=f"_account_{account_id}",
            posted_at=None,
            media_type="ACCOUNT",
            permalink=None,
            caption=None,
            metrics={
                "subscriber_count": _to_int(stats.get("subscriberCount")),
                "view_count": _to_int(stats.get("viewCount")),
                "video_count": _to_int(stats.get("videoCount")),
            },
        )

    return summary


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--max-posts", type=int, default=200)
    args = parser.parse_args(argv)
    import json
    print(json.dumps(fetch(lookback_days=args.lookback, max_posts=args.max_posts), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
