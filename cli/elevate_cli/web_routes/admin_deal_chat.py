"""Per-property "Ask Ozzie" chat for a single deal card.

Phase 1: answer questions about ONE property using a compact, curated context
built from the deal's own facts (parties, money, dates, stage, open tasks,
recent activity, documents). Persists the transcript per deal on disk so the
panel rehydrates on reopen. It also PROPOSES real skill actions across the whole
property lifecycle (CMA, property lookup, MLC, seller package, Matrix draft,
photos, listing kit, marketing, seller update, offer/CPS, WEBForms, signing,
subject removal, SkySlope, closing, contacts) as a Confirm button; nothing runs
until the user taps Run, which dispatches through the same /api/admin/tasks/run
path the card buttons use. Button-only flows (price reduction, cancel, relist,
collapse, showing confirmation) are pointed to the card button, not dispatched.

Modeled on admin_onboarding.py's onboarding chat (same auxiliary-client +
deterministic-fallback shape) but scoped to a deal and persisted per deal.
A curated context (not all 37 admin skills) keeps the prompt small and avoids
the admin-run context-window bloat.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _DealChatBody(BaseModel):
    message: str = ""


# Where the per-deal transcripts live. One small JSON file per deal; no schema
# change, survives restarts, isolated from the operational store. Resolved per
# call (not at import) so ELEVATE_HOME is honored in tests/isolated homes.
def _chat_dir() -> Path:
    from elevate_constants import get_elevate_home

    return get_elevate_home() / "deal-chats"


_MAX_PERSISTED_TURNS = 60  # keep transcripts bounded
_MAX_CONTEXT_TURNS = 14    # how much history we feed the model each turn

_PENDING_STATUS_RE = re.compile(
    r"\b(?:pending|next|open|todo|status|done|complete|completed|finished)\b"
    r"|\bwhat(?:'?s| is) left\b"
    r"|\bto do\b",
    re.IGNORECASE,
)


_OZZIE_SYSTEM = (
    "You are Ozzie, Skyleigh McCallum's executive assistant for ONE specific "
    "real estate deal. Skyleigh is a busy Kamloops, BC realtor. You answer her "
    "questions about THIS property only, using the deal snapshot below as ground "
    "truth. "
    "VOICE: direct operator, warm but tight. Get-it-done energy. No fluff. "
    "Never use em dashes. Never say 'Certainly', 'Great question', 'I'd be happy "
    "to', 'As an AI', or any filler opener. No sycophancy. "
    "RULES: "
    "(1) Lead with the answer. Keep replies to 1-4 short sentences. No markdown "
    "headers, no bold. A short list is fine only when she asks for several items. "
    "(2) Treat the snapshot as current. If a fact isn't in the snapshot, say you "
    "don't have it on file rather than guessing prices, dates, or legal info. "
    "(3) You can answer about: what's pending / the next step, parties, price and "
    "deposit, key dates, current stage, recent activity, and which documents are "
    "on file. "
    "(4) You CAN kick off real work for THIS property, but never silently and "
    "never claiming it is already done. When she asks you to run, start, generate, "
    "prep, build, pull, file, or send one of the actions below, reply with ONE "
    "short sentence saying what you'll run, then put a directive on its OWN LAST "
    "LINE, exactly: ACTION: <key>. She gets a Confirm button before anything runs, "
    "so do NOT ask 'want me to' first, just confirm what you'll run and emit the "
    "directive. Valid keys: "
    "cma (run a CMA, comps, pricing, market evaluation); "
    "cma_report (generate or regenerate the CMA report or PDF); "
    "property_lookup (pull BC Assessment, zoning, lot size, or property info); "
    "mlc (listing intake, or fill the Multiple Listing Contract); "
    "seller_package (send the pre-appointment seller package); "
    "matrix (create the draft or incomplete MLS listing in Matrix); "
    "photos (clean up or prep the listing photos); "
    "listing_kit (build the MLS listing kit, remarks, features); "
    "marketing (any social / Instagram / Facebook post, Mailjet or email blast, "
    "just-listed or coming-soon graphic, newsletter, or marketing launch); "
    "seller_update (run or rerun the weekly seller update / listing performance / "
    "showing feedback report); "
    "offer (offer or CPS prep or review); "
    "webforms (pull a CPS, amendment, or other WEBForms contract PDF); "
    "signing (send documents out for signature); "
    "subject_removal (subject or condition removal admin); "
    "skyslope (upload, file, or sync documents / tasks on SkySlope); "
    "closing (closing, conveyance, or closeout admin); "
    "contact (add or verify a contact in Lofty, or log a note). "
    "A Mailjet or email blast, an Instagram or Facebook or social post, or a "
    "newsletter is ALWAYS a marketing directive EVEN IF she frames it as part of a "
    "seller update or listing-performance rerun, so emit marketing for those. "
    "Use at most ONE directive per reply, only when she is clearly asking to DO "
    "that thing; if she asks for two, pick the primary one and mention she can ask "
    "for the other next. If her request does not match a key, do NOT emit a "
    "directive. Never say you started, sent, or filed anything yourself. "
    "(5) A few property jobs run from the card's own button, not from chat: price "
    "reduction, cancelling the listing, cancel-and-relist, a collapsed or "
    "fell-through sale, and confirming a showing. If she asks for one of those, do "
    "NOT emit a directive. Tell her in one line to use that button on this card, "
    "name the button, and offer to answer questions about it. "
    "(6) When you reference the property, use its short address, not the deal id."
)


# Actions Ozzie can PROPOSE (never auto-run). The user confirms in the panel,
# which then dispatches through the same admin task-run path the card buttons use
# (POST /api/admin/tasks/run -> queue_action_run). Skills are passed as full
# "real-estate-admin/<skill>" refs: dispatch's _canonical_admin_skill_ref returns
# any ref containing "/" as-is, so resolution never depends on the short-key map
# staying in sync. Every ref below has a skill dir under cli/skills/real-estate-admin.
# Widening this dict is the ONLY change needed to give Ozzie more reach: the panel
# passes proposedAction.skill straight through, and no skill instructions load in
# the chat turn (the heavy load happens inside the confirmed async run), so adding
# actions does NOT grow the per-turn context.
_OZZIE_ACTIONS: Dict[str, Dict[str, str]] = {
    # Evaluation / pricing
    "cma":             {"skill": "real-estate-admin/cma",                        "label": "Run CMA"},
    "cma_report":      {"skill": "real-estate-admin/cma-generator",             "label": "Generate CMA report"},
    "property_lookup": {"skill": "real-estate-admin/property-lookup",           "label": "Pull assessment + zoning"},
    # Listing setup
    "mlc":             {"skill": "real-estate-admin/mlc",                       "label": "Listing intake + MLC"},
    "seller_package":  {"skill": "real-estate-admin/seller-package",           "label": "Send seller package"},
    "matrix":          {"skill": "real-estate-admin/matrix-incomplete-listing", "label": "Create MLS draft listing"},
    "photos":          {"skill": "real-estate-admin/photo-cleanup",            "label": "Clean up listing photos"},
    "listing_kit":     {"skill": "real-estate-admin/listing-build",            "label": "Build listing kit"},
    # Live listing
    "marketing":       {"skill": "real-estate-admin/marketing",               "label": "Marketing (social / newsletter / blast)"},
    # seller-updates is a workflow skill with NO real-estate-admin dispatch ref
    # (0 refs in dispatch.py); the proven path is the BARE name via tasks/run,
    # same as the card buttons. Do NOT "upgrade" this to a full ref — it won't load.
    "seller_update":   {"skill": "seller-updates",                            "label": "Run weekly seller update"},
    # Under contract
    "offer":           {"skill": "real-estate-admin/offer-review",            "label": "Offer prep / review"},
    "webforms":        {"skill": "real-estate-admin/webforms",                "label": "Pull a contract PDF"},
    "signing":         {"skill": "real-estate-admin/signing-package",         "label": "Send docs for signature"},
    "subject_removal": {"skill": "real-estate-admin/subject-removal",         "label": "Subject removal"},
    "skyslope":        {"skill": "real-estate-admin/skyslope-sync",           "label": "Sync SkySlope"},
    "closing":         {"skill": "real-estate-admin/closing-admin",           "label": "Closing / conveyance"},
    # Anytime
    "contact":         {"skill": "real-estate-admin/lofty-crm-client-contacts","label": "Add / verify contact + log note"},
}

# Matches a directive line like "ACTION: cma" (tolerates markdown/quote prefixes).
_ACTION_RE = re.compile(r"(?im)^[ \t>*_-]*ACTION:\s*([a-z_]+)\s*$")


def _extract_action(reply: str):
    """Pull a trailing 'ACTION: <key>' directive out of the model reply.

    Returns (clean_reply, proposed|None). The directive line is always stripped
    from the visible reply. Unknown keys yield no action, so a bad/hallucinated
    directive never dispatches.
    """
    matches = list(_ACTION_RE.finditer(reply or ""))
    if not matches:
        return reply, None
    cleaned = _ACTION_RE.sub("", reply).strip()
    key = matches[-1].group(1).strip().lower()
    spec = _OZZIE_ACTIONS.get(key)
    if not spec:
        return cleaned, None
    return cleaned, {"key": key, "skill": spec["skill"], "label": spec["label"]}


def _proposed_from_key(key: str):
    spec = _OZZIE_ACTIONS.get((key or "").strip().lower())
    if not spec:
        return None
    return {"key": key.strip().lower(), "skill": spec["skill"], "label": spec["label"]}


# Ozzie's committal replies open with "I'll ..." (run, prep, generate, send,
# pull, build, create, sync, add). When the model commits like that but forgets
# the trailing "ACTION:" directive, the panel would show the sentence with no
# Confirm button — a dead end. We detect the opener and do ONE cheap constrained
# follow-up that maps the sentence to a key (see post_deal_chat). Straight-quote
# and curly-quote apostrophes both count.
def _looks_committal(reply: str) -> bool:
    s = (reply or "").strip().lower()
    return s.startswith(("i'll ", "i’ll ", "i will "))


def _fmt_money(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    digits = s.replace("$", "").replace(",", "").strip()
    try:
        n = float(digits)
        return f"${n:,.0f}"
    except Exception:
        return s


def _deal_chat_context(deal_id: str) -> Dict[str, Any]:
    """Return {context: <str>, address: <str>} — a compact, curated snapshot.

    Pulls only what answers the common questions; deliberately small to keep the
    prompt tight (no full attachment bodies, no province guide, capped events).
    """
    from elevate_cli.data import connect, get_deal_context

    with connect() as conn:
        ctx = get_deal_context(conn, deal_id)

    deal = ctx.get("deal") or {}
    chk = ctx.get("checklist") or {}
    primary = ctx.get("primaryContact") or {}
    cos = ctx.get("coContacts") or []
    flow = ctx.get("dealFlow") or {}
    events = ctx.get("events") or []
    attachments = ctx.get("attachments") or []
    prior_runs = ctx.get("priorRuns") or []

    address = (
        deal.get("listingAddress")
        or deal.get("address")
        or deal.get("addr")
        or "this property"
    )
    side = str(deal.get("side") or "listing")

    # Parties: card overrides first, then contacts.
    buyers: List[str] = []
    sellers: List[str] = []
    if primary.get("displayName"):
        (buyers if side == "buyer" else sellers).append(primary["displayName"])
    for c in cos:
        role = str(c.get("role") or "").lower()
        nm = ((c.get("contact") or {}).get("displayName")) or ""
        if nm:
            (sellers if "seller" in role else buyers).append(nm)

    def _card_list(keys: List[str], fallback: List[str]) -> List[str]:
        for k in keys:
            v = chk.get(k)
            if isinstance(v, list):
                vals = [str(x).strip() for x in v if str(x).strip()]
                if vals:
                    return vals
            elif isinstance(v, str) and v.strip():
                return [p.strip() for p in v.split(",") if p.strip()]
        return fallback

    buyers = list(dict.fromkeys(_card_list(["buyerClientNames", "buyerNames"], buyers)))
    sellers = list(dict.fromkeys(_card_list(["sellerLegalNames", "sellerNames"], sellers)))

    price = _fmt_money(chk.get("cpsPurchasePrice") or deal.get("offerPrice") or deal.get("listPrice"))
    deposit = _fmt_money(chk.get("cpsDeposit") or deal.get("depositAmount"))

    lines: List[str] = ["--- DEAL SNAPSHOT (ground truth) ---"]
    lines.append(f"Property: {address}")
    lines.append(f"Side: {'buyer' if side == 'buyer' else 'listing (seller)'}")
    stage_name = flow.get("name") or flow.get("phase") or ""
    stage_num = deal.get("currentStage")
    if stage_name or stage_num is not None:
        lines.append(f"Current stage: {stage_name or ''}".strip() + (f" (stage {stage_num})" if stage_num is not None else ""))
    if deal.get("mlsNumber"):
        lines.append(f"MLS#: {deal['mlsNumber']}")
    if sellers:
        lines.append(f"Sellers: {', '.join(sellers)}")
    if buyers:
        lines.append(f"Buyers: {', '.join(buyers)}")
    if price:
        lines.append(f"Price: {price}")
    if deposit:
        lines.append(f"Deposit: {deposit}")

    # Key dates.
    date_bits = []
    for label, key in (
        ("Offer", "offerDate"), ("Subject removal", "subjectRemovalDate"),
        ("Completion", "completionDate"), ("Possession", "possessionDate"),
        ("List", "listDate"), ("Expiry", "expiryDate"),
    ):
        v = chk.get(key) or deal.get(key)
        if v:
            date_bits.append(f"{label}: {v}")
    if date_bits:
        lines.append("Key dates: " + " · ".join(date_bits))

    # Open / waiting tasks from prior runs.
    open_runs = [
        r for r in prior_runs
        if str(r.get("status") or "").lower() in ("queued", "running", "waiting_human", "waiting_external", "failed")
    ]
    if open_runs:
        bits = []
        for r in open_runs[:6]:
            t = r.get("registryName") or r.get("skill") or "task"
            st = r.get("status") or ""
            bits.append(f"{t} [{st}]")
        lines.append("Open tasks: " + "; ".join(bits))

    # Documents on file (names only).
    if attachments:
        names = [str(a.get("name") or a.get("filename") or "").strip() for a in attachments]
        names = [n for n in names if n]
        if names:
            shown = names[:12]
            more = f" (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
            lines.append(f"Documents on file ({len(names)}): " + ", ".join(shown) + more)

    # Recent activity (most recent first, capped). deal_events carry a `kind`
    # plus optional stage move (fromStage->toStage) or field change.
    if events:
        act_lines: List[str] = []
        for ev in events[:8]:
            ts = str(ev.get("createdAt") or "")[:16]
            kind = str(ev.get("kind") or "").strip()
            detail = ""
            if ev.get("toStage") is not None and ev.get("fromStage") != ev.get("toStage"):
                detail = f"stage {ev.get('fromStage')}→{ev.get('toStage')}"
            elif ev.get("fieldName"):
                nv = str(ev.get("newValue") or "").strip()
                detail = f"{ev['fieldName']}={nv}" if nv else str(ev["fieldName"])
            summary = " ".join(p for p in (kind, detail) if p).strip()
            if summary:
                act_lines.append(f"  - {ts} {summary}".rstrip())
        if act_lines:
            lines.append("Recent activity:")
            lines.extend(act_lines)

    return {"context": "\n".join(lines), "address": address}


def _deal_chat_fallback(messages: List[Dict[str, str]], context: str, address: str) -> str:
    """Deterministic answer when no auxiliary LLM client is configured.

    Pulls the few highest-value lines straight out of the snapshot so the panel
    is still useful headless.
    """
    last = (messages[-1].get("content") if messages else "") or ""
    q = last.lower()
    snap = {}
    for line in context.splitlines():
        if ": " in line:
            k, _, v = line.partition(": ")
            snap[k.strip().lower()] = v.strip()

    if _PENDING_STATUS_RE.search(q):
        if "open tasks" in snap:
            return f"Open on {address}: {snap['open tasks']}."
        if "current stage" in snap:
            return f"{address} is at {snap['current stage']}. Nothing flagged as open right now."
    if any(t in q for t in ("price", "list", "offer")):
        if "price" in snap:
            return f"{address} is at {snap['price']}."
    if "deposit" in q and "deposit" in snap:
        return f"Deposit on {address} is {snap['deposit']}."
    if any(t in q for t in ("date", "completion", "possession", "subject")) and "key dates" in snap:
        return f"{address} key dates — {snap['key dates']}."
    if any(t in q for t in ("who", "seller", "buyer", "party", "parties")):
        bits = []
        if "sellers" in snap:
            bits.append(f"sellers {snap['sellers']}")
        if "buyers" in snap:
            bits.append(f"buyers {snap['buyers']}")
        if bits:
            return f"On {address}: " + "; ".join(bits) + "."
    if any(t in q for t in ("doc", "file", "paper", "form")) and "documents on file" in snap:
        return f"On file for {address}: {snap['documents on file']}."
    if any(t in q for t in ("activity", "recent", "happened", "latest", "update")):
        recents = [l.strip("  - ").strip() for l in context.splitlines() if l.startswith("  - ")]
        if recents:
            return f"Latest on {address}: {recents[0]}."
    # Default: stage + first open item.
    head = f"{address}"
    if "current stage" in snap:
        head += f" is at {snap['current stage']}"
    if "open tasks" in snap:
        return f"{head}. Open: {snap['open tasks']}."
    return f"{head}. Ask me what's pending, the price, key dates, the parties, or what's on file."


def _chat_path(deal_id: str) -> Path:
    safe = "".join(ch for ch in str(deal_id) if ch.isalnum() or ch in ("-", "_")) or "deal"
    return _chat_dir() / f"{safe}.json"


def _load_transcript(deal_id: str) -> List[Dict[str, str]]:
    p = _chat_path(deal_id)
    if not p.exists():
        return []
    data = json.loads(p.read_text("utf-8"))
    if isinstance(data, dict):
        if "messages" not in data:
            raise ValueError("deal chat transcript is missing messages")
        msgs = data["messages"]
    elif isinstance(data, list):
        # Keep the original list-only format readable, but validate it with the
        # same strict contract as the current envelope format.
        msgs = data
    else:
        raise ValueError("deal chat transcript must be an object or list")

    if not isinstance(msgs, list):
        raise ValueError("deal chat transcript messages must be a list")

    transcript: List[Dict[str, str]] = []
    for index, message in enumerate(msgs):
        if not isinstance(message, dict):
            raise ValueError(f"deal chat transcript message {index} must be an object")
        role = message.get("role")
        content = message.get("content")
        ts = message.get("ts", "")
        if role not in {"user", "assistant"}:
            raise ValueError(f"deal chat transcript message {index} has an invalid role")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"deal chat transcript message {index} has invalid content")
        if not isinstance(ts, str):
            raise ValueError(f"deal chat transcript message {index} has an invalid timestamp")
        transcript.append({"role": role, "content": content, "ts": ts})
    return transcript


def _save_transcript(deal_id: str, messages: List[Dict[str, str]]) -> None:
    _chat_dir().mkdir(parents=True, exist_ok=True)
    trimmed = messages[-_MAX_PERSISTED_TURNS:]
    tmp = _chat_path(deal_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"dealId": deal_id, "messages": trimmed}, ensure_ascii=False), "utf-8")
    tmp.replace(_chat_path(deal_id))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_admin_deal_chat_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/deals/{deal_id}/chat")
    def get_deal_chat(deal_id: str):
        """Rehydrate the per-deal transcript when the panel opens."""
        try:
            messages = _load_transcript(deal_id)
        except Exception:
            _log.exception("deal chat: failed to load transcript for %s", deal_id)
            raise HTTPException(
                status_code=500,
                detail="Deal chat transcript could not be read safely.",
            )
        return {"ok": True, "messages": messages}

    @router.post("/api/admin/deals/{deal_id}/chat")
    def post_deal_chat(deal_id: str, body: _DealChatBody):
        """Append the user's message, answer it against the deal snapshot, persist."""
        text = (body.message or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Empty message")

        try:
            built = _deal_chat_context(deal_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="Deal not found")
        except Exception as exc:
            _log.exception("deal chat: failed to build context for %s", deal_id)
            raise HTTPException(status_code=500, detail=f"Deal chat unavailable: {exc}")

        context = built["context"]
        address = built["address"]

        try:
            transcript = _load_transcript(deal_id)
        except Exception:
            _log.exception("deal chat: failed to load transcript for %s", deal_id)
            raise HTTPException(
                status_code=500,
                detail="Deal chat transcript could not be read safely.",
            )
        transcript.append({"role": "user", "content": text, "ts": _now_iso()})

        # History fed to the model: recent turns only, role+content.
        history = [{"role": m["role"], "content": m["content"]} for m in transcript[-_MAX_CONTEXT_TURNS:]]
        system_prompt = _OZZIE_SYSTEM + "\n\n" + context

        reply: Optional[str] = None
        model_used = None
        try:
            from agent.auxiliary_client import (
                _validate_llm_response,
                get_text_auxiliary_client,
            )

            client, model = get_text_auxiliary_client("deal_chat")
        except Exception as exc:
            _log.info("deal chat: auxiliary client unavailable (%s) — falling back", exc)
            client, model = None, None

        if client is not None and model:
            try:
                resp = _validate_llm_response(
                    client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            *history,
                        ],
                        temperature=0.4,
                        max_tokens=400,
                        timeout=20,
                    ),
                    "deal_chat",
                )
                choice = resp.choices[0]
                message = choice.message
                if (
                    getattr(choice, "finish_reason", None) != "stop"
                    or getattr(message, "tool_calls", None)
                ):
                    raise ValueError(
                        "deal chat response did not end with an exact "
                        "text-only stop"
                    )
                content = getattr(message, "content", None)
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("deal chat response did not contain text")
                if _PENDING_STATUS_RE.search(text):
                    raise ValueError(
                        "deal chat pending/status questions require the "
                        "deterministic deal snapshot answer"
                    )
                reply = content.strip()
                model_used = model
            except Exception as exc:
                _log.info("deal chat: LLM call failed (%s) — falling back", exc)

        if not reply:
            reply = _deal_chat_fallback(history, context, address)

        # Pull any "ACTION: <key>" directive out. The visible/persisted reply never
        # includes the directive; the proposed action is returned for the panel to
        # confirm (it never runs here — the user taps Confirm, which dispatches via
        # the same POST /api/admin/tasks/run path the card buttons use).
        reply, proposed = _extract_action(reply)

        # Recovery: the model sometimes commits ("I'll run the seller update...")
        # but drops the ACTION line, which would leave the panel with no Confirm
        # button. When the reply is committal and no action parsed, do ONE cheap
        # constrained call that maps the sentence to a key (or "none"). This never
        # dispatches — it only attaches the proposal so the Confirm button shows.
        if proposed is None and reply and _looks_committal(reply) and client is not None and model:
            try:
                keys = ", ".join(_OZZIE_ACTIONS.keys())
                pick = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": (
                            "Map the realtor-assistant sentence to ONE action key. "
                            "Output ONLY one line, exactly 'ACTION: <key>', where <key> is one of: "
                            + keys + ", or 'ACTION: none' if it is not committing to run one of those. "
                            "No other text."
                        )},
                        {"role": "user", "content": reply},
                    ],
                    temperature=0,
                    max_tokens=12,
                    timeout=12,
                )
                m = _ACTION_RE.search(pick.choices[0].message.content or "")
                if m:
                    proposed = _proposed_from_key(m.group(1))
            except Exception as exc:
                _log.info("deal chat: action-recovery call failed (%s)", exc)

        if proposed and not reply:
            reply = f"I'll {proposed['label'].lower()} for {address}. Confirm below and I'll kick it off."

        transcript.append({"role": "assistant", "content": reply, "ts": _now_iso()})
        try:
            _save_transcript(deal_id, transcript)
        except Exception:
            _log.exception("deal chat: failed to save transcript for %s", deal_id)
            raise HTTPException(
                status_code=500,
                detail="Deal chat response could not be saved.",
            )

        return {"ok": True, "reply": reply, "model": model_used, "proposedAction": proposed,
                "messages": [{"role": m["role"], "content": m["content"]} for m in transcript[-_MAX_PERSISTED_TURNS:]]}

    return router
