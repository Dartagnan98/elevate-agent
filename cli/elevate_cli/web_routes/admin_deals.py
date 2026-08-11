"""Admin deal workflow routes."""

import logging
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, cast

from elevate_constants import get_elevate_home
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from elevate_cli.data.deals import DealPhaseGateBlocked

_module_log = logging.getLogger(__name__)


RequireReady = Callable[[], None]
AdminJurisdictionConfig = Callable[[], Dict[str, str]]


class _DealCreateBody(BaseModel):
    title: str
    side: str
    province: Optional[str] = None
    board: Optional[str] = None
    market: Optional[str] = None
    currentStage: int = 0
    primaryContactId: Optional[str] = None
    loftyContactId: Optional[str] = None
    listingAddress: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    dispatchInitialStage: bool = True
    suppressInitialDispatch: bool = False


class _ProfilePromotionBody(BaseModel):
    profileId: str
    side: str
    displayName: Optional[str] = None
    primaryContactId: Optional[str] = None
    listingAddress: Optional[str] = None
    workflow: Optional[str] = None
    province: Optional[str] = None
    board: Optional[str] = None
    market: Optional[str] = None
    currentStage: int = 0
    profileContext: Dict[str, Any] = Field(default_factory=dict)
    verifiers: List[Dict[str, Any]] = Field(default_factory=list)
    fields: Dict[str, Any] = Field(default_factory=dict)
    dispatchInitialStage: bool = True


class _DealMoveBody(BaseModel):
    toStage: int
    force: bool = False


class _DealCollapseBody(BaseModel):
    side: Optional[str] = None


class _DealToggleBody(BaseModel):
    field: str
    value: Any


class _GatherCpsBody(BaseModel):
    mls: str
    deal_id: Optional[str] = None
    dry_run: bool = False


class _GenerateCpsBody(BaseModel):
    umbrella: str
    clauses: List[str] = []
    customClauses: List[Dict[str, Any]] = []
    vars: Dict[str, Any] = {}
    address: Optional[str] = None
    deal_id: Optional[str] = None
    dry_run: bool = False
    forms: Optional[List[str]] = None  # which accessory forms to include in the package


class _GenerateFormBody(BaseModel):
    form: str            # pnc | dorts | disclosure-rem
    address: Optional[str] = None
    deal_id: Optional[str] = None
    dry_run: bool = False


class _OnboardingDocBody(BaseModel):
    form: str            # agency | dorts | pnc


class _OnboardingSignBody(BaseModel):
    # Optional: restrict onboarding docs to specific buyer(s) by name -- e.g. a
    # newly-added co-buyer who needs their own DORTS/PNC when the other buyer
    # already onboarded. Omitted / empty => fill for all buyers on the deal.
    buyers: Optional[List[str]] = None


# Canonical map of wizard-fillable SIGNABLE forms: form key -> (offer-prep-forms.py
# arg, human label). The filing engine and the prepare-signables endpoint agree on
# these keys. Only forms that fill deterministically from deal data belong here.
_SIGNABLE_FORMS: Dict[str, Dict[str, str]] = {
    # formArg -> offer-prep-forms.py fill arg; specForm -> digisign_engine block-spec
    # name (blank-forms/specs/<specForm>.json) so blocks land per form.
    "dorts": {"formArg": "dorts", "specForm": "dorts", "label": "Disclosure of Representation in Trading Services (DORTS)"},
    "pnc": {"formArg": "pnc", "specForm": "pnc", "label": "Privacy Notice & Consent (PNC)"},
    "disclosure-rem": {"formArg": "disclosure-rem", "specForm": "disclosure-of-remuneration", "label": "Disclosure of Remuneration"},
}


class _PrepareSignablesBody(BaseModel):
    # Which wizard-fillable signable forms to prepare + stage as ONE DigiSign draft.
    forms: List[str] = []
    buyers: Optional[List[str]] = None
    purpose: Optional[str] = None


class _CmaRunBody(BaseModel):
    phase: str           # collect | actives | normalize | finish | render | qa


class _CmaCompToggleBody(BaseModel):
    mls: str
    kind: str            # sold | active


class _CmaRegenBody(BaseModel):
    instructions: str = ""   # free text, e.g. "expand to Westsyde + Westmount, target $635k"


class _CmaRepriceBody(BaseModel):
    price: str = ""          # exact target list price, e.g. "$635,000"
    rationale: str = ""      # the operator's "why" (folded into the CMA narrative)


class _CmaCaptureProspectingBody(BaseModel):
    mls: str                 # the active comp the operator chose as the prospecting anchor


class _DealContactBody(BaseModel):
    role: str
    contactId: str
    notes: Optional[str] = None


class _DealAttachmentBody(BaseModel):
    kind: str
    filePath: str
    summary: Optional[str] = None
    sourceRunId: Optional[str] = None
    sourceSnapshotId: Optional[str] = None


class _KitDocApproveBody(BaseModel):
    # Toggle an offer-kit document's status from the card (approved / draft).
    status: Optional[str] = "approved"


class _KitFieldBody(BaseModel):
    # Save one editable kit-document field (the in-app, phone-friendly form input).
    key: str
    value: Optional[str] = ""


class _PullListingBody(BaseModel):
    # Pull a listing's docs/title/facts from Xposure by MLS #.
    mls: str


class _KitAddBody(BaseModel):
    # Add a form to the offer kit: upload a PDF (base64) or pick a catalog template.
    templateId: Optional[str] = None
    name: Optional[str] = None
    filename: Optional[str] = None
    contentB64: Optional[str] = None


class _DealFieldsBody(BaseModel):
    fields: Dict[str, Any]


class _RunResultArtifact(BaseModel):
    kind: str
    file_path: Optional[str] = None
    filePath: Optional[str] = None
    summary: Optional[str] = None
    source_snapshot_id: Optional[str] = None
    sourceSnapshotId: Optional[str] = None


class _RunResultBody(BaseModel):
    status: str
    idempotency_key: Optional[str] = None
    idempotencyKey: Optional[str] = None
    artifacts: List[_RunResultArtifact] = []
    next_tasks: List[Dict[str, Any]] = []
    nextTasks: List[Dict[str, Any]] = []
    checklist_updates: List[Dict[str, Any]] = []
    checklistUpdates: List[Dict[str, Any]] = []
    human_prompt: Optional[Dict[str, Any]] = None
    humanPrompt: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class _ManualReviewedRunDocumentBody(BaseModel):
    reviewed: bool = False
    kind: str
    formCode: str
    provider: str
    reviewerName: str
    versionStatus: str
    sourceReceipt: Dict[str, Any]
    documentVersion: Optional[str] = None
    effectiveDate: Optional[str] = None
    versionVerifiedAt: Optional[str] = None
    filename: Optional[str] = None
    contentB64: Optional[str] = None
    filePath: Optional[str] = None
    summary: Optional[str] = None


class _DealAdvanceBody(BaseModel):
    force: bool = False


def _model_dump(model: BaseModel) -> dict:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return model.dict(exclude_none=True)


_COLLAPSE_ACTOR = "dashboard:deal-collapsed-button"
_LISTING_RESET_STAGE = 5
_BUYER_RESET_STAGE = 0
_LISTING_CLEAR_FIELDS: Dict[str, Any] = {
    "offerDate": None,
    "subjectRemovalDate": None,
    "depositDueDate": None,
    "completionDate": None,
    "possessionDate": None,
    "offerPrice": None,
    "depositAmount": None,
    "offerAcceptedAt": None,
    "subjectsRemovedAt": None,
    "completedAt": None,
    "depositInTrustAt": None,
}
_BUYER_CLEAR_FIELDS: Dict[str, Any] = {
    **_LISTING_CLEAR_FIELDS,
    "mlsNumber": None,
    "legalDescription": None,
    "lotSizeSqft": None,
    "yearBuilt": None,
    "listPrice": None,
    "listingDate": None,
    "listingPublishedAt": None,
}
_LISTING_EXTRA_RE = re.compile(
    r"(buyer|purchaser|offer|accepted|deposit|subject|completion|possession|adjustment)",
    re.I,
)
_BUYER_EXTRA_RE = re.compile(
    # Also clear the OTHER-side (listing/cooperating) agent + brokerage: a
    # collapsed buyer deal reused for a new property has a different listing
    # side, and stale cooperating info bled into the Oakdale remuneration form.
    r"(property|listing|address|mls|legal|pid|strata|offer|accepted|deposit|subject|completion|possession|adjustment|cooperat|coop)",
    re.I,
)
_BUYER_ROLE_RE = re.compile(r"(buyer|purchaser|tenant)", re.I)

_DOCUMENT_SETUP_READY = {"configured", "connected", "manual"}
_DOCUMENT_ASSET_DEFAULTS = {
    "formEngine": "knowledge/deals/forms/fill-form-generic.py",
    "cpsAssembler": "knowledge/deals/forms/assemble-cps-terms.py",
    "clauseLibrary": "knowledge/deals/forms/webforms-clauses.json",
    "listingPull": "scripts/pull-listing-by-mls.js",
    "cpsGather": "scripts/cps-prep-package.sh",
    "cpsGenerate": "scripts/cps-generate.py",
    "offerForms": "scripts/offer-prep-forms.py",
    "offerPackage": "scripts/offer-prep-package.py",
    "dealDocuments": "scripts/deal-docs-list.py",
    "buyerAgency": "scripts/buyer-agency-fill.py",
    "cmaRunner": "scripts/cma-phase-runner.py",
    "cmaCaptureProspecting": "scripts/capture-prospecting.sh",
    "digisignEngine": "scripts/digisign_engine.py",
}
_DOCUMENT_TEMPLATE_DEFAULTS = {
    "cps-residential": "knowledge/deals/forms/cps-residential-fillable-template.pdf",
    "cps-mobile": "knowledge/deals/forms/cps-mobile-fillable-template.pdf",
    "cps-mobile-addendum": "knowledge/deals/forms/cps-mobile-addendum-template.pdf",
    "cps-addendum": "knowledge/deals/forms/cps-addendum-template.pdf",
    "disclosure-remuneration": "knowledge/deals/forms/disclosure-remuneration-template.pdf",
    "privacy-notice": "knowledge/deals/forms/privacy-notice-template.pdf",
    "bcfsa-disclosure": "knowledge/deals/forms/bcfsa-disclosure-template.pdf",
    "condition-waiver": "knowledge/deals/forms/condition-waiver-template.pdf",
    "subject-removal": "knowledge/deals/forms/subject-removal-template.pdf",
}


def _document_setup_error(code: str, message: str, **details: Any) -> None:
    raise HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": message,
            "setupKey": "forms_provider",
            **details,
        },
    )


def _document_setup_snapshot() -> Dict[str, Any]:
    from elevate_cli.data import connect, get_admin_setup

    with connect() as conn:
        return get_admin_setup(conn)


def _document_identity(snapshot: Mapping[str, Any] | None = None) -> tuple[str, str]:
    current = snapshot or _document_setup_snapshot()
    raw_profile = current.get("profile")
    profile = raw_profile if isinstance(raw_profile, Mapping) else {}
    realtor = str(profile.get("realtorLegalName") or profile.get("licenseName") or "").strip()
    brokerage = str(profile.get("brokerageName") or "").strip()
    missing = [
        field
        for field, value in (("realtorLegalName", realtor), ("brokerageName", brokerage))
        if not value
    ]
    if missing:
        _document_setup_error(
            "document_identity_incomplete",
            "Complete the realtor legal name and brokerage name in Admin Setup before generating forms.",
            missingFields=missing,
        )
    return realtor, brokerage


def _document_pack_config(
    snapshot: Mapping[str, Any] | None = None,
) -> tuple[Path, Mapping[str, Any]]:
    current = snapshot or _document_setup_snapshot()
    raw_items = current.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    item = next(
        (entry for entry in items if isinstance(entry, Mapping) and entry.get("key") == "forms_provider"),
        {},
    )
    raw_value = item.get("value") if isinstance(item, Mapping) else None
    value = raw_value if isinstance(raw_value, Mapping) else {}
    configured_root = value.get("documentPackRoot") or value.get("packRoot")
    explicit_root = os.environ.get("ELEVATE_DOCUMENT_PACK_ROOT", "").strip()
    root_value = configured_root or explicit_root
    if not root_value:
        _document_setup_error(
            "document_pack_not_configured",
            "Configure forms_provider.value.documentPackRoot in Admin Setup, or set ELEVATE_DOCUMENT_PACK_ROOT, before using document tools.",
        )
    if configured_root and str(item.get("status") or "") not in _DOCUMENT_SETUP_READY:
        _document_setup_error(
            "document_pack_not_verified",
            "Mark the Forms provider configured after verifying its documentPackRoot.",
        )
    root = Path(str(root_value)).expanduser()
    if not root.is_absolute():
        root = get_elevate_home() / root
    root = root.resolve()
    if not root.is_dir():
        _document_setup_error(
            "document_pack_missing",
            f"The configured document pack root does not exist: {root}",
            configuredPath=str(root),
        )
    return root, value


def _document_asset(
    asset_key: str,
    *,
    snapshot: Mapping[str, Any] | None = None,
    template_id: str | None = None,
) -> Path:
    root, config = _document_pack_config(snapshot)
    raw_assets = config.get("assets")
    assets = raw_assets if isinstance(raw_assets, Mapping) else {}
    if template_id is not None:
        raw_templates = config.get("templates")
        templates = raw_templates if isinstance(raw_templates, Mapping) else {}
        configured = templates.get(template_id)
        default = _DOCUMENT_TEMPLATE_DEFAULTS.get(template_id)
        label = f"template {template_id}"
    else:
        configured = assets.get(asset_key) or config.get(asset_key)
        default = _DOCUMENT_ASSET_DEFAULTS.get(asset_key)
        label = asset_key
    if not configured and not default:
        _document_setup_error(
            "document_asset_not_configured",
            f"No document-pack mapping exists for {label}.",
            asset=label,
        )
    candidate = Path(str(configured or default)).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        _document_setup_error(
            "document_asset_outside_pack",
            f"The configured {label} must remain inside the verified document pack root.",
            asset=label,
            configuredPath=str(candidate),
        )
    if not candidate.is_file():
        _document_setup_error(
            "document_asset_missing",
            f"The configured {label} file is missing: {candidate}",
            asset=label,
            configuredPath=str(candidate),
        )
    return candidate


def _artifact_slug(value: Any, fallback: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-.") or fallback


def _profile_artifact_dir(*parts: str) -> Path:
    profile_root = get_elevate_home().expanduser().resolve()
    path = profile_root.joinpath(*parts).resolve()
    try:
        path.relative_to(profile_root)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_artifact_outside_profile",
                "message": "The document artifact directory must remain inside the current Elevate profile.",
            },
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_exact_beta_forms_provider_for_local_document_mutation() -> None:
    """Fail closed before any mutable local Offer Kit/form-pack operation."""
    from elevate_constants import exact_realtor_beta_active

    if not exact_realtor_beta_active():
        return
    from elevate_cli.data import connect
    from elevate_cli.data.admin_setup import forms_provider_capability

    with connect() as conn:
        capability = forms_provider_capability(conn)
    provider_available = capability.get("available") is True
    raise HTTPException(
        status_code=409,
        detail={
            "code": "local_reference_form_route_disabled",
            "reason": (
                "provider_native_route_required"
                if provider_available
                else capability.get("reason") or "live_forms_provider_not_verified"
            ),
            "message": (
                "This exact-Beta route uses mutable local reference templates and is disabled. "
                "Complete the form in the licensed provider and attach the reviewed PDF."
            ),
            "manualCompletion": "Attach the reviewed PDF and manual export claim to the exact parked provider-form task.",
        },
    )


def _persist_manual_review_upload(
    *,
    deal_id: str,
    run_id: str,
    filename: str | None,
    content_b64: str,
) -> Path:
    """Persist one bounded browser-uploaded PDF inside the active profile."""
    import base64
    import binascii
    import tempfile
    import uuid

    encoded = str(content_b64 or "").strip()
    if encoded.startswith("data:"):
        encoded = encoded.partition(",")[2]
    if not encoded:
        raise HTTPException(status_code=400, detail="PDF content is required")
    if len(encoded) > 36 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF upload exceeds the 25 MB limit")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="PDF upload is not valid base64") from exc
    if not data or len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF upload exceeds the 25 MB limit")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="uploaded document is not a PDF")

    root = _profile_artifact_dir("uploads", "manual-reviewed-documents")
    original = _artifact_slug(filename or "reviewed-document.pdf", "reviewed-document.pdf")
    if not original.lower().endswith(".pdf"):
        original = f"{original}.pdf"
    destination = root / (
        f"{_artifact_slug(deal_id, 'deal')}-{_artifact_slug(run_id, 'run')}-"
        f"{uuid.uuid4().hex[:12]}-{original}"
    )
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.stem}-",
        suffix=".tmp",
        dir=root,
        delete=False,
    ) as staged:
        staged.write(data)
        staged.flush()
        os.fsync(staged.fileno())
        staged_path = Path(staged.name)
    try:
        os.replace(staged_path, destination)
    finally:
        try:
            staged_path.unlink()
        except OSError:
            pass
    return destination


def _is_pdf(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 5:
            return False
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _offer_kit_path(deal_id: str, doc_id: str) -> Path:
    root = _profile_artifact_dir("cache", "documents", "admin_artifacts", "offer-kits")
    return (
        root
        / f"{_artifact_slug(deal_id, 'deal')}-{_artifact_slug(doc_id, 'document')}.pdf"
    ).resolve()


def _verified_offer_kit_path(
    deal_id: str,
    doc_id: str,
    stored_path: Any,
    *,
    require_file: bool = False,
) -> Path:
    """Resolve a stored kit artifact only when it belongs to this profile."""
    expected = _offer_kit_path(deal_id, doc_id)
    candidate = Path(str(stored_path or "")).expanduser()
    if not candidate.is_absolute():
        candidate = get_elevate_home() / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        candidate = Path()
    if candidate != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_artifact_outside_profile",
                "message": "Regenerate this document inside the current Elevate profile before opening or approving it.",
            },
        )
    if require_file and not _is_pdf(expected):
        raise HTTPException(status_code=404, detail="kit document not generated yet")
    return expected


def _document_log_path(name: str) -> Path:
    root = _profile_artifact_dir("cache", "documents", "admin_artifacts", "logs")
    return (root / _artifact_slug(name, "document-tool.log")).resolve()


def _document_subprocess_env(*, clean_python: bool = False) -> Dict[str, str]:
    blocked = {
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONEXECUTABLE",
        "VIRTUAL_ENV",
        "PYTHONNOUSERSITE",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if not clean_python or key not in blocked
    }
    env["HOME"] = str(Path.home().expanduser().resolve())
    env["PATH"] = env.get("PATH") or "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    return env


def _document_runtime(kind: str, snapshot: Mapping[str, Any] | None = None) -> str:
    root, config = _document_pack_config(snapshot)
    defaults = {"python": "python3", "bash": "bash"}
    config_keys = {"python": "pythonExecutable", "bash": "bashExecutable"}
    env_keys = {"python": "ELEVATE_DOCUMENT_PYTHON", "bash": "ELEVATE_DOCUMENT_BASH"}
    raw_runtimes = config.get("runtimes")
    runtimes = raw_runtimes if isinstance(raw_runtimes, Mapping) else {}
    configured = (
        runtimes.get(kind)
        or config.get(config_keys[kind])
        or os.environ.get(env_keys[kind], "").strip()
    )
    command = str(configured or defaults[kind])
    if Path(command).is_absolute() or os.sep in command:
        candidate = Path(command).expanduser()
        relative_to_pack = not candidate.is_absolute()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if relative_to_pack:
            try:
                candidate.relative_to(root)
            except ValueError:
                _document_setup_error(
                    "document_runtime_outside_pack",
                    f"The configured {kind} runtime must remain inside the document pack.",
                    runtime=kind,
                    configuredPath=str(candidate),
                )
    else:
        found = shutil.which(command)
        candidate = Path(found).resolve() if found else Path()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        _document_setup_error(
            "document_runtime_missing",
            f"Configure an executable {kind} runtime for the document pack.",
            runtime=kind,
            configuredPath=str(candidate) if candidate != Path() else command,
        )
    return str(candidate)


@contextmanager
def _document_payload(payload: Mapping[str, Any], prefix: str):
    import json
    import tempfile

    root = _profile_artifact_dir("cache", "documents", "admin_artifacts", "payloads")
    with tempfile.NamedTemporaryFile(
        "w",
        prefix=f"{_artifact_slug(prefix, 'payload')}-",
        suffix=".json",
        dir=root,
        delete=False,
    ) as handle:
        json.dump(payload, handle)
        path = Path(handle.name)
    try:
        yield str(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _collapse_contact_name(item: Dict[str, Any]) -> str | None:
    contact = item.get("contact") or {}
    if not isinstance(contact, dict):
        return None
    for key in ("displayName", "display_name", "name", "fullName", "primaryEmail", "primary_email"):
        value = contact.get(key)
        if value:
            return str(value)
    return None


def _scrub_extra_toggles(conn: Any, deal_id: str, pattern: re.Pattern[str]) -> Dict[str, Any]:
    from elevate_cli.data.deals import _decode_json, _encode_json

    row = conn.execute("SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)).fetchone()
    extra = _decode_json(row["extra_toggles_json"]) if row and row["extra_toggles_json"] else {}
    if not isinstance(extra, dict):
        extra = {}
    # Never scrub the collapse archive itself (collapsedOfferHistory / collapsedAt
    # / collapseReason) -- its key contains "offer" and would match the buyer regex.
    removed = {key: extra[key] for key in list(extra.keys())
               if pattern.search(str(key)) and not str(key).lower().startswith("collapse")}
    if removed:
        for key in removed:
            extra.pop(key, None)
        conn.execute(
            "UPDATE deals SET extra_toggles_json=?, updated_at=? WHERE id=?",
            (
                _encode_json(extra),
                datetime.now(timezone.utc).isoformat(),
                deal_id,
            ),
        )
    return removed


def _remove_listing_buyers(conn: Any, deal_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, role, contact_id, notes FROM deal_contacts WHERE deal_id=?",
        (deal_id,),
    ).fetchall()
    removed: List[Dict[str, Any]] = []
    for row in rows:
        role = str(row["role"] or "")
        if _BUYER_ROLE_RE.search(role):
            removed.append(
                {
                    "id": row["id"],
                    "role": role,
                    "contactId": row["contact_id"],
                    "notes": row["notes"],
                }
            )
            conn.execute("DELETE FROM deal_contacts WHERE id=?", (row["id"],))
    return removed


def _maybe_rename_buyer_card(conn: Any, deal_id: str) -> str | None:
    from elevate_cli.data import list_deal_contacts

    contacts = list_deal_contacts(conn, deal_id)
    buyer_names: List[str] = []
    for item in contacts:
        role = str(item.get("role") or "")
        if _BUYER_ROLE_RE.search(role) or role.lower() in {"client", "primary"}:
            name = _collapse_contact_name(item)
            if name and name not in buyer_names:
                buyer_names.append(name)
    if not buyer_names:
        return None
    new_title = "Buyer: " + " & ".join(buyer_names[:2])
    conn.execute(
        "UPDATE deals SET title=?, updated_at=? WHERE id=?",
        (
            new_title,
            datetime.now(timezone.utc).isoformat(),
            deal_id,
        ),
    )
    return new_title


_CLIENT_DOC_ROLE_RE = {
    "buyer": re.compile(r"(buyer|purchaser|tenant|client|primary)", re.I),
    "listing": re.compile(r"(seller|vendor|landlord|client|primary)", re.I),
}


def _client_docs_dir(contact_id: str) -> Path:
    return _profile_artifact_dir("client-docs", _artifact_slug(contact_id, "contact"))


def _promote_client_documents(conn: Any, deal_id: str, side: str) -> Dict[str, Any]:
    """Safety net: before a collapse clears a deal, lift any client-level
    compliance docs (DORTS/PNC/FINTRAC/LOTR/BAEC) off the deal and onto the
    person, so they survive and can be reused on the client's next deal.

    Conservative on purpose:
      * only promotes when the deal has exactly ONE contact in the relevant
        role (avoids attaching one client's doc to another -- contamination);
      * marks promoted docs signed_status='unknown' (a collapse cannot visually
        verify signatures), so nothing auto-reuses an unverified doc later;
      * property/deal-level docs are left exactly where they are.

    Never raises to the caller -- returns a report of what happened.
    """
    from elevate_cli.data import (
        client_doc_type_for,
        list_deal_attachments,
        list_deal_contacts,
        upsert_contact_document,
    )

    promoted: List[Dict[str, Any]] = []
    unpromotable: List[Dict[str, Any]] = []

    role_re = _CLIENT_DOC_ROLE_RE.get(side, _CLIENT_DOC_ROLE_RE["buyer"])
    contacts = [
        c for c in list_deal_contacts(conn, deal_id)
        if role_re.search(str(c.get("role") or ""))
    ]
    # De-dupe contacts by id.
    seen_ids: set = set()
    role_contacts: List[Dict[str, Any]] = []
    for c in contacts:
        cid = c.get("contactId") or c.get("contact_id")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            role_contacts.append(c)

    attachments = list_deal_attachments(conn, deal_id, limit=500)
    for att in attachments:
        doc_type = client_doc_type_for(att.get("kind"), att.get("filePath"), att.get("summary"))
        if not doc_type:
            continue  # deal-level -- leave it on the deal
        if len(role_contacts) != 1:
            unpromotable.append({
                "docType": doc_type,
                "attachmentId": att.get("id"),
                "reason": (
                    "no matching-role contact on deal" if not role_contacts
                    else f"{len(role_contacts)} contacts on deal -- needs manual attribution"
                ),
            })
            continue
        contact = role_contacts[0]
        contact_id = contact.get("contactId") or contact.get("contact_id")
        src = att.get("filePath")
        dest_path = src
        try:
            if src and os.path.isfile(src):
                ext = os.path.splitext(src)[1] or ".pdf"
                dest = _client_docs_dir(contact_id) / f"{doc_type}-{att.get('id')}{ext}"
                shutil.copy2(src, dest)
                dest_path = str(dest)
        except Exception:
            _module_log.warning("client-doc copy failed for att %s", att.get("id"), exc_info=True)
            dest_path = src  # preserve the pointer even if the copy failed
        try:
            row = upsert_contact_document(
                conn,
                contact_id=contact_id,
                doc_type=doc_type,
                file_path=dest_path or "",
                signed_status="unknown",
                source_deal_id=deal_id,
                source_attachment_id=att.get("id"),
                verified_by="collapse-autopromote",
                summary=att.get("summary"),
            )
            promoted.append({
                "docType": doc_type,
                "contactId": contact_id,
                "contactDocumentId": row.get("id"),
            })
        except Exception as exc:
            unpromotable.append({
                "docType": doc_type,
                "attachmentId": att.get("id"),
                "reason": f"promote failed: {exc}",
            })

    return {"promoted": promoted, "unpromotable": unpromotable}


_CLIENT_DOC_LABELS = {
    "dorts": "DORTS (Representation Disclosure)",
    "pnc": "Privacy Notice & Consent",
    "fintrac_id": "FINTRAC Individual ID",
    "lotr": "LOTR",
    "baec": "Buyer Agency Agreement",
}


def _client_document_status_tag(doc: Dict[str, Any]) -> str:
    """A short status tag for the Documents-tab row: Reusable / Expires <date> /
    Verified <date> / Expired / Needs re-sign."""
    today = datetime.now(timezone.utc).date().isoformat()
    doc_type = doc.get("docType")
    valid_until = doc.get("validUntil")
    if doc.get("status") == "expired" or (valid_until and str(valid_until)[:10] < today):
        return "Expired"
    if doc.get("signedStatus") not in ("fully_signed", None) and doc.get("verifiedBy") == "collapse-autopromote":
        # preserved on collapse but signatures never visually confirmed
        return "Verify signing"
    if doc_type in ("dorts", "pnc"):
        return "Reusable"
    if valid_until:
        return f"Expires {str(valid_until)[:10]}"
    if doc.get("fintracVerifiedAt"):
        return f"Verified {str(doc['fintracVerifiedAt'])[:10]}"
    return "Client doc"


def _client_document_entries(deal_id: str) -> List[Dict[str, Any]]:
    """Return the deal's client-level documents shaped like the Documents-panel
    file rows, under a dedicated 'Client Documents' group. Resolved by the deal's
    contacts, so the same docs appear on every deal that client is on."""
    from elevate_cli.data import (
        connect,
        list_contact_documents_for_contacts,
        list_deal_contacts,
    )

    with connect() as conn:
        contacts = list_deal_contacts(conn, deal_id)
        contact_ids = [c.get("contactId") or c.get("contact_id") for c in contacts]
        docs = list_contact_documents_for_contacts(conn, [c for c in contact_ids if c])

    entries: List[Dict[str, Any]] = []
    for d in docs:
        drive_id = d.get("driveFileId")
        url = (
            f"https://drive.google.com/file/d/{drive_id}/view"
            if drive_id
            else f"/api/admin/contact-documents/{d['id']}/file"
        )
        entries.append({
            "name": _CLIENT_DOC_LABELS.get(d.get("docType"), d.get("docType") or "Client document"),
            "id": f"cd:{d['id']}",
            "url": url,
            "mime": "application/pdf",
            "modified": d.get("updatedAt") or d.get("createdAt") or "",
            "group": "Client Documents",
            "tag": _client_document_status_tag(d),
        })
    return entries


def _collapse_admin_deal(conn: Any, deal_id: str, requested_side: str | None) -> Dict[str, Any]:
    from elevate_cli.data import get_deal, move_deal_stage, set_deal_fields, set_deal_toggle
    from elevate_cli.data.deals import _insert_deal_event

    deal = get_deal(conn, deal_id)
    if deal is None:
        raise LookupError(f"deal {deal_id!r} not found")
    side = requested_side or deal.get("side")
    if side not in {"listing", "buyer"}:
        raise ValueError(f"unsupported deal side {side!r}")
    current_stage = int(deal.get("currentStage") or 0)
    if side == "listing" and current_stage not in {7, 8}:
        raise ValueError("listing deal collapse is only available from Accepted or Condition Removal")
    if side == "buyer" and current_stage not in {1, 2, 3}:
        raise ValueError("buyer deal collapse is only available from accepted-offer buyer stages")

    # Safety net: preserve client-level compliance docs on the person BEFORE we
    # clear/reset the deal, so a collapse never strands a reusable DORTS/PNC/
    # FINTRAC/LOTR/BAEC. Never let this break the collapse itself.
    try:
        client_docs_result = _promote_client_documents(conn, deal_id, side)
    except Exception:
        _module_log.exception("client-doc promotion failed for deal %s (collapse continues)", deal_id)
        client_docs_result = {"promoted": [], "unpromotable": [], "error": "promotion_failed"}

    target_stage = _LISTING_RESET_STAGE if side == "listing" else _BUYER_RESET_STAGE
    clear_fields = _LISTING_CLEAR_FIELDS if side == "listing" else _BUYER_CLEAR_FIELDS
    removed_contacts = _remove_listing_buyers(conn, deal_id) if side == "listing" else []
    removed_extra = _scrub_extra_toggles(conn, deal_id, _LISTING_EXTRA_RE if side == "listing" else _BUYER_EXTRA_RE)
    new_title = None

    # Archive everything that belonged to the dead deal -- the offer/property
    # columns we're about to clear AND the scrubbed extra (cooperating agent/
    # brokerage, etc.) -- to extra.collapsedOfferHistory[] so it's preserved, not
    # just deleted. Never let this break the collapse.
    try:
        from elevate_cli.data.deals import _decode_json, _encode_json
        archived = {k: deal.get(k) for k in clear_fields if deal.get(k) not in (None, "")}
        archived.update({k: v for k, v in (removed_extra or {}).items() if v not in (None, "")})
        if archived:
            erow = conn.execute("SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)).fetchone()
            extra = _decode_json(erow["extra_toggles_json"]) if erow and erow["extra_toggles_json"] else {}
            if not isinstance(extra, dict):
                extra = {}
            hist = extra.get("collapsedOfferHistory")
            if not isinstance(hist, list):
                hist = []
            archived["collapsedAt"] = datetime.now(timezone.utc).isoformat()
            archived["side"] = side
            hist.append(archived)
            extra["collapsedOfferHistory"] = hist
            conn.execute(
                "UPDATE deals SET extra_toggles_json=?, updated_at=? WHERE id=?",
                (_encode_json(extra), datetime.now(timezone.utc).isoformat(), deal_id),
            )
    except Exception:
        _module_log.warning("collapse archive to collapsedOfferHistory failed for %s", deal_id, exc_info=True)

    set_deal_fields(conn, deal_id, actor=_COLLAPSE_ACTOR, fields=clear_fields)
    if side == "buyer":
        conn.execute(
            "UPDATE deals SET listing_address=NULL, source_row_id=NULL, updated_at=? WHERE id=?",
            (
                datetime.now(timezone.utc).isoformat(),
                deal_id,
            ),
        )
        new_title = _maybe_rename_buyer_card(conn, deal_id)
    set_deal_toggle(conn, deal_id, field="deal_collapsed", value=True, actor=_COLLAPSE_ACTOR)
    set_deal_toggle(conn, deal_id, field="collapsed_reset_target_stage", value=target_stage, actor=_COLLAPSE_ACTOR)
    set_deal_toggle(conn, deal_id, field="collapsed_reset_side", value=side, actor=_COLLAPSE_ACTOR)
    moved = move_deal_stage(conn, deal_id, to_stage=target_stage, actor=_COLLAPSE_ACTOR, force=True)
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="toggle_change",
        actor=_COLLAPSE_ACTOR,
        field_name="deal_collapsed_reset",
        old_value={"stage": current_stage, "side": side},
        new_value={"stage": target_stage, "side": side},
        payload={
            "reason": "deal_collapsed_button",
            "listingBehavior": "move_to_listing_live_and_clear_previous_buyers",
            "buyerBehavior": "move_to_top_25_and_clear_property_information",
            "clearedFields": sorted(clear_fields.keys()),
            "removedBuyerContacts": removed_contacts,
            "removedExtraKeys": sorted(removed_extra.keys()),
            "newTitle": new_title,
            "promotedClientDocs": client_docs_result.get("promoted", []),
            "unpromotableClientDocs": client_docs_result.get("unpromotable", []),
        },
    )
    return {
        "success": True,
        "deal": moved,
        "targetStage": target_stage,
        "removedBuyerContacts": len(removed_contacts),
        "removedExtraKeys": sorted(removed_extra.keys()),
        "newTitle": new_title,
        "promotedClientDocs": client_docs_result.get("promoted", []),
        "unpromotableClientDocs": client_docs_result.get("unpromotable", []),
    }


def create_admin_deals_router(
    *,
    require_admin_setup_ready_for_launch: RequireReady,
    admin_jurisdiction_config: AdminJurisdictionConfig,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/deals")
    def get_admin_deals(
        side: Optional[str] = None,
        current_stage: Optional[int] = None,
        status: Optional[str] = "active",
        province: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        try:
            from elevate_cli.data import connect, list_deals
            from elevate_cli.data.deals import deal_card_gate

            with connect() as conn:
                rows = list_deals(
                    conn,
                    side=side or None,
                    current_stage=current_stage,
                    status=status or None,
                    province=province.strip().upper() if province and province.strip() else None,
                    limit=limit,
                    offset=offset,
                )
                for row in rows:
                    try:
                        scorecard = deal_card_gate(conn, row)
                        row["scorecard"] = scorecard
                        if scorecard.get("progress"):
                            row["progress"] = scorecard["progress"]
                    except Exception:
                        _log.debug("deal_card_gate failed for deal %s", row.get("id"), exc_info=True)
                return {"items": rows, "count": len(rows), "jurisdiction": admin_jurisdiction_config()}
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/deals failed")
            raise HTTPException(status_code=500, detail=f"Admin deals failed: {exc}")

    @router.get("/api/admin/upcoming-events")
    def get_admin_upcoming_events(days: int = 21):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data.admin_calendar import list_upcoming_admin_events

            safe_days = max(1, min(int(days or 21), 90))
            with connect() as conn:
                return list_upcoming_admin_events(conn, days=safe_days)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/upcoming-events failed")
            raise HTTPException(status_code=500, detail=f"Admin upcoming events failed: {exc}")

    @router.post("/api/admin/deals")
    def post_admin_deal(body: _DealCreateBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, create_deal, get_admin_setup

            jurisdiction = admin_jurisdiction_config()
            with connect() as conn:
                setup_profile = (get_admin_setup(conn).get("profile") or {})
                province = body.province if body.province is not None else (jurisdiction["province"] or setup_profile.get("province"))
                market = body.market if body.market is not None else (jurisdiction["market"] or setup_profile.get("market"))
                from elevate_cli.data.beta_province_pack import enforce_exact_beta_province

                enforce_exact_beta_province(province)
                return create_deal(
                    conn,
                    title=body.title,
                    side=body.side,
                    actor=web_actor,
                    province=(province or "").strip().upper(),
                    board=(body.board or "").strip() or None,
                    market=(market or "").strip() or None,
                    current_stage=body.currentStage,
                    primary_contact_id=body.primaryContactId,
                    lofty_contact_id=body.loftyContactId,
                    listing_address=body.listingAddress,
                    fields=body.fields,
                    dispatch_initial_stage=body.dispatchInitialStage and not body.suppressInitialDispatch,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals failed")
            raise HTTPException(status_code=500, detail=f"Create deal failed: {exc}")

    @router.post("/api/admin/profile-promotions")
    def post_admin_profile_promotion(body: _ProfilePromotionBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, get_admin_setup, promote_profile_to_admin_deal

            jurisdiction = admin_jurisdiction_config()
            with connect() as conn:
                setup_profile = (get_admin_setup(conn).get("profile") or {})
                province = body.province if body.province is not None else (jurisdiction["province"] or setup_profile.get("province"))
                market = body.market if body.market is not None else (jurisdiction["market"] or setup_profile.get("market"))
                from elevate_cli.data.beta_province_pack import enforce_exact_beta_province

                enforce_exact_beta_province(province)
                return promote_profile_to_admin_deal(
                    conn,
                    profile_id=body.profileId,
                    side=body.side,
                    actor=web_actor,
                    province=(province or "").strip().upper(),
                    board=(body.board or "").strip() or None,
                    market=(market or "").strip() or None,
                    current_stage=body.currentStage,
                    display_name=body.displayName,
                    primary_contact_id=body.primaryContactId,
                    listing_address=body.listingAddress,
                    workflow=body.workflow,
                    profile_context=body.profileContext,
                    verifiers=body.verifiers,
                    fields=body.fields,
                    dispatch_initial_stage=body.dispatchInitialStage,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/profile-promotions failed")
            raise HTTPException(status_code=500, detail=f"Promote profile failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/move")
    def post_admin_deal_move(deal_id: str, body: _DealMoveBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, move_deal_stage

            with connect() as conn:
                return move_deal_stage(
                    conn,
                    deal_id,
                    to_stage=body.toStage,
                    actor=web_actor,
                    force=body.force,
                )
        except HTTPException:
            raise
        except DealPhaseGateBlocked as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "gate": exc.gate,
                },
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/move failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Move deal failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/collapse")
    def post_admin_deal_collapse(deal_id: str, body: _DealCollapseBody):
        try:
            require_admin_setup_ready_for_launch()
            requested_side = body.side if body.side in {"listing", "buyer", None} else None
            from elevate_cli.data import connect

            with connect() as conn:
                result = _collapse_admin_deal(conn, deal_id, requested_side)
                conn.commit()
                return result
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/collapse failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Collapse deal failed: {exc}")

    @router.get("/api/admin/deals/deadlines")
    def get_admin_deal_deadlines(near_subject_days: int = 21, near_close_days: int = 30):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, deals_overview

            with connect() as conn:
                ov = deals_overview(
                    conn,
                    near_subject_days=near_subject_days,
                    near_close_days=near_close_days,
                )
            return {
                "subjectsSoon": ov.get("subjectsSoon", []),
                "closingsSoon": ov.get("closingsSoon", []),
                "staleStages": ov.get("staleStages", []),
            }
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/deadlines failed")
            raise HTTPException(status_code=500, detail=f"Deadlines failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/toggle")
    def post_admin_deal_toggle(deal_id: str, body: _DealToggleBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, set_deal_toggle

            with connect() as conn:
                return set_deal_toggle(
                    conn,
                    deal_id,
                    field=body.field,
                    value=body.value,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/toggle failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Toggle deal failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/cma-pdf")
    def get_admin_deal_cma_pdf(deal_id: str):
        # Auth is enforced by the dashboard middleware (Bearer header or, for
        # window.open() new-tab loads, the ?token= query param — see web_auth).
        try:
            from elevate_cli.data import connect, list_deal_attachments

            with connect() as conn:
                rows = list_deal_attachments(conn, deal_id, kind="cma_report", limit=1)
            if not rows:
                raise HTTPException(status_code=404, detail="no final CMA on file")
            file_path = rows[0].get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="CMA file missing")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="inline",
            )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/cma-pdf failed", deal_id)
            raise HTTPException(status_code=500, detail=f"CMA PDF failed: {exc}")

    @router.get("/api/deals/{deal_id}/run-draft-pdf/{run_id}")
    @router.get("/api/admin/deals/{deal_id}/run-draft-pdf/{run_id}")
    def get_run_draft_pdf(deal_id: str, run_id: str):
        # Serves the `previewPdf` a waiting_human run parked in its
        # human_prompt_json, so the WAITING ON YOU / ACTION NEEDED card's
        # "Preview PDF ↗" opens the actual drafted document. Auth via the
        # dashboard middleware (Bearer header or ?token= for window.open new-tab
        # loads — path whitelisted by _DRAFT_PDF_PATH_RE in web_auth). Without
        # this route the path fell through to the SPA catch-all and the button
        # opened a blank dashboard tab instead of the PDF.
        try:
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT deal_id, human_prompt_json FROM admin_action_runs WHERE id=?",
                    (run_id,),
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="run not found")
            if row["deal_id"] and deal_id and row["deal_id"] != deal_id:
                raise HTTPException(status_code=404, detail="run does not belong to deal")
            prompt: Dict[str, Any] = {}
            try:
                hp = row["human_prompt_json"]
                prompt = _json.loads(hp) if hp and str(hp).strip() else {}
            except Exception:
                prompt = {}
            file_path = prompt.get("previewPdf") or prompt.get("preview_pdf") or ""
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="preview PDF missing")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET run-draft-pdf failed for run %s", run_id)
            raise HTTPException(status_code=500, detail=f"preview PDF failed: {exc}")

    @router.get("/api/deals/{deal_id}/seller-update-pdf")
    @router.get("/api/admin/deals/{deal_id}/seller-update-pdf")
    def get_admin_deal_seller_update_pdf(deal_id: str):
        # Auth is enforced by the dashboard middleware (Bearer header or, for
        # window.open() new-tab loads, the ?token= query param — see web_auth).
        # Scorecards use `seller_update` for the clickable latest PDF, while
        # run/audit history can store `seller_update_pdf`; accept both and serve
        # the newest existing local PDF inline.
        try:
            from elevate_cli.data import connect, list_deal_attachments

            rows = []
            with connect() as conn:
                for kind in ("seller_update", "seller_update_pdf"):
                    rows.extend(list_deal_attachments(cast(Any, conn), deal_id, kind=kind, limit=5))
            rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
            for row in rows:
                file_path = row.get("filePath")
                if file_path and os.path.exists(file_path):
                    return FileResponse(
                        file_path,
                        media_type="application/pdf",
                        filename=os.path.basename(file_path),
                        content_disposition_type="inline",
                    )
            if rows:
                raise HTTPException(status_code=404, detail="weekly update PDF file missing")
            raise HTTPException(status_code=404, detail="no weekly update PDF on file")
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/seller-update-pdf failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Seller update PDF failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/kit-doc/{doc_id}")
    def get_admin_deal_kit_doc(deal_id: str, doc_id: str, download: int = 0):
        # Serve one offer-kit document PDF. download=0 → inline (quick read-only
        # view in a browser tab). download=1 → attachment, so it saves and opens
        # in Preview/Acrobat where the AcroForm fields are actually editable
        # (browser tabs render forms read-only). Auth: Bearer header or ?token=.
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="deal not found")
            raw = row["extra_toggles_json"]
            toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            docs = ((toggles.get("offerKit") or {}).get("documents") or [])
            doc = next((d for d in docs if d.get("id") == doc_id), None)
            if not doc:
                raise HTTPException(status_code=404, detail="kit document not found")
            file_path = _verified_offer_kit_path(
                deal_id,
                doc_id,
                doc.get("filePath"),
                require_file=True,
            )
            if not doc.get("ready"):
                raise HTTPException(status_code=409, detail="regenerate this document before opening it")
            return FileResponse(
                str(file_path),
                media_type="application/pdf",
                filename=file_path.name,
                content_disposition_type="attachment" if download else "inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/kit-doc/%s failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit doc failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/approve")
    def post_admin_deal_kit_doc_approve(deal_id: str, doc_id: str, body: _KitDocApproveBody):
        # Toggle a kit document's status (approved / draft) from the card.
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            import json as _json
            from elevate_cli.data import connect

            new_status = (body.status or "approved").strip() or "approved"
            if new_status not in {"approved", "draft"}:
                raise HTTPException(status_code=400, detail="status must be approved or draft")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                docs = kit.get("documents") or []
                found = False
                for d in docs:
                    if d.get("id") == doc_id:
                        if new_status == "approved":
                            _verified_offer_kit_path(
                                deal_id,
                                doc_id,
                                d.get("filePath"),
                                require_file=True,
                            )
                            if not d.get("ready"):
                                raise HTTPException(
                                    status_code=409,
                                    detail="regenerate this document before approving it",
                                )
                        d["status"] = new_status
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="kit document not found")
                kit["documents"] = docs
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "status": new_status}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/%s/approve failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit doc approve failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/field")
    def post_admin_deal_kit_doc_field(deal_id: str, doc_id: str, body: _KitFieldBody):
        # Save one editable form field for a kit document (the in-app inputs the
        # operator edits on the card / on their phone).
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                docs = kit.get("documents") or []
                found = False
                for d in docs:
                    if d.get("id") == doc_id:
                        flds = d.get("fields") or {}
                        flds[body.key] = body.value or ""
                        d["fields"] = flds
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="kit document not found")
                for d in docs:
                    if doc_id == "cps-residential" or d.get("id") == doc_id:
                        d["ready"] = False
                        d["status"] = "draft"
                kit["documents"] = docs
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "key": body.key, "value": body.value}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/%s/field failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit field save failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/generate")
    def post_admin_deal_kit_doc_generate(deal_id: str, doc_id: str):
        # Fill the official fillable form template from the document's card fields
        # and write the per-deal editable PDF. This is the "Generate" button: the
        # operator edits fields on the card, then generates the compliant PDF.
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            import json as _json
            import subprocess
            import tempfile
            from elevate_cli.data import connect

            snapshot = _document_setup_snapshot()
            realtor_name, brokerage_name = _document_identity(snapshot)
            engine = _document_asset("formEngine", snapshot=snapshot)
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json, legal_description FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                deal_legal = row["legal_description"] or ""
                kit = toggles.get("offerKit") or {}
                docs = kit.get("documents") or []
                doc = next((d for d in docs if d.get("id") == doc_id), None)
                if not doc:
                    raise HTTPException(status_code=404, detail="kit document not found")
            if doc_id not in _DOCUMENT_TEMPLATE_DEFAULTS:
                raise HTTPException(status_code=400, detail="no template wired for this document yet")
            umbrella = (toggles.get("cpsUmbrella") or "residential").strip().lower()
            is_mobile = umbrella == "mobile"
            # A mobile deal fills the base CPS slot on the Manufactured Home
            # (Rental Pad) contract, not the residential form. The manufactured
            # subjects live on a separate addendum (cps-mobile-addendum), so the
            # base CPS Section 3 only points to it.
            if doc_id == "cps-residential" and is_mobile:
                template = _document_asset("template", snapshot=snapshot, template_id="cps-mobile")
            else:
                template = _document_asset("template", snapshot=snapshot, template_id=doc_id)
            # Canonical data lives on the CPS doc's fields; every form fills from it.
            cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
            cf = cps.get("fields") or {}
            pp = [x.strip() for x in str(cf.get("property", "")).split(",")]
            pnum = pstreet = pcity = pstate = pzip = ""
            if pp and pp[0]:
                sp = pp[0].split(" ", 1)
                if sp and sp[0].isdigit():
                    pnum, pstreet = sp[0], (sp[1] if len(sp) > 1 else "")
                else:
                    pstreet = pp[0]
            if len(pp) >= 2:
                pcity = pp[1]
            if len(pp) >= 3:
                ps = pp[2].split(" ", 1)
                pstate, pzip = ps[0], (ps[1] if len(ps) > 1 else "")
            sellers = [x.strip() for x in str(toggles.get("sellerNames") or "").split(",") if x.strip()]
            import datetime as _dt
            today = _dt.date.today().isoformat()
            context = {
                "buyer1": cf.get("buyer1", ""), "buyer2": cf.get("buyer2", ""), "buyer3": cf.get("buyer3", ""),
                "seller1": sellers[0] if len(sellers) > 0 else "",
                "seller2": sellers[1] if len(sellers) > 1 else "",
                "p_streetnum": pnum, "p_street": pstreet, "p_city": pcity, "p_state": pstate, "p_zip": pzip,
                "p_unit": (cf.get("p_unit") or toggles.get("mhParkPad") or ""),
                "legal": (cf.get("legal") or deal_legal or toggles.get("legalDescription") or ""),
                "pid": (cf.get("pid") or toggles.get("pid") or ""),
                "otherPids": (cf.get("otherPids") or toggles.get("otherPids") or ""),
                "possessionTime": (cf.get("possessionTime") or toggles.get("acceptedOffer.possessionTime") or ""),
                "mls": str(toggles.get("mlsNumber") or toggles.get("mls") or ""),
                "agentName": realtor_name, "officeName": brokerage_name,
                "price": cf.get("price", ""), "priceWords": cf.get("priceWords", ""),
                "deposit": cf.get("deposit", ""), "depositHolder": cf.get("depositHolder", ""),
                "depositDue": cf.get("depositDue", ""),
                "completionDate": cf.get("completionDate", ""), "possessionDate": cf.get("possessionDate", ""),
                "adjustmentDate": cf.get("adjustmentDate", ""),
                "included": cf.get("included", ""), "excluded": cf.get("excluded", ""), "conditions": cf.get("conditions", ""),
                "today": today, "contractDate": cf.get("contractDate", "") or today,
                # Manufactured-home specs — fill the addendum's mobile fields
                # (Registration #, Serial #, CSA/electrical, make/model/year).
                "mhRegistration": (cf.get("mhRegistration") or toggles.get("mhRegistration") or ""),
                "mhSerial": (cf.get("mhSerial") or toggles.get("mhSerial") or ""),
                "mhCsaLabel": (cf.get("mhCsaLabel") or toggles.get("mhCsaLabel") or ""),
                "mhMake": (cf.get("mhMake") or toggles.get("mhMake") or ""),
                "mhModel": (cf.get("mhModel") or toggles.get("mhModel") or ""),
                "mhYear": (cf.get("mhYear") or toggles.get("mhYear") or ""),
            }
            # Assemble the wizard's selected subjects/clauses into the CPS Section-3
            # terms text (numbered, sole-benefit line). Overrides the free-text
            # conditions so the contract reflects the Subjects step.
            cps_clauses = toggles.get("cpsClauses") or []
            cps_custom = toggles.get("cpsCustomClauses") or []
            asm_warnings: list = []
            def _split_addendum_schedule(text):
                # Distribute the assembled subjects across the Manufactured Home
                # Addendum's 3 equal schedule boxes (9.5pt) so each page reads
                # spaced, not crammed. Build atomic units (intro line, each
                # numbered subject, each trailing clause), give every unit a
                # blank-line separator, then choose the 2 page-breaks that
                # minimize the tallest page (balanced partition), breaking only
                # between whole units so no subject is cut mid-sentence.
                # ~95 chars/line approximates the ~548pt-wide box at 9.5pt.
                import re as _re
                CPL = 95
                def _ulines(u):
                    n = 0
                    for para in u.split("\n"):
                        n += 1 if not para else max(1, -(-len(para) // CPL))
                    return n
                units, cur = [], []
                def _flush():
                    if cur:
                        units.append("\n".join(cur)); cur.clear()
                for ln in text.split("\n"):
                    if _re.match(r"^\d+\)\s", ln):
                        _flush(); cur.append(ln)
                    elif ln == "":
                        _flush()
                    elif cur and not _re.match(r"^\d+\)\s", cur[0]):
                        cur.append(ln)
                    else:
                        _flush(); cur.append(ln)
                _flush()
                if len(units) <= 3:
                    padded = units + [""] * (3 - len(units))
                    return padded[0], padded[1], padded[2]
                w = [_ulines(u) + 1 for u in units]  # +1 blank separator/unit
                N = len(units)
                best = None
                for i in range(1, N - 1):
                    for j in range(i + 1, N):
                        m = max(sum(w[0:i]), sum(w[i:j]), sum(w[j:N]))
                        if best is None or m < best[0]:
                            best = (m, i, j)
                _, i, j = best
                groups = [units[0:i], units[i:j], units[j:N]]
                return tuple("\n\n".join(g).strip() for g in groups)

            if is_mobile:
                if doc_id == "cps-mobile-addendum":
                    # The Manufactured Home Addendum carries the wizard's selected
                    # subjects (assembled below, split across its 3 schedule pages).
                    # With NOTHING selected, keep the template's standard boilerplate.
                    if not (cps_clauses or cps_custom):
                        context["preserveSchedule"] = True
                        context["conditions"] = ""
                else:
                    # Base Manufactured Home CPS Section 3 just points to the addendum.
                    context["conditions"] = "see attached addendum"
            # Assemble the selected subjects for any non-mobile CPS OR the mobile
            # addendum (the base mobile CPS never assembles — it points to the
            # addendum). A custom-only deal must still get its terms.
            assemble_here = bool(cps_clauses or cps_custom) and (
                (not is_mobile) or doc_id == "cps-mobile-addendum"
            )
            if assemble_here:
                asm_input = {
                    "umbrella": toggles.get("cpsUmbrella") or "residential",
                    "selections": cps_clauses,
                    "vars": {**(toggles.get("cpsVars") or {}), "subject_removal_date": toggles.get("subjectRemovalDate") or ""},
                    "custom": cps_custom,
                }
                assembler = _document_asset("cpsAssembler", snapshot=snapshot)
                with _document_payload(asm_input, "cps-terms") as asm_path:
                    asm = subprocess.run(
                        [_document_runtime("python", snapshot), str(assembler), asm_path],
                        capture_output=True, text=True, timeout=30,
                        env=_document_subprocess_env(clean_python=True),
                    )
                if asm.returncode != 0 or not asm.stdout.strip():
                    raise HTTPException(
                        status_code=500,
                        detail=f"clause assembly failed: {(asm.stderr or '')[:300]}",
                    )
                assembled = asm.stdout.strip()
                if doc_id == "cps-mobile-addendum":
                    # Flow the assembled subjects across the addendum's 3 pages.
                    c1, c2, c3 = _split_addendum_schedule(assembled)
                    context["conditions"] = c1
                    context["conditions2"] = c2
                    context["conditions3"] = c3
                else:
                    context["conditions"] = assembled
                # Surface any "unknown clause id" warnings the assembler emitted
                # (frontend/library drift) so a dropped subject is visible, not silent.
                for ln in (asm.stderr or "").splitlines():
                    if "unknown clause id" in ln:
                        asm_warnings.append(ln.split("WARNING:", 1)[-1].strip())
            out_path = _offer_kit_path(deal_id, doc_id)
            with tempfile.NamedTemporaryFile(
                prefix=f".{out_path.stem}-",
                suffix=".pdf",
                dir=out_path.parent,
                delete=False,
            ) as staged:
                staged_path = Path(staged.name)
            try:
                staged_path.unlink()
            except OSError:
                pass
            # Clean env: the app sets PYTHON* vars that can point the configured
            # app runtime (no pypdf). HOME must be set so it finds user-site pypdf.
            filled = None
            try:
                with _document_payload(context, "form-context") as ctx_path:
                    proc = subprocess.run(
                        [
                            _document_runtime("python", snapshot),
                            str(engine),
                            ctx_path,
                            str(template),
                            str(staged_path),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        env=_document_subprocess_env(clean_python=True),
                    )
                if proc.returncode != 0:
                    raise HTTPException(status_code=500, detail=f"fill failed: {(proc.stderr or '')[:300]}")
                if not _is_pdf(staged_path):
                    raise HTTPException(
                        status_code=500,
                        detail="fill engine exited successfully but did not produce a valid new PDF",
                    )
                # Post-fill verification: the filler prints "filled X/Y fields" to
                # stdout. A truthy PDF that filled 0 fields is a silent failure —
                # treat it as one.
                import re as _re
                m = _re.search(r"filled\s+(\d+)\s*/\s*(\d+)", proc.stdout or "")
                if m:
                    filled = int(m.group(1))
                if filled == 0:
                    raise HTTPException(status_code=500, detail="fill wrote 0 fields — check the template + field mapping")
                os.replace(staged_path, out_path)
            finally:
                try:
                    staged_path.unlink()
                except OSError:
                    pass
            # Surface blank required fields so the card can prompt instead of
            # shipping a hollow contract that looked "done".
            warnings = []
            if doc_id == "cps-residential":
                required = {
                    "buyer": context.get("buyer1", ""),
                    "property": context.get("p_street", "") or context.get("property", ""),
                    "price": context.get("price", ""),
                    "completion date": context.get("completionDate", ""),
                }
                if cps_clauses or cps_custom:
                    required["subjects/conditions"] = context.get("conditions", "")
                warnings = [f"{label} is blank" for label, val in required.items() if not str(val).strip()]
            warnings = warnings + asm_warnings
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {}
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        d["filePath"] = str(out_path)
                        d["ready"] = True
                        d["status"] = "draft"
                        d["warnings"] = warnings
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "generated": True, "filePath": str(out_path),
                    "filled": filled, "warnings": warnings}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/%s/generate failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Generate failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/offer-kit/build")
    def post_admin_deal_build_offer_kit(deal_id: str):
        # Build / refresh the offer kit for a buyer deal, seeding each document's
        # fields from the deal's data so most of the form is pre-filled. Preserves
        # operator edits on an existing kit (the deal only fills blanks).
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json, listing_address FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                listing = row["listing_address"] or ""

                def ao(k):
                    return str(toggles.get("acceptedOffer." + k) or "")

                # Terms come from the Offer Kit wizard's Step-2 fields, saved as
                # bare toggles (cpsPurchasePrice, cpsDeposit, cpsDepositTerms,
                # cpsInclusions, cpsExclusions, completionDate/possessionDate/
                # adjustmentDate). At offer-prep stage the acceptedOffer.* keys do
                # not exist yet, so seed from the wizard keys first and only fall
                # back to acceptedOffer.* for post-acceptance re-builds. Without
                # this the generated CPS came out blank on price/deposit/dates.
                def term(wizard_key, ao_key):
                    return str(toggles.get(wizard_key) or "").strip() or ao(ao_key)

                bn = toggles.get("buyerNames") or ", ".join(toggles.get("skyslopeBuyerNames") or [])
                parts = [p.strip() for p in str(bn).split(",") if p.strip()]
                seeded = {
                    "buyer1": parts[0] if len(parts) > 0 else "",
                    "buyer2": parts[1] if len(parts) > 1 else "",
                    "property": listing,
                    "price": term("cpsPurchasePrice", "purchasePrice"),
                    "priceWords": "",
                    "deposit": term("cpsDeposit", "depositAmount"),
                    "depositHolder": ao("depositHolder") or "Listing Brokerage in trust",
                    "depositDue": term("cpsDepositTerms", "depositDue"),
                    "completionDate": term("completionDate", "completionDate"),
                    "possessionDate": term("possessionDate", "possessionDate"),
                    "adjustmentDate": term("adjustmentDate", "adjustmentDate"),
                    "included": term("cpsInclusions", "includedItems"),
                    "excluded": term("cpsExclusions", "excludedItems"),
                    "conditions": str(toggles.get("subjectConditions") or ""),
                }
                existing = toggles.get("offerKit") or {}
                ex_docs = existing.get("documents") or []
                ex_by_id = {d.get("id"): d for d in ex_docs if d.get("id")}

                # The standard forms + their default on/off (mirrors the wizard's
                # KIT_FORM_DEFAULTS). Only forms kept ON get a slot. A mobile deal
                # swaps the residential CPS + generic addendum for the Manufactured
                # Home (Rental Pad) contract + its dedicated standard addendum.
                umbrella = (toggles.get("cpsUmbrella") or "residential").strip().lower()
                is_mobile = umbrella == "mobile"
                if is_mobile:
                    STD = [
                        ("cps-residential", "CPS - Manufactured Home (Rental Pad)", True),
                        ("cps-mobile-addendum", "CPS - Manufactured Home Addendum", True),
                        ("disclosure-remuneration", "Disclosure of Remuneration (RECBC 5-11)", False),
                        ("privacy-notice", "Privacy Notice and Consent", True),
                        ("bcfsa-disclosure", "BCFSA - Disclosure of Representation", True),
                        ("condition-waiver", "Notice of Condition Waiver / Declaration of Fulfillment", True),
                    ]
                else:
                    STD = [
                        ("cps-residential", "CPS - Residential", True),
                        ("cps-addendum", "CPS - Addendum / Amendment", True),
                        ("disclosure-remuneration", "Disclosure of Remuneration (RECBC 5-11)", False),
                        ("privacy-notice", "Privacy Notice and Consent", True),
                        ("bcfsa-disclosure", "BCFSA - Disclosure of Representation", True),
                        ("condition-waiver", "Notice of Condition Waiver / Declaration of Fulfillment", True),
                    ]
                # Union of every umbrella's standard ids — decides which existing
                # docs are truly custom (preserve) vs stale standard docs left over
                # from a prior umbrella (drop on rebuild, e.g. the residential CPS
                # + generic addendum when switching a deal to mobile).
                std_ids = {
                    "cps-residential", "cps-addendum", "cps-mobile-addendum",
                    "disclosure-remuneration", "privacy-notice",
                    "bcfsa-disclosure", "condition-waiver",
                }
                kit_forms = toggles.get("cpsKitForms") or {}

                def _enabled(fid, dflt):
                    v = kit_forms.get(fid)
                    return bool(dflt) if v is None else bool(v)

                documents = []
                for sid, sname, dflt in STD:
                    if not _enabled(sid, dflt):
                        continue
                    prev = ex_by_id.get(sid) or {}
                    # The CPS + mobile addendum seed their fields from the deal;
                    # keep any operator edits.
                    fields = None
                    if sid in ("cps-residential", "cps-mobile-addendum"):
                        fields = dict(seeded)
                        for k, v in (prev.get("fields") or {}).items():
                            if v:
                                fields[k] = v
                    path = _offer_kit_path(deal_id, sid)
                    doc = {
                        "id": sid,
                        "name": sname,
                        "status": prev.get("status", "draft"),
                        "fillable": True,
                        "ready": bool(prev.get("ready")) and _is_pdf(path),
                        "filePath": str(path),
                    }
                    if fields is not None:
                        doc["fields"] = fields
                    documents.append(doc)

                # Preserve any custom / uploaded documents (ids outside the six
                # standard forms) — hitting Build must never drop them.
                for d in ex_docs:
                    if d.get("id") and d.get("id") not in std_ids:
                        documents.append(d)

                kit = {"createdAt": existing.get("createdAt") or "", "documents": documents}
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"built": True, "documents": len(kit["documents"])}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/offer-kit/build failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Build offer kit failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/add")
    def post_admin_deal_kit_doc_add(deal_id: str, body: _KitAddBody):
        # Add a form to the offer kit: upload a PDF (base64 in contentB64) or pick
        # a wired catalog template (templateId). Appends to offerKit.documents.
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            import json as _json
            import base64 as _b64
            import re as _re
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
                kit = toggles.get("offerKit") or {"createdAt": "", "documents": []}
                docs = kit.get("documents") or []
                if body.contentB64:
                    fname = (body.filename or "form.pdf").strip()
                    if not fname.lower().endswith(".pdf"):
                        fname += ".pdf"
                    slug = _re.sub(r"[^a-z0-9]+", "-", fname.lower().rsplit(".", 1)[0]).strip("-") or "form"
                    doc_id = "custom-" + slug
                    n = 2
                    while any(d.get("id") == doc_id for d in docs):
                        doc_id = f"custom-{slug}-{n}"
                        n += 1
                    try:
                        data = _b64.b64decode(body.contentB64)
                    except Exception:
                        raise HTTPException(status_code=400, detail="bad file content")
                    if not data.startswith(b"%PDF-"):
                        raise HTTPException(status_code=400, detail="uploaded file is not a PDF")
                    out_path = _offer_kit_path(deal_id, doc_id)
                    with out_path.open("wb") as fh:
                        fh.write(data)
                    ready = _is_pdf(out_path)
                    docs.append({"id": doc_id, "name": fname, "status": "draft", "fillable": False, "ready": ready, "filePath": str(out_path)})
                elif body.templateId:
                    tid = body.templateId.strip()
                    if any(d.get("id") == tid for d in docs):
                        raise HTTPException(status_code=400, detail="already in kit")
                    _document_asset("template", template_id=tid)
                    cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
                    out_path = _offer_kit_path(deal_id, tid)
                    docs.append({"id": tid, "name": (body.name or tid), "status": "draft", "fillable": True, "ready": _is_pdf(out_path), "filePath": str(out_path), "fields": dict(cps.get("fields") or {})})
                else:
                    raise HTTPException(status_code=400, detail="need a file or templateId")
                kit["documents"] = docs
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"ok": True, "documents": len(docs)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/kit-doc/add failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Add form failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/pull-listing")
    def post_admin_deal_pull_listing(deal_id: str, body: _PullListingBody):
        # Kick off the Xposure listing pull (docs + title + facts incl. postal
        # code) in the background and mark the deal as pulling. The scraper writes
        # results back via the dashboard API and flips listingPullStatus when done.
        try:
            import json as _json
            import subprocess
            from elevate_cli.data import connect

            mls = (body.mls or "").strip()
            if not mls:
                raise HTTPException(status_code=400, detail="mls required")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            script = _document_asset("listingPull")
            node = shutil.which("node")
            if not node:
                _document_setup_error(
                    "document_runtime_missing",
                    "Install Node.js or configure it on PATH before pulling listing documents.",
                    runtime="node",
                )
            log_path = _document_log_path("pull-listing.log")
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [node, str(script), deal_id, mls],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=_document_subprocess_env(),
                    start_new_session=True,
                )
            with connect() as conn:
                toggles["mlsNumber"] = mls
                toggles["listingPullStatus"] = "pulling"
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"started": True, "mls": mls, "pid": process.pid}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/pull-listing failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Pull listing failed: {exc}")

    @router.get("/api/admin/clause-library")
    def get_admin_clause_library():
        # Serve the scraped WEBForms clause library (Personal/Office/System) for
        # the Insert Clauses popup. Refreshes whenever pull-clauses-from-webforms.js
        # rewrites the file — no rebuild needed.
        try:
            import json as _json
            path = _document_asset("clauseLibrary")
            return _json.loads(path.read_text(encoding="utf-8"))
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/clause-library failed")
            raise HTTPException(status_code=500, detail=f"Clause library failed: {exc}")

    class _PersonalClauseBody(BaseModel):
        # Save a new reusable personal clause into the shared clause library.
        title: Optional[str] = ""
        wording: str

    @router.post("/api/admin/clause-library/personal")
    def add_personal_clause(body: _PersonalClauseBody):
        # Append a personal clause to the configured clause library (the same file
        # the GET route serves) so it shows up in the picker on every future deal.
        try:
            import json as _json
            path = _document_asset("clauseLibrary")
            wording = (body.wording or "").strip()
            if not wording:
                raise HTTPException(status_code=400, detail="Clause wording is required")
            title = (body.title or "").strip() or "Personal clause"
            data = _json.loads(path.read_text(encoding="utf-8"))
            folders = data.setdefault("folders", {})
            personal = folders.setdefault("personal", [])
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "clause"
            cid = "personal-" + slug
            existing = {c.get("id") for c in personal}
            base, n = cid, 2
            while cid in existing:
                cid = f"{base}-{n}"
                n += 1
            clause = {"id": cid, "title": title, "primary_wording": wording, "category": "personal"}
            personal.append(clause)
            data.setdefault("counts", {})["personal"] = len(personal)
            with open(path, "w") as fh:
                _json.dump(data, fh, indent=2, ensure_ascii=False)
            return {"clause": clause}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/clause-library/personal failed")
            raise HTTPException(status_code=500, detail=f"Add personal clause failed: {exc}")

    @router.get("/api/deals/{deal_id}/context")
    def get_deal_source_context(deal_id: str):
        try:
            from elevate_cli.data import connect, get_deal_context

            with connect() as conn:
                return get_deal_context(conn, deal_id)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("GET /api/deals/%s/context failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal context failed: {exc}")

    @router.post("/api/deals/{deal_id}/fields")
    def post_deal_fields(deal_id: str, body: _DealFieldsBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, set_deal_fields

            with connect() as conn:
                return set_deal_fields(conn, deal_id, actor=web_actor, fields=body.fields)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/fields failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal field update failed: {exc}")

    @router.post("/api/deals/{deal_id}/advance")
    def post_deal_advance(deal_id: str, body: _DealAdvanceBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import connect, get_deal_context, move_deal_stage

            with connect() as conn:
                context = get_deal_context(conn, deal_id)
                gate = ((context.get("dealFlow") or {}).get("gate") or {})
                next_stage = gate.get("nextStage")
                if next_stage is None:
                    raise HTTPException(status_code=400, detail="deal is already at the final stage")
                if not body.force and not gate.get("canAdvance"):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "deal phase gate is blocked",
                            "gate": gate,
                        },
                    )
                move_deal_stage(
                    conn,
                    deal_id,
                    to_stage=int(next_stage),
                    actor=web_actor,
                    force=body.force,
                    gate_checked=not body.force,
                )
                return get_deal_context(conn, deal_id)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/advance failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal advance failed: {exc}")

    @router.post("/api/deals/{deal_id}/contacts")
    def post_deal_contact(deal_id: str, body: _DealContactBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import add_deal_contact, connect

            with connect() as conn:
                return add_deal_contact(
                    conn,
                    deal_id,
                    role=body.role,
                    contact_id=body.contactId,
                    notes=body.notes,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/contacts failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal contact link failed: {exc}")

    @router.post("/api/deals/{deal_id}/attachments")
    def post_deal_attachment(deal_id: str, body: _DealAttachmentBody):
        try:
            require_admin_setup_ready_for_launch()
            from elevate_cli.data import add_deal_attachment, connect

            with connect() as conn:
                return add_deal_attachment(
                    conn,
                    deal_id,
                    kind=body.kind,
                    file_path=body.filePath,
                    summary=body.summary,
                    source_run_id=body.sourceRunId,
                    source_snapshot_id=body.sourceSnapshotId,
                    actor=web_actor,
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/attachments failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal attachment failed: {exc}")

    @router.post("/api/deals/{deal_id}/runs/{run_id}/result")
    def post_deal_run_result(deal_id: str, run_id: str, body: _RunResultBody):
        try:
            from elevate_cli.data import connect, record_run_result

            artifacts = [_model_dump(item) for item in body.artifacts]
            next_tasks = body.next_tasks or body.nextTasks
            checklist_updates = body.checklist_updates or body.checklistUpdates
            human_prompt = body.human_prompt or body.humanPrompt
            idempotency_key = body.idempotency_key or body.idempotencyKey
            with connect() as conn:
                return record_run_result(
                    conn,
                    deal_id,
                    run_id,
                    status=body.status,
                    idempotency_key=idempotency_key,
                    artifacts=artifacts,
                    next_tasks=next_tasks,
                    checklist_updates=checklist_updates,
                    human_prompt=human_prompt,
                    error=body.error,
                    actor="skill:web-callback",
                )
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception("POST /api/deals/%s/runs/%s/result failed", deal_id, run_id)
            raise HTTPException(status_code=500, detail=f"Deal run result failed: {exc}")

    @router.post(
        "/api/deals/{deal_id}/runs/{run_id}/manual-reviewed-document"
    )
    def post_manual_reviewed_run_document(
        deal_id: str,
        run_id: str,
        body: _ManualReviewedRunDocumentBody,
    ):
        """Complete one task-bound provider-form run with reviewed evidence."""
        uploaded_path: Path | None = None
        completed = False
        try:
            has_upload = bool(str(body.contentB64 or "").strip())
            has_local_path = bool(str(body.filePath or "").strip())
            if has_upload == has_local_path:
                raise HTTPException(
                    status_code=400,
                    detail="provide exactly one of contentB64 or filePath",
                )
            if has_upload:
                uploaded_path = _persist_manual_review_upload(
                    deal_id=deal_id,
                    run_id=run_id,
                    filename=body.filename,
                    content_b64=str(body.contentB64),
                )
                file_path = str(uploaded_path)
            else:
                file_path = str(body.filePath or "")

            from elevate_cli.data import (
                complete_run_with_reviewed_manual_pdf,
                connect,
            )

            with connect() as conn:
                result = complete_run_with_reviewed_manual_pdf(
                    conn,
                    deal_id,
                    run_id,
                    kind=body.kind,
                    file_path=file_path,
                    reviewed=body.reviewed,
                    form_code=body.formCode,
                    provider=body.provider,
                    reviewer_name=body.reviewerName,
                    version_status=body.versionStatus,
                    source_receipt=body.sourceReceipt,
                    document_version=body.documentVersion,
                    effective_date=body.effectiveDate,
                    version_verified_at=body.versionVerifiedAt,
                    summary=body.summary,
                    actor=web_actor,
                )
            completed = True
            return result
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            _log.exception(
                "POST /api/deals/%s/runs/%s/manual-reviewed-document failed",
                deal_id,
                run_id,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Manual reviewed document completion failed: {exc}",
            )
        finally:
            if uploaded_path is not None and not completed:
                try:
                    uploaded_path.unlink()
                except OSError:
                    pass

    # --- CPS Offer Prep (buyer side) -------------------------------------

    def _cps_deal_facts(deal_id: Optional[str]) -> Dict[str, Any]:
        """Build the CPS / accessory-form fill facts from a deal: party names
        (resolved the same way the score card displays them — extra first,
        contacts as fallback), money (card override -> deal columns), mailing
        addresses, dates, and the cooperating commission for the remuneration
        form. Returns {} on any failure (forms then fill blank lines)."""
        if not deal_id:
            return {}
        try:
            from elevate_cli.data import connect
            from elevate_cli.data.deals import get_deal_context

            with connect() as conn:
                ctx = get_deal_context(conn, deal_id)
            d = ctx.get("deal") or {}
            chk = ctx.get("checklist") or {}
            primary = ctx.get("primaryContact") or {}
            cos = ctx.get("coContacts") or []
            buyers: List[str] = []
            sellers: List[str] = []
            if primary.get("displayName"):
                buyers.append(primary["displayName"])
            for c in cos:
                role = str(c.get("role") or "").lower()
                nm = ((c.get("contact") or {}).get("displayName")) or ""
                if not nm:
                    continue
                (sellers if "seller" in role else buyers).append(nm)
            buyers = list(dict.fromkeys(buyers))
            sellers = list(dict.fromkeys(sellers))

            def _card_names(keys, fallback):
                for k in keys:
                    v = chk.get(k)
                    if isinstance(v, list):
                        vals = [str(x).strip() for x in v if str(x).strip()]
                        if vals:
                            return vals
                    elif isinstance(v, str) and v.strip():
                        return [p.strip() for p in v.split(",") if p.strip()]
                return fallback
            buyers = _card_names(["buyerClientNames", "skyslopeBuyerNames", "buyerNames"], buyers)
            sellers = _card_names(["sellerLegalNames", "skyslopeSellerNames", "sellerNames"], sellers)

            card_price = str(chk.get("cpsPurchasePrice") or "").strip()
            card_deposit = str(chk.get("cpsDeposit") or "").strip()
            card_deposit_terms = str(chk.get("cpsDepositTerms") or "").strip()
            commission = ""
            bse = chk.get("buyerSideEarn")
            if isinstance(bse, dict):
                commission = str(bse.get("cooperatingCommission") or "").strip()
            commission = commission or str(chk.get("cooperatingCommission") or "").strip()
            return {
                "listingAddress": d.get("listingAddress"),
                "buyers": buyers, "sellers": sellers,
                "buyerAddress": chk.get("mailingAddress"),
                "sellerAddress": chk.get("sellerMailingAddress") or chk.get("seller_mailing_address"),
                "price": card_price or d.get("offerPrice") or d.get("listPrice"),
                "depositAmount": card_deposit or d.get("depositAmount"),
                "depositTerms": card_deposit_terms or None,
                "mlsNumber": d.get("mlsNumber"),
                "targetMls": chk.get("targetMls"),  # MLS used at gather; locates the title for legal/PID extraction
                "legalDescription": chk.get("cpsLegalDescription") or d.get("legalDescription"),
                "pid": chk.get("cpsPid") or d.get("pid"),
                "completionDate": chk.get("completionDate") or d.get("completionDate"),
                "possessionDate": chk.get("possessionDate") or d.get("possessionDate"),
                "adjustmentDate": chk.get("adjustmentDate") or chk.get("completionDate") or d.get("completionDate"),
                "possessionTime": chk.get("possessionTime"),
                "offerDate": d.get("offerDate"),
                "commission": commission,
                # Section B paying party for the Disclosure of Remuneration.
                "cooperatingBrokerage": chk.get("cooperatingBrokerage") or d.get("cooperatingBrokerage") or "",
                "payingParty": chk.get("cooperatingBrokerage") or d.get("cooperatingBrokerage") or "",
            }
        except Exception:
            _log.warning("CPS deal facts load failed for %s", deal_id, exc_info=True)
            return {}
    # Gather the listing's MLS sheet + Docs-tab documents from Xposure into the
    # buyer deal's Drive folder, then assemble a CPS draft on the actual BCREA
    # form + Schedule A. Both call scripts from the configured document pack,
    # spawned with the configured Python because PDF dependencies may not exist
    # may be user installs the dashboard's default python can't see.

    @router.post("/api/admin/offer-prep/gather")
    def post_offer_prep_gather(body: _GatherCpsBody):
        """Kick off the Xposure gather (login -> MLS search -> docs + MLS sheet
        -> file into the deal folder). Detached + slow (~1-2 min), so this
        returns immediately after starting it."""
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            mls = (body.mls or "").strip()
            if not mls.isdigit() or not (6 <= len(mls) <= 9):
                raise HTTPException(status_code=400, detail="Enter a valid MLS number")
            script = _document_asset("cpsGather")
            args = [_document_runtime("bash"), str(script), mls]
            if body.dry_run:
                args.append("--dry-run")
            # DEAL_ID lets the gather write the extracted legal/PID back onto the
            # deal once the title finishes downloading, so Generate has them no
            # matter the timing.
            gather_env = {**_document_subprocess_env(), "DEAL_ID": (body.deal_id or "")}
            _sp.Popen(
                args,
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
                start_new_session=True,
                env=gather_env,
            )
            _log.info("offer-prep CPS gather started for MLS %s (dry_run=%s)", mls, body.dry_run)
            return {"ok": True, "started": True, "mls": mls, "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep CPS gather failed")
            raise HTTPException(status_code=500, detail=f"CPS gather failed: {exc}")

    @router.post("/api/admin/offer-prep/generate")
    def post_offer_prep_generate(body: _GenerateCpsBody):
        """Fill the real BCREA Contract of Purchase and Sale from the deal's
        facts (parties, price, legal, dates) and append Schedule A (selected
        subjects + clauses), then file the draft into the deal folder.
        Synchronous (no browser), returns the result + Drive URL."""
        import json as _json
        import subprocess as _sp

        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            require_admin_setup_ready_for_launch()
            if not body.umbrella:
                raise HTTPException(status_code=400, detail="Pick a form first")
            # Pull the deal's real facts so the base CPS form fills itself.
            deal_facts = _cps_deal_facts(body.deal_id)
            payload = {
                "umbrella": body.umbrella, "clauses": body.clauses,
                "customClauses": body.customClauses, "vars": body.vars,
                "address": (body.address or "Property"), "dealId": (body.deal_id or "deal"),
                "dryRun": body.dry_run, "deal": deal_facts,
            }
            script = _document_asset("cpsGenerate")
            # Strip the dashboard's bundled PYTHON* overrides for the configured
            # document runtime.
            child_env = _document_subprocess_env(clean_python=True)
            with _document_payload(payload, "cps-generate") as pf:
                r = _sp.run([_document_runtime("python"), str(script), pf], capture_output=True,
                            text=True, timeout=120, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line)
                    break
                except Exception:
                    continue
            if r.returncode != 0 or not result.get("ok"):
                _log.error("CPS generate produced no PDF: %s | %s", (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Generation failed to produce a PDF")
            saved = bool(result.get("save") or result.get("saved"))
            _log.info("CPS draft generated for %s (dry_run=%s, saved=%s)", result.get("address"), body.dry_run, saved)
            return {"ok": True, "address": result.get("address"), "saved": saved,
                    "url": result.get("url"), "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep CPS generate failed")
            raise HTTPException(status_code=500, detail=f"CPS generate failed: {exc}")

    @router.post("/api/admin/offer-prep/form")
    def post_offer_prep_form(body: _GenerateFormBody):
        """Fill one buyer-side accessory form (PNC / DORTS representation /
        Disclosure of Remuneration) from the deal facts and file it into the
        deal folder. Synchronous; returns the result + Drive URL."""
        import json as _json
        import subprocess as _sp

        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            require_admin_setup_ready_for_launch()
            form = (body.form or "").strip().lower()
            if form not in ("pnc", "dorts", "disclosure-rem"):
                raise HTTPException(status_code=400, detail="Unknown form")
            deal_facts = _cps_deal_facts(body.deal_id)
            payload = {
                "form": form, "address": (body.address or "Property"),
                "dealId": (body.deal_id or "deal"), "dryRun": body.dry_run,
                "deal": deal_facts,
            }
            script = _document_asset("offerForms")
            child_env = _document_subprocess_env(clean_python=True)
            with _document_payload(payload, f"offer-form-{form}") as pf:
                r = _sp.run([_document_runtime("python"), str(script), pf], capture_output=True,
                            text=True, timeout=120, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line)
                    break
                except Exception:
                    continue
            if r.returncode != 0 or not result.get("ok"):
                _log.error("offer form %s produced no PDF: %s | %s", form, (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Form generation failed")
            _log.info("offer-prep form %s generated for %s (dry_run=%s)", form, result.get("address"), body.dry_run)
            return {"ok": True, "form": form, "address": result.get("address"),
                    "saved": bool(result.get("save") or result.get("saved")),
                    "url": result.get("url"), "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep form generate failed")
            raise HTTPException(status_code=500, detail=f"Form generate failed: {exc}")

    @router.post("/api/admin/offer-prep/package")
    def post_offer_prep_package(body: _GenerateCpsBody):
        """Build the full offer package — CPS draft + DORTS + PNC + Disclosure of
        Remuneration merged into one PDF — and file it to the deal folder for
        preview. Returns the Drive URL."""
        import json as _json
        import subprocess as _sp

        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            require_admin_setup_ready_for_launch()
            if not body.umbrella:
                raise HTTPException(status_code=400, detail="Pick a form first")
            deal_facts = _cps_deal_facts(body.deal_id)
            payload = {
                "umbrella": body.umbrella, "clauses": body.clauses,
                "customClauses": body.customClauses, "vars": body.vars,
                "address": (body.address or "Property"), "dealId": (body.deal_id or "deal"),
                "dryRun": body.dry_run, "deal": deal_facts, "forms": body.forms,
            }
            script = _document_asset("offerPackage")
            child_env = _document_subprocess_env(clean_python=True)
            with _document_payload(payload, "offer-package") as pf:
                r = _sp.run([_document_runtime("python"), str(script), pf], capture_output=True,
                            text=True, timeout=180, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line)
                    break
                except Exception:
                    continue
            if r.returncode != 0 or not result.get("ok"):
                _log.error("offer package produced no PDF: %s | %s", (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Package build failed")
            _log.info("offer package built for %s (%s docs, dry_run=%s)", result.get("address"), result.get("count"), body.dry_run)
            return {"ok": True, "address": result.get("address"), "count": result.get("count"),
                    "url": result.get("url"), "dryRun": body.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("offer-prep package build failed")
            raise HTTPException(status_code=500, detail=f"Package build failed: {exc}")

    def _user_site_env():
        return _document_subprocess_env(clean_python=True)

    @router.get("/api/admin/deals/{deal_id}/documents")
    def get_deal_documents(deal_id: str):
        """List the deal's Drive-folder files (classified/grouped) for the card's
        Documents panel. Read-only — runs deal-docs-list.py against the deal's
        property address."""
        import json as _json
        import subprocess as _sp

        try:
            require_admin_setup_ready_for_launch()
            facts = _cps_deal_facts(deal_id)
            # Deal folders are named by the street address only (no city/postal),
            # so match on the portion before the first comma.
            address = str(facts.get("listingAddress") or "").split(",")[0].strip()
            empty = {"ok": True, "folderId": None, "folderUrl": None, "files": []}
            if not address:
                return empty
            script = _document_asset("dealDocuments")
            r = _sp.run([_document_runtime("python"), str(script), "--address", address],
                        capture_output=True, text=True, timeout=60, env=_user_site_env())
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    parsed = _json.loads(line)
                    if isinstance(parsed, dict):
                        result = parsed
                        break
                except Exception:
                    continue
            if r.returncode != 0 or not result:
                _log.warning("deal documents failed: %s | %s", (r.stdout or "")[-200:], (r.stderr or "")[-200:])
                raise HTTPException(status_code=500, detail="Document listing did not complete")
            # Append the client-level (contact-scoped) documents as their own
            # group, so property docs and reusable client docs live in the same
            # Documents tab, just separated. See client-doc-reuse-architecture.md.
            try:
                result.setdefault("files", [])
                result["files"].extend(_client_document_entries(deal_id))
            except Exception:
                _log.exception("append client documents failed for deal %s", deal_id)
            return result
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("list deal documents failed")
            raise HTTPException(status_code=500, detail=f"List documents failed: {exc}")

    @router.get("/api/admin/contact-documents/{doc_id}/file")
    def get_contact_document_file(doc_id: str):
        # Auth via dashboard middleware (Bearer header or ?token= for new-tab
        # loads). Serves a preserved client-level compliance doc inline.
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT file_path FROM contact_documents WHERE id=?", (doc_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="client document not found")
            file_path = row["file_path"]
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="client document file missing")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET contact-document %s file failed", doc_id)
            raise HTTPException(status_code=500, detail=f"Client document fetch failed: {exc}")

    def _resolve_buyer_recipients(deal_id: str) -> List[Dict[str, str]]:
        """Buyer-role signers (first/last/email) for a DigiSign envelope."""
        from elevate_cli.data import connect
        recips: List[Dict[str, str]] = []
        with connect() as conn:
            rows = conn.execute(
                "SELECT c.display_name, c.primary_email FROM deal_contacts dc "
                "JOIN contacts c ON c.id = dc.contact_id WHERE dc.deal_id=?",
                (deal_id,),
            ).fetchall()
            for i, r in enumerate([row for row in rows if _BUYER_ROLE_RE.search(str(row["display_name"] or "")) or True]):
                name = str(r["display_name"] or "").strip()
                email = str(r["primary_email"] or "").strip()
                if not name or not email:
                    continue
                parts = name.split()
                first, last = (" ".join(parts[:-1]) or parts[0], parts[-1]) if len(parts) > 1 else (name, name)
                recips.append({"role": "buyer", "first": first, "last": last, "email": email, "signerIndex": len(recips)})
        return recips

    def _build_digisign_draft(deal_id: str, prefilled: List[Dict[str, str]], address: str) -> Dict[str, Any]:
        """Deterministically build ONE DigiSign draft envelope containing all the
        prepared PDFs, with signature/initial/date blocks placed per each form's
        spec. Draft only (send=False) -- Skyleigh reviews + sends. Guaranteed
        one-envelope by code (not agent instruction). Returns {ok, envelopeId,
        editorUrl, status} or {ok:false, error}."""
        import json as _json
        import subprocess as _sp
        try:
            engine = _document_asset("digisignEngine")
        except HTTPException as exc:
            return {"ok": False, "error": f"digisign engine not configured: {exc.detail}"}
        recipients = _resolve_buyer_recipients(deal_id)
        if not recipients:
            return {"ok": False, "error": "no buyer recipient with name+email on deal"}
        # Add Skyleigh as the agent/licensee signer (DORTS + Remuneration need the
        # agent signature; the engine skips her on client-only forms like PNC).
        recipients.append({"role": "agent", "first": "Skyleigh", "last": "McCallum",
                           "email": "skyleigh.mccallum@gmail.com", "signerIndex": 0})
        docs = []
        for d in prefilled:
            spec = _SIGNABLE_FORMS.get(d.get("form"), {})
            spec_form = spec.get("specForm")
            if spec_form and d.get("pdf"):
                docs.append({"form": spec_form, "pdf": d["pdf"]})
        if not docs:
            return {"ok": False, "error": "no docs mapped to block specs"}
        who = ", ".join(f"{r['first']} {r['last']}" for r in recipients)
        manifest = {
            "envelope_name": f"{address} - Onboarding & Disclosures - {who}",
            "email_subject": f"Please review & sign - {address}",
            "email_body": f"Hi, please review and sign the attached documents for {address}. Thank you, Skyleigh.",
            "documents": docs,
            "recipients": recipients,
            "send": False,
        }
        # digisign_engine's token refresh shells out to `node`; the dashboard's
        # launchd PATH omits /usr/local/bin, so add it explicitly.
        eng_env = _user_site_env()
        eng_env["PATH"] = "/usr/local/bin:/usr/bin:/bin:" + eng_env.get("PATH", "")
        try:
            with _document_payload(manifest, f"digisign-manifest-{deal_id}") as mf:
                r = _sp.run([_document_runtime("python"), str(engine), "--manifest", mf],
                            capture_output=True, text=True, timeout=240, env=eng_env)
        except Exception as exc:
            return {"ok": False, "error": f"engine invoke failed: {exc}"}
        # digisign_engine prints one pretty (multi-line) JSON blob; parse whole.
        res: Dict[str, Any] = {}
        txt = (r.stdout or "").strip()
        try:
            res = _json.loads(txt)
        except Exception:
            a, b = txt.find("{"), txt.rfind("}")
            if a >= 0 and b > a:
                try:
                    res = _json.loads(txt[a:b + 1])
                except Exception:
                    res = {}
        env_id = res.get("envelope_id")
        if not env_id:
            return {"ok": False, "error": f"engine produced no envelope: {((r.stdout or '')[-200:] + ' | ' + (r.stderr or '')[-200:])}"}
        return {"ok": True, "envelopeId": env_id, "editorUrl": res.get("editor_url"), "status": res.get("status"), "blocksPlaced": res.get("blocks_placed")}

    def _prep_signables_draft(deal_id: str, form_keys: List[str], *, purpose: str, buyers=None) -> Dict[str, Any]:
        """Fill a set of wizard-fillable signable forms from deal data, merge them
        into ONE preview PDF, and park a single draft-first review card that -- on
        approval -- sends them as ONE DigiSign envelope. Draft-first: never sends
        here. Returns {ok, runId, previewPdf, prepared[], missing[]}. Shared by the
        onboarding flow and the accepted-offer filing engine."""
        import json as _json
        import subprocess as _sp
        from elevate_cli.data import connect
        from elevate_cli.data.dispatch import queue_action_run

        facts = _cps_deal_facts(deal_id)
        if buyers:
            want = {str(b).strip().lower() for b in buyers if b}
            matched = [b for b in (facts.get("buyers") or []) if str(b).strip().lower() in want]
            facts["buyers"] = matched or [str(b).strip() for b in buyers if b]
        address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"
        script = _document_asset("offerForms")

        prefilled: List[Dict[str, str]] = []
        labels: List[str] = []
        missing: List[str] = []
        for key in form_keys:
            spec = _SIGNABLE_FORMS.get(key)
            if not spec:
                missing.append(key); continue
            pl = {"address": address, "dealId": deal_id, "dryRun": True, "deal": facts, "form": spec["formArg"]}
            with _document_payload(pl, f"prepare-signable-{deal_id}-{key}") as pf:
                r = _sp.run([_document_runtime("python"), str(script), pf], capture_output=True,
                            text=True, timeout=120, env=_user_site_env())
            res: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    res = _json.loads(line); break
                except Exception:
                    continue
            if res.get("ok") and res.get("pdf") and os.path.exists(res["pdf"]):
                prefilled.append({"form": key, "pdf": res["pdf"]}); labels.append(spec["label"])
            else:
                missing.append(key)

        if not prefilled:
            return {"ok": False, "error": "no forms could be prepared", "missing": missing}

        pv_dir = _profile_artifact_dir("uploads", "signable-previews")
        safe_purpose = re.sub(r"[^a-z0-9._-]+", "-", (purpose or "signables").lower())
        preview_pdf = str(pv_dir / f"{_artifact_slug(deal_id, 'deal')}-{safe_purpose}-preview.pdf")
        merge_src = (
            "import sys\nfrom pypdf import PdfReader, PdfWriter\nw = PdfWriter()\n"
            "for f in sys.argv[2:]:\n    for p in PdfReader(f).pages:\n        w.add_page(p)\n"
            "with open(sys.argv[1], 'wb') as fh:\n    w.write(fh)\n"
        )
        mr = _sp.run([_document_runtime("python"), "-c", merge_src, preview_pdf] + [d["pdf"] for d in prefilled],
                     capture_output=True, text=True, timeout=60,
                     env=_document_subprocess_env(clean_python=True))
        if not (mr.returncode == 0 and os.path.exists(preview_pdf)):
            preview_pdf = None

        # Deterministic: build ONE DigiSign draft envelope with blocks placed
        # (guaranteed one-envelope + blocks in code, not agent instruction).
        draft = _build_digisign_draft(deal_id, prefilled, address)
        if not draft.get("ok"):
            _log.warning("digisign draft build failed for deal %s: %s", deal_id, draft.get("error"))

        buyers_list = [b for b in (facts.get("buyers") or []) if b]
        who = ", ".join(buyers_list) or "the buyer(s)"
        doc_list = "; ".join(labels)
        payload = {
            "purpose": purpose,
            "documents": labels,
            "prefilledDocs": prefilled,
            "previewPdf": preview_pdf or "",
            "digisignDraft": draft if draft.get("ok") else None,
            "note": (
                f"These documents are ALREADY filled (paths in prefilledDocs). If digisignDraft is present, ONE "
                f"DigiSign draft envelope is already created with blocks placed (envelopeId/editorUrl) -- do NOT "
                f"create another; just review + send. Otherwise build ONE DigiSign envelope containing ALL of "
                f"these PDFs for {who} (same signer + same deal = one envelope) and PLACE the signature/initial/"
                f"date blocks per each form's spec (digisign_engine load_spec). Do not re-fill. Draft only; do not send. No BAEC."
            ),
        }
        with connect() as conn:
            run = queue_action_run(
                conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                name="Send document package for signatures", payload=payload,
                create_cron_job=not bool(preview_pdf), actor="dashboard:prepare-signables")
            rid = run.get("id") if isinstance(run, dict) else None
            if (preview_pdf or draft.get("ok")) and rid:
                draft_line = (
                    f" A DigiSign draft (one envelope, blocks placed) is ready: {draft.get('editorUrl')}."
                    if draft.get("ok") else ""
                )
                prompt = {
                    "title": "Review & approve: prepared signatures",
                    "message": f"{doc_list} drafted and filled for {who}.{draft_line} Open the Preview to review, then approve to send for signature by DigiSign.",
                    "requiredFields": [f"Approve sending {doc_list} to {who} for signature by DigiSign? yes/no"],
                    "previewPdf": preview_pdf,
                    "editorUrl": draft.get("editorUrl") if draft.get("ok") else None,
                }
                conn.execute("UPDATE admin_action_runs SET status='waiting_human', human_prompt_json=? WHERE id=?", (_json.dumps(prompt), rid))
        return {"ok": True, "runId": rid, "previewPdf": preview_pdf, "draftFirst": bool(preview_pdf), "digisignDraft": draft if draft.get("ok") else {"ok": False, "error": draft.get("error")}, "prepared": [d["form"] for d in prefilled], "missing": missing}

    @router.post("/api/admin/deals/{deal_id}/prepare-signables")
    def post_prepare_signables(deal_id: str, body: _PrepareSignablesBody):
        """Prepare a set of wizard-fillable signable forms (DORTS/PNC/Disclosure of
        Remuneration/...) from deal data and stage them as ONE draft-first DigiSign
        envelope. Called by the filing engine when required signables are missing,
        or directly. Never sends -- parks a review card."""
        try:
            require_admin_setup_ready_for_launch()
            forms = [f for f in (body.forms or []) if f in _SIGNABLE_FORMS]
            if not forms:
                raise HTTPException(status_code=400, detail=f"no known signable forms in {body.forms!r}")
            res = _prep_signables_draft(deal_id, forms, purpose=body.purpose or "prepared-signables", buyers=body.buyers)
            if not res.get("ok"):
                raise HTTPException(status_code=500, detail=res.get("error") or "prepare failed")
            return res
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("prepare-signables failed for deal %s", deal_id)
            raise HTTPException(status_code=500, detail=f"Prepare signables failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/onboarding-doc")
    def post_onboarding_doc(deal_id: str, body: _OnboardingDocBody):
        """Generate one Client-Onboarding document (agency / dorts / pnc) filled
        from the deal + client, filed to the deal folder. Returns the Drive URL."""
        import json as _json
        import subprocess as _sp

        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            require_admin_setup_ready_for_launch()
            form = (body.form or "").strip().lower()
            if form not in ("agency", "dorts", "pnc"):
                raise HTTPException(status_code=400, detail="Unknown onboarding form")
            facts = _cps_deal_facts(deal_id)
            address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"
            payload: Dict[str, Any] = {"address": address, "dealId": deal_id, "dryRun": False, "deal": facts}
            if form == "agency":
                script = _document_asset("buyerAgency")
            else:
                payload["form"] = form
                script = _document_asset("offerForms")
            with _document_payload(payload, f"onboarding-{form}") as pf:
                r = _sp.run([_document_runtime("python"), str(script), pf], capture_output=True,
                            text=True, timeout=120, env=_user_site_env())
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line)
                    break
                except Exception:
                    continue
            if r.returncode != 0 or not result.get("ok"):
                _log.error("onboarding %s produced no PDF: %s | %s", form, (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Onboarding doc generation failed")
            return {"ok": True, "form": form, "url": result.get("url")}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("onboarding doc generate failed")
            raise HTTPException(status_code=500, detail=f"Onboarding doc failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/onboarding-sign")
    def post_onboarding_sign(deal_id: str, body: Optional[_OnboardingSignBody] = None):
        """Draft-first onboarding signatures. Deterministically fills DORTS + PNC,
        merges one preview PDF, and parks a review card carrying that preview
        (previewPdf) so the user reviews the actual drafts BEFORE approving. After
        approval, the signing-package skill uploads the already-filled PDFs and
        sends via the configured provider — the agent never has to fill or decide,
        which keeps that run small. Falls back to direct agent dispatch if the
        deterministic prep fails (never worse than the prior behavior).

        BAEC/Buyer's Agency is intentionally NOT part of onboarding — Skyleigh does
        not use the BAEC. Pass ``body.buyers`` to fill only specific buyer(s) (e.g.
        a newly-added co-buyer); omit to fill for all buyers on the deal."""
        try:
            _require_exact_beta_forms_provider_for_local_document_mutation()
            require_admin_setup_ready_for_launch()
            import json as _json
            import subprocess as _sp
            from elevate_cli.data import connect
            from elevate_cli.data.dispatch import queue_action_run

            facts = _cps_deal_facts(deal_id)
            # Optional buyer targeting: when the caller names specific buyers,
            # fill only those (order preserved) instead of every buyer on the deal.
            if body and body.buyers:
                want = {str(b).strip().lower() for b in body.buyers if b}
                matched = [
                    b for b in (facts.get("buyers") or [])
                    if str(b).strip().lower() in want
                ]
                facts["buyers"] = matched or [str(b).strip() for b in body.buyers if b]
            address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"

            # --- Deterministic draft prep: fill the docs + merge one preview ---
            prefilled: List[Dict[str, str]] = []
            preview_pdf = None
            offer_forms_script = _document_asset("offerForms")
            try:
                # BAEC excluded (Skyleigh does not use the Buyer's Agency); onboarding = DORTS + PNC.
                forms_seq = [
                    ("dorts", offer_forms_script, "dorts"),
                    ("pnc", offer_forms_script, "pnc"),
                ]
                for key, script, formarg in forms_seq:
                    pl: Dict[str, Any] = {"address": address, "dealId": deal_id, "dryRun": True, "deal": facts}
                    if formarg:
                        pl["form"] = formarg
                    with _document_payload(pl, f"onboarding-sign-{key}") as pf:
                        r = _sp.run([_document_runtime("python"), str(script), pf], capture_output=True,
                                    text=True, timeout=120, env=_user_site_env())
                    res: Dict[str, Any] = {}
                    for line in reversed((r.stdout or "").strip().splitlines()):
                        try:
                            res = _json.loads(line)
                            break
                        except Exception:
                            continue
                    pdf = Path(str(res.get("pdf") or "")).expanduser()
                    if r.returncode == 0 and res.get("ok") and _is_pdf(pdf):
                        prefilled.append({"form": key, "pdf": str(pdf)})
                if prefilled and len(prefilled) == len(forms_seq):
                    pv_dir = _profile_artifact_dir("uploads", "onboarding-previews")
                    preview_path = pv_dir / f"{_artifact_slug(deal_id, 'deal')}-onboarding-preview.pdf"
                    merge_src = (
                        "import sys\n"
                        "from pypdf import PdfReader, PdfWriter\n"
                        "w = PdfWriter()\n"
                        "for f in sys.argv[2:]:\n"
                        "    for p in PdfReader(f).pages:\n"
                        "        w.add_page(p)\n"
                        "with open(sys.argv[1], 'wb') as fh:\n"
                        "    w.write(fh)\n"
                    )
                    mr = _sp.run([_document_runtime("python"), "-c", merge_src, str(preview_path)] + [d["pdf"] for d in prefilled],
                                 capture_output=True, text=True, timeout=60,
                                 env=_document_subprocess_env(clean_python=True))
                    if mr.returncode == 0 and _is_pdf(preview_path):
                        preview_pdf = str(preview_path)
            except Exception:
                _log.exception("onboarding draft prep failed; falling back to agent dispatch")
                prefilled = []
                preview_pdf = None

            buyers = [b for b in (facts.get("buyers") or []) if b]
            who = ", ".join(buyers) or "the buyer(s)"
            payload = {
                "purpose": "buyer-onboarding-signatures",
                "documents": [
                    "Disclosure of Representation in Trading Services (DORTS)",
                    "Privacy Notice & Consent (PNC)",
                ],
                "prefilledDocs": prefilled,
                "previewPdf": preview_pdf or "",
                "note": (
                    "The onboarding documents (DORTS + PNC) are ALREADY filled (local paths in prefilledDocs). "
                    "After the user approves, upload exactly those PDFs to the configured signing "
                    "provider and send them for signature to the buyer(s). Do not re-fill or regenerate them. "
                    "No BAEC/Buyer's Agency is part of this package."
                ),
            }

            with connect() as conn:
                if preview_pdf:
                    run = queue_action_run(
                        conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                        name="Send onboarding package for signatures", payload=payload,
                        create_cron_job=False, actor="dashboard:onboarding")
                    rid = run.get("id") if isinstance(run, dict) else None
                    prompt = {
                        "title": "Review & approve: onboarding signatures",
                        "message": (
                            f"DORTS and PNC are drafted and filled for {who}. "
                            "Open the Preview to review, then approve to send them for signature by DigiSign."
                        ),
                        "requiredFields": [
                            f"Approve sending the filled DORTS & PNC to {who} for signature by DigiSign? yes/no"
                        ],
                        "previewPdf": preview_pdf,
                    }
                    conn.execute(
                        "UPDATE admin_action_runs SET status='waiting_human', human_prompt_json=? WHERE id=?",
                        (_json.dumps(prompt), rid),
                    )
                    return {"ok": True, "runId": rid, "previewPdf": preview_pdf, "draftFirst": True}
                # Fallback: prior behavior — let the agent fill, park, and send.
                run = queue_action_run(
                    conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                    name="Send onboarding package for signatures", payload=payload,
                    create_cron_job=True, actor="dashboard:onboarding")
                return {"ok": True, "runId": run.get("id") if isinstance(run, dict) else None, "draftFirst": False}
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("onboarding sign dispatch failed")
            raise HTTPException(status_code=500, detail=f"Send for signatures failed: {exc}")

    class _KitSignBody(BaseModel):
        # Which offer-kit documents to draft into the DigiSign envelope.
        docIds: List[str] = []

    @router.post("/api/admin/deals/{deal_id}/offer-kit/draft-signatures")
    def post_offer_kit_draft_signatures(deal_id: str, body: _KitSignBody):
        """Draft-first: create a SkySlope DigiSign DRAFT envelope from the
        selected + approved offer-kit documents. Nothing is sent to the client —
        the signing-package skill uploads the PDFs, places signers/blocks, and
        leaves the envelope as a DRAFT for Skyleigh to review and send from
        DigiSign. Mirrors onboarding-sign (merge preview + park a review card)."""
        try:
            require_admin_setup_ready_for_launch()
            import json as _json
            import subprocess as _sp
            from elevate_cli.data import connect
            from elevate_cli.data.dispatch import queue_action_run

            facts = _cps_deal_facts(deal_id)
            address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="deal not found")
                raw = row["extra_toggles_json"]
                toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            docs = ((toggles.get("offerKit") or {}).get("documents") or [])
            want = set(body.docIds or [])
            chosen = []
            for d in docs:
                if want and d.get("id") not in want:
                    continue
                fp = d.get("filePath")
                if d.get("status") == "approved" and fp and os.path.exists(fp):
                    chosen.append({"form": d.get("id"), "name": d.get("name") or d.get("id"), "pdf": fp})
            if not chosen:
                raise HTTPException(status_code=400, detail="No approved documents selected. Approve the docs first, then draft for signatures.")

            preview_pdf = None
            try:
                pv_dir = _profile_artifact_dir("uploads", "offer-kit-sign-previews")
                preview_path = str(pv_dir / f"{_artifact_slug(deal_id, 'deal')}-offer-kit-sign-preview.pdf")
                merge_src = (
                    "import sys\n"
                    "from pypdf import PdfReader, PdfWriter\n"
                    "w = PdfWriter()\n"
                    "for f in sys.argv[2:]:\n"
                    "    for p in PdfReader(f).pages:\n"
                    "        w.add_page(p)\n"
                    "with open(sys.argv[1], 'wb') as fh:\n"
                    "    w.write(fh)\n"
                )
                mr = _sp.run([_document_runtime("python"), "-c", merge_src, preview_path] + [c["pdf"] for c in chosen],
                             capture_output=True, text=True, timeout=60,
                             env=_document_subprocess_env(clean_python=True))
                if mr.returncode == 0 and os.path.exists(preview_path):
                    preview_pdf = preview_path
            except Exception:
                _log.exception("offer-kit sign preview merge failed")
                preview_pdf = None

            buyers = [b for b in (facts.get("buyers") or []) if b]
            who = ", ".join(buyers) or "the buyer(s)"
            doc_names = [c["name"] for c in chosen]
            payload = {
                "purpose": "offer-kit-draft-signatures",
                "mode": "draft",
                "documents": doc_names,
                "prefilledDocs": [{"form": c["form"], "pdf": c["pdf"]} for c in chosen],
                "previewPdf": preview_pdf or "",
                "note": (
                    "These offer-kit documents are ALREADY filled + approved (local paths in "
                    "prefilledDocs). After the user approves, upload EXACTLY those PDFs to SkySlope "
                    "DigiSign, add the buyer(s) as signers and place the signature/initial blocks, "
                    "and create the envelope as a DRAFT. DO NOT SEND — leave it as a draft in "
                    "DigiSign for Skyleigh to review and send herself. Do not re-fill or regenerate."
                ),
            }

            with connect() as conn:
                run = queue_action_run(
                    conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                    name="Draft offer kit for signatures (DigiSign)", payload=payload,
                    create_cron_job=False, actor="dashboard:offer-kit-sign")
                rid = run.get("id") if isinstance(run, dict) else None
                prompt = {
                    "title": "Review & approve: draft for signatures",
                    "message": (
                        f"{len(chosen)} approved document(s) for {who} are ready to draft into a "
                        "SkySlope DigiSign envelope. Open the Preview to review, then approve to "
                        "create the DRAFT envelope (nothing is sent — you send it from DigiSign)."
                    ),
                    "requiredFields": [
                        f"Approve creating a DRAFT DigiSign envelope ({', '.join(doc_names)}) for {who}? yes/no"
                    ],
                    "previewPdf": preview_pdf or "",
                }
                conn.execute(
                    "UPDATE admin_action_runs SET status='waiting_human', human_prompt_json=? WHERE id=?",
                    (_json.dumps(prompt), rid),
                )
            return {"ok": True, "runId": rid, "previewPdf": preview_pdf or "", "documents": doc_names, "draftFirst": True}
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("offer-kit draft-signatures dispatch failed")
            raise HTTPException(status_code=500, detail=f"Draft for signatures failed: {exc}")

    # --- CMA wizard (listing side): checkpointed phase runner + comp review ---
    def _cma_runner() -> Path:
        return _document_asset("cmaRunner")

    def _cma_addr(deal_id):
        facts = _cps_deal_facts(deal_id)
        return str(facts.get("listingAddress") or "").split(",")[0].strip()

    def _cma_call(addr, args, timeout=60):
        import json as _json
        import subprocess as _sp
        runner = _cma_runner()
        r = _sp.run([_document_runtime("python"), str(runner), "--address", addr] + args,
                    capture_output=True, text=True, timeout=timeout, env=_user_site_env())
        if r.returncode != 0:
            raise HTTPException(status_code=500, detail="CMA runner failed")
        for line in reversed((r.stdout or "").strip().splitlines()):
            try:
                result = _json.loads(line)
                if isinstance(result, dict):
                    return result
            except Exception:
                continue
        _log.warning("cma-runner no JSON (%s): %s | %s", args, (r.stdout or "")[-200:], (r.stderr or "")[-200:])
        raise HTTPException(status_code=500, detail="CMA runner returned no result")

    def _cma_photos_url(deal_id):
        """The seller's subject-photos Drive folder link saved on the deal (or "").
        Read straight from the deal's extra_toggles_json, same as the offerKit read
        elsewhere in this module."""
        try:
            from elevate_cli.data import connect
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if not row or not row["extra_toggles_json"]:
                return ""
            raw = row["extra_toggles_json"]
            t = raw if isinstance(raw, dict) else (_json.loads(raw) if str(raw).strip() else {})
            return str(t.get("cmaPhotosDriveUrl") or t.get("driveFolderUrl") or "").strip()
        except Exception:
            return ""

    @router.get("/api/admin/deals/{deal_id}/cma/phases")
    def get_cma_phases(deal_id: str):
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                return {"ok": True, "done": 0, "total": 0, "phases": [], "pdfUrl": None,
                        "photosUrl": "", "photosUrlSet": False}
            res = _cma_call(addr, ["--status"], timeout=30)
            url = _cma_photos_url(deal_id)
            if isinstance(res, dict):
                res["photosUrl"] = url
                res["photosUrlSet"] = bool(url)
            return res
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma phases failed")
            raise HTTPException(status_code=500, detail=f"CMA phases failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/run")
    def post_cma_run(deal_id: str, body: _CmaRunBody):
        """Kick a single CMA phase. Detached — browser phases run for minutes;
        the wizard polls /cma/phases for status."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            import subprocess as _sp
            # Dep gate: the runner silently no-ops a phase whose upstream deps aren't
            # done (detached, output discarded), so a premature 'render' click would
            # look dead. Check deps synchronously and fail loud instead.
            chk = _cma_call(addr, ["--phase", body.phase, "--can-run"], timeout=30)
            if isinstance(chk, dict) and chk.get("unmet"):
                _lbl = {"collect": "Subject", "actives": "Active competition",
                        "photos": "Photos", "normalize": "Pricing", "finish": "Pricing",
                        "prospecting": "buyer-demand prospecting", "render": "Render"}
                _need = ", ".join(_lbl.get(d, d) for d in chk["unmet"])
                raise HTTPException(status_code=409,
                                    detail=f"Can't run {body.phase} yet — capture {_need} first.")
            runner = _cma_runner()
            _sp.Popen([_document_runtime("python"), str(runner), "--address", addr, "--phase", body.phase],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      start_new_session=True)
            return {"ok": True, "started": True, "phase": body.phase}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma run failed")
            raise HTTPException(status_code=500, detail=f"CMA run failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/skip-photos")
    def post_cma_skip_photos(deal_id: str):
        """Skip the photo/finish step when there are no usable photos: writes
        neutral analysis so normalize/render still run (price-based, no finish
        adjustment) and marks photos done so the wizard advances. Synchronous."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            return _cma_call(addr, ["--skip-photos"], timeout=60)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma skip-photos failed")
            raise HTTPException(status_code=500, detail=f"CMA skip-photos failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/score-photos")
    def post_cma_score_photos(deal_id: str):
        """Run the seller's photos: materialize them from the saved Drive folder,
        AI-score finish/condition, and mark the photos phase done. Detached — the
        scoring takes minutes; the wizard polls /cma/phases and the photos phase
        shows 'running' until it lands (or 'failed' with a reason). Requires a
        saved photos Drive link (cmaPhotosDriveUrl); if there is none, the caller
        should use skip-photos instead."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            url = _cma_photos_url(deal_id)
            if not url:
                raise HTTPException(status_code=400, detail="No photos Drive link saved on this deal")
            import subprocess as _sp
            runner = _cma_runner()
            _sp.Popen([_document_runtime("python"), str(runner), "--address", addr,
                       "--score-photos", "--folder", url],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      start_new_session=True)
            return {"ok": True, "started": True, "photosUrl": url}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma score-photos failed")
            raise HTTPException(status_code=500, detail=f"CMA score-photos failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/regenerate-comps")
    def post_cma_regenerate(deal_id: str, body: _CmaRegenBody):
        """Re-pull comps with adjustments parsed from free text (e.g. 'expand to
        Westsyde + Westmount, target $635k'): sets CMA_AREAS / CMA_VALUE_ANCHOR,
        resets the comp-derived phases, and re-runs collect (detached)."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            import re as _re
            import subprocess as _sp
            text = body.instructions or ""
            env = _user_site_env()
            anchor = ""
            m = _re.search(r"([0-9]{3})[, ]?([0-9]{3})\b", text)
            if m:
                anchor = m.group(1) + m.group(2)
            else:
                mk = _re.search(r"([0-9]{3})\s*k\b", text, _re.I)
                if mk:
                    anchor = mk.group(1) + "000"
            if anchor:
                env["CMA_VALUE_ANCHOR"] = anchor
            AREAS = ["Brocklehurst", "Westsyde", "Westmount", "Batchelor", "North Kamloops",
                     "South Kamloops", "Sahali", "Aberdeen", "Dallas", "Valleyview", "Juniper",
                     "Barnhartvale", "Rayleigh", "Pineview", "Sun Rivers", "Dufferin"]
            picked = [a for a in AREAS if a.lower() in text.lower()]
            if picked:
                env["CMA_AREAS"] = ",".join(picked)
            env["CMA_MAX_COMPS"] = "10"
            runner = _cma_runner()
            reset = _sp.run([_document_runtime("python"), str(runner), "--address", addr, "--reset-downstream"],
                            env=env, capture_output=True, timeout=30)
            if reset.returncode != 0:
                raise HTTPException(status_code=500, detail="CMA reset failed; collect was not started")
            _sp.Popen([_document_runtime("python"), str(runner), "--address", addr, "--phase", "collect"],
                      env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
            return {"ok": True, "started": True, "areas": env.get("CMA_AREAS"),
                    "anchor": env.get("CMA_VALUE_ANCHOR"), "instructions": text}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma regenerate failed")
            raise HTTPException(status_code=500, detail=f"CMA regenerate failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/cma/comp-photo/{comp_num}")
    def get_cma_comp_photo(deal_id: str, comp_num: int):
        """Serve a comp's first captured photo (comp-N-photo-00.jpg) for the
        Comparables-step thumbnail. 404 if that comp has no photo (placeholder)."""
        import glob as _glob
        base = str(_cma_runner().parent / "screenshots" / "comp-photos")
        cand = os.path.join(base, f"comp-{comp_num}-photo-00.jpg")
        if not os.path.exists(cand):
            hits = sorted(_glob.glob(os.path.join(base, f"comp-{comp_num}-photo-*.jpg")))
            cand = hits[0] if hits else ""
        if not cand or not os.path.exists(cand):
            raise HTTPException(status_code=404, detail="no photo for this comp")
        return FileResponse(cand, media_type="image/jpeg")

    @router.get("/api/admin/deals/{deal_id}/cma/pricing")
    def get_cma_pricing(deal_id: str):
        """Pricing breakdown for the wizard's Pricing step: recommended price,
        range, the better/comparable/worse sandwich, and the strategy reasoning."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            return _cma_call(addr, ["--pricing"], timeout=30)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma pricing failed")
            raise HTTPException(status_code=500, detail=f"CMA pricing failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/reprice")
    def post_cma_reprice(deal_id: str, body: _CmaRepriceBody):
        """The 'Your take' override: force the recommended price to exactly
        body.price, fold body.rationale into the narrative, and re-derive the
        sandwich + comp descriptions + PDF. Detached; the wizard polls pricing."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            import subprocess as _sp
            runner = _cma_runner()
            _sp.Popen([_document_runtime("python"), str(runner), "--address", addr, "--reprice",
                       "--price", body.price or "", "--rationale", body.rationale or ""],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
            return {"ok": True, "started": True, "price": body.price}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma reprice failed")
            raise HTTPException(status_code=500, detail=f"CMA reprice failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/capture-prospecting")
    def post_cma_capture_prospecting(deal_id: str, body: _CmaCaptureProspectingBody):
        """The Pricing step's 'Capture buyer demand': one last Xposure pull for the
        active listing the operator chose as the prospecting anchor (persistent
        profile, no MFA). Detached; reshapes to prospecting-brackets.json and marks
        the prospecting phase done. The wizard polls /cma/phases for completion."""
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            if not (body.mls or "").strip():
                raise HTTPException(status_code=400, detail="Pick an active listing first")
            import subprocess as _sp
            script = _document_asset("cmaCaptureProspecting")
            _sp.Popen([_document_runtime("bash"), str(script), body.mls, addr],
                      env=_user_site_env(), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
            return {"ok": True, "started": True, "mls": body.mls}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma capture-prospecting failed")
            raise HTTPException(status_code=500, detail=f"CMA capture-prospecting failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/cma/comps")
    def get_cma_comps(deal_id: str):
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                return {"ok": True, "sold": [], "active": []}
            return _cma_call(addr, ["--comps"], timeout=30)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma comps failed")
            raise HTTPException(status_code=500, detail=f"CMA comps failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/cma/comp-toggle")
    def post_cma_comp_toggle(deal_id: str, body: _CmaCompToggleBody):
        try:
            require_admin_setup_ready_for_launch()
            addr = _cma_addr(deal_id)
            if not addr:
                raise HTTPException(status_code=400, detail="No listing address on this deal")
            return _cma_call(addr, ["--toggle-comp", body.mls, "--kind", body.kind], timeout=20)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("cma comp-toggle failed")
            raise HTTPException(status_code=500, detail=f"CMA comp-toggle failed: {exc}")

    return router
