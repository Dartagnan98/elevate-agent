"""Auxiliary one-shot data migration: legacy SQLite/JSONL → Postgres.

Picks up where ``_pg_data_migrate.py`` left off. That module moves the
operational DB (contacts, deals, events, etc). This module moves the
"auxiliary" stores that lived outside operational.db:

  1. ``~/.elevate/orchestration.db``          → PG orchestration_* tables
  2. ``~/.elevate/usage_ledger.sqlite``       → PG turn_usage (rare/vestigial)
  3. ``~/.elevate/state.db`` turn_usage table → PG turn_usage
  4. ``~/.elevate/state.db`` sessions+messages+state_meta → PG chat_* tables
  5. ``~/.elevate/sessions/*.jsonl``          → PG chat_messages (orphan frames)

Each step is sentinel-gated through ``_schema_migrations``:

  - 9002 = orchestration migration done
  - 9003 = usage_ledger migration done
  - 9004 = state.db chat session migration done
  - 9005 = jsonl orphan migration done

Re-running this script is safe — completed sentinels are no-ops. To
force a re-run, delete the matching sentinel row from
``_schema_migrations`` first.

Source files are backed up to ``~/.elevate/`` with a
``.pre-pg-aux-migration`` suffix (where applicable) before any rows are
copied. The backups stay on disk for manual rollback until the user
runs ``elevate db purge-sqlite-backup`` (TODO command, manual rm for now).
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from elevate_constants import get_elevate_home
from elevate_cli.data.connection import connect

_LOG = logging.getLogger(__name__)


# Sentinel versions in `_schema_migrations`.
SENTINEL_ORCH = "9002"
SENTINEL_USAGE = "9003"
SENTINEL_CHAT = "9004"
SENTINEL_JSONL = "9005"

_BATCH = 1000


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pg_value(value: Any) -> Any:
    if isinstance(value, str) and "\x00" in value:
        return value.replace("\x00", "")
    return value


def _pg_row(values: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(_pg_value(value) for value in values)


def _has_sentinel(pg_conn, version: str) -> bool:
    row = pg_conn.execute(
        "SELECT 1 FROM _schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    return row is not None


def _mark_sentinel(pg_conn, version: str, name: str) -> None:
    raw = pg_conn._raw  # noqa: SLF001
    with raw.cursor() as cur:
        cur.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
            (version, name, "n/a-aux-import", _utcnow()),
        )
    raw.commit()


def _backup(src: Path) -> Path | None:
    if not src.exists():
        return None
    backup = src.with_suffix(src.suffix + ".pre-pg-aux-migration")
    if backup.exists():
        _LOG.info("backup: %s already exists", backup)
        return backup
    shutil.copy2(src, backup)
    _LOG.info("backup: wrote %s", backup)
    return backup


def _open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_columns(src: sqlite3.Connection, table: str) -> List[str]:
    rows = src.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [r[1] for r in rows]


def _pg_columns(pg_conn, table: str) -> List[str]:
    rows = pg_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def _stream_rows(
    src: sqlite3.Connection, table: str, cols: List[str], batch: int = _BATCH
) -> Iterable[List[tuple]]:
    quoted = ", ".join(f'"{c}"' for c in cols)
    cur = src.execute(f'SELECT {quoted} FROM "{table}"')
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            return
        yield [_pg_row(r) for r in rows]


def _copy_table(
    src: sqlite3.Connection,
    pg_conn,
    *,
    sqlite_table: str,
    pg_table: str,
    column_map: Dict[str, str] | None = None,
    on_conflict: str = "ON CONFLICT DO NOTHING",
) -> tuple[int, int]:
    """Copy rows from SQLite table → PG table.

    ``column_map`` lets the SQLite column name differ from the PG one
    (e.g. ``state.db`` has ``id`` for sessions but we keep the same
    column in chat_sessions). When None, columns are matched by name.
    """
    src_cols = _sqlite_columns(src, sqlite_table)
    pg_cols = _pg_columns(pg_conn, pg_table)

    chosen_src: List[str] = []
    chosen_pg: List[str] = []
    for sc in src_cols:
        pc = (column_map or {}).get(sc, sc)
        if pc in pg_cols:
            chosen_src.append(sc)
            chosen_pg.append(pc)

    if not chosen_src:
        _LOG.warning(
            "copy: %s → %s — no overlapping columns; skipping",
            sqlite_table, pg_table,
        )
        return 0, 0

    placeholders = ", ".join(["%s"] * len(chosen_pg))
    quoted = ", ".join(f'"{c}"' for c in chosen_pg)
    insert_sql = (
        f'INSERT INTO "{pg_table}" ({quoted}) VALUES ({placeholders}) {on_conflict}'
    )

    total = src.execute(f'SELECT COUNT(*) FROM "{sqlite_table}"').fetchone()[0]
    copied = 0
    raw = pg_conn._raw  # noqa: SLF001
    with raw.cursor() as cur:
        for batch in _stream_rows(src, sqlite_table, chosen_src):
            cur.executemany(insert_sql, batch)
            copied += len(batch)
    raw.commit()
    _LOG.info(
        "copy: %s → %s  rows=%d copied≤%d",
        sqlite_table, pg_table, total, copied,
    )
    return total, copied


# ─── per-store migrators ──────────────────────────────────────────────


def migrate_orchestration(pg_conn) -> Dict[str, Any]:
    """orchestration.db → PG orchestration_* tables."""
    src_path = get_elevate_home() / "orchestration.db"
    if _has_sentinel(pg_conn, SENTINEL_ORCH):
        return {"ran": False, "reason": "already migrated"}
    if not src_path.exists():
        _mark_sentinel(pg_conn, SENTINEL_ORCH, "aux:orchestration:no-source")
        return {"ran": False, "reason": "no source file"}

    _backup(src_path)
    src = _open_sqlite(src_path)
    try:
        totals: dict[str, tuple[int, int]] = {}
        for tbl in ("orchestration_agents", "orchestration_runs", "orchestration_events"):
            t, c = _copy_table(src, pg_conn, sqlite_table=tbl, pg_table=tbl)
            totals[tbl] = (t, c)
    finally:
        src.close()

    _mark_sentinel(pg_conn, SENTINEL_ORCH, "aux:orchestration")
    return {"ran": True, "source": str(src_path), "totals": totals}


def migrate_usage_ledger(pg_conn) -> Dict[str, Any]:
    """state.db turn_usage + vestigial usage_ledger.sqlite → PG turn_usage."""
    state_db = get_elevate_home() / "state.db"
    vestigial = get_elevate_home() / "usage_ledger.sqlite"

    if _has_sentinel(pg_conn, SENTINEL_USAGE):
        return {"ran": False, "reason": "already migrated"}

    totals: dict[str, tuple[int, int]] = {}

    # 1. state.db.turn_usage → PG turn_usage
    if state_db.exists():
        # No backup — state.db is too big and stays live for now.
        src = _open_sqlite(state_db)
        try:
            cols = _sqlite_columns(src, "turn_usage")
            if cols:
                t, c = _copy_table(
                    src, pg_conn,
                    sqlite_table="turn_usage", pg_table="turn_usage",
                )
                totals["state.db:turn_usage"] = (t, c)
        finally:
            src.close()

    # 2. vestigial usage_ledger.sqlite (columns differ — usage_turns shape)
    if vestigial.exists():
        _backup(vestigial)
        src = _open_sqlite(vestigial)
        try:
            cols = _sqlite_columns(src, "usage_turns")
            if cols:
                # Map vestigial column shape onto state.db shape.
                # vestigial usage_turns columns differ:
                # - vestigial.created_at (TEXT iso) → pg.created_at (TIMESTAMPTZ — let default fire)
                # - vestigial doesn't have `timestamp` (REAL epoch); synthesise from created_at
                # The simplest safe import: pull rows, derive a `timestamp` float
                # from created_at, then route through record_turn() so the PG
                # column defaults take care of the rest.
                from elevate_cli.data.usage_ledger import record_turn

                rows = src.execute("SELECT * FROM usage_turns").fetchall()
                imported = 0
                for row in rows:
                    d = dict(row)
                    # Synthesise epoch from ISO created_at if needed.
                    if "timestamp" not in d or d.get("timestamp") is None:
                        ts_iso = d.get("created_at")
                        try:
                            if isinstance(ts_iso, str):
                                ts_iso = ts_iso.replace("Z", "+00:00")
                                d["timestamp"] = datetime.fromisoformat(ts_iso).timestamp()
                            else:
                                d["timestamp"] = 0.0
                        except Exception:
                            d["timestamp"] = 0.0
                    # vestigial.selected_toolsets_json → PG.selected_toolsets
                    if "selected_toolsets" not in d and "selected_toolsets_json" in d:
                        d["selected_toolsets"] = d.get("selected_toolsets_json")
                    # vestigial.tool_calls_json → PG.tool_calls
                    if "tool_calls" not in d and "tool_calls_json" in d:
                        d["tool_calls"] = d.get("tool_calls_json")
                    if record_turn(d) is not None:
                        imported += 1
                totals["usage_ledger.sqlite:usage_turns"] = (len(rows), imported)
        finally:
            src.close()

    _mark_sentinel(pg_conn, SENTINEL_USAGE, "aux:usage_ledger")
    return {"ran": True, "totals": totals}


def migrate_chat_sessions(pg_conn) -> Dict[str, Any]:
    """state.db sessions + messages + state_meta → PG chat_* tables.

    Only populates the PG tables. The legacy state.db continues to be
    written by SessionDB until the SessionDB cutover follow-up ships.
    Re-running this migration after fresh state.db writes WILL drift
    until the cutover lands — that's expected and explicitly documented.
    """
    src_path = get_elevate_home() / "state.db"
    if _has_sentinel(pg_conn, SENTINEL_CHAT):
        return {"ran": False, "reason": "already migrated"}
    if not src_path.exists():
        _mark_sentinel(pg_conn, SENTINEL_CHAT, "aux:chat:no-source")
        return {"ran": False, "reason": "no source file"}

    src = _open_sqlite(src_path)
    try:
        totals: dict[str, tuple[int, int]] = {}

        # 1. sessions → chat_sessions  (same column names; ON CONFLICT(id) DO NOTHING)
        t, c = _copy_table(
            src, pg_conn,
            sqlite_table="sessions", pg_table="chat_sessions",
            on_conflict="ON CONFLICT (id) DO NOTHING",
        )
        totals["sessions"] = (t, c)

        # 2. messages → chat_messages  (id is SERIAL on PG, drop SQLite id col
        #    so PG generates fresh ones; otherwise rerun would conflict)
        src_cols = _sqlite_columns(src, "messages")
        pg_cols = _pg_columns(pg_conn, "chat_messages")
        chosen = [c for c in src_cols if c in pg_cols and c != "id"]
        if chosen:
            placeholders = ", ".join(["%s"] * len(chosen))
            quoted = ", ".join(f'"{c}"' for c in chosen)
            insert_sql = (
                f'INSERT INTO "chat_messages" ({quoted}) VALUES ({placeholders}) '
                "ON CONFLICT DO NOTHING"
            )
            total = src.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            copied = 0
            raw = pg_conn._raw  # noqa: SLF001
            with raw.cursor() as cur:
                for batch in _stream_rows(src, "messages", chosen):
                    cur.executemany(insert_sql, batch)
                    copied += len(batch)
            raw.commit()
            totals["messages"] = (total, copied)

        # 3. state_meta → chat_state_meta
        if "state_meta" in {r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}:
            t, c = _copy_table(
                src, pg_conn,
                sqlite_table="state_meta", pg_table="chat_state_meta",
                on_conflict="ON CONFLICT (key) DO NOTHING",
            )
            totals["state_meta"] = (t, c)
    finally:
        src.close()

    _mark_sentinel(pg_conn, SENTINEL_CHAT, "aux:chat_sessions")
    return {"ran": True, "source": str(src_path), "totals": totals}


def migrate_session_jsonl(pg_conn) -> Dict[str, Any]:
    """Import any JSONL transcript frames not already in chat_messages.

    Hits the directory ``~/.elevate/sessions/*.jsonl``. Skips frames
    whose ``session_id`` already has rows in ``chat_messages``. This
    only catches transcripts that pre-date the SessionDB era (when
    JSONL was the sole storage). New sessions go straight into PG and
    skip this path entirely.
    """
    sessions_dir = get_elevate_home() / "sessions"
    if _has_sentinel(pg_conn, SENTINEL_JSONL):
        return {"ran": False, "reason": "already migrated"}
    if not sessions_dir.exists():
        _mark_sentinel(pg_conn, SENTINEL_JSONL, "aux:jsonl:no-dir")
        return {"ran": False, "reason": "no sessions dir"}

    files = sorted(sessions_dir.glob("*.jsonl"))
    imported_files = 0
    imported_frames = 0
    skipped_files = 0

    # Resolve session_ids already in PG to avoid double-inserts.
    existing_session_ids: set[str] = set()
    rows = pg_conn.execute(
        "SELECT DISTINCT session_id FROM chat_messages"
    ).fetchall()
    for r in rows:
        sid = r[0] if isinstance(r, (list, tuple)) else r.get("session_id")
        if sid:
            existing_session_ids.add(sid)

    raw = pg_conn._raw  # noqa: SLF001
    for f in files:
        # JSONL filename convention: ``{session_id}.jsonl`` (post-2025) OR
        # a timestamped dump like ``20260430_121945_ea9689b7.jsonl`` (older).
        # We use the stem as the session_id either way.
        session_id = f.stem
        if session_id in existing_session_ids:
            skipped_files += 1
            continue

        # Ensure a parent session row exists (synthesise minimal one).
        try:
            with raw.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_sessions (id, source, started_at) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (session_id, "jsonl-backfill", f.stat().st_mtime),
                )
            raw.commit()
        except Exception as exc:
            _LOG.warning("jsonl: synth session row failed for %s: %s", session_id, exc)
            continue

        # Stream frames.
        frame_count = 0
        try:
            with f.open("r", encoding="utf-8") as fh, raw.cursor() as cur:
                batch: list[tuple] = []
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    role = frame.get("role") or "unknown"
                    if role == "session_meta":
                        # System frame, not a message — skip.
                        continue
                    content = frame.get("content")
                    if isinstance(content, (list, dict)):
                        content = json.dumps(content, ensure_ascii=False)
                    tool_calls = frame.get("tool_calls")
                    if isinstance(tool_calls, (list, dict)):
                        tool_calls = json.dumps(tool_calls, ensure_ascii=False)
                    reasoning_details = frame.get("reasoning_details")
                    if isinstance(reasoning_details, (list, dict)):
                        reasoning_details = json.dumps(
                            reasoning_details, ensure_ascii=False
                        )
                    codex_reasoning = frame.get("codex_reasoning_items")
                    if isinstance(codex_reasoning, (list, dict)):
                        codex_reasoning = json.dumps(
                            codex_reasoning, ensure_ascii=False
                        )
                    codex_message = frame.get("codex_message_items")
                    if isinstance(codex_message, (list, dict)):
                        codex_message = json.dumps(codex_message, ensure_ascii=False)
                    timestamp = frame.get("timestamp")
                    if not isinstance(timestamp, (int, float)):
                        timestamp = f.stat().st_mtime

                    batch.append(_pg_row((
                        session_id,
                        role,
                        content if isinstance(content, str) else None,
                        frame.get("tool_call_id"),
                        tool_calls if isinstance(tool_calls, str) else None,
                        frame.get("tool_name"),
                        float(timestamp),
                        None,  # token_count
                        frame.get("finish_reason"),
                        frame.get("reasoning"),
                        frame.get("reasoning_content"),
                        reasoning_details if isinstance(reasoning_details, str) else None,
                        codex_reasoning if isinstance(codex_reasoning, str) else None,
                        codex_message if isinstance(codex_message, str) else None,
                        frame.get("platform_message_id"),
                    )))
                    if len(batch) >= _BATCH:
                        cur.executemany(
                            'INSERT INTO chat_messages '
                            '(session_id, role, content, tool_call_id, tool_calls, '
                            'tool_name, timestamp, token_count, finish_reason, '
                            'reasoning, reasoning_content, reasoning_details, '
                            'codex_reasoning_items, codex_message_items, '
                            'platform_message_id) '
                            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '
                            '%s, %s, %s, %s)',
                            batch,
                        )
                        frame_count += len(batch)
                        batch.clear()
                if batch:
                    cur.executemany(
                        'INSERT INTO chat_messages '
                        '(session_id, role, content, tool_call_id, tool_calls, '
                        'tool_name, timestamp, token_count, finish_reason, '
                        'reasoning, reasoning_content, reasoning_details, '
                        'codex_reasoning_items, codex_message_items, '
                        'platform_message_id) '
                        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '
                        '%s, %s, %s, %s)',
                        batch,
                    )
                    frame_count += len(batch)
            raw.commit()
            existing_session_ids.add(session_id)
            imported_files += 1
            imported_frames += frame_count
            _LOG.info("jsonl: %s → %d frames", f.name, frame_count)
        except Exception as exc:
            _LOG.warning("jsonl: import failed for %s: %s", f.name, exc)
            raw.rollback()

    _mark_sentinel(pg_conn, SENTINEL_JSONL, "aux:jsonl")
    return {
        "ran": True,
        "files_imported": imported_files,
        "files_skipped": skipped_files,
        "frames_imported": imported_frames,
    }


# ─── public entry point ───────────────────────────────────────────────


def run_all() -> Dict[str, Any]:
    """Run every auxiliary migration in order. Idempotent.

    Bulk copies run under ``session_replication_role='replica'`` so FK
    constraints don't reject rows that reference parents loaded later in
    the same batch (same trick the operational DB import uses). The
    role is restored before commit even if a migrator raises.
    """
    summary: Dict[str, Any] = {}
    with connect() as conn:
        raw = conn._raw  # noqa: SLF001
        with raw.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")
        raw.commit()
        try:
            summary["orchestration"] = migrate_orchestration(conn)
            summary["usage_ledger"] = migrate_usage_ledger(conn)
            summary["chat_sessions"] = migrate_chat_sessions(conn)
            summary["session_jsonl"] = migrate_session_jsonl(conn)
        finally:
            with raw.cursor() as cur:
                cur.execute("SET session_replication_role = 'origin'")
            raw.commit()
    summary["completed_at"] = _utcnow()
    return summary


__all__ = [
    "run_all",
    "migrate_orchestration",
    "migrate_usage_ledger",
    "migrate_chat_sessions",
    "migrate_session_jsonl",
]
