"""Admin profile promotion tool for lead-to-deal handoffs."""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result


def _admin_profile_tool(args: dict[str, Any], **kw: Any) -> str:
    action = str(args.get("action") or "promote").strip().lower()
    if action != "promote":
        return tool_error(f"unknown admin_profile action {action!r}")
    try:
        from elevate_cli.data import (
            connect,
            get_admin_setup,
            promote_profile_to_admin_deal,
            require_admin_setup_ready,
        )

        with connect() as conn:
            require_admin_setup_ready(conn)
            setup_profile = (get_admin_setup(conn).get("profile") or {})
            province = str(args.get("province") or setup_profile.get("province") or "").strip().upper()
            market = args.get("market") if args.get("market") is not None else setup_profile.get("market")
            result = promote_profile_to_admin_deal(
                conn,
                profile_id=str(args.get("profile_id") or args.get("profileId") or "").strip(),
                side=str(args.get("side") or "").strip(),
                actor=str(args.get("actor") or "admin").strip() or "admin",
                province=province,
                board=args.get("board"),
                market=market,
                current_stage=int(args.get("current_stage") or args.get("currentStage") or 0),
                display_name=args.get("display_name") or args.get("displayName"),
                primary_contact_id=args.get("primary_contact_id") or args.get("primaryContactId"),
                listing_address=args.get("listing_address") or args.get("listingAddress"),
                workflow=args.get("workflow"),
                profile_context=args.get("profile_context") or args.get("profileContext") or {},
                verifiers=args.get("verifiers") or [],
                fields=args.get("fields") or {},
                dispatch_initial_stage=bool(args.get("dispatch_initial_stage", args.get("dispatchInitialStage", True))),
            )
            return tool_result(success=True, **result)
    except Exception as exc:
        return tool_error(str(exc))


ADMIN_PROFILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "admin_profile",
        "description": (
            "Promote a verified lead profile into the Admin deal source of truth. "
            "Use this after a seller/buyer handoff has enough context and must "
            "create or update the matching Admin file without duplicating people."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["promote"],
                    "description": "Operation to perform. Defaults to promote.",
                },
                "profile_id": {"type": "string"},
                "side": {"type": "string", "enum": ["listing", "buyer"]},
                "actor": {"type": "string"},
                "province": {"type": "string"},
                "board": {"type": "string"},
                "market": {"type": "string"},
                "current_stage": {"type": "integer", "minimum": 0, "maximum": 10},
                "display_name": {"type": "string"},
                "primary_contact_id": {"type": "string"},
                "listing_address": {"type": "string"},
                "workflow": {"type": "string"},
                "profile_context": {"type": "object"},
                "verifiers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "value": {"type": "string"},
                            "key": {"type": "string"},
                        },
                    },
                },
                "fields": {"type": "object"},
                "dispatch_initial_stage": {
                    "type": "boolean",
                    "description": "Dispatch initial Admin stage automations after create. Defaults true.",
                },
            },
            "required": ["profile_id", "side"],
        },
    },
}


registry.register(
    name="admin_profile",
    toolset="admin_profile",
    schema=ADMIN_PROFILE_SCHEMA,
    handler=lambda args, **kw: _admin_profile_tool(args, **kw),
    description="Promote verified lead profiles into Admin deal files",
    emoji="",
)
