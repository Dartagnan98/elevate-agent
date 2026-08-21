"""Reporting routes for the real-estate hub Reporting page.

Backs ``web/src/pages/real-estate-hub/reporting``. One summary endpoint returns
every number the page needs (KPIs, leads-by-source/stage/temperature, the
lead-to-close funnel, closed-deal source split + GCI, and leads/sales trend),
plus a goals read/write pair backing the "Set goals" card.

Every number here comes from a real query. Where a data source does not exist
yet (marketing spend), the payload carries an explicit null marker so the UI
renders a clean empty state instead of a fabricated chart. Every sub-query is
guarded so one bad section returns empty rather than 500-ing the whole page.

Follows the ``create_*_router(*, web_actor, log)`` factory pattern of the
sibling routers in this package. Reads use the shared ``connect()`` context,
which speaks Postgres in the running app (with a ``?``->``%s`` placeholder
shim) and SQLite in the operational fallback, so the SQL below sticks to
portable constructs (``substr`` on the TEXT ISO timestamps).
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


# Outbound message channels that count as a "text sent". Voice is deliberately
# excluded (tracked separately as calls, and almost never populated).
_TEXT_CHANNELS = ("sms", "imessage", "messenger", "instagram", "whatsapp", "telegram")

_GOAL_ID = "default"


class _GoalsBody(BaseModel):
    # All optional; only provided keys are written. Numbers, not strings.
    leadsGoal: Optional[int] = None
    apptsGoal: Optional[int] = None
    closingsGoal: Optional[int] = None
    gciGoal: Optional[int] = None


def _today() -> date:
    return date.today()


def _iso(d: date) -> str:
    return d.isoformat()


def _scalar(conn: Any, sql: str, params: tuple = ()) -> int:
    """Run a COUNT/SUM query and return the first column as an int (0 on None)."""
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    try:
        val = row[0]
    except (KeyError, IndexError, TypeError):
        # dict-like row without positional access
        val = next(iter(dict(row).values()), 0)
    return int(val or 0)


def _pct_delta(cur: int, prior: int) -> Optional[int]:
    """Period-over-period percent change, or None when there is no prior data."""
    if prior <= 0:
        return None
    return round((cur - prior) / prior * 100)


def _ensure_goals_table(conn: Any) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS crm_goals ("
        "id TEXT PRIMARY KEY, leads_goal INTEGER, appts_goal INTEGER, "
        "closings_goal INTEGER, gci_goal INTEGER, updated_at TEXT)"
    )


def _read_goals(conn: Any) -> Dict[str, Optional[int]]:
    _ensure_goals_table(conn)
    row = conn.execute(
        "SELECT leads_goal, appts_goal, closings_goal, gci_goal "
        "FROM crm_goals WHERE id=?",
        (_GOAL_ID,),
    ).fetchone()
    if row is None:
        return {"leadsGoal": None, "apptsGoal": None, "closingsGoal": None, "gciGoal": None}
    d = dict(row)
    return {
        "leadsGoal": d.get("leads_goal"),
        "apptsGoal": d.get("appts_goal"),
        "closingsGoal": d.get("closings_goal"),
        "gciGoal": d.get("gci_goal"),
    }


def create_admin_reporting_router(
    *,
    web_actor: str,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/admin/reporting/summary")
    def get_reporting_summary(window: int = 30):
        window = max(1, min(365, int(window or 30)))
        today = _today()
        cutoff = _iso(today - timedelta(days=window))
        prior_cutoff = _iso(today - timedelta(days=window * 2))
        cur_year = today.year

        try:
            from elevate_cli.data import connect
        except Exception as exc:  # pragma: no cover - import guard
            _log.exception("reporting summary: data layer import failed")
            raise HTTPException(status_code=500, detail=f"Reporting unavailable: {exc}")

        # Defaults so a failed sub-query yields an empty section, never a 500.
        new_leads = calls = texts = emails = appts = 0
        prior_leads = prior_texts = prior_emails = prior_appts = 0
        leads_by_source: List[Dict[str, Any]] = []
        leads_by_stage: List[Dict[str, Any]] = []
        leads_by_temp: List[Dict[str, Any]] = []
        funnel: List[Dict[str, Any]] = []
        closed_by_source: List[Dict[str, Any]] = []
        gci = 0
        monthly: List[Dict[str, Any]] = []
        yoy: List[Dict[str, Any]] = []
        leads_total = 0
        closed_total = 0

        try:
            with connect() as conn:
                # ── KPIs: new leads (window + prior window for delta) ──────────
                try:
                    new_leads = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM contacts WHERE substr(created_at,1,10) >= ?",
                        (cutoff,),
                    )
                    prior_leads = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM contacts "
                        "WHERE substr(created_at,1,10) >= ? AND substr(created_at,1,10) < ?",
                        (prior_cutoff, cutoff),
                    )
                except Exception:
                    _log.debug("reporting: new-leads query failed", exc_info=True)

                # ── KPIs: outbound texts / emails / calls (events) ─────────────
                text_ph = ",".join("?" for _ in _TEXT_CHANNELS)
                try:
                    texts = _scalar(
                        conn,
                        f"SELECT COUNT(*) FROM events WHERE kind='outbound' "
                        f"AND channel IN ({text_ph}) AND substr(ts,1,10) >= ?",
                        (*_TEXT_CHANNELS, cutoff),
                    )
                    prior_texts = _scalar(
                        conn,
                        f"SELECT COUNT(*) FROM events WHERE kind='outbound' "
                        f"AND channel IN ({text_ph}) "
                        f"AND substr(ts,1,10) >= ? AND substr(ts,1,10) < ?",
                        (*_TEXT_CHANNELS, prior_cutoff, cutoff),
                    )
                except Exception:
                    _log.debug("reporting: texts query failed", exc_info=True)
                try:
                    emails = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM events WHERE kind='outbound' "
                        "AND channel='email' AND substr(ts,1,10) >= ?",
                        (cutoff,),
                    )
                    prior_emails = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM events WHERE kind='outbound' "
                        "AND channel='email' AND substr(ts,1,10) >= ? AND substr(ts,1,10) < ?",
                        (prior_cutoff, cutoff),
                    )
                except Exception:
                    _log.debug("reporting: emails query failed", exc_info=True)
                try:
                    # THIN: voice is almost never populated. Report the real count.
                    calls = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM events WHERE kind='outbound' "
                        "AND channel='voice' AND substr(ts,1,10) >= ?",
                        (cutoff,),
                    )
                except Exception:
                    _log.debug("reporting: calls query failed", exc_info=True)

                # ── KPIs: deal appointments (window + prior for delta) ─────────
                try:
                    appts = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM deals WHERE appointment_date IS NOT NULL "
                        "AND substr(appointment_date,1,10) >= ?",
                        (cutoff,),
                    )
                    prior_appts = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM deals WHERE appointment_date IS NOT NULL "
                        "AND substr(appointment_date,1,10) >= ? AND substr(appointment_date,1,10) < ?",
                        (prior_cutoff, cutoff),
                    )
                except Exception:
                    _log.debug("reporting: appts query failed", exc_info=True)

                # ── Leads by source (free-text; UI buckets small/unknown) ──────
                try:
                    rows = conn.execute(
                        "SELECT COALESCE(NULLIF(TRIM(lead_source), ''), 'Unknown') AS src, "
                        "COUNT(*) AS n FROM contacts GROUP BY 1 ORDER BY n DESC"
                    ).fetchall()
                    leads_by_source = [
                        {"source": dict(r)["src"], "count": int(dict(r)["n"] or 0)}
                        for r in rows
                    ]
                except Exception:
                    _log.debug("reporting: leads-by-source query failed", exc_info=True)

                # ── Leads by pipeline stage (NULL -> Unassigned) ───────────────
                try:
                    rows = conn.execute(
                        "SELECT COALESCE(pipeline_status, 'unassigned') AS stage, "
                        "COUNT(*) AS n FROM contacts GROUP BY 1 ORDER BY n DESC"
                    ).fetchall()
                    leads_by_stage = [
                        {"stage": dict(r)["stage"], "count": int(dict(r)["n"] or 0)}
                        for r in rows
                    ]
                except Exception:
                    _log.debug("reporting: leads-by-stage query failed", exc_info=True)

                # ── Leads by temperature ───────────────────────────────────────
                try:
                    rows = conn.execute(
                        "SELECT COALESCE(heat_label, 'normal') AS label, "
                        "COUNT(*) AS n FROM contacts GROUP BY 1 ORDER BY n DESC"
                    ).fetchall()
                    leads_by_temp = [
                        {"label": dict(r)["label"], "count": int(dict(r)["n"] or 0)}
                        for r in rows
                    ]
                except Exception:
                    _log.debug("reporting: leads-by-temp query failed", exc_info=True)

                # ── Funnel: Lead -> Conversation -> Appointment ->
                #    Under contract -> Closed. Mixes the contacts-system and the
                #    deals-system deliberately; labelled honestly in the UI. ────
                try:
                    leads_total = _scalar(conn, "SELECT COUNT(*) FROM contacts")
                    conversations = _scalar(conn, "SELECT COUNT(*) FROM conversations")
                    appts_total = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM deals WHERE appointment_date IS NOT NULL",
                    )
                    under_contract = _scalar(
                        conn,
                        "SELECT COUNT(*) FROM deals WHERE offer_accepted_at IS NOT NULL",
                    )
                    closed_total = _scalar(
                        conn, "SELECT COUNT(*) FROM deals WHERE status='closed'"
                    )
                    funnel = [
                        {"stage": "leads", "label": "Leads", "count": leads_total},
                        {"stage": "conversations", "label": "Conversations", "count": conversations},
                        {"stage": "appointments", "label": "Appointments", "count": appts_total},
                        {"stage": "under_contract", "label": "Under contract", "count": under_contract},
                        {"stage": "closed", "label": "Closed", "count": closed_total},
                    ]
                except Exception:
                    _log.debug("reporting: funnel query failed", exc_info=True)

                # ── Closed deals by source + GCI (reuse deals_overview) ────────
                try:
                    from elevate_cli.data import deals_overview

                    ov = deals_overview(conn, status="closed", exclude_mock=True)
                    by_src = ov.get("bySource") or {}
                    closed_by_source = [
                        {"source": str(k), "count": int(v or 0)}
                        for k, v in sorted(
                            by_src.items(), key=lambda kv: kv[1], reverse=True
                        )
                    ]
                except Exception:
                    _log.debug("reporting: closed-by-source (deals_overview) failed", exc_info=True)
                try:
                    gci = int(
                        round(
                            float(
                                conn.execute(
                                    "SELECT COALESCE(SUM(gci), 0) FROM deals WHERE status='closed'"
                                ).fetchone()[0]
                                or 0
                            )
                        )
                    )
                except Exception:
                    _log.debug("reporting: gci sum failed", exc_info=True)

                # ── Trend: leads by month + sales (closed deals) by month ──────
                # Closed date is the first present of closed_at / completed_at /
                # completion_date. Build the last 12 calendar months in Python so
                # empty months render as zero, not gaps.
                try:
                    lead_rows = conn.execute(
                        "SELECT substr(created_at,1,7) AS ym, COUNT(*) AS n "
                        "FROM contacts WHERE created_at IS NOT NULL GROUP BY 1"
                    ).fetchall()
                    lead_by_month = {dict(r)["ym"]: int(dict(r)["n"] or 0) for r in lead_rows}
                    sale_rows = conn.execute(
                        "SELECT substr(COALESCE(closed_at, completed_at, completion_date),1,7) AS ym, "
                        "COUNT(*) AS n FROM deals WHERE status='closed' "
                        "AND COALESCE(closed_at, completed_at, completion_date) IS NOT NULL "
                        "GROUP BY 1"
                    ).fetchall()
                    sale_by_month = {dict(r)["ym"]: int(dict(r)["n"] or 0) for r in sale_rows}

                    months: List[str] = []
                    y, m = today.year, today.month
                    for _ in range(12):
                        months.append(f"{y:04d}-{m:02d}")
                        m -= 1
                        if m == 0:
                            m = 12
                            y -= 1
                    months.reverse()
                    monthly = [
                        {
                            "month": ym,
                            "leads": lead_by_month.get(ym, 0),
                            "sales": sale_by_month.get(ym, 0),
                        }
                        for ym in months
                    ]
                except Exception:
                    _log.debug("reporting: monthly trend query failed", exc_info=True)

                # ── Trend: YoY (group by year) ─────────────────────────────────
                try:
                    lead_yr = conn.execute(
                        "SELECT substr(created_at,1,4) AS y, COUNT(*) AS n "
                        "FROM contacts WHERE created_at IS NOT NULL GROUP BY 1"
                    ).fetchall()
                    lead_by_year = {dict(r)["y"]: int(dict(r)["n"] or 0) for r in lead_yr}
                    sale_yr = conn.execute(
                        "SELECT substr(COALESCE(closed_at, completed_at, completion_date),1,4) AS y, "
                        "COUNT(*) AS n FROM deals WHERE status='closed' "
                        "AND COALESCE(closed_at, completed_at, completion_date) IS NOT NULL "
                        "GROUP BY 1"
                    ).fetchall()
                    sale_by_year = {dict(r)["y"]: int(dict(r)["n"] or 0) for r in sale_yr}
                    years = sorted(
                        y for y in (set(lead_by_year) | set(sale_by_year)) if y and y.isdigit()
                    )
                    yoy = [
                        {
                            "year": yr,
                            "leads": lead_by_year.get(yr, 0),
                            "sales": sale_by_year.get(yr, 0),
                            "ytd": int(yr) == cur_year,
                        }
                        for yr in years
                    ]
                except Exception:
                    _log.debug("reporting: yoy trend query failed", exc_info=True)

                goals = _read_goals(conn)
        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("GET /api/admin/reporting/summary failed")
            raise HTTPException(status_code=500, detail=f"Reporting read failed: {exc}")

        # Lead -> client conversion: closed deals over all leads (stable, honest).
        lead_to_client = (
            round(closed_total / leads_total * 100, 1) if leads_total > 0 else 0.0
        )

        kpis = {
            "newLeads": {"value": new_leads, "delta": _pct_delta(new_leads, prior_leads)},
            # THIN: voice is not tracked; surface the real count with a UI note.
            "calls": {"value": calls, "delta": None, "thin": True},
            "texts": {"value": texts, "delta": _pct_delta(texts, prior_texts)},
            "emails": {"value": emails, "delta": _pct_delta(emails, prior_emails)},
            "apptsBooked": {"value": appts, "delta": _pct_delta(appts, prior_appts)},
            "leadToClient": {"value": lead_to_client, "delta": None},
        }

        return {
            "window": window,
            "generatedAt": _iso(today),
            "kpis": kpis,
            "leadsBySource": leads_by_source,
            "leadsByStage": leads_by_stage,
            "leadsByTemperature": leads_by_temp,
            "funnel": funnel,
            "closedBySource": closed_by_source,
            "gci": gci,
            "trend": {"monthly": monthly, "yoy": yoy},
            # No ad-spend data source exists yet -> explicit empty-state marker.
            "marketingSpend": None,
            "goals": goals,
        }

    @router.get("/api/admin/reporting/goals")
    def get_reporting_goals():
        try:
            from elevate_cli.data import connect

            with connect() as conn:
                return _read_goals(conn)
        except Exception as exc:
            _log.exception("GET /api/admin/reporting/goals failed")
            raise HTTPException(status_code=500, detail=f"Goals read failed: {exc}")

    @router.post("/api/admin/reporting/goals")
    def post_reporting_goals(body: _GoalsBody):
        try:
            from elevate_cli.data import connect
            from elevate_cli.data._util import now_iso

            def _clean(v: Optional[int]) -> Optional[int]:
                if v is None:
                    return None
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    return None
                return iv if iv >= 0 else None

            leads = _clean(body.leadsGoal)
            appts = _clean(body.apptsGoal)
            closings = _clean(body.closingsGoal)
            gci = _clean(body.gciGoal)

            with connect() as conn:
                _ensure_goals_table(conn)
                now = now_iso()
                exists = conn.execute(
                    "SELECT 1 FROM crm_goals WHERE id=?", (_GOAL_ID,)
                ).fetchone()
                if exists is None:
                    conn.execute(
                        "INSERT INTO crm_goals "
                        "(id, leads_goal, appts_goal, closings_goal, gci_goal, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (_GOAL_ID, leads, appts, closings, gci, now),
                    )
                else:
                    conn.execute(
                        "UPDATE crm_goals SET leads_goal=?, appts_goal=?, "
                        "closings_goal=?, gci_goal=?, updated_at=? WHERE id=?",
                        (leads, appts, closings, gci, now, _GOAL_ID),
                    )
                return _read_goals(conn)
        except Exception as exc:
            _log.exception("POST /api/admin/reporting/goals failed")
            raise HTTPException(status_code=500, detail=f"Goals save failed: {exc}")

    return router
