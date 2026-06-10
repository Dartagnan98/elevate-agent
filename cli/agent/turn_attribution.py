"""Attribute a finished agent turn to the deal(s) / contact(s) it worked on,
and record that activity so the Admin/Leads board reflects it.

The problem
-----------
When the agent works a deal through generic tools — drafting a counter,
reading a contract PDF, prepping docs — no ``deal_id`` flows through those
tools, so the turn leaves no trace on the deal and the board's freshness
(``deals.updated_at`` / ``contacts.last_activity_at``) goes stale while real
work happens. The formal tools (``admin_deal``) already log themselves; this
closes the gap for everything else.

How attribution works (deterministic, no LLM)
---------------------------------------------
For the just-finished turn we resolve touched entities in three escalating
ways, highest-confidence first:

1. **Explicit id** — a ``deal_id`` / ``contact_id`` in any tool's arguments
   (confidence 1.0).
2. **Entity-index match** — the turn's text (user message, assistant reply,
   tool args/results: draft bodies, file paths, queries) contains a deal's
   listing address/title or a contact's full name / email (confidence ~0.8).
3. **Session-sticky** — an entity referenced explicitly EARLIER in this same
   session boosts an otherwise-weak single-token match over the bar.

Only attributions at or above ``AUTO_LOG_THRESHOLD`` are logged. An entity the
agent ALREADY formally updated this turn (a real ``admin_deal`` mutation) is
skipped — it logged itself. Everything here is best-effort: a failure must
never break the turn.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Confidence at/above which an attribution is auto-logged.
AUTO_LOG_THRESHOLD = 0.7

# Tools whose presence (with action != show/list) means the agent FORMALLY
# updated that deal this turn — it logged itself, so skip the activity marker.
_DEAL_MUTATION_TOOLS = {"admin_deal"}
_DEAL_READONLY_ACTIONS = {"show", "list", "", None}

# Min length for an address/title substring to count as a match — short
# strings ("12", "the") would false-positive everywhere.
_MIN_SUBSTR = 6


@dataclass
class Attribution:
    entity_kind: str  # "deal" | "contact"
    entity_id: str
    confidence: float
    label: str  # human label (address / name) for logs
    tools: list[str] = field(default_factory=list)
    summary: str = ""


# ── turn slicing ──────────────────────────────────────────────────────────


def _current_turn(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Messages from the LAST user message to the end — i.e. this turn."""
    last_user = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user = i
            break
    return list(messages[last_user:]) if last_user >= 0 else list(messages)


def _iter_tool_calls(turn: Iterable[Mapping[str, Any]]):
    """Yield (name, args_dict) for every tool call made in the turn."""
    for msg in turn:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            raw = fn.get("arguments")
            args: dict[str, Any] = {}
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        args = parsed
                except Exception:
                    pass
            elif isinstance(raw, dict):
                args = raw
            yield name, args


def session_sticky_ids(messages: Sequence[Mapping[str, Any]]) -> set[str]:
    """Entity ids explicitly referenced anywhere in the conversation so far —
    a ``deal_id`` / ``contact_id`` that passed through any tool on a prior turn.
    These are demonstrably "what this session has been working on" and boost an
    otherwise-ambiguous match in the current turn."""
    ids: set[str] = set()
    for name, args in _iter_tool_calls(messages):
        for key in ("deal_id", "contact_id"):
            v = str(args.get(key) or "").strip()
            if v:
                ids.add(v)
    return ids


def _turn_text(turn: Iterable[Mapping[str, Any]]) -> str:
    """All free text in the turn: messages + tool arg/result values. This is
    what we fuzzy-match the roster against."""
    parts: list[str] = []
    for msg in turn:
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    parts.append(fn["arguments"])
    return "\n".join(parts)


# ── tool → human verb summary ─────────────────────────────────────────────

_VERB_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"draft|compose|reply|message|email|sms"), "drafted a message"),
    (re.compile(r"edit_file|write_file|create_file|apply_patch|str_replace"), "edited files"),
    (re.compile(r"read_file|open|cat|view"), "read documents"),
    (re.compile(r"browser|web|fetch|search|scrape"), "researched online"),
    (re.compile(r"terminal|bash|shell|exec|command"), "ran commands"),
    (re.compile(r"calendar|schedule|event"), "checked the calendar"),
    (re.compile(r"deal|admin"), "reviewed the deal"),
    (re.compile(r"contact|lead|crm"), "reviewed the contact"),
]


def _summarize(tools: Sequence[str]) -> str:
    verbs: list[str] = []
    for tool in tools:
        for pat, verb in _VERB_MAP:
            if pat.search(tool.lower()):
                if verb not in verbs:
                    verbs.append(verb)
                break
    if not verbs:
        return "worked on this"
    return ", ".join(verbs[:3])


# ── fuzzy entity matching ─────────────────────────────────────────────────


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _match_deal(text: str, deal: Mapping[str, Any]) -> float:
    """Confidence that ``text`` references this deal via address/title."""
    best = 0.0
    for key in ("address", "title"):
        needle = _norm(deal.get(key))
        if len(needle) >= _MIN_SUBSTR and needle in text:
            best = max(best, 0.8)
    return best


def _match_contact(text: str, contact: Mapping[str, Any]) -> float:
    """Confidence that ``text`` references this contact via email / full name."""
    email = _norm(contact.get("primaryEmail"))
    if email and "@" in email and email in text:
        return 0.85
    name = _norm(contact.get("displayName"))
    tokens = [t for t in name.split(" ") if len(t) >= 2]
    if not tokens:
        return 0.0
    present = [t for t in tokens if t in text]
    if len(tokens) >= 2 and len(present) == len(tokens):
        return 0.8  # full name present
    # A partial name hit (e.g. just the first name) is ambiguous on its own —
    # 0.4 sits below the auto-log bar and only passes with a sticky boost.
    if present and any(len(t) >= 4 for t in present):
        return 0.4
    return 0.0


# ── main entry ─────────────────────────────────────────────────────────────


def resolve_attributions(
    conn,
    messages: Sequence[Mapping[str, Any]],
    *,
    sticky_ids: Iterable[str] | None = None,
) -> list[Attribution]:
    """Resolve which deals/contacts the current turn worked on. Pure read —
    does not write. ``sticky_ids`` are entity ids referenced earlier in the
    session; they boost weak matches over the auto-log bar."""
    from elevate_cli.data import find_contacts, list_deals

    turn = _current_turn(messages)
    tools_used = [name for name, _ in _iter_tool_calls(turn) if name]
    if not turn:
        return []

    # Explicit ids + which deals were formally mutated (so we can skip them).
    explicit_deal_ids: set[str] = set()
    explicit_contact_ids: set[str] = set()
    mutated_deal_ids: set[str] = set()
    for name, args in _iter_tool_calls(turn):
        did = str(args.get("deal_id") or "").strip()
        cid = str(args.get("contact_id") or "").strip()
        if did:
            explicit_deal_ids.add(did)
            action = args.get("action")
            if name in _DEAL_MUTATION_TOOLS and action not in _DEAL_READONLY_ACTIONS:
                mutated_deal_ids.add(did)
        if cid:
            explicit_contact_ids.add(cid)

    text = _norm(_turn_text(turn))
    sticky = {str(s) for s in (sticky_ids or [])}
    summary = _summarize(tools_used)
    out: list[Attribution] = []

    # Rosters are small per account; fetch once.
    deals = list_deals(conn, status="active", limit=500)
    contacts = find_contacts(conn, limit=500)

    deal_by_id = {str(d.get("id")): d for d in deals}
    contact_by_id = {str(c.get("id")): c for c in contacts}

    for did in explicit_deal_ids:
        if did in mutated_deal_ids:
            continue  # it logged itself
        d = deal_by_id.get(did, {"id": did})
        out.append(Attribution(
            "deal", did, 1.0,
            str(d.get("address") or d.get("title") or did), list(tools_used), summary,
        ))

    for cid in explicit_contact_ids:
        c = contact_by_id.get(cid, {"id": cid})
        out.append(Attribution(
            "contact", cid, 1.0,
            str(c.get("displayName") or cid), list(tools_used), summary,
        ))

    # Fuzzy matches on entities NOT already explicit.
    for d in deals:
        did = str(d.get("id"))
        if did in explicit_deal_ids:
            continue
        score = _match_deal(text, d)
        if score and did in sticky:
            score = min(1.0, score + 0.15)
        if score >= AUTO_LOG_THRESHOLD:
            out.append(Attribution(
                "deal", did, score,
                str(d.get("address") or d.get("title") or did), list(tools_used), summary,
            ))

    for c in contacts:
        cid = str(c.get("id"))
        if cid in explicit_contact_ids:
            continue
        score = _match_contact(text, c)
        if score and cid in sticky:
            score = min(1.0, score + 0.35)  # sticky lifts a single-token hit
        if score >= AUTO_LOG_THRESHOLD:
            out.append(Attribution(
                "contact", cid, score,
                str(c.get("displayName") or cid), list(tools_used), summary,
            ))

    return out


def record_turn_activity(
    conn,
    messages: Sequence[Mapping[str, Any]],
    *,
    actor: str,
    session_id: str | None = None,
    sticky_ids: Iterable[str] | None = None,
) -> list[Attribution]:
    """Resolve + persist activity for the current turn. Returns what was
    logged. Best-effort: any failure is swallowed (returns what got through)."""
    try:
        attributions = resolve_attributions(conn, messages, sticky_ids=sticky_ids)
    except Exception as exc:
        logger.debug("turn attribution resolve failed: %s", exc)
        return []

    from elevate_cli.data import record_agent_activity, record_deal_activity

    logged: list[Attribution] = []
    for a in attributions:
        try:
            if a.entity_kind == "deal":
                ev = record_deal_activity(
                    conn, a.entity_id, actor=actor, summary=a.summary,
                    tools=a.tools, session_id=session_id, confidence=a.confidence,
                )
                if ev is not None:
                    logged.append(a)
            elif a.entity_kind == "contact":
                record_agent_activity(
                    conn, contact_id=a.entity_id, actor=actor, summary=a.summary,
                    tools=a.tools, session_id=session_id, confidence=a.confidence,
                )
                logged.append(a)
        except Exception as exc:
            logger.debug("turn activity write failed for %s %s: %s", a.entity_kind, a.entity_id, exc)
    if logged:
        logger.info(
            "turn attribution: logged %d entity activity marker(s) [%s]",
            len(logged),
            ", ".join(f"{a.entity_kind}:{a.label}" for a in logged),
        )
    return logged


def attribute_turn_safely(
    messages: Sequence[Mapping[str, Any]],
    *,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Fire-and-forget post-turn attribution for the live agent loop.

    Opens its own account-scoped connection, skips turns that used no tools
    (nothing was *worked*), and never raises — attribution must never affect
    the user-facing turn. Gated to accounts that actually have the real-estate
    admin pack so non-RE sessions pay nothing.
    """
    try:
        turn = _current_turn(messages)
        if not any(name for name, _ in _iter_tool_calls(turn)):
            return  # pure conversational turn — no work to attribute

        from elevate_cli.access import (
            ENTITLEMENT_REAL_ESTATE_ADMIN,
            is_entitlement_active,
        )
        if not is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, None):
            return

        actor = f"agent:{(agent_id or '').strip() or 'session'}"
        sticky = session_sticky_ids(messages)

        from elevate_cli.data import connect
        with connect() as conn:
            record_turn_activity(
                conn, messages, actor=actor, session_id=session_id, sticky_ids=sticky,
            )
    except Exception as exc:  # never let attribution break a turn
        logger.debug("attribute_turn_safely skipped: %s", exc)
