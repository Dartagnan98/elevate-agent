from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable


_CLOUD_SKILL_SYNC_INTERVAL_S = int(os.environ.get("ELEVATE_CLOUD_SKILL_SYNC_INTERVAL_S", "3600"))


def _cloud_skill_sync_once(reason: str, *, log: logging.Logger) -> None:
    try:
        from elevate_cli import cloud_skills
        from elevate_cli import license as lic_mod
    except Exception as exc:
        log.debug("cloud-skill sync (%s): import failed: %s", reason, exc)
        return

    lic = lic_mod.load()
    if not lic:
        log.debug("cloud-skill sync (%s): no license, skipping", reason)
        return

    try:
        if lic.is_expired():
            lic = lic_mod.refresh(lic)
    except Exception as exc:
        log.info("cloud-skill sync (%s): license refresh failed: %s", reason, exc)
        return

    try:
        result = cloud_skills.sync_all()
    except Exception as exc:
        log.info("cloud-skill sync (%s): sync failed: %s", reason, exc)
        return

    log.info(
        "cloud-skill sync (%s): %d skills, %d removed, %d errors",
        reason,
        result.get("skill_count", 0),
        len(result.get("removed", []) or []),
        len(result.get("errors", []) or []),
    )


async def _cloud_skill_heartbeat(
    *,
    interval_s: int = _CLOUD_SKILL_SYNC_INTERVAL_S,
    sync_once: Callable[[str], None],
) -> None:
    while True:
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            return
        await asyncio.get_running_loop().run_in_executor(None, sync_once, "heartbeat")


async def kickoff_cloud_skill_sync(
    application,
    *,
    sync_once: Callable[[str], None],
    heartbeat: Callable[[], Awaitable[None]],
) -> None:
    loop = asyncio.get_running_loop()
    # Run the first sync off the event loop so a slow network doesn't delay
    # the gateway accepting connections.
    loop.run_in_executor(None, sync_once, "startup")
    application.state.cloud_skill_heartbeat_task = loop.create_task(heartbeat())


async def stop_cloud_skill_heartbeat(application) -> None:
    task = getattr(application.state, "cloud_skill_heartbeat_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def install_cloud_skill_lifecycle(
    application,
    *,
    log: logging.Logger,
    interval_s: int = _CLOUD_SKILL_SYNC_INTERVAL_S,
) -> None:
    def sync_once(reason: str) -> None:
        _cloud_skill_sync_once(reason, log=log)

    async def heartbeat() -> None:
        await _cloud_skill_heartbeat(interval_s=interval_s, sync_once=sync_once)

    @application.on_event("startup")
    async def _kickoff_cloud_skill_sync() -> None:
        await kickoff_cloud_skill_sync(
            application,
            sync_once=sync_once,
            heartbeat=heartbeat,
        )

    @application.on_event("shutdown")
    async def _stop_cloud_skill_heartbeat() -> None:
        await stop_cloud_skill_heartbeat(application)
