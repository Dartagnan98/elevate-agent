"""Lane channel picker and onboarding status routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class LaneChannelsBody(BaseModel):
    channels: list[str]


def _build_available_channels() -> dict[str, Any]:
    """Compute which channels the user can pick from for a lane."""
    from elevate_cli.source_connectors import build_source_connectors_response
    from elevate_cli import composio_client

    src_resp = build_source_connectors_response(include_prompts=False)
    source_channels: list[dict[str, Any]] = []
    for c in src_resp.get("connectors", []):
        sid = str(c.get("id") or "")
        if not sid:
            continue
        state = str(c.get("state") or "").lower()
        if state in {"blocked", "not_configured"}:
            continue
        source_channels.append({
            "id": f"source:{sid}",
            "sourceId": sid,
            "label": str(c.get("label") or sid),
            "channel": str(c.get("channel") or sid),
            "state": state or "ok",
        })

    matrix = composio_client.load_capability_matrix() or {}
    composio_channels: list[dict[str, Any]] = []
    for slug, entry in (matrix.get("toolkits") or {}).items():
        send = (entry or {}).get("send") or {}
        if not send.get("supported"):
            continue
        try:
            accounts_resp = composio_client.list_all_connected_accounts(toolkit=slug)
            if not accounts_resp.get("ok"):
                continue
            accounts = (accounts_resp.get("data") or {}).get("items") or []
            if not accounts:
                continue
        except Exception:
            continue
        composio_channels.append({
            "id": f"composio:{slug}",
            "toolkit": slug,
            "slug": send.get("slug"),
            "label": str(slug).replace("_", " ").title(),
            "verification": send.get("verification") or "unknown",
            "accountCount": len(accounts),
        })

    return {
        "sourceChannels": source_channels,
        "composioChannels": composio_channels,
    }


def _reconcile_lane_config(config: dict[str, Any], available: dict[str, Any]) -> dict[str, Any]:
    """Strip stale enabled channels from a lane config snapshot."""
    if not isinstance(config, dict):
        return config
    valid_ids = (
        {c["id"] for c in available.get("sourceChannels", [])}
        | {c["id"] for c in available.get("composioChannels", [])}
    )
    saved = list(config.get("enabledChannels") or [])
    kept = [c for c in saved if c in valid_ids]
    dropped = [c for c in saved if c not in valid_ids]
    if not dropped:
        return config
    out = dict(config)
    out["enabledChannels"] = kept
    out["droppedChannels"] = dropped
    return out


def create_lanes_router(*, log: logging.Logger | None = None) -> APIRouter:
    """Build lane channel picker and onboarding routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/lanes")
    async def list_lanes_endpoint():
        try:
            from elevate_cli import outreach_db

            avail = _build_available_channels()
            lanes = [_reconcile_lane_config(l, avail) for l in outreach_db.list_lane_configs()]
            return {
                "lanes": lanes,
                "available": avail,
            }
        except Exception as exc:
            _log.exception("GET /api/lanes failed")
            raise HTTPException(status_code=500, detail=f"List lanes failed: {exc}")

    @router.get("/api/lanes/{lane}/channels")
    async def get_lane_channels_endpoint(lane: str):
        try:
            from elevate_cli import outreach_db

            avail = _build_available_channels()
            return {
                "config": _reconcile_lane_config(outreach_db.get_lane_config(lane), avail),
                "available": avail,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/lanes/{lane}/channels failed")
            raise HTTPException(status_code=500, detail=f"Get lane channels failed: {exc}")

    @router.get("/api/onboarding/status")
    async def get_onboarding_status_endpoint(request: Request):
        from elevate_cli.onboarding import compute_onboarding_status, parse_if_none_match

        try:
            status = compute_onboarding_status()
            inm = parse_if_none_match(request.headers.get("if-none-match"))
            etag = status["etag"]
            if inm and inm == etag:
                return Response(status_code=304, headers={"ETag": f'"{etag}"'})
            return JSONResponse(status, headers={"ETag": f'"{etag}"'})
        except Exception as exc:
            _log.exception("GET /api/onboarding/status failed")
            raise HTTPException(status_code=500, detail=f"Onboarding status failed: {exc}")

    @router.post("/api/outreach/templates/seed-all")
    async def seed_all_templates_endpoint():
        try:
            from elevate_cli import outreach_db

            return outreach_db.seed_all_templates()
        except Exception as exc:
            _log.exception("POST /api/outreach/templates/seed-all failed")
            raise HTTPException(status_code=500, detail=f"Seed templates failed: {exc}")

    @router.put("/api/lanes/{lane}/channels")
    async def put_lane_channels_endpoint(lane: str, body: LaneChannelsBody):
        try:
            from elevate_cli import outreach_db

            avail = _build_available_channels()
            valid_ids = {c["id"] for c in avail["sourceChannels"]} | {c["id"] for c in avail["composioChannels"]}

            cleaned: list[str] = []
            rejected: list[str] = []
            for raw in body.channels:
                cid = str(raw).strip()
                if not cid:
                    continue
                if cid in valid_ids:
                    cleaned.append(cid)
                else:
                    rejected.append(cid)

            if rejected:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown or unsupported channels: {', '.join(rejected)}",
                )

            config = outreach_db.set_lane_channels(lane, cleaned)
            return {"config": config, "available": avail}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/lanes/{lane}/channels failed")
            raise HTTPException(status_code=500, detail=f"Set lane channels failed: {exc}")

    return router
