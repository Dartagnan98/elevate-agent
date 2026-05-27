"""One-call pipeline snapshot for the agent.

Replaces the chain of ``list_deals`` → N × ``get_deal`` → ad-hoc SQL
counts that the agent used to run when the user asked "what's active
in my pipeline" or "what's closing soon". Returns a curated dict with
totals, stage breakdown, source breakdown, near-term closings, near-term
subject-removal dates, and a stale-stage flag — everything the agent
needs to brief the user without 10+ round-trips.

Single action, single call. Pack-gated on ``real_estate_admin``.
"""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result


def _deals_overview_handler(args: dict[str, Any], **_: Any) -> str:
    from elevate_cli.access import (
        ENTITLEMENT_REAL_ESTATE_ADMIN,
        is_entitlement_active,
    )

    if not is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, None):
        return tool_result(
            success=False,
            error="requires_entitlement",
            required_pack="real_estate_admin",
            message=(
                "deals_overview requires the 'real_estate_admin' pack. "
                "Surface an upgrade prompt; do not retry."
            ),
        )

    status = args.get("status", "active")
    if isinstance(status, str):
        status = status.strip().lower() or None
    if status == "all":
        status = None

    side = args.get("side")
    if isinstance(side, str):
        side = side.strip().lower() or None

    exclude_mock = args.get("exclude_mock", True)
    if isinstance(exclude_mock, str):
        exclude_mock = exclude_mock.strip().lower() not in {"0", "false", "no"}

    def _int(key: str, default: int) -> int:
        try:
            return int(args.get(key) if args.get(key) is not None else default)
        except (TypeError, ValueError):
            return default

    near_close_days = max(0, _int("near_close_days", 30))
    near_subject_days = max(0, _int("near_subject_days", 21))
    stale_days = max(1, _int("stale_days", 14))

    from elevate_cli.data.connection import connect
    from elevate_cli.data.deals import deals_overview

    try:
        with connect() as conn:
            snap = deals_overview(
                conn,
                status=status,
                side=side,
                exclude_mock=exclude_mock,
                near_close_days=near_close_days,
                near_subject_days=near_subject_days,
                stale_days=stale_days,
            )
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")

    return tool_result(success=True, overview=snap)


DEALS_OVERVIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "deals_overview",
        "description": (
            "Whole-pipeline snapshot in ONE call. Use this instead of "
            "chaining list_deals + get_deal + SQL counts whenever the "
            "user asks 'what's active', 'what's closing soon', 'where "
            "are my deals', 'morning briefing', or any aggregate "
            "pipeline question.\n\n"
            "Returns: totals (active count after mock filter, raw matched, "
            "by status, by side), byStage (0-10 → count), bySource "
            "(label → count), mockDeals (what was filtered out and why), "
            "closingsSoon (with daysToClose, sorted soonest-first), "
            "subjectsSoon (subject-removal dates, sorted soonest-first), "
            "staleStages (deals sitting in one stage longer than "
            "stale_days), and deals (thin scan-friendly list of every "
            "active deal sorted by stage then completion date).\n\n"
            "Mock filter: automatically drops deals whose source label/key "
            "contains 'mock', 'beta', 'dry-run', 'test_' so test data "
            "doesn't inflate counts. Set exclude_mock=false to keep them.\n\n"
            "Date windows: closingsSoon includes deals -7 to +near_close_days "
            "days out (so just-closed deals still show). subjectsSoon "
            "includes -3 to +near_subject_days. staleStages flags any "
            "deal whose stage_entered_at is older than stale_days and "
            "isn't in stage 10 (closed)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "closed", "archived", "all"],
                    "description": (
                        "Filter by deal status. Default 'active'. Use "
                        "'all' to include every status."
                    ),
                },
                "side": {
                    "type": "string",
                    "enum": ["listing", "buyer"],
                    "description": "Optional side filter.",
                },
                "exclude_mock": {
                    "type": "boolean",
                    "description": (
                        "Drop deals whose source looks like test data "
                        "(mock/beta/dry-run/test_). Default true."
                    ),
                },
                "near_close_days": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 180,
                    "description": (
                        "Window for closingsSoon. Default 30."
                    ),
                },
                "near_subject_days": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 90,
                    "description": (
                        "Window for subjectsSoon. Default 21."
                    ),
                },
                "stale_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": (
                        "How many days in one stage before a deal is "
                        "flagged stuck. Default 14."
                    ),
                },
            },
            "required": [],
        },
    },
}


registry.register(
    name="deals_overview",
    toolset="deals_overview",
    schema=DEALS_OVERVIEW_SCHEMA,
    handler=_deals_overview_handler,
    description=(
        "One-call pipeline snapshot: totals, by-stage, by-source, "
        "closings-soon, subjects-soon, stale-stages, thin deal list."
    ),
    emoji="",
)
