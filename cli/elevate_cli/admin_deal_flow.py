"""Small Admin deal-flow resolver for the active real-estate package.

This is intentionally not a generic rules engine.  It gives the active
deployment package one place to define stage names, checklist gates, forms,
condition add-ons, and automation defaults, then computes a plain API shape
the dashboard and skills can consume.
"""

from __future__ import annotations

from typing import Any, Mapping


DEFAULT_PACKAGE_KEY = "ca.bc.aoir.kamloops"


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


_KAMLOOPS: dict[str, Any] = {
    "packageKey": DEFAULT_PACKAGE_KEY,
    "country": "CA",
    "province": "BC",
    "board": "AOIR",
    "market": "Kamloops",
    "localOverrides": {
        "mlsBoard": "AOIR",
        "marketLabel": "Kamloops + Interior BC",
        "defaultCurrency": "CAD",
        "preferredShowingSource": "ShowingTime",
    },
    "listing": {
        "stages": [
            _stage(
                "CMA",
                "Pricing call",
                [
                    ("draft-cma-followup", "Draft CMA follow-up message"),
                    ("pricing-recap", "Send pricing recap to seller"),
                    ("missing-info-list", "Identify info needed before listing paperwork"),
                ],
                docs=[("cma_report", "CMA report")],
                triggers=[("cma-complete", "Run CMA skill", "cma")],
            ),
            _stage(
                "Listing Intake",
                "Names + dates",
                [
                    ("intake-legal-names", "Collect legal names + address"),
                    ("intake-price-commission", "Confirm listing price + commission + dates"),
                    ("intake-included-excluded", "Document included/excluded items + possession"),
                ],
                fields=[
                    ("listingAddress", "Listing address"),
                    ("signingAuthority", "Signing authority"),
                    ("listPrice", "List price"),
                ],
            ),
            _stage(
                "Paperwork",
                "Title + forms",
                [
                    ("pull-title", "Pull title"),
                    ("organize-photos", "Organize photos / floorplan / video schedule"),
                ],
                docs=[("title_search", "Title search")],
            ),
            _stage(
                "Pre-Launch",
                "MLC + signing",
                [
                    ("fill-mlc", "Fill MLC + required forms"),
                    ("digisign-send", "Send DigiSign envelope"),
                    ("track-signatures", "Confirm all signatures received"),
                ],
                docs=[("mlc_pdf", "MLC PDF"), ("signed_envelope", "Signed listing envelope")],
                forms=[("MLC", "AOIR Multiple Listing Contract"), ("FINTRAC", "FINTRAC identity form")],
                triggers=[("mlc-workflow", "Run MLC workflow", "mlc"), ("digisign-sync", "Sync DigiSign status", "digisign")],
            ),
            _stage(
                "Marketing",
                "MLS + socials",
                [
                    ("mls-remarks", "Draft MLS remarks + public description"),
                    ("feature-sheet", "Feature sheet copy"),
                    ("social-posts", "Social posts queued"),
                    ("email-blast", "Email blast sent"),
                ],
                fields=[("mlsNumber", "MLS number")],
                triggers=[("seller-update", "Generate seller launch update", "seller-updates")],
            ),
            _stage(
                "Showings",
                "Updates + OH",
                [
                    ("open-house", "Open house scheduled"),
                    ("showingtime-digest", "Weekly ShowingTime + market digest sent"),
                ],
                triggers=[("showingtime-digest", "Attach ShowingTime digest", "showingtime")],
            ),
            _stage(
                "Offer",
                "Summary + terms",
                [
                    ("offer-summary", "Offer summary prepared"),
                    ("subject-deadline", "Subject removal deadline tracked"),
                    ("inspection-timing", "Inspection scheduled"),
                ],
                fields=[("offerDate", "Offer date"), ("subjectRemovalDate", "Subject removal date")],
                docs=[("offer_pdf", "Offer PDF")],
            ),
            _stage(
                "Subjects",
                "Deposit + lawyer",
                [
                    ("deposit-confirmed", "Deposit landed in trust"),
                    ("lawyer-engaged", "Lawyer / conveyancer engaged"),
                    ("completion-locked", "Completion + possession dates locked"),
                ],
                fields=[("depositDueDate", "Deposit due date"), ("completionDate", "Completion date"), ("possessionDate", "Possession date")],
                docs=[("deposit_receipt", "Deposit receipt")],
            ),
            _stage(
                "Closing",
                "Keys + possession",
                [
                    ("completion-checklist", "Completion checklist complete"),
                    ("key-handoff", "Key handoff coordinated"),
                ],
                triggers=[("gmail-doc-router", "Route inbound closing PDFs", "gmail-doc-router")],
            ),
            _stage(
                "Gift + Nurture",
                "Review + referral",
                [
                    ("closing-gift", "Closing gift ordered + sent"),
                    ("thank-you", "Thank-you / review / referral drafts queued"),
                    ("anniversary", "Anniversary reminder added"),
                    ("past-client-nurture", "Moved into past-client nurture"),
                ],
                fields=[("anniversaryDate", "Anniversary date")],
            ),
        ],
    },
    "buyer": {
        "stages": [
            _stage("Intake", "Profile + budget", [("buyer-profile", "Buyer profile captured"), ("search-criteria", "MLS / Lofty search filter built")]),
            _stage("Search Setup", "Criteria + MLS", [("shortlist", "Property shortlist + ranked-fit"), ("showing-route", "Showing route + itinerary")]),
            _stage("Tours", "Route + notes", [("followup-draft", "Per-showing follow-up draft"), ("feedback-summary", "Feedback summary")]),
            _stage("Follow-Up", "Feedback + fit", [("criteria-update", "Buyer criteria updated"), ("comp-pull", "Comparable sales pulled")]),
            _stage("Offer Prep", "Comps + CPS", [("lender-paperwork", "Lender paperwork sent"), ("accepted-offer-checklist", "Accepted-offer checklist run"), ("doc-list", "Doc list built")], docs=[("cps_draft", "CPS draft")]),
            _stage("Accepted", "Lender + docs", [("inspection-booked", "Inspection booked"), ("insurance-deadline", "Insurance deadline tracked")], fields=[("subjectRemovalDate", "Subject removal date")]),
            _stage("Conditions", "Inspection + strata", [("deposit-due", "Deposit due date tracked"), ("lawyer-info", "Lawyer / conveyancer info captured")], fields=[("depositDueDate", "Deposit due date")]),
            _stage("Subjects Off", "Deposit + dates", [("subjects-removed", "All subjects removed"), ("deposit-received", "Deposit received"), ("completion-locked", "Completion + possession dates locked")], fields=[("completionDate", "Completion date"), ("possessionDate", "Possession date")]),
            _stage("Closing", "Lawyer + walkthrough", [("lawyer-final-docs", "Final docs forwarded to lawyer"), ("completion-checklist", "Completion checklist complete"), ("final-walkthrough", "Final walkthrough scheduled")]),
            _stage("Possession", "Gift + follow-up", [("utility-reminder", "Utility / change-of-address reminder sent"), ("key-handoff", "Key handoff coordinated"), ("closing-gift", "Closing gift sent"), ("thank-you", "Thank-you / review / referral drafts queued")], fields=[("anniversaryDate", "Anniversary date")]),
        ],
    },
}


_CONDITION_ADDITIONS: dict[str, list[dict[str, Any]]] = {
    "propertySubtype:strata": [
        {"stage": 6, "id": "strata-docs-review", "label": "Strata documents reviewed", "docKind": "strata_docs"}
    ],
    "property_subtype:strata": [
        {"stage": 6, "id": "strata-docs-review", "label": "Strata documents reviewed", "docKind": "strata_docs"}
    ],
    "tenanted:true": [
        {"stage": 2, "id": "tenancy-docs", "label": "Tenancy docs / notice requirements checked", "docKind": "tenancy_docs"}
    ],
    "multipleOffers:true": [
        {"stage": 6, "id": "offer-matrix", "label": "Multiple-offer comparison matrix prepared", "docKind": "offer_matrix"}
    ],
    "multiple_offers:true": [
        {"stage": 6, "id": "offer-matrix", "label": "Multiple-offer comparison matrix prepared", "docKind": "offer_matrix"}
    ],
    "poaSigning:true": [
        {"stage": 3, "id": "poa-review", "label": "POA authority reviewed", "docKind": "poa_authority"}
    ],
    "poa_signing:true": [
        {"stage": 3, "id": "poa-review", "label": "POA authority reviewed", "docKind": "poa_authority"}
    ],
}


def package_key_from_deal(deal: Mapping[str, Any]) -> str:
    country = str(deal.get("country") or "ca").strip().lower()
    province = str(deal.get("province") or "bc").strip().lower()
    board = str(deal.get("board") or "aoir").strip().lower()
    market = str(deal.get("market") or "kamloops").strip().lower().replace(" ", "-")
    return ".".join(part for part in (country, province, board, market) if part)


def resolve_admin_deal_flow(
    *,
    package_key: str,
    side: str,
    stage: int,
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve package rules for the current side/stage."""
    package = _KAMLOOPS if package_key == DEFAULT_PACKAGE_KEY else _KAMLOOPS
    side_key = side if side in {"listing", "buyer"} else "listing"
    stage_index = min(9, max(0, int(stage)))
    stages = package[side_key]["stages"]
    current = stages[stage_index]
    additions = _condition_checklist_additions(conditions or {}, stage_index)
    checklist = [*current["checklist"], *additions]
    return {
        "packageKey": package["packageKey"],
        "side": side_key,
        "stage": stage_index,
        "stageName": current["title"],
        "stageSubtitle": current["subtitle"],
        "nextStage": stage_index + 1 if stage_index < 9 else None,
        "nextStageName": stages[stage_index + 1]["title"] if stage_index < 9 else None,
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
        "localOverrides": package["localOverrides"],
    }


def resolve_deal_phase(
    *,
    deal: Mapping[str, Any],
    checklist: Mapping[str, Any] | None,
    attachments: list[Mapping[str, Any]] | None,
    prior_runs: list[Mapping[str, Any]] | None,
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return resolved package rules plus gate state for the deal's phase."""
    package_key = package_key_from_deal(deal)
    flow = resolve_admin_deal_flow(
        package_key=package_key,
        side=str(deal.get("side") or "listing"),
        stage=int(deal.get("currentStage") or 0),
        conditions=conditions,
    )
    done = checklist or {}
    attachment_kinds = {str(item.get("kind") or "") for item in (attachments or [])}
    missing_checklist = [
        item for item in flow["checklistItems"]
        if item.get("required") and done.get(item["id"]) is not True
    ]
    missing_fields = [
        item for item in flow["requiredFields"]
        if not _present(deal.get(item["field"]))
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


def _condition_checklist_additions(conditions: Mapping[str, Any], stage: int) -> list[dict[str, Any]]:
    additions: list[dict[str, Any]] = []
    for key, value in conditions.items():
        normalized = f"{key}:{str(value).lower() if isinstance(value, bool) else value}"
        for item in _CONDITION_ADDITIONS.get(normalized, []):
            if int(item["stage"]) == stage:
                additions.append({"id": item["id"], "label": item["label"], "required": True, "docKind": item.get("docKind")})
    return additions


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


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
