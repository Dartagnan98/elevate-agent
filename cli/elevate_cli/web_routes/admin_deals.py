"""Admin deal workflow routes."""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
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
    # Per-document manual overrides from the card's inline "Edit" panel. These
    # win over the values derived from the deal, so the operator can correct a
    # draft (buyer mailing address, phone, agency term, remuneration wording)
    # without editing the deal itself. Empty/blank values are ignored.
    fields: Optional[Dict[str, Any]] = None


_FORM_LABELS = {
    "agency": "Designated Buyer's Agency Agreement",
    "dorts": "Disclosure of Representation in Trading Services (DORTS)",
    "pnc": "Privacy Notice & Consent (PNC)",
}


class _OnboardingSignBody(BaseModel):
    # Optional: restrict onboarding docs to specific buyer(s) by name -- e.g. a
    # newly-added co-buyer who needs their own DORTS/PNC when the other buyer
    # already onboarded. Omitted / empty => fill for all buyers on the deal.
    buyers: Optional[List[str]] = None
    # Optional: which onboarding docs go in the envelope (agency / dorts / pnc).
    # Omitted => DORTS + PNC, the historical default.
    forms: Optional[List[str]] = None


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


class _DealAdvanceBody(BaseModel):
    force: bool = False


def _model_dump(model: BaseModel) -> dict:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return model.dict(exclude_none=True)


def _render_pdf_page_png(pdf_path: str, page: int = 1, dpi: int = 105) -> tuple[bytes, int]:
    """Rasterise one page of a PDF to PNG bytes. Returns (png, page_count).

    The desktop shell has no PDF plugin, so a document can only be checked
    in-app as an image. PyMuPDF is in the runtime; poppler's pdftoppm is a
    fallback for installs that predate it. Results are cached beside the PDF
    and keyed on the PDF's mtime, so a redraft can never serve a stale image.
    """
    import subprocess
    import tempfile

    try:
        mtime = int(os.path.getmtime(pdf_path))
    except OSError:
        mtime = 0
    cache = f"{pdf_path}.p{page}.{dpi}.{mtime}.png"
    if os.path.exists(cache):
        try:
            with open(cache, "rb") as fh:
                data = fh.read()
            if data:
                return data, _pdf_page_count(pdf_path)
        except OSError:
            pass

    png: bytes | None = None
    pages = 1
    try:
        import fitz  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            pages = doc.page_count
            idx = min(max(page, 1), pages) - 1
            png = doc.load_page(idx).get_pixmap(dpi=dpi).tobytes("png")
    except Exception:
        # Fallback: poppler. Not on the app's PATH by default, so try the
        # Homebrew locations explicitly before giving up.
        for exe in ("pdftoppm", "/opt/homebrew/bin/pdftoppm", "/usr/local/bin/pdftoppm"):
            try:
                with tempfile.TemporaryDirectory() as td:
                    stem = os.path.join(td, "p")
                    subprocess.run(
                        [exe, "-f", str(page), "-l", str(page), "-r", str(dpi),
                         "-png", "-singlefile", pdf_path, stem],
                        check=True, capture_output=True, timeout=30,
                    )
                    with open(stem + ".png", "rb") as fh:
                        png = fh.read()
                pages = _pdf_page_count(pdf_path)
                break
            except Exception:
                continue

    if not png:
        raise RuntimeError("no PDF rasteriser available (PyMuPDF and poppler both failed)")

    try:
        with open(cache, "wb") as fh:
            fh.write(png)
        # Drop older renders of this PDF so the cache can't grow without bound.
        base = os.path.basename(pdf_path)
        folder = os.path.dirname(pdf_path) or "."
        for name in os.listdir(folder):
            if name.startswith(base + ".p") and name.endswith(".png") and name != os.path.basename(cache):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
    except OSError:
        pass
    return png, pages


_ONES = ("", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _amount_in_words(amount: Any) -> str:
    """"$630,000" -> "Six Hundred Thirty Thousand". Title-cased for a contract line.

    The CPS asks for the purchase price in words and nothing was producing it,
    so that line came out blank on every contract. Returns "" on anything that
    isn't a plain amount rather than guessing.
    """
    digits = re.sub(r"[^\d.]", "", str(amount or "")).split(".")[0]
    if not digits:
        return ""
    try:
        n = int(digits)
    except ValueError:
        return ""
    if n <= 0 or n >= 1_000_000_000:
        return ""

    def under_thousand(v: int) -> str:
        out = []
        if v >= 100:
            out.append(_ONES[v // 100] + " hundred")
            v %= 100
        if v >= 20:
            out.append(_TENS[v // 10] + ("-" + _ONES[v % 10] if v % 10 else ""))
        elif v:
            out.append(_ONES[v])
        return " ".join(out)

    parts = []
    for div, name in ((1_000_000, "million"), (1_000, "thousand")):
        if n >= div:
            parts.append(under_thousand(n // div) + " " + name)
            n %= div
    if n:
        parts.append(under_thousand(n))
    words = " ".join(p for p in parts if p.strip())
    return " ".join(w[:1].upper() + w[1:] for w in words.split())


_FORMS_DIR = "/Users/admin/skyleigh-tools/knowledge/deals/forms"

# Every field a human might reasonably correct on a document, in the order they
# should appear. Agent / brokerage / office identity is deliberately absent:
# it is on most forms but comes from the profile, is the same on every document,
# and putting officeZip on twelve rows buries the fields that actually vary.
_CARD_FIELD_CATALOG: List[Dict[str, Any]] = [
    {"key": "buyer1", "label": "Buyer 1"},
    {"key": "buyer2", "label": "Buyer 2"},
    {"key": "buyer3", "label": "Buyer 3"},
    {"key": "seller1", "label": "Seller 1"},
    {"key": "seller2", "label": "Seller 2"},
    {"key": "property", "label": "Property address"},
    {"key": "pid", "label": "PID"},
    {"key": "otherPids", "label": "Other PIDs"},
    {"key": "mls", "label": "MLS #"},
    {"key": "price", "label": "Purchase price ($)"},
    {"key": "priceWords", "label": "Price in words"},
    {"key": "listPrice", "label": "List price ($)"},
    {"key": "deposit", "label": "Deposit ($)"},
    {"key": "depositHolder", "label": "Deposit held by"},
    {"key": "depositDue", "label": "Deposit due"},
    {"key": "contractDate", "label": "Contract date"},
    {"key": "completionDate", "label": "Completion date"},
    {"key": "possessionDate", "label": "Possession date"},
    {"key": "possessionTime", "label": "Possession time"},
    {"key": "adjustmentDate", "label": "Adjustment date"},
    {"key": "listDate", "label": "Listing date"},
    {"key": "expiryDate", "label": "Expiry date"},
    {"key": "changeDate", "label": "Change effective date"},
    {"key": "oldPrice", "label": "Price changing from ($)"},
    {"key": "newPrice", "label": "New price ($)"},
    {"key": "commissionTotal", "label": "Total remuneration"},
    {"key": "commissionCoop", "label": "Paid to cooperating brokerage"},
    {"key": "commissionRetained", "label": "Retained by listing brokerage"},
    {"key": "commissionNoCoop", "label": "Retained if no cooperating brokerage"},
    {"key": "remunerationFrom", "label": "Remuneration paid by"},
    {"key": "mhRegistration", "label": "Registration #"},
    {"key": "mhSerial", "label": "Serial #"},
    {"key": "mhCsaLabel", "label": "CSA / Silver label"},
    {"key": "mhYear", "label": "Year"},
    {"key": "mhMake", "label": "Make"},
    {"key": "mhModel", "label": "Model"},
    {"key": "listingTerms", "label": "Listing terms"},
    {"key": "legal", "label": "Legal description", "multiline": True},
    {"key": "included", "label": "Included items", "multiline": True},
    {"key": "excluded", "label": "Excluded items", "multiline": True},
    {"key": "conditions", "label": "Subject conditions / clauses", "multiline": True},
]
# The card shows one "Property address"; the forms split it across these.
_ADDRESS_PARTS = {"p_street", "p_streetnum", "p_city", "p_state", "p_zip", "p_unit",
                  "p_streetType", "p_streetDir"}
# On nearly every form and identical every time — kept, but in the quiet tier so
# it cannot bury the fields that actually vary deal to deal. Hiding it outright
# recreated the original complaint: printed on the page, no box on the card.
_IDENTITY_KEYS = {"agentName", "officeName", "listingAgent", "listingBrokerage",
                  "sellingBrokerage", "teamName", "coAgent", "officeAddress",
                  "officeCity", "officeState", "officeZip", "officePhone",
                  "officeCell", "today"}

_TEMPLATES: Dict[str, str] = {
        "cps-residential": f"{_FORMS_DIR}/cps-residential-fillable-template.pdf",
        "cps-mobile": f"{_FORMS_DIR}/cps-mobile-fillable-template.pdf",
        "cps-mobile-addendum": f"{_FORMS_DIR}/cps-mobile-addendum-template.pdf",
        "cps-addendum": f"{_FORMS_DIR}/cps-addendum-template.pdf",
        "disclosure-remuneration": f"{_FORMS_DIR}/disclosure-remuneration-template.pdf",
        "privacy-notice": f"{_FORMS_DIR}/privacy-notice-template.pdf",
        "bcfsa-disclosure": f"{_FORMS_DIR}/bcfsa-disclosure-template.pdf",
        "condition-waiver": f"{_FORMS_DIR}/condition-waiver-template.pdf",
        # No subject-removal: Skyleigh uses the Notice of Condition Waiver
        # (conditional removal) instead (2026-07-27). Do not re-add.
        # Conditional disclosures — added to a kit on demand from the
        # "Add a form" catalog rather than built into every package.
        "expected-remuneration": f"{_FORMS_DIR}/expected-remuneration-template.pdf",
        "multiple-offers": f"{_FORMS_DIR}/multiple-offers-template.pdf",
        "referral-payment": f"{_FORMS_DIR}/referral-payment-template.pdf",
        "exp-referral-payment": f"{_FORMS_DIR}/exp-referral-payment-template.pdf",
        "interest-in-trade": f"{_FORMS_DIR}/interest-in-trade-template.pdf",
        "material-latent-defects": f"{_FORMS_DIR}/material-latent-defects-template.pdf",
}

# Onboarding fills the same three documents the kits do. Agency has its own
# fillable blank; DORTS and PNC point at the editable templates rather than the
# flat PDFs the overlay script used.
_ONBOARDING_TEMPLATES: Dict[str, str] = {
    "agency": "/Users/admin/skyleigh-tools/blank-forms/Buyer-Agency.pdf",
    "dorts": f"{_FORMS_DIR}/bcfsa-disclosure-template.pdf",
    "pnc": f"{_FORMS_DIR}/privacy-notice-template.pdf",
}

_FIELD_MAP_CACHE: Dict[str, Any] = {}


def _fill_engine_maps() -> tuple[Dict[str, str], List[Any]]:
    """DIRECT + DATE_PREFIXES from fill-form-generic.py, WITHOUT importing it.

    The engine imports pypdf, which the app runtime does not have (that is why
    every fill shells out to /usr/bin/python3). Parsing the two literals out of
    the source keeps a single source of truth for the field mapping instead of a
    copy here that would silently drift the first time a form is wired.
    """
    path = f"{_FORMS_DIR}/fill-form-generic.py"
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return {}, []
    cached = _FIELD_MAP_CACHE.get("maps")
    if cached and cached[0] == stamp:
        return cached[1], cached[2]
    import ast as _ast

    direct: Dict[str, str] = {}
    dates: List[Any] = []
    try:
        with open(path) as fh:
            tree = _ast.parse(fh.read())
        for node in tree.body:
            if isinstance(node, _ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], _ast.Name):
                name = node.targets[0].id
                if name == "DIRECT":
                    direct = _ast.literal_eval(node.value)
                elif name == "DATE_PREFIXES":
                    dates = _ast.literal_eval(node.value)
    except Exception:
        _log.exception("could not read the fill-engine field maps")
    _FIELD_MAP_CACHE["maps"] = (stamp, direct, dates)
    return direct, dates


# Widgets that are never typed into on the card. Evidence-based, structural
# rules rather than a per-form hand list, because the naming conventions are
# stable across the whole BCREA/WEBForms library:
#   hid*            template plumbing (hidDynamicPage, hidAndBSAmp, hidsand)
#   page furniture  page numbers / dynamic-page counters
#   signing stems   filled by the e-sign step, not by typing
# A field the fill engine explicitly maps ALWAYS wins over these — DIRECT
# deliberately fills txtbuyersig*/txtsellersig* as the printed-name lines the
# BCREA forms ask for under each signature.
_SUPPRESS_PREFIXES = ("hid",)
_SUPPRESS_STEMS = ("pageof", "pagenum", "dynamicpage")
# Digit-tolerant: the library numbers these (txtWitness1Sig, txtSWitness1Sig,
# txtSignerSig2, txtCsignature3), so a plain substring test misses most of them.
_SIGNING_RE = re.compile(r"(witness\d*sig|signersig\d*|signature\d*|csignature\d*|realtorsig\d*|initial\d*)")


def _humanise_field(name: str) -> str:
    """txtDiscloseNotes -> "Disclose notes". A floor, not a substitute for a
    curated label: better a plainly-named box than an invisible one."""
    n = re.sub(r"^(txt|chk|cmb|lst)", "", str(name or ""))
    n = re.sub(r"^Opt_", "", n)
    n = re.sub(r"_+", " ", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
    n = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # The generator's own typos, fixed for DISPLAY only — never in the write key.
    n = (n[:1].upper() + n[1:]) if n else str(name)
    for wrong, right in (("enumeration", "emuneration"), ("Disclosued", "Disclosed"),
                         ("cknowledgemnt", "cknowledgement"), ("Addschedule", "Schedule")):
        n = n.replace(wrong, right)
    return n


def _checkbox_labels() -> Dict[str, Dict[str, Any]]:
    """Real words for the checkbox groups, from forms/checkbox-labels.json.

    A PDF checkbox carries an export state ("1", "2") and NOTHING that says what
    the state means — the words sit in the page text beside the box. So the card
    could only ever offer "Option 1 / Option 2", which on a disclosure form is
    the same as offering nothing: the tick IS the disclosure.

    FAILS OPEN, deliberately. A missing file, malformed JSON or an unknown
    template all return {} and the card falls back to "Option N". A checkbox that
    is unreachable is a compliance gap; a checkbox with a dull label is not.
    """
    path = f"{_FORMS_DIR}/checkbox-labels.json"
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _FIELD_MAP_CACHE.get("cblabels")
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        import json as _json

        with open(path) as fh:
            data = _json.load(fh)
        out = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    except Exception:
        _log.exception("could not read %s — checkbox groups fall back to 'Option N'", path)
        out = {}
    _FIELD_MAP_CACHE["cblabels"] = (stamp, out)
    return out


def _template_field_defs(template_path: str) -> Optional[List[Dict[str, Any]]]:
    """Every field the document ACTUALLY has, from its own AcroForm widgets.

    THE POLARITY MATTERS. This used to render
    `template ∩ fill-engine-mapping ∩ hand-written catalogue` — two allow-lists
    — so a 9-field DORTS showed 2 fields and a 32-field Disclosure of Interest
    in Trade showed 2. Worse, the fields deliberately left OUT of the fill
    mapping *because a human must supply them* (txtNoticeTo, txtRelationship,
    txtRenumeration*, the disclosure checkboxes) were exactly the ones no human
    could reach. Allow-listing what to DISPLAY is the wrong polarity when
    omission means a compliance field goes unsigned-for.

    Now: the widget list is the membership test. The mapping is an annotation
    layer that supplies a nicer label, a prefill key and ordering. Anything
    unclassified defaults to VISIBLE. Returns None when no template could be
    read at all (the card then keeps whatever it had) — distinct from [], which
    means "this form genuinely has no fillable spaces".
    """
    if not template_path or not os.path.exists(template_path):
        return None
    try:
        stamp = os.path.getmtime(template_path)
    except OSError:
        stamp = 0
    ck = f"defs:{template_path}"
    hit = _FIELD_MAP_CACHE.get(ck)
    if hit and hit[0] == stamp:
        return hit[1]

    direct, dates = _fill_engine_maps()
    label_for = {d["key"]: d["label"] for d in _CARD_FIELD_CATALOG}
    order_of = {d["key"]: i for i, d in enumerate(_CARD_FIELD_CATALOG)}
    cb_meta = _checkbox_labels().get(os.path.basename(template_path), {})

    # widget name -> {page, type, states, multiline}
    seen: Dict[str, Dict[str, Any]] = {}
    try:
        import fitz

        with fitz.open(template_path) as doc:
            for pno, page in enumerate(doc):
                for w in (page.widgets() or []):
                    nm = str(w.field_name or "")
                    if not nm:
                        continue
                    rec = seen.setdefault(nm, {"page": pno + 1, "type": w.field_type_string,
                                               "states": [], "multiline": False, "readonly": False,
                                               "default": ""})
                    # What the BLANK template already has ticked. The BCFSA
                    # disclosure ships with "representing you as my client"
                    # pre-selected, so a card that showed nothing would warn
                    # about a box the PDF has marked. Surfaced as a prefill.
                    try:
                        fv = str(w.field_value or "").strip().lstrip("/")
                        if fv and fv.lower() != "off":
                            rec["default"] = fv
                    except Exception:
                        pass
                    try:
                        rect = w.rect
                        if (rect.y1 - rect.y0) > 26:
                            rec["multiline"] = True
                    except Exception:
                        pass
                    on = getattr(w, "on_state", None)
                    if callable(on):
                        try:
                            on = on()
                        except Exception:
                            on = None
                    if on and on not in ("Off", None) and on not in rec["states"]:
                        rec["states"].append(str(on))
                    try:
                        if (w.field_flags or 0) & 1:      # ReadOnly
                            rec["readonly"] = True
                    except Exception:
                        pass
    except Exception:
        _log.exception("could not read the AcroForm fields of %s", template_path)
        return None

    defs: List[Dict[str, Any]] = []
    for nm, rec in seen.items():
        low = re.sub(r"[^a-z0-9_]", "", nm.lower())
        ctx_key = direct.get(low)
        if not ctx_key:
            for prefix, key in dates:
                if low.startswith(prefix):
                    ctx_key = key
                    break
        # Suppression only applies to fields the engine does NOT deliberately fill.
        if not ctx_key:
            if low.startswith(_SUPPRESS_PREFIXES) or any(t in low for t in _SUPPRESS_STEMS):
                continue
            if rec["readonly"]:
                continue
            if _SIGNING_RE.search(low):
                continue
        # Identity that comes from the profile is real, but it is the same on
        # every document — it goes in the quiet tier rather than up top.
        tier = "standard" if ctx_key in _IDENTITY_KEYS else ("known" if ctx_key else "extra")
        is_check = str(rec["type"] or "").lower().startswith("checkbox")
        label = label_for.get(ctx_key or "", "") or _humanise_field(nm)
        d: Dict[str, Any] = {
            "key": ctx_key or f"@{nm}",     # @ = write this widget verbatim
            "widget": nm,
            "label": label,
            "multiline": bool(rec["multiline"]) and not is_check,
            "page": rec["page"],
            "type": "checkbox" if is_check else "text",
            "options": sorted(rec["states"]) if is_check and len(rec["states"]) > 1 else [],
            "tier": tier,
        }
        if is_check:
            if rec.get("default"):
                d["default"] = rec["default"]
            # The words for a tick live in the page text, not in the widget.
            # Anything unlabelled keeps the humanised name + "Option N".
            meta = cb_meta.get(nm) or {}
            if meta.get("label"):
                d["label"] = str(meta["label"])
            opts = {str(k): str(v) for k, v in (meta.get("options") or {}).items()}
            if opts:
                d["optionLabels"] = opts
            # A disclosure that leaves with nothing ticked is the gap this
            # flags; `requiredWhen` covers the follow-on ticks that only matter
            # once an earlier choice was made.
            if meta.get("required"):
                d["mustTick"] = True
            dep = meta.get("requiredWhen") or {}
            if dep.get("widget") and dep.get("in"):
                d["mustTickWhen"] = {"key": f"@{dep['widget']}",
                                     "in": [str(s) for s in dep["in"]]}
        defs.append(d)

    # One card field per context key (the forms split an address across six
    # widgets); verbatim widgets stay distinct.
    merged: Dict[str, Dict[str, Any]] = {}
    for d in defs:
        k = d["key"]
        if k in merged:
            merged[k]["page"] = min(merged[k]["page"], d["page"])
            merged[k]["multiline"] = merged[k]["multiline"] or d["multiline"]
            for o in d["options"]:
                if o not in merged[k]["options"]:
                    merged[k]["options"].append(o)
            continue
        merged[k] = d
    if any(k in _ADDRESS_PARTS for k in merged):
        page = min(v["page"] for k, v in merged.items() if k in _ADDRESS_PARTS)
        for k in list(merged):
            if k in _ADDRESS_PARTS:
                del merged[k]
        merged["property"] = {"key": "property", "widget": "", "label": "Property address",
                              "multiline": False, "page": page, "type": "text",
                              "options": [], "tier": "known"}

    out = sorted(merged.values(), key=lambda d: (
        {"known": 0, "extra": 1, "standard": 2}[d["tier"]],
        order_of.get(d["key"], 500),
        d["page"], d["label"]))
    _FIELD_MAP_CACHE[ck] = (stamp, out)
    return out


def _apply_checkbox_defaults(defs: Optional[List[Dict[str, Any]]], own: Dict[str, Any],
                             values: Dict[str, str], derived: List[str]) -> None:
    """Show the tick the blank template already carries, as a prefill.

    Some BCREA/BCFSA templates ship with an option pre-selected — the DORTS has
    "representing you as my client" ticked in the blank. The card used to show
    nothing there, which meant it disagreed with the PDF it was previewing and
    the pre-send check would flag a question the document had already answered.

    `own` is the document's OWN saved fields, and the key being PRESENT there is
    what matters, not whether it is truthy. Unticking a box saves "" — falsy,
    and indistinguishable from never-set unless we look for the key itself. Test
    truthiness instead and the default silently comes back on the card while the
    fill engine correctly clears it in the PDF, so the two disagree about a
    disclosure. An explicit untick is an answer.
    """
    if not defs:
        return
    for d in defs:
        if d.get("type") != "checkbox" or not d.get("default"):
            continue
        if d["key"] in own or values.get(d["key"]):
            continue
        values[d["key"]] = d["default"]
        derived.append(d["key"])


def _verify_kit_files(context: Any) -> Any:
    """Drop `filePath` from any kit document whose PDF is no longer on disk.

    The document record keeps its filePath forever, but the artifact cache is
    transient — 9 of 13 live buyer-kit documents pointed at files that had been
    cleared. The card read that as "Drafted", offered a Review button that
    produced nothing, and would happily tick the document into a signing
    envelope. Checked here, at the serving boundary, so every consumer sees the
    same truth; the stored record is left alone (a redraft rewrites it anyway).
    """
    try:
        toggles = (context or {}).get("deal", {}).get("extraToggles") or {}
    except AttributeError:
        return context
    for kit_key in ("offerKit", "listingKit"):
        kit = toggles.get(kit_key)
        if not isinstance(kit, dict):
            continue
        for doc in kit.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            fp = doc.get("filePath")
            if fp and not os.path.exists(str(fp)):
                doc["fileMissing"] = True
                doc["filePath"] = None
    # Onboarding docs are a dict keyed by form, not a list. Same problem: the
    # row reads "Drafted" off a filePath that may no longer exist.
    onboarding = toggles.get("onboardingDocs")
    if isinstance(onboarding, dict):
        for doc in onboarding.values():
            if not isinstance(doc, dict):
                continue
            fp = doc.get("filePath")
            if fp and not os.path.exists(str(fp)):
                doc["fileMissing"] = True
                doc["filePath"] = None
    return context


def _pdf_page_count(pdf_path: str) -> int:
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            return int(doc.page_count)
    except Exception:
        return 1


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


def _client_docs_dir(contact_id: str):
    from pathlib import Path

    base = Path(os.path.expanduser("~/.elevate/client-docs")) / contact_id
    base.mkdir(parents=True, exist_ok=True)
    return base


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
    import shutil
    from pathlib import Path

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
    if side == "listing" and current_stage not in {6, 7}:
        raise ValueError("listing deal collapse is only available from Accepted Offer or Condition Removal")
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
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="kit document not generated yet")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="attachment" if download else "inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/kit-doc/%s failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit doc failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/preview")
    def get_admin_deal_kit_doc_preview(deal_id: str, doc_id: str, page: int = 1, dpi: int = 105):
        # Rasterise one page of a kit PDF to PNG so the card can show what was
        # actually drafted WITHOUT opening a tab. The desktop shell has no PDF
        # plugin, so window.open() on a PDF renders a blank pane — checking a
        # document before it goes to a client was impossible from inside the app.
        # PyMuPDF ships in the runtime; poppler is a fallback for older installs.
        # Cached beside the PDF and invalidated by the PDF's own mtime, so a
        # redraft always supersedes the image it replaces.
        try:
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
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="kit document not drafted yet")
            png, pages = _render_pdf_page_png(file_path, max(1, int(page or 1)), int(dpi or 105))
            return Response(
                content=png,
                media_type="image/png",
                headers={"X-Page-Count": str(pages), "Cache-Control": "no-store"},
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/kit-doc/%s/preview failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/fields")
    def get_admin_deal_kit_doc_fields(deal_id: str, doc_id: str):
        # Everything the deal already knows for this document, keyed to the
        # card's field editor. The generator has always resolved these at fill
        # time, but the card only ever displayed doc["fields"] — which is empty
        # until someone types — so the editor showed a column of blank boxes on
        # a deal that knew the buyers, the address, the price and the dates.
        #
        # `values` is what to SHOW. `derived` lists the keys that came from the
        # deal rather than an explicit edit, so the card can leave them dynamic:
        # saving one unchanged would pin it and stop it tracking the deal.
        try:
            import json as _json
            from elevate_cli.data import connect

            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json, legal_description FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="deal not found")
            raw = row["extra_toggles_json"]
            toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            deal_legal = row["legal_description"] or ""
            docs = ((toggles.get("offerKit") or {}).get("documents") or [])
            doc = next((d for d in docs if d.get("id") == doc_id), None) or {"id": doc_id}

            own = {k: str(v or "").strip() for k, v in (doc.get("fields") or {}).items()}
            cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
            cpsf = {k: str(v or "").strip() for k, v in (cps.get("fields") or {}).items()}
            facts = _cps_deal_facts(deal_id) or {}
            buyers = [b for b in (facts.get("buyers") or []) if b]
            t = lambda *keys: next((str(toggles.get(k) or "").strip() for k in keys
                                    if str(toggles.get(k) or "").strip()), "")

            # Same precedence the generator uses, minus the operator's own edit
            # (that is layered on separately below so we can report which is which).
            deal_side = {
                "buyer1": buyers[0] if len(buyers) > 0 else "",
                "buyer2": buyers[1] if len(buyers) > 1 else "",
                "property": facts.get("listingAddress") or t("listingAddress") or "",
                "price": t("cpsPurchasePrice", "acceptedOffer.purchasePrice") or str(facts.get("purchasePrice") or ""),
                "deposit": t("cpsDeposit", "acceptedOffer.depositAmount"),
                "depositHolder": t("acceptedOffer.depositHolder") or "Listing Brokerage in trust",
                "depositDue": t("cpsDepositTerms", "acceptedOffer.depositDue"),
                "completionDate": t("completionDate", "acceptedOffer.completionDate"),
                "possessionDate": t("possessionDate", "acceptedOffer.possessionDate"),
                "adjustmentDate": t("adjustmentDate", "acceptedOffer.adjustmentDate"),
                "included": t("cpsInclusions"),
                "excluded": t("cpsExclusions"),
                "conditions": t("subjectConditions"),
                "legal": deal_legal or t("legalDescription"),
                "pid": t("pid"),
            }
            # The price in words is on the CPS and nothing was generating it.
            if deal_side["price"]:
                deal_side["priceWords"] = _amount_in_words(deal_side["price"])
            else:
                deal_side["priceWords"] = ""

            values: Dict[str, str] = {}
            derived: List[str] = []
            for key in set(list(deal_side.keys()) + list(own.keys()) + list(cpsf.keys())):
                if own.get(key):
                    values[key] = own[key]
                    continue
                v = cpsf.get(key) or deal_side.get(key) or ""
                values[key] = v
                if v:
                    derived.append(key)
            # Only the fields this document actually has, read off its own
            # template. Everything used to show the same 13 regardless.
            umbrella = str(toggles.get("cpsUmbrella") or "residential").strip().lower()
            tpl_id = "cps-mobile" if (doc_id == "cps-residential" and umbrella == "mobile") else doc_id
            defs = _template_field_defs(_TEMPLATES.get(tpl_id, ""))
            _apply_checkbox_defaults(defs, own, values, derived)
            out: Dict[str, Any] = {"fields": values, "derived": sorted(derived)}
            if defs is not None:
                out["defs"] = defs
            return out
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/kit-doc/%s/fields failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Kit doc fields failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/kit-doc/{doc_id}/approve")
    def post_admin_deal_kit_doc_approve(deal_id: str, doc_id: str, body: _KitDocApproveBody):
        # Toggle a kit document's status (approved / draft) from the card.
        try:
            import json as _json
            from elevate_cli.data import connect

            new_status = (body.status or "approved").strip() or "approved"
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
                found = False
                import datetime as _dt3
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        flds = d.get("fields") or {}
                        flds[body.key] = body.value or ""
                        d["fields"] = flds
                        # Marks the PDF on disk as out of date until it is rebuilt.
                        d["editedAt"] = _dt3.datetime.utcnow().isoformat()
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="kit document not found")
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
            import json as _json
            import subprocess
            import tempfile
            from elevate_cli.data import connect

            FORMS = _FORMS_DIR
            ENGINE = f"{FORMS}/fill-form-generic.py"
            TEMPLATES = _TEMPLATES
            # A template with no fillable fields can never produce a real document
            # (the filler would write 0 fields and we raise below), so fail early
            # with a message that names the actual problem. subject-removal is in
            # this state today: the PDF on disk is flat.
            # NB: cannot use pypdf here — the app runtime does not have it (that is
            # why every fill shells out to /usr/bin/python3). A byte scan for the
            # /AcroForm marker is dependency-free and enough to tell a fillable
            # template from a flat one.
            if doc_id in TEMPLATES and os.path.exists(TEMPLATES[doc_id]):
                try:
                    with open(TEMPLATES[doc_id], "rb") as _fh:
                        _has_form = b"/AcroForm" in _fh.read()
                except Exception:
                    _has_form = True  # unreadable: let the filler report it
                if not _has_form:
                    raise HTTPException(
                        status_code=400,
                        detail=f"The {doc_id} template is a flat PDF with no fillable fields. Download the editable version from WEBForms and replace {os.path.basename(TEMPLATES[doc_id])}.",
                    )
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
            if doc_id not in TEMPLATES:
                raise HTTPException(status_code=400, detail="no template wired for this document yet")
            umbrella = (toggles.get("cpsUmbrella") or "residential").strip().lower()
            is_mobile = umbrella == "mobile"
            # A mobile deal fills the base CPS slot on the Manufactured Home
            # (Rental Pad) contract, not the residential form. The manufactured
            # subjects live on a separate addendum (cps-mobile-addendum), so the
            # base CPS Section 3 only points to it.
            if doc_id == "cps-residential" and is_mobile:
                template = TEMPLATES["cps-mobile"]
            else:
                template = TEMPLATES[doc_id]
            # Every form fills from a merged source, in this precedence:
            #   1. the CPS doc's fields  (an operator edit always wins)
            #   2. the deal's own toggles
            #   3. _cps_deal_facts       (names resolved from the deal's contacts)
            # It used to read ONLY the CPS doc's fields, so a kit built WITHOUT the
            # CPS (e.g. subject removal on a deal whose contract already exists)
            # produced documents with blank buyers and blank dates even though the
            # deal knew all of it. Fixed 2026-07-27.
            cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
            _facts = _cps_deal_facts(deal_id) or {}
            _fact_buyers = [b for b in (_facts.get("buyers") or []) if b]
            _fact_sellers = [x for x in (_facts.get("sellers") or []) if x]
            # THIS document's own fields come first. Reading only the CPS doc's
            # fields meant a per-document edit (e.g. the schedule text on a
            # Notice of Condition Waiver) was silently ignored unless you were
            # editing the CPS itself. Fixed 2026-07-27.
            _own_raw = doc.get("fields") or {}
            _cf_raw = cps.get("fields") or {}

            def _cf_get(key, *fallbacks, default=""):
                own = str(_own_raw.get(key) or "").strip()
                if own:
                    return own
                v = str(_cf_raw.get(key) or "").strip()
                if v:
                    return v
                for fb in fallbacks:
                    fv = str(fb or "").strip()
                    if fv:
                        return fv
                return default

            class _CF(dict):
                """Reads like the old `cf` dict but falls through to the deal."""
                def get(self, key, default=""):
                    return _cf_get(key, _FALLBACK.get(key), default=default)

            _FALLBACK = {
                "buyer1": _fact_buyers[0] if len(_fact_buyers) > 0 else "",
                "buyer2": _fact_buyers[1] if len(_fact_buyers) > 1 else "",
                "buyer3": _fact_buyers[2] if len(_fact_buyers) > 2 else "",
                "property": _facts.get("listingAddress") or "",
                "price": toggles.get("cpsPurchasePrice") or toggles.get("acceptedOffer.purchasePrice") or _facts.get("purchasePrice") or "",
                "deposit": toggles.get("cpsDeposit") or toggles.get("acceptedOffer.depositAmount") or "",
                "depositHolder": toggles.get("acceptedOffer.depositHolder") or "Listing Brokerage in trust",
                "depositDue": toggles.get("cpsDepositTerms") or toggles.get("acceptedOffer.depositDue") or "",
                "completionDate": toggles.get("completionDate") or toggles.get("acceptedOffer.completionDate") or "",
                "possessionDate": toggles.get("possessionDate") or toggles.get("acceptedOffer.possessionDate") or "",
                "adjustmentDate": toggles.get("adjustmentDate") or toggles.get("acceptedOffer.adjustmentDate") or "",
                "included": toggles.get("cpsInclusions") or "",
                "excluded": toggles.get("cpsExclusions") or "",
                "contractDate": toggles.get("acceptedOffer.acceptedDate") or toggles.get("offerDate") or "",
            }
            cf = _CF()
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
            if not sellers:
                sellers = _fact_sellers
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
                # Brokerage/agent identity — the licensed brokerage on a BCREA CPS
                # is eXp Realty (Forever Real Estate Group is the team brand, not
                # the brokerage). These mirror the vetted constants baked into the
                # blank template so the filler writes them explicitly (rather than
                # relying on the template, which the contamination-clearing pass
                # would otherwise wipe when the context omitted them).
                "agentName": "Skyleigh McCallum PREC*",
                "officeName": "eXp Realty (Kelowna)",
                "officeAddress": "1631 Dickson Ave, Suite 1100",
                "officeCity": "Kelowna", "officeState": "BC", "officeZip": "V1Y0B5",
                "officePhone": "(833) 817-6506",
                # Price in words: an operator edit wins, otherwise derive it from
                # the price. Nothing was producing it, so the CPS's "dollars
                # ($____) ____________" line filled blank on every contract.
                "price": cf.get("price", ""),
                "priceWords": cf.get("priceWords", "") or _amount_in_words(cf.get("price", "")),
                "deposit": cf.get("deposit", ""), "depositHolder": cf.get("depositHolder", ""),
                "depositDue": cf.get("depositDue", ""),
                "completionDate": cf.get("completionDate", ""), "possessionDate": cf.get("possessionDate", ""),
                "adjustmentDate": cf.get("adjustmentDate", ""),
                "included": cf.get("included", ""), "excluded": cf.get("excluded", ""), "conditions": cf.get("conditions", ""),
                # Disclosure of Remuneration: who pays it (the other brokerage).
                "remunerationFrom": cf.get("remunerationFrom", ""),
                "today": today,
                # NOT defaulted to today: see _FALLBACK["contractDate"]. If the
                # deal does not know when the contract was made, leave it blank
                # rather than stamping today's date on it.
                "contractDate": cf.get("contractDate", ""),
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
            # A Notice of Condition Waiver states WHICH condition(s) are being
            # removed on this notice — not the contract's whole subject list. It
            # was assembling all of them, so a waiver for one subject listed
            # every subject. Its schedule is operator-controlled instead.
            _NO_ASSEMBLE = {"condition-waiver", "subject-removal"}
            assemble_here = bool(cps_clauses or cps_custom) and (
                (not is_mobile) or doc_id == "cps-mobile-addendum"
            ) and doc_id not in _NO_ASSEMBLE
            if assemble_here:
                asm_input = {
                    "umbrella": toggles.get("cpsUmbrella") or "residential",
                    "selections": cps_clauses,
                    "vars": {**(toggles.get("cpsVars") or {}), "subject_removal_date": toggles.get("subjectRemovalDate") or ""},
                    "custom": cps_custom,
                }
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as af:
                    _json.dump(asm_input, af)
                    asm_path = af.name
                asm = subprocess.run(
                    ["/usr/bin/python3", f"{FORMS}/assemble-cps-terms.py", asm_path],
                    capture_output=True, text=True, timeout=30,
                    env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"},
                )
                try:
                    os.unlink(asm_path)
                except Exception:
                    pass
                if asm.returncode == 0 and asm.stdout.strip():
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
            out_path = doc.get("filePath") or (
                f"/Users/admin/.elevate/cache/documents/admin_artifacts/offer-kits/{deal_id}-{doc_id}.pdf"
            )
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            # Per-widget overrides typed on the card. The card now shows every
            # field the document actually has, and most of those (the compliance
            # narrative fields, the disclosure checkboxes) have no context key —
            # they are stored under "@<widgetName>" and written verbatim.
            _widgets = {k[1:]: v for k, v in (doc.get("fields") or {}).items()
                        if isinstance(k, str) and k.startswith("@") and v is not None}
            if _widgets:
                context["__widgets__"] = _widgets
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                _json.dump(context, tf)
                ctx_path = tf.name
            # Clean env: the app sets PYTHON* vars that point /usr/bin/python3 at the
            # app runtime (no pypdf). HOME must be set so it finds user-site pypdf.
            proc = subprocess.run(
                ["/usr/bin/python3", ENGINE, ctx_path, template, out_path],
                capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"},
            )
            try:
                os.unlink(ctx_path)
            except Exception:
                pass
            if proc.returncode != 0:
                raise HTTPException(status_code=500, detail=f"fill failed: {(proc.stderr or '')[:300]}")
            # Post-fill verification: the filler prints "filled X/Y fields" to
            # stdout. A truthy PDF that filled 0 fields, or a missing/empty output
            # file, is a silent failure — treat it as one. Also surface blank
            # required fields so the card can prompt instead of shipping a hollow
            # contract that looked "done".
            import re as _re
            filled = None
            m = _re.search(r"filled\s+(\d+)\s*/\s*(\d+)", proc.stdout or "")
            if m:
                filled = int(m.group(1))
            if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
                raise HTTPException(status_code=500, detail="fill produced no usable PDF")
            if filled == 0:
                raise HTTPException(status_code=500, detail="fill wrote 0 fields — check the template + field mapping")
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
                import datetime as _dt4
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        d["filePath"] = out_path
                        d["ready"] = True
                        d["status"] = "draft"
                        d["warnings"] = warnings
                        d["generatedAt"] = _dt4.datetime.utcnow().isoformat()
                        d.pop("editedAt", None)
                toggles["offerKit"] = kit
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            return {"id": doc_id, "generated": True, "filled": filled, "warnings": warnings}
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
            import json as _json
            from elevate_cli.data import connect

            KITDIR = "/Users/admin/.elevate/cache/documents/admin_artifacts/offer-kits"
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
                    doc = {
                        "id": sid,
                        "name": sname,
                        "status": prev.get("status", "draft"),
                        "fillable": True,
                        "ready": bool(prev.get("ready", True)),
                        "filePath": prev.get("filePath") or f"{KITDIR}/{deal_id}-{sid}.pdf",
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

    # ── Listing Kit (seller side) ────────────────────────────────────────────
    # The listing-kit wizard shipped calling six endpoints that were never
    # written. Every call 404'd, the frontend swallowed the errors with
    # .catch(() => {}), and it reported "✓ Built N documents into the listing
    # package" unconditionally — so it claimed success after doing nothing, and
    # extra.listingKit was never written, which is why its Built Documents block
    # never rendered. These are the missing halves. Deliberately mirrors the
    # offer-kit routes above so the two kits behave the same way.
    LISTING_KITDIR = "/Users/admin/.elevate/cache/documents/admin_artifacts/listing-kits"

    # Standard listing forms + default on/off. The default-ON entries mirror
    # LISTING_FORMS / LISTING_FORM_DEFAULTS in listing-kit-wizard.tsx and must
    # stay in sync with them. The default-OFF disclosures below are intentionally
    # backend-only — the wizard surfaces those through Add a form instead of the
    # standard toggle list, so the two lists are NOT the same length.
    # FINTRAC is deliberately absent: Skyleigh does not do FINTRAC on a form any
    # more (confirmed 2026-07-27). Do not re-add it as a document.
    LISTING_STD = [
        ("mlc", "MLC — Multiple Listing Contract", True),
        ("dorts", "DORTS — Disclosure of Representation", True),
        ("pnc", "PNC — Privacy Notice & Consent", True),
        ("pds", "PDS — Property Disclosure Statement", True),
        ("pds-rural-addendum", "PDS — Rural Premises Addendum", False),
        ("pds-no-disclosure", "Property NO-Disclosure Statement", False),
        # Seller-side, needed when an offer comes in (BCFSA s.57). Default off so
        # it is not built at listing time, but present so it can be turned on the
        # moment there is an offer to present.
        ("expected-remuneration", "Disclosure to Sellers of Expected Remuneration", False),
        ("multiple-offers", "Disclosure of Multiple Offers Presented", False),
        ("material-latent-defects", "REALTORS' Disclosure of Material Latent Defects", False),
    ]
    # Anything else the listing needs is added on demand from the Add a form
    # catalog below, or uploaded. Deliberately NOT here: the MLS Data Input Sheet
    # (AIR/Matrix board form, not BCREA) and Subject Removal (Skyleigh uses the
    # Notice of Condition Waiver / conditional removal instead).
    LISTING_CATALOG = [
        ("mlc-amendment", "Amendment to Listing Contract (price / terms)"),
        ("expected-remuneration", "Disclosure to Sellers of Expected Remuneration"),
        ("multiple-offers", "Disclosure of Multiple Offers Presented"),
        ("material-latent-defects", "REALTORS' Disclosure of Material Latent Defects"),
        ("interest-in-trade", "BCFSA — Disclosure of Interest in Trade"),
        ("referral-payment", "Disclosure of Referral Payment"),
        ("exp-referral-payment", "eXp (BC) — Disclosure of Referral Payment to be Received"),
        ("condition-waiver", "Notice of Condition Waiver / Declaration of Fulfillment"),
    ]
    LISTING_STD_IDS = {sid for sid, _n, _d in LISTING_STD}
    # Forms that used to be standard and must be removed from existing kits on
    # rebuild, not silently preserved as "custom" documents.
    LISTING_RETIRED = {"fintrac", "mls-input", "subject-removal", "schedule-a"}
    # Which listing forms have a real filler wired today. Anything not in here
    # returns an explicit 400 rather than pretending it generated something.
    # Base set; the catalog/disclosure ids are folded in below once their template
    # map is defined, so the two can never drift apart.
    LISTING_WIRED = {"mlc", "dorts", "pnc", "pds", "pds-rural-addendum", "pds-no-disclosure"}

    # The PDS comes in one variant per property sub-type, so the listing's own
    # sub-type picks the form — the same way a mobile deal swaps the residential
    # CPS for the Manufactured Home contract. Sub-type ids mirror LISTING_TYPES in
    # listing-kit-wizard.tsx. Mobile/manufactured uses the Residential PDS (BCREA
    # publishes no manufactured-specific PDS).
    _FORMS_DIR = "/Users/admin/skyleigh-tools/knowledge/deals/forms"
    PDS_BY_SUBTYPE = {
        "residential": f"{_FORMS_DIR}/pds-residential-template.pdf",
        "mobile": f"{_FORMS_DIR}/pds-residential-template.pdf",
        "strata": f"{_FORMS_DIR}/pds-strata-template.pdf",
        "bare-land-strata": f"{_FORMS_DIR}/pds-bare-land-strata-template.pdf",
        "rural": f"{_FORMS_DIR}/pds-rural-template.pdf",
        "lot": f"{_FORMS_DIR}/pds-lot-template.pdf",
    }
    PDS_FIXED = {
        "pds-rural-addendum": f"{_FORMS_DIR}/pds-rural-addendum-template.pdf",
        "pds-no-disclosure": f"{_FORMS_DIR}/pds-no-disclosure-template.pdf",
    }
    # Schedule A is NOT a separate document — it is part of the MLC and prints on
    # the MLC's own Schedule A page (txtAddSchedule). This is the standard
    # services text; it mirrors SCHEDULE_A_BOILERPLATE in fill-listing-package.py
    # and SCHEDULE_A_CLAUSES in listing-kit-wizard.tsx (ids -> wording), which is
    # why the wizard only persists clause ids.
    SCHEDULE_A_INTRO = (
        "In order to assist in effecting the sale of your property we will use reasonable efforts "
        "to market the property and promote your interests. Our services include:"
    )
    SCHEDULE_A_SERVICES = [
        "Listing the property on the Multiple Listing Service® of our Board",
        "Cooperating with brokerages working with buyers",
        "Advertising the property including www.realtor.ca and/or www.icx.ca",
        "Placing a For Sale sign on the property",
        "Showing the property at times acceptable to the seller and, if any tenants, subject to tenant's rights",
        "Responding to consumer and REALTOR® inquiries",
        "Showing the property to prospective buyers",
        "Disclosing in a timely manner to the seller all appropriate facts affecting the transaction known to us",
        "Keeping the seller informed regarding the progress of the transaction",
        "Reviewing Contracts of Purchase and Sale submitted for the seller's consideration",
        "Assisting the seller in negotiating favourable terms and conditions with a buyer",
        "Assisting in the completion and possession process",
    ]
    SCHEDULE_A_CLAUSES = {
        "collapsed-sale": "Commission is earned if an accepted offer collapses due to seller default.",
        "marketing": "Authorizes signage, MLS, social, and online marketing of the property.",
        "lockbox": "Seller consents to a lockbox and reasonable showing access.",
        "measurement": "Measurements are approximate; buyer to verify if important.",
        "media-ownership": "Listing photos & media remain the property of the brokerage.",
        "dual-agency-ack": "Seller acknowledges the designated agency relationship and its limits.",
    }

    def _schedule_a_text(toggles: Dict[str, Any]) -> str:
        lines = [SCHEDULE_A_INTRO, ""]
        lines += [f"- {s}" for s in SCHEDULE_A_SERVICES]
        picked = [c for c in (toggles.get("scheduleAClauses") or []) if c in SCHEDULE_A_CLAUSES]
        custom = [c for c in (toggles.get("scheduleACustomClauses") or [])
                  if isinstance(c, dict) and str(c.get("wording") or "").strip()]
        if picked or custom:
            lines += ["", "ADDITIONAL TERMS:"]
            lines += [f"- {SCHEDULE_A_CLAUSES[c]}" for c in picked]
            lines += [f"- {str(c['wording']).strip()}" for c in custom]
        return "\n".join(lines)

    def _commission_text(short: Any) -> str:
        """Card shorthand "3.5% / 1.5%" -> the MLC's long phrasing. Mirrors
        _commission_text in fill-listing-package.py — keep the two in step."""
        import re as _re3
        s = str(short or "").strip()
        if not s:
            return ""
        sides = [p.strip() for p in _re3.split(r"[/|]", s) if p.strip()]
        if len(sides) >= 2:
            first = sides[0]
            first_txt = first if first.startswith("$") else f"{first} ON THE FIRST $100,000"
            return f"{first_txt} AND {sides[1]} ON THE REMAINDER".upper()
        return s.upper()

    # Seller-side conditional disclosures. One fixed template each, filled by the
    # same generic WEBForms filler the PDS uses.
    LISTING_DISCLOSURES = {
        "expected-remuneration": f"{_FORMS_DIR}/expected-remuneration-template.pdf",
        "multiple-offers": f"{_FORMS_DIR}/multiple-offers-template.pdf",
        "material-latent-defects": f"{_FORMS_DIR}/material-latent-defects-template.pdf",
        "interest-in-trade": f"{_FORMS_DIR}/interest-in-trade-template.pdf",
        "referral-payment": f"{_FORMS_DIR}/referral-payment-template.pdf",
        "exp-referral-payment": f"{_FORMS_DIR}/exp-referral-payment-template.pdf",
        "condition-waiver": f"{_FORMS_DIR}/condition-waiver-template.pdf",
        "mlc-amendment": f"{_FORMS_DIR}/mlc-amendment-template.pdf",
        # DORTS and PNC used to fall through to the flat-PDF overlay script,
        # which draws text at fixed coordinates on a PDF with NO fillable
        # spaces — so the card could not show their fields and nothing typed
        # could reach them. These are the same editable templates the buyer
        # Transaction Kit already fills successfully.
        "dorts": f"{_FORMS_DIR}/bcfsa-disclosure-template.pdf",
        "pnc": f"{_FORMS_DIR}/privacy-notice-template.pdf",
    }
    LISTING_WIRED = LISTING_WIRED | set(LISTING_DISCLOSURES)

    def _pds_subtype(toggles: Dict[str, Any]) -> tuple:
        """Pick the PDS variant from whatever the deal actually says its property
        is. Real data here is free text, not the wizard's clean ids ("Bare Land
        Strata / Half Duplex (Two Storey)", "Residential / Manufactured Home on
        Land", "condo"), so match on keywords in priority order. Returns
        (subtype_key, source_text, warning_or_None)."""
        raw = ""
        for k in ("listingUmbrella", "propertySubType", "propertyType", "umbrella"):
            v = str(toggles.get(k) or "").strip()
            if v:
                raw = v
                break
        s = raw.lower()
        if not s:
            return ("residential", raw, "property sub-type is not set — used the Residential PDS")
        # Commercial / business sales have no residential PDS at all. Never
        # silently hand back a residential form for one.
        if any(w in s for w in ("commercial", "business opportunity", "share sale")):
            return (None, raw, None)
        # Order matters: "bare land strata" also contains "strata".
        if "bare land" in s or "bareland" in s:
            return ("bare-land-strata", raw, None)
        if "strata" in s or "condo" in s or "apartment" in s:
            return ("strata", raw, None)
        if "rural" in s or "acreage" in s:
            return ("rural", raw, None)
        if "land only" in s or "vacant" in s or s in ("lot", "lots"):
            return ("lot", raw, None)
        if "manufactured" in s or "mobile" in s:
            # BCREA publishes no manufactured-specific PDS; the Residential PDS
            # is the correct form. Not a fallback, so no warning.
            return ("residential", raw, None)
        if "residential" in s or "detached" in s or "duplex" in s or "single family" in s:
            return ("residential", raw, None)
        return ("residential", raw, f"unrecognized property sub-type '{raw}' — used the Residential PDS")

    def _listing_toggles(conn, deal_id: str) -> Dict[str, Any]:
        import json as _json
        row = conn.execute(
            "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="deal not found")
        raw = row["extra_toggles_json"]
        return raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})

    def _listing_save(conn, deal_id: str, toggles: Dict[str, Any]) -> None:
        import json as _json
        conn.execute(
            "UPDATE deals SET extra_toggles_json=? WHERE id=?",
            (_json.dumps(toggles), deal_id),
        )

    @router.post("/api/admin/deals/{deal_id}/listing-kit/build")
    def post_admin_deal_build_listing_kit(deal_id: str):
        # Seed extra.listingKit.documents so the wizard's Built Documents block
        # has something to render. Preserves operator edits and any custom docs,
        # exactly like the offer-kit build above.
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
                existing = toggles.get("listingKit") or {}
                ex_docs = existing.get("documents") or []
                ex_by_id = {d.get("id"): d for d in ex_docs if d.get("id")}
                kit_forms = toggles.get("listingKitForms") or {}

                def _enabled(fid, dflt):
                    if fid == "mlc":
                        return True  # required
                    v = kit_forms.get(fid)
                    return bool(dflt) if v is None else bool(v)

                documents = []
                for sid, sname, dflt in LISTING_STD:
                    if not _enabled(sid, dflt):
                        continue
                    prev = ex_by_id.get(sid) or {}
                    documents.append({
                        "id": sid,
                        "name": sname,
                        "status": prev.get("status", "draft"),
                        "fillable": sid in LISTING_WIRED,
                        # A doc is only "ready" once it has actually generated a
                        # file. Seeding ready=True is what let the offer kit show
                        # Approve on documents that did not exist yet.
                        "ready": bool(prev.get("filePath")) and os.path.exists(str(prev.get("filePath") or "")),
                        "filePath": prev.get("filePath") or "",
                        "wired": sid in LISTING_WIRED,
                    })
                    if prev.get("fields"):
                        documents[-1]["fields"] = prev["fields"]
                    if prev.get("warnings"):
                        documents[-1]["warnings"] = prev["warnings"]

                # Preserve custom / catalog-added docs, but drop retired standard
                # forms. Without this a kit built before a form was retired keeps
                # showing it forever, because it no longer matches LISTING_STD_IDS
                # and so reads as "custom".
                for d in ex_docs:
                    did = d.get("id")
                    if did and did not in LISTING_STD_IDS and did not in LISTING_RETIRED:
                        documents.append(d)

                toggles["listingKit"] = {
                    "createdAt": existing.get("createdAt") or "",
                    "documents": documents,
                }
                _listing_save(conn, deal_id, toggles)
            return {"built": True, "documents": len(documents),
                    "wired": sorted(LISTING_WIRED & {d["id"] for d in documents})}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/listing-kit/build failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Build listing kit failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/listing-kit-doc/{doc_id}")
    def get_admin_deal_listing_kit_doc(deal_id: str, doc_id: str, download: int = 0):
        # Serve one listing-kit PDF. Auth: Bearer header or ?token= (the window.open
        # path), already allowlisted by _KIT_DOC_PATH_RE in web_auth.py.
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
            docs = ((toggles.get("listingKit") or {}).get("documents") or [])
            doc = next((d for d in docs if d.get("id") == doc_id), None)
            if not doc:
                raise HTTPException(status_code=404, detail="listing kit document not found")
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="listing document not generated yet")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="attachment" if download else "inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/listing-kit-doc/%s failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Listing kit doc failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/listing-kit-doc/{doc_id}/preview")
    def get_admin_deal_listing_kit_doc_preview(deal_id: str, doc_id: str, page: int = 1, dpi: int = 105):
        # Listing-side twin of the offer-kit preview. See _render_pdf_page_png.
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
            docs = ((toggles.get("listingKit") or {}).get("documents") or [])
            doc = next((d for d in docs if d.get("id") == doc_id), None)
            if not doc:
                raise HTTPException(status_code=404, detail="listing kit document not found")
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="listing document not drafted yet")
            png, pages = _render_pdf_page_png(file_path, max(1, int(page or 1)), int(dpi or 105))
            return Response(content=png, media_type="image/png",
                            headers={"X-Page-Count": str(pages), "Cache-Control": "no-store"})
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/listing-kit-doc/%s/preview failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/listing-kit-doc/{doc_id}/fields")
    def get_admin_deal_listing_kit_doc_fields(deal_id: str, doc_id: str):
        # What the listing deal already knows, keyed to the card's field editor.
        # Seller-side twin of the offer-kit /fields route.
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
                row = conn.execute(
                    "SELECT legal_description FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            deal_legal = (row["legal_description"] if row else "") or ""
            docs = ((toggles.get("listingKit") or {}).get("documents") or [])
            doc = next((d for d in docs if d.get("id") == doc_id), None) or {"id": doc_id}
            own = {k: str(v or "").strip() for k, v in (doc.get("fields") or {}).items()}
            facts = _cps_deal_facts(deal_id) or {}
            sellers = [s for s in (facts.get("sellers") or []) if s]
            if not sellers:
                sellers = [s.strip() for s in str(toggles.get("sellerNames") or "").split(",") if s.strip()]
            t = lambda *keys: next((str(toggles.get(k) or "").strip() for k in keys
                                    if str(toggles.get(k) or "").strip()), "")
            deal_side = {
                "seller1": sellers[0] if len(sellers) > 0 else "",
                "seller2": sellers[1] if len(sellers) > 1 else "",
                "property": facts.get("listingAddress") or t("listingAddress") or "",
                "listPrice": t("listPrice"),
                "listPriceWords": _amount_in_words(t("listPrice")),
                "listingCommission": t("listingCommission"),
                "buyerAgencyComp": t("buyerAgencyComp"),
                "listingDate": t("listingDate"),
                "expiryDate": t("expiryDate"),
                "designatedAgency": t("designatedAgency") or "Skyleigh McCallum",
                "pid": t("pid"),
                "legal": deal_legal or t("legalDescription", "legal"),
                "lotSize": t("lotSize"),
                "assessmentValue": t("assessmentValue"),
                "zoning": t("zoning"),
                "mls": t("mlsNumber", "mls"),
            }
            values: Dict[str, str] = {}
            derived: List[str] = []
            for key in set(list(deal_side.keys()) + list(own.keys())):
                if own.get(key):
                    values[key] = own[key]
                    continue
                v = deal_side.get(key) or ""
                values[key] = v
                if v:
                    derived.append(key)
            # Only the fields this listing document actually has.
            tpl = ""
            if doc_id == "mlc":
                tpl = f"{_FORMS_DIR}/mlc-fillable-template.pdf"
            elif doc_id in LISTING_DISCLOSURES:
                tpl = LISTING_DISCLOSURES[doc_id]
            elif doc_id in PDS_FIXED:
                tpl = PDS_FIXED[doc_id]
            elif doc_id == "pds":
                sub, _raw, _warn = _pds_subtype(toggles)
                tpl = PDS_BY_SUBTYPE.get(sub, "") if sub else ""
            l_defs = _template_field_defs(tpl)
            _apply_checkbox_defaults(l_defs, own, values, derived)
            l_out: Dict[str, Any] = {"fields": values, "derived": sorted(derived)}
            if l_defs is not None:
                l_out["defs"] = l_defs
            return l_out
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/listing-kit-doc/%s/fields failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Listing kit fields failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/listing-kit-doc/{doc_id}/approve")
    def post_admin_deal_listing_kit_doc_approve(deal_id: str, doc_id: str, body: _KitDocApproveBody):
        try:
            from elevate_cli.data import connect

            new_status = (body.status or "approved").strip() or "approved"
            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
                kit = toggles.get("listingKit") or {}
                found = False
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        # Never let an ungenerated document be approved.
                        if new_status == "approved" and not (d.get("filePath") and os.path.exists(str(d.get("filePath")))):
                            raise HTTPException(status_code=400, detail="generate the document before approving it")
                        d["status"] = new_status
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="listing kit document not found")
                toggles["listingKit"] = kit
                _listing_save(conn, deal_id, toggles)
            return {"id": doc_id, "status": new_status}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/listing-kit-doc/%s/approve failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Listing approve failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/listing-kit-doc/{doc_id}/field")
    def post_admin_deal_listing_kit_doc_field(deal_id: str, doc_id: str, body: _KitFieldBody):
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
                kit = toggles.get("listingKit") or {}
                found = False
                import datetime as _dt5
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        flds = d.get("fields") or {}
                        flds[body.key] = body.value or ""
                        d["fields"] = flds
                        d["editedAt"] = _dt5.datetime.utcnow().isoformat()
                        found = True
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="listing kit document not found")
                toggles["listingKit"] = kit
                _listing_save(conn, deal_id, toggles)
            return {"id": doc_id, "key": body.key, "value": body.value}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/listing-kit-doc/%s/field failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Listing field save failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/listing-kit-doc/{doc_id}/generate")
    def post_admin_deal_listing_kit_doc_generate(deal_id: str, doc_id: str):
        # Fill one listing document. The MLC, the PDS variants and the seller
        # disclosures all go through the official fillable templates + the generic
        # WEBForms filler. DORTS + PNC go through offer-prep-forms.py. Anything
        # else has no filler yet and says so instead of faking a result.
        try:
            import json as _json
            import shutil as _shutil
            import subprocess as _sp
            from elevate_cli.data import connect

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
            kit = toggles.get("listingKit") or {}
            docs = kit.get("documents") or []
            doc = next((d for d in docs if d.get("id") == doc_id), None)
            if not doc:
                raise HTTPException(status_code=404, detail="listing kit document not found")
            if doc_id not in LISTING_WIRED:
                raise HTTPException(
                    status_code=400,
                    detail=f"No filler wired for {doc_id} yet — it needs a fillable template before it can generate.",
                )

            facts = _cps_deal_facts(deal_id) or {}
            sellers = [s for s in (facts.get("sellers") or []) if s]
            if not sellers:
                sellers = [s.strip() for s in str(toggles.get("sellerNames") or "").split(",") if s.strip()]
            # Deal data often carries co-sellers as one "A; B" string. Every BCREA
            # form gives each seller their own name + signature line, so split them
            # out instead of stacking both names on line 1. Only on ";" — a comma
            # can legitimately be inside a name ("John Smith, Jr.").
            _split: List[str] = []
            for s in sellers:
                _split.extend(p.strip() for p in str(s).split(";") if p.strip())
            sellers = _split or sellers
            address = str(facts.get("listingAddress") or toggles.get("listingAddress") or "").strip()

            os.makedirs(LISTING_KITDIR, exist_ok=True)
            out_path = doc.get("filePath") or f"{LISTING_KITDIR}/{deal_id}-{doc_id}.pdf"
            warnings: List[str] = []

            if doc_id == "mlc":
                # Switched 2026-07-27 from the coordinate-overlay fill on the flat
                # blank to the official fillable MLC + the generic WEBForms filler.
                # Output stays an editable AcroForm, and Schedule A goes into the
                # MLC's own Schedule A page rather than being a separate document.
                # Deals with an already-signed MLC keep the document they signed —
                # this only affects MLCs generated from here on.
                template = f"{_FORMS_DIR}/mlc-fillable-template.pdf"
                if not os.path.exists(template):
                    raise HTTPException(status_code=500, detail="mlc-fillable-template.pdf missing")
                engine = f"{_FORMS_DIR}/fill-form-generic.py"
                addr_parts = [x.strip() for x in address.split(",") if x.strip()]
                street = addr_parts[0] if addr_parts else ""
                import re as _re4
                snum = sname = stype = ""
                m = _re4.match(r"^(\d+)\s+(.+?)\s+(\w+)$", street)
                if m:
                    snum, sname, stype = m.group(1), m.group(2), m.group(3)
                else:
                    sp = street.split(" ", 1)
                    if sp and sp[0].isdigit():
                        snum, sname = sp[0], (sp[1] if len(sp) > 1 else "")
                    else:
                        sname = street
                pc_m = _re4.search(r"[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d", " ".join(addr_parts[1:]))
                p_zip = pc_m.group(0).upper() if pc_m else ""
                city = _re4.sub(r"[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d", "", addr_parts[1] if len(addr_parts) > 1 else "")
                city = _re4.sub(r"\b(BC|B\.C\.|British Columbia)\b", "", city, flags=_re4.I).strip(" ,")
                total = _commission_text(toggles.get("listingCommission"))
                coop = _commission_text(toggles.get("buyerAgencyComp"))
                import datetime as _dt2
                ctx = {
                    "p_streetnum": snum, "p_street": sname, "p_streetType": stype,
                    "p_city": city, "p_state": "BC", "p_zip": p_zip,
                    "p_unit": toggles.get("unitNumber") or "",
                    "legal": toggles.get("legalDescription") or toggles.get("legal") or "",
                    "pid": toggles.get("pid") or "",
                    "otherPids": toggles.get("otherPids") or "",
                    "mls": toggles.get("mlsNumber") or "",
                    "listPrice": toggles.get("listPrice") or "",
                    "listDate": toggles.get("listingDate") or "",
                    "expiryDate": toggles.get("expiryDate") or "",
                    "listingTerms": toggles.get("listingTerms") or "Cash to new mortgage",
                    "commissionTotal": total,
                    "commissionCoop": coop,
                    "commissionNoCoop": total,
                    "conditions": _schedule_a_text(toggles),
                    "signDate": _dt2.date.today().isoformat(),
                    "today": _dt2.date.today().isoformat(),
                    "listingAgent": toggles.get("designatedAgency") or "Skyleigh McCallum Personal Real Estate Corporation",
                    "coAgent": "Antonia Gujinovic",
                    "listingBrokerage": "eXp Realty",
                    "officeName": "eXp Realty",
                    "officeAddress": "1631 Dickson Ave, Suite 1100",
                    "officeCity": "Kelowna", "officeState": "BC",
                    "officeZip": "V1Y 0B5", "officePhone": "(833) 817-6506",
                }
                for i, s in enumerate(sellers[:3], start=1):
                    ctx[f"seller{i}"] = s
                for k, v in (doc.get("fields") or {}).items():
                    if v:
                        ctx[k] = v
                cf = f"/tmp/listing-kit-{deal_id}-mlc-ctx.json"
                with open(cf, "w") as f:
                    _w = {k[1:]: v for k, v in (doc.get("fields") or {}).items()
                          if isinstance(k, str) and k.startswith("@") and v is not None}
                    if _w:
                        ctx["__widgets__"] = _w
                    _json.dump(ctx, f)
                r = _sp.run(["/usr/bin/python3", engine, cf, template, out_path],
                            capture_output=True, text=True, timeout=180, env=_user_site_env())
                if r.returncode != 0:
                    raise HTTPException(status_code=500, detail=f"MLC fill failed: {(r.stderr or '')[:300]}")
                for label, val in (
                    ("sellers", ", ".join(sellers)),
                    ("property address", address),
                    ("list price", toggles.get("listPrice")),
                    ("listing commission", toggles.get("listingCommission")),
                    ("buyer agency compensation", toggles.get("buyerAgencyComp")),
                    ("effective date", toggles.get("listingDate")),
                    ("expiry date", toggles.get("expiryDate")),
                    ("PID", toggles.get("pid")),
                ):
                    if not str(val or "").strip():
                        warnings.append(f"{label} is blank")
                # The MLC's "Listing Brokerage will retain" line cannot be derived
                # from two split-rate strings, so it is never auto-filled.
                warnings.append("listing brokerage's retained share (Section 5 D(ii)) needs filling by hand")
            elif doc_id.startswith("pds") or doc_id in LISTING_DISCLOSURES:
                # PDS. The seller answers the disclosure questions themselves —
                # those are not form fields and we must never pre-answer them.
                # We fill only the property identity block + date, then it goes to
                # the seller to complete. Variant is chosen by the listing's
                # sub-type so a strata listing gets the strata PDS, etc.
                if doc_id in LISTING_DISCLOSURES:
                    template = LISTING_DISCLOSURES[doc_id]
                elif doc_id in PDS_FIXED:
                    template = PDS_FIXED[doc_id]
                else:
                    subtype, raw_subtype, warn = _pds_subtype(toggles)
                    if subtype is None:
                        raise HTTPException(
                            status_code=400,
                            detail=f"'{raw_subtype}' is a commercial/business sale — there is no residential PDS for it. Use the No-Disclosure statement or a commercial disclosure instead.",
                        )
                    template = PDS_BY_SUBTYPE[subtype]
                    if warn:
                        warnings.append(warn)
                if not os.path.exists(template):
                    raise HTTPException(status_code=500, detail=f"{doc_id} template missing: {os.path.basename(template)}")
                engine = f"{_FORMS_DIR}/fill-form-generic.py"
                addr_parts = [x.strip() for x in address.split(",") if x.strip()]
                street = addr_parts[0] if addr_parts else ""
                snum = sname = ""
                sp = street.split(" ", 1)
                if sp and sp[0].isdigit():
                    snum, sname = sp[0], (sp[1] if len(sp) > 1 else "")
                else:
                    sname = street
                # The city part of a deal address usually carries the province and
                # postal code too ("Louis Creek BC V0E 2E0"). Split them out so
                # each lands in its own field instead of all three in CITY.
                import re as _re2
                city_raw = addr_parts[1] if len(addr_parts) > 1 else ""
                pc_m = _re2.search(r"[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d", " ".join(addr_parts[1:]))
                p_zip = pc_m.group(0).upper() if pc_m else ""
                city = _re2.sub(r"[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d", "", city_raw)
                city = _re2.sub(r"\b(BC|B\.C\.|British Columbia)\b", "", city, flags=_re2.I).strip(" ,")
                import datetime as _dt
                ctx = {
                    "p_streetnum": snum, "p_street": sname,
                    "p_city": city,
                    "p_zip": p_zip,
                    "p_state": "BC",
                    "legal": toggles.get("legalDescription") or toggles.get("legal") or "",
                    "mls": toggles.get("mlsNumber") or "",
                    "today": _dt.date.today().isoformat(),
                }
                for i, s in enumerate(sellers[:3], start=1):
                    ctx[f"seller{i}"] = s
                # BCFSA disclosures print the professional's own details. Skyleigh's
                # rule: designated agent in full, and the team field carries BOTH
                # licensees. Blank here is a compliance gap, not a cosmetic one.
                ctx.update({
                    "agentName": "Skyleigh McCallum Personal Real Estate Corporation",
                    "listingAgent": "Skyleigh McCallum Personal Real Estate Corporation",
                    "coAgent": "Antonia Gujinovic",
                    "teamName": "Forever Real Estate Group — Skyleigh McCallum, Antonia Gujinovic",
                    "listingBrokerage": "eXp Realty",
                    "officeName": "eXp Realty",
                    "officeAddress": "1631 Dickson Ave, Suite 1100",
                    "officeCity": "Kelowna",
                    "officeState": "BC",
                    "officeZip": "V1Y 0B5",
                    "officePhone": "(833) 817-6506",
                    "pid": toggles.get("pid") or "",
                })
                if doc_id == "mlc-amendment":
                    # Old price = what the listing is at now; new price only if the
                    # card already carries one. Never invent the new figure — a
                    # blank line is correct until she decides the number.
                    ctx["oldPrice"] = str(toggles.get("listPrice") or "")
                    ctx["newPrice"] = str(toggles.get("newListPrice") or "")
                    ctx["listingTerms"] = str(toggles.get("listingTerms") or "")
                    if not ctx["oldPrice"].strip():
                        warnings.append("current list price is blank")
                    if not ctx["newPrice"].strip():
                        warnings.append("new price is blank — fill it in before sending")
                cf = f"/tmp/listing-kit-{deal_id}-{doc_id}-ctx.json"
                with open(cf, "w") as f:
                    _w = {k[1:]: v for k, v in (doc.get("fields") or {}).items()
                          if isinstance(k, str) and k.startswith("@") and v is not None}
                    if _w:
                        ctx["__widgets__"] = _w
                    _json.dump(ctx, f)
                r = _sp.run(["/usr/bin/python3", engine, cf, template, out_path],
                            capture_output=True, text=True, timeout=120, env=_user_site_env())
                if r.returncode != 0:
                    raise HTTPException(status_code=500, detail=f"{doc_id} fill failed: {(r.stderr or '')[:300]}")
                if not sellers:
                    warnings.append("seller names are blank")
                if not str(ctx["p_streetnum"] or ctx["p_street"]).strip():
                    warnings.append("property address is blank")
            else:
                # DORTS / PNC. The form names "the client"; on a listing the
                # clients are the sellers, so they go in the buyers slot the
                # filler reads. Same form, seller-side parties.
                script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")
                if not os.path.exists(script):
                    raise HTTPException(status_code=500, detail="offer-prep-forms.py not found")
                payload_facts = dict(facts)
                payload_facts["buyers"] = sellers
                payload_facts["sellers"] = sellers
                pl = {"address": address or "Property", "dealId": deal_id,
                      "dryRun": True, "form": doc_id, "deal": payload_facts}
                pf = f"/tmp/listing-kit-{deal_id}-{doc_id}.json"
                with open(pf, "w") as f:
                    _json.dump(pl, f)
                r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                            text=True, timeout=120, env=_user_site_env())
                res: Dict[str, Any] = {}
                for line in reversed((r.stdout or "").strip().splitlines()):
                    try:
                        res = _json.loads(line)
                        break
                    except Exception:
                        continue
                if not (res.get("ok") and res.get("pdf") and os.path.exists(res["pdf"])):
                    raise HTTPException(status_code=500, detail=f"{doc_id} fill failed: {(r.stderr or '')[:300]}")
                _shutil.move(res["pdf"], out_path)
                if not sellers:
                    warnings.append("seller names are blank")

            if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
                raise HTTPException(status_code=500, detail="fill produced no usable PDF")

            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
                kit = toggles.get("listingKit") or {}
                import datetime as _dt4
                for d in (kit.get("documents") or []):
                    if d.get("id") == doc_id:
                        d["filePath"] = out_path
                        d["ready"] = True
                        d["status"] = "draft"
                        d["warnings"] = warnings
                        d["generatedAt"] = _dt4.datetime.utcnow().isoformat()
                        d.pop("editedAt", None)
                toggles["listingKit"] = kit
                _listing_save(conn, deal_id, toggles)
            return {"id": doc_id, "generated": True, "warnings": warnings}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/listing-kit-doc/%s/generate failed", deal_id, doc_id)
            raise HTTPException(status_code=500, detail=f"Generate failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/listing-kit/catalog")
    def get_admin_deal_listing_kit_catalog(deal_id: str):
        # Forms the Build & Sign page can add on demand. Only offer the ones whose
        # template actually exists and is fillable, so the catalog never lists
        # something that will fail the moment she picks it.
        out = []
        for fid, label in LISTING_CATALOG:
            tpl = LISTING_DISCLOSURES.get(fid)
            ok = False
            if tpl and os.path.exists(tpl):
                try:
                    with open(tpl, "rb") as fh:
                        ok = b"/AcroForm" in fh.read()
                except Exception:
                    ok = False
            out.append({"id": fid, "label": label, "available": ok,
                        "reason": "" if ok else "no fillable template yet"})
        return {"forms": out}

    @router.post("/api/admin/deals/{deal_id}/listing-kit-doc/add")
    def post_admin_deal_listing_kit_doc_add(deal_id: str, body: _KitAddBody):
        # Add a form to the listing kit: upload a PDF (base64 in contentB64) or
        # pick a catalog template. Mirrors kit-doc/add on the offer side.
        try:
            import base64 as _b64
            import re as _re
            from elevate_cli.data import connect

            os.makedirs(LISTING_KITDIR, exist_ok=True)
            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
                kit = toggles.get("listingKit") or {"createdAt": "", "documents": []}
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
                    out_path = f"{LISTING_KITDIR}/{deal_id}-{doc_id}.pdf"
                    with open(out_path, "wb") as fh:
                        fh.write(data)
                    docs.append({"id": doc_id, "name": fname, "status": "draft",
                                 "fillable": False, "ready": True, "filePath": out_path})
                elif body.templateId:
                    tid = body.templateId.strip()
                    if any(d.get("id") == tid for d in docs):
                        raise HTTPException(status_code=400, detail="already in this listing kit")
                    tpl = LISTING_DISCLOSURES.get(tid)
                    if not tpl or not os.path.exists(tpl):
                        raise HTTPException(
                            status_code=400,
                            detail=f"No template for {tid} yet — download the editable version from WEBForms first.",
                        )
                    label = next((l for i, l in LISTING_CATALOG if i == tid), tid)
                    docs.append({"id": tid, "name": (body.name or label), "status": "draft",
                                 "fillable": True, "ready": False, "filePath": ""})
                else:
                    raise HTTPException(status_code=400, detail="need a file or templateId")
                kit["documents"] = docs
                toggles["listingKit"] = kit
                _listing_save(conn, deal_id, toggles)
            return {"ok": True, "documents": len(docs)}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("POST /api/admin/deals/%s/listing-kit-doc/add failed", deal_id)
            raise HTTPException(status_code=500, detail=f"Add form failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/listing-sign")
    def post_admin_deal_listing_sign(deal_id: str):
        """Draft-first send of the listing package to the sellers. Merges the
        approved listing documents into one preview and parks a Review & approve
        card carrying it, so nothing reaches the sellers before Skyleigh has seen
        the actual drafts. Mirrors onboarding-sign."""
        try:
            require_admin_setup_ready_for_launch()
            import json as _json
            import subprocess as _sp
            from elevate_cli.data import connect
            from elevate_cli.data.dispatch import queue_action_run

            facts = _cps_deal_facts(deal_id) or {}
            with connect() as conn:
                toggles = _listing_toggles(conn, deal_id)
            docs = ((toggles.get("listingKit") or {}).get("documents") or [])
            chosen = [
                d for d in docs
                if d.get("status") == "approved"
                and d.get("filePath") and os.path.exists(str(d.get("filePath")))
            ]
            if not chosen:
                raise HTTPException(
                    status_code=400,
                    detail="Nothing to send yet — generate and approve at least one listing document first.",
                )

            preview_pdf = None
            try:
                pv_dir = os.path.expanduser("~/.elevate/uploads/listing-previews")
                os.makedirs(pv_dir, exist_ok=True)
                preview_path = f"{pv_dir}/{deal_id}-listing-preview.pdf"
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
                mr = _sp.run(
                    ["/usr/bin/python3", "-c", merge_src, preview_path] + [str(d["filePath"]) for d in chosen],
                    capture_output=True, text=True, timeout=60, env=_user_site_env(),
                )
                if mr.returncode == 0 and os.path.exists(preview_path):
                    preview_pdf = preview_path
            except Exception:
                _log.exception("listing preview merge failed; parking without a preview")
                preview_pdf = None

            sellers = [s for s in (facts.get("sellers") or []) if s]
            who = ", ".join(sellers) or "the seller(s)"
            payload = {
                "purpose": "listing-package-signatures",
                "documents": [d.get("name") for d in chosen],
                "prefilledDocs": [{"form": d.get("id"), "pdf": d.get("filePath")} for d in chosen],
                "previewPdf": preview_pdf or "",
                "note": (
                    "The listing documents are ALREADY filled (local paths in prefilledDocs). "
                    "After the user approves, upload exactly those PDFs to the configured signing "
                    "provider and send them to the seller(s) in ONE envelope. Do not re-fill or regenerate."
                ),
            }
            with connect() as conn:
                run = queue_action_run(
                    conn, deal_id=deal_id, skill="real-estate-admin/signing-package",
                    name="Send listing package for signatures", payload=payload,
                    create_cron_job=not preview_pdf, actor="dashboard:listing-kit")
                rid = run.get("id") if isinstance(run, dict) else None
                if preview_pdf:
                    prompt = {
                        "title": "Review & approve: listing package",
                        "message": (
                            f"{len(chosen)} listing document(s) are drafted and filled for {who}. "
                            "Open the Preview to review, then approve to send them for signature by DigiSign."
                        ),
                        "requiredFields": [
                            f"Approve sending the filled listing package to {who} for signature by DigiSign? yes/no"
                        ],
                        "previewPdf": preview_pdf,
                    }
                    conn.execute(
                        "UPDATE admin_action_runs SET status='waiting_human', human_prompt_json=? WHERE id=?",
                        (_json.dumps(prompt), rid),
                    )
            return {"ok": True, "runId": rid, "previewPdf": preview_pdf or "",
                    "documents": len(chosen), "draftFirst": bool(preview_pdf)}
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            _log.exception("listing sign dispatch failed")
            raise HTTPException(status_code=500, detail=f"Send for signatures failed: {exc}")

    @router.post("/api/admin/deals/{deal_id}/listing-pull-records")
    def post_admin_deal_listing_pull_records(deal_id: str):
        # Title / BC Assessment / zoning pull. No automated pull is wired yet, so
        # say that plainly instead of leaving the wizard spinning for 3 minutes on
        # a 404 (which is what it did before).
        raise HTTPException(
            status_code=501,
            detail="Automated records pull is not wired yet. Pull title through the mlc-title flow and the PID, legal description and zoning fields will populate.",
        )

    @router.post("/api/admin/deals/{deal_id}/kit-doc/add")
    def post_admin_deal_kit_doc_add(deal_id: str, body: _KitAddBody):
        # Add a form to the offer kit: upload a PDF (base64 in contentB64) or pick
        # a wired catalog template (templateId). Appends to offerKit.documents.
        try:
            import json as _json
            import base64 as _b64
            import re as _re
            from elevate_cli.data import connect

            KITDIR = "/Users/admin/.elevate/cache/documents/admin_artifacts/offer-kits"
            os.makedirs(KITDIR, exist_ok=True)
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
                    out_path = f"{KITDIR}/{deal_id}-{doc_id}.pdf"
                    with open(out_path, "wb") as fh:
                        fh.write(data)
                    docs.append({"id": doc_id, "name": fname, "status": "draft", "fillable": False, "ready": True, "filePath": out_path})
                elif body.templateId:
                    tid = body.templateId.strip()
                    if any(d.get("id") == tid for d in docs):
                        raise HTTPException(status_code=400, detail="already in kit")
                    cps = next((d for d in docs if d.get("id") == "cps-residential"), {}) or {}
                    docs.append({"id": tid, "name": (body.name or tid), "status": "draft", "fillable": True, "ready": True, "filePath": f"{KITDIR}/{deal_id}-{tid}.pdf", "fields": dict(cps.get("fields") or {})})
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
                toggles["mlsNumber"] = mls
                toggles["listingPullStatus"] = "pulling"
                conn.execute(
                    "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                    (_json.dumps(toggles), deal_id),
                )
            script = "/Users/admin/skyleigh-tools/scripts/pull-listing-by-mls.js"
            if os.path.exists(script):
                log = open("/Users/admin/.elevate/cache/pull-listing.log", "a")
                subprocess.Popen(
                    ["/usr/local/bin/node", script, deal_id, mls],
                    stdout=log, stderr=subprocess.STDOUT,
                    env={"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin", "HOME": "/Users/admin"},
                )
            return {"started": True, "mls": mls}
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
            path = "/Users/admin/skyleigh-tools/knowledge/deals/forms/webforms-clauses.json"
            if not os.path.exists(path):
                return {"folders": {"system": [], "office": [], "personal": []}, "counts": {}}
            return _json.loads(open(path).read())
        except Exception as exc:
            _log.exception("GET /api/admin/clause-library failed")
            raise HTTPException(status_code=500, detail=f"Clause library failed: {exc}")

    class _PersonalClauseBody(BaseModel):
        # Save a new reusable personal clause into the shared clause library.
        title: Optional[str] = ""
        wording: str

    @router.post("/api/admin/clause-library/personal")
    def add_personal_clause(body: _PersonalClauseBody):
        # Append a personal clause to webforms-clauses.json (the same file the
        # GET route serves) so it shows up in the picker on every future deal.
        try:
            import json as _json
            path = "/Users/admin/skyleigh-tools/knowledge/deals/forms/webforms-clauses.json"
            wording = (body.wording or "").strip()
            if not wording:
                raise HTTPException(status_code=400, detail="Clause wording is required")
            title = (body.title or "").strip() or "Personal clause"
            if os.path.exists(path):
                data = _json.loads(open(path).read())
            else:
                data = {"folders": {"system": [], "office": [], "personal": []}, "counts": {}}
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
                return _verify_kit_files(get_deal_context(conn, deal_id))
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
                context = _verify_kit_files(get_deal_context(conn, deal_id))
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
                return _verify_kit_files(get_deal_context(conn, deal_id))
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
    # form + Schedule A. Both call scripts in ~/skyleigh-tools (separate repo),
    # spawned with /usr/bin/python3 because the PDF deps (reportlab/pypdf/fitz)
    # are --user installs the dashboard's default python can't see.

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
            script = os.path.expanduser("~/skyleigh-tools/scripts/cps-prep-package.sh")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="CPS gather script not found")
            args = ["/bin/bash", script, mls]
            if body.dry_run:
                args.append("--dry-run")
            # DEAL_ID lets the gather write the extracted legal/PID back onto the
            # deal once the title finishes downloading, so Generate has them no
            # matter the timing.
            gather_env = {**os.environ, "DEAL_ID": (body.deal_id or "")}
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
        import re as _re
        import subprocess as _sp

        try:
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
            pf = f"/tmp/cps-gen-payload-{body.deal_id or 'x'}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            script = os.path.expanduser("~/skyleigh-tools/scripts/cps-generate.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="CPS generate script not found")
            # /usr/bin/python3 has reportlab/pypdf/fitz as --user installs; the
            # dashboard hides them with PYTHONNOUSERSITE + a bundle PYTHONPATH/
            # PYTHONHOME. Strip those and point at the user site-packages.
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                                      "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
            child_env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=120, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("CPS generate produced no PDF: %s | %s", (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Generation failed to produce a PDF")
            _log.info("CPS draft generated for %s (dry_run=%s, saved=%s)", result.get("address"), body.dry_run, "save" in result)
            return {"ok": True, "address": result.get("address"), "saved": ("save" in result),
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
        import re as _re
        import subprocess as _sp

        try:
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
            pf = f"/tmp/offer-form-payload-{body.deal_id or 'x'}-{form}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="Offer-prep forms script not found")
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                                      "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
            child_env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=120, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("offer form %s produced no PDF: %s | %s", form, (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Form generation failed")
            _log.info("offer-prep form %s generated for %s (dry_run=%s)", form, result.get("address"), body.dry_run)
            return {"ok": True, "form": form, "address": result.get("address"),
                    "saved": ("save" in result), "url": result.get("url"), "dryRun": body.dry_run}
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
        import re as _re
        import subprocess as _sp

        try:
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
            pf = f"/tmp/offer-package-payload-{body.deal_id or 'x'}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-package.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="Offer-prep package script not found")
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                                      "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
            child_env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=180, env=child_env)
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
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

    def _doc_is_stale(doc: Dict[str, Any]) -> bool:
        """A kit document is stale when its fields were edited after the PDF was
        last generated. Both stamps are written by the routes below; a document
        with no editedAt was never hand-edited, so it is never stale."""
        ed = str(doc.get("editedAt") or "")
        gen = str(doc.get("generatedAt") or "")
        if not ed:
            return False
        return (not gen) or ed > gen

    def _user_site_env():
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
        env["PYTHONPATH"] = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
        return env

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
            script = os.path.expanduser("~/skyleigh-tools/scripts/deal-docs-list.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="docs-list script not found")
            r = _sp.run(["/usr/bin/python3", script, "--address", address],
                        capture_output=True, text=True, timeout=60, env=_user_site_env())
            base = None
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    base = _json.loads(line)
                    break
                except Exception:
                    continue
            if base is None:
                _log.warning("deal documents: no JSON from docs-list: %s | %s", (r.stdout or "")[-200:], (r.stderr or "")[-200:])
                base = dict(empty)
            # Append the client-level (contact-scoped) documents as their own
            # group, so property docs and reusable client docs live in the same
            # Documents tab, just separated. See client-doc-reuse-architecture.md.
            try:
                base.setdefault("files", [])
                base["files"].extend(_client_document_entries(deal_id))
            except Exception:
                _log.exception("append client documents failed for deal %s", deal_id)
            return base
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
        engine = "/Users/admin/elevate-premium/scripts/digisign_engine.py"
        if not os.path.exists(engine):
            return {"ok": False, "error": "digisign_engine.py not found"}
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
        mf = f"/tmp/digisign-manifest-{deal_id}.json"
        with open(mf, "w") as f:
            _json.dump(manifest, f)
        # digisign_engine's token refresh shells out to `node`; the dashboard's
        # launchd PATH omits /usr/local/bin, so add it explicitly.
        eng_env = _user_site_env()
        eng_env["PATH"] = "/usr/local/bin:/usr/bin:/bin:" + eng_env.get("PATH", "")
        try:
            r = _sp.run(["/usr/bin/python3", engine, "--manifest", mf], capture_output=True, text=True, timeout=240, env=eng_env)
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
        script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")

        prefilled: List[Dict[str, str]] = []
        labels: List[str] = []
        missing: List[str] = []
        for key in form_keys:
            spec = _SIGNABLE_FORMS.get(key)
            if not spec or not os.path.exists(script):
                missing.append(key); continue
            pl = {"address": address, "dealId": deal_id, "dryRun": True, "deal": facts, "form": spec["formArg"]}
            pf = f"/tmp/prepare-signable-{deal_id}-{key}.json"
            with open(pf, "w") as f:
                _json.dump(pl, f)
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True, text=True, timeout=120, env=_user_site_env())
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

        pv_dir = os.path.expanduser("~/.elevate/uploads/signable-previews")
        os.makedirs(pv_dir, exist_ok=True)
        safe_purpose = re.sub(r"[^a-z0-9._-]+", "-", (purpose or "signables").lower())
        preview_pdf = f"{pv_dir}/{deal_id}-{safe_purpose}-preview.pdf"
        merge_src = (
            "import sys\nfrom pypdf import PdfReader, PdfWriter\nw = PdfWriter()\n"
            "for f in sys.argv[2:]:\n    for p in PdfReader(f).pages:\n        w.add_page(p)\n"
            "with open(sys.argv[1], 'wb') as fh:\n    w.write(fh)\n"
        )
        mr = _sp.run(["/usr/bin/python3", "-c", merge_src, preview_pdf] + [d["pdf"] for d in prefilled],
                     capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"})
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
            require_admin_setup_ready_for_launch()
            form = (body.form or "").strip().lower()
            if form not in ("agency", "dorts", "pnc"):
                raise HTTPException(status_code=400, detail="Unknown onboarding form")
            facts = _cps_deal_facts(deal_id)
            # Manual overrides from the card's Edit panel win over deal-derived
            # values. Blank entries are dropped so an untouched input never wipes
            # a good value that came off the deal.
            overrides = {
                k: v for k, v in (body.fields or {}).items()
                if v is not None and str(v).strip() != ""
            }
            # Keep the operator's raw entries for the card to re-seed the Edit
            # panel; `overrides` below gets consumed while merging into facts.
            saved_overrides = dict(overrides)
            if overrides:
                buyers_ov = overrides.pop("buyers", None)
                if isinstance(buyers_ov, str):
                    buyers_ov = [b.strip() for b in buyers_ov.split(",") if b.strip()]
                if isinstance(buyers_ov, list) and buyers_ov:
                    facts["buyers"] = buyers_ov
                facts.update(overrides)
            address = str(facts.get("listingAddress") or "Property").split(",")[0].strip() or "Property"
            payload: Dict[str, Any] = {"address": address, "dealId": deal_id, "dryRun": False, "deal": facts}
            if form == "agency":
                script = os.path.expanduser("~/skyleigh-tools/scripts/buyer-agency-fill.py")
            else:
                payload["form"] = form
                script = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")
            if not os.path.exists(script):
                raise HTTPException(status_code=500, detail="onboarding form script not found")
            pf = f"/tmp/onboarding-{deal_id}-{form}.json"
            with open(pf, "w") as f:
                _json.dump(payload, f)
            r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                        text=True, timeout=120, env=_user_site_env())
            result: Dict[str, Any] = {}
            for line in reversed((r.stdout or "").strip().splitlines()):
                try:
                    result = _json.loads(line); break
                except Exception:
                    continue
            if not result.get("ok"):
                _log.error("onboarding %s produced no PDF: %s | %s", form, (r.stdout or "")[-300:], (r.stderr or "")[-300:])
                raise HTTPException(status_code=500, detail="Onboarding doc generation failed")
            # Record where the filled PDF landed so the card's Open / Download
            # buttons can serve it, and so the drafted state survives a reload.
            # The scripts write to /private/tmp, which macOS clears -- copy it
            # into the durable admin-artifacts dir first.
            import datetime as _dt
            import shutil as _shutil
            src_pdf = result.get("pdf") or ""
            kept = ""
            if src_pdf and os.path.exists(src_pdf):
                dest_dir = os.path.expanduser("~/.elevate/cache/documents/admin_artifacts/onboarding")
                os.makedirs(dest_dir, exist_ok=True)
                kept = os.path.join(dest_dir, f"{deal_id}-{form}.pdf")
                try:
                    _shutil.copy2(src_pdf, kept)
                except Exception:
                    _log.warning("could not persist onboarding %s pdf", form, exc_info=True)
                    kept = src_pdf
            try:
                from elevate_cli.data import connect as _connect
                with _connect() as conn:
                    row = conn.execute(
                        "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                    ).fetchone()
                    if row is not None:
                        raw = row["extra_toggles_json"]
                        toggles = raw if isinstance(raw, dict) else (
                            _json.loads(raw) if raw and str(raw).strip() else {})
                        docs = toggles.get("onboardingDocs")
                        if not isinstance(docs, dict):
                            docs = {}
                        docs[form] = {
                            "filePath": kept,
                            "url": result.get("url") or "",
                            "fields": saved_overrides,
                            "generatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
                        }
                        toggles["onboardingDocs"] = docs
                        conn.execute(
                            "UPDATE deals SET extra_toggles_json=? WHERE id=?",
                            (_json.dumps(toggles), deal_id),
                        )
            except Exception:
                _log.warning("could not record onboarding doc %s on deal %s", form, deal_id, exc_info=True)
            return {"ok": True, "form": form, "url": result.get("url"), "filePath": kept}
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("onboarding doc generate failed")
            raise HTTPException(status_code=500, detail=f"Onboarding doc failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/onboarding-doc/{form}")
    def get_onboarding_doc(deal_id: str, form: str, download: int = 0):
        # Serve a drafted onboarding PDF. download=0 -> inline (quick read-only
        # view in a tab). download=1 -> attachment, which opens in Preview where
        # the AcroForm fields are actually editable (browser tabs render forms
        # read-only). Mirrors the kit-doc route. Auth: Bearer header or ?token=.
        try:
            import json as _json
            from elevate_cli.data import connect

            form = (form or "").strip().lower()
            if form not in ("agency", "dorts", "pnc"):
                raise HTTPException(status_code=400, detail="Unknown onboarding form")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="deal not found")
            raw = row["extra_toggles_json"]
            toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            doc = ((toggles.get("onboardingDocs") or {}).get(form)) or {}
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="not drafted yet")
            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=os.path.basename(file_path),
                content_disposition_type="attachment" if download else "inline",
            )
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/onboarding-doc/%s failed", deal_id, form)
            raise HTTPException(status_code=500, detail=f"Onboarding doc failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/onboarding-doc/{form}/fields")
    def get_onboarding_doc_fields(deal_id: str, form: str):
        # Onboarding's twin of the kit /fields routes, so all three paperwork
        # surfaces read their fields off the same place: the document itself.
        try:
            import json as _json
            from elevate_cli.data import connect

            form = (form or "").strip().lower()
            if form not in _ONBOARDING_TEMPLATES:
                raise HTTPException(status_code=400, detail="Unknown onboarding form")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="deal not found")
            raw = row["extra_toggles_json"]
            toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            own = {k: str(v or "").strip()
                   for k, v in ((toggles.get("onboardingDocFields") or {}).get(form) or {}).items()}
            facts = _cps_deal_facts(deal_id) or {}
            buyers = [b for b in (facts.get("buyers") or []) if b]
            rows = toggles.get("onboardingBuyers") or []
            if not buyers and isinstance(rows, list):
                buyers = [str((r or {}).get("name") or "").strip() for r in rows]
                buyers = [b for b in buyers if b]
            t = lambda *ks: next((str(toggles.get(k) or "").strip() for k in ks
                                  if str(toggles.get(k) or "").strip()), "")
            phones = [str((r or {}).get("phone") or "").strip() for r in rows if isinstance(r, dict)]
            deal_side = {
                "buyer1": buyers[0] if len(buyers) > 0 else "",
                "buyer2": buyers[1] if len(buyers) > 1 else "",
                "buyer3": buyers[2] if len(buyers) > 2 else "",
                "buyerAddress": t("buyer.mailingAddress"),
                "buyerPhone": next((p for p in phones if p), "") or t("buyer.phones"),
                "termMonths": t("agencyTermMonths") or "6",
                "commission": t("agencyCommission")
                or "As per the cooperating commission offered on the MLS listing of the property purchased.",
            }
            values: Dict[str, str] = {}
            derived: List[str] = []
            for key in set(list(deal_side.keys()) + list(own.keys())):
                if own.get(key):
                    values[key] = own[key]
                    continue
                v = deal_side.get(key) or ""
                values[key] = v
                if v:
                    derived.append(key)
            defs = _template_field_defs(_ONBOARDING_TEMPLATES[form])
            _apply_checkbox_defaults(defs, own, values, derived)
            out: Dict[str, Any] = {"fields": values, "derived": sorted(derived)}
            if defs is not None:
                out["defs"] = defs
            return out
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/onboarding-doc/%s/fields failed", deal_id, form)
            raise HTTPException(status_code=500, detail=f"Onboarding fields failed: {exc}")

    @router.get("/api/admin/deals/{deal_id}/onboarding-doc/{form}/preview")
    def get_onboarding_doc_preview(deal_id: str, form: str, page: int = 1, dpi: int = 105):
        # Onboarding twin of the offer-kit preview. See _render_pdf_page_png.
        try:
            import json as _json
            from elevate_cli.data import connect

            form = (form or "").strip().lower()
            if form not in ("agency", "dorts", "pnc"):
                raise HTTPException(status_code=400, detail="Unknown onboarding form")
            with connect() as conn:
                row = conn.execute(
                    "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="deal not found")
            raw = row["extra_toggles_json"]
            toggles = raw if isinstance(raw, dict) else (_json.loads(raw) if raw and str(raw).strip() else {})
            doc = ((toggles.get("onboardingDocs") or {}).get(form)) or {}
            file_path = doc.get("filePath")
            if not file_path or not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="not drafted yet")
            png, pages = _render_pdf_page_png(file_path, max(1, int(page or 1)), int(dpi or 105))
            return Response(content=png, media_type="image/png",
                            headers={"X-Page-Count": str(pages), "Cache-Control": "no-store"})
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/deals/%s/onboarding-doc/%s/preview failed", deal_id, form)
            raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")

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
            require_admin_setup_ready_for_launch()
            import json as _json
            import subprocess as _sp
            from elevate_cli.data import connect
            from elevate_cli.data.dispatch import queue_action_run

            # Resolve + validate the requested documents BEFORE anything else.
            # A bad selection must fail loudly here, never fall through to a
            # dispatch with an empty document list.
            _OFFER_PREP = os.path.expanduser("~/skyleigh-tools/scripts/offer-prep-forms.py")
            _ALL_FORMS = {
                "agency": ("agency", os.path.expanduser("~/skyleigh-tools/scripts/buyer-agency-fill.py"), None),
                "dorts": ("dorts", _OFFER_PREP, "dorts"),
                "pnc": ("pnc", _OFFER_PREP, "pnc"),
            }
            _requested = body.forms if body else None
            if _requested is not None and len(_requested) == 0:
                raise HTTPException(status_code=400, detail="Pick at least one document to send.")
            _wanted = [str(f).strip().lower() for f in (_requested if _requested else ["dorts", "pnc"])]
            _unknown = [f for f in _wanted if f not in _ALL_FORMS]
            if _unknown:
                raise HTTPException(status_code=400, detail=f"Unknown document(s): {', '.join(_unknown)}")
            _forms_seq = [_ALL_FORMS[f] for f in _wanted]
            if not _forms_seq:
                raise HTTPException(status_code=400, detail="Pick at least one document to send.")

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
            # Only the documents the operator ticked on the card go in the
            # envelope. Bound OUTSIDE the try: the fallback handler below catches
            # everything, so an early failure must not leave this unbound when the
            # payload is built.
            forms_seq = list(_forms_seq)
            try:
                for key, script, formarg in forms_seq:
                    if not os.path.exists(script):
                        continue
                    pl: Dict[str, Any] = {"address": address, "dealId": deal_id, "dryRun": True, "deal": facts}
                    if formarg:
                        pl["form"] = formarg
                    pf = f"/tmp/onboarding-sign-{deal_id}-{key}.json"
                    with open(pf, "w") as f:
                        _json.dump(pl, f)
                    r = _sp.run(["/usr/bin/python3", script, pf], capture_output=True,
                                text=True, timeout=120, env=_user_site_env())
                    res: Dict[str, Any] = {}
                    for line in reversed((r.stdout or "").strip().splitlines()):
                        try:
                            res = _json.loads(line); break
                        except Exception:
                            continue
                    if res.get("ok") and res.get("pdf") and os.path.exists(res["pdf"]):
                        prefilled.append({"form": key, "pdf": res["pdf"]})
                if prefilled and len(prefilled) == len(forms_seq):
                    pv_dir = os.path.expanduser("~/.elevate/uploads/onboarding-previews")
                    os.makedirs(pv_dir, exist_ok=True)
                    preview_path = f"{pv_dir}/{deal_id}-onboarding-preview.pdf"
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
                    mr = _sp.run(["/usr/bin/python3", "-c", merge_src, preview_path] + [d["pdf"] for d in prefilled],
                                 capture_output=True, text=True, timeout=60,
                                 env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"})
                    if mr.returncode == 0 and os.path.exists(preview_path):
                        preview_pdf = preview_path
            except Exception:
                _log.exception("onboarding draft prep failed; falling back to agent dispatch")
                prefilled = []
                preview_pdf = None

            buyers = [b for b in (facts.get("buyers") or []) if b]
            who = ", ".join(buyers) or "the buyer(s)"
            _doc_list = " + ".join(k.upper() if k != "agency" else "Buyer's Agency"
                                   for k, _s, _a in forms_seq) or "the documents"
            payload = {
                "purpose": "buyer-onboarding-signatures",
                "documents": [_FORM_LABELS.get(k, k) for k, _s, _a in forms_seq],
                "prefilledDocs": prefilled,
                "previewPdf": preview_pdf or "",
                "note": (
                    "The onboarding documents listed above are ALREADY filled (local paths in "
                    "prefilledDocs). After the user approves, upload exactly those PDFs to the "
                    "configured signing provider and send them to the buyer(s) in ONE envelope. "
                    "Do not re-fill, regenerate, or add any document that is not in this list."
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
                            f"{_doc_list} drafted and filled for {who}. "
                            "Open the Preview to review, then approve to send for signature by DigiSign."
                        ),
                        "requiredFields": [
                            f"Approve sending the filled {_doc_list} to {who} for signature by DigiSign? yes/no"
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

    class _SendCheckBody(BaseModel):
        # Which surface, and the exact documents the send sheet is holding.
        side: str = "buyer"
        docIds: List[str] = []

    @router.post("/api/admin/deals/{deal_id}/kit-send-check")
    def post_admin_deal_kit_send_check(deal_id: str, body: _SendCheckBody):
        """Disclosures in this envelope that would leave with nothing ticked.

        On a BCFSA disclosure the checkbox IS the disclosure — a DORTS with
        neither "representing you" nor "not representing you" ticked discloses
        nothing, and a Disclosure of Interest in Trade with no Part A choice
        says the licensee has an interest without saying which kind. Both look
        finished on the card: every text field is full, the PDF renders, the
        row says "Drafted".

        Read-only and advisory. It reports; the send sheet warns; Skyleigh still
        decides. Blocking the send would be wrong — there are legitimate reasons
        to send a form the client ticks themselves.

        Takes the doc ids from the send sheet rather than re-deriving what is
        sendable, so the answer is about the envelope actually in front of her.
        """
        try:
            import json as _json
            from elevate_cli.data import connect

            side = (body.side or "buyer").strip().lower()
            wanted = [str(d) for d in (body.docIds or []) if str(d).strip()]
            if not wanted:
                return {"documents": []}

            with connect() as conn:
                if side == "listing":
                    toggles = _listing_toggles(conn, deal_id)
                else:
                    row = conn.execute(
                        "SELECT extra_toggles_json FROM deals WHERE id=?", (deal_id,)
                    ).fetchone()
                    if row is None:
                        raise HTTPException(status_code=404, detail="deal not found")
                    raw = row["extra_toggles_json"]
                    toggles = raw if isinstance(raw, dict) else (
                        _json.loads(raw) if raw and str(raw).strip() else {})

            # (template path, saved field values, display name) per document id.
            def resolve(doc_id: str):
                if side == "listing":
                    docs = ((toggles.get("listingKit") or {}).get("documents") or [])
                    doc = next((d for d in docs if d.get("id") == doc_id), {}) or {}
                    tpl = ""
                    if doc_id == "mlc":
                        tpl = f"{_FORMS_DIR}/mlc-fillable-template.pdf"
                    elif doc_id in LISTING_DISCLOSURES:
                        tpl = LISTING_DISCLOSURES[doc_id]
                    elif doc_id in PDS_FIXED:
                        tpl = PDS_FIXED[doc_id]
                    elif doc_id == "pds":
                        sub, _raw, _warn = _pds_subtype(toggles)
                        tpl = PDS_BY_SUBTYPE.get(sub, "") if sub else ""
                    return tpl, (doc.get("fields") or {}), (doc.get("name") or doc_id)
                if side == "onboarding":
                    form = doc_id.strip().lower()
                    names = {"agency": "Buyer Agency Agreement",
                             "dorts": "Disclosure of Representation in Trading Services",
                             "pnc": "Privacy Notice and Consent"}
                    # Same two layers the panel reads: what the last draft used,
                    # with any edit saved since on top.
                    fields = dict(((toggles.get("onboardingDocs") or {}).get(form) or {}).get("fields") or {})
                    fields.update((toggles.get("onboardingDocFields") or {}).get(form) or {})
                    return _ONBOARDING_TEMPLATES.get(form, ""), fields, names.get(form, form)
                docs = ((toggles.get("offerKit") or {}).get("documents") or [])
                doc = next((d for d in docs if d.get("id") == doc_id), {}) or {}
                umbrella = str(toggles.get("cpsUmbrella") or "residential").strip().lower()
                tpl_id = "cps-mobile" if (doc_id == "cps-residential" and umbrella == "mobile") else doc_id
                return (_TEMPLATES.get(tpl_id, ""), (doc.get("fields") or {}),
                        (doc.get("name") or doc_id))

            out: List[Dict[str, Any]] = []
            for doc_id in wanted:
                tpl, fields, name = resolve(doc_id)
                defs = _template_field_defs(tpl) if tpl else None
                if not defs:
                    continue
                ticked = {k: str(v or "").strip() for k, v in (fields or {}).items()}
                # Same layering the card shows: an operator tick, else whatever
                # the blank template already carries. Without this the check
                # would flag a box the PDF has marked. An explicit untick (key
                # present, value "") is an answer and keeps its own emptiness.
                for d in defs:
                    if (d.get("type") == "checkbox" and d.get("default")
                            and d["key"] not in (fields or {}) and not ticked.get(d["key"])):
                        ticked[d["key"]] = str(d["default"])
                gaps = []
                for d in defs:
                    if d.get("type") != "checkbox" or ticked.get(d["key"]):
                        continue
                    need = bool(d.get("mustTick"))
                    dep = d.get("mustTickWhen") or {}
                    if not need and dep.get("key"):
                        need = ticked.get(dep["key"], "") in (dep.get("in") or [])
                    if need:
                        gaps.append({"label": d.get("label") or d["key"], "page": d.get("page")})
                if gaps:
                    out.append({"id": doc_id, "name": name, "groups": gaps})
            return {"documents": out}
        except HTTPException:
            raise
        except Exception as exc:
            # Advisory only: never let this break the send sheet.
            _log.exception("POST /api/admin/deals/%s/kit-send-check failed", deal_id)
            return {"documents": [], "error": str(exc)}

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
            stale: List[str] = []
            for d in docs:
                if want and d.get("id") not in want:
                    continue
                fp = d.get("filePath")
                if not (fp and os.path.exists(fp)):
                    continue
                if _doc_is_stale(d):
                    stale.append(d.get("name") or d.get("id"))
                    continue
                chosen.append({"form": d.get("id"), "name": d.get("name") or d.get("id"), "pdf": fp})
            if stale:
                raise HTTPException(
                    status_code=400,
                    detail=f"Redraft before sending — edited since last drafted: {', '.join(stale)}",
                )
            if not chosen:
                raise HTTPException(status_code=400, detail="No drafted documents selected. Draft them first, then send for signatures.")

            preview_pdf = None
            try:
                pv_dir = os.path.expanduser("~/.elevate/uploads/offer-kit-sign-previews")
                os.makedirs(pv_dir, exist_ok=True)
                preview_path = f"{pv_dir}/{deal_id}-offer-kit-sign-preview.pdf"
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
                mr = _sp.run(["/usr/bin/python3", "-c", merge_src, preview_path] + [c["pdf"] for c in chosen],
                             capture_output=True, text=True, timeout=60,
                             env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/Users/admin"})
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
    _CMA_RUNNER = os.path.expanduser("~/skyleigh-tools/scripts/cma-phase-runner.py")

    def _cma_addr(deal_id):
        facts = _cps_deal_facts(deal_id)
        return str(facts.get("listingAddress") or "").split(",")[0].strip()

    def _cma_call(addr, args, timeout=60):
        import json as _json
        import subprocess as _sp
        r = _sp.run(["/usr/bin/python3", _CMA_RUNNER, "--address", addr] + args,
                    capture_output=True, text=True, timeout=timeout, env=_user_site_env())
        for line in reversed((r.stdout or "").strip().splitlines()):
            try:
                return _json.loads(line)
            except Exception:
                continue
        _log.warning("cma-runner no JSON (%s): %s | %s", args, (r.stdout or "")[-200:], (r.stderr or "")[-200:])
        return {}

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
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--phase", body.phase],
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
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr,
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
            import re as _re, subprocess as _sp
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
            _sp.run(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--reset-downstream"],
                    env=env, capture_output=True, timeout=30)
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--phase", "collect"],
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
        base = os.path.join(os.path.dirname(_CMA_RUNNER), "screenshots", "comp-photos")
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
            _sp.Popen(["/usr/bin/python3", _CMA_RUNNER, "--address", addr, "--reprice",
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
            import os as _os, subprocess as _sp
            script = _os.path.join(_os.path.dirname(_CMA_RUNNER), "capture-prospecting.sh")
            _sp.Popen(["/bin/bash", script, body.mls, addr],
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
