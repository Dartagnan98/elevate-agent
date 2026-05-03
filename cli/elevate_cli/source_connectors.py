"""Local real-estate source connector helpers for the Elevate Agent Hub.

This ports the useful ElevateOS source-connector contract into the Python
dashboard runtime.  The hub stays local-first: connectors write normalized
records under a customer tools root and the UI reads those records without
requiring a cloud backend.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
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

JSONL_FILES = (
    "contacts.jsonl",
    "conversations.jsonl",
    "messages.jsonl",
    "lead-events.jsonl",
    "tasks.jsonl",
)

SOURCE_CONNECTION_BLUEPRINTS: tuple[JsonRecord, ...] = (
    {
        "id": "apple-messages",
        "source": "Apple Messages",
        "category": "messages",
        "informationNeeded": "Mac user, included handles, conversation scope, read permission, and reply policy.",
        "connectionLayer": "Local bridge or export writes normalized conversations, messages, lead events, and approval tasks.",
        "uiDestination": "Outreach threads, Leads, Today follow-ups, and approval queues for draft replies.",
        "successSignal": "A synced iMessage/SMS conversation appears as a thread with a lead event and reply-needed task.",
    },
    {
        "id": "sms-provider",
        "source": "SMS Provider",
        "category": "messages",
        "informationNeeded": "Provider name, numbers, webhook/API/export access, contact matching, and send approval policy.",
        "connectionLayer": "Webhook, poller, or import adapter maps provider records into Elevate message and lead files.",
        "uiDestination": "Live lead inbox, Outreach, Today hot replies, and source health in Settings.",
        "successSignal": "A new inbound provider text creates a message record, lead event, and follow-up task without manual copying.",
    },
    {
        "id": "android-device",
        "source": "Android Device SMS",
        "category": "messages",
        "informationNeeded": "Export method, device owner approval, included numbers, backup format, and sync cadence.",
        "connectionLayer": "Optional mobile helper, backup export, or manual import turns device messages into normalized source records.",
        "uiDestination": "Same SMS UI path as provider texts: Outreach, Leads, Today, and approval tasks.",
        "successSignal": "Imported Android messages show source confidence and do not claim live sync unless a helper exists.",
    },
    {
        "id": "rcs",
        "source": "RCS",
        "category": "messages",
        "informationNeeded": "Whether this is business RCS/provider messaging or personal device RCS, plus webhook/export access.",
        "connectionLayer": "Business/provider RCS uses a connector; personal RCS becomes a setup blocker unless export access exists.",
        "uiDestination": "Provider-style message threads and lead events when connected; setup blockers in Settings when not connectable.",
        "successSignal": "RCS is labeled connected, import-only, or blocked instead of being folded into generic SMS.",
    },
    {
        "id": "crm",
        "source": "CRM",
        "category": "leads",
        "informationNeeded": "CRM name, auth method, stage meanings, reliable fields, activity types, and owner mapping.",
        "connectionLayer": "CRM adapter maps contacts, stages, notes, activities, and exposed messages into Elevate records.",
        "uiDestination": "Leads, Deals, Outreach context, Today pipeline, and stale-follow-up queues.",
        "successSignal": "A CRM stage or activity change updates the lead/deal view and creates the right next action.",
    },
    {
        "id": "social",
        "source": "Social DMs",
        "category": "messages",
        "informationNeeded": "Business inboxes, account type, provider/API/export path, lead definition, and reply workflow.",
        "connectionLayer": "Official webhook, provider export, or manual import turns business DMs into conversations and lead events.",
        "uiDestination": "Lead inbox, Outreach, nurture tasks, and approvals for drafted replies.",
        "successSignal": "A qualified DM becomes a lead with channel, source URL, confidence, and an owner task.",
    },
    {
        "id": "email",
        "source": "Email",
        "category": "messages",
        "informationNeeded": "Mailbox, folders/labels, search terms, attachment policy, and storage destination.",
        "connectionLayer": "Read-only mailbox adapter or export importer creates conversations, lead events, and document tasks.",
        "uiDestination": "Leads, Outreach, document intake, admin tasks, and Today reply-needed rows.",
        "successSignal": "A website lead or referral email appears with source thread, summary, and next-step task.",
    },
    {
        "id": "skills",
        "source": "Skill Outputs",
        "category": "operations",
        "informationNeeded": "Skill name, artifact folders, refresh cadence, record shape, and which UI lane should consume it.",
        "connectionLayer": "Artifact reader ingests JSON, JSONL, markdown, PDFs, screenshots, and exports from the tools/data root.",
        "uiDestination": "Listings, Deals, seller updates, market stats, document routing, admin queues, and source activity.",
        "successSignal": "A fresh skill artifact shows in the correct dashboard lane with timestamp, source, and actionability.",
    },
    {
        "id": "market-stats",
        "source": "Market Stats",
        "category": "operations",
        "informationNeeded": "Market regions, property types, stats source, refresh cadence, and client-facing summary needs.",
        "connectionLayer": "Board, MLS, report, CSV, spreadsheet, or manual import writes dashboard-ready stats and artifacts.",
        "uiDestination": "Listings, Deals, Today prep, Ads/Social content, and market-report tasks.",
        "successSignal": "A fresh market artifact appears with period, region, metrics, source files, and next operator step.",
    },
    {
        "id": "admin-requirements",
        "source": "Admin Requirements",
        "category": "admin",
        "informationNeeded": "Jurisdiction, brokerage rules, transaction stages, required forms, deadlines, and human-only checks.",
        "connectionLayer": "Checklist or source import writes required items and generated admin tasks.",
        "uiDestination": "Deals, Today admin queue, Tasks, documents, and approvals.",
        "successSignal": "A deal stage exposes required docs, missing items, deadlines, and owner tasks without hardcoded brokerage rules.",
    },
    {
        "id": "document-storage",
        "source": "Document Storage",
        "category": "admin",
        "informationNeeded": "Storage provider/root, folder naming, document categories, permissions, and dry-run routing policy.",
        "connectionLayer": "Local or cloud indexer writes document-index records and routing tasks.",
        "uiDestination": "Deals, Today admin queue, document intake, and source activity.",
        "successSignal": "A sample document record appears with category, deal/listing match, confidence, status, and next action.",
    },
    {
        "id": "forms-signing",
        "source": "Forms & Signing",
        "category": "forms",
        "informationNeeded": "Form provider, blank forms/templates, recipient roles, field map, and approval policy.",
        "connectionLayer": "Provider-neutral form map and packet index writes dry-run packet records and approval tasks.",
        "uiDestination": "Deals, Today admin queue, approvals, and document routing.",
        "successSignal": "A packet draft appears as a dry-run artifact and every send/signing action is gated behind approval.",
    },
)

OWNER_BY_SOURCE = {
    "apple-messages": "Outreach",
    "sms-provider": "Outreach",
    "android-device": "Outreach",
    "rcs": "Outreach",
    "crm": "Outreach",
    "social": "Outreach",
    "email": "Outreach",
    "skills": "Executive Assistant",
    "market-stats": "Ads",
    "admin-requirements": "Admin",
    "document-storage": "Admin",
    "forms-signing": "Admin",
}

UI_BY_SOURCE = {
    "apple-messages": ["Outreach", "Leads", "Today", "Approvals"],
    "sms-provider": ["Outreach", "Leads", "Today", "Settings"],
    "android-device": ["Outreach", "Leads", "Today", "Approvals"],
    "rcs": ["Outreach", "Leads", "Today", "Settings"],
    "crm": ["Leads", "Deals", "Outreach", "Today"],
    "social": ["Leads", "Outreach", "Social Media", "Approvals"],
    "email": ["Leads", "Outreach", "Documents", "Today"],
    "skills": ["Listings", "Deals", "Documents", "Settings"],
    "market-stats": ["Listings", "Deals", "Ads", "Social Media"],
    "admin-requirements": ["Deals", "Tasks", "Approvals", "Today"],
    "document-storage": ["Deals", "Documents", "Tasks", "Today"],
    "forms-signing": ["Deals", "Approvals", "Documents", "Today"],
}

SOURCE_PROMPT_CATEGORIES = (
    {"id": "all", "label": "All"},
    {"id": "messages", "label": "Messages"},
    {"id": "leads", "label": "Leads"},
    {"id": "operations", "label": "Market"},
    {"id": "admin", "label": "Admin"},
    {"id": "forms", "label": "Forms"},
)

CONNECTION_CONTRACT = """Build this as an Elevate Agent connection layer, not a standalone note:

- Read the customer tools root from sources.tools_root or ELEVATE_TOOLS_ROOT.
- Create or update data/sources/<source-id> inside the customer tools root.
- Write source.json with provider, account_label, connection_type, auth_status, sync_mode, owner_agent, enabled_ui_surfaces, setup_status, last_sync_at, and setup_notes.
- Write status.json with connected, import_only, blocked, last_error, next_operator_step, and last_checked_at.
- Normalize people into contacts.jsonl, threads into conversations.jsonl, inbound/outbound items into messages.jsonl, qualified moments into lead-events.jsonl, and human work into tasks.jsonl.
- Store provider exports, screenshots, PDFs, reports, or raw files under artifacts/.
- Add or document the repeatable connector entrypoint: webhook route, polling command, import command, or local bridge command.

Start read-only. Do not send messages, submit forms, move files, change permissions, upload data, or create persistent API keys unless the operator explicitly approves that action."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _candidate_tools_root(config: dict[str, Any]) -> Path:
    sources_cfg = _as_dict(config.get("sources"))
    integrations_cfg = _as_dict(config.get("integrations"))
    env_root = os.getenv("ELEVATE_TOOLS_ROOT", "").strip()
    configured = str(sources_cfg.get("tools_root") or integrations_cfg.get("tools_root") or "").strip()
    skyleigh_tmp = get_elevate_home() / "tmp" / "skyleigh-tools"
    if env_root:
        return _expand_path(env_root)
    if configured:
        return _expand_path(configured)
    if skyleigh_tmp.exists():
        return skyleigh_tmp
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
    elif (get_elevate_home() / "tmp" / "skyleigh-tools").exists():
        root_source = "detected-skyleigh-tools"
    else:
        root_source = "default-local"

    return {
        "toolsRoot": str(tools_root),
        "toolsRootSource": root_source,
        "toolsRootIo": "local",
        "sourceRoot": str(source_root),
    }


def _source_dir(source_root: Path, source_id: str) -> Path:
    return source_root / source_id


def _read_json(path: Path) -> JsonRecord | None:
    try:
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _write_json(path: Path, value: JsonRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _count_jsonl(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except Exception:
        return 0


def _write_jsonl_if_empty(path: Path, record: JsonRecord) -> None:
    if _count_jsonl(path) > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _state_from_status(source_exists: bool, status: JsonRecord | None) -> str:
    if not source_exists and not status:
        return "not_configured"
    if not status:
        return "needs_operator"
    if status.get("blocked") is True:
        return "blocked"
    if status.get("connected") is True:
        return "connected"
    if status.get("import_only") is True:
        return "import_only"
    if str(status.get("last_error") or "").strip():
        return "error"
    return "needs_operator"


def _blueprint(source_id: str) -> JsonRecord | None:
    return next((item for item in SOURCE_CONNECTION_BLUEPRINTS if item["id"] == source_id), None)


def source_prompt_for(source_id: str) -> str:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return ""
    surfaces = ", ".join(UI_BY_SOURCE.get(source_id, ["Settings"]))
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    return (
        f"You are wiring {blueprint['source']} into Elevate Agent.\n\n"
        f"Connection goal:\nCreate a read-only local source first. Use source_id={source_id}. "
        "If credentials, OAuth, exports, webhook approval, or app review are needed, mark status.json as needs_operator with the exact next step.\n\n"
        f"Information Elevate needs:\n{blueprint['informationNeeded']}\n\n"
        f"{CONNECTION_CONTRACT}\n\n"
        f"Connector behavior:\n- owner_agent={owner}\n- target UI surfaces: {surfaces}\n"
        "- include source_id, source_record_id, source_url when available, display_name, channel, direction, timestamp, text or summary, confidence, tags, and target_ui_surfaces.\n"
        "- put outbound work in tasks.jsonl with approval_required=true unless the operator explicitly authorizes sending.\n\n"
        f"Done when:\n{blueprint['successSignal']}\n"
    )


def connector_view(source_root: Path, source_id: str) -> JsonRecord | None:
    blueprint = _blueprint(source_id)
    if not blueprint:
        return None
    source_dir = _source_dir(source_root, source_id)
    source_path = source_dir / "source.json"
    status_path = source_dir / "status.json"
    artifacts_dir = source_dir / "artifacts"
    source = _read_json(source_path)
    status = _read_json(status_path)
    source_exists = bool(source)
    state = _state_from_status(source_exists, status)
    record_counts = {
        file_name.removesuffix(".jsonl"): _count_jsonl(source_dir / file_name)
        for file_name in JSONL_FILES
    }
    enabled_surfaces = source.get("enabled_ui_surfaces") if isinstance(source, dict) else None
    if not isinstance(enabled_surfaces, list):
        enabled_surfaces = UI_BY_SOURCE.get(source_id, [])
    owner_agent = ""
    if isinstance(source, dict):
        owner_agent = str(source.get("owner_agent") or "").strip()

    return {
        "id": source_id,
        "label": blueprint["source"],
        "category": blueprint.get("category", "operations"),
        "state": state,
        "sourceExists": source_exists,
        "sourceDir": str(source_dir),
        "sourcePath": str(source_path),
        "statusPath": str(status_path),
        "artifactsDir": str(artifacts_dir),
        "connectionType": source.get("connection_type") if isinstance(source, dict) else None,
        "syncMode": source.get("sync_mode") if isinstance(source, dict) else None,
        "authStatus": source.get("auth_status") if isinstance(source, dict) else None,
        "ownerAgent": owner_agent or OWNER_BY_SOURCE.get(source_id, "Executive Assistant"),
        "enabledUiSurfaces": [str(item) for item in enabled_surfaces if str(item).strip()],
        "connected": bool(status and status.get("connected") is True),
        "importOnly": bool(status and status.get("import_only") is True),
        "blocked": bool(status and status.get("blocked") is True),
        "lastError": str(status.get("last_error") or "").strip() if isinstance(status, dict) and status.get("last_error") else None,
        "nextOperatorStep": (
            str(status.get("next_operator_step") or "").strip()
            if isinstance(status, dict) and status.get("next_operator_step")
            else (
                "Initialize this source to create the connector files."
                if state == "not_configured"
                else None
            )
        ),
        "lastCheckedAt": status.get("last_checked_at") if isinstance(status, dict) else None,
        "recordCounts": record_counts,
        "prompt": source_prompt_for(source_id),
    }


def build_source_connectors_response(config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    connectors = [
        view
        for item in SOURCE_CONNECTION_BLUEPRINTS
        if (view := connector_view(source_root, str(item["id"]))) is not None
    ]
    return {
        **info,
        "blueprints": [dict(item, prompt=source_prompt_for(str(item["id"]))) for item in SOURCE_CONNECTION_BLUEPRINTS],
        "promptCategories": list(SOURCE_PROMPT_CATEGORIES),
        "connectors": connectors,
    }


def scaffold_source(source_id: str, config: dict[str, Any] | None = None) -> JsonRecord:
    config = config or load_config()
    blueprint = _blueprint(source_id)
    if not blueprint:
        raise ValueError(f"Unknown source connector: {source_id}")

    info = get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    source_dir = _source_dir(source_root, source_id)
    artifacts_dir = source_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    now = _now()
    surfaces = UI_BY_SOURCE.get(source_id, ["Settings"])
    owner = OWNER_BY_SOURCE.get(source_id, "Executive Assistant")
    _write_json(
        source_dir / "source.json",
        {
            "source_id": source_id,
            "provider": blueprint["source"],
            "account_label": f"{blueprint['source']} local test",
            "connection_type": "manual_import",
            "auth_status": "not_required_for_local_test",
            "sync_mode": "manual",
            "owner_agent": owner,
            "enabled_ui_surfaces": surfaces,
            "setup_status": "import_only",
            "last_sync_at": now,
            "setup_notes": "Local connector scaffold generated from Elevate Agent Settings for testing.",
        },
    )
    _write_json(
        source_dir / "status.json",
        {
            "connected": False,
            "import_only": True,
            "blocked": False,
            "last_error": None,
            "next_operator_step": "Replace this local scaffold with a real webhook, polling command, import command, or local bridge.",
            "last_checked_at": now,
        },
    )

    common = {
        "source_id": source_id,
        "source_url": None,
        "display_name": f"{blueprint['source']} Demo Lead",
        "channel": source_id,
        "confidence": 0.72,
        "tags": ["demo", "connector-test"],
        "target_ui_surfaces": surfaces,
    }
    _write_jsonl_if_empty(source_dir / "contacts.jsonl", {**common, "source_record_id": f"{source_id}-demo-contact"})
    _write_jsonl_if_empty(
        source_dir / "conversations.jsonl",
        {
            **common,
            "source_record_id": f"{source_id}-demo-thread",
            "timestamp": now,
            "summary": "Demo connector conversation created from Settings.",
        },
    )
    _write_jsonl_if_empty(
        source_dir / "messages.jsonl",
        {
            **common,
            "source_record_id": f"{source_id}-demo-message",
            "direction": "inbound",
            "timestamp": now,
            "text": "Demo inbound message for connector testing.",
        },
    )
    _write_jsonl_if_empty(
        source_dir / "lead-events.jsonl",
        {
            **common,
            "source_record_id": f"{source_id}-demo-lead-event",
            "direction": "inbound",
            "timestamp": now,
            "type": "new_lead",
            "summary": "Demo lead event from local connector scaffold.",
        },
    )
    _write_jsonl_if_empty(
        source_dir / "tasks.jsonl",
        {
            "source_id": source_id,
            "source_record_id": f"{source_id}-demo-task",
            "display_name": f"{blueprint['source']} Demo Lead",
            "timestamp": now,
            "title": f"Review {blueprint['source']} connector scaffold",
            "status": "open",
            "approval_required": False,
            "owner_agent": owner,
            "confidence": 0.72,
            "tags": ["demo", "connector-test"],
            "target_ui_surfaces": ["Today", "Settings"],
        },
    )
    view = connector_view(source_root, source_id)
    if view is None:
        raise RuntimeError("Connector scaffold was written but could not be read")
    return view


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


def _merge_crm(raw: Any) -> JsonRecord:
    merged = deepcopy(DEFAULT_CRM)
    raw_dict = _as_dict(raw)
    for key, value in raw_dict.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
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
    return {
        "configPath": str(get_config_path()),
        "secretsPath": str(get_env_path()),
        "sourceRoot": get_source_root_info(config)["sourceRoot"],
        "crm": _crm_to_ui(crm, load_env()),
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
    api_key = str(form.get("apiKey") or load_env().get(env_key) or "")
    base_url = str(crm.get("base_url") or "").rstrip("/")
    leads_path = str(_as_dict(crm.get("endpoints")).get("leads") or "/v1/leads")
    if not base_url:
        return {"success": False, "error": "CRM base URL is required"}
    if not api_key:
        return {"success": False, "error": f"{env_key} is not set"}

    url = f"{base_url}/{leads_path.lstrip('/')}"
    headers = {"Accept": "application/json"}
    if crm.get("auth_type") == "query":
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        query[str(crm.get("auth_query_param") or "api_key")] = [api_key]
        url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
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
