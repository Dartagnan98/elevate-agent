"""Central registry for all hermes-agent tools.

Each tool file calls ``registry.register()`` at module level to declare its
schema, handler, toolset membership, and availability check.  ``model_tools.py``
queries the registry instead of maintaining its own parallel data structures.

Import chain (circular-import safe):
    tools/registry.py  (no imports from model_tools or tool files)
           ^
    tools/*.py  (import from tools.registry at module level)
           ^
    model_tools.py  (imports tools.registry + all tool modules)
           ^
    run_agent.py, cli.py, batch_runner.py, etc.
"""

import ast
import hashlib
import importlib
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def _exact_beta_effect_enforcement_active() -> bool:
    """Return whether every registry start must honor accepted-turn effects.

    Keep the policy import lazy because the registry is imported during early
    CLI startup.  The environment fallback keeps a partially installed Beta
    fail closed without changing Stable's legacy dispatch behavior.
    """
    try:
        from elevate_cli.beta_provider_policy import beta_provider_policy_active

        return beta_provider_policy_active()
    except Exception:
        return os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"


def _normalize_function_schema(name: str, schema: dict) -> dict:
    """Store one canonical inner function schema.

    Most callers register ``{name, description, parameters}``, but a small
    legacy set passes the complete OpenAI ``{type, function}`` envelope.  The
    registry owns that envelope, so unwrap it once and reject deeper nesting
    instead of emitting ``function.function`` to providers.
    """
    if not isinstance(schema, dict):
        raise TypeError(f"Tool '{name}' schema must be a dict")

    if schema.get("type") == "function" or "function" in schema:
        if schema.get("type") != "function" or not isinstance(schema.get("function"), dict):
            raise ValueError(f"Tool '{name}' has an invalid function wrapper")
        schema = schema["function"]

    if "function" in schema:
        raise ValueError(f"Tool '{name}' schema contains nested function.function")

    normalized = dict(schema)
    parameters = normalized.get("parameters")
    if isinstance(parameters, dict) and isinstance(parameters.get("required"), list):
        properties = parameters.get("properties")
        property_names = set(properties) if isinstance(properties, dict) else set()
        missing = [field for field in parameters["required"] if field not in property_names]
        if missing:
            raise ValueError(
                f"Tool '{name}' requires undeclared parameter(s): {', '.join(map(str, missing))}"
            )
    return normalized


def _is_registry_register_call(node: ast.AST) -> bool:
    """Return True when *node* is a ``registry.register(...)`` call expression."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "register"
        and isinstance(func.value, ast.Name)
        and func.value.id == "registry"
    )


def _module_registers_tools(module_path: Path) -> bool:
    """Return True when the module contains a top-level ``registry.register(...)`` call.

    Only inspects module-body statements so that helper modules which happen
    to call ``registry.register()`` inside a function are not picked up.
    """
    try:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
    except (OSError, SyntaxError):
        return False

    return any(_is_registry_register_call(stmt) for stmt in tree.body)


def discover_builtin_tools(tools_dir: Optional[Path] = None) -> List[str]:
    """Import built-in self-registering tool modules and return their module names."""
    tools_path = Path(tools_dir) if tools_dir is not None else Path(__file__).resolve().parent
    module_names = [
        f"tools.{path.stem}"
        for path in sorted(tools_path.glob("*.py"))
        if path.name not in {"__init__.py", "registry.py", "mcp_tool.py"}
        and _module_registers_tools(path)
    ]

    imported: List[str] = []
    for mod_name in module_names:
        try:
            importlib.import_module(mod_name)
            imported.append(mod_name)
        except Exception as e:
            logger.warning("Could not import tool module %s: %s", mod_name, e)
    return imported


class ToolEntry:
    """Metadata for a single registered tool."""

    __slots__ = (
        "entry_id", "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "is_async", "description", "emoji",
        "max_result_size_chars", "dynamic_schema_overrides",
        "effects", "effect_resolver",
    )

    def __init__(self, entry_id, name, toolset, schema, handler, check_fn,
                 requires_env, is_async, description, emoji,
                 max_result_size_chars=None, dynamic_schema_overrides=None,
                 effects=None, effect_resolver=None):
        # Unique within one ToolRegistry instance and never reused.  Unlike the
        # registry-wide generation, this changes only when this exact name is
        # registered again, so unrelated MCP/toolset churn does not invalidate
        # a prepared call.
        self.entry_id = entry_id
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env
        self.is_async = is_async
        self.description = description
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars
        # Optional zero-arg callable returning a dict of schema overrides
        # applied at get_definitions() time. Use for fields that depend on
        # runtime config (e.g. delegate_task's description must reflect the
        # user's current delegation.max_concurrent_children / max_spawn_depth
        # so the model isn't told the wrong limits). The callable is invoked
        # on every get_definitions() call; results are merged shallow on top
        # of the base schema before the {"type": "function", ...} wrap.
        self.dynamic_schema_overrides = dynamic_schema_overrides
        # Frozen static effect metadata plus an optional argument-dependent
        # resolver.  These are introspection-only until the live dispatch
        # adapters explicitly invoke the effect-policy evaluator.
        self.effects = effects
        self.effect_resolver = effect_resolver


_USE_CURRENT_EXECUTION_POLICY = object()


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """Durable identity bound to one accepted-turn tool invocation."""

    session_id: str
    invocation_id: str
    accepted_turn_id: str
    policy_revision: int

    def __post_init__(self) -> None:
        for field_name in ("session_id", "invocation_id", "accepted_turn_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            value = value.strip()
            if not value:
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        if isinstance(self.policy_revision, bool) or not isinstance(
            self.policy_revision,
            int,
        ):
            raise TypeError("policy_revision must be an integer")
        if self.policy_revision < 0:
            raise ValueError("policy_revision cannot be negative")


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    """Immutable shadow snapshot of one registry tool call.

    Canonical JSON is authoritative for arguments and supported handler kwargs.
    The resolver and handler receive fresh decodes, so a caller mutating either
    original object after preparation cannot change what was authorized or run.
    """

    tool_name: str
    context: ToolCallContext
    entry_id: Optional[int]
    registry_generation: int
    canonical_args_json: Optional[str]
    args_digest: Optional[str]
    canonical_handler_kwargs_json: Optional[str]
    handler_kwargs_digest: Optional[str]
    captured_handler: Optional[Callable] = field(repr=False, compare=False)
    captured_is_async: bool = False
    captured_effects: frozenset = frozenset()
    captured_effect_resolver: Optional[Callable] = field(
        default=None,
        repr=False,
        compare=False,
    )
    resolved_effects: frozenset = frozenset()
    execution_policy: Any = field(default=None, repr=False)
    authorization: Any = None
    preparation_error: Optional[str] = None
    effect_resolution_error: Optional[str] = None

    def thaw_args(self) -> dict:
        """Return a fresh mutable decode of the bound argument snapshot."""
        if self.canonical_args_json is None:
            raise ValueError("prepared call has no canonical argument snapshot")
        value = json.loads(self.canonical_args_json)
        if not isinstance(value, dict):  # defensive; preparation enforces this
            raise ValueError("prepared call argument snapshot is not an object")
        return value

    def thaw_handler_kwargs(self) -> dict:
        """Return fresh handler kwargs from the bound JSON snapshot."""
        if self.canonical_handler_kwargs_json is None:
            raise ValueError("prepared call has no handler-kwargs snapshot")
        value = json.loads(self.canonical_handler_kwargs_json)
        if not isinstance(value, dict):  # defensive; preparation enforces this
            raise ValueError("prepared handler kwargs are not an object")
        return value


@dataclass(frozen=True, slots=True)
class ShadowToolExecution:
    """Result of one atomic prepared execution and its start decision.

    ``effect_receipt`` is the in-process anchor
    (:class:`tools.effect_broker.ToolEffectReceiptRef`) to the durable
    claim/receipt trail when the exact-Beta effect broker engaged for this
    call, or ``None`` (read-only calls, refused starts, Stable dispatch).
    """

    prepared: PreparedToolCall
    result: Any
    started: bool
    start_generation: int
    stale_reason: Optional[str] = None
    execution_error: Optional[str] = None
    effect_receipt: Any = None


def _validate_json_value(value: Any, path: str = "$") -> None:
    """Reject Python values that do not have an exact JSON representation."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string object key")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise TypeError(f"{path} contains non-JSON value {type(value).__name__}")


def _canonicalize_tool_args(args: Any) -> tuple[str, str]:
    """Return canonical JSON and its SHA-256 digest for one args object."""
    if not isinstance(args, dict):
        raise TypeError("tool arguments must be a JSON object")
    _validate_json_value(args)
    canonical = json.dumps(
        args,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, digest


_SHADOW_HANDLER_KWARGS = frozenset({
    "task_id",
    "user_task",
    "enabled_tools",
    "session_id",
})


def _canonicalize_handler_kwargs(kwargs: Any) -> tuple[str, str]:
    """Freeze the JSON-safe model-tools context accepted by shadow dispatch."""
    if kwargs is None:
        kwargs = {}
    if not isinstance(kwargs, dict):
        raise TypeError("handler kwargs must be a JSON object")
    unexpected = sorted(
        (str(key) for key in kwargs if key not in _SHADOW_HANDLER_KWARGS)
    )
    if unexpected:
        raise ValueError(
            "unsupported handler kwargs: " + ", ".join(map(str, unexpected))
        )
    return _canonicalize_tool_args(kwargs)


# ---------------------------------------------------------------------------
# check_fn TTL cache
#
# check_fn callables like tools/terminal_tool.check_terminal_requirements
# probe external state (Docker daemon, Modal SDK install, playwright binary
# availability). For a long-lived CLI or gateway process, calling them on
# every get_definitions() is pure waste — external state changes on human
# timescales. Cache results for ~30 s so env-var flips via ``/tools``
# or live credential file changes propagate within a turn or two without
# requiring any explicit invalidation.
# ---------------------------------------------------------------------------

_CHECK_FN_TTL_SECONDS = 30.0
_check_fn_cache: Dict[Callable, tuple[float, bool]] = {}
_check_fn_cache_lock = threading.Lock()


def _check_fn_cached(fn: Callable) -> bool:
    """Return bool(fn()), TTL-cached across calls. Swallows exceptions as False."""
    now = time.monotonic()
    with _check_fn_cache_lock:
        cached = _check_fn_cache.get(fn)
        if cached is not None:
            ts, value = cached
            if now - ts < _CHECK_FN_TTL_SECONDS:
                return value
    try:
        value = bool(fn())
    except Exception:
        value = False
    with _check_fn_cache_lock:
        _check_fn_cache[fn] = (now, value)
    return value


def invalidate_check_fn_cache() -> None:
    """Drop all cached ``check_fn`` results. Call after config changes that
    affect tool availability (e.g. ``/tools enable``)."""
    with _check_fn_cache_lock:
        _check_fn_cache.clear()


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files."""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}
        self._toolset_aliases: Dict[str, str] = {}
        # MCP dynamic refresh can mutate the registry while other threads are
        # reading tool metadata, so keep mutations serialized and readers on
        # stable snapshots.
        self._lock = threading.RLock()
        # Monotonically-increasing generation counter. Bumped on every
        # mutation (register / deregister / register_toolset_alias / MCP
        # refresh). External callers (e.g. get_tool_definitions) can memoize
        # against it: a cache entry keyed on the generation is valid for as
        # long as the generation hasn't changed.
        self._generation: int = 0
        # Per-registration identity. Unlike ``_generation``, this is never
        # bumped by unrelated registry mutations and no value is ever reused.
        self._next_entry_id: int = 0

    def _snapshot_state(self) -> tuple[List[ToolEntry], Dict[str, Callable]]:
        """Return a coherent snapshot of registry entries and toolset checks."""
        with self._lock:
            return list(self._tools.values()), dict(self._toolset_checks)

    def _snapshot_entries(self) -> List[ToolEntry]:
        """Return a stable snapshot of registered tool entries."""
        return self._snapshot_state()[0]

    def _snapshot_toolset_checks(self) -> Dict[str, Callable]:
        """Return a stable snapshot of toolset availability checks."""
        return self._snapshot_state()[1]

    def _evaluate_toolset_check(self, toolset: str, check: Callable | None) -> bool:
        """Run a toolset check, treating missing or failing checks as unavailable/available."""
        if not check:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset %s check raised; marking unavailable", toolset)
            return False

    def get_entry(self, name: str) -> Optional[ToolEntry]:
        """Return a registered tool entry by name, or None."""
        with self._lock:
            return self._tools.get(name)

    def get_registered_toolset_names(self) -> List[str]:
        """Return sorted unique toolset names present in the registry."""
        return sorted({entry.toolset for entry in self._snapshot_entries()})

    def get_tool_names_for_toolset(self, toolset: str) -> List[str]:
        """Return sorted tool names registered under a given toolset."""
        return sorted(
            entry.name for entry in self._snapshot_entries()
            if entry.toolset == toolset
        )

    def register_toolset_alias(self, alias: str, toolset: str) -> None:
        """Register an explicit alias for a canonical toolset name."""
        with self._lock:
            existing = self._toolset_aliases.get(alias)
            if existing and existing != toolset:
                logger.warning(
                    "Toolset alias collision: '%s' (%s) overwritten by %s",
                    alias, existing, toolset,
                )
            self._toolset_aliases[alias] = toolset
            self._generation += 1

    def get_registered_toolset_aliases(self) -> Dict[str, str]:
        """Return a snapshot of ``{alias: canonical_toolset}`` mappings."""
        with self._lock:
            return dict(self._toolset_aliases)

    def get_toolset_alias_target(self, alias: str) -> Optional[str]:
        """Return the canonical toolset name for an alias, or None."""
        with self._lock:
            return self._toolset_aliases.get(alias)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Callable = None,
        requires_env: list = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: int | float | None = None,
        dynamic_schema_overrides: Callable = None,
        override: bool = False,
        effects=None,
        effect_resolver: Callable = None,
    ):
        """Register a tool.  Called at module-import time by each tool file.

        ``override=True`` is an explicit opt-in for plugins that intend to
        replace an existing built-in tool implementation (e.g. swap the
        default browser tool for a headed-Chrome CDP backend). Without it,
        registrations that would shadow an existing tool from a different
        toolset are rejected to prevent accidental overwrites.
        """
        with self._lock:
            existing = self._tools.get(name)
            if existing and existing.toolset != toolset:
                # Allow MCP-to-MCP overwrites (legitimate: server refresh,
                # or two MCP servers with overlapping tool names).
                both_mcp = (
                    existing.toolset.startswith("mcp-")
                    and toolset.startswith("mcp-")
                )
                if both_mcp:
                    logger.debug(
                        "Tool '%s': MCP toolset '%s' overwriting MCP toolset '%s'",
                        name, toolset, existing.toolset,
                    )
                elif override:
                    # Explicit plugin opt-in: replace the existing tool.
                    # Logged at INFO so the override is auditable in agent.log.
                    logger.info(
                        "Tool '%s': toolset '%s' overriding existing toolset '%s' "
                        "(override=True opt-in)",
                        name, toolset, existing.toolset,
                    )
                else:
                    # Reject shadowing — prevent plugins/MCP from overwriting
                    # built-in tools or vice versa.
                    logger.error(
                        "Tool registration REJECTED: '%s' (toolset '%s') would "
                        "shadow existing tool from toolset '%s'. Pass "
                        "override=True to register() if the replacement is "
                        "intentional, or deregister the existing tool first.",
                        name, toolset, existing.toolset,
                    )
                    return
            schema = _normalize_function_schema(name, schema)
            if effect_resolver is not None and not callable(effect_resolver):
                raise TypeError(f"Tool '{name}' effect_resolver must be callable")
            normalized_effects = None
            if effects is not None:
                from tools.approval import normalize_effects

                normalized_effects = normalize_effects(effects)
            self._next_entry_id += 1
            self._tools[name] = ToolEntry(
                entry_id=self._next_entry_id,
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
                dynamic_schema_overrides=dynamic_schema_overrides,
                effects=normalized_effects,
                effect_resolver=effect_resolver,
            )
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
            self._generation += 1

    def deregister(self, name: str) -> None:
        """Remove a tool from the registry.

        Also cleans up the toolset check if no other tools remain in the
        same toolset.  Used by MCP dynamic tool discovery to nuke-and-repave
        when a server sends ``notifications/tools/list_changed``.
        """
        with self._lock:
            entry = self._tools.pop(name, None)
            if entry is None:
                return
            # Drop the toolset check and aliases if this was the last tool in
            # that toolset.
            toolset_still_exists = any(
                e.toolset == entry.toolset for e in self._tools.values()
            )
            if not toolset_still_exists:
                self._toolset_checks.pop(entry.toolset, None)
                self._toolset_aliases = {
                    alias: target
                    for alias, target in self._toolset_aliases.items()
                    if target != entry.toolset
                }
            self._generation += 1
        logger.debug("Deregistered tool: %s", name)

    # ------------------------------------------------------------------
    # Schema retrieval
    # ------------------------------------------------------------------

    def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]:
        """Return OpenAI-format tool schemas for the requested tool names.

        Only tools whose ``check_fn()`` returns True (or have no check_fn)
        are included. ``check_fn()`` results are cached for ~30 s via
        :func:`_check_fn_cached` to amortize repeat probes (check_terminal_
        requirements probes modal/docker, browser checks probe playwright,
        etc.); TTL chosen so env-var changes (``/tools enable foo``)
        still take effect in near-real-time without forcing a full cache
        flush on every call.
        """
        result = []
        # Per-call cache on top of the 30 s TTL — handles repeat probes of the
        # same check_fn within one definitions pass without re-reading the
        # TTL clock.
        check_results: Dict[Callable, bool] = {}
        entries_by_name = {entry.name: entry for entry in self._snapshot_entries()}
        for name in sorted(tool_names):
            entry = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = _check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            # Ensure schema always has a "name" field — use entry.name as fallback
            schema_with_name = {**entry.schema, "name": entry.name}
            # Apply runtime-dynamic overrides (e.g. delegate_task description
            # depends on current delegation.max_concurrent_children /
            # max_spawn_depth). Caller side (model_tools.get_tool_definitions)
            # already keys its memo on config.yaml mtime + size, so changes
            # to delegation.* in config invalidate the cache automatically.
            if entry.dynamic_schema_overrides is not None:
                try:
                    overrides = entry.dynamic_schema_overrides()
                    if isinstance(overrides, dict):
                        schema_with_name.update(overrides)
                except Exception as exc:
                    logger.warning(
                        "dynamic_schema_overrides for tool %s raised %s; "
                        "using static schema",
                        name, exc,
                    )
            result.append({"type": "function", "function": schema_with_name})
        return result

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _prepare_shadow_call(
        self,
        name: str,
        args: Any,
        context: ToolCallContext,
        execution_policy: Any = _USE_CURRENT_EXECUTION_POLICY,
        *,
        handler_kwargs: Any = None,
    ) -> PreparedToolCall:
        """Freeze one registry entry, invocation inputs, effects, and policy.

        This is deliberately private: production callers continue to use
        :meth:`dispatch`.  Splitting preparation from start gives the race
        tests a deterministic seam without exposing a second public workflow.
        """
        from tools.approval import (
            Effect,
            EffectKind,
            ExecutionPolicy,
            authorize_effects,
            get_current_execution_policy,
            normalize_effects,
        )

        if not isinstance(context, ToolCallContext):
            raise TypeError("context must be a ToolCallContext")
        if execution_policy is _USE_CURRENT_EXECUTION_POLICY:
            execution_policy = get_current_execution_policy()
        elif execution_policy is not None and not isinstance(
            execution_policy,
            ExecutionPolicy,
        ):
            raise TypeError("execution_policy must be an ExecutionPolicy or None")
        if (
            execution_policy is not None
            and execution_policy.accepted_turn_id != context.accepted_turn_id
        ):
            raise ValueError(
                "context accepted_turn_id does not match execution policy"
            )

        with self._lock:
            generation = self._generation
            entry = self._tools.get(name)
            if entry is None:
                entry_id = None
                handler = None
                is_async = False
                static_effects = frozenset()
                effect_resolver = None
            else:
                entry_id = entry.entry_id
                handler = entry.handler
                is_async = bool(entry.is_async)
                static_effects = frozenset(entry.effects or ())
                effect_resolver = entry.effect_resolver

        canonical_args_json = None
        args_digest = None
        canonical_handler_kwargs_json = None
        handler_kwargs_digest = None
        preparation_error = "unknown_tool" if entry is None else None
        try:
            canonical_args_json, args_digest = _canonicalize_tool_args(args)
        except Exception as exc:
            if preparation_error is None:
                preparation_error = (
                    f"invalid_arguments:{type(exc).__name__}:{exc}"
                )
        try:
            canonical_handler_kwargs_json, handler_kwargs_digest = (
                _canonicalize_handler_kwargs(handler_kwargs)
            )
        except Exception as exc:
            if preparation_error is None:
                preparation_error = (
                    f"invalid_handler_context:{type(exc).__name__}:{exc}"
                )

        unknown_effect = Effect(EffectKind.UNKNOWN)
        resolved_effects = set(static_effects)
        effect_resolution_error = None
        if (
            entry is None
            or canonical_args_json is None
            or canonical_handler_kwargs_json is None
        ):
            resolved_effects.add(unknown_effect)
        elif effect_resolver is not None:
            try:
                dynamic_effects = normalize_effects(
                    effect_resolver(json.loads(canonical_args_json))
                )
            except Exception as exc:
                logger.warning("effect_resolver for tool %s raised %s", name, exc)
                dynamic_effects = frozenset({unknown_effect})
                effect_resolution_error = (
                    f"resolver_exception:{type(exc).__name__}:{exc}"
                )
            if not dynamic_effects:
                dynamic_effects = frozenset({unknown_effect})
                effect_resolution_error = "resolver_returned_no_effects"
            resolved_effects.update(dynamic_effects)
        if not resolved_effects:
            resolved_effects.add(unknown_effect)

        frozen_effects = frozenset(resolved_effects)
        authorization = authorize_effects(execution_policy, frozen_effects)
        return PreparedToolCall(
            tool_name=name,
            context=context,
            entry_id=entry_id,
            registry_generation=generation,
            canonical_args_json=canonical_args_json,
            args_digest=args_digest,
            canonical_handler_kwargs_json=canonical_handler_kwargs_json,
            handler_kwargs_digest=handler_kwargs_digest,
            captured_handler=handler,
            captured_is_async=is_async,
            captured_effects=static_effects,
            captured_effect_resolver=effect_resolver,
            resolved_effects=frozen_effects,
            execution_policy=execution_policy,
            authorization=authorization,
            preparation_error=preparation_error,
            effect_resolution_error=effect_resolution_error,
        )

    def prepare_shadow(
        self,
        name: str,
        args: Any,
        *,
        context: ToolCallContext,
        execution_policy: Any = _USE_CURRENT_EXECUTION_POLICY,
        handler_kwargs: Any = None,
    ) -> PreparedToolCall:
        """Freeze and authorize one call without running hooks or a handler.

        Exact-Beta adapters use this as their first, side-effect-free gate.  A
        separately exposed start operation lets them keep the exact policy,
        registry entry, arguments, and handler context that passed that gate.
        """
        return self._prepare_shadow_call(
            name,
            args,
            context,
            execution_policy,
            handler_kwargs=handler_kwargs,
        )

    def _shadow_start_error(
        self,
        prepared: PreparedToolCall,
        code: str,
        detail: str,
        *,
        stale_reason: Optional[str] = None,
    ) -> ShadowToolExecution:
        """Build a deterministic non-start result for the shadow primitive."""
        with self._lock:
            generation = self._generation
        return ShadowToolExecution(
            prepared=prepared,
            result=json.dumps({"error": detail, "shadow_status": code}),
            started=False,
            start_generation=generation,
            stale_reason=stale_reason,
        )

    def _start_prepared_shadow(
        self,
        prepared: PreparedToolCall,
    ) -> ShadowToolExecution:
        """Revalidate entry identity, then run exactly the captured handler."""
        if prepared.preparation_error == "unknown_tool":
            return self._shadow_start_error(
                prepared,
                "unknown_tool",
                f"Unknown tool: {prepared.tool_name}",
            )
        if prepared.preparation_error is not None:
            status = (
                "invalid_handler_context"
                if prepared.preparation_error.startswith("invalid_handler_context:")
                else "invalid_arguments"
            )
            return self._shadow_start_error(
                prepared,
                status,
                prepared.preparation_error,
            )

        # This locked identity check is the start linearization point. A later
        # replacement cannot swap in its handler; an earlier one prevents this
        # prepared call from starting. Global generation is diagnostic only.
        with self._lock:
            current = self._tools.get(prepared.tool_name)
            start_generation = self._generation
            if current is None:
                stale_reason = "deregistered"
            elif current.entry_id != prepared.entry_id:
                stale_reason = "entry_replaced"
            elif (
                current.handler is not prepared.captured_handler
                or bool(current.is_async) != prepared.captured_is_async
                or frozenset(current.effects or ()) != prepared.captured_effects
                or current.effect_resolver is not prepared.captured_effect_resolver
            ):
                # ``get_entry`` is a long-standing public API and returns the
                # live ToolEntry object. Until that compatibility surface can
                # return an immutable view, direct field mutation must be
                # treated exactly like replacement so it cannot change what
                # was authorized without rotating the registration identity.
                stale_reason = "entry_mutated"
            else:
                stale_reason = None

        if stale_reason is not None:
            return ShadowToolExecution(
                prepared=prepared,
                result=json.dumps({
                    "error": (
                        "Prepared tool registration is stale: "
                        f"{prepared.tool_name}"
                    ),
                    "shadow_status": "stale_registration",
                    "reason": stale_reason,
                }),
                started=False,
                start_generation=start_generation,
                stale_reason=stale_reason,
            )

        exact_beta = _exact_beta_effect_enforcement_active()
        if exact_beta and prepared.tool_name == "terminal":
            # Realtor Beta does not ship terminal capability.  Enforce that at
            # the atomic registry start boundary as well as model schema and
            # preflight boundaries so direct prepared-call users cannot revive
            # it with an otherwise-allowing read policy.
            return self._shadow_start_error(
                prepared,
                "effect_policy_block",
                "Terminal is unavailable in Realtor Beta.",
            )
        if exact_beta and not prepared.authorization.allowed:
            return self._shadow_start_error(
                prepared,
                "effect_policy_block",
                "Tool effect blocked by the accepted-turn policy: "
                f"{prepared.authorization.reason}",
            )

        # Exact Beta binds every beyond-read start to a durable one-winner
        # claim and a terminal receipt (the ``0bbb80997`` terminal machinery
        # generalized to the whole registry shadow path).  A refused claim —
        # duplicate invocation identity, failed revalidation, or an
        # unavailable store — fails closed before the handler can run.
        # Stable dispatch never reaches this block (byte parity).
        effect_claim = None
        if exact_beta:
            from tools.effect_broker import (
                acquire_prepared_effect_claim,
                claim_required_for_effects,
            )

            if claim_required_for_effects(prepared.resolved_effects):
                decision = acquire_prepared_effect_claim(prepared)
                if decision.claim is None:
                    return self._shadow_start_error(
                        prepared,
                        decision.status_code,
                        decision.detail,
                    )
                effect_claim = decision.claim

        execution_error = None
        invocation_outcome_unknowable = False
        try:
            handler = prepared.captured_handler
            if handler is None:  # defensive; a valid entry always has one
                raise RuntimeError("prepared call has no captured handler")
            args = prepared.thaw_args()
            handler_kwargs = prepared.thaw_handler_kwargs()
            if prepared.captured_is_async:
                from model_tools import _run_async

                result = _run_async(handler(args, **handler_kwargs))
            else:
                result = handler(args, **handler_kwargs)
        except Exception as exc:
            logger.exception(
                "Tool %s shadow execution error: %s",
                prepared.tool_name,
                exc,
            )
            raw = f"Tool execution failed: {type(exc).__name__}: {exc}"
            try:
                from model_tools import _sanitize_tool_error

                sanitized = _sanitize_tool_error(raw)
            except Exception:
                sanitized = raw
            execution_error = f"handler_exception:{type(exc).__name__}"
            result = json.dumps({"error": sanitized})
            # _run_async's running-loop branch ABANDONS its worker on
            # timeout: the coroutine may still be applying the effect.  A
            # 'failed' receipt would falsely assert the effect did not occur
            # and invite an automatic retry that double-applies on top of
            # the still-running abandoned write.  Terminalize this window as
            # 'unknown', exactly like the terminal tool's
            # invocation-started outcome handling.
            import concurrent.futures

            invocation_outcome_unknowable = isinstance(
                exc,
                concurrent.futures.TimeoutError,
            )
        except BaseException:
            # Cancellation / interpreter shutdown propagate, but the durable
            # trail must not be left in the claimed crash-window state when
            # this process survives: the outcome is genuinely unknowable.
            if effect_claim is not None:
                from tools.effect_broker import finish_effect_claim

                finish_effect_claim(
                    effect_claim,
                    status="unknown",
                    failure_code="execution_interrupted",
                )
            raise

        effect_receipt = None
        if effect_claim is not None:
            from tools.effect_broker import (
                ToolEffectReceiptRef,
                effect_outcome_unknown_payload,
                effect_receipt_unavailable_payload,
                finish_effect_claim,
                model_result_digest,
            )

            if execution_error is None:
                final_status = finish_effect_claim(
                    effect_claim,
                    status="succeeded",
                    result_identity=result,
                )
                if final_status != "succeeded":
                    # Receipt loss is never success: replace the handler's
                    # output with the typed unknown-outcome payload.
                    execution_error = "effect_receipt_unavailable"
                    result = effect_receipt_unavailable_payload(
                        prepared.tool_name
                    )
            elif invocation_outcome_unknowable:
                final_status = finish_effect_claim(
                    effect_claim,
                    status="unknown",
                    failure_code="execution_timeout_abandoned",
                )
                # The plain error text would invite an automatic retry under
                # a fresh invocation id; the typed do-not-retry payload is
                # the only honest model-visible outcome here.
                result = effect_outcome_unknown_payload(prepared.tool_name)
            else:
                final_status = finish_effect_claim(
                    effect_claim,
                    status="failed",
                    result_identity=result,
                    failure_code="handler_exception",
                )
            effect_receipt = ToolEffectReceiptRef(
                claim_id=effect_claim.claim_id,
                session_id=effect_claim.session_id,
                invocation_id=effect_claim.invocation_id,
                tool_name=effect_claim.tool_name,
                final_status=final_status,
                expected_result_digests=frozenset(
                    {model_result_digest(result)}
                ),
            )

        return ShadowToolExecution(
            prepared=prepared,
            result=result,
            started=True,
            start_generation=start_generation,
            execution_error=execution_error,
            effect_receipt=effect_receipt,
        )

    def execute_prepared_shadow(
        self,
        prepared: PreparedToolCall,
    ) -> ShadowToolExecution:
        """Revalidate and start one call frozen by :meth:`prepare_shadow`."""
        if not isinstance(prepared, PreparedToolCall):
            raise TypeError("prepared must be a PreparedToolCall")
        return self._start_prepared_shadow(prepared)

    def execute_shadow(
        self,
        name: str,
        args: Any,
        *,
        context: ToolCallContext,
        execution_policy: Any = _USE_CURRENT_EXECUTION_POLICY,
        handler_kwargs: Any = None,
    ) -> ShadowToolExecution:
        """Exercise the atomic registry path with a frozen call snapshot.

        Stable retains observational authorization behavior. Exact Realtor
        Beta enforces every denied/unknown effect before its handler starts;
        terminal additionally requires its durable approval-effect context.
        """
        prepared = self.prepare_shadow(
            name,
            args,
            context=context,
            execution_policy=execution_policy,
            handler_kwargs=handler_kwargs,
        )
        return self.execute_prepared_shadow(prepared)

    def dispatch(self, name: str, args: dict, **kwargs) -> str:
        """Execute a tool handler by name.

        Exact Realtor Beta disables this legacy, non-atomic adapter entirely.
        Beta callers must use ``prepare_shadow`` + ``execute_prepared_shadow``
        so the entry, arguments, effects, policy identity, and start decision
        are revalidated together under the registry lock.

        * Async handlers are bridged automatically via ``_run_async()``.
        * All exceptions are caught and returned as ``{"error": "..."}``
          for consistent error format.
        """
        if _exact_beta_effect_enforcement_active():
            return json.dumps(
                {
                    "error": (
                        "Legacy tool dispatch is unavailable in exact Realtor "
                        "Beta; use the prepared atomic execution path."
                    ),
                    "shadow_status": "legacy_dispatch_block",
                }
            )
        entry = self.get_entry(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            if entry.is_async:
                from model_tools import _run_async
                return _run_async(entry.handler(args, **kwargs))
            return entry.handler(args, **kwargs)
        except Exception as e:
            logger.exception("Tool %s dispatch error: %s", name, e)
            # Route through the sanitizer so framing tokens / CDATA / fences
            # in exception strings don't reach the model as structural noise.
            # See model_tools._sanitize_tool_error for rationale.
            raw = f"Tool execution failed: {type(e).__name__}: {e}"
            try:
                from model_tools import _sanitize_tool_error
                sanitized = _sanitize_tool_error(raw)
            except Exception:
                sanitized = raw  # defensive: never let the sanitizer block error propagation
            return json.dumps({"error": sanitized})

    # ------------------------------------------------------------------
    # Query helpers  (replace redundant dicts in model_tools.py)
    # ------------------------------------------------------------------

    def get_max_result_size(self, name: str, default: int | float | None = None) -> int | float:
        """Return per-tool max result size, or *default* (or global default)."""
        entry = self.get_entry(name)
        if entry and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        if default is not None:
            return default
        from tools.budget_config import DEFAULT_RESULT_SIZE_CHARS
        return DEFAULT_RESULT_SIZE_CHARS

    def get_all_tool_names(self) -> List[str]:
        """Return sorted list of all registered tool names."""
        return sorted(entry.name for entry in self._snapshot_entries())

    def get_schema(self, name: str) -> Optional[dict]:
        """Return a tool's raw schema dict, bypassing check_fn filtering.

        Useful for token estimation and introspection where availability
        doesn't matter — only the schema content does.
        """
        entry = self.get_entry(name)
        return entry.schema if entry else None

    def get_toolset_for_tool(self, name: str) -> Optional[str]:
        """Return the toolset a tool belongs to, or None."""
        entry = self.get_entry(name)
        return entry.toolset if entry else None

    def get_effect_metadata(self, name: str) -> dict:
        """Return typed effect declaration metadata for one tool.

        Undeclared and unknown tools are reported as ``unknown``.  The
        resolver callable itself is never exposed through introspection.
        """
        from tools.approval import Effect, EffectKind

        entry = self.get_entry(name)
        if entry is None:
            return {
                "declared": False,
                "effects": frozenset({Effect(EffectKind.UNKNOWN)}),
                "has_resolver": False,
            }
        declared = bool(entry.effects) or entry.effect_resolver is not None
        if declared:
            effects = entry.effects or frozenset()
        else:
            effects = frozenset({Effect(EffectKind.UNKNOWN)})
        return {
            "declared": declared,
            "effects": effects,
            "has_resolver": entry.effect_resolver is not None,
        }

    def resolve_effects(self, name: str, args: Optional[dict] = None):
        """Resolve a tool's complete typed effect set for the supplied args.

        Static and dynamic effects are unioned.  Missing declarations, empty
        resolver results, malformed metadata, and resolver exceptions produce
        ``unknown`` so a restricted policy cannot fail open.
        """
        from tools.approval import Effect, EffectKind, normalize_effects

        entry = self.get_entry(name)
        if entry is None:
            return frozenset({Effect(EffectKind.UNKNOWN)})

        resolved = set(entry.effects or ())
        if entry.effect_resolver is not None:
            if not isinstance(args, dict):
                dynamic = frozenset({Effect(EffectKind.UNKNOWN)})
            else:
                try:
                    dynamic = normalize_effects(entry.effect_resolver(dict(args)))
                except Exception as exc:
                    logger.warning("effect_resolver for tool %s raised %s", name, exc)
                    dynamic = frozenset({Effect(EffectKind.UNKNOWN)})
                if not dynamic:
                    dynamic = frozenset({Effect(EffectKind.UNKNOWN)})
            resolved.update(dynamic)
        if not resolved:
            resolved.add(Effect(EffectKind.UNKNOWN))
        return frozenset(resolved)

    def get_emoji(self, name: str, default: str = "⚡") -> str:
        """Return the emoji for a tool, or *default* if unset."""
        entry = self.get_entry(name)
        return (entry.emoji if entry and entry.emoji else default)

    def get_tool_to_toolset_map(self) -> Dict[str, str]:
        """Return ``{tool_name: toolset_name}`` for every registered tool."""
        return {entry.name: entry.toolset for entry in self._snapshot_entries()}

    def is_toolset_available(self, toolset: str) -> bool:
        """Check if a toolset's requirements are met.

        Returns False (rather than crashing) when the check function raises
        an unexpected exception (e.g. network error, missing import, bad config).
        """
        with self._lock:
            check = self._toolset_checks.get(toolset)
        return self._evaluate_toolset_check(toolset, check)

    def check_toolset_requirements(self) -> Dict[str, bool]:
        """Return ``{toolset: available_bool}`` for every toolset."""
        entries, toolset_checks = self._snapshot_state()
        toolsets = sorted({entry.toolset for entry in entries})
        return {
            toolset: self._evaluate_toolset_check(toolset, toolset_checks.get(toolset))
            for toolset in toolsets
        }

    def get_available_toolsets(self) -> Dict[str, dict]:
        """Return toolset metadata for UI display."""
        toolsets: Dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = {
                    "available": self._evaluate_toolset_check(
                        ts, toolset_checks.get(ts)
                    ),
                    "tools": [],
                    "description": "",
                    "requirements": [],
                }
            toolsets[ts]["tools"].append(entry.name)
            if entry.requires_env:
                for env in entry.requires_env:
                    if env not in toolsets[ts]["requirements"]:
                        toolsets[ts]["requirements"].append(env)
        return toolsets

    def get_toolset_requirements(self) -> Dict[str, dict]:
        """Build a TOOLSET_REQUIREMENTS-compatible dict for backward compat."""
        result: Dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in result:
                result[ts] = {
                    "name": ts,
                    "env_vars": [],
                    "check_fn": toolset_checks.get(ts),
                    "setup_url": None,
                    "tools": [],
                }
            if entry.name not in result[ts]["tools"]:
                result[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in result[ts]["env_vars"]:
                    result[ts]["env_vars"].append(env)
        return result

    def check_tool_availability(self, quiet: bool = False):
        """Return (available_toolsets, unavailable_info) like the old function."""
        available = []
        unavailable = []
        seen = set()
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts in seen:
                continue
            seen.add(ts)
            if self._evaluate_toolset_check(ts, toolset_checks.get(ts)):
                available.append(ts)
            else:
                unavailable.append({
                    "name": ts,
                    "env_vars": entry.requires_env,
                    "tools": [e.name for e in entries if e.toolset == ts],
                })
        return available, unavailable


# Module-level singleton
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Helpers for tool response serialization
# ---------------------------------------------------------------------------
# Every tool handler must return a JSON string.  These helpers eliminate the
# boilerplate ``json.dumps({"error": msg}, ensure_ascii=False)`` that appears
# hundreds of times across tool files.
#
# Usage:
#   from tools.registry import registry, tool_error, tool_result
#
#   return tool_error("something went wrong")
#   return tool_error("not found", code=404)
#   return tool_result(success=True, data=payload)
#   return tool_result(items)            # pass a dict directly


def tool_error(message, **extra) -> str:
    """Return a JSON error string for tool handlers.

    >>> tool_error("file not found")
    '{"error": "file not found"}'
    >>> tool_error("bad input", success=False)
    '{"error": "bad input", "success": false}'
    """
    result = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def tool_result(data=None, **kwargs) -> str:
    """Return a JSON result string for tool handlers.

    Accepts a dict positional arg *or* keyword arguments (not both):

    >>> tool_result(success=True, count=42)
    '{"success": true, "count": 42}'
    >>> tool_result({"key": "value"})
    '{"key": "value"}'
    """
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)
