"""Access and license activation routes for the dashboard."""

import os
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from elevate_cli.access import dashboard_access_status


RequireToken = Callable[[Request], None]


class LicenseActivateBody(BaseModel):
    email: str
    password: str
    backend_url: Optional[str] = None
    skip_skill_sync: bool = False
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class LoginCodeRequestBody(BaseModel):
    email: str
    backend_url: Optional[str] = None


class LoginCodeVerifyBody(BaseModel):
    email: str
    code: str
    backend_url: Optional[str] = None
    skip_skill_sync: bool = False


def create_license_router(*, require_token: RequireToken) -> APIRouter:
    """Build routes for local access state and license activation."""
    router = APIRouter()

    def _set_backend_url(lic_mod, backend_url: Optional[str], *, persist: bool) -> None:
        if not backend_url:
            return
        lic_mod.BACKEND_URL = backend_url.rstrip("/")
        os.environ["ELEVATE_BACKEND_URL"] = lic_mod.BACKEND_URL
        if not persist:
            return
        try:
            from elevate_cli.config import save_env_value

            save_env_value("ELEVATE_BACKEND_URL", lic_mod.BACKEND_URL)
        except Exception:
            pass

    @router.get("/api/access")
    async def get_access_status():
        """Return local entitlement state used to unlock paid dashboard packs."""
        return dashboard_access_status()

    @router.get("/api/license/status")
    async def get_license_status():
        from elevate_cli import license as lic_mod

        lic = lic_mod.load()
        if not lic:
            return {
                "authenticated": False,
                "email": None,
                "tier": None,
                "license_id": None,
                "entitlements": [],
                "expires_at": None,
                "expired": True,
                "status_text": lic_mod.status_text(),
                "packs": dashboard_access_status().get("packs", {}),
            }
        return {
            "authenticated": True,
            "email": lic.email,
            "tier": lic.tier,
            "license_id": lic.license_id,
            "entitlements": list(lic.entitlements or []),
            "expires_at": lic.expires_at,
            "expired": lic.is_expired(margin=0),
            "status_text": lic_mod.status_text(lic),
            "packs": dashboard_access_status().get("packs", {}),
        }

    @router.post("/api/license/activate")
    async def activate_license(body: LicenseActivateBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _set_backend_url(lic_mod, body.backend_url, persist=True)

        try:
            lic = lic_mod.login(body.email, body.password)
        except lic_mod.LicenseError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        activation = lic_mod.activate_install(lic, sync_skills=not body.skip_skill_sync)
        return {
            "authenticated": True,
            "email": lic.email,
            "tier": lic.tier,
            "license_id": lic.license_id,
            "entitlements": list(lic.entitlements or []),
            "expires_at": lic.expires_at,
            "packs": activation.get("packs", {}),
            "skill_count": activation.get("skill_count", 0),
            "skill_names": activation.get("skill_names", []),
            "skill_error": activation.get("skill_error"),
        }

    @router.post("/api/license/signup")
    async def signup_license(body: LicenseActivateBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _set_backend_url(lic_mod, body.backend_url, persist=True)

        try:
            lic = lic_mod.create_account(
                body.email,
                body.password,
                first_name=body.first_name,
                last_name=body.last_name,
            )
        except lic_mod.LicenseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        activation = lic_mod.activate_install(lic, sync_skills=not body.skip_skill_sync)
        return {
            "authenticated": True,
            "email": lic.email,
            "tier": lic.tier,
            "license_id": lic.license_id,
            "entitlements": list(lic.entitlements or []),
            "expires_at": lic.expires_at,
            "packs": activation.get("packs", {}),
            "skill_count": activation.get("skill_count", 0),
            "skill_names": activation.get("skill_names", []),
            "skill_error": activation.get("skill_error"),
        }

    @router.post("/api/license/request-code")
    async def request_license_code(body: LoginCodeRequestBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _set_backend_url(lic_mod, body.backend_url, persist=False)

        try:
            lic_mod.request_login_code(body.email)
        except lic_mod.LicenseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True}

    @router.post("/api/license/activate-code")
    async def activate_license_code(body: LoginCodeVerifyBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _set_backend_url(lic_mod, body.backend_url, persist=False)

        try:
            lic = lic_mod.login_with_code(body.email, body.code)
        except lic_mod.LicenseError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        activation = lic_mod.activate_install(lic, sync_skills=not body.skip_skill_sync)
        return {
            "authenticated": True,
            "email": lic.email,
            "tier": lic.tier,
            "license_id": lic.license_id,
            "entitlements": list(lic.entitlements or []),
            "expires_at": lic.expires_at,
            "packs": activation.get("packs", {}),
            "skill_count": activation.get("skill_count", 0),
            "skill_names": activation.get("skill_names", []),
            "skill_error": activation.get("skill_error"),
        }

    @router.post("/api/license/sync-skills")
    async def sync_license_skills(request: Request):
        require_token(request)

        from elevate_cli import cloud_skills
        from elevate_cli import license as lic_mod

        lic = lic_mod.load()
        if not lic:
            raise HTTPException(status_code=401, detail="Not authenticated. Activate first.")

        try:
            if lic.is_expired():
                lic = lic_mod.refresh(lic)
        except lic_mod.LicenseError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        try:
            sync_result = cloud_skills.sync_all()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Skill sync failed: {exc}")

        return {
            "skill_count": sync_result.get("skill_count", 0),
            "skill_names": sync_result.get("skill_names", []),
            "path": sync_result.get("path"),
            "removed": sync_result.get("removed", []),
            "errors": sync_result.get("errors", []),
            "packs": dashboard_access_status().get("packs", {}),
        }

    @router.post("/api/license/logout")
    async def logout_license(request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        cleared = lic_mod.clear()

        from elevate_cli.access import REAL_ESTATE_ENTITLEMENTS, update_entitlement

        for entitlement in REAL_ESTATE_ENTITLEMENTS:
            try:
                update_entitlement(entitlement, status="locked", owned_snapshot=False)
            except Exception:
                pass

        return {
            "authenticated": False,
            "cleared": cleared,
            "packs": dashboard_access_status().get("packs", {}),
        }

    return router
