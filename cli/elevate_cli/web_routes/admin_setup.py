"""Admin, Leads, and Agent setup routes."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from elevate_cli.config import load_config, load_env, save_config, save_env_value


class _AdminJurisdictionBody(BaseModel):
    country: Optional[str] = None
    province: Optional[str] = None
    market: Optional[str] = None
    packageKey: Optional[str] = None
    package_key: Optional[str] = None


class _AdminSetupItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _AdminSetupUpdateBody(BaseModel):
    profile: Optional[Dict[str, Any]] = None
    items: List[_AdminSetupItemBody] = []


class _LeadsSetupItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _LeadsSetupUpdateBody(BaseModel):
    items: List[_LeadsSetupItemBody] = []


class _AgentSetupItemBody(BaseModel):
    key: str
    status: str = "missing"
    provider: Optional[str] = None
    value: Any = None
    notes: Optional[str] = None


class _AgentSetupUpdateBody(BaseModel):
    items: List[_AgentSetupItemBody] = []


def _clean_admin_jurisdiction_value(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text


def admin_jurisdiction_config() -> Dict[str, str]:
    """Return Admin Hub deal-flow defaults.

    Product onboarding is the canonical source after a profile exists; config is
    only the fallback/override layer for package keys and fresh installs.
    """
    from elevate_cli.admin_deal_flow import package_key_from_jurisdiction

    real_estate = (load_config().get("real_estate") or {})
    setup_profile: Dict[str, Any] = {}
    try:
        from elevate_cli.data import connect, get_admin_setup

        with connect() as conn:
            setup_profile = (get_admin_setup(conn).get("profile") or {})
    except Exception:
        setup_profile = {}

    country = _clean_admin_jurisdiction_value(
        setup_profile.get("country") or real_estate.get("country"),
        "CA",
    ).upper()
    province = _clean_admin_jurisdiction_value(
        setup_profile.get("province") or real_estate.get("province"),
        "",
    ).upper()
    market = _clean_admin_jurisdiction_value(
        setup_profile.get("market") or real_estate.get("market"),
        "",
    )
    package_key = package_key_from_jurisdiction(
        country=country,
        province=province,
        package_key=real_estate.get("package_key") or real_estate.get("packageKey"),
    )
    return {
        "country": country,
        "province": province,
        "market": market,
        "packageKey": package_key,
    }


def require_admin_setup_ready_for_launch() -> None:
    """Block Admin launch/mutation endpoints until the setup gate is complete."""
    from elevate_cli.data import connect, get_admin_setup

    with connect() as conn:
        setup = get_admin_setup(conn)
    if setup.get("complete"):
        return
    raise HTTPException(
        status_code=409,
        detail={
            "message": "Admin setup must be completed before starting admin work.",
            "setup": setup,
        },
    )


def _admin_setup_runtime_env_values() -> Dict[str, str]:
    env_values: Dict[str, str] = {
        str(key): str(value)
        for key, value in load_env().items()
        if value is not None
    }
    for key, value in os.environ.items():
        if value:
            env_values[key] = value
    return env_values


def _mirror_admin_setup_portal_env(
    items: List[_AdminSetupItemBody],
    *,
    log: logging.Logger,
) -> None:
    """Persist onboarding portal login fields into the runtime .env file.

    The Admin wizard owns the browser playbook, but SkySlope/MLS scripts read
    env vars. Mirroring non-empty values here keeps onboarding and runtime from
    drifting without ever clearing an existing credential when the user leaves a
    password box blank.
    """
    try:
        from elevate_cli.portal_credentials import (
            portal_env_updates_from_playbooks,
            portal_playbooks_for_storage,
        )
    except Exception:
        log.exception("admin setup portal env mirror: helper import failed")
        return

    for item in items:
        if item.key != "browser_workflows" or not isinstance(item.value, dict):
            continue
        playbooks = item.value.get("playbooks")
        updates = portal_env_updates_from_playbooks(playbooks if isinstance(playbooks, dict) else {})
        for key, value in updates.items():
            save_env_value(key, value)
        item.value["playbooks"] = portal_playbooks_for_storage(
            playbooks if isinstance(playbooks, dict) else {}
        )
        if updates:
            log.info(
                "admin setup portal env mirror: saved %s",
                ", ".join(sorted(updates)),
            )


_WIZARD_PROVIDER_TO_CONFIG = {
    "openai": "openai-codex",
    "qwen": "qwen-oauth",
    "azure_openai": "azure-foundry",
}
_WIZARD_MEMORY_TO_CONFIG = {
    "sqlite_local": "holographic",
    "supabase": "supabase",
}


def _materialize_agent_setup_to_config(conn) -> Dict[str, Any]:
    """Write onboarding model/embedding/memory selections into config.yaml."""
    applied: Dict[str, Any] = {}
    try:
        from elevate_cli.config import load_config, save_config
    except Exception as exc:  # pragma: no cover
        return {"error": f"config module unavailable: {exc}"}

    items: Dict[str, Dict[str, Any]] = {}
    try:
        rows = conn.execute(
            "SELECT key, status, provider, value_json FROM agent_setup_items"
        ).fetchall()
        for r in rows:
            d = dict(r)
            try:
                d["value"] = json.loads(d.get("value_json") or "{}") or {}
            except Exception:
                d["value"] = {}
            items[d.get("key")] = d
    except Exception as exc:
        return {"error": f"could not read setup items: {exc}"}

    cfg = load_config()
    changed = False

    mp = items.get("model_primary") or {}
    prov = str(mp.get("provider") or "").strip()
    model = str((mp.get("value") or {}).get("model") or "").strip()
    if prov and model:
        canon = _WIZARD_PROVIDER_TO_CONFIG.get(prov, prov)
        mc = cfg.get("model")
        if not isinstance(mc, dict):
            mc = {}
            cfg["model"] = mc
        mc["provider"] = canon
        mc["default"] = model
        changed = True
        applied["model"] = {"provider": canon, "model": model}

    me = items.get("model_embedding") or {}
    eprov = str(me.get("provider") or "").strip()
    emodel = str((me.get("value") or {}).get("model") or "").strip()
    if eprov:
        plugins = cfg.get("plugins")
        if not isinstance(plugins, dict):
            plugins = {}
            cfg["plugins"] = plugins
        store = plugins.get("elevate-memory-store")
        if not isinstance(store, dict):
            store = {}
            plugins["elevate-memory-store"] = store
        store["embedding_provider"] = eprov
        if emodel:
            store["embedding_model"] = emodel
        changed = True
        applied["embedding"] = {"provider": eprov, "model": emodel}

    mm = items.get("memory_store") or {}
    mprov = str(mm.get("provider") or "").strip()
    if mprov:
        canon_mem = _WIZARD_MEMORY_TO_CONFIG.get(mprov, mprov)
        mem = cfg.get("memory")
        if not isinstance(mem, dict):
            mem = {}
            cfg["memory"] = mem
        mem["provider"] = canon_mem
        changed = True
        applied["memory"] = {"provider": canon_mem}

    if changed:
        save_config(cfg)
    return applied


def create_admin_setup_router(
    *,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/jurisdiction")
    async def get_admin_jurisdiction():
        """Return the configured admin deal-flow package. No UI switching."""
        return admin_jurisdiction_config()

    @router.put("/api/admin/jurisdiction")
    def put_admin_jurisdiction(body: _AdminJurisdictionBody):
        """Persist the workspace default province/package for Admin Hub deals."""
        try:
            from elevate_cli.admin_deal_flow import package_key_from_jurisdiction

            config = load_config()
            real_estate = dict(config.get("real_estate") or {})
            country = _clean_admin_jurisdiction_value(
                body.country if body.country is not None else real_estate.get("country"),
                "CA",
            ).upper()
            province = _clean_admin_jurisdiction_value(
                body.province if body.province is not None else real_estate.get("province"),
                "",
            ).upper()
            market = _clean_admin_jurisdiction_value(
                body.market if body.market is not None else real_estate.get("market"),
                "",
            )
            explicit_package = body.packageKey or body.package_key
            package_key = package_key_from_jurisdiction(
                country=country,
                province=province,
                package_key=explicit_package,
            )
            real_estate.update(
                {
                    "country": country,
                    "province": province,
                    "market": market,
                    "package_key": package_key,
                }
            )
            config["real_estate"] = real_estate
            save_config(config)
            try:
                from elevate_cli.data import connect, update_admin_setup

                with connect() as conn:
                    update_admin_setup(
                        conn,
                        profile={"country": country, "province": province, "market": market},
                        actor="admin:jurisdiction",
                    )
            except Exception:
                _log.exception("failed to sync Admin setup jurisdiction profile")
                raise
            return admin_jurisdiction_config()
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/admin/jurisdiction failed")
            raise HTTPException(status_code=500, detail=f"Update jurisdiction failed: {exc}")

    @router.get("/api/admin/setup")
    def get_admin_setup_endpoint():
        """Return the Admin first-run readiness profile."""
        try:
            from elevate_cli.data import connect, get_admin_setup

            with connect() as conn:
                return get_admin_setup(conn)
        except Exception as exc:
            _log.exception("GET /api/admin/setup failed")
            raise HTTPException(status_code=500, detail=f"Admin setup failed: {exc}")

    @router.put("/api/admin/setup")
    def put_admin_setup_endpoint(body: _AdminSetupUpdateBody):
        """Update Admin setup profile/items while the launch gate is open."""
        try:
            from elevate_cli.data import connect, update_admin_setup

            _mirror_admin_setup_portal_env(body.items, log=_log)
            with connect() as conn:
                setup = update_admin_setup(
                    conn,
                    profile=body.profile,
                    items=[item.dict() for item in body.items],
                    actor=web_actor,
                )
            if body.profile and any(key in body.profile for key in ("country", "province", "market", "packageKey", "package_key")):
                from elevate_cli.admin_deal_flow import package_key_from_jurisdiction

                config = load_config()
                real_estate = dict(config.get("real_estate") or {})
                country = _clean_admin_jurisdiction_value(body.profile.get("country"), real_estate.get("country") or "CA").upper()
                province = _clean_admin_jurisdiction_value(body.profile.get("province"), real_estate.get("province") or "").upper()
                market = _clean_admin_jurisdiction_value(body.profile.get("market"), real_estate.get("market") or "")
                package_key = package_key_from_jurisdiction(
                    country=country,
                    province=province,
                    package_key=body.profile.get("packageKey") or body.profile.get("package_key") or real_estate.get("package_key"),
                )
                real_estate.update({"country": country, "province": province, "market": market, "package_key": package_key})
                config["real_estate"] = real_estate
                save_config(config)
            return setup
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/admin/setup failed")
            raise HTTPException(status_code=500, detail=f"Update admin setup failed: {exc}")

    @router.post("/api/admin/setup/complete")
    def post_admin_setup_complete_endpoint():
        """Mark Admin setup complete after all required readiness items are filled."""
        try:
            from elevate_cli.data import complete_admin_setup, connect

            with connect() as conn:
                return complete_admin_setup(conn, actor=web_actor)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/setup/complete failed")
            raise HTTPException(status_code=500, detail=f"Complete admin setup failed: {exc}")

    @router.post("/api/admin/setup/verify")
    def post_admin_setup_verify_endpoint():
        """Check setup items against local runtime connectors and imported guides."""
        warnings: List[str] = []
        try:
            from elevate_cli.data import (
                connect,
                get_admin_setup,
                import_exp_agent_centre,
                province_guide_summary,
                sync_admin_setup_runtime,
            )

            config = load_config()
            source_connectors: Dict[str, Any] | None = None
            composio_accounts: Dict[str, Any] | None = None
            try:
                from elevate_cli.source_connectors import build_source_connectors_response

                source_connectors = build_source_connectors_response(config, include_prompts=False)
            except Exception as exc:
                warnings.append(f"Source connector check skipped: {exc}")
            try:
                from elevate_cli import composio_client

                composio_accounts = composio_client.list_all_connected_accounts(
                    page_size=100,
                    max_pages=2,
                )
                if not composio_accounts.get("ok"):
                    warnings.append(
                        f"Composio account check skipped: {composio_accounts.get('error') or 'not connected'}"
                    )
            except Exception as exc:
                warnings.append(f"Composio account check skipped: {exc}")

            with connect() as conn:
                setup = get_admin_setup(conn)
                province = str(setup.get("profile", {}).get("province") or "").strip().upper()
                province_guide: Dict[str, Any] | None = None
                try:
                    import_exp_agent_centre(conn)
                    if province:
                        province_guide = province_guide_summary(conn, province)
                except Exception as exc:
                    warnings.append(f"Province guide import skipped: {exc}")
                verified = sync_admin_setup_runtime(
                    conn,
                    env_values=_admin_setup_runtime_env_values(),
                    source_connectors=source_connectors,
                    composio_accounts=composio_accounts,
                    province_guide=province_guide,
                    actor=web_actor,
                )
            if warnings:
                verified["verificationWarnings"] = warnings
            return verified
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/setup/verify failed")
            raise HTTPException(status_code=500, detail=f"Verify admin setup failed: {exc}")

    @router.get("/api/leads/setup")
    def get_leads_setup_endpoint():
        """Return the Leads onboarding readiness snapshot."""
        try:
            from elevate_cli.data import connect, get_leads_setup

            with connect() as conn:
                return get_leads_setup(conn)
        except Exception as exc:
            _log.exception("GET /api/leads/setup failed")
            raise HTTPException(status_code=500, detail=f"Leads setup failed: {exc}")

    @router.put("/api/leads/setup")
    def put_leads_setup_endpoint(body: _LeadsSetupUpdateBody):
        """Update Leads setup items while the gate is open."""
        try:
            from elevate_cli.data import connect, update_leads_setup

            with connect() as conn:
                return update_leads_setup(
                    conn,
                    items=[item.dict() for item in body.items],
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/leads/setup failed")
            raise HTTPException(status_code=500, detail=f"Update leads setup failed: {exc}")

    @router.post("/api/leads/setup/complete")
    def post_leads_setup_complete_endpoint():
        """Mark Leads onboarding complete once CRM + at least one lead source + auto-reply are ready."""
        try:
            from elevate_cli.data import complete_leads_setup, connect

            with connect() as conn:
                return complete_leads_setup(conn)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/leads/setup/complete failed")
            raise HTTPException(status_code=500, detail=f"Complete leads setup failed: {exc}")

    @router.post("/api/leads/setup/reset")
    def post_leads_setup_reset_endpoint():
        """Re-open the Leads onboarding gate without wiping item state."""
        try:
            from elevate_cli.data import connect, reset_leads_setup

            with connect() as conn:
                return reset_leads_setup(conn)
        except Exception as exc:
            _log.exception("POST /api/leads/setup/reset failed")
            raise HTTPException(status_code=500, detail=f"Reset leads setup failed: {exc}")

    @router.get("/api/agent/setup")
    def get_agent_setup_endpoint():
        """Return the top-level Agent onboarding readiness snapshot."""
        try:
            from elevate_cli.data import connect, get_agent_setup

            with connect() as conn:
                return get_agent_setup(conn)
        except Exception as exc:
            _log.exception("GET /api/agent/setup failed")
            raise HTTPException(status_code=500, detail=f"Agent setup failed: {exc}")

    @router.put("/api/agent/setup")
    def put_agent_setup_endpoint(body: _AgentSetupUpdateBody):
        """Update Agent setup items while the gate is open."""
        try:
            from elevate_cli.data import connect, update_agent_setup

            with connect() as conn:
                return update_agent_setup(
                    conn,
                    items=[item.dict() for item in body.items],
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("PUT /api/agent/setup failed")
            raise HTTPException(status_code=500, detail=f"Update agent setup failed: {exc}")

    @router.post("/api/agent/setup/complete")
    def post_agent_setup_complete_endpoint():
        """Mark Agent onboarding complete once primary LLM + embedding + memory store are ready.

        On success, materialize the wizard's model/embedding/memory selections into
        config.yaml so finishing onboarding actually configures the agent (the
        selections otherwise live only in the readiness-tracker DB).
        """
        try:
            from elevate_cli.data import complete_agent_setup, connect

            with connect() as conn:
                snapshot = complete_agent_setup(conn)
                try:
                    snapshot["materialized"] = _materialize_agent_setup_to_config(conn)
                except Exception as exc:  # never let materialization undo completion
                    _log.exception("agent setup materialization failed")
                    snapshot["materialize_error"] = str(exc)
                return snapshot
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/agent/setup/complete failed")
            raise HTTPException(status_code=500, detail=f"Complete agent setup failed: {exc}")

    @router.post("/api/agent/setup/reset")
    def post_agent_setup_reset_endpoint():
        """Re-open the Agent onboarding gate without wiping item state."""
        try:
            from elevate_cli.data import connect, reset_agent_setup

            with connect() as conn:
                return reset_agent_setup(conn)
        except Exception as exc:
            _log.exception("POST /api/agent/setup/reset failed")
            raise HTTPException(status_code=500, detail=f"Reset agent setup failed: {exc}")

    return router
