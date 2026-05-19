"""Maintenance helpers for Elevate memory providers.

The holographic memory journal records completed turns cheaply during normal
use. These helpers promote pending journal entries into durable facts outside
of the session lifecycle, so long-running gateway sessions do not have to end
before memory gets organized.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from elevate_constants import get_elevate_home
from utils import atomic_json_write, is_truthy_value

logger = logging.getLogger(__name__)

STATE_FILENAME = "memory_daily_state.json"
MAINTENANCE_SESSION_ID = "memory-maintenance"


def _parse_int(value: Any, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _load_runtime_config(config: dict | None = None) -> dict:
    if isinstance(config, dict):
        return config
    try:
        from elevate_cli.config import load_config

        loaded = load_config()
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        logger.debug("Could not load memory maintenance config: %s", exc)
        return {}


def _plugin_config(config: dict) -> dict:
    plugins = config.get("plugins") if isinstance(config, dict) else {}
    if not isinstance(plugins, dict):
        return {}
    plugin_config = plugins.get("elevate-memory-store") or {}
    return plugin_config if isinstance(plugin_config, dict) else {}


def _memory_provider_name(config: dict) -> str:
    memory = config.get("memory") if isinstance(config, dict) else {}
    if not isinstance(memory, dict):
        return ""
    return str(memory.get("provider") or "").strip()


def _state_path(elevate_home: Path | None = None) -> Path:
    return (elevate_home or get_elevate_home()) / STATE_FILENAME


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _write_state(path: Path, state: dict) -> None:
    atomic_json_write(path, state, indent=2)


def _configured_now(config: dict, now: datetime | None = None) -> datetime:
    tz_name = str(config.get("timezone") or "").strip()
    tzinfo = None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            tzinfo = ZoneInfo(tz_name)
        except Exception:
            tzinfo = None

    if now is None:
        return datetime.now(tzinfo).astimezone() if tzinfo is None else datetime.now(tzinfo)
    if now.tzinfo is None:
        return now.astimezone() if tzinfo is None else now.replace(tzinfo=tzinfo)
    return now.astimezone(tzinfo) if tzinfo is not None else now.astimezone()


def _target_daily_run_day(config: dict, plugin_config: dict, now: datetime | None = None) -> str:
    local_now = _configured_now(config, now=now)
    hour = _parse_int(plugin_config.get("daily_organize_hour"), 23, minimum=0, maximum=23)
    minute = _parse_int(plugin_config.get("daily_organize_minute"), 55, minimum=0, maximum=59)
    scheduled_today = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now >= scheduled_today:
        return local_now.date().isoformat()
    return (local_now.date() - timedelta(days=1)).isoformat()


def organize_holographic_journal(
    *,
    config: dict | None = None,
    session_id: str | None = None,
    session_day: str | None = None,
    limit: int | None = None,
    drain: bool = False,
    max_batches: int | None = None,
) -> dict:
    """Promote pending holographic turn-journal rows into durable facts."""

    runtime_config = _load_runtime_config(config)
    if _memory_provider_name(runtime_config) != "holographic":
        return {
            "ran": False,
            "reason": "holographic memory is not the active provider",
            "processed": 0,
            "promoted": 0,
            "pending": 0,
            "total": 0,
            "batches": 0,
        }

    plugin_config = _plugin_config(runtime_config)
    batch_limit = _parse_int(
        limit if limit is not None else plugin_config.get("organize_batch_limit"),
        20,
        minimum=1,
    )
    batch_cap = _parse_int(
        max_batches if max_batches is not None else plugin_config.get("daily_organize_max_batches"),
        50,
        minimum=1,
    )

    from plugins.memory.holographic import HolographicMemoryProvider

    provider = HolographicMemoryProvider(config=plugin_config)
    provider.initialize(MAINTENANCE_SESSION_ID)
    try:
        from plugins.memory.holographic import activity as memory_activity

        memory_activity.record_event(
            "memory.daily_organize.started",
            message="daily journal organization",
            state="maintaining",
            step="maintain",
            status="running",
            data={"session_id": session_id, "session_day": session_day, "drain": drain},
        )
    except Exception:
        memory_activity = None  # type: ignore[assignment]
    processed = 0
    promoted = 0
    pending = 0
    total = 0
    batches = 0
    try:
        while True:
            result = provider._organize_journal(
                session_id=session_id,
                session_day=session_day,
                limit=batch_limit,
            )
            batches += 1
            processed += int(result.get("processed", 0) or 0)
            promoted += int(result.get("promoted", 0) or 0)
            pending = int(result.get("pending", 0) or 0)
            total = int(result.get("total", 0) or 0)

            if not drain:
                break
            if int(result.get("processed", 0) or 0) <= 0:
                break
            if pending <= 0:
                break
            if batches >= batch_cap:
                break
    finally:
        provider.shutdown()

    try:
        if memory_activity is not None:  # type: ignore[name-defined]
            memory_activity.record_event(
                "memory.daily_organize.complete",
                message=f"processed {processed}, promoted {promoted}",
                state="idle",
                step="maintain",
                status="done" if pending == 0 else "pending",
                data={"processed": processed, "promoted": promoted, "pending": pending, "batches": batches},
            )
    except Exception:
        pass

    return {
        "ran": True,
        "reason": "organized",
        "processed": processed,
        "promoted": promoted,
        "pending": pending,
        "total": total,
        "batches": batches,
        "batch_limit": batch_limit,
        "batch_cap": batch_cap,
        "drained": drain and pending == 0,
        "limited": drain and pending > 0 and batches >= batch_cap,
    }


def _prune_relation_graph(runtime_config: dict, plugin_config: dict) -> dict | None:
    """Run the bounded memory_relations prune + incremental vacuum.

    Helper for the daily path only. Returns the store result dict, or None if
    the prune could not be set up (never raises into the daily loop).
    """
    max_delete = _parse_int(
        plugin_config.get("relations_prune_max_delete"), 5000, minimum=0
    )
    if max_delete <= 0:
        return {"ran": False, "reason": "relations prune disabled (max_delete<=0)"}
    batch_size = _parse_int(
        plugin_config.get("relations_prune_batch_size"), 500, minimum=1
    )
    vacuum_pages = _parse_int(
        plugin_config.get("relations_incremental_vacuum_pages"), 2000, minimum=0
    )
    try:
        from plugins.memory.holographic import HolographicMemoryProvider
        from plugins.memory.holographic.store import DAILY_MAINTENANCE_TOKEN

        provider = HolographicMemoryProvider(config=plugin_config)
        provider.initialize(MAINTENANCE_SESSION_ID)
    except Exception as exc:
        logger.debug("Relation prune setup failed: %s", exc)
        return None
    try:
        store = getattr(provider, "_store", None)
        if store is None:
            return None
        return store.prune_and_compact_relations(
            daily_maintenance_token=DAILY_MAINTENANCE_TOKEN,
            max_delete=max_delete,
            batch_size=batch_size,
            incremental_vacuum_pages=vacuum_pages,
        )
    except Exception as exc:
        logger.debug("Relation prune failed: %s", exc)
        return {"ran": False, "reason": f"error: {exc}"}
    finally:
        try:
            provider.shutdown()
        except Exception:
            pass


def run_due_daily_memory_maintenance(
    *,
    config: dict | None = None,
    now: datetime | None = None,
    force: bool = False,
    elevate_home: Path | None = None,
) -> dict:
    """Run the daily holographic organizer if the configured day is due."""

    runtime_config = _load_runtime_config(config)
    if _memory_provider_name(runtime_config) != "holographic":
        return {"ran": False, "reason": "holographic memory is not the active provider"}

    plugin_config = _plugin_config(runtime_config)
    enabled = is_truthy_value(plugin_config.get("daily_organize_enabled"), default=True)
    if not enabled and not force:
        return {"ran": False, "reason": "daily memory organization is disabled"}

    state_file = _state_path(elevate_home)
    state = _read_state(state_file)
    target_day = _target_daily_run_day(runtime_config, plugin_config, now=now)
    if not force and state.get("last_daily_run_day") == target_day:
        return {
            "ran": False,
            "reason": f"daily memory organization already ran for {target_day}",
            "target_day": target_day,
            "state_path": str(state_file),
        }

    local_now = _configured_now(runtime_config, now=now)
    result = organize_holographic_journal(
        config=runtime_config,
        drain=True,
        max_batches=_parse_int(plugin_config.get("daily_organize_max_batches"), 50, minimum=1),
    )

    # Bounded relation-graph prune + incremental space reclaim. This is the
    # ONLY call site: run_due_daily_memory_maintenance is daily-gated (one run
    # per target_day) and is never on the per-turn or per-recall hot path. The
    # destructive store method additionally hard-guards on an opaque token that
    # no recall code holds, so it is structurally un-triggerable elsewhere.
    relations_result = _prune_relation_graph(runtime_config, plugin_config)
    if relations_result is not None:
        result["relations_maintenance"] = relations_result

    state.update(
        {
            "last_daily_run_day": target_day,
            "last_run_at": local_now.isoformat(),
            "last_result": result,
        }
    )
    _write_state(state_file, state)
    result.update(
        {
            "target_day": target_day,
            "state_path": str(state_file),
            "daily": True,
        }
    )
    return result
