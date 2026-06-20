"""Composio integration routes."""

import asyncio
import logging
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class ComposioKeyBody(BaseModel):
    apiKey: str


class ComposioConnectBody(BaseModel):
    toolkitSlug: str
    redirectUrl: Optional[str] = None
    userId: Optional[str] = None


class ComposioFacebookSelectionBody(BaseModel):
    pageIds: list[str]


class ComposioCustomAuthBody(BaseModel):
    toolkitSlug: str
    credentials: dict
    authScheme: Optional[str] = None
    redirectUrl: Optional[str] = None
    userId: Optional[str] = None


_COMPOSIO_SWR: dict[str, tuple[float, Any]] = {}
_COMPOSIO_SWR_LOCK = threading.Lock()
_COMPOSIO_SWR_REFRESHING: set[str] = set()
_COMPOSIO_STATUS_TTL_SEC = 60.0
_COMPOSIO_CONNECTIONS_TTL_SEC = 30.0
_COMPOSIO_TOOLKITS_CACHE: dict[str, tuple[float, Any]] = {}
_COMPOSIO_TOOLKITS_TTL_SEC = 300.0


def _composio_refresh_async(key: str, fetch, log: logging.Logger) -> None:
    """Refresh one SWR entry on a background thread, deduped per key."""
    with _COMPOSIO_SWR_LOCK:
        if key in _COMPOSIO_SWR_REFRESHING:
            return
        _COMPOSIO_SWR_REFRESHING.add(key)

    def _run() -> None:
        try:
            value = fetch()
            with _COMPOSIO_SWR_LOCK:
                _COMPOSIO_SWR[key] = (time.monotonic(), value)
        except Exception:
            log.debug("Composio SWR refresh failed for %s", key, exc_info=True)
        finally:
            with _COMPOSIO_SWR_LOCK:
                _COMPOSIO_SWR_REFRESHING.discard(key)

    threading.Thread(
        target=_run, daemon=True, name=f"composio-swr-{key}"
    ).start()


def _composio_cached(key: str, ttl: float, fetch, log: logging.Logger):
    """Return a cached Composio read and revalidate stale values in the background."""
    now = time.monotonic()
    with _COMPOSIO_SWR_LOCK:
        entry = _COMPOSIO_SWR.get(key)
    if entry is not None:
        ts, value = entry
        if (now - ts) >= ttl:
            _composio_refresh_async(key, fetch, log)
        return value
    value = fetch()
    with _COMPOSIO_SWR_LOCK:
        _COMPOSIO_SWR[key] = (time.monotonic(), value)
    return value


def _composio_cache_invalidate() -> None:
    """Drop cached Composio reads after mutations."""
    with _COMPOSIO_SWR_LOCK:
        _COMPOSIO_SWR.clear()


def _prewarm_composio_toolkits_in_background(log: logging.Logger) -> None:
    """Fire-and-forget background fetch of the full toolkit catalog."""

    def _warm() -> None:
        try:
            from elevate_cli import composio_client

            with _COMPOSIO_SWR_LOCK:
                has_connections = "connections" in _COMPOSIO_SWR
            if not has_connections:
                _composio_refresh_async(
                    "connections", composio_client.list_connected_accounts, log
                )

            cache_key = "all::::100"
            entry = _COMPOSIO_TOOLKITS_CACHE.get(cache_key)
            now = time.monotonic()
            if entry and (now - entry[0]) < _COMPOSIO_TOOLKITS_TTL_SEC:
                return
            result = composio_client.list_all_toolkits(page_size=100)
            _COMPOSIO_TOOLKITS_CACHE[cache_key] = (now, result)
        except Exception:
            log.debug("Composio pre-warm failed", exc_info=True)

    threading.Thread(target=_warm, daemon=True, name="composio-prewarm").start()


def create_composio_router(
    *,
    prewarm_composio_toolkits_func=_prewarm_composio_toolkits_in_background,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/composio/status")
    async def composio_status():
        try:
            from elevate_cli import composio_client

            result = await asyncio.to_thread(
                _composio_cached,
                "status",
                _COMPOSIO_STATUS_TTL_SEC,
                composio_client.get_status,
                _log,
            )
            if isinstance(result, dict) and result.get("valid"):
                prewarm_composio_toolkits_func(_log)
            return result
        except Exception as exc:
            _log.exception("GET /api/composio/status failed")
            raise HTTPException(status_code=500, detail=f"Composio status failed: {exc}")

    @router.post("/api/composio/key")
    async def composio_set_key(body: ComposioKeyBody):
        try:
            from elevate_cli import composio_client

            result = composio_client.set_api_key(body.apiKey)
            if not result.get("ok"):
                raise HTTPException(status_code=400, detail=result.get("error", "Invalid key"))
            _composio_cache_invalidate()
            return composio_client.get_status()
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/composio/key failed")
            raise HTTPException(status_code=500, detail=f"Set Composio key failed: {exc}")

    @router.delete("/api/composio/key")
    async def composio_clear_key():
        try:
            from elevate_cli import composio_client

            composio_client.clear_api_key()
            _composio_cache_invalidate()
            return composio_client.get_status()
        except Exception as exc:
            _log.exception("DELETE /api/composio/key failed")
            raise HTTPException(status_code=500, detail=f"Clear Composio key failed: {exc}")

    @router.get("/api/composio/connections")
    async def composio_connections(fresh: bool = False):
        try:
            from elevate_cli import composio_client

            if fresh:
                result = await asyncio.to_thread(composio_client.list_connected_accounts)
                with _COMPOSIO_SWR_LOCK:
                    _COMPOSIO_SWR["connections"] = (time.monotonic(), result)
                return result
            return await asyncio.to_thread(
                _composio_cached,
                "connections",
                _COMPOSIO_CONNECTIONS_TTL_SEC,
                composio_client.list_connected_accounts,
                _log,
            )
        except Exception as exc:
            _log.exception("GET /api/composio/connections failed")
            raise HTTPException(status_code=500, detail=f"List Composio connections failed: {exc}")

    @router.get("/api/composio/connections/all")
    async def composio_connections_all(
        toolkit: Optional[str] = None,
        page_size: int = 100,
        max_pages: int = 50,
    ):
        try:
            from elevate_cli import composio_client

            return composio_client.list_all_connected_accounts(
                toolkit=toolkit, page_size=page_size, max_pages=max_pages,
            )
        except Exception as exc:
            _log.exception("GET /api/composio/connections/all failed")
            raise HTTPException(status_code=500, detail=f"List all Composio connections failed: {exc}")

    @router.get("/api/composio/capabilities")
    async def composio_capabilities(toolkit: Optional[str] = None):
        try:
            from elevate_cli import composio_client

            if toolkit:
                return composio_client.capability(toolkit)
            return composio_client.load_capability_matrix()
        except Exception as exc:
            _log.exception("GET /api/composio/capabilities failed")
            raise HTTPException(status_code=500, detail=f"Composio capabilities failed: {exc}")

    @router.get("/api/composio/toolkits")
    async def composio_toolkits(
        category: Optional[str] = None,
        all: bool = True,
        limit: int = 100,
        cursor: Optional[str] = None,
        search: Optional[str] = None,
    ):
        try:
            from elevate_cli import composio_client

            if search:
                return composio_client.list_toolkits(
                    category=category, limit=limit, search=search
                )
            if cursor or not all:
                return composio_client.list_toolkits(
                    category=category, limit=limit, cursor=cursor
                )

            cache_key = f"all::{category or ''}::{limit}"
            entry = _COMPOSIO_TOOLKITS_CACHE.get(cache_key)
            now = time.monotonic()
            if entry and (now - entry[0]) < _COMPOSIO_TOOLKITS_TTL_SEC:
                return entry[1]
            result = composio_client.list_all_toolkits(category=category, page_size=limit)
            _COMPOSIO_TOOLKITS_CACHE[cache_key] = (now, result)
            return result
        except Exception as exc:
            _log.exception("GET /api/composio/toolkits failed")
            raise HTTPException(status_code=500, detail=f"List Composio toolkits failed: {exc}")

    @router.post("/api/composio/connect")
    async def composio_connect(body: ComposioConnectBody):
        try:
            from elevate_cli import composio_client

            return composio_client.initiate_connection(
                body.toolkitSlug,
                redirect_url=body.redirectUrl,
                user_id=body.userId,
            )
        except Exception as exc:
            _log.exception("POST /api/composio/connect failed")
            raise HTTPException(status_code=500, detail=f"Composio connect failed: {exc}")

    @router.get("/api/composio/toolkits/{slug}")
    async def composio_toolkit_details(slug: str):
        try:
            from elevate_cli import composio_client

            return composio_client.get_toolkit_details(slug)
        except Exception as exc:
            _log.exception("GET /api/composio/toolkits/{slug} failed")
            raise HTTPException(status_code=500, detail=f"Toolkit details failed: {exc}")

    @router.post("/api/composio/auth-configs/custom")
    async def composio_create_custom_auth(body: ComposioCustomAuthBody):
        try:
            from elevate_cli import composio_client

            created = composio_client.create_custom_auth_config(
                body.toolkitSlug,
                body.credentials or {},
                auth_scheme=body.authScheme,
            )
            if not created.get("ok"):
                return created
            data = created.get("data") or {}
            ac = data.get("auth_config") if isinstance(data, dict) else None
            ac_id = (ac or {}).get("id") if isinstance(ac, dict) else None
            if not ac_id:
                return {"ok": False, "error": "auth_config created but no id returned", "raw": created}
            link = composio_client.initiate_connection(
                body.toolkitSlug,
                redirect_url=body.redirectUrl,
                user_id=body.userId,
                auth_config_id=ac_id,
            )
            if isinstance(link, dict) and isinstance(link.get("data"), dict):
                link["data"].setdefault("auth_config_id", ac_id)
                link["data"].setdefault("auth_config_created", True)
            return link
        except Exception as exc:
            _log.exception("POST /api/composio/auth-configs/custom failed")
            raise HTTPException(status_code=500, detail=f"Custom auth config failed: {exc}")

    @router.delete("/api/composio/connections/{account_id}")
    async def composio_delete_connection(account_id: str):
        try:
            from elevate_cli import composio_client

            result = composio_client.delete_connected_account(account_id)
            _composio_cache_invalidate()
            return result
        except Exception as exc:
            _log.exception("DELETE /api/composio/connections failed")
            raise HTTPException(status_code=500, detail=f"Delete Composio connection failed: {exc}")

    @router.get("/api/composio/facebook/pages")
    async def composio_facebook_pages():
        try:
            from elevate_cli import composio_inbound

            return composio_inbound.list_facebook_pages_for_picker()
        except Exception as exc:
            _log.exception("GET /api/composio/facebook/pages failed")
            raise HTTPException(status_code=500, detail=f"Composio FB pages failed: {exc}")

    @router.put("/api/composio/facebook/pages")
    async def composio_facebook_set_pages(body: ComposioFacebookSelectionBody):
        try:
            from elevate_cli import composio_inbound

            return composio_inbound.set_facebook_page_selection(body.pageIds or [])
        except Exception as exc:
            _log.exception("PUT /api/composio/facebook/pages failed")
            raise HTTPException(status_code=500, detail=f"Composio FB selection save failed: {exc}")

    @router.post("/api/composio/inbound/pull")
    async def composio_inbound_pull():
        try:
            from elevate_cli import composio_inbound

            return composio_inbound.pull_all_supported()
        except Exception as exc:
            _log.exception("POST /api/composio/inbound/pull failed")
            raise HTTPException(status_code=500, detail=f"Composio inbound pull failed: {exc}")

    return router
