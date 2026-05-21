"""Admin setup readiness helpers.

The Admin board should not launch deal automation until the realtor has told
Elevate which accounts, providers, province package, and approval lane to use.
This module owns that singleton readiness profile in operational.db.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from elevate_constants import get_elevate_home
from elevate_cli.data._util import now_iso

_log = logging.getLogger(__name__)


PROFILE_ID = "default"
READY_STATUSES = {"configured", "connected", "manual"}
VALID_STATUSES = READY_STATUSES | {"missing", "skipped"}
VERIFICATION_REQUIRED_KEYS: set[str] = set()
BROWSER_WORKFLOW_REQUIRED_KEYS = ("mls", "compliance", "showing")
ADMIN_ONBOARDING_MEMORY_FILE = "ADMIN_ONBOARDING.md"
ADMIN_PROVINCE_PLAYBOOK_FILE = "ADMIN_PROVINCE_PLAYBOOK.md"

PROVINCE_TERMINOLOGY: dict[str, dict[str, str]] = {
    "BC": {
        "label": "British Columbia",
        "regulator": "BC Financial Services Authority (BCFSA)",
        "listingContract": "Multiple Listing Contract (MLC)",
        "buyerContract": "Exclusive Buyer Agency Agreement (EBA)",
        "offer": "Contract of Purchase and Sale (CPS)",
        "disclosure": "Property Disclosure Statement (PDS)",
        "conditionTerm": "subjects",
        "conditionRemoval": "Subject Removal / Notice to Remove Subjects",
        "lawyerRole": "lawyer or notary",
        "depositRule": "deposit due within 24 hours of subject removal unless the CPS states otherwise",
        "complianceBoard": "DLC / paragon-style local board portal",
    },
    "AB": {
        "label": "Alberta",
        "regulator": "Real Estate Council of Alberta (RECA)",
        "listingContract": "Exclusive Seller Representation Agreement",
        "buyerContract": "Exclusive Buyer Representation Agreement",
        "offer": "Residential Real Estate Purchase Contract",
        "disclosure": "Real Property Report (RPR) + Compliance",
        "conditionTerm": "conditions",
        "conditionRemoval": "Condition Removal / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit timing per contract — confirm trust deposit with brokerage",
        "complianceBoard": "Pillar 9 / local board portal",
    },
    "SK": {
        "label": "Saskatchewan",
        "regulator": "Saskatchewan Real Estate Commission (SREC)",
        "listingContract": "Exclusive Seller Representation Agreement",
        "buyerContract": "Exclusive Buyer Representation Agreement",
        "offer": "Contract of Purchase and Sale",
        "disclosure": "Property Condition Disclosure Statement (PCDS)",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per contract; confirm brokerage trust schedule",
        "complianceBoard": "Saskatoon Region / Regina MLS portal",
    },
    "MB": {
        "label": "Manitoba",
        "regulator": "Manitoba Securities Commission (Real Estate Division)",
        "listingContract": "Exclusive Listing Contract",
        "buyerContract": "Buyer Brokerage Agreement",
        "offer": "Offer to Purchase",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per offer; confirm brokerage trust schedule",
        "complianceBoard": "WinnipegREALTORS portal",
    },
    "ON": {
        "label": "Ontario",
        "regulator": "Real Estate Council of Ontario (RECO)",
        "listingContract": "Listing Agreement (OREA Form 200)",
        "buyerContract": "Buyer Representation Agreement (OREA Form 300)",
        "offer": "Agreement of Purchase and Sale (OREA Form 100)",
        "disclosure": "Seller Property Information Statement (SPIS, optional)",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit due upon acceptance (or per APS); confirm brokerage trust schedule",
        "complianceBoard": "TRREB / local board MLS",
    },
    "QC": {
        "label": "Québec",
        "regulator": "Organisme d'autoréglementation du courtage immobilier du Québec (OACIQ)",
        "listingContract": "Brokerage Contract — Sale (OACIQ form)",
        "buyerContract": "Brokerage Contract — Purchase (OACIQ form)",
        "offer": "Promise to Purchase",
        "disclosure": "Declarations of the Seller (DR / SD)",
        "conditionTerm": "conditions",
        "conditionRemoval": "Fulfilment of conditions / withdrawal",
        "lawyerRole": "notary",
        "depositRule": "deposit per Promise; OACIQ trust account rules apply",
        "complianceBoard": "Centris MLS portal",
    },
    "NB": {
        "label": "New Brunswick",
        "regulator": "Financial and Consumer Services Commission (FCNB)",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Agency Agreement",
        "offer": "Standard Form Agreement of Purchase and Sale",
        "disclosure": "Property Condition Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "NBREA MLS portal",
    },
    "NS": {
        "label": "Nova Scotia",
        "regulator": "Nova Scotia Real Estate Commission (NSREC)",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Designated Brokerage Agreement",
        "offer": "Agreement of Purchase and Sale",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "NSAR MLS portal",
    },
    "PE": {
        "label": "Prince Edward Island",
        "regulator": "PEI Real Estate Commission",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Brokerage Agreement",
        "offer": "Agreement of Purchase and Sale",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "PEI Real Estate Association portal",
    },
    "NL": {
        "label": "Newfoundland and Labrador",
        "regulator": "Newfoundland and Labrador Association of Realtors",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Brokerage Agreement",
        "offer": "Agreement of Purchase and Sale",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "NLAR MLS portal",
    },
    "YT": {
        "label": "Yukon",
        "regulator": "Yukon Real Estate Council",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Agency Agreement",
        "offer": "Agreement of Purchase and Sale",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "Yukon REALTORS Association portal",
    },
    "NT": {
        "label": "Northwest Territories",
        "regulator": "NWT Real Estate Agents Licensing Board",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Agency Agreement",
        "offer": "Agreement of Purchase and Sale",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "NWT Association of REALTORS portal",
    },
    "NU": {
        "label": "Nunavut",
        "regulator": "Government of Nunavut (Consumer Affairs)",
        "listingContract": "Listing Agreement",
        "buyerContract": "Buyer Agency Agreement",
        "offer": "Agreement of Purchase and Sale",
        "disclosure": "Property Disclosure Statement",
        "conditionTerm": "conditions",
        "conditionRemoval": "Notice of Fulfilment / Waiver",
        "lawyerRole": "lawyer",
        "depositRule": "deposit per APS; confirm brokerage trust schedule",
        "complianceBoard": "Local MLS portal",
    },
}

_DEFAULT_ITEMS = [
    {
        "key": "identity_profile",
        "category": "profile",
        "label": "Realtor profile",
        "description": "Legal/licensed name, brokerage, team/PREC, and broker contact.",
        "required": True,
        "sort_order": 10,
    },
    {
        "key": "jurisdiction",
        "category": "regional",
        "label": "Province package",
        "description": "Country, province, market, and board memberships that select the admin guide.",
        "required": True,
        "sort_order": 20,
    },
    {
        "key": "approval_channel",
        "category": "communication",
        "label": "Admin approval channel",
        "description": "Telegram or another lane where Admin asks for human approval.",
        "required": True,
        "sort_order": 30,
    },
    {
        "key": "email",
        "category": "accounts",
        "label": "Email",
        "description": "Gmail/Outlook account for drafts, seller packages, and document routing.",
        "required": True,
        "sort_order": 40,
    },
    {
        "key": "calendar",
        "category": "accounts",
        "label": "Calendar",
        "description": "Appointment, showing, subject removal, completion, and possession dates.",
        "required": True,
        "sort_order": 50,
    },
    {
        "key": "drive",
        "category": "accounts",
        "label": "Cloud document storage",
        "description": "Drive, OneDrive, or SharePoint folder structure for transaction files.",
        "required": True,
        "sort_order": 60,
    },
    {
        "key": "crm",
        "category": "accounts",
        "label": "CRM",
        "description": "Lead/contact source with stable contact IDs, phones, emails, and pipeline stages.",
        "required": True,
        "sort_order": 70,
    },
    {
        "key": "mls",
        "category": "accounts",
        "label": "MLS / board portal",
        "description": "Matrix, Xposure, Paragon, Pillar9, or local MLS access.",
        "required": True,
        "sort_order": 80,
    },
    {
        "key": "forms_provider",
        "category": "providers",
        "label": "Forms provider",
        "description": "WEBForms, TransactionDesk, brokerage forms, or local form library.",
        "required": True,
        "sort_order": 90,
    },
    {
        "key": "signing_provider",
        "category": "providers",
        "label": "Signing provider",
        "description": "DigiSign, DocuSign, Authentisign, or another e-sign provider.",
        "required": True,
        "sort_order": 100,
    },
    {
        "key": "compliance_platform",
        "category": "providers",
        "label": "Brokerage compliance",
        "description": "SkySlope, Lone Wolf, dotloop, or brokerage admin portal.",
        "required": True,
        "sort_order": 110,
    },
    {
        "key": "showing_platform",
        "category": "providers",
        "label": "Showing feedback",
        "description": "ShowingTime, BrokerBay, Touchbase, or manual showing feedback source.",
        "required": True,
        "sort_order": 120,
    },
    {
        "key": "browser_workflows",
        "category": "providers",
        "label": "Browser-use portal playbooks",
        "description": "Login URLs, credential references, and run notes for MLS, compliance, and showing portals.",
        "required": True,
        "sort_order": 125,
    },
    {
        "key": "photo_processing",
        "category": "providers",
        "label": "Photo processing",
        "description": "Drive/Dropbox source plus Nano Banana, Higgsfield, MCP, or manual photo cleanup workflow.",
        "required": True,
        "sort_order": 127,
    },
    {
        "key": "fintrac_workflow",
        "category": "compliance",
        "label": "FINTRAC / ID workflow",
        "description": "Fintracker or manual evidence process for FINTRAC fields and FIN numbers.",
        "required": True,
        "sort_order": 130,
    },
    {
        "key": "regional_memory",
        "category": "regional",
        "label": "Regional admin memory",
        "description": "Province docs, deposit rules, local property sources, admin emails, and MLS quirks.",
        "required": True,
        "sort_order": 140,
    },
]


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


def _redact_memory_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    secretish = re.compile(
        r"(password|passwd|passcode|secret|token|api[_ -]?key)\s*[:=]",
        re.IGNORECASE,
    )
    secret_value = re.compile(
        r"(\b\d{6,}:[A-Za-z0-9_-]{20,}\b"
        r"|\b(?:sk|ghp|github_pat|xox[baprs]|AIza|ya29)[A-Za-z0-9_.-]{12,}\b"
        r"|\b[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b)",
        re.IGNORECASE,
    )
    if secretish.search(text) or secret_value.search(text):
        return "[redacted secret reference]"
    return text


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _clean_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _env_value(env_values: Mapping[str, Any] | None, *keys: str) -> str | None:
    if not env_values:
        return None
    for key in keys:
        value = _clean_text(env_values.get(key))
        if value:
            return value
    return None


def _source_connectors_by_id(source_connectors: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(source_connectors, Mapping):
        return {}
    connectors = source_connectors.get("connectors")
    if not isinstance(connectors, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for connector in connectors:
        if not isinstance(connector, Mapping):
            continue
        connector_id = _clean_key(connector.get("id"))
        if connector_id:
            result[connector_id] = dict(connector)
    return result


def _connector_connected(connector: Mapping[str, Any] | None) -> bool:
    if not connector:
        return False
    state = _clean_key(connector.get("state"))
    return bool(connector.get("connected") is True or state == "connected")


def _connector_configured(connector: Mapping[str, Any] | None) -> bool:
    if not connector:
        return False
    state = _clean_key(connector.get("state"))
    return bool(
        connector.get("sourceExists") is True
        or connector.get("importOnly") is True
        or state in {"connected", "import-only", "needs-operator"}
    )


def _account_toolkits(composio_accounts: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(composio_accounts, Mapping) or not composio_accounts.get("ok"):
        return set()
    data = composio_accounts.get("data")
    if isinstance(data, Mapping):
        accounts = data.get("items") or data.get("data") or []
    else:
        accounts = data or []
    if not isinstance(accounts, list):
        return set()
    toolkits: set[str] = set()
    for account in accounts:
        if not isinstance(account, Mapping):
            continue
        status = _clean_key(account.get("status"))
        if status and status not in {"active", "connected", "enabled", "initiated"}:
            continue
        toolkit = account.get("toolkit")
        if isinstance(toolkit, Mapping):
            raw_slug = toolkit.get("slug") or toolkit.get("name")
        else:
            raw_slug = toolkit
        slug = _clean_key(
            raw_slug
            or account.get("toolkit_slug")
            or account.get("toolkitSlug")
            or account.get("appName")
        )
        if slug:
            toolkits.add(slug)
    return toolkits


def _guide_counts(province_guide: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(province_guide, Mapping):
        return {}
    coverage = province_guide.get("coverage")
    if isinstance(coverage, Mapping):
        province_guide = {**province_guide, **coverage}
    counts: dict[str, int] = {}
    for key, aliases in {
        "forms": ("forms", "formsCount", "formCount"),
        "checklists": ("checklists", "checklistsCount", "checklistCount"),
        "pages": ("referencePages", "pages", "referencePageCount", "pageCount"),
    }.items():
        total = 0
        for alias in aliases:
            value = province_guide.get(alias)
            if isinstance(value, list):
                total = max(total, len(value))
            elif isinstance(value, int):
                total = max(total, value)
        counts[key] = total
    return counts


def _ensure_seeded(conn: sqlite3.Connection) -> None:
    now = now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO admin_setup_profile(
            id, country, default_folder_pattern, created_at, updated_at
        ) VALUES (?, 'CA', 'Address - Client - Deal Type', ?, ?)
        """,
        (PROFILE_ID, now, now),
    )
    for item in _DEFAULT_ITEMS:
        conn.execute(
            """
            INSERT OR IGNORE INTO admin_setup_items(
                key, category, label, description, required, sort_order, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["key"],
                item["category"],
                item["label"],
                item["description"],
                1 if item["required"] else 0,
                int(item["sort_order"]),
                now,
            ),
        )


def _row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "realtorLegalName": row["realtor_legal_name"],
        "licenseName": row["license_name"],
        "brokerageName": row["brokerage_name"],
        "teamName": row["team_name"],
        "country": row["country"],
        "province": row["province"],
        "market": row["market"],
        "boardMemberships": _decode_json(row["board_memberships_json"]) or [],
        "emailProvider": row["email_provider"],
        "calendarProvider": row["calendar_provider"],
        "driveProvider": row["drive_provider"],
        "crmProvider": row["crm_provider"],
        "mlsProvider": row["mls_provider"],
        "formsProvider": row["forms_provider"],
        "signingProvider": row["signing_provider"],
        "complianceProvider": row["compliance_provider"],
        "showingProvider": row["showing_provider"],
        "fintracProvider": row["fintrac_provider"],
        "approvalChannel": row["approval_channel"],
        "managingBrokerEmail": row["managing_broker_email"],
        "defaultFolderPattern": row["default_folder_pattern"],
        "commissionNotes": row["commission_notes"],
        "servicesSchedule": row["services_schedule"],
        "regionalMemory": _decode_json(row["regional_memory_json"]) or {},
        "approvalPolicy": _decode_json(row["approval_policy_json"]) or {},
        "completedAt": row["completed_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "required": bool(row["required"]),
        "status": row["status"],
        "provider": row["provider"],
        "value": _decode_json(row["value_json"]),
        "notes": row["notes"],
        "sortOrder": row["sort_order"],
        "updatedAt": row["updated_at"],
    }


def _item_has_runtime_verification(item: Mapping[str, Any]) -> bool:
    value = item.get("value")
    if not isinstance(value, Mapping):
        return False
    verification = value.get("verification")
    if not isinstance(verification, Mapping):
        return False
    return bool(verification.get("checkedAt") and verification.get("signals"))


def _item_has_browser_workflow_contract(item: Mapping[str, Any]) -> bool:
    value = item.get("value")
    if not isinstance(value, Mapping):
        return False
    if str(value.get("mode") or "").strip().lower() not in {"browser-use", "browser_use", "browser"}:
        return False
    playbooks = value.get("playbooks")
    if not isinstance(playbooks, Mapping):
        return False
    for key in BROWSER_WORKFLOW_REQUIRED_KEYS:
        playbook = playbooks.get(key)
        if not isinstance(playbook, Mapping):
            return False
        provider = str(playbook.get("provider") or "").strip()
        has_access_hint = any(
            str(playbook.get(field) or "").strip()
            for field in ("loginUrl", "credentialRef", "notes")
        )
        if not provider or not has_access_hint:
            return False
    return True


def _item_counts_ready(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status") or "")
    if status not in READY_STATUSES:
        return False
    key = str(item.get("key") or "")
    if key in VERIFICATION_REQUIRED_KEYS:
        return _item_has_runtime_verification(item)
    if key == "browser_workflows":
        return _item_has_browser_workflow_contract(item)
    return True


def _snapshot(profile: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    required = [item for item in items if item["required"]]
    complete_required = [
        item for item in required if _item_counts_ready(item)
    ]
    missing = [
        item for item in required if not _item_counts_ready(item)
    ]
    complete = bool(required) and len(complete_required) == len(required)
    readiness = [_item_readiness(item) for item in required]
    return {
        "profile": profile,
        "items": items,
        "readiness": readiness,
        "complete": complete,
        "launchRequired": not complete,
        "canStartAdmin": complete,
        "requiredCount": len(required),
        "completedRequiredCount": len(complete_required),
        "missingRequiredKeys": [item["key"] for item in missing],
        "completionPct": round((len(complete_required) / len(required)) * 100) if required else 100,
    }


def _item_readiness(item: Mapping[str, Any]) -> dict[str, Any]:
    key = str(item.get("key") or "")
    label = str(item.get("label") or key)
    status = str(item.get("status") or "missing")
    provider = item.get("provider")
    value = item.get("value")
    ready = _item_counts_ready(item)
    state = "ready" if ready else "missing_value"
    action = "No action needed."
    detail = f"{label} is ready."

    if not ready:
        if key in VERIFICATION_REQUIRED_KEYS and status in READY_STATUSES:
            state = "needs_runtime_verification"
            action = "Connect or verify the live account, then run Verify connections."
            detail = f"{label} has a saved value but still needs a live connector signal."
        elif key == "browser_workflows":
            state = "incomplete_browser_playbook"
            action = "Add provider, login URL or credential reference, and browser-use notes for MLS, compliance, and showing."
            detail = "Browser-use portal playbooks are incomplete."
        elif status in READY_STATUSES:
            state = "incomplete_setup"
            action = "Review this setup item and add the missing required details."
            detail = f"{label} is configured but does not meet the readiness contract."
        else:
            state = "missing_value"
            action = "Enter the provider or setup details, then save setup."
            detail = f"{label} has not been configured yet."

    return {
        "key": key,
        "label": label,
        "category": item.get("category"),
        "status": status,
        "provider": provider,
        "ready": ready,
        "state": state,
        "detail": detail,
        "action": action,
        "hasValue": bool(value),
        "updatedAt": item.get("updatedAt"),
    }


def _admin_setup_memory_path() -> Path:
    return get_elevate_home() / "memories" / ADMIN_ONBOARDING_MEMORY_FILE


def _admin_province_playbook_path() -> Path:
    return get_elevate_home() / "memories" / ADMIN_PROVINCE_PLAYBOOK_FILE


def _atomic_write(path: Path, content: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".admin_pb_")
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
    return len(content.encode("utf-8"))


def build_admin_province_playbook(
    snapshot: Mapping[str, Any],
    province_memory: Mapping[str, Any] | None,
) -> str:
    """Render the province-specialized Admin operating playbook.

    Combines the realtor's saved profile + provider stack with the chosen
    province's regulator, contract names, condition vocabulary, and the
    forms/checklists imported into SQLite from the eXp Agent Centre scrape.
    This is the prompt the Admin agent loads as its province-aware source
    of truth.
    """
    profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), Mapping) else {}
    items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
    by_key = {item.get("key"): item for item in items if isinstance(item, Mapping)}

    def provider_for(key: str, fallback: str = "") -> str:
        item = by_key.get(key) or {}
        raw = item.get("provider") if isinstance(item, Mapping) else None
        return _redact_memory_text(raw or fallback) or "not recorded"

    province_code = str(profile.get("province") or "").strip().upper() or "UNKNOWN"
    province_lookup = PROVINCE_TERMINOLOGY.get(province_code, {})
    province_label = province_lookup.get("label", province_code)
    regulator = province_lookup.get("regulator", "the provincial real estate regulator")
    listing_contract = province_lookup.get("listingContract", "the listing contract")
    buyer_contract = province_lookup.get("buyerContract", "the buyer representation agreement")
    offer_doc = province_lookup.get("offer", "the offer document")
    disclosure_doc = province_lookup.get("disclosure", "the seller's property disclosure")
    condition_term = province_lookup.get("conditionTerm", "conditions")
    condition_removal = province_lookup.get("conditionRemoval", "Notice of Fulfilment / Waiver")
    lawyer_role = province_lookup.get("lawyerRole", "lawyer")
    deposit_rule = province_lookup.get("depositRule", "deposit timing per the offer document")

    realtor_name = _redact_memory_text(profile.get("realtorLegalName")) or "the realtor"
    brokerage = _redact_memory_text(profile.get("brokerageName")) or "the brokerage"
    market = _redact_memory_text(profile.get("market")) or province_label
    boards = [
        _redact_memory_text(item)
        for item in (profile.get("boardMemberships") or [])
        if _redact_memory_text(item)
    ]

    lines: list[str] = []
    lines.append(f"# Admin operating playbook — {province_label}")
    lines.append("")
    lines.append(
        "This file is the Admin agent's province-specialized source of truth. "
        "It is regenerated whenever onboarding is finished + verified. "
        "Treat the realtor profile and the provincial vocabulary below as "
        "authoritative; pull deeper detail from `province_guides` in SQLite "
        "when a specific form, checklist, or reference page is needed."
    )
    lines.append("")

    lines.append(f"## Operator profile")
    lines.append(f"- Realtor: {realtor_name}")
    lines.append(f"- Brokerage: {brokerage}")
    lines.append(f"- Province: {province_label} ({province_code})")
    lines.append(f"- Primary market: {market}")
    if boards:
        lines.append(f"- Board memberships: {', '.join(boards)}")
    approval_channel = _redact_memory_text(profile.get("approvalChannel")) or provider_for("approval_channel")
    lines.append(f"- Approval lane: {approval_channel}")
    managing_broker = _redact_memory_text(profile.get("managingBrokerEmail"))
    if managing_broker:
        lines.append(f"- Managing broker / admin email: {managing_broker}")
    lines.append("")

    lines.append("## Provincial vocabulary (use these terms, not generic English)")
    lines.append(f"- Regulator: {regulator}")
    lines.append(f"- Listing contract: {listing_contract}")
    lines.append(f"- Buyer representation: {buyer_contract}")
    lines.append(f"- Offer document: {offer_doc}")
    lines.append(f"- Seller disclosure: {disclosure_doc}")
    lines.append(f"- Pre-firm clauses are called **{condition_term}** in {province_label}.")
    lines.append(f"- Removing those clauses uses: **{condition_removal}**.")
    lines.append(f"- Closing is handled by a **{lawyer_role}**.")
    lines.append(f"- Deposit rule: {deposit_rule}.")
    lines.append("")

    lines.append("## Active provider stack")
    lines.append(f"- Email: {provider_for('email', profile.get('emailProvider') or '')}")
    lines.append(f"- Calendar: {provider_for('calendar', profile.get('calendarProvider') or '')}")
    lines.append(f"- Cloud storage: {provider_for('drive', profile.get('driveProvider') or '')}")
    lines.append(f"- CRM: {provider_for('crm', profile.get('crmProvider') or '')}")
    lines.append(f"- MLS / board portal: {provider_for('mls', profile.get('mlsProvider') or '')}")
    lines.append(f"- Forms: {provider_for('forms_provider', profile.get('formsProvider') or '')}")
    lines.append(f"- Signing: {provider_for('signing_provider', profile.get('signingProvider') or '')}")
    lines.append(f"- Compliance: {provider_for('compliance_platform', profile.get('complianceProvider') or '')}")
    lines.append(f"- Showings: {provider_for('showing_platform', profile.get('showingProvider') or '')}")
    lines.append(f"- Photo processing: {provider_for('photo_processing', profile.get('photoProcessingProvider') or '')}")
    lines.append(f"- FINTRAC / ID workflow: {provider_for('fintrac_workflow', profile.get('fintracProvider') or '')}")
    lines.append("")

    if isinstance(province_memory, Mapping):
        coverage = province_memory.get("coverage") if isinstance(province_memory.get("coverage"), Mapping) else {}
        lines.append("## Province forms + reference material (imported from eXp Agent Centre)")
        ref_pages = int(coverage.get("referencePages") or 0)
        checklists = int(coverage.get("checklists") or 0)
        forms = int(coverage.get("forms") or 0)
        lines.append(
            f"- Coverage: {ref_pages} reference pages, {checklists} checklists, {forms} forms."
        )
        lines.append(
            "- Full corpus lives in SQLite `province_guides`; pull deeper excerpts on demand."
        )
        lines.append("")
        form_rows = province_memory.get("forms") if isinstance(province_memory.get("forms"), list) else []
        if form_rows:
            lines.append("### Key forms")
            for row in form_rows[:20]:
                if not isinstance(row, Mapping):
                    continue
                code = _redact_memory_text(row.get("code")) or "(no code)"
                name = _redact_memory_text(row.get("name")) or "(unnamed form)"
                category = _redact_memory_text(row.get("category"))
                suffix = f" — {category}" if category else ""
                lines.append(f"- **{code}**: {name}{suffix}")
            if len(form_rows) > 20:
                lines.append(f"- (+{len(form_rows) - 20} more forms in SQLite)")
            lines.append("")
        checklist_rows = province_memory.get("checklists") if isinstance(province_memory.get("checklists"), list) else []
        if checklist_rows:
            lines.append("### Checklists")
            for row in checklist_rows[:8]:
                if not isinstance(row, Mapping):
                    continue
                title = _redact_memory_text(row.get("title")) or "(untitled)"
                slug = _redact_memory_text(row.get("slug")) or ""
                lines.append(f"- {title} (`{slug}`)")
            if len(checklist_rows) > 8:
                lines.append(f"- (+{len(checklist_rows) - 8} more checklists in SQLite)")
            lines.append("")
        ref_rows = province_memory.get("referencePages") if isinstance(province_memory.get("referencePages"), list) else []
        if ref_rows:
            lines.append("### Reference pages")
            for row in ref_rows[:6]:
                if not isinstance(row, Mapping):
                    continue
                title = _redact_memory_text(row.get("title")) or "(untitled)"
                page_type = _redact_memory_text(row.get("pageType")) or ""
                suffix = f" [{page_type}]" if page_type else ""
                lines.append(f"- {title}{suffix}")
            lines.append("")
    else:
        lines.append("## Province forms + reference material")
        lines.append(
            f"- No imported guide for {province_label} yet. Fall back to "
            "manual references and ask the realtor when a form is unclear."
        )
        lines.append("")

    regional_memory = profile.get("regionalMemory") if isinstance(profile.get("regionalMemory"), Mapping) else {}
    regional_notes = _redact_memory_text(regional_memory.get("notes"))
    approval_policy = profile.get("approvalPolicy") if isinstance(profile.get("approvalPolicy"), Mapping) else {}
    approval_notes = _redact_memory_text(approval_policy.get("notes"))
    lines.append("## Operating notes")
    lines.append(f"- Regional memory: {regional_notes or 'not recorded'}")
    lines.append(
        f"- Approval policy: {approval_notes or 'Ask through the Admin approval lane before any external send, signature, MLS change, or client-visible message.'}"
    )
    lines.append("- Folder pattern: " + (_redact_memory_text(profile.get("defaultFolderPattern")) or "Address - Client - Deal Type"))
    commission = _redact_memory_text(profile.get("commissionNotes"))
    if commission:
        lines.append(f"- Commission / service notes: {commission}")
    lines.append("")

    lines.append("## How to operate")
    lines.append(
        f"- Run the {province_label} stage flow exactly as configured in the Admin kanban; "
        f"never use generic terminology where the provincial vocabulary above applies."
    )
    lines.append(
        f"- When proposing a document, prefer the {province_label} form code listed above; "
        "if a form is missing from SQLite, surface the gap and pause."
    )
    lines.append(
        "- Treat browser portal credentials as references only — open the saved browser profile "
        "for the chosen provider rather than asking the realtor for passwords."
    )
    lines.append(
        "- Do not re-ask the realtor for anything captured in this file; if data has gone stale "
        "or a portal login no longer works, surface that explicitly through the approval lane."
    )
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def sync_admin_province_playbook(conn: sqlite3.Connection) -> dict[str, Any]:
    """Render + write the province-specialized Admin playbook file."""
    from elevate_cli.data.province_guides import province_agent_memory

    snapshot = get_admin_setup(conn)
    province = str((snapshot.get("profile") or {}).get("province") or "").strip().upper()
    province_memory: dict[str, Any] | None = None
    if province:
        try:
            province_memory = province_agent_memory(conn, province)
        except Exception:
            province_memory = None
    content = build_admin_province_playbook(snapshot, province_memory)
    path = _admin_province_playbook_path()
    bytes_written = _atomic_write(path, content)
    return {
        "path": str(path),
        "bytes": bytes_written,
        "province": province or None,
        "hasProvinceGuide": bool(province_memory and province_memory.get("coverage", {}).get("hasTransactionGuide")),
    }


def admin_setup_memory_summary(snapshot: Mapping[str, Any]) -> str:
    """Return the sanitized Admin onboarding memory injected into future agents."""
    profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), Mapping) else {}
    items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
    by_key = {item.get("key"): item for item in items if isinstance(item, Mapping)}

    def item_value(key: str) -> Mapping[str, Any]:
        item = by_key.get(key) or {}
        value = item.get("value") if isinstance(item, Mapping) else {}
        return value if isinstance(value, Mapping) else {}

    def provider(key: str, fallback: str = "") -> str:
        item = by_key.get(key) or {}
        raw = item.get("provider") if isinstance(item, Mapping) else None
        return _redact_memory_text(raw or fallback)

    browser = item_value("browser_workflows")
    playbooks = browser.get("playbooks") if isinstance(browser.get("playbooks"), Mapping) else {}
    photo = item_value("photo_processing")
    regional_memory = profile.get("regionalMemory") if isinstance(profile.get("regionalMemory"), Mapping) else {}
    approval_policy = profile.get("approvalPolicy") if isinstance(profile.get("approvalPolicy"), Mapping) else {}

    lines = [
        "# Admin onboarding memory",
        "",
        "This file is generated from SQLite Admin setup. SQLite operational.db remains the source of truth; use this as durable recall so agents do not ask the realtor for the same setup details again.",
        "",
        "## Realtor profile",
        f"- Name: {_redact_memory_text(profile.get('realtorLegalName')) or 'unknown'}",
        f"- Brokerage: {_redact_memory_text(profile.get('brokerageName')) or 'unknown'}",
        f"- Province/market: {_redact_memory_text(profile.get('province')) or 'unknown'} / {_redact_memory_text(profile.get('market')) or 'unknown'}",
        f"- Boards: {', '.join(_redact_memory_text(item) for item in (profile.get('boardMemberships') or []) if _redact_memory_text(item)) or 'none recorded'}",
        f"- Approval channel: {_redact_memory_text(profile.get('approvalChannel')) or provider('approval_channel') or 'unknown'}",
        "",
        "## Connected admin providers",
        f"- Email: {provider('email', profile.get('emailProvider') or '') or 'not recorded'}",
        f"- Calendar: {provider('calendar', profile.get('calendarProvider') or '') or 'not recorded'}",
        f"- Cloud storage: {provider('drive', profile.get('driveProvider') or '') or 'not recorded'}",
        f"- CRM: {provider('crm', profile.get('crmProvider') or '') or 'not recorded'}",
        f"- Forms: {provider('forms_provider', profile.get('formsProvider') or '') or 'not recorded'}",
        f"- Signing: {provider('signing_provider', profile.get('signingProvider') or '') or 'not recorded'}",
        f"- FINTRAC: {provider('fintrac_workflow', profile.get('fintracProvider') or '') or 'not recorded'}",
        "",
        "## Browser-use portal playbooks",
    ]
    for key, label in (
        ("mls", "MLS"),
        ("compliance", "Compliance/SkySlope"),
        ("showing", "Showing platform"),
    ):
        playbook = playbooks.get(key) if isinstance(playbooks, Mapping) else {}
        playbook = playbook if isinstance(playbook, Mapping) else {}
        lines.extend(
            [
                f"- {label} provider: {_redact_memory_text(playbook.get('provider')) or provider('mls' if key == 'mls' else 'compliance_platform' if key == 'compliance' else 'showing_platform') or 'not recorded'}",
                f"  Login URL: {_redact_memory_text(playbook.get('loginUrl')) or 'not recorded'}",
                f"  Credential ref: {_redact_memory_text(playbook.get('credentialRef')) or 'not recorded'}",
            ]
        )
    browser_notes = _redact_memory_text(browser.get("notes"))
    if browser_notes:
        lines.append(f"- Browser-use notes: {browser_notes}")
    lines.extend(
        [
            "",
            "## Photo processing",
            f"- Provider/workflow: {_redact_memory_text(photo.get('provider')) or provider('photo_processing') or 'not recorded'}",
            f"- Source: {_redact_memory_text(photo.get('source')) or 'not recorded'}",
        ]
    )
    photo_notes = _redact_memory_text(photo.get("notes"))
    if photo_notes:
        lines.append(f"- Notes: {photo_notes}")
    regional_notes = _redact_memory_text(regional_memory.get("notes"))
    approval_notes = _redact_memory_text(approval_policy.get("notes"))
    lines.extend(
        [
            "",
            "## Operating notes",
            f"- Regional memory: {regional_notes or 'not recorded'}",
            f"- Approval policy: {approval_notes or 'Ask through Admin Telegram before external sends, signatures, MLS changes, or client-visible messages.'}",
            "- Do not ask for these onboarding details again unless the source-of-truth setup item is missing, stale, or a browser-use run proves the saved access does not work.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def sync_admin_setup_memory(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Publish the current Admin setup into profile-scoped agent memory."""
    path = _admin_setup_memory_path()
    content = admin_setup_memory_summary(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".admin_setup_")
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


def get_admin_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    _ensure_seeded(conn)
    profile_row = conn.execute(
        "SELECT * FROM admin_setup_profile WHERE id=?", (PROFILE_ID,)
    ).fetchone()
    item_rows = conn.execute(
        "SELECT * FROM admin_setup_items ORDER BY sort_order ASC, key ASC"
    ).fetchall()
    snapshot = _snapshot(_row_to_profile(profile_row), [_row_to_item(row) for row in item_rows])
    memory_path = _admin_setup_memory_path()
    snapshot["memory"] = {
        "path": str(memory_path),
        "synced": memory_path.exists(),
    }
    return snapshot


_PROFILE_FIELD_MAP = {
    "realtorLegalName": "realtor_legal_name",
    "licenseName": "license_name",
    "brokerageName": "brokerage_name",
    "teamName": "team_name",
    "country": "country",
    "province": "province",
    "market": "market",
    "emailProvider": "email_provider",
    "calendarProvider": "calendar_provider",
    "driveProvider": "drive_provider",
    "crmProvider": "crm_provider",
    "mlsProvider": "mls_provider",
    "formsProvider": "forms_provider",
    "signingProvider": "signing_provider",
    "complianceProvider": "compliance_provider",
    "showingProvider": "showing_provider",
    "fintracProvider": "fintrac_provider",
    "approvalChannel": "approval_channel",
    "managingBrokerEmail": "managing_broker_email",
    "defaultFolderPattern": "default_folder_pattern",
    "commissionNotes": "commission_notes",
    "servicesSchedule": "services_schedule",
}
_JSON_PROFILE_FIELD_MAP = {
    "boardMemberships": "board_memberships_json",
    "regionalMemory": "regional_memory_json",
    "approvalPolicy": "approval_policy_json",
}


def update_admin_setup(
    conn: sqlite3.Connection,
    *,
    profile: Mapping[str, Any] | None = None,
    items: Iterable[Mapping[str, Any]] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    del actor  # reserved for future audit events
    _ensure_seeded(conn)
    now = now_iso()
    if profile:
        updates: list[str] = []
        values: list[Any] = []
        for api_key, db_key in _PROFILE_FIELD_MAP.items():
            if api_key not in profile:
                continue
            value = _clean_text(profile.get(api_key))
            if api_key == "country" and not value:
                value = "CA"
            if api_key == "province" and value:
                value = value.upper()
            updates.append(f"{db_key}=?")
            values.append(value)
        for api_key, db_key in _JSON_PROFILE_FIELD_MAP.items():
            if api_key not in profile:
                continue
            updates.append(f"{db_key}=?")
            values.append(_encode_json(profile.get(api_key)))
        if updates:
            updates.append("updated_at=?")
            values.append(now)
            values.append(PROFILE_ID)
            conn.execute(
                f"UPDATE admin_setup_profile SET {', '.join(updates)} WHERE id=?",
                values,
            )
    if items:
        for item in items:
            key = str(item.get("key") or "").strip()
            if not key:
                raise ValueError("setup item key is required")
            row = conn.execute(
                "SELECT key FROM admin_setup_items WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                raise LookupError(f"admin setup item {key!r} not found")
            status = str(item.get("status") or "missing").strip()
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid admin setup status {status!r}")
            conn.execute(
                """
                UPDATE admin_setup_items
                SET status=?, provider=?, value_json=?, notes=?, updated_at=?
                WHERE key=?
                """,
                (
                    status,
                    _clean_text(item.get("provider")),
                    _encode_json(item.get("value")),
                    _clean_text(item.get("notes")),
                    now,
                    key,
                ),
            )
    snapshot = get_admin_setup(conn)
    memory = sync_admin_setup_memory(snapshot)
    snapshot["memory"] = {**snapshot.get("memory", {}), **memory, "synced": True}
    return snapshot


def sync_admin_setup_runtime(
    conn: sqlite3.Connection,
    *,
    env_values: Mapping[str, Any] | None = None,
    source_connectors: Mapping[str, Any] | None = None,
    composio_accounts: Mapping[str, Any] | None = None,
    province_guide: Mapping[str, Any] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Upgrade setup readiness from observed local runtime signals.

    This is intentionally additive. It marks an item ready only when there is
    concrete local evidence (connected connector, account, env credential, or
    imported province guide), and otherwise leaves the realtor-entered setup
    values alone.
    """
    snapshot = get_admin_setup(conn)
    profile = snapshot["profile"]
    items_by_key = {item["key"]: item for item in snapshot["items"]}
    connectors = _source_connectors_by_id(source_connectors)
    composio_toolkits = _account_toolkits(composio_accounts)
    checked_at = now_iso()
    updates: list[dict[str, Any]] = []

    def mark(
        key: str,
        *,
        status: str,
        provider: str | None = None,
        signals: list[str] | None = None,
        details: Mapping[str, Any] | None = None,
        notes: str | None = None,
    ) -> None:
        item = items_by_key.get(key)
        if not item:
            return
        value = item.get("value")
        if not isinstance(value, dict):
            value = {}
        verification = dict(value.get("verification") or {})
        verification.update(
            {
                "checkedAt": checked_at,
                "verifiedBy": "admin_setup_runtime",
                "signals": signals or [],
            }
        )
        if details:
            verification["details"] = dict(details)
        merged_value = {**value, "verification": verification}
        next_status = status if status in VALID_STATUSES else item["status"]
        current_status = str(item.get("status") or "missing")
        if current_status in READY_STATUSES and next_status not in READY_STATUSES:
            next_status = current_status
        updates.append(
            {
                "key": key,
                "status": next_status,
                "provider": provider or item.get("provider"),
                "value": merged_value,
                "notes": notes if notes is not None else item.get("notes"),
            }
        )

    admin_token = _env_value(
        env_values,
        "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN",
        "ADMIN_TELEGRAM_BOT_TOKEN",
    )
    admin_channel = _env_value(
        env_values,
        "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL",
        "ADMIN_TELEGRAM_CHANNEL",
        "TELEGRAM_HOME_CHANNEL",
        "TELEGRAM_CHAT_ID",
    )
    if admin_token and admin_channel:
        mark(
            "approval_channel",
            status="connected",
            provider="telegram",
            signals=["Admin Telegram bot token configured", "Admin Telegram lane configured"],
            details={
                "botTokenEnv": "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN",
                "channelEnv": "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL",
            },
        )

    email_connector = connectors.get("email")
    email_toolkits = sorted(composio_toolkits.intersection({"gmail", "gmail-oauth2", "outlook"}))
    if _connector_connected(email_connector):
        mark(
            "email",
            status="connected",
            provider=str(email_connector.get("label") or "Email"),
            signals=["Email source connector connected"],
            details={"sourceId": "email", "state": email_connector.get("state")},
        )
    elif email_toolkits:
        mark(
            "email",
            status="connected",
            provider=email_toolkits[0],
            signals=["Composio email account connected"],
            details={"toolkits": email_toolkits},
        )

    if composio_toolkits.intersection({"google-calendar", "googlecalendar", "outlook-calendar"}):
        mark(
            "calendar",
            status="connected",
            provider="Composio calendar",
            signals=["Calendar account connected through Composio"],
            details={"toolkits": sorted(composio_toolkits)},
        )

    storage_connector = connectors.get("document-storage")
    if _connector_connected(storage_connector):
        mark(
            "drive",
            status="connected",
            provider=str(storage_connector.get("label") or "Document Storage"),
            signals=["Document storage connector connected"],
            details={"sourceId": "document-storage", "state": storage_connector.get("state")},
        )
    elif composio_toolkits.intersection({"google-drive", "googledrive", "onedrive"}):
        mark(
            "drive",
            status="connected",
            provider="Composio storage",
            signals=["Cloud document storage connected through Composio"],
            details={"toolkits": sorted(composio_toolkits)},
        )

    crm_connector = connectors.get("crm")
    crm_env = _env_value(env_values, "LOFTY_API_KEY", "LOFTY_ACCESS_TOKEN", "CRM_API_KEY")
    if _connector_connected(crm_connector):
        mark(
            "crm",
            status="connected",
            provider=str(crm_connector.get("label") or "CRM"),
            signals=["CRM source connector connected"],
            details={"sourceId": "crm", "state": crm_connector.get("state")},
        )
    elif crm_env:
        mark(
            "crm",
            status="configured",
            provider=profile.get("crmProvider") or "CRM",
            signals=["CRM API credential configured"],
            details={"env": "CRM_API_KEY/LOFTY_API_KEY"},
        )

    if _env_value(
        env_values,
        "MLS_USERNAME",
        "MLS_USER",
        "MLS_API_KEY",
        "MATRIX_USERNAME",
        "XPOSURE_USERNAME",
        "PARAGON_USERNAME",
    ):
        mark(
            "mls",
            status="configured",
            provider=profile.get("mlsProvider") or "MLS",
            signals=["MLS credential configured"],
        )

    forms_connector = connectors.get("forms-signing")
    if _connector_configured(forms_connector):
        mark(
            "forms_provider",
            status="configured",
            provider=str(forms_connector.get("label") or profile.get("formsProvider") or "Forms"),
            signals=["Forms/signing source connector configured"],
            details={"sourceId": "forms-signing", "state": forms_connector.get("state")},
        )
        mark(
            "signing_provider",
            status="configured",
            provider=str(forms_connector.get("label") or profile.get("signingProvider") or "Signing"),
            signals=["Forms/signing source connector configured"],
            details={"sourceId": "forms-signing", "state": forms_connector.get("state")},
        )

    if _env_value(env_values, "SKYSLOPE_API_KEY", "SKYSLOPE_USERNAME", "LONEWOLF_API_KEY"):
        mark(
            "compliance_platform",
            status="configured",
            provider=profile.get("complianceProvider") or "Compliance",
            signals=["Compliance platform credential configured"],
        )

    if _env_value(env_values, "SHOWINGTIME_USERNAME", "SHOWINGTIME_API_KEY", "BROKERBAY_API_KEY"):
        mark(
            "showing_platform",
            status="configured",
            provider=profile.get("showingProvider") or "Showing platform",
            signals=["Showing platform credential configured"],
        )

    guide_counts = _guide_counts(province_guide)
    province = str(profile.get("province") or "").upper()
    guide_memory_result: dict[str, Any] | None = None
    if province and sum(guide_counts.values()) > 0:
        mark(
            "regional_memory",
            status="configured",
            provider=province,
            signals=["Province guide imported into SQLite"],
            details={"province": province, **guide_counts},
        )
        # Make the full province guide corpus searchable on demand: ingest it
        # into the holographic memory store so the agent can document_search /
        # recall it, not just read the compact excerpts injected into prompts.
        try:
            from elevate_cli.data.province_guide_memory import (
                sync_province_guide_to_memory,
            )

            guide_memory_result = sync_province_guide_to_memory(conn, province)
        except Exception:  # noqa: BLE001 - memory sync must never break setup
            _log.warning("province guide memory sync failed", exc_info=True)

    if not updates:
        memory = sync_admin_setup_memory(snapshot)
        snapshot["memory"] = {**snapshot.get("memory", {}), **memory, "synced": True}
        try:
            playbook = sync_admin_province_playbook(conn)
            snapshot["playbook"] = playbook
        except Exception:
            pass
        if guide_memory_result is not None:
            snapshot["guideMemory"] = guide_memory_result
        return snapshot
    updated = update_admin_setup(conn, items=updates, actor=actor)
    try:
        playbook = sync_admin_province_playbook(conn)
        updated["playbook"] = playbook
    except Exception:
        pass
    if guide_memory_result is not None:
        updated["guideMemory"] = guide_memory_result
    return updated


def complete_admin_setup(
    conn: sqlite3.Connection,
    *,
    actor: str = "human",
) -> dict[str, Any]:
    del actor
    snapshot = get_admin_setup(conn)
    if snapshot["missingRequiredKeys"]:
        raise ValueError(
            "admin setup is missing required items: "
            + ", ".join(snapshot["missingRequiredKeys"])
        )
    now = now_iso()
    conn.execute(
        """
        UPDATE admin_setup_profile
        SET completed_at=COALESCE(completed_at, ?), updated_at=?
        WHERE id=?
        """,
        (now, now, PROFILE_ID),
    )
    snapshot = get_admin_setup(conn)
    memory = sync_admin_setup_memory(snapshot)
    snapshot["memory"] = {**snapshot.get("memory", {}), **memory, "synced": True}
    try:
        playbook = sync_admin_province_playbook(conn)
        snapshot["playbook"] = playbook
    except Exception:
        pass
    return snapshot


def admin_setup_ready(conn: sqlite3.Connection) -> bool:
    return bool(get_admin_setup(conn)["complete"])


def require_admin_setup_ready(conn: sqlite3.Connection) -> None:
    snapshot = get_admin_setup(conn)
    if snapshot["complete"]:
        return
    missing = ", ".join(snapshot["missingRequiredKeys"])
    raise PermissionError(f"admin setup is required before starting admin work: {missing}")
