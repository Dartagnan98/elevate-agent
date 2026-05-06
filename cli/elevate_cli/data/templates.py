"""Template proposal, approval, edit, retire — and stats.

Public surface:

* :func:`propose_template`           — any actor (cron / agent / human)
* :func:`approve_template`           — humans only
* :func:`reject_template`
* :func:`retire_template`
* :func:`edit_template`              — bumps version, supersedes the old row
* :func:`list_templates`             — filterable
* :func:`list_proposed_templates`
* :func:`get_template`
* :func:`template_stats`             — confident replies only
* :func:`template_stats_with_ambiguous`
* :func:`template_leaderboard`       — Sprint 4: leaderboard with min sample window
* :func:`record_template_use`        — counters used by Sprint 4 picker
* :func:`record_template_reply`

The approval invariant (status='live' ⇒ approved_at + approved_by) is
enforced both in the SQL CHECK constraint AND in this module — DB
keeps you safe in case a future migration loosens it, the module
keeps the error message useful.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.data import events as _events
from elevate_cli.data._util import new_id, now_iso


# Sprint 4 leaderboard threshold: a template doesn't appear on the
# authoritative leaderboard until it has cleared either bar.
_LEADERBOARD_MIN_USES = 50
_LEADERBOARD_MIN_AGE_DAYS = 30


_VALID_ORIGINS = {"human", "ai_oneoff", "ai_pattern", "ai_failure_analysis"}
_VALID_LANES = {"new-outreach", "hot-leads-watcher", "follow-ups"}


def _row_to_template(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    uses = int(row["uses"] or 0)
    replies = int(row["replies"] or 0)
    wins = int(row["wins"] or 0)
    reply_rate = replies / uses if uses else 0.0
    win_rate = wins / uses if uses else 0.0
    match_rules = None
    if "match_rules" in keys and row["match_rules"]:
        try:
            match_rules = json.loads(row["match_rules"])
        except json.JSONDecodeError:
            match_rules = None
    return {
        "id": row["id"],
        "lane": row["lane"],
        "name": row["name"],
        "body": row["body"],
        "channel": row["channel"],
        "active": bool(row["active"]),
        "status": row["status"],
        "rationale": row["rationale"] if "rationale" in keys else None,
        "version": row["version"],
        "matchRules": match_rules,
        "origin": row["origin"],
        "proposedByEventId": row["proposed_by_event_id"],
        "parentTemplateId": row["parent_template_id"],
        "approvedAt": row["approved_at"],
        "approvedBy": row["approved_by"],
        "uses": uses,
        "replies": replies,
        "wins": wins,
        "replyRate": round(reply_rate, 3),
        "winRate": round(win_rate, 3),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# ─── Reads ─────────────────────────────────────────────────────────────


def get_template(
    conn: sqlite3.Connection, template_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM templates WHERE id=?", (template_id,)
    ).fetchone()
    return _row_to_template(row) if row else None


def list_templates(
    conn: sqlite3.Connection,
    *,
    lane: str | None = None,
    status: str | None = None,
    origin: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM templates WHERE 1=1"
    params: list[Any] = []
    if lane:
        sql += " AND lane = ?"
        params.append(lane)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if origin:
        sql += " AND origin = ?"
        params.append(origin)
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY lane, name, version DESC"
    return [
        _row_to_template(r) for r in conn.execute(sql, params).fetchall()
    ]


def list_proposed_templates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return list_templates(conn, status="proposed")


# ─── Lifecycle ─────────────────────────────────────────────────────────


def propose_template(
    conn: sqlite3.Connection,
    *,
    lane: str,
    name: str,
    body: str,
    channel: str = "any",
    origin: str = "ai_oneoff",
    rationale: str | None = None,
    match_rules: Any = None,
    proposed_by_event_id: str | None = None,
    parent_template_id: str | None = None,
    actor: str,
    seed_event_contact_id: str | None = None,
) -> dict[str, Any]:
    """Create a new template in ``status='proposed'``.

    Cron and agents are allowed to call this. Approval (flipping the
    row to ``status='live'``) is gated by :func:`approve_template`,
    which rejects non-human actors.
    """
    if lane not in _VALID_LANES:
        raise ValueError(f"unknown lane {lane!r}")
    if origin not in _VALID_ORIGINS:
        raise ValueError(f"invalid origin {origin!r}")

    now = now_iso()
    tid = new_id()
    parent_version = 1
    if parent_template_id:
        parent = get_template(conn, parent_template_id)
        if parent is None:
            raise LookupError(f"parent template {parent_template_id!r} not found")
        parent_version = int(parent["version"]) + 1

    conn.execute(
        """
        INSERT INTO templates(
            id, lane, name, body, channel, active, status, rationale,
            uses, replies, wins, version, match_rules, origin,
            proposed_by_event_id, parent_template_id,
            approved_at, approved_by,
            created_at, updated_at
        ) VALUES (?,?,?,?,?, 0, 'proposed', ?, 0, 0, 0, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
        """,
        (
            tid, lane, name, body, channel, rationale, parent_version,
            json.dumps(match_rules) if match_rules is not None else None,
            origin,
            proposed_by_event_id, parent_template_id, now, now,
        ),
    )
    if seed_event_contact_id:
        _events.record_template_event(
            conn,
            kind="template_candidate",
            contact_id=seed_event_contact_id,
            template_id=tid,
            actor=actor,
            payload={"lane": lane, "origin": origin, "rationale": rationale},
        )
    return get_template(conn, tid)  # type: ignore[return-value]


def approve_template(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    actor: str,
    seed_event_contact_id: str | None = None,
) -> dict[str, Any]:
    """Flip a proposed template to ``status='live'``.

    Only human actors may approve — the rule is enforced both here AND
    by the SQL CHECK constraint on ``templates`` (no approved_at means
    the live status fails the constraint). Agents and cron should call
    :func:`propose_template` and wait for a human.
    """
    if not actor.startswith("human"):
        raise PermissionError(
            "approve_template requires a human actor (starts with 'human')"
        )
    now = now_iso()
    cur = conn.execute(
        """
        UPDATE templates
        SET status='live', active=1, approved_at=?, approved_by=?, updated_at=?
        WHERE id=? AND status='proposed'
        """,
        (now, actor, now, template_id),
    )
    if cur.rowcount == 0:
        existing = get_template(conn, template_id)
        if existing is None:
            raise LookupError(f"template {template_id!r} not found")
        if existing["status"] == "live":
            return existing
        raise ValueError(
            f"template {template_id!r} is in status={existing['status']!r}, "
            "only 'proposed' rows can be approved"
        )
    if seed_event_contact_id:
        _events.record_template_event(
            conn,
            kind="template_approved",
            contact_id=seed_event_contact_id,
            template_id=template_id,
            actor=actor,
        )
    return get_template(conn, template_id)  # type: ignore[return-value]


def reject_template(
    conn: sqlite3.Connection,
    template_id: str,
    reason: str,
    *,
    actor: str,
    seed_event_contact_id: str | None = None,
) -> dict[str, Any]:
    """Mark a proposed template ``status='retired'`` with a rejection note."""
    now = now_iso()
    conn.execute(
        """
        UPDATE templates
        SET status='retired', active=0, rationale=COALESCE(rationale,'') || ?, updated_at=?
        WHERE id=?
        """,
        (f"\n[rejected by {actor}: {reason}]", now, template_id),
    )
    if seed_event_contact_id:
        _events.record_template_event(
            conn,
            kind="template_rejected",
            contact_id=seed_event_contact_id,
            template_id=template_id,
            actor=actor,
            payload={"reason": reason},
        )
    return get_template(conn, template_id)  # type: ignore[return-value]


def retire_template(
    conn: sqlite3.Connection, template_id: str, *, actor: str
) -> dict[str, Any]:
    """Soft-deprecate a live template. Stats stay queryable."""
    conn.execute(
        "UPDATE templates SET status='retired', active=0, updated_at=? WHERE id=?",
        (now_iso(), template_id),
    )
    return get_template(conn, template_id)  # type: ignore[return-value]


def edit_template(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    new_body: str,
    actor: str,
) -> dict[str, Any]:
    """Bump version: the old row becomes ``status='superseded'`` and a
    new live row is created with ``version+1``. The new row inherits
    the lane/name/channel/match_rules; counters reset to zero so that
    stats stay clean.

    Approval-gating: humans can call this directly and the new row goes
    straight to live (auto-approved by the editor). Agents must use
    :func:`propose_template` with ``parent_template_id=`` for an edit
    they want a human to review."""
    if not actor.startswith("human"):
        raise PermissionError(
            "edit_template requires a human actor; agents must propose_template "
            "with parent_template_id= and wait for human approve."
        )

    parent = get_template(conn, template_id)
    if parent is None:
        raise LookupError(f"template {template_id!r} not found")
    if parent["status"] not in {"live", "proposed"}:
        raise ValueError(
            f"can only edit live/proposed templates; this one is "
            f"status={parent['status']!r}"
        )

    now = now_iso()
    # Mark parent as superseded
    conn.execute(
        "UPDATE templates SET status='superseded', active=0, updated_at=? WHERE id=?",
        (now, template_id),
    )

    # Create the new live row
    new_id_ = new_id()
    conn.execute(
        """
        INSERT INTO templates(
            id, lane, name, body, channel, active, status, rationale,
            uses, replies, wins, version, match_rules, origin,
            proposed_by_event_id, parent_template_id,
            approved_at, approved_by, created_at, updated_at
        ) VALUES (?,?,?,?,?, 1, 'live', ?, 0, 0, 0, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            new_id_,
            parent["lane"], parent["name"], new_body, parent["channel"],
            parent["rationale"],
            int(parent["version"]) + 1,
            json.dumps(parent["matchRules"]) if parent["matchRules"] is not None else None,
            "human",                # human edits are origin='human'
            template_id,            # parent_template_id
            now, actor,             # approved_at + approved_by
            now, now,
        ),
    )
    return get_template(conn, new_id_)  # type: ignore[return-value]


# ─── Counters + stats ──────────────────────────────────────────────────


def record_template_use(
    conn: sqlite3.Connection, template_id: str, *, count: int = 1
) -> None:
    """Bump ``uses`` after a successful send. Sprint 4's picker calls
    this; Sprint 1E's backfill replays history through it."""
    conn.execute(
        "UPDATE templates SET uses = uses + ?, updated_at=? WHERE id=?",
        (count, now_iso(), template_id),
    )


def record_template_reply(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    confident: bool = True,
    count: int = 1,
) -> None:
    """Bump ``replies`` (always) and ``wins`` (only when confident).

    ``replies`` is the raw count — every confirmed reply increments it.
    ``wins`` is the "confident reply attribution" count, used by the
    picker to compute Thompson-sampling priors that aren't poisoned by
    ambiguous attribution."""
    if confident:
        conn.execute(
            """
            UPDATE templates
            SET replies = replies + ?, wins = wins + ?, updated_at=?
            WHERE id=?
            """,
            (count, count, now_iso(), template_id),
        )
    else:
        conn.execute(
            "UPDATE templates SET replies = replies + ?, updated_at=? WHERE id=?",
            (count, now_iso(), template_id),
        )


def template_stats(
    conn: sqlite3.Connection, template_id: str
) -> dict[str, Any] | None:
    """Confident-only stats. Built straight off the counters; the
    nightly events_summary rollup is the cross-check, not the source."""
    t = get_template(conn, template_id)
    if t is None:
        return None
    return {
        "templateId": template_id,
        "lane": t["lane"],
        "uses": t["uses"],
        "replies": t["replies"],
        "winsConfident": t["wins"],
        "replyRate": t["replyRate"],
        "winRate": t["winRate"],
    }


def template_stats_with_ambiguous(
    conn: sqlite3.Connection, template_id: str
) -> dict[str, Any] | None:
    """Same as :func:`template_stats` but also surfaces ambiguous-attribution
    counts from the events log. Used by the /admin/templates leaderboard
    so the human can see "this template might also be responsible for N
    other replies we couldn't safely attribute"."""
    base = template_stats(conn, template_id)
    if base is None:
        return None
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM events
        WHERE kind = 'attribution_ambiguous'
          AND payload_json LIKE ?
        """,
        (f'%"{template_id}"%',),
    ).fetchone()
    base["ambiguousReplies"] = int(row["n"] or 0)
    return base


def _root_template_id(
    conn: sqlite3.Connection, template_id: str
) -> str:
    """Walk ``parent_template_id`` until we hit the root of an edit
    chain. Used by the leaderboard to roll versions up by lineage."""
    cur = template_id
    seen = {cur}
    while True:
        row = conn.execute(
            "SELECT parent_template_id FROM templates WHERE id=?", (cur,)
        ).fetchone()
        if row is None or not row["parent_template_id"]:
            return cur
        parent = row["parent_template_id"]
        if parent in seen:
            return cur  # cycle guard — should never trigger
        seen.add(parent)
        cur = parent


def template_leaderboard(
    conn: sqlite3.Connection,
    *,
    lane: str | None = None,
    channel: str | None = None,
    since: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Two-bucket leaderboard for /admin/templates.

    Returns ``{"authoritative": [...], "trial": [...]}``:

    * **authoritative** — templates that have cleared the min sample
      window (``uses ≥ 50`` OR created more than 30 days ago). These
      stats are believable.
    * **trial** — picker-eligible but stats too thin to rank yet.
      Surface separately so the realtor doesn't dismiss a brand-new
      template just because its tiny sample looks ugly.

    Versions roll up by ``parent_template_id`` lineage: every row in
    the chain contributes its uses/replies/wins to the lineage's
    aggregate, and the row with the highest version wins the display
    name + body. ``createdAt`` reports the lineage's earliest row so
    the age check measures the lineage, not the latest edit.

    ``since`` (ISO) is a future hook — V1 ignores it because we don't
    yet keep per-day rollups; counters on the templates row are
    cumulative. Reserved so callers can wire the parameter today and
    get richer behaviour in V2 without a signature change.
    """
    sql = "SELECT * FROM templates WHERE status IN ('live','retired','superseded')"
    params: list[Any] = []
    if lane is not None:
        sql += " AND lane = ?"
        params.append(lane)
    if channel is not None:
        sql += " AND (channel = ? OR channel = 'any')"
        params.append(channel)
    rows = conn.execute(sql, params).fetchall()

    # Group rows by lineage root.
    lineages: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tpl = _row_to_template(row)
        root = _root_template_id(conn, tpl["id"])
        lineages.setdefault(root, []).append(tpl)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_LEADERBOARD_MIN_AGE_DAYS)
    authoritative: list[dict[str, Any]] = []
    trial: list[dict[str, Any]] = []

    for root_id, members in lineages.items():
        # Aggregate counters across the lineage; pick the latest live
        # row (or fall back to the highest-version row) as the display.
        live_rows = [m for m in members if m["status"] == "live"]
        display = max(
            live_rows or members,
            key=lambda m: (m["version"], m["updatedAt"] or ""),
        )
        uses = sum(int(m["uses"] or 0) for m in members)
        replies = sum(int(m["replies"] or 0) for m in members)
        wins = sum(int(m["wins"] or 0) for m in members)
        first_created = min(m["createdAt"] for m in members)

        try:
            created_dt = datetime.fromisoformat(
                first_created.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            created_dt = now  # treat unparseable timestamps as brand-new

        meets_uses = uses >= _LEADERBOARD_MIN_USES
        meets_age = created_dt < cutoff
        bucket = authoritative if (meets_uses or meets_age) else trial

        bucket.append({
            "lineageRootId": root_id,
            "displayId": display["id"],
            "lane": display["lane"],
            "name": display["name"],
            "body": display["body"],
            "channel": display["channel"],
            "status": display["status"],
            "version": display["version"],
            "uses": uses,
            "replies": replies,
            "wins": wins,
            "replyRate": round(replies / uses, 3) if uses else 0.0,
            "winRate": round(wins / uses, 3) if uses else 0.0,
            "createdAt": first_created,
            "versionCount": len(members),
        })

    authoritative.sort(key=lambda r: (r["winRate"], r["uses"]), reverse=True)
    trial.sort(key=lambda r: r["createdAt"], reverse=True)
    return {"authoritative": authoritative, "trial": trial}
