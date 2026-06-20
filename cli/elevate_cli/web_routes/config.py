"""Read-only configuration and model metadata routes."""

import logging
from typing import Any, Dict

from fastapi import APIRouter

from elevate_cli.config import load_config


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


def create_config_router(
    *,
    default_config: Dict[str, Any],
    config_schema: Dict[str, Dict[str, Any]],
    category_order: list[str],
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build read-only routes for config, schema, and model metadata."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
        config = dict(config)
        model_val = config.get("model")
        if isinstance(model_val, dict):
            ctx_len = model_val.get("context_length", 0)
            config["model"] = model_val.get("default", model_val.get("name", ""))
            config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
        else:
            config["model_context_length"] = 0
        return config

    @router.get("/api/config")
    async def get_config():
        config = _normalize_config_for_web(load_config())
        return {k: v for k, v in config.items() if not k.startswith("_")}

    @router.get("/api/config/defaults")
    async def get_defaults():
        return default_config

    @router.get("/api/config/schema")
    async def get_schema():
        return {"fields": config_schema, "category_order": category_order}

    @router.get("/api/model/info")
    def get_model_info():
        """Return resolved model metadata for the currently configured model."""
        try:
            cfg = load_config()
            model_cfg = cfg.get("model", "")

            if isinstance(model_cfg, dict):
                model_name = model_cfg.get("default", model_cfg.get("name", ""))
                provider = model_cfg.get("provider", "")
                base_url = model_cfg.get("base_url", "")
                config_ctx = model_cfg.get("context_length")
            else:
                model_name = str(model_cfg) if model_cfg else ""
                provider = ""
                base_url = ""
                config_ctx = None

            if not model_name:
                return dict(_EMPTY_MODEL_INFO, provider=provider)

            try:
                from agent.model_metadata import get_model_context_length

                auto_ctx = get_model_context_length(
                    model=model_name,
                    base_url=base_url,
                    provider=provider,
                    config_context_length=None,
                )
            except Exception:
                auto_ctx = 0

            config_ctx_int = 0
            if isinstance(config_ctx, int) and config_ctx > 0:
                config_ctx_int = config_ctx
            effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

            caps = {}
            try:
                from agent.models_dev import get_model_capabilities

                mc = get_model_capabilities(provider=provider, model=model_name)
                if mc is not None:
                    caps = {
                        "supports_tools": mc.supports_tools,
                        "supports_vision": mc.supports_vision,
                        "supports_reasoning": mc.supports_reasoning,
                        "context_window": mc.context_window,
                        "max_output_tokens": mc.max_output_tokens,
                        "model_family": mc.model_family,
                    }
            except Exception:
                pass

            return {
                "model": model_name,
                "provider": provider,
                "auto_context_length": auto_ctx,
                "config_context_length": config_ctx_int,
                "effective_context_length": effective_ctx,
                "capabilities": caps,
            }
        except Exception:
            _log.exception("GET /api/model/info failed")
            return dict(_EMPTY_MODEL_INFO)

    @router.get("/api/models/available")
    def get_models_available():
        try:
            from elevate_cli.tier_resolver import list_available_models

            return list_available_models()
        except Exception:
            _log.exception("GET /api/models/available failed")
            return {"models": [], "default": ""}

    @router.get("/api/models/by-provider")
    def get_models_by_provider(provider: str = ""):
        prov = str(provider or "").strip()
        if not prov:
            return {"provider": "", "models": []}
        try:
            from elevate_cli.models import normalize_provider, provider_model_ids

            normalized = normalize_provider(prov)
            models = provider_model_ids(normalized) or []
            return {"provider": normalized, "models": list(models)}
        except Exception:
            _log.exception("GET /api/models/by-provider failed for provider=%s", prov)
            return {"provider": prov, "models": []}

    return router
