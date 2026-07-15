"""A3 regression — ordered SessionDB projection is one atomic retry unit."""
import os
from unittest.mock import patch


def _make_agent(session_db):
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        from run_agent import AIAgent
        return AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            quiet_mode=True,
            session_db=session_db,
            session_id="test-a3-partial",
            skip_context_files=True,
            skip_memory=True,
        )


def test_partial_flush_failure_does_not_duplicate_on_retry(tmp_path):
    from elevate_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    agent = _make_agent(db)

    messages = [
        {"role": "user", "content": "m0"},
        {"role": "assistant", "content": "m1"},
        {"role": "user", "content": "m2"},
        {"role": "assistant", "content": "m3"},
        {"role": "user", "content": "m4"},
    ]

    real_batch = db.append_messages_idempotent
    calls = {"n": 0}

    def flaky_batch(*args, **kwargs):
        calls["n"] += 1
        assert len(args[1]) == 5
        raise RuntimeError("transient atomic batch failure")

    # The integration calls the batch API once. A failed transaction leaves
    # no prefix rows and the retry cursor remains at the batch start.
    with patch.object(
        db, "append_messages_idempotent", side_effect=flaky_batch
    ):
        agent._flush_messages_to_session_db(messages, [])

    rows = db.get_messages(agent.session_id)
    assert rows == []
    assert calls["n"] == 1
    assert agent._last_flushed_db_idx == 0
    stable_ids = [message["client_message_id"] for message in messages]

    # Retry the exact stable identities through the healthy atomic batch.
    with patch.object(
        db, "append_messages_idempotent", wraps=real_batch
    ) as healthy_batch:
        agent._flush_messages_to_session_db(messages, [])
    healthy_batch.assert_called_once()
    rows = db.get_messages(agent.session_id)
    assert len(rows) == 5
    contents = [r["content"] for r in rows]
    assert contents == ["m0", "m1", "m2", "m3", "m4"]
    assert [row["client_message_id"] for row in rows] == stable_ids
    assert agent._last_flushed_db_idx == 5

    # A later flush is a cursor no-op: no duplicate batch call or rows.
    with patch.object(
        db, "append_messages_idempotent", wraps=real_batch
    ) as no_op_batch:
        agent._flush_messages_to_session_db(messages, [])
    no_op_batch.assert_not_called()
    assert len(db.get_messages(agent.session_id)) == 5
