"""A3 regression — a mid-batch append failure must not duplicate rows on retry.

_flush_messages_to_session_db advanced its cursor (_last_flushed_db_idx) only
after the whole batch, so a failure on message N left rows 0..N-1 committed but
the cursor unmoved — the next flush replayed them, duplicating transcript rows
(messages has no UNIQUE on client_message_id). The cursor now advances per
successful append, so a retry resumes at the failed message.
"""
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

    real_append = db.append_message
    calls = {"n": 0}

    def flaky_append(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # fail on the 3rd message (index 2)
            raise RuntimeError("transient DB lock")
        return real_append(*args, **kwargs)

    # First flush: append fails on index 2 → rows 0,1 committed, cursor lands at 2.
    with patch.object(db, "append_message", side_effect=flaky_append):
        agent._flush_messages_to_session_db(messages, [])

    rows = db.get_messages(agent.session_id)
    assert len(rows) == 2, f"expected 2 rows committed before the failure, got {len(rows)}"
    assert agent._last_flushed_db_idx == 2, (
        f"cursor must sit at the failed message, got {agent._last_flushed_db_idx}"
    )

    # Retry with healthy append: only 2,3,4 get written — NOT a replay of 0,1.
    agent._flush_messages_to_session_db(messages, [])
    rows = db.get_messages(agent.session_id)
    assert len(rows) == 5, f"expected 5 total after retry (no duplicates), got {len(rows)}"
    contents = [r["content"] for r in rows]
    assert contents == ["m0", "m1", "m2", "m3", "m4"], f"duplicate/misordered rows: {contents}"
