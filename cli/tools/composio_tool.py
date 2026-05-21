#!/usr/bin/env python3
"""Composio connection tool — first-class agent access to the integration hub.

Why this exists
---------------
Composio in Elevate has exactly ONE supported surface: the HTTP API keyed by
``COMPOSIO_API_KEY`` in ``~/.elevate/.env`` and wrapped by
``elevate_cli.composio_client``. Connected accounts (Gmail, Instagram,
Facebook, GitHub, YouTube, ...) live there.

There is a *second*, unsupported surface that users sometimes add to their
config by hand: a ``COMPOSIO`` entry under ``mcp_servers`` pointing at
``connect.composio.dev/mcp`` with ``auth: oauth``. That hosted-MCP path is a
different integration entirely — it does its own browser OAuth handshake and
does NOT read the API key. When it is misconfigured the agent gets stuck in a
login/OAuth loop and wrongly concludes "Composio is not connected", even
though the API surface has live accounts.

This tool gives the agent a direct, deterministic way to answer
"is Composio connected and what accounts does it have" by hitting the API
surface — no OAuth, no MCP, no browser. It is read-only by design: it reports
state, it never sends messages or mutates accounts.

Behavioral guidance lives in the schema description so the agent reaches for
this tool instead of chasing the hosted-MCP OAuth flow.
"""

from __future__ import annotations

import json
from typing import Any


# --- Helpers ---------------------------------------------------------------


def _client():
    """Lazy import so importing this module never drags in httpx/tenacity."""
    from elevate_cli import composio_client

    return composio_client


def _toolkit_slug(account: dict[str, Any]) -> str:
    """Pull a toolkit slug off a connected_account record across API shapes."""
    if not isinstance(account, dict):
        return ""
    tk = account.get("toolkit")
    if isinstance(tk, dict):
        return str(tk.get("slug") or tk.get("name") or tk.get("id") or "").strip().lower()
    if isinstance(tk, str):
        return tk.strip().lower()
    return str(account.get("toolkit_slug") or "").strip().lower()


def _normalize_account(account: dict[str, Any]) -> dict[str, Any]:
    """Flatten a connected_account record to the fields the agent cares about."""
    if not isinstance(account, dict):
        return {"raw": account}
    return {
        "id": account.get("id") or account.get("connected_account_id"),
        "toolkit": _toolkit_slug(account),
        "status": account.get("status"),
        "user_id": account.get("user_id"),
    }


# --- Core ------------------------------------------------------------------


def composio_tool(action: str | None = None, *, toolkit: str | None = None, search: str | None = None) -> str:
    """Read-only Composio introspection. Returns a JSON string.

    Actions:
      - ``status``   : is the API key configured and valid
      - ``accounts`` : list connected accounts (optionally filtered to one toolkit)
      - ``toolkits`` : browse the catalog of connectable toolkits (optional search)
    """
    from tools.registry import tool_error

    act = (action or "status").strip().lower()
    client = _client()

    if act == "status":
        status = client.get_status()
        return json.dumps({"action": "status", **status}, ensure_ascii=False)

    if act == "accounts":
        status = client.get_status()
        if not status.get("hasKey"):
            return json.dumps(
                {
                    "action": "accounts",
                    "configured": False,
                    "accounts": [],
                    "note": (
                        "No COMPOSIO_API_KEY set. Composio connects via an API "
                        "key in ~/.elevate/.env — not via the hosted MCP server. "
                        "Set the key in Settings, then retry."
                    ),
                },
                ensure_ascii=False,
            )
        resp = client.list_all_connected_accounts(toolkit=(toolkit or None))
        if not resp.get("ok"):
            return tool_error(
                f"Composio accounts lookup failed: {resp.get('error')}",
                status=resp.get("status"),
            )
        items = (resp.get("data") or {}).get("items") or []
        accounts = [_normalize_account(a) for a in items]
        active = [a for a in accounts if str(a.get("status") or "").upper() == "ACTIVE"]
        return json.dumps(
            {
                "action": "accounts",
                "configured": True,
                "valid": bool(status.get("valid")),
                "total": len(accounts),
                "active_count": len(active),
                "accounts": accounts,
            },
            ensure_ascii=False,
        )

    if act == "toolkits":
        if search:
            resp = client.list_toolkits(search=search, limit=50)
            if not resp.get("ok"):
                return tool_error(f"Composio toolkit search failed: {resp.get('error')}")
            body = resp.get("data") or {}
        else:
            resp = client.list_all_toolkits()
            if not resp.get("ok"):
                return tool_error(f"Composio toolkit listing failed: {resp.get('error')}")
            body = resp.get("data") or {}
        raw = body.get("items") if isinstance(body, dict) else body
        toolkits = []
        for tk in raw or []:
            if isinstance(tk, dict):
                toolkits.append(
                    {
                        "slug": tk.get("slug") or tk.get("name"),
                        "name": tk.get("name") or tk.get("slug"),
                    }
                )
        return json.dumps(
            {"action": "toolkits", "count": len(toolkits), "toolkits": toolkits},
            ensure_ascii=False,
        )

    return tool_error(
        f"Unknown composio action '{action}'. Use one of: status, accounts, toolkits."
    )


def check_composio_requirements() -> bool:
    """Available whenever a Composio API key is configured.

    Gated on the key so a fresh install with no Composio setup does not show
    a tool that can only ever return "not configured". As soon as the user
    adds a key in Settings the tool appears on the next turn.
    """
    try:
        return bool(_client()._read_api_key())
    except Exception:
        return False


# --- Schema ----------------------------------------------------------------

COMPOSIO_SCHEMA = {
    "name": "composio",
    "description": (
        "Inspect the Composio integration hub — the connected social / "
        "messaging / dev accounts (Gmail, Instagram, Facebook, YouTube, "
        "GitHub, etc.).\n\n"
        "Use this whenever the user asks what is connected, whether Composio "
        "is set up, or which channels are available. It reads Composio's HTTP "
        "API directly using the configured COMPOSIO_API_KEY.\n\n"
        "IMPORTANT: Composio connects via that API key, NOT via a hosted MCP "
        "server or browser OAuth. Do not try to launch a Composio login / "
        "OAuth flow to check connection state — call this tool instead.\n\n"
        "Actions:\n"
        "- status   : whether the API key is configured and valid\n"
        "- accounts : list connected accounts (id, toolkit, status); pass "
        "'toolkit' to filter to one (e.g. gmail)\n"
        "- toolkits : browse the catalog of connectable toolkits; pass "
        "'search' to filter\n\n"
        "Read-only: this tool never sends messages or changes accounts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "accounts", "toolkits"],
                "description": "What to inspect. Defaults to 'status'.",
            },
            "toolkit": {
                "type": "string",
                "description": (
                    "For action=accounts: filter to a single toolkit slug, "
                    "e.g. 'gmail', 'instagram'."
                ),
            },
            "search": {
                "type": "string",
                "description": "For action=toolkits: filter the catalog by name or slug.",
            },
        },
        "required": ["action"],
    },
}


# --- Registry --------------------------------------------------------------

from tools.registry import registry

registry.register(
    name="composio",
    toolset="composio",
    schema=COMPOSIO_SCHEMA,
    handler=lambda args, **kw: composio_tool(
        action=args.get("action"),
        toolkit=args.get("toolkit"),
        search=args.get("search"),
    ),
    check_fn=check_composio_requirements,
    emoji="🔌",
)
