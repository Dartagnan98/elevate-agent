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
- ``subagents_pack`` (optional skippable) — toggle the cortextos
  PTY-agent pack (Jimmy/Gary/Nina/Ricky/QC). Off by default for solo
  runtimes.

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
        "key": "operator_channel_telegram",
        "category": "channel",
        "label": "Telegram operator channel",
        "description": "Where the agent pings you for approvals + status. Telegram bot token + chat id.",
        "required": False,
        "sort_order": 60,
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
        "key": "subagents_pack",
        "category": "subagents",
        "label": "Sub-agents pack",
        "description": "Optional. Spin up specialist PTY agents (Jimmy / Gary / Nina / Ricky / QC). Skippable for solo runtimes.",
        "required": False,
        "sort_order": 80,
    },
]


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
    items = [_row_to_item(row) for row in rows]
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
