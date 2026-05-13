"""Onboarding readiness snapshot — single source of truth.

Both the web wizard (``GET /api/onboarding/status``) and the cron readiness
gate (``run_job``) compute against the same checks so a job that was queued
"only run when ready" can be skipped at fire-time if conditions regressed.

The checks are intentionally cheap (sub-second). They probe configuration
state — not network latency — so we can call this every cron tick without
becoming the bottleneck.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

_log = logging.getLogger(__name__)


def compute_onboarding_status() -> dict[str, Any]:
    """Aggregate every readiness check the wizard cares about. Pure read.

    Each check returns ``{id, label, ok, detail}``. ``ready`` is the AND of
    every required check.ok. ``etag`` is a stable hash of the (id, ok, detail)
    snapshot so the dashboard can poll cheaply without re-rendering on noise.
    ``version`` is derived from the same digest — bumping when any check's
    outcome OR detail string changes — so cron job clients can use it as a
    readiness fingerprint without inspecting individual checks.
    """
    from elevate_cli import outreach_db, composio_client, tier_resolver
    from elevate_cli.source_connectors import build_source_connectors_response

    checks: list[dict[str, Any]] = []

    # 1. At least one tier resolves to a model.
    try:
        any_tier = False
        sample = None
        for tier in tier_resolver.VALID_TIERS:
            resolved = tier_resolver.resolve_tier(tier)
            if resolved:
                any_tier = True
                sample = (tier, resolved)
                break
        checks.append({
            "id": "tier_model",
            "label": "Harness model resolved",
            "ok": bool(any_tier),
            "detail": (f"{sample[0]} → {sample[1]}" if sample else "no tier resolves to a harness model"),
        })
    except Exception as exc:
        checks.append({"id": "tier_model", "label": "Harness model resolved", "ok": False, "detail": f"resolver error: {exc}"})

    # 2. At least one source connector is in 'connected' state.
    try:
        conns = build_source_connectors_response().get("connectors", [])
        connected = [c for c in conns if str(c.get("state") or "").lower() in {"connected", "ok"}]
        checks.append({
            "id": "source_connector",
            "label": "Source connector connected",
            "ok": len(connected) > 0,
            "detail": (", ".join(str(c.get("label") or c.get("id")) for c in connected) or "no connector is connected"),
        })
    except Exception as exc:
        checks.append({"id": "source_connector", "label": "Source connector connected", "ok": False, "detail": f"connector probe failed: {exc}"})

    # 3. Composio API key configured (optional but soft-warned).
    try:
        composio_status = composio_client.get_status()
        ok = bool(composio_status.get("valid"))
        checks.append({
            "id": "composio_key",
            "label": "Composio API key configured",
            "ok": ok,
            "detail": ("valid" if ok else (composio_status.get("error") or "not configured")),
            "optional": True,
        })
    except Exception as exc:
        checks.append({"id": "composio_key", "label": "Composio API key configured", "ok": False, "detail": str(exc), "optional": True})

    # 4. At least one channel picked for at least one lane.
    try:
        lanes = outreach_db.list_lane_configs()
        any_chan = any(len(l.get("enabledChannels") or []) > 0 for l in lanes)
        checks.append({
            "id": "lane_channels",
            "label": "Lane has at least one channel enabled",
            "ok": any_chan,
            "detail": (
                ", ".join(f"{l['lane']}={len(l.get('enabledChannels') or [])}" for l in lanes)
            ),
        })
    except Exception as exc:
        checks.append({"id": "lane_channels", "label": "Lane has at least one channel enabled", "ok": False, "detail": str(exc)})

    # 5. At least one active template per lane.
    try:
        per_lane: dict[str, int] = {}
        missing: list[str] = []
        for lane in outreach_db.LANES:
            tpls = [t for t in outreach_db.list_templates(lane=lane) if t.get("active") and (t.get("status") or "active") == "active"]
            per_lane[lane] = len(tpls)
            if not tpls:
                missing.append(lane)
        checks.append({
            "id": "templates_seeded",
            "label": "Active templates available for every lane",
            "ok": len(missing) == 0,
            "detail": (f"missing: {', '.join(missing)}" if missing else f"counts: {per_lane}"),
        })
    except Exception as exc:
        checks.append({"id": "templates_seeded", "label": "Active templates available for every lane", "ok": False, "detail": str(exc)})

    # 6. Every unlocked pack has completed its own setup contract.
    try:
        from elevate_cli.data import connect, get_pack_onboarding

        with connect() as conn:
            pack_setup = get_pack_onboarding(conn)
        missing = pack_setup.get("launchRequiredPacks") or []
        checks.append({
            "id": "pack_onboarding",
            "label": "Unlocked pack onboarding complete",
            "ok": not missing,
            "detail": (
                f"{pack_setup.get('completedActiveCount', 0)}/{pack_setup.get('activeCount', 0)} active packs ready"
                if not missing
                else "needs setup: " + ", ".join(str(item) for item in missing)
            ),
        })
    except Exception as exc:
        checks.append({"id": "pack_onboarding", "label": "Unlocked pack onboarding complete", "ok": False, "detail": str(exc)})

    required_checks = [c for c in checks if not c.get("optional")]
    ready = all(c["ok"] for c in required_checks) if required_checks else False

    digest_input = "|".join(
        f"{c['id']}={int(bool(c['ok']))}::{c.get('detail', '')}"
        for c in checks
    )
    digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()
    etag = digest[:12]
    version = digest[:8]  # Hex string — easier to ferry through job JSON

    return {
        "version": version,
        "etag": etag,
        "ready": ready,
        "checks": checks,
    }


def parse_if_none_match(raw: str | None) -> str | None:
    """Normalize an ``If-None-Match`` header for comparison.

    Strips the optional ``W/`` weak validator prefix and surrounding double
    quotes so callers (curl, browsers, fetch) all compare against the bare
    etag we emit. Returns ``None`` for missing/blank values.
    """
    if not raw:
        return None
    val = raw.strip()
    if val.startswith("W/") or val.startswith("w/"):
        val = val[2:].strip()
    val = val.strip('"').strip()
    return val or None
