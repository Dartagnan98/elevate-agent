#!/usr/bin/env python3
"""Registry-routed dispatch for context-engine (``lcm_*``) tools.

The agent loop historically dispatched context-engine tools (``lcm_grep``,
``lcm_describe``, ``lcm_expand``, … — whatever the active
:class:`~agent.context_engine.ContextEngine` announces through
``get_tool_schemas()``) straight into
``context_compressor.handle_tool_call(name, args, messages=messages)``,
bypassing the atomic registry shadow boundary entirely.  This module moves
that lane onto the common adapter (``model_tools.dispatch_agent_owned_registry_tool``,
ERB-406 step 4 / package A2a; per-lane recipe in
``elevate-a2b-migration-recipe-2026-07-17.md``) so every invocation is
captured with a frozen registration identity, canonical args digest, and
accepted-turn policy context exactly like ordinary registry tools.

Process state — the live context-engine instance AND the mutable in-memory
``messages`` list the handler ingests/rewrites — can never ride in the
registry's JSON snapshots (they are rejected by canonicalization on purpose,
and the ``messages`` list is huge and mutated in place).  Both ride together
through one dispatch-scoped :class:`~tools.dispatch_companion.DispatchCompanion`
holding a small immutable binding struct.  The registered handler resolves
that companion EAGERLY at handler start and never stores it for a lazy read.

Effect honesty (ERB-404 doctrine; declaration != allowance): a context-engine
tool mutates conversation/compression state by design and no pure-read path
has been proven for any of them, so every tool is registered with NO effect
declaration (``effects=None`` -> UNKNOWN).  A restricted accepted-turn policy
therefore fails closed on these tools under exact Realtor Beta instead of
assuming a read.  The lane is naturally inert on the built-in compressor
(which announces no tools) and on any Beta build without a plugin context
engine; the declaration is defensive for the day one is present.

Schemas are advertised to the model directly by ``run_agent`` (the tool
schemas are appended to ``self.tools`` at agent init), so the registry
toolset ``context-engine`` is listed in ``toolsets.HIDDEN_REGISTRY_TOOLSETS``:
its process-global registrations never surface through generic toolset
enumeration or ``get_tool_definitions`` — schema visibility is owned entirely
by the context-engine subsystem, never duplicated by toolset listing.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, NamedTuple, Optional

from tools.dispatch_companion import DispatchCompanion
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

# Dispatch-only registry toolset for context-engine tools.  Hidden (see
# ``toolsets.HIDDEN_REGISTRY_TOOLSETS``) so registering these tools never
# leaks their schemas through toolset enumeration; the model already sees
# them via ``run_agent``'s direct schema injection.
CONTEXT_ENGINE_TOOLSET = "context-engine"

# Serializes the get_entry()-then-register() sequence below.  Registration is
# process-global and idempotent, so the unlocked race was benign (a second
# thread could only re-run an idempotent register), but the lock makes the
# check-and-register atomic instead of relying on that reasoning — matching
# the memory-provider lane's ``_REGISTRY_ROUTED_REGISTRATION_LOCK``.
_REGISTRY_ROUTED_REGISTRATION_LOCK = threading.Lock()

_CONTEXT_ENGINE_COMPANION = DispatchCompanion("active_context_engine")


class _ContextEngineBinding(NamedTuple):
    """One dispatch's worth of context-engine process state.

    ``engine`` is the live context-engine instance; ``messages`` is the SAME
    mutable in-memory conversation list the agent loop is processing (bound by
    reference, never serialized — the handler ingests/rewrites it in place).
    """

    engine: Any
    messages: Any


def bind_active_context_engine(engine: Any, messages: Any):
    """Expose *engine* + *messages* to the registered handler for one dispatch."""
    return _CONTEXT_ENGINE_COMPANION.bound(_ContextEngineBinding(engine, messages))


def _registry_routed_context_engine_tool_handler(tool_name: str):
    """Build the registered handler for one context-engine tool.

    The companion is resolved eagerly at handler start, never stored for lazy
    reads.  ``**_kwargs`` (the JSON handler-kwargs snapshot: ``task_id`` /
    ``user_task`` / ``enabled_tools``) is ignored for process state so nothing
    smuggled through dispatch kwargs can reach the engine or the ``messages``
    list — those ride exclusively through the companion.

    The engine's ``handle_tool_call`` exception is swallowed into the exact
    legacy branch payload (``{"error": "Context engine tool '<name>'
    failed: …"}``) and logged with the exact legacy message so byte-identical
    caller behavior is preserved: the registry never sees the exception (which
    would otherwise produce its generic ``Tool execution failed`` payload).
    """

    def _handler(args, **_kwargs) -> str:
        binding = _CONTEXT_ENGINE_COMPANION.get()
        if binding is None or binding.engine is None:
            return tool_error(
                f"Context engine tool '{tool_name}' has no active context "
                "engine in this execution context."
            )
        try:
            return binding.engine.handle_tool_call(
                tool_name,
                args if isinstance(args, dict) else {},
                messages=binding.messages,
            )
        except Exception as tool_error_exc:  # noqa: BLE001 - parity with branch
            logger.error(
                "context_engine.handle_tool_call raised for %s: %s",
                tool_name,
                tool_error_exc,
                exc_info=True,
            )
            return json.dumps(
                {
                    "error": (
                        f"Context engine tool '{tool_name}' failed: "
                        f"{tool_error_exc}"
                    )
                }
            )

    return _handler


def ensure_registry_routed_context_engine_tool(
    name: str, schema: Dict[str, Any]
) -> None:
    """Idempotently register one context-engine tool onto the atomic boundary.

    Registered with NO effect declaration (``effects=None`` -> UNKNOWN): no
    pure-read path is proven for any context-engine tool, so a restricted
    accepted-turn policy denies it — the honest, fail-closed state (ERB-404).

    A name that collides with an entry from a DIFFERENT toolset is left alone
    (not re-registered under ``context-engine``): such a tool keeps the direct
    engine path in :func:`dispatch_context_engine_tool_via_registry` so a
    context-engine tool never silently dispatches to an unrelated core tool.
    """
    if not name or not isinstance(schema, dict):
        return
    with _REGISTRY_ROUTED_REGISTRATION_LOCK:
        existing = registry.get_entry(name)
        if existing is not None:
            if existing.toolset != CONTEXT_ENGINE_TOOLSET:
                logger.warning(
                    "Context engine tool '%s' name collides with an existing "
                    "'%s' registry entry; leaving it on the direct engine path.",
                    name,
                    existing.toolset,
                )
            return
        try:
            registry.register(
                name=name,
                toolset=CONTEXT_ENGINE_TOOLSET,
                schema=dict(schema),
                handler=_registry_routed_context_engine_tool_handler(name),
                is_async=False,
                description=str(schema.get("description") or ""),
                effects=None,
                effect_resolver=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not register context engine tool '%s' in the tool "
                "registry: %s",
                name,
                exc,
            )


def ensure_registry_routed_context_engine_tools(engine: Any) -> None:
    """Idempotently register every tool *engine* announces.

    Registration failure for any one tool (malformed schema, engine inventory
    error) is swallowed so the direct-dispatch fallback in
    :func:`dispatch_context_engine_tool_via_registry` still handles it.
    """
    if engine is None:
        return
    try:
        schemas: List[Any] = engine.get_tool_schemas()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Context engine get_tool_schemas() failed during registry "
            "registration: %s",
            exc,
        )
        return
    for schema in schemas:
        if isinstance(schema, dict):
            name = schema.get("name") or ""
            if name:
                ensure_registry_routed_context_engine_tool(name, schema)


def dispatch_context_engine_tool_via_registry(
    engine: Any,
    messages: Any,
    function_name: str,
    function_args: Dict[str, Any],
    *,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> str:
    """Route one context-engine tool through the atomic shadow boundary.

    The engine + live ``messages`` list are bound only for the duration of
    this dispatch, so the registered handler cannot reach engine state outside
    the shadow boundary.  The routed entry must belong to the
    ``context-engine`` toolset — if registration is genuinely impossible
    (malformed engine schema) or the tool name collides with an unrelated
    toolset's entry, the direct engine path is preserved (byte-identical to
    the pre-migration branch: the raw ``handle_tool_call`` call, whose
    exceptions propagate to the caller's branch wrapper) and the routing gap
    is logged instead of dispatching to the wrong handler.
    """
    if engine is None:
        return tool_error(
            f"No context engine handles tool '{function_name}'"
        )
    # Tools are registered once at agent init (announce time). Only re-enumerate
    # the engine's schemas when this tool is not yet registered — the common
    # case is a cheap ``get_entry`` hit. A pre-existing entry from a DIFFERENT
    # toolset (name collision) is left untouched and handled by the guard below.
    entry = registry.get_entry(function_name)
    if entry is None:
        ensure_registry_routed_context_engine_tools(engine)
        entry = registry.get_entry(function_name)
    if entry is None or entry.toolset != CONTEXT_ENGINE_TOOLSET:
        logger.warning(
            "Registry routing unavailable for context engine tool '%s' "
            "(entry=%s); using direct engine dispatch",
            function_name,
            None if entry is None else entry.toolset,
        )
        return engine.handle_tool_call(
            function_name, function_args, messages=messages
        )

    from model_tools import dispatch_agent_owned_registry_tool

    return dispatch_agent_owned_registry_tool(
        function_name,
        function_args,
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        companions=(bind_active_context_engine(engine, messages),),
    )
