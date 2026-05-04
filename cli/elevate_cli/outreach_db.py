"""SQLite store for outreach templates, draft attempts, and outcomes.

Lives at <tools_root>/data/outreach/outreach.db. The schema is small on purpose:
the agent picks a template, writes a draft, the human approves, and we record
which template produced which message and whether the lead replied.
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

from elevate_cli.config import load_config
from elevate_cli.source_connectors import _candidate_tools_root


LANES = ("new-outreach", "hot-leads-watcher", "follow-ups")
SEED_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "new-outreach": [
        {
            "name": "Warm intro",
            "body": "Hey {first_name}, saw you came through {source}. I help folks in {city} find the right place without the usual back and forth. What are you trying to figure out first?",
        },
        {
            "name": "Buyer fit",
            "body": "Hey {first_name}, you mentioned {topic} on {source}. Quick question: are you looking to be in by a date or still figuring out timing?",
        },
        {
            "name": "Listing alert",
            "body": "Hi {first_name}, a couple new {area} listings just hit that match what you flagged. Want me to send the short list?",
        },
    ],
    "hot-leads-watcher": [
        {
            "name": "Live nudge",
            "body": "{first_name}, just saw your {signal}. Want me to set up a viewing this week?",
        },
    ],
    "follow-ups": [
        {
            "name": "7 day check-in",
            "body": "Hey {first_name}, circling back on {topic}. Anything change on your end? Happy to send fresh options.",
        },
        {
            "name": "Soft close",
            "body": "Hi {first_name}, no pressure, just want to make sure I'm not missing anything. What would make the next step easy for you?",
        },
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    config = load_config()
    root = _candidate_tools_root(config) / "data" / "outreach"
    root.mkdir(parents=True, exist_ok=True)
    return root / "outreach.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit IMMEDIATE transaction for multi-write atomicity.

    Use when callers need an exclusive write lock for the whole block (e.g. approve
    -> enqueue must atomically pair the task-state flip with the send_queue insert).
    """
    if conn.in_transaction:
        conn.execute("ROLLBACK")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            lane TEXT NOT NULL,
            name TEXT NOT NULL,
            body TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'any',
            active INTEGER NOT NULL DEFAULT 1,
            uses INTEGER NOT NULL DEFAULT 0,
            replies INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_templates_lane ON templates(lane, active);

        -- (lane, name) is the natural key for templates — the seed list keys
        -- on it and seed_all_templates() relies on it for idempotent re-seeds.
        -- The UNIQUE INDEX is created after a defensive de-dupe pass below
        -- so legacy DBs don't fail the migration.

        CREATE TABLE IF NOT EXISTS draft_attempts (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            lane TEXT NOT NULL,
            source_id TEXT,
            thread_id TEXT,
            task_id TEXT,
            status TEXT NOT NULL DEFAULT 'drafted',
            created_at TEXT NOT NULL,
            outcome_recorded_at TEXT,
            outcome TEXT,
            FOREIGN KEY(template_id) REFERENCES templates(id)
        );

        CREATE INDEX IF NOT EXISTS idx_attempts_template ON draft_attempts(template_id);
        CREATE INDEX IF NOT EXISTS idx_attempts_thread ON draft_attempts(thread_id);

        CREATE TABLE IF NOT EXISTS send_queue (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            source_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            last_error TEXT,
            provider_message_id TEXT,
            attempt_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_send_queue_status ON send_queue(status, next_retry_at);
        CREATE INDEX IF NOT EXISTS idx_send_queue_task ON send_queue(source_id, thread_id, task_id);

        CREATE TABLE IF NOT EXISTS thread_meta (
            source_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            label TEXT NOT NULL DEFAULT 'unknown',
            reason TEXT,
            scored_by TEXT,
            scored_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source_id, thread_id)
        );

        CREATE INDEX IF NOT EXISTS idx_thread_meta_label ON thread_meta(label);
        CREATE INDEX IF NOT EXISTS idx_thread_meta_score ON thread_meta(score);

        CREATE TABLE IF NOT EXISTS lane_config (
            lane TEXT PRIMARY KEY,
            enabled_channels_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        );

        -- Phase 5 (composio inbound): O(1) provider-message dedupe.
        -- Replaces the prior strategy of streaming the full messages.jsonl
        -- on every tick — that scaled with file size and was unbounded.
        -- We key on (toolkit, provider_message_id) because pmids are only
        -- unique within a toolkit's namespace.
        CREATE TABLE IF NOT EXISTS inbound_seen (
            toolkit TEXT NOT NULL,
            provider_message_id TEXT NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY (toolkit, provider_message_id)
        );
        """
    )

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(templates)")}
    if "status" not in cols:
        conn.execute("ALTER TABLE templates ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if "rationale" not in cols:
        conn.execute("ALTER TABLE templates ADD COLUMN rationale TEXT")

    # Defensive de-dupe before enforcing UNIQUE(lane, name). For each
    # (lane, name) keep the most recently updated row — the rest are
    # almost always re-seed leftovers and never had distinct content the
    # user cared about. This MUST run before the unique index creation
    # below, or the index creation will fail on legacy DBs.
    dupe_rows = conn.execute(
        """
        SELECT id FROM templates
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY lane, name
                    ORDER BY updated_at DESC, created_at DESC, id
                ) AS rn
                FROM templates
            )
            WHERE rn = 1
        )
        """
    ).fetchall()
    if dupe_rows:
        ids = [r["id"] for r in dupe_rows]
        conn.executemany("DELETE FROM templates WHERE id = ?", [(i,) for i in ids])

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_templates_lane_name ON templates(lane, name)"
    )

    seeded_marker = _read_meta(conn, "seeded_v1")
    if not seeded_marker:
        for lane, items in SEED_TEMPLATES.items():
            for item in items:
                # INSERT OR IGNORE so the seed is idempotent: if a previous
                # partial run inserted the row but didn't write the marker,
                # we don't crash on UNIQUE(lane, name) the next start-up.
                _insert_template(
                    conn,
                    lane=lane,
                    name=item["name"],
                    body=item["body"],
                    or_ignore=True,
                )
        _write_meta(conn, "seeded_v1", _now())


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
        return random.choice(untried)
    if random.random() < epsilon:
        return random.choice(templates)
    templates.sort(key=lambda t: (t["winRate"], t["replyRate"], -t["uses"]), reverse=True)
    return templates[0]


def record_use(
    template_id: str,
    *,
    lane: str,
    source_id: str | None,
    thread_id: str | None,
    task_id: str | None,
) -> str:
    lane = _normalize_lane(lane)
    attempt_id = uuid.uuid4().hex
    now = _now()
    with connect() as conn:
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
    return _row_to_send(row)


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
