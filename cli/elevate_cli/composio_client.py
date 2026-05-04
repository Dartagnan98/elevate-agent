"""Composio v3 HTTP client.

Wraps a small subset of https://backend.composio.dev for the /leads connector
flow: status check, list connected accounts, list toolkits (app catalog),
initiate auth. Always returns plain dict / list payloads. Network and 4xx/5xx
failures surface as a structured `{"ok": False, "error": ..., "status": ...}`
so the UI can render an empty / error state instead of crashing.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from elevate_cli.config import load_env, save_env_value


COMPOSIO_BASE_URL = "https://backend.composio.dev"
COMPOSIO_API_KEY_ENV = "COMPOSIO_API_KEY"
DEFAULT_TIMEOUT = 15.0


def _read_api_key() -> str:
    env_values = load_env()
    key = (env_values.get(COMPOSIO_API_KEY_ENV) or os.getenv(COMPOSIO_API_KEY_ENV) or "").strip()
    return key


def _headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }


def _err(message: str, status: int | None = None, raw: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if status is not None:
        payload["status"] = status
    if raw is not None:
        payload["raw"] = raw
    return payload


def _request(method: str, path: str, *, params: dict | None = None, json_body: dict | None = None) -> dict[str, Any]:
    api_key = _read_api_key()
    if not api_key:
        return _err("COMPOSIO_API_KEY is not configured", status=None)

    url = f"{COMPOSIO_BASE_URL.rstrip('/')}{path}"
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
    save_env_value(COMPOSIO_API_KEY_ENV, cleaned)
    return {"ok": True, "configured": True}


def clear_api_key() -> dict[str, Any]:
    save_env_value(COMPOSIO_API_KEY_ENV, "")
    return {"ok": True, "configured": False}


def get_status() -> dict[str, Any]:
    """Cheap status probe. Returns whether a key exists + whether it works."""
    api_key = _read_api_key()
    if not api_key:
        return {
            "configured": False,
            "hasKey": False,
            "valid": False,
            "baseUrl": COMPOSIO_BASE_URL,
        }
    probe = _request("GET", "/api/v3/connected_accounts", params={"limit": 1})
    if probe.get("ok"):
        return {
            "configured": True,
            "hasKey": True,
            "valid": True,
            "baseUrl": COMPOSIO_BASE_URL,
        }
    return {
        "configured": True,
        "hasKey": True,
        "valid": False,
        "baseUrl": COMPOSIO_BASE_URL,
        "error": probe.get("error"),
        "status": probe.get("status"),
    }


def list_connected_accounts(*, limit: int = 100, toolkit: Optional[str] = None) -> dict[str, Any]:
    """Single-page connected accounts. Use ``list_all_connected_accounts`` to paginate."""
    params: dict[str, Any] = {"limit": limit}
    if toolkit:
        params["toolkit_slugs"] = toolkit
    return _request("GET", "/api/v3/connected_accounts", params=params)


def list_all_connected_accounts(
    *,
    toolkit: Optional[str] = None,
    page_size: int = 100,
    max_pages: int = 50,
) -> dict[str, Any]:
    """Paginate connected_accounts until exhausted or ``max_pages`` reached.

    Composio v3 returns ``{items: [...], next_cursor: "..."}`` (or no cursor
    when there's nothing more). Phase 5a needs this because the single
    ``limit=100`` call truncates large multi-tenant orgs.

    Returns ``{ok, data: {items, page_count, truncated}}`` on success.
    """
    items: list[Any] = []
    cursor: Optional[str] = None
    pages = 0
    truncated = False

    while pages < max_pages:
        params: dict[str, Any] = {"limit": page_size}
        if toolkit:
            params["toolkit_slugs"] = toolkit
        if cursor:
            params["cursor"] = cursor

        resp = _request("GET", "/api/v3/connected_accounts", params=params)
        if not resp.get("ok"):
            return resp

        body = resp.get("data") or {}
        # Composio responses come back as either a list or {items: [...]}; tolerate both.
        page_items: list[Any] = []
        next_cursor: Optional[str] = None
        if isinstance(body, list):
            page_items = body
        elif isinstance(body, dict):
            page_items = list(body.get("items") or body.get("data") or [])
            next_cursor = body.get("next_cursor") or body.get("nextCursor")
        items.extend(page_items)
        pages += 1

        if not next_cursor or not page_items:
            break
        cursor = next_cursor
    else:
        truncated = True

    return {
        "ok": True,
        "data": {
            "items": items,
            "page_count": pages,
            "truncated": truncated,
        },
        "status": 200,
    }


def get_connected_account(account_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/v3/connected_accounts/{account_id}")


def execute_tool(
    slug: str,
    account_id: str,
    args: dict[str, Any],
    *,
    user_id: Optional[str] = None,
    custom_auth_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Execute a Composio tool call against a specific connected account.

    Composio v3 endpoint: ``POST /api/v3/tools/execute/{SLUG}`` with body
    ``{user_id, connected_account_id, arguments}``. The previous shape
    (slug-in-body to ``/api/v3/tools/execute``) returned 404 — it doesn't
    exist. ``user_id`` is required even when ``connected_account_id`` is
    present (Composio rejects with code 1811 otherwise).

    If ``user_id`` is omitted, we look it up off the connected_account
    record — a small extra round-trip but keeps the call site clean for
    callers that already have the account_id.
    """
    if not slug or not isinstance(slug, str):
        return _err("execute_tool: missing slug")
    if not account_id or not isinstance(account_id, str):
        return _err("execute_tool: missing connected_account_id")

    if not user_id:
        acct_resp = get_connected_account(account_id)
        if acct_resp.get("ok"):
            data = acct_resp.get("data") or {}
            if isinstance(data, dict):
                user_id = (
                    data.get("user_id")
                    or (data.get("data") or {}).get("user_id") if isinstance(data.get("data"), dict) else None
                ) or data.get("user_id")
    if not user_id:
        user_id = _get_or_create_user_id()

    body: dict[str, Any] = {
        "user_id": user_id,
        "connected_account_id": account_id.strip(),
        "arguments": dict(args or {}),
    }
    if custom_auth_params:
        body["custom_auth_params"] = custom_auth_params
    return _request("POST", f"/api/v3/tools/execute/{slug.strip()}", json_body=body)


def load_capability_matrix() -> dict[str, Any]:
    """Read the bundled per-toolkit send/inbound/read_only matrix.

    Source of truth for which Composio toolkits the channel picker is
    allowed to expose. Lives in ``composio_capabilities.json`` next to this
    module so the matrix versions with the code.
    """
    import json
    from pathlib import Path
    here = Path(__file__).resolve().parent
    path = here / "composio_capabilities.json"
    if not path.exists():
        return {"toolkits": {}, "version": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"toolkits": {}, "version": 0, "error": str(exc)}


def capability(toolkit_slug: str) -> dict[str, Any]:
    """Return capability info for a toolkit slug. Unknown -> unverified stub."""
    matrix = load_capability_matrix()
    entry = (matrix.get("toolkits") or {}).get(toolkit_slug)
    if not entry:
        return {
            "toolkit": toolkit_slug,
            "send": {"supported": False, "verification": "unknown"},
            "inbound": {"supported": False, "verification": "unknown"},
            "read_only": True,
        }
    return {"toolkit": toolkit_slug, **entry}


def list_toolkits(*, category: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if category:
        params["category"] = category
    return _request("GET", "/api/v3/toolkits", params=params)


def list_all_toolkits(
    *,
    category: Optional[str] = None,
    page_size: int = 100,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Paginate through every toolkit Composio exposes.

    The catalog UI in Elevate is the canonical surface for Composio
    connection management, so we need the full list — not just the first
    100. Walks ``next_cursor`` until exhausted or ``max_pages`` reached.
    """
    items: list[Any] = []
    cursor: Optional[str] = None
    pages = 0
    truncated = False

    while pages < max_pages:
        params: dict[str, Any] = {"limit": page_size}
        if category:
            params["category"] = category
        if cursor:
            params["cursor"] = cursor

        resp = _request("GET", "/api/v3/toolkits", params=params)
        if not resp.get("ok"):
            return resp

        body = resp.get("data") or {}
        page_items: list[Any] = []
        next_cursor: Optional[str] = None
        if isinstance(body, list):
            page_items = body
        elif isinstance(body, dict):
            page_items = list(body.get("items") or body.get("data") or [])
            next_cursor = body.get("next_cursor") or body.get("nextCursor")
        items.extend(page_items)
        pages += 1

        if not next_cursor or not page_items:
            break
        cursor = next_cursor
    else:
        truncated = True

    return {
        "ok": True,
        "data": {
            "items": items,
            "page_count": pages,
            "truncated": truncated,
        },
        "status": 200,
    }


def get_toolkit(slug: str) -> dict[str, Any]:
    return _request("GET", f"/api/v3/toolkits/{slug}")


COMPOSIO_USER_ID_ENV = "COMPOSIO_USER_ID"


def _get_or_create_user_id() -> str:
    """Stable per-install user id passed to Composio's link endpoint.

    Composio scopes connected accounts under a user_id from the calling
    application. For a single-tenant local Elevate install this just needs
    to be a stable opaque string — we generate a UUID once and persist it
    to ``~/.elevate/.env``. Roundtrips honour ``os.environ`` first so
    callers can override per process if needed.
    """
    env_values = load_env()
    existing = (env_values.get(COMPOSIO_USER_ID_ENV) or os.getenv(COMPOSIO_USER_ID_ENV) or "").strip()
    if existing:
        return existing
    import uuid as _uuid

    new_id = f"elevate-{_uuid.uuid4().hex[:12]}"
    save_env_value(COMPOSIO_USER_ID_ENV, new_id)
    return new_id


def list_auth_configs(toolkit_slug: Optional[str] = None, *, limit: int = 50) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if toolkit_slug:
        params["toolkit_slugs"] = toolkit_slug
    return _request("GET", "/api/v3/auth_configs", params=params)


def create_managed_auth_config(toolkit_slug: str) -> dict[str, Any]:
    """Create a Composio-managed auth config for a toolkit.

    "Managed" means Composio supplies the OAuth client — no client_id/secret
    needed from us. This is what makes the in-app "Connect" UX one-click:
    user has zero auth_configs in their project on first run; we POST one
    here, then immediately use the returned id to link a connected account.
    """
    body = {
        "toolkit": {"slug": toolkit_slug},
        "auth_config": {"type": "use_composio_managed_auth"},
    }
    return _request("POST", "/api/v3/auth_configs", json_body=body)


def _auth_config_toolkit_slug(item: dict[str, Any]) -> str:
    """Extract toolkit slug from an auth_config record across response shapes."""
    if not isinstance(item, dict):
        return ""
    tk = item.get("toolkit")
    if isinstance(tk, dict):
        slug = tk.get("slug") or tk.get("name") or tk.get("id") or ""
    elif isinstance(tk, str):
        slug = tk
    else:
        slug = item.get("toolkit_slug") or ""
    return str(slug).strip().lower()


def find_or_create_auth_config(toolkit_slug: str) -> dict[str, Any]:
    """Return ``{ok, auth_config_id, created}`` for the toolkit.

    Looks up an existing auth_config first (idempotent — clicking Connect
    twice on Gmail must not create two configs). Falls back to
    Composio-managed creation if none exist.

    Composio's ``toolkit_slugs`` query filter has been observed to return
    ALL auth_configs regardless of the filter, so we re-check each item's
    toolkit slug client-side. Without this guard, every Connect button
    resolves to whichever auth_config Composio returned first — typically
    the first one ever created in the project.
    """
    target = (toolkit_slug or "").strip().lower()
    listed = list_auth_configs(toolkit_slug=toolkit_slug, limit=50)
    if listed.get("ok"):
        body = listed.get("data") or {}
        items = body.get("items") if isinstance(body, dict) else None
        if items is None and isinstance(body, list):
            items = body
        for item in items or []:
            if _auth_config_toolkit_slug(item) != target:
                continue
            ac_id = (item or {}).get("id") or (item or {}).get("auth_config_id")
            if ac_id:
                return {"ok": True, "auth_config_id": ac_id, "created": False}

    created = create_managed_auth_config(toolkit_slug)
    if not created.get("ok"):
        return created
    data = created.get("data") or {}
    ac = data.get("auth_config") if isinstance(data, dict) else None
    ac_id = (ac or {}).get("id")
    if not ac_id:
        return _err("auth_config created but no id returned", raw=created)
    return {"ok": True, "auth_config_id": ac_id, "created": True}


def initiate_connection(
    toolkit_slug: str,
    *,
    redirect_url: Optional[str] = None,
    user_id: Optional[str] = None,
    auth_config_id: Optional[str] = None,
) -> dict[str, Any]:
    """Start the Composio account-link flow for a toolkit.

    Composio v3 requires both ``auth_config_id`` and ``user_id`` on the
    link call. We auto-resolve both so the UI can stay one-click:
      • ``auth_config_id`` defaults to the first existing config for the
        toolkit, or a freshly created Composio-managed one.
      • ``user_id`` defaults to a stable per-install id stored in .env.

    Returns ``{ok, data: {redirect_url, link_token, connected_account_id}}``
    on success — the UI opens ``redirect_url`` for the OAuth handshake.
    """
    if not auth_config_id:
        ac = find_or_create_auth_config(toolkit_slug)
        if not ac.get("ok"):
            return ac
        auth_config_id = ac["auth_config_id"]

    body: dict[str, Any] = {
        "auth_config_id": auth_config_id,
        "user_id": user_id or _get_or_create_user_id(),
    }
    if redirect_url:
        body["redirect_url"] = redirect_url

    resp = _request("POST", "/api/v3/connected_accounts/link", json_body=body)
    if resp.get("ok"):
        # Surface the auth_config_id so the UI can show "managed by Composio"
        # without having to round-trip GET /auth_configs again.
        data = resp.get("data") or {}
        if isinstance(data, dict):
            data.setdefault("auth_config_id", auth_config_id)
    return resp


def delete_connected_account(account_id: str) -> dict[str, Any]:
    return _request("DELETE", f"/api/v3/connected_accounts/{account_id}")
