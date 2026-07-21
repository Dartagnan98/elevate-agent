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
# Setting either of these does not just relabel the contact: ``close_to_admin``
# promotes it onto the deal board, so the declared effect set must say so.
_DEAL_PROMOTING_STATUSES = frozenset({"closed_seller", "closed_buyer"})
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
    from elevate_cli.data.connection import (
        OperationalStoreNotReady,
        connect,
        connect_ready_read_only,
    )

    # ``show`` is a pure read: run it over the already-ready forced-READ-ONLY
    # store so inspecting a lead never bootstraps/migrates the operational
    # store as a cold-connect side effect. The write actions below keep the
    # general ``connect()`` because they must mutate.
    if action == "show":
        try:
            with connect_ready_read_only() as conn:
                contact = get_contact(conn, contact_id)
                if contact is None:
                    return tool_error(f"contact {contact_id!r} not found")
                return tool_result(success=True, lead=_brief(contact))
        except OperationalStoreNotReady:
            return tool_result(
                success=False,
                error="operational_store_not_ready",
                message=(
                    "Lead data is still starting for the active account. "
                    "Wait for Elevate startup to complete, then retry once."
                ),
            )

    try:
        with connect() as conn:
            contact = get_contact(conn, contact_id)
            if contact is None:
                return tool_error(f"contact {contact_id!r} not found")

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
                push = _maybe_push_crm(conn, updated, status)
                if push.get("reason") == "not_authorized":
                    # The local label was saved; only the mirror was withheld.
                    # Say that in plain English — the realtor should not have
                    # to decode a policy code to find out their CRM is stale.
                    return tool_result(
                        success=True,
                        set=status,
                        lead=_brief(updated),
                        crmSync="skipped",
                        message=(
                            f"Saved this lead as {status} on your board. I did not "
                            "update your CRM — sending changes to an outside system "
                            "needs your OK first. Tell me if you want it pushed "
                            "across, or change it in your CRM directly."
                        ),
                    )
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


def _maybe_push_crm(conn, contact: dict[str, Any], status: str) -> dict[str, Any]:
    """Push the status to the connected CRM when the operator opted in. Best-
    effort: a CRM failure never fails the local write (the board is the source
    of truth; CRM is a mirror).

    Returns the push result so the caller can tell the realtor, in plain
    words, when the local label was saved but the CRM mirror was withheld.
    """
    try:
        from tools.lead_status_crm import push_lead_status_to_crm
        result = push_lead_status_to_crm(conn, contact, status)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


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


def _crm_mirror_reachable_for_set() -> bool:
    """Whether a ``set`` will attempt the external CRM mirror on this box.

    Read through :func:`tools.lead_status_crm.crm_status_push_enabled` — the
    same expression :func:`push_lead_status_to_crm` evaluates — so the
    declared effect set and the dispatched behavior are one decision, not
    two.  The onboarding profile is read over the already-ready
    forced-READ-ONLY boundary so classifying a call never bootstraps or
    migrates the operational store as a side effect.

    Fails CLOSED: anything that prevents a confident "the mirror is off"
    answer returns ``True``, which declares ``write_external:crm`` and gets
    the call refused under a local-only ceiling rather than letting an
    undeclared external write through.

    A cold operational store is the ONE exception, and it is not a weakening:
    ``OperationalStoreNotReady`` means the onboarding profile is unreadable,
    which is exactly the case where the handler's own ``_onboarding_crm``
    already degrades to ``{}`` and lets ``config.yaml`` decide.  Mirroring
    that keeps declaration and dispatch identical.  Treating it as "mirror
    on" instead would refuse the call with a policy-shaped error and hide the
    real, actionable "your data is still starting up" message the handler
    would otherwise return.
    """
    from tools.lead_status_crm import crm_status_push_enabled

    try:
        from elevate_cli.data.connection import (
            OperationalStoreNotReady,
            connect_ready_read_only,
        )

        try:
            with connect_ready_read_only() as conn:
                return bool(crm_status_push_enabled(conn))
        except OperationalStoreNotReady:
            return bool(crm_status_push_enabled(None))
    except Exception:
        return True


def _lead_status_effect_resolver(args: dict):
    """Classify each action against what the handler physically does.

    ``show`` runs over ``connect_ready_read_only()`` and only reads the
    contact row, so it is a truthful ``read:leads``.

    ``heat``/``follow_up``/``classify`` read the contact and then mutate that
    contact's own labels in the local operational store — ``update_flags`` /
    ``classify_contact`` — with no network, filesystem, process, or external
    reach on any branch.  They are ``read:leads`` + ``write_local:leads``:
    the realtor's own pipeline labels, on the realtor's own machine,
    reversible by hand.

    ``set`` is the one action with an outward branch: after the local
    ``set_pipeline_status`` it calls ``_maybe_push_crm``, which can mirror
    the status into Lofty / Follow Up Boss / Sierra.  That branch is declared,
    not hidden — when the operator's CRM-mirror opt-in is on, ``set``
    resolves to ``{read:leads, write_local:leads, write_external:crm}`` and
    the workspace ceiling refuses the whole call, because a CRM write is a
    write to someone else's system that can trip that system's own client
    automations.  With the mirror off (the shipped default) the action is
    purely local and resolves without ``write_external``.  The dispatch side
    is severed independently in ``push_lead_status_to_crm`` on the live
    policy, so a mirror that flips on between declaration and dispatch still
    cannot push.

    ``set`` also carries a SECOND, easily-missed local write: the two closing
    statuses cascade into the deal board.  ``set_pipeline_status`` routes
    ``closed_seller``/``closed_buyer`` through ``close_to_admin`` ->
    ``promote_profile_to_admin_deal`` -> ``create_deal``, so those two values
    also write ``write_local:deals``.  Both effects are inside the workspace
    ceiling, so nothing is denied by declaring it — but an effect receipt that
    named only ``write_local:leads`` for a call that created a deal would be a
    false record, and the receipt is the evidence.

    Any unrecognized action stays unknown/fail-closed.  The normalization
    mirrors the handler's ``str(args.get("action") or "").strip().lower()``
    exactly so the declared surface can never diverge from the dispatch.
    """
    from tools.approval import EffectKind

    action = args.get("action") if isinstance(args, dict) else None
    act = str(action or "").strip().lower()
    if act == "show":
        return {"read:leads"}
    if act == "set":
        effects = {"read:leads", "write_local:leads"}
        status = str(args.get("status") or "").strip().lower()
        if status in _DEAL_PROMOTING_STATUSES:
            effects.add("write_local:deals")
        if _crm_mirror_reachable_for_set():
            effects.add("write_external:crm")
        return effects
    if act in {"heat", "follow_up", "classify"}:
        return {"read:leads", "write_local:leads"}
    return {EffectKind.UNKNOWN}


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
    effect_resolver=_lead_status_effect_resolver,
)
