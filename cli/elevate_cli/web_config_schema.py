from __future__ import annotations

from typing import Any, Dict

from elevate_cli.config import DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "model": {
        "type": "string",
        "description": "Default model (e.g. anthropic/claude-sonnet-4.6)",
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Context window override (0 = auto-detect from model metadata)",
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Terminal execution backend",
        "options": ["local", "docker", "ssh", "modal", "daytona", "singularity"],
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modal sandbox mode",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Text-to-speech provider",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Speech-to-text provider",
        "options": ["local", "openai", "mistral"],
    },
    "display.skin": {
        "type": "select",
        "description": "CLI visual theme",
        "options": ["default", "ares", "mono", "slate"],
    },
    "dashboard.theme": {
        "type": "select",
        "description": "Web dashboard visual theme",
        "options": ["default", "midnight", "ember", "mono", "cyberpunk", "rose"],
    },
    "sources.tools_root": {
        "type": "string",
        "description": "Customer tools root containing data/sources/<source-id>",
        "category": "sources",
    },
    "integrations.tools_root": {
        "type": "string",
        "description": "Legacy alias for customer tools root; sources.tools_root takes precedence",
        "category": "integrations",
    },
    "integrations.crm.provider": {
        "type": "select",
        "description": "CRM provider preset",
        "options": ["custom", "lofty", "follow_up_boss", "kvcore", "chime", "wise_agent", "real_geeks"],
        "category": "integrations",
    },
    "integrations.crm.auth_type": {
        "type": "select",
        "description": "CRM API authentication placement",
        "options": ["header", "query"],
        "category": "integrations",
    },
    "agent_hub.default_agent": {
        "type": "string",
        "description": "Default Agent Hub persona for new local chat sessions",
        "category": "agent_hub",
    },
    "agent_hub.agents": {
        # NOTE: agent definitions are authoritative in the per-account DB
        # (hub_agents, migration 0026). config.yaml's copy is a frozen
        # one-shot-import archive — edits here are inert on read. Manage
        # agents via /api/agent-hub/agents. Kept in the schema for back-compat.
        "type": "json",
        "description": "Agent Hub personas/orchestration metadata (read-only archive; manage via Agent Hub)",
        "category": "agent_hub",
    },
    "display.resume_display": {
        "type": "select",
        "description": "How resumed sessions display history",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Input behavior while agent is running",
        "options": ["queue", "interrupt", "block"],
    },
    "memory.provider": {
        "type": "select",
        "description": "Memory provider plugin",
        "options": ["", "builtin", "holographic", "honcho", "openviking", "mem0", "hindsight", "retaindb", "byterover"],
    },
    "plugins.elevate-memory-store.db_path": {
        "type": "string",
        "description": "Holographic memory SQLite database path",
        "category": "memory",
    },
    "plugins.elevate-memory-store.auto_extract": {
        "type": "boolean",
        "description": "Auto-extract durable facts at session end",
        "category": "memory",
    },
    "plugins.elevate-memory-store.turn_journal_enabled": {
        "type": "boolean",
        "description": "Record completed turns locally for daily/session memory organization",
        "category": "memory",
    },
    "plugins.elevate-memory-store.organize_on_session_end": {
        "type": "boolean",
        "description": "Organize pending journal turns when a session ends",
        "category": "memory",
    },
    "plugins.elevate-memory-store.organize_every_n_turns": {
        "type": "number",
        "description": "Also organize pending journal turns every N completed turns (0 disables)",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_enabled": {
        "type": "boolean",
        "description": "Run local daily journal organization even when sessions stay open",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_hour": {
        "type": "number",
        "description": "Local hour for daily journal organization",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_minute": {
        "type": "number",
        "description": "Local minute for daily journal organization",
        "category": "memory",
    },
    "plugins.elevate-memory-store.daily_organize_max_batches": {
        "type": "number",
        "description": "Maximum memory organization batches in one daily pass",
        "category": "memory",
    },
    "plugins.elevate-memory-store.turn_journal_max_chars": {
        "type": "number",
        "description": "Maximum characters saved per side of a turn",
        "category": "memory",
    },
    "plugins.elevate-memory-store.organize_batch_limit": {
        "type": "number",
        "description": "Maximum pending turns to organize in one pass",
        "category": "memory",
    },
    "plugins.elevate-memory-store.layered_prefetch_enabled": {
        "type": "boolean",
        "description": "Inject recent, durable, and graph memory lanes instead of one flat memory list",
        "category": "memory",
    },
    "plugins.elevate-memory-store.recent_recall_enabled": {
        "type": "boolean",
        "description": "Include recent same-session journal recall",
        "category": "memory",
    },
    "plugins.elevate-memory-store.graph_recall_enabled": {
        "type": "boolean",
        "description": "Include wiki-style entity graph recall",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_enabled": {
        "type": "boolean",
        "description": "Enable semantic embeddings for durable memory search",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_provider": {
        "type": "select",
        "description": "Embedding backend",
        "options": ["openai", "ollama", "openai_compatible", "local_minilm"],
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_model": {
        "type": "string",
        "description": "Embedding model name",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_dimensions": {
        "type": "string",
        "description": "Optional embedding dimensions override",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_base_url": {
        "type": "string",
        "description": "Optional OpenAI-compatible embedding base URL",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_api_key_env": {
        "type": "string",
        "description": "Environment variable containing the embedding API key",
        "category": "memory",
    },
    "plugins.elevate-memory-store.embedding_cache_dir": {
        "type": "string",
        "description": "Optional local model cache directory for local_minilm",
        "category": "memory",
    },
    "access.profile": {
        "type": "select",
        "description": "Access profile for local entitlement gates",
        "options": ["standalone", "exp", "team_pack"],
        "category": "access",
    },
    "access.affiliation.status": {
        "type": "select",
        "description": "Affiliation status used by team/EXP skill access gates",
        "options": ["active", "inactive", "left", "paused"],
        "category": "access",
    },
    "platforms.telegram.reply_to_mode": {
        "type": "select",
        "description": "Telegram reply threading mode",
        "options": ["off", "first", "all"],
        "category": "platforms",
    },
    "platforms.telegram.extra.unauthorized_dm_behavior": {
        "type": "select",
        "description": "Telegram behavior for unpaired direct messages",
        "options": ["pair", "ignore"],
        "category": "platforms",
    },
    "platforms.api_server.reply_to_mode": {
        "type": "select",
        "description": "API server reply threading mode",
        "options": ["off", "first", "all"],
        "category": "platforms",
    },
    "approvals.mode": {
        "type": "select",
        "description": "Dangerous command approval mode",
        "options": ["ask", "yolo", "deny"],
    },
    "approvals.permission_mode": {
        "type": "select",
        "description": "Tool permission mode (Claude-style). Overrides 'mode' when set: "
        "default = ask first, acceptEdits = auto-accept file edits, "
        "plan = read-only, bypassPermissions = never ask",
        "options": ["default", "acceptEdits", "plan", "bypassPermissions"],
    },
    "context.engine": {
        "type": "select",
        "description": "Context management engine",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Simulated typing delay mode",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Log level for agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "API service tier (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Reasoning effort for delegated subagents",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "approvals": "security",
    "human_delay": "display",
    "dashboard": "display",
    "code_execution": "agent",
    "prompt_caching": "agent",
    "goals": "agent",
    "sources": "integrations",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general", "agent", "agent_hub", "sources", "integrations", "platforms", "terminal", "display",
    "delegation", "memory", "access", "plugins", "compression", "security",
    "browser", "voice", "tts", "stt", "logging", "discord", "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in ("_config_version",):
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            if full_key.startswith("plugins.elevate-memory-store."):
                entry["category"] = "memory"
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(entry["category"], entry["category"])
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle.  Insert model_context_length right after
# the "model" key so it renders adjacent in the frontend.
_mcl_entry = _SCHEMA_OVERRIDES["model_context_length"]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        _ordered_schema["model_context_length"] = _mcl_entry
CONFIG_SCHEMA = _ordered_schema
