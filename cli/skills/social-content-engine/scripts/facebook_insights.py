"""Facebook Page metric fetcher (Composio).

Composio slugs used:
- FACEBOOK_GET_USER_PAGES     — discover the page(s) the connected user manages
- FACEBOOK_GET_PAGE_POSTS     — list posts on a page
- FACEBOOK_GET_POST_INSIGHTS  — per-post insights
- FACEBOOK_GET_PAGE_INSIGHTS  — page-level insights
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

from _metrics_io import append_metric, find_composio_account, has_post_been_seen, resolve_connected_account


TOOLKIT_SLUG = "facebook"
SLUG_USER_PAGES = "FACEBOOK_GET_USER_PAGES"
SLUG_PAGE_POSTS = "FACEBOOK_GET_PAGE_POSTS"
SLUG_POST_INSIGHTS = "FACEBOOK_GET_POST_INSIGHTS"
SLUG_PAGE_INSIGHTS = "FACEBOOK_GET_PAGE_INSIGHTS"

POST_METRICS = [
    "post_impressions",
    "post_impressions_unique",
    "post_engaged_users",
    "post_reactions_by_type_total",
    "post_clicks",
    "post_video_views",
    "post_video_avg_time_watched",
    "post_video_view_time_organic",
]
PAGE_METRICS = [
    "page_impressions",
    "page_impressions_unique",
    "page_engaged_users",
    "page_fans",
    "page_fan_adds",
    "page_views_total",
]


def _within(created_time: str | None, cutoff: datetime) -> bool:
    if not created_time:
        return True
    try:
        dt = datetime.fromisoformat(created_time.replace("+0000", "+00:00"))
    except ValueError:
        return True
    return dt >= cutoff


def fetch(*, lookback_days: int = 30, max_posts: int = 200) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "platform": "facebook",
        "lookback_days": lookback_days,
        "posts_seen": 0,
        "posts_with_insights": 0,
        "errors": [],
        "status": "ok",
    }

    account, conn_status = resolve_connected_account(TOOLKIT_SLUG)
    if not account:
        summary["status"] = conn_status
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
        # Composio shape: {ok, data: {data|response_data: <graph>, successful, error}}
        # Graph shape: {data: [...], paging: {...}} or {response_data: {data: [...]}}
        body = resp.get("data") or {}
        if not isinstance(body, dict):
            return {}
        inner = body.get("data") if isinstance(body.get("data"), dict) else body
        if isinstance(inner, dict) and isinstance(inner.get("response_data"), dict):
            inner = inner["response_data"]
        return inner if isinstance(inner, dict) else {}

    # 1) Discover the pages (use the connected user's managed pages)
    pages_resp = composio_client.execute_tool(SLUG_USER_PAGES, account_id, {})
    if not pages_resp.get("ok"):
        summary["errors"].append(f"user_pages: {pages_resp.get('error')}")
        return summary
    pages = _unwrap(pages_resp).get("data") or []
    if not isinstance(pages, list) or not pages:
        summary["status"] = "no_pages"
        return summary

    # Respect the page selection saved via /api/composio/facebook/pages.
    # If the user picked a subset on the backend, only pull those pages.
    try:
        from elevate_cli.composio_inbound import load_selection
        selection = load_selection("facebook") or {}
        selected_ids = set(selection.get("selected_page_ids") or [])
    except Exception as exc:
        summary["errors"].append(f"load_selection: {exc}")
        selected_ids = set()
    if selected_ids:
        pages = [
            p for p in pages
            if isinstance(p, dict) and p.get("id") in selected_ids
        ]
        if not pages:
            summary["status"] = "no_selected_pages_match"
            return summary
        summary["selected_page_ids"] = sorted(selected_ids)
    summary["pages_seen"] = [pg.get("name") for pg in pages if isinstance(pg, dict)]

    import requests

    for pg in pages:
        if not isinstance(pg, dict):
            continue
        page_id = pg.get("id")
        page_name = pg.get("name")
        page_token = pg.get("access_token")
        if not page_id or not page_token:
            continue

        # 2) List posts on this page (direct Graph API — Composio's tool only
        # passes the user token, but the new Pages experience requires the
        # page-specific access_token returned in step 1)
        try:
            r = requests.get(
                f"https://graph.facebook.com/v20.0/{page_id}/posts",
                params={
                    "access_token": page_token,
                    "limit": min(max_posts, 100),
                    # summary=true on edges returns total_count without enumerating items
                    "fields": (
                        "id,message,created_time,permalink_url,attachments,full_picture,"
                        "likes.summary(true).limit(0),comments.summary(true).limit(0),"
                        "reactions.summary(true).limit(0),shares"
                    ),
                },
                timeout=45,
            )
            posts = (r.json() or {}).get("data") or []
        except Exception as exc:
            summary["errors"].append(f"page_posts[{page_name}]: {exc}")
            continue

        for p in posts:
            if not isinstance(p, dict):
                continue
            created_time = p.get("created_time")
            if not _within(created_time, cutoff):
                continue
            post_id = p.get("id")
            if not post_id:
                continue
            # 3) Engagement counts pulled directly from post fields
            #    (likes/comments/reactions use summary=true&limit=0 to return
            #    total_count without enumerating items; shares is a {count} dict)
            metrics_payload: dict[str, Any] = {"_page": page_name}

            def _summary_total(field: Any) -> int | None:
                if not isinstance(field, dict):
                    return None
                s = field.get("summary")
                if isinstance(s, dict):
                    return s.get("total_count")
                return None

            like_count = _summary_total(p.get("likes"))
            comment_count = _summary_total(p.get("comments"))
            reaction_count = _summary_total(p.get("reactions"))
            shares = p.get("shares")
            share_count = shares.get("count") if isinstance(shares, dict) else None

            if like_count is not None:
                metrics_payload["like_count"] = like_count
            if comment_count is not None:
                metrics_payload["comment_count"] = comment_count
            if reaction_count is not None:
                metrics_payload["reaction_count"] = reaction_count
            if share_count is not None:
                metrics_payload["share_count"] = share_count

            engagement_total = sum(
                v for v in (reaction_count or like_count, comment_count, share_count)
                if isinstance(v, int)
            )
            if engagement_total:
                metrics_payload["engagement_total"] = engagement_total

            # 4) Try per-post insights for impressions/reach/video views
            #    (often returns empty for Pages without elevated permissions —
            #    we tolerate failure and rely on engagement counts above)
            try:
                ir = requests.get(
                    f"https://graph.facebook.com/v20.0/{post_id}/insights",
                    params={"access_token": page_token, "metric": ",".join(POST_METRICS)},
                    timeout=20,
                )
                idata = (ir.json() or {}).get("data") or []
                for entry in idata:
                    if isinstance(entry, dict) and entry.get("name"):
                        vals = entry.get("values") or []
                        metrics_payload[entry["name"]] = (
                            vals[0].get("value") if vals and isinstance(vals[0], dict) else None
                        )
                impressions = metrics_payload.get("post_impressions") or metrics_payload.get("post_impressions_unique")
                if isinstance(impressions, int) and impressions > 0 and engagement_total:
                    metrics_payload["engagement_rate"] = round(engagement_total / impressions, 4)
                summary["posts_with_insights"] += 1
            except Exception as exc:
                metrics_payload["_insights_error"] = str(exc)

            append_metric(
                platform="facebook",
                post_id=str(post_id),
                posted_at=created_time,
                media_type="POST",
                permalink=p.get("permalink_url"),
                caption=p.get("message"),
                metrics=metrics_payload,
                raw={"post": p, "page": {"id": page_id, "name": page_name}},
                include_raw=True,
            )
            summary["posts_seen"] += 1

        # 4) Page-level insights (direct Graph API w/ page token)
        try:
            pr = requests.get(
                f"https://graph.facebook.com/v20.0/{page_id}/insights",
                params={"access_token": page_token, "metric": ",".join(PAGE_METRICS), "period": "day"},
                timeout=20,
            )
            page_metrics: dict[str, Any] = {"_page": page_name}
            for entry in (pr.json() or {}).get("data") or []:
                if isinstance(entry, dict) and entry.get("name"):
                    page_metrics[entry["name"]] = entry.get("values")
            append_metric(
                platform="facebook",
                post_id=f"_account_{page_id}",
                posted_at=None,
                media_type="ACCOUNT",
                permalink=None,
                caption=None,
                metrics=page_metrics,
            )
        except Exception as exc:
            summary["errors"].append(f"page_insights[{page_name}]: {exc}")

    return summary


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
