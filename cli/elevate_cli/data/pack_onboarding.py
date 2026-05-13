"""Pack onboarding contracts.

Core and paid packs declare the setup data they need before workflows can run
safely. The desktop setup page uses this module as the single source of truth
for pack-specific onboarding forms, while the runtime can check the same
snapshot before launching pack-owned skills.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from elevate_constants import get_elevate_home
from elevate_cli.access import (
    ENTITLEMENT_CORE,
    ENTITLEMENT_REAL_ESTATE_ADMIN,
    ENTITLEMENT_REAL_ESTATE_CMA,
    ENTITLEMENT_REAL_ESTATE_MARKETING,
    ENTITLEMENT_REAL_ESTATE_SALES,
    is_entitlement_active,
    load_access_config,
)
from elevate_cli.data._util import now_iso
from elevate_cli.data.admin_setup import get_admin_setup


READY_STATUSES = {"configured", "connected", "manual"}
VALID_STATUSES = READY_STATUSES | {"missing", "skipped"}
PACK_ONBOARDING_MEMORY_FILE = "PACK_ONBOARDING.md"


@dataclass(frozen=True)
class PackItemSpec:
    key: str
    category: str
    label: str
    description: str
    env_keys: tuple[str, ...] = ()
    required: bool = True
    sort_order: int = 0


@dataclass(frozen=True)
class PackSpec:
    pack_id: str
    label: str
    entitlement: str
    description: str
    items: tuple[PackItemSpec, ...]


PACK_SPECS: tuple[PackSpec, ...] = (
    PackSpec(
        pack_id=ENTITLEMENT_CORE,
        label="Basic",
        entitlement=ENTITLEMENT_CORE,
        description="Core Elevate runtime, local SQLite data, memory, model provider, messaging gateway, browser-use tools, and updates.",
        items=(
            PackItemSpec("user_profile", "profile", "User profile", "Your name, default assistant name, company, and timezone.", sort_order=10),
            PackItemSpec("model_provider", "model", "Model provider", "Default model/provider for chat, skills, and local agent runs.", ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"), sort_order=20),
            PackItemSpec("memory_embeddings", "memory", "Memory and embeddings", "Local memory store plus embedding provider/model for semantic recall.", ("OPENAI_API_KEY", "OPENAI_EMBEDDING_MODEL", "EMBEDDINGS_API_KEY"), sort_order=30),
            PackItemSpec("messaging_gateway", "communication", "Messaging gateway", "Main Telegram or messaging lane for the Executive Assistant.", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR"), required=False, sort_order=40),
            PackItemSpec("browser_use_tools", "tools", "Browser-use tools", "Browser-use provider and notes for controlled web automation.", ("BROWSER_USE_PROVIDER", "BROWSER_USE_API_KEY"), required=False, sort_order=50),
            PackItemSpec("account_connectors", "accounts", "Account connectors", "Composio and local connectors for Gmail, Calendar, Drive, Docs, and browser workflows.", ("COMPOSIO_API_KEY", "GMAIL_CLIENT_ID", "GOOGLE_DRIVE_ACCOUNT"), required=False, sort_order=60),
            PackItemSpec("local_databases", "storage", "Local SQLite databases", "State, operational, and memory SQLite stores created by the installer.", sort_order=70),
            PackItemSpec("update_channel", "updates", "Update channel", "How this install receives release checks and one-command updates.", ("ELEVATE_UPDATE_CHANNEL", "ELEVATE_BACKEND_URL"), required=False, sort_order=80),
        ),
    ),
    PackSpec(
        pack_id=ENTITLEMENT_REAL_ESTATE_ADMIN,
        label="Admin",
        entitlement=ENTITLEMENT_REAL_ESTATE_ADMIN,
        description="Listing/deal admin, source-of-truth deal files, province docs, approvals, and browser-use portals.",
        items=(
            PackItemSpec("identity_profile", "profile", "Realtor profile", "Legal name, brokerage, team/PREC, and broker contact.", sort_order=10),
            PackItemSpec("jurisdiction", "regional", "Province package", "Country, province, market, and local guide package.", sort_order=20),
            PackItemSpec("approval_channel", "communication", "Admin approval lane", "Dedicated Admin Telegram lane for human approvals.", ("ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL"), sort_order=30),
            PackItemSpec("email", "accounts", "Email", "Gmail or Outlook for seller packages, drafts, and document routing.", ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "OUTLOOK_CLIENT_ID"), sort_order=40),
            PackItemSpec("calendar", "accounts", "Calendar", "Appointments, showing dates, subject removal, completion, possession.", ("GOOGLE_CALENDAR_ACCOUNT", "OUTLOOK_CALENDAR_ACCOUNT"), sort_order=50),
            PackItemSpec("drive", "accounts", "Cloud storage", "Drive, Dropbox, OneDrive, or SharePoint transaction folders.", ("GOOGLE_DRIVE_ACCOUNT", "DROPBOX_ACCESS_TOKEN", "ONEDRIVE_ACCOUNT"), sort_order=60),
            PackItemSpec("crm", "accounts", "CRM / lead source", "Stable contact IDs, phones, emails, and pipeline stages.", ("CRM_API_KEY", "LOFTY_API_KEY", "FOLLOWUPBOSS_API_KEY", "SIERRA_API_KEY"), sort_order=70),
            PackItemSpec("mls", "accounts", "MLS / board portal", "Matrix, Xposure, Paragon, Pillar9, or local MLS access.", ("MLS_LOGIN_URL", "MLS_USERNAME", "MATRIX_USERNAME", "XPOSURE_USERNAME"), sort_order=80),
            PackItemSpec("forms_provider", "providers", "Forms provider", "WEBForms, TransactionDesk, brokerage forms, or local form library.", ("FORMS_LOGIN_URL", "WEBFORMS_USERNAME"), sort_order=90),
            PackItemSpec("signing_provider", "providers", "Signing provider", "DigiSign, DocuSign, Authentisign, or another e-sign provider.", ("SIGNING_LOGIN_URL", "DIGISIGN_USERNAME", "DOCUSIGN_ACCOUNT_ID"), sort_order=100),
            PackItemSpec("compliance_platform", "providers", "Compliance platform", "SkySlope, Lone Wolf, dotloop, or brokerage admin portal.", ("COMPLIANCE_LOGIN_URL", "SKYSLOPE_USERNAME", "SKYSLOPE_API_KEY"), sort_order=110),
            PackItemSpec("showing_platform", "providers", "Showing feedback", "ShowingTime, BrokerBay, Touchbase, or manual showing feedback.", ("SHOWING_LOGIN_URL", "SHOWINGTIME_USERNAME", "BROKERBAY_API_KEY"), sort_order=120),
            PackItemSpec("browser_workflows", "providers", "Browser-use portal playbooks", "Login URLs, credential refs, and run notes for MLS, compliance, and showing portals.", ("BROWSER_USE_PROVIDER",), sort_order=125),
            PackItemSpec("photo_processing", "providers", "Photo processing", "Drive/Dropbox source plus Higgsfield, Nano Banana, or manual photo cleanup workflow.", ("PHOTO_SOURCE_ROOT", "HIGGSFIELD_API_KEY", "NANO_BANANA_API_KEY"), sort_order=127),
            PackItemSpec("regional_memory", "regional", "Regional admin memory", "Province docs, deposit rules, local property sources, and MLS quirks.", sort_order=140),
        ),
    ),
    PackSpec(
        pack_id=ENTITLEMENT_REAL_ESTATE_SALES,
        label="Leads",
        entitlement=ENTITLEMENT_REAL_ESTATE_SALES,
        description="Lead inbox, profile matching, buyer searches, follow-ups, skipped/hot lead queues, and handoff to Admin.",
        items=(
            PackItemSpec("crm_source", "accounts", "CRM / lead database", "Where leads, profiles, conversations, and pipeline status come from.", ("CRM_API_KEY", "LOFTY_API_KEY", "FOLLOWUPBOSS_API_KEY", "SIERRA_API_KEY"), sort_order=10),
            PackItemSpec("message_sources", "accounts", "Message sources", "Email, SMS, Instagram, WhatsApp, or CRM messages that populate conversations.", ("GMAIL_CLIENT_ID", "TWILIO_ACCOUNT_SID", "META_ACCESS_TOKEN", "WHATSAPP_TOKEN"), sort_order=20),
            PackItemSpec("identity_verifiers", "matching", "Identity verifiers", "Phone and email rules used to match conversations to profiles safely.", sort_order=30),
            PackItemSpec("buyer_search_sources", "buyer-search", "Buyer search sources", "Saved searches, MLS criteria, and local search providers.", ("MLS_LOGIN_URL", "MLS_USERNAME"), sort_order=40),
            PackItemSpec("followup_rules", "automation", "Follow-up rules", "When to draft, skip, revive, or ask for human approval.", sort_order=50),
            PackItemSpec("admin_handoff", "handoff", "Admin handoff", "How qualified buyers/sellers are pushed to Admin workflows.", sort_order=60),
        ),
    ),
    PackSpec(
        pack_id=ENTITLEMENT_REAL_ESTATE_MARKETING,
        label="Marketing",
        entitlement=ENTITLEMENT_REAL_ESTATE_MARKETING,
        description="Seller packages, listing launch marketing, seller updates, social drafts, and asset routing.",
        items=(
            PackItemSpec("brand_profile", "brand", "Brand profile", "Agent bio, value proposition, tone, logos, and standard disclaimers.", sort_order=10),
            PackItemSpec("email_drafts", "accounts", "Email draft account", "Gmail or Outlook account where seller packages and updates are drafted.", ("GMAIL_CLIENT_ID", "OUTLOOK_CLIENT_ID"), sort_order=20),
            PackItemSpec("social_scheduler", "accounts", "Social scheduler", "Ayrshare, Buffer, Meta, or manual queue used for social drafts.", ("AYRSHARE_API_KEY", "BUFFER_ACCESS_TOKEN", "META_ACCESS_TOKEN"), sort_order=30),
            PackItemSpec("asset_storage", "assets", "Marketing asset storage", "Drive/Dropbox folder for photos, captions, graphics, and seller-update PDFs.", ("GOOGLE_DRIVE_ACCOUNT", "DROPBOX_ACCESS_TOKEN", "MARKETING_ASSET_ROOT"), sort_order=40),
            PackItemSpec("listing_media_source", "assets", "Listing media source", "Where approved photos, video, floorplans, and feature sheets are pulled from.", ("PHOTO_SOURCE_ROOT", "LISTING_MEDIA_ROOT"), sort_order=50),
            PackItemSpec("approval_lane", "communication", "Marketing approval lane", "Where drafts are sent before anything client-visible is sent.", ("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL",), sort_order=60),
        ),
    ),
    PackSpec(
        pack_id=ENTITLEMENT_REAL_ESTATE_CMA,
        label="CMA",
        entitlement=ENTITLEMENT_REAL_ESTATE_CMA,
        description="CMA pricing workflow, MLS comparable research, report generation, and approval before client delivery.",
        items=(
            PackItemSpec("mls_cma_source", "accounts", "MLS/CMA source", "MLS portal, Cloud CMA, or local comp source used for valuation.", ("MLS_LOGIN_URL", "MLS_USERNAME", "CLOUD_CMA_API_KEY"), sort_order=10),
            PackItemSpec("pricing_rules", "analysis", "Pricing rules", "Agent pricing preferences, adjustment notes, and local comp assumptions.", sort_order=20),
            PackItemSpec("report_template", "documents", "Report template", "CMA report style, disclaimers, agent branding, and export destination.", ("CMA_TEMPLATE_PATH", "CMA_OUTPUT_ROOT"), sort_order=30),
            PackItemSpec("approval_lane", "communication", "CMA approval lane", "Where the draft CMA goes before client delivery.", ("ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL",), sort_order=40),
        ),
    ),
)


def _encode_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _decode_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _ready(status: Any) -> bool:
    return str(status or "").strip() in READY_STATUSES


def _redact(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    secret_value = re.compile(
        r"(\b\d{6,}:[A-Za-z0-9_-]{20,}\b"
        r"|\b(?:sk|ghp|github_pat|xox[baprs]|AIza|ya29)[A-Za-z0-9_.-]{12,}\b"
        r"|\b[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b)",
        re.IGNORECASE,
    )
    if secret_value.search(text):
        return "[redacted secret reference]"
    return text


def _ensure_seeded(conn: sqlite3.Connection) -> None:
    now = now_iso()
    for pack in PACK_SPECS:
        conn.execute(
            """
            INSERT OR IGNORE INTO pack_onboarding_profiles(
                pack_id, label, entitlement, description, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pack.pack_id, pack.label, pack.entitlement, pack.description, now, now),
        )
        for item in pack.items:
            conn.execute(
                """
                INSERT OR IGNORE INTO pack_onboarding_items(
                    pack_id, key, category, label, description, required,
                    env_keys_json, sort_order, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack.pack_id,
                    item.key,
                    item.category,
                    item.label,
                    item.description,
                    1 if item.required else 0,
                    _encode_json(list(item.env_keys)),
                    item.sort_order,
                    now,
                ),
            )


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "packId": row["pack_id"],
        "key": row["key"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "required": bool(row["required"]),
        "status": row["status"],
        "provider": row["provider"],
        "envKeys": _decode_json(row["env_keys_json"]) or [],
        "value": _decode_json(row["value_json"]),
        "notes": row["notes"],
        "sortOrder": row["sort_order"],
        "updatedAt": row["updated_at"],
    }


def _admin_items_for_snapshot(conn: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        admin = get_admin_setup(conn)
    except Exception:
        return {}, {}
    by_key = {
        item.get("key"): item
        for item in admin.get("items", [])
        if isinstance(item, Mapping) and item.get("key")
    }
    return admin, by_key


def _env_present(*keys: str) -> list[str]:
    try:
        from elevate_cli.config import get_env_value
    except Exception:
        return []
    present: list[str] = []
    for key in keys:
        try:
            if _clean_text(get_env_value(key)):
                present.append(key)
        except Exception:
            continue
    return present


def _core_items_for_snapshot() -> dict[str, dict[str, Any]]:
    """Return runtime-proven Basic setup values without mutating SQLite."""
    try:
        from elevate_cli.config import load_config

        config = load_config()
    except Exception:
        config = {}

    home = get_elevate_home()
    now = now_iso()
    updates: dict[str, dict[str, Any]] = {}

    def configured(
        key: str,
        provider: str,
        *,
        value: Mapping[str, Any] | None = None,
        notes: str | None = None,
    ) -> None:
        updates[key] = {
            "status": "configured",
            "provider": provider,
            "value": dict(value or {}),
            "notes": notes,
            "updatedAt": now,
            "source": "runtime",
        }

    configured(
        "user_profile",
        "Local Elevate profile",
        value={"elevateHome": str(home), "source": "runtime"},
        notes="Detected local Elevate home.",
    )

    model_cfg = config.get("model") if isinstance(config, Mapping) else None
    provider = ""
    model = ""
    if isinstance(model_cfg, Mapping):
        provider = str(model_cfg.get("provider") or model_cfg.get("inference_provider") or "").strip()
        model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
    elif isinstance(model_cfg, str):
        model = model_cfg.strip()
    model_env = _env_present("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
    if provider or model or model_env:
        configured(
            "model_provider",
            provider or "configured model provider",
            value={"provider": provider, "model": model, "env": model_env},
        )

    memory_cfg = config.get("memory") if isinstance(config, Mapping) else None
    memory_db = home / "memory_store.db"
    embedding_env = _env_present("OPENAI_API_KEY", "OPENAI_EMBEDDING_MODEL", "EMBEDDINGS_API_KEY")
    memory_enabled = isinstance(memory_cfg, Mapping) and bool(memory_cfg.get("enabled", True))
    if memory_enabled or memory_db.exists() or embedding_env:
        configured(
            "memory_embeddings",
            "Local memory",
            value={"memoryDb": str(memory_db), "memoryDbExists": memory_db.exists(), "env": embedding_env},
        )

    gateway_env = _env_present("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR")
    if gateway_env:
        configured(
            "messaging_gateway",
            "Telegram",
            value={"env": gateway_env},
        )

    browser_env = _env_present("BROWSER_USE_PROVIDER", "BROWSER_USE_API_KEY")
    if browser_env:
        configured("browser_use_tools", "Browser Use", value={"env": browser_env})

    connector_env = _env_present("COMPOSIO_API_KEY", "GMAIL_CLIENT_ID", "GOOGLE_DRIVE_ACCOUNT")
    if connector_env:
        configured("account_connectors", "Configured connector env", value={"env": connector_env})

    state_db = home / "state.db"
    operational_db = home / "data" / "operational.db"
    if state_db.exists() and operational_db.exists():
        configured(
            "local_databases",
            "SQLite",
            value={
                "stateDb": str(state_db),
                "operationalDb": str(operational_db),
                "memoryDb": str(memory_db),
                "memoryDbExists": memory_db.exists(),
            },
        )

    update_env = _env_present("ELEVATE_UPDATE_CHANNEL", "ELEVATE_BACKEND_URL")
    configured(
        "update_channel",
        "Elevate update",
        value={"env": update_env, "command": "elevate update"},
        notes="One-command update path is available from the local CLI.",
    )
    return updates


def get_pack_onboarding(
    conn: sqlite3.Connection,
    *,
    access_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return onboarding state for every known pack."""
    _ensure_seeded(conn)
    access = dict(access_config) if isinstance(access_config, Mapping) else load_access_config()
    rows = conn.execute("SELECT * FROM pack_onboarding_profiles").fetchall()
    profile_rows = {row["pack_id"]: row for row in rows}
    item_rows = conn.execute(
        "SELECT * FROM pack_onboarding_items ORDER BY pack_id ASC, sort_order ASC, key ASC"
    ).fetchall()
    items_by_pack: dict[str, list[dict[str, Any]]] = {}
    for row in item_rows:
        items_by_pack.setdefault(row["pack_id"], []).append(_row_to_item(row))

    admin_setup, admin_items = _admin_items_for_snapshot(conn)
    core_items = _core_items_for_snapshot()
    packs: list[dict[str, Any]] = []
    for spec in PACK_SPECS:
        row = profile_rows.get(spec.pack_id)
        unlocked = is_entitlement_active(spec.entitlement, access)
        items = items_by_pack.get(spec.pack_id, [])
        if spec.pack_id == ENTITLEMENT_CORE and core_items:
            merged = []
            for item in items:
                source = core_items.get(item["key"])
                if source and not _ready(item.get("status")):
                    merged.append({**item, **source})
                else:
                    merged.append(item)
            items = merged
        elif spec.pack_id == ENTITLEMENT_REAL_ESTATE_ADMIN and admin_items:
            merged: list[dict[str, Any]] = []
            for item in items:
                source = admin_items.get(item["key"])
                if source:
                    merged.append(
                        {
                            **item,
                            "status": source.get("status") or item["status"],
                            "provider": source.get("provider") or item.get("provider"),
                            "value": source.get("value") if source.get("value") is not None else item.get("value"),
                            "notes": source.get("notes") or item.get("notes"),
                            "updatedAt": source.get("updatedAt") or item["updatedAt"],
                            "source": "admin_setup",
                        }
                    )
                else:
                    merged.append(item)
            items = merged
        required = [item for item in items if item.get("required")]
        complete_required = [item for item in required if _ready(item.get("status"))]
        missing = [item for item in required if not _ready(item.get("status"))]
        table_complete = bool(required) and len(complete_required) == len(required)
        if spec.pack_id == ENTITLEMENT_REAL_ESTATE_ADMIN:
            complete = bool(admin_setup.get("complete")) or table_complete
        else:
            complete = table_complete
        completed_at = row["completed_at"] if row else None
        packs.append(
            {
                "packId": spec.pack_id,
                "label": spec.label,
                "entitlement": spec.entitlement,
                "description": spec.description,
                "unlocked": bool(unlocked),
                "status": row["status"] if row else "missing",
                "complete": bool(complete),
                "launchRequired": bool(unlocked and not complete),
                "requiredCount": len(required),
                "completedRequiredCount": len(complete_required),
                "missingRequiredKeys": [item["key"] for item in missing],
                "completionPct": round((len(complete_required) / len(required)) * 100) if required else 100,
                "completedAt": completed_at,
                "updatedAt": row["updated_at"] if row else None,
                "items": items,
            }
        )
    active = [pack for pack in packs if pack["unlocked"]]
    required_active = [pack for pack in active if pack["launchRequired"]]
    memory_path = _pack_onboarding_memory_path()
    return {
        "packs": packs,
        "activeCount": len(active),
        "completedActiveCount": len([pack for pack in active if pack["complete"]]),
        "launchRequiredPacks": [pack["packId"] for pack in required_active],
        "complete": len(required_active) == 0,
        "memory": {"path": str(memory_path), "synced": memory_path.exists()},
    }


def update_pack_onboarding(
    conn: sqlite3.Connection,
    pack_id: str,
    *,
    items: Iterable[Mapping[str, Any]] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    del actor
    _ensure_seeded(conn)
    if not conn.execute("SELECT pack_id FROM pack_onboarding_profiles WHERE pack_id=?", (pack_id,)).fetchone():
        raise LookupError(f"unknown onboarding pack {pack_id!r}")
    now = now_iso()
    if items:
        for item in items:
            key = str(item.get("key") or "").strip()
            if not key:
                raise ValueError("pack onboarding item key is required")
            exists = conn.execute(
                "SELECT key FROM pack_onboarding_items WHERE pack_id=? AND key=?",
                (pack_id, key),
            ).fetchone()
            if exists is None:
                raise LookupError(f"pack onboarding item {pack_id}:{key} not found")
            status = str(item.get("status") or "missing").strip()
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid pack onboarding status {status!r}")
            conn.execute(
                """
                UPDATE pack_onboarding_items
                SET status=?, provider=?, value_json=?, notes=?, updated_at=?
                WHERE pack_id=? AND key=?
                """,
                (
                    status,
                    _clean_text(item.get("provider")),
                    _encode_json(item.get("value")),
                    _clean_text(item.get("notes")),
                    now,
                    pack_id,
                    key,
                ),
            )
    conn.execute(
        """
        UPDATE pack_onboarding_profiles
        SET status=?, updated_at=?
        WHERE pack_id=?
        """,
        ("configured", now, pack_id),
    )
    snapshot = get_pack_onboarding(conn)
    memory = sync_pack_onboarding_memory(snapshot)
    snapshot["memory"] = {**snapshot.get("memory", {}), **memory, "synced": True}
    return snapshot


def complete_pack_onboarding(
    conn: sqlite3.Connection,
    pack_id: str,
    *,
    actor: str = "human",
) -> dict[str, Any]:
    del actor
    snapshot = get_pack_onboarding(conn)
    pack = next((item for item in snapshot["packs"] if item["packId"] == pack_id), None)
    if pack is None:
        raise LookupError(f"unknown onboarding pack {pack_id!r}")
    if pack.get("missingRequiredKeys"):
        raise ValueError(
            f"{pack.get('label') or pack_id} onboarding is missing required items: "
            + ", ".join(pack["missingRequiredKeys"])
        )
    now = now_iso()
    conn.execute(
        """
        UPDATE pack_onboarding_profiles
        SET status='configured', completed_at=COALESCE(completed_at, ?), updated_at=?
        WHERE pack_id=?
        """,
        (now, now, pack_id),
    )
    snapshot = get_pack_onboarding(conn)
    memory = sync_pack_onboarding_memory(snapshot)
    snapshot["memory"] = {**snapshot.get("memory", {}), **memory, "synced": True}
    return snapshot


def _pack_onboarding_memory_path() -> Path:
    return get_elevate_home() / "memories" / PACK_ONBOARDING_MEMORY_FILE


def pack_onboarding_memory_summary(snapshot: Mapping[str, Any]) -> str:
    lines = [
        "# Pack onboarding memory",
        "",
        "This file is generated from SQLite pack onboarding. SQLite operational.db remains the source of truth; use this as durable recall so agents do not ask for the same pack setup details again.",
        "",
    ]
    packs = snapshot.get("packs") if isinstance(snapshot.get("packs"), list) else []
    for pack in packs:
        if not isinstance(pack, Mapping) or not pack.get("unlocked"):
            continue
        lines.extend(
            [
                f"## {_redact(pack.get('label')) or pack.get('packId')}",
                f"- Complete: {'yes' if pack.get('complete') else 'no'}",
                f"- Missing: {', '.join(pack.get('missingRequiredKeys') or []) or 'none'}",
            ]
        )
        for item in pack.get("items") or []:
            if not isinstance(item, Mapping) or not item.get("provider"):
                continue
            lines.append(
                f"- {item.get('label') or item.get('key')}: {_redact(item.get('provider'))}"
            )
        lines.append("")
    lines.append("- Never include raw passwords, API keys, bot tokens, or OAuth secrets in chat. Use env vars or credential references.")
    return "\n".join(lines).strip() + "\n"


def sync_pack_onboarding_memory(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    path = _pack_onboarding_memory_path()
    content = pack_onboarding_memory_summary(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".pack_onboarding_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return {"path": str(path), "bytes": len(content.encode("utf-8"))}


def pack_onboarding_ready(conn: sqlite3.Connection, pack_id: str) -> bool:
    snapshot = get_pack_onboarding(conn)
    pack = next((item for item in snapshot["packs"] if item["packId"] == pack_id), None)
    return bool(pack and pack.get("complete"))
