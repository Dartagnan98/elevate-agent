"""Outreach templates tool — the outreach skill calls this to pick + record templates."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def outreach_templates(
    action: str,
    lane: Optional[str] = None,
    template_id: Optional[str] = None,
    name: Optional[str] = None,
    body: Optional[str] = None,
    channel: Optional[str] = None,
    active: Optional[bool] = None,
    epsilon: Optional[float] = None,
    source_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    task_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
    outcome: Optional[str] = None,
    **_kw: Any,
) -> str:
    try:
        from elevate_cli import outreach_db
    except Exception as exc:
        return tool_error(f"outreach_db unavailable: {exc}")

    op = (action or "").strip().lower()
    try:
        if op in ("list", "list_templates", "templates"):
            data = outreach_db.list_templates(lane=lane)
            return json.dumps({"ok": True, "templates": data})

        if op in ("grouped", "list_grouped"):
            return json.dumps({"ok": True, "lanes": outreach_db.list_templates_grouped()})

        if op == "create":
            if not lane or not name or not body:
                return tool_error("create requires lane, name, body")
            tpl = outreach_db.create_template(
                lane=lane, name=name, body=body, channel=channel or "any"
            )
            return json.dumps({"ok": True, "template": tpl})

        if op == "update":
            if not template_id:
                return tool_error("update requires template_id")
            tpl = outreach_db.update_template(
                template_id,
                name=name,
                body=body,
                channel=channel,
                active=active,
            )
            return json.dumps({"ok": True, "template": tpl})

        if op == "delete":
            if not template_id:
                return tool_error("delete requires template_id")
            removed = outreach_db.delete_template(template_id)
            return json.dumps({"ok": removed})

        if op == "pick":
            if not lane:
                return tool_error("pick requires lane")
            tpl = outreach_db.pick_template(
                lane,
                channel=channel or "any",
                epsilon=0.2 if epsilon is None else float(epsilon),
            )
            if not tpl:
                return json.dumps({"ok": True, "template": None, "note": "no active templates for lane"})
            return json.dumps({"ok": True, "template": tpl})

        if op in ("record_use", "use", "record"):
            if not template_id or not lane:
                return tool_error("record_use requires template_id and lane")
            attempt = outreach_db.record_use(
                template_id,
                lane=lane,
                source_id=source_id,
                thread_id=thread_id,
                task_id=task_id,
            )
            return json.dumps({"ok": True, "attemptId": attempt})

        if op in ("record_outcome", "outcome"):
            if not attempt_id or not outcome:
                return tool_error("record_outcome requires attempt_id and outcome")
            return json.dumps({"ok": True, **outreach_db.record_outcome(attempt_id, outcome)})

        if op == "stats":
            return json.dumps({"ok": True, "stats": outreach_db.stats()})

        return tool_error(
            f"unknown action '{action}'. valid: list, grouped, create, update, delete, pick, record_use, record_outcome, stats"
        )
    except ValueError as exc:
        return tool_error(str(exc))
    except Exception as exc:
        logger.exception("outreach_templates failed")
        return tool_error(f"outreach_templates failed: {exc}")


OUTREACH_TEMPLATES_SCHEMA = {
    "name": "outreach_templates",
    "description": (
        "Manage outreach message templates per lane (new-outreach, hot-leads-watcher, follow-ups). "
        "The outreach skill uses pick → record_use → (later) record_outcome to learn which templates "
        "actually produce replies and won deals. Humans manage templates in the Templates tab on /leads."
        "\n\nActions:"
        "\n- list: list templates, optionally filtered by lane"
        "\n- grouped: all lanes in one shot, keyed by lane"
        "\n- create: add a template (lane + name + body required; supports {first_name}, {city}, {topic}, {source}, {area}, {signal})"
        "\n- update: change name/body/channel/active by template_id"
        "\n- delete: remove by template_id"
        "\n- pick: epsilon-greedy choose a template for a lane (untried first, then best win-rate, sometimes random)"
        "\n- record_use: log that a template was used to draft a message (returns attempt_id)"
        "\n- record_outcome: mark attempt 'replied' | 'won' | 'lost' | 'no_response'"
        "\n- stats: counts of templates / attempts / replies"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list", "grouped", "create", "update", "delete",
                    "pick", "record_use", "record_outcome", "stats",
                ],
            },
            "lane": {
                "type": "string",
                "enum": ["new-outreach", "hot-leads-watcher", "follow-ups"],
                "description": "Outreach lane the template belongs to.",
            },
            "template_id": {"type": "string"},
            "name": {"type": "string"},
            "body": {"type": "string", "description": "Message body. Variables in {curly_braces} get filled by the agent."},
            "channel": {"type": "string", "description": "any | sms | email | dm. Defaults to any."},
            "active": {"type": "boolean"},
            "epsilon": {"type": "number", "description": "Exploration rate for pick. Default 0.2."},
            "source_id": {"type": "string"},
            "thread_id": {"type": "string"},
            "task_id": {"type": "string"},
            "attempt_id": {"type": "string"},
            "outcome": {
                "type": "string",
                "enum": ["replied", "won", "lost", "no_response"],
            },
        },
        "required": ["action"],
    },
}


def check_outreach_templates_requirements() -> bool:
    return True


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="outreach_templates",
    toolset="outreach",
    schema=OUTREACH_TEMPLATES_SCHEMA,
    handler=lambda args, **kw: outreach_templates(
        action=args.get("action", ""),
        lane=args.get("lane"),
        template_id=args.get("template_id"),
        name=args.get("name"),
        body=args.get("body"),
        channel=args.get("channel"),
        active=args.get("active"),
        epsilon=args.get("epsilon"),
        source_id=args.get("source_id"),
        thread_id=args.get("thread_id"),
        task_id=args.get("task_id"),
        attempt_id=args.get("attempt_id"),
        outcome=args.get("outcome"),
    ),
    check_fn=check_outreach_templates_requirements,
    emoji="✉️",
)
