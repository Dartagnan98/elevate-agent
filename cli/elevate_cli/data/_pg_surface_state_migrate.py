"""One-shot data migration: heartbeat surface JSON files -> account database.

Sentinel: ``9010_surface_state_import.legacy`` in ``_schema_migrations``.

Source: ``accounts/<key>/heartbeats/`` for the ACTIVE account —
``surfaces.json`` (registry), and per surface dir ``config.json``,
``goals.json``, ``goals_history.jsonl``, ``heartbeat.json``,
``experiments/active.json`` (legacy single), ``experiments/active/<cycle>.json``
(per-cycle), ``experiments/history/*.json``.

Destinations: ``surface_registry``, ``surface_state``,
``surface_goals_history``, ``surface_experiments`` (migration 0024).

The legacy files are left in place (tolerant, same as the outreach import
leaving the sqlite file) — markdown artifacts in the same dirs
(``learnings.md``, ``history/*.md``) intentionally stay file-based.

Failure mode: copy errors leave the sentinel UN-set so the next boot retries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LOG = logging.getLogger(__name__)

_SENTINEL_VERSION = "9010"
_SENTINEL_NAME = "surface_state_import.legacy"
_SENTINEL_SHA = "n/a-surface-state-import"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _heartbeats_dir() -> Optional[Path]:
    try:
        from elevate_constants import get_account_data_dir

        return get_account_data_dir() / "heartbeats"
    except Exception:
        return None


def _already_migrated(pg_conn) -> bool:
    row = pg_conn.execute(
        "SELECT 1 FROM _schema_migrations WHERE version = %s",
        (_SENTINEL_VERSION,),
    ).fetchone()
    return row is not None


def _mark_migrated(pg_conn) -> None:
    raw = pg_conn._raw  # noqa: SLF001
    with raw.cursor() as cur:
        cur.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
            (_SENTINEL_VERSION, _SENTINEL_NAME, _SENTINEL_SHA, _utcnow()),
        )
    raw.commit()


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def maybe_migrate_surface_state(pg_conn) -> dict[str, Any]:
    """Top-level entry point. Idempotent. Returns a summary dict."""
    summary: dict[str, Any] = {
        "ran": False,
        "reason": "",
        "registry": 0,
        "surfaces": 0,
        "goals_history": 0,
        "experiments": 0,
        "heartbeats": 0,
    }

    if _already_migrated(pg_conn):
        summary["reason"] = "sentinel-present"
        return summary

    root = _heartbeats_dir()
    if root is None or not root.is_dir():
        _mark_migrated(pg_conn)
        summary["reason"] = "no-legacy-heartbeats-dir"
        return summary

    from elevate_cli.data import surface_state as ss

    _LOG.info("pg-surface-state-migrate: starting from %s", root)

    # Registry — surfaces.json holds {"surfaces": {name: spec}}.
    reg_doc = _read_json(root / "surfaces.json")
    if isinstance(reg_doc, dict):
        for surface, spec in (reg_doc.get("surfaces") or {}).items():
            if not isinstance(spec, dict):
                continue
            ss.upsert_registry(pg_conn, surface, dict(spec))
            summary["registry"] += 1

    # Per-surface state.
    for surface_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if not surface_dir.is_dir():
            continue
        surface = surface_dir.name
        imported_any = False

        config = _read_json(surface_dir / "config.json")
        if isinstance(config, dict) and config:
            ss.set_config(pg_conn, surface, config)
            imported_any = True

        goals = _read_json(surface_dir / "goals.json")
        if isinstance(goals, dict) and goals:
            ss.set_goals(pg_conn, surface, goals, history=False)
            imported_any = True

        hist_path = surface_dir / "goals_history.jsonl"
        if hist_path.is_file():
            try:
                for line in hist_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    from elevate_cli.data._util import new_id

                    pg_conn.execute(
                        "INSERT INTO surface_goals_history(id, surface, at, payload) "
                        "VALUES(?,?,?,?)",
                        (
                            new_id(),
                            surface,
                            str(payload.get("at") or _utcnow()),
                            json.dumps(payload, default=str),
                        ),
                    )
                    summary["goals_history"] += 1
                imported_any = True
            except Exception:
                _LOG.warning("goals history import failed for %s", surface, exc_info=True)

        hb = _read_json(surface_dir / "heartbeat.json")
        if isinstance(hb, dict) and hb:
            ss.set_heartbeat(pg_conn, surface, hb)
            summary["heartbeats"] += 1
            imported_any = True

        # Experiments: legacy single active.json, per-cycle active/<cycle>.json,
        # and completed history/*.json.
        exp_dir = surface_dir / "experiments"
        legacy_active = _read_json(exp_dir / "active.json")
        if isinstance(legacy_active, dict) and legacy_active:
            legacy_active.setdefault("status", "running")
            ss.upsert_experiment(pg_conn, surface, legacy_active)
            summary["experiments"] += 1
            imported_any = True
        active_dir = exp_dir / "active"
        if active_dir.is_dir():
            for f in sorted(active_dir.glob("*.json")):
                rec = _read_json(f)
                if not isinstance(rec, dict) or not rec:
                    continue
                rec.setdefault("cycle", f.stem)
                rec.setdefault("status", "running")
                ss.upsert_experiment(pg_conn, surface, rec)
                summary["experiments"] += 1
                imported_any = True
        history_dir = exp_dir / "history"
        if history_dir.is_dir():
            for f in sorted(history_dir.glob("*.json")):
                rec = _read_json(f)
                if not isinstance(rec, dict) or not rec:
                    continue
                rec.setdefault("status", "completed")
                ss.upsert_experiment(pg_conn, surface, rec)
                summary["experiments"] += 1
                imported_any = True

        if imported_any:
            summary["surfaces"] += 1

    raw = pg_conn._raw  # noqa: SLF001
    raw.commit()
    _mark_migrated(pg_conn)

    summary["ran"] = True
    summary["reason"] = "migrated"
    _LOG.info(
        "pg-surface-state-migrate: done (%d surfaces, %d experiments, %d registry rows)",
        summary["surfaces"],
        summary["experiments"],
        summary["registry"],
    )
    return summary


__all__ = ["maybe_migrate_surface_state"]
