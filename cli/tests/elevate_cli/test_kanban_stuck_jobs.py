from __future__ import annotations

import time

import pytest

from elevate_cli import kanban_db as kb
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _claimed_task(conn, *, max_runtime_seconds: int | None = None) -> tuple[str, int]:
    task_id = kb.create_task(
        conn,
        title="stuck worker",
        assignee="codex",
        max_runtime_seconds=max_runtime_seconds,
    )
    claimed = kb.claim_task(conn, task_id)
    assert claimed is not None
    row = conn.execute(
        "SELECT current_run_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    assert row and row["current_run_id"]
    return task_id, int(row["current_run_id"])


def _age_running_attempt(conn, task_id: str, run_id: int, *, seconds: int) -> None:
    started_at = int(time.time()) - seconds
    conn.execute(
        """
        UPDATE tasks
           SET started_at = ?,
               last_heartbeat_at = ?,
               worker_pid = ?
         WHERE id = ?
        """,
        (started_at, started_at, 999999, task_id),
    )
    conn.execute(
        """
        UPDATE task_runs
           SET started_at = ?,
               last_heartbeat_at = ?,
               worker_pid = ?
         WHERE id = ?
        """,
        (started_at, started_at, 999999, run_id),
    )


def test_max_runtime_timeout_requeues_and_logs_event():
    with kb.connect() as conn:
        task_id, run_id = _claimed_task(conn, max_runtime_seconds=1)
        _age_running_attempt(conn, task_id, run_id, seconds=120)

        timed_out = kb.enforce_max_runtime(conn, signal_fn=lambda *_args: None)

        assert timed_out == [task_id]
        task = kb.get_task(conn, task_id)
        assert task is not None
        assert task.status == "ready"
        assert task.current_run_id is None
        assert task.consecutive_failures == 1

        run = conn.execute(
            "SELECT status, outcome, error FROM task_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["status"] == "timed_out"
        assert run["outcome"] == "timed_out"
        assert "elapsed" in run["error"]

        events = kb.list_events(conn, task_id)
        assert any(event.kind == "timed_out" for event in events)


def test_stale_heartbeat_requeues_without_tripping_failure_counter():
    with kb.connect() as conn:
        task_id, run_id = _claimed_task(conn)
        _age_running_attempt(conn, task_id, run_id, seconds=7200)

        stale = kb.detect_stale_running(
            conn,
            stale_timeout_seconds=3600,
            signal_fn=lambda *_args: None,
        )

        assert stale == [task_id]
        task = kb.get_task(conn, task_id)
        assert task is not None
        assert task.status == "ready"
        assert task.current_run_id is None
        assert task.consecutive_failures == 0

        run = conn.execute(
            "SELECT status, outcome, error FROM task_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["status"] == "stale"
        assert run["outcome"] == "stale"
        assert "no heartbeat" in run["error"]

        events = kb.list_events(conn, task_id)
        assert any(event.kind == "stale" for event in events)
