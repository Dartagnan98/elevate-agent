"""Outreach store for templates, draft attempts, send queue, and outcomes.

Originally a sqlite file at ``<tools_root>/data/outreach/outreach.db``;
now backed by the central embedded Postgres (DB ``elevate_operational``)
via ``elevate_cli.data.connection``. The on-disk schema lives in
``data/migrations_pg/0011_outreach_store.sql`` and is applied on the
first ``data.connection.connect()`` call in the process. Legacy sqlite
rows are imported once by ``_pg_outreach_migrate.py`` (sentinel 9009)
on first boot after the cutover.

Call sites still use unprefixed table names (``templates``,
``draft_attempts``, etc.); migration 0011 ships compat views over the
prefixed ``outreach_*`` tables so this SQL surface keeps working
unchanged.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import psycopg

from elevate_cli.config import load_config
from elevate_cli.source_connectors import _candidate_tools_root
from elevate_cli.data import connection as _data_connection


LANES = ("new-outreach", "hot-leads-watcher", "follow-ups")
# Template bodies can carry a `[[gif:keyword]]` marker — the agent expands it
# to a GIF attachment when rendering. The UI shows a "GIF" badge for any
# template whose body contains the marker.
SEED_TEMPLATES: dict[str, list[dict[str, str]]] = {
    # First-touch (NEPQ). The intro carries the realtor's identity via the
    # {agent_name}/{brokerage} placeholders, which are filled from the
    # realtor's setup profile at draft time (see ``apply_realtor_identity``)
    # — NOT hardcoded — so the same seed ships to every install.
    "new-outreach": [
        {
            "name": "NEPQ buyer activity context",
            "body": "Hi {first_name} ! It's {agent_name} from {brokerage} :)\n\nSaw you were looking at {activity_context}. I don't want to send stuff that misses the mark.\n\nAre you focused on {area}, or still narrowing things down ?",
        },
        {
            "name": "NEPQ property view agency check",
            "body": "Hi {first_name} ! It's {agent_name} from {brokerage} :)\n\nSaw you were looking at {viewed_property}. Are you already working with an agent on that one, or are you still unrepresented ?",
        },
        {
            "name": "NEPQ seller value split",
            "body": "Hi {first_name} ! It's {agent_name} from {brokerage} :)\n\nSaw you came through about {seller_topic}. Are you mainly trying to get a ballpark number, or are you actually thinking about making a move ?",
        },
        {
            "name": "NEPQ unknown context",
            "body": "Hi {first_name} ! It's {agent_name} from {brokerage} :)\n\nYour name came through from {source}, but I don't have much context on what you were searching for.\n\nAre you looking around {area}, or did you land there by accident ?",
        },
    ],
    "hot-leads-watcher": [
        {
            "name": "NEPQ hot property view",
            "body": "{first_name}, saw you were back looking at {viewed_property}.\n\nIs that one actually worth a closer look, or was it more of a maybe ?",
        },
        {
            "name": "NEPQ hot search activity",
            "body": "{first_name}, I saw {search_activity} around {criteria}.\n\nAre those still the kind of places you want to see, or should I adjust what you're getting ?",
        },
    ],
    "follow-ups": [
        {
            "name": "NEPQ no-context cleanup",
            "body": "Hi {first_name}, I'm cleaning up my system and don't want to keep sending noise.\n\nAre you still keeping an eye on {area}, or should I pause things for now ?",
        },
        {
            "name": "NEPQ search still useful",
            "body": "Hey {first_name}, circling back on {criteria}.\n\nAre the matches still useful, or has the search gone on the back burner for now ?",
        },
        {
            "name": "NEPQ seller timing",
            "body": "Hi {first_name}, circling back on {seller_topic}.\n\nAre you still curious what the number looks like, or has the idea of moving gone quiet for now ?",
        },
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    """Legacy on-disk sqlite path.

    Still computed so callers that probe / archive the old file have a
    stable answer, but no longer opened — the live store is PG. The
    one-shot importer (``_pg_outreach_migrate.py``) reads from this
    location on first boot and is idempotent thereafter.
    """
    config = load_config()
    root = _candidate_tools_root(config) / "data" / "outreach"
    root.mkdir(parents=True, exist_ok=True)
    return root / "outreach.db"


# Module-level guard so the v2 template seed runs at most once per process
# (and only when the PG ``outreach_meta`` row is missing). Skipping the
# probe round-trip on every connect() shaves a few ms off hot paths like
# the draft pipeline that opens dozens of short-lived connections.
_SEEDED_THIS_PROCESS = False


@contextmanager
def connect() -> Iterator[Any]:
    """Open a PG-backed outreach connection.

    Delegates to ``data.connection.connect()`` so the connection comes
    from the shared pool, picks up schema migrations on the first call,
    and commits-or-rolls-back on context exit. The yielded object is a
    ``PgConnection`` shim with the sqlite-style ``execute() / cursor() /
    row[0|"col"] / executescript()`` surface, so the 80+ call sites in
    this module keep working unchanged.

    The legacy sqlite path (``db_path()``) is not touched here — the
    one-shot importer handles it once at gateway boot.
    """
    with _data_connection.connect() as conn:
        _maybe_seed_templates(conn)
        yield conn


@contextmanager
def transaction(conn) -> Iterator[Any]:
    """Explicit write-transaction wrapper, atomic over multiple statements.

    Sqlite-era contract was ``BEGIN IMMEDIATE`` so concurrent writers
    serialize cleanly (approve → enqueue must atomically pair the
    task-state flip with the send_queue insert). PG gives us the same
    guarantee through MVCC + the outer
    ``data.connection.transaction()`` wrapper, which rolls back on
    exception and commits on clean exit.
    """
    with _data_connection.transaction(conn):
        yield conn


def _maybe_seed_templates(conn) -> None:
    """Seed the v2 template set on first PG connection if not already seeded.

    The DDL itself lives in ``0011_outreach_store.sql`` (tables + indexes
    + compat views) so we don't need the sqlite-era ``CREATE TABLE IF NOT
    EXISTS`` / additive-column / unique-index dance here. What this
    function preserves is the seed-once behaviour: any fresh install
    (and the cutover from the empty 0-byte sqlite file on
    an existing install) needs the SEED_TEMPLATES set inserted into the
    new PG tables so the agent has lanes to draft against. ``INSERT OR
    IGNORE INTO templates`` keeps user-edited templates intact — only
    new (lane, name) pairs get inserted.
    """
    global _SEEDED_THIS_PROCESS
    if _SEEDED_THIS_PROCESS:
        return

    seeded_marker = _read_meta(conn, "seeded_v2")
    if seeded_marker:
        _SEEDED_THIS_PROCESS = True
        return

    for lane, items in SEED_TEMPLATES.items():
        for item in items:
            _insert_template(
                conn,
                lane=lane,
                name=item["name"],
                body=item["body"],
                or_ignore=True,
            )
    _write_meta(conn, "seeded_v2", _now())
    # Backfill the v1 marker so older code paths still see "seeded".
    _write_meta(conn, "seeded_v1", _now())
    _SEEDED_THIS_PROCESS = True


def _read_meta(conn: sqlite3.Connection, key: str) -> str | None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _realtor_identity(conn=None) -> dict[str, str]:
    """Best-effort read of the realtor's public identity from the admin setup
    profile, used to fill the ``{agent_name}``/``{brokerage}`` placeholders in
    outreach templates so first-touch copy carries THIS realtor's name instead
    of a hardcoded one. Returns blanks when identity isn't set yet (a fresh
    install before setup, or the table not yet created) so the placeholder is
    simply left in place.
    """

    def _query(c) -> dict[str, str]:
        try:
            row = c.execute(
                "SELECT license_name, realtor_legal_name, brokerage_name "
                "FROM admin_setup_profile LIMIT 1"
            ).fetchone()
        except Exception:
            return {"agent_name": "", "brokerage": ""}
        if not row:
            return {"agent_name": "", "brokerage": ""}
        name = (row["license_name"] or row["realtor_legal_name"] or "").strip()
        return {"agent_name": name, "brokerage": (row["brokerage_name"] or "").strip()}

    if conn is not None:
        return _query(conn)
    try:
        with _data_connection.connect() as c:
            return _query(c)
    except Exception:
        return {"agent_name": "", "brokerage": ""}


def apply_realtor_identity(body: str, conn=None) -> str:
    """Fill identity placeholders (``{agent_name}``, ``{brokerage}``) in a
    template body from the realtor's saved setup profile. Lead-context
    variables (e.g. ``{first_name}``) are intentionally left for the drafting
    agent. No-op when the body has no identity placeholder or identity isn't
    set yet — keeping the seed identical for every install while resolving to
    the right name at draft time.
    """
    if not body or ("{agent_name}" not in body and "{brokerage}" not in body):
        return body
    ident = _realtor_identity(conn)
    if ident.get("agent_name"):
        body = body.replace("{agent_name}", ident["agent_name"])
    if ident.get("brokerage"):
        body = body.replace("{brokerage}", ident["brokerage"])
    return body


def _insert_template(
    conn: sqlite3.Connection,
    *,
    lane: str,
    name: str,
    body: str,
    channel: str = "any",
    or_ignore: bool = False,
) -> str:
    """Insert a template. Returns the new id, or the existing id if
    ``or_ignore=True`` and ``(lane, name)`` already exists.

    The unique index on ``(lane, name)`` makes this safe for re-seed: with
    ``or_ignore=True`` we treat a UNIQUE collision as a no-op and resolve
    to the existing template's id.
    """
    template_id = uuid.uuid4().hex
    now = _now()
    sql = (
        "INSERT %s INTO templates (id, lane, name, body, channel, active, uses, replies, wins, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, 0, 0, 0, ?, ?)"
    ) % ("OR IGNORE" if or_ignore else "")
    cur = conn.execute(sql, (template_id, lane, name, body, channel, now, now))
    if or_ignore and cur.rowcount == 0:
        existing = conn.execute(
            "SELECT id FROM templates WHERE lane = ? AND name = ?",
            (lane, name),
        ).fetchone()
        if existing:
            return existing["id"]
    return template_id


def _row_to_template(row: sqlite3.Row) -> dict[str, Any]:
    uses = int(row["uses"] or 0)
    replies = int(row["replies"] or 0)
    wins = int(row["wins"] or 0)
    reply_rate = replies / uses if uses else 0.0
    win_rate = wins / uses if uses else 0.0
    keys = row.keys()
    status = row["status"] if "status" in keys else "active"
    rationale = row["rationale"] if "rationale" in keys else None
    return {
        "id": row["id"],
        "lane": row["lane"],
        "name": row["name"],
        "body": row["body"],
        "channel": row["channel"],
        "active": bool(row["active"]),
        "status": status or "active",
        "rationale": rationale,
        "uses": uses,
        "replies": replies,
        "wins": wins,
        "replyRate": round(reply_rate, 3),
        "winRate": round(win_rate, 3),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _normalize_lane(lane: str) -> str:
    lane = (lane or "").strip().lower()
    if lane not in LANES:
        raise ValueError(f"unknown lane '{lane}'. Valid: {', '.join(LANES)}")
    return lane


def list_templates(lane: str | None = None, include_inactive: bool = True) -> list[dict[str, Any]]:
    with connect() as conn:
        params: list[Any] = []
        sql = "SELECT * FROM templates"
        clauses: list[str] = []
        if lane:
            clauses.append("lane = ?")
            params.append(_normalize_lane(lane))
        if not include_inactive:
            clauses.append("active = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY lane, created_at"
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_template(r) for r in rows]


def list_templates_grouped() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    for tpl in list_templates():
        grouped.setdefault(tpl["lane"], []).append(tpl)
    return grouped


def create_template(
    *,
    lane: str,
    name: str,
    body: str,
    channel: str = "any",
) -> dict[str, Any]:
    lane = _normalize_lane(lane)
    name = (name or "").strip()
    body = (body or "").strip()
    if not name or not body:
        raise ValueError("name and body are required")
    with connect() as conn:
        template_id = _insert_template(conn, lane=lane, name=name, body=body, channel=channel)
        row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    return _row_to_template(row)


def update_template(
    template_id: str,
    *,
    name: str | None = None,
    body: str | None = None,
    channel: str | None = None,
    active: bool | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    params: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        params.append(name.strip())
    if body is not None:
        fields.append("body = ?")
        params.append(body.strip())
    if channel is not None:
        fields.append("channel = ?")
        params.append(channel.strip() or "any")
    if active is not None:
        fields.append("active = ?")
        params.append(1 if active else 0)
    if not fields:
        with connect() as conn:
            row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
            if not row:
                raise ValueError(f"template {template_id} not found")
            return _row_to_template(row)
    fields.append("updated_at = ?")
    params.append(_now())
    params.append(template_id)
    with connect() as conn:
        cur = conn.execute(f"UPDATE templates SET {', '.join(fields)} WHERE id = ?", params)
        if cur.rowcount == 0:
            raise ValueError(f"template {template_id} not found")
        row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    return _row_to_template(row)


def delete_template(template_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM templates WHERE id=?", (template_id,))
        return cur.rowcount > 0


def pick_template(lane: str, *, channel: str = "any", epsilon: float = 0.2) -> dict[str, Any] | None:
    """Epsilon-greedy template choice: usually best win-rate, sometimes a fresh one."""
    lane = _normalize_lane(lane)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM templates
            WHERE lane=? AND active=1
              AND (status IS NULL OR status='active')
              AND (channel=? OR channel='any')
            """,
            (lane, channel),
        ).fetchall()
    if not rows:
        return None
    templates = [_row_to_template(r) for r in rows]
    import random

    untried = [t for t in templates if t["uses"] == 0]
    if untried:
        chosen = random.choice(untried)
    elif random.random() < epsilon:
        chosen = random.choice(templates)
    else:
        templates.sort(key=lambda t: (t["winRate"], t["replyRate"], -t["uses"]), reverse=True)
        chosen = templates[0]
    # Fill the realtor's identity ({agent_name}/{brokerage}) so first-touch copy
    # isn't hardcoded to one realtor. Lead-side vars stay for the drafting agent.
    if chosen and chosen.get("body"):
        chosen = dict(chosen)
        chosen["body"] = apply_realtor_identity(chosen["body"])
    return chosen


def record_use_in_transaction(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    lane: str,
    source_id: str | None,
    thread_id: str | None,
    task_id: str | None,
) -> str:
    """Record one template use on an already-open transaction."""
    lane = _normalize_lane(lane)
    attempt_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        """
        INSERT INTO draft_attempts (id, template_id, lane, source_id, thread_id, task_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'drafted', ?)
        """,
        (attempt_id, template_id, lane, source_id, thread_id, task_id, now),
    )
    conn.execute(
        "UPDATE templates SET uses = uses + 1, updated_at = ? WHERE id = ?",
        (now, template_id),
    )
    return attempt_id


def record_use(
    template_id: str,
    *,
    lane: str,
    source_id: str | None,
    thread_id: str | None,
    task_id: str | None,
) -> str:
    with connect() as conn:
        return record_use_in_transaction(
            conn,
            template_id,
            lane=lane,
            source_id=source_id,
            thread_id=thread_id,
            task_id=task_id,
        )


def record_outcome(attempt_id: str, outcome: str) -> dict[str, Any]:
    """outcome ∈ {'replied','won','lost','no_response'}"""
    if outcome not in ("replied", "won", "lost", "no_response"):
        raise ValueError("outcome must be one of: replied, won, lost, no_response")
    now = _now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM draft_attempts WHERE id=?", (attempt_id,)).fetchone()
        if not row:
            raise ValueError(f"attempt {attempt_id} not found")
        conn.execute(
            "UPDATE draft_attempts SET outcome=?, outcome_recorded_at=?, status=? WHERE id=?",
            (outcome, now, "outcome_recorded", attempt_id),
        )
        if outcome == "replied":
            conn.execute(
                "UPDATE templates SET replies = replies + 1, updated_at=? WHERE id=?",
                (now, row["template_id"]),
            )
        elif outcome == "won":
            conn.execute(
                "UPDATE templates SET replies = replies + 1, wins = wins + 1, updated_at=? WHERE id=?",
                (now, row["template_id"]),
            )
        tpl = conn.execute("SELECT * FROM templates WHERE id=?", (row["template_id"],)).fetchone()
    return {"attemptId": attempt_id, "outcome": outcome, "template": _row_to_template(tpl)}


def stats() -> dict[str, Any]:
    with connect() as conn:
        templates = conn.execute("SELECT COUNT(*) AS n FROM templates").fetchone()["n"]
        attempts = conn.execute("SELECT COUNT(*) AS n FROM draft_attempts").fetchone()["n"]
        replies = conn.execute(
            "SELECT COUNT(*) AS n FROM draft_attempts WHERE outcome IN ('replied','won')"
        ).fetchone()["n"]
    return {"templates": templates, "attempts": attempts, "replies": replies}


# ---------------------------------------------------------------------------
# Overview / drift / approval flow
# ---------------------------------------------------------------------------

MIN_USES_FOR_RANKING = 5
DRIFT_DROP_THRESHOLD = 0.30
RECENT_WINDOW_DAYS = 30


def _recent_attempt_stats(conn: sqlite3.Connection, template_id: str, days: int) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc).timestamp() - days * 86400)
    iso_cutoff = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS uses,
          SUM(CASE WHEN outcome IN ('replied','won') THEN 1 ELSE 0 END) AS replies,
          SUM(CASE WHEN outcome='won' THEN 1 ELSE 0 END) AS wins
        FROM draft_attempts
        WHERE template_id = ? AND created_at >= ?
        """,
        (template_id, iso_cutoff),
    ).fetchone()
    uses = int(row["uses"] or 0)
    replies = int(row["replies"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "uses": uses,
        "replies": replies,
        "wins": wins,
        "replyRate": round(replies / uses, 3) if uses else 0.0,
        "winRate": round(wins / uses, 3) if uses else 0.0,
    }


def overview() -> dict[str, Any]:
    """Per-lane summary used by the Templates dashboard."""
    lanes_payload: list[dict[str, Any]] = []
    pending_total = 0
    with connect() as conn:
        for lane in LANES:
            rows = conn.execute(
                "SELECT * FROM templates WHERE lane=? ORDER BY created_at",
                (lane,),
            ).fetchall()
            templates = [_row_to_template(r) for r in rows]
            active = [t for t in templates if t["active"] and t["status"] == "active"]
            pending = [t for t in templates if t["status"] == "pending_approval"]
            pending_total += len(pending)

            ranked = [t for t in active if t["uses"] >= MIN_USES_FOR_RANKING]
            ranked.sort(key=lambda t: (t["replyRate"], -t["uses"]), reverse=True)
            best = ranked[0] if ranked else None
            worst = ranked[-1] if len(ranked) > 1 else None

            drift: list[dict[str, Any]] = []
            for tpl in active:
                if tpl["uses"] < MIN_USES_FOR_RANKING:
                    continue
                recent = _recent_attempt_stats(conn, tpl["id"], RECENT_WINDOW_DAYS)
                if recent["uses"] < MIN_USES_FOR_RANKING:
                    continue
                drop = tpl["replyRate"] - recent["replyRate"]
                if tpl["replyRate"] > 0 and drop / tpl["replyRate"] >= DRIFT_DROP_THRESHOLD:
                    drift.append({
                        "template": tpl,
                        "recent": recent,
                        "deltaPct": round((drop / tpl["replyRate"]) * 100, 1),
                    })

            total_attempts = sum(t["uses"] for t in active)
            total_replies = sum(t["replies"] for t in active)
            lane_reply_rate = (total_replies / total_attempts) if total_attempts else 0.0

            lanes_payload.append({
                "lane": lane,
                "totalTemplates": len(templates),
                "activeTemplates": len(active),
                "pendingTemplates": len(pending),
                "totalAttempts": total_attempts,
                "totalReplies": total_replies,
                "laneReplyRate": round(lane_reply_rate, 3),
                "best": best,
                "worst": worst if worst and worst["id"] != (best["id"] if best else None) else None,
                "drift": drift,
                "pending": pending,
            })

    return {
        "lanes": lanes_payload,
        "pendingTotal": pending_total,
        "thresholds": {
            "minUsesForRanking": MIN_USES_FOR_RANKING,
            "driftDropPct": int(DRIFT_DROP_THRESHOLD * 100),
            "recentWindowDays": RECENT_WINDOW_DAYS,
        },
    }


def create_pending_template(
    *,
    lane: str,
    name: str,
    body: str,
    channel: str = "any",
    rationale: str | None = None,
) -> dict[str, Any]:
    lane = _normalize_lane(lane)
    name = (name or "").strip()
    body = (body or "").strip()
    if not name or not body:
        raise ValueError("name and body are required")
    template_id = uuid.uuid4().hex
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO templates
              (id, lane, name, body, channel, active, status, rationale,
               uses, replies, wins, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, 'pending_approval', ?, 0, 0, 0, ?, ?)
            """,
            (template_id, lane, name, body, channel, rationale, now, now),
        )
        row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    return _row_to_template(row)


def approve_template(template_id: str) -> dict[str, Any]:
    now = _now()
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE templates SET status='active', active=1, updated_at=?
            WHERE id=?
            """,
            (now, template_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"template {template_id} not found")
        row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    return _row_to_template(row)


def reject_template(template_id: str) -> bool:
    now = _now()
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE templates SET status='archived', active=0, updated_at=?
            WHERE id=?
            """,
            (now, template_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Send queue
# ---------------------------------------------------------------------------

SEND_STATUS_QUEUED = "queued"
SEND_STATUS_SENDING = "sending"
SEND_STATUS_SENT = "sent"
SEND_STATUS_RETRYING = "retrying"
SEND_STATUS_FAILED = "failed"


def make_idempotency_key(source_id: str, thread_id: str, task_id: str, revision: int = 0) -> str:
    return f"{source_id}:{thread_id}:{task_id}:r{revision}"


def enqueue_send(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    thread_id: str,
    task_id: str,
    channel: str,
    payload: dict[str, Any],
    attempt_id: str | None = None,
    revision: int = 0,
) -> dict[str, Any]:
    """Insert a send_queue row inside the caller's transaction.

    Idempotent: if a row with the same idempotency_key already exists, returns
    the existing row instead of raising. Caller MUST already hold a write
    transaction (use `transaction(conn)` in the approve flow).
    """
    key = make_idempotency_key(source_id, thread_id, task_id, revision)
    existing = conn.execute(
        "SELECT * FROM send_queue WHERE idempotency_key=?", (key,)
    ).fetchone()
    if existing:
        return _row_to_send(existing)
    now = _now()
    queue_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO send_queue
            (id, idempotency_key, source_id, thread_id, task_id, channel,
             payload_json, status, attempts, attempt_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            queue_id, key, source_id, thread_id, task_id, channel,
            json.dumps(payload), SEND_STATUS_QUEUED, attempt_id, now, now,
        ),
    )
    row = conn.execute("SELECT * FROM send_queue WHERE id=?", (queue_id,)).fetchone()
    return _row_to_send(row)


def _row_to_send(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = row.keys()
    payload_json = row["payload_json"]
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except json.JSONDecodeError:
        payload = {"_decode_error": True, "raw": payload_json}
    return {
        "id": row["id"],
        "idempotencyKey": row["idempotency_key"],
        "sourceId": row["source_id"],
        "threadId": row["thread_id"],
        "taskId": row["task_id"],
        "channel": row["channel"],
        "payload": payload,
        "status": row["status"],
        "attempts": int(row["attempts"] or 0),
        "nextRetryAt": row["next_retry_at"] if "next_retry_at" in keys else None,
        "lastError": row["last_error"] if "last_error" in keys else None,
        "providerMessageId": row["provider_message_id"] if "provider_message_id" in keys else None,
        "attemptId": row["attempt_id"] if "attempt_id" in keys else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_send_by_task(source_id: str, thread_id: str, task_id: str) -> dict[str, Any] | None:
    """Return the most recent send_queue row for this draft task, or None."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM send_queue
            WHERE source_id=? AND thread_id=? AND task_id=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (source_id, thread_id, task_id),
        ).fetchone()
    return _row_to_send(row)


def list_sends_by_thread(
    source_id: str, thread_id: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Return send_queue rows for a thread, newest first."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM send_queue
            WHERE source_id=? AND thread_id=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (source_id, thread_id, max(1, min(int(limit or 50), 200))),
        ).fetchall()
    return [s for s in (_row_to_send(r) for r in rows) if s is not None]


def list_recent_sends(
    *,
    statuses: tuple[str, ...] = (SEND_STATUS_SENT,),
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return send_queue rows across all sources, newest first.

    Powers the /leads "Sent" tab. Defaults to status=sent only so the UI
    shows confirmed deliveries; callers can pass other statuses (queued,
    sending, retrying, failed) for an "outbound activity" view.
    """
    placeholders = ",".join("?" for _ in statuses) or "''"
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM send_queue
            WHERE status IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (*statuses, max(1, min(int(limit or 100), 500))),
        ).fetchall()
    return [s for s in (_row_to_send(r) for r in rows) if s is not None]


def claim_due_sends(limit: int = 10) -> list[dict[str, Any]]:
    """Atomically claim up to `limit` due rows: status in (queued, retrying)
    AND (next_retry_at IS NULL OR next_retry_at <= now). Flips claimed rows to
    'sending' inside one transaction so two ticks cannot race for the same row.
    """
    now = _now()
    claimed: list[dict[str, Any]] = []
    with connect() as conn:
        with transaction(conn):
            rows = conn.execute(
                f"""
                SELECT * FROM send_queue
                WHERE status IN ('{SEND_STATUS_QUEUED}', '{SEND_STATUS_RETRYING}')
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE send_queue SET status=?, updated_at=? WHERE id=?",
                    (SEND_STATUS_SENDING, now, row["id"]),
                )
                claimed.append(_row_to_send(row) | {"status": SEND_STATUS_SENDING})
    return claimed


def approve_pending_send(source_id: str, task_id: str) -> dict[str, Any] | None:
    """Flip a ``pending_approval`` send_queue row to ``queued`` so the sender picks
    it up. The /leads Approve button surfaces send_queue rows as drafts (id
    ``<source>:send-queue:<queue_id>``, taskId = the row's task_id or id), but the
    approve path historically only touched source-dir tasks — so these never queued
    and never sent. Match by (source_id, task_id|id) and release the latest pending
    one. Returns the queued row, or None if there's no pending row to release."""
    now = _now()
    with connect() as conn:
        with transaction(conn):
            row = conn.execute(
                """
                SELECT * FROM send_queue
                 WHERE status = 'pending_approval'
                   AND source_id = ?
                   AND (task_id = ? OR id = ?)
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
                (source_id, task_id, task_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE send_queue SET status=?, updated_at=? WHERE id=?",
                (SEND_STATUS_QUEUED, now, row["id"]),
            )
        out = conn.execute("SELECT * FROM send_queue WHERE id=?", (row["id"],)).fetchone()
    return _row_to_send(out)


def mark_sent(queue_id: str, provider_message_id: str) -> dict[str, Any] | None:
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE send_queue
               SET status=?, provider_message_id=?, last_error=NULL, updated_at=?
             WHERE id=?
            """,
            (SEND_STATUS_SENT, provider_message_id, now, queue_id),
        )
        row = conn.execute("SELECT * FROM send_queue WHERE id=?", (queue_id,)).fetchone()
    send = _row_to_send(row)
    if send:
        _mirror_send_to_operational_db(send)
    return send


def _mirror_send_to_operational_db(send: dict[str, Any]) -> None:
    """Codex audit P2 (2026-05-05): on every successful send, mirror an
    outbound event into operational.db so DB-primary readers
    (db_thread_context_response) and downstream attribution see the send
    without waiting for a CRM resync. Idempotent — the events table
    enforces unique event_hash, so re-runs no-op.

    Best-effort: failures here must not break the user-facing send path.
    """
    try:
        payload = send.get("payload") or {}
        body = payload.get("text") or payload.get("draft_text") or ""
        if not body:
            return
        source_id = send.get("sourceId")
        thread_id = send.get("threadId")
        if not (source_id and thread_id):
            return
        from elevate_cli.data import connect as _data_connect
        from elevate_cli.data import events as _data_events
        with _data_connect() as conn:
            conv = conn.execute(
                "SELECT id, contact_id FROM conversations "
                "WHERE source_id=? AND thread_key=?",
                (source_id, thread_id),
            ).fetchone()
            if conv is None:
                return  # no DB conversation yet — sync hasn't run
            _data_events.record_outbound(
                conn,
                contact_id=conv["contact_id"],
                conversation_id=conv["id"],
                channel=send.get("channel") or "unknown",
                body=str(body),
                source_id=str(source_id),
                thread_key=str(thread_id),
            )
    except Exception:
        # Best-effort mirror — never block a real send on this.
        return


def mark_retrying(queue_id: str, *, error: str, next_retry_at: str) -> dict[str, Any] | None:
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE send_queue
               SET status=?, attempts=attempts+1, last_error=?, next_retry_at=?, updated_at=?
             WHERE id=?
            """,
            (SEND_STATUS_RETRYING, error, next_retry_at, now, queue_id),
        )
        row = conn.execute("SELECT * FROM send_queue WHERE id=?", (queue_id,)).fetchone()
    return _row_to_send(row)


def mark_failed(queue_id: str, *, error: str) -> dict[str, Any] | None:
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE send_queue
               SET status=?, attempts=attempts+1, last_error=?, next_retry_at=NULL, updated_at=?
             WHERE id=?
            """,
            (SEND_STATUS_FAILED, error, now, queue_id),
        )
        row = conn.execute("SELECT * FROM send_queue WHERE id=?", (queue_id,)).fetchone()
    return _row_to_send(row)


def send_queue_stats() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM send_queue GROUP BY status"
        ).fetchall()
    out = {row["status"]: int(row["n"]) for row in rows}
    return out


# ---------------------------------------------------------------------------
# Thread metadata (Phase 6: lead scorer + dead label)
# ---------------------------------------------------------------------------

THREAD_LABELS = {"buyer", "seller", "investor", "chitchat", "dead", "unknown"}


def _normalize_label(label: str) -> str:
    label = (label or "").strip().lower()
    if label not in THREAD_LABELS:
        raise ValueError(f"unknown thread label '{label}'. Valid: {', '.join(sorted(THREAD_LABELS))}")
    return label


def _row_to_thread_meta(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "sourceId": row["source_id"],
        "threadId": row["thread_id"],
        "score": int(row["score"] or 0),
        "label": row["label"] or "unknown",
        "reason": row["reason"],
        "scoredBy": row["scored_by"],
        "scoredAt": row["scored_at"],
        "updatedAt": row["updated_at"],
    }


def get_thread_meta(source_id: str, thread_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM thread_meta WHERE source_id=? AND thread_id=?",
            (source_id, thread_id),
        ).fetchone()
    return _row_to_thread_meta(row)


def upsert_thread_score(
    source_id: str,
    thread_id: str,
    *,
    score: int,
    label: str,
    reason: str | None = None,
    scored_by: str | None = None,
) -> dict[str, Any]:
    """Idempotent score upsert. ``label`` must be one of THREAD_LABELS.

    Score is clamped to [0, 100]. Reason is freeform short text the UI can
    surface in a tooltip ("inbound says 'looking June, $1.5M'", "no reply
    in 60d", etc.).
    """
    if not source_id or not thread_id:
        raise ValueError("source_id and thread_id are required")
    label_norm = _normalize_label(label)
    score_clamped = max(0, min(100, int(score)))
    now = _now()
    with connect() as conn:
        with transaction(conn):
            existing = conn.execute(
                "SELECT scored_at FROM thread_meta WHERE source_id=? AND thread_id=?",
                (source_id, thread_id),
            ).fetchone()
            scored_at = existing["scored_at"] if existing else now
            conn.execute(
                """
                INSERT INTO thread_meta (source_id, thread_id, score, label, reason, scored_by, scored_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, thread_id) DO UPDATE SET
                    score = excluded.score,
                    label = excluded.label,
                    reason = excluded.reason,
                    scored_by = excluded.scored_by,
                    updated_at = excluded.updated_at
                """,
                (source_id, thread_id, score_clamped, label_norm, reason, scored_by, scored_at, now),
            )
            row = conn.execute(
                "SELECT * FROM thread_meta WHERE source_id=? AND thread_id=?",
                (source_id, thread_id),
            ).fetchone()
    return _row_to_thread_meta(row)  # type: ignore[return-value]


def mark_thread_dead(
    source_id: str,
    thread_id: str,
    *,
    reason: str | None = None,
    scored_by: str | None = None,
) -> dict[str, Any]:
    """Convenience: set score=0, label='dead'. Used when a human or the scorer
    decides to retire a thread from active lanes."""
    return upsert_thread_score(
        source_id,
        thread_id,
        score=0,
        label="dead",
        reason=reason,
        scored_by=scored_by,
    )


def list_thread_meta(
    *,
    label: str | None = None,
    min_score: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM thread_meta"
    clauses: list[str] = []
    params: list[Any] = []
    if label:
        clauses.append("label = ?")
        params.append(_normalize_label(label))
    if min_score is not None:
        clauses.append("score >= ?")
        params.append(int(min_score))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY score DESC, updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_thread_meta(r) for r in rows if r is not None]  # type: ignore[list-item]


def thread_meta_stats() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT label, COUNT(*) AS n FROM thread_meta GROUP BY label"
        ).fetchall()
    return {row["label"]: int(row["n"]) for row in rows}


# ---------------------------------------------------------------------------
# Lane channel configuration (Phase 7: per-lane channel picker)
# ---------------------------------------------------------------------------

def seed_all_templates() -> dict[str, Any]:
    """Idempotent re-seed of the SEED_TEMPLATES set.

    Safe to call from the onboarding wizard. UNIQUE(lane, name) makes
    re-seeds a no-op for any (lane, name) pair already present. Existing
    user-edited templates are left alone.
    """
    inserted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    with connect() as conn:
        with transaction(conn):
            for lane, items in SEED_TEMPLATES.items():
                for item in items:
                    existing = conn.execute(
                        "SELECT id FROM templates WHERE lane = ? AND name = ?",
                        (lane, item["name"]),
                    ).fetchone()
                    if existing:
                        skipped.append({"lane": lane, "name": item["name"]})
                        continue
                    tid = _insert_template(
                        conn,
                        lane=lane,
                        name=item["name"],
                        body=item["body"],
                        or_ignore=True,
                    )
                    inserted.append({"lane": lane, "name": item["name"], "id": tid})
            _write_meta(conn, "seeded_v1", _now())
    return {
        "inserted": inserted,
        "skipped": skipped,
        "totalInserted": len(inserted),
        "totalSkipped": len(skipped),
    }


def get_lane_config(lane: str) -> dict[str, Any]:
    """Return ``{lane, enabledChannels, updatedAt}``. Returns an empty
    enabledChannels list if the lane has never been configured — never raises
    on a missing row, since "no rules yet" is a valid lane state."""
    lane_norm = _normalize_lane(lane)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM lane_config WHERE lane = ?", (lane_norm,)
        ).fetchone()
    if row is None:
        return {"lane": lane_norm, "enabledChannels": [], "updatedAt": None}
    try:
        channels = json.loads(row["enabled_channels_json"]) or []
    except Exception:
        channels = []
    if not isinstance(channels, list):
        channels = []
    return {
        "lane": lane_norm,
        "enabledChannels": [str(c) for c in channels],
        "updatedAt": row["updated_at"],
    }


def list_lane_configs() -> list[dict[str, Any]]:
    """One row per known lane. Lanes with no row return empty enabledChannels."""
    return [get_lane_config(lane) for lane in LANES]


# ---------------------------------------------------------------------------
# Composio inbound dedupe (Phase 5)
# ---------------------------------------------------------------------------

def inbound_seen_lookup(toolkit: str, pmids: Iterable[str]) -> set[str]:
    """Return the subset of ``pmids`` already recorded for ``toolkit``.

    O(1) per id via the (toolkit, provider_message_id) primary key —
    replaces the prior strategy of streaming the entire messages.jsonl on
    every tick, which scaled with file size and was unbounded.
    """
    ids = [str(p).strip() for p in pmids if str(p).strip()]
    if not ids:
        return set()
    seen: set[str] = set()
    with connect() as conn:
        # SQLite has a 999-bound on host params for older builds; chunk to be safe.
        chunk = 500
        for i in range(0, len(ids), chunk):
            batch = ids[i : i + chunk]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT provider_message_id FROM inbound_seen WHERE toolkit = ? AND provider_message_id IN ({placeholders})",
                (toolkit, *batch),
            ).fetchall()
            for r in rows:
                seen.add(str(r["provider_message_id"]))
    return seen


def inbound_seen_record(toolkit: str, pmids: Iterable[str]) -> int:
    """Record ``pmids`` as seen for ``toolkit``. Returns count of new rows.

    INSERT OR IGNORE so concurrent inbound pulls (or a retry that re-fetches
    a page) don't bounce on the primary key.
    """
    ids = [str(p).strip() for p in pmids if str(p).strip()]
    if not ids:
        return 0
    now = _now()
    rows_before = 0
    rows_after = 0
    with connect() as conn:
        rows_before = conn.execute(
            "SELECT COUNT(*) AS n FROM inbound_seen WHERE toolkit = ?", (toolkit,)
        ).fetchone()["n"]
        with transaction(conn):
            conn.executemany(
                "INSERT OR IGNORE INTO inbound_seen (toolkit, provider_message_id, seen_at) VALUES (?, ?, ?)",
                [(toolkit, p, now) for p in ids],
            )
        rows_after = conn.execute(
            "SELECT COUNT(*) AS n FROM inbound_seen WHERE toolkit = ?", (toolkit,)
        ).fetchone()["n"]
    return int(rows_after - rows_before)


def set_lane_channels(lane: str, channels: list[str]) -> dict[str, Any]:
    """Idempotent set of the lane's enabled channels.

    No validation against the capability matrix happens here — the DB layer
    just persists what the caller provides. The web layer is responsible for
    rejecting channels the user can't actually send through, so the matrix
    can evolve without invalidating stored config.
    """
    lane_norm = _normalize_lane(lane)
    if not isinstance(channels, list):
        raise ValueError("channels must be a list of strings")
    cleaned = [str(c).strip() for c in channels if str(c).strip()]
    payload = json.dumps(cleaned)
    now = _now()
    with connect() as conn:
        with transaction(conn):
            conn.execute(
                """
                INSERT INTO lane_config (lane, enabled_channels_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(lane) DO UPDATE SET
                    enabled_channels_json = excluded.enabled_channels_json,
                    updated_at = excluded.updated_at
                """,
                (lane_norm, payload, now),
            )
    return get_lane_config(lane_norm)
