"""Dashboard theme and plugin routes."""

import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from elevate_cli.config import get_elevate_home, load_config, save_config


_BUILTIN_DASHBOARD_THEMES = [
    {"name": "dark", "label": "Dark", "description": "Deep blue-black workspace for focused agent work"},
    {"name": "light", "label": "Light", "description": "Bright workspace with crisp blue agent controls"},
]

_DASHBOARD_THEME_NAMES = {t["name"] for t in _BUILTIN_DASHBOARD_THEMES}
_DASHBOARD_THEME_ALIASES = {
    "cyberpunk": "dark",
    "default": "dark",
    "ember": "dark",
    "midnight": "dark",
    "mono": "dark",
    "rose": "dark",
}


class ThemeSetBody(BaseModel):
    name: str


def _normalise_dashboard_theme_name(name: Any) -> str:
    if isinstance(name, str):
        if name in _DASHBOARD_THEME_NAMES:
            return name
        if name in _DASHBOARD_THEME_ALIASES:
            return _DASHBOARD_THEME_ALIASES[name]
    return "dark"


def _parse_theme_layer(value: Any, default_hex: str, default_alpha: float = 1.0) -> Optional[Dict[str, Any]]:
    """Normalise a theme layer spec from YAML into `{hex, alpha}` form."""
    if value is None:
        return {"hex": default_hex, "alpha": default_alpha}
    if isinstance(value, str):
        return {"hex": value, "alpha": default_alpha}
    if isinstance(value, dict):
        hex_val = value.get("hex", default_hex)
        alpha_val = value.get("alpha", default_alpha)
        if not isinstance(hex_val, str):
            return None
        try:
            alpha_f = float(alpha_val)
        except (TypeError, ValueError):
            alpha_f = default_alpha
        return {"hex": hex_val, "alpha": max(0.0, min(1.0, alpha_f))}
    return None


_THEME_DEFAULT_TYPOGRAPHY: Dict[str, str] = {
    "fontSans": 'Aptos, "Avenir Next", "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
    "fontMono": 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace',
    "baseSize": "15px",
    "lineHeight": "1.55",
    "letterSpacing": "0",
}

_THEME_DEFAULT_LAYOUT: Dict[str, str] = {
    "radius": "0.5rem",
    "density": "comfortable",
}

_THEME_OVERRIDE_KEYS = {
    "card", "cardForeground", "popover", "popoverForeground",
    "primary", "primaryForeground", "secondary", "secondaryForeground",
    "muted", "mutedForeground", "accent", "accentForeground",
    "destructive", "destructiveForeground", "success", "warning",
    "border", "input", "ring",
}

_THEME_NAMED_ASSET_KEYS = {"bg", "hero", "logo", "crest", "sidebar", "header"}
_THEME_COMPONENT_BUCKETS = {
    "card", "header", "footer", "sidebar", "tab",
    "progress", "badge", "backdrop", "page",
}
_THEME_LAYOUT_VARIANTS = {"standard", "cockpit", "tiled"}
_THEME_CUSTOM_CSS_MAX = 32 * 1024


def _normalise_theme_definition(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a user theme YAML into the wire format `ThemeProvider` expects."""
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    palette_src = data.get("palette", {}) if isinstance(data.get("palette"), dict) else {}
    colors_src = data.get("colors", {}) if isinstance(data.get("colors"), dict) else {}

    def _layer(key: str, default_hex: str, default_alpha: float = 1.0) -> Dict[str, Any]:
        spec = palette_src.get(key, colors_src.get(key))
        parsed = _parse_theme_layer(spec, default_hex, default_alpha)
        return parsed if parsed is not None else {"hex": default_hex, "alpha": default_alpha}

    palette = {
        "background": _layer("background", "#07182f", 1.0),
        "midground": _layer("midground", "#e7f0ff", 1.0),
        "foreground": _layer("foreground", "#ffffff", 0.0),
        "warmGlow": palette_src.get("warmGlow") or data.get("warmGlow") or "rgba(76, 141, 255, 0.34)",
        "noiseOpacity": 1.0,
    }
    raw_noise = palette_src.get("noiseOpacity", data.get("noiseOpacity"))
    try:
        palette["noiseOpacity"] = float(raw_noise) if raw_noise is not None else 1.0
    except (TypeError, ValueError):
        palette["noiseOpacity"] = 1.0

    typo_src = data.get("typography", {}) if isinstance(data.get("typography"), dict) else {}
    typography = dict(_THEME_DEFAULT_TYPOGRAPHY)
    for key in ("fontSans", "fontMono", "fontDisplay", "fontUrl", "baseSize", "lineHeight", "letterSpacing"):
        val = typo_src.get(key)
        if isinstance(val, str) and val.strip():
            typography[key] = val

    layout_src = data.get("layout", {}) if isinstance(data.get("layout"), dict) else {}
    layout = dict(_THEME_DEFAULT_LAYOUT)
    radius = layout_src.get("radius")
    if isinstance(radius, str) and radius.strip():
        layout["radius"] = radius
    density = layout_src.get("density")
    if isinstance(density, str) and density in ("compact", "comfortable", "spacious"):
        layout["density"] = density

    overrides_src = data.get("colorOverrides", {})
    color_overrides: Dict[str, str] = {}
    if isinstance(overrides_src, dict):
        for key, val in overrides_src.items():
            if key in _THEME_OVERRIDE_KEYS and isinstance(val, str) and val.strip():
                color_overrides[key] = val

    assets_out: Dict[str, Any] = {}
    assets_src = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    for key in _THEME_NAMED_ASSET_KEYS:
        val = assets_src.get(key)
        if isinstance(val, str) and val.strip():
            assets_out[key] = val
    custom_assets_src = assets_src.get("custom")
    if isinstance(custom_assets_src, dict):
        custom_assets: Dict[str, str] = {}
        for key, val in custom_assets_src.items():
            if (
                isinstance(key, str)
                and key.replace("-", "").replace("_", "").isalnum()
                and isinstance(val, str)
                and val.strip()
            ):
                custom_assets[key] = val
        if custom_assets:
            assets_out["custom"] = custom_assets

    custom_css_val = data.get("customCSS")
    custom_css: Optional[str] = None
    if isinstance(custom_css_val, str) and custom_css_val.strip():
        custom_css = custom_css_val[:_THEME_CUSTOM_CSS_MAX]

    component_styles_src = data.get("componentStyles", {})
    component_styles: Dict[str, Dict[str, str]] = {}
    if isinstance(component_styles_src, dict):
        for bucket, props in component_styles_src.items():
            if bucket not in _THEME_COMPONENT_BUCKETS or not isinstance(props, dict):
                continue
            clean: Dict[str, str] = {}
            for prop, value in props.items():
                if (
                    isinstance(prop, str)
                    and prop.replace("-", "").replace("_", "").isalnum()
                    and isinstance(value, (str, int, float))
                    and str(value).strip()
                ):
                    clean[prop] = str(value)
            if clean:
                component_styles[bucket] = clean

    layout_variant_src = data.get("layoutVariant")
    layout_variant = (
        layout_variant_src
        if isinstance(layout_variant_src, str) and layout_variant_src in _THEME_LAYOUT_VARIANTS
        else "standard"
    )

    result: Dict[str, Any] = {
        "name": name,
        "label": data.get("label") or name,
        "description": data.get("description", ""),
        "palette": palette,
        "typography": typography,
        "layout": layout,
        "layoutVariant": layout_variant,
    }
    if color_overrides:
        result["colorOverrides"] = color_overrides
    if assets_out:
        result["assets"] = assets_out
    if custom_css is not None:
        result["customCSS"] = custom_css
    if component_styles:
        result["componentStyles"] = component_styles
    return result


def _discover_user_themes() -> list:
    themes_dir = get_elevate_home() / "dashboard-themes"
    if not themes_dir.is_dir():
        return []
    result = []
    for f in sorted(themes_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalised = _normalise_theme_definition(data)
        if normalised is not None:
            result.append(normalised)
    return result


_dashboard_plugins_cache: Optional[list] = None


def _discover_dashboard_plugins(project_root: Path, log: logging.Logger) -> list:
    """Scan plugins/*/dashboard/manifest.json for dashboard extensions."""
    plugins = []
    seen_names: set = set()
    search_dirs = [
        (get_elevate_home() / "plugins", "user"),
        (project_root / "plugins" / "memory", "bundled"),
        (project_root / "plugins", "bundled"),
    ]
    if os.environ.get("ELEVATE_ENABLE_PROJECT_PLUGINS"):
        search_dirs.append((Path.cwd() / ".elevate" / "plugins", "project"))

    for plugins_root, source in search_dirs:
        if not plugins_root.is_dir():
            continue
        for child in sorted(plugins_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "dashboard" / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                name = data.get("name", child.name)
                if name in seen_names:
                    continue
                seen_names.add(name)
                raw_tab = data.get("tab", {}) if isinstance(data.get("tab"), dict) else {}
                tab_info = {
                    "path": raw_tab.get("path", f"/{name}"),
                    "position": raw_tab.get("position", "end"),
                }
                override_path = raw_tab.get("override")
                if isinstance(override_path, str) and override_path.startswith("/"):
                    tab_info["override"] = override_path
                if bool(raw_tab.get("hidden")):
                    tab_info["hidden"] = True
                slots_src = data.get("slots")
                slots: List[str] = []
                if isinstance(slots_src, list):
                    slots = [s for s in slots_src if isinstance(s, str) and s]
                plugins.append({
                    "name": name,
                    "label": data.get("label", name),
                    "description": data.get("description", ""),
                    "icon": data.get("icon", "Puzzle"),
                    "version": data.get("version", "0.0.0"),
                    "tab": tab_info,
                    "slots": slots,
                    "entry": data.get("entry", "dist/index.js"),
                    "css": data.get("css"),
                    "has_api": bool(data.get("api")),
                    "source": source,
                    "_dir": str(child / "dashboard"),
                    "_api_file": data.get("api"),
                })
            except Exception as exc:
                log.warning("Bad dashboard plugin manifest %s: %s", manifest_file, exc)
                continue
    return plugins


def _get_dashboard_plugins(project_root: Path, log: logging.Logger, force_rescan: bool = False) -> list:
    global _dashboard_plugins_cache
    if _dashboard_plugins_cache is None or force_rescan:
        _dashboard_plugins_cache = _discover_dashboard_plugins(project_root, log)
    return _dashboard_plugins_cache


def create_dashboard_router(*, project_root: Path, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/dashboard/themes")
    async def get_dashboard_themes():
        config = load_config()
        active = _normalise_dashboard_theme_name(config.get("dashboard", {}).get("theme", "dark"))
        themes = []
        for t in _BUILTIN_DASHBOARD_THEMES:
            themes.append(t)
        return {"themes": themes, "active": active}

    @router.put("/api/dashboard/theme")
    async def set_dashboard_theme(body: ThemeSetBody):
        config = load_config()
        if "dashboard" not in config:
            config["dashboard"] = {}
        config["dashboard"]["theme"] = _normalise_dashboard_theme_name(body.name)
        save_config(config)
        return {"ok": True, "theme": config["dashboard"]["theme"]}

    @router.get("/api/dashboard/plugins")
    async def get_dashboard_plugins():
        plugins = _get_dashboard_plugins(project_root, _log)
        return [
            {k: v for k, v in p.items() if not k.startswith("_")}
            for p in plugins
        ]

    @router.get("/api/dashboard/plugins/rescan")
    async def rescan_dashboard_plugins():
        plugins = _get_dashboard_plugins(project_root, _log, force_rescan=True)
        return {"ok": True, "count": len(plugins)}

    @router.get("/dashboard-plugins/{plugin_name}/{file_path:path}")
    async def serve_plugin_asset(plugin_name: str, file_path: str):
        plugins = _get_dashboard_plugins(project_root, _log)
        plugin = next((p for p in plugins if p["name"] == plugin_name), None)
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")

        base = Path(plugin["_dir"])
        target = (base / file_path).resolve()
        if not target.is_relative_to(base.resolve()):
            raise HTTPException(status_code=403, detail="Path traversal blocked")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        content_types = {
            ".js": "application/javascript",
            ".mjs": "application/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".html": "text/html",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
        }
        return FileResponse(target, media_type=content_types.get(target.suffix.lower(), "application/octet-stream"))

    return router


def mount_dashboard_plugin_api_routes(app: Any, *, project_root: Path, log: logging.Logger | None = None) -> None:
    """Import and mount backend API routes from plugins that declare them."""
    _log = log or logging.getLogger(__name__)
    for plugin in _get_dashboard_plugins(project_root, _log):
        api_file_name = plugin.get("_api_file")
        if not api_file_name:
            continue
        api_path = Path(plugin["_dir"]) / api_file_name
        if not api_path.exists():
            _log.warning("Plugin %s declares api=%s but file not found", plugin["name"], api_file_name)
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"elevate_dashboard_plugin_{plugin['name']}", api_path,
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            router = getattr(mod, "router", None)
            if router is None:
                _log.warning("Plugin %s api file has no 'router' attribute", plugin["name"])
                continue
            app.include_router(
                router,
                prefix=f"/api/plugins/{plugin['name']}",
                include_in_schema=False,
            )
            _log.info("Mounted plugin API routes: /api/plugins/%s/", plugin["name"])
        except Exception as exc:
            _log.warning("Failed to load plugin %s API routes: %s", plugin["name"], exc)
