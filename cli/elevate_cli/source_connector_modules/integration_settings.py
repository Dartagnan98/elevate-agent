"""CRM integration settings helpers for source connectors."""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

from elevate_cli.config import (
    get_config_path,
    get_elevate_home,
    get_env_path,
    load_config,
    load_env,
    save_config,
    save_env_value,
)


JsonRecord = dict[str, Any]


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _candidate_tools_root(config: dict[str, Any]) -> Path:
    sources_cfg = _as_dict(config.get("sources"))
    integrations_cfg = _as_dict(config.get("integrations"))
    env_root = os.getenv("ELEVATE_TOOLS_ROOT", "").strip()
    configured = str(sources_cfg.get("tools_root") or integrations_cfg.get("tools_root") or "").strip()
    client_tools_tmp = get_elevate_home() / "tmp" / "client-tools"
    if env_root:
        return _expand_path(env_root)
    if configured:
        return _expand_path(configured)
    if client_tools_tmp.exists():
        return client_tools_tmp
    return get_elevate_home() / "tools"


def get_source_root_info(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    sources_cfg = _as_dict(config.get("sources"))
    tools_root = _candidate_tools_root(config)
    source_root = tools_root / "data" / "sources"
    if os.getenv("ELEVATE_TOOLS_ROOT", "").strip():
        root_source = "env"
    elif sources_cfg.get("tools_root"):
        root_source = "config"
    elif (get_elevate_home() / "tmp" / "client-tools").exists():
        root_source = "detected-client-tools"
    else:
        root_source = "default-local"

    return {
        "toolsRoot": str(tools_root),
        "toolsRootSource": root_source,
        "toolsRootIo": "local",
        "sourceRoot": str(source_root),
    }


def _combined_env(config: dict[str, Any]) -> dict[str, str]:
    values = dict(load_env())
    tools_env = _candidate_tools_root(config) / ".env"
    try:
        if tools_env.exists():
            for line in tools_env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key and key not in values:
                    values[key] = value.strip().strip("\"'")
    except Exception:
        pass
    return values


def _configured_composio_server(config: dict[str, Any]) -> JsonRecord | None:
    servers = _as_dict(config.get("mcp_servers"))
    for name, raw_server in servers.items():
        server = _as_dict(raw_server)
        args = server.get("args")
        haystack_parts = [
            str(name),
            str(server.get("url") or ""),
            str(server.get("command") or ""),
            " ".join(str(item) for item in args) if isinstance(args, list) else str(args or ""),
        ]
        if "composio" not in " ".join(haystack_parts).lower():
            continue
        return {
            "name": str(name),
            "transport": "http" if server.get("url") else "stdio",
            "url": str(server.get("url") or ""),
            "command": str(server.get("command") or ""),
        }
    return None


def _basic_auth_header(api_key: str) -> str:
    encoded = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


DEFAULT_CRM = {
    "provider": "custom",
    "label": "CRM",
    "api_key_env": "CRM_API_KEY",
    "base_url": "",
    "auth_type": "header",
    "auth_header": "Authorization",
    "auth_prefix": "Bearer ",
    "auth_query_param": "api_key",
    "db_columns": {
        "lead_id": "crm_lead_id",
        "stage": "crm_stage",
        "tags": "crm_tags",
    },
    "endpoints": {
        "leads": "/v1/leads",
        "lead": "/v1/leads/:id",
        "notes": "/v1/leads/:id/notes",
    },
}


_CRM_PROVIDER_ALIASES = {
    "lofty": "lofty",
    "lofty crm": "lofty",
    "loftycrm": "lofty",
    "chime": "lofty",  # Chime → Lofty rebrand
    "follow up boss": "followupboss",
    "followupboss": "followupboss",
    "follow up boss crm": "followupboss",
    "fub": "followupboss",
    "sierra": "sierra",
    "sierra interactive": "sierra",
    "boldtrail": "boldtrail",
    "bold trail": "boldtrail",
    "kvcore": "boldtrail",  # kvCORE → BoldTrail rebrand
    "kvcore / boldtrail": "boldtrail",
    "brivity": "brivity",
}


def _canonical_crm_provider(raw: Any) -> str:
    """Normalize whatever provider was picked at onboarding (or in config) to a
    canonical slug the crm_* write functions branch on. Tolerates display forms
    like "Lofty CRM" / "Sierra Interactive". Returns "" when nothing is set —
    we NEVER assume a default provider."""
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    if s in _CRM_PROVIDER_ALIASES:
        return _CRM_PROVIDER_ALIASES[s]
    # Tolerate a trailing "crm" suffix ("lofty crm", "loftycrm") before lookup.
    trimmed = s[:-3].strip() if s.endswith("crm") else s
    if trimmed in _CRM_PROVIDER_ALIASES:
        return _CRM_PROVIDER_ALIASES[trimmed]
    return trimmed.replace(" ", "")


_CRM_PROVIDER_ENV_DEFAULTS = {
    "lofty": "LOFTY_API_KEY",
    "followupboss": "FUB_API_KEY",
    "sierra": "SIERRA_API_KEY",
    "boldtrail": "BOLDTRAIL_API_KEY",
    "brivity": "BRIVITY_API_KEY",
}


def _provider_from_admin_profile() -> str:
    """Read admin_setup_profile.crm_provider and normalize to canonical slug.

    Returns "" if the admin profile is empty or unreadable. Never raises —
    this is a soft overlay on top of config.yaml. Reads from the Postgres
    operational store via the standard data layer (was reading the legacy
    SQLite operational.db directly until the PG cutover).
    """
    try:
        from elevate_cli.data import connect as _data_connect
    except Exception:
        return ""
    try:
        with _data_connect() as con:
            cur = con.execute(
                "SELECT crm_provider FROM admin_setup_profile WHERE id = %s",
                ("default",),
            )
            row = cur.fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    # Row may be a tuple or a Row-like depending on cursor settings.
    raw_val = row[0] if not hasattr(row, "keys") else row["crm_provider"]
    return _canonical_crm_provider(raw_val)


def _merge_crm(raw: Any) -> JsonRecord:
    merged = deepcopy(DEFAULT_CRM)
    raw_dict = _as_dict(raw)
    for key, value in raw_dict.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    # Auto-resolve provider from admin onboarding when config is still the
    # default ("custom") or empty. The user already told the wizard which
    # CRM they use — don't make them edit yaml.
    config_provider = str(merged.get("provider") or "").strip().lower()
    if config_provider in {"", "custom"}:
        admin_provider = _provider_from_admin_profile()
        if admin_provider:
            merged["provider"] = admin_provider
            # Derive the env var name unless the config explicitly set one.
            if str(merged.get("api_key_env") or "CRM_API_KEY") == "CRM_API_KEY":
                env_default = _CRM_PROVIDER_ENV_DEFAULTS.get(admin_provider)
                if env_default:
                    merged["api_key_env"] = env_default
    return merged


def _crm_to_ui(crm: JsonRecord, env_values: dict[str, str]) -> JsonRecord:
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    key_value = env_values.get(env_key) or ""
    return {
        "provider": str(crm.get("provider") or "custom"),
        "label": str(crm.get("label") or "CRM"),
        "apiKeyEnv": env_key,
        "hasApiKey": bool(key_value),
        "apiKeyPreview": f"{key_value[:4]}...{key_value[-4:]}" if len(key_value) > 8 else ("set" if key_value else None),
        "baseUrl": str(crm.get("base_url") or ""),
        "authType": str(crm.get("auth_type") or "header"),
        "authHeader": str(crm.get("auth_header") or "Authorization"),
        "authPrefix": str(crm.get("auth_prefix") or "Bearer "),
        "authQueryParam": str(crm.get("auth_query_param") or "api_key"),
        "dbColumns": {
            "leadId": str(_as_dict(crm.get("db_columns")).get("lead_id") or "crm_lead_id"),
            "stage": str(_as_dict(crm.get("db_columns")).get("stage") or "crm_stage"),
            "tags": str(_as_dict(crm.get("db_columns")).get("tags") or "crm_tags"),
        },
        "endpoints": {
            "leads": str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads"),
            "lead": str(_as_dict(crm.get("endpoints")).get("lead") or "/v1/leads/:id"),
            "notes": str(_as_dict(crm.get("endpoints")).get("notes") or "/v1/leads/:id/notes"),
        },
    }


def get_integration_settings(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    integrations = _as_dict(config.get("integrations"))
    crm = _merge_crm(integrations.get("crm"))
    env_values = _combined_env(config)
    if env_values.get("LOFTY_API_KEY") and not str(crm.get("base_url") or "").strip():
        crm.update(
            {
                "provider": "lofty",
                "label": "Lofty CRM",
                "api_key_env": "LOFTY_API_KEY",
                "base_url": "https://api.lofty.com",
                "auth_type": "header",
                "auth_header": "Authorization",
                "auth_prefix": "token ",
                "endpoints": {
                    **_as_dict(crm.get("endpoints")),
                    "leads": "/v1.0/leads",
                    "lead": "/v1.0/leads/:id",
                    "notes": "/v2.0/leads/:id/activities",
                },
            }
        )
    return {
        "configPath": str(get_config_path()),
        "secretsPath": str(get_env_path()),
        "sourceRoot": get_source_root_info(config)["sourceRoot"],
        "crm": _crm_to_ui(crm, env_values),
    }


def _ui_crm_to_config(form: JsonRecord) -> JsonRecord:
    db_columns = _as_dict(form.get("dbColumns"))
    endpoints = _as_dict(form.get("endpoints"))
    return {
        "provider": str(form.get("provider") or "custom"),
        "label": str(form.get("label") or "CRM"),
        "api_key_env": str(form.get("apiKeyEnv") or "CRM_API_KEY"),
        "base_url": str(form.get("baseUrl") or "").rstrip("/"),
        "auth_type": str(form.get("authType") or "header"),
        "auth_header": str(form.get("authHeader") or "Authorization"),
        "auth_prefix": str(form.get("authPrefix") or "Bearer "),
        "auth_query_param": str(form.get("authQueryParam") or "api_key"),
        "db_columns": {
            "lead_id": str(db_columns.get("leadId") or "crm_lead_id"),
            "stage": str(db_columns.get("stage") or "crm_stage"),
            "tags": str(db_columns.get("tags") or "crm_tags"),
        },
        "endpoints": {
            "leads": str(endpoints.get("leads") or "/v1/leads"),
            "lead": str(endpoints.get("lead") or "/v1/leads/:id"),
            "notes": str(endpoints.get("notes") or "/v1/leads/:id/notes"),
        },
    }


def save_integration_settings(form: JsonRecord) -> JsonRecord:
    config = load_config()
    next_config = deepcopy(config)
    next_config.setdefault("integrations", {})
    next_config["integrations"]["crm"] = _ui_crm_to_config(form)
    api_key = str(form.get("apiKey") or "")
    if api_key:
        save_env_value(str(next_config["integrations"]["crm"]["api_key_env"]), api_key)
    save_config(next_config)
    return get_integration_settings(load_config())


def test_crm_connection(form: JsonRecord) -> JsonRecord:
    crm = _ui_crm_to_config(form)
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(form.get("apiKey") or _combined_env(load_config()).get(env_key) or "")
    base_url = str(crm.get("base_url") or "").rstrip("/")
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")
    if not base_url:
        return {"success": False, "error": "CRM base URL is required"}
    if not api_key:
        return {"success": False, "error": f"{env_key} is not set"}

    url = f"{base_url}/{leads_path.lstrip('/')}"
    headers = {"Accept": "application/json"}
    auth_type = str(crm.get("auth_type") or "header").lower()
    if auth_type == "query":
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        query[str(crm.get("auth_query_param") or "api_key")] = [api_key]
        url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
    elif auth_type == "basic":
        headers["Authorization"] = _basic_auth_header(api_key)
    else:
        headers[str(crm.get("auth_header") or "Authorization")] = f"{crm.get('auth_prefix') or ''}{api_key}"

    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1024 * 1024)
            status = response.status
        parsed = json.loads(raw.decode("utf-8") or "{}")
        count = 0
        if isinstance(parsed, list):
            count = len(parsed)
        elif isinstance(parsed, dict):
            for key in ("leads", "data", "items", "results", "records"):
                value = parsed.get(key)
                if isinstance(value, list):
                    count = len(value)
                    break
        return {"success": True, "status": status, "message": f"Connection worked. Saw {count} lead record(s)."}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
