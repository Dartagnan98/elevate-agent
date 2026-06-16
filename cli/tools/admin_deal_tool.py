"""Agent-facing write surface for the real-estate admin deal board (kanban).

``deals_overview`` *reads* the pipeline; this tool *writes* a single deal so the
agent can finalize work in a live session — toggle checklist cells, set fields,
attach artifacts, and advance the card — the same way a background stage run does
through its result callback. The kanban board reads the deal live, so every write
syncs immediately.

Use this when a skill (CMA, MLC, etc.) was invoked *in a session*: hold the
back-and-forth in the chat, then finalize the deal here so the board reflects the
outcome. Background/stage runs finalize through the run-result callback instead.

Pack-gated on ``real_estate_admin``.
"""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result

# Honest, non-"skill" actor: an in-session agent action with the realtor present.
# (The "skill:" prefix triggers the unattended-run protection that blocks
# approval-gated cells; in a live session the agent finalizes with the user, so
# it uses an agent-level actor. Policy on approval cells lives in the skills.)
_ACTOR = "agent:admin_deal"


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "n", ""}


def _gate_brief(context: dict) -> dict:
    gate = ((context.get("dealFlow") or {}).get("gate") or {})
    return {
        "stage": gate.get("stage"),
        "stageName": gate.get("stageName"),
        "nextStage": gate.get("nextStage"),
        "nextStageName": gate.get("nextStageName"),
        "canAdvance": gate.get("canAdvance"),
        "missingChecklist": [i.get("id") for i in (gate.get("missingChecklist") or [])],
        "missingFields": [i.get("field") for i in (gate.get("missingFields") or [])],
        "missingDocs": [i.get("kind") for i in (gate.get("missingDocs") or [])],
    }


def _admin_deal_handler(args: dict[str, Any], **_: Any) -> str:
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
                "admin_deal requires the 'real_estate_admin' pack. "
                "Surface an upgrade prompt; do not retry."
            ),
        )

    action = str(args.get("action") or "").strip().lower()
    deal_id = str(args.get("deal_id") or "").strip()
    if not deal_id:
        return tool_error("deal_id is required")

    from elevate_cli.data import (
        add_deal_attachment,
        get_deal_context,
        move_deal_stage,
        set_deal_fields,
        set_deal_toggle,
    )
    from elevate_cli.data.connection import connect

    try:
        with connect() as conn:
            if action == "show":
                ctx = get_deal_context(conn, deal_id)
                deal = ctx.get("deal") or {}
                return tool_result(
                    success=True,
                    deal={
                        "id": deal.get("id"),
                        "title": deal.get("title"),
                        "side": deal.get("side"),
                        "currentStage": deal.get("currentStage"),
                    },
                    gate=_gate_brief(ctx),
                )

            if action == "set_checklist":
                # Accept either one cell (field + value) or many in one call
                # (cells: {id: value}). Bulk avoids the "tick one cell and stop"
                # failure where the model fires a single toggle and moves on.
                cells = args.get("cells")
                applied: dict[str, Any] = {}
                if isinstance(cells, dict) and cells:
                    for raw_field, raw_value in cells.items():
                        cell = str(raw_field or "").strip()
                        if not cell:
                            continue
                        set_deal_toggle(conn, deal_id, field=cell, value=raw_value, actor=_ACTOR)
                        applied[cell] = raw_value
                    if not applied:
                        return tool_error("set_checklist 'cells' had no valid checklist ids")
                else:
                    field = str(args.get("field") or "").strip()
                    if not field:
                        return tool_error(
                            "set_checklist requires 'field' (a checklist/workflow id) or a 'cells' map"
                        )
                    value = args.get("value", True)
                    set_deal_toggle(conn, deal_id, field=field, value=value, actor=_ACTOR)
                    applied[field] = value
                ctx = get_deal_context(conn, deal_id)
                return tool_result(success=True, applied=applied, gate=_gate_brief(ctx))

            if action == "set_fields":
                fields = args.get("fields")
                if not isinstance(fields, dict) or not fields:
                    return tool_error("set_fields requires a non-empty 'fields' object")
                # A gate's required "fields" mix named deal columns (listPrice,
                # listingAddress, dates) with workflow_* cells stored as toggles.
                # Route each automatically so the agent can pass either kind.
                named: dict[str, Any] = {}
                for key, value in fields.items():
                    if str(key).startswith("workflow_"):
                        set_deal_toggle(conn, deal_id, field=str(key), value=value, actor=_ACTOR)
                    else:
                        named[str(key)] = value
                if named:
                    set_deal_fields(conn, deal_id, actor=_ACTOR, fields=named)
                ctx = get_deal_context(conn, deal_id)
                return tool_result(success=True, applied=fields, gate=_gate_brief(ctx))

            if action == "attach":
                kind = str(args.get("kind") or "").strip()
                file_path = str(args.get("file_path") or args.get("filePath") or "").strip()
                if not kind or not file_path:
                    return tool_error("attach requires 'kind' and 'file_path'")
                att = add_deal_attachment(
                    conn,
                    deal_id,
                    kind=kind,
                    file_path=file_path,
                    summary=args.get("summary"),
                    actor=_ACTOR,
                )
                ctx = get_deal_context(conn, deal_id)
                return tool_result(
                    success=True,
                    attachment={"kind": att.get("kind"), "filePath": att.get("filePath")},
                    gate=_gate_brief(ctx),
                )

            if action == "advance":
                ctx = get_deal_context(conn, deal_id)
                gate = ((ctx.get("dealFlow") or {}).get("gate") or {})
                next_stage = gate.get("nextStage")
                force = _parse_bool(args.get("force"))
                if next_stage is None:
                    return tool_result(
                        success=False,
                        message="deal is already at the final stage",
                        gate=_gate_brief(ctx),
                    )
                if not force and not gate.get("canAdvance"):
                    return tool_result(
                        success=False,
                        message="phase gate is blocked — resolve the missing items first, or pass force=true",
                        gate=_gate_brief(ctx),
                    )
                move_deal_stage(
                    conn, deal_id,
                    to_stage=int(next_stage), actor=_ACTOR,
                    force=force, gate_checked=not force,
                )
                ctx = get_deal_context(conn, deal_id)
                return tool_result(success=True, advanced=True, gate=_gate_brief(ctx))

            if action == "complete_run":
                # Finalize the stage's pending run the way the cron callback does:
                # apply checklist updates + artifacts, clear the blocking run, and
                # let the gate auto-advance. This is the in-session equivalent of
                # the background run-result callback.
                from elevate_cli.data import list_action_runs, record_run_result

                run_id = str(args.get("run_id") or "").strip()
                skill_filter = str(args.get("skill") or "").strip().lower()
                if not run_id:
                    active = [
                        r for r in list_action_runs(conn, deal_id=deal_id)
                        if r.get("status") in {"running", "queued", "waiting_human", "waiting_external"}
                    ]
                    if skill_filter:
                        active = [r for r in active if skill_filter in str(r.get("skill") or "").lower()]
                    if not active:
                        return tool_error(
                            "no active run on this deal to complete; use set_checklist/set_fields/advance instead"
                        )
                    if len(active) > 1:
                        return tool_result(
                            success=False,
                            message="multiple active runs — pass run_id or skill to pick one",
                            runs=[{"id": r["id"], "skill": r.get("skill"), "status": r.get("status")} for r in active],
                        )
                    run_id = active[0]["id"]
                status = str(args.get("status") or "succeeded").strip()
                record_run_result(
                    conn, deal_id, run_id,
                    status=status,
                    idempotency_key=args.get("idempotency_key") or args.get("idempotencyKey"),
                    checklist_updates=args.get("checklist_updates") or args.get("checklistUpdates"),
                    artifacts=args.get("artifacts"),
                    human_prompt=args.get("human_prompt") or args.get("humanPrompt"),
                    actor=_ACTOR,
                )
                ctx = get_deal_context(conn, deal_id)
                return tool_result(success=True, completedRun=run_id, status=status, gate=_gate_brief(ctx))

            if action == "move":
                to_stage = args.get("to_stage")
                if to_stage is None:
                    return tool_error("move requires 'to_stage'")
                force = _parse_bool(args.get("force"))
                move_deal_stage(
                    conn, deal_id,
                    to_stage=int(to_stage), actor=_ACTOR,
                    force=force, gate_checked=not force,
                )
                ctx = get_deal_context(conn, deal_id)
                return tool_result(success=True, movedTo=int(to_stage), gate=_gate_brief(ctx))

            return tool_error(
                f"unknown action {action!r}; use one of: "
                "show, set_checklist, set_fields, attach, advance, move"
            )
    except LookupError as exc:
        return tool_error(str(exc))
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        return tool_error(f"{type(exc).__name__}: {exc}")


ADMIN_DEAL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "admin_deal",
        "description": (
            "Write a single real-estate deal's kanban card so a session "
            "finalizes the same way a background run does. Use after you've "
            "gathered what a skill needed (e.g. CMA list price) in the chat: "
            "write it to the deal and the board syncs live.\n\n"
            "Actions:\n"
            "- show: deal + gate (stage, what's missing, whether it can advance).\n"
            "- set_checklist: tick checklist/workflow cells — one (field + value) or many at once (cells map). Prefer the cells map when a stage completes several items.\n"
            "- set_fields: set named deal fields (listPrice, listingAddress, dates...).\n"
            "- attach: attach an artifact (kind + file_path).\n"
            "- complete_run: finalize the stage's pending run (applies checklist_updates "
            "+ artifacts, clears the blocking run, auto-advances). Use this to close out "
            "a skill the deal launched on stage entry — it's the in-session equivalent of "
            "the background result callback. Resolves the deal's active run automatically "
            "(or pass run_id / skill).\n"
            "- advance: move the card to the next stage when the gate is clear.\n"
            "- move: move to an explicit stage (use force=true to override the gate).\n\n"
            "A deal that entered a stage on its own has a pending run that BLOCKS the gate "
            "until done — use complete_run to close it, not force. Every write returns the "
            "updated gate. Approval-gated cells (stage-complete, listing-description-approved, "
            "photo-review) and any external send still need the realtor's explicit OK first — "
            "ask, then set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["show", "set_checklist", "set_fields", "attach", "complete_run", "advance", "move"],
                    "description": "Which board operation to run.",
                },
                "deal_id": {"type": "string", "description": "The deal id to operate on."},
                "field": {"type": "string", "description": "set_checklist: the checklist/workflow id to tick (single-cell form)."},
                "value": {"description": "set_checklist: the value (default true). Booleans tick cells; strings/dates fill workflow fields."},
                "cells": {"type": "object", "description": "set_checklist: { checklistId: value } to tick several cells in one call. Use instead of field/value when a stage completes multiple items."},
                "fields": {"type": "object", "description": "set_fields: { fieldName: value } of named deal fields."},
                "kind": {"type": "string", "description": "attach: artifact kind (e.g. cma_report, offer_pdf)."},
                "file_path": {"type": "string", "description": "attach: path to the artifact file."},
                "summary": {"type": "string", "description": "attach: short description of the artifact."},
                "run_id": {"type": "string", "description": "complete_run: explicit run id (else the deal's active run is used)."},
                "skill": {"type": "string", "description": "complete_run: pick the active run by skill when several are pending."},
                "status": {"type": "string", "enum": ["succeeded", "waiting_human", "failed", "skipped"], "description": "complete_run: run outcome. Default succeeded."},
                "checklist_updates": {"type": "array", "items": {"type": "object"}, "description": "complete_run: [{id, completed}] cells to tick."},
                "artifacts": {"type": "array", "items": {"type": "object"}, "description": "complete_run: [{kind, file_path, summary}] artifacts to attach."},
                "human_prompt": {"type": "object", "description": "complete_run: {title, message, requiredFields} when status is waiting_human."},
                "idempotency_key": {"type": "string", "description": "complete_run: stable key so retries don't duplicate."},
                "to_stage": {"type": "integer", "minimum": 0, "maximum": 10, "description": "move: target stage index."},
                "force": {"type": "boolean", "description": "advance/move: override the phase gate. Default false."},
            },
            "required": ["action", "deal_id"],
        },
    },
}


registry.register(
    name="admin_deal",
    toolset="admin_deal",
    schema=ADMIN_DEAL_SCHEMA,
    handler=_admin_deal_handler,
    description=(
        "Write a real-estate deal's kanban card (checklist, fields, artifacts, "
        "stage) so an in-session finalize syncs to the board."
    ),
    emoji="",
)
