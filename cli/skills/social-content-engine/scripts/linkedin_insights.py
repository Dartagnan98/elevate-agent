"""LinkedIn metric fetcher (Composio).

LinkedIn's organic API surface is org-page-centric. The current Composio
toolkit only exposes:
- LINKEDIN_GET_SHARE_STATS    — share-level statistics for an organization
- LINKEDIN_GET_ORG_PAGE_STATS — page views, custom button clicks
- LINKEDIN_GET_NETWORK_SIZE   — follower count
- LINKEDIN_GET_POST_CONTENT   — single post content (no metrics)
- LINKEDIN_LIST_REACTIONS     — reactions per post

For real estate this is mostly useful when an agent has an organization
page. Personal-profile post listing is not exposed.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  re-exec under the bundled app Python if launched by a bare python3

import argparse
import sys
from typing import Any

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from _metrics_io import append_metric, find_composio_account


TOOLKIT_SLUG = "linkedin"
SLUG_SHARE_STATS = "LINKEDIN_GET_SHARE_STATS"
SLUG_ORG_STATS = "LINKEDIN_GET_ORG_PAGE_STATS"
SLUG_NETWORK = "LINKEDIN_GET_NETWORK_SIZE"


def fetch(*, lookback_days: int = 30, max_posts: int = 200) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "platform": "linkedin",
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

    org_urn = (account.get("metadata") or {}).get("organization_urn") or _os.environ.get(
        "LINKEDIN_ORG_URN"
    )

    if not org_urn:
        summary["status"] = "no_organization_urn"
        summary["errors"].append(
            "LinkedIn fetcher needs an organization URN. Set LINKEDIN_ORG_URN or store on connected account metadata."
        )
        return summary

    # 1) Org-level page stats
    org_resp = composio_client.execute_tool(
        SLUG_ORG_STATS,
        account_id,
        {"organization_urn": org_urn, "time_granularity": "DAY"},
    )
    if org_resp.get("ok"):
        ob = org_resp.get("data") or {}
        ord_ = ob.get("response_data") if isinstance(ob, dict) else None
        elements = (ord_ or {}).get("elements") or ob.get("elements") or []
        page_metrics: dict[str, Any] = {"page_views_by_day": []}
        for el in elements:
            if isinstance(el, dict):
                page_metrics["page_views_by_day"].append(
                    {
                        "time_range": el.get("timeRange"),
                        "total_page_views": ((el.get("totalPageStatistics") or {}).get("views") or {}).get("allPageViews", {}).get("pageViews"),
                    }
                )
        append_metric(
            platform="linkedin",
            post_id=f"_account_{account_id}",
            posted_at=None,
            media_type="ACCOUNT",
            permalink=None,
            caption=None,
            metrics=page_metrics,
        )
    else:
        summary["errors"].append(f"org_stats: {org_resp.get('error')}")

    # 2) Network size (follower count)
    net_resp = composio_client.execute_tool(SLUG_NETWORK, account_id, {"organization_urn": org_urn})
    if net_resp.get("ok"):
        nb = net_resp.get("data") or {}
        nrd = nb.get("response_data") if isinstance(nb, dict) else None
        first_follower_count = (
            (nrd or {}).get("firstDegreeSize") or nb.get("firstDegreeSize")
        )
        append_metric(
            platform="linkedin",
            post_id=f"_followers_{account_id}",
            posted_at=None,
            media_type="ACCOUNT",
            permalink=None,
            caption=None,
            metrics={"follower_count": first_follower_count},
        )

    # 3) Share stats — per-post metrics for the org's recent shares
    share_resp = composio_client.execute_tool(
        SLUG_SHARE_STATS,
        account_id,
        {"organization_urn": org_urn, "count": min(max_posts, 50)},
    )
    if share_resp.get("ok"):
        sb = share_resp.get("data") or {}
        srd = sb.get("response_data") if isinstance(sb, dict) else None
        elements = (srd or {}).get("elements") or sb.get("elements") or []
        for el in elements:
            if not isinstance(el, dict):
                continue
            share_urn = el.get("share") or el.get("shareUrn") or el.get("ugcPost")
            stats = el.get("totalShareStatistics") or el
            metrics = {
                "impression_count": stats.get("impressionCount"),
                "click_count": stats.get("clickCount"),
                "like_count": stats.get("likeCount"),
                "comment_count": stats.get("commentCount"),
                "share_count": stats.get("shareCount"),
                "engagement": stats.get("engagement"),
                "unique_impression_count": stats.get("uniqueImpressionsCount"),
            }
            append_metric(
                platform="linkedin",
                post_id=str(share_urn or f"unknown_{summary['posts_seen']}"),
                posted_at=None,
                media_type="POST",
                permalink=None,
                caption=None,
                metrics=metrics,
            )
            summary["posts_seen"] += 1
            summary["posts_with_insights"] += 1
    else:
        summary["errors"].append(f"share_stats: {share_resp.get('error')}")

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
