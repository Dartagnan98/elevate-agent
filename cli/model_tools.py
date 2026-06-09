#!/usr/bin/env python3
"""
Model Tools Module

Thin orchestration layer over the tool registry. Each tool file in tools/
self-registers its schema, handler, and metadata via tools.registry.register().
This module triggers discovery (by importing all tool modules), then provides
the public API that run_agent.py, cli.py, batch_runner.py, and the RL
environments consume.

Public API (signatures preserved from the original 2,400-line version):
    get_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode) -> list
    handle_function_call(function_name, function_args, task_id, user_task) -> str
    TOOL_TO_TOOLSET_MAP: dict          (for batch_runner.py)
    TOOLSET_REQUIREMENTS: dict         (for cli.py, doctor.py)
    get_all_tool_names() -> list
    get_toolset_for_tool(name) -> str
    get_available_toolsets() -> dict
    check_toolset_requirements() -> dict
    check_tool_availability(quiet) -> tuple
"""

import json
import asyncio
import copy
import logging
import os
import threading
import time
from typing import Dict, Any, List, Optional, Tuple

from tools.registry import discover_builtin_tools, registry
from toolsets import resolve_toolset, validate_toolset

# Memo for get_tool_definitions(). Building the list resolves toolsets, runs
# registry.get_definitions (per-tool check_fns) and rebuilds the dynamic
# execute_code/discord/browser schemas — the discord rebuild can do network
# I/O. Tool sets are stable within a session, so cache the result. A config
# edit invalidates immediately (mtime is part of the key). Result is
# deep-copied in and out so callers can't mutate the cached schemas.
#
# PROMPT-CACHE PREFIX STABILITY: in the Anthropic API the cached prefix is
# tools -> system -> messages. ONE byte of schema drift between turns of the
# same conversation invalidates the whole cached prefix (tools + system
# prompt), turning ~0.1x cached reads into full-price re-writes. The gateway
# constructs a fresh AIAgent per message, so this memo is what keeps the
# tools array byte-identical across turns. Hence:
#   - TTL is long (10 min, ELEVATE_TOOL_DEFS_TTL_S to override) — staleness
#     of dynamic pieces (discord intents, sandbox availability) is bounded
#     but rebuilds are rare.
#   - On a TTL-expiry rebuild we compare against the previous entry: if the
#     content is identical we keep serving the same bytes; if it changed we
#     log which tools drifted so cache-bust regressions are debuggable.
_TOOL_DEFS_CACHE: Dict[Any, Tuple[float, List[Dict[str, Any]]]] = {}
_TOOL_DEFS_CACHE_LOCK = threading.Lock()
# Last discord_server schema that built successfully — reused when the
# intents probe fails transiently so the tool doesn't flap in and out of
# the tools array (each flap busts the prompt-cache prefix).
_LAST_GOOD_DISCORD_SCHEMA: Optional[Dict[str, Any]] = None
try:
    _TOOL_DEFS_TTL_S = float(os.getenv("ELEVATE_TOOL_DEFS_TTL_S", "600"))
except ValueError:
    _TOOL_DEFS_TTL_S = 600.0


def _tool_defs_diff_names(
    old: List[Dict[str, Any]], new: List[Dict[str, Any]]
) -> List[str]:
    """Names of tools whose schema bytes differ between two definition lists."""

    def _by_name(defs: List[Dict[str, Any]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for td in defs:
            name = (td.get("function") or {}).get("name") or "?"
            try:
                out[name] = json.dumps(td, sort_keys=True)
            except (TypeError, ValueError):
                out[name] = repr(td)
        return out

    old_map, new_map = _by_name(old), _by_name(new)
    changed = [n for n in new_map if old_map.get(n) != new_map[n]]
    changed += [n for n in old_map if n not in new_map]
    return sorted(set(changed))


def _tool_defs_config_mtime_ns() -> int:
    try:
        from elevate_cli.config import get_config_path

        return get_config_path().stat().st_mtime_ns
    except Exception:
        return 0

logger = logging.getLogger(__name__)


# =============================================================================
# Async Bridging  (single source of truth -- used by registry.dispatch too)
# =============================================================================

_tool_loop = None          # persistent loop for the main (CLI) thread
_tool_loop_lock = threading.Lock()
_worker_thread_local = threading.local()  # per-worker-thread persistent loops


def _get_tool_loop():
    """Return a long-lived event loop for running async tool handlers.

    Using a persistent loop (instead of asyncio.run() which creates and
    *closes* a fresh loop every time) prevents "Event loop is closed"
    errors that occur when cached httpx/AsyncOpenAI clients attempt to
    close their transport on a dead loop during garbage collection.
    """
    global _tool_loop
    with _tool_loop_lock:
        if _tool_loop is None or _tool_loop.is_closed():
            _tool_loop = asyncio.new_event_loop()
        return _tool_loop


def _get_worker_loop():
    """Return a persistent event loop for the current worker thread.

    Each worker thread (e.g., delegate_task's ThreadPoolExecutor threads)
    gets its own long-lived loop stored in thread-local storage.  This
    prevents the "Event loop is closed" errors that occurred when
    asyncio.run() was used per-call: asyncio.run() creates a loop, runs
    the coroutine, then *closes* the loop — but cached httpx/AsyncOpenAI
    clients remain bound to that now-dead loop and raise RuntimeError
    during garbage collection or subsequent use.

    By keeping the loop alive for the thread's lifetime, cached clients
    stay valid and their cleanup runs on a live loop.
    """
    loop = getattr(_worker_thread_local, 'loop', None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _worker_thread_local.loop = loop
    return loop


def _run_async(coro):
    """Run an async coroutine from a sync context.

    If the current thread already has a running event loop (e.g., inside
    the gateway's async stack or Atropos's event loop), we spin up a
    disposable thread so asyncio.run() can create its own loop without
    conflicting.

    For the common CLI path (no running loop), we use a persistent event
    loop so that cached async clients (httpx / AsyncOpenAI) remain bound
    to a live loop and don't trigger "Event loop is closed" on GC.

    When called from a worker thread (parallel tool execution), we use a
    per-thread persistent loop to avoid both contention with the main
    thread's shared loop AND the "Event loop is closed" errors caused by
    asyncio.run()'s create-and-destroy lifecycle.

    This is the single source of truth for sync->async bridging in tool
    handlers. The RL paths (agent_loop.py, tool_context.py) also provide
    outer thread-pool wrapping as defense-in-depth, but each handler is
    self-protecting via this function.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Inside an async context (gateway, RL env) — run in a fresh thread.
        import concurrent.futures
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(asyncio.run, coro)
        try:
            return future.result(timeout=300)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    # If we're on a worker thread (e.g., parallel tool execution in
    # delegate_task), use a per-thread persistent loop.  This avoids
    # contention with the main thread's shared loop while keeping cached
    # httpx/AsyncOpenAI clients bound to a live loop for the thread's
    # lifetime — preventing "Event loop is closed" on GC cleanup.
    if threading.current_thread() is not threading.main_thread():
        worker_loop = _get_worker_loop()
        return worker_loop.run_until_complete(coro)

    tool_loop = _get_tool_loop()
    return tool_loop.run_until_complete(coro)


# =============================================================================
# Tool Discovery  (importing each module triggers its registry.register calls)
# =============================================================================

discover_builtin_tools()

# MCP tool discovery is intentionally lazy. Import-time discovery can spawn
# external processes or block scripts that only need built-in tools. We discover
# MCP tools on the first get_tool_definitions() call that could actually expose
# MCP tools: full profile, disabled-toolset profile without mcp disabled, or an
# explicit mcp/mcp-* toolset request.
_mcp_discovery_lock = threading.Lock()
_mcp_discovery_attempted = False


def _mcp_discovery_disabled() -> bool:
    return str(os.getenv("ELEVATE_SKIP_MCP_DISCOVERY", "")).strip().lower() in {"1", "true", "yes", "on"}


def _should_discover_mcp(enabled_toolsets: List[str] | None, disabled_toolsets: List[str] | None) -> bool:
    if _mcp_discovery_disabled():
        return False
    if enabled_toolsets is not None:
        names = {str(name) for name in enabled_toolsets}
        return "mcp" in names or any(name.startswith("mcp-") for name in names)
    disabled = {str(name) for name in (disabled_toolsets or [])}
    return "mcp" not in disabled


def _ensure_mcp_tools_discovered(enabled_toolsets: List[str] | None = None, disabled_toolsets: List[str] | None = None) -> None:
    global _mcp_discovery_attempted
    if _mcp_discovery_attempted or not _should_discover_mcp(enabled_toolsets, disabled_toolsets):
        return
    with _mcp_discovery_lock:
        if _mcp_discovery_attempted:
            return
        _mcp_discovery_attempted = True
        try:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
        except Exception as e:
            logger.debug("MCP tool discovery failed: %s", e)

# Plugin tool discovery
try:
    from elevate_cli.plugins import discover_plugins
    discover_plugins()
except Exception as e:
    logger.debug("Plugin discovery failed: %s", e)


# =============================================================================
# Backward-compat constants  (built once after discovery)
# =============================================================================

TOOL_TO_TOOLSET_MAP: Dict[str, str] = registry.get_tool_to_toolset_map()

TOOLSET_REQUIREMENTS: Dict[str, dict] = registry.get_toolset_requirements()

# Resolved tool names from the last get_tool_definitions() call.
# Used by code_execution_tool to know which tools are available in this session.
_last_resolved_tool_names: List[str] = []


# =============================================================================
# Legacy toolset name mapping  (old _tools-suffixed names -> tool name lists)
# =============================================================================

_LEGACY_TOOLSET_MAP = {
    "web_tools": ["web_search", "web_extract"],
    "terminal_tools": ["terminal"],
    "vision_tools": ["vision_analyze"],
    "moa_tools": ["mixture_of_agents"],
    "image_tools": ["image_generate"],
    "skills_tools": ["skills_list", "skill_view", "skill_manage"],
    "browser_tools": [
        "browser_navigate", "browser_snapshot", "browser_click",
        "browser_type", "browser_scroll", "browser_back",
        "browser_press", "browser_get_images",
        "browser_vision", "browser_console"
    ],
    "cronjob_tools": ["cronjob"],
    "rl_tools": [
        "rl_list_environments", "rl_select_environment",
        "rl_get_current_config", "rl_edit_config",
        "rl_start_training", "rl_check_status",
        "rl_stop_training", "rl_get_results",
        "rl_list_runs", "rl_test_inference"
    ],
    "file_tools": ["read_file", "write_file", "patch", "search_files"],
    "tts_tools": ["text_to_speech"],
}


# =============================================================================
# get_tool_definitions  (the main schema provider)
# =============================================================================

def get_tool_definitions(
    enabled_toolsets: List[str] = None,
    disabled_toolsets: List[str] = None,
    quiet_mode: bool = False,
) -> List[Dict[str, Any]]:
    """
    Get tool definitions for model API calls with toolset-based filtering.

    All tools must be part of a toolset to be accessible.

    Args:
        enabled_toolsets: Only include tools from these toolsets.
        disabled_toolsets: Exclude tools from these toolsets (if enabled_toolsets is None).
        quiet_mode: Suppress status prints.

    Returns:
        Filtered list of OpenAI-format tool definitions.
    """
    cache_key = (
        tuple(sorted(enabled_toolsets)) if enabled_toolsets is not None else None,
        tuple(sorted(disabled_toolsets)) if disabled_toolsets else None,
        bool(quiet_mode),
        _tool_defs_config_mtime_ns(),
    )
    with _TOOL_DEFS_CACHE_LOCK:
        _ent = _TOOL_DEFS_CACHE.get(cache_key)
        if _ent is not None and _ent[0] > time.monotonic():
            return copy.deepcopy(_ent[1])
        # Keep the expired entry around for the drift comparison below —
        # if the rebuild produces identical content we keep serving the
        # exact same objects (byte-stable for the prompt-cache prefix).
        _prev_defs = copy.deepcopy(_ent[1]) if _ent is not None else None

    _ensure_mcp_tools_discovered(enabled_toolsets, disabled_toolsets)

    # Determine which tool names the caller wants
    tools_to_include: set = set()

    if enabled_toolsets is not None:
        for toolset_name in enabled_toolsets:
            if validate_toolset(toolset_name):
                resolved = resolve_toolset(toolset_name)
                tools_to_include.update(resolved)
                if not quiet_mode:
                    print(f"✅ Enabled toolset '{toolset_name}': {', '.join(resolved) if resolved else 'no tools'}")
            elif toolset_name in _LEGACY_TOOLSET_MAP:
                legacy_tools = _LEGACY_TOOLSET_MAP[toolset_name]
                tools_to_include.update(legacy_tools)
                if not quiet_mode:
                    print(f"✅ Enabled legacy toolset '{toolset_name}': {', '.join(legacy_tools)}")
            else:
                if not quiet_mode:
                    print(f"⚠️  Unknown toolset: {toolset_name}")

    elif disabled_toolsets:
        from toolsets import get_all_toolsets
        for ts_name in get_all_toolsets():
            tools_to_include.update(resolve_toolset(ts_name))

        for toolset_name in disabled_toolsets:
            if validate_toolset(toolset_name):
                resolved = resolve_toolset(toolset_name)
                tools_to_include.difference_update(resolved)
                if not quiet_mode:
                    print(f"🚫 Disabled toolset '{toolset_name}': {', '.join(resolved) if resolved else 'no tools'}")
            elif toolset_name in _LEGACY_TOOLSET_MAP:
                legacy_tools = _LEGACY_TOOLSET_MAP[toolset_name]
                tools_to_include.difference_update(legacy_tools)
                if not quiet_mode:
                    print(f"🚫 Disabled legacy toolset '{toolset_name}': {', '.join(legacy_tools)}")
            else:
                if not quiet_mode:
                    print(f"⚠️  Unknown toolset: {toolset_name}")
    else:
        from toolsets import get_all_toolsets
        for ts_name in get_all_toolsets():
            tools_to_include.update(resolve_toolset(ts_name))

    # Plugin-registered tools are now resolved through the normal toolset
    # path — validate_toolset() / resolve_toolset() / get_all_toolsets()
    # all check the tool registry for plugin-provided toolsets.  No bypass
    # needed; plugins respect enabled_toolsets / disabled_toolsets like any
    # other toolset.

    # Ask the registry for schemas (only returns tools whose check_fn passes)
    filtered_tools = registry.get_definitions(tools_to_include, quiet=quiet_mode)

    # The set of tool names that actually passed check_fn filtering.
    # Use this (not tools_to_include) for any downstream schema that references
    # other tools by name — otherwise the model sees tools mentioned in
    # descriptions that don't actually exist, and hallucinates calls to them.
    available_tool_names = {t["function"]["name"] for t in filtered_tools}

    # Rebuild execute_code schema to only list sandbox tools that are actually
    # available.  Without this, the model sees "web_search is available in
    # execute_code" even when the API key isn't configured or the toolset is
    # disabled (#560-discord).
    if "execute_code" in available_tool_names:
        from tools.code_execution_tool import SANDBOX_ALLOWED_TOOLS, build_execute_code_schema, _get_execution_mode
        sandbox_enabled = SANDBOX_ALLOWED_TOOLS & available_tool_names
        dynamic_schema = build_execute_code_schema(sandbox_enabled, mode=_get_execution_mode())
        for i, td in enumerate(filtered_tools):
            if td.get("function", {}).get("name") == "execute_code":
                filtered_tools[i] = {"type": "function", "function": dynamic_schema}
                break

    # Rebuild discord_server schema based on the bot's privileged intents
    # (detected from GET /applications/@me) and the user's action allowlist
    # in config.  Hides actions the bot's intents don't support so the
    # model never attempts them, and annotates fetch_messages when the
    # MESSAGE_CONTENT intent is missing.
    if "discord_server" in available_tool_names:
        try:
            from tools.discord_tool import get_dynamic_schema
            dynamic = get_dynamic_schema()
            if dynamic is not None:
                global _LAST_GOOD_DISCORD_SCHEMA
                _LAST_GOOD_DISCORD_SCHEMA = copy.deepcopy(dynamic)
        except Exception:  # pragma: no cover — defensive, fall back to static
            # Transient failure (network blip on the intents probe): reuse the
            # last schema that built successfully instead of dropping the tool.
            # Dropping it would both lose the tool for a turn AND change the
            # tools array bytes, invalidating the prompt-cache prefix twice
            # (once on drop, once on restore).
            dynamic = copy.deepcopy(_LAST_GOOD_DISCORD_SCHEMA) if _LAST_GOOD_DISCORD_SCHEMA else None
        if dynamic is None:
            # Tool filtered out entirely (empty allowlist or detection disabled
            # the only remaining actions).  Drop it from the schema list.
            filtered_tools = [
                t for t in filtered_tools
                if t.get("function", {}).get("name") != "discord_server"
            ]
            available_tool_names.discard("discord_server")
        else:
            for i, td in enumerate(filtered_tools):
                if td.get("function", {}).get("name") == "discord_server":
                    filtered_tools[i] = {"type": "function", "function": dynamic}
                    break

    # Strip web tool cross-references from browser_navigate description when
    # web_search / web_extract are not available.  The static schema says
    # "prefer web_search or web_extract" which causes the model to hallucinate
    # those tools when they're missing.
    if "browser_navigate" in available_tool_names:
        web_tools_available = {"web_search", "web_extract"} & available_tool_names
        if not web_tools_available:
            for i, td in enumerate(filtered_tools):
                if td.get("function", {}).get("name") == "browser_navigate":
                    desc = td["function"].get("description", "")
                    desc = desc.replace(
                        " For simple information retrieval, prefer web_search or web_extract (faster, cheaper).",
                        "",
                    )
                    filtered_tools[i] = {
                        "type": "function",
                        "function": {**td["function"], "description": desc},
                    }
                    break

    # Strip cross-tool guidance from file schemas when the referenced tool is
    # not actually loaded in this focused profile.  Otherwise narrowed wrapper
    # profiles still nudge the model toward unavailable tool names.
    if "terminal" not in available_tool_names or "vision_analyze" not in available_tool_names:
        _schema_replacements = {}
        if "terminal" not in available_tool_names:
            _schema_replacements.update({
                "read_file": [
                    (" Use this instead of cat/head/tail in terminal.", ""),
                ],
                "write_file": [
                    (" Use this instead of echo/cat heredoc in terminal.", ""),
                ],
                "patch": [
                    (" Use this instead of sed/awk in terminal.", ""),
                ],
                "search_files": [
                    (" Use this instead of grep/rg/find/ls in terminal.", ""),
                    (" Also use this instead of ls — results sorted by modification time.", " Results are sorted by modification time."),
                ],
            })
        if "vision_analyze" not in available_tool_names:
            _schema_replacements.setdefault("read_file", []).append(
                (" NOTE: Cannot read images or binary files — use vision_analyze for images.", " NOTE: Cannot read images or binary files.")
            )

        for i, td in enumerate(filtered_tools):
            name = td.get("function", {}).get("name")
            replacements = _schema_replacements.get(name)
            if not replacements:
                continue
            fn = dict(td.get("function", {}))
            desc = fn.get("description", "")
            for old, new in replacements:
                desc = desc.replace(old, new)
            fn["description"] = desc
            filtered_tools[i] = {"type": "function", "function": fn}

    # A few schemas intentionally mention companion tools when those tools are
    # present. In narrow profiles, remove those cross-references so the model
    # does not try to call tools the runtime filtered out.
    _profile_replacements = {}
    if "terminal" in available_tool_names:
        terminal_replacements = []
        if "read_file" not in available_tool_names:
            terminal_replacements.append(
                ("Do NOT use cat/head/tail to read files — use read_file instead.\n", "")
            )
        if "search_files" not in available_tool_names:
            terminal_replacements.extend(
                [
                    ("Do NOT use grep/rg/find to search — use search_files instead.\n", ""),
                    ("Do NOT use ls to list directories — use search_files(target='files') instead.\n", ""),
                ]
            )
        if "write_file" not in available_tool_names:
            terminal_replacements.append(
                ("Do NOT use echo/cat heredoc to create files — use write_file instead.\n", "")
            )
        if terminal_replacements:
            _profile_replacements["terminal"] = terminal_replacements

    if "clarify" in available_tool_names and "terminal" not in available_tool_names:
        _profile_replacements["clarify"] = [
            (
                "commands (the terminal tool handles that). Prefer making a reasonable ",
                "commands. Prefer making a reasonable ",
            )
        ]

    if "memory" in available_tool_names and "session_search" not in available_tool_names:
        _profile_replacements["memory"] = [
            (
                "state to memory; use session_search to recall those from past transcripts.\n",
                "state to memory.\n",
            ),
            (
                "If you've discovered a new way to do something, solved a problem that could be "
                "necessary later, save it as a skill with the skill tool.\n\n",
                "",
            )
            if "skill_manage" not in available_tool_names
            else ("", ""),
        ]

    if _profile_replacements:
        for i, td in enumerate(filtered_tools):
            name = td.get("function", {}).get("name")
            replacements = _profile_replacements.get(name)
            if not replacements:
                continue
            fn = copy.deepcopy(td.get("function", {}))
            desc = fn.get("description", "")
            for old, new in replacements:
                if old:
                    desc = desc.replace(old, new)
            fn["description"] = desc
            filtered_tools[i] = {"type": "function", "function": fn}

    # Delegate schemas need profile-aware toolset hints.  The static schema
    # lists all built-in subagent toolsets, which is misleading after
    # enabled_toolsets narrowed the parent session.
    if "delegate_task" in available_tool_names:
        try:
            from toolsets import get_all_toolsets
            from tools.delegate_tool import DELEGATE_BLOCKED_TOOLS

            excluded = {"debugging", "safe", "delegation", "moa", "rl"}
            available_child_toolsets = []
            for toolset_name in sorted(get_all_toolsets()):
                if toolset_name in excluded or toolset_name.startswith("elevate-"):
                    continue
                resolved = set(resolve_toolset(toolset_name))
                if not resolved:
                    continue
                if not (resolved & available_tool_names):
                    continue
                if resolved <= set(DELEGATE_BLOCKED_TOOLS):
                    continue
                available_child_toolsets.append(toolset_name)

            if available_child_toolsets:
                toolset_hint = ", ".join(f"'{name}'" for name in available_child_toolsets)
            else:
                toolset_hint = "inherit the current focused profile"
            child_terminal_available = "terminal" in available_child_toolsets

            for i, td in enumerate(filtered_tools):
                if td.get("function", {}).get("name") != "delegate_task":
                    continue
                fn = copy.deepcopy(td.get("function", {}))
                if not child_terminal_available:
                    desc = fn.get("description", "")
                    desc = desc.replace(
                        "Each subagent gets its own conversation, terminal session, and toolset. ",
                        "Each subagent gets its own conversation and focused toolset. ",
                    )
                    desc = desc.replace(
                        "- Each subagent gets its own terminal session (separate working directory and state).\n",
                        "",
                    )
                    desc = desc.replace(
                        "Each gets its own subagent with isolated context and terminal session. ",
                        "Each gets its own subagent with isolated context. ",
                    )
                    fn["description"] = desc
                props = (fn.get("parameters") or {}).get("properties") or {}
                if not child_terminal_available and "tasks" in props:
                    task_desc = props["tasks"].get("description", "")
                    props["tasks"]["description"] = task_desc.replace(
                        "Each gets its own subagent with isolated context and terminal session. ",
                        "Each gets its own subagent with isolated context. ",
                    )
                if "toolsets" in props:
                    props["toolsets"]["description"] = (
                        "Toolsets to enable for this subagent. "
                        "Default: inherits your enabled toolsets. "
                        f"Available loaded child toolsets: {toolset_hint}."
                    )
                task_props = (((props.get("tasks") or {}).get("items") or {}).get("properties") or {})
                if "toolsets" in task_props:
                    task_props["toolsets"]["description"] = (
                        "Toolsets for this specific task. "
                        f"Available loaded child toolsets: {toolset_hint}."
                    )
                filtered_tools[i] = {"type": "function", "function": fn}
                break
        except Exception as e:
            logger.debug("delegate_task dynamic schema skipped: %s", e)

    if not quiet_mode:
        if filtered_tools:
            tool_names = [t["function"]["name"] for t in filtered_tools]
            print(f"🛠️  Final tool selection ({len(filtered_tools)} tools): {', '.join(tool_names)}")
        else:
            print("🛠️  No tools selected (all filtered out or unavailable)")

    global _last_resolved_tool_names
    _last_resolved_tool_names = [t["function"]["name"] for t in filtered_tools]

    # Sanitize schemas for broad backend compatibility. llama.cpp's
    # json-schema-to-grammar converter (used by its OAI server to build
    # GBNF tool-call parsers) rejects some shapes that cloud providers
    # silently accept — bare "type": "object" with no properties,
    # string-valued schema nodes from malformed MCP servers, etc. This
    # is a no-op for schemas that are already well-formed.
    try:
        from tools.schema_sanitizer import sanitize_tool_schemas
        filtered_tools = sanitize_tool_schemas(filtered_tools)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("Schema sanitization skipped: %s", e)

    # Drift check against the previous (possibly TTL-expired) entry. Identical
    # content -> reuse the previous list so the serialized request prefix stays
    # byte-for-byte stable. Changed content -> log which tools drifted, since
    # every drift invalidates the provider-side prompt cache for all active
    # conversations using this toolset profile.
    if _prev_defs is not None:
        changed = _tool_defs_diff_names(_prev_defs, filtered_tools)
        if not changed:
            filtered_tools = _prev_defs
        else:
            logger.info(
                "tool definitions drifted on rebuild (prompt-cache prefix "
                "invalidated): %s",
                ", ".join(changed),
            )

    with _TOOL_DEFS_CACHE_LOCK:
        _TOOL_DEFS_CACHE[cache_key] = (
            time.monotonic() + _TOOL_DEFS_TTL_S,
            copy.deepcopy(filtered_tools),
        )
    return filtered_tools


# =============================================================================
# handle_function_call  (the main dispatcher)
# =============================================================================

# Tools whose execution is intercepted by the agent loop (run_agent.py)
# because they need agent-level state (TodoStore, MemoryStore, etc.).
# The registry still holds their schemas; dispatch just returns a stub error
# so if something slips through, the LLM sees a sensible message.
_AGENT_LOOP_TOOLS = {"todo", "memory", "session_search", "delegate_task"}
_READ_SEARCH_TOOLS = {"read_file", "search_files"}


# =========================================================================
# Tool argument type coercion
# =========================================================================

def coerce_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce tool call arguments to match their JSON Schema types.

    LLMs frequently return numbers as strings (``"42"`` instead of ``42``)
    and booleans as strings (``"true"`` instead of ``true``).  This compares
    each argument value against the tool's registered JSON Schema and attempts
    safe coercion when the value is a string but the schema expects a different
    type.  Original values are preserved when coercion fails.

    Handles ``"type": "integer"``, ``"type": "number"``, ``"type": "boolean"``,
    and union types (``"type": ["integer", "string"]``).
    """
    if not args or not isinstance(args, dict):
        return args

    schema = registry.get_schema(tool_name)
    if not schema:
        return args

    properties = (schema.get("parameters") or {}).get("properties")
    if not properties:
        return args

    for key, value in args.items():
        if not isinstance(value, str):
            continue
        prop_schema = properties.get(key)
        if not prop_schema:
            continue
        expected = prop_schema.get("type")
        if not expected:
            continue
        coerced = _coerce_value(value, expected)
        if coerced is not value:
            args[key] = coerced

    return args


def _coerce_value(value: str, expected_type):
    """Attempt to coerce a string *value* to *expected_type*.

    Returns the original string when coercion is not applicable or fails.
    """
    if isinstance(expected_type, list):
        # Union type — try each in order, return first successful coercion
        for t in expected_type:
            result = _coerce_value(value, t)
            if result is not value:
                return result
        return value

    if expected_type in ("integer", "number"):
        return _coerce_number(value, integer_only=(expected_type == "integer"))
    if expected_type == "boolean":
        return _coerce_boolean(value)
    if expected_type == "array":
        return _coerce_json(value, list)
    if expected_type == "object":
        return _coerce_json(value, dict)
    return value


def _coerce_json(value: str, expected_python_type: type):
    """Parse *value* as JSON when the schema expects an array or object.

    Handles model output drift where a complex oneOf/discriminated-union schema
    causes the LLM to emit the array/object as a JSON string instead of a native
    structure.  Returns the original string if parsing fails or yields the wrong
    Python type.
    """
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value
    if isinstance(parsed, expected_python_type):
        logger.debug(
            "coerce_tool_args: coerced string to %s via json.loads",
            expected_python_type.__name__,
        )
        return parsed
    return value


def _coerce_number(value: str, integer_only: bool = False):
    """Try to parse *value* as a number.  Returns original string on failure."""
    try:
        f = float(value)
    except (ValueError, OverflowError):
        return value
    # Guard against inf/nan before int() conversion
    if f != f or f == float("inf") or f == float("-inf"):
        return f
    # If it looks like an integer (no fractional part), return int
    if f == int(f):
        return int(f)
    if integer_only:
        # Schema wants an integer but value has decimals — keep as string
        return value
    return f


def _coerce_boolean(value: str):
    """Try to parse *value* as a boolean.  Returns original string on failure."""
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return value


def handle_function_call(
    function_name: str,
    function_args: Dict[str, Any],
    task_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_task: Optional[str] = None,
    enabled_tools: Optional[List[str]] = None,
    skip_pre_tool_call_hook: bool = False,
) -> str:
    """
    Main function call dispatcher that routes calls to the tool registry.

    Args:
        function_name: Name of the function to call.
        function_args: Arguments for the function.
        task_id: Unique identifier for terminal/browser session isolation.
        user_task: The user's original task (for browser_snapshot context).
        enabled_tools: Tool names enabled for this session.  When provided,
                       execute_code uses this list to determine which sandbox
                       tools to generate.  Falls back to the process-global
                       ``_last_resolved_tool_names`` for backward compat.

    Returns:
        Function result as a JSON string.
    """
    # Coerce string arguments to their schema-declared types (e.g. "42"→42)
    function_args = coerce_tool_args(function_name, function_args)

    try:
        if function_name in _AGENT_LOOP_TOOLS:
            return json.dumps({"error": f"{function_name} must be handled by the agent loop"})

        # Check plugin hooks for a block directive (unless caller already
        # checked — e.g. run_agent._invoke_tool passes skip=True to
        # avoid double-firing the hook).
        if not skip_pre_tool_call_hook:
            block_message: Optional[str] = None
            try:
                from elevate_cli.plugins import get_pre_tool_call_block_message
                block_message = get_pre_tool_call_block_message(
                    function_name,
                    function_args,
                    task_id=task_id or "",
                    session_id=session_id or "",
                    tool_call_id=tool_call_id or "",
                )
            except Exception:
                pass

            if block_message is not None:
                return json.dumps({"error": block_message}, ensure_ascii=False)
        else:
            # Still fire the hook for observers — just don't check for blocking
            # (the caller already did that).
            try:
                from elevate_cli.plugins import invoke_hook
                invoke_hook(
                    "pre_tool_call",
                    tool_name=function_name,
                    args=function_args,
                    task_id=task_id or "",
                    session_id=session_id or "",
                    tool_call_id=tool_call_id or "",
                )
            except Exception:
                pass

        # Notify the read-loop tracker when a non-read/search tool runs,
        # so the *consecutive* counter resets (reads after other work are fine).
        if function_name not in _READ_SEARCH_TOOLS:
            try:
                from tools.file_tools import notify_other_tool_call
                notify_other_tool_call(task_id or "default")
            except Exception:
                pass  # file_tools may not be loaded yet

        if function_name == "execute_code":
            # Prefer the caller-provided list so subagents can't overwrite
            # the parent's tool set via the process-global.
            sandbox_enabled = enabled_tools if enabled_tools is not None else _last_resolved_tool_names
            result = registry.dispatch(
                function_name, function_args,
                task_id=task_id,
                enabled_tools=sandbox_enabled,
            )
        else:
            result = registry.dispatch(
                function_name, function_args,
                task_id=task_id,
                user_task=user_task,
            )

        try:
            from elevate_cli.plugins import invoke_hook
            invoke_hook(
                "post_tool_call",
                tool_name=function_name,
                args=function_args,
                result=result,
                task_id=task_id or "",
                session_id=session_id or "",
                tool_call_id=tool_call_id or "",
            )
        except Exception:
            pass

        # Generic tool-result canonicalization seam: plugins receive the
        # final result string (JSON, usually) and may replace it by
        # returning a string from transform_tool_result. Runs after
        # post_tool_call (which stays observational) and before the result
        # is appended back into conversation context. Fail-open; the first
        # valid string return wins; non-string returns are ignored.
        try:
            from elevate_cli.plugins import invoke_hook
            hook_results = invoke_hook(
                "transform_tool_result",
                tool_name=function_name,
                args=function_args,
                result=result,
                task_id=task_id or "",
                session_id=session_id or "",
                tool_call_id=tool_call_id or "",
            )
            for hook_result in hook_results:
                if isinstance(hook_result, str):
                    result = hook_result
                    break
        except Exception:
            pass

        return result

    except Exception as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)


# =============================================================================
# Backward-compat wrapper functions
# =============================================================================

def get_all_tool_names() -> List[str]:
    """Return all registered tool names."""
    return registry.get_all_tool_names()


def get_toolset_for_tool(tool_name: str) -> Optional[str]:
    """Return the toolset a tool belongs to."""
    return registry.get_toolset_for_tool(tool_name)


def get_available_toolsets() -> Dict[str, dict]:
    """Return toolset availability info for UI display."""
    return registry.get_available_toolsets()


def check_toolset_requirements() -> Dict[str, bool]:
    """Return {toolset: available_bool} for every registered toolset."""
    return registry.check_toolset_requirements()


def check_tool_availability(quiet: bool = False) -> Tuple[List[str], List[dict]]:
    """Return (available_toolsets, unavailable_info)."""
    return registry.check_tool_availability(quiet=quiet)
