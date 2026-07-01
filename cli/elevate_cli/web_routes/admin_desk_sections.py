"""Admin desk aggregation endpoints: Critical Dates + Approvals queue.

Both surface cross-deal state on the Admin desk (between the KPI block and the
kanban board) so Skyleigh doesn't have to open every card:

  GET /api/admin/critical-dates   -> upcoming transaction deadlines, bucketed
  GET /api/admin/approvals-queue   -> everything in waiting_human, grouped

Read-only. The Approvals UI reuses the EXISTING approve endpoint
(/api/admin/action-runs/{id}/approve) to act — no new approval path here.
"""

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter


# ── date parsing (the deal date columns are free-text TEXT) ──
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(raw: Any) -> Optional[date]:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # ISO first (2026-07-02 / 2026-07-02T...)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # "July 2, 2026" / "Jul 2 2026" / "Jul 2"
    m = re.search(r"([A-Za-z]{3,})\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?", s)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            day = int(m.group(2))
            yr = int(m.group(3)) if m.group(3) else date.today().year
            try:
                return date(yr, mon, day)
            except ValueError:
                return None
    return None


def _bucket(days: int) -> Optional[str]:
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days <= 7:
        return "this_week"
    if days <= 14:
        return "upcoming"
    return None


def _toggles(d: Dict[str, Any]) -> Dict[str, Any]:
    t = d.get("extraToggles") or d.get("checklist") or {}
    if isinstance(t, str):
        try:
            t = json.loads(t)
        except Exception:
            t = {}
    return t if isinstance(t, dict) else {}


def _deposit_resolved(d: Dict[str, Any]) -> bool:
    """A deposit no longer needs surfacing once it's received / in trust."""
    if d.get("depositInTrustAt"):
        return True
    tg = _toggles(d)
    if str(tg.get("depositStatus") or "").lower() == "received":
        return True
    if tg.get("depositReceivedDate"):
        return True
    return False


_DATE_LABELS = {
    "deposit_due": "Deposit due",
    "subject_removal": "Subject removal",
    "completion": "Completion",
    "possession": "Possession",
    "expiry": "Listing expiry",
}


def _rel_label(days: int) -> str:
    if days < 0:
        n = -days
        return f"{n} day{'s' if n != 1 else ''} late"
    if days == 0:
        return "due today"
    return f"in {days} day{'s' if days != 1 else ''}"


def create_admin_desk_sections_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/critical-dates")
    def get_critical_dates(horizon: int = 14):
        """Aggregate upcoming deadlines across active deals, bucketed vs today."""
        try:
            from elevate_cli.data import connect, list_deals

            with connect() as conn:
                deals = list_deals(conn, status="active", limit=500)
        except Exception as exc:
            _log.exception("critical-dates: failed to list deals")
            return {"ok": False, "error": str(exc), "items": [],
                    "counts": {"overdue": 0, "today": 0, "thisWeek": 0, "upcoming": 0}}

        today = date.today()
        items: List[Dict[str, Any]] = []
        for d in deals:
            addr = d.get("listingAddress") or d.get("addr") or d.get("address") or "(no address)"
            side = (d.get("side") or "listing")
            specs = [
                ("deposit_due", d.get("depositDueDate") or d.get("deposit_due_date") or _toggles(d).get("depositDueDate"), not _deposit_resolved(d)),
                ("subject_removal", d.get("subjectRemovalDate") or d.get("subject_removal_date"),
                 not d.get("subjectsRemovedAt") and not d.get("subjects_removed_at")),
                ("completion", d.get("completionDate") or d.get("completion_date"), True),
                ("possession", d.get("possessionDate") or d.get("possession_date"), True),
            ]
            if side == "listing":
                specs.append(("expiry", d.get("expirationDate") or d.get("expiration_date"), True))
            for kind, raw, include in specs:
                if not include:
                    continue
                dt = _parse_date(raw)
                if not dt:
                    continue
                days = (dt - today).days
                bucket = _bucket(days)
                if not bucket:
                    continue
                items.append({
                    "dealId": d.get("id"),
                    "address": addr,
                    "side": "Buyer" if side == "buyer" else "Listing",
                    "kind": kind,
                    "label": _DATE_LABELS.get(kind, kind),
                    "date": dt.isoformat(),
                    "daysDelta": days,
                    "rel": _rel_label(days),
                    "bucket": bucket,
                })

        order = {"overdue": 0, "today": 1, "this_week": 2, "upcoming": 3}
        items.sort(key=lambda x: (order.get(x["bucket"], 9), x["daysDelta"]))
        counts = {
            "overdue": sum(1 for i in items if i["bucket"] == "overdue"),
            "today": sum(1 for i in items if i["bucket"] == "today"),
            "thisWeek": sum(1 for i in items if i["bucket"] == "this_week"),
            "upcoming": sum(1 for i in items if i["bucket"] == "upcoming"),
        }
        return {"ok": True, "items": items, "counts": counts}

    @router.get("/api/admin/approvals-queue")
    def get_approvals_queue():
        """List everything in waiting_human across active deals, grouped into
        documents-to-send vs stage gates. The UI approves via the existing
        /api/admin/action-runs/{id}/approve endpoint."""
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                addr_map: Dict[str, str] = {}
                side_map: Dict[str, str] = {}
                for row in conn.execute(
                    "SELECT id, listing_address, side, status FROM deals"
                ).fetchall():
                    addr_map[row["id"]] = row["listing_address"] or "(no address)"
                    side_map[row["id"]] = row["side"] or "listing"
                rows = conn.execute(
                    """
                    SELECT r.id AS id, r.deal_id AS deal_id, r.created_at AS created_at,
                           r.human_prompt_json AS human_prompt_json, reg.name AS reg_name
                    FROM admin_action_runs r
                    LEFT JOIN admin_action_registry reg ON r.registry_id = reg.id
                    WHERE r.status = 'waiting_human'
                    ORDER BY r.created_at DESC
                    """
                ).fetchall()
        except Exception as exc:
            _log.exception("approvals-queue: query failed")
            return {"ok": False, "error": str(exc), "documents": [], "gates": [], "count": 0}

        documents: List[Dict[str, Any]] = []
        gates: List[Dict[str, Any]] = []
        for r in rows:
            deal_id = r["deal_id"]
            prompt: Dict[str, Any] = {}
            try:
                hp = r["human_prompt_json"]
                prompt = json.loads(hp) if hp and str(hp).strip() else {}
            except Exception:
                prompt = {}
            title = (prompt.get("title") or r["reg_name"] or "Approval needed").strip()
            message = (prompt.get("message") or "").strip()
            has_preview = bool(prompt.get("previewPdf"))
            blob = f"{r['reg_name'] or ''} {title} {message}".lower()
            # "Document to send" = a true outbound action waiting on sign-off, not
            # an incoming review. Match send-intent phrases (and DigiSign signing),
            # NOT bare "package"/"send" which also appear in review prompts
            # ("review offer package", "before any external send").
            is_doc = any(
                k in blob for k in (
                    "approve to send", "approve & send", "ready to send", "send for sign",
                    "send them for sign", "for signature by", "send for signature",
                    "send the update", "send update", "mailjet", "newsletter", "blast",
                )
            )
            if "digisign" in blob and ("send" in blob or "for sign" in blob):
                is_doc = True
            item = {
                "runId": r["id"],
                "dealId": deal_id,
                "address": addr_map.get(deal_id, "(no address)"),
                "side": "Buyer" if side_map.get(deal_id) == "buyer" else "Listing",
                "title": title,
                "message": message[:200],
                "hasPreview": has_preview,
                "outbound": is_doc,
                "createdAt": str(r["created_at"] or "")[:16],
            }
            (documents if is_doc else gates).append(item)

        return {
            "ok": True,
            "documents": documents,
            "gates": gates,
            "count": len(documents) + len(gates),
        }

    return router
