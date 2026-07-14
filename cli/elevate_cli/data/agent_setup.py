"""Top-level Elevate agent onboarding gate.

Captures the foundational configuration the runtime needs before it can
do anything useful:

- ``model_primary`` (required) — primary LLM provider + API key
  (Anthropic / OpenAI / OpenRouter).
- ``model_embedding`` (required) — embedding provider + API key. Used by
  memory store + retrieval. Often piggybacks on the primary LLM key.
- ``memory_store`` (required) — where session + long-term memory lives.
  Defaults to local SQLite; Supabase is the alternative.
- ``model_image`` (optional) — image generation key (Nano Banana / OpenAI
  images / Replicate). Skippable.
- ``composio_workspace`` (optional) — Composio workspace + key for the
  100+ pre-wired tools. Skippable.
- ``operator_channel_telegram`` (optional) — Telegram bot token + chat id
  for operator notifications + approvals.
- ``operator_channel_slack`` (optional) — Slack webhook + channel as the
  alternative operator surface.
- ``subagents_pack`` (optional skippable) — toggle the specialist
  PTY-agent pack (Executive Assistant / Admin / Outreach / Ads /
  Marketing / Social Media). Off by default for solo runtimes.

Required minimum quorum is just the three required items above. Everything
else is opt-in so a fresh agent can be brought up in 60 seconds and the
remaining surfaces backfilled as the operator hooks them up.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping

from elevate_constants import get_elevate_home
from elevate_cli.beta_provider_policy import (
    beta_provider_policy_active,
    build_beta_primary_overlay,
    read_beta_codex_auth_status,
)
from elevate_cli.data._util import now_iso


STATE_ID = "default"
READY_STATUSES = {"configured", "connected", "manual"}
VALID_STATUSES = READY_STATUSES | {"missing", "skipped"}

_SECRET_FIELDS_BY_ITEM: dict[str, tuple[str, ...]] = {
    "model_primary": ("apiKey",),
    "model_embedding": ("apiKey",),
    "model_image": ("apiKey",),
    "memory_store": ("supabaseKey",),
    "composio_workspace": ("apiKey",),
    "operator_channel_telegram": ("botToken",),
    "operator_channel_discord": ("botToken",),
    "operator_channel_whatsapp": ("token",),
    "operator_channel_slack": ("webhookUrl",),
}

_PRIMARY_PROVIDER_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
    "xai": ("XAI_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "zai": ("GLM_API_KEY", "ZAI_API_KEY", "ZHIPU_API_KEY", "Z_AI_API_KEY"),
    "kimi-coding": ("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    "nvidia": ("NVIDIA_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "ollama-cloud": ("OLLAMA_API_KEY",),
    "azure_openai": ("AZURE_FOUNDRY_API_KEY",),
    "azure-foundry": ("AZURE_FOUNDRY_API_KEY",),
    "qwen": ("DASHSCOPE_API_KEY",),
    "alibaba": ("DASHSCOPE_API_KEY",),
}


_DEFAULT_ITEMS: list[dict[str, Any]] = [
    {
        "key": "model_primary",
        "category": "model",
        "label": "Primary LLM",
        "description": "The model the agent thinks with. Anthropic / OpenAI / OpenRouter and an API key.",
        "required": True,
        "sort_order": 10,
    },
    {
        "key": "model_embedding",
        "category": "model",
        "label": "Embedding model",
        "description": "Optional. Sharpens semantic recall; memory falls back to keyword search without it.",
        "required": False,
        "sort_order": 20,
    },
    {
        "key": "model_image",
        "category": "model",
        "label": "Image generation (Nano Banana)",
        "description": "Optional. The Nano Banana Gemini-CLI extension ships pre-installed — just drop in a Gemini API key from AI Studio and the /generate, /edit, /restore, /icon, /pattern, /story, /diagram commands light up.",
        "required": False,
        "sort_order": 30,
    },
    {
        "key": "tts_provider",
        "category": "tts",
        "label": "Text-to-Speech provider",
        "description": "Optional. Voice for the agent. Edge TTS (free), ElevenLabs, OpenAI TTS, xAI, MiniMax, Mistral, Gemini, NeuTTS, KittenTTS.",
        "required": False,
        "sort_order": 32,
    },
    {
        "key": "terminal_backend",
        "category": "terminal",
        "label": "Terminal backend",
        "description": "Where the agent runs shell commands. Local, Docker, Modal, SSH, Daytona, or Singularity. Local is fine for most operators.",
        "required": False,
        "sort_order": 34,
    },
    {
        "key": "agent_settings",
        "category": "agent_settings",
        "label": "Agent settings",
        "description": "Max iterations, tool progress mode, compression threshold, session reset cadence.",
        "required": False,
        "sort_order": 36,
    },
    {
        "key": "memory_store",
        "category": "memory",
        "label": "Memory store",
        "description": "Where the agent keeps long-term memory. Local SQLite works out of the box; Supabase if you want it shared.",
        "required": True,
        "sort_order": 40,
    },
    {
        "key": "composio_workspace",
        "category": "tools",
        "label": "Composio workspace",
        "description": "Optional. Connects 100+ pre-wired tools (Gmail, Calendar, Slack, etc.). Skip if you don't use Composio.",
        "required": False,
        "sort_order": 50,
    },
    {
        "key": "operator_channel_cli",
        "category": "channel",
        "label": "CLI",
        "description": "Talk to the agent inside the terminal. Always on — confirm it's the surface you want.",
        "required": False,
        "sort_order": 55,
    },
    {
        "key": "operator_channel_telegram",
        "category": "channel",
        "label": "Telegram operator channel",
        "description": "Where the agent pings you for approvals + status. Telegram bot token + chat id.",
        "required": False,
        "sort_order": 60,
    },
    {
        "key": "operator_channel_imessage",
        "category": "channel",
        "label": "iMessage operator channel",
        "description": "Pipe inbound iMessage threads into the agent via the local Messages database.",
        "required": False,
        "sort_order": 62,
    },
    {
        "key": "operator_channel_discord",
        "category": "channel",
        "label": "Discord operator channel",
        "description": "Bot token + channel id. Inbound DMs + channel pings route to the agent.",
        "required": False,
        "sort_order": 64,
    },
    {
        "key": "operator_channel_whatsapp",
        "category": "channel",
        "label": "WhatsApp operator channel",
        "description": "WhatsApp Business API or Composio gateway. Inbound messages route to the agent.",
        "required": False,
        "sort_order": 66,
    },
    {
        "key": "operator_channel_slack",
        "category": "channel",
        "label": "Slack operator channel",
        "description": "Alternative operator surface. Incoming webhook + target channel.",
        "required": False,
        "sort_order": 70,
    },
    {
        "key": "operator_channel_signal",
        "category": "channel",
        "label": "Signal operator channel",
        "description": "signal-cli bridge — paste the local HTTP URL plus your E.164 account.",
        "required": False,
        "sort_order": 71,
    },
    {
        "key": "operator_channel_matrix",
        "category": "channel",
        "label": "Matrix operator channel",
        "description": "Homeserver URL + access token (or password). Optional E2EE.",
        "required": False,
        "sort_order": 71.1,
    },
    {
        "key": "operator_channel_mattermost",
        "category": "channel",
        "label": "Mattermost operator channel",
        "description": "Mattermost server URL + bot token.",
        "required": False,
        "sort_order": 71.2,
    },
    {
        "key": "operator_channel_email",
        "category": "channel",
        "label": "Email operator channel",
        "description": "Email (IMAP/SMTP). Gmail: enable 2FA + use an App Password.",
        "required": False,
        "sort_order": 71.3,
    },
    {
        "key": "operator_channel_sms",
        "category": "channel",
        "label": "SMS (Twilio) operator channel",
        "description": "Twilio SID + auth token + E.164 phone number for inbound/outbound SMS.",
        "required": False,
        "sort_order": 71.4,
    },
    {
        "key": "operator_channel_dingtalk",
        "category": "channel",
        "label": "DingTalk operator channel",
        "description": "AppKey + AppSecret (manual) or QR scan inside the DingTalk app.",
        "required": False,
        "sort_order": 71.5,
    },
    {
        "key": "operator_channel_feishu",
        "category": "channel",
        "label": "Feishu / Lark operator channel",
        "description": "App ID + App Secret + domain (feishu/lark). WebSocket or Webhook mode.",
        "required": False,
        "sort_order": 71.6,
    },
    {
        "key": "operator_channel_wecom",
        "category": "channel",
        "label": "WeCom (Enterprise WeChat) operator channel",
        "description": "Bot ID + secret. Optional allowlist + home chat.",
        "required": False,
        "sort_order": 71.7,
    },
    {
        "key": "operator_channel_wecom_callback",
        "category": "channel",
        "label": "WeCom Callback (self-built app)",
        "description": "Corp ID + Corp Secret + Agent ID + Callback Token + Encoding AES key.",
        "required": False,
        "sort_order": 71.8,
    },
    {
        "key": "operator_channel_weixin",
        "category": "channel",
        "label": "Weixin / WeChat operator channel",
        "description": "QR login writes account id + token. DM policy + group policy configurable.",
        "required": False,
        "sort_order": 71.9,
    },
    {
        "key": "operator_channel_qqbot",
        "category": "channel",
        "label": "QQ Bot operator channel",
        "description": "App ID + App Secret (manual) or QR scan.",
        "required": False,
        "sort_order": 72.0,
    },
    {
        "key": "operator_channel_webhooks",
        "category": "channel",
        "label": "Generic webhooks",
        "description": "Inbound HTTP webhook listener with shared HMAC secret. Port + secret.",
        "required": False,
        "sort_order": 72.2,
    },
    {
        "key": "outbound_imessage",
        "category": "outbound",
        "label": "Outbound iMessage",
        "description": "Let the agent send via Apple Messages on this Mac. Requires Messages.app permission + the local Messages bridge.",
        "required": False,
        "sort_order": 75,
    },
    {
        "key": "outbound_telegram",
        "category": "outbound",
        "label": "Outbound Telegram",
        "description": "Let the agent send Telegram replies. Uses the bot token wired in the Telegram channel step.",
        "required": False,
        "sort_order": 76,
    },
    {
        "key": "outbound_discord",
        "category": "outbound",
        "label": "Outbound Discord",
        "description": "Let the agent send Discord messages. Uses the bot token wired in the Discord channel step.",
        "required": False,
        "sort_order": 77,
    },
    {
        "key": "outbound_whatsapp",
        "category": "outbound",
        "label": "Outbound WhatsApp",
        "description": "Let the agent send WhatsApp messages via the Baileys bridge or the Meta Cloud API.",
        "required": False,
        "sort_order": 78,
    },
    {
        "key": "outbound_slack",
        "category": "outbound",
        "label": "Outbound Slack",
        "description": "Let the agent post to Slack. Uses the bot token wired in the Slack channel step.",
        "required": False,
        "sort_order": 79,
    },
    {
        "key": "subagents_pack",
        "category": "subagents",
        "label": "Sub-agents pack",
        "description": "Optional. Spin up specialist PTY agents (Executive Assistant / Admin / Outreach / Ads / Marketing / Social Media). Skippable for solo runtimes.",
        "required": False,
        "sort_order": 80,
    },
    {
        "key": "agent_channel_routing",
        "category": "channel",
        "label": "Per-agent channel routing",
        "description": (
            "Optional. Wire each agent (Executive Assistant / Admin / Outreach / Ads / "
            "Marketing / Social Media) to one or more channels — Telegram chat ids, "
            "iMessage handles, Slack channels, Discord channels, WhatsApp numbers. "
            "Multiple entries per slot are allowed. No fallback — an agent with no "
            "channels wired only acts when another agent hands work to it."
        ),
        "required": False,
        "sort_order": 90,
    },
]


SUBAGENT_KEYS = [
    "executive-assistant",
    "admin",
    "outreach",
    "ads",
    "marketing",
    "social-media",
]
AGENT_CHANNEL_TYPES = ["telegram", "imessage", "slack", "discord", "whatsapp"]


def _ensure_seeded(conn: sqlite3.Connection) -> None:
    """Seed default items + state row exactly once."""
    now = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO agent_setup_state(id, created_at, updated_at) VALUES (?, ?, ?)",
        (STATE_ID, now, now),
    )
    for item in _DEFAULT_ITEMS:
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_setup_items
                (key, category, label, description, required, status, provider, value_json, notes, sort_order, updated_at)
            VALUES (?, ?, ?, ?, ?, 'missing', NULL, NULL, NULL, ?, ?)
            """,
            (
                item["key"],
                item["category"],
                item["label"],
                item.get("description"),
                1 if item["required"] else 0,
                item["sort_order"],
                now,
            ),
        )
    _scrub_persisted_secrets(conn)


def _encode_json(value: Any) -> str | None:
    import json
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _decode_json(value: str | None) -> Any:
    import json
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _sanitize_value_for_storage(key: str, value: Any) -> Any:
    """Never persist onboarding secrets in the readiness database."""
    if not isinstance(value, dict):
        return value
    sanitized = dict(value)
    for field in _SECRET_FIELDS_BY_ITEM.get(key, ()):
        if field in sanitized:
            sanitized[field] = ""
    return sanitized


def _scrub_persisted_secrets(conn: sqlite3.Connection) -> None:
    """Remove plaintext secrets written by older onboarding builds."""
    rows = conn.execute(
        "SELECT key, value_json FROM agent_setup_items WHERE value_json IS NOT NULL"
    ).fetchall()
    for row in rows:
        key = row["key"]
        value = _decode_json(row["value_json"])
        sanitized = _sanitize_value_for_storage(key, value)
        if sanitized != value:
            conn.execute(
                "UPDATE agent_setup_items SET value_json=? WHERE key=?",
                (_encode_json(sanitized), key),
            )


def _token_preview(value: str | None, visible: int = 4) -> str:
    if not value:
        return ""
    s = str(value).strip()
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _detect_runtime_credentials() -> dict[str, dict[str, Any]]:
    """Detect provider credentials already wired into the runtime.

    Returns a map of item-key → in-memory overlay values. The wizard reads
    these so it can show "this is already set up" instead of an empty form.
    Only the public-safe fields (provider, model defaults, masked previews,
    secret_present flags) are surfaced; the raw secret stays in env / file.
    """
    import os

    # Pull from os.environ first, then fall back to ~/.elevate/.env so we
    # surface anything the user wrote into the dotenv file even if the
    # running process hasn't reloaded it yet.
    file_env: dict[str, str] = {}
    try:
        from elevate_cli.config import load_env as _load_env

        file_env = _load_env() or {}
    except Exception:
        file_env = {}

    def _get(*names: str) -> str | None:
        for name in names:
            val = os.environ.get(name)
            if val:
                return val
            val = file_env.get(name)
            if val:
                return val
        return None

    overlays: dict[str, dict[str, Any]] = {}

    anthropic_token = _get("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    openai_key = _get("OPENAI_API_KEY")
    primary_gemini_key = _get(
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"
    )
    gemini_key = primary_gemini_key or _get("NANO_BANANA_API_KEY")
    voyage_key = _get("VOYAGE_API_KEY")
    telegram_token = _get("TELEGRAM_BOT_TOKEN")
    telegram_chat = _get("TELEGRAM_CHAT_ID", "TELEGRAM_DEFAULT_CHAT_ID")
    composio_key = _get("COMPOSIO_API_KEY")
    supabase_url = _get("SUPABASE_URL")
    supabase_key = _get("SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")

    try:
        from elevate_cli.config import (
            get_compatible_custom_providers as _get_custom_providers,
            load_config as _load_cfg,
        )

        _cfg = _load_cfg() or {}
        _cfg_model = _cfg.get("model") or {}
        _custom_providers = _get_custom_providers(_cfg)
    except Exception:
        _cfg = {}
        _cfg_model = {}
        _custom_providers = []
    if not isinstance(_cfg_model, dict):
        _cfg_model = {}

    _cfg_provider = str(_cfg_model.get("provider") or "").strip()
    _cfg_default = str(_cfg_model.get("default") or _cfg_model.get("model") or "").strip()
    beta_policy_enabled = beta_provider_policy_active()

    if beta_policy_enabled:
        beta_auth_status = read_beta_codex_auth_status(get_elevate_home())
        overlays["model_primary"] = build_beta_primary_overlay(
            _cfg,
            beta_auth_status,
        )

    def _matching_primary_credential(provider: str) -> tuple[str, str | None] | None:
        """Return (source, secret) only for the configured provider."""
        try:
            from elevate_cli import auth as _auth
            from elevate_cli.providers import resolve_provider_full
        except Exception:
            return None

        user_providers = _cfg.get("providers") if isinstance(_cfg.get("providers"), dict) else {}
        try:
            provider_def = resolve_provider_full(provider, user_providers, _custom_providers)
        except Exception:
            provider_def = None
        try:
            runtime_provider = _auth.resolve_provider(provider)
        except Exception:
            runtime_provider = str(getattr(provider_def, "id", "") or provider).strip().lower()

        def _runtime_prerequisites_ready() -> bool:
            if runtime_provider != "azure-foundry":
                return True
            return bool(
                str(_cfg_model.get("base_url") or "").strip()
                or _get("AZURE_FOUNDRY_BASE_URL")
            )

        provider_config = _auth.PROVIDER_REGISTRY.get(runtime_provider)
        auth_type = (
            provider_config.auth_type
            if provider_config is not None
            else str(getattr(provider_def, "auth_type", "api_key") or "api_key")
        )
        if auth_type != "api_key":
            try:
                status = _auth.get_auth_status(runtime_provider)
            except Exception:
                status = {}
            return ("oauth", None) if status.get("logged_in") else None

        config_entries: list[dict[str, Any]] = []
        direct_entry = user_providers.get(provider) if isinstance(user_providers, dict) else None
        if isinstance(direct_entry, dict):
            config_entries.append(direct_entry)
        requested = provider.strip().lower()
        for entry in _custom_providers:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip().lower()
            provider_key = str(entry.get("provider_key") or "").strip().lower()
            slug = f"custom:{name.replace(' ', '-')}" if name else ""
            if requested in {name, provider_key, slug}:
                config_entries.append(entry)

        env_names: list[str] = []
        for hint in ("key_env", "api_key_env"):
            name = str(_cfg_model.get(hint) or "").strip()
            if name:
                env_names.append(name)
        exact_env_names = _PRIMARY_PROVIDER_ENV_NAMES.get(requested)
        if exact_env_names is not None:
            env_names.extend(exact_env_names)
        else:
            env_names.extend(getattr(provider_def, "api_key_env_vars", ()) or ())
            if provider_config is not None:
                env_names.extend(provider_config.api_key_env_vars)
        for entry in config_entries:
            name = str(entry.get("key_env") or "").strip()
            if name:
                env_names.append(name)

        seen: set[str] = set()
        for name in env_names:
            if not name or name in seen:
                continue
            seen.add(name)
            secret = _get(name)
            if secret and _auth.has_usable_secret(secret):
                return ("env", secret) if _runtime_prerequisites_ready() else None

        for entry in config_entries:
            secret = str(entry.get("api_key") or "").strip()
            if secret and _auth.has_usable_secret(secret):
                return (
                    ("config_inline", secret)
                    if _runtime_prerequisites_ready()
                    else None
                )

        if runtime_provider == "anthropic":
            try:
                from agent.anthropic_adapter import (
                    is_claude_code_token_valid,
                    read_claude_code_credentials,
                    read_elevate_oauth_credentials,
                )

                if any(
                    creds and is_claude_code_token_valid(creds)
                    for creds in (
                        read_elevate_oauth_credentials(),
                        read_claude_code_credentials(),
                    )
                ):
                    return "oauth", None
            except Exception:
                pass
        return None

    if beta_policy_enabled:
        # Primary inference is owned by the Beta policy above.  Do not inspect
        # ambient/profile API keys or invoke the mutable OAuth status path.
        pass
    elif _cfg_provider and _cfg_default:
        matched = _matching_primary_credential(_cfg_provider)
        secret_source, matched_secret = matched or ("config", None)
        overlays["model_primary"] = {
            "status": "configured" if matched else "missing",
            "provider": _cfg_provider,
            "value": {
                "model": _cfg_default,
                "runtimeProvider": _cfg_provider,
                "apiKey": "",
                "secretPresent": bool(matched),
                "secretSource": secret_source,
                "secretPreview": _token_preview(matched_secret),
            },
        }
    elif _matching_primary_credential("openai-codex"):
        overlays["model_primary"] = {
            "status": "configured",
            "provider": "openai-codex",
            "value": {
                "model": "gpt-5.5",
                "runtimeProvider": "openai-codex",
                "apiKey": "",
                "secretPresent": True,
                "secretSource": "oauth",
            },
        }
    elif anthropic_token:
        overlays["model_primary"] = {
            "status": "configured",
            "provider": "anthropic",
            "value": {
                "model": "claude-opus-4-7",
                "apiKey": "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(anthropic_token),
            },
        }
    elif openai_key:
        overlays["model_primary"] = {
            "status": "configured",
            "provider": "openai",
            "value": {
                "model": "gpt-4-turbo",
                "apiKey": "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(openai_key),
            },
        }
    elif primary_gemini_key:
        overlays["model_primary"] = {
            "status": "configured",
            "provider": "gemini",
            "value": {
                "model": "gemini-2.5-flash",
                "runtimeProvider": "gemini",
                "apiKey": "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(primary_gemini_key),
            },
        }

    embedding_key = voyage_key or openai_key or anthropic_token
    if embedding_key:
        if voyage_key:
            provider, model = "voyage", "voyage-3"
        elif openai_key:
            provider, model = "openai", "text-embedding-3-large"
        else:
            provider, model = "anthropic", "voyage-3"
        shares_primary = bool(anthropic_token and not (voyage_key or openai_key)) or (
            openai_key and overlays.get("model_primary", {}).get("provider") == "openai"
        )
        overlays["model_embedding"] = {
            "status": "configured",
            "provider": provider,
            "value": {
                "model": model,
                "apiKey": "",
                "sharesPrimaryKey": bool(shares_primary),
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(embedding_key),
            },
        }

    if gemini_key:
        overlays["model_image"] = {
            "status": "configured",
            "provider": "gemini",
            "value": {
                "apiKey": "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(gemini_key),
            },
        }

    overlays["memory_store"] = {
        "status": "configured",
        "provider": "supabase" if (supabase_url and supabase_key) else "sqlite_local",
        "value": {
            "supabaseUrl": supabase_url or "",
            "supabaseKey": "",
            "secretPresent": bool(supabase_key),
            "secretSource": "env" if supabase_key else None,
            "secretPreview": _token_preview(supabase_key) if supabase_key else "",
        },
    }

    if composio_key:
        overlays["composio_workspace"] = {
            "status": "configured",
            "provider": "composio",
            "value": {
                "apiKey": "",
                "workspace": _get("COMPOSIO_WORKSPACE") or "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(composio_key),
            },
        }

    if telegram_token:
        overlays["operator_channel_telegram"] = {
            "status": "configured",
            "provider": "telegram",
            "value": {
                "botToken": "",
                "chatId": telegram_chat or "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(telegram_token),
                # Mirror the full CLI _setup_telegram surface so the wizard
                # can show the existing config instead of an empty form.
                "allowedUsers": _get("TELEGRAM_ALLOWED_USERS") or "",
                "homeChannel": _get("TELEGRAM_HOME_CHANNEL") or "",
                "dmBehavior": _get("TELEGRAM_UNAUTHORIZED_DM_BEHAVIOR") or "",
                "allowAllUsers": (_get("GATEWAY_ALLOW_ALL_USERS") or "").lower() == "true",
            },
        }

    # CLI is the always-on surface. The fact that this code is executing
    # means the user is talking to Elevate — surface it as configured so the
    # wizard never paints CLI as "Off".
    overlays["operator_channel_cli"] = {
        "status": "configured",
        "provider": "elevate-cli",
        "value": {"enabled": True, "alwaysOn": True},
    }

    # iMessage — BlueBubbles bridge first (works on any machine), then
    # local Messages.db (Mac-only, requires Full Disk Access). Either
    # path flips the channel to configured.
    bluebubbles_url = _get("BLUEBUBBLES_SERVER_URL")
    bluebubbles_password = _get("BLUEBUBBLES_PASSWORD")
    if bluebubbles_url and bluebubbles_password:
        overlays["operator_channel_imessage"] = {
            "status": "configured",
            "provider": "bluebubbles",
            "value": {
                "handle": _get("BLUEBUBBLES_HOME_CHANNEL") or "",
                "secretSource": "env",
                "secretPresent": True,
                "secretPreview": _token_preview(bluebubbles_password),
                "bluebubblesServerUrl": bluebubbles_url,
                "bluebubblesAllowedUsers": _get("BLUEBUBBLES_ALLOWED_USERS") or "",
                "bluebubblesHomeChannel": _get("BLUEBUBBLES_HOME_CHANNEL") or "",
            },
        }
    else:
        try:
            from pathlib import Path

            messages_db = Path.home() / "Library" / "Messages" / "chat.db"
            if messages_db.exists() and os.access(messages_db, os.R_OK):
                overlays["operator_channel_imessage"] = {
                    "status": "configured",
                    "provider": "imessage",
                    "value": {"handle": "", "secretSource": "macos"},
                }
        except Exception:
            pass

    discord_token = _get("DISCORD_BOT_TOKEN")
    discord_channel = _get("DISCORD_CHANNEL_ID")
    if discord_token and discord_channel:
        overlays["operator_channel_discord"] = {
            "status": "configured",
            "provider": "discord",
            "value": {
                "botToken": "",
                "channelId": discord_channel,
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(discord_token),
            },
        }

    whatsapp_token = _get("WHATSAPP_TOKEN", "WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone = _get("WHATSAPP_PHONE_ID", "WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_provider = _get("WHATSAPP_PROVIDER") or (
        "meta_cloud_api" if whatsapp_token else None
    )
    if whatsapp_token and whatsapp_provider:
        overlays["operator_channel_whatsapp"] = {
            "status": "configured",
            "provider": "whatsapp",
            "value": {
                "provider": whatsapp_provider,
                "token": "",
                "phoneId": whatsapp_phone or "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(whatsapp_token),
            },
        }

    slack_webhook = _get("SLACK_WEBHOOK_URL")
    slack_channel = _get("SLACK_DEFAULT_CHANNEL", "SLACK_CHANNEL")
    if slack_webhook:
        overlays["operator_channel_slack"] = {
            "status": "configured",
            "provider": "slack",
            "value": {
                "webhookUrl": "",
                "channel": slack_channel or "",
                "secretPresent": True,
                "secretSource": "env",
                "secretPreview": _token_preview(slack_webhook),
            },
        }

    return overlays


def _apply_runtime_overlay(
    item: dict[str, Any],
    overlays: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Surface detected runtime credentials into the wizard snapshot.

    Two modes:
      1. Item is still untouched (status='missing' + value is None) →
         pre-fill provider + model + masked preview so the wizard shows
         "already configured" instead of an empty form.
      2. Item is already configured but the saved value has no apiKey
         (the operator stored the choice without re-pasting the secret) →
         enrich the saved value with secretPresent + secretPreview so the
         wizard input shows "Already set — …last4 (paste to replace)" on
         re-runs. Persisted provider/model/apiKey always win.
    """
    if overlays is None:
        overlays = _detect_runtime_credentials()
    item_key = item["key"]
    overlay = overlays.get(item_key)
    if not overlay:
        if item_key == "model_primary" and item.get("provider"):
            merged = dict(item)
            merged["status"] = "missing"
            return merged
        return item

    if item_key == "model_primary" and beta_provider_policy_active():
        # Beta primary state is server-authoritative.  A stale persisted
        # provider/model must never override the policy overlay.  When config
        # is fresh but the setup DB contains an older selection, surface that
        # selection as explicitly blocked rather than silently hiding it.
        overlay_value = overlay.get("value") or {}
        persisted_value = item.get("value")
        persisted_value = persisted_value if isinstance(persisted_value, dict) else {}
        if (
            not overlay_value.get("configuredProvider")
            and not overlay_value.get("configuredModel")
            and (item.get("provider") or persisted_value.get("model"))
        ):
            overlay = build_beta_primary_overlay(
                {
                    "model": {
                        "provider": item.get("provider"),
                        "default": persisted_value.get("model"),
                    }
                },
                {
                    "logged_in": bool(overlay_value.get("authReady")),
                    "reason": overlay_value.get("authReason"),
                },
            )
        merged = dict(item)
        merged["status"] = overlay["status"]
        merged["provider"] = overlay["provider"]
        merged["value"] = overlay["value"]
        merged["detected"] = overlay["status"] in READY_STATUSES
        return merged

    status = item.get("status") or ""
    value = item.get("value")

    # Required readiness is server-derived. A client-declared configured
    # primary is valid only when the exact runtime provider has a credential.
    if item_key == "model_primary" and item.get("provider") and isinstance(value, dict):
        expected_provider = str(value.get("runtimeProvider") or item.get("provider") or "").strip()
        detected_provider = str(overlay.get("provider") or "").strip()
        ready = (
            overlay.get("status") in READY_STATUSES
            and detected_provider == expected_provider
        )
        merged = dict(item)
        merged["status"] = "configured" if ready else "missing"
        enriched = dict(value)
        overlay_value = overlay.get("value") or {}
        for hint_key in ("secretPresent", "secretPreview", "secretSource"):
            if hint_key in overlay_value:
                enriched[hint_key] = overlay_value[hint_key]
        merged["value"] = enriched
        merged["detected"] = bool(ready)
        return merged

    # Local memory is intrinsically ready; Supabase is ready only when both
    # URL and key are detected from the runtime profile.
    if item_key == "memory_store" and item.get("provider") and isinstance(value, dict):
        selected_provider = str(item.get("provider") or "").strip()
        ready = selected_provider == "sqlite_local" or (
            selected_provider == "supabase"
            and overlay.get("status") in READY_STATUSES
            and overlay.get("provider") == "supabase"
        )
        merged = dict(item)
        merged["status"] = "configured" if ready else "missing"
        enriched = dict(value)
        overlay_value = overlay.get("value") or {}
        for hint_key in ("secretPresent", "secretPreview", "secretSource"):
            if hint_key in overlay_value:
                enriched[hint_key] = overlay_value[hint_key]
        merged["value"] = enriched
        merged["detected"] = bool(ready)
        return merged

    # Mode 1: untouched item gets the full overlay.
    if status == "missing" and value is None:
        merged = dict(item)
        merged["status"] = overlay.get("status", merged["status"])
        merged["provider"] = overlay.get("provider", merged["provider"])
        merged["value"] = overlay.get("value", merged["value"])
        merged["detected"] = True
        return merged

    # Mode 1b: item was persisted as missing/skipped with no real value but
    # env vars have since been wired (e.g. operator ran BlueBubbles bridge
    # setup or pasted TELEGRAM_BOT_TOKEN after the first wizard pass).
    # Promote to the overlay's status/provider/value so the wizard shows
    # the new credentials instead of the stale "off" state.
    persisted_provider = item.get("provider") or ""
    if status in {"missing", "skipped"} and not persisted_provider:
        merged = dict(item)
        merged["status"] = overlay.get("status", merged["status"])
        merged["provider"] = overlay.get("provider", merged["provider"])
        if isinstance(value, dict) and isinstance(overlay.get("value"), dict):
            # Merge: env-detected fields fill in, but anything the operator
            # actually typed (e.g. a handle) wins.
            merged_value = {**overlay["value"], **{k: v for k, v in value.items() if v not in (None, "", False)}}
            merged["value"] = merged_value
        else:
            merged["value"] = overlay.get("value", value)
        merged["detected"] = True
        return merged

    # Mode 1c: item has a persisted provider but is still flagged missing —
    # e.g. the wizard saved an OAuth provider choice (gpt-5.5 via Codex) that
    # carries no API key, so the save couldn't prove a credential. If the
    # runtime now detects a ready credential for it (config-pinned model, OAuth
    # login, or env key), promote the STATUS only and keep the operator's
    # provider/model. Without this the readiness gate reports the chosen primary
    # as "missing" forever for OAuth-only setups.
    if status in {"missing", "skipped"} and overlay.get("status") in READY_STATUSES:
        merged = dict(item)
        merged["status"] = overlay["status"]
        merged["detected"] = True
        return merged

    # Mode 2: enrich an already-saved item with secret previews so re-run
    # wizards know the env still has the key. Never overwrite what the
    # operator actually typed.
    if not isinstance(value, dict):
        return item
    overlay_value = overlay.get("value") or {}
    enriched = dict(value)
    changed = False
    # Always keep secret hints fresh.
    for hint_key in ("secretPresent", "secretPreview", "secretSource"):
        if hint_key in overlay_value and not enriched.get(hint_key):
            enriched[hint_key] = overlay_value[hint_key]
            changed = True
    # For provider-specific config (BlueBubbles URL, Telegram allowlist,
    # etc.), surface overlay values only when the operator hasn't typed
    # something different. Keys must be opt-in to avoid leaking unrelated
    # overlay data onto a persisted item.
    for hint_key in (
        "bluebubblesServerUrl",
        "bluebubblesAllowedUsers",
        "bluebubblesHomeChannel",
        "allowedUsers",
        "homeChannel",
        "dmBehavior",
        "allowAllUsers",
    ):
        if hint_key in overlay_value and hint_key not in enriched:
            enriched[hint_key] = overlay_value[hint_key]
            changed = True
    if not changed:
        return item
    merged = dict(item)
    merged["value"] = enriched
    return merged


# Canonical required-ness lives in code (_DEFAULT_ITEMS), not the seeded DB
# rows — so flipping an item required→optional (e.g. model_embedding) takes
# effect on existing installs without a re-seed/migration.
_REQUIRED_BY_KEY = {it["key"]: bool(it["required"]) for it in _DEFAULT_ITEMS}


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "required": _REQUIRED_BY_KEY.get(row["key"], bool(row["required"])),
        "status": row["status"],
        "provider": row["provider"],
        "value": _decode_json(row["value_json"]),
        "notes": row["notes"],
        "sortOrder": row["sort_order"],
        "updatedAt": row["updated_at"],
    }


def _item_counts_ready(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status") or "")
    return status in READY_STATUSES


def _snapshot(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> dict[str, Any]:
    required = [item for item in items if item["required"]]
    complete_required = [item for item in required if _item_counts_ready(item)]
    missing = [item for item in required if not _item_counts_ready(item)]
    missing_keys = [item["key"] for item in missing]

    state_row = conn.execute(
        "SELECT * FROM agent_setup_state WHERE id=?", (STATE_ID,)
    ).fetchone()
    completed_at = state_row["completed_at"] if state_row else None

    required_count = len(required)
    completed_count = len(complete_required)
    complete = completed_count == required_count

    return {
        "items": items,
        "requiredCount": required_count,
        "completedRequiredCount": completed_count,
        "missingRequiredKeys": missing_keys,
        "completionPct": round((completed_count / required_count) * 100) if required_count else 100,
        "complete": complete,
        "completedAt": completed_at,
        "launchRequired": not complete,
    }


def get_agent_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    _ensure_seeded(conn)
    rows = conn.execute(
        "SELECT * FROM agent_setup_items ORDER BY sort_order ASC, key ASC"
    ).fetchall()
    overlays = _detect_runtime_credentials()
    items = [_apply_runtime_overlay(_row_to_item(row), overlays) for row in rows]
    return _snapshot(conn, items)


def update_agent_setup(
    conn: sqlite3.Connection,
    *,
    items: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    _ensure_seeded(conn)
    now = now_iso()
    if items:
        for item in items:
            key = str(item.get("key") or "").strip()
            if not key:
                raise ValueError("agent setup item key is required")
            row = conn.execute(
                "SELECT key FROM agent_setup_items WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                raise LookupError(f"agent setup item {key!r} not found")
            status = str(item.get("status") or "missing").strip()
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid agent setup status {status!r}")
            conn.execute(
                """
                UPDATE agent_setup_items
                SET status=?, provider=?, value_json=?, notes=?, updated_at=?
                WHERE key=?
                """,
                (
                    status,
                    _clean_text(item.get("provider")),
                    _encode_json(_sanitize_value_for_storage(key, item.get("value"))),
                    _clean_text(item.get("notes")),
                    now,
                    key,
                ),
            )
    conn.execute(
        "UPDATE agent_setup_state SET updated_at=? WHERE id=?",
        (now, STATE_ID),
    )
    return get_agent_setup(conn)


def complete_agent_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    """Mark the gate as complete if all required items are ready.

    Raises ``ValueError`` if there are still missing required keys — the
    caller should surface that as a 409 rather than silently mark green.
    """
    snapshot = get_agent_setup(conn)
    if not snapshot["complete"]:
        raise ValueError(
            "Agent setup is not complete. Missing: "
            + ", ".join(snapshot["missingRequiredKeys"])
        )
    now = now_iso()
    conn.execute(
        "UPDATE agent_setup_state SET completed_at=?, updated_at=? WHERE id=?",
        (now, now, STATE_ID),
    )
    return get_agent_setup(conn)


def reset_agent_setup(conn: sqlite3.Connection) -> dict[str, Any]:
    """Re-open the gate without wiping item state. Used by 'Re-run onboarding'."""
    _ensure_seeded(conn)
    now = now_iso()
    conn.execute(
        "UPDATE agent_setup_state SET completed_at=NULL, updated_at=? WHERE id=?",
        (now, STATE_ID),
    )
    return get_agent_setup(conn)
