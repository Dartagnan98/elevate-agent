"""Source connector, source inbox, and sender routes for the dashboard."""

import logging

from fastapi import APIRouter

from elevate_cli.web_routes.source_apple_messages import register_apple_messages_routes
from elevate_cli.web_routes.source_connector_management import register_source_connector_management_routes
from elevate_cli.web_routes.source_inbox import register_source_inbox_routes
from elevate_cli.web_routes.source_inbox_sends import register_source_inbox_send_routes
from elevate_cli.web_routes.source_sender import register_sender_routes


def create_source_connectors_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build routes for source connectors, source inbox, and sender controls."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    # ---------------------------------------------------------------------------
    # Real-estate source connectors and integration settings
    # ---------------------------------------------------------------------------

    register_source_connector_management_routes(router, log=_log)
    register_source_inbox_routes(router, log=_log)
    register_apple_messages_routes(router, log=_log)
    register_source_inbox_send_routes(router, log=_log)
    register_sender_routes(router, log=_log)

    return router
