"""Replayed wire messages must not inflate history, counts, or the PG mirror."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from elevate_state import SessionDB


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_SESSIONDB_READ_FROM_PG", "0")
    from elevate_cli.data import sessiondb_shadow
    shadow = Mock()
    monkeypatch.setattr(sessiondb_shadow, "shadow_append_message", shadow)
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("one", source="tui")
    yield db, shadow
    db.close()


def test_replayed_identity_preserves_one_row_and_one_shadow_write(store):
    db, shadow = store
    kwargs = dict(content="", client_message_id="assistant-wire-id", tool_calls=[{"id": "call-1", "function": {"name": "read_file", "arguments": "{}"}}])
    first = db.append_message("one", "assistant", **kwargs)
    replay = db.append_message("one", "assistant", **kwargs)
    assert first == replay
    assert db.message_count("one") == 1
    assert db.get_session("one")["tool_call_count"] == 1
    assert shadow.call_count == 1


def test_same_text_with_distinct_identities_is_not_a_duplicate(store):
    db, shadow = store
    db.append_message("one", "user", "Try again", client_message_id="first")
    db.append_message("one", "user", "Try again", client_message_id="second")
    assert db.message_count("one") == 2
    assert shadow.call_count == 2


def test_message_identity_is_scoped_to_its_session(store):
    db, shadow = store
    db.create_session("two", source="tui")
    db.append_message("one", "user", "Hello", client_message_id="same-id")
    db.append_message("two", "user", "Hello", client_message_id="same-id")
    assert db.message_count("one") == db.message_count("two") == 1
    assert shadow.call_count == 2


def test_concurrent_connections_cannot_append_the_same_wire_message_twice(store, tmp_path):
    db, shadow = store
    other = SessionDB(db_path=tmp_path / "state.db")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(conn.append_message, "one", "user", "Hello", client_message_id="concurrent") for conn in (db, other)]
            ids = [future.result() for future in futures]
        assert ids[0] == ids[1]
        assert db.message_count("one") == 1
        assert shadow.call_count == 1
    finally:
        other.close()
