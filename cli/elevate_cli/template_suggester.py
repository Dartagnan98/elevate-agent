"""Generate a fresh outreach template variant for human approval.

Anchors on (a) the lane's best-performing existing template and (b) the
agent's voice from ~/.elevate/SOUL.md or the configured brand profile, so
the candidate sounds like the user — not generic LLM output.

Falls back to a minimal heuristic variant if no Anthropic key is configured,
so the approval queue is still populated for manual editing.
"""

from __future__ import annotations

import json
import os
import random
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from elevate_cli import outreach_db
from elevate_cli.config import load_env


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 600
TIMEOUT = 30.0


LANE_BRIEFS = {
    "new-outreach": "Cold first message to a brand-new lead. They have not been contacted before. Goal is to start a real conversation, not pitch.",
    "hot-leads-watcher": "Time-sensitive nudge after a live signal (just replied / just opened / CRM stage moved). Short, specific, low-pressure.",
    "follow-ups": "Re-touch on a thread that went cold (5+ days since their last reply). Goal is to reopen the loop without sounding desperate.",
}


def _voice_anchor() -> str:
    soul = Path.home() / ".elevate" / "SOUL.md"
    if soul.exists():
        try:
            text = soul.read_text(encoding="utf-8")
            return text[:1500]
        except Exception:
            pass
    return "Direct, grounded, no fluff. Short sentences. No corporate AI language."


def _anthropic_key() -> str | None:
    env = load_env()
    key = (env.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
    return key or None


def _heuristic_variant(lane: str, anchor: dict[str, Any] | None) -> dict[str, Any]:
    """Fallback when no LLM key — light shuffle of the anchor template."""
    base = anchor["body"] if anchor else "Hey {first_name}, quick one — what's the next thing you're trying to figure out?"
    name = f"Variant {random.randint(100, 999)}"
    return {
        "name": name,
        "body": base,
        "channel": (anchor or {}).get("channel", "any"),
        "rationale": "No Anthropic key configured — copied anchor as starter. Edit before approving.",
    }


def _call_anthropic(*, system: str, user: str) -> dict[str, Any] | None:
    api_key = _anthropic_key()
    if not api_key:
        return None
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(ANTHROPIC_URL, headers=headers, json=body)
        if resp.status_code >= 400:
            return None
        data = resp.json()
        for block in data.get("content", []):
            if block.get("type") == "text":
                return {"text": block.get("text", "")}
    except Exception:
        return None
    return None


def _parse_llm_output(text: str) -> dict[str, str] | None:
    """Expect a JSON block in the response. Strip code fences if present."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            text = text[first : last + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if not parsed.get("name") or not parsed.get("body"):
        return None
    return {
        "name": str(parsed["name"]).strip()[:80],
        "body": str(parsed["body"]).strip()[:1500],
        "rationale": str(parsed.get("rationale", "")).strip()[:400],
    }


def suggest_variant(
    lane: str,
    *,
    channel: str = "any",
    extra_brief: Optional[str] = None,
) -> dict[str, Any]:
    lane = outreach_db._normalize_lane(lane)
    grouped = outreach_db.list_templates_grouped()
    lane_templates = [t for t in grouped.get(lane, []) if t["active"] and t["status"] == "active"]
    lane_templates.sort(key=lambda t: (t["replyRate"], t["uses"]), reverse=True)
    anchor = lane_templates[0] if lane_templates else None

    # Build the prompt
    brief = LANE_BRIEFS.get(lane, "Outreach message.")
    voice = _voice_anchor()
    anchor_block = ""
    if anchor:
        anchor_block = (
            f"Best-performing existing template ({anchor['replyRate']*100:.0f}% reply rate "
            f"over {anchor['uses']} sends):\n"
            f"Name: {anchor['name']}\n"
            f"Body: {anchor['body']}\n"
        )
    others_block = ""
    if len(lane_templates) > 1:
        others_block = "Existing templates in this lane (do NOT repeat their phrasing):\n" + "\n".join(
            f"- {t['name']}: {t['body']}" for t in lane_templates[1:6]
        )

    system = (
        "You write outreach message variants for a real estate agent. "
        "You write in the agent's voice — direct, short, no corporate AI language, "
        "no emojis unless the anchor uses them. Never invent facts about specific listings. "
        "Use these variables only: {first_name}, {city}, {topic}, {source}, {area}, {signal}. "
        "If a variable would not have meaningful data for some leads, rewrite to not need it. "
        "Output a SINGLE JSON object with keys: name (5-8 words), body (under 350 characters), "
        "rationale (one sentence on what this tests vs the anchor). No prose outside the JSON."
    )
    user_parts = [
        f"Lane: {lane}",
        f"Lane purpose: {brief}",
        f"Channel: {channel}",
        f"Agent voice anchor:\n{voice}",
    ]
    if anchor_block:
        user_parts.append(anchor_block)
    if others_block:
        user_parts.append(others_block)
    if extra_brief:
        user_parts.append(f"Extra direction from agent: {extra_brief}")
    user_parts.append(
        "Generate ONE new variant that is meaningfully different from the anchor "
        "(different opener, different angle, or different ask) but stays in the same voice."
    )
    user = "\n\n".join(user_parts)

    llm = _call_anthropic(system=system, user=user)
    parsed: dict[str, str] | None = None
    if llm and llm.get("text"):
        parsed = _parse_llm_output(llm["text"])

    if not parsed:
        return _heuristic_variant(lane, anchor)

    return {
        "name": parsed["name"],
        "body": parsed["body"],
        "channel": channel,
        "rationale": parsed.get("rationale") or "AI-generated variant for testing.",
    }


def suggest_and_save(
    lane: str,
    *,
    channel: str = "any",
    extra_brief: Optional[str] = None,
) -> dict[str, Any]:
    """Generate a variant and persist it as pending_approval."""
    candidate = suggest_variant(lane, channel=channel, extra_brief=extra_brief)
    saved = outreach_db.create_pending_template(
        lane=lane,
        name=candidate["name"],
        body=candidate["body"],
        channel=candidate.get("channel") or "any",
        rationale=candidate.get("rationale"),
    )
    return saved
