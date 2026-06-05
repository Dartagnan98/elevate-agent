"""
Cloud automation kit — fetch the premium lead/admin automation/heartbeat specs
from the Elevate backend, the same way ``cloud_skills`` fetches skill bodies.

The CLI used to hardcode SURFACE_AUTOMATION_DEFAULTS + SURFACE_HEARTBEAT_DEFAULTS
in ``cron.jobs`` and seed them for any account whose gateway ran. This module
makes the kit a backend-driven, entitlement-gated download:

  - GET /api/automations/list returns only the rows the license is entitled to
    (tier + entitlement gated, exactly like /api/skills/list).
  - ``fetch_kit()`` returns ``{"automations": [...], "heartbeats": {surface: spec}}``
    mapped into the shapes ``cron.jobs`` already seeds from, or ``None`` when the
    backend is unreachable / the license is missing (the caller then falls back to
    the bundled defaults so offline + already-entitled accounts still seed).

A backend reply that is reachable-but-empty (unentitled) returns empty collections,
NOT ``None`` — so the gate is honoured: entitled-but-no-kit seeds nothing rather
than falling back to the bundled set.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from elevate_cli import license as elevate_license


_CACHE: Optional[dict] = None
_CACHE_AT: float = 0.0
_CACHE_TTL_SECONDS = 600.0  # 10 min — seeding is idempotent, no need to re-hammer


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=elevate_license.backend_url(),
        timeout=15.0,
        headers={"user-agent": "elevate-cli/0.11"},
    )


def _auth_header(lic: "elevate_license.License") -> dict:
    return {"authorization": f"Bearer {lic.access_token}"}


def list_automations() -> list[dict]:
    """Raw GET /api/automations/list. Raises LicenseError on auth/transport failure."""
    lic = elevate_license.ensure_valid()
    with _client() as client:
        resp = client.get("/api/automations/list", headers=_auth_header(lic))
    if not resp.is_success:
        raise elevate_license.LicenseError(
            f"automations list failed ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json().get("automations", [])


def _map_kit(rows: list[dict]) -> dict:
    """Split the flat backend rows into the two shapes cron.jobs seeds from.

    automation -> {name, surface, schedule, skill, prompt}  (SURFACE_AUTOMATION_DEFAULTS)
    heartbeat  -> {surface: {name, schedule, goal, experiment}}  (SURFACE_HEARTBEAT_DEFAULTS)
    """
    automations: list[dict] = []
    heartbeats: dict[str, dict] = {}
    for row in rows or []:
        kind = str(row.get("kind") or "automation")
        if kind == "heartbeat":
            surface = str(row.get("surface") or "").strip()
            if not surface:
                continue
            spec = row.get("spec") or {}
            heartbeats[surface] = {
                "name": row.get("name"),
                "schedule": row.get("schedule"),
                "goal": spec.get("goal", ""),
                "experiment": spec.get("experiment", {}),
            }
        else:
            automations.append(
                {
                    "name": row.get("name"),
                    "surface": row.get("surface") or "",
                    "schedule": row.get("schedule"),
                    "skill": row.get("skill"),
                    "prompt": row.get("prompt") or "",
                }
            )
    return {"automations": automations, "heartbeats": heartbeats}


def fetch_kit(*, force: bool = False) -> Optional[dict]:
    """Return the entitled kit mapped to the cron.jobs seed shapes, or ``None`` when
    the backend can't be reached / there's no license (caller falls back to bundled).

    Cached for ``_CACHE_TTL_SECONDS`` so the long-running gateway scheduler doesn't
    hit the network on every tick. ``force=True`` bypasses the cache.
    """
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    if not force and _CACHE is not None and (now - _CACHE_AT) < _CACHE_TTL_SECONDS:
        return _CACHE
    try:
        rows = list_automations()
    except Exception:
        # Unreachable / unlicensed → signal fallback to bundled defaults.
        return None
    kit = _map_kit(rows)
    _CACHE = kit
    _CACHE_AT = now
    return kit
