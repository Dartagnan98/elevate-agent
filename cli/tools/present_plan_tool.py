"""present_plan tool — the agent's FULL, detailed plan for the Plan panel.

Unlike the terse `todo` checklist, this holds a rich Markdown plan (overview,
numbered steps with concrete specs, considerations / risks, open questions)
that renders in the chat's Plan side panel for review and approval.

The handler echoes the plan back as its JSON result. That result is stored
untruncated in the session message history, and
``GET /api/sessions/{id}/plan`` reads the most recent one for the panel.
"""

from __future__ import annotations

import json
from typing import Optional


def present_plan_tool(plan: str, title: Optional[str] = None) -> str:
    plan = (plan or "").strip()
    if not plan:
        return json.dumps({"error": "plan is required (a Markdown string)"})
    payload = {"plan": plan}
    if title:
        payload["title"] = str(title).strip()[:200]
    return json.dumps(payload)


PRESENT_PLAN_SCHEMA = {
    "name": "present_plan",
    "description": (
        "Present your FULL, detailed plan for the current task — it renders in "
        "the user's Plan panel for review and approval. Use this in plan mode "
        "(or whenever the user wants to see the plan before you execute).\n\n"
        "Pass `plan` as rich Markdown — this is the SPEC, not a checklist:\n"
        "- A short overview paragraph (approach + key trade-off).\n"
        "- Numbered steps, each with concrete detail: exactly what you'll do, "
        "which files / tools / endpoints / commands, inputs and outputs, and "
        "the acceptance criteria for that step.\n"
        "- A 'Considerations & risks' section.\n"
        "- An 'Open questions' section for anything you need the user to "
        "confirm.\n\n"
        "Be specific and thorough. Call again to replace it with a revised "
        "plan after the user gives feedback."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": (
                    "The full plan as Markdown: overview + detailed numbered "
                    "steps with specs + considerations/risks + open questions."
                ),
            },
            "title": {
                "type": "string",
                "description": "Optional short title for the plan.",
            },
        },
        "required": ["plan"],
    },
}


# --- Registry (top-level call so the module is auto-discovered) ---
from tools.registry import registry  # noqa: E402

registry.register(
    name="present_plan",
    toolset="todo",
    schema=PRESENT_PLAN_SCHEMA,
    handler=lambda args, **kw: present_plan_tool(
        plan=args.get("plan", ""), title=args.get("title")
    ),
    emoji="🧭",
)
