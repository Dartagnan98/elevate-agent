"""Per-property "Ask Ozzie" chat for a single deal card.

Phase 1: answer questions about ONE property using a compact, curated context
built from the deal's own facts (parties, money, dates, stage, open tasks,
recent activity, documents). Persists the transcript per deal on disk so the
panel rehydrates on reopen. Skill-dispatch-by-voice is deliberately Phase 2 —
this endpoint only answers.

Modeled on admin_onboarding.py's onboarding chat (same auxiliary-client +
deterministic-fallback shape) but scoped to a deal and persisted per deal.
A curated context (not all 37 admin skills) keeps the prompt small and avoids
the admin-run context-window bloat.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class _DealChatBody(BaseModel):
    message: str = ""


# Where the per-deal transcripts live. One small JSON file per deal; no schema
# change, survives restarts, isolated from the operational store.
_CHAT_DIR = Path(os.path.expanduser("~/.elevate/deal-chats"))
_MAX_PERSISTED_TURNS = 60  # keep transcripts bounded
_MAX_CONTEXT_TURNS = 14    # how much history we feed the model each turn


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
    "(4) You CANNOT run any workflows yet (CMA, listing kit, seller update, offer "
    "prep, sending anything). If she asks you to DO one of those, tell her plainly "
    "that running skills from chat is coming soon and point her to the card button "
    "for now. Never claim you started, sent, or filed anything. "
    "(5) When you reference the property, use its short address, not the deal id."
)


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

    if any(t in q for t in ("pending", "next", "what's left", "whats left", "to do", "todo", "open")):
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
    return _CHAT_DIR / f"{safe}.json"


def _load_transcript(deal_id: str) -> List[Dict[str, str]]:
    p = _chat_path(deal_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text("utf-8"))
        msgs = data.get("messages") if isinstance(data, dict) else data
        if isinstance(msgs, list):
            return [
                {"role": str(m.get("role") or "assistant"), "content": str(m.get("content") or ""),
                 "ts": str(m.get("ts") or "")}
                for m in msgs if isinstance(m, dict) and str(m.get("content") or "").strip()
            ]
    except Exception:
        return []
    return []


def _save_transcript(deal_id: str, messages: List[Dict[str, str]]) -> None:
    try:
        _CHAT_DIR.mkdir(parents=True, exist_ok=True)
        trimmed = messages[-_MAX_PERSISTED_TURNS:]
        tmp = _chat_path(deal_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"dealId": deal_id, "messages": trimmed}, ensure_ascii=False), "utf-8")
        tmp.replace(_chat_path(deal_id))
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_admin_deal_chat_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/deals/{deal_id}/chat")
    def get_deal_chat(deal_id: str):
        """Rehydrate the per-deal transcript when the panel opens."""
        return {"ok": True, "messages": _load_transcript(deal_id)}

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

        transcript = _load_transcript(deal_id)
        transcript.append({"role": "user", "content": text, "ts": _now_iso()})

        # History fed to the model: recent turns only, role+content.
        history = [{"role": m["role"], "content": m["content"]} for m in transcript[-_MAX_CONTEXT_TURNS:]]
        system_prompt = _OZZIE_SYSTEM + "\n\n" + context

        reply: Optional[str] = None
        model_used = None
        try:
            from agent.auxiliary_client import get_text_auxiliary_client

            client, model = get_text_auxiliary_client("deal_chat")
        except Exception as exc:
            _log.info("deal chat: auxiliary client unavailable (%s) — falling back", exc)
            client, model = None, None

        if client is not None and model:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system_prompt}, *history],
                    temperature=0.4,
                    max_tokens=400,
                    timeout=20,
                )
                reply = (resp.choices[0].message.content or "").strip()
                model_used = model
            except Exception as exc:
                _log.info("deal chat: LLM call failed (%s) — falling back", exc)

        if not reply:
            reply = _deal_chat_fallback(history, context, address)

        transcript.append({"role": "assistant", "content": reply, "ts": _now_iso()})
        _save_transcript(deal_id, transcript)

        return {"ok": True, "reply": reply, "model": model_used,
                "messages": [{"role": m["role"], "content": m["content"]} for m in transcript[-_MAX_PERSISTED_TURNS:]]}

    return router
