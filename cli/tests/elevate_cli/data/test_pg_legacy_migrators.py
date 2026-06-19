from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from elevate_cli.data.connection import _reset_schema_cache, connect
from elevate_cli.data.paths import operational_db_path
from elevate_cli.data import (
    _pg_data_migrate,
    _pg_kanban_migrate,
    _pg_memory_migrate,
    _pg_outreach_migrate,
    _pg_response_migrate,
)


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _sentinel(conn, version: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM _schema_migrations WHERE version = %s",
        (version,),
    ).fetchone() is not None


def test_pg_data_migrator_copies_legacy_operational_rows():
    legacy = _sqlite(operational_db_path())
    try:
        legacy.execute(
            "CREATE TABLE _schema_migrations("
            "version TEXT PRIMARY KEY, name TEXT, sha256 TEXT, applied_at TEXT)"
        )
        legacy.execute(
            "CREATE TABLE contacts("
            "id TEXT PRIMARY KEY, display_name TEXT, type TEXT, stage TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        legacy.execute(
            "INSERT INTO contacts VALUES (?,?,?,?,?,?)",
            ("legacy-contact", "Legacy Contact", "buyer", "warm", "2026-01-01", "2026-01-01"),
        )
        legacy.commit()
    finally:
        legacy.close()

    with connect() as conn:
        result = _pg_data_migrate.maybe_migrate_sqlite_to_pg(conn)
        row = conn.execute(
            "SELECT display_name, stage FROM contacts WHERE id='legacy-contact'"
        ).fetchone()
        assert result["reason"] == "migrated"
        assert result["tables"]["contacts"]["src"] == 1
        assert Path(result["backup_path"]).exists()
        assert row["display_name"] == "Legacy Contact"
        assert row["stage"] == "warm"
        assert _sentinel(conn, "9001")


def test_pg_memory_migrator_copies_legacy_memory_rows():
    legacy = _sqlite(_pg_memory_migrate.memory_store_path())
    try:
        legacy.execute(
            "CREATE TABLE facts("
            "fact_id INTEGER PRIMARY KEY, content TEXT UNIQUE, category TEXT, "
            "tags TEXT, trust_score REAL, created_at TEXT, updated_at TEXT)"
        )
        legacy.execute(
            "INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
            (41, "Legacy memory fact", "general", "legacy", 0.8, "2026-01-01", "2026-01-01"),
        )
        legacy.commit()
    finally:
        legacy.close()

    with connect() as conn:
        result = _pg_memory_migrate.maybe_migrate_memory_store(conn)
        row = conn.execute(
            "SELECT content, trust_score, search_tsv IS NOT NULL AS indexed "
            "FROM memory_facts WHERE fact_id=41"
        ).fetchone()
        assert result["reason"] == "migrated"
        assert result["tables"]["memory_facts"]["src"] == 1
        assert row["content"] == "Legacy memory fact"
        assert float(row["trust_score"]) == 0.8
        assert row["indexed"] is True
        assert _sentinel(conn, "9006")


def test_pg_response_migrator_copies_legacy_response_rows():
    legacy = _sqlite(_pg_response_migrate.response_store_path())
    try:
        legacy.execute(
            "CREATE TABLE responses("
            "response_id TEXT PRIMARY KEY, data TEXT NOT NULL, accessed_at REAL NOT NULL)"
        )
        legacy.execute(
            "CREATE TABLE conversations(name TEXT PRIMARY KEY, response_id TEXT NOT NULL)"
        )
        legacy.execute("INSERT INTO responses VALUES (?,?,?)", ("resp_1", '{"ok":true}', 123.5))
        legacy.execute("INSERT INTO conversations VALUES (?,?)", ("chat-1", "resp_1"))
        legacy.commit()
    finally:
        legacy.close()

    with connect() as conn:
        result = _pg_response_migrate.maybe_migrate_response_store(conn)
        response = conn.execute(
            "SELECT data FROM response_store_responses WHERE response_id='resp_1'"
        ).fetchone()
        conversation = conn.execute(
            "SELECT response_id FROM response_store_conversations WHERE name='chat-1'"
        ).fetchone()
        assert result["reason"] == "migrated"
        assert response["data"] == '{"ok":true}'
        assert conversation["response_id"] == "resp_1"
        assert _sentinel(conn, "9007")


def test_pg_kanban_migrator_copies_legacy_task_rows():
    columns = (
        "id, title, body, assignee, status, priority, created_by, created_at, "
        "started_at, completed_at, workspace_kind, workspace_path, branch_name, "
        "claim_lock, claim_expires, tenant, result, idempotency_key, "
        "consecutive_failures, worker_pid, last_failure_error, "
        "max_runtime_seconds, last_heartbeat_at, current_run_id, "
        "workflow_template_id, current_step_key, skills, model_override, "
        "max_retries, session_id"
    )
    legacy = _sqlite(_pg_kanban_migrate.kanban_store_path())
    try:
        legacy.execute(
            "CREATE TABLE tasks(" + ", ".join(f"{col.strip()} TEXT" for col in columns.split(",")) + ")"
        )
        legacy.execute(
            f"INSERT INTO tasks ({columns}) VALUES ({','.join(['?'] * len(columns.split(',')))})",
            (
                "task-1", "Legacy task", "body", "agent", "todo", 5, "human", 1,
                None, None, "scratch", "/tmp/work", "main", None, None, "tenant",
                None, "idem-1", 0, None, None, 60, None, None, None, None, None,
                None, 2, "session-1",
            ),
        )
        legacy.commit()
    finally:
        legacy.close()

    with connect() as conn:
        result = _pg_kanban_migrate.maybe_migrate_kanban_store(conn)
        row = conn.execute(
            "SELECT title, status, idempotency_key FROM kanban_tasks WHERE id='task-1'"
        ).fetchone()
        assert result["reason"] == "migrated"
        assert result["tables"]["kanban_tasks"]["src"] == 1
        assert row["title"] == "Legacy task"
        assert row["status"] == "todo"
        assert row["idempotency_key"] == "idem-1"
        assert _sentinel(conn, "9008")


def test_pg_outreach_migrator_copies_legacy_template_rows():
    legacy = _sqlite(_pg_outreach_migrate.outreach_store_path())
    try:
        legacy.execute(
            "CREATE TABLE templates("
            "id TEXT PRIMARY KEY, lane TEXT, name TEXT, body TEXT, channel TEXT, "
            "active INTEGER, uses INTEGER, replies INTEGER, wins INTEGER, "
            "status TEXT, rationale TEXT, created_at TEXT, updated_at TEXT)"
        )
        legacy.execute(
            "INSERT INTO templates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "tpl-legacy", "follow-ups", "Legacy follow up", "Checking in",
                "sms", 1, 2, 1, 0, "active", "legacy", "2026-01-01", "2026-01-01",
            ),
        )
        legacy.commit()
    finally:
        legacy.close()

    with connect() as conn:
        result = _pg_outreach_migrate.maybe_migrate_outreach_store(conn)
        row = conn.execute(
            "SELECT lane, body, channel FROM outreach_templates WHERE id='tpl-legacy'"
        ).fetchone()
        assert result["reason"] == "migrated"
        assert result["tables"]["outreach_templates"]["src"] == 1
        assert row["lane"] == "follow-ups"
        assert row["body"] == "Checking in"
        assert row["channel"] == "sms"
        assert _sentinel(conn, "9009")
