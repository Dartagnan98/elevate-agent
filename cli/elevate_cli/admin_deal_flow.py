"""Small Admin deal-flow resolver for real-estate admin packages.

This is intentionally not a generic rules engine.  It gives the active
deployment package one place to define stage names, checklist gates, forms,
condition add-ons, and automation defaults, then computes a plain API shape
the dashboard and skills can consume.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping


DEFAULT_PACKAGE_KEY = "generic.real-estate"
BC_PACKAGE_KEY = "ca.bc"
CANADIAN_PROVINCE_LABELS = {
    "ab": "Alberta",
    "bc": "British Columbia",
    "mb": "Manitoba",
    "nb": "New Brunswick",
    "nl": "Newfoundland and Labrador",
    "ns": "Nova Scotia",
    "nt": "Northwest Territories",
    "nu": "Nunavut",
    "on": "Ontario",
    "pe": "Prince Edward Island",
    "pei": "Prince Edward Island",
    "qc": "Quebec",
    "sk": "Saskatchewan",
    "yt": "Yukon",
    "yk": "Yukon",
}


_WORKFLOW_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _workflow_key(label: str) -> str:
    text = label.strip().lower().replace("✓", "")
    text = text.replace("%", " pct ")
    text = _WORKFLOW_NON_ALNUM_RE.sub("_", text).strip("_")
    return f"workflow_{text or 'field'}"


def _wf(label: str, source_label: str | None = None) -> tuple[str, str]:
    return (_workflow_key(source_label or label), label)


def _stage(title: str, subtitle: str, items: list[tuple[str, str]], *, fields: list[tuple[str, str]] | None = None, docs: list[tuple[str, str]] | None = None, forms: list[tuple[str, str]] | None = None, triggers: list[tuple[str, str, str]] | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "subtitle": subtitle,
        "checklist": [{"id": item_id, "label": label, "required": True} for item_id, label in items],
        "requiredFields": [{"field": field, "label": label} for field, label in (fields or [])],
        "requiredDocs": [{"kind": kind, "label": label} for kind, label in (docs or [])],
        "forms": [{"code": code, "name": name} for code, name in (forms or [])],
        "automationTriggers": [{"id": trigger_id, "label": label, "skill": skill} for trigger_id, label, skill in (triggers or [])],
    }


_BACKGROUND_AUTOMATIONS: list[dict[str, Any]] = [
    {
        "id": "gmail-doc-router",
        "name": "Gmail Doc Router",
        "skill": "gmail-doc-router",
        "kind": "cron",
        "affectsStages": [2, 6, 7, 8],
        "description": "Routes inbound Gmail attachments to the right deal and Drive folder.",
    },
    {
        "id": "seller-update",
        "name": "Seller Update",
        "skill": "seller-update",
        "kind": "cron",
        "affectsStages": [6],
        "description": "Pulls ShowingTime feedback and creates Gmail seller-update drafts.",
    },
]


_BC: dict[str, Any] = {
    "packageKey": BC_PACKAGE_KEY,
    "country": "CA",
    "province": "BC",
    "localOverrides": {
        "provinceLabel": "British Columbia",
        "marketLabel": "BC",
        "defaultCurrency": "CAD",
        "preferredShowingSource": "Configured showing source",
    },
    "backgroundAutomations": deepcopy(_BACKGROUND_AUTOMATIONS),
    "listing": {
        "stages": [
            _stage(
                "Pre-CMA",
                "Dashboard setup + contact verification",
                [
                    ("pre_cma_dashboard_setup", "Pre-CMA dashboard setup complete"),
                    ("lofty_contact_verified", "Lofty contact verified / created"),
                    ("pre_cma_handoff", "Client/property notes saved for CMA"),
                ],
                fields=[
                    _wf("Client 1 name", "Client 1 Name"),
                    _wf("Client 1 email", "Client 1 Email"),
                    _wf("Lead source", "Lead Source"),
                    _wf("CMA date requested", "CMA Date Requested"),
                ],
                triggers=[
                    ("pre-cma-dashboard-setup", "Set up Pre-CMA dashboard", "pre-cma-dashboard-setup"),
                    ("lofty-crm-client-contacts", "Verify Lofty contact", "lofty-crm-client-contacts"),
                ],
            ),
            _stage(
                "CMA / Evaluation",
                "PDF + pricing story",
                [
                    ("cma_pdf_ready", "CMA PDF / evaluation ready"),
                    ("pricing_story_approved", "Pricing story approved"),
                    ("client_yes_to_listing", "Client said yes to listing"),
                ],
                fields=[
                    _wf("CMA date requested", "CMA Date Requested"),
                    ("listPrice", "Recommended list price"),
                ],
                docs=[("cma_report", "CMA report")],
                triggers=[
                    ("cma-complete", "Run CMA skill", "cma"),
                    ("seller-package", "Prepare seller evaluation package", "seller-package"),
                ],
            ),
            _stage(
                "Listing Intake",
                "Trigger MLC + missing fields",
                [
                    ("mlc_intake_started", "MLC intake triggered"),
                    ("listing_missing_fields", "Missing listing fields surfaced"),
                    ("listing_docs_approval", "Listing docs/signature placements ready for approval"),
                ],
                fields=[
                    ("listingAddress", "Property address"),
                    ("signingAuthority", "Signing authority"),
                    ("listPrice", "List price"),
                    ("commissionPct", "Commission rate"),
                    ("listingDate", "Planned go-live date"),
                    ("listingType", "Listing type"),
                ],
                docs=[("title_search", "Title search"), ("signed_envelope", "Signed listing envelope")],
                forms=[("MLC", "Multiple Listing Contract"), ("FINTRAC", "FINTRAC identity form"), ("PDS", "Property Disclosure Statement")],
                triggers=[
                    ("mlc-intake", "Collect listing info for MLC", "mlc"),
                    ("deal-matcher-intake", "Match inbound docs to the deal", "deal-matcher"),
                    ("signing-package-sync", "Sync signing status", "signing-package"),
                ],
            ),
            _stage(
                "SkySlope & Matrix Prep",
                "Compliance file + incomplete MLS draft",
                [
                    ("signed_listing_docs_saved", "Signed listing docs saved to Drive"),
                    ("skyslope_file_created", "SkySlope file created / synced"),
                    ("matrix_incomplete_listing_prepped", "Matrix/Xposure incomplete listing prepped"),
                    ("matrix_missing_fields_surfaced", "Matrix missing fields surfaced"),
                ],
                fields=[
                    _wf("SkySlope transaction URL", "SkySlope Transaction URL"),
                    ("mlsNumber", "MLS number if already assigned"),
                ],
                docs=[("signed_envelope", "Signed listing envelope"), ("matrix_incomplete_draft", "Matrix/Xposure incomplete draft")],
                triggers=[
                    ("skyslope-doc-check", "Create/sync SkySlope opening docs", "skyslope-sync"),
                    ("matrix-incomplete", "Prepare Matrix/Xposure incomplete listing", "matrix-incomplete-listing"),
                ],
            ),
            _stage(
                "Marketing Go",
                "Coming-soon + launch assets",
                [
                    ("marketing_go_started", "Marketing Go started after SkySlope/Matrix prep"),
                    ("photographer_drive_link_received", "Photographer Google Drive/photo link received or requested"),
                    ("marketing_go_questions_answered", "Marketing Go questions answered / blockers surfaced"),
                    ("photo_cleanup_complete", "Photo cleanup complete"),
                    ("cleaned_photos_saved_to_drive", "Cleaned photos saved to listing Google Drive folder"),
                    ("best_99_matrix_photos_selected", "Best 99 Matrix photos selected if photographer sent more than 99"),
                    ("matrix_photos_uploaded", "Photos uploaded to Matrix/Xposure"),
                    ("matrix_listing_finished_with_photos", "Matrix listing finished with final photos"),
                    ("coming_soon_assets_ready", "Coming-soon assets ready"),
                    ("landing_page_ready", "Landing page ready"),
                    ("launch_copy_social_email_ready", "Launch copy, social posts, and email assets ready"),
                    ("marketing_package_ready_for_approval", "Marketing package ready for approval"),
                ],
                fields=[
                    _wf("Photo shoot date", "Photo Shoot Date"),
                    _wf("AI: Garage / Carport"),
                    _wf("AI: Suite Detected"),
                    _wf("AI: AC / Heat Pump"),
                    _wf("AI: Appliances Listed"),
                    _wf("AI: Flooring Types"),
                ],
                docs=[("listing_photos", "Listing photos")],
                triggers=[
                    ("photo-cleanup", "Prepare listing-ready photos", "photo-cleanup"),
                    ("marketing-go-package", "Prepare Marketing Go launch package", "marketing"),
                    ("matrix-final-photos", "Upload final photos to Matrix/Xposure", "matrix-incomplete-listing"),
                ],
            ),
            _stage(
                "Listing Live / Marketing",
                "MLS live + seller updates",
                [
                    _wf("Just listed blast sent", "Just Listed Blast Sent"),
                    _wf("Social posts published", "Social Posts Published"),
                    _wf("Flodesk mailout sent", "Flodesk Mailout Sent"),
                    _wf("Lofty text blast sent", "Lofty Text Blast Sent"),
                    _wf("Stage 5 complete", "Stage 5 Complete ✓"),
                ],
                fields=[
                    ("mlsNumber", "MLS number"),
                    ("listingPublishedAt", "Live date"),
                    _wf("Order sign up date", "Order Sign Up Date"),
                    _wf("Coming soon posts date", "Coming Soon Posts Date"),
                ],
                triggers=[("marketing-live", "Run listing-live marketing", "marketing")],
            ),
            _stage(
                "Accepted Offer",
                "Contract review + dates",
                [
                    _wf("Within-24hrs contract reviewed", "Within-24hrs Contract Reviewed ✓"),
                    _wf("Accepted-offer checklist email sent", "Email Buyer: Accepted Offer Checklist Sent"),
                    _wf("FINTRAC drivers/occupation/employer captured", "FINTRAC Drivers/Occupation/Employer Captured ✓"),
                    _wf("Calendar dates added", "Calendar Dates Added ✓"),
                    _wf("Moving checklist sent", "Moving Checklist Sent"),
                    _wf("Stage 6 complete", "Stage 6 Complete ✓"),
                ],
                fields=[
                    ("offerDate", "Offer received date"),
                    ("offerAcceptedAt", "Accepted offer date"),
                    _wf("Title charges ordered date", "Title Charges Ordered Date"),
                    ("depositInTrustAt", "Deposit ROF received date"),
                    ("completionDate", "Completion date"),
                ],
                docs=[("offer_pdf", "Offer PDF")],
                triggers=[("offer-review", "Review accepted-offer package", "offer-review")],
            ),
            _stage(
                "Condition Removal",
                "Conditions + lawyer package",
                [
                    _wf("Condition removal / waiver sent", "Subject Removal Form Sent"),
                    _wf("Title charges verified", "Title Charges Verified"),
                    _wf("BIR + PDS received", "BIR + PDS Received"),
                    _wf("Lawyer info requested", "Lawyer Info Requested"),
                    _wf("Conditions removed / waived", "Stage 7 Complete ✓"),
                ],
                fields=[
                    ("subjectRemovalDate", "Subject removal date"),
                    _wf("Order sold rider date", "Order Sold Rider Date"),
                ],
                docs=[("subject_removal_form", "Condition removal / waiver"), ("deposit_receipt", "Deposit receipt")],
                triggers=[
                    ("subject-removal", "Run condition-removal admin check", "subject-removal"),
                    ("subject-removal-docs", "Sync condition-removal signing", "signing-package"),
                ],
            ),
            _stage(
                "Closed",
                "Archive + nurture",
                [
                    _wf("Commission submitted", "Commission Submitted"),
                    _wf("SkySlope deal closed", "SkySlope Deal Closed"),
                    _wf("Sold update sent", "Sold Update Sent"),
                    _wf("Closing gift sent", "Closing Gift Sent"),
                    _wf("Review requested", "Review Requested"),
                    _wf("Stage 9 complete", "Stage 9 Complete ✓"),
                ],
                fields=[("anniversaryDate", "Anniversary date")],
                triggers=[
                    ("skyslope-closeout", "Verify SkySlope closeout", "skyslope-sync"),
                    ("sold-marketing", "Create sold update and nurture handoff", "marketing"),
                ],
            ),
        ],
    },
    "buyer": {
        "stages": [
            _stage("Offer Prep", "Comps + CPS", [("lender-paperwork", "Lender paperwork sent"), ("accepted-offer-checklist", "Accepted-offer checklist run"), ("doc-list", "Doc list built")], docs=[("cps_draft", "CPS draft")]),
            _stage("Accepted", "Lender + docs", [("inspection-booked", "Inspection booked"), ("insurance-deadline", "Insurance deadline tracked")], fields=[("subjectRemovalDate", "Subject removal date")]),
            _stage("Conditions", "Inspection + strata", [("deposit-due", "Deposit due date tracked"), ("lawyer-info", "Lawyer / conveyancer info captured")], fields=[("depositDueDate", "Deposit due date")]),
            _stage("Subjects Off", "Deposit + dates", [("subjects-removed", "All subjects removed"), ("deposit-received", "Deposit received"), ("completion-locked", "Completion + possession dates locked")], fields=[("completionDate", "Completion date"), ("possessionDate", "Possession date")]),
        ],
    },
}


def _generic_package() -> dict[str, Any]:
    package = deepcopy(_BC)
    package.update(
        {
            "packageKey": DEFAULT_PACKAGE_KEY,
            "country": "",
            "province": "",
            "localOverrides": {
                "mlsBoard": "",
                "marketLabel": "Configured market",
                "defaultCurrency": "CAD",
                "preferredShowingSource": "Configured showing source",
            },
        }
    )
    return package


_PACKAGES: dict[str, dict[str, Any]] = {
    DEFAULT_PACKAGE_KEY: _generic_package(),
    BC_PACKAGE_KEY: _BC,
}


# BC is the only Canadian province that calls buyer/seller conditions
# "subjects" ("subject removal", "subjects off"). Every other province uses
# "conditions" ("condition removal/waiver"). The reference flow (_BC) is written
# in BC terminology, so when it's reused for another province we rewrite the
# visible stage names + checklist labels. Field KEYS (e.g. subjectRemovalDate)
# and checklist IDs are deliberately left untouched so the gate logic, data
# binding, and per-deal document overlay keep working. Ordered specific->generic
# so multi-word phrases match before the bare-word fallback.
_CONDITION_TERM_SUBS: list[tuple[Any, str]] = [
    (re.compile(r"\bSubjects Off\b"), "Conditions Removed"),
    (re.compile(r"\bSubject Removal\b"), "Condition Removal"),
    (re.compile(r"\bsubjects off\b"), "conditions removed"),
    (re.compile(r"\bsubject removal\b"), "condition removal"),
    (re.compile(r"\bSubjects\b"), "Conditions"),
    (re.compile(r"\bSubject\b"), "Condition"),
    (re.compile(r"\bsubjects\b"), "conditions"),
    (re.compile(r"\bsubject\b"), "condition"),
]


def _reterm_condition(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _CONDITION_TERM_SUBS:
        text = pattern.sub(repl, text)
    return text


def _apply_condition_terminology(package: dict[str, Any]) -> None:
    """Rewrite BC 'subject' terminology to 'condition' on display text only."""
    for side in ("listing", "buyer"):
        side_cfg = package.get(side)
        if not isinstance(side_cfg, dict):
            continue
        for stage in side_cfg.get("stages", []) or []:
            if not isinstance(stage, dict):
                continue
            stage["title"] = _reterm_condition(stage.get("title", ""))
            stage["subtitle"] = _reterm_condition(stage.get("subtitle", ""))
            for item in stage.get("checklist", []) or []:
                if isinstance(item, dict):
                    item["label"] = _reterm_condition(item.get("label", ""))
            for field in stage.get("requiredFields", []) or []:
                if isinstance(field, dict):
                    field["label"] = _reterm_condition(field.get("label", ""))
            for doc in stage.get("requiredDocs", []) or []:
                if isinstance(doc, dict):
                    doc["label"] = _reterm_condition(doc.get("label", ""))


def _canadian_province_package(province_slug: str) -> dict[str, Any]:
    province = province_slug.upper()
    package = deepcopy(_BC)
    package.update(
        {
            "packageKey": f"ca.{province_slug}",
            "country": "CA",
            "province": province,
            "localOverrides": {
                **package["localOverrides"],
                "provinceLabel": CANADIAN_PROVINCE_LABELS.get(province_slug, province),
                "marketLabel": province,
                "defaultCurrency": "CAD",
                "preferredShowingSource": "Configured showing source",
            },
        }
    )
    # Non-BC provinces use "condition" terminology, not BC's "subjects".
    _apply_condition_terminology(package)
    return package


def _package_for_key(package_key: str) -> dict[str, Any]:
    if package_key in _PACKAGES:
        return _PACKAGES[package_key]
    parts = package_key.split(".")
    if len(parts) == 2 and parts[0] == "ca" and parts[1] in CANADIAN_PROVINCE_LABELS:
        return _canadian_province_package(parts[1])
    return _PACKAGES[DEFAULT_PACKAGE_KEY]


_CONDITION_ADDITIONS: dict[str, list[dict[str, Any]]] = {
    "propertySubtype:strata": [
        {"stage": 7, "id": "strata-docs-review", "label": "Strata documents reviewed", "docKind": "strata_docs"}
    ],
    "property_subtype:strata": [
        {"stage": 7, "id": "strata-docs-review", "label": "Strata documents reviewed", "docKind": "strata_docs"}
    ],
    "tenanted:true": [
        {"stage": 2, "id": "tenancy-docs", "label": "Tenancy docs / notice requirements checked", "docKind": "tenancy_docs"}
    ],
    "multipleOffers:true": [
        {"stage": 7, "id": "offer-matrix", "label": "Multiple-offer comparison matrix prepared", "docKind": "offer_matrix"}
    ],
    "multiple_offers:true": [
        {"stage": 7, "id": "offer-matrix", "label": "Multiple-offer comparison matrix prepared", "docKind": "offer_matrix"}
    ],
    "poaSigning:true": [
        {"stage": 2, "id": "poa-review", "label": "POA authority reviewed", "docKind": "poa_authority"}
    ],
    "poa_signing:true": [
        {"stage": 2, "id": "poa-review", "label": "POA authority reviewed", "docKind": "poa_authority"}
    ],
}


def _slug(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


def _known_or_default(package_key: str) -> str:
    if package_key in _PACKAGES:
        return package_key
    parts = package_key.split(".")
    if len(parts) == 2 and parts[0] == "ca" and parts[1] in CANADIAN_PROVINCE_LABELS:
        return package_key
    if len(parts) >= 2:
        province_key = ".".join(parts[:2])
        if province_key in _PACKAGES:
            return province_key
    return DEFAULT_PACKAGE_KEY


def package_key_from_jurisdiction(
    *,
    country: Any = None,
    province: Any = None,
    package_key: Any = None,
) -> str:
    explicit = _slug(package_key)
    if explicit:
        return _known_or_default(explicit)
    province_slug = _slug(province)
    if not province_slug:
        return DEFAULT_PACKAGE_KEY
    country_slug = _slug(country) or "ca"
    candidate = ".".join(part for part in (country_slug, province_slug) if part)
    return _known_or_default(candidate)


def package_key_from_deal(deal: Mapping[str, Any]) -> str:
    extra = deal.get("extraToggles") if isinstance(deal.get("extraToggles"), Mapping) else {}
    explicit = deal.get("packageKey") or deal.get("package_key") or extra.get("packageKey") or extra.get("package_key")
    return package_key_from_jurisdiction(
        country=deal.get("country"),
        province=deal.get("province"),
        package_key=explicit,
    )


def resolve_admin_deal_flow(
    *,
    package_key: str,
    side: str,
    stage: int,
    conditions: Mapping[str, Any] | None = None,
    condition_docs: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve package rules for the current side/stage."""
    resolved_key = _slug(package_key) or DEFAULT_PACKAGE_KEY
    package = _package_for_key(resolved_key)
    side_key = side if side in {"listing", "buyer"} else "listing"
    stages = package[side_key]["stages"]
    last_stage = len(stages) - 1
    stage_index = min(last_stage, max(0, int(stage)))
    current = stages[stage_index]
    additions = _condition_checklist_additions(
        conditions or {},
        stage_index,
        condition_docs=condition_docs,
    )
    checklist = [*current["checklist"], *additions]
    next_stage = stage_index + 1 if stage_index < last_stage else None
    next_stage_name = stages[next_stage]["title"] if next_stage is not None else None
    return {
        "packageKey": package["packageKey"],
        "side": side_key,
        "stage": stage_index,
        "stageName": current["title"],
        "stageSubtitle": current["subtitle"],
        "nextStage": next_stage,
        "nextStageName": next_stage_name,
        "checklistItems": checklist,
        "requiredFields": current["requiredFields"],
        "requiredForms": current["forms"],
        "requiredDocs": [
            *current["requiredDocs"],
            *[
                {"kind": item["docKind"], "label": item["label"]}
                for item in additions
                if item.get("docKind")
            ],
        ],
        "automationTriggers": current["automationTriggers"],
        "backgroundAutomations": package.get("backgroundAutomations", []),
        "localOverrides": package["localOverrides"],
    }


def resolve_deal_phase(
    *,
    deal: Mapping[str, Any],
    checklist: Mapping[str, Any] | None,
    attachments: list[Mapping[str, Any]] | None,
    prior_runs: list[Mapping[str, Any]] | None,
    conditions: Mapping[str, Any] | None = None,
    condition_docs: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return resolved package rules plus gate state for the deal's phase."""
    package_key = package_key_from_deal(deal)
    flow = resolve_admin_deal_flow(
        package_key=package_key,
        side=str(deal.get("side") or "listing"),
        stage=int(deal.get("currentStage") or 0),
        conditions=conditions,
        condition_docs=condition_docs,
    )
    done = checklist or {}
    attachment_kinds = {str(item.get("kind") or "") for item in (attachments or [])}
    missing_checklist = [
        item for item in flow["checklistItems"]
        if item.get("required") and done.get(item["id"]) is not True
    ]
    missing_fields = [
        item for item in flow["requiredFields"]
        if not _present(_deal_field_value(deal, done, str(item["field"])))
    ]
    missing_docs = [
        item for item in flow["requiredDocs"]
        if item["kind"] not in attachment_kinds
    ]
    blocking_runs = [
        _run_brief(run) for run in (prior_runs or [])
        if run.get("status") in {"queued", "running", "waiting_human", "waiting_external"}
        and _run_stage(run) == flow["stage"]
    ]
    can_advance = (
        flow["nextStage"] is not None
        and not missing_checklist
        and not missing_fields
        and not missing_docs
        and not blocking_runs
    )
    flow["gate"] = {
        "stage": flow["stage"],
        "stageName": flow["stageName"],
        "nextStage": flow["nextStage"],
        "nextStageName": flow["nextStageName"],
        "canAdvance": can_advance,
        "completedChecklist": len(flow["checklistItems"]) - len(missing_checklist),
        "totalChecklist": len(flow["checklistItems"]),
        "missingChecklist": missing_checklist,
        "missingFields": missing_fields,
        "missingDocs": missing_docs,
        "blockingRuns": blocking_runs,
    }
    return flow


def _condition_checklist_additions(
    conditions: Mapping[str, Any],
    stage: int,
    *,
    condition_docs: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    additions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in condition_docs or []:
        doc_stage = doc.get("stage")
        if doc_stage is not None and int(doc_stage) != stage:
            continue
        doc_kind = str(doc.get("docCode") or doc.get("doc_code") or "").strip()
        if not doc_kind or doc_kind in seen:
            continue
        seen.add(doc_kind)
        label = str(doc.get("docName") or doc.get("doc_name") or doc_kind)
        additions.append(
            {
                "id": f"{doc_kind}-review",
                "label": label,
                "required": True,
                "docKind": doc_kind,
                "source": "sqlite:conditional_docs",
            }
        )
    for key, value in conditions.items():
        normalized = f"{key}:{str(value).lower() if isinstance(value, bool) else value}"
        for item in _CONDITION_ADDITIONS.get(normalized, []):
            if item.get("docKind") in seen:
                continue
            seen.add(str(item.get("docKind") or item["id"]))
            if int(item["stage"]) == stage:
                additions.append({"id": item["id"], "label": item["label"], "required": True, "docKind": item.get("docKind")})
    return additions


def _present(value: Any) -> bool:
    if value is None:
        return False
    if value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _deal_field_value(deal: Mapping[str, Any], checklist: Mapping[str, Any], field: str) -> Any:
    if field in deal:
        return deal.get(field)
    if field in checklist:
        return checklist.get(field)
    extra = deal.get("extraToggles") if isinstance(deal.get("extraToggles"), Mapping) else {}
    if field in extra:
        return extra.get(field)
    return None


def _run_stage(run: Mapping[str, Any]) -> int | None:
    payload = run.get("payload")
    if not isinstance(payload, Mapping):
        return None
    stage = payload.get("toStage", payload.get("currentStage"))
    try:
        return int(stage) if stage is not None else None
    except (TypeError, ValueError):
        return None


def _run_brief(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "label": run.get("registryName") or run.get("skill") or "Admin run",
        "status": run.get("status"),
        "updatedAt": run.get("updatedAt"),
    }
