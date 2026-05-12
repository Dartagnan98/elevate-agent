"""Helpers for routing visible agents to platform lanes.

The runtime has one gateway process per platform today, but several visible
agents.  These helpers keep the mapping small: each agent can have a Telegram
chat/topic target, while the Executive Assistant remains the default lane.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any


_LEGACY_AGENT_TELEGRAM_ENV_VARS: dict[str, tuple[str, ...]] = {
    "executive-assistant": ("TELEGRAM_HOME_CHANNEL",),
    "admin": (
        "ELEVATE_ADMIN_AGENT_TELEGRAM_CHANNEL",
        "TELEGRAM_ADMIN_AGENT_CHANNEL",
        "ADMIN_AGENT_TELEGRAM_CHAT_ID",
    ),
}


def normalize_agent_id(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    cleaned = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            cleaned.append(ch)
            last_dash = False
        elif not last_dash:
            cleaned.append("-")
            last_dash = True
    return "".join(cleaned).strip("-") or "executive-assistant"


def agent_telegram_env_var(agent_id: str) -> str:
    key = normalize_agent_id(agent_id).upper().replace("-", "_")
    return f"ELEVATE_AGENT_{key}_TELEGRAM_CHANNEL"


def agent_telegram_bot_token_env_var(agent_id: str) -> str:
    key = normalize_agent_id(agent_id).upper().replace("-", "_")
    return f"ELEVATE_AGENT_{key}_TELEGRAM_BOT_TOKEN"


def agent_telegram_bot_token_env_vars(agent_id: str) -> tuple[str, ...]:
    normalized = normalize_agent_id(agent_id)
    return (agent_telegram_bot_token_env_var(normalized),)


def agent_telegram_env_vars(agent_id: str) -> tuple[str, ...]:
    normalized = normalize_agent_id(agent_id)
    names = [agent_telegram_env_var(normalized)]
    for legacy in _LEGACY_AGENT_TELEGRAM_ENV_VARS.get(normalized, ()):
        if legacy not in names:
            names.append(legacy)
    return tuple(names)


def _env_or_config_value(name: str) -> str:
    try:
        from elevate_cli.config import get_env_value

        value = str(get_env_value(name) or "").strip()
        if value:
            return value
    except Exception:
        pass
    return os.getenv(name, "").strip()


def _looks_like_telegram_bot_token(value: Any) -> bool:
    text = str(value or "").strip()
    if text.lower().startswith("telegram:"):
        text = text.split(":", 1)[1]
    return bool(re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{20,}", text))


def agent_telegram_bot_token(agent_id: str) -> str:
    for env_var in agent_telegram_bot_token_env_vars(agent_id):
        value = _env_or_config_value(env_var)
        if value:
            return value
    return ""


def agent_telegram_uses_shared_bot(agent_id: str) -> bool:
    token = agent_telegram_bot_token(agent_id)
    if not token:
        return False
    shared_token = _env_or_config_value("TELEGRAM_BOT_TOKEN")
    if not shared_token or token != shared_token:
        return False
    return normalize_agent_id(agent_id) != "executive-assistant"


def agent_telegram_delivery_target(agent_id: str, *, default: str = "telegram") -> str:
    for env_var in agent_telegram_env_vars(agent_id):
        value = _env_or_config_value(env_var)
        if not value:
            continue
        if _looks_like_telegram_bot_token(value):
            continue
        if value.lower().startswith("telegram:"):
            return value
        return f"telegram:{value}"
    return default


def agent_telegram_lane_ready(agent_id: str) -> bool:
    """Return True when an agent has both a bot token and delivery target."""
    token = agent_telegram_bot_token(agent_id)
    if not token or agent_telegram_uses_shared_bot(agent_id):
        return False
    return bool(agent_telegram_delivery_target(agent_id, default=""))


def parse_telegram_target(value: Any) -> tuple[str, str | None]:
    text = str(value or "").strip()
    if not text:
        return "", None
    if _looks_like_telegram_bot_token(text):
        return "", None
    if text.lower().startswith("telegram:"):
        text = text.split(":", 1)[1]
    parts = [part for part in text.split(":") if part]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return text, None


def telegram_target_matches(value: Any, *, chat_id: str, thread_id: str | None = None) -> bool:
    target_chat_id, target_thread_id = parse_telegram_target(value)
    if not target_chat_id or str(target_chat_id) != str(chat_id):
        return False
    if target_thread_id and str(target_thread_id) != str(thread_id or ""):
        return False
    return True


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _agent_defs(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        from elevate_cli.agent_hub import _load_agent_defs

        return _load_agent_defs(dict(config))
    except Exception:
        return []


def _agent_target_values(agent: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    for container in (agent, metadata):
        for key in ("telegram_target", "telegram_channel", "telegram_chat_id", "telegram"):
            value = container.get(key) if isinstance(container, Mapping) else None
            if isinstance(value, Mapping):
                value = value.get("target") or value.get("chat_id")
            if value:
                values.append(str(value))
        env_name = container.get("telegram_target_env") if isinstance(container, Mapping) else None
        if env_name:
            env_value = _env_or_config_value(str(env_name))
            if env_value:
                values.append(env_value)
    for env_var in agent_telegram_env_vars(str(agent.get("id") or agent.get("agent_id") or "")):
        value = _env_or_config_value(env_var)
        if value:
            values.append(value)
    return values


def resolve_agent_lane_for_source(
    config: Mapping[str, Any],
    *,
    platform: str,
    chat_id: str,
    thread_id: str | None = None,
    chat_topic: str | None = None,
    explicit_agent_id: str | None = None,
) -> dict[str, Any] | None:
    agents = _agent_defs(config)
    by_id = {normalize_agent_id(agent.get("id")): agent for agent in agents}
    if explicit_agent_id:
        return by_id.get(normalize_agent_id(explicit_agent_id))

    if platform == "telegram":
        for agent in agents:
            for target in _agent_target_values(agent):
                if telegram_target_matches(target, chat_id=str(chat_id), thread_id=thread_id):
                    return agent

        topic_normalized = normalize_agent_id(chat_topic)
        if topic_normalized in by_id:
            return by_id[topic_normalized]
        for agent in agents:
            if normalize_agent_id(agent.get("name")) == topic_normalized:
                return agent

    hub_cfg = config.get("agent_hub") if isinstance(config.get("agent_hub"), Mapping) else {}
    default_id = str(hub_cfg.get("default_agent") or "executive-assistant")
    return by_id.get(normalize_agent_id(default_id)) or (agents[0] if agents else None)


def merge_agent_skills(existing: Any, agent: Mapping[str, Any] | None) -> list[str] | str | None:
    merged: list[str] = []
    if agent:
        merged.extend(_as_list(agent.get("skills")))
    merged.extend(_as_list(existing))
    seen: set[str] = set()
    result: list[str] = []
    for skill in merged:
        if skill not in seen:
            seen.add(skill)
            result.append(skill)
    if not result:
        return None
    return result[0] if len(result) == 1 else result


def agent_lane_prompt(agent: Mapping[str, Any] | None) -> str:
    if not agent:
        return ""
    agent_id = normalize_agent_id(agent.get("id") or agent.get("agent_id"))
    name = str(agent.get("name") or agent.get("display_name") or agent_id).strip()
    role = str(agent.get("role") or "").strip()
    description = str(agent.get("description") or "").strip()
    prompt = str(agent.get("prompt") or "").strip()
    parts = [
        f"[Agent lane: {name} ({agent_id}).",
        "You are speaking as this agent in its own conversation lane.",
        "The Executive Assistant is the all-in-one router/coordinator; specialist agents own their narrower work and can hand tasks back or across when needed.",
    ]
    if role:
        parts.append(f"Role: {role}.")
    if description:
        parts.append(f"Description: {description}.")
    if prompt:
        parts.append(f"Agent instructions: {prompt}")
    parts.append("]")
    return " ".join(parts)
