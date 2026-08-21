"""Best-effort Telegram alert when an Admin deal run parks at ``waiting_human``.

The dashboard and stage-entry dispatch paths park runs that need a human
decision but -- unlike cron-delivered runs -- never notified anyone, so a card
could sit "waiting on you" invisibly. This module sends one best-effort Telegram
message to the Admin agent lane so the human learns a card needs input.

Design rules:
- NEVER raise. Notification must never break a deal write; every failure is
  swallowed and the caller continues.
- Non-blocking. The HTTP POST runs on a daemon thread so a slow/unreachable
  Telegram API can never stall a request handler.
"""
from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any, Mapping

_ADMIN_AGENT_ID = "admin"
_DASHBOARD_URL = "http://127.0.0.1:9120"


def _resolve_lane() -> tuple[str, str] | None:
    """Return (bot_token, chat_id) for the Admin Telegram lane, or None."""
    try:
        from gateway.agent_lanes import (
            agent_telegram_bot_token,
            agent_telegram_delivery_target,
            parse_telegram_target,
        )

        token = agent_telegram_bot_token(_ADMIN_AGENT_ID)
        # parse_telegram_target returns (chat_id, thread_id) -- chat_id is first.
        chat_id, _thread = parse_telegram_target(
            agent_telegram_delivery_target(_ADMIN_AGENT_ID)
        )
        if token and chat_id:
            return str(token), str(chat_id)
    except Exception:
        return None
    return None


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    data = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def _compose(
    deal: Mapping[str, Any] | None,
    run_name: str | None,
    human_prompt: Mapping[str, Any] | None,
) -> tuple[str, str]:
    deal = deal or {}
    address = deal.get("listingAddress") or deal.get("title") or "a deal"
    deal_id = str(deal.get("id") or "")
    lines = [f"\U0001f514 <b>Info needed</b> — {address}"]
    if run_name:
        lines.append(str(run_name))
    fields = None
    if isinstance(human_prompt, Mapping):
        fields = human_prompt.get("requiredFields")
    if isinstance(fields, (list, tuple)) and fields:
        lines.extend(f"• {item}" for item in fields)
    elif isinstance(human_prompt, Mapping) and human_prompt.get("message"):
        lines.append(str(human_prompt.get("message")))
    if deal_id:
        lines.append(f"{_DASHBOARD_URL}/admin?deal={deal_id}")
    return "\n".join(lines), deal_id


def notify_waiting_human(
    deal: Mapping[str, Any] | None,
    run_id: str,
    run_name: str | None = None,
    human_prompt: Mapping[str, Any] | None = None,
) -> bool:
    """Fire-and-forget Telegram ping that a run parked waiting for the human.

    Returns True if a send thread was started (not a delivery guarantee), False
    if the lane could not be resolved. Never raises.
    """
    try:
        lane = _resolve_lane()
        if not lane:
            return False
        token, chat_id = lane
        text, _deal_id = _compose(deal, run_name, human_prompt)

        def _worker() -> None:
            try:
                _send_telegram(token, chat_id, text)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()
        return True
    except Exception:
        return False
