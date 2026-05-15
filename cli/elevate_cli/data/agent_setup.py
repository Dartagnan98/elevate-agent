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

from elevate_cli.data._util import now_iso


STATE_ID = "default"
READY_STATUSES = {"configured", "connected", "manual"}
VALID_STATUSES = READY_STATUSES | {"missing", "skipped"}


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
        "description": "Used for memory recall and retrieval. Usually the same provider as your primary LLM.",
        "required": True,
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
        "key": "outbound_imessage",
        "category": "outbound",
        "label": "Outbound iMessage",
        "description": "Let the agent send via Apple Messages on this Mac. Requires Messages.app permission + the local Messages bridge.",
        "required": False,
        "sort_order": 75,
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
    gemini_key = _get("GEMINI_API_KEY", "GOOGLE_API_KEY", "NANO_BANANA_API_KEY")
    voyage_key = _get("VOYAGE_API_KEY")
    telegram_token = _get("TELEGRAM_BOT_TOKEN")
    telegram_chat = _get("TELEGRAM_CHAT_ID", "TELEGRAM_DEFAULT_CHAT_ID")
    composio_key = _get("COMPOSIO_API_KEY")
    supabase_url = _get("SUPABASE_URL")
    supabase_key = _get("SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")

    if anthropic_token:
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


def _apply_runtime_overlay(item: dict[str, Any]) -> dict[str, Any]:
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
    overlays = _detect_runtime_credentials()
    overlay = overlays.get(item["key"])
    if not overlay:
        return item

    status = item.get("status") or ""
    value = item.get("value")

    # Mode 1: untouched item gets the full overlay.
    if status == "missing" and value is None:
        merged = dict(item)
        merged["status"] = overlay.get("status", merged["status"])
        merged["provider"] = overlay.get("provider", merged["provider"])
        merged["value"] = overlay.get("value", merged["value"])
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
    for hint_key in ("secretPresent", "secretPreview", "secretSource"):
        if hint_key in overlay_value and not enriched.get(hint_key):
            enriched[hint_key] = overlay_value[hint_key]
            changed = True
    if not changed:
        return item
    merged = dict(item)
    merged["value"] = enriched
    return merged


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "required": bool(row["required"]),
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
    items = [_apply_runtime_overlay(_row_to_item(row)) for row in rows]
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
                    _encode_json(item.get("value")),
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
