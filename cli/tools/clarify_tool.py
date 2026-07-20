#!/usr/bin/env python3
"""
Clarify Tool Module - Interactive Clarifying Questions

Allows the agent to present structured multiple-choice questions or open-ended
prompts to the user. In CLI mode, choices are navigable with arrow keys. On
messaging platforms, choices are rendered as a numbered list.

The actual user-interaction logic lives in the platform layer (cli.py for CLI,
gateway/run.py for messaging). This module defines the schema, validation, and
a thin dispatcher that delegates to a platform-provided callback.
"""

import json
from typing import List, Optional, Callable

from tools.dispatch_companion import DispatchCompanion
from tools.registry import registry, tool_error


# Maximum number of predefined choices the agent can offer.
# A 5th "Other (type your answer)" option is always appended by the UI.
MAX_CHOICES = 4

# The platform-provided UI callback is process state, not tool-call data, so it
# can never ride through the registry's JSON-frozen argument/handler-kwargs
# snapshot.  Agent dispatch binds it here for exactly the duration of one
# registry shadow dispatch; the registered handler is the only consumer.  A
# caller that reaches the registered handler outside that binding (legacy
# ``registry.dispatch`` without an agent, plugin dispatch, hallucinated calls)
# gets the long-standing "not available" typed error and the callback can
# never run outside the shadow-dispatch boundary.
_CLARIFY_CALLBACK_COMPANION = DispatchCompanion("active_clarify_callback")


def bind_clarify_callback(callback: Optional[Callable]):
    """Expose *callback* to the registered clarify handler for one dispatch."""
    return _CLARIFY_CALLBACK_COMPANION.bound(callback)


def _registered_clarify_handler(args, **_kwargs) -> str:
    """Register-time handler: consumes only the bound platform callback.

    Handler kwargs are deliberately ignored — the registry's frozen
    handler-kwargs snapshot is JSON-only, so a callable smuggled through
    dispatch kwargs must never reach the callback seam.  The companion is
    resolved eagerly here, never stored for lazy reads.
    """
    args = args if isinstance(args, dict) else {}
    return clarify_tool(
        question=args.get("question", ""),
        choices=args.get("choices"),
        callback=_CLARIFY_CALLBACK_COMPANION.get(),
    )


def dispatch_clarify_via_registry(
    function_args,
    *,
    callback: Optional[Callable],
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    return_outcome: bool = False,
):
    """Route one clarify invocation through the atomic registry boundary.

    Every agent special-case branch calls this instead of ``clarify_tool``
    directly, so the call is captured with the same frozen identity,
    args-digest, and policy context as ordinary registry tools.  The UI
    callback is bound only for the duration of this dispatch and only the
    registered handler can consume it.  ``return_outcome=True`` returns the
    adapter's :class:`ToolDispatchOutcome` (truthful physical-start proof
    for the exact-Beta loops); the default returns the raw result
    byte-identically.
    """
    from model_tools import dispatch_agent_owned_registry_tool

    return dispatch_agent_owned_registry_tool(
        "clarify",
        function_args if isinstance(function_args, dict) else {},
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        companions=(bind_clarify_callback(callback),),
        return_outcome=return_outcome,
    )


def clarify_tool(
    question: str,
    choices: Optional[List[str]] = None,
    callback: Optional[Callable] = None,
) -> str:
    """
    Ask the user a question, optionally with multiple-choice options.

    Args:
        question: The question text to present.
        choices:  Up to 4 predefined answer choices. When omitted the
                  question is purely open-ended.
        callback: Platform-provided function that handles the actual UI
                  interaction. Signature: callback(question, choices) -> str.
                  Injected by the agent runner (cli.py / gateway).

    Returns:
        JSON string with the user's response.
    """
    if not question or not question.strip():
        return tool_error("Question text is required.")

    question = question.strip()

    # Validate and trim choices
    if choices is not None:
        if not isinstance(choices, list):
            return tool_error("choices must be a list of strings.")
        choices = [str(c).strip() for c in choices if str(c).strip()]
        if len(choices) > MAX_CHOICES:
            choices = choices[:MAX_CHOICES]
        if not choices:
            choices = None  # empty list → open-ended

    if callback is None:
        return json.dumps(
            {"error": "Clarify tool is not available in this execution context."},
            ensure_ascii=False,
        )

    try:
        user_response = callback(question, choices)
    except Exception as exc:
        return json.dumps(
            {"error": f"Failed to get user input: {exc}"},
            ensure_ascii=False,
        )

    return json.dumps({
        "question": question,
        "choices_offered": choices,
        "user_response": str(user_response).strip(),
    }, ensure_ascii=False)


def check_clarify_requirements() -> bool:
    """Clarify tool has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

CLARIFY_SCHEMA = {
    "name": "clarify",
    "description": (
        "Ask the user a question when you need clarification, feedback, or a "
        "decision before proceeding. Supports two modes:\n\n"
        "1. **Multiple choice** — provide up to 4 choices. The user picks one "
        "or types their own answer via a 5th 'Other' option.\n"
        "2. **Open-ended** — omit choices entirely. The user types a free-form "
        "response.\n\n"
        "Use this tool when:\n"
        "- The task is ambiguous and you need the user to choose an approach\n"
        "- You want post-task feedback ('How did that work out?')\n"
        "- You want to offer to save a skill or update memory\n"
        "- A decision has meaningful trade-offs the user should weigh in on\n\n"
        "Do NOT use this tool for simple yes/no confirmation of dangerous "
        "commands (the terminal tool handles that). Prefer making a reasonable "
        "default choice yourself when the decision is low-stakes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to present to the user.",
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_CHOICES,
                "description": (
                    "Up to 4 answer choices. Omit this parameter entirely to "
                    "ask an open-ended question. When provided, the UI "
                    "automatically appends an 'Other (type your answer)' option."
                ),
            },
        },
        "required": ["question"],
    },
}


# --- Registry ---
registry.register(
    name="clarify",
    toolset="clarify",
    schema=CLARIFY_SCHEMA,
    handler=_registered_clarify_handler,
    check_fn=check_clarify_requirements,
    emoji="❓",
)
