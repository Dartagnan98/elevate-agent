"""Bug / feedback reports submitted from the dashboard.

A lightweight, file-backed capture so anyone on the team can flag a bug, a
clunky flow, or a design nit from the top-right "Report a bug" button. No DB
migration — reports live under ~/.elevate/bug-reports/ as an append-only JSONL
index plus one screenshot file per report.

  POST /api/bug-reports              -> submit {note, screenshot?, context...}
  GET  /api/bug-reports              -> list newest-first (screenshots inlined)
  POST /api/bug-reports/{id}/resolve -> mark open/resolved

Read/write is low-volume (a handful of reports), so the list endpoint inlines
each screenshot as a data URL — no separate authenticated image endpoint, which
keeps <img> tags simple.
"""

import base64
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_STORE = os.path.expanduser("~/.elevate/bug-reports")
_INDEX = os.path.join(_STORE, "index.jsonl")
_SHOTS = os.path.join(_STORE, "shots")
_LOCK = threading.Lock()

# Cap a single screenshot at ~5 MB of base64 so a giant capture can't wedge the
# store; the client already downscales, this is a backstop.
_MAX_SHOT_B64 = 5 * 1024 * 1024


def _ensure_dirs() -> None:
    os.makedirs(_SHOTS, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_all() -> List[Dict[str, Any]]:
    if not os.path.exists(_INDEX):
        return []
    out: List[Dict[str, Any]] = []
    with open(_INDEX, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _save_screenshot(report_id: str, data_url: Optional[str]) -> Optional[str]:
    """Decode a data URL and write it to shots/<id>.<ext>. Returns filename."""
    if not data_url or not isinstance(data_url, str) or "," not in data_url:
        return None
    if len(data_url) > _MAX_SHOT_B64:
        return None
    header, b64 = data_url.split(",", 1)
    ext = "png"
    if "image/jpeg" in header or "image/jpg" in header:
        ext = "jpg"
    elif "image/webp" in header:
        ext = "webp"
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    fname = f"{report_id}.{ext}"
    with open(os.path.join(_SHOTS, fname), "wb") as fh:
        fh.write(raw)
    return fname


def _shot_data_url(fname: Optional[str]) -> Optional[str]:
    if not fname:
        return None
    path = os.path.join(_SHOTS, fname)
    if not os.path.exists(path):
        return None
    ext = fname.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
    try:
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


class BugReportIn(BaseModel):
    note: str
    screenshot: Optional[str] = None      # data URL
    page: Optional[str] = None            # route/path the user was on
    pageTitle: Optional[str] = None
    dealId: Optional[str] = None
    dealTitle: Optional[str] = None
    userAgent: Optional[str] = None
    viewport: Optional[str] = None
    reporter: Optional[str] = None
    consoleErrors: Optional[List[str]] = None


class ResolveIn(BaseModel):
    resolved: bool = True


def create_bug_reports_router(*, log: logging.Logger | None = None) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.post("/api/bug-reports")
    def submit_bug_report(body: BugReportIn):
        note = (body.note or "").strip()
        if not note:
            raise HTTPException(status_code=400, detail="A description is required.")
        _ensure_dirs()
        rid = uuid.uuid4().hex[:12]
        with _LOCK:
            existing = _read_all()
            number = len(existing) + 1
            shot = _save_screenshot(rid, body.screenshot)
            rec = {
                "id": rid,
                "number": number,
                "note": note[:8000],
                "page": body.page,
                "pageTitle": body.pageTitle,
                "dealId": body.dealId,
                "dealTitle": body.dealTitle,
                "userAgent": body.userAgent,
                "viewport": body.viewport,
                "reporter": body.reporter,
                "consoleErrors": (body.consoleErrors or [])[:20],
                "screenshotFile": shot,
                "status": "open",
                "createdAt": _now_iso(),
                "resolvedAt": None,
            }
            with open(_INDEX, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        _log.info("bug report #%s submitted (%s)", number, rid)
        return {"ok": True, "id": rid, "number": number}

    @router.get("/api/bug-reports")
    def list_bug_reports(include_resolved: bool = True):
        records = _read_all()
        records.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
        reports = []
        open_count = 0
        for r in records:
            status = r.get("status", "open")
            if status == "open":
                open_count += 1
            if not include_resolved and status != "open":
                continue
            reports.append({
                "id": r.get("id"),
                "number": r.get("number"),
                "note": r.get("note"),
                "page": r.get("page"),
                "pageTitle": r.get("pageTitle"),
                "dealId": r.get("dealId"),
                "dealTitle": r.get("dealTitle"),
                "userAgent": r.get("userAgent"),
                "viewport": r.get("viewport"),
                "reporter": r.get("reporter"),
                "consoleErrors": r.get("consoleErrors") or [],
                "screenshot": _shot_data_url(r.get("screenshotFile")),
                "status": status,
                "createdAt": r.get("createdAt"),
                "resolvedAt": r.get("resolvedAt"),
            })
        return {"ok": True, "reports": reports, "openCount": open_count,
                "total": len(records)}

    @router.post("/api/bug-reports/{report_id}/resolve")
    def resolve_bug_report(report_id: str, body: ResolveIn):
        with _LOCK:
            records = _read_all()
            found = False
            for r in records:
                if r.get("id") == report_id:
                    r["status"] = "resolved" if body.resolved else "open"
                    r["resolvedAt"] = _now_iso() if body.resolved else None
                    found = True
                    break
            if not found:
                raise HTTPException(status_code=404, detail="Report not found.")
            tmp = _INDEX + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r) + "\n")
            os.replace(tmp, _INDEX)
        return {"ok": True, "id": report_id,
                "status": "resolved" if body.resolved else "open"}

    return router
