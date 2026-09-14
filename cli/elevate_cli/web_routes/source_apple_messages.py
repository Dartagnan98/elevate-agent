"""Apple Messages source-inbox routes."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class AppleMessagesDirections(BaseModel):
    inbound: bool | None = None
    outbound: bool | None = None


def register_apple_messages_routes(router: APIRouter, *, log: logging.Logger) -> None:
    @router.get("/api/source-inbox/apple-messages/directions")
    async def get_apple_messages_directions_route():
        try:
            from elevate_cli.source_connectors import get_apple_messages_directions

            return get_apple_messages_directions(None)
        except Exception as exc:
            log.exception("GET apple-messages/directions failed")
            raise HTTPException(status_code=500, detail=f"Failed to read directions: {exc}")

    @router.post("/api/source-inbox/apple-messages/directions")
    async def set_apple_messages_directions_route(body: AppleMessagesDirections):
        try:
            from elevate_cli.source_connectors import (
                initialize_apple_messages_source,
                set_apple_messages_directions,
            )

            result = set_apple_messages_directions(
                inbound=body.inbound, outbound=body.outbound
            )
            # Re-run init so status.json (and the banner) reflect the new inbound
            # state immediately: turning inbound off writes a non-blocked paused
            # status; turning it on re-checks chat.db access. Best-effort.
            try:
                initialize_apple_messages_source()
            except Exception:
                log.warning("apple-messages re-init after toggle failed", exc_info=True)
            return result
        except Exception as exc:
            log.exception("POST apple-messages/directions failed")
            raise HTTPException(status_code=500, detail=f"Failed to set directions: {exc}")
