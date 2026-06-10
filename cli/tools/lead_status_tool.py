"""Agent-facing write surface for a LEAD's status, heat, and follow-up.

``leads_overview`` *reads* the outreach pipeline; this tool lets the agent
*label a lead as it works it* — set the pipeline status (new_lead / follow_up /
ghosting / dead / closed_seller / closed_buyer), heat (hot/warm/watch/normal),
and the follow-up cadence flag. Writes are stamped ``set_by="ai"`` so they never
overwrite a status the operator set by hand (operator always wins).

When the operator has the CRM push opt-in enabled (``crm.push_status: true``),
a status change also pushes to the connected CRM (Lofty / Follow Up Boss /
Sierra) so the realtor's system of record stays in sync. Off by default.

This closes the gap where the ISA agent worked a lead but left it unlabeled, so
the next heartbeat re-processed it blind.
"""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result

_ACTOR = "agent:lead_status"

_PIPELINE_VALUES = {
    "new_lead", "follow_up", "ghosting", "dead", "closed_seller", "closed_buyer",
}
_HEAT_VALUES = {"hot", "warm", "watch", "normal"}
_TYPE_VALUES = {"buyer", "listing", "other"}


def _lead_status_handler(args: dict[str, Any], **_: Any) -> str:
    from elevate_cli.access import (
        ENTITLEMENT_REAL_ESTATE_SALES,
        is_entitlement_active,
    )

    if not is_entitlement_active(ENTITLEMENT_REAL_ESTATE_SALES, None):
        return tool_result(
            success=False,
            error="requires_entitlement",
            required_pack="real_estate_sales",
            message=(
                "lead_status requires the 'real_estate_sales' pack. Surface an "
                "upgrade prompt; do not retry."
            ),
        )

    action = str(args.get("action") or "").strip().lower()
    contact_id = str(args.get("contact_id") or "").strip()
    if not contact_id:
        return tool_error("contact_id is required")

    from elevate_cli.data import (
        classify_contact,
        get_contact,
        set_pipeline_status,
        update_flags,
    )
    from elevate_cli.data.connection import connect

    try:
        with connect() as conn:
            contact = get_contact(conn, contact_id)
            if contact is None:
                return tool_error(f"contact {contact_id!r} not found")

            if action == "show":
                return tool_result(success=True, lead=_brief(contact))

            if action == "set":
                status = str(args.get("status") or "").strip().lower()
                if status not in _PIPELINE_VALUES:
                    return tool_error(
                        f"status must be one of {sorted(_PIPELINE_VALUES)}"
                    )
                updated = set_pipeline_status(
                    conn, contact_id, status=status, actor=_ACTOR, set_by="ai",
                )
                # Operator-owned status is a no-op (precedence enforced in the
                # data layer) — tell the agent so it doesn't keep trying.
                if updated.get("pipelineStatusSetBy") == "operator" and \
                        updated.get("pipelineStatus") != status:
                    return tool_result(
                        success=False, skipped="operator_set",
                        message="The operator set this lead's status by hand; "
                                "leave it. (AI can't override an operator mark.)",
                        lead=_brief(updated),
                    )
                _maybe_push_crm(conn, updated, status)
                return tool_result(success=True, set=status, lead=_brief(updated))

            if action == "heat":
                label = str(args.get("label") or "").strip().lower()
                if label not in _HEAT_VALUES:
                    return tool_error(f"label must be one of {sorted(_HEAT_VALUES)}")
                flags: dict[str, Any] = {"heatLabel": label}
                if args.get("score") is not None:
                    flags["heatScore"] = int(args["score"])
                if args.get("reason"):
                    flags["heatReason"] = str(args["reason"])[:500]
                updated = update_flags(conn, contact_id, actor=_ACTOR, **flags)
                return tool_result(success=True, heat=label, lead=_brief(updated))

            if action == "follow_up":
                needs = args.get("needs", True)
                flags = {"needsFollowUp": bool(needs)}
                if args.get("next_at") or args.get("nextAt"):
                    flags["nextFollowUpAt"] = str(args.get("next_at") or args.get("nextAt"))
                updated = update_flags(conn, contact_id, actor=_ACTOR, **flags)
                return tool_result(
                    success=True, needsFollowUp=bool(needs), lead=_brief(updated),
                )

            if action == "classify":
                ctype = str(args.get("type") or "").strip().lower()
                if ctype not in _TYPE_VALUES:
                    return tool_error(f"type must be one of {sorted(_TYPE_VALUES)}")
                updated = classify_contact(conn, contact_id, ctype, actor=_ACTOR)
                return tool_result(success=True, classified=ctype, lead=_brief(updated))

            return tool_error(
                f"unknown action {action!r}; use one of: "
                "show, set, heat, follow_up, classify"
            )
    except LookupError as exc:
        return tool_error(str(exc))
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")


def _brief(contact: dict[str, Any] | None) -> dict[str, Any]:
    c = contact or {}
    return {
        "id": c.get("id"),
        "name": c.get("displayName"),
        "pipelineStatus": c.get("pipelineStatus"),
        "pipelineStatusSetBy": c.get("pipelineStatusSetBy"),
        "heatLabel": c.get("heatLabel"),
        "needsFollowUp": c.get("needsFollowUp"),
        "nextFollowUpAt": c.get("nextFollowUpAt"),
        "stage": c.get("stage"),
        "lastActivityAt": c.get("lastActivityAt"),
    }


def _maybe_push_crm(conn, contact: dict[str, Any], status: str) -> None:
    """Push the status to the connected CRM when the operator opted in. Best-
    effort: a CRM failure never fails the local write (the board is the source
    of truth; CRM is a mirror)."""
    try:
        from tools.lead_status_crm import push_lead_status_to_crm
        push_lead_status_to_crm(conn, contact, status)
    except Exception:
        pass


LEAD_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lead_status",
        "description": (
            "Label a lead as you work it: set its pipeline status, heat, "
            "follow-up cadence, or buyer/listing type. The Leads board reads "
            "this live, and the next heartbeat sees it was handled (so it "
            "won't re-process the lead). Writes are AI-stamped and never "
            "override a status the operator set by hand.\n\n"
            "Actions:\n"
            "- show: current status/heat/follow-up for a contact.\n"
            "- set: pipeline status — new_lead, follow_up, ghosting, dead, "
            "closed_seller, closed_buyer.\n"
            "- heat: hot/warm/watch/normal (+ optional score 0-100, reason).\n"
            "- follow_up: needs follow-up flag (+ optional next_at ISO date).\n"
            "- classify: buyer/listing/other.\n\n"
            "Use this after you respond to or assess a lead so the board "
            "reflects where it's at. If you're unsure what status fits, ask "
            "before guessing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["show", "set", "heat", "follow_up", "classify"],
                    "description": "What to do.",
                },
                "contact_id": {
                    "type": "string",
                    "description": "The lead/contact id (from leads_overview, "
                                   "the inbox, or your messaging context).",
                },
                "status": {
                    "type": "string",
                    "enum": sorted(_PIPELINE_VALUES),
                    "description": "Pipeline status (action=set).",
                },
                "label": {
                    "type": "string",
                    "enum": sorted(_HEAT_VALUES),
                    "description": "Heat label (action=heat).",
                },
                "score": {"type": "integer", "description": "Heat score 0-100 (action=heat)."},
                "reason": {"type": "string", "description": "Short heat reason (action=heat)."},
                "needs": {"type": "boolean", "description": "Needs follow-up? (action=follow_up)."},
                "next_at": {"type": "string", "description": "Next follow-up ISO date (action=follow_up)."},
                "type": {
                    "type": "string",
                    "enum": sorted(_TYPE_VALUES),
                    "description": "Contact type (action=classify).",
                },
            },
            "required": ["action", "contact_id"],
        },
    },
}


registry.register(
    name="lead_status",
    toolset="lead_status",
    schema=LEAD_STATUS_SCHEMA,
    handler=_lead_status_handler,
    description=(
        "Set a lead's pipeline status, heat, follow-up, or type so the Leads "
        "board and the next heartbeat reflect where it's at."
    ),
    emoji="",
)
