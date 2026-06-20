"""Analytics routes for dashboard usage reporting."""

import logging
import time
from typing import Any, Callable

from fastapi import APIRouter


SessionDbFactory = Callable[[], Any]


def create_analytics_router(
    *,
    get_session_db: SessionDbFactory,
    log: logging.Logger | None = None,
) -> APIRouter:
    """Build dashboard analytics routes."""
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.get("/api/analytics/usage")
    def get_usage_analytics(days: int = 30):
        from agent.insights import InsightsEngine

        cutoff = time.time() - (days * 86400) if days > 0 else None
        where_sql = "WHERE started_at > ?" if cutoff is not None else ""
        params = (cutoff,) if cutoff is not None else ()
        try:
            from elevate_cli.data.connection import connect

            with connect() as conn:
                cur = conn.execute(f"""
                    SELECT to_timestamp(started_at)::date::text as day,
                           COALESCE(SUM(input_tokens), 0) as input_tokens,
                           COALESCE(SUM(output_tokens), 0) as output_tokens,
                           COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                           COALESCE(SUM(reasoning_tokens), 0) as reasoning_tokens,
                           COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                           COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                           COUNT(*) as sessions,
                           COALESCE(SUM(api_call_count), 0) as api_calls
                    FROM chat_sessions {where_sql}
                    GROUP BY 1 ORDER BY 1
                """, params)
                daily = [dict(r) for r in cur.fetchall()]

                model_where = (
                    f"{where_sql} AND model IS NOT NULL"
                    if where_sql
                    else "WHERE model IS NOT NULL"
                )
                cur2 = conn.execute(f"""
                    SELECT model,
                           COALESCE(SUM(input_tokens), 0) as input_tokens,
                           COALESCE(SUM(output_tokens), 0) as output_tokens,
                           COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                           COUNT(*) as sessions,
                           COALESCE(SUM(api_call_count), 0) as api_calls
                    FROM chat_sessions {model_where}
                    GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
                """, params)
                by_model = [dict(r) for r in cur2.fetchall()]

                cur3 = conn.execute(f"""
                    SELECT COALESCE(SUM(input_tokens), 0) as total_input,
                           COALESCE(SUM(output_tokens), 0) as total_output,
                           COALESCE(SUM(cache_read_tokens), 0) as total_cache_read,
                           COALESCE(SUM(reasoning_tokens), 0) as total_reasoning,
                           COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                           COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                           COUNT(*) as total_sessions,
                           COALESCE(SUM(api_call_count), 0) as total_api_calls
                    FROM chat_sessions {where_sql}
                """, params)
                totals = dict(cur3.fetchone())

            try:
                db = get_session_db()
                try:
                    insights_report = InsightsEngine(db).generate(days=days if days > 0 else 3650)
                    skills = insights_report.get("skills")
                finally:
                    db.close()
            except Exception:
                skills = None
            if not isinstance(skills, dict):
                skills = {
                    "summary": {
                        "total_skill_loads": 0,
                        "total_skill_edits": 0,
                        "total_skill_actions": 0,
                        "distinct_skills_used": 0,
                    },
                    "top_skills": [],
                }
            return {
                "daily": daily,
                "by_model": by_model,
                "totals": totals,
                "period_days": days,
                "skills": skills,
                "source": "postgres",
            }
        except Exception:
            _log.debug("analytics usage PG read failed, falling back to SQLite", exc_info=True)

        db = get_session_db()
        try:
            cutoff = time.time() - (days * 86400) if days > 0 else 0
            cur = db._conn.execute("""
                SELECT date(started_at, 'unixepoch') as day,
                       SUM(input_tokens) as input_tokens,
                       SUM(output_tokens) as output_tokens,
                       SUM(cache_read_tokens) as cache_read_tokens,
                       SUM(reasoning_tokens) as reasoning_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                       COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                       COUNT(*) as sessions,
                       SUM(COALESCE(api_call_count, 0)) as api_calls
                FROM sessions WHERE started_at > ?
                GROUP BY day ORDER BY day
            """, (cutoff,))
            daily = [dict(r) for r in cur.fetchall()]

            cur2 = db._conn.execute("""
                SELECT model,
                       SUM(input_tokens) as input_tokens,
                       SUM(output_tokens) as output_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                       COUNT(*) as sessions,
                       SUM(COALESCE(api_call_count, 0)) as api_calls
                FROM sessions WHERE started_at > ? AND model IS NOT NULL
                GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
            """, (cutoff,))
            by_model = [dict(r) for r in cur2.fetchall()]

            cur3 = db._conn.execute("""
                SELECT SUM(input_tokens) as total_input,
                       SUM(output_tokens) as total_output,
                       SUM(cache_read_tokens) as total_cache_read,
                       SUM(reasoning_tokens) as total_reasoning,
                       COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                       COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                       COUNT(*) as total_sessions,
                       SUM(COALESCE(api_call_count, 0)) as total_api_calls
                FROM sessions WHERE started_at > ?
            """, (cutoff,))
            totals = dict(cur3.fetchone())
            insights_report = InsightsEngine(db).generate(days=days)
            skills = insights_report.get("skills", {
                "summary": {
                    "total_skill_loads": 0,
                    "total_skill_edits": 0,
                    "total_skill_actions": 0,
                    "distinct_skills_used": 0,
                },
                "top_skills": [],
            })

            return {
                "daily": daily,
                "by_model": by_model,
                "totals": totals,
                "period_days": days,
                "skills": skills,
                "source": "sqlite",
            }
        finally:
            db.close()

    return router
