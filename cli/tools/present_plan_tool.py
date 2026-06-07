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
from typing import Any, Dict, List, Optional, Tuple


PLAN_INJECTION_HEADER = (
    "[Your latest Plan panel plan was preserved across context compression "
    "- reference only, not a new request]"
)
_PLAN_MAX_CHARS = 24_000


def present_plan_tool(plan: str, title: Optional[str] = None) -> str:
    plan = (plan or "").strip()
    if not plan:
        return json.dumps({"error": "plan is required (a Markdown string)"})
    payload = {"plan": plan}
    if title:
        payload["title"] = str(title).strip()[:200]
    return json.dumps(payload)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _tool_name_by_call_id(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            call_id = str(tc.get("id") or "")
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            if call_id and name:
                names[call_id] = name
    return names


def _parse_plan_payload(content: Any) -> Optional[Tuple[str, Optional[str]]]:
    text = _content_text(content).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    plan = data.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        return None
    title = data.get("title")
    return plan.strip(), str(title).strip() if title else None


def _parse_plan_injection(content: Any) -> Optional[Tuple[str, Optional[str]]]:
    text = _content_text(content).strip()
    if not text.startswith(PLAN_INJECTION_HEADER):
        return None
    lines = text.splitlines()
    title: Optional[str] = None
    start_idx = 1
    if len(lines) > 1 and lines[1].startswith("Title: "):
        title = lines[1][len("Title: "):].strip() or None
        start_idx = 2
    while start_idx < len(lines) and not lines[start_idx].strip():
        start_idx += 1
    plan = "\n".join(lines[start_idx:]).strip()
    return (plan, title) if plan else None


def extract_latest_plan_from_messages(
    messages: List[Dict[str, Any]],
) -> Optional[Tuple[str, Optional[str]]]:
    """Return the latest Plan panel payload found in a transcript.

    Handles the desktop/gateway shapes we see in practice:
    - tool result messages with ``tool_name == "present_plan"``
    - tool result messages whose ``tool_call_id`` maps to an assistant
      ``present_plan`` call
    - already-injected plan snapshots from a prior compaction
    """
    call_names = _tool_name_by_call_id(messages)
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue

        injected = _parse_plan_injection(msg.get("content"))
        if injected:
            return injected

        if msg.get("role") != "tool":
            continue
        tool_name = str(msg.get("tool_name") or "")
        if not tool_name:
            tool_name = call_names.get(str(msg.get("tool_call_id") or ""), "")
        if tool_name and tool_name != "present_plan":
            continue

        parsed = _parse_plan_payload(msg.get("content"))
        if parsed and (
            tool_name == "present_plan"
            or '"plan"' in _content_text(msg.get("content"))
        ):
            return parsed
    return None


def _clip_plan_for_context(plan: str, max_chars: int) -> str:
    if len(plan) <= max_chars:
        return plan
    head_chars = int(max_chars * 0.65)
    tail_chars = max_chars - head_chars
    return (
        plan[:head_chars].rstrip()
        + (
            "\n\n...[plan truncated during context compression; the full plan "
            "remains in the Plan panel/session history]...\n\n"
        )
        + plan[-tail_chars:].lstrip()
    )


def format_latest_plan_for_injection(
    messages: List[Dict[str, Any]],
    *,
    max_chars: int = _PLAN_MAX_CHARS,
) -> Optional[str]:
    latest = extract_latest_plan_from_messages(messages)
    if not latest:
        return None
    plan, title = latest
    lines = [PLAN_INJECTION_HEADER]
    if title:
        lines.append(f"Title: {title[:200]}")
    lines.append("")
    lines.append(_clip_plan_for_context(plan, max_chars))
    return "\n".join(lines)


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
