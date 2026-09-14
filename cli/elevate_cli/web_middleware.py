"""FastAPI middleware registration for the Elevate dashboard."""

import logging
import time
from collections.abc import Callable
from typing import Any, Awaitable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def install_dashboard_middlewares(
    app: FastAPI,
    *,
    public_api_paths: frozenset,
    is_accepted_host: Callable[[str, str], bool],
    has_valid_session_token: Callable[[Request], bool],
    has_valid_run_token: Callable[[Request], bool],
    request_id_for_log: Callable[[Request], str],
    session_id_for_log: Callable[[Request], str],
    request_id_header_name: str,
    log: logging.Logger,
) -> None:
    @app.middleware("http")
    async def host_header_middleware(request: Request, call_next: Callable[[Request], Awaitable[Any]]):
        """Reject requests whose Host header doesn't match the bound interface."""
        bound_host = getattr(app.state, "bound_host", None)
        if bound_host:
            host_header = request.headers.get("host", "")
            if not is_accepted_host(host_header, bound_host):
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            "Invalid Host header. Dashboard requests must use "
                            "the hostname the server was bound to."
                        ),
                    },
                )
        return await call_next(request)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Callable[[Request], Awaitable[Any]]):
        """Require the session token on all /api/ routes except the public list."""
        path = request.url.path
        if path.startswith("/api/") and path not in public_api_paths:
            if not (has_valid_session_token(request) or has_valid_run_token(request)):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized"},
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Any]]):
        request_id = request_id_for_log(request)
        session_id = session_id_for_log(request)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            log.exception(
                "request failed request_id=%s session_id=%s method=%s path=%s elapsed_ms=%.1f",
                request_id,
                session_id,
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[request_id_header_name] = request_id
        log.info(
            "request complete request_id=%s session_id=%s method=%s path=%s status=%s elapsed_ms=%.1f",
            request_id,
            session_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
