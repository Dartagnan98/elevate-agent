"""Route registration for Agent Hub, admin flows, heartbeats, and chat."""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from elevate_cli.web_routes.agent_hub import create_agent_hub_router
from elevate_cli.web_routes.admin_contacts import create_admin_contacts_router
from elevate_cli.web_routes.admin_onboarding import create_admin_onboarding_router
from elevate_cli.web_routes.admin_pack import create_admin_pack_router
from elevate_cli.web_routes.admin_setup import create_admin_setup_router
from elevate_cli.web_routes.chat_websockets import create_chat_websocket_router
from elevate_cli.web_routes.heartbeats import create_heartbeats_router


def register_agent_admin_routes(
    app: FastAPI,
    *,
    web_actor: str,
    log: logging.Logger,
    require_admin_setup_ready_for_launch: Callable[[], None],
    fs_cache_get: Callable[..., Any],
    fs_cache_put: Callable[..., Any],
    fs_cache_invalidate: Callable[..., Any],
    embedded_chat_enabled: Callable[[], bool],
    session_token: Callable[[], str],
    bound_host: Callable[[], str | None],
    bound_port: Callable[[], int | None],
    license_signed_in: Callable[[], bool],
    resolve_chat_argv: Callable[..., tuple[list[str], str | None, dict | None]],
    pty_bridge_class: Callable[[], Any],
    pty_unavailable_error_class: Callable[[], type[BaseException]],
) -> None:
    app.include_router(
        create_agent_hub_router(
            require_admin_setup_ready_for_launch=require_admin_setup_ready_for_launch,
            log=log,
        )
    )

    app.include_router(create_admin_contacts_router(web_actor=web_actor, log=log))
    app.include_router(create_admin_setup_router(web_actor=web_actor, log=log))
    app.include_router(create_admin_onboarding_router(log=log))
    app.include_router(create_admin_pack_router(web_actor=web_actor, log=log))
    app.include_router(
        create_heartbeats_router(
            fs_cache_get=fs_cache_get,
            fs_cache_put=fs_cache_put,
            fs_cache_invalidate=fs_cache_invalidate,
            log=log,
        )
    )

    app.include_router(
        create_chat_websocket_router(
            embedded_chat_enabled=embedded_chat_enabled,
            session_token=session_token,
            bound_host=bound_host,
            bound_port=bound_port,
            license_signed_in=license_signed_in,
            resolve_chat_argv=resolve_chat_argv,
            pty_bridge_class=pty_bridge_class,
            pty_unavailable_error_class=pty_unavailable_error_class,
            log=log,
        )
    )
