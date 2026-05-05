"""Ayrshare REST client.

Direct wrapper for https://app.ayrshare.com/api — Ayrshare auth is a single
API key per workspace, so we don't need Composio's OAuth dance for it.
Composio's own Ayrshare toolkit only exposes 3 actions (history, schedule,
delete) and is missing the actual `post` action, so we go direct.

Surface area:
- post(): create + publish a post to one or more platforms (immediate or scheduled)
- history(): list past posts with engagement metrics
- analytics_post(): per-post analytics (deep metrics on a specific post)
- analytics_user(): per-platform account-level analytics
- delete(): delete a posted/scheduled post
- profiles(): list connected social profiles (which platforms have OAuth tokens stored in Ayrshare)

Returns the same `{ok, data, status}` envelope as composio_client.py so call
sites can handle errors uniformly.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from elevate_cli.config import load_env, save_env_value


AYRSHARE_BASE_URL = "https://app.ayrshare.com/api"
AYRSHARE_API_KEY_ENV = "AYRSHARE_API_KEY"
DEFAULT_TIMEOUT = 30.0


def _read_api_key() -> str:
    env_values = load_env()
    key = (env_values.get(AYRSHARE_API_KEY_ENV) or os.getenv(AYRSHARE_API_KEY_ENV) or "").strip()
    return key


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _err(message: str, status: int | None = None, raw: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if status is not None:
        payload["status"] = status
    if raw is not None:
        payload["raw"] = raw
    return payload


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict[str, Any]:
    api_key = _read_api_key()
    if not api_key:
        return _err("AYRSHARE_API_KEY is not configured", status=None)

    url = f"{AYRSHARE_BASE_URL.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.request(
                method,
                url,
                headers=_headers(api_key),
                params=params,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        return _err(f"Network error: {exc}")

    body: Any
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    if resp.status_code >= 400:
        msg = body.get("message") if isinstance(body, dict) else None
        return _err(msg or f"HTTP {resp.status_code}", status=resp.status_code, raw=body)

    return {"ok": True, "data": body, "status": resp.status_code}


def set_api_key(value: str) -> dict[str, Any]:
    cleaned = (value or "").strip()
    if not cleaned:
        return {"ok": False, "error": "Empty API key"}
    save_env_value(AYRSHARE_API_KEY_ENV, cleaned)
    return {"ok": True, "configured": True}


def clear_api_key() -> dict[str, Any]:
    save_env_value(AYRSHARE_API_KEY_ENV, "")
    return {"ok": True, "configured": False}


def get_status() -> dict[str, Any]:
    """Cheap status probe. Returns whether a key exists + whether it works."""
    api_key = _read_api_key()
    if not api_key:
        return {
            "configured": False,
            "hasKey": False,
            "valid": False,
            "baseUrl": AYRSHARE_BASE_URL,
        }
    probe = _request("GET", "/user")
    if probe.get("ok"):
        data = probe.get("data") or {}
        return {
            "configured": True,
            "hasKey": True,
            "valid": True,
            "baseUrl": AYRSHARE_BASE_URL,
            "active_social_accounts": data.get("activeSocialAccounts") or [],
            "display_names": data.get("displayNames") or [],
            "monthly_post_count": data.get("monthlyPostCount"),
            "monthly_post_quota": data.get("monthlyPostQuota"),
        }
    return {
        "configured": True,
        "hasKey": True,
        "valid": False,
        "baseUrl": AYRSHARE_BASE_URL,
        "error": probe.get("error"),
        "status": probe.get("status"),
    }


def profiles() -> dict[str, Any]:
    """List connected social profiles (which platforms have OAuth tokens stored in Ayrshare)."""
    return _request("GET", "/user")


def post(
    *,
    post_text: str,
    platforms: list[str],
    media_urls: Optional[list[str]] = None,
    scheduled_at: Optional[str] = None,
    profile_key: Optional[str] = None,
    platform_options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create a post.

    Args:
      post_text: caption / body
      platforms: list of platform slugs (instagram, tiktok, youtube, facebook, linkedin, twitter, etc.)
      media_urls: optional list of public image/video URLs
      scheduled_at: optional ISO-8601 UTC timestamp; if omitted, posts immediately
      profile_key: optional Ayrshare profile key for multi-profile accounts
      platform_options: optional per-platform overrides (e.g. {"instagram": {"reels": true}})
    """
    body: dict[str, Any] = {
        "post": post_text,
        "platforms": list(platforms or []),
    }
    if media_urls:
        body["mediaUrls"] = list(media_urls)
    if scheduled_at:
        body["scheduleDate"] = scheduled_at
    if profile_key:
        body["profileKey"] = profile_key
    if platform_options:
        body.update(platform_options)
    return _request("POST", "/post", json_body=body)


def history(
    *,
    last_records: int = 100,
    last_days: Optional[int] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """List past posts with engagement metrics.

    Args:
      last_records: how many to return (max 5000 per Ayrshare)
      last_days: filter to posts within last N days
      status: filter by status ("success", "scheduled", "error", "deleted")
    """
    params: dict[str, Any] = {"lastRecords": last_records}
    if last_days is not None:
        params["lastDays"] = last_days
    if status:
        params["status"] = status
    return _request("GET", "/history", params=params)


def analytics_post(post_id: str) -> dict[str, Any]:
    """Per-post analytics. `post_id` is Ayrshare's id from the post() response."""
    if not post_id:
        return _err("analytics_post: missing post_id")
    return _request("POST", "/analytics/post", json_body={"id": post_id})


def analytics_user(platforms: list[str]) -> dict[str, Any]:
    """Per-platform account-level analytics (followers, growth, profile views, etc)."""
    if not platforms:
        return _err("analytics_user: missing platforms")
    return _request("POST", "/analytics/social", json_body={"platforms": list(platforms)})


def delete_post(post_id: str) -> dict[str, Any]:
    """Delete a posted or scheduled post."""
    if not post_id:
        return _err("delete_post: missing post_id")
    return _request("DELETE", "/post", json_body={"id": post_id})


def list_scheduled() -> dict[str, Any]:
    """List currently scheduled (not yet posted) posts."""
    return _request("GET", "/post", params={"status": "scheduled"})
