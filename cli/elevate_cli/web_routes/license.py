"""Access and license activation routes for the dashboard."""

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

    def _license_http_exception(exc, *, default_status: int) -> HTTPException:
        code = str(getattr(exc, "code", "license_error") or "license_error")
        if code == "beta_backend_identity_unavailable":
            status = 503
        elif code == "beta_backend_override_not_allowed" or code.startswith(
            "beta_license_store_"
        ) or code in {
            "beta_activation_incomplete",
            "beta_auth_sign_out_required",
            "beta_auth_transition_conflict",
            "beta_auth_superseded",
        }:
            status = 409
        elif code in {
            "beta_invalid_credentials",
            "beta_login_code_invalid",
            "beta_subscription_inactive",
            "beta_account_exists",
            "beta_signup_invalid",
            "beta_auth_rate_limited",
        }:
            status = default_status
        elif code in {
            "beta_auth_upstream_failed",
            "beta_auth_upstream_unavailable",
            "beta_device_link_upstream_failed",
            "beta_device_link_upstream_unavailable",
        }:
            status = 502
        elif code == "beta_license_revoked":
            status = 401
        elif code == "beta_entitlement_verifier_unavailable":
            status = 503
        elif code.startswith("beta_license_response_") or code.startswith(
            "beta_entitlement_"
        ):
            status = 502
        elif code.startswith("beta_"):
            status = 500
        else:
            status = default_status
        detail = exc.as_detail() if code != "license_error" else str(exc)
        return HTTPException(status_code=status, detail=detail)

    def _configure_backend(lic_mod, backend_url: Optional[str], *, persist: bool) -> None:
        """Apply Stable compatibility or return a typed Beta policy error."""
        try:
            lic_mod.configure_backend_override(backend_url, persist=persist)
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=503)

    @router.get("/api/access")
    async def get_access_status():
        """Return local entitlement state used to unlock paid dashboard packs."""
        return dashboard_access_status()

    @router.get("/api/license/status")
    async def get_license_status():
        from elevate_cli import license as lic_mod

        if lic_mod._exact_realtor_beta_active():
            try:
                lic = lic_mod.read_verified_beta_license_snapshot(
                    require_current=True,
                )
            except lic_mod.LicenseError:
                lic = None
        else:
            lic = lic_mod.load()
        if not lic:
            status_text = (
                "Not signed in. Sign in to Realtor Beta."
                if lic_mod._exact_realtor_beta_active()
                else lic_mod.status_text()
            )
            return {
                "authenticated": False,
                "account_verified": False,
                "activation_complete": False,
                "email": None,
                "tier": None,
                "license_id": None,
                "entitlements": [],
                "expires_at": None,
                "expired": True,
                "status_text": status_text,
                "packs": dashboard_access_status().get("packs", {}),
            }
        activation_complete = (
            # ``heal_beta_activation`` is a no-op unless the receipt is bound
            # to this same account and only the shipped skill bundle moved
            # (i.e. the app updated) — that shouldn't surface a setup gate.
            (
                lic_mod.beta_activation_complete(lic)
                or lic_mod.heal_beta_activation(lic)
            )
            if lic_mod._exact_realtor_beta_active()
            else True
        )
        return {
            "authenticated": activation_complete,
            "account_verified": True,
            "activation_complete": activation_complete,
            "email": lic.email,
            "tier": lic.tier,
            "license_id": lic.license_id,
            "entitlements": list(lic.entitlements or []),
            "expires_at": lic.expires_at,
            "expired": lic.is_expired(margin=0),
            "status_text": (
                lic_mod.status_text(lic)
                if activation_complete
                else "Account verified. Finish required Realtor Beta skill setup."
            ),
            "packs": dashboard_access_status().get("packs", {}),
        }

    @router.post("/api/license/activate")
    async def activate_license(body: LicenseActivateBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _configure_backend(lic_mod, body.backend_url, persist=True)
        try:
            lic = lic_mod.login(body.email, body.password)
            activation = lic_mod.activate_install(
                lic,
                sync_skills=(
                    True
                    if lic_mod._exact_realtor_beta_active()
                    else not body.skip_skill_sync
                ),
            )
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=401)

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
            "skill_sync_warnings": activation.get("skill_sync_warnings", []),
            "activation_complete": bool(activation.get("activation_complete")),
        }

    @router.post("/api/license/signup")
    async def signup_license(body: LicenseActivateBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _configure_backend(lic_mod, body.backend_url, persist=True)
        try:
            lic = lic_mod.create_account(
                body.email,
                body.password,
                first_name=body.first_name,
                last_name=body.last_name,
            )
            activation = lic_mod.activate_install(
                lic,
                sync_skills=(
                    True
                    if lic_mod._exact_realtor_beta_active()
                    else not body.skip_skill_sync
                ),
            )
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=400)

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
            "skill_sync_warnings": activation.get("skill_sync_warnings", []),
            "activation_complete": bool(activation.get("activation_complete")),
        }

    @router.post("/api/license/request-code")
    async def request_license_code(body: LoginCodeRequestBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _configure_backend(lic_mod, body.backend_url, persist=False)
        try:
            lic_mod.request_login_code(body.email)
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=400)
        return {"ok": True}

    @router.post("/api/license/activate-code")
    async def activate_license_code(body: LoginCodeVerifyBody, request: Request):
        require_token(request)

        from elevate_cli import license as lic_mod

        _configure_backend(lic_mod, body.backend_url, persist=False)
        try:
            lic = lic_mod.login_with_code(body.email, body.code)
            activation = lic_mod.activate_install(
                lic,
                sync_skills=(
                    True
                    if lic_mod._exact_realtor_beta_active()
                    else not body.skip_skill_sync
                ),
            )
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=401)

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
            "skill_sync_warnings": activation.get("skill_sync_warnings", []),
            "activation_complete": bool(activation.get("activation_complete")),
        }

    @router.post("/api/license/sync-skills")
    async def sync_license_skills(request: Request):
        require_token(request)

        from elevate_cli import cloud_skills
        from elevate_cli import license as lic_mod

        lic = lic_mod.load()
        if not lic:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated. Activate first.",
            )

        try:
            if lic.is_expired():
                lic = lic_mod.refresh(lic)
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=401)

        try:
            if lic_mod._exact_realtor_beta_active():
                activation = lic_mod.activate_install(lic, sync_skills=True)
                sync_result = {
                    "skill_count": activation.get("skill_count", 0),
                    "skill_names": activation.get("skill_names", []),
                    "path": activation.get("skills_path"),
                    "removed": [],
                    "errors": activation.get("skill_sync_warnings", []),
                    "activation_complete": bool(
                        activation.get("activation_complete")
                    ),
                }
            else:
                sync_result = cloud_skills.sync_all()
                sync_result["activation_complete"] = not bool(
                    sync_result.get("errors")
                )
        except lic_mod.LicenseError as exc:
            raise _license_http_exception(exc, default_status=409)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Skill sync failed: {exc}")

        return {
            "skill_count": sync_result.get("skill_count", 0),
            "skill_names": sync_result.get("skill_names", []),
            "path": sync_result.get("path"),
            "removed": sync_result.get("removed", []),
            "errors": sync_result.get("errors", []),
            "activation_complete": bool(
                sync_result.get("activation_complete")
            ),
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
