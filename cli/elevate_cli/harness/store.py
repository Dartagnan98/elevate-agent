from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .models import HarnessRun, RunStatus, SourceSnapshot, utc_now_iso


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class HarnessStore:
    """SQLite persistence for AI harness runs/events/sources.

    Tests may pass a temporary DB path. Runtime should pass the existing
    ``~/.elevate/state.db`` path so Elevate keeps one local state database.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS harness_runs (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  run_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  account_context TEXT,
                  jurisdiction TEXT,
                  mode TEXT NOT NULL DEFAULT 'read_only',
                  allowed_domains_json TEXT NOT NULL DEFAULT '[]',
                  input_json TEXT NOT NULL DEFAULT '{}',
                  progress_json TEXT NOT NULL DEFAULT '{}',
                  resume_cursor_json TEXT NOT NULL DEFAULT '{}',
                  error_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS harness_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  message TEXT NOT NULL,
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(run_id) REFERENCES harness_runs(id)
                );

                CREATE TABLE IF NOT EXISTS source_snapshots (
                  id TEXT PRIMARY KEY,
                  run_id TEXT,
                  source_type TEXT NOT NULL,
                  source_uri TEXT NOT NULL,
                  title TEXT,
                  account_context TEXT,
                  jurisdiction TEXT,
                  raw_text_path TEXT,
                  markdown_path TEXT,
                  json_path TEXT,
                  file_path TEXT,
                  content_hash TEXT NOT NULL,
                  trust_level TEXT NOT NULL DEFAULT 'source',
                  captured_at TEXT NOT NULL,
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY(run_id) REFERENCES harness_runs(id)
                );
                """
            )

    def upsert_run(self, run: HarnessRun) -> None:
        run.updated_at = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO harness_runs (
                    id, name, run_type, status, account_context, jurisdiction, mode,
                    allowed_domains_json, input_json, progress_json,
                    resume_cursor_json, error_json, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    run_type=excluded.run_type,
                    status=excluded.status,
                    account_context=excluded.account_context,
                    jurisdiction=excluded.jurisdiction,
                    mode=excluded.mode,
                    allowed_domains_json=excluded.allowed_domains_json,
                    input_json=excluded.input_json,
                    progress_json=excluded.progress_json,
                    resume_cursor_json=excluded.resume_cursor_json,
                    error_json=excluded.error_json,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at
                """,
                (
                    run.id,
                    run.name,
                    run.run_type,
                    run.status,
                    run.account_context,
                    run.jurisdiction,
                    run.mode,
                    _json(run.allowed_domains),
                    _json(run.input),
                    _json(run.progress),
                    _json(run.resume_cursor),
                    _json(run.error),
                    run.created_at,
                    run.updated_at,
                    run.completed_at,
                ),
            )

    def get_run(self, run_id: str) -> HarnessRun | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM harness_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_runs(self, limit: int = 100) -> list[HarnessRun]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM harness_runs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def update_run_status(self, run_id: str, status: RunStatus, error: dict[str, Any] | None = None) -> None:
        completed_at = utc_now_iso() if status in {"completed", "failed", "cancelled"} else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE harness_runs
                   SET status = ?, error_json = COALESCE(?, error_json), updated_at = ?, completed_at = COALESCE(?, completed_at)
                 WHERE id = ?
                """,
                (status, _json(error) if error is not None else None, utc_now_iso(), completed_at, run_id),
            )

    def append_event(self, run_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO harness_events (run_id, event_type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, event_type, message, _json(payload or {}), utc_now_iso()),
            )

    def list_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM harness_events
                 WHERE run_id = ?
                 ORDER BY id ASC
                 LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [dict(row) | {"payload": _loads(row["payload_json"], {})} for row in rows]

    def insert_source_snapshot(self, snapshot: SourceSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO source_snapshots (
                    id, run_id, source_type, source_uri, title, account_context,
                    jurisdiction, raw_text_path, markdown_path, json_path, file_path,
                    content_hash, trust_level, captured_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.run_id,
                    snapshot.source_type,
                    snapshot.source_uri,
                    snapshot.title,
                    snapshot.account_context,
                    snapshot.jurisdiction,
                    snapshot.raw_text_path,
                    snapshot.markdown_path,
                    snapshot.json_path,
                    snapshot.file_path,
                    snapshot.content_hash,
                    snapshot.trust_level,
                    snapshot.captured_at,
                    _json(snapshot.metadata),
                ),
            )

    def list_source_snapshots(self, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM source_snapshots"
        params: tuple[Any, ...]
        if run_id:
            query += " WHERE run_id = ?"
            params = (run_id, limit)
        else:
            params = (limit,)
        query += " ORDER BY captured_at DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) | {"metadata": _loads(row["metadata_json"], {})} for row in rows]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> HarnessRun:
        return HarnessRun(
            id=row["id"],
            name=row["name"],
            run_type=row["run_type"],
            status=row["status"],
            account_context=row["account_context"],
            jurisdiction=row["jurisdiction"],
            mode=row["mode"],
            allowed_domains=_loads(row["allowed_domains_json"], []),
            input=_loads(row["input_json"], {}),
            progress=_loads(row["progress_json"], {}),
            resume_cursor=_loads(row["resume_cursor_json"], {}),
            error=_loads(row["error_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )
