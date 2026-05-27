"""Per-entity working-state journal tool.

Lets the agent persist "where we left off" on a specific deal or
contact so the NEXT session knows the current state without the user
re-briefing. The session prompt builder injects a short digest at
session start; this tool is how the agent reads and writes individual
entries through the turn.

Four actions:

* ``recall``       — read the latest active entry for one entity
* ``update``       — record a new snapshot, superseding the previous
* ``resolve``      — close out the work with a final note
* ``list_active``  — every non-resolved active entry across all
                     entities the user has purchased access to

Entitlement
-----------

Working-state rows piggyback on the ``notes`` table (migration 0002).
``notes`` is part of ``elevate_core`` for contact-scoped entries.
Deal-scoped entries require ``real_estate_admin`` since deals
themselves are gated.

If the caller targets ``entity_kind='deal'`` without the admin pack,
the tool returns a ``requires_entitlement`` error so the AI can
surface an upgrade prompt rather than retry.
"""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result


# ─── Entity-kind → required pack ────────────────────────────────────


def _required_pack(entity_kind: str) -> str:
    if entity_kind == "deal":
        return "real_estate_admin"
    return "elevate_core"


def _enforce_pack(entity_kind: str) -> str | None:
    from elevate_cli.access import is_entitlement_active

    pack = _required_pack(entity_kind)
    if pack == "elevate_core":
        return None
    if not is_entitlement_active(pack, None):
        return tool_result(
            success=False,
            error="requires_entitlement",
            entity_kind=entity_kind,
            required_pack=pack,
            message=(
                f"Working state on {entity_kind}s requires the "
                f"'{pack}' pack. Surface an upgrade prompt; do not retry."
            ),
        )
    return None


# ─── Action handlers ────────────────────────────────────────────────


def _action_recall(args: dict[str, Any]) -> str:
    entity_kind = str(args.get("entity_kind") or "").strip().lower()
    entity_id = str(args.get("entity_id") or "").strip()
    if not entity_kind or not entity_id:
        return tool_error("'entity_kind' and 'entity_id' are required")
    gated = _enforce_pack(entity_kind)
    if gated is not None:
        return gated

    from elevate_cli.data.connection import connect
    from elevate_cli.data.working_state import recall_working_state

    try:
        with connect() as conn:
            row = recall_working_state(
                conn, entity_kind=entity_kind, entity_id=entity_id
            )
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")

    if row is None:
        return tool_result(
            success=True,
            entity_kind=entity_kind,
            entity_id=entity_id,
            state=None,
            message=(
                f"No active working-state entry for {entity_kind} "
                f"{entity_id}. Call action='update' to record one."
            ),
        )
    return tool_result(success=True, state=row)


def _action_update(args: dict[str, Any]) -> str:
    entity_kind = str(args.get("entity_kind") or "").strip().lower()
    entity_id = str(args.get("entity_id") or "").strip()
    body = str(args.get("body") or "").strip()
    if not entity_kind or not entity_id or not body:
        return tool_error(
            "'entity_kind', 'entity_id', and 'body' are required"
        )
    gated = _enforce_pack(entity_kind)
    if gated is not None:
        return gated

    status = args.get("status")
    next_action = args.get("next_action")
    blocked_on = args.get("blocked_on")
    agent_kind = args.get("agent_kind")
    author_name = args.get("author_name") or agent_kind or "agent"

    from elevate_cli.data.connection import connect, transaction
    from elevate_cli.data.working_state import update_working_state

    try:
        with connect() as conn:
            with transaction(conn):
                row = update_working_state(
                    conn,
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    body=body,
                    status=status,
                    next_action=next_action,
                    blocked_on=blocked_on,
                    agent_kind=agent_kind,
                    author_name=author_name,
                )
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")

    return tool_result(success=True, state=row)


def _action_resolve(args: dict[str, Any]) -> str:
    entity_kind = str(args.get("entity_kind") or "").strip().lower()
    entity_id = str(args.get("entity_id") or "").strip()
    body = str(args.get("body") or "").strip()
    if not entity_kind or not entity_id or not body:
        return tool_error(
            "'entity_kind', 'entity_id', and 'body' are required for resolve"
        )
    gated = _enforce_pack(entity_kind)
    if gated is not None:
        return gated

    agent_kind = args.get("agent_kind")
    author_name = args.get("author_name") or agent_kind or "agent"

    from elevate_cli.data.connection import connect, transaction
    from elevate_cli.data.working_state import resolve_working_state

    try:
        with connect() as conn:
            with transaction(conn):
                row = resolve_working_state(
                    conn,
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    body=body,
                    agent_kind=agent_kind,
                    author_name=author_name,
                )
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")

    return tool_result(success=True, state=row)


def _action_list_active(args: dict[str, Any]) -> str:
    from elevate_cli.access import (
        ENTITLEMENT_REAL_ESTATE_ADMIN,
        is_entitlement_active,
    )

    requested = args.get("entity_kinds")
    if requested:
        kinds = [str(k).strip().lower() for k in requested]
    else:
        kinds = ["contact", "deal"]
    invalid = [k for k in kinds if k not in {"contact", "deal"}]
    if invalid:
        return tool_error(f"invalid entity_kind(s): {invalid}")

    # Silently drop 'deal' from the requested set if the user doesn't
    # have the admin pack. Listing should never 401 — the agent might
    # just want contacts.
    if "deal" in kinds and not is_entitlement_active(
        ENTITLEMENT_REAL_ESTATE_ADMIN, None
    ):
        kinds = [k for k in kinds if k != "deal"]

    limit = int(args.get("limit") or 30)
    limit = max(1, min(limit, 100))

    from elevate_cli.data.connection import connect
    from elevate_cli.data.working_state import list_active_working_state

    try:
        with connect() as conn:
            rows = list_active_working_state(
                conn, entity_kinds=kinds, limit=limit
            )
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")

    return tool_result(success=True, count=len(rows), items=rows)


# ─── Dispatch + schema ──────────────────────────────────────────────


_ACTIONS = {
    "recall": _action_recall,
    "update": _action_update,
    "resolve": _action_resolve,
    "list_active": _action_list_active,
}


def _working_state_handler(args: dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "").strip().lower()
    handler = _ACTIONS.get(action)
    if handler is None:
        return tool_error(
            f"unknown action '{action}'. "
            "Use one of: recall, update, resolve, list_active."
        )
    try:
        return handler(args)
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")


WORKING_STATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "working_state",
        "description": (
            "Per-entity 'where we left off' journal for deals and contacts "
            "(leads are contacts with lead_signals). Persists across sessions "
            "so the NEXT session knows the current state without the user "
            "re-briefing. The session prompt already includes a short digest "
            "of active entries — use this tool to (a) recall full body when "
            "you need to dig in, (b) update when you make progress, "
            "(c) resolve when done, (d) list everything in flight.\n\n"
            "Write a working-state entry whenever a meaningful step happens on "
            "a deal/lead: sent an offer, scheduled a showing, drafted a reply "
            "awaiting send, hit a blocker. Keep the body short ('Sent counter "
            "at $450k, awaiting reply from listing agent') and use "
            "next_action / blocked_on for the one-line follow-up.\n\n"
            "Status: 'in_progress' (default), 'pending_external' (waiting on "
            "a third party), 'blocked' (need user input), or 'resolved' (done). "
            "Resolved entries drop out of the session-start digest."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["recall", "update", "resolve", "list_active"],
                    "description": "Which operation to perform.",
                },
                "entity_kind": {
                    "type": "string",
                    "enum": ["contact", "deal"],
                    "description": (
                        "Entity type. Required for recall/update/resolve. "
                        "Leads use 'contact' (a lead IS a contact with "
                        "lead_signals)."
                    ),
                },
                "entity_id": {
                    "type": "string",
                    "description": (
                        "Contact id or deal id. Required for "
                        "recall/update/resolve."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "(update/resolve) Short narrative of current state. "
                        "1-2 sentences max — this is what future-you reads "
                        "first when picking up the work again."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": [
                        "in_progress",
                        "pending_external",
                        "blocked",
                        "resolved",
                    ],
                    "description": (
                        "(update) Defaults to 'in_progress'. Use "
                        "'pending_external' when waiting on a third party, "
                        "'blocked' when the user must act, 'resolved' to "
                        "close out (or call action='resolve' instead)."
                    ),
                },
                "next_action": {
                    "type": "string",
                    "description": (
                        "(update) One-line next step. Empty if nothing "
                        "specific is owed yet."
                    ),
                },
                "blocked_on": {
                    "type": "string",
                    "description": (
                        "(update) Who or what we're waiting on. Only "
                        "meaningful with status 'pending_external' / "
                        "'blocked'."
                    ),
                },
                "agent_kind": {
                    "type": "string",
                    "description": (
                        "(update/resolve) Which agent kind wrote this "
                        "(e.g. 'executive-assistant', 'leads-watcher'). "
                        "Lets the digest attribute work to the right agent."
                    ),
                },
                "author_name": {
                    "type": "string",
                    "description": (
                        "(update/resolve) Specific writer label. Defaults "
                        "to agent_kind or 'agent'."
                    ),
                },
                "entity_kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["contact", "deal"]},
                    "description": (
                        "(list_active) Filter to these kinds. Default is "
                        "both. 'deal' is silently dropped if the user "
                        "doesn't own the admin pack."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "(list_active) Max rows. Default 30.",
                },
            },
            "required": ["action"],
        },
    },
}


registry.register(
    name="working_state",
    toolset="working_state",
    schema=WORKING_STATE_SCHEMA,
    handler=_working_state_handler,
    description=(
        "Per-deal / per-contact 'where we left off' journal. Persisted in "
        "the notes table; agent reads it back on the next session via the "
        "system-prompt digest."
    ),
    emoji="",
)
