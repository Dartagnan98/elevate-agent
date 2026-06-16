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


def _prev_user_index(messages: Sequence[Mapping[str, Any]], current_user_idx: int) -> int:
    """Index of the user message that opened the turn BEFORE the current one."""
    for i in range(current_user_idx - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return -1


def build_turn_nudge(
    messages: Sequence[Mapping[str, Any]],
    current_user_idx: int,
) -> str | None:
    """If the LAST completed turn worked a deal but recorded no formal board
    change, return a one-line reminder to inject into this turn. Stateless: it
    re-derives from history each turn, so a fresh AIAgent (gateway/cron rebuilds
    one per message) still produces it. The "last completed turn" window
    advances each turn, so a nudge is not repeated once the agent acts or moves
    on. Deal-focused — that's where stage/checklist drift actually hurts.

    Best-effort and self-gated (real-estate accounts only); never raises.
    """
    try:
        prev = _prev_user_index(messages, current_user_idx)
        if prev < 0:
            return None
        last_turn = list(messages[prev:current_user_idx])
        if not any(name for name, _ in _iter_tool_calls(last_turn)):
            return None

        from elevate_cli.access import (
            ENTITLEMENT_REAL_ESTATE_ADMIN,
            ENTITLEMENT_REAL_ESTATE_SALES,
            is_entitlement_active,
        )
        if not (
            is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, None)
            or is_entitlement_active(ENTITLEMENT_REAL_ESTATE_SALES, None)
        ):
            return None

        from elevate_cli.data import connect, get_contact
        sticky = session_sticky_ids(messages[:prev])
        with connect() as conn:
            attributions = resolve_attributions(conn, last_turn, sticky_ids=sticky)
            # A worked lead with NO pipeline status yet — ask the agent to label
            # it (so the next heartbeat sees it handled, not untouched).
            unlabeled: list[str] = []
            for a in attributions:
                if a.entity_kind != "contact":
                    continue
                c = get_contact(conn, a.entity_id)
                if c is not None and not (c.get("pipelineStatus") or "").strip():
                    unlabeled.append(a.label)

        deals = [a for a in attributions if a.entity_kind == "deal"]
        lines: list[str] = []
        if deals:
            labels = ", ".join(sorted({a.label for a in deals})[:3])
            lines.append(
                f"Last turn you worked on {labels} but recorded no board change. "
                "If a stage advanced, a checklist item completed, or a key "
                "date/price changed, update it with admin_deal. If it was only "
                "research or drafting, ignore this."
            )
        if unlabeled:
            names = ", ".join(sorted(set(unlabeled))[:3])
            lines.append(
                f"You worked {names} but left no lead status. Set one with "
                "lead_status (new_lead / follow_up / ghosting / dead, plus heat) "
                "so the next run sees it handled — or, if you can't tell what fits, "
                "ask rather than guess."
            )
        if not lines:
            return None
        return "[board-sync reminder] " + " ".join(lines)
    except Exception as exc:
        logger.debug("build_turn_nudge skipped: %s", exc)
        return None


def _resolver_enabled() -> bool:
    """The micro-resolver (LLM backstop) is OFF by default — it adds an aux
    model call per ambiguous turn. Opt in with ``attribution.resolver: true`` in
    ~/.elevate/config.yaml."""
    try:
        from elevate_cli.config import load_config
        cfg = load_config() or {}
        node = cfg.get("attribution")
        return bool(isinstance(node, dict) and node.get("resolver"))
    except Exception:
        return False


def _run_micro_resolver(
    turn_text: str,
    summary: str,
    tools: list[str],
    *,
    actor: str,
    session_id: str | None,
    main_runtime: Mapping[str, Any] | None,
) -> None:
    """LLM backstop (step 3): for a turn the deterministic layers couldn't
    place, ask a cheap model which deal/contact it concerned. Runs in its own
    thread with its own connection; never raises. Logs at confidence 0.6."""
    try:
        from elevate_cli.data import connect, record_agent_activity, record_deal_activity
        from agent.auxiliary_client import call_llm

        with connect() as conn:
            from elevate_cli.data import find_contacts, list_deals
            deals = list_deals(conn, status="active", limit=200)
            contacts = find_contacts(conn, limit=200)
        if not deals and not contacts:
            return

        roster_deals = "\n".join(
            f"  deal {d.get('id')}: {d.get('address') or d.get('title') or '?'}"
            for d in deals
        )[:4000]
        roster_contacts = "\n".join(
            f"  contact {c.get('id')}: {c.get('displayName') or '?'}"
            for c in contacts
        )[:4000]
        prompt = (
            "You attribute realtor agent work to the deal/contact it concerned.\n"
            "A turn just ran. Decide which known deals/contacts (if any) it was "
            "about. Be conservative — answer none unless clearly about one.\n\n"
            f"Turn did: {summary}\n"
            f"Turn text (truncated):\n{turn_text[:2000]}\n\n"
            f"Known deals:\n{roster_deals or '  (none)'}\n"
            f"Known contacts:\n{roster_contacts or '  (none)'}\n\n"
            'Reply ONLY compact JSON: {"deal_ids":[...],"contact_ids":[...]} '
            "(empty arrays if none)."
        )
        resp = call_llm(
            task="session_search",
            main_runtime=dict(main_runtime or {}),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            timeout=20,
        )
        content = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return
        parsed = json.loads(m.group(0))
        deal_ids = [str(x) for x in (parsed.get("deal_ids") or [])][:5]
        contact_ids = [str(x) for x in (parsed.get("contact_ids") or [])][:5]
        if not deal_ids and not contact_ids:
            return

        valid_deals = {str(d.get("id")) for d in deals}
        valid_contacts = {str(c.get("id")) for c in contacts}
        with connect() as conn:
            for did in deal_ids:
                if did in valid_deals:
                    record_deal_activity(
                        conn, did, actor=actor, summary=summary, tools=tools,
                        session_id=session_id, confidence=0.6,
                    )
            for cid in contact_ids:
                if cid in valid_contacts:
                    record_agent_activity(
                        conn, contact_id=cid, actor=actor, summary=summary,
                        tools=tools, session_id=session_id, confidence=0.6,
                    )
        logger.info(
            "micro-resolver attributed %d deal(s) + %d contact(s)",
            len([d for d in deal_ids if d in valid_deals]),
            len([c for c in contact_ids if c in valid_contacts]),
        )
    except Exception as exc:
        logger.debug("micro-resolver skipped: %s", exc)


# ── L2: post-turn scorecard inference ────────────────────────────────────────
# The case Phase B exists to fix: the agent gathers a fact in CONVERSATION (a
# CMA list price, a confirmed inspection date) and never calls a write tool, so
# the deal's checklist drifts and the realtor keeps asking it to update. The
# deterministic layers above only stamp freshness; this reflects the actual
# work onto the scorecard — bounded so it can never invent progress.

# Confidence bar to WRITE an inferred cell. Higher than the freshness auto-log
# bar (0.7): a wrong tick is more consequential than a wrong activity marker, so
# we only infer on a deal we're confident the turn was actually about.
SCORECARD_INFER_THRESHOLD = 0.8


def _scorecard_inference_enabled() -> bool:
    """L2 is ON by default for entitled real-estate accounts. Opt out with
    ``attribution.scorecard_inference: false`` in ~/.elevate/config.yaml."""
    try:
        from elevate_cli.config import load_config
        cfg = load_config() or {}
        node = cfg.get("attribution")
        if isinstance(node, dict) and "scorecard_inference" in node:
            return bool(node.get("scorecard_inference"))
    except Exception:
        pass
    return True


def _infer_satisfied_cells(
    turn_text: str,
    summary: str,
    open_cells: list[Mapping[str, Any]],
    *,
    main_runtime: Mapping[str, Any] | None,
) -> set[str]:
    """Schema-locked aux call: of THIS deal's open cells, which did the turn
    actually complete? Conservative, and closed-set — only ids from the
    provided list are ever returned (the model cannot invent a cell)."""
    from agent.auxiliary_client import call_llm

    valid_ids = {str(c.get("id")) for c in open_cells if c.get("id")}
    if not valid_ids:
        return set()
    listing = "\n".join(f"  - {c['id']}: {c.get('label') or c['id']}" for c in open_cells)
    prompt = (
        "You track a real-estate deal's checklist. Below are the ONLY open "
        "checklist items for its current stage. A turn of agent work just "
        "finished. Decide which of these items the turn ACTUALLY completed or "
        "confirmed done — not merely mentioned, planned, or researched.\n"
        "Be conservative: if unsure, leave it out. Never invent ids.\n\n"
        f"Open checklist items:\n{listing}\n\n"
        f"Turn did: {summary}\n"
        f"Turn text (truncated):\n{turn_text[:2500]}\n\n"
        'Reply ONLY compact JSON: {"satisfied_ids":[...]} using ids from the '
        "list above (empty array if none)."
    )
    resp = call_llm(
        task="session_search",
        main_runtime=dict(main_runtime or {}),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        timeout=20,
    )
    content = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return set()
    parsed = json.loads(m.group(0))
    ids = parsed.get("satisfied_ids") or []
    # Closed-set guarantee: only ids that were actually open on this deal.
    return {str(x) for x in ids if str(x) in valid_ids}


def run_scorecard_inference(
    turn: Sequence[Mapping[str, Any]],
    *,
    sticky_ids: Iterable[str] | None = None,
    session_id: str | None = None,
    main_runtime: Mapping[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """L2 thread target: reflect conversational deal work onto the scorecard.

    For each high-confidence resolved deal that has OPEN current-stage cells,
    ask a schema-locked aux call which of those exact cells the turn satisfied,
    then tick them (actor='agent:inferred') — skipping any the realtor
    explicitly controls. Bounded all the way down: no resolved deal -> nothing;
    no open cells -> no aux call; closed candidate set -> no invented progress.
    Returns the [(deal_id, cell_id)] applied. Never raises.
    """
    applied: list[tuple[str, str]] = []
    try:
        if not turn:
            return applied
        from elevate_cli.data import connect
        from elevate_cli.data.deals import (
            deal_open_stage_cells,
            get_deal,
            human_controlled_checklist_cells,
            set_deal_toggle,
        )

        with connect() as conn:
            attributions = resolve_attributions(conn, turn, sticky_ids=sticky_ids)
            deals = [
                a for a in attributions
                if a.entity_kind == "deal" and a.confidence >= SCORECARD_INFER_THRESHOLD
            ]
            if not deals:
                return applied
            tools_used = [name for name, _ in _iter_tool_calls(list(turn)) if name]
            summary = _summarize(tools_used)
            turn_text = _turn_text(turn)
            for a in deals:
                deal = get_deal(conn, a.entity_id)
                if deal is None:
                    continue
                open_cells = deal_open_stage_cells(conn, deal)
                if not open_cells:
                    continue  # no open cells -> no aux call (cost guard)
                protected = human_controlled_checklist_cells(conn, a.entity_id)
                candidate = [c for c in open_cells if c["id"] not in protected]
                if not candidate:
                    continue
                satisfied = _infer_satisfied_cells(
                    turn_text, summary, candidate, main_runtime=main_runtime,
                )
                for cid in satisfied:
                    try:
                        set_deal_toggle(
                            conn, a.entity_id, field=cid, value=True, actor="agent:inferred",
                        )
                        applied.append((a.entity_id, cid))
                    except Exception as exc:
                        logger.debug(
                            "scorecard inference write failed %s/%s: %s", a.entity_id, cid, exc
                        )
        if applied:
            logger.info(
                "scorecard inference: ticked %d cell(s) [%s]",
                len(applied),
                ", ".join(f"{d}:{c}" for d, c in applied),
            )
    except Exception as exc:
        logger.debug("scorecard inference skipped: %s", exc)
    return applied


def attribute_turn_safely(
    messages: Sequence[Mapping[str, Any]],
    *,
    agent_id: str | None = None,
    session_id: str | None = None,
    main_runtime: Mapping[str, Any] | None = None,
) -> None:
    """Fire-and-forget post-turn attribution for the live agent loop.

    Opens its own account-scoped connection, skips turns that used no tools
    (nothing was *worked*), and never raises — attribution must never affect
    the user-facing turn. Gated to accounts that actually have the real-estate
    admin pack so non-RE sessions pay nothing.
    """
    try:
        turn = _current_turn(messages)
        turn_has_tools = any(name for name, _ in _iter_tool_calls(turn))

        # Entitlement gate FIRST — both freshness logging and scorecard inference
        # need the real-estate pack, and gating here (rather than behind the tool
        # check) is exactly what lets scorecard inference run on pure
        # conversational turns. Non-RE sessions still pay nothing.
        from elevate_cli.access import (
            ENTITLEMENT_REAL_ESTATE_ADMIN,
            ENTITLEMENT_REAL_ESTATE_SALES,
            is_entitlement_active,
        )
        if not (
            is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, None)
            or is_entitlement_active(ENTITLEMENT_REAL_ESTATE_SALES, None)
        ):
            return

        actor = f"agent:{(agent_id or '').strip() or 'session'}"
        sticky = session_sticky_ids(messages)

        # ── Freshness logging — tool-gated (a "worked" turn used tools). ──
        logged: list[Attribution] = []
        if turn_has_tools:
            from elevate_cli.data import connect
            with connect() as conn:
                logged = record_turn_activity(
                    conn, messages, actor=actor, session_id=session_id, sticky_ids=sticky,
                )

        # ── L2 scorecard inference — NOT tool-gated. ──
        # Runs on any turn (including pure chat) so conversational deal work
        # still reaches the checklist — the exact case freshness logging misses.
        # Off-thread; self-bounded so it only spends an aux call when the
        # resolved deal actually has open current-stage cells.
        if _scorecard_inference_enabled():
            import threading
            threading.Thread(
                target=run_scorecard_inference,
                args=(list(turn),),
                kwargs=dict(
                    sticky_ids=set(sticky), session_id=session_id, main_runtime=main_runtime,
                ),
                daemon=True,
            ).start()

        # Step 3 — micro-resolver backstop. Tool turns only, operator opt-in, and
        # only when the deterministic layers placed NOTHING. Off-thread.
        if turn_has_tools and not logged and _resolver_enabled():
            tools_used = [name for name, _ in _iter_tool_calls(turn) if name]
            text = _turn_text(turn)
            if text.strip():
                import threading
                threading.Thread(
                    target=_run_micro_resolver,
                    args=(text, _summarize(tools_used), tools_used),
                    kwargs=dict(
                        actor=actor, session_id=session_id, main_runtime=main_runtime,
                    ),
                    daemon=True,
                ).start()
    except Exception as exc:  # never let attribution break a turn
        logger.debug("attribute_turn_safely skipped: %s", exc)
