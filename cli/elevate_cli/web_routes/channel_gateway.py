"""Gateway control routes for the channel setup surface."""

import logging
import subprocess
from typing import Callable

from fastapi import APIRouter, HTTPException

SpawnElevateAction = Callable[[list[str], str], subprocess.Popen]


def register_gateway_routes(
    router: APIRouter,
    *,
    log: logging.Logger,
    spawn_elevate_action: SpawnElevateAction,
) -> None:
    @router.post("/api/gateway/restart")
    async def restart_gateway():
        try:
            proc = spawn_elevate_action(["gateway", "restart"], "gateway-restart")
        except Exception as exc:
            log.exception("Failed to spawn gateway restart")
            raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")
        return {
            "ok": True,
            "pid": proc.pid,
            "name": "gateway-restart",
        }

    @router.post("/api/gateway/start")
    async def start_gateway_action():
        try:
            proc = spawn_elevate_action(["gateway", "run", "--replace"], "gateway-start")
        except Exception as exc:
            log.exception("Failed to spawn gateway start")
            raise HTTPException(status_code=500, detail=f"Failed to start gateway: {exc}")
        return {
            "ok": True,
            "pid": proc.pid,
            "name": "gateway-start",
        }
