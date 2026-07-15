"""Local durability tests for SessionDB's identified append contract."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

import elevate_state
from elevate_cli.data import sessiondb_shadow
from elevate_state import SessionDB, SessionMessageConflictError


@pytest.fixture()
def session_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Use only a temporary SQLite DB and inert, observable shadow hooks."""
    monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
    db_path = tmp_path / "state.db"
    shadow_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(name: str):
        def _shadow(*args: Any, **kwargs: Any) -> None:
            visible_row = None
            if name == "shadow_append_message":
                # A separate connection can only see the row after the local
                # BEGIN IMMEDIATE transaction has committed.
                with sqlite3.connect(db_path) as observer:
                    visible_row = observer.execute(
                        "SELECT id FROM messages WHERE session_id = ? "
                        "AND client_message_id = ? ORDER BY id",
                        (args[0], kwargs["client_message_id"]),
                    ).fetchone()
            shadow_calls.append(
                (name, args, {**kwargs, "_local_row_visible": visible_row})
            )

        return _shadow

    # SessionDB imports these functions at call time. Replacing every public
    # shadow hook guarantees this fixture cannot open a network connection.
    for hook_name in sessiondb_shadow.__all__:
        monkeypatch.setattr(sessiondb_shadow, hook_name, _record(hook_name))

    db = SessionDB(db_path=db_path)
    db.create_session(session_id="session-1", source="cli")
    shadow_calls.clear()
    try:
        yield db, db_path, shadow_calls
    finally:
        db.close()


def _message_rows(db: SessionDB) -> list[sqlite3.Row]:
    return db._conn.execute(  # noqa: SLF001 - durability invariant test
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
        ("session-1",),
    ).fetchall()


def _session_counters(db: SessionDB) -> tuple[int, int]:
    row = db._conn.execute(  # noqa: SLF001 - durability invariant test
        "SELECT message_count, tool_call_count FROM sessions WHERE id = ?",
        ("session-1",),
    ).fetchone()
    return int(row["message_count"]), int(row["tool_call_count"])


def _append_guidance(db: SessionDB, **overrides: Any) -> int:
    payload = {
        "session_id": "session-1",
        "role": "user",
        "content": "Use the signed offer instead",
        "finish_reason": "guidance_reserved",
        "client_message_id": "gateway-follow-up-A",
    }
    payload.update(overrides)
    return db.append_message_idempotent(**payload)


def _batch_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": "Use the signed offer instead",
            "finish_reason": "guidance_reserved_steer",
            "client_message_id": "batch-guidance-A",
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "tool-call-A",
                    "type": "function",
                    "function": {"name": "deal_lookup", "arguments": "{}"},
                }
            ],
            "finish_reason": "tool_calls",
            "client_message_id": "batch-assistant-A",
        },
        {
            "role": "tool",
            "content": '{"status":"found"}',
            "tool_name": "deal_lookup",
            "tool_call_id": "tool-call-A",
            "client_message_id": "batch-tool-A",
        },
    ]


def test_new_insert_commits_locally_before_one_best_effort_shadow(session_store):
    db, _db_path, shadow_calls = session_store

    row_id = _append_guidance(db)

    rows = _message_rows(db)
    assert [row["id"] for row in rows] == [row_id]
    assert rows[0]["finish_reason"] == "guidance_reserved"
    assert _session_counters(db) == (1, 0)
    append_shadows = [call for call in shadow_calls if call[0] == "shadow_append_message"]
    assert len(append_shadows) == 1
    assert append_shadows[0][2]["_local_row_visible"] == (row_id,)


def test_exact_replay_returns_existing_id_without_counter_or_shadow_duplication(
    session_store,
):
    db, _db_path, shadow_calls = session_store

    first_id = _append_guidance(db)
    replay_id = _append_guidance(db)

    assert replay_id == first_id
    assert len(_message_rows(db)) == 1
    assert _session_counters(db) == (1, 0)
    assert [name for name, _args, _kwargs in shadow_calls].count(
        "shadow_append_message"
    ) == 1


def test_two_local_writers_atomically_converge_on_one_row(session_store):
    db, db_path, shadow_calls = session_store
    second_db = SessionDB(db_path=db_path)
    start = threading.Barrier(2)

    def _race(writer: SessionDB) -> int:
        start.wait(timeout=2)
        return _append_guidance(writer)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_race, writer) for writer in (db, second_db)]
            row_ids = [future.result(timeout=5) for future in futures]
    finally:
        second_db.close()

    assert row_ids[0] == row_ids[1]
    assert [row["id"] for row in _message_rows(db)] == [row_ids[0]]
    assert _session_counters(db) == (1, 0)
    assert [name for name, _args, _kwargs in shadow_calls].count(
        "shadow_append_message"
    ) == 1


def test_shadow_failure_cannot_undo_local_commit_or_retry_on_replay(
    session_store,
    monkeypatch: pytest.MonkeyPatch,
):
    db, _db_path, _shadow_calls = session_store
    attempts = 0

    def _fail_shadow(*_args: Any, **_kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("shadow unavailable")

    monkeypatch.setattr(
        sessiondb_shadow,
        "shadow_append_message",
        _fail_shadow,
    )

    row_id = _append_guidance(db)
    assert _append_guidance(db) == row_id
    assert [row["id"] for row in _message_rows(db)] == [row_id]
    assert _session_counters(db) == (1, 0)
    assert attempts == 1


def test_exact_batch_replay_returns_ordered_ids_without_new_rows_or_shadows(
    session_store,
):
    db, _db_path, shadow_calls = session_store
    batch = _batch_messages()

    first_ids = db.append_messages_idempotent("session-1", batch)
    replay_ids = db.append_messages_idempotent("session-1", batch)

    assert replay_ids == first_ids
    assert [row["id"] for row in _message_rows(db)] == first_ids
    assert _session_counters(db) == (3, 1)
    append_shadows = [call for call in shadow_calls if call[0] == "shadow_append_message"]
    assert len(append_shadows) == 3
    assert [call[2]["client_message_id"] for call in append_shadows] == [
        "batch-guidance-A",
        "batch-assistant-A",
        "batch-tool-A",
    ]
    assert all(call[2]["_local_row_visible"] for call in append_shadows)


def test_batch_row_two_conflict_rolls_back_row_one_and_all_counter_changes(
    session_store,
):
    db, _db_path, shadow_calls = session_store
    conflicting_batch = [
        {
            "role": "user",
            "content": "first durable state",
            "client_message_id": "same-id-inside-batch",
        },
        {
            "role": "user",
            "content": "conflicting durable state",
            "client_message_id": "same-id-inside-batch",
        },
    ]

    with pytest.raises(SessionMessageConflictError):
        db.append_messages_idempotent("session-1", conflicting_batch)

    assert _message_rows(db) == []
    assert _session_counters(db) == (0, 0)
    assert shadow_calls == []


def test_batch_row_two_sqlite_failure_rolls_back_row_one_and_counters(
    session_store,
):
    db, _db_path, shadow_calls = session_store
    db._conn.execute(  # noqa: SLF001 - deterministic transaction fault injection
        """CREATE TRIGGER fail_batch_row_two
        BEFORE INSERT ON messages
        WHEN NEW.client_message_id = 'forced-failure-B'
        BEGIN
            SELECT RAISE(ABORT, 'forced row two failure');
        END"""
    )
    batch = [
        {
            "role": "user",
            "content": "row one",
            "client_message_id": "before-failure-A",
        },
        {
            "role": "tool",
            "content": "row two",
            "tool_call_id": "tool-call-failure",
            "client_message_id": "forced-failure-B",
        },
    ]

    with pytest.raises(sqlite3.IntegrityError, match="forced row two failure"):
        db.append_messages_idempotent("session-1", batch)

    assert _message_rows(db) == []
    assert _session_counters(db) == (0, 0)
    assert shadow_calls == []


def test_two_local_writers_atomically_converge_on_one_ordered_batch(
    session_store,
):
    db, db_path, shadow_calls = session_store
    second_db = SessionDB(db_path=db_path)
    start = threading.Barrier(2)
    batch = _batch_messages()

    def _race(writer: SessionDB) -> list[int]:
        start.wait(timeout=2)
        return writer.append_messages_idempotent("session-1", batch)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_race, writer) for writer in (db, second_db)]
            row_id_batches = [future.result(timeout=5) for future in futures]
    finally:
        second_db.close()

    assert row_id_batches[0] == row_id_batches[1]
    assert [row["id"] for row in _message_rows(db)] == row_id_batches[0]
    assert _session_counters(db) == (3, 1)
    append_shadows = [call for call in shadow_calls if call[0] == "shadow_append_message"]
    assert len(append_shadows) == 3


@pytest.mark.parametrize(
    ("overrides", "conflicting_field"),
    [
        ({"content": "Use the listing agreement"}, "content"),
        ({"role": "assistant"}, "role"),
        ({"finish_reason": "different_state"}, "finish_reason"),
    ],
)
def test_identity_reuse_with_different_durable_state_is_an_explicit_conflict(
    session_store,
    overrides,
    conflicting_field,
):
    db, _db_path, shadow_calls = session_store
    first_id = _append_guidance(db)

    with pytest.raises(SessionMessageConflictError) as caught:
        _append_guidance(db, **overrides)

    assert caught.value.session_id == "session-1"
    assert caught.value.client_message_id == "gateway-follow-up-A"
    assert conflicting_field not in str(caught.value)  # no payload details leak
    assert [row["id"] for row in _message_rows(db)] == [first_id]
    assert _session_counters(db) == (1, 0)
    assert [name for name, _args, _kwargs in shadow_calls].count(
        "shadow_append_message"
    ) == 1


def test_idempotent_append_never_consults_the_pg_read_path(
    session_store,
    monkeypatch: pytest.MonkeyPatch,
):
    db, _db_path, _shadow_calls = session_store

    def _unexpected_pg_read() -> bool:
        raise AssertionError("idempotent local append consulted PG read state")

    monkeypatch.setattr(elevate_state, "_read_from_pg", _unexpected_pg_read)

    row_id = _append_guidance(db)
    assert _append_guidance(db) == row_id


def test_cold_resume_restores_only_the_allowlisted_user_guidance_marker(
    session_store,
):
    db, db_path, _shadow_calls = session_store
    _append_guidance(db)
    db.append_message_idempotent(
        session_id="session-1",
        role="user",
        content="steer lane row",
        finish_reason="guidance_reserved_steer",
        client_message_id="steer-user-B",
    )
    db.append_message_idempotent(
        session_id="session-1",
        role="user",
        content="soft lane row",
        finish_reason="guidance_reserved_soft",
        client_message_id="soft-user-C",
    )
    db.append_message_idempotent(
        session_id="session-1",
        role="user",
        content="ordinary user row",
        finish_reason="unsafe_user_state",
        client_message_id="ordinary-user-D",
    )
    db.close()

    reopened = SessionDB(db_path=db_path)
    try:
        messages = reopened.get_messages_as_conversation("session-1")
    finally:
        reopened.close()

    assert messages[0] == {
        "role": "user",
        "content": "Use the signed offer instead",
        "client_message_id": "gateway-follow-up-A",
        "finish_reason": "guidance_reserved",
    }
    assert messages[1] == {
        "role": "user",
        "content": "steer lane row",
        "client_message_id": "steer-user-B",
        "finish_reason": "guidance_reserved_steer",
    }
    assert messages[2] == {
        "role": "user",
        "content": "soft lane row",
        "client_message_id": "soft-user-C",
        "finish_reason": "guidance_reserved_soft",
    }
    assert messages[3] == {
        "role": "user",
        "content": "ordinary user row",
        "client_message_id": "ordinary-user-D",
    }
