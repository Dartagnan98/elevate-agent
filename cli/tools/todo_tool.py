#!/usr/bin/env python3
"""
Todo Tool Module - Planning & Task Management

Provides an in-memory task list the agent uses to decompose complex tasks,
track progress, and maintain focus across long conversations. The state
lives on the AIAgent instance (one per session) and is re-injected into
the conversation after context compression events.

Design:
- Single `todo` tool: provide `todos` param to write, omit to read
- Every call returns the full current list
- No system prompt mutation, no tool response modification
- Behavioral guidance lives entirely in the tool schema description
"""

import json
import re
from typing import Dict, Any, List, Optional


# Valid status values for todo items
VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
TODO_INJECTION_HEADER = "[Your active task list was preserved across context compression]"


class TodoStore:
    """
    In-memory todo list. One instance per AIAgent (one per session).

    Items are ordered -- list position is priority. Each item has:
      - id: unique string identifier (agent-chosen)
      - content: task description
      - status: pending | in_progress | completed | cancelled
    """

    def __init__(self):
        self._items: List[Dict[str, str]] = []

    def write(self, todos: List[Dict[str, Any]], merge: bool = False) -> List[Dict[str, str]]:
        """
        Write todos. Returns the full current list after writing.

        Args:
            todos: list of {id, content, status} dicts
            merge: if False, replace the entire list. If True, update
                   existing items by id and append new ones.
        """
        if not merge:
            # Replace mode: new list entirely
            self._items = [self._validate(t) for t in self._dedupe_by_id(todos)]
        else:
            # Merge mode: update existing items by id, append new ones
            existing = {item["id"]: item for item in self._items}
            for t in self._dedupe_by_id(todos):
                item_id = str(t.get("id", "")).strip()
                if not item_id:
                    continue  # Can't merge without an id

                if item_id in existing:
                    # Update only the fields the LLM actually provided
                    if "content" in t and t["content"]:
                        existing[item_id]["content"] = str(t["content"]).strip()
                    if "status" in t and t["status"]:
                        status = str(t["status"]).strip().lower()
                        if status in VALID_STATUSES:
                            existing[item_id]["status"] = status
                else:
                    # New item -- validate fully and append to end
                    validated = self._validate(t)
                    existing[validated["id"]] = validated
                    self._items.append(validated)
            # Rebuild _items preserving order for existing items
            seen = set()
            rebuilt = []
            for item in self._items:
                current = existing.get(item["id"], item)
                if current["id"] not in seen:
                    rebuilt.append(current)
                    seen.add(current["id"])
            self._items = rebuilt
        return self.read()

    def read(self) -> List[Dict[str, str]]:
        """Return a copy of the current list."""
        return [item.copy() for item in self._items]

    def has_items(self) -> bool:
        """Check if there are any items in the list."""
        return bool(self._items)

    def format_for_injection(self) -> Optional[str]:
        """
        Render the todo list for post-compression injection.

        Returns a human-readable string to append to the compressed
        message history, or None if the list is empty.
        """
        if not self._items:
            return None

        # Status markers for compact display
        markers = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
            "cancelled": "[~]",
        }

        # Only inject pending/in_progress items — completed/cancelled ones
        # cause the model to re-do finished work after compression.
        active_items = [
            item for item in self._items
            if item["status"] in {"pending", "in_progress"}
        ]
        if not active_items:
            return None

        lines = [TODO_INJECTION_HEADER]
        for item in active_items:
            marker = markers.get(item["status"], "[?]")
            lines.append(f"- {marker} {item['id']}. {item['content']} ({item['status']})")

        return "\n".join(lines)

    @staticmethod
    def _validate(item: Dict[str, Any]) -> Dict[str, str]:
        """
        Validate and normalize a todo item.

        Ensures required fields exist and status is valid.
        Returns a clean dict with only {id, content, status}.
        """
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            item_id = "?"

        content = str(item.get("content", "")).strip()
        if not content:
            content = "(no description)"

        status = str(item.get("status", "pending")).strip().lower()
        if status not in VALID_STATUSES:
            status = "pending"

        return {"id": item_id, "content": content, "status": status}

    @staticmethod
    def _dedupe_by_id(todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse duplicate ids, keeping the last occurrence in its position."""
        last_index: Dict[str, int] = {}
        for i, item in enumerate(todos):
            item_id = str(item.get("id", "")).strip() or "?"
            last_index[item_id] = i
        return [todos[i] for i in sorted(last_index.values())]


def parse_todo_injection(text: str) -> List[Dict[str, str]]:
    """Parse the human-readable post-compression todo snapshot.

    Fresh gateway agents rebuild TodoStore from history. After compaction the
    original JSON tool result may be summarized away, leaving only this
    injected checklist, so make the preserved context machine-readable again.
    """
    if not isinstance(text, str) or TODO_INJECTION_HEADER not in text:
        return []

    pattern = re.compile(
        r"^-\s*(\[[ x>~]\])\s+(.+?)\.\s+(.+)\s+\((pending|in_progress|completed|cancelled)\)\s*$"
    )
    items: List[Dict[str, str]] = []
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        _marker, item_id, content, status = match.groups()
        if status not in VALID_STATUSES:
            continue
        item_id = item_id.strip()
        content = content.strip()
        if item_id and content:
            items.append({"id": item_id, "content": content, "status": status})
    return TodoStore._dedupe_by_id(items)


def todo_tool(
    todos: Optional[List[Dict[str, Any]]] = None,
    merge: bool = False,
    store: Optional[TodoStore] = None,
) -> str:
    """
    Single entry point for the todo tool. Reads or writes depending on params.

    Args:
        todos: if provided, write these items. If None, read current list.
        merge: if True, update by id. If False (default), replace entire list.
        store: the TodoStore instance from the AIAgent.

    Returns:
        JSON string with the full current list and summary metadata.
    """
    if store is None:
        return tool_error("TodoStore not initialized")

    if todos is not None:
        items = store.write(todos, merge)
    else:
        items = store.read()

    # Build summary counts
    pending = sum(1 for i in items if i["status"] == "pending")
    in_progress = sum(1 for i in items if i["status"] == "in_progress")
    completed = sum(1 for i in items if i["status"] == "completed")
    cancelled = sum(1 for i in items if i["status"] == "cancelled")

    return json.dumps({
        "todos": items,
        "summary": {
            "total": len(items),
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "cancelled": cancelled,
        },
    }, ensure_ascii=False)


def check_todo_requirements() -> bool:
    """Todo tool has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================
# Behavioral guidance is baked into the description so it's part of the
# static tool schema (cached, never changes mid-conversation).

TODO_SCHEMA = {
    "name": "todo",
    "description": (
        "Manage your task list for the current session. Use for complex tasks "
        "with 3+ steps or when the user provides multiple tasks. "
        "Call with no parameters to read the current list.\n\n"
        "Writing:\n"
        "- Provide 'todos' array to create/update items\n"
        "- merge=false (default): replace the entire list with a fresh plan\n"
        "- merge=true: update existing items by id, add any new ones\n\n"
        "Each item: {id: string, content: string, "
        "status: pending|in_progress|completed|cancelled}\n"
        "List order is priority. Only ONE item in_progress at a time.\n"
        "Mark items completed immediately when done. If something fails, "
        "cancel it and add a revised item.\n\n"
        "Always returns the full current list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Task items to write. Omit to read current list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique item identifier"
                        },
                        "content": {
                            "type": "string",
                            "description": "Task description"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "Current status"
                        }
                    },
                    "required": ["id", "content", "status"]
                }
            },
            "merge": {
                "type": "boolean",
                "description": (
                    "true: update existing items by id, add new ones. "
                    "false (default): replace the entire list."
                ),
                "default": False
            }
        },
        "required": []
    }
}


# --- Registry ---
from tools.registry import registry, tool_error  # noqa: E402 — deliberate late import; registry imports tool modules
from tools.dispatch_companion import DispatchCompanion  # noqa: E402


# The per-session ``TodoStore`` is process state on the AIAgent, not tool-call
# data, so it can never ride through the registry's JSON-frozen
# argument/handler-kwargs snapshot.  Agent dispatch binds it here for exactly
# the duration of one registry shadow dispatch; the registered handler is the
# only consumer.  A caller that reaches the registered handler outside that
# binding (legacy ``registry.dispatch`` without an agent, plugin dispatch,
# hallucinated calls) sees ``None`` and gets ``todo_tool``'s long-standing
# "TodoStore not initialized" typed error — the plan store can never be
# reached outside the shadow-dispatch boundary.
_TODO_STORE_COMPANION = DispatchCompanion("active_todo_store")


def bind_todo_store(store):
    """Expose *store* to the registered todo handler for one dispatch."""
    return _TODO_STORE_COMPANION.bound(store)


def _registered_todo_handler(args, **_kwargs) -> str:
    """Register-time handler: sources the plan store from the companion.

    Handler kwargs are deliberately ignored — the registry's frozen
    handler-kwargs snapshot is JSON-only, so a ``TodoStore`` smuggled through
    dispatch kwargs (the old ``kw.get("store")`` seam) can never reach the
    plan store.  The companion is resolved eagerly here, never stored for
    lazy reads; a ``None`` result yields ``todo_tool``'s "TodoStore not
    initialized" error rather than guessing at ambient state.
    """
    args = args if isinstance(args, dict) else {}
    return todo_tool(
        todos=args.get("todos"),
        merge=args.get("merge", False),
        store=_TODO_STORE_COMPANION.get(),
    )


def dispatch_todo_via_registry(
    function_args,
    *,
    store,
    task_id=None,
    session_id=None,
    tool_call_id=None,
    return_outcome=False,
):
    """Route one todo invocation through the atomic registry boundary.

    Every agent special-case branch calls this instead of ``todo_tool``
    directly, so the call is captured with the same frozen identity,
    args-digest, and policy context as ordinary registry tools.  The plan
    store is bound only for the duration of this dispatch and only the
    registered handler can consume it.  ``return_outcome=True`` returns the
    adapter's :class:`ToolDispatchOutcome` (truthful physical-start proof
    for the exact-Beta loops); the default returns the raw result
    byte-identically.
    """
    from model_tools import dispatch_agent_owned_registry_tool

    return dispatch_agent_owned_registry_tool(
        "todo",
        function_args if isinstance(function_args, dict) else {},
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        companions=(bind_todo_store(store),),
        return_outcome=return_outcome,
    )


def _todo_effect_resolver(args: dict):
    """Classify todo calls against the per-session in-memory plan store.

    The todo list lives on the AIAgent's :class:`TodoStore` (one per
    session): the tool touches no filesystem, database, network, process,
    or cross-session state on any branch.  A call without a ``todos``
    payload only copies the current list, so it resolves to an exact
    ``read:session_plan``.  A call carrying ``todos`` (including an empty
    list, which replaces the plan) mutates that session-plan state and
    resolves to ``write_local:session_plan`` — the same capability the
    PLAN / DRAFT_ONLY policy ceilings already sanction for plan upkeep.
    The branch condition mirrors the handler exactly: the handler writes
    iff ``args.get("todos") is not None``.
    """
    if not isinstance(args, dict) or args.get("todos") is None:
        return {"read:session_plan"}
    return {"write_local:session_plan"}


registry.register(
    name="todo",
    toolset="todo",
    schema=TODO_SCHEMA,
    handler=_registered_todo_handler,
    check_fn=check_todo_requirements,
    emoji="📋",
    effect_resolver=_todo_effect_resolver,
)
