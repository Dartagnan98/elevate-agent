"""One-call leads/outreach snapshot for the agent — the leads equivalent of
``deals_overview``.

When the user asks "where are my leads", "what's pending approval", "what's in
the outreach queue", "did anything send", or any aggregate outreach question,
call this ONCE instead of chaining elevate_db SQL counts. Returns the send-queue
pipeline: counts by status, what's pending approval (by channel + source), and
the most recent sends — everything needed to brief the realtor on lead outreach.

Backed by the per-account ``send_queue`` (the /leads approval + send pipeline).
"""

from __future__ import annotations

from typing import Any

from tools.registry import registry, tool_error, tool_result


def _leads_overview_handler(args: dict[str, Any], **_: Any) -> str:
    from elevate_cli import outreach_db

    def _int(key: str, default: int) -> int:
        try:
            v = args.get(key)
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    recent_limit = max(1, min(_int("recent_limit", 5), 25))

    try:
        status_counts = outreach_db.send_queue_stats()
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"leads_overview: send_queue unavailable: {exc}")

    pending_by_channel: dict[str, int] = {}
    pending_by_source: dict[str, int] = {}
    try:
        with outreach_db.connect() as conn:
            for row in conn.execute(
                "SELECT channel, COUNT(*) AS n FROM send_queue "
                "WHERE status='pending_approval' GROUP BY channel"
            ):
                pending_by_channel[str(row["channel"] or "unknown")] = int(row["n"])
            for row in conn.execute(
                "SELECT source_id, COUNT(*) AS n FROM send_queue "
                "WHERE status='pending_approval' GROUP BY source_id"
            ):
                pending_by_source[str(row["source_id"] or "unknown")] = int(row["n"])
    except Exception:  # noqa: BLE001 — breakdowns are best-effort
        pass

    recent_sends: list[dict[str, Any]] = []
    try:
        for s in outreach_db.list_recent_sends(
            statuses=(outreach_db.SEND_STATUS_SENT,), limit=recent_limit
        ):
            payload = s.get("payload") if isinstance(s.get("payload"), dict) else {}
            recipient = payload.get("recipient") if isinstance(payload.get("recipient"), dict) else {}
            recent_sends.append(
                {
                    "to": recipient.get("person_name") or recipient.get("email") or recipient.get("phone"),
                    "channel": s.get("channel"),
                    "at": s.get("updatedAt") or s.get("createdAt"),
                }
            )
    except Exception:  # noqa: BLE001
        pass

    # Leads the agent already worked recently (with the status it left them in)
    # so a heartbeat skips re-processing them and sees what was decided.
    recently_worked: list[dict[str, Any]] = []
    try:
        from elevate_cli.data import connect, leads_worked_recently
        since_hours = max(1, min(_int("worked_since_hours", 18), 168))
        with connect() as conn:
            recently_worked = leads_worked_recently(conn, since_hours=since_hours, limit=50)
    except Exception:  # noqa: BLE001 — best-effort
        pass

    overview = {
        "pendingApproval": status_counts.get("pending_approval", 0),
        "queued": status_counts.get("queued", 0),
        "sending": status_counts.get("sending", 0),
        "sent": status_counts.get("sent", 0),
        "failed": status_counts.get("failed", 0),
        "retrying": status_counts.get("retrying", 0),
        "byStatus": status_counts,
        "pendingByChannel": pending_by_channel,
        "pendingBySource": pending_by_source,
        "recentSends": recent_sends,
        "recentlyWorked": recently_worked,
    }
    return tool_result(success=True, overview=overview)


LEADS_OVERVIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "leads_overview",
        "description": (
            "Whole leads/outreach pipeline snapshot in ONE call. Use this "
            "instead of chaining elevate_db SQL counts whenever the user asks "
            "'where are my leads', 'what's pending approval', 'what's in the "
            "outreach queue', 'did anything send', or any aggregate outreach "
            "question.\n\n"
            "Returns: pendingApproval/queued/sending/sent/failed/retrying counts, "
            "byStatus (raw send_queue status map), pendingByChannel "
            "(sms/email/social → count), pendingBySource (apple-messages/crm/"
            "composio-gmail → count), recentSends (last N delivered, with "
            "recipient + channel + time), and recentlyWorked (leads YOU already "
            "handled in the last ~18h with the status you left them in — check "
            "this before working a lead so you don't redo it). Backed by the "
            "send_queue that powers the /leads Approve queue."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recent_limit": {
                    "type": "integer",
                    "description": "How many recent sends to include (default 5, max 25).",
                },
            },
        },
    },
}


registry.register(
    name="leads_overview",
    toolset="leads_overview",
    schema=LEADS_OVERVIEW_SCHEMA,
    handler=_leads_overview_handler,
    description=(
        "One-call leads/outreach snapshot: send-queue status counts, "
        "pending-approval by channel + source, recent sends."
    ),
    emoji="",
)
