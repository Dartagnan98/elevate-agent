"""Pack onboarding and province guide routes."""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _PackOnboardingItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _PackOnboardingUpdateBody(BaseModel):
    items: List[_PackOnboardingItemBody] = []


class _ProvinceGuideImportBody(BaseModel):
    root: Optional[str] = None
    province: Optional[str] = None
    pruneOtherProvinces: bool = False


def create_admin_pack_router(
    *,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/pack-onboarding")
    def get_pack_onboarding_endpoint():
        """Return pack-specific onboarding contracts for unlocked real estate packs."""
        try:
            from elevate_cli.data import connect, get_pack_onboarding

            with connect() as conn:
                return get_pack_onboarding(conn)
        except Exception as exc:
            _log.exception("GET /api/pack-onboarding failed")
            raise HTTPException(status_code=500, detail=f"Pack onboarding failed: {exc}")

    @router.put("/api/pack-onboarding/{pack_id}")
    def put_pack_onboarding_endpoint(pack_id: str, body: _PackOnboardingUpdateBody):
        """Save onboarding answers for one paid pack."""
        try:
            from elevate_cli.data import connect, update_pack_onboarding

            with connect() as conn:
                return update_pack_onboarding(
                    conn,
                    pack_id,
                    items=[item.dict() for item in body.items],
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/pack-onboarding/%s failed", pack_id)
            raise HTTPException(status_code=500, detail=f"Update pack onboarding failed: {exc}")

    @router.post("/api/pack-onboarding/{pack_id}/complete")
    def post_pack_onboarding_complete_endpoint(pack_id: str):
        """Mark one pack onboarding complete once required fields are ready."""
        try:
            from elevate_cli.data import complete_pack_onboarding, connect

            with connect() as conn:
                return complete_pack_onboarding(conn, pack_id, actor=web_actor)
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/pack-onboarding/%s/complete failed", pack_id)
            raise HTTPException(status_code=500, detail=f"Complete pack onboarding failed: {exc}")

    @router.get("/api/admin/province-guides")
    def get_admin_province_guides(province: Optional[str] = None):
        """Return SQLite-backed province guide coverage/reference material."""
        try:
            from elevate_cli.data import connect, province_coverage, province_guide_summary
            from elevate_cli.data.province_guides import normalize_province_code

            with connect() as conn:
                requested_province = normalize_province_code(province) if province and province.strip() else None
                if requested_province:
                    return province_guide_summary(conn, requested_province)
                return {"items": province_coverage(conn)}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/province-guides failed")
            raise HTTPException(status_code=500, detail=f"Province guides failed: {exc}")

    @router.post("/api/admin/province-guides/import")
    def post_admin_province_guides_import(body: Optional[_ProvinceGuideImportBody] = None):
        """Import local eXp Agent Centre scrape output into SQLite."""
        try:
            from elevate_cli.data import connect, import_exp_agent_centre
            from elevate_cli.data.province_guides import normalize_province_code

            root = body.root.strip() if body and body.root and body.root.strip() else None
            requested_province = normalize_province_code(body.province) if body and body.province else None
            prune = body.pruneOtherProvinces if body is not None else False
            with connect() as conn:
                return import_exp_agent_centre(
                    conn,
                    root=root,
                    province=requested_province,
                    prune_other_provinces=prune,
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/province-guides/import failed")
            raise HTTPException(status_code=500, detail=f"Province guide import failed: {exc}")

    return router
